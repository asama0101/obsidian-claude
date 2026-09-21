"""task_save.py のユニットテスト。

標準ライブラリの unittest のみを使用する。
"""

import datetime
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

# scripts/ ディレクトリを import パスに追加する
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import task_save  # noqa: E402

_TEMPLATE_TEXT = (
    "---\n"
    "type: task\n"
    'project: ""\n'
    'start_date: "{{date:YYYY-MM-DD}}"\n'
    'due_date: "{{date:YYYY-MM-DD}}"\n'
    "status: 1_todo\n"
    "tags:\n"
    "  - task\n"
    "---\n"
    "# {{title}}\n"
    "\n"
    "## 📌 作業手順・サブタスク\n"
    "- [ ] \n"
    "\n"
    "## 🔗 関連リンク・参照資料\n"
    "- \n"
    "\n"
    "## 📝 メモ\n"
)


class TestExtractProjectName(unittest.TestCase):
    def test_リンク形式からプロジェクト名を取り出す(self):
        self.assertEqual(
            task_save.extract_project_name("[[VaultMigration]]"), "VaultMigration"
        )

    def test_リンク形式でなければそのまま返す(self):
        self.assertEqual(task_save.extract_project_name("PlainName"), "PlainName")


class TestBuildNoteText(unittest.TestCase):
    def setUp(self):
        self.dt = datetime.datetime(2026, 9, 21, 14, 30)

    def test_projectとstatusとstart_dateが設定される(self):
        note_text = task_save.build_note_text(
            _TEMPLATE_TEXT,
            title="資料を送る",
            project="[[VaultMigration]]",
            due_date=None,
            dt=self.dt,
        )
        fm_text, body_text = self._split(note_text)
        self.assertIn('project: "[[VaultMigration]]"', fm_text)
        self.assertIn("status: 1_todo", fm_text)
        self.assertIn('start_date: "2026-09-21"', fm_text)
        self.assertIn("# 資料を送る", body_text)

    def test_due_date未指定なら空欄のまま(self):
        note_text = task_save.build_note_text(
            _TEMPLATE_TEXT,
            title="資料を送る",
            project="[[VaultMigration]]",
            due_date=None,
            dt=self.dt,
        )
        fm_text, _ = self._split(note_text)
        self.assertIn('due_date: ""', fm_text)

    def test_due_date指定時はその値が設定される(self):
        note_text = task_save.build_note_text(
            _TEMPLATE_TEXT,
            title="資料を送る",
            project="[[VaultMigration]]",
            due_date="2026-10-01",
            dt=self.dt,
        )
        fm_text, _ = self._split(note_text)
        self.assertIn('due_date: "2026-10-01"', fm_text)

    @staticmethod
    def _split(note_text: str) -> tuple[str, str]:
        lines = note_text.split("\n")
        assert lines[0] == "---"
        for i in range(1, len(lines)):
            if lines[i] == "---":
                return "\n".join(lines[1:i]), "\n".join(lines[i + 1 :])
        raise AssertionError("frontmatter終端が見つからない")


class TestMain(unittest.TestCase):
    def _make_vault(self, tmp, project_names=()):
        vault_root = Path(tmp)
        template_dir = vault_root / "70_Templates"
        template_dir.mkdir(parents=True)
        (template_dir / "Task_Template.md").write_text(_TEMPLATE_TEXT, encoding="utf-8")
        for name in project_names:
            (vault_root / "10_Projects" / name).mkdir(parents=True)
        return vault_root

    def _run(self, vault_root, *extra_args):
        script_path = Path(__file__).resolve().parent.parent / "task_save.py"
        return subprocess.run(
            [
                sys.executable,
                str(script_path),
                "--vault-root",
                str(vault_root),
                *extra_args,
            ],
            capture_output=True,
            text=True,
        )

    def test_project未指定はエラーになる(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault_root = self._make_vault(tmp)
            result = self._run(
                vault_root, "--title", "資料を送る", "--project", ""
            )
            self.assertEqual(result.returncode, 1)
            output = json.loads(result.stdout)
            self.assertEqual(output, {"status": "error", "reason": "project_required"})

    def test_正常系でノートが作成されJSONが出力される(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault_root = self._make_vault(tmp, project_names=["VaultMigration"])
            result = self._run(
                vault_root,
                "--title",
                "資料を送る",
                "--project",
                "[[VaultMigration]]",
            )
            self.assertEqual(result.returncode, 0)
            output = json.loads(result.stdout)
            note_path = Path(output["note_path"])
            self.assertTrue(note_path.exists())
            self.assertEqual(
                note_path.parent,
                vault_root / "10_Projects" / "VaultMigration" / "Tasks",
            )
            content = note_path.read_text(encoding="utf-8")
            self.assertIn('project: "[[VaultMigration]]"', content)
            self.assertIn("status: 1_todo", content)

    def test_存在しないプロジェクトはエラーになる(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault_root = self._make_vault(tmp)
            result = self._run(
                vault_root,
                "--title",
                "資料を送る",
                "--project",
                "[[NoSuchProject]]",
            )
            self.assertEqual(result.returncode, 1)
            output = json.loads(result.stdout)
            self.assertEqual(output, {"status": "error", "reason": "project_not_found"})
            self.assertFalse(
                (vault_root / "10_Projects" / "NoSuchProject").exists()
            )


if __name__ == "__main__":
    unittest.main()
