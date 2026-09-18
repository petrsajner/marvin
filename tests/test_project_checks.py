"""Project checks: runner states, status persistence and the API endpoints."""
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
from harness.web_api import create_app


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

    def _wait_done(self, timeout: float = 60.0) -> dict:
        deadline = time.time() + timeout
        while time.time() < deadline:
            status = project_checks.read_status(self.project)
            if not status["running"] and status["checks"]:
                return status
            time.sleep(0.2)
        raise TimeoutError("checks did not finish")

    def _checks_config(self, rows: list[dict]) -> None:
        config = {"checks": rows}
        (self.project / ".qwen").mkdir(exist_ok=True)
        (self.project / ".qwen" / "project.yaml").write_text(
            json.dumps(config), encoding="utf-8")

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
        # The status file survives a fresh read (no in-memory state needed).
        raw = json.loads((self.project / ".qwen" / "check-status.json").read_text(encoding="utf-8"))
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
            if status["checks"] and not status["running"]:
                break
            time.sleep(0.3)
        self.assertEqual(status["checks"][0]["state"], "pass")
        self.assertEqual(
            self.client.post("/api/projects/nope/checks/run").status_code, 400)

    def test_fix_endpoint_reuses_session_and_submits_prompt(self):
        with patch.object(ApplicationService, "submit") as submit:
            response = self.client.post(f"/api/projects/{self.project['id']}/checks/fix")
            response.raise_for_status()
            session_id = response.json()["session_id"]
            submit.assert_called_once()
            args, kwargs = submit.call_args
            self.assertEqual(args[0], session_id)
            self.assertIn("start_project_check", args[1])
            self.assertIn("Never weaken", args[1])
        session = self.service.session(session_id)
        self.assertEqual(session.meta.get("workspace"), str(self.repo))


if __name__ == "__main__":
    unittest.main()
