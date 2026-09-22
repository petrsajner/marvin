"""Served-app URL discovery and the opt-in plan-first note stay wired."""
import unittest

from harness.internal_messages import INTERNAL_USER_PREFIXES
from harness.processes import ManagedProcess, served_url


class ServedUrlTests(unittest.TestCase):
    def test_local_server_urls_are_found_and_normalized(self):
        self.assertEqual(served_url("  Local: http://localhost:5173/\n"),
                         "http://localhost:5173/")
        self.assertEqual(served_url("serving on http://0.0.0.0:8000"),
                         "http://127.0.0.1:8000")

    def test_noise_yields_nothing(self):
        self.assertIsNone(served_url("compiling...\nready"))
        self.assertIsNone(served_url("see https://example.com:443/docs"))

    def test_process_records_the_first_url_it_sees(self):
        item = ManagedProcess("id1", "cmd", "bash", ".", None, 0)
        item.append("first http://127.0.0.1:3000\n")
        item.append("second http://localhost:4000\n")
        self.assertEqual(item.url, "http://127.0.0.1:3000")


class PlanFirstNoteTests(unittest.TestCase):
    def test_plan_first_note_is_hidden_like_other_protocols(self):
        from harness.agent import PLAN_FIRST_NOTE
        self.assertTrue(PLAN_FIRST_NOTE.startswith(INTERNAL_USER_PREFIXES))
        # The approval escape is what keeps the mode from re-planning forever.
        self.assertIn("do not re-plan", PLAN_FIRST_NOTE)


if __name__ == "__main__":
    unittest.main()
