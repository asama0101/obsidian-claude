"""議事録ノートからアクションアイテムを抽出するスクリプト。

正規表現による決定的な処理のみを行い、LLMは使用しない。
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import vault_lib

# `## ⚡ アクションアイテム` または `### ⚡ アクションアイテム（今回）` の見出し行
_SECTION_HEADING_PATTERN = re.compile(
    r"^#{2,3} ⚡ アクションアイテム(?:（今回）)?[ \t]*$", re.MULTILINE
)
# 次の見出し行(セクションの終端)
_NEXT_HEADING_PATTERN = re.compile(r"^#", re.MULTILINE)
# `- [ ] 本文` 形式のチェックボックス行
_CHECKBOX_PATTERN = re.compile(r"^- \[ \] ?(.*)$", re.MULTILINE)


def extract_action_items(text: str) -> list[str]:
    """本文からアクションアイテムのセクションを探し、チェックボックス行の本文一覧を返す。"""
    heading_match = _SECTION_HEADING_PATTERN.search(text)
    if heading_match is None:
        return []

    section_start = heading_match.end()
    next_heading_match = _NEXT_HEADING_PATTERN.search(text, section_start)
    section_end = next_heading_match.start() if next_heading_match else len(text)
    section_text = text[section_start:section_end]

    return [m.group(1) for m in _CHECKBOX_PATTERN.finditer(section_text)]


def extract_project(text: str) -> str | None:
    """frontmatterから project の値を取得する。未設定なら None。"""
    fm_text, _ = vault_lib.split_frontmatter(text)
    project = vault_lib.get_fm_value(fm_text, "project")
    return project or None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--note", required=True)
    parser.add_argument("--vault-root", default=None)
    args = parser.parse_args()

    vault_root = Path(args.vault_root) if args.vault_root else vault_lib.VAULT_ROOT
    note_path = Path(args.note)
    if not note_path.is_absolute():
        note_path = vault_root / note_path

    text = note_path.read_text(encoding="utf-8")
    result = {
        "items": extract_action_items(text),
        "project": extract_project(text),
    }
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
