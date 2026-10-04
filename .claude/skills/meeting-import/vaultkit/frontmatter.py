"""ノートのfrontmatter（YAMLの部分集合）を読み書きする。

扱える値は、文字列と文字列のリストだけ。コメント・入れ子・複数行の値は扱わない。
扱えない行を見つけたら FrontmatterError を送出する。

- 空の値は、書くときは `key:`（値なし）、読むときは空文字列になる。
  空のリストも `key:` と書くため、読み戻すと空文字列になる。
- 読むとき、改行コードはLFに揃える。
- インライン形式のリスト（`[a, b]`）は、二重引用符の中のエスケープ（`\\"`）を扱えない。
  書くときはインライン形式を使わないため、通常は問題にならない。
"""
import re


class FrontmatterError(ValueError):
    """frontmatterを解釈できない、または書けないときに送出する。"""


_FENCE = "---"
_KEY_LINE = re.compile(r"^([^\s:#-][^:]*):(?:[ \t]+(.*))?$")
_LIST_ITEM = re.compile(r"^\s+-(?:\s+(.*))?$")
_NEEDS_QUOTE = re.compile(r"""^[\[\]{}&*!|>'"%@`#,?:-]|^\s|\s$|: |:$|\s#|^[-+]?[0-9]+(\.[0-9]+)?$|^[0-9]+:[0-9]+""")
_RESERVED = {"true", "false", "null", "yes", "no", "on", "off", "~"}
_PLAIN_NON_STRING = re.compile(r"^(?:true|false|null|yes|no|on|off|~)$|^[-+]?[0-9]+(\.[0-9]+)?$", re.IGNORECASE)


def split(text):
    """(frontmatterの行のリスト, 本文) を返す。frontmatterが無ければ ([], 本文) を返す。"""
    normalized = text.removeprefix("﻿").replace("\r\n", "\n")
    lines = normalized.split("\n")
    if lines[0].rstrip() != _FENCE:
        return None, normalized
    for i in range(1, len(lines)):
        if lines[i].rstrip() == _FENCE:
            return lines[1:i], "\n".join(lines[i + 1 :])
    raise FrontmatterError("frontmatterが閉じられていません")


def _unquote(text):
    if len(text) >= 2 and text[0] == '"' and text[-1] == '"':
        return re.sub(r'\\(["\\])', r"\1", text[1:-1])
    if len(text) >= 2 and text[0] == "'" and text[-1] == "'":
        return text[1:-1].replace("''", "'")
    return text


def _check_scalar(key, raw):
    """値の表記が、文字列として読み書きして変わらないことを確かめる。変わる表記は FrontmatterError にする。

    引用符なしの true/false/null や数値はYAMLでは文字列でなく、行末の ` #` はコメントになる。
    これらを文字列として読んで書き戻すと、触っていない項目の型が黙って変わってしまうため、
    読む時点で明示的に失敗させる（引用符で囲めば、文字列として読める）。
    """
    if raw[0] in "\"'":
        if len(raw) < 2 or raw[-1] != raw[0]:
            raise FrontmatterError(f"引用符が閉じていない、または引用符のあとに文字があります: {key}: {raw}")
        return
    if _PLAIN_NON_STRING.match(raw) or re.search(r"\s#", raw):
        raise FrontmatterError(f"文字列として読めない値です（引用符で囲んでください）: {key}: {raw}")


def _split_inline(inner):
    items, buf, quote = [], [], None
    for ch in inner:
        if quote:
            buf.append(ch)
            if ch == quote:
                quote = None
        elif ch in "\"'":
            quote = ch
            buf.append(ch)
        elif ch == ",":
            items.append("".join(buf).strip())
            buf = []
        else:
            buf.append(ch)
    items.append("".join(buf).strip())
    return [_unquote(item) for item in items if item != ""]


def parse(text):
    """(メタデータのdict, 本文) を返す。frontmatterが無ければ ({}, 本文) を返す。"""
    lines, body = split(text)
    if lines is None:
        return {}, body
    meta = {}
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            i += 1
            continue
        match = _KEY_LINE.match(line)
        if not match:
            raise FrontmatterError(f"解釈できない行です: {line!r}")
        key, raw = match.group(1).strip(), (match.group(2) or "").strip()
        if key in meta:
            raise FrontmatterError(f"キーが重複しています: {key}")
        i += 1
        if raw == "":
            items = []
            while i < len(lines) and _LIST_ITEM.match(lines[i]):
                item = (_LIST_ITEM.match(lines[i]).group(1) or "").strip()
                if item:
                    _check_scalar(key, item)
                items.append(_unquote(item))
                i += 1
            meta[key] = items if items else ""
        elif raw.startswith("[") and raw.endswith("]") and not raw.startswith("[["):
            meta[key] = _split_inline(raw[1:-1])
        else:
            _check_scalar(key, raw)
            meta[key] = _unquote(raw)
    return meta, body


def _format_scalar(value):
    if not isinstance(value, str):
        raise FrontmatterError(f"文字列以外の値は書けません: {value!r}")
    if "\n" in value:
        raise FrontmatterError("改行を含む値は書けません")
    if value == "":
        return ""
    if value.lower() in _RESERVED or _NEEDS_QUOTE.search(value):
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return value


def dump(meta, body):
    """メタデータと本文から、ノートのテキストを組み立てる。"""
    lines = [_FENCE]
    for key, value in meta.items():
        if isinstance(value, list):
            lines.append(f"{key}:")
            lines.extend(f"  - {_format_scalar(item)}".rstrip() for item in value)
        else:
            text = _format_scalar(value)
            lines.append(f"{key}: {text}" if text else f"{key}:")
    lines.append(_FENCE)
    return "\n".join(lines) + "\n" + body


def update(text, changes):
    """`changes`をメタデータへ反映したノートのテキストを返す。新しいキーは末尾に足す。"""
    meta, body = parse(text)
    meta.update(changes)
    return dump(meta, body)
