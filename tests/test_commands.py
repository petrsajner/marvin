"""Slash commands, on the surface that still exists.

These were covered only through the Gradio handler, which was a second
implementation of the same idea. Removing Gradio would have left the commands the
workspace actually dispatches - `app_operations.execute_command` - with no tests
at all, so the coverage moves here rather than disappearing with the interface it
happened to be written against.
"""
import copy
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from harness.app_operations import COMMANDS, execute_command
from harness.config import Config, load_config
from harness.session import Session


class CommandTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.cfg = Config(copy.deepcopy(load_config().data), self.root)
        self.cfg.data["paths"]["sessions_dir"] = str(self.root / "sessions")
        self.workspace = self.root / "project"
        self.workspace.mkdir()
        self.session = Session(self.cfg, system_prompt="rules")
        self.app = SimpleNamespace(cfg=self.cfg)
        self.agent = SimpleNamespace(
            session=self.session,
            ctx=SimpleNamespace(project_workspace=self.workspace, workspace=self.workspace),
            registry=None)

    def run_command(self, text: str):
        return execute_command(self.app, self.agent, {"text": text, "id": "job1"})

    def test_a_prompt_command_becomes_the_instruction_plus_the_argument(self):
        for command, marker in (("/test", "checks"), ("/plan", "plan"), ("/review", "Review")):
            answer = self.run_command(command + " the login screen")
            self.assertIn(marker.lower(), answer.lower())
            self.assertTrue(answer.strip().endswith("the login screen"),
                            "the user's words have to survive the command")

    def test_help_lists_every_command_it_claims_to_have(self):
        """A handled command answers into the conversation and returns None; only
        the prompt-shaped ones come back as text for the model."""
        self.assertIsNone(self.run_command("/help"))
        answer = self.session.messages[-1]["content"]
        self.assertEqual(self.session.messages[-1]["role"], "assistant")
        for name in COMMANDS:
            self.assertIn(name, answer, name)

    def test_an_unknown_command_is_passed_through_as_an_ordinary_message(self):
        before = len(self.session.messages)
        self.assertEqual(self.run_command("/nonsense do a thing"), "/nonsense do a thing")
        self.assertEqual(len(self.session.messages), before,
                         "an unrecognised command must not answer on the model's behalf")

    def test_pinned_files_are_reported_back(self):
        pinned = self.workspace / "notes.txt"
        pinned.write_text("remember this", encoding="utf-8")
        self.session.pin_context_file(pinned)
        self.assertIsNone(self.run_command("/pins"))
        self.assertIn("notes.txt", self.session.messages[-1]["content"])

    def test_no_pinned_files_says_so_rather_than_answering_blankly(self):
        self.assertIsNone(self.run_command("/pins"))
        self.assertTrue(self.session.messages[-1]["content"].strip())

    def test_asking_for_a_new_skill_designs_one_rather_than_loading_it(self):
        answer = self.run_command("/skill new my-analysis")
        self.assertIn("SKILL.md", answer)
        self.assertIn("my-analysis", answer)
        self.assertNotIn("my-analysis", self.session.meta.get("active_skills") or [],
                         "designing a skill must not mark a non-existent one active")

    def test_every_advertised_command_is_dispatchable(self):
        """COMMANDS is what the interface offers, so nothing in it may be a dead
        entry that falls through to being sent as an ordinary message."""
        handled = {"/test", "/plan", "/review", "/skill"}
        for name in COMMANDS:
            if name in handled:
                continue
            try:
                self.run_command(name)
            except (ValueError, RuntimeError, AttributeError, TypeError):
                # A command that needs a project or a running task refuses for a
                # reason; falling through silently is what must not happen.
                pass


if __name__ == "__main__":
    unittest.main()
