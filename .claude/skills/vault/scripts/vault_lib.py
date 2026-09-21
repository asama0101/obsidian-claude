"""Obsidian Vault用 Claude Codeプラグイン「vault」の共通ライブラリ。

frontmatter操作・テンプレート展開・マーカーブロック操作・git操作・
プロジェクトあいまい一致判定など、複数のスクリプトから共有される
処理をまとめる。標準ライブラリのみに依存する。
"""

from __future__ import annotations

import datetime
import re
import subprocess
from pathlib import Path

# .claude/skills/vault/scripts/ の3階層上が Vault ルート
VAULT_ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent

# Windows で使用できないファイル名文字
_FORBIDDEN_FILENAME_CHARS = re.compile(r'[\\/:*?"<>|]')

# 曜日インデックス(datetime.weekday(): 0=月曜)から日本語1文字への対応
_WEEKDAY_LABELS = ["月", "火", "水", "木", "金", "土", "日"]


def run_git(*args: str, cwd, check: bool = True) -> str:
    """`git` コマンドを実行し、stdout(末尾改行を除いたもの)を返す。

    subprocessのtext=Trueはプラットフォームのデフォルトエンコーディング
    （Windowsではcp932等）でstdoutをデコードしようとし、日本語ファイル名
    （Shift-JISで表現できない文字を含む場合）でUnicodeDecodeErrorを起こし
    stdoutがNoneになることがあるため、明示的にUTF-8を指定する。

    check=True の場合、非ゼロ終了時は CalledProcessError を送出する。
    """
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if check and result.returncode != 0:
        raise subprocess.CalledProcessError(
            result.returncode, ["git", *args], output=result.stdout, stderr=result.stderr
        )
    return result.stdout.rstrip("\n")


def sanitize_filename(title: str) -> str:
    """Windows禁止文字を除去し、前後空白をtrimし、80文字に切り詰める。"""
    sanitized = _FORBIDDEN_FILENAME_CHARS.sub("", title).strip()
    return sanitized[:80]


def unique_path(dir: Path, filename: str) -> Path:
    """dir/filename が既存なら衝突しないパスを返す(既存ファイルは上書きしない)。"""
    candidate = dir / filename
    if not candidate.exists():
        return candidate

    stem = candidate.stem
    suffix = candidate.suffix
    n = 2
    while True:
        candidate = dir / f"{stem}-{n}{suffix}"
        if not candidate.exists():
            return candidate
        n += 1


def split_frontmatter(text: str) -> tuple[str, str]:
    """先頭の frontmatter ブロックと本文を分離する。"""
    if not text.startswith("---\n"):
        return "", text

    lines = text.split("\n")
    for i in range(1, len(lines)):
        if lines[i] == "---":
            fm_text = "\n".join(lines[1:i])
            body_text = "\n".join(lines[i + 1 :])
            return fm_text, body_text

    # 終端の --- が見つからない場合は frontmatter とみなさない
    return "", text


def get_fm_value(fm_text: str, key: str) -> str | None:
    """frontmatterテキストから key の値を取り出す。無ければ None。"""
    prefix = f"{key}:"
    for line in fm_text.split("\n"):
        if line.startswith(prefix):
            value = line[len(prefix) :].strip()
            if value.startswith('"') and value.endswith('"') and len(value) >= 2:
                value = value[1:-1]
            return value
    return None


def set_fm_value(fm_text: str, key: str, value: str) -> str:
    """frontmatterテキスト内の key: 行を置換、無ければ末尾に追加する。"""
    prefix = f"{key}:"
    new_line = f'{key}: "{value}"'
    lines = fm_text.split("\n") if fm_text else []

    for i, line in enumerate(lines):
        if line.startswith(prefix):
            lines[i] = new_line
            return "\n".join(lines)

    lines.append(new_line)
    return "\n".join(lines)


def add_tag(fm_text: str, tag: str) -> str:
    """frontmatterテキストの tags: リストに1件追加する。tags: が無ければ新設する。"""
    lines = fm_text.split("\n") if fm_text else []
    for i, line in enumerate(lines):
        if line.startswith("tags:"):
            j = i + 1
            while j < len(lines) and lines[j].startswith("  - "):
                j += 1
            lines.insert(j, f"  - {tag}")
            return "\n".join(lines)
    lines.append("tags:")
    lines.append(f"  - {tag}")
    return "\n".join(lines)


def get_fm_tags(fm_text: str) -> list[str]:
    """frontmatterテキストから tags: リストを取り出す。無ければ空リスト。"""
    lines = fm_text.split("\n")
    for i, line in enumerate(lines):
        if line.startswith("tags:"):
            tags = []
            j = i + 1
            while j < len(lines) and lines[j].startswith("  - "):
                tags.append(lines[j][4:].strip())
                j += 1
            return tags
    return []


def fill_template(template_text: str, *, title: str, dt: datetime.datetime) -> str:
    """テンプレート内のプレースホルダを実値に置換する。"""
    result = template_text
    result = result.replace("{{title}}", title)
    result = result.replace("{{date:YYYY-MM-DD}}", dt.strftime("%Y-%m-%d"))
    result = result.replace("{{date:ddd}}", _WEEKDAY_LABELS[dt.weekday()])
    result = result.replace("{{time:HH:mm}}", dt.strftime("%H:%M"))
    return result


def get_marker_block(text: str, start_marker: str, end_marker: str) -> str:
    """マーカー行の間のテキストを返す。見つからなければ空文字。"""
    start_line = f"<!-- {start_marker} -->"
    end_line = f"<!-- {end_marker} -->"
    start_idx = text.find(start_line)
    if start_idx == -1:
        return ""
    end_idx = text.find(end_line, start_idx)
    if end_idx == -1:
        return ""

    inner_start = start_idx + len(start_line)
    inner = text[inner_start:end_idx]
    # マーカー行の前後の改行を取り除く
    if inner.startswith("\n"):
        inner = inner[1:]
    if inner.endswith("\n"):
        inner = inner[:-1]
    return inner


def set_marker_block(text: str, start_marker: str, end_marker: str, new_inner: str) -> str:
    """マーカー行を保持したまま、間のテキストを new_inner に置換する。"""
    start_line = f"<!-- {start_marker} -->"
    end_line = f"<!-- {end_marker} -->"
    start_idx = text.find(start_line)
    if start_idx == -1:
        return text
    end_idx = text.find(end_line, start_idx)
    if end_idx == -1:
        return text

    inner_start = start_idx + len(start_line)
    before = text[:inner_start]
    after = text[end_idx:]
    return f"{before}\n{new_inner}\n{after}"


def list_project_names(projects_dir: Path) -> list[str]:
    """projects_dir直下のサブディレクトリ名をソートして返す。

    projects_dirが存在しない、またはディレクトリでない場合は空リストを返す。
    """
    if not projects_dir.exists() or not projects_dir.is_dir():
        return []

    return sorted(entry.name for entry in projects_dir.iterdir() if entry.is_dir())


def _tokenize(name: str) -> list[str]:
    """ディレクトリ名を空白/ハイフン/アンダースコアで分割し、3文字以上のトークンを返す。"""
    tokens = re.split(r"[\s\-_]+", name)
    return [t for t in tokens if len(t) >= 3]


def fuzzy_project_match(text: str, projects_dir: Path) -> str | None:
    """projects_dir 配下のディレクトリ名から text にあいまい一致するプロジェクトを探す。

    ちょうど1件一致した場合のみ '"[[ディレクトリ名]]"' を返す。
    """
    matched_names: list[str] = []
    for name in list_project_names(projects_dir):
        tokens = _tokenize(name)
        if any(token in text for token in tokens):
            matched_names.append(name)

    if len(matched_names) == 1:
        return f'"[[{matched_names[0]}]]"'
    return None
