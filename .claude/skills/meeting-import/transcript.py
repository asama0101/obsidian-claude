#!/usr/bin/env python3
"""会議の文字起こしのファイル（Teams の .docx / .vtt、.txt / .md）を、プレーンテキストにして標準出力に出す。

  transcript.py <ファイル>

- .vtt: 時刻の行と番号の行を除き、`<v 話者>本文</v>` を `話者: 本文` にする。同じ話者の連続した発言はまとめる。
- .docx: word/document.xml の段落を1行ずつ取り出す（標準ライブラリだけで読む）。
- .txt / .md: そのまま出す。
読めないときは、理由を1行出して終了コード1。
"""
import html
import re
import sys
import zipfile
from pathlib import Path

_TIME = re.compile(r"^\d{1,2}:\d{2}(:\d{2})?[.,]\d{3}\s+-->\s+")
_VOICE = re.compile(r"<v\s+([^>]+)>(.*?)(?:</v>|$)", re.S)
_TAG = re.compile(r"<[^>]+>")


def from_vtt(text):
    out = []
    last_speaker = None
    for block in re.split(r"\r?\n\s*\r?\n", text):
        lines = [l for l in block.strip().splitlines() if l.strip()]
        if not lines or lines[0].startswith("WEBVTT") or lines[0].startswith("NOTE"):
            continue
        body = [l for l in lines if not _TIME.match(l) and not re.fullmatch(r"[\w-]+(/\d+-\d+)?", l.strip())]
        joined = " ".join(body)
        m = _VOICE.search(joined)
        speaker, words = (m.group(1).strip(), m.group(2)) if m else ("", joined)
        words = html.unescape(_TAG.sub("", words)).strip()
        if not words:
            continue
        if speaker and speaker == last_speaker and out:
            out[-1] += " " + words
        else:
            out.append(f"{speaker}: {words}" if speaker else words)
        last_speaker = speaker
    return "\n".join(out)


def from_docx(path):
    with zipfile.ZipFile(path) as z:
        xml = z.read("word/document.xml").decode("utf-8")
    paras = []
    for p in re.findall(r"<w:p[ >].*?</w:p>", xml, re.S):
        p = re.sub(r"<w:tab/>", "\t", p)
        p = re.sub(r"<w:br/>", "\n", p)
        text = html.unescape("".join(re.findall(r"<w:t[^>]*>(.*?)</w:t>", p, re.S)))
        if text.strip():
            paras.append(text.strip())
    return "\n".join(paras)


def main(argv=None):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    args = argv if argv is not None else sys.argv[1:]
    if len(args) != 1:
        print("使い方: transcript.py <ファイル>")
        return 1
    path = Path(args[0])
    try:
        suffix = path.suffix.lower()
        if suffix == ".vtt":
            print(from_vtt(path.read_text(encoding="utf-8-sig")))
        elif suffix == ".docx":
            print(from_docx(path))
        elif suffix in (".txt", ".md"):
            print(path.read_text(encoding="utf-8-sig"))
        else:
            print(f"対応していない形式です: {path.suffix}（.vtt / .docx / .txt / .md）")
            return 1
    except (OSError, UnicodeDecodeError, zipfile.BadZipFile, KeyError) as error:
        print(f"読めません: {path.name}（{type(error).__name__}: {error}）")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
