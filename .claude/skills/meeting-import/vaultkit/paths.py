"""Vault 内のフォルダの場所。"""
import os
from pathlib import Path

KIND_FOLDERS = {
    "task": "20_tasks",
    "meeting": "70_meetings",
}


def vault_root():
    """Vault のルートを返す。環境変数 VAULT_ROOT があればそれを使い（テスト用）、無ければこのファイルの位置から求める。"""
    override = os.environ.get("VAULT_ROOT")
    if override:
        return Path(override)
    # <root>/.claude/skills/meeting-import/vaultkit/paths.py
    return Path(__file__).resolve().parents[4]


def note_dir(kind):
    """種別（task / meeting）のノートを置くフォルダを返す。"""
    return vault_root() / KIND_FOLDERS[kind]


def find_note(kind, name):
    """種別のノートを、名前（`.md` は省略可）から探して、パスを返す。

    `/`・`\\`・`:`・`..` を含む名前（フォルダの外を指しうる）と、該当ノートが無いときは None。
    """
    stem = name.removesuffix(".md")
    if not stem or stem in (".", "..") or any(char in stem for char in "/\\:"):
        return None
    path = note_dir(kind) / f"{stem}.md"
    return path if path.is_file() else None
