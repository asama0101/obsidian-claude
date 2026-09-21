"""knowhow スキルのノート保存スクリプト。

Claude 側が「概要→手順→注意点」に構造化した JSON を受け取り、
Knowhow_Template.md を展開してノートとして保存する。
標準ライブラリのみに依存する。
"""

from __future__ import annotations

import argparse
import datetime
import json
from pathlib import Path

import vault_lib

# セクション種別ごとの見出しテキスト(テンプレート内の表記と完全一致させる)
_HEADING_OVERVIEW = "## 💡 概要・結論"
_HEADING_STEPS = "## 🛠 手順・実行方法 / 解決策"
_HEADING_PITFALLS = "## ⚠️ 注意点・ハマりポイント"
_HEADING_REFERENCES = "## 🔗 参照・関連リンク"
_HEADING_ORIGINAL_TEXT = "## 📄 ノウハウ本文"


def _to_lines(value) -> list[str]:
    """リストならそのまま、文字列なら改行分割して空行を除いたリストを返す。"""
    if isinstance(value, list):
        return [str(item) for item in value]
    return [line for line in str(value).splitlines() if line.strip()]


def render_bullets(items) -> str:
    """箇条書き(`- `形式)のテキストを返す。"""
    return "\n".join(f"- {item}" for item in _to_lines(items))


def render_numbered(items) -> str:
    """番号付きリスト(`1. `形式)のテキストを返す。"""
    return "\n".join(f"{i}. {item}" for i, item in enumerate(_to_lines(items), start=1))


def render_blockquote(text: str) -> str:
    """各行を`> `で引用形式にする(内容は加工しない)。"""
    return "\n".join(f"> {line}" for line in str(text).split("\n"))


def _add_tag(fm_text: str, tag: str) -> str:
    """frontmatter の tags: リストへ新しいタグ行を追加する。"""
    lines = fm_text.split("\n") if fm_text else []

    for i, line in enumerate(lines):
        if line.startswith("tags:"):
            j = i + 1
            while j < len(lines) and lines[j].startswith("  - "):
                j += 1
            lines.insert(j, f"  - {tag}")
            return "\n".join(lines)

    # tags: キーが無ければ新規に追加する
    lines.append("tags:")
    lines.append(f"  - {tag}")
    return "\n".join(lines)


def _replace_section(body: str, heading: str, new_content: str) -> str:
    """見出し行の直後にあるプレースホルダ部分を new_content に置換する。

    次の見出し(`## `始まり)または区切り線(`---`)の手前までを置換対象とする。
    置換後は元のテンプレートと同じく見出し・区切りとの間に空行を1行残す。
    """
    lines = body.split("\n")

    start = None
    for i, line in enumerate(lines):
        if line == heading:
            start = i
            break
    if start is None:
        raise ValueError(f"セクション見出しが見つかりません: {heading}")

    end = len(lines)
    for j in range(start + 1, len(lines)):
        if lines[j].startswith("## ") or lines[j] == "---":
            end = j
            break

    new_lines = lines[: start + 1] + new_content.split("\n") + [""] + lines[end:]
    return "\n".join(new_lines)


def build_note(content: dict, template_text: str, dt: datetime.datetime) -> str:
    """content の内容をテンプレートへ差し込み、ノート全文を返す。"""
    title = content["title"]
    category = content["category"]

    filled = vault_lib.fill_template(template_text, title=title, dt=dt)
    fm_text, body_text = vault_lib.split_frontmatter(filled)

    fm_text = vault_lib.set_fm_value(fm_text, "category", category)
    fm_text = _add_tag(fm_text, f"knowledge/{category}")

    body_text = _replace_section(
        body_text, _HEADING_OVERVIEW, render_bullets(content["overview"])
    )
    body_text = _replace_section(
        body_text, _HEADING_STEPS, render_numbered(content["steps"])
    )
    body_text = _replace_section(
        body_text, _HEADING_PITFALLS, render_bullets(content["pitfalls"])
    )
    body_text = _replace_section(
        body_text, _HEADING_REFERENCES, render_bullets(content["references"])
    )
    body_text = _replace_section(
        body_text,
        _HEADING_ORIGINAL_TEXT,
        render_blockquote(content["original_text"]),
    )

    return f"---\n{fm_text}\n---\n{body_text}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--content-json", required=True)
    parser.add_argument("--vault-root", default=None)
    args = parser.parse_args(argv)

    vault_root = Path(args.vault_root) if args.vault_root else vault_lib.VAULT_ROOT
    content = json.loads(Path(args.content_json).read_text(encoding="utf-8"))

    template_path = vault_root / "70_Templates" / "Knowhow_Template.md"
    template_text = template_path.read_text(encoding="utf-8")

    dt = datetime.datetime.now()
    note_text = build_note(content, template_text, dt)

    out_dir = vault_root / "20_Areas" / "Knowledge"
    out_dir.mkdir(parents=True, exist_ok=True)
    filename = vault_lib.sanitize_filename(content["title"]) + ".md"
    note_path = vault_lib.unique_path(out_dir, filename)
    note_path.write_text(note_text, encoding="utf-8")

    print(json.dumps({"note_path": str(note_path)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
