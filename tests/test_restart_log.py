"""Why the model server restarted, recorded at the moment the decision is taken.

A restart throws away the processed prompt - 92 seconds for 150k tokens,
measured - and the decision used to record nothing about which of its four
conditions caused it, so the reason had to be reconstructed from prompt sizes in
a log days later.
"""
import json
import tempfile
import unittest
from pathlib import Path

from harness import restart_log


class RestartLogTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.runtime = Path(self.temporary.name)

    def test_every_condition_that_argued_for_a_restart_is_named(self):
        """They are not exclusive, and which fired is the whole question."""
        found = restart_log.reasons(profile_changed=True, hardware_changed=True,
                                    healthy=False, running="q4", wanted="q5")
        self.assertEqual(found, ["profile_changed", "hardware_changed",
                                 "server_unhealthy", "different_model_running"])

    def test_a_model_the_owner_chose_reads_differently_from_no_server_at_all(self):
        self.assertEqual(
            restart_log.reasons(profile_changed=False, hardware_changed=False,
                                healthy=True, running="q4", wanted="q5"),
            ["different_model_running"])
        self.assertEqual(
            restart_log.reasons(profile_changed=False, hardware_changed=False,
                                healthy=True, running=None, wanted="q5"),
            ["no_server_running"])

    def test_nothing_is_recorded_when_nothing_argued_for_a_restart(self):
        self.assertEqual(
            restart_log.reasons(profile_changed=False, hardware_changed=False,
                                healthy=True, running="q5", wanted="q5"), [])

    def test_a_decision_is_written_down_with_what_it_cost(self):
        restart_log.record(self.runtime, reason=["different_model_running"],
                           wanted="q5", running="q4", profile="q8_0", context=196608)
        rows = restart_log.entries(self.runtime)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["reason"], ["different_model_running"])
        self.assertEqual(rows[0]["wanted"], "q5")
        self.assertEqual(rows[0]["running"], "q4")
        self.assertEqual(rows[0]["context"], 196608)
        self.assertIn("when", rows[0])

    def test_the_log_records_no_conversation(self):
        restart_log.record(self.runtime, reason="server_unhealthy", wanted="q5",
                           running=None, profile="q8_0", context=196608)
        text = (self.runtime / restart_log.FILENAME).read_text(encoding="utf-8")
        for field in json.loads(text.strip()):
            self.assertIn(field, {"at", "when", "reason", "wanted", "running",
                                  "profile", "context", "note"})

    def test_the_log_stays_bounded(self):
        for index in range(restart_log.KEEP + 40):
            restart_log.record(self.runtime, reason="server_unhealthy",
                               wanted="q5", context=index)
        rows = restart_log.entries(self.runtime)
        self.assertEqual(len(rows), restart_log.KEEP)
        self.assertEqual(rows[-1]["context"], restart_log.KEEP + 39,
                         "the newest decision must survive the trim")

    def test_a_switch_the_owner_asked_for_is_counted_apart(self):
        restart_log.record(self.runtime, reason=["different_model_running"], wanted="q5")
        restart_log.record(self.runtime, reason=["different_model_running"], wanted="q4")
        restart_log.record(self.runtime, reason=["server_unhealthy"], wanted="q5")
        restart_log.record(self.runtime, reason=["profile_changed", "different_model_running"],
                           wanted="q5")
        report = restart_log.summary(self.runtime)
        self.assertEqual(report["restarts"], 4)
        self.assertEqual(report["model_switch_only"], 2,
                         "only a plain switch counts; one with another cause does not")
        self.assertEqual(report["by_reason"]["different_model_running"], 3)
        self.assertEqual(report["by_reason"]["server_unhealthy"], 1)

    def test_a_diagnostic_never_stops_a_task(self):
        """Recording must fail silently; a task must not die over a log line."""
        blocked = self.runtime / "blocked"
        blocked.write_text("not a directory", encoding="utf-8")
        restart_log.record(blocked, reason="server_unhealthy", wanted="q5")
        self.assertEqual(restart_log.entries(blocked), [])

    def test_an_unreadable_line_is_skipped_rather_than_fatal(self):
        restart_log.record(self.runtime, reason="server_unhealthy", wanted="q5")
        path = self.runtime / restart_log.FILENAME
        path.write_text(path.read_text(encoding="utf-8") + "{ truncated\n", encoding="utf-8")
        self.assertEqual(len(restart_log.entries(self.runtime)), 1)

    def test_nothing_recorded_yet_reads_as_nothing_rather_than_failing(self):
        self.assertEqual(restart_log.entries(self.runtime), [])
        self.assertEqual(restart_log.summary(self.runtime),
                         {"restarts": 0, "by_reason": {}, "model_switch_only": 0,
                          "first": None, "last": None})


if __name__ == "__main__":
    unittest.main()
