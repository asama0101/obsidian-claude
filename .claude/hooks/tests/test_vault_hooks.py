"""vault_hooks.py のテスト（unittest、追加インストール不要）。

実行: python -m unittest discover -s .claude/hooks/tests
一時フォルダに Vault を作り、環境変数 CLAUDE_PROJECT_DIR / VAULT_TODAY で差し替えて、
フックを実際の呼び出しと同じく、標準入力に JSON を渡して実行する。
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "vault_hooks.py"
TODAY = "2026-10-04"
MARKERS = "## ガントチャート\n<!-- gantt:start -->\n<!-- gantt:end -->\n"


def task(status="todo", start="2026-10-04", due="2026-10-10", completed=""):
    return (
        f"---\ntype: task\nstatus: {status}\nproject: \"[[P]]\"\nstart: {start}\ndue: {due}\n"
        f"completed: {completed}\nmemo:\ncreated: 2026-10-01\ntags: []\n---\n# t\n"
    )


class HookTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.vault = Path(self._tmp.name)
        for d in ("20_tasks", "60_daily", "00_inbox"):
            (self.vault / d).mkdir()
        (self.vault / "00_inbox" / ".gitkeep").write_text("", encoding="utf-8")

    def tearDown(self):
        self._tmp.cleanup()

    def write(self, rel, text):
        path = self.vault / rel
        path.write_text(text, encoding="utf-8")
        return path

    def note(self):
        return self.write(f"60_daily/{TODAY}.md", f"# {TODAY}\n\n{MARKERS}\n## 今日のメモ\n")

    def run_hook(self, command, payload=None):
        env = {**os.environ, "CLAUDE_PROJECT_DIR": str(self.vault), "VAULT_TODAY": TODAY}
        r = subprocess.run(
            [sys.executable, str(SCRIPT), command],
            input=json.dumps(payload or {}).encode("utf-8"),
            capture_output=True,
            env=env,
        )
        self.assertEqual(r.returncode, 0, r.stderr.decode("utf-8", "replace"))
        return r.stdout.decode("utf-8")

    def context(self):
        out = json.loads(self.run_hook("session-start", {"hook_event_name": "SessionStart"}))
        self.assertEqual(out["hookSpecificOutput"]["hookEventName"], "SessionStart")
        return out["hookSpecificOutput"]["additionalContext"]


class TestSessionStart(HookTestCase):
    def test_reports_status(self):
        self.note()
        self.write("20_tasks/遅れ.md", task("todo", "2026-10-01", "2026-10-10"))
        self.write("20_tasks/期限切れ.md", task("in_progress", "2026-09-01", "2026-10-03"))
        self.write("20_tasks/今日期限.md", task("in_progress", "2026-10-01", "2026-10-04"))
        self.write("20_tasks/先.md", task("todo", "2026-10-05", "2026-10-06"))
        self.write("00_inbox/メモ.md", "x")
        self.write("00_inbox/思いつき.md", task("idea", "", ""))
        (self.vault / "00_inbox" / "grilling").mkdir()
        ctx = self.context()
        self.assertIn("今日のデイリーノート: あり（ガントを更新した）", ctx)
        self.assertIn("タスク: 遅れ 2 件、今日が期限 1 件、idea 1 件", ctx)
        self.assertIn("インボックス（00_inbox/）: タスク 1 件、その他 2 件", ctx)
        self.assertNotIn("ブランチ", ctx)

    def test_updates_the_gantt(self):
        note = self.note()
        self.write("20_tasks/作業.md", task("in_progress", "2026-10-04", "2026-10-06"))
        self.write("20_tasks/日付なし.md", task("todo", "", ""))
        ctx = self.context()
        self.assertIn("今日のデイリーノート: あり（ガントを更新した）", ctx)
        self.assertIn("注意: start / due が空または不正なためガントに出していないタスク: 日付なし", ctx)
        self.assertIn("作業 :active", note.read_text(encoding="utf-8"))

    def test_without_a_daily_note(self):
        ctx = self.context()
        self.assertIn("今日のデイリーノート: なし（作成は daily-start）", ctx)
        self.assertIn("タスク: 遅れ 0 件、今日が期限 0 件、idea 0 件", ctx)
        self.assertIn("インボックス（00_inbox/）: タスク 0 件、その他 0 件", ctx)

    def test_an_unreadable_task_does_not_break_the_hook(self):
        (self.vault / "20_tasks" / "壊れた.md").write_bytes(b"\xff\xfe\x00")
        self.write("20_tasks/遅れ.md", task("todo", "2026-10-01", "2026-10-10"))
        self.assertIn("タスク: 遅れ 1 件", self.context())


class TestPostToolUse(HookTestCase):
    def payload(self, rel):
        return {"hook_event_name": "PostToolUse", "tool_name": "Write", "tool_input": {"file_path": str(self.vault / rel)}}

    def test_editing_a_task_updates_the_gantt_silently(self):
        note = self.note()
        self.write("20_tasks/作業.md", task("in_progress", "2026-10-04", "2026-10-06"))
        self.assertEqual(self.run_hook("post-tool-use", self.payload("20_tasks/作業.md")), "")
        self.assertIn("作業 :active", note.read_text(encoding="utf-8"))

    def test_files_outside_20_tasks_are_ignored(self):
        note = self.note()
        before = note.read_bytes()
        self.write("20_tasks/作業.md", task("in_progress", "2026-10-04", "2026-10-06"))
        for rel in ("30_knowledge/メモ.md", "CLAUDE.md", "20_tasks/sub/x.md", "20_tasks/x.txt", "00_inbox/sub/x.md"):
            with self.subTest(rel=rel):
                self.run_hook("post-tool-use", self.payload(rel))
                self.assertEqual(note.read_bytes(), before)

    def test_editing_a_task_in_the_inbox_updates_the_gantt(self):
        note = self.note()
        self.write("00_inbox/受信.md", task("in_progress", "2026-10-04", "2026-10-06"))
        self.assertEqual(self.run_hook("post-tool-use", self.payload("00_inbox/受信.md")), "")
        self.assertIn("受信 :active", note.read_text(encoding="utf-8"))

    def test_without_a_daily_note_nothing_happens(self):
        self.write("20_tasks/作業.md", task())
        self.assertEqual(self.run_hook("post-tool-use", self.payload("20_tasks/作業.md")), "")
        self.assertFalse((self.vault / "60_daily" / f"{TODAY}.md").exists())

    def test_a_note_without_markers_is_left_alone(self):
        note = self.write(f"60_daily/{TODAY}.md", "# マーカーなし\n")
        self.write("20_tasks/作業.md", task())
        self.assertEqual(self.run_hook("post-tool-use", self.payload("20_tasks/作業.md")), "")
        self.assertEqual(note.read_text(encoding="utf-8"), "# マーカーなし\n")

    def test_broken_input_does_not_fail(self):
        env = {**os.environ, "CLAUDE_PROJECT_DIR": str(self.vault), "VAULT_TODAY": TODAY}
        r = subprocess.run([sys.executable, str(SCRIPT), "post-tool-use"], input=b"not json", capture_output=True, env=env)
        self.assertEqual((r.returncode, r.stdout), (0, b""))


class TestNotifications(HookTestCase):
    def setUp(self):
        super().setUp()
        self.state = self.vault / "_state"
        self.log = self.vault / "_notify.log"

    def run_hook(self, command, payload=None):
        env = {**os.environ, "CLAUDE_PROJECT_DIR": str(self.vault), "VAULT_TODAY": TODAY,
               "VAULT_HOOK_STATE": str(self.state), "VAULT_NOTIFY_LOG": str(self.log)}
        r = subprocess.run([sys.executable, str(SCRIPT), command], input=json.dumps(payload or {}).encode("utf-8"),
                           capture_output=True, env=env)
        self.assertEqual(r.returncode, 0, r.stderr.decode("utf-8", "replace"))
        return r.stdout.decode("utf-8")

    def toasts(self):
        if not self.log.exists():
            return []
        return [json.loads(l) for l in self.log.read_text(encoding="utf-8").splitlines()]

    def edit(self, rel, session="s1"):
        self.run_hook("post-tool-use", {"session_id": session, "tool_name": "Write",
                                        "tool_input": {"file_path": str(self.vault / rel)}})

    def test_stop_lists_the_files_edited_in_the_turn_and_clears_them(self):
        for rel in ("30_knowledge/a.md", "30_knowledge/b.md", "30_knowledge/a.md", "70_meetings/c.md", "50_documents/d.md"):
            self.edit(rel)
        self.edit("30_knowledge/other.md", session="s2")
        self.assertEqual(self.run_hook("stop", {"session_id": "s1"}), "")
        [toast] = self.toasts()
        self.assertEqual(toast["title"], "Claude Code: 完了")
        self.assertEqual(toast["lines"][0], "30_knowledge/a.md, 30_knowledge/b.md, 70_meetings/c.md ほか 1 件")
        self.assertIn("4 件", toast["lines"][1])
        self.assertTrue(toast["launch"].startswith("obsidian://open?vault="))
        self.assertTrue(toast["launch"].endswith("&file=30_knowledge/a"))
        self.run_hook("stop", {"session_id": "s1"})
        self.assertEqual(self.toasts()[-1]["lines"], ["ファイルの変更はありません"])

    def test_notification_says_waiting(self):
        self.run_hook("notification", {"session_id": "s1", "message": "Claude needs your permission to use Bash"})
        self.assertEqual(self.toasts(), [{"title": "Claude Code: 確認待ち",
                                          "lines": ["Claude needs your permission to use Bash"], "launch": ""}])


if __name__ == "__main__":
    unittest.main()
