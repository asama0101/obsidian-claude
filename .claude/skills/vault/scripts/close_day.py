"""Obsidian Vault用 Claude Codeプラグイン「vault」の close スキル本体。

当日ブランチ上の変更をコミットし、当日デイリーノートの
「本日作成・更新したノート」セクションを更新した上で main へ
ff-only マージする。結果は JSON 形式で標準出力に出す。
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

import vault_lib

# 当日ブランチ名の形式(YYYY-MM-DD)
_DAILY_BRANCH_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# 更新ノート一覧から除外するパス接頭辞
_EXCLUDED_PREFIXES = ("70_Templates/", ".claude/")

# frontmatterのtype値のうちグループとして認識する既知の値
_KNOWN_TYPES = ("project", "meeting", "task", "knowhow", "webclip")

# 更新ノート一覧の表示グループ順(固定)。otherは既知7種以外・type未定義の受け皿。
_TYPE_GROUP_ORDER = ("project", "meeting", "task", "knowhow", "webclip", "other")


def _normalize_note_type(raw_type: str | None) -> str:
    """frontmatterのtype値をグルーピング用のtypeキーへ正規化する。

    meeting_seriesはmeetingへ統合し、既知7種以外・type未定義はotherへ丸め込む。
    """
    if raw_type == "meeting_series":
        return "meeting"
    if raw_type in _KNOWN_TYPES:
        return raw_type
    return "other"


def _read_note_type(path: Path) -> str | None:
    """ノートファイルを読み込みfrontmatterのtype値を返す。

    ファイル読み込みでI/Oエラー(FileNotFoundError等)が起きた場合はNoneを返す
    (呼び出し側の_normalize_note_typeによりotherへ丸め込まれる)。
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    fm_text, _ = vault_lib.split_frontmatter(text)
    return vault_lib.get_fm_value(fm_text, "type")


def _git_status_porcelain(vault_root: Path) -> str:
    """`git status --porcelain` の生出力を返す。

    vault_lib.run_git() は rstrip("\n") のみで先頭の空白は保持するため
    （porcelain形式は行頭が半角スペースの場合に意味を持つ）、そのまま使える。
    `--untracked-files=all` を指定し、丸ごと新規のディレクトリ（例:
    新規プロジェクトの最初のノート）でもディレクトリ名1行に折りたたまず
    個々のファイルを列挙させる（デフォルトの `normal` モードだと
    追跡済みファイルが1つも無いディレクトリは1行に集約されてしまう）。
    """
    return vault_lib.run_git(
        "-c",
        "core.quotepath=false",
        "status",
        "--porcelain",
        "--untracked-files=all",
        cwd=vault_root,
    )


def _unquote_git_path(raw: str) -> str:
    """gitがダブルクォートで囲んだパスをアンクォートする。

    `git status --porcelain` は、パスにスペース・括弧等の特定の文字が
    含まれる場合、`core.quotepath=false` を指定していてもパス全体を
    ダブルクォートで囲み、`"` と `\\` のみバックスラッシュエスケープする
    ことがある（非ASCIIバイトの8進数エスケープは quotepath=false により
    発生しない想定）。クォートされていない場合はそのまま返す。
    """
    if len(raw) >= 2 and raw[0] == '"' and raw[-1] == '"':
        inner = raw[1:-1]
        result: list[str] = []
        i = 0
        while i < len(inner):
            ch = inner[i]
            if ch == "\\" and i + 1 < len(inner) and inner[i + 1] in ('"', "\\"):
                result.append(inner[i + 1])
                i += 2
                continue
            result.append(ch)
            i += 1
        return "".join(result)
    return raw


def _parse_status_paths(porcelain_output: str) -> set[str]:
    """`git status --porcelain` の出力からファイルパス集合を得る。

    リネームの場合は変更後のパスを採用する。パスがダブルクォートで
    囲まれている場合はアンクォートする。
    """
    paths: set[str] = set()
    for line in porcelain_output.splitlines():
        if not line:
            continue
        rest = line[3:]
        if "->" in rest:
            rest = rest.split("->", 1)[1].strip()
        paths.add(_unquote_git_path(rest))
    return paths


def _collect_updated_paths(vault_root: Path) -> set[str]:
    """分岐点以降のコミット済み変更と未コミット変更のパス和集合を返す。"""
    merge_base = vault_lib.run_git("merge-base", "main", "HEAD", cwd=vault_root)
    committed_output = vault_lib.run_git(
        "diff", "--name-only", merge_base, "HEAD", cwd=vault_root
    )
    committed_paths = {line for line in committed_output.splitlines() if line}

    status_output = _git_status_porcelain(vault_root)
    status_paths = _parse_status_paths(status_output)

    return committed_paths | status_paths


def _filter_updated_notes(
    paths: set[str], date_str: str, vault_root: Path
) -> list[tuple[str, Path]]:
    """close対象外(当日ノート自身/テンプレート/.claude配下/非.md)を除外し、
    (ファイル名(拡張子除く), フルパス) のstemソート済みリストを返す。
    """
    daily_note_path = f"00_Daily/{date_str}.md"
    entries: list[tuple[str, Path]] = []
    for path in paths:
        normalized = path.replace("\\", "/")
        if not normalized.endswith(".md"):
            continue
        if normalized == daily_note_path:
            continue
        if any(normalized.startswith(prefix) for prefix in _EXCLUDED_PREFIXES):
            continue
        entries.append((Path(normalized).stem, vault_root / normalized))
    return sorted(entries, key=lambda entry: entry[0])


def _build_updated_notes_block(entries: list[tuple[str, Path]]) -> str:
    """更新ノート一覧からtype別にグルーピングしたマーカーブロック内テキストを組み立てる。

    entriesは_filter_updated_notesが返すstemソート済みの(stem, フルパス)リスト。
    グループ内の順序はentriesの並び(=stemソート順)をそのまま引き継ぐ。
    """
    if not entries:
        return "- （本日の更新ノートなし）"

    groups: dict[str, list[str]] = {key: [] for key in _TYPE_GROUP_ORDER}
    for stem, path in entries:
        raw_type = _read_note_type(path)
        groups[_normalize_note_type(raw_type)].append(stem)

    lines: list[str] = []
    for group_key in _TYPE_GROUP_ORDER:
        stems = groups[group_key]
        if not stems:
            continue
        if lines:
            lines.append("")
        lines.append(f"**{group_key}**")
        lines.extend(f"- [[{stem}]]" for stem in stems)
    return "\n".join(lines)


def _has_pending_changes(vault_root: Path) -> bool:
    return bool(_git_status_porcelain(vault_root).strip())


def _scan_task_review_targets(vault_root: Path, date_str: str) -> list[dict]:
    """日付・ステータスの見直しが必要なタスクノートを検出する。

    走査対象は `10_Projects/*/Tasks/*.md` と `20_Areas/Tasks/*.md`。
    typeが"task"のノートのうち、次の3条件のいずれかに該当するものを返す。
    1. created_date == date_str かつ start_date が空
    2. start_date == date_str かつ status == "1_todo"
    3. due_date == date_str かつ status が "4_done"/"5_cancel" 以外
    """
    candidate_paths = list(vault_root.glob("10_Projects/*/Tasks/*.md"))
    candidate_paths.extend((vault_root / "20_Areas" / "Tasks").glob("*.md"))

    targets: list[dict] = []
    for path in candidate_paths:
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        fm_text, _ = vault_lib.split_frontmatter(text)
        if vault_lib.get_fm_value(fm_text, "type") != "task":
            continue

        created_date = vault_lib.get_fm_value(fm_text, "created_date")
        start_date = vault_lib.get_fm_value(fm_text, "start_date")
        due_date = vault_lib.get_fm_value(fm_text, "due_date")
        status = vault_lib.get_fm_value(fm_text, "status")

        matched = (
            (created_date == date_str and not start_date)
            or (start_date == date_str and status == "1_todo")
            or (due_date == date_str and status not in ("4_done", "5_cancel"))
        )
        if matched:
            targets.append({"note_path": str(path), "title": path.stem})

    return sorted(targets, key=lambda entry: entry["title"])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--vault-root",
        type=str,
        default=None,
        help="VAULT_ROOT を上書きする(テスト用)。",
    )
    args = parser.parse_args(argv)

    vault_root = Path(args.vault_root) if args.vault_root else vault_lib.VAULT_ROOT

    # 1. 当日ブランチ上か確認する
    branch = vault_lib.run_git("rev-parse", "--abbrev-ref", "HEAD", cwd=vault_root)
    if not _DAILY_BRANCH_RE.match(branch):
        print(
            json.dumps(
                {"status": "error", "reason": "not_on_daily_branch"}, ensure_ascii=False
            )
        )
        return 1

    date_str = branch

    # 1b. タスクの日付・ステータス見直し対象を確認する(該当あれば後続処理へ進まず中断する)
    review_targets = _scan_task_review_targets(vault_root, date_str)
    if review_targets:
        print(
            json.dumps(
                {"status": "needs_task_review", "tasks": review_targets},
                ensure_ascii=False,
            )
        )
        return 1

    # 2-4. 更新ノート一覧を作成する
    updated_paths = _collect_updated_paths(vault_root)
    entries = _filter_updated_notes(updated_paths, date_str, vault_root)
    note_names = [stem for stem, _ in entries]
    block_text = _build_updated_notes_block(entries)

    # 5. 当日デイリーノートのマーカーブロックを置換して書き戻す
    daily_note_path = vault_root / "00_Daily" / f"{date_str}.md"
    daily_note_text = daily_note_path.read_text(encoding="utf-8")
    new_daily_note_text = vault_lib.set_marker_block(
        daily_note_text, "UPDATED_NOTES_START", "UPDATED_NOTES_END", block_text
    )
    daily_note_path.write_text(new_daily_note_text, encoding="utf-8")

    # 6. 変更があればコミットする
    committed = False
    if _has_pending_changes(vault_root):
        vault_lib.run_git("add", "-A", cwd=vault_root)
        vault_lib.run_git(
            "commit", "-m", f"Close daily log for {date_str}", cwd=vault_root
        )
        committed = True

    # 7. 既にclose済みか確認する
    main_rev = vault_lib.run_git("rev-parse", "main", cwd=vault_root)
    head_rev = vault_lib.run_git("rev-parse", "HEAD", cwd=vault_root)
    if main_rev == head_rev:
        print(json.dumps({"status": "already_closed"}, ensure_ascii=False))
        return 0

    # 8. main へ ff-only マージする
    vault_lib.run_git("checkout", "main", cwd=vault_root)
    try:
        vault_lib.run_git("merge", "--ff-only", branch, cwd=vault_root)
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.output or str(exc)).strip()
        print(
            json.dumps(
                {"status": "merge_failed", "detail": detail}, ensure_ascii=False
            )
        )
        return 1

    # 8b. マージ済みの当日ブランチを削除する。ff-onlyマージ直後のため
    # branch の内容はすべて main に含まれており、`-d`(安全な削除、
    # 未マージなら失敗する)で問題なく削除できる。
    vault_lib.run_git("branch", "-d", branch, cwd=vault_root)
    branch_deleted = True

    # 9. origin が設定されていれば push を試みる(失敗しても致命的エラーにしない)
    pushed = False
    try:
        vault_lib.run_git("remote", "get-url", "origin", cwd=vault_root)
    except subprocess.CalledProcessError:
        pass
    else:
        try:
            vault_lib.run_git("push", "origin", "main", cwd=vault_root)
            pushed = True
        except subprocess.CalledProcessError:
            pushed = False

    # 10. 結果を出力する
    print(
        json.dumps(
            {
                "status": "ok",
                "updated_notes": note_names,
                "committed": committed,
                "branch_deleted": branch_deleted,
                "pushed": pushed,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
