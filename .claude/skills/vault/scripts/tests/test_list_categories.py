"""list_categories.py のユニットテスト。

標準ライブラリの unittest のみを使用する。
"""

import contextlib
import io
import json
import sys
import tempfile
import unittest
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


class TestListCategoryTags(unittest.TestCase):
    def test_対象ディレクトリが無ければ空リストを返す(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault_root = Path(tmp)
            result = list_categories.list_category_tags(vault_root)
            self.assertEqual(result, [])

    def test_単一のKnowhowノートからタグを収集する(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault_root = Path(tmp)
            _write_note(
                vault_root / "20_Areas" / "Knowledge" / "note.md",
                ["python/pandas"],
            )
            result = list_categories.list_category_tags(vault_root)
            self.assertEqual(result, ["python/pandas"])

    def test_両ディレクトリで重複するタグは1件に統合されソートされる(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault_root = Path(tmp)
            _write_note(
                vault_root / "20_Areas" / "Knowledge" / "note1.md",
                ["python/pandas"],
            )
            _write_note(
                vault_root / "20_Areas" / "WebClips" / "note2.md",
                ["python/pandas"],
            )
            _write_note(
                vault_root / "20_Areas" / "WebClips" / "note3.md",
                ["git/rebase"],
            )
            result = list_categories.list_category_tags(vault_root)
            self.assertEqual(result, ["git/rebase", "python/pandas"])

    def test_スラッシュ0個と2個以上のタグは除外される(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault_root = Path(tmp)
            _write_note(
                vault_root / "20_Areas" / "Knowledge" / "flat.md",
                ["knowhow"],
            )
            _write_note(
                vault_root / "20_Areas" / "Knowledge" / "deep.md",
                ["a/b/c"],
            )
            _write_note(
                vault_root / "20_Areas" / "Knowledge" / "valid.md",
                ["python/pandas"],
            )
            result = list_categories.list_category_tags(vault_root)
            self.assertEqual(result, ["python/pandas"])


class TestMain(unittest.TestCase):
    def test_main実行でJSONがstdoutに出力される(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault_root = Path(tmp)
            _write_note(
                vault_root / "20_Areas" / "Knowledge" / "note.md",
                ["python/pandas"],
            )
            argv = ["--vault-root", str(vault_root)]

            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                result = list_categories.main(argv)

            self.assertEqual(result, 0)
            output = json.loads(buf.getvalue())
            self.assertEqual(output, {"tags": ["python/pandas"]})


if __name__ == "__main__":
    unittest.main()
