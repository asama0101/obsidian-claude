"""Vault のフック（.claude/settings.json から呼ばれる）。

  python vault_hooks.py session-start
      セッション開始時: 今日のデイリーノートのガントを更新し（ノートなしなら更新しない）、
      短い状況（デイリーノートの有無、「遅れ」「今日が期限」の件数、インボックスの件数）を
      Claude に渡す（SessionStart の additionalContext）。
  python vault_hooks.py post-tool-use
      Claude が 20_tasks/*.md を編集した直後: ガントを更新する。更新できないとき
      （デイリーノートなし、マーカーなし）は何も言わずに飛ばす。

判定・ガントの生成は .claude/skills/daily-start/daily_start.py の関数を使う（定義を二重に持たない）。
どちらも、失敗してもセッションを止めない（例外は握りつぶして終了コード 0）。
テスト用: 環境変数 CLAUDE_PROJECT_DIR で Vault を、VAULT_TODAY（YYYY-MM-DD）で今日を差し替えられる。
"""
import contextlib
import datetime as dt
import io
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "skills" / "daily-start"))

import daily_start as ds  # noqa: E402

INBOX = "00_inbox"


def vault_root():
    override = os.environ.get("CLAUDE_PROJECT_DIR")
    return Path(override) if override else HERE.parents[1]


def today():
    override = os.environ.get("VAULT_TODAY")
    return dt.date.fromisoformat(override) if override else dt.date.today()


def daily_note(vault, day):
    return vault / "60_daily" / f"{day.isoformat()}.md"


def refresh_gantt(vault, day):
    """更新できる状況なら、ガントを更新する。(更新したか, 注意の行) を返す。標準出力には何も出さない。"""
    note = daily_note(vault, day)
    if not note.exists():
        return False, []
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            problems = ds.update_gantt(note, vault, day)
    except (OSError, UnicodeDecodeError):
        return False, []
    return problems is not None, problems or []


def count_groups(vault, day):
    counts = {}
    for p in sorted((vault / "20_tasks").glob("*.md")):
        props, _ = ds.read_task(p)
        if not props or props.get("type") != "task":
            continue
        group = ds.dashboard_group(props, day)
        if group:
            counts[group] = counts.get(group, 0) + 1
    return counts


def inbox_count(vault):
    folder = vault / INBOX
    if not folder.is_dir():
        return 0
    return sum(1 for p in folder.iterdir() if p.is_file() and p.name != ".gitkeep")


def session_context(vault, day):
    note = daily_note(vault, day)
    updated, problems = refresh_gantt(vault, day)
    counts = count_groups(vault, day)

    if not note.exists():
        note_line = "今日のデイリーノート: なし（作成は daily-start）"
    else:
        note_line = "今日のデイリーノート: あり（ガントを更新した）" if updated else "今日のデイリーノート: あり（ガントは更新していない）"
    lines = [
        f"Vault の状況（{day.isoformat()}、セッション開始時のフックが作成）",
        f"- {note_line}",
        f"- タスク: 遅れ {counts.get('遅れ', 0)} 件、今日が期限 {counts.get('今日が期限', 0)} 件",
        f"- インボックス（{INBOX}/）: {inbox_count(vault)} 件",
    ]
    lines += [f"- {p}" for p in problems]
    return "\n".join(lines)


def is_task_note(vault, file_path):
    if not file_path:
        return False
    try:
        path = Path(file_path)
        if not path.is_absolute():
            path = vault / path
        rel = path.resolve().relative_to((vault / "20_tasks").resolve())
    except (ValueError, OSError):
        return False
    return len(rel.parts) == 1 and rel.suffix == ".md"


def main(argv):
    command = argv[1] if len(argv) > 1 else ""
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except (json.JSONDecodeError, UnicodeDecodeError):
        payload = {}
    vault = vault_root()
    day = today()
    if command == "session-start":
        context = session_context(vault, day)
        out = {"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": context}}
        sys.stdout.buffer.write(json.dumps(out, ensure_ascii=False).encode("utf-8"))
    elif command == "post-tool-use":
        file_path = (payload.get("tool_input") or {}).get("file_path", "")
        if is_task_note(vault, file_path):
            refresh_gantt(vault, day)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv))
    except Exception:  # フックの失敗でセッションを止めない
        sys.exit(0)
