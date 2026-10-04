"""デイリーノートの作成、ガントチャートの再生成、Obsidian の起動を行う。

使い方: python daily_start.py [--no-launch] [--gantt-only] [--vault <Vault のパス>] [--date YYYY-MM-DD]
--gantt-only: 既存のノートのガントだけを更新する（gantt-update スキル用。ノート作成・Obsidian 起動はしない）

読めないタスクや、start / due が空のタスクは、ガントに出さずに名前を表示する。
"""
import argparse
import datetime as dt
import os
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import quote

DEFAULT_VAULT = Path(__file__).resolve().parents[3]
OBSIDIAN_EXE = Path(r"C:\Program Files\Obsidian\Obsidian.exe")
GANTT_START = "<!-- gantt:start -->"
GANTT_END = "<!-- gantt:end -->"
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
# ガントの表示期間: ノートの日付の PAST_DAYS 日前〜FUTURE_DAYS 日後。
# 完了済みは、ノートの日付に完了したものだけ表示する。
PAST_DAYS = 0
FUTURE_DAYS = 90

# タスクを置くフォルダ（振り分け前の 00_inbox と、振り分け後の 20_tasks。どちらも直下だけ）
TASK_DIRS = ("20_tasks", "00_inbox")
# 進めるタスクの状態。idea / shelved / cancelled はダッシュボードの区分表・ガントに出さない
ACTIVE = ("todo", "in_progress", "waiting", "requested")
# ガントで名前の先頭に付ける印
MARKS = {"waiting": "⏸", "requested": "✉"}


def read(path):
    return path.read_text(encoding="utf-8")


def write(path, text):
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def parse_frontmatter(text):
    m = re.match(r"\A---\r?\n(.*?)\r?\n---", text, re.S)
    if not m:
        return {}
    props = {}
    for line in m.group(1).splitlines():
        km = re.match(r"^([A-Za-z_][\w-]*):\s*(.*)$", line)
        if km:
            props[km.group(1)] = km.group(2).strip().strip("\"'")
    return props


def link_name(value):
    """[[名前|別名]] を 名前 に変換する。リンクでなければそのまま返す。"""
    m = re.match(r"^\[\[([^\]|#]+)", value)
    return m.group(1).strip() if m else value.strip()


def clean(name):
    """Mermaid の gantt で崩れる文字を除く。"""
    return re.sub(r"[:;#,\"]", " ", name).strip()


CHECK_RE = re.compile(r"^\s*[-*]\s+\[([ xX])\]\s+(.+?)\s*$")
CHECK_DUE_RE = re.compile(r"\s*期限:(\d{4}-\d{2}-\d{2})\s*$")
CHECK_BLOCK_RE = re.compile(re.escape(GANTT_START) + r"(.*?)" + re.escape(GANTT_END), re.S)


def parse_checklist(text):
    """タスク本文のチェックリストを、マイルストーンとして取り出す。

    対象は `<!-- gantt:start -->` 〜 `<!-- gantt:end -->` の間の行だけ（組は複数でもよい。
    マーカーが無ければ何も拾わない）。書式: `- [ ] 項目名 期限:YYYY-MM-DD`（期限は任意）。
    """
    lines = [line for block in CHECK_BLOCK_RE.findall(text) for line in block.splitlines()]
    items = []
    for line in lines:
        m = CHECK_RE.match(line)
        if not m:
            continue
        name = m.group(2)
        due = None
        dm = CHECK_DUE_RE.search(name)
        if dm:
            try:
                due = dt.date.fromisoformat(dm.group(1))
            except ValueError:
                due = None
            name = name[: dm.start()]
        name = clean(name)
        if name:
            items.append({"name": name, "due": due, "done": m.group(1) != " "})
    return items


def render_template(text, today, title):
    def date_sub(m):
        fmt = m.group(1) or "YYYY-MM-DD"
        py = fmt.replace("YYYY", "%Y").replace("MM", "%m").replace("DD", "%d")
        return today.strftime(py)

    text = re.sub(r"\{\{date(?::([^}]*))?\}\}", date_sub, text)
    return text.replace("{{title}}", title)


def create_daily(vault, today):
    path = vault / "60_daily" / f"{today.isoformat()}.md"
    if path.exists():
        return path, False
    template = vault / "90_system" / "templates" / "daily.md"
    if template.exists():
        body = render_template(read(template), today, today.isoformat())
    else:
        body = f"---\ntype: daily\ncreated: {today.isoformat()}\n---\n# {today.isoformat()}\n"
    path.parent.mkdir(exist_ok=True)
    write(path, body)
    return path, True


def is_late(status, start, due, today):
    """「遅れ」（ガントでは赤）の判定。ダッシュボードの Bases（daily-tasks.base）と同じ定義にする。

    todo は start だけ、in_progress / waiting / requested は due だけを見る（使わない方は None でもよい）。
    """
    if status == "todo":
        return start <= today
    if status in ("in_progress", "waiting", "requested"):
        return due < today
    return False


def dashboard_group(props, today):
    """ダッシュボード（daily-tasks.base の formula 区分）と同じ区分を返す。該当なしは None。

    "遅れ" / "今日が期限" / "作業中" / "依頼中" / "保留" / "今日完了"（1つのタスクは最初に該当した区分だけ）。
    「遅れ」は is_late と同じ定義（判定に要る日付が空なら遅れにしない）。
    idea / shelved / cancelled は区分なし（アイデアは別の表で見る）。
    """
    status = props.get("status", "todo")
    start, due = to_date(props.get("start", "")), to_date(props.get("due", ""))
    if status == "done":
        return "今日完了" if to_date(props.get("completed", "")) == today else None
    if status not in ACTIVE:
        return None
    needed = start if status == "todo" else due
    if needed is not None and is_late(status, start, due, today):
        return "遅れ"
    if due == today:
        return "今日が期限"
    return {"in_progress": "作業中", "requested": "依頼中", "waiting": "保留"}.get(status)


def read_task(p):
    """タスクのノートを読み、(props, text) を返す。読めなければ (None, 理由)。"""
    try:
        text = read(p)
    except (OSError, UnicodeDecodeError) as e:
        return None, f"{type(e).__name__}: {e}"
    return parse_frontmatter(text), text


def to_date(value):
    """YYYY-MM-DD を date にする。空・不正なら None。"""
    if not DATE_RE.match(value):
        return None
    try:
        return dt.date.fromisoformat(value)
    except ValueError:
        return None


def task_dates(props):
    """(start, due) を date で返す。どちらかが空・不正なら None。"""
    start, due = to_date(props.get("start", "")), to_date(props.get("due", ""))
    return (start, due) if start and due else None


def task_files(vault):
    """タスクのノートの候補（TASK_DIRS の直下の .md）を返す。"""
    files = []
    for d in TASK_DIRS:
        files += (vault / d).glob("*.md")
    return sorted(files, key=lambda p: (p.stem, p.parent.name))


def collect_gantt_tasks(vault, today, problems=None):
    """ガントに出すタスクを集める。

    problems（リスト）を渡すと、ガントに出さなかった理由のある未完了タスクを、表示用の行として足す
    （読めないノート、start / due が空・不正なもの）。
    """
    left = today - dt.timedelta(days=PAST_DAYS)
    right = today + dt.timedelta(days=FUTURE_DAYS)
    tasks = []
    unreadable, undated = [], []
    for p in task_files(vault):
        props, text = read_task(p)
        if props is None:
            unreadable.append(f"{p.stem}（{text}）")
            continue
        if props.get("type") != "task":
            continue
        status = props.get("status", "todo")
        if status not in ACTIVE and status != "done":
            continue
        dates = task_dates(props)
        if dates is None:
            if status != "done":
                undated.append(p.stem)
            continue
        start, due = dates
        if status == "done":
            if to_date(props.get("completed", "")) != today:
                continue
        elif start > right or due < left or (status == "todo" and start < left):
            # 左端より前に期限がある未完了、および開始が遅れている todo は、
            # ガントに出さない（ダッシュボードの「遅れ」で確認する）
            continue
        late = is_late(status, start, due, today)
        name = clean(p.stem)
        name = MARKS.get(status, "") + name
        if due < left:
            # 完了済みで期限が左端より前のものは、左端に1日分だけ寄せて表示する
            s, e = left, left
        else:
            s, e = max(start, left), min(max(due, start), right)
            if start < left:
                name = "←" + name
            if due > right:
                name += f"→{due.isoformat()}"
        tasks.append(
            {
                "name": name,
                "project": clean(link_name(props.get("project", ""))) or "プロジェクトなし",
                "start": s,
                "due": e,
                "status": status,
                "late": late,
                "milestones": parse_checklist(text),
            }
        )
    if problems is not None:
        if unreadable:
            problems.append("注意: 読めないためガントに出していないタスク: " + ", ".join(unreadable))
        if undated:
            problems.append("注意: start / due が空または不正なためガントに出していないタスク: " + ", ".join(undated))
    return tasks


def milestone_line(m, start, n, today):
    """チェックリスト項目を、タスクの表示開始日に置くマイルストーンの1行にする。

    完了は done（グレー）、期限が基準日より前の未完了は crit（赤）。期限は名前の後ろに付けるだけ。
    """
    name = "◇" + m["name"]
    if m["due"]:
        name += f"（期限 {m['due'].isoformat()}）"
    tag = "milestone, "
    if m["done"]:
        tag += "done, "
    elif m["due"] and m["due"] < today:
        tag += "crit, "
    return f"    {name} :{tag}t{n}, {start.isoformat()}, 0d"


def build_gantt(tasks, today):
    if not tasks:
        return "開始日（start）と期限（due）を持つタスクがありません。"
    lines = ["```mermaid", "gantt", "    dateFormat YYYY-MM-DD", "    axisFormat %m/%d", "    tickInterval 1week"]
    projects = sorted({t["project"] for t in tasks})
    n = 0
    for proj in projects:
        lines.append(f"    section {proj}")
        for t in tasks:
            if t["project"] != proj:
                continue
            n += 1
            end = max(t["due"], t["start"]) + dt.timedelta(days=1)  # 終了日は排他的
            tag = "crit, " if t["late"] else {"done": "done, ", "in_progress": "active, "}.get(t["status"], "")
            lines.append(f"    {t['name']} :{tag}t{n}, {t['start'].isoformat()}, {end.isoformat()}")
            for m in t["milestones"]:
                n += 1
                lines.append(milestone_line(m, t["start"], n, today))
    lines.append("```")
    return "\n".join(lines)


def update_gantt(note, vault, today):
    """ノートのガントを再生成する。マーカーが無ければ None、更新したら注意の行のリスト（空もあり）を返す。"""
    text = read(note)
    if GANTT_START not in text or GANTT_END not in text:
        print(f"ガントのマーカーがないため更新しません: {note.name}")
        return None
    problems = []
    block = build_gantt(collect_gantt_tasks(vault, today, problems), today)
    pattern = re.compile(re.escape(GANTT_START) + r".*?" + re.escape(GANTT_END), re.S)
    new = pattern.sub(lambda _: f"{GANTT_START}\n{block}\n{GANTT_END}", text)
    if new != text:
        write(note, new)
    return problems


def launch_obsidian(vault, note):
    rel = note.relative_to(vault).with_suffix("").as_posix()
    uri = f"obsidian://open?vault={quote(vault.name)}&file={quote(rel)}"
    try:
        os.startfile(uri)
    except OSError:
        subprocess.Popen([str(OBSIDIAN_EXE)])


def gantt_only(vault, today):
    """既存のデイリーノートのガントだけを更新する。ノートがないときはエラー終了する。"""
    note = vault / "60_daily" / f"{today.isoformat()}.md"
    if not note.exists():
        print(f"警告: デイリーノートがありません: {note}（作成は daily-start）")
        sys.exit(1)
    problems = update_gantt(note, vault, today)
    if problems is None:
        sys.exit(1)
    print(f"更新: {note}")
    for line in problems:
        print(line)


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-launch", action="store_true", help="Obsidian を起動しない")
    ap.add_argument("--vault", type=Path, default=DEFAULT_VAULT)
    ap.add_argument("--date", type=dt.date.fromisoformat, default=dt.date.today())
    ap.add_argument(
        "--gantt-only",
        action="store_true",
        help="既存のデイリーノートのガントだけを更新する（ノートの作成、Obsidian の起動をしない）",
    )
    args = ap.parse_args()

    if args.gantt_only:
        gantt_only(args.vault, args.date)
        return

    note, created = create_daily(args.vault, args.date)
    print(("作成: " if created else "既存: ") + str(note))
    for line in update_gantt(note, args.vault, args.date) or []:
        print(line)
    if not args.no_launch:
        launch_obsidian(args.vault, note)


if __name__ == "__main__":
    main()
