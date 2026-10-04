"""knowledge-harvest スキル用のスクリプト（標準ライブラリだけで動く）。

サブコマンド:
  targets [--date YYYY-MM-DD]
      棚卸しの対象を JSON で出力する。
      - memo: 今日のデイリーの「今日のメモ」の項目のうち、行末に「 → [[」の印がないもの
      - tasks: 前回の棚卸し以降に更新されたタスクのノート（20_tasks・00_inbox の直下）と、
        その「経緯」の節の、印のない行
      - since: 判定に使った日時（前回の棚卸しの日時。記録がなければ今日の 0 時）
  index
      80_context/_index.md（索引）と 80_context/_rules.md（再発防止のルール）を作り直す。
  mark [--at ISO日時]
      棚卸しを終えた日時を 90_system/harvest-state.json に記録する（既定は今）。

テスト用: --vault で Vault を差し替えられる。
"""
import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path

DEFAULT_VAULT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "daily-start"))

import daily_start as ds  # noqa: E402

CONTEXT = "80_context"
STATE = Path("90_system") / "harvest-state.json"
MARK = " → [["
INDEX_NOTE = "<!-- 自動生成（knowledge-harvest の harvest.py index）。手で編集しない -->"


# ---------------------------------------------------------------- 共通

def section(text, heading):
    """`## heading` の節の本文の行（次の `## ` の前まで）を返す。なければ空のリスト。"""
    lines = text.splitlines()
    out, inside = [], False
    for line in lines:
        if re.match(r"^##\s", line):
            if inside:
                break
            inside = line[2:].strip() == heading
            continue
        if inside:
            out.append(line)
    return out


def first_text(lines):
    """節の行から、最初の中身のある行（箇条書きの記号は外す）を返す。"""
    for line in lines:
        s = re.sub(r"^\s*[-*]\s+(\[[ xX]\]\s+)?", "", line).strip()
        if s and not s.startswith("%%") and not s.startswith("<!--"):
            return s
    return ""


def read_state(vault):
    try:
        data = json.loads((vault / STATE).read_text(encoding="utf-8"))
        return dt.datetime.fromisoformat(data["last"])
    except (OSError, ValueError, KeyError, TypeError):
        return None


# ---------------------------------------------------------------- targets

def memo_items(text):
    """「今日のメモ」の項目（子の行を含めて1項目）のうち、印のないものを返す。"""
    items, cur = [], None
    for line in section(text, "今日のメモ"):
        if re.match(r"^[-*]\s+\S", line):
            if cur:
                items.append(cur)
            cur = [line]
        elif cur is not None and line.strip() and line[:1] in (" ", "\t"):
            cur.append(line)
        elif line.strip():
            if cur:
                items.append(cur)
            cur = None
            items.append([line])
    if cur:
        items.append(cur)
    return ["\n".join(i) for i in items if MARK not in i[0]]


def progress_lines(text):
    """「経緯」の節の、中身のある行のうち印のないもの（日付の見出しは文脈として残す）。"""
    out = []
    for line in section(text, "経緯"):
        if not line.strip():
            continue
        if line.lstrip().startswith("#"):
            out.append(line)
        elif MARK not in line:
            out.append(line)
    # 見出しだけで中身のない日付は除く
    cleaned = []
    for i, line in enumerate(out):
        if line.lstrip().startswith("#") and (i + 1 >= len(out) or out[i + 1].lstrip().startswith("#")):
            continue
        cleaned.append(line)
    return cleaned


def cmd_targets(vault, day):
    since = read_state(vault) or dt.datetime.combine(day, dt.time())
    note = vault / "60_daily" / f"{day.isoformat()}.md"
    memo = memo_items(ds.read(note)) if note.exists() else []
    tasks = []
    for p in ds.task_files(vault):
        try:
            mtime = dt.datetime.fromtimestamp(p.stat().st_mtime)
        except OSError:
            continue
        if mtime <= since:
            continue
        props, text = ds.read_task(p)
        if not props or props.get("type") != "task":
            continue
        tasks.append(
            {
                "path": p.relative_to(vault).as_posix(),
                "status": props.get("status", ""),
                "project": ds.link_name(props.get("project", "")),
                "updated": mtime.isoformat(timespec="minutes"),
                "progress": progress_lines(text),
            }
        )
    out = {"since": since.isoformat(timespec="minutes"), "memo": memo, "tasks": tasks}
    sys.stdout.buffer.write(json.dumps(out, ensure_ascii=False, indent=1).encode("utf-8"))
    return 0


# ---------------------------------------------------------------- index

def notes(vault, sub):
    folder = vault / CONTEXT / sub
    return sorted(folder.glob("*.md")) if folder.is_dir() else []


def active_projects(vault):
    out = []
    for p in sorted((vault / "10_projects").glob("*/*.md")):
        if p.stem != p.parent.name:
            continue
        props, _ = ds.read_task(p)
        if props and props.get("type") == "project" and props.get("status") == "active":
            out.append(p.stem)
    return out


def build_index(vault):
    lines = [INDEX_NOTE, "# Claude のインプットの索引", "",
             f"`{CONTEXT}/` の記録の一覧。詳しくは各ノートを開いて読む。", ""]

    lines.append("## 進行中のプロジェクト（現在の要約）")
    # 進捗ログは「<プロジェクト名> 進捗ログ.md」。対応は frontmatter の project で取る
    logs = {}
    for p in notes(vault, "projects"):
        logs[ds.link_name(ds.parse_frontmatter(ds.read(p)).get("project", "")) or p.stem] = p
    projects = active_projects(vault)
    if not projects:
        lines.append("- なし")
    for name in projects:
        log = logs.get(name)
        if not log:
            lines.append(f"- [[{name}]]: 進捗ログなし")
            continue
        summary = [s.strip() for s in section(ds.read(log), "現在の要約") if s.strip()]
        lines.append(f"- [[{name}]]（進捗ログ: [[{log.stem}]]）")
        lines += [f"  {s}" for s in summary[:4]]
    lines.append("")

    for sub, title, head in (("decisions", "判断記録", "決定"), ("knowledge", "技術知見", "要約"), ("mistakes", "失敗記録", "何が起きたか")):
        lines.append(f"## {title}")
        found = notes(vault, sub)
        if not found:
            lines.append("- なし")
        for p in found:
            text = ds.read(p)
            props = ds.parse_frontmatter(text)
            extra = ", ".join(x for x in (props.get("date", ""), ds.link_name(props.get("project", ""))) if x)
            summary = first_text(section(text, head))
            lines.append(f"- [[{p.stem}]]" + (f"（{extra}）" if extra else "") + (f": {summary}" if summary else ""))
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def build_rules(vault):
    lines = [INDEX_NOTE, "# 再発防止のルール", "",
             f"`{CONTEXT}/mistakes/` の失敗記録の「再発防止のルール」を集めたもの。作業のときは必ず守る。", ""]
    count = 0
    for p in notes(vault, "mistakes"):
        for line in section(ds.read(p), "再発防止のルール"):
            s = re.sub(r"^\s*[-*]\s+", "", line).strip()
            if s and not s.startswith("%%"):
                lines.append(f"- {s}（[[{p.stem}]]）")
                count += 1
    if not count:
        lines.append("- なし")
    return "\n".join(lines).rstrip() + "\n"


def cmd_index(vault):
    folder = vault / CONTEXT
    folder.mkdir(exist_ok=True)
    for name, text in (("_index.md", build_index(vault)), ("_rules.md", build_rules(vault))):
        path = folder / name
        old = path.read_text(encoding="utf-8") if path.exists() else None
        if old != text:
            ds.write(path, text)
        print(f"{'更新' if old != text else '変更なし'}: {path.relative_to(vault).as_posix()}")
    return 0


# ---------------------------------------------------------------- mark

def cmd_mark(vault, at):
    path = vault / STATE
    path.parent.mkdir(parents=True, exist_ok=True)
    ds.write(path, json.dumps({"last": at.isoformat(timespec="seconds")}, ensure_ascii=False) + "\n")
    print(f"記録: 前回の棚卸し = {at.isoformat(timespec='seconds')}")
    return 0


def main(argv=None):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--vault", type=Path, default=DEFAULT_VAULT)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("targets")
    p.add_argument("--date", type=dt.date.fromisoformat, default=dt.date.today())
    sub.add_parser("index")
    p = sub.add_parser("mark")
    p.add_argument("--at", type=dt.datetime.fromisoformat, default=None)
    args = ap.parse_args(argv)
    if args.cmd == "targets":
        return cmd_targets(args.vault, args.date)
    if args.cmd == "index":
        return cmd_index(args.vault)
    return cmd_mark(args.vault, args.at or dt.datetime.now())


if __name__ == "__main__":
    sys.exit(main())
