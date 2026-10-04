"""Vault のフック（.claude/settings.json から呼ばれる）。

  python vault_hooks.py session-start
      セッション開始時: 今日のデイリーノートのガントを更新し（ノートなしなら更新しない）、
      短い状況（デイリーノートの有無、「遅れ」「今日が期限」の件数、idea の件数、インボックスの
      タスクとその他の件数）を Claude に渡す（SessionStart の additionalContext）。
  python vault_hooks.py post-tool-use
      Claude が 20_tasks/*.md か 00_inbox/*.md を編集した直後: ガントを更新する。更新できないとき
      （デイリーノートなし、マーカーなし）は何も言わずに飛ばす。
      あわせて、編集したファイルをセッションごとに記録する（stop の通知で使う）。
  python vault_hooks.py stop
      Claude の応答が終わるたび: Windows の通知で「完了」と、そのターンで作成・編集したファイル
      （多ければ件数）を知らせる。通知をクリックすると、最初のファイルを Obsidian で開く。
  python vault_hooks.py notification
      Claude が許可や入力を待っているとき: Windows の通知で「確認待ち」を知らせる。

判定・ガントの生成は .claude/skills/daily-start/daily_start.py の関数を使う（定義を二重に持たない）。
どちらも、失敗してもセッションを止めない（例外は握りつぶして終了コード 0）。
テスト用: 環境変数 CLAUDE_PROJECT_DIR で Vault を、VAULT_TODAY（YYYY-MM-DD）で今日を、
VAULT_HOOK_STATE で編集の記録の置き場所を差し替えられる。通知は VAULT_NOTIFY_LOG（notify.py）で記録だけにできる。
"""
import contextlib
import datetime as dt
import io
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from urllib.parse import quote

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "skills" / "daily-start"))
sys.path.insert(0, str(HERE))

import daily_start as ds  # noqa: E402
import notify  # noqa: E402

INBOX = "00_inbox"
SHOWN_FILES = 3  # 通知に名前を出すファイルの数（残りは件数）


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
    """ダッシュボードの区分ごとの件数と、idea の件数（キー "idea"）を返す。"""
    counts = {}
    for p in ds.task_files(vault):
        props, _ = ds.read_task(p)
        if not props or props.get("type") != "task":
            continue
        group = ds.dashboard_group(props, day)
        if props.get("status") == "idea":
            group = "idea"
        if group:
            counts[group] = counts.get(group, 0) + 1
    return counts


def inbox_counts(vault):
    """インボックスの直下の (タスクのノートの件数, その他のファイル・フォルダの件数) を返す。"""
    folder = vault / INBOX
    if not folder.is_dir():
        return 0, 0
    tasks = others = 0
    for p in folder.iterdir():
        if p.name in (".gitkeep", "desktop.ini"):
            continue
        props = ds.read_task(p)[0] if p.is_file() and p.suffix == ".md" else None
        if props and props.get("type") == "task":
            tasks += 1
        else:
            others += 1
    return tasks, others


def session_context(vault, day):
    note = daily_note(vault, day)
    updated, problems = refresh_gantt(vault, day)
    counts = count_groups(vault, day)
    inbox_tasks, inbox_others = inbox_counts(vault)

    if not note.exists():
        note_line = "今日のデイリーノート: なし（作成は daily-start）"
    else:
        note_line = "今日のデイリーノート: あり（ガントを更新した）" if updated else "今日のデイリーノート: あり（ガントは更新していない）"
    lines = [
        f"Vault の状況（{day.isoformat()}、セッション開始時のフックが作成）",
        f"- {note_line}",
        f"- タスク: 遅れ {counts.get('遅れ', 0)} 件、今日が期限 {counts.get('今日が期限', 0)} 件、idea {counts.get('idea', 0)} 件",
        f"- インボックス（{INBOX}/）: タスク {inbox_tasks} 件、その他 {inbox_others} 件",
    ]
    lines += [f"- {p}" for p in problems]
    return "\n".join(lines)


def is_task_note(vault, file_path):
    """TASK_DIRS（20_tasks・00_inbox）の直下の .md なら True。"""
    if not file_path:
        return False
    try:
        path = Path(file_path)
        if not path.is_absolute():
            path = vault / path
        path = path.resolve()
    except OSError:
        return False
    for d in ds.TASK_DIRS:
        try:
            rel = path.relative_to((vault / d).resolve())
        except ValueError:
            continue
        return len(rel.parts) == 1 and rel.suffix == ".md"
    return False


def state_file(session_id):
    """セッションごとの、編集したファイルの記録（1行1パス）。"""
    root = Path(os.environ.get("VAULT_HOOK_STATE") or Path(tempfile.gettempdir()) / "claude-vault-hooks")
    safe = re.sub(r"[^\w-]", "_", session_id or "unknown")
    return root / f"{safe}.txt"


def record_edit(session_id, file_path):
    if not file_path:
        return
    path = state_file(session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(str(file_path).replace("\n", " ") + "\n")


def take_edits(session_id):
    """記録した編集を、重複を除いて順に返し、記録を消す。"""
    path = state_file(session_id)
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
        path.unlink()
    except OSError:
        return []
    seen, out = set(), []
    for line in lines:
        if line and line not in seen:
            seen.add(line)
            out.append(line)
    return out


def display_name(vault, file_path):
    """Vault の中なら Vault からの相対パス、外ならファイル名。"""
    try:
        return Path(file_path).resolve().relative_to(vault.resolve()).as_posix()
    except (ValueError, OSError):
        return Path(file_path).name


def obsidian_uri(vault, file_path):
    """Vault の中の Markdown なら、Obsidian で開く URI。それ以外は空。"""
    try:
        rel = Path(file_path).resolve().relative_to(vault.resolve())
    except (ValueError, OSError):
        return ""
    if rel.suffix != ".md":
        return ""
    return f"obsidian://open?vault={quote(vault.name)}&file={quote(rel.with_suffix('').as_posix())}"


def notify_stop(vault, payload):
    edits = take_edits(payload.get("session_id", ""))
    if not edits:
        notify.show("Claude Code: 完了", ["ファイルの変更はありません"])
        return
    names = [display_name(vault, f) for f in edits]
    lines = [", ".join(names[:SHOWN_FILES]) + (f" ほか {len(names) - SHOWN_FILES} 件" if len(names) > SHOWN_FILES else "")]
    lines.append(f"作成・編集: {len(names)} 件（クリックで最初のファイルを開く）")
    uri = next((u for u in (obsidian_uri(vault, f) for f in edits) if u), "")
    notify.show("Claude Code: 完了", lines, uri)


def notify_waiting(payload):
    message = payload.get("message") or "Claude が入力を待っています"
    notify.show("Claude Code: 確認待ち", [message])


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
        record_edit(payload.get("session_id", ""), file_path)
        if is_task_note(vault, file_path):
            refresh_gantt(vault, day)
    elif command == "stop":
        notify_stop(vault, payload)
    elif command == "notification":
        notify_waiting(payload)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv))
    except Exception:  # フックの失敗でセッションを止めない
        sys.exit(0)
