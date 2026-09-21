"""vault_lib.py のユニットテスト。

標準ライブラリの unittest のみを使用する。
"""

import datetime
import sys
import tempfile
import unittest
from pathlib import Path

# scripts/ ディレクトリを import パスに追加する
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import vault_lib  # noqa: E402


class TestSanitizeFilename(unittest.TestCase):
    def test_禁止文字を除去する(self):
        title = 'a\\b/c:d*e?f"g<h>i|j'
        self.assertEqual(vault_lib.sanitize_filename(title), "abcdefghij")

    def test_前後空白をtrimする(self):
        self.assertEqual(vault_lib.sanitize_filename("  hello  "), "hello")

    def test_80文字超は切り詰める(self):
        title = "a" * 100
        result = vault_lib.sanitize_filename(title)
        self.assertEqual(len(result), 80)
        self.assertEqual(result, "a" * 80)

    def test_80文字以下はそのまま(self):
        title = "a" * 80
        self.assertEqual(vault_lib.sanitize_filename(title), title)


class TestUniquePath(unittest.TestCase):
    def test_衝突しない場合はそのまま返す(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            result = vault_lib.unique_path(d, "note.md")
            self.assertEqual(result, d / "note.md")

    def test_衝突時はsuffixを付与する(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            (d / "note.md").write_text("existing", encoding="utf-8")
            result = vault_lib.unique_path(d, "note.md")
            self.assertEqual(result, d / "note-2.md")

    def test_複数衝突時はさらにインクリメントする(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            (d / "note.md").write_text("existing", encoding="utf-8")
            (d / "note-2.md").write_text("existing", encoding="utf-8")
            result = vault_lib.unique_path(d, "note.md")
            self.assertEqual(result, d / "note-3.md")

    def test_既存ファイルを上書きしない(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            (d / "note.md").write_text("original content", encoding="utf-8")
            vault_lib.unique_path(d, "note.md")
            self.assertEqual((d / "note.md").read_text(encoding="utf-8"), "original content")


class TestSplitFrontmatter(unittest.TestCase):
    def test_frontmatterありの場合(self):
        text = '---\ntitle: "foo"\ntags: []\n---\nbody line1\nbody line2'
        fm, body = vault_lib.split_frontmatter(text)
        self.assertEqual(fm, 'title: "foo"\ntags: []')
        self.assertEqual(body, "body line1\nbody line2")

    def test_frontmatterなしの場合(self):
        text = "just a plain body\nwith no frontmatter"
        fm, body = vault_lib.split_frontmatter(text)
        self.assertEqual(fm, "")
        self.assertEqual(body, text)


class TestGetFmValue(unittest.TestCase):
    def test_存在するキーを取得する(self):
        fm = 'title: "foo"\ndate: "2026-09-21"'
        self.assertEqual(vault_lib.get_fm_value(fm, "title"), "foo")
        self.assertEqual(vault_lib.get_fm_value(fm, "date"), "2026-09-21")

    def test_存在しないキーはNoneを返す(self):
        fm = 'title: "foo"'
        self.assertIsNone(vault_lib.get_fm_value(fm, "missing"))

    def test_クォート無しの値も取得できる(self):
        fm = "count: 5"
        self.assertEqual(vault_lib.get_fm_value(fm, "count"), "5")


class TestSetFmValue(unittest.TestCase):
    def test_既存キーを置換し他行は変化しない(self):
        fm = 'title: "foo"\ntags: []\ndate: "2026-09-21"'
        result = vault_lib.set_fm_value(fm, "title", "bar")
        self.assertEqual(result, 'title: "bar"\ntags: []\ndate: "2026-09-21"')

    def test_存在しないキーは末尾に追加する(self):
        fm = 'title: "foo"'
        result = vault_lib.set_fm_value(fm, "status", "done")
        self.assertEqual(result, 'title: "foo"\nstatus: "done"')


class TestAddTag(unittest.TestCase):
    def test_既存タグリストの末尾に追加する(self):
        fm = 'title: "foo"\ntags:\n  - existing'
        result = vault_lib.add_tag(fm, "new-tag")
        self.assertEqual(result, 'title: "foo"\ntags:\n  - existing\n  - new-tag')

    def test_tagsキーが無い場合は新設する(self):
        fm = 'title: "foo"'
        result = vault_lib.add_tag(fm, "new-tag")
        self.assertEqual(result, 'title: "foo"\ntags:\n  - new-tag')

    def test_tagsキーが空の場合はそこに追加する(self):
        fm = 'title: "foo"\ntags:\ndate: "2026-09-21"'
        result = vault_lib.add_tag(fm, "new-tag")
        self.assertEqual(result, 'title: "foo"\ntags:\n  - new-tag\ndate: "2026-09-21"')


class TestGetFmTags(unittest.TestCase):
    def test_複数タグを順番通り取得する(self):
        fm = "tags:\n  - alpha\n  - beta\n  - gamma"
        self.assertEqual(vault_lib.get_fm_tags(fm), ["alpha", "beta", "gamma"])

    def test_tagsキーが無い場合は空リスト(self):
        fm = 'title: "foo"'
        self.assertEqual(vault_lib.get_fm_tags(fm), [])

    def test_tagsキーが空の場合は空リスト(self):
        fm = 'title: "foo"\ntags:\ndate: "2026-09-21"'
        self.assertEqual(vault_lib.get_fm_tags(fm), [])

    def test_単一タグを取得する(self):
        fm = "tags:\n  - solo"
        self.assertEqual(vault_lib.get_fm_tags(fm), ["solo"])


class TestFillTemplate(unittest.TestCase):
    def setUp(self):
        # 2026-09-21 は月曜日
        self.dt = datetime.datetime(2026, 9, 21, 14, 30)

    def test_title置換(self):
        result = vault_lib.fill_template("{{title}}", title="MyTitle", dt=self.dt)
        self.assertEqual(result, "MyTitle")

    def test_date置換(self):
        result = vault_lib.fill_template("{{date:YYYY-MM-DD}}", title="t", dt=self.dt)
        self.assertEqual(result, "2026-09-21")

    def test_曜日置換(self):
        result = vault_lib.fill_template("{{date:ddd}}", title="t", dt=self.dt)
        self.assertEqual(result, "月")

    def test_時刻置換(self):
        result = vault_lib.fill_template("{{time:HH:mm}}", title="t", dt=self.dt)
        self.assertEqual(result, "14:30")

    def test_複数同時使用(self):
        template = "# {{title}} ({{date:YYYY-MM-DD}} {{date:ddd}} {{time:HH:mm}})"
        result = vault_lib.fill_template(template, title="会議", dt=self.dt)
        self.assertEqual(result, "# 会議 (2026-09-21 月 14:30)")

    def test_他のプレースホルダは残す(self):
        result = vault_lib.fill_template("{{unknown}}", title="t", dt=self.dt)
        self.assertEqual(result, "{{unknown}}")

    def test_各曜日の変換(self):
        # 2026-09-21(月) から 2026-09-27(日) まで
        expected = ["月", "火", "水", "木", "金", "土", "日"]
        for i, label in enumerate(expected):
            dt = datetime.datetime(2026, 9, 21 + i)
            result = vault_lib.fill_template("{{date:ddd}}", title="t", dt=dt)
            self.assertEqual(result, label)


class TestMarkerBlock(unittest.TestCase):
    def test_get_marker_blockで抽出する(self):
        text = "before\n<!-- START -->\ninner line1\ninner line2\n<!-- END -->\nafter"
        result = vault_lib.get_marker_block(text, "START", "END")
        self.assertEqual(result, "inner line1\ninner line2")

    def test_get_marker_blockで見つからない場合は空文字(self):
        text = "no markers here"
        result = vault_lib.get_marker_block(text, "START", "END")
        self.assertEqual(result, "")

    def test_set_marker_blockでマーカー行を保持し中身を置換する(self):
        text = "before\n<!-- START -->\nold inner\n<!-- END -->\nafter"
        result = vault_lib.set_marker_block(text, "START", "END", "new inner")
        self.assertEqual(
            result, "before\n<!-- START -->\nnew inner\n<!-- END -->\nafter"
        )


class TestListProjectNames(unittest.TestCase):
    def test_複数ディレクトリがある場合ソートされた名前を返す(self):
        with tempfile.TemporaryDirectory() as tmp:
            projects_dir = Path(tmp) / "Projects"
            projects_dir.mkdir()
            (projects_dir / "Beta").mkdir()
            (projects_dir / "Alpha").mkdir()
            result = vault_lib.list_project_names(projects_dir)
            self.assertEqual(result, ["Alpha", "Beta"])

    def test_ディレクトリ以外のファイルは除外される(self):
        with tempfile.TemporaryDirectory() as tmp:
            projects_dir = Path(tmp) / "Projects"
            projects_dir.mkdir()
            (projects_dir / "Alpha").mkdir()
            (projects_dir / "note.md").write_text("dummy", encoding="utf-8")
            result = vault_lib.list_project_names(projects_dir)
            self.assertEqual(result, ["Alpha"])

    def test_projects_dirが存在しない場合は空リスト(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing_dir = Path(tmp) / "NoSuchDir"
            result = vault_lib.list_project_names(missing_dir)
            self.assertEqual(result, [])


class TestFuzzyProjectMatch(unittest.TestCase):
    def _make_projects(self, tmp, names):
        projects_dir = Path(tmp) / "Projects"
        projects_dir.mkdir()
        for name in names:
            (projects_dir / name).mkdir()
        return projects_dir

    def test_1件一致(self):
        with tempfile.TemporaryDirectory() as tmp:
            projects_dir = self._make_projects(tmp, ["VaultMigration", "OtherProj"])
            result = vault_lib.fuzzy_project_match(
                "VaultMigrationの件について相談", projects_dir
            )
            self.assertEqual(result, '"[[VaultMigration]]"')

    def test_0件一致(self):
        with tempfile.TemporaryDirectory() as tmp:
            projects_dir = self._make_projects(tmp, ["VaultMigration", "OtherProj"])
            result = vault_lib.fuzzy_project_match("全く関係ない文章です", projects_dir)
            self.assertIsNone(result)

    def test_2件以上一致でNone(self):
        with tempfile.TemporaryDirectory() as tmp:
            projects_dir = self._make_projects(tmp, ["VaultAlpha", "VaultBeta"])
            result = vault_lib.fuzzy_project_match("VaultについてAlphaとBetaの話", projects_dir)
            self.assertIsNone(result)

    def test_projects_dirが存在しない場合はNone(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing_dir = Path(tmp) / "NoSuchDir"
            result = vault_lib.fuzzy_project_match("何でもいい文章", missing_dir)
            self.assertIsNone(result)


class TestVaultRoot(unittest.TestCase):
    def test_VAULT_ROOTがPathである(self):
        self.assertIsInstance(vault_lib.VAULT_ROOT, Path)

    def test_VAULT_ROOTは_claude_skills_vault_scriptsの親である(self):
        # vault_lib.py は <VAULT_ROOT>/.claude/skills/vault/scripts/vault_lib.py に配置される
        expected_file = (
            vault_lib.VAULT_ROOT / ".claude" / "skills" / "vault" / "scripts" / "vault_lib.py"
        )
        self.assertEqual(expected_file, Path(vault_lib.__file__).resolve())


class TestRunGit(unittest.TestCase):
    def test_git_versionを実行できる(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = vault_lib.run_git("--version", cwd=tmp)
            self.assertIn("git version", result)

    def test_check_trueで異常終了時に例外を送出する(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(Exception):
                vault_lib.run_git("not-a-real-git-command", cwd=tmp)


if __name__ == "__main__":
    unittest.main()
