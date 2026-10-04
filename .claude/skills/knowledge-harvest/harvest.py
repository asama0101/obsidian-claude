"""knowledge-harvest スキル用のスクリプト（標準ライブラリだけで動く）。

サブコマンド:
  targets [--date YYYY-MM-DD]
      棚卸しの対象を JSON で出力する。
      - memo: 今日のデイリーの「今日のメモ」の項目のうち、行末に「 → [[」の印がないもの
      - tasks: 前回の棚卸し以降に更新されたタスクのノート（20_tasks・00_inbox の直下）と、
        その「経緯」の節の、印のない行
      - since: 判定に使った日時（前回の棚卸しの日時。記録がなければ今日の 0 時）
  index
      80_context/_index.md（索引）と 80_context/_rules.md（再発防止のルール）を、
      80_context の 技術知見.md・判断記録.md・失敗記録.md・進捗ログ.md から作り直す。
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

# 種類ごとのファイル名と、索引に出す項目
KINDS = (("判断記録", "決定"), ("技術知見", "要約"), ("失敗記録", "何が起きたか"))
PROGRESS = "進捗ログ"


def context_text(vault, name):
    path = vault / CONTEXT / f"{name}.md"
    return ds.read(path) if path.exists() else ""


def blocks(lines, level):
    """見出しのレベル level の節を (見出し, 本文の行) のリストで返す。
    本文は、同じかそれより上のレベルの見出しの前まで。最初の見出しより前の行は捨てる。"""
    out, cur = [], None
    for line in lines:
        m = re.match(r"^(#{1,6})\s+(.*?)\s*$", line)
        if m and len(m.group(1)) <= level:
            cur = None
            if len(m.group(1)) == level:
                cur = (m.group(2), [])
                out.append(cur)
            continue
        if cur is not None:
            cur[1].append(line)
    return out


def fields(lines):
    """1件の本文の「- 項目名: 内容」を {項目名: [行]} で返す。
    内容は、同じ行の残りと、その下の字下げした行（箇条書きの記号は外す）。"""
    out, key = {}, None
    for line in lines:
        m = re.match(r"^[-*]\s+([^:：]+?)[:：]\s*(.*)$", line)
        if m:
            key = m.group(1).strip()
            out.setdefault(key, [])
            if m.group(2).strip():
                out[key].append(m.group(2).strip())
        elif key and line[:1] in (" ", "\t") and line.strip():
            s = re.sub(r"^\s*[-*]\s+", "", line).strip()
            if s and not s.startswith("%%"):
                out[key].append(s)
        elif line.strip():
            key = None
    return out


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
    # 進捗ログ.md の「## プロジェクト名」の節の「### 現在の要約」
    logs = dict(blocks(context_text(vault, PROGRESS).splitlines(), 2))
    projects = active_projects(vault)
    if not projects:
        lines.append("- なし")
    for name in projects:
        if name not in logs:
            lines.append(f"- [[{name}]]: 進捗ログなし")
            continue
        summary = dict(blocks(logs[name], 3)).get("現在の要約", [])
        summary = [s.strip() for s in summary if s.strip() and not s.strip().startswith("%%")]
        lines.append(f"- [[{name}]]（[[{PROGRESS}#{name}]]）")
        lines += [f"  {s}" for s in summary[:4]]
    lines.append("")

    for title, head in KINDS:
        lines.append(f"## {title}")
        found = blocks(context_text(vault, title).splitlines(), 2)
        if not found:
            lines.append("- なし")
        for name, body in found:
            f = fields(body)
            extra = ", ".join(x for x in (first_text(f.get("日付", [])), ds.link_name(first_text(f.get("プロジェクト", [])))) if x)
            summary = first_text(f.get(head, []))
            lines.append(f"- [[{title}#{name}]]" + (f"（{extra}）" if extra else "") + (f": {summary}" if summary else ""))
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def build_rules(vault):
    lines = [INDEX_NOTE, "# 再発防止のルール", "",
             f"`{CONTEXT}/失敗記録.md` の「再発防止のルール」を集めたもの。作業のときは必ず守る。", ""]
    count = 0
    for name, body in blocks(context_text(vault, "失敗記録").splitlines(), 2):
        for s in fields(body).get("再発防止のルール", []):
            lines.append(f"- {s}（[[失敗記録#{name}]]）")
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
