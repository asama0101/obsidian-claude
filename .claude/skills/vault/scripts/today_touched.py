"""Obsidian Vault用 Claude Codeプラグイン「vault」の today-touched スキル本体。

close_day.pyから移設した更新ノート検出ロジックを独立スキルとして持つ。
CLI引数なしで実行し(テスト用の--vault-rootのみ例外)、毎回全体を再計算する
冪等スクリプトである。締め忘れ確認・コミット・mainへのマージは一切行わず、
当日デイリーノートの「本日作成・更新したノート」マーカーブロックの
再生成のみを担う。close_day.pyとはimport/subprocess関係を持たない
完全に独立したスクリプトとする。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import vault_lib

# 当日ブランチ名の形式(YYYY-MM-DD)
_DAILY_BRANCH_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# 更新ノート一覧から除外するパス接頭辞
_EXCLUDED_PREFIXES = ("80_Templates/", ".claude/")

# frontmatterのtype値のうちグループとして認識する既知の値
_KNOWN_TYPES = ("project", "meeting", "task", "knowhow", "webclip")

# 更新ノート一覧の表示グループ順(固定)。otherは既知5種以外・type未定義の受け皿。
_TYPE_GROUP_ORDER = ("project", "meeting", "task", "knowhow", "webclip", "other")


def _normalize_note_type(raw_type: str | None) -> str:
    """frontmatterのtype値をグルーピング用のtypeキーへ正規化する。

    meeting_seriesはmeetingへ統合し、既知5種以外・type未定義はotherへ丸め込む。
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


_EXISTING_MARKER_ENTRY_PATTERN = re.compile(r"^- \[\[(.+)\]\]$")


def _parse_existing_marker_stems(daily_note_text: str) -> set[str]:
    """既存のマーカーブロックから、既に記録済みのノートstem集合を取り出す。

    グループ見出し(`**project**`等)や「本日の更新ノートなし」プレースホルダー
    行は`- [[stem]]`形式にマッチしないため自然に無視される。
    """
    block = vault_lib.get_marker_block(
        daily_note_text, "UPDATED_NOTES_START", "UPDATED_NOTES_END"
    )
    stems: set[str] = set()
    for line in block.split("\n"):
        match = _EXISTING_MARKER_ENTRY_PATTERN.match(line.strip())
        if match:
            stems.add(match.group(1))
    return stems


def _resolve_stem_path(stem: str, vault_root: Path) -> Path | None:
    """stem(拡張子除くファイル名)からVault内の実ファイルパスを解決する。

    Obsidianの`[[stem]]`形式リンクはVault内でのファイル名一意性を前提と
    しているため、最初に見つかった一致を採用する。`.claude`配下やgit内部
    ディレクトリ等は除外する。
    """
    for candidate in vault_root.rglob(f"{stem}.md"):
        relative = candidate.relative_to(vault_root).as_posix()
        if relative.startswith(".git/") or relative.startswith(".claude/"):
            continue
        if any(relative.startswith(prefix) for prefix in _EXCLUDED_PREFIXES):
            continue
        return candidate
    return None


def _merge_with_existing_entries(
    entries: list[tuple[str, Path]], daily_note_text: str, date_str: str, vault_root: Path
) -> list[tuple[str, Path]]:
    """今回の差分結果に、既存マーカーブロックに記録済みのノートを和集合する。

    close_day.pyのff-onlyマージでmainが当日ブランチに追いつくと、次回実行時の
    差分基準(merge-base)が前進し、それより前に記録済みだった更新ノートが
    差分から検出できなくなる。今回の差分だけで置き換えるとその記録が消えて
    しまうため、既存マーカーブロックの内容を読み取り、まだ実在するノードは
    保持する。
    """
    daily_note_stem = date_str
    fresh_stems = {stem for stem, _ in entries}
    merged = list(entries)
    for stem in _parse_existing_marker_stems(daily_note_text) - fresh_stems:
        if stem == daily_note_stem:
            continue
        resolved = _resolve_stem_path(stem, vault_root)
        if resolved is not None and resolved.exists():
            merged.append((stem, resolved))
    return sorted(merged, key=lambda entry: entry[0])


def _filter_updated_notes(
    paths: set[str], date_str: str, vault_root: Path
) -> list[tuple[str, Path]]:
    """対象外(当日ノート自身/テンプレート/.claude配下/非.md/実在しないファイル)を
    除外し、(ファイル名(拡張子除く), フルパス) のstemソート済みリストを返す。
    """
    daily_note_path = f"10_Daily/{date_str}.md"
    entries: list[tuple[str, Path]] = []
    for path in paths:
        normalized = path.replace("\\", "/")
        if not normalized.endswith(".md"):
            continue
        if normalized == daily_note_path:
            continue
        if any(normalized.startswith(prefix) for prefix in _EXCLUDED_PREFIXES):
            continue
        full_path = vault_root / normalized
        if not full_path.exists():
            continue
        entries.append((Path(normalized).stem, full_path))
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

    # 2-3. 更新ノート一覧を作成する
    daily_note_path = vault_root / "10_Daily" / f"{date_str}.md"
    daily_note_text = daily_note_path.read_text(encoding="utf-8")

    updated_paths = _collect_updated_paths(vault_root)
    entries = _filter_updated_notes(updated_paths, date_str, vault_root)
    entries = _merge_with_existing_entries(entries, daily_note_text, date_str, vault_root)
    note_names = [stem for stem, _ in entries]
    block_text = _build_updated_notes_block(entries)

    # 4. 当日デイリーノートのマーカーブロックを置換して書き戻す
    new_daily_note_text = vault_lib.set_marker_block(
        daily_note_text, "UPDATED_NOTES_START", "UPDATED_NOTES_END", block_text
    )
    daily_note_path.write_text(new_daily_note_text, encoding="utf-8")

    print(
        json.dumps(
            {"status": "ok", "updated_notes": note_names},
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
