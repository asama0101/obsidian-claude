"""daily_start.py のテスト（unittest、追加インストール不要）。

実行: python -m unittest discover -s .claude/skills/daily-start/tests
"""
import datetime as dt
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import daily_start as ds  # noqa: E402

TODAY = dt.date(2026, 10, 4)
D = dt.date.fromisoformat


def task(status="todo", start="2026-10-04", due="2026-10-10", completed="", project="[[P]]", body=""):
    return (
        f"---\ntype: task\nstatus: {status}\nproject: \"{project}\"\nstart: {start}\ndue: {due}\n"
        f"completed: {completed}\nmemo:\ncreated: 2026-10-01\ntags: []\n---\n# t\n{body}"
    )


class TempVault(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.vault = Path(self._tmp.name)
        (self.vault / "20_tasks").mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def write_task(self, name, text):
        (self.vault / "20_tasks" / f"{name}.md").write_text(text, encoding="utf-8")


class TestIsLate(unittest.TestCase):
    def test_todo_is_late_when_start_is_on_or_before_today(self):
        self.assertTrue(ds.is_late("todo", D("2026-10-04"), D("2026-10-10"), TODAY))
        self.assertTrue(ds.is_late("todo", D("2026-10-01"), D("2026-10-10"), TODAY))
        self.assertFalse(ds.is_late("todo", D("2026-10-05"), D("2026-10-10"), TODAY))

    def test_in_progress_waiting_and_requested_are_late_when_due_is_before_today(self):
        for status in ("in_progress", "waiting", "requested"):
            with self.subTest(status=status):
                self.assertTrue(ds.is_late(status, D("2026-10-01"), D("2026-10-03"), TODAY))
                self.assertFalse(ds.is_late(status, D("2026-10-01"), D("2026-10-04"), TODAY))

    def test_done_and_inactive_states_are_never_late(self):
        for status in ("done", "idea", "shelved", "cancelled"):
            with self.subTest(status=status):
                self.assertFalse(ds.is_late(status, D("2026-09-01"), D("2026-09-02"), TODAY))


class TestDashboardGroup(unittest.TestCase):
    """daily-tasks.base の formula「区分」と同じ区分になること。"""

    def group(self, **kw):
        props = {"status": "todo", "start": "", "due": "", "completed": ""}
        props.update(kw)
        return ds.dashboard_group(props, TODAY)

    def test_groups(self):
        cases = [
            (dict(status="todo", start="2026-10-04", due="2026-10-10"), "遅れ"),
            (dict(status="todo", start="2026-10-05", due="2026-10-04"), "今日が期限"),
            (dict(status="todo", start="2026-10-05", due="2026-10-10"), None),
            (dict(status="in_progress", start="2026-10-01", due="2026-10-03"), "遅れ"),
            (dict(status="in_progress", start="2026-10-01", due="2026-10-04"), "今日が期限"),
            (dict(status="in_progress", start="2026-10-01", due="2026-10-10"), "作業中"),
            (dict(status="requested", start="2026-10-01", due="2026-10-10"), "依頼中"),
            (dict(status="requested", start="2026-10-01", due="2026-10-03"), "遅れ"),
            (dict(status="waiting", start="2026-10-01", due="2026-10-10"), "保留"),
            (dict(status="waiting", start="2026-10-01", due="2026-10-01"), "遅れ"),
            (dict(status="done", completed="2026-10-04"), "今日完了"),
            (dict(status="done", completed="2026-10-03"), None),
            (dict(status="todo"), None),
            (dict(status="in_progress"), "作業中"),
            (dict(status="idea", start="2026-10-01", due="2026-10-04"), None),
            (dict(status="shelved", start="2026-10-01", due="2026-10-04"), None),
            (dict(status="cancelled", start="2026-10-01", due="2026-10-04"), None),
        ]
        for props, expected in cases:
            with self.subTest(props=props):
                self.assertEqual(self.group(**props), expected)


class TestParseChecklist(unittest.TestCase):
    def names(self, body):
        return [m["name"] for m in ds.parse_checklist(task(body=body))]

    def test_only_items_between_the_markers_are_picked(self):
        body = (
            "## 完了条件\n- [ ] 外の項目\n## チェックリスト\n"
            f"{ds.GANTT_START}\n- [ ] 資料を集める 期限:2026-10-10\n- [x] 済んだ項目\n{ds.GANTT_END}\n"
            "- [ ] 囲いの後\n## 経緯\n- [ ] 経緯の項目\n"
        )
        items = ds.parse_checklist(task(body=body))
        self.assertEqual(items, [
            {"name": "資料を集める", "due": D("2026-10-10"), "done": False},
            {"name": "済んだ項目", "due": None, "done": True},
        ])

    def test_several_blocks_are_all_picked(self):
        body = f"{ds.GANTT_START}\n- [ ] a\n{ds.GANTT_END}\n- [ ] 外\n{ds.GANTT_START}\n- [ ] b\n{ds.GANTT_END}\n"
        self.assertEqual(self.names(body), ["a", "b"])

    def test_nothing_is_picked_without_markers_or_with_an_unclosed_start(self):
        self.assertEqual(self.names("## チェックリスト\n- [ ] a\n"), [])
        self.assertEqual(self.names(f"{ds.GANTT_START}\n- [ ] a\n"), [])

    def test_crlf_line_endings(self):
        body = f"{ds.GANTT_START}\r\n- [ ] a 期限:2026-10-10\r\n{ds.GANTT_END}\r\n"
        self.assertEqual(ds.parse_checklist(task(body=body)), [{"name": "a", "due": D("2026-10-10"), "done": False}])


class TestCollectGanttTasks(TempVault):
    def names(self, problems=None):
        return [t["name"] for t in ds.collect_gantt_tasks(self.vault, TODAY, problems)]

    def test_shows_open_tasks_in_range(self):
        self.write_task("A", task("in_progress", "2026-10-01", "2026-10-10"))
        self.write_task("B", task("todo", "2026-10-05", "2026-10-06"))
        self.assertEqual(self.names(), ["←A", "B"])

    def test_hides_late_todo_and_overdue_open_tasks(self):
        self.write_task("遅れtodo", task("todo", "2026-10-01", "2026-10-10"))
        self.write_task("期限切れ", task("in_progress", "2026-09-01", "2026-10-03"))
        self.assertEqual(self.names(), [])

    def test_a_todo_starting_today_is_shown_as_late(self):
        self.write_task("今日", task("todo", "2026-10-04", "2026-10-05"))
        [t] = ds.collect_gantt_tasks(self.vault, TODAY)
        self.assertTrue(t["late"])

    def test_done_tasks_only_when_completed_today(self):
        self.write_task("今日完了", task("done", "2026-10-01", "2026-10-04", completed="2026-10-04"))
        self.write_task("昨日完了", task("done", "2026-10-01", "2026-10-03", completed="2026-10-03"))
        self.write_task("日付不正", task("done", "2026-10-01", "2026-10-04", completed="2026-13-01"))
        self.assertEqual(self.names(), ["←今日完了"])  # 開始が左端より前なので ← が付く

    def test_waiting_and_requested_get_a_mark(self):
        self.write_task("待ち", task("waiting", "2026-10-04", "2026-10-08"))
        self.write_task("依頼", task("requested", "2026-10-04", "2026-10-08"))
        self.assertEqual(sorted(self.names()), ["⏸待ち", "✉依頼"])

    def test_idea_shelved_and_cancelled_are_hidden_even_without_dates(self):
        self.write_task("思いつき", task("idea", "", ""))
        self.write_task("塩漬け", task("shelved", "2026-10-04", "2026-10-08"))
        self.write_task("中止", task("cancelled", "2026-10-04", "2026-10-08"))
        problems = []
        self.assertEqual(self.names(problems), [])
        self.assertEqual(problems, [])

    def test_tasks_in_the_inbox_are_included(self):
        (self.vault / "00_inbox").mkdir()
        (self.vault / "00_inbox" / "受信.md").write_text(task("todo", "2026-10-05", "2026-10-06"), encoding="utf-8")
        (self.vault / "00_inbox" / "資料.md").write_text("---\ntype: doc\n---\n", encoding="utf-8")
        self.assertEqual(self.names(), ["受信"])

    def test_undated_open_tasks_are_skipped_and_reported(self):
        self.write_task("日付なし", task("todo", "", ""))
        self.write_task("期限なし", task("in_progress", "2026-10-04", ""))
        self.write_task("不正", task("todo", "2026-10-04", "2026-02-30"))
        self.write_task("完了で日付なし", task("done", "", "", completed="2026-10-04"))
        problems = []
        self.assertEqual(self.names(problems), [])
        self.assertEqual(problems, ["注意: start / due が空または不正なためガントに出していないタスク: 不正, 日付なし, 期限なし"])

    def test_an_unreadable_note_does_not_stop_the_others(self):
        (self.vault / "20_tasks" / "壊れた.md").write_bytes(b"---\ntype: task\n\xff\xfe\x00broken\n---\n")
        self.write_task("正常", task("in_progress", "2026-10-04", "2026-10-06"))
        problems = []
        self.assertEqual(self.names(problems), ["正常"])
        self.assertEqual(len(problems), 1)
        self.assertTrue(problems[0].startswith("注意: 読めないためガントに出していないタスク: 壊れた（UnicodeDecodeError"))

    def test_non_task_notes_are_ignored_silently(self):
        self.write_task("メモ", "---\ntype: knowledge\n---\n")
        problems = []
        self.assertEqual(self.names(problems), [])
        self.assertEqual(problems, [])

    def test_no_problems_list_means_nothing_is_reported(self):
        self.write_task("日付なし", task("todo", "", ""))
        self.assertEqual(self.names(), [])


class TestUpdateGantt(TempVault):
    def test_rewrites_only_between_the_markers_and_returns_problems(self):
        self.write_task("A", task("in_progress", "2026-10-04", "2026-10-06"))
        self.write_task("日付なし", task("todo", "", ""))
        note = self.vault / "note.md"
        note.write_text(f"前\n{ds.GANTT_START}\n古い\n{ds.GANTT_END}\n後\n", encoding="utf-8")
        problems = ds.update_gantt(note, self.vault, TODAY)
        text = note.read_text(encoding="utf-8")
        self.assertTrue(text.startswith(f"前\n{ds.GANTT_START}\n```mermaid\n"))
        self.assertTrue(text.endswith(f"```\n{ds.GANTT_END}\n後\n"))
        self.assertIn("    A :active, t1, 2026-10-04, 2026-10-07", text)
        self.assertEqual(len(problems), 1)

    def test_a_note_without_markers_is_left_alone(self):
        note = self.vault / "note.md"
        note.write_text("本文\n", encoding="utf-8")
        self.assertIsNone(ds.update_gantt(note, self.vault, TODAY))
        self.assertEqual(note.read_text(encoding="utf-8"), "本文\n")


if __name__ == "__main__":
    unittest.main()
