"""vaultkit.frontmatter のテスト（旧 Vault の pytest 版を unittest に移植）。"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vaultkit import frontmatter  # noqa: E402
from vaultkit.frontmatter import FrontmatterError  # noqa: E402


class TestRoundTrip(unittest.TestCase):
    def test_scalar_round_trips(self):
        for value in [
            "plain", "[[Pythonのスキルアップ]]", "a: b", "# tag", "true", "123", "10:30", "日本語 テキスト",
            'say "hi"', "back\\slash", " leading", "trailing ", "[x]", "2026-10-03", "-dash", "",
        ]:
            with self.subTest(value=value):
                text = frontmatter.dump({"k": value}, "")
                self.assertEqual(frontmatter.parse(text)[0], {"k": value})

    def test_list_round_trips_with_links_and_japanese(self):
        meta = {"attendees": ["[[山田]]", "佐藤 太郎", "a: b"]}
        self.assertEqual(frontmatter.parse(frontmatter.dump(meta, ""))[0], meta)

    def test_canonical_text_is_stable(self):
        text = '---\ntype: task\nproject: "[[A]]"\nstart: 2026-10-03\nattendees:\n  - X\n  - Y\n---\n\n## 手順\n- [ ] a\n'
        self.assertEqual(frontmatter.dump(*frontmatter.parse(text)), text)


class TestDump(unittest.TestCase):
    def test_writes_empty_value_without_quotes(self):
        self.assertEqual(frontmatter.dump({"project": "", "type": "task"}, ""), "---\nproject:\ntype: task\n---\n")

    def test_quotes_links_so_obsidian_does_not_read_a_nested_list(self):
        self.assertEqual(frontmatter.dump({"project": "[[A]]"}, ""), '---\nproject: "[[A]]"\n---\n')

    def test_keeps_dates_unquoted(self):
        self.assertEqual(frontmatter.dump({"start": "2026-10-03"}, ""), "---\nstart: 2026-10-03\n---\n")

    def test_rejects_value_with_newline(self):
        with self.assertRaises(FrontmatterError):
            frontmatter.dump({"k": "a\nb"}, "")

    def test_rejects_non_string_value(self):
        with self.assertRaises(FrontmatterError):
            frontmatter.dump({"k": 1}, "")

    def test_quotes_a_value_ending_in_a_colon(self):
        text = frontmatter.dump({"k": "a/b:", "tags": ["x/y:"]}, "")
        self.assertIn('k: "a/b:"', text)
        self.assertIn('  - "x/y:"', text)
        self.assertEqual(frontmatter.parse(text)[0], {"k": "a/b:", "tags": ["x/y:"]})


class TestParse(unittest.TestCase):
    def test_returns_body_after_closing_fence(self):
        self.assertEqual(frontmatter.parse("---\ntype: task\n---\n\n## 手順\n"), ({"type": "task"}, "\n## 手順\n"))

    def test_text_without_frontmatter(self):
        self.assertEqual(frontmatter.parse("## 手順\n"), ({}, "## 手順\n"))

    def test_accepts_crlf(self):
        meta, body = frontmatter.parse('---\r\ntype: task\r\nproject: "[[A]]"\r\n---\r\n本文\r\n')
        self.assertEqual(meta, {"type": "task", "project": "[[A]]"})
        self.assertEqual(body, "本文\n")

    def test_accepts_utf8_bom(self):
        meta, body = frontmatter.parse("﻿---\r\ntype: task\r\nstatus: todo\r\n---\r\n本文\r\n")
        self.assertEqual(meta, {"type": "task", "status": "todo"})
        self.assertEqual(body, "本文\n")

    def test_reads_inline_list_and_block_list(self):
        meta, _ = frontmatter.parse('---\na: [x, "y, z"]\nb:\n  - p\n  - q\n---\n')
        self.assertEqual(meta, {"a": ["x", "y, z"], "b": ["p", "q"]})

    def test_reads_empty_inline_list(self):
        self.assertEqual(frontmatter.parse("---\ntags: []\n---\n")[0], {"tags": []})

    def test_keeps_unquoted_link_as_string(self):
        self.assertEqual(frontmatter.parse("---\nproject: [[A]]\n---\n")[0], {"project": "[[A]]"})

    def test_reads_bare_key_as_empty_string(self):
        self.assertEqual(frontmatter.parse("---\nproject:\nstart:\n---\n")[0], {"project": "", "start": ""})

    def test_keeps_colon_in_value(self):
        meta, _ = frontmatter.parse("---\nsource: https://example.com/a?b=1\n---\n")
        self.assertEqual(meta, {"source": "https://example.com/a?b=1"})

    def test_rejects_unclosed_frontmatter(self):
        with self.assertRaises(FrontmatterError):
            frontmatter.parse("---\ntype: task\n本文\n")

    def test_rejects_duplicate_keys(self):
        with self.assertRaises(FrontmatterError):
            frontmatter.parse("---\na: x\na: y\n---\n")

    def test_rejects_unreadable_line(self):
        with self.assertRaises(FrontmatterError):
            frontmatter.parse("---\n- orphan item\n---\n")

    def test_rejects_plain_scalars_that_yaml_reads_as_non_strings(self):
        for raw in ["true", "False", "null", "~", "yes", "3", "-1", "1.5"]:
            with self.subTest(raw=raw), self.assertRaises(FrontmatterError):
                frontmatter.parse(f"---\nk: {raw}\n---\n")

    def test_rejects_trailing_comments_and_broken_quotes(self):
        for raw in ['"[[A]]" # 仮', "値 # コメント", '"unclosed', "'a' b"]:
            with self.subTest(raw=raw), self.assertRaises(FrontmatterError):
                frontmatter.parse(f"---\nk: {raw}\n---\n")

    def test_quoted_non_string_looking_values_are_kept_as_strings(self):
        meta, _ = frontmatter.parse("---\na: \"true\"\nb: \"3\"\nc: 'null'\n---\n")
        self.assertEqual(meta, {"a": "true", "b": "3", "c": "null"})


class TestUpdate(unittest.TestCase):
    def test_changes_value_keeps_order_and_body(self):
        updated = frontmatter.update("---\ntype: task\nstatus: todo\n---\n\n本文\n", {"status": "doing", "due": "2026-10-05"})
        self.assertEqual(updated, "---\ntype: task\nstatus: doing\ndue: 2026-10-05\n---\n\n本文\n")

    def test_adds_frontmatter_to_text_without_it(self):
        self.assertEqual(frontmatter.update("本文\n", {"type": "task"}), "---\ntype: task\n---\n本文\n")

    def test_refuses_to_rewrite_a_note_it_cannot_read_faithfully(self):
        with self.assertRaises(FrontmatterError):
            frontmatter.update("---\ndone: true\nstatus: todo\n---\n", {"status": "doing"})


if __name__ == "__main__":
    unittest.main()
