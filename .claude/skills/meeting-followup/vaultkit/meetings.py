"""議事録ノートの「アクションアイテム」の節の解析と、処理済みの印付け。

- 書式: `- [ ] 内容 @担当 期限:YYYY-MM-DD`（担当と期限は省略可。チェックボックスなしの `- 内容` も可）。
- 処理済みの印: 行末の `→ [[タスク名]]`。本文が1つのリンクだけの行（旧 Vault の印）も処理済みとみなす。
- 項目は、行番号でなく文言で指定する（確認のあいだに Obsidian で行が増減しても、正しい行を指せるように）。
"""
import re

ACTIONS_HEADING = "## アクションアイテム"
# `- [ ] 内容`・`- [x] 内容`・`- 内容`（先頭に空白があってもよい）。
_ITEM = re.compile(r"^\s*-\s+(?:\[([ xX])\]\s*)?(.*?)\s*$")
_RESOLVED = re.compile(r"(?:^|\s)→\s*\[\[[^\[\]]+\]\]$|^\[\[[^\[\]]+\]\]$")
_ASSIGNEE = re.compile(r"(?:^|\s)@(\S+)")
_DUE = re.compile(r"(?:^|\s)期限:(\d{4}-\d{2}-\d{2})(?=\s|$)")
_LINK_NAME = re.compile(r"^\[\[([^\]|#]+)")


def project_name(value):
    """`[[プロジェクト名]]`（別名・見出し付きも可）から、プロジェクト名を取り出す。リンクでなければ、そのまま返す。"""
    text = value.strip()
    match = _LINK_NAME.match(text)
    return match.group(1).strip() if match else text


def section_bounds(lines, heading):
    """`heading` の節の本文の範囲 (開始行, 終了行) を返す。終了行は含まない。節が無ければ None。"""
    for start, line in enumerate(lines):
        if line.strip() == heading:
            end = start + 1
            while end < len(lines) and not lines[end].startswith("## "):
                end += 1
            return start + 1, end
    return None


def _unresolved(lines):
    """[(行の位置, 本文)] を返す。完了済み・空・処理済みの印がある行は除く。"""
    bounds = section_bounds(lines, ACTIONS_HEADING)
    if bounds is None:
        return []
    found = []
    for index in range(*bounds):
        match = _ITEM.match(lines[index])
        if not match:
            continue
        mark, body = match.groups()
        if mark and mark in "xX":
            continue
        if body and not _RESOLVED.search(body):
            found.append((index, body))
    return found


def unresolved_actions(text):
    """未処理のアクションアイテムの本文を、出てくる順に返す。"""
    return [body for _, body in _unresolved(text.split("\n"))]


def parse_item(body):
    """本文を {"text", "content", "assignee", "due"} に分ける。`text` は本文そのもの（`link` の指定に使う）。"""
    assignee = _ASSIGNEE.search(body)
    due = _DUE.search(body)
    content = _DUE.sub(" ", _ASSIGNEE.sub(" ", body))
    return {
        "text": body,
        "content": " ".join(content.split()),
        "assignee": assignee.group(1) if assignee else "",
        "due": due.group(1) if due else "",
    }


def link_action(text, item, task_name):
    """本文が `item` の、最初の未処理の項目の行末に ` → [[task_name]]` を足したテキストを返す。無ければ ValueError。"""
    lines = text.split("\n")
    for index, body in _unresolved(lines):
        if body == item.strip():
            line = lines[index]
            cr = "\r" if line.endswith("\r") else ""
            lines[index] = f"{line.rstrip()} → [[{task_name}]]{cr}"
            return "\n".join(lines)
    raise ValueError(f"{ACTIONS_HEADING} に、未処理の項目「{item}」がありません")
