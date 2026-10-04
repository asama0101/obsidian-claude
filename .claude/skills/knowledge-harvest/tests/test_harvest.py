"""harvest.py のテスト（unittest、追加インストール不要）。

実行: python -m unittest discover -s .claude/skills/knowledge-harvest/tests
"""
import contextlib
import datetime as dt
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import harvest as hv  # noqa: E402

DAY = dt.date(2026, 10, 4)

DAILY = """---
type: daily
---
# 2026-10-04

## 今日のメモ
- 電話: A社から見積もりの依頼
  - 金曜まで
- 処理済み → [[既存]]
- URL https://example.com

## 振り返り
- ここは対象外
"""

TASK = """---
type: task
status: in_progress
project: "[[P]]"
---
# t

## 完了条件

## 経緯
### 2026-10-03
- 取り出し済み → [[知見]]
### 2026-10-04
- 新しい発見
- もう1つ

## 成果
"""


class TempVault(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.vault = Path(self._tmp.name)
        for d in ("20_tasks", "00_inbox", "60_daily", "10_projects/P", "10_projects/Q", "80_context"):
            (self.vault / d).mkdir(parents=True)

    def tearDown(self):
        self._tmp.cleanup()

    def write(self, rel, text, mtime=None):
        p = self.vault / rel
        p.write_text(text, encoding="utf-8")
        if mtime:
            ts = mtime.timestamp()
            os.utime(p, (ts, ts))
        return p

    def run_cmd(self, *args):
        buf = io.BytesIO()
        out = io.TextIOWrapper(buf, encoding="utf-8")
        with contextlib.redirect_stdout(out):
            hv.main(["--vault", str(self.vault), *args])
        out.flush()
        return buf.getvalue().decode("utf-8")


class TestTargets(TempVault):
    def test_memo_items_without_marks_and_tasks_updated_since_the_last_harvest(self):
        self.write("60_daily/2026-10-04.md", DAILY)
        self.write("20_tasks/新しい.md", TASK, mtime=dt.datetime(2026, 10, 4, 15))
        self.write("00_inbox/受信.md", TASK, mtime=dt.datetime(2026, 10, 4, 16))
        self.write("20_tasks/古い.md", TASK, mtime=dt.datetime(2026, 10, 4, 9))
        self.write("00_inbox/資料.md", "---\ntype: doc\n---\n", mtime=dt.datetime(2026, 10, 4, 16))
        hv.cmd_mark(self.vault, dt.datetime(2026, 10, 4, 12))
        data = json.loads(self.run_cmd("targets", "--date", "2026-10-04"))
        self.assertEqual(data["since"], "2026-10-04T12:00")
        self.assertEqual(data["memo"], ["- 電話: A社から見積もりの依頼\n  - 金曜まで", "- URL https://example.com"])
        tasks = {t["path"]: t for t in data["tasks"]}
        self.assertEqual(sorted(tasks), ["00_inbox/受信.md", "20_tasks/新しい.md"])
        self.assertEqual(tasks["20_tasks/新しい.md"]["progress"], ["### 2026-10-04", "- 新しい発見", "- もう1つ"])
        self.assertEqual(tasks["20_tasks/新しい.md"]["project"], "P")

    def test_without_a_state_the_start_of_the_day_is_used(self):
        self.write("20_tasks/昨日.md", TASK, mtime=dt.datetime(2026, 10, 3, 23))
        self.write("20_tasks/今日.md", TASK, mtime=dt.datetime(2026, 10, 4, 1))
        data = json.loads(self.run_cmd("targets", "--date", "2026-10-04"))
        self.assertEqual(data["since"], "2026-10-04T00:00")
        self.assertEqual([t["path"] for t in data["tasks"]], ["20_tasks/今日.md"])
        self.assertEqual(data["memo"], [])


PROGRESS = """# 進捗ログ

%% 書式の説明 %%

## P
### 現在の要約
- いまの状況: 順調
- 次の一手: 試す
- 課題・リスク: なし
- 最終更新: 2026-10-04
- 5行目は出さない
### ログ
#### 2026-10-04
- 進んだこと: x
"""

DECISIONS = """# 判断記録

%% 書式の説明 %%

## 方式の選択
- 日付: 2026-10-04
- プロジェクト: [[P]]
- 背景: x
- 選択肢:
  - A 案
  - B 案
- 決定: A 案にする

## 日付のない判断
- 決定:
  - 字下げした行から取る
"""

KNOWLEDGE = """# 技術知見

## 文字コード
- 日付: 2026-10-03
- 要約: UTF-8 で書く
- 内容: URL https://example.com も書ける
"""

MISTAKES = """# 失敗記録

## 消してしまった
- 日付: 2026-10-04
- 何が起きたか: 消した
- 再発防止のルール: 消す前に中身を見る

## 上書きした
- 何が起きたか: 上書きした
- 再発防止のルール:
  - 書く前に読む
  - 差分を見せる
- 追記 2026-10-05: もう一度起きた
"""


class TestIndex(TempVault):
    def test_builds_the_index_and_the_rules(self):
        self.write("10_projects/P/P.md", "---\ntype: project\nstatus: active\n---\n# P\n")
        self.write("10_projects/Q/Q.md", "---\ntype: project\nstatus: active\n---\n# Q\n")
        self.write("80_context/進捗ログ.md", PROGRESS)
        self.write("80_context/判断記録.md", DECISIONS)
        self.write("80_context/技術知見.md", KNOWLEDGE)
        self.write("80_context/失敗記録.md", MISTAKES)
        self.run_cmd("index")
        index = (self.vault / "80_context/_index.md").read_text(encoding="utf-8")
        rules = (self.vault / "80_context/_rules.md").read_text(encoding="utf-8")
        self.assertIn("- [[P]]（[[進捗ログ#P]]）\n  - いまの状況: 順調\n  - 次の一手: 試す\n"
                      "  - 課題・リスク: なし\n  - 最終更新: 2026-10-04\n", index)
        self.assertNotIn("5行目", index)
        self.assertIn("- [[Q]]: 進捗ログなし", index)
        self.assertIn("- [[判断記録#方式の選択]]（2026-10-04, P）: A 案にする", index)
        self.assertIn("- [[判断記録#日付のない判断]]: 字下げした行から取る", index)
        self.assertIn("- [[技術知見#文字コード]]（2026-10-03）: UTF-8 で書く", index)
        self.assertIn("- [[失敗記録#消してしまった]]（2026-10-04）: 消した", index)
        self.assertIn("- 消す前に中身を見る（[[失敗記録#消してしまった]]）", rules)
        self.assertIn("- 書く前に読む（[[失敗記録#上書きした]]）\n- 差分を見せる（[[失敗記録#上書きした]]）\n", rules)
        self.assertNotIn("もう一度起きた", rules)
        self.assertNotIn("書式の説明", index)

    def test_empty_context(self):
        self.run_cmd("index")
        index = (self.vault / "80_context/_index.md").read_text(encoding="utf-8")
        for title in ("判断記録", "技術知見", "失敗記録"):
            self.assertIn(f"## {title}\n- なし", index)
        self.assertIn("## 進行中のプロジェクト（現在の要約）\n- なし", index)
        self.assertIn("- なし", (self.vault / "80_context/_rules.md").read_text(encoding="utf-8"))

    def test_files_without_entries(self):
        self.write("80_context/判断記録.md", "# 判断記録\n\n%% 書式の説明 %%\n")
        self.run_cmd("index")
        index = (self.vault / "80_context/_index.md").read_text(encoding="utf-8")
        self.assertIn("## 判断記録\n- なし", index)


if __name__ == "__main__":
    unittest.main()
