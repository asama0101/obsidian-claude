"""タスクノートの「進捗メモ」セクションにtodo項目を追加するスクリプト。"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import vault_lib

# プレースホルダー行（本文が無い `- [ ] ` 行）判定用
_PLACEHOLDER_LINE_PATTERN = re.compile(r"^- \[ \][ \t]*$")

# 未完了チェックボックス行からラベルを取り出す（重複判定用）
_UNCHECKED_LABEL_PATTERN = re.compile(r"^- \[ \] (.+)$")


def _existing_unchecked_labels(section: str) -> set[str]:
    """既存セクション内の未完了(`- [ ] `)チェックボックス行のラベル集合を返す。

    完全一致のラベル文字列での重複判定に使う。プレースホルダー行(本文なし)は
    ラベルが空になるため対象外(マッチしない)。
    """
    labels = set()
    for line in section.split("\n"):
        match = _UNCHECKED_LABEL_PATTERN.match(line.strip())
        if match:
            labels.add(match.group(1))
    return labels


def _apply_todos(existing_section: str, todos: list[str]) -> tuple[str, str, int]:
    """既存セクションにtodoを反映し、(新セクション, mode, 追加件数)を返す。

    既存セクションが空、またはプレースホルダー行のみで構成されるなら置換
    ("replace")、実質的な記載があるなら末尾へ追記("append")する。追記時、
    既存セクションに既に同一テキストの未完了行があるtodoは重複追加しない。
    追加件数は重複排除後の実際の追加件数。
    """
    cleaned_todos = [todo.strip() for todo in todos if todo.strip()]

    is_placeholder_only = True
    for line in existing_section.split("\n"):
        stripped = line.strip()
        if not stripped:
            continue
        if _PLACEHOLDER_LINE_PATTERN.match(stripped):
            continue
        is_placeholder_only = False
        break

    if is_placeholder_only:
        new_lines = [f"- [ ] {todo}" for todo in cleaned_todos]
        return "\n".join(new_lines), "replace", len(cleaned_todos)

    existing_labels = _existing_unchecked_labels(existing_section)
    deduped_todos = [todo for todo in cleaned_todos if todo not in existing_labels]
    if not deduped_todos:
        return existing_section, "append", 0

    new_lines = [f"- [ ] {todo}" for todo in deduped_todos]
    new_section = existing_section.rstrip("\n") + "\n" + "\n".join(new_lines)
    return new_section, "append", len(deduped_todos)


def _resolve_note_path(note_arg: str, vault_root: Path) -> Path:
    """--note引数をvault_root基準の絶対パスに解決する。"""
    note_path = Path(note_arg)
    if not note_path.is_absolute():
        note_path = vault_root / note_path
    return note_path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--note", required=True)
    parser.add_argument("--todo", action="append", default=[])
    parser.add_argument("--vault-root", default=None)
    args = parser.parse_args()

    todos = [todo for todo in args.todo if todo.strip()]
    if not todos:
        print(json.dumps({"status": "error", "reason": "no_todos"}, ensure_ascii=False))
        sys.exit(1)

    vault_root = Path(args.vault_root) if args.vault_root else vault_lib.VAULT_ROOT

    note_path = _resolve_note_path(args.note, vault_root)
    try:
        note_path.resolve().relative_to(vault_root.resolve())
    except ValueError:
        print(
            json.dumps({"status": "error", "reason": "path_outside_vault"}, ensure_ascii=False)
        )
        sys.exit(1)

    if not note_path.is_file():
        print(json.dumps({"status": "error", "reason": "note_not_found"}, ensure_ascii=False))
        sys.exit(1)

    note_text = note_path.read_text(encoding="utf-8")
    fm_text, body_text = vault_lib.split_frontmatter(note_text)
    if vault_lib.get_fm_value(fm_text, "type") != "task":
        print(json.dumps({"status": "error", "reason": "not_a_task_note"}, ensure_ascii=False))
        sys.exit(1)

    existing_section = vault_lib.get_heading_section(body_text, vault_lib.PROGRESS_HEADING_PATTERN)
    new_section, mode, added = _apply_todos(existing_section, todos)
    new_body = vault_lib.set_heading_section(
        body_text, vault_lib.PROGRESS_HEADING_PATTERN, new_section
    )

    note_path.write_text(f"---\n{fm_text}\n---\n{new_body}", encoding="utf-8")

    print(
        json.dumps(
            {"status": "ok", "note_path": str(note_path), "added": added, "mode": mode},
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
