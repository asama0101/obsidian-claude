"""list_categories.py のユニットテスト。

pytest（`.claude/skills/vault/scripts/.venv/`のvenv限定の開発依存）を使用する。
"""

import contextlib
import io
import json
import sys
import tempfile
from pathlib import Path

# scripts/ ディレクトリを import パスに追加する
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import list_categories  # noqa: E402


def _write_note(path: Path, tags: list[str]) -> None:
    """frontmatterにtags:リストを持つ最小限のノートを書き込む。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    tags_block = "\n".join(f"  - {tag}" for tag in tags)
    text = f"---\ntags:\n{tags_block}\n---\n# タイトル\n本文\n"
    path.write_text(text, encoding="utf-8")


def test_対象ディレクトリが無ければ空リストを返す():
    with tempfile.TemporaryDirectory() as tmp:
        vault_root = Path(tmp)
        result = list_categories.list_category_tags(vault_root)
        assert result == []


def test_単一のKnowhowノートからタグを収集する():
    with tempfile.TemporaryDirectory() as tmp:
        vault_root = Path(tmp)
        _write_note(
            vault_root / "30_Areas" / "Knowledge" / "note.md",
            ["python/pandas"],
        )
        result = list_categories.list_category_tags(vault_root)
        assert result == ["python/pandas"]


def test_両ディレクトリで重複するタグは1件に統合されソートされる():
    with tempfile.TemporaryDirectory() as tmp:
        vault_root = Path(tmp)
        _write_note(
            vault_root / "30_Areas" / "Knowledge" / "note1.md",
            ["python/pandas"],
        )
        _write_note(
            vault_root / "30_Areas" / "WebClips" / "note2.md",
            ["python/pandas"],
        )
        _write_note(
            vault_root / "30_Areas" / "WebClips" / "note3.md",
            ["git/rebase"],
        )
        result = list_categories.list_category_tags(vault_root)
        assert result == ["git/rebase", "python/pandas"]


def test_スラッシュ0個と2個以上のタグは除外される():
    with tempfile.TemporaryDirectory() as tmp:
        vault_root = Path(tmp)
        _write_note(
            vault_root / "30_Areas" / "Knowledge" / "flat.md",
            ["knowhow"],
        )
        _write_note(
            vault_root / "30_Areas" / "Knowledge" / "deep.md",
            ["a/b/c"],
        )
        _write_note(
            vault_root / "30_Areas" / "Knowledge" / "valid.md",
            ["python/pandas"],
        )
        result = list_categories.list_category_tags(vault_root)
        assert result == ["python/pandas"]


def test_main実行でJSONがstdoutに出力される():
    with tempfile.TemporaryDirectory() as tmp:
        vault_root = Path(tmp)
        _write_note(
            vault_root / "30_Areas" / "Knowledge" / "note.md",
            ["python/pandas"],
        )
        argv = ["--vault-root", str(vault_root)]

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            result = list_categories.main(argv)

        assert result == 0
        output = json.loads(buf.getvalue())
        assert output == {"tags": ["python/pandas"]}
