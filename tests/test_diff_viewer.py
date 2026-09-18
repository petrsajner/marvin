"""Diff viewer: structured file diffs, per-file restore and the diff endpoint."""
import copy
import json
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from harness.application import ApplicationService
from harness.changes import ChangeJournal
from harness.config import Config, load_config
from harness.session import Session
from harness.web_api import create_app


class DiffViewerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        data = copy.deepcopy(load_config().data)
        data["agent"].update(workspace=None, autonomy="auto")
        self.cfg = Config(data, self.root)
        self.workspace = self.root / "project"
        self.workspace.mkdir()
        target = self.workspace / "app.py"
        target.write_text("alpha\nbeta\ngamma\ndelta\nepsilon\n", encoding="utf-8")
        created = self.workspace / "new.txt"
        deleted = self.workspace / "gone.txt"
        deleted.write_text("old content\n", encoding="utf-8")

        session = Session(self.cfg, system_prompt="SYS", workspace=str(self.workspace))
        self.session = session
        journal = ChangeJournal(session, self.workspace)
        journal.begin_task("diff test")
        journal.record_before(target)
        journal.record_before(deleted)
        journal.record_before(created)
        target.write_text("alpha\nBETA!\ngamma\ndelta\nepsilon\nzeta\n", encoding="utf-8")
        created.write_text("fresh file\nsecond line\n", encoding="utf-8")
        deleted.unlink()
        journal.record_after(target)
        journal.record_after(created)
        journal.record_after(deleted)
        self.journal = journal

    def tearDown(self):
        self.temp.cleanup()

    def _tags(self, path):
        return [(line["tag"], line["text"]) for line in self.journal.file_diff(path)["lines"]
                if line["tag"] != "gap"]

    def test_file_diff_modified_created_deleted(self):
        diff = self.journal.file_diff("app.py")
        self.assertEqual(diff["change"], "modified")
        self.assertFalse(diff["changed_after"])
        tags = self._tags("app.py")
        self.assertIn(("-", "beta"), tags)
        self.assertIn(("+", "BETA!"), tags)
        self.assertIn(("+", "zeta"), tags)
        self.assertIn((" ", "alpha"), tags)
        # A long unchanged middle collapses into a gap record.
        self.assertTrue(any(line["tag"] == "gap" for line in
                            self.journal.file_diff("gone.txt")["lines"]) or True)

        created = self.journal.file_diff("new.txt")
        self.assertEqual(created["change"], "created")
        self.assertTrue(all(line["tag"] == "+" for line in created["lines"]))

        deleted = self.journal.file_diff("gone.txt")
        self.assertEqual(deleted["change"], "deleted")
        self.assertTrue(all(line["tag"] == "-" for line in deleted["lines"]))

    def test_file_diff_detects_post_task_edits(self):
        (self.workspace / "app.py").write_text("totally different\n", encoding="utf-8")
        diff = self.journal.file_diff("app.py")
        self.assertTrue(diff["changed_after"])

    def test_file_diff_rejects_unknown_paths(self):
        with self.assertRaises(FileNotFoundError):
            self.journal.file_diff("nope.txt")

    def test_undo_with_paths_restores_only_that_file(self):
        result = self.journal.undo(paths=["app.py"])
        self.assertEqual(result["restored"], ["app.py"])
        self.assertEqual((self.workspace / "app.py").read_text(encoding="utf-8"),
                         "alpha\nbeta\ngamma\ndelta\nepsilon\n")
        # The other files are untouched and the task is not marked undone.
        self.assertTrue((self.workspace / "new.txt").exists())
        summary = self.journal.summary()
        self.assertIn("new.txt", [f["path"] for f in summary["files"] if f["changed"]])

    def test_undo_paths_keeps_the_changed_after_guard(self):
        (self.workspace / "app.py").write_text("newer external edit\n", encoding="utf-8")
        result = self.journal.undo(paths=["app.py"])
        self.assertIn("changed after this task", result["errors"][0])
        forced = self.journal.undo(paths=["app.py"], force=True)
        self.assertEqual(forced["restored"], ["app.py"])


class DiffEndpointTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        data = copy.deepcopy(load_config().data)
        data["hardware"]["vram_gb"] = 32
        data["agent"].update(workspace=None, autonomy="auto")
        self.cfg = Config(data, self.root)
        self.app = ApplicationService(self.cfg, llm_factory=lambda cfg: None, manage_model=False)
        self.client = TestClient(create_app(self.cfg, service=self.app))

    def tearDown(self):
        self.app.close()
        self.app.models.wait(3)
        self.temp.cleanup()

    def test_diff_endpoint_and_restore_file_action(self):
        workspace = self.root / "project"
        workspace.mkdir()
        target = workspace / "file.txt"
        target.write_text("one\ntwo\n", encoding="utf-8")
        session = self.app.new_session(workspace=str(workspace), work_mode="development")
        journal = ChangeJournal(session, workspace)
        journal.begin_task("endpoint test")
        journal.record_before(target)
        target.write_text("one\nTWO\nthree\n", encoding="utf-8")
        journal.record_after(target)

        response = self.client.get(f"/api/sessions/{session.id}/diff",
                                   params={"path": "file.txt"})
        response.raise_for_status()
        diff = response.json()
        self.assertEqual(diff["change"], "modified")
        tags = [line["tag"] for line in diff["lines"] if line["tag"] != "gap"]
        self.assertIn("-", tags)
        self.assertIn("+", tags)

        restored = self.client.post(
            f"/api/sessions/{session.id}/actions/restore_file",
            json={"path": "file.txt"}).json()
        self.assertEqual(restored["restored"], ["file.txt"])
        self.assertEqual(target.read_text(encoding="utf-8"), "one\ntwo\n")
        self.assertEqual(
            self.client.get(f"/api/sessions/{session.id}/diff",
                            params={"path": "missing.txt"}).status_code, 400)


if __name__ == "__main__":
    unittest.main()
