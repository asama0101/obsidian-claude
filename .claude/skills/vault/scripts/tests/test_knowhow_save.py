"""knowhow_save.py のユニットテスト。

標準ライブラリの unittest のみを使用する。
"""

import contextlib
import datetime
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

# scripts/ ディレクトリを import パスに追加する
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import knowhow_save  # noqa: E402
import vault_lib  # noqa: E402

TEMPLATE_PATH = vault_lib.VAULT_ROOT / "70_Templates" / "Knowhow_Template.md"


def _sample_content(**overrides):
    content = {
        "title": "テストノウハウ",
        "category": "python",
        "overview": "これは概要です。",
        "steps": ["手順1を実行する", "手順2を確認する"],
        "pitfalls": ["注意点A", "注意点B"],
        "references": ["https://example.com/doc"],
        "original_text": "元のメモ行1\n元のメモ行2",
    }
    content.update(overrides)
    return content


class TestBuildNote(unittest.TestCase):
    def setUp(self):
        self.template_text = TEMPLATE_PATH.read_text(encoding="utf-8")
        self.dt = datetime.datetime(2026, 9, 21, 10, 0)

    def test_categoryとtagsが設定される(self):
        content = _sample_content(category="python")
        note = knowhow_save.build_note(content, self.template_text, self.dt)
        fm_text, _ = vault_lib.split_frontmatter(note)
        self.assertEqual(vault_lib.get_fm_value(fm_text, "category"), "python")
        self.assertIn("  - knowhow", fm_text)
        self.assertIn("  - knowledge/python", fm_text)

    def test_overviewが概要セクションに入る(self):
        content = _sample_content(overview="これは概要です。")
        note = knowhow_save.build_note(content, self.template_text, self.dt)
        self.assertIn("## 💡 概要・結論\n- これは概要です。", note)

    def test_stepsが番号付きで手順セクションに入る(self):
        content = _sample_content(steps=["最初の手順", "次の手順"])
        note = knowhow_save.build_note(content, self.template_text, self.dt)
        self.assertIn(
            "## 🛠 手順・実行方法 / 解決策\n1. 最初の手順\n2. 次の手順", note
        )

    def test_pitfallsが箇条書きで注意点セクションに入る(self):
        content = _sample_content(pitfalls=["ハマりA", "ハマりB"])
        note = knowhow_save.build_note(content, self.template_text, self.dt)
        self.assertIn(
            "## ⚠️ 注意点・ハマりポイント\n- ハマりA\n- ハマりB", note
        )

    def test_referencesが箇条書きで参照セクションに入る(self):
        content = _sample_content(
            references=["https://example.com/a", "https://example.com/b"]
        )
        note = knowhow_save.build_note(content, self.template_text, self.dt)
        self.assertIn(
            "## 🔗 参照・関連リンク\n- https://example.com/a\n- https://example.com/b",
            note,
        )

    def test_original_textが加工されず引用形式で残る(self):
        content = _sample_content(original_text="生ログ行1\n生ログ行2\n  インデント行")
        note = knowhow_save.build_note(content, self.template_text, self.dt)
        self.assertIn(
            "## 📄 ノウハウ本文\n> 生ログ行1\n> 生ログ行2\n>   インデント行", note
        )

    def test_タイトルが本文見出しに反映される(self):
        content = _sample_content(title="日付フォーマットの罠")
        note = knowhow_save.build_note(content, self.template_text, self.dt)
        self.assertIn("# 日付フォーマットの罠", note)


class TestMain(unittest.TestCase):
    def _make_vault(self, tmp):
        vault_root = Path(tmp)
        (vault_root / "70_Templates").mkdir(parents=True)
        (vault_root / "70_Templates" / "Knowhow_Template.md").write_text(
            TEMPLATE_PATH.read_text(encoding="utf-8"), encoding="utf-8"
        )
        (vault_root / "20_Areas" / "Knowledge").mkdir(parents=True)
        return vault_root

    def _write_content_json(self, tmp, content):
        path = Path(tmp) / "content.json"
        path.write_text(json.dumps(content, ensure_ascii=False), encoding="utf-8")
        return path

    def test_note_pathが出力され保存される(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault_root = self._make_vault(tmp)
            content = _sample_content(title="保存テスト")
            content_json = self._write_content_json(tmp, content)
            argv = [
                "--content-json",
                str(content_json),
                "--vault-root",
                str(vault_root),
            ]

            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                result = knowhow_save.main(argv)

            self.assertEqual(result, 0)
            output = json.loads(buf.getvalue())
            note_path = Path(output["note_path"])
            self.assertTrue(note_path.exists())
            self.assertEqual(note_path.parent, vault_root / "20_Areas" / "Knowledge")
            saved_text = note_path.read_text(encoding="utf-8")
            self.assertIn('category: "python"', saved_text)
            self.assertIn("  - knowledge/python", saved_text)

    def test_ファイル名衝突時はunique_pathで回避する(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault_root = self._make_vault(tmp)
            knowledge_dir = vault_root / "20_Areas" / "Knowledge"
            existing = knowledge_dir / "衝突テスト.md"
            existing.write_text("既存ノート", encoding="utf-8")

            content = _sample_content(title="衝突テスト")
            content_json = self._write_content_json(tmp, content)
            argv = [
                "--content-json",
                str(content_json),
                "--vault-root",
                str(vault_root),
            ]

            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                knowhow_save.main(argv)

            output = json.loads(buf.getvalue())
            note_path = Path(output["note_path"])
            self.assertEqual(note_path.name, "衝突テスト-2.md")
            # 既存ファイルの中身は変更されない
            self.assertEqual(existing.read_text(encoding="utf-8"), "既存ノート")


if __name__ == "__main__":
    unittest.main()
