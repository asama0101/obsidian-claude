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
        self.write("20_tasks/期限切れ.md", task("doing", "2026-09-01", "2026-10-03"))
        self.write("20_tasks/今日期限.md", task("doing", "2026-10-01", "2026-10-04"))
        self.write("20_tasks/先.md", task("todo", "2026-10-05", "2026-10-06"))
        self.write("00_inbox/メモ.md", "x")
        ctx = self.context()
        self.assertIn("今日のデイリーノート: あり（ガントを更新した）", ctx)
        self.assertIn("タスク: 遅れ 2 件、今日が期限 1 件", ctx)
        self.assertIn("インボックス（00_inbox/）: 1 件", ctx)
        self.assertNotIn("ブランチ", ctx)

    def test_updates_the_gantt(self):
        note = self.note()
        self.write("20_tasks/作業.md", task("doing", "2026-10-04", "2026-10-06"))
        self.write("20_tasks/日付なし.md", task("todo", "", ""))
        ctx = self.context()
        self.assertIn("今日のデイリーノート: あり（ガントを更新した）", ctx)
        self.assertIn("注意: start / due が空または不正なためガントに出していないタスク: 日付なし", ctx)
        self.assertIn("作業 :active", note.read_text(encoding="utf-8"))

    def test_without_a_daily_note(self):
        ctx = self.context()
        self.assertIn("今日のデイリーノート: なし（作成は daily-start）", ctx)
        self.assertIn("タスク: 遅れ 0 件、今日が期限 0 件", ctx)
        self.assertIn("インボックス（00_inbox/）: 0 件", ctx)

    def test_an_unreadable_task_does_not_break_the_hook(self):
        (self.vault / "20_tasks" / "壊れた.md").write_bytes(b"\xff\xfe\x00")
        self.write("20_tasks/遅れ.md", task("todo", "2026-10-01", "2026-10-10"))
        self.assertIn("タスク: 遅れ 1 件", self.context())


class TestPostToolUse(HookTestCase):
    def payload(self, rel):
        return {"hook_event_name": "PostToolUse", "tool_name": "Write", "tool_input": {"file_path": str(self.vault / rel)}}

    def test_editing_a_task_updates_the_gantt_silently(self):
        note = self.note()
        self.write("20_tasks/作業.md", task("doing", "2026-10-04", "2026-10-06"))
        self.assertEqual(self.run_hook("post-tool-use", self.payload("20_tasks/作業.md")), "")
        self.assertIn("作業 :active", note.read_text(encoding="utf-8"))

    def test_files_outside_20_tasks_are_ignored(self):
        note = self.note()
        before = note.read_bytes()
        self.write("20_tasks/作業.md", task("doing", "2026-10-04", "2026-10-06"))
        for rel in ("00_inbox/メモ.md", "CLAUDE.md", "20_tasks/sub/x.md", "20_tasks/x.txt"):
            with self.subTest(rel=rel):
                self.run_hook("post-tool-use", self.payload(rel))
                self.assertEqual(note.read_bytes(), before)

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


if __name__ == "__main__":
    unittest.main()
