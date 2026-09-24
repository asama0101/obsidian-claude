"""アクションアイテムや口頭指示からタスクノートを作成するスクリプト。"""

from __future__ import annotations

import argparse
import datetime
import json
import sys
from pathlib import Path

import vault_lib

_TEMPLATE_RELATIVE_PATH = "80_Templates/Task_Template.md"


def build_note_text(
    template_text: str,
    *,
    title: str,
    project: str,
    due_date: str | None,
    dt: datetime.datetime,
    source: str | None = None,
) -> str:
    """テンプレートを埋め、frontmatterを確定してタスクノート本文を組み立てる。"""
    filled = vault_lib.fill_template(template_text, title=title, dt=dt)
    fm_text, body_text = vault_lib.split_frontmatter(filled)

    fm_text = vault_lib.set_fm_value(fm_text, "project", vault_lib.normalize_project_link(project))
    fm_text = vault_lib.set_fm_raw_value(fm_text, "created_date", dt.strftime("%Y-%m-%d"))
    # start_date はテンプレート側で空欄のままにするため、ここでは一切セットしない
    # due_date は fill_template で今日の日付が入るため、未指定時は明示的に空欄へ戻す
    fm_text = vault_lib.set_fm_raw_value(fm_text, "due_date", due_date or "")
    if source:
        fm_text = vault_lib.set_fm_value(fm_text, "source_meeting", source)

    return f"---\n{fm_text}\n---\n{body_text}"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--title", required=True)
    parser.add_argument("--project", default=None)
    parser.add_argument("--due-date", dest="due_date", default=None)
    parser.add_argument(
        "--source",
        default=None,
        help='議事録ノートへのwikilink（例: "[[2026-09-21 定例MTG]]"）。議事録経由で'
        "呼ばれた場合のみ指定し、フリーフォーム入力時は省略する。",
    )
    parser.add_argument("--vault-root", default=None)
    args = parser.parse_args()

    if args.source and ("\n" in args.source or '"' in args.source):
        print(json.dumps({"status": "error", "reason": "invalid_source"}, ensure_ascii=False))
        sys.exit(1)

    vault_root = Path(args.vault_root) if args.vault_root else vault_lib.VAULT_ROOT

    if args.project:
        project_name = vault_lib.extract_project_name(args.project)
        project_dir = vault_root / "20_Projects" / project_name
        if not project_dir.is_dir():
            print(
                json.dumps({"status": "error", "reason": "project_not_found"}, ensure_ascii=False)
            )
            sys.exit(1)
        tasks_dir = project_dir / "Tasks"
    else:
        tasks_dir = vault_root / "30_Areas" / "Tasks"

    template_text = (vault_root / _TEMPLATE_RELATIVE_PATH).read_text(encoding="utf-8")

    now = datetime.datetime.now()
    note_text = build_note_text(
        template_text,
        title=args.title,
        project=args.project or "",
        due_date=args.due_date,
        source=args.source,
        dt=now,
    )

    tasks_dir.mkdir(parents=True, exist_ok=True)

    filename = f"{vault_lib.sanitize_filename(args.title)}.md"
    note_path = vault_lib.unique_path(tasks_dir, filename)
    note_path.write_text(note_text, encoding="utf-8")

    print(json.dumps({"note_path": str(note_path)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
