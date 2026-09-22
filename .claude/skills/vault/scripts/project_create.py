"""プロジェクトタイトルのみからプロジェクト一式を作成するスクリプト。

Project_Template.md からプロジェクト概要ノートを作成し、Tasks/Meetings/Documents
の3つの空サブフォルダを 10_Projects/<title>/ 配下に作る。LLMの判断を介さない、
決定論的な処理のみで完結する。
"""

from __future__ import annotations

import argparse
import datetime
import json
import sys
from pathlib import Path

import vault_lib

_TEMPLATE_RELATIVE_PATH = "70_Templates/Project_Template.md"
_SUBFOLDERS = ["Tasks", "Meetings", "Documents"]


def create_project(
    vault_root: Path,
    *,
    title: str,
    due_date: str | None,
    dt: datetime.datetime,
) -> dict:
    """プロジェクト一式(概要ノート+3サブフォルダ)を作成する。

    10_Projects/<title>/ が既に存在する場合は何も作成・変更せず、
    {"status": "error", "reason": "project_already_exists"} を返す。
    """
    safe_title = vault_lib.sanitize_filename(title)
    project_dir = vault_root / "10_Projects" / safe_title

    if project_dir.exists():
        return {"status": "error", "reason": "project_already_exists"}

    for subfolder in _SUBFOLDERS:
        (project_dir / subfolder).mkdir(parents=True, exist_ok=True)

    template_text = (vault_root / _TEMPLATE_RELATIVE_PATH).read_text(encoding="utf-8")
    filled = vault_lib.fill_template(template_text, title=title, dt=dt)
    fm_text, body_text = vault_lib.split_frontmatter(filled)

    if due_date:
        fm_text = vault_lib.set_fm_raw_value(fm_text, "due_date", due_date)

    note_text = f"---\n{fm_text}\n---\n{body_text}"

    note_path = project_dir / f"{safe_title}.md"
    note_path.write_text(note_text, encoding="utf-8")

    return {
        "status": "ok",
        "note_path": str(note_path),
        "folders": list(_SUBFOLDERS),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="project スキル: プロジェクト一式の作成")
    parser.add_argument("--title", required=True)
    parser.add_argument("--due-date", dest="due_date", default=None)
    parser.add_argument(
        "--vault-root",
        default=None,
        help="VAULT_ROOTを上書きする(テスト容易性のため)。省略時はvault_lib.VAULT_ROOTを使う。",
    )
    args = parser.parse_args(argv)

    vault_root = Path(args.vault_root) if args.vault_root else vault_lib.VAULT_ROOT

    result = create_project(
        vault_root,
        title=args.title,
        due_date=args.due_date,
        dt=datetime.datetime.now(),
    )

    print(json.dumps(result, ensure_ascii=False))
    return 1 if result["status"] == "error" else 0


if __name__ == "__main__":
    sys.exit(main())
