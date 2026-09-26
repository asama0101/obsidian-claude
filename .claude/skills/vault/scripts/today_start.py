"""Obsidian Vault用 Claude Codeプラグイン「vault」の today スキル本体。

1日の作業開始時に実行する。未マージの過去日ブランチが残っていないか確認し、
当日日付のgitブランチを作成・チェックアウトしたうえで、デイリーノートを
テンプレートから作成する（前日ノートのCarryoverブロックがあれば転記する）。
また、新規ブランチ作成時はmain上の未コミット変更を検出しコミットする。
"""

from __future__ import annotations

import argparse
import datetime
import json
import re
import sys
from pathlib import Path

import vault_lib

# YYYY-MM-DD 形式のブランチ名/ファイル名に一致する正規表現
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

_CARRYOVER_START = "CARRYOVER_START"
_CARRYOVER_END = "CARRYOVER_END"


def _list_branch_names(vault_root: Path) -> list[str]:
    """ローカルブランチ名の一覧を返す。"""
    output = vault_lib.run_git("branch", "--format=%(refname:short)", cwd=vault_root)
    return [line.strip() for line in output.split("\n") if line.strip()]


def _find_carryover_source(daily_dir: Path, today: str) -> Path | None:
    """10_Daily配下から当日より前の日付で最新のノートを探す。

    ファイル名(日付文字列)の降順で走査し、最初に見つかったものを返す。
    連続した日付である必要はない。見つからなければ None。
    """
    if not daily_dir.exists():
        return None

    candidates = sorted(
        (p for p in daily_dir.glob("*.md") if _DATE_RE.match(p.stem) and p.stem < today),
        key=lambda p: p.stem,
        reverse=True,
    )
    return candidates[0] if candidates else None


def _has_origin_remote(vault_root: Path) -> bool:
    """origin リモートが設定されているかを判定する。"""
    try:
        vault_lib.run_git("remote", "get-url", "origin", cwd=vault_root)
        return True
    except Exception:
        return False


def _commit_stray_changes(vault_root: Path, today: str) -> str | None:
    """mainに残っていた追跡済みファイルの未コミット変更を検出し、新ブランチ上でコミットする。

    コミットした場合はそのコミットSHAを、変更が無ければNoneを返す。
    """
    # --untracked-files=no: 未追跡の新規ファイルは対象外(git add -uの対象範囲と一致させる)。
    status_output = vault_lib.run_git(
        "-c", "core.quotepath=false",
        "status", "--porcelain", "--untracked-files=no",
        cwd=vault_root,
    )
    if not status_output.strip():
        return None

    vault_lib.run_git("add", "-u", cwd=vault_root)
    vault_lib.run_git(
        "commit", "-m",
        f"Commit stray uncommitted changes found on main before opening daily branch for {today}",
        cwd=vault_root,
    )
    return vault_lib.run_git("rev-parse", "HEAD", cwd=vault_root).strip()


def run(vault_root: Path, dt: datetime.datetime | None = None) -> dict:
    """today スキルの処理本体。結果を dict で返す(JSON化はしない)。"""
    dt = dt or datetime.datetime.now()
    today = dt.strftime("%Y-%m-%d")

    # run()全体で使う。分岐に関わらずここで初期化する(既存ブランチパスでは常にNoneのまま)。
    stray_commit_sha: str | None = None

    # 1. 未マージの過去日ブランチが残っていないか確認する。
    #    このスクリプト自身はマージ・削除しない。
    no_merged_output = vault_lib.run_git(
        "branch", "--no-merged", "main", "--format=%(refname:short)", cwd=vault_root
    )
    no_merged_branches = [line.strip() for line in no_merged_output.split("\n") if line.strip()]
    blocked_branches = [
        b for b in no_merged_branches if _DATE_RE.match(b) and b != today
    ]
    if blocked_branches:
        return {
            "status": "blocked",
            "branches": blocked_branches,
            "stray_changes_committed": stray_commit_sha,
        }

    # 2. 当日ブランチの確認・作成(べき等)
    if today in _list_branch_names(vault_root):
        vault_lib.run_git("checkout", today, cwd=vault_root)
        branch_status = "existing"
    else:
        vault_lib.run_git("checkout", "main", cwd=vault_root)
        if _has_origin_remote(vault_root):
            # 失敗しても続行する(オフライン等を許容するため)。
            vault_lib.run_git("pull", "--ff-only", cwd=vault_root, check=False)
        vault_lib.run_git("checkout", "-b", today, cwd=vault_root)
        branch_status = "created"

        stray_commit_sha = _commit_stray_changes(vault_root, today)

    # 3. デイリーノートが既に存在する場合はCarryover転記をスキップする。
    daily_dir = vault_root / "10_Daily"
    daily_note_path = daily_dir / f"{today}.md"
    if daily_note_path.exists():
        return {
            "status": "ok",
            "branch": branch_status,
            "daily_note": "skipped",
            "stray_changes_committed": stray_commit_sha,
        }

    # 4. 前日候補ノートを探す(連続していなくてもよい)。
    carryover_source_path = _find_carryover_source(daily_dir, today)
    carryover_source = carryover_source_path.stem if carryover_source_path else None

    # 5. 前日ノートからCarryoverブロックの中身だけを読み取る(元ノートは変更しない)。
    carryover_inner = None
    if carryover_source_path is not None:
        prev_text = carryover_source_path.read_text(encoding="utf-8")
        carryover_inner = vault_lib.get_marker_block(prev_text, _CARRYOVER_START, _CARRYOVER_END)

    # 6. テンプレートを展開し、Carryoverブロックのみ差し替える。
    #    UPDATED_NOTESブロックはプレースホルダのまま(closeスキルが後で上書きする)。
    template_path = vault_root / "80_Templates" / "Daily_Template.md"
    template_text = template_path.read_text(encoding="utf-8")
    filled_text = vault_lib.fill_template(template_text, title=today, dt=dt)
    if carryover_inner:
        filled_text = vault_lib.set_marker_block(
            filled_text, _CARRYOVER_START, _CARRYOVER_END, carryover_inner
        )

    # 7. デイリーノートを書き込む。
    daily_dir.mkdir(parents=True, exist_ok=True)
    daily_note_path.write_text(filled_text, encoding="utf-8")

    return {
        "status": "ok",
        "branch": branch_status,
        "daily_note": "created",
        "carryover_source": carryover_source,
        "stray_changes_committed": stray_commit_sha,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="today スキル: 当日ブランチ作成とデイリーノート作成")
    parser.add_argument(
        "--vault-root",
        default=None,
        help="VAULT_ROOTを上書きする(テスト容易性のため)。省略時はvault_lib.VAULT_ROOTを使う。",
    )
    args = parser.parse_args(argv)

    vault_root = Path(args.vault_root) if args.vault_root else vault_lib.VAULT_ROOT
    result = run(vault_root)
    print(json.dumps(result, ensure_ascii=False))
    return 1 if result["status"] == "blocked" else 0


if __name__ == "__main__":
    sys.exit(main())
