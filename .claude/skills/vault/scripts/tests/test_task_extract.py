"""task_extract.py のユニットテスト。

標準ライブラリの unittest のみを使用する。
"""

import sys
import unittest
from pathlib import Path

# scripts/ ディレクトリを import パスに追加する
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import task_extract  # noqa: E402


class TestExtractActionItems(unittest.TestCase):
    def test_h2見出しから複数件抽出する(self):
        text = (
            "# タイトル\n\n"
            "## ⚡ アクションアイテム\n"
            "- [ ] 資料を送る\n"
            "- [ ] 次回日程を決める\n"
        )
        self.assertEqual(
            task_extract.extract_action_items(text),
            ["資料を送る", "次回日程を決める"],
        )

    def test_h3今回見出しから抽出する(self):
        text = "### ⚡ アクションアイテム（今回）\n- [ ] 議事録を送付する\n"
        self.assertEqual(
            task_extract.extract_action_items(text), ["議事録を送付する"]
        )

    def test_見出しが無ければ空リスト(self):
        text = "# タイトル\n\n## 💬 議題・メモ\n- 雑談\n"
        self.assertEqual(task_extract.extract_action_items(text), [])

    def test_該当行が0件なら空リスト(self):
        text = "## ⚡ アクションアイテム\n\n"
        self.assertEqual(task_extract.extract_action_items(text), [])

    def test_次の見出しで抽出を止める(self):
        text = (
            "## ⚡ アクションアイテム\n"
            "- [ ] 対象タスク\n"
            "## 📅 次回開催予定\n"
            "- [ ] 対象外タスク\n"
        )
        self.assertEqual(task_extract.extract_action_items(text), ["対象タスク"])

    def test_文書末尾までが対象範囲になる(self):
        text = "## ⚡ アクションアイテム\n- [ ] 最後のタスク"
        self.assertEqual(task_extract.extract_action_items(text), ["最後のタスク"])


class TestExtractProject(unittest.TestCase):
    def test_projectが設定されており対応ディレクトリが実在する場合は取得できる(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            vault_root = Path(tmp)
            (vault_root / "10_Projects" / "VaultMigration").mkdir(parents=True)
            text = '---\nproject: "[[VaultMigration]]"\n---\n# body'
            self.assertEqual(
                task_extract.extract_project(text, vault_root), "[[VaultMigration]]"
            )

    def test_projectが空文字の場合はNoneになる(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            vault_root = Path(tmp)
            text = '---\nproject: ""\n---\n# body'
            self.assertIsNone(task_extract.extract_project(text, vault_root))

    def test_projectキーが無い場合はNoneになる(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            vault_root = Path(tmp)
            text = '---\ntitle: "foo"\n---\n# body'
            self.assertIsNone(task_extract.extract_project(text, vault_root))

    def test_projectが設定されているが対応ディレクトリが実在しない場合はNoneになる(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            vault_root = Path(tmp)
            text = '---\nproject: "[[アーカイブ済みプロジェクト]]"\n---\n# body'
            self.assertIsNone(task_extract.extract_project(text, vault_root))


class TestMain(unittest.TestCase):
    def test_main実行でJSONが標準出力される(self):
        import json
        import subprocess
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            vault_root = Path(tmp)
            (vault_root / "10_Projects" / "VaultMigration").mkdir(parents=True)
            note_path = vault_root / "note.md"
            note_path.write_text(
                '---\nproject: "[[VaultMigration]]"\n---\n'
                "# 議事録\n\n"
                "## ⚡ アクションアイテム\n"
                "- [ ] タスクA\n"
                "- [ ] タスクB\n",
                encoding="utf-8",
            )
            script_path = Path(__file__).resolve().parent.parent / "task_extract.py"
            result = subprocess.run(
                [
                    sys.executable,
                    str(script_path),
                    "--note",
                    str(note_path),
                    "--vault-root",
                    str(vault_root),
                ],
                capture_output=True,
                text=True,
                check=True,
            )
            output = json.loads(result.stdout)
            self.assertEqual(output, {
                "items": ["タスクA", "タスクB"],
                "project": "[[VaultMigration]]",
            })


if __name__ == "__main__":
    unittest.main()
