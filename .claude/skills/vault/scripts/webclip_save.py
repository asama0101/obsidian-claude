"""WebページのクリップをVaultのノートとして保存するスクリプト。

Claude側でWebFetch+要約して作成したJSON(title/summary/key_points/full_text)を
受け取り、summary/key_pointsの各項目に紐づく画像および、full_text中に
![alt](URL)形式でインライン埋め込まれた画像をまとめてダウンロードして
80_Attachments/に保存し、WebClip_Template.mdベースのノートを
30_Resources/WebClips/に作成する。標準ライブラリのみに依存する。
"""

from __future__ import annotations

import argparse
import datetime
import json
import mimetypes
import re
import sys
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

import vault_lib

# 画像として扱う既知の拡張子(URL末尾からの判定に使う)
_KNOWN_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".svg"}

# full_text中の標準Markdown画像記法 ![alt](URL) を検出する。
# altは`]`を含まない任意文字列、URLは`)`が来るまでの文字列(ネストした括弧は非対応)。
_MARKDOWN_IMAGE_RE = re.compile(r"!\[[^\]]*\]\(([^)]*)\)")

# User-Agent未指定だとBot判定で403を返す画像CDNがあるため、ブラウザ相当のUAを送る。
_DOWNLOAD_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


def _guess_extension(url: str, content_type: str | None) -> str:
    """URLの末尾かContent-Typeヘッダから画像の拡張子を判定する。不明なら.jpgとする。"""
    path = urlparse(url).path
    suffix = Path(path).suffix.lower()
    if suffix in _KNOWN_IMAGE_EXTENSIONS:
        return suffix

    if content_type:
        guessed = mimetypes.guess_extension(content_type.split(";")[0].strip())
        if guessed:
            # mimetypesがjpegに対し非標準な.jpeを返す場合があるため正規化する
            return ".jpg" if guessed == ".jpe" else guessed

    return ".jpg"


def _download_image(url: str, timeout: float = 10.0) -> tuple[bytes, str | None]:
    """URLから画像データをダウンロードし、(バイナリデータ, content-type)を返す。"""
    request = urllib.request.Request(
        url, headers={"User-Agent": _DOWNLOAD_USER_AGENT}
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        data = response.read()
        content_type = response.headers.get_content_type()
    return data, content_type


def download_images(
    image_urls: list[str], title: str, attachments_dir: Path
) -> tuple[dict[str, str], list[str]]:
    """画像URL群(重複無し)をダウンロードしattachments_dirに保存する。

    個々のダウンロード失敗は例外を捕捉してスキップし、処理全体は継続する。
    戻り値: (URL -> 保存したファイル名 のマップ, 失敗したURLのリスト)
    """
    url_to_filename: dict[str, str] = {}
    images_failed: list[str] = []
    base_name = vault_lib.sanitize_filename(title) or "webclip"

    if image_urls:
        attachments_dir.mkdir(parents=True, exist_ok=True)

    for i, url in enumerate(image_urls, start=1):
        try:
            data, content_type = _download_image(url)
            ext = _guess_extension(url, content_type)
            filename = f"{base_name}-{i}{ext}"
            dest = vault_lib.unique_path(attachments_dir, filename)
            dest.write_bytes(data)
            url_to_filename[url] = dest.name
        except Exception:
            images_failed.append(url)

    return url_to_filename, images_failed


def _normalize_items(raw_items: list) -> list[dict]:
    """summary/key_pointsの各項目を{"text": ..., "image_url": ...}に正規化する。

    image_urlキーが無い、または値が空文字列/nullなら空文字列として扱う。
    """
    normalized: list[dict] = []
    for item in raw_items:
        text = item.get("text", "")
        image_url = item.get("image_url") or ""
        normalized.append({"text": text, "image_url": image_url})
    return normalized


def _collect_unique_urls(
    *item_lists: list[dict], full_text_urls: list[str] | None = None
) -> list[str]:
    """複数の正規化済み項目リストとfull_text由来のURL群から、重複無く出現順で集める。"""
    seen: list[str] = []
    for items in item_lists:
        for item in items:
            url = item["image_url"]
            if url and url not in seen:
                seen.append(url)
    for url in full_text_urls or []:
        if url and url not in seen:
            seen.append(url)
    return seen


def _extract_full_text_image_urls(full_text: str) -> list[str]:
    """full_text中の![alt](URL)記法から画像URLを出現順(重複含む)で抽出する。"""
    return _MARKDOWN_IMAGE_RE.findall(full_text)


def _replace_full_text_images(full_text: str, url_to_filename: dict[str, str]) -> str:
    """full_text中の![alt](URL)記法を、ダウンロード済みならローカル埋め込みに置換する。

    ダウンロードに失敗した(url_to_filenameに存在しない)URLの箇所は記法ごと取り除く。
    """

    def _replace(match: re.Match) -> str:
        url = match.group(1)
        filename = url_to_filename.get(url)
        if filename:
            return f"![[80_Attachments/{filename}]]"
        return ""

    return _MARKDOWN_IMAGE_RE.sub(_replace, full_text)


def _resolve_item_filenames(
    normalized_items: list[dict], url_to_filename: dict[str, str]
) -> list[dict]:
    """正規化済み項目にダウンロード結果のファイル名を紐づける。

    ダウンロードに失敗した(url_to_filenameに存在しない)項目のfilenameはNoneになる。
    """
    resolved = []
    for item in normalized_items:
        url = item["image_url"]
        filename = url_to_filename.get(url) if url else None
        resolved.append({"text": item["text"], "filename": filename})
    return resolved


def _bullet_list_with_images(items: list[dict]) -> str:
    """項目リストをMarkdownの箇条書きに変換し、画像があれば直下に埋め込む。

    空なら空欄行のままにする。
    """
    if not items:
        return "- "
    lines: list[str] = []
    for item in items:
        lines.append(f"- {item['text']}")
        filename = item.get("filename")
        if filename:
            lines.append(f"  ![[80_Attachments/{filename}]]")
    return "\n".join(lines)


def _blockquote(text: str) -> str:
    """複数行テキストをMarkdownの引用形式(各行に"> "を付与)に変換する。"""
    lines = text.splitlines() or [""]
    return "\n".join(f"> {line}" for line in lines)


def build_note_text(
    *,
    template_text: str,
    title: str,
    dt: datetime.datetime,
    url: str,
    summary_items: list[dict],
    key_points_items: list[dict],
    full_text: str,
    tag: str,
) -> str:
    """テンプレートに内容を差し込み、完成したノート全文を返す。

    summary_items/key_points_itemsは{"text": str, "filename": str | None}のリスト。
    full_textは画像記法(![alt](URL))が既にローカル埋め込み(![[80_Attachments/...]])
    へ置換済みの状態で渡される想定(呼び出し側で_replace_full_text_images済み)。
    tagは"<category>/<topic>"形式のカテゴリタグで、frontmatterのtags:リストに追加する。
    """
    text = vault_lib.fill_template(template_text, title=title, dt=dt)
    fm, body = vault_lib.split_frontmatter(text)

    fm = vault_lib.set_fm_value(fm, "url", url)
    fm = vault_lib.add_tag(fm, tag)

    body = body.replace(
        "## \U0001f4cc 概要・要約\n- ",
        "## \U0001f4cc 概要・要約\n" + _bullet_list_with_images(summary_items),
        1,
    )
    body = body.replace(
        "## \U0001f4a1 キーポイント\n- ",
        "## \U0001f4a1 キーポイント\n" + _bullet_list_with_images(key_points_items),
        1,
    )
    body = body.replace(
        "## \U0001f4c4 クリップ本文\n>",
        "## \U0001f4c4 クリップ本文\n" + _blockquote(full_text),
        1,
    )

    return f"---\n{fm}\n---\n{body}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="WebページをクリップしてVaultにノート化する")
    parser.add_argument("--url", required=True)
    parser.add_argument("--content-json", required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--vault-root", default=None)
    args = parser.parse_args(argv)

    vault_root = Path(args.vault_root) if args.vault_root else vault_lib.VAULT_ROOT
    content = json.loads(Path(args.content_json).read_text(encoding="utf-8"))

    title = content.get("title") or "Untitled"
    normalized_summary = _normalize_items(content.get("summary", []))
    normalized_key_points = _normalize_items(content.get("key_points", []))
    full_text = content.get("full_text", "")
    full_text_image_urls = _extract_full_text_image_urls(full_text)

    unique_urls = _collect_unique_urls(
        normalized_summary, normalized_key_points, full_text_urls=full_text_image_urls
    )

    attachments_dir = vault_root / "80_Attachments"
    url_to_filename, images_failed = download_images(unique_urls, title, attachments_dir)
    images_saved = list(url_to_filename.values())

    summary_items = _resolve_item_filenames(normalized_summary, url_to_filename)
    key_points_items = _resolve_item_filenames(normalized_key_points, url_to_filename)
    full_text = _replace_full_text_images(full_text, url_to_filename)

    template_path = vault_root / "70_Templates" / "WebClip_Template.md"
    template_text = template_path.read_text(encoding="utf-8")

    note_text = build_note_text(
        template_text=template_text,
        title=title,
        dt=datetime.datetime.now(),
        url=args.url,
        summary_items=summary_items,
        key_points_items=key_points_items,
        full_text=full_text,
        tag=args.tag,
    )

    dest_dir = vault_root / "30_Resources" / "WebClips"
    dest_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{vault_lib.sanitize_filename(title) or 'webclip'}.md"
    note_path = vault_lib.unique_path(dest_dir, filename)
    note_path.write_text(note_text, encoding="utf-8")

    result = {
        "note_path": str(note_path),
        "images_saved": images_saved,
        "images_failed": images_failed,
    }
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
