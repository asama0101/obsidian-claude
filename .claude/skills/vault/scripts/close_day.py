"""Obsidian Vault用 Claude Codeプラグイン「vault」の close スキル本体。

当日ブランチ上の変更をコミットし、main へ ff-only マージする。
結果は JSON 形式で標準出力に出す。
「本日作成・更新したノート」一覧の再生成は today_touched.py（today-touched
スキル）の責務であり、このスクリプトは UPDATED_NOTES マーカーに一切触れない。
また、マージ直後の作業ツリー整合性を確認する。
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


def _has_pending_changes(vault_root: Path) -> bool:
    return bool(_git_status_porcelain(vault_root).strip())


def _post_merge_diff(vault_root: Path) -> str:
    """マージ直後の作業ツリーの状態を porcelain 形式の文字列で返す。

    空文字列なら HEAD の内容と完全一致(クリーン)、非空なら何らかの差分がある。
    """
    return _git_status_porcelain(vault_root)


def _scan_task_review_targets(vault_root: Path, date_str: str) -> list[dict]:
    """日付・ステータスの見直しが必要なタスクノートを検出する。

    走査対象は `20_Projects/*/Tasks/*.md` と `30_Areas/Tasks/*.md`。
    typeが"task"のノートのうち、次の3条件のいずれかに該当するものを返す。
    1. created_date == date_str かつ start_date が空
    2. start_date == date_str かつ status が "1_todo"
       ("3_pending"は意図的な保留状態であり、単純な未着手忘れとは異なるため対象外)
    3. due_date == date_str かつ status が "4_done"/"5_cancel" 以外
    """
    candidate_paths = list(vault_root.glob("20_Projects/*/Tasks/*.md"))
    candidate_paths.extend((vault_root / "30_Areas" / "Tasks").glob("*.md"))

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

    # 2. 変更があればコミットする
    committed = False
    if _has_pending_changes(vault_root):
        vault_lib.run_git("add", "-A", cwd=vault_root)
        vault_lib.run_git(
            "commit", "-m", f"Close daily log for {date_str}", cwd=vault_root
        )
        committed = True

    # 3. 既にclose済みか確認する
    main_rev = vault_lib.run_git("rev-parse", "main", cwd=vault_root)
    head_rev = vault_lib.run_git("rev-parse", "HEAD", cwd=vault_root)
    if main_rev == head_rev:
        print(json.dumps({"status": "already_closed"}, ensure_ascii=False))
        return 0

    # 4. main へ ff-only マージする
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

    # 4c. マージ直後の作業ツリーがマージ後のコミット内容と完全に一致しているか確認する。
    # 不一致があれば(OneDriveの同期復元等による想定外の状態変化の可能性があるため)
    # ブランチ削除・push を行わず、当日ブランチを残したまま調査できるようにする。
    mismatch_detail = _post_merge_diff(vault_root)
    if mismatch_detail.strip():
        print(
            json.dumps(
                {"status": "post_merge_mismatch", "detail": mismatch_detail},
                ensure_ascii=False,
            )
        )
        return 1

    # 4b. マージ済みの当日ブランチを削除する。ff-onlyマージ直後のため
    # branch の内容はすべて main に含まれており、`-d`(安全な削除、
    # 未マージなら失敗する)で問題なく削除できる。
    vault_lib.run_git("branch", "-d", branch, cwd=vault_root)
    branch_deleted = True

    # 5. origin が設定されていれば push を試みる(失敗しても致命的エラーにしない)
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

    # 6. 結果を出力する
    print(
        json.dumps(
            {
                "status": "ok",
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
