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


def _git_status_porcelain(vault_root: Path) -> str:
    """`git status --porcelain` の生出力を返す。

    vault_lib.run_git() は rstrip("\n") のみで先頭の空白は保持するため
    （porcelain形式は行頭が半角スペースの場合に意味を持つ）、そのまま使える。
    """
    return vault_lib.run_git(
        "-c", "core.quotepath=false", "status", "--porcelain", cwd=vault_root
    )


def _parse_status_paths(porcelain_output: str) -> set[str]:
    """`git status --porcelain` の出力からファイルパス集合を得る。

    リネームの場合は変更後のパスを採用する。
    """
    paths: set[str] = set()
    for line in porcelain_output.splitlines():
        if not line:
            continue
        rest = line[3:]
        if "->" in rest:
            rest = rest.split("->", 1)[1].strip()
        paths.add(rest)
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


def _filter_updated_notes(paths: set[str], date_str: str) -> list[str]:
    """close対象外(当日ノート自身/テンプレート/.claude配下/非.md)を除外し、
    ファイル名(拡張子除く)のソート済みリストを返す。
    """
    daily_note_path = f"00_Daily/{date_str}.md"
    names = []
    for path in paths:
        normalized = path.replace("\\", "/")
        if not normalized.endswith(".md"):
            continue
        if normalized == daily_note_path:
            continue
        if any(normalized.startswith(prefix) for prefix in _EXCLUDED_PREFIXES):
            continue
        names.append(Path(normalized).stem)
    return sorted(names)


def _build_updated_notes_block(note_names: list[str]) -> str:
    """更新ノート一覧からマーカーブロック内テキストを組み立てる。"""
    if not note_names:
        return "- （本日の更新ノートなし）"
    return "\n".join(f"- [[{name}]]" for name in note_names)


def _has_pending_changes(vault_root: Path) -> bool:
    return bool(_git_status_porcelain(vault_root).strip())


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

    # 2-4. 更新ノート一覧を作成する
    updated_paths = _collect_updated_paths(vault_root)
    note_names = _filter_updated_notes(updated_paths, date_str)
    block_text = _build_updated_notes_block(note_names)

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
                "pushed": pushed,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
