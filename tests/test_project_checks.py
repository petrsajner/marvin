"""Project checks: detection on real layouts, runner states, status and endpoints."""
import copy
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from harness import project_checks
from harness.application import ApplicationService
from harness.config import Config, load_config
from harness.project_profile import ProjectProfile
from harness.web_api import create_app

PASSING_TEST = """import unittest
class T(unittest.TestCase):
    def test_ok(self):
        self.assertEqual(1, 1)
"""
FAILING_TEST = """import unittest
class T(unittest.TestCase):
    def test_bad(self):
        self.assertEqual(1, 2)
"""


class DetectionTests(unittest.TestCase):
    """The layouts that matter are the user's projects, not this repository's."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.cfg = Config(copy.deepcopy(load_config().data), self.root)

    def tearDown(self):
        self.temp.cleanup()

    def _profile(self, files):
        for name, content in files.items():
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        return ProjectProfile(self.root, project_checks._python_for(self.root))

    def test_root_level_test_module_is_detected(self):
        check = self._profile({"test_arkanoid.py": PASSING_TEST}).select()
        self.assertIsNotNone(check)
        self.assertIn("-m unittest discover -s . -p", check.command)

    def test_tests_directory_uses_stdlib_discovery(self):
        check = self._profile({"tests/test_ui.py": PASSING_TEST}).select()
        self.assertIsNotNone(check)
        self.assertIn("-m unittest discover -s tests", check.command)
        self.assertNotIn("pytest", check.command)

    def test_project_without_tests_detects_nothing(self):
        self.assertEqual(self._profile({"notes.md": "x", "model.py": "y"}).checks(), [])

    def test_pytest_only_when_configured_and_importable(self):
        profile = self._profile({"tests/test_ui.py": PASSING_TEST,
                                 "pytest.ini": "[pytest]\n"})
        with patch("harness.project_profile._module_available", return_value=True):
            self.assertIn("-m pytest", profile.select().command)
        with patch("harness.project_profile._module_available", return_value=False):
            # A configured runner that cannot be imported would fail on startup;
            # the stdlib runner keeps the check usable instead.
            self.assertIn("-m unittest discover", profile.select().command)

    def test_uninstalled_lint_and_typecheck_are_not_offered(self):
        profile = self._profile({"tests/test_ui.py": PASSING_TEST,
                                 "pyproject.toml": "[tool.ruff]\n[tool.mypy]\n"})
        with patch("harness.project_profile._module_available", return_value=False):
            self.assertEqual([item.kind for item in profile.checks()], ["test"])

    def test_marvin_layout_keeps_its_entry_script(self):
        check = self._profile({"tests/test_core.py": PASSING_TEST}).select()
        self.assertIn("tests/test_core.py", check.command)


class ProjectCheckRunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        data = copy.deepcopy(load_config().data)
        data["agent"].update(workspace=None, autonomy="auto")
        self.cfg = Config(data, self.root)
        self.project = self.root / "repo"
        (self.project / "tests").mkdir(parents=True)

    def tearDown(self):
        self.temp.cleanup()

    def _status(self):
        return project_checks.status(self.cfg, self.project)

    def _wait_done(self, timeout=90.0):
        terminal = {"pass", "fail", "timeout", "error"}
        deadline = time.time() + timeout
        while time.time() < deadline:
            status = self._status()
            if (not status["running"] and status["checks"]
                    and all(row["state"] in terminal for row in status["checks"])):
                return status
            time.sleep(0.2)
        raise TimeoutError("checks did not finish")

    def _checks_config(self, rows):
        (self.project / ".qwen").mkdir(exist_ok=True)
        (self.project / ".qwen" / "project.yaml").write_text(
            json.dumps({"checks": rows}), encoding="utf-8")

    def test_runner_records_pass_fail_and_timeout(self):
        self._checks_config([
            {"id": "ok", "label": "Passing", "command": "Write-Output fine", "timeout": 30},
            {"id": "bad", "label": "Failing", "command": "exit 3", "timeout": 30},
            {"id": "slow", "label": "Slow", "command": "Start-Sleep -Seconds 60",
             "timeout": 1, "shell": "powershell"},
        ])
        self.assertTrue(project_checks.run_checks(self.cfg, self.project))
        status = self._wait_done()
        states = {row["id"]: row["state"] for row in status["checks"]}
        self.assertEqual(states, {"ok": "pass", "bad": "fail", "slow": "timeout"})
        by_id = {row["id"]: row for row in status["checks"]}
        self.assertEqual(by_id["ok"]["exit_code"], 0)
        self.assertEqual(by_id["bad"]["exit_code"], 3)
        self.assertIn("fine", by_id["ok"]["summary"])
        raw = json.loads(
            (self.project / ".qwen" / "check-status.json").read_text(encoding="utf-8"))
        self.assertEqual(len(raw["checks"]), 3)

    def test_second_run_while_running_is_rejected(self):
        self._checks_config([
            {"id": "slow", "label": "Slow", "command": "Start-Sleep -Seconds 30", "timeout": 60},
        ])
        try:
            self.assertTrue(project_checks.run_checks(self.cfg, self.project))
            self.assertFalse(project_checks.run_checks(self.cfg, self.project))
        finally:
            deadline = time.time() + 60
            while project_checks.is_running(self.project) and time.time() < deadline:
                time.sleep(0.2)

    def test_detected_checks_are_listed_before_the_first_run(self):
        (self.project / "tests" / "test_ui.py").write_text(PASSING_TEST, encoding="utf-8")
        status = self._status()
        self.assertTrue(status["available"])
        self.assertEqual([row["state"] for row in status["checks"]], ["never"])
        self.assertFalse(status["running"])

    def test_stale_outcome_of_a_removed_check_is_dropped(self):
        self._checks_config([{"id": "ok", "label": "Passing", "command": "Write-Output fine"}])
        self.assertTrue(project_checks.run_checks(self.cfg, self.project))
        self._wait_done()
        self._checks_config([{"id": "other", "label": "Other", "command": "Write-Output x"}])
        status = self._status()
        self.assertEqual([row["id"] for row in status["checks"]], ["other"])
        self.assertEqual(status["checks"][0]["state"], "never")

    def test_failed_detection_does_not_wedge_the_project(self):
        (self.project / "tests" / "test_ui.py").write_text(PASSING_TEST, encoding="utf-8")
        with patch.object(project_checks, "check_definitions", side_effect=OSError("boom")):
            with self.assertRaises(OSError):
                project_checks.run_checks(self.cfg, self.project)
        self.assertFalse(project_checks.is_running(self.project))
        self.assertTrue(project_checks.run_checks(self.cfg, self.project))
        self._wait_done()

    def test_nothing_detected_reports_no_start(self):
        self.assertFalse(project_checks.run_checks(self.cfg, self.project))
        self.assertFalse(project_checks.is_running(self.project))

    def test_stdlib_discovery_actually_runs_the_project_tests(self):
        """The command detection produces must work with the app's own interpreter."""
        (self.project / "tests" / "test_ui.py").write_text(PASSING_TEST, encoding="utf-8")
        self.assertTrue(project_checks.run_checks(self.cfg, self.project))
        self.assertEqual(self._wait_done()["checks"][0]["state"], "pass")
        (self.project / "tests" / "test_ui.py").write_text(FAILING_TEST, encoding="utf-8")
        self.assertTrue(project_checks.run_checks(self.cfg, self.project))
        self.assertEqual(self._wait_done()["checks"][0]["state"], "fail")

    def test_root_layout_actually_runs(self):
        (self.project / "test_arkanoid.py").write_text(PASSING_TEST, encoding="utf-8")
        (self.project / "tests").rmdir()
        self.assertTrue(project_checks.run_checks(self.cfg, self.project))
        self.assertEqual(self._wait_done()["checks"][0]["state"], "pass")


class ProjectCheckEndpointTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        data = copy.deepcopy(load_config().data)
        data["hardware"]["vram_gb"] = 32
        data["agent"].update(workspace=None, autonomy="auto")
        self.cfg = Config(data, self.root)
        self.service = ApplicationService(self.cfg, llm_factory=lambda c: None,
                                          manage_model=False)
        self.client = TestClient(create_app(self.cfg, service=self.service))
        self.repo = self.root / "repo"
        (self.repo / "tests").mkdir(parents=True)
        (self.repo / "tests" / "test_ui.py").write_text(PASSING_TEST, encoding="utf-8")
        response = self.client.post("/api/projects", json={"path": str(self.repo)})
        self.project = response.json()["project"]

    def tearDown(self):
        self.service.close()
        self.service.models.wait(3)
        self.temp.cleanup()

    def test_status_reports_unavailable_without_checks(self):
        bare = self.root / "bare"
        bare.mkdir()
        project = self.client.post("/api/projects", json={"path": str(bare)}).json()["project"]
        status = self.client.get(f"/api/projects/{project['id']}/checks").json()
        self.assertFalse(status["available"])
        self.assertEqual(status["checks"], [])

    def test_run_endpoint_starts_and_records_status(self):
        (self.repo / "tests" / "test_core.py").write_text("print('ok')\n", encoding="utf-8")
        response = self.client.post(f"/api/projects/{self.project['id']}/checks/run")
        response.raise_for_status()
        deadline = time.time() + 90
        while time.time() < deadline:
            status = self.client.get(f"/api/projects/{self.project['id']}/checks").json()
            if (status["checks"] and not status["running"]
                    and status["checks"][0]["state"] != "never"):
                break
            time.sleep(0.3)
        self.assertEqual(status["checks"][0]["state"], "pass")
        self.assertEqual(
            self.client.post("/api/projects/nope/checks/run").status_code, 400)

    def test_fix_endpoint_reuses_a_development_chat(self):
        with patch.object(ApplicationService, "submit") as submit:
            response = self.client.post(f"/api/projects/{self.project['id']}/checks/fix")
            response.raise_for_status()
            session_id = response.json()["session_id"]
            submit.assert_called_once()
            args, _ = submit.call_args
            self.assertEqual(args[0], session_id)
            self.assertIn("start_project_check", args[1])
            self.assertIn("Never weaken", args[1])
        session = self.service.session(session_id)
        self.assertEqual(session.meta.get("workspace"), str(self.repo))
        self.assertEqual(session.meta.get("work_mode"), "development")

    def test_fix_endpoint_opens_a_development_chat_when_the_project_chat_is_not_one(self):
        """start_project_check exists only in development and computer mode."""
        other = self.root / "talk"
        (other / "tests").mkdir(parents=True)
        (other / "tests" / "test_ui.py").write_text(PASSING_TEST, encoding="utf-8")
        created = self.client.post(
            "/api/projects", json={"path": str(other), "mode": "discussion"}).json()
        discussion_id = created["session_id"]
        self.assertEqual(
            self.service.session(discussion_id).meta.get("work_mode"), "discussion")
        with patch.object(ApplicationService, "submit"):
            session_id = self.client.post(
                f"/api/projects/{created['project']['id']}/checks/fix").json()["session_id"]
        self.assertNotEqual(session_id, discussion_id)
        session = self.service.session(session_id)
        self.assertEqual(session.meta.get("work_mode"), "development")
        self.assertEqual(session.meta.get("workspace"), str(other))

    def test_fix_endpoint_refuses_a_project_without_checks(self):
        bare = self.root / "bare"
        bare.mkdir()
        project = self.client.post("/api/projects", json={"path": str(bare)}).json()["project"]
        response = self.client.post(f"/api/projects/{project['id']}/checks/fix")
        self.assertEqual(response.status_code, 400)
        self.assertIn("No project checks detected", response.json()["detail"])


if __name__ == "__main__":
    unittest.main()
