"""End-to-end service contracts without a GPU or browser process."""
from __future__ import annotations

import copy
import io
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from types import SimpleNamespace

from fastapi.testclient import TestClient
from PIL import Image

from harness.application import ApplicationService
from harness.app_operations import perform_action
from harness.app_storage import export_project, import_project
from harness.changes import ChangeJournal
from harness.config import Config, load_config
from harness.documents import read_document_content
from harness.llm import AssistantResult, LLMClient
from harness.projects import Projects
from harness.session import Session
from harness.web_api import create_app


def wait_for(predicate, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("Timed out waiting for operation")


class Model:
    calls = []
    gate = threading.Event()

    def __init__(self, cfg):
        self.cfg = cfg

    def stream(self, messages, **kwargs):
        self.calls.append((copy.deepcopy(messages), copy.deepcopy(self.cfg.data)))
        should_stop = kwargs.get("should_stop", lambda: False)
        on_text = kwargs.get("on_text", lambda text: None)
        content = [m.get("content", "") for m in messages if m.get("role") == "user"]
        content = " ".join(str(c) for c in content)
        if "hold-task" in content and "clarification" not in content:
            on_text("Partial answer.")
            while not self.gate.wait(0.01):
                if should_stop():
                    return AssistantResult(content="Partial answer.", stopped=True)
        on_text("Finished answer.")
        return AssistantResult(content="Finished answer.", usage={"prompt_tokens": 42, "completion_tokens": 8})


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        data = copy.deepcopy(load_config().data)
        data["agent"]["workspace"] = None
        data["agent"]["autonomy"] = "auto"
        data["work_mode"] = "discussion"
        data["hardware"]["vram_gb"] = 32
        self.cfg = Config(data, self.root)
        Model.calls = []
        Model.gate = threading.Event()
        self.service = ApplicationService(self.cfg, llm_factory=Model, manage_model=False)
        self.client = TestClient(create_app(self.cfg, service=self.service))
        self.client.__enter__()

    def tearDown(self):
        Model.gate.set()
        self.client.__exit__(None, None, None)
        self.temp.cleanup()

    def new_chat(self, **kwargs):
        return self.client.post("/api/sessions", json=kwargs).json()["session_id"]

    def test_runtime_memory_failure_remains_visible_across_cached_polls(self):
        from unittest.mock import patch
        failure = self.cfg.path("paths.runtime_dir") / "model-failure.json"
        failure.write_text(json.dumps({"model": "q5", "error": "Model stopped because system memory became critically low."}))
        with patch("harness.servermgmt.server_state", return_value="down"), \
             patch("harness.servermgmt.running_model", return_value=None), \
             patch("harness.servermgmt.vram_value", return_value="2 / 32 GB"):
            first = self.client.get("/api/runtime").json()
            second = self.client.get("/api/runtime").json()
        self.assertEqual(first["switch"]["status"], "failed")
        self.assertEqual(second["switch"]["error"], first["switch"]["error"])

    def test_failed_switch_restores_applied_hardware_preference(self):
        from unittest.mock import patch
        from harness.model_switch import ModelSwitchSnapshot
        restored = Config(copy.deepcopy(self.cfg.data), self.cfg.root)
        restored.data["hardware"]["vram_gb"] = "auto"
        self.service.models.cfg = restored
        self.service.preferences.update(model="flash_next_q3", vram_gb=16)
        with patch.object(self.service.models, "snapshot", return_value=ModelSwitchSnapshot("failed", "flash_next_q3")):
            self.service.model_switch_failed("flash_next_q3", "q5")
        self.assertEqual(self.service.preferences["model"], "q5")
        self.assertEqual(self.service.preferences["vram_gb"], "auto")

    def test_context_display_keeps_active_capacity_then_uses_selected_model(self):
        from harness.app_operations import session_detail
        sid = self.new_chat()
        self.service.submit(sid, "hold-task", request_id="capacity-test")
        wait_for(lambda: bool(Model.calls))
        old_limit = self.service.agents[sid].cfg.context_size()
        self.client.patch("/api/settings", json={"model": "flash_next_q3"}).raise_for_status()
        self.assertEqual(session_detail(self.service, self.service.session(sid))["context"]["limit"], old_limit)
        Model.gate.set()
        self.completed("capacity-test")
        wait_for(lambda: self.service.active is None)
        self.assertEqual(session_detail(self.service, self.service.session(sid))["context"]["limit"], 262144)

    def completed(self, key):
        wait_for(lambda: self.service.store.job(key)["status"] in ("complete", "stopped", "failed"))

    def interrupted_model_job(self, sid, key, *, old_model="flash_next_q3", status="failed"):
        session = self.service.session(sid)
        session.add("user", "Continue the existing task.")
        settings = copy.deepcopy(self.service.preferences)
        settings.update(model=old_model, thinking="xhigh", autonomy="supervised")
        cfg = self.service.config_for(session, settings)
        job = {"id": key, "session_id": sid, "text": "Continue the existing task.",
               "attachments": [], "settings": settings, "config": cfg.data,
               "created": time.time(), "error": "Previous model ran out of memory"}
        self.service.store.save_job(job, status)
        return job

    def test_continue_reuses_selected_running_model_and_current_kv(self):
        from unittest.mock import patch
        for status, old, selected, profile in (
            ("failed", "flash_next_q3", "q5", "q8_0"),
            ("stopped", "flash_next_q3", "q4", "q8_0_compact"),
            ("interrupted", "q5", "q5", "f16"),
            ("waiting_confirmation", "flash_next_q3", "q3", "q8_0_32k"),
            ("failed", "flash_next_q3", "flash_next_q3", "q8_0_128k"),
        ):
            with self.subTest(status=status, model=selected, profile=profile):
                sid = self.new_chat()
                rid = "resume-" + status + "-" + selected
                original = self.interrupted_model_job(sid, rid, old_model=old, status=status)
                self.client.patch("/api/settings", json={"model": selected,
                    "kv_cache_modes": {selected: profile}, "vram_gb": "auto",
                    "autonomy": "auto", "thinking": "low"}).raise_for_status()
                self.service.models.cfg = self.service.config_for(self.service.session(sid))
                self.service.manage_model = True
                try:
                    with patch("harness.servermgmt.health", return_value=True), \
                         patch("harness.servermgmt.running_model", return_value=selected), \
                         patch.object(self.service.models, "request", side_effect=AssertionError("Already selected model must not restart")) as request:
                        response = self.client.post(f"/api/sessions/{sid}/actions/resume", json={})
                        response.raise_for_status()
                        self.completed(rid)
                        wait_for(lambda: self.service.active is None)
                        saved = self.service.store.job(rid)
                        self.assertEqual(saved["status"], "complete", saved["payload"].get("error"))
                        request.assert_not_called()
                    self.assertEqual(Model.calls[-1][1]["default_model"], selected)
                    agent = self.service.agents[sid]
                    self.assertEqual(agent.cfg.kv_cache_mode(), profile)
                    self.assertEqual(agent._ctx_limit(), self.service.models.cfg.context_size())
                    self.assertEqual(agent.cfg.data["reasoning_effort"], "xhigh")
                    self.assertEqual(agent.cfg.agent["autonomy"], "supervised")
                    self.assertEqual(saved["payload"]["settings"]["model"], selected)
                    self.assertEqual(saved["payload"]["config"]["hardware"]["vram_gb"], "auto")
                    self.assertNotIn("error", saved["payload"])
                    self.assertEqual(saved["payload"]["id"], original["id"])
                    self.assertEqual(original["config"]["default_model"], old)
                    self.assertEqual(original["settings"]["model"], old)
                    self.assertEqual(len([m for m in agent.session.messages if m.get("content") == original["text"]]), 1)
                finally:
                    self.service.manage_model = False

    def test_continue_with_smaller_model_compresses_for_its_context_without_losing_history(self):
        from unittest.mock import patch
        sid = self.new_chat()
        session = self.service.session(sid)
        history = []
        for number in range(4):
            history.append(session.add("user", f"Earlier question {number}"))
            history.append(session.add("assistant", f"Earlier findings {number}: " + "data " * 12000))
        for number in range(3):
            history.append(session.add("user", f"Recent question {number}"))
            history.append(session.add("assistant", f"Recent finding {number}"))
        self.interrupted_model_job(sid, "smaller-context")
        self.client.patch("/api/settings", json={"model": "q3", "kv_cache_modes": {"q3": "q8_0_32k"}}).raise_for_status()
        with patch("harness.context.summarize_messages", return_value="Retained findings and decisions.") as summarize:
            self.service.resume(sid)
            self.completed("smaller-context")
            wait_for(lambda: self.service.active is None)
            self.assertEqual(self.service.store.job("smaller-context")["status"], "complete")
            summarize.assert_called_once()
            self.assertEqual(summarize.call_args.args[0].cfg.model_key(), "q3")
            self.assertEqual(summarize.call_args.args[0].cfg.context_size(), 32768)
        self.assertIsNotNone(session.compression)
        self.assertTrue(all(any(m.get("id") == original["id"] and m["content"] == original["content"]
                                for m in session.messages) for original in history))

    def test_messages_arriving_at_completion_are_not_stranded_as_steering(self):
        finished = threading.Event()
        release = threading.Event()
        original_drive = self.service._drive

        def hold_completed_job(job):
            original_drive(job)
            if job["id"] == "completion-first":
                finished.set()
                release.wait(5)

        self.service._drive = hold_completed_job
        sid = self.new_chat()
        try:
            self.service.submit(sid, "First task.", request_id="completion-first")
            self.assertTrue(finished.wait(5))
            self.assertEqual(self.service.store.job("completion-first")["status"], "complete")
            self.assertIsNotNone(self.service.active)
            self.service.submit(sid, "Second task.", request_id="completion-second")
            self.service.submit(sid, "Third task.", request_id="completion-third")
            release.set()
            self.completed("completion-second")
            self.completed("completion-third")
            self.assertEqual(self.service.store.job("completion-second")["status"], "complete")
            self.assertEqual(self.service.store.job("completion-third")["status"], "complete")
            users = [m["content"] for m in self.service.session(sid).messages
                     if m.get("role") == "user" and m.get("content") in ("First task.", "Second task.", "Third task.")]
            self.assertEqual(users, ["First task.", "Second task.", "Third task."])
            self.assertFalse(self.service.store.jobs(("steering",)))
        finally:
            release.set()

    def test_late_steering_keeps_queue_paused_after_stop(self):
        finished = threading.Event()
        release = threading.Event()
        original_drive = self.service._drive

        def hold_completed_job(job):
            original_drive(job)
            finished.set()
            release.wait(5)

        self.service._drive = hold_completed_job
        sid = self.new_chat()
        try:
            self.service.submit(sid, "First task.", request_id="paused-first")
            self.assertTrue(finished.wait(5))
            self.service.submit(sid, "Next task.", request_id="paused-next")
            self.assertTrue(self.service.stop(sid))
            release.set()
            wait_for(lambda: self.service.active is None)
            self.assertTrue(self.service.queue_paused)
            self.assertEqual(self.service.store.job("paused-next")["status"], "queued")
        finally:
            release.set()

    def test_launcher_identity_rejects_other_installation_and_legacy_server(self):
        from harness.web_identity import belongs_to_installation
        payload = self.client.get("/config").json()
        self.assertTrue(belongs_to_installation(payload, self.root))
        self.assertTrue(belongs_to_installation(payload, self.root, payload["version"]))
        self.assertFalse(belongs_to_installation(payload, self.root, "old-version"))
        self.assertFalse(belongs_to_installation(payload, self.root / "other-installation"))
        self.assertFalse(belongs_to_installation({"components": []}, self.root))
        self.assertEqual(Path(payload["data_root"]), self.root)

    def test_launcher_reuses_own_server_on_alternate_port(self):
        from unittest.mock import patch
        from launcher.launcher_app import _existing_web_port
        with patch("launcher.launcher_app._port_busy", side_effect=lambda port: port in (7860, 7861)), \
             patch("launcher.launcher_app._is_our_webui", side_effect=lambda url: url.endswith(":7861")):
            self.assertEqual(_existing_web_port(7860), 7861)

    def test_autostart_restores_last_successful_model_and_kv(self):
        from harness.model_switch import ModelSwitchController
        from unittest.mock import patch
        gate = threading.Event()
        self.service.models = ModelSwitchController(self.cfg, ensure_fn=lambda *_: gate.wait(2),
                                                   stop_fn=lambda *a, **k: True, running_fn=lambda *_: False)
        self.service.preferences.update(model="q5", last_running_model="q4", last_running_kv="q8_0")
        self.service.manage_model = True
        try:
            with patch.object(self.service, "fit_hardware"):
                self.service.autostart_model()
            self.assertEqual(self.service.models.snapshot().target, "q4")
            self.assertTrue(self.service.models.snapshot().busy)
            self.assertGreater(self.service.models.snapshot().started_at, 0)
            self.assertEqual(self.service.preferences["kv_cache_modes"]["q4"], "q8_0")
        finally:
            gate.set()
            self.service.models.wait(3)
            self.service.manage_model = False
        saved = json.loads(self.service.preferences_path.read_text(encoding="utf-8"))
        self.assertEqual(saved["last_running_model"], "q4")
        self.assertEqual(saved["last_running_kv"], "q8_0")
        self.assertEqual(self.service.models.snapshot().status, "ready")

    def test_failed_start_does_not_replace_last_successful_model(self):
        from harness.model_switch import ModelSwitchController
        self.service.preferences.update(model="q5", last_running_model="q4")
        self.service.models = ModelSwitchController(self.cfg, ensure_fn=lambda *_: False,
                                                   stop_fn=lambda *a, **k: True, running_fn=lambda *_: False)
        response = self.client.post("/api/runtime/start").json()
        self.assertIn("switch", response)
        self.service.models.wait(2)
        self.assertEqual(self.service.models.snapshot().status, "failed")
        self.assertEqual(self.service.preferences["last_running_model"], "q4")

    def test_api_lifespan_autostarts_by_default(self):
        from unittest.mock import patch
        with patch.object(self.service, "autostart_model") as start, patch.dict("os.environ", {"QWEN_AUTOSTART_SERVER": "1"}):
            with TestClient(create_app(self.cfg, service=self.service)):
                start.assert_called_once()

    def test_reopened_desktop_autostarts_without_interrupting_active_work(self):
        from unittest.mock import patch
        with patch.object(self.service, "autostart_model") as start:
            self.client.post("/api/runtime/autostart").raise_for_status()
            start.assert_called_once()
            self.service.active = {"session_id": "test"}
            try:
                self.client.post("/api/runtime/autostart").raise_for_status()
                start.assert_called_once()
            finally:
                self.service.active = None

    def test_existing_project_chats_memory_and_skills_visible_without_conversion(self):
        project = Projects(self.cfg).create_new("Existing project")
        old = Session(self.cfg, workspace=project["path"], work_mode="research")
        old.add("user", "Work from the previous UI")
        old.add("assistant", "Existing saved answer")
        memory = self.root / "memory" / "GLOBAL.md"
        memory.parent.mkdir(exist_ok=True)
        memory.write_text("# Global memory\nKeep existing preferences", encoding="utf-8")
        skill = Path(project["path"]) / ".qwen-skills" / "existing-work"
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text("---\nname: existing-work\ndescription: Existing workflow\n---\nKeep this workflow", encoding="utf-8")
        original = (old.dir / "messages.jsonl").read_bytes()
        state = self.client.get("/api/state", params={"session_id": old.id}).json()
        self.assertIn(old.id, [s["id"] for s in state["sessions"]])
        self.assertIn(project["id"], [p["id"] for p in state["projects"]])
        chat = self.client.get(f"/api/sessions/{old.id}").json()
        self.assertEqual(chat["messages"][-1]["content"], "Existing saved answer")
        detail = self.client.get(f"/api/sessions/{old.id}/detail").json()
        self.assertIn("Keep existing preferences", detail["memory"]["global"]["content"])
        self.assertIn("existing-work", [s["name"] for s in detail["skills"]])
        self.assertEqual(original, (old.dir / "messages.jsonl").read_bytes())

    def test_fork_keeps_document_after_original_chat_deleted(self):
        sid = self.new_chat()
        session = self.service.session(sid)
        session.persist()
        source = session.dir / "attachments" / "notes.txt"
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text("Keep this document", encoding="utf-8")
        item = self.service.store.register_file(source, sid, "attachment", "notes.txt")
        session.add("user", "Read " + str(source))
        session.messages[-1]["attachments"] = [item["id"]]
        session._rewrite_jsonl()
        result = perform_action(self.service, sid, "fork", {})
        fork = self.service.session(result["session_id"])
        copied = self.service.store.file(fork.messages[-1]["attachments"][0])
        perform_action(self.service, sid, "delete", {})
        self.assertEqual(Path(copied["path"]).read_text(encoding="utf-8"), "Keep this document")
        self.assertIn(copied["path"], fork.messages[-1]["content"])
        self.assertNotEqual(copied["id"], item["id"])

    def test_navigation_does_not_rebind_running_task_and_submit_is_idempotent(self):
        first, second = self.new_chat(), self.new_chat()
        job = {"text": "hold-task", "request_id": "one"}
        self.client.post(f"/api/sessions/{first}/submit", json=job).raise_for_status()
        wait_for(lambda: bool(self.service.active))
        self.client.post(f"/api/sessions/{first}/submit", json=job).raise_for_status()
        self.client.post(f"/api/sessions/{second}/select").raise_for_status()
        self.assertEqual(self.service.active["session_id"], first)
        Model.gate.set()
        self.completed("one")
        self.assertEqual(len([m for m in self.service.session(first).messages if m.get("content") == "hold-task"]), 1)
        self.assertFalse(self.service.session(second).messages)

    def test_steering_and_queue_capture_settings(self):
        sid = self.new_chat()
        self.client.post(f"/api/sessions/{sid}/submit", json={"text": "hold-task", "request_id": "first"})
        wait_for(lambda: len(Model.calls) == 1)
        self.client.patch("/api/settings", json={"thinking": "low"})
        self.client.post(f"/api/sessions/{sid}/submit", json={"text": "clarification", "request_id": "steer"})
        self.completed("first")
        self.assertEqual(self.service.store.job("steer")["status"], "complete")
        self.assertEqual(Model.calls[-1][1]["reasoning_effort"], "xhigh")
        self.client.post(f"/api/sessions/{sid}/submit", json={"text": "next", "request_id": "next", "delivery": "queue"})
        self.completed("next")
        self.assertEqual(Model.calls[-1][1]["reasoning_effort"], "low")
        self.assertTrue(any(m.get("content") == "Partial answer." for m in self.service.session(sid).messages))

    def test_attachment_payload_names_preview_and_reload(self):
        sid = self.new_chat()
        buffer = io.BytesIO()
        Image.new("RGB", (20, 16), "green").save(buffer, format="PNG")
        uploaded = self.client.post(f"/api/sessions/{sid}/attachments", files={"file": ("náhled.png", buffer.getvalue(), "image/png")}).json()
        self.client.post(f"/api/sessions/{sid}/actions/draft", json={"text": "draft", "attachments": [uploaded]}).raise_for_status()
        self.assertEqual(self.client.get(f"/api/sessions/{sid}").json()["draft"]["attachments"][0]["name"], "náhled.png")
        self.client.post(f"/api/sessions/{sid}/submit", json={"text": "", "attachments": [uploaded["id"]], "request_id": "image"}).raise_for_status()
        self.completed("image")
        user = next(m for m in Model.calls[0][0] if isinstance(m.get("content"), list))
        self.assertTrue(any(p.get("type") == "image_url" and p["image_url"]["url"].startswith("data:image/png;base64,") for p in user["content"]))
        response = self.client.get(f"/api/sessions/{sid}").json()
        files = [f for m in response["messages"] if m["role"] == "user" for f in m["files"]]
        self.assertEqual(len(files), 1)
        self.assertEqual(files[0]["name"], "náhled.png")
        self.assertEqual(self.client.get(files[0]["url"]).content, buffer.getvalue())
        loaded = Session.load(self.cfg, sid)
        self.assertTrue(Path(next(m for m in loaded.messages if m.get("images"))["images"][0]).is_file())

    def test_stop_is_visible_and_does_not_release_queued_work(self):
        sid = self.new_chat()
        self.client.post(f"/api/sessions/{sid}/submit", json={"text": "hold-task", "request_id": "hold"})
        wait_for(lambda: bool(Model.calls))
        self.client.post(f"/api/sessions/{sid}/submit", json={"text": "next", "request_id": "queued", "delivery": "queue"})
        self.client.post(f"/api/sessions/{sid}/actions/stop", json={})
        self.completed("hold")
        self.assertEqual(self.service.store.job("hold")["status"], "stopped")
        self.assertEqual(self.service.store.job("queued")["status"], "queued")
        self.assertTrue(self.service.queue_paused)

    def test_project_move_reconfigures_chat_and_keeps_other_chat_unchanged(self):
        source = self.client.post("/api/projects", json={"name": "Project A", "mode": "writing"}).json()
        other = self.new_chat()
        sid = source["session_id"]
        result = self.client.post(f"/api/sessions/{sid}/actions/move", json={"project_id": None})
        result.raise_for_status()
        self.assertIsNone(self.service.session(sid).meta["workspace"])
        self.assertEqual(self.service.session(other).meta["work_mode"], "discussion")
        self.assertIsNone(self.service.config_for(self.service.session(sid)).agent["workspace"])

    def test_events_replay_and_no_internal_ids_in_model_payload(self):
        sid = self.new_chat()
        before = self.service.store.sequence()
        self.client.post(f"/api/sessions/{sid}/submit", json={"text": "hello", "request_id": "events"})
        self.completed("events")
        events = self.service.store.after(before, 1000)
        self.assertTrue(any(e["kind"] == "message" for e in events))
        self.assertEqual([e["seq"] for e in events], sorted(e["seq"] for e in events))
        self.assertFalse(any("id" in m or "run_id" in m for m in Model.calls[0][0]))

    def test_document_ranges_and_word_structure(self):
        import openpyxl
        from docx import Document
        wb = openpyxl.Workbook()
        ws = wb.active
        ws["A150"] = "late row"
        ws["B150"] = "=1+2"
        target = self.root / "book.xlsx"
        wb.save(target)
        text = read_document_content(target, cell_range="A150:B150", formulas=True)
        self.assertIn("late row", text)
        self.assertIn("=1+2", text)
        doc = Document()
        doc.add_paragraph("before")
        doc.add_table(rows=1, cols=1).cell(0, 0).text = "table"
        doc.add_paragraph("after")
        word = self.root / "word.docx"
        doc.save(word)
        text = read_document_content(word)
        self.assertLess(text.index("before"), text.index("table"))
        self.assertLess(text.index("table"), text.index("after"))

    def test_checkpoint_conflict_and_portable_project(self):
        project = Projects(self.cfg).create_new("Portable")
        workspace = Path(project["path"])
        file = workspace / "notes.txt"
        file.write_text("original")
        sid = self.service.new_session(str(workspace), "writing").id
        session = self.service.session(sid)
        session.add("user", "Remember this project")
        journal = ChangeJournal(session, workspace)
        cp = journal.create_checkpoint("before edit")
        file.write_text("model edit")
        journal.reconcile_workspace()
        file.write_text("later user edit")
        result = journal.undo(cp)
        self.assertTrue(result["errors"])
        self.assertEqual(file.read_text(), "later user edit")
        archive = export_project(self.cfg, project, self.root / "portable.zip")
        imported = import_project(self.cfg, archive)
        self.assertNotEqual(imported["path"], project["path"])
        self.assertEqual((Path(imported["path"]) / "notes.txt").read_text(), "later user edit")
        sessions = Session.list_sessions(self.cfg)
        self.assertTrue(any(s["workspace"] == imported["path"] for s in sessions))

    def test_portable_document_attachments_and_decision_links(self):
        project = Projects(self.cfg).create_new("Document project")
        session = self.service.new_session(project["path"], "discussion")
        target = session.dir / "attachments" / "document.txt"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("portable document")
        file = self.service.store.register_file(target, session.id, "attachment", name="document.txt")
        message = session.add("user", f"Read this document: {target}")
        message["attachments"] = [file["id"]]
        session._rewrite_jsonl()
        from harness.decisions import DecisionStore
        DecisionStore(project["path"]).save("Keep the chosen format", session.id, "accepted")
        archive = export_project(self.cfg, project, self.root / "documents.zip")
        imported = import_project(self.cfg, archive)
        imported_session = next(s for s in Session.list_sessions(self.cfg) if s["workspace"] == imported["path"])
        loaded = Session.load(self.cfg, imported_session["id"])
        copied = self.service.store.file(loaded.messages[0]["attachments"][0])
        self.assertTrue(Path(copied["path"]).is_file())
        self.assertNotEqual(copied["path"], str(target))
        self.assertIn(copied["path"], loaded.messages[0]["content"])
        self.assertEqual(DecisionStore(imported["path"]).list()[0]["source_session"], loaded.id)

    def test_recovery_keeps_partial_text_and_marks_unknown_tool_outcome(self):
        sid = self.new_chat()
        session = self.service.session(sid)
        cfg = self.service.config_for(session, {"model": "flash_next_q3"})
        session.add("user", "recover-task")
        session.add("assistant", "", tool_calls=[{"id": "crash-call", "type": "function",
                    "function": {"name": "write_file", "arguments": '{"path":"already.txt","content":"done"}'}}])
        (session.dir / "already.txt").write_text("done")
        partial = {"text": "Visible partial text", "reasoning": "", "run_id": "recover"}
        (session.dir / "run-live.json").write_text(json.dumps(partial))
        job = {"id": "recover", "session_id": sid, "text": "recover-task", "attachments": [],
               "config": cfg.data, "settings": {**copy.deepcopy(self.service.preferences), "model": "flash_next_q3"},
               "created": time.time()}
        self.service.store.save_job(job, "running")
        self.service.preferences["model"] = "q5"
        self.service.save_preferences()
        self.service.close()
        recovered = ApplicationService(self.cfg, llm_factory=Model, manage_model=False)
        try:
            self.assertEqual(recovered.store.job("recover")["status"], "interrupted")
            recovered.resume(sid)
            wait_for(lambda: recovered.store.job("recover")["status"] == "complete")
            history = recovered.session(sid).messages
            self.assertTrue(any(m.get("content") == partial["text"] for m in history))
            self.assertEqual(len([m for m in history if m.get("tool_call_id") == "crash-call"]), 1)
            self.assertEqual((session.dir / "already.txt").read_text(), "done")
            self.assertEqual(Model.calls[-1][1]["default_model"], "q5")
        finally:
            recovered.close()

    def test_compression_reads_middle_and_uses_discussion_focus(self):
        from harness.context import summarize_messages
        calls = []
        class Summarizer:
            cfg = self.cfg
            def stream(self, messages, **kwargs):
                calls.append(messages[-1]["content"])
                return AssistantResult(content="Decisions and original references preserved.")
        text = "A" * 190000 + "MIDDLE_REQUIREMENT_9281" + "Z" * 190000
        summarize_messages(Summarizer(), [{"id": "source-message", "role": "user", "content": text}])
        self.assertTrue(any("MIDDLE_REQUIREMENT_9281" in prompt for prompt in calls))
        self.assertIn("discussion", calls[0])
        self.assertNotIn("coding agent", calls[0])

    def test_pdf_vision_page_and_word_edit_preserves_style(self):
        from reportlab.pdfgen.canvas import Canvas
        from docx import Document
        from harness.tools.base import AgentContext
        from harness.tools.document_edit import EditWordTool, ViewDocumentPageTool
        session = self.service.new_session(work_mode="writing")
        ctx = AgentContext(self.cfg, session, workspace=self.root)
        ctx.changes = ChangeJournal(session, self.root)
        path = self.root / "scan.pdf"
        canvas = Canvas(str(path))
        canvas.setFillColorRGB(0, 1, 0)
        canvas.rect(10, 10, 200, 200, fill=True)
        canvas.save()
        ViewDocumentPageTool().run(ctx, str(path))
        self.assertTrue(ctx.pending_images[0].is_file())
        word = self.root / "edit.docx"
        doc = Document()
        paragraph = doc.add_paragraph()
        paragraph.add_run("Keep ").bold = True
        paragraph.add_run("old wording").italic = True
        doc.add_table(rows=1, cols=1).cell(0, 0).text = "table retained"
        doc.save(word)
        EditWordTool().run(ctx, str(word), "old wording", "new wording")
        reloaded = Document(word)
        self.assertTrue(reloaded.paragraphs[0].runs[0].bold)
        self.assertTrue(reloaded.paragraphs[0].runs[1].italic)
        self.assertEqual(reloaded.tables[0].cell(0, 0).text, "table retained")
        doc = Document()
        doc.add_paragraph("old old")
        doc.save(word)
        EditWordTool().run(ctx, str(word), "old", "old-new", replace_all=True)
        self.assertEqual(Document(word).paragraphs[0].text, "old-new old-new")


class TransportTests(unittest.TestCase):
    def test_stop_before_any_bytes_returns_quickly(self):
        cfg = load_config()
        client = LLMClient.__new__(LLMClient)
        client.cfg, client.model_name = cfg, "test"
        blocked = threading.Event()
        closed = threading.Event()
        class Stream:
            def __iter__(self):
                blocked.wait(3)
                return iter([])
            def close(self):
                closed.set()
                blocked.set()
        client.client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **kw: Stream())))
        stop = threading.Event()
        timer = threading.Timer(0.05, stop.set)
        timer.start()
        started = time.monotonic()
        result = client.stream([], should_stop=stop.is_set)
        self.assertTrue(result.stopped)
        self.assertLess(time.monotonic() - started, 0.8)
        self.assertTrue(closed.is_set())
        timer.join()


if __name__ == "__main__":
    unittest.main()
