"""grilling-html スキル用のスクリプト。

サブコマンド:
  init   --theme T [--parent P]  セッションフォルダを作り、パスを1行で出力する
                              （既定の置き場所は 00_inbox。後で daily-end がプロジェクトへ振り分ける。
                               --parent で別の場所に作れる。例: personal-setup はスクラッチパッドに作る）
  render --session-dir D --round N [--final] --input J.json
                              質問 JSON から round-N.html（または final.html）を生成し、パスを出力する
  index  --session-dir D      フォルダ内のファイルを並べた index.md を（再）生成する

質問 JSON:
  {"title": "...", "intro": "...", "questions": [
     {"id": "Q1", "title": "...", "body": "...", "multi": false,
      "options": [{"key": "A", "label": "...", "desc": "..."}],
      "recommended": ["A"], "reason": "..."}]}
final の JSON:
  {"title": "...", "intro": "...", "summary": "（SPEC 案の本文）"}
"""
import argparse
import datetime
import json
import re
import sys
from pathlib import Path

DEFAULT_VAULT = Path(__file__).resolve().parents[3]
TEMPLATE = Path(__file__).with_name("grilling_html_template.html")
INVALID = re.compile(r'[\\/:*?"<>|\s]+')


def session_root(vault: Path) -> Path:
    return vault / "00_inbox"


def cmd_init(args) -> int:
    vault = Path(args.vault)
    stamp = datetime.datetime.now().strftime("%Y-%m-%d_%H%M")
    theme = INVALID.sub("-", args.theme).strip("-") or "grilling"
    parent = Path(args.parent) if args.parent else session_root(vault)
    d = parent / f"{stamp}_grilling_{theme}"
    d.mkdir(parents=True, exist_ok=True)
    print(d)
    return 0


def embed(data: dict) -> str:
    # <script> 内に埋め込むため、終了タグと行区切り文字を無害化する
    text = json.dumps(data, ensure_ascii=False)
    return text.replace("</", "<\\/").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")


def cmd_render(args) -> int:
    d = Path(args.session_dir)
    d.mkdir(parents=True, exist_ok=True)
    payload = json.loads(Path(args.input).read_text(encoding="utf-8"))
    payload["session"] = d.name
    payload["round"] = args.round
    payload["mode"] = "final" if args.final else "round"
    if not payload.get("title"):
        payload["title"] = "最終確認" if args.final else f"ラウンド {args.round}"
    html = TEMPLATE.read_text(encoding="utf-8").replace("__DATA__", embed(payload))
    out = d / ("final.html" if args.final else f"round-{args.round}.html")
    out.write_text(html, encoding="utf-8")
    print(out)
    return 0


def cmd_index(args) -> int:
    d = Path(args.session_dir)
    rounds = sorted(d.glob("round-*.answers.md"), key=lambda p: int(re.search(r"round-(\d+)", p.name).group(1)))
    lines = [
        "---",
        "type: doc",
        "status: draft",
        f"created: {datetime.date.today().isoformat()}",
        "tags: []",
        "---",
        f"# {d.name}",
        "",
        "## ラウンド",
    ]
    for p in rounds:
        lines.append(f"- [[{p.stem}]]")
    if not rounds:
        lines.append("- （まだありません）")
    lines.append("")
    lines.append("## 最終")
    for name in ("final.answers", "final-summary"):
        if (d / f"{name}.md").exists():
            lines.append(f"- [[{name}]]")
    (d / "index.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(d / "index.md")
    return 0


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap =argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--vault", default=str(DEFAULT_VAULT))
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("init")
    p.add_argument("--theme", required=True)
    p.add_argument("--parent", help="セッションフォルダを作る親フォルダ（既定: <Vault>/00_inbox）")
    p.set_defaults(fn=cmd_init)

    p = sub.add_parser("render")
    p.add_argument("--session-dir", required=True)
    p.add_argument("--round", type=int, required=True)
    p.add_argument("--final", action="store_true")
    p.add_argument("--input", required=True)
    p.set_defaults(fn=cmd_render)

    p = sub.add_parser("index")
    p.add_argument("--session-dir", required=True)
    p.set_defaults(fn=cmd_index)

    args = ap.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
