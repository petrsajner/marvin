"""Git auto-commit: per-project switch, message composition, gates, real repo."""
import copy
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

from harness.application import ApplicationService
from harness.changes import ChangeJournal
from harness.config import Config, load_config
from harness.projects import Projects
from harness.session import Session
from harness.tools.git import GitCommitTool
from harness.web_api import create_app


def _ctx(workspace, journal=None):
    return SimpleNamespace(workspace=workspace, changes=journal)


class AutocommitSwitchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        data = copy.deepcopy(load_config().data)
        data["agent"].update(workspace=None, autonomy="auto")
        self.cfg = Config(data, self.root)
        self.app = ApplicationService(self.cfg, llm_factory=lambda c: None,
                                      manage_model=False)
        self.client = TestClient(create_app(self.cfg, service=self.app))

    def tearDown(self):
        self.app.close()
        self.app.models.wait(3)
        self.temp.cleanup()

    def test_switch_is_off_by_default_and_flips_via_api(self):
        workspace = self.root / "repo"
        workspace.mkdir()
        project = self.client.post("/api/projects", json={"path": str(workspace)}).json()["project"]
        self.assertFalse(project.get("autocommit"))
        response = self.client.patch(f"/api/projects/{project['id']}",
                                     json={"autocommit": True})
        response.raise_for_status()
        self.assertTrue(response.json()["autocommit"])
        self.assertTrue(Projects(self.cfg).by_path(str(workspace))["autocommit"])
        self.assertFalse(
            self.client.patch(f"/api/projects/{project['id']}",
                              json={"autocommit": "yes"}).status_code == 200)
        self.assertEqual(
            self.client.patch("/api/projects/nope", json={"autocommit": True}).status_code, 400)
        state = self.client.get("/api/state").json()
        stored = next(p for p in state["projects"] if p["id"] == project["id"])
        self.assertTrue(stored["autocommit"])


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

    def _enable(self, enabled: bool):
        projects = Projects(self.cfg)
        if not projects.by_path(str(self.root)):
            projects.attach_folder(str(self.root))
        projects.set_autocommit(str(self.root), enabled)

    def _agent(self):
        plan = SimpleNamespace(load=lambda: {"goal": "Bump app to version 2"})
        return SimpleNamespace(
            ctx=SimpleNamespace(workspace=self.root, changes=self.journal, task_plan=plan),
            work_mode="development")

    def test_autocommit_stages_only_task_files(self):
        self._enable(True)
        note = self.service._maybe_autocommit(
            self._agent(), self.session, {"text": "bump"}, "✅ Done\n- app.txt: v2")
        # The wording carries no plural agreement, so it translates into Czech.
        self.assertTrue(note and note.startswith("Auto-committed as "), note)
        self.assertIn("(1 files)", note)
        log = self._git(["log", "-1", "--format=%s%n%n%b"])
        self.assertIn("Bump app to version 2", log.stdout)
        self.assertIn("app.txt: v2", log.stdout)
        self.assertIn(f"Marvin: session {self.session.id}", log.stdout)
        status = self._git(["status", "--porcelain"])
        self.assertIn("?? extra.txt", status.stdout)      # untracked file untouched
        self.assertNotIn("app.txt", status.stdout)        # committed cleanly

    def test_switch_off_means_no_commit(self):
        self._enable(True)
        self._enable(False)
        note = self.service._maybe_autocommit(
            self._agent(), self.session, {"text": "bump"}, "✅ Done")
        self.assertIsNone(note)
        self.assertIn("app.txt", self._git(["status", "--porcelain"]).stdout)

    def test_wrong_mode_skips(self):
        self._enable(True)
        agent = self._agent()
        agent.work_mode = "research"
        self.assertIsNone(self.service._maybe_autocommit(
            agent, self.session, {"text": "x"}, "✅ Done"))

    def test_commit_tool_regression(self):
        result = GitCommitTool().run(_ctx(self.root, self.journal),
                                     "manual commit via tool")
        self.assertIn("[exit code: 0]", result)
        subject = self._git(["log", "-1", "--format=%s"]).stdout.strip()
        self.assertEqual(subject, "manual commit via tool")


if __name__ == "__main__":
    unittest.main()
