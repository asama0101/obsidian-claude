"""WebページのクリップをVaultのノートとして保存するスクリプト。

Claude側でWebFetch+要約して作成したJSON(title/summary/key_points/excerpt/
image_urls)を受け取り、画像をダウンロードして80_Attachments/に保存し、
WebClip_Template.mdベースのノートを30_Resources/WebClips/に作成する。
標準ライブラリのみに依存する。
"""

from __future__ import annotations

import argparse
import datetime
import json
import mimetypes
import sys
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

import vault_lib

# 画像として扱う既知の拡張子(URL末尾からの判定に使う)
_KNOWN_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".svg"}


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
    with urllib.request.urlopen(url, timeout=timeout) as response:
        data = response.read()
        content_type = response.headers.get_content_type()
    return data, content_type


def download_images(image_urls: list[str], title: str, attachments_dir: Path) -> tuple[list[str], list[str]]:
    """画像URL群をダウンロードしattachments_dirに保存する。

    個々のダウンロード失敗は例外を捕捉してスキップし、処理全体は継続する。
    戻り値: (保存したファイル名のリスト, 失敗したURLのリスト)
    """
    images_saved: list[str] = []
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
            images_saved.append(dest.name)
        except Exception:
            images_failed.append(url)

    return images_saved, images_failed


def _bullet_list(items: list[str]) -> str:
    """箇条書き項目のリストをMarkdownの箇条書きに変換する。空なら空欄行のままにする。"""
    if not items:
        return "- "
    return "\n".join(f"- {item}" for item in items)


def _blockquote(text: str) -> str:
    """複数行テキストをMarkdownの引用形式(各行に"> "を付与)に変換する。"""
    lines = text.splitlines() or [""]
    return "\n".join(f"> {line}" for line in lines)


def _set_fm_raw(fm_text: str, key: str, raw_value: str) -> str:
    """frontmatterのkey行を、クォートを追加せずraw_valueで置換または追加する。

    vault_lib.set_fm_valueと異なり、既にYAML表現済みの値(例: `"[[Project]]"`)を
    そのまま書き込みたい場合に使う。
    """
    prefix = f"{key}:"
    new_line = f"{key}: {raw_value}"
    lines = fm_text.split("\n") if fm_text else []

    for i, line in enumerate(lines):
        if line.startswith(prefix):
            lines[i] = new_line
            return "\n".join(lines)

    lines.append(new_line)
    return "\n".join(lines)


def build_note_text(
    *,
    template_text: str,
    title: str,
    dt: datetime.datetime,
    url: str,
    project_match: str | None,
    summary: list[str],
    key_points: list[str],
    excerpt: str,
    images_saved: list[str],
) -> str:
    """テンプレートに内容を差し込み、完成したノート全文を返す。"""
    text = vault_lib.fill_template(template_text, title=title, dt=dt)
    fm, body = vault_lib.split_frontmatter(text)

    fm = vault_lib.set_fm_value(fm, "url", url)
    if project_match:
        fm = _set_fm_raw(fm, "project", project_match)

    if images_saved:
        images_md = "\n".join(f"![[80_Attachments/{name}]]" for name in images_saved)
        body = body.replace(f"# {title}\n\n", f"# {title}\n\n{images_md}\n\n", 1)

    body = body.replace("## \U0001f4cc 概要・要約\n- ", "## \U0001f4cc 概要・要約\n" + _bullet_list(summary), 1)
    body = body.replace("## \U0001f4a1 キーポイント\n- ", "## \U0001f4a1 キーポイント\n" + _bullet_list(key_points), 1)
    body = body.replace("## \U0001f4c4 クリップ本文\n>", "## \U0001f4c4 クリップ本文\n" + _blockquote(excerpt), 1)

    return f"---\n{fm}\n---\n{body}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="WebページをクリップしてVaultにノート化する")
    parser.add_argument("--url", required=True)
    parser.add_argument("--content-json", required=True)
    parser.add_argument("--project-hint", default=None)
    parser.add_argument("--vault-root", default=None)
    args = parser.parse_args(argv)

    vault_root = Path(args.vault_root) if args.vault_root else vault_lib.VAULT_ROOT
    content = json.loads(Path(args.content_json).read_text(encoding="utf-8"))

    title = content.get("title") or "Untitled"
    summary = content.get("summary", [])
    key_points = content.get("key_points", [])
    excerpt = content.get("excerpt", "")
    image_urls = content.get("image_urls", [])

    attachments_dir = vault_root / "80_Attachments"
    images_saved, images_failed = download_images(image_urls, title, attachments_dir)

    project_match = None
    if args.project_hint:
        projects_dir = vault_root / "10_Projects"
        project_match = vault_lib.fuzzy_project_match(args.project_hint, projects_dir)

    template_path = vault_root / "70_Templates" / "WebClip_Template.md"
    template_text = template_path.read_text(encoding="utf-8")

    note_text = build_note_text(
        template_text=template_text,
        title=title,
        dt=datetime.datetime.now(),
        url=args.url,
        project_match=project_match,
        summary=summary,
        key_points=key_points,
        excerpt=excerpt,
        images_saved=images_saved,
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
