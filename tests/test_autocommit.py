"""Git auto-commit: project flag, message composition, gates and a real temp repo."""
import copy
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from harness.application import ApplicationService
from harness.changes import ChangeJournal
from harness.config import Config, load_config
from harness.project_profile import autocommit_enabled
from harness.session import Session
from harness.tools.git import GitCommitTool, task_paths


def _ctx(workspace, journal=None):
    return SimpleNamespace(workspace=workspace, changes=journal)


class AutocommitFlagTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / ".qwen").mkdir()

    def tearDown(self):
        self.temp.cleanup()

    def _write(self, content: str):
        (self.root / ".qwen" / "project.yaml").write_text(content, encoding="utf-8")

    def test_flag_off_by_default_and_tolerates_garbage(self):
        self.assertFalse(autocommit_enabled(self.root))
        self.assertFalse(autocommit_enabled(None))
        self._write("checks:\n  - id: tests\n    command: npm test\n")
        self.assertFalse(autocommit_enabled(self.root))
        self._write("git: {autocommit: banana}\n")
        self.assertFalse(autocommit_enabled(self.root))
        self._write("git:\n  autocommit: true\n")
        self.assertTrue(autocommit_enabled(self.root))


class AutocommitMessageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        data = copy.deepcopy(load_config().data)
        data["agent"].update(workspace=None, autonomy="auto")
        self.cfg = Config(data, self.root)
        self.service = ApplicationService(self.cfg, llm_factory=lambda c: None,
                                          manage_model=False)

    def tearDown(self):
        self.service.close()
        self.service.models.wait(3)
        self.temp.cleanup()

    def _agent(self, workspace, journal, plan=None):
        return SimpleNamespace(
            ctx=SimpleNamespace(workspace=workspace, changes=journal, task_plan=plan),
            work_mode="development")

    def test_message_uses_goal_and_done_section(self):
        session = Session(self.cfg, system_prompt="SYS", workspace=str(self.root))
        journal = ChangeJournal(session, self.root)
        journal.begin_task("Add retry with backoff")
        summary = ("✅ Done\n- fs.py: added retry loop\n- tests: covered\n\n"
                   "🔍 Found\n- nothing\n\n📋 Next\n- polish")
        plan = SimpleNamespace(load=lambda: {"goal": "Add retry with backoff"})
        agent = self._agent(self.root, journal, plan)
        message = self.service._autocommit_message(agent, session, {"text": "raw"}, summary)
        self.assertTrue(message.startswith("Add retry with backoff"))
        self.assertIn("- fs.py: added retry loop", message)
        self.assertNotIn("🔍 Found", message)
        self.assertIn(f"Marvin: session {session.id}", message)

    def test_message_falls_back_to_job_text_and_validation(self):
        session = Session(self.cfg, system_prompt="SYS", workspace=str(self.root))
        journal = ChangeJournal(session, self.root)
        journal.begin_task("unstructured answer")
        plan = SimpleNamespace(load=lambda: {
            "goal": "", "validations": [{"status": "passed", "label": "pytest"}]})
        agent = self._agent(self.root, journal, plan)
        message = self.service._autocommit_message(agent, session,
                                                   {"text": "fix the bug please"}, "plain text")
        self.assertTrue(message.startswith("fix the bug please"))
        self.assertIn("Validation: passed — pytest", message)


class AutocommitIntegrationTests(unittest.TestCase):
    """Offline integration against a real temporary Git repository."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self._git(["init", "-q"])
        self._git(["config", "user.email", "marvin@test"])
        self._git(["config", "user.name", "Marvin Test"])
        target = self.root / "app.txt"
        target.write_text("version 1\n", encoding="utf-8")
        self._git(["add", "app.txt"])
        self._git(["commit", "-q", "-m", "initial"])

        data = copy.deepcopy(load_config().data)
        data["agent"].update(workspace=str(self.root), autonomy="auto")
        self.cfg = Config(data, self.root)
        self.service = ApplicationService(self.cfg, llm_factory=lambda c: None,
                                          manage_model=False)
        self.session = Session(self.cfg, system_prompt="SYS", workspace=str(self.root))
        self.journal = ChangeJournal(self.session, self.root)
        self.journal.begin_task("Bump app to version 2")
        self.journal.record_before(self.root / "app.txt")
        (self.root / "app.txt").write_text("version 2\n", encoding="utf-8")
        (self.root / "extra.txt").write_text("not part of the task\n", encoding="utf-8")
        self.journal.record_after(self.root / "app.txt")

    def tearDown(self):
        self.service.close()
        self.service.models.wait(3)
        self.temp.cleanup()

    def _git(self, args):
        return subprocess.run(["git", *args], cwd=self.root, capture_output=True,
                              text=True, encoding="utf-8", timeout=30)

    def _agent(self):
        plan = SimpleNamespace(load=lambda: {"goal": "Bump app to version 2"})
        return SimpleNamespace(
            ctx=SimpleNamespace(workspace=self.root, changes=self.journal, task_plan=plan),
            work_mode="development")

    def test_autocommit_stages_only_task_files(self):
        (self.root / ".qwen").mkdir()
        (self.root / ".qwen" / "project.yaml").write_text(
            "git:\n  autocommit: true\n", encoding="utf-8")
        note = self.service._maybe_autocommit(
            self._agent(), self.session, {"text": "bump"}, "✅ Done\n- app.txt: v2")
        self.assertTrue(note and note.startswith("Auto-committed 1 file"), note)
        log = self._git(["log", "-1", "--format=%s%n%n%b"])
        self.assertIn("Bump app to version 2", log.stdout)
        self.assertIn("app.txt: v2", log.stdout)
        self.assertIn(f"Marvin: session {self.session.id}", log.stdout)
        status = self._git(["status", "--porcelain"])
        self.assertIn("?? extra.txt", status.stdout)      # untracked file untouched
        self.assertNotIn("app.txt", status.stdout)        # committed cleanly

    def test_no_flag_no_commit(self):
        note = self.service._maybe_autocommit(
            self._agent(), self.session, {"text": "bump"}, "✅ Done")
        self.assertIsNone(note)
        self.assertIn("app.txt", self._git(["status", "--porcelain"]).stdout)

    def test_wrong_mode_or_unchanged_journal_skips(self):
        (self.root / ".qwen").mkdir()
        (self.root / ".qwen" / "project.yaml").write_text(
            "git:\n  autocommit: true\n", encoding="utf-8")
        agent = self._agent()
        agent.work_mode = "research"
        self.assertIsNone(self.service._maybe_autocommit(
            agent, self.session, {"text": "x"}, "✅ Done"))
        # Research workspace (no journal changes recorded for other files) stays silent.

    def test_commit_tool_regression(self):
        result = GitCommitTool().run(_ctx(self.root, self.journal),
                                     "manual commit via tool")
        self.assertIn("[exit code: 0]", result)
        subject = self._git(["log", "-1", "--format=%s"]).stdout.strip()
        self.assertEqual(subject, "manual commit via tool")


if __name__ == "__main__":
    unittest.main()
