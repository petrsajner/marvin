"""Test-and-fix report parsing and prompt construction."""
import unittest

from harness.changes import ChangeJournal
from harness.test_fix import (MAX_ROUNDS, build_test_fix_prompt,
                              split_test_report)


class _StubJournal:
    def summary(self):
        return {"task_id": "t1", "label": "",
                "files": [{"path": "index.html", "change": "modified",
                           "changed": True}]}

    change_card = ChangeJournal.change_card


SAMPLE = (
    "All done.\n"
    "CHANGES:\n"
    "- index.html | added the Start button\n"
    "TESTREPORT:\n"
    "- Start button opens the game | ok\n"
    "- Score resets on reload | problem: the score keeps the old value\n"
)


class TestFixTests(unittest.TestCase):
    def test_prompt_names_the_target_and_bounds_the_rounds(self):
        prompt = build_test_fix_prompt("C:/apps/index.html")
        self.assertIn("C:/apps/index.html", prompt)
        self.assertIn(f"at most {MAX_ROUNDS} test rounds", prompt)
        self.assertIn("browser_console", prompt)
        self.assertIn("TESTREPORT:", prompt)

    def test_report_rows_carry_verdicts_and_are_stripped(self):
        kept, rows = split_test_report(SAMPLE)
        self.assertNotIn("TESTREPORT", kept)
        self.assertIn("CHANGES:", kept)
        self.assertEqual(len(rows), 2)
        self.assertTrue(rows[0]["ok"])
        self.assertFalse(rows[1]["ok"])
        self.assertIn("old value", rows[1]["note"])

    def test_change_card_stops_before_the_test_report(self):
        kept, rows = _StubJournal().change_card(SAMPLE)
        self.assertNotIn("CHANGES:", kept)
        self.assertIn("TESTREPORT:", kept)  # left intact for the report parser
        self.assertEqual(rows[0]["path"], "index.html")
        self.assertEqual(rows[0]["note"], "added the Start button")
        after, checks = split_test_report(kept)
        self.assertEqual(len(checks), 2)
        self.assertNotIn("TESTREPORT", after)

    def test_missing_block_is_no_card(self):
        text = "Just an answer."
        self.assertEqual(split_test_report(text), (text, []))


if __name__ == "__main__":
    unittest.main()
