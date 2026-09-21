"""project_create.py のユニットテスト。

標準ライブラリの unittest のみを使用する。
"""

import datetime
import sys
import tempfile
import unittest
from pathlib import Path

# scripts/ ディレクトリを import パスに追加する
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import project_create  # noqa: E402

_TEMPLATE_TEXT = (
    "---\n"
    "type: project\n"
    'start_date: "{{date:YYYY-MM-DD}}"\n'
    "due_date: \n"
    "---\n"
    "# プロジェクト: {{title}}\n"
    "\n"
    "## 🎯 概要・目的\n"
    "- \n"
)


def _make_vault(tmp) -> Path:
    vault_root = Path(tmp)
    template_dir = vault_root / "70_Templates"
    template_dir.mkdir(parents=True)
    (template_dir / "Project_Template.md").write_text(_TEMPLATE_TEXT, encoding="utf-8")
    return vault_root


class TestCreateProject(unittest.TestCase):
    def setUp(self):
        self.dt = datetime.datetime(2026, 9, 21, 14, 30)

    def test_正常系で3つのサブフォルダとノートが作成される(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault_root = _make_vault(tmp)
            result = project_create.create_project(
                vault_root, title="新規プロジェクト", due_date=None, dt=self.dt
            )

            self.assertEqual(result["status"], "ok")

            project_dir = vault_root / "10_Projects" / "新規プロジェクト"
            self.assertTrue((project_dir / "Tasks").is_dir())
            self.assertTrue((project_dir / "Meetings").is_dir())
            self.assertTrue((project_dir / "Documents").is_dir())

            note_path = Path(result["note_path"])
            self.assertTrue(note_path.is_file())
            self.assertEqual(note_path, project_dir / "新規プロジェクト.md")

            content = note_path.read_text(encoding="utf-8")
            self.assertIn('start_date: "2026-09-21"', content)
            self.assertIn("type: project", content)
            self.assertIn("# プロジェクト: 新規プロジェクト", content)

            self.assertEqual(result["folders"], ["Tasks", "Meetings", "Documents"])

    def test_due_date指定時はfrontmatterに反映される(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault_root = _make_vault(tmp)
            result = project_create.create_project(
                vault_root, title="期限あり", due_date="2026-10-01", dt=self.dt
            )

            note_path = Path(result["note_path"])
            content = note_path.read_text(encoding="utf-8")
            self.assertIn('due_date: "2026-10-01"', content)

    def test_due_date未指定ならfrontmatterは空欄のまま(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault_root = _make_vault(tmp)
            result = project_create.create_project(
                vault_root, title="期限なし", due_date=None, dt=self.dt
            )

            note_path = Path(result["note_path"])
            content = note_path.read_text(encoding="utf-8")
            self.assertIn("due_date: \n", content)
            self.assertNotIn('due_date: "', content)

    def test_既存プロジェクトがあれば何も作成せずエラーを返す(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault_root = _make_vault(tmp)
            existing_dir = vault_root / "10_Projects" / "既存プロジェクト"
            existing_dir.mkdir(parents=True)

            result = project_create.create_project(
                vault_root, title="既存プロジェクト", due_date=None, dt=self.dt
            )

            self.assertEqual(
                result, {"status": "error", "reason": "project_already_exists"}
            )

            # 何も新規作成されていないこと
            self.assertFalse((existing_dir / "Tasks").exists())
            self.assertFalse((existing_dir / "Meetings").exists())
            self.assertFalse((existing_dir / "Documents").exists())
            self.assertFalse((existing_dir / "既存プロジェクト.md").exists())
            self.assertEqual(list(existing_dir.iterdir()), [])


class TestMain(unittest.TestCase):
    def test_main経由の正常系でJSONが出力される(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault_root = _make_vault(tmp)
            argv = [
                "--title",
                "CLIプロジェクト",
                "--vault-root",
                str(vault_root),
            ]
            exit_code = project_create.main(argv)

            self.assertEqual(exit_code, 0)
            note_path = (
                vault_root / "10_Projects" / "CLIプロジェクト" / "CLIプロジェクト.md"
            )
            self.assertTrue(note_path.is_file())

    def test_main経由の既存プロジェクトはエラー終了する(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault_root = _make_vault(tmp)
            (vault_root / "10_Projects" / "重複プロジェクト").mkdir(parents=True)

            argv = [
                "--title",
                "重複プロジェクト",
                "--vault-root",
                str(vault_root),
            ]
            exit_code = project_create.main(argv)

            self.assertEqual(exit_code, 1)


if __name__ == "__main__":
    unittest.main()
