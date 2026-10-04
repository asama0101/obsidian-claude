"""meeting_actions.py（CLI）のテスト。一時フォルダを Vault に見立てて（環境変数 VAULT_ROOT）実行する。"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "meeting_actions.py"
MEETING = "2026-10-05_定例"


def run(vault, *args):
    env = {**os.environ, "VAULT_ROOT": str(vault)}
    r = subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, env=env)
    out = r.stdout.decode("utf-8").strip()
    return r.returncode, (json.loads(out) if out else None)


class VaultTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.vault = Path(self._tmp.name)
        (self.vault / "70_meetings").mkdir()
        (self.vault / "20_tasks").mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def write_meeting(self, *actions, project="[[P]]", name=MEETING, newline="\n"):
        lines = [
            "---", "type: meeting", "date: 2026-10-05", f'project: "{project}"' if project else "project:",
            "location: 会議室A", "source:", "created: 2026-10-05", "tags: []", "---", f"# {name}", "",
            "## 参加者", "- 山田（営業）", "- 佐藤", "", "## 目的・議題", "- ", "", "## 議事・決定事項", "- ", "", "## アクションアイテム", *actions, "",
            "## 参照ドキュメント", "- ", "",
        ]
        path = self.vault / "70_meetings" / f"{name}.md"
        path.write_bytes(newline.join(lines).encode("utf-8"))
        return path

    def write_task(self, name):
        (self.vault / "20_tasks" / f"{name}.md").write_text("---\ntype: task\n---\n", encoding="utf-8")


class TestList(VaultTestCase):
    def test_returns_the_unresolved_items_with_the_meeting_project_and_date(self):
        self.write_meeting("- [ ] 資料を送る 期限:2026-10-10", "- [ ] ", "- [x] 済んだ項目", "- [ ] 済み → [[T]]")
        code, out = run(self.vault, "list", "--meeting", MEETING)
        self.assertEqual(code, 0)
        self.assertEqual(
            out,
            {
                "status": "ok",
                "meeting": MEETING,
                "path": f"70_meetings/{MEETING}.md",
                "date": "2026-10-05",
                "project": "P",
                "items": [{"text": "資料を送る 期限:2026-10-10", "content": "資料を送る", "due": "2026-10-10"}],
            },
        )

    def test_the_project_is_empty_when_the_meeting_has_none(self):
        self.write_meeting("- [ ] a", project="")
        self.assertEqual(run(self.vault, "list", "--meeting", MEETING)[1]["project"], "")

    def test_the_extension_may_be_given(self):
        self.write_meeting("- [ ] a")
        code, out = run(self.vault, "list", "--meeting", MEETING + ".md")
        self.assertEqual((code, out["meeting"]), (0, MEETING))

    def test_a_missing_meeting_is_reported(self):
        self.assertEqual(run(self.vault, "list", "--meeting", "無い"), (1, {"status": "not_found", "meeting": "無い"}))

    def test_a_name_that_leaves_the_folder_is_not_found(self):
        (self.vault / "secret.md").write_text("x", encoding="utf-8")
        code, out = run(self.vault, "list", "--meeting", "../secret")
        self.assertEqual((code, out["status"]), (1, "not_found"))

    def test_unreadable_frontmatter_is_reported_not_crashed_on(self):
        (self.vault / "70_meetings" / f"{MEETING}.md").write_text("---\ntype: meeting\n", encoding="utf-8")
        code, out = run(self.vault, "list", "--meeting", MEETING)
        self.assertEqual((code, out["status"]), (1, "invalid"))
        self.assertIn("frontmatter", out["problems"][0])


class TestLink(VaultTestCase):
    def test_marks_only_that_line_and_leaves_the_rest_byte_for_byte(self):
        path = self.write_meeting("- [ ] 資料を送る", "- [ ] 会場を押さえる")
        self.write_task("資料を作る")
        before = path.read_bytes()
        code, out = run(self.vault, "link", "--meeting", MEETING, "--text", "資料を送る", "--task", "資料を作る")
        self.assertEqual(code, 0)
        self.assertEqual(
            out, {"status": "linked", "path": f"70_meetings/{MEETING}.md", "text": "資料を送る", "task": "資料を作る"}
        )
        self.assertEqual(
            path.read_bytes(),
            before.replace("- [ ] 資料を送る".encode(), "- [ ] 資料を送る → [[資料を作る]]".encode()),
        )

    def test_keeps_crlf_line_endings(self):
        path = self.write_meeting("- [ ] 資料を送る", "- [ ] 会場を押さえる", newline="\r\n")
        self.write_task("T")
        before = path.read_bytes()
        run(self.vault, "link", "--meeting", MEETING, "--text", "資料を送る", "--task", "T")
        self.assertEqual(path.read_bytes(), before.replace("- [ ] 資料を送る".encode(), "- [ ] 資料を送る → [[T]]".encode()))

    def test_a_linked_item_is_no_longer_listed(self):
        self.write_meeting("- [ ] 資料を送る", "- [ ] 会場を押さえる")
        self.write_task("資料を作る")
        run(self.vault, "link", "--meeting", MEETING, "--text", "資料を送る", "--task", "資料を作る")
        self.assertEqual([i["text"] for i in run(self.vault, "list", "--meeting", MEETING)[1]["items"]], ["会場を押さえる"])

    def test_an_unknown_task_is_refused_and_the_note_is_unchanged(self):
        path = self.write_meeting("- [ ] 資料を送る")
        before = path.read_bytes()
        code, out = run(self.vault, "link", "--meeting", MEETING, "--text", "資料を送る", "--task", "無い")
        self.assertEqual((code, out), (1, {"status": "invalid", "problems": ["タスクノートがありません: 無い"]}))
        self.assertEqual(path.read_bytes(), before)

    def test_a_task_name_that_leaves_the_folder_is_refused(self):
        path = self.write_meeting("- [ ] 資料を送る")
        (self.vault / "secret.md").write_text("x", encoding="utf-8")
        before = path.read_bytes()
        code, out = run(self.vault, "link", "--meeting", MEETING, "--text", "資料を送る", "--task", "../secret")
        self.assertEqual((code, out["status"]), (1, "invalid"))
        self.assertEqual(path.read_bytes(), before)

    def test_text_that_matches_no_item_is_refused_and_the_note_is_unchanged(self):
        path = self.write_meeting("- [ ] 資料を送る")
        self.write_task("資料を作る")
        before = path.read_bytes()
        code, out = run(self.vault, "link", "--meeting", MEETING, "--text", "違う文言", "--task", "資料を作る")
        self.assertEqual((code, out["status"]), (1, "invalid"))
        self.assertEqual(path.read_bytes(), before)

    def test_a_missing_meeting_is_reported(self):
        self.write_task("資料を作る")
        code, out = run(self.vault, "link", "--meeting", "無い", "--text", "a", "--task", "資料を作る")
        self.assertEqual((code, out["status"]), (1, "not_found"))

    def test_duplicate_items_are_linked_one_at_a_time(self):
        path = self.write_meeting("- [ ] 同じ項目", "- [ ] 同じ項目")
        self.write_task("T1")
        self.write_task("T2")
        run(self.vault, "link", "--meeting", MEETING, "--text", "同じ項目", "--task", "T1")
        run(self.vault, "link", "--meeting", MEETING, "--text", "同じ項目", "--task", "T2")
        text = path.read_text(encoding="utf-8")
        self.assertLess(text.index("同じ項目 → [[T1]]"), text.index("同じ項目 → [[T2]]"))
        self.assertEqual(run(self.vault, "list", "--meeting", MEETING)[1]["items"], [])


if __name__ == "__main__":
    unittest.main()
