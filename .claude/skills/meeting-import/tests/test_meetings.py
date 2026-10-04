"""vaultkit.meetings のテスト（旧 Vault の pytest 版を unittest に移植し、印の形式を `→ [[タスク名]]` に変えた）。"""
import sys
import unittest
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_DIR))

from vaultkit import meetings  # noqa: E402

TEXT = "\n".join(
    [
        "---",
        "type: meeting",
        "date: 2026-10-05",
        "---",
        "",
        "## 目的・議題",
        "- [ ] 議題の節は対象外",
        "",
        "## アクションアイテム",
        "- [ ] 資料を送る 期限:2026-10-10",
        "- [x] 済んだ項目",
        "- [X] 大文字の済んだ項目",
        "- [ ] ",
        "- [ ] 処理済みの項目 → [[済み]]",
        "- [ ] [[旧形式の済み]]",
        "- 見積もりを出す",
        "  - [ ] 子の項目",
        "- [ ] [[別]]の件を確認する",
        "",
        "## 参照ドキュメント",
        "- [ ] ここは対象外",
    ]
)
UNRESOLVED = ["資料を送る 期限:2026-10-10", "見積もりを出す", "子の項目", "[[別]]の件を確認する"]


class TestUnresolvedActions(unittest.TestCase):
    def test_returns_unresolved_items_in_order(self):
        self.assertEqual(meetings.unresolved_actions(TEXT), UNRESOLVED)

    def test_items_with_the_new_or_old_mark_are_resolved(self):
        for line in ["- [ ] a → [[A]]", "- [ ] a 期限:2026-10-10 → [[A|別名]]", "- [ ] [[A]]", "- [[A]]", "  - [ ] [[A#見出し]]  "]:
            with self.subTest(line=line):
                self.assertEqual(meetings.unresolved_actions(f"## アクションアイテム\n{line}\n"), [])

    def test_an_item_that_merely_contains_a_link_is_still_unresolved(self):
        for item in ["[[A]]と[[B]]を比べる", "宿を調べる[[A]]", "[[A]] [[B]]", "→ [[A]]の続きを書く"]:
            with self.subTest(item=item):
                self.assertEqual(meetings.unresolved_actions(f"## アクションアイテム\n- [ ] {item}\n"), [item])

    def test_ignores_items_in_other_sections(self):
        items = meetings.unresolved_actions(TEXT)
        self.assertNotIn("議題の節は対象外", items)
        self.assertNotIn("ここは対象外", items)

    def test_missing_section_gives_nothing(self):
        self.assertEqual(meetings.unresolved_actions("## 議事・決定事項\n- [ ] a\n"), [])

    def test_section_at_the_end_of_the_file(self):
        self.assertEqual(meetings.unresolved_actions("## アクションアイテム\n- [ ] a"), ["a"])

    def test_crlf_text(self):
        self.assertEqual(meetings.unresolved_actions("## アクションアイテム\r\n- [ ] a\r\n- [ ] b → [[B]]\r\n"), ["a"])


class TestParseItem(unittest.TestCase):
    def test_splits_the_due_date(self):
        self.assertEqual(
            meetings.parse_item("資料を送る 期限:2026-10-10"),
            {"text": "資料を送る 期限:2026-10-10", "content": "資料を送る", "due": "2026-10-10"},
        )

    def test_due_is_optional_and_at_signs_are_kept(self):
        self.assertEqual(meetings.parse_item("見積もり"), {"text": "見積もり", "content": "見積もり", "due": ""})
        self.assertEqual(meetings.parse_item("a@example.com に送る")["content"], "a@example.com に送る")

    def test_a_malformed_due_is_left_in_the_content(self):
        item = meetings.parse_item("送る 期限:来週")
        self.assertEqual((item["due"], item["content"]), ("", "送る 期限:来週"))


class TestLinkAction(unittest.TestCase):
    def test_appends_the_mark_to_only_that_line_and_leaves_it_unchecked(self):
        updated = meetings.link_action(TEXT, "資料を送る 期限:2026-10-10", "資料を作る")
        before, after = TEXT.split("\n"), updated.split("\n")
        self.assertEqual(after[9], "- [ ] 資料を送る 期限:2026-10-10 → [[資料を作る]]")
        self.assertEqual(after[:9], before[:9])
        self.assertEqual(after[10:], before[10:])

    def test_a_linked_item_no_longer_appears_as_unresolved(self):
        updated = meetings.link_action(TEXT, "資料を送る 期限:2026-10-10", "x")
        self.assertEqual(meetings.unresolved_actions(updated), UNRESOLVED[1:])

    def test_a_plain_bullet_and_an_indented_item_keep_their_shape(self):
        updated = meetings.link_action(TEXT, "見積もりを出す", "x")
        self.assertIn("\n- 見積もりを出す → [[x]]\n", updated)
        updated = meetings.link_action(TEXT, "子の項目", "y")
        self.assertIn("\n  - [ ] 子の項目 → [[y]]\n", updated)

    def test_still_works_after_lines_were_inserted_above(self):
        shifted = TEXT.replace("## 目的・議題", "## 目的・議題\n- 新しい議題\n- もう1つ")
        self.assertIn("- [ ] 資料を送る 期限:2026-10-10 → [[x]]", meetings.link_action(shifted, "資料を送る 期限:2026-10-10", "x"))

    def test_only_the_first_of_duplicate_items_is_marked(self):
        text = "## アクションアイテム\n- [ ] a\n- [ ] a\n"
        self.assertEqual(meetings.link_action(text, "a", "x"), "## アクションアイテム\n- [ ] a → [[x]]\n- [ ] a\n")

    def test_surrounding_whitespace_in_the_item_is_ignored(self):
        self.assertIn("→ [[x]]", meetings.link_action(TEXT, "  見積もりを出す ", "x"))

    def test_keeps_crlf_line_endings(self):
        text = "## アクションアイテム\r\n- [ ] a\r\n- [ ] b\r\n"
        self.assertEqual(meetings.link_action(text, "a", "x"), "## アクションアイテム\r\n- [ ] a → [[x]]\r\n- [ ] b\r\n")

    def test_rejects_items_that_are_not_unresolved_in_the_section(self):
        for item in ["存在しない", "", "処理済みの項目 → [[済み]]", "済んだ項目", "議題の節は対象外", "ここは対象外"]:
            with self.subTest(item=item), self.assertRaises(ValueError):
                meetings.link_action(TEXT, item, "x")


class TestProjectName(unittest.TestCase):
    def test_extracts_the_name_from_a_link(self):
        for value, name in [("[[P]]", "P"), ("[[P|別名]]", "P"), (" [[P#見出し]] ", "P"), ("P", "P"), ("", "")]:
            with self.subTest(value=value):
                self.assertEqual(meetings.project_name(value), name)


class TestTemplate(unittest.TestCase):
    def test_the_meeting_template_has_the_actions_section_and_no_unresolved_item(self):
        # 書式の見本はコメント（%% … %%）なので、項目として拾わない
        template = SKILL_DIR.parents[2] / "90_system" / "templates" / "meeting.md"
        text = template.read_text(encoding="utf-8")
        self.assertIn(meetings.ACTIONS_HEADING, text)
        self.assertEqual(meetings.unresolved_actions(text), [])


if __name__ == "__main__":
    unittest.main()
