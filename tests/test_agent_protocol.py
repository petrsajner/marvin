"""Advisory loop warnings and the task protocol's diff review (owner, 2026-10-07)."""
from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from harness.agent import LOOP_CYCLE_REPEATS, repeated_cycle
from harness.config import load_config


class RepeatedCycleTests(unittest.TestCase):
    def test_a_cycle_of_two_to_four_steps_is_found_after_three_rounds(self):
        for size in (2, 3, 4):
            steps = [f"tool{i}:{{}}" for i in range(size)]
            self.assertEqual(repeated_cycle(["start"] + steps * LOOP_CYCLE_REPEATS), size, size)
            self.assertEqual(repeated_cycle(["start"] + steps * (LOOP_CYCLE_REPEATS - 1)), 0, size)

    def test_progress_and_single_repeats_are_not_cycles(self):
        self.assertEqual(repeated_cycle(["a", "a", "a", "a", "a", "a"]), 0, "the exact-repeat warning covers this")
        self.assertEqual(repeated_cycle([f"read_file:{{\"path\": \"{i}\"}}" for i in range(12)]), 0)
        self.assertEqual(repeated_cycle(["a", "b", "a", "b", "a", "c"]), 0)


class AgentLoopWarningTests(unittest.TestCase):
    def setUp(self):
        from harness.agent import Agent, build_registry
        from harness.prompts import system_prompt
        from harness.safety import SafetyPolicy
        from harness.session import Session
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        cfg = load_config(root / "missing.yaml", root=root)
        cfg.data["paths"]["sessions_dir"] = str(root / "sessions")
        cfg.data["agent"]["workspace"] = str(root)
        (root / "notes.txt").write_text("notes", encoding="utf-8")
        self.calls = []
        test = self

        class Model:
            def stream(self, messages, **kwargs):
                from harness.llm import AssistantResult
                name, arguments = test.calls.pop(0)
                return AssistantResult(tool_calls=[{"id": f"c{len(test.calls)}", "type": "function",
                                                    "function": {"name": name, "arguments": arguments}}])

        self.session = Session(cfg, system_prompt=system_prompt("agent"), workspace=str(root))
        self.agent = Agent(cfg, Model(), self.session, build_registry("agent"), SafetyPolicy("auto"), mode="agent")
        self.agent.new_task("Check the notes")

    def tearDown(self):
        self.temp.cleanup()

    def warnings(self):
        return [m["content"] for m in self.session.messages
                if m.get("role") == "user" and str(m.get("content", "")).startswith("[LOOP WARNING")]

    def test_a_cycle_of_different_calls_gets_one_advisory_warning_per_round_of_repeats(self):
        cycle = [("list_dir", "{}"), ("read_file", '{"path": "notes.txt"}'), ("task_plan_status", "{}")]
        rounds = 2 * LOOP_CYCLE_REPEATS
        self.calls = cycle * rounds
        for _ in range(len(cycle) * rounds):
            self.agent.step()
        warnings = self.warnings()
        self.assertEqual(len(warnings), 2, "once per full set of repeats, not on every step")
        self.assertIn("cycle of 3 (list_dir, read_file, task_plan_status)", warnings[0])

    def test_the_exact_repeat_warning_is_unchanged(self):
        self.calls = [("list_dir", "{}")] * 2
        self.agent.step()
        self.agent.step()
        self.assertEqual(len(self.warnings()), 1)
        self.assertIn("exact same tool call", self.warnings()[0])


class DiffReviewTests(unittest.TestCase):
    def store(self, root: Path):
        from harness.task_plan import TaskPlanStore

        class Session:
            dir = root / "chat"
            transient = False
            meta = {"workspace": str(root / "project")}

        (root / "project").mkdir(exist_ok=True)
        store = TaskPlanStore(Session())
        store.begin("Change the value")
        return store

    def test_outside_git_the_change_journal_is_the_diff_review(self):
        with tempfile.TemporaryDirectory() as temporary:
            store = self.store(Path(temporary))
            self.assertFalse(store.git_workspace())
            self.assertIn("list_task_changes", "; ".join(store.readiness(has_changes=True)))
            self.assertIn("Changes reviewed with list_task_changes (not a Git repository): no", store.context_block())
            store.observe_tool("git_diff", {}, "ERROR: not a git repository")
            self.assertFalse(store.load()["diff_reviewed"])
            store.observe_tool("list_task_changes", {}, "target.py: modified")
            self.assertTrue(store.load()["diff_reviewed"])
            self.assertNotIn("reviewed", "; ".join(store.readiness(has_changes=True)))

    def test_in_a_git_repository_the_git_diff_is_still_required(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / ".git").mkdir()
            store = self.store(root)
            self.assertTrue(store.git_workspace(), "the project is inside the repository")
            store.observe_tool("list_task_changes", {}, "target.py: modified")
            self.assertFalse(store.load()["diff_reviewed"])
            self.assertIn("Git diff reviewed: no", store.context_block())
            store.observe_tool("git_diff", {}, "diff --git a/target.py\n[exit code: 0]")
            self.assertTrue(store.load()["diff_reviewed"])


if __name__ == "__main__":
    unittest.main()
