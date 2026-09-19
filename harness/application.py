"""Single-model application service, independent of browser connections and UI frameworks."""
from __future__ import annotations

import copy
import json
import subprocess
import threading
import time
import uuid
from pathlib import Path

from harness.agent import Agent, Status, build_registry
from harness.app_storage import EventStore
from harness.browser import BrowserSession
from harness.changes import atomic_write_text
from harness.config import Config
from harness.llm import LLMClient
from harness.model_switch import ModelSwitchController
from harness.processes import ProcessManager
from harness.projects import Projects
from harness.prompts import build_system_prompt
from harness.safety import SafetyPolicy
from harness.session import IMG_MIMES, Session
from harness.work_modes import WORK_MODES, normalize_work_mode


def read_json(path: Path, fallback=None):
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return fallback if fallback is not None else {}


class ApplicationService:
    def __init__(self, cfg: Config, *, llm_factory=LLMClient, manage_model=True):
        self.cfg = cfg
        self.llm_factory = llm_factory
        self.manage_model = manage_model
        self.lock = threading.RLock()
        self.wake = threading.Condition(self.lock)
        self.closed = False
        self.queue_paused = False
        self.sessions: dict[str, Session] = {}
        self.agents: dict[str, Agent] = {}
        self.live: dict[str, dict] = {}
        self.active: dict | None = None
        self.abort = threading.Event()
        # Why the current run was interrupted: "stop", "steer" or nothing. A stop
        # takes effect at once; a clarification waits for the prompt read so the
        # cached prefix survives.
        self.abort_reason = ""
        self.models = ModelSwitchController(cfg)
        self.store = EventStore(cfg.path("paths.runtime_dir") / "application.sqlite3")
        self.preferences_path = cfg.path("paths.runtime_dir") / "workspace-settings.json"
        legacy = read_json(cfg.path("paths.runtime_dir") / "webui-state.json")
        self.preferences = {
            "model": legacy.get("model", cfg.model_key()),
            "thinking": "off" if legacy.get("thinking", cfg.data.get("thinking", True)) is False
                        else legacy.get("reasoning_effort", cfg.data.get("reasoning_effort", "xhigh")),
            "language": legacy.get("language", "en"), "theme": "dark", "density": "comfortable",
            "autonomy": legacy.get("autonomy", cfg.agent.get("autonomy", "supervised")),
            "work_mode": legacy.get("work_mode", cfg.data.get("work_mode", "discussion")),
            "session_id": legacy.get("session_id"), "kv_cache_modes": legacy.get("kv_cache_modes", {}),
            "adaptive_kv_requests": {},
            "send_mode": "steer", **read_json(self.preferences_path),
        }
        if self.preferences["model"] not in cfg.data["models"]:
            self.preferences["model"] = cfg.model_key()
        # Semantic search is opt-in; the runtime flag mirrors the saved preference.
        self.preferences.setdefault("semantic_search", False)
        # Dictation is opt-in too, and the microphone belongs to the service: a
        # reloaded page must not leave a stream open or start a second one.
        self.preferences.setdefault("voice_input", False)
        self.preferences.setdefault("voice_language", "auto")
        self.preferences.setdefault("voice_device", None)
        self.recorder = None
        self._voice_install = {"running": False, "error": "", "done": 0, "total": 0}
        self._openart_install = {"running": False, "error": "", "done": 0, "total": 0}
        # Asking the CLI who is signed in starts a process, and the settings panel
        # polls. The answer changes only when the owner signs in or out, so it is
        # remembered briefly and cleared outright when they do either.
        self._openart_account = {"at": 0.0, "value": None}
        # Where new projects are created. Empty means the folder beside the
        # installation, which is all that used to be possible.
        self.preferences.setdefault("projects_root", "")
        self.apply_projects_root(self.preferences["projects_root"])
        cfg.data["_semantic_search"] = bool(self.preferences["semantic_search"])
        self.preferences.setdefault("vram_gb", legacy.get("vram_gb", cfg.data.get("hardware", {}).get("vram_gb", "auto")))
        from harness.gpu import normalize_vram_setting
        for setting in ("vram_gb", "last_running_vram_gb"):
            if setting in self.preferences:
                try:
                    self.preferences[setting] = normalize_vram_setting(self.preferences[setting])
                except ValueError:
                    self.preferences[setting] = "auto"
        previous_key = self.preferences.get("last_running_model")
        if previous_key in cfg.data["models"] and cfg.model_ready(previous_key):
            previous = Config(copy.deepcopy(cfg.data), cfg.root)
            previous.data["default_model"] = previous_key
            previous.data.setdefault("hardware", {})["vram_gb"] = self.preferences.get("last_running_vram_gb", "auto")
            previous_profile = self.preferences.get("last_running_kv")
            if previous_profile in previous.kv_cache_profiles(previous_key):
                previous.set_kv_cache_mode(previous_key, previous_profile)
            previous_budget = previous.data["hardware"]["vram_gb"]
            preset_key = "auto" if previous_budget == "auto" else f"{float(previous_budget):g}"
            saved = self.preferences.get("memory_presets", {}).get(preset_key, {})
            from harness.hardware import detect_hardware
            if (saved.get("hardware_fingerprint") == detect_hardware().fingerprint()
                    and saved.get("model") == previous_key and saved.get("profile") == previous_profile
                    and saved.get("placement", {}).get("model") == previous_key):
                previous.data["_recovery_placement"] = copy.deepcopy(saved["placement"])
            self.models.remember_configuration(previous, previous_key)
        if manage_model:
            self.fit_hardware()
        from harness.i18n import detect_language, set_language
        if not legacy.get("language") and not self.preferences_path.exists():
            self.preferences["language"] = detect_language(cfg.root) or "en"
        # Only the legacy Gradio surface used to do this, so every message the
        # harness itself produced stayed English in the Czech interface.
        set_language(self.preferences["language"])
        for job in self.store.jobs(("running", "steering")):
            payload = job["payload"]
            if job["status"] == "running":
                old_live = cfg.path("paths.sessions_dir") / job["session_id"] / "run-live.json"
                if old_live.is_file():
                    atomic_write_text(old_live.with_name("interrupted-live.json"), old_live.read_text(encoding="utf-8"))
            self.store.save_job(payload, "interrupted" if job["status"] == "running" else "queued")
        self.worker = threading.Thread(target=self._work, name="marvin-run-controller", daemon=True)
        self.worker.start()

    # ---------------------------------------------------------------- dictation
    def voice_state(self, devices: bool = False) -> dict:
        """Dictation status. Device enumeration is skipped unless asked for: it
        queries the audio system, and the interface polls the general state."""
        from harness import speech
        absent = speech.missing(self.cfg)
        can_record, reason = speech.capture_available()
        return {
            "enabled": bool(self.preferences.get("voice_input")),
            "ready": not absent and can_record,
            "missing": absent,
            "capture_error": reason,
            "recording": bool(self.recorder and self.recorder.active),
            "seconds": self.recorder.seconds if self.recorder else 0.0,
            "language": self.preferences.get("voice_language", "auto"),
            "device": self.preferences.get("voice_device"),
            "devices": speech.input_devices() if devices else [],
            "installing": self._voice_install["running"],
            "install_error": self._voice_install["error"],
            "install_done": self._voice_install["done"],
            "install_total": self._voice_install["total"],
        }

    def voice_start(self) -> dict:
        from harness import speech
        from harness.i18n import t
        absent = speech.missing(self.cfg)
        if absent:
            raise ValueError(t("Dictation is not installed yet: {items}",
                               items=", ".join(absent)))
        can_record, reason = speech.capture_available()
        if not can_record:
            raise ValueError(reason or t("No microphone is connected."))
        self.cfg.data["speech"]["device"] = self.preferences.get("voice_device")
        if self.recorder is None:
            self.recorder = speech.Recorder(self.cfg)
        self.recorder.start()
        return self.voice_state()

    def voice_cancel(self) -> dict:
        if self.recorder:
            self.recorder.cancel()
        return self.voice_state()

    def voice_stop(self) -> dict:
        """Stop recording and return what was heard. Never sends anything."""
        from harness import speech
        if not (self.recorder and self.recorder.active):
            return {"text": "", "heard": False, **self.voice_state()}
        wav = self.recorder.stop()
        if wav is None:
            return {"text": "", "heard": False, **self.voice_state()}
        try:
            text = speech.transcribe(self.cfg, wav, self.preferences.get("voice_language"))
        finally:
            wav.unlink(missing_ok=True)
        return {"text": text, "heard": bool(text), **self.voice_state()}

    def prepare_voice_input(self) -> None:
        """Download the pinned dictation assets once, in the background."""
        from harness import speech
        if speech.ready(self.cfg) or self._voice_install["running"]:
            return
        self._voice_install.update(running=True, error="", done=0,
                                   total=speech.install_bytes())

        def _install():
            def advance(done: int, total: int) -> None:
                self._voice_install.update(done=done, total=total)

            try:
                speech.install(self.cfg, on_progress=advance)
            except Exception as error:
                self._voice_install["error"] = f"{type(error).__name__}: {error}"
            finally:
                self._voice_install["running"] = False

        threading.Thread(target=_install, name="marvin-voice-setup", daemon=True).start()

    # ---------------------------------------------------------- image generation
    OPENART_ACCOUNT_TTL = 30.0

    def openart_state(self, refresh: bool = False) -> dict:
        """Whether a picture can be generated, and what the owner still has to do."""
        from harness import openart
        installed = openart.installed(self.cfg)
        account = None
        if installed:
            now = time.time()
            fresh = now - self._openart_account["at"] < self.OPENART_ACCOUNT_TTL
            if refresh or not fresh:
                self._openart_account = {"at": now, "value": openart.account(self.cfg)}
            account = self._openart_account["value"]
        return {
            "enabled": openart.enabled(self.cfg),
            "installed": installed,
            "signed_in": bool(openart.identity(account)),
            # Identity and balance only; nothing that could be a credential.
            "account": {"name": openart.identity(account),
                        "plan": str(account.get("plan") or ""),
                        "credits": account.get("credits")} if openart.identity(account) else None,
            "models": [{"id": row[0], "description": row[1]} for row in openart.MODELS],
            "installing": self._openart_install["running"],
            "install_error": self._openart_install["error"],
            "install_done": self._openart_install["done"],
            "install_total": self._openart_install["total"],
        }

    def set_openart_enabled(self, value: bool) -> dict:
        """The owner's switch. Independent of sign-in: signed in but off stays off."""
        self.cfg.data.setdefault("openart", {})["enabled"] = bool(value)
        if value:
            self.prepare_openart()
        return self.openart_state()

    def prepare_openart(self) -> None:
        """Download the pinned CLI once, in the background."""
        from harness import openart
        if openart.installed(self.cfg) or self._openart_install["running"]:
            return
        self._openart_install.update(running=True, error="", done=0,
                                     total=openart.install_bytes())

        def _install():
            def advance(done: int) -> None:
                self._openart_install["done"] = done

            try:
                openart.install(self.cfg, on_progress=advance)
            except Exception as error:
                self._openart_install["error"] = f"{type(error).__name__}: {error}"
            finally:
                self._openart_install["running"] = False

        threading.Thread(target=_install, name="marvin-openart-setup", daemon=True).start()

    def openart_login(self) -> dict:
        """Open the browser sign-in. The owner completes it; this never sees it."""
        from harness import openart
        from harness.i18n import t
        if not openart.installed(self.cfg):
            return {"ok": False, "error": t("The image generation program is not installed.")}
        try:
            subprocess.Popen(openart.login_argv(self.cfg),
                             creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0))
        except OSError as error:
            return {"ok": False, "error": f"{type(error).__name__}: {error}"}
        self._openart_account = {"at": 0.0, "value": None}
        return {"ok": True}

    def openart_logout(self) -> dict:
        from harness import openart
        ok = openart.logout(self.cfg)
        self._openart_account = {"at": 0.0, "value": None}
        return {"ok": ok, **self.openart_state(refresh=True)}

    def apply_projects_root(self, value: str) -> str:
        """Point new projects at a folder, or back at the built-in one.

        Projects reads projects.root_dir from the live configuration, which every
        request shares, so this is the one place that has to set it."""
        if not str(value or "").strip():
            self.cfg.data.setdefault("projects", {}).pop("root_dir", None)
            return ""
        from harness.projects import validate_root
        resolved = validate_root(value, self.cfg)
        self.cfg.data.setdefault("projects", {})["root_dir"] = str(resolved)
        return str(resolved)

    def save_preferences(self):
        atomic_write_text(self.preferences_path, json.dumps(self.preferences, ensure_ascii=False, indent=2))

    def remember_running_model(self, key, profile):
        with self.lock:
            from harness.hardware import detect_hardware
            self.preferences["last_running_model"] = key
            self.preferences["last_running_kv"] = profile
            self.preferences["last_running_vram_gb"] = self.models.cfg.data.get("hardware", {}).get("vram_gb", "auto")
            budget = self.preferences["last_running_vram_gb"]
            preset_key = "auto" if budget == "auto" else f"{float(budget):g}"
            self.preferences.setdefault("memory_presets", {})[preset_key] = {
                "model": key, "profile": profile,
                "hardware_fingerprint": detect_hardware().fingerprint(),
                "placement": copy.deepcopy(self.models.cfg.data.get("_active_placement", {})),
                "recovered_context": self.models.cfg.data.get("_recovered_contexts", {}).get(key),
                "requested_profile": (self.preferences.get("adaptive_kv_requests", {}).get(key, profile)
                                      if self.models.cfg.model(key).get("adaptive_runtime") else profile)}
            self.save_preferences()

    def start_model(self, *, restart=False):
        key = self.preferences["model"]
        profile = self.preferences.get("kv_cache_modes", {}).get(key, self.cfg.kv_cache_mode(key))
        if self.cfg.model(key).get("adaptive_runtime"):
            profile = self.preferences.get("adaptive_kv_requests", {}).get(key, self.cfg.kv_cache_mode(key))
        if profile not in self.cfg.kv_cache_profiles(key):
            profile = self.cfg.kv_cache_mode(key)
        data = copy.deepcopy(self.cfg.data)
        data["default_model"] = key
        data.setdefault("hardware", {})["vram_gb"] = self.preferences.get("vram_gb", "auto")
        current = Config(data, self.cfg.root)
        preset_key = "auto" if self.preferences.get("vram_gb", "auto") == "auto" else f"{float(self.preferences['vram_gb']):g}"
        preset = self.preferences.get("memory_presets", {}).get(preset_key, {})
        from harness.hardware import detect_hardware
        if (preset.get("hardware_fingerprint") == detect_hardware().fingerprint()
                and preset.get("model") == key and preset.get("profile") == profile):
            if preset.get("placement", {}).get("model") == key:
                current.data["_recovery_placement"] = copy.deepcopy(preset["placement"])
            if preset.get("recovered_context"):
                current.data.setdefault("_recovered_contexts", {})[key] = preset["recovered_context"]
        return self.models.request(key, restart=restart, kv_profile=profile,
                                   config=current, on_success=self.model_became_ready,
                                   on_failure=lambda restored: self.model_switch_failed(key, restored))

    def model_became_ready(self, model):
        with self.lock:
            profile = self.models.cfg.kv_cache_mode(model)
            if self.models.cfg.data.pop("_memory_profile_recovered", False) and self.preferences["model"] == model:
                self.preferences.setdefault("adaptive_kv_requests", {})[model] = profile
            self.models.cfg.data.get("_recovery_origin_mtp", {}).pop(model, None)
            self.preferences.setdefault("kv_cache_modes", {})[model] = profile
            self.remember_running_model(model, profile)
            self.store.emit(None, "settings_changed", copy.deepcopy(self.preferences))

    def model_switch_failed(self, requested, restored):
        with self.lock:
            snapshot = self.models.snapshot()
            if (restored and snapshot.status == "failed" and snapshot.target == requested
                    and self.preferences["model"] == requested):
                self.preferences["model"] = restored
                self.preferences["vram_gb"] = self.models.cfg.data.get("hardware", {}).get("vram_gb", "auto")
                self.model_became_ready(restored)

    def autostart_model(self):
        if not self.manage_model:
            return
        key = self.preferences.get("last_running_model", self.preferences["model"])
        if key in self.cfg.data["models"]:
            if "last_running_vram_gb" in self.preferences:
                self.preferences["vram_gb"] = self.preferences["last_running_vram_gb"]
            elif key != self.preferences["model"]:
                # Older releases did not persist the applied budget. A pending
                # failed model selection must not poison the restored model.
                self.preferences["vram_gb"] = self.cfg.data.get("hardware", {}).get("vram_gb", "auto")
            self.preferences["model"] = key
            profile = self.preferences.get("last_running_kv")
            if profile in self.cfg.kv_cache_profiles(key):
                self.preferences.setdefault("kv_cache_modes", {})[key] = profile
        self.fit_hardware()
        self.start_model()

    def fit_hardware(self):
        from harness.gpu import best_fit, effective_vram_gb, fits
        candidate = Config(copy.deepcopy(self.cfg.data), self.cfg.root)
        candidate.data.setdefault("hardware", {})["vram_gb"] = self.preferences.get("vram_gb", "auto")
        key = self.preferences["model"]
        if candidate.model(key).get("adaptive_runtime"):
            # Full planning happens after the old model frees its resources. Do not
            # change model identity based solely on a VRAM-only preflight.
            return
        candidate.data["default_model"] = key
        profile = self.preferences.get("kv_cache_modes", {}).get(key, candidate.kv_cache_mode(key))
        if profile not in candidate.kv_cache_profiles(key):
            profile = candidate.kv_cache_mode(key)
            self.preferences.setdefault("kv_cache_modes", {})[key] = profile
        if profile in candidate.kv_cache_profiles(key):
            candidate.set_kv_cache_mode(key, profile)
        vram = effective_vram_gb(candidate)
        if vram and not fits(candidate, key, profile, vram):
            choice = best_fit(candidate, vram)
            if choice:
                self.preferences["model"] = choice[0]
                self.preferences.setdefault("kv_cache_modes", {})[choice[0]] = choice[1]

    def session(self, session_id: str) -> Session:
        with self.lock:
            if session_id not in self.sessions:
                self.sessions[session_id] = Session.load(self.cfg, session_id)
            return self.sessions[session_id]

    def new_session(self, workspace=None, work_mode=None):
        with self.lock:
            if workspace and not Path(workspace).is_dir():
                raise FileNotFoundError(f"Project folder is unavailable: {workspace}")
            mode = normalize_work_mode(work_mode or self.preferences["work_mode"])
            session = Session(self.cfg, workspace=workspace or None, work_mode=mode, transient=True)
            self.sessions[session.id] = session
            self.select_session(session.id)
            self.store.emit(session.id, "session_changed", {"id": session.id})
            return session

    def select_session(self, session_id):
        session = self.session(session_id)
        self.preferences["session_id"] = session.id
        self.save_preferences()
        return session

    def select_project(self, project_id=None):
        project = next((p for p in Projects(self.cfg).list_all() if p["id"] == project_id), None)
        if project and project.get("missing"):
            raise FileNotFoundError(f"Project folder is unavailable: {project['path']}")
        workspace = project["path"] if project else None
        matches = [s for s in Session.list_sessions(self.cfg, limit=100000) if s.get("workspace") == workspace]
        return self.select_session(matches[0]["id"]) if matches else self.new_session(
            workspace, project.get("work_mode") if project else "discussion")

    def config_for(self, session, settings=None):
        if session.meta.get("workspace") and not Path(session.meta["workspace"]).is_dir():
            raise FileNotFoundError(f"Project folder is unavailable: {session.meta['workspace']}")
        preferences = {**self.preferences, **(settings or {})}
        data = copy.deepcopy(self.cfg.data)
        data["default_model"] = preferences["model"]
        data["thinking"] = preferences["thinking"] != "off"
        data["reasoning_effort"] = preferences["thinking"] if data["thinking"] else "xhigh"
        data["work_mode"] = session.meta.get("work_mode") or preferences["work_mode"]
        data["agent"]["workspace"] = session.meta.get("workspace")
        data["agent"]["autonomy"] = preferences["autonomy"]
        data["agent"]["mode"] = WORK_MODES[data["work_mode"]].agent_mode
        data.setdefault("hardware", {})["vram_gb"] = preferences.get("vram_gb", "auto")
        cfg = Config(data, self.cfg.root)
        for model, profile in preferences.get("kv_cache_modes", {}).items():
            if model in data["models"] and profile in cfg.kv_cache_profiles(model):
                cfg.set_kv_cache_mode(model, profile)
        return cfg

    def submit(self, session_id, text, attachments=None, *, request_id=None, delivery="steer", kind="message"):
        with self.wake:
            self.queue_paused = False
            request_id = request_id or uuid.uuid4().hex
            existing = self.store.job(request_id)
            if existing:
                return existing
            session = self.session(session_id)
            cfg = self.config_for(session)
            files = [self.store.file(key) for key in (attachments or [])]
            if any(not f or f["session_id"] != session_id for f in files):
                raise ValueError("Attachment does not belong to this conversation")
            if any(Path(f["path"]).suffix.lower() in IMG_MIMES for f in files) and not cfg.mmproj_file():
                raise ValueError("Selected model has no vision. Choose a vision-capable model; attachments remain in the draft.")
            if kind == "message" and not text.strip() and not files:
                raise ValueError("Message is empty")
            job = {"id": request_id, "session_id": session_id, "text": text,
                   "attachments": [f["id"] for f in files], "delivery": delivery, "kind": kind,
                   "settings": copy.deepcopy(self.preferences), "config": copy.deepcopy(cfg.data),
                   "created": time.time()}
            status = "queued"
            if (self.active and self.active["session_id"] == session_id
                    and delivery == "steer" and kind == "message" and not text.startswith("/")):
                status = "steering"
                self.abort_reason = "steer"
                self.abort.set()
                if (self.live.get(session_id) or {}).get("phase") == "reading_context":
                    # Say so, or the silence looks like the message was lost.
                    self.store.emit(session_id, "notice", {
                        "kind": "steer_deferred", "text": "",
                        "run_id": self.active["id"], "created": time.time()})
            self.store.save_job(job, status)
            self.store.emit(session_id, "submission", {"id": request_id, "status": status, **job})
            self.wake.notify_all()
            return self.store.job(request_id)

    def edit_queued(self, request_id, text=None, cancel=False):
        with self.lock:
            job = self.store.job(request_id)
            if not job or job["status"] not in ("queued", "steering"):
                raise ValueError("This message has already started")
            payload = job["payload"]
            if text is not None:
                payload["text"] = text
            self.store.save_job(payload, "cancelled" if cancel else job["status"])
            self.store.emit(job["session_id"], "queue_changed", {})

    def stop(self, session_id=None):
        with self.lock:
            if self.active and (not session_id or self.active["session_id"] == session_id):
                self.queue_paused = True
                self.abort_reason = "stop"
                self.abort.set()
                self.store.emit(self.active["session_id"], "run_status", {"status": "stopping", "run_id": self.active["id"]})
                return True
            return False

    def resume(self, session_id, approve=None):
        with self.wake:
            self.queue_paused = False
            candidates = [j for j in self.store.jobs(("interrupted", "stopped", "failed", "waiting_confirmation"))
                          if j["session_id"] == session_id]
            if not candidates:
                raise ValueError("No interrupted task in this chat")
            job = copy.deepcopy(candidates[-1]["payload"])
            # Continue resumes the work, not its old GPU allocation. A manual
            # model/KV change after a failure must remain authoritative. Keep
            # the task's mode, reasoning and safety settings intact.
            current = self.config_for(self.session(session_id))
            key = current.model_key()
            for name in ("model", "kv_cache_modes", "adaptive_kv_requests", "vram_gb"):
                job["settings"][name] = copy.deepcopy(self.preferences[name])
            job["config"]["default_model"] = key
            job["config"]["models"][key] = copy.deepcopy(current.model(key))
            job["config"]["hardware"] = copy.deepcopy(current.data.get("hardware", {}))
            job.pop("error", None)
            job["resume"] = True
            job["approve"] = approve
            self.store.save_job(job, "queued")
            self.wake.notify_all()
            return job

    def _work(self):
        while True:
            with self.wake:
                jobs = self.store.jobs(("queued",))
                if self.closed:
                    return
                if not jobs or self.queue_paused:
                    self.wake.wait(timeout=0.5)
                    continue
                job = jobs[0]["payload"]
                self.active = job
                self.abort = threading.Event()
                self.abort_reason = ""
                self.store.save_job(job, "running")
            try:
                self._drive(job)
            except Exception as exc:
                status = "stopped" if self.abort.is_set() else "failed"
                job["error"] = str(exc) if status == "failed" else ""
                self.store.save_job(job, status)
                self._emit_failure(job["session_id"], job["id"], job["error"])
                self.store.emit(job["session_id"], "run_status", {"status": status, "error": job["error"], "run_id": job["id"]})
            finally:
                with self.wake:
                    # A submit can arrive after _drive's final steering check but before
                    # active is cleared. No run remains to consume that steering: retain
                    # it as normal queued work, under the same lock used by submit.
                    late = [item for item in self.store.jobs(("steering",))
                            if item["session_id"] == job["session_id"]]
                    for item in late:
                        self.store.save_job(item["payload"], "queued")
                    if late:
                        self.store.emit(job["session_id"], "queue_changed", {})
                    self.active = None
                    self.wake.notify_all()

    def _image_paths(self, job):
        files = [self.store.file(key) for key in job.get("attachments", [])]
        return [Path(f["path"]) for f in files if f and Path(f["path"]).suffix.lower() in IMG_MIMES]

    def _job_text(self, job):
        text = job["text"]
        files = [self.store.file(key) for key in job.get("attachments", [])]
        docs = [f for f in files if f and Path(f["path"]).suffix.lower() not in IMG_MIMES]
        if docs:
            text += "\n\nAttached documents available through read_document:\n" + "\n".join(f["path"] for f in docs)
        return text or "Please analyze the attached image(s)."

    @staticmethod
    def _seal_interrupted_tools(session):
        answered = {m.get("tool_call_id") for m in session.messages if m.get("role") == "tool"}
        pending = [call for m in session.messages for call in m.get("tool_calls", []) if call["id"] not in answered]
        for call in pending:
            session.add("tool", "Execution was interrupted; outcome unknown. Inspect actual state before retrying.",
                        tool_call_id=call["id"], name=call["function"]["name"])

    def _emit_failure(self, session_id: str, run_id: str, error: str) -> None:
        """Leave a failure where the user can still find it.

        run_status only raises a toast, which fades; someone who does not program
        is then left with nothing. A notice is durable and carries the next step
        when the failure is one we recognise."""
        if not (error or "").strip():
            return
        from harness.failures import failure_notice
        self.store.emit(session_id, "notice",
                        failure_notice(error, run_id, time.time()))

    def _maybe_autocommit(self, agent, session, job, result_text: str) -> str | None:
        """Commit the task's changed files when the project opted into auto-commit.

        Runs after a successfully completed development/computer task in a Git
        repository. Failures never fail the run; they surface as a notice."""
        workspace = session.meta.get("workspace")
        if not workspace or agent.work_mode not in ("development", "computer"):
            return None
        from harness.projects import Projects
        project = Projects(self.cfg).by_path(workspace)
        if not (project or {}).get("autocommit"):
            return None
        from harness.tools.git import commit_files, is_repo, task_paths
        if not is_repo(agent.ctx):
            return None
        paths = task_paths(agent.ctx)
        if not paths:
            return None
        message = self._autocommit_message(agent, session, job, result_text)
        if not message:
            return None
        from harness.i18n import t
        result = commit_files(agent.ctx, paths, message)
        if not result.get("ok"):
            return t("Auto-commit failed: {error}", error=str(result.get("error"))[:300])
        # Phrased so it needs no plural agreement in either language.
        return t("Auto-committed as {hash} ({count} files)",
                 hash=result.get("hash") or "HEAD", count=len(paths))

    @staticmethod
    def _autocommit_message(agent, session, job, result_text: str) -> str:
        """Subject from the task goal, body from the final summary's Done section."""
        plan = agent.ctx.task_plan.load() if agent.ctx.task_plan else {}
        goal = str(plan.get("goal") or job.get("text") or "").strip().replace("\n", " ")
        subject = (goal[:97] + "…") if len(goal) > 100 else goal
        if not subject:
            return ""
        done: list[str] = []
        in_done = False
        for line in (result_text or "").splitlines():
            stripped = line.strip()
            if not in_done and stripped.startswith("✅"):
                in_done = True
            elif in_done and stripped.startswith(("🔍", "📋", "⏸")):
                break
            if in_done:
                done.append(line.rstrip())
        body = "\n".join(done).strip()[:1500]
        if not body:
            validations = plan.get("validations") or []
            if validations:
                last = validations[-1]
                body = f"Validation: {last.get('status')} — {last.get('label')}"
        trailer = (f"Marvin: session {session.id} · task "
                   f"{agent.ctx.changes.summary().get('task_id', '')}")
        return f"{subject}\n\n{body}\n\n{trailer}" if body else f"{subject}\n\n{trailer}"

    def _recover_memory_profile(self, cfg, job, live, session):
        """Retry a pressure-interrupted model call with a smaller context, at most
        once per available context. Completed tool results remain in history."""
        if not self.manage_model or self.abort.is_set():
            return False
        from harness import servermgmt
        failure = servermgmt.last_failure(cfg)
        if (failure.get("code") not in ("ram_pressure", "vram_pressure") or failure.get("model") != cfg.model_key()
                or failure.get("time", 0) < live["started"]):
            return False
        from harness.gpu import lower_memory_profiles
        choices = lower_memory_profiles(cfg)
        if not choices:
            return False
        profile = choices[0]
        key = cfg.model_key()
        if cfg.kv_cache_profiles(key).get(cfg.kv_cache_mode(key), {}).get("speculative") == "mtp":
            # Keep interleaving MTP/plain variants during this recovery sequence.
            cfg.data.setdefault("_recovery_origin_mtp", {})[key] = True
        from harness.measured_profiles import freeze_placement
        active = self.models.cfg.data.get("_active_placement", {})
        if active.get("model") == key:
            cfg.data["_active_placement"] = copy.deepcopy(active)
        freeze_placement(cfg, key)
        cfg.data.setdefault("_recovered_contexts", {})[key] = cfg.kv_cache_profiles(key)[profile]["ctx_size"]
        if live.get("text") or live.get("reasoning"):
            session.add("assistant", live.get("text", ""), reasoning=live.get("reasoning", ""))
        self._seal_interrupted_tools(session)
        from harness.i18n import t
        self.store.emit(session.id, "notice", {"text": t("Adjusting the memory profile and continuing the task."),
                                              "run_id": job["id"], "created": time.time()})
        from harness import restart_log
        restart_log.record_for(cfg, reason="memory_pressure_recovery", wanted=key,
                               running=key, profile=profile, note=failure.get("code"))
        live.update(phase="loading_model", phase_started=time.time(), text="", reasoning="", prompt_progress=None)
        self.models.request(key, restart=True, kv_profile=profile, config=cfg,
                            on_success=self.model_became_ready,
                            on_failure=lambda restored: self.model_switch_failed(key, restored))
        while self.models.snapshot().busy and not self.abort.wait(.1):
            pass
        if self.abort.is_set() or self.models.snapshot().status != "ready":
            return False
        if not servermgmt.health(cfg) or servermgmt.running_model(cfg) != key:
            return False
        applied = self.models.cfg.kv_cache_mode(key)
        if applied == cfg.kv_cache_mode(key):
            return False
        cfg.set_kv_cache_mode(key, applied)
        cfg.data["_active_placement"] = copy.deepcopy(self.models.cfg.data.get("_active_placement", {}))
        job["config"] = copy.deepcopy(cfg.data)
        job["settings"].setdefault("kv_cache_modes", {})[key] = applied
        self.store.save_job(job, "running")
        with self.lock:
            if (self.preferences["model"] == key and cfg.model(key).get("adaptive_runtime")
                    and self.preferences.get("vram_gb", "auto") == cfg.data.get("hardware", {}).get("vram_gb", "auto")):
                self.preferences.setdefault("adaptive_kv_requests", {})[key] = applied
            self.remember_running_model(key, applied)
        return True

    def _drive(self, job):
        sid, rid = job["session_id"], job["id"]
        session = self.session(sid)
        cfg = Config(copy.deepcopy(job["config"]), self.cfg.root)
        if self.manage_model:
            # Device limits and corrected profile definitions belong to this PC,
            # not to the date when an old queued request was recorded.
            from harness.gpu import best_fit, effective_vram_gb, fits
            key, profile = cfg.model_key(), cfg.kv_cache_mode()
            with self.lock:
                cfg.data["models"] = copy.deepcopy(self.cfg.data["models"])
                cfg.data.setdefault("hardware", {})["vram_gb"] = self.preferences.get("vram_gb", "auto")
            if key not in cfg.data["models"]:
                key = self.preferences["model"]
            cfg.data["default_model"] = key
            if profile in cfg.kv_cache_profiles(key):
                cfg.set_kv_cache_mode(key, profile)
            budget = effective_vram_gb(cfg)
            if not cfg.model(key).get("adaptive_runtime") and not fits(cfg, key, cfg.kv_cache_mode(key), budget):
                choice = best_fit(cfg, budget)
                if not choice:
                    raise RuntimeError("No model profile fits the current GPU memory budget")
                key, profile = choice
                cfg.data["default_model"] = key
                cfg.set_kv_cache_mode(key, profile)
            job["config"] = copy.deepcopy(cfg.data)
            job["settings"]["model"] = key
            job["settings"]["vram_gb"] = cfg.data["hardware"]["vram_gb"]
            job["settings"].setdefault("kv_cache_modes", {})[key] = cfg.kv_cache_mode(key)
            self.store.save_job(job, "running")
        cfg.agent["workspace"] = session.meta.get("workspace")
        mode = cfg.data["work_mode"]
        spec = WORK_MODES[mode]
        llm = self.llm_factory(cfg)
        live_path = session.dir / "run-live.json"
        first_step = 1 + max((m.get("step_id", -1) for m in session.messages if m.get("run_id") == rid), default=-1)
        live = {"run_id": rid, "session_id": sid, "step": first_step, "text": "", "reasoning": "",
                "phase": "preparing", "tool": "", "tool_chars": 0, "started": time.time(),
                "config": {"model": cfg.model_key(), "thinking": job["settings"]["thinking"], "work_mode": mode}}
        self.live[sid] = live
        last_flush = [0.0]

        def flush(force=False):
            now = time.monotonic()
            if force or now - last_flush[0] >= 0.3:
                last_flush[0] = now
                atomic_write_text(live_path, json.dumps(live, ensure_ascii=False))
                self.store.emit(sid, "live", dict(live))

        def event(kind, payload):
            previous_phase = live["phase"]
            if kind == "text":
                live["text"] += payload
                live["phase"] = "answering"
            elif kind == "reasoning":
                live["reasoning"] += payload
                live["phase"] = "thinking"
            elif kind == "tool_delta":
                name, arguments = payload
                live["tool"] = name or live["tool"]
                live["tool_chars"] += len(arguments or "")
                live["phase"] = "preparing_tool"
            elif kind == "prompt_progress":
                live["phase"] = "reading_context"
                live["prompt_progress"] = payload
            elif kind == "generation_started":
                live["phase"] = "generating"
            elif kind == "tool_start":
                live["phase"] = "executing"
                live["tool"] = payload[0]
                live["arguments"] = {k: str(v)[:500] for k, v in (payload[1] or {}).items() if k not in ("content", "data")}
            elif kind == "usage":
                self.store.emit(sid, "usage", payload)
            elif kind == "tool_result":
                self.store.emit(sid, "tool_completed", {"name": payload[0]})
            elif kind == "info":
                live["info"] = str(payload)
                self.store.emit(sid, "notice", {"text": str(payload), "run_id": rid, "created": time.time()})
            if live["phase"] != previous_phase:
                live["phase_started"] = time.time()
            flush(kind in ("tool_start", "tool_result", "info"))

        def message_saved(message):
            self.store.emit(sid, "message", self.message_payload(session, message))

        def capture_context():
            import hashlib
            from harness.memory import MemoryStore
            memory = MemoryStore(cfg, session.meta.get("workspace"), mode)
            records = []
            for scope in ("global", "mode", "project"):
                path = memory._path_for(scope)
                if path and path.is_file():
                    content = path.read_text(encoding="utf-8")
                    records.append({"scope": scope, "path": str(path), "content": content,
                                    "sha256": hashlib.sha256(content.encode()).hexdigest()})
            target = session.dir / "runs" / rid / f"context-{live['step']}.json"
            snapshot = {"run_id": rid, "created": time.time(), "work_mode": mode,
                        "model": cfg.model_key(), "memory": records,
                        "pinned_files": list(session.meta.get("pinned_files", [])),
                        "system_prompt": session.messages[0].get("content", "") if session.messages else ""}
            atomic_write_text(target, json.dumps(snapshot, ensure_ascii=False, indent=2))
            session.meta["context_snapshot"] = str(target)
            session._save_meta()

        session.on_message = message_saved
        session.run_id = rid
        session.request_id = rid
        if not session.messages or session.messages[0].get("role") != "system":
            session.messages.insert(0, {"role": "system", "content": "", "id": f"{sid}:system"})
        previous_agent = self.agents.get(sid)
        agent = Agent(cfg, llm, session, build_registry(spec.agent_mode, mode, cfg),
                      SafetyPolicy(autonomy=cfg.agent["autonomy"]), mode=spec.agent_mode,
                      work_mode=mode, abort_flag=self.abort, on_event=event,
                      may_abort_prefill=lambda: self.abort_reason != "steer",
                      process_manager=previous_agent.ctx.processes if previous_agent else None,
                      browser_manager=previous_agent.ctx.browser if previous_agent else None)
        if not session.meta.get("workspace"):
            agent.ctx.workspace = session.dir
            agent.ctx.changes.set_workspace(session.dir)
        self.agents[sid] = agent
        agent._overflow_retried = False
        flush(True)
        try:
            if job.get("kind") == "command" or job["text"].startswith("/"):
                from harness.app_operations import execute_command
                transformed = execute_command(self, agent, job)
                if transformed is None:
                    self.store.save_job(job, "complete")
                    return
                job = {**job, "text": transformed}
            if self.manage_model:
                from harness import servermgmt
                key = cfg.model_key()
                profile_changed = cfg.kv_cache_mode(key) != self.models.cfg.kv_cache_mode(key)
                hardware_changed = cfg.data.get("hardware") != self.models.cfg.data.get("hardware")
                # Ask each condition once and keep the answers. A restart throws
                # away the processed prompt - 92 seconds for 150k tokens - and
                # until now the decision recorded nothing about why it was taken.
                healthy = servermgmt.health(cfg)
                running = servermgmt.running_model(cfg)
                if profile_changed or hardware_changed or not healthy or running != key:
                    from harness import restart_log
                    restart_log.record_for(
                        cfg,
                        reason=restart_log.reasons(profile_changed=profile_changed,
                                                   hardware_changed=hardware_changed,
                                                   healthy=healthy, running=running, wanted=key),
                        wanted=key, running=running, profile=cfg.kv_cache_mode(key))
                    live["phase"] = "loading_model"
                    flush(True)
                    profile = cfg.kv_cache_mode(key)
                    if cfg.model(key).get("adaptive_runtime"):
                        profile = job["settings"].get("adaptive_kv_requests", {}).get(key, self.cfg.kv_cache_mode(key))
                    self.models.request(key, restart=bool(profile_changed or hardware_changed), kv_profile=profile, config=cfg,
                                        on_success=self.model_became_ready,
                                        on_failure=lambda restored: self.model_switch_failed(key, restored))
                    while self.models.snapshot().busy and not self.abort.wait(0.1):
                        pass
                    if self.abort.is_set():
                        self.store.save_job(job, "stopped")
                        return
                    if (self.models.snapshot().status != "ready" or not servermgmt.health(cfg)
                            or servermgmt.running_model(cfg) != key):
                        raise RuntimeError(self.models.snapshot().error or "Model server is not ready")
                cfg.set_kv_cache_mode(key, self.models.cfg.kv_cache_mode(key))
                self.remember_running_model(key, cfg.kv_cache_mode(key))
            if job.get("resume"):
                saved_live = read_json(session.dir / "interrupted-live.json")
                if saved_live.get("text") and not any(m.get("content") == saved_live["text"] for m in session.messages[-8:]):
                    session.add("assistant", saved_live["text"], reasoning=saved_live.get("reasoning"))
                # A missing tool result after a crash must be inspected, never blindly replayed.
                self._seal_interrupted_tools(session)
                agent.refresh_system_prompt()
            else:
                for previous in self.store.jobs(("interrupted", "stopped", "failed", "waiting_confirmation")):
                    if previous["session_id"] == sid and previous["id"] != rid:
                        self.store.save_job(previous["payload"], "superseded")
                agent.new_task(self._job_text(job), images=self._image_paths(job))
                user = next((m for m in reversed(session.messages) if Session._is_user_boundary(m)), None)
                if user and job.get("attachments"):
                    user["attachments"] = job["attachments"]
                    session._rewrite_jsonl()
                    message_saved(user)
                if session.meta.get("workspace") and mode in ("development", "computer", "writing"):
                    agent.ctx.changes.capture_workspace()
            approve = job.get("approve")
            capture_context()
            while True:
                live.update(step=live["step"] + 1, text="", reasoning="", tool="", tool_chars=0,
                            phase="preparing", prompt_progress=None, phase_started=time.time())
                session.step_id = live["step"]
                flush(True)
                result = agent.step(approve=approve)
                approve = None
                flush(True)
                if agent.ctx.project_workspace:
                    agent.ctx.changes.reconcile_workspace()
                steering = [item for item in self.store.jobs(("steering",)) if item["session_id"] == sid]
                if steering:
                    for item in steering:
                        addition = item["payload"]
                        session.request_id = addition["id"]
                        agent.steer(self._job_text(addition), images=self._image_paths(addition))
                        user = next(m for m in reversed(session.messages) if Session._is_user_boundary(m))
                        user["attachments"] = addition.get("attachments", [])
                        session._rewrite_jsonl()
                        message_saved(user)
                        self.store.save_job(addition, "complete")
                    capture_context()
                    self.abort.clear()
                    self.abort_reason = ""
                    continue
                if result.status is Status.CONTINUE:
                    continue
                if result.status is Status.ERROR and self._recover_memory_profile(cfg, job, live, session):
                    agent._overflow_retried = False
                    agent.refresh_system_prompt()
                    capture_context()
                    continue
                if result.status is Status.ERROR and self.manage_model:
                    from harness import servermgmt
                    failure = servermgmt.last_failure(cfg)
                    if (failure.get("model") == cfg.model_key() and failure.get("time", 0) >= live["started"]
                            and failure.get("code") in ("ram_pressure", "vram_pressure")):
                        result.text = failure["error"]
                        job["error"] = result.text
                status = "stopped" if self.abort.is_set() else {
                    Status.FINAL: "complete", Status.ABORTED: "stopped",
                    Status.ERROR: "failed", Status.NEEDS_CONFIRMATION: "waiting_confirmation"}[result.status]
                if status == "complete":
                    commit_note = self._maybe_autocommit(agent, session, job, result.text)
                else:
                    commit_note = None
                self.store.save_job(job, status)
                if status in ("stopped", "failed") and (live["text"] or live["reasoning"]):
                    if not any(m.get("role") == "assistant" and m.get("step_id") == live["step"]
                               and m.get("run_id") == rid for m in session.messages[-8:]):
                        session.add("assistant", live["text"], reasoning=live["reasoning"])
                if commit_note:
                    self.store.emit(sid, "notice", {"text": commit_note,
                                                    "run_id": rid, "created": time.time()})
                if status == "failed":
                    self._emit_failure(sid, rid, job.get("error") or result.text)
                self.store.emit(sid, "run_status", {"run_id": rid, "status": status,
                    "text": result.text, "pending": result.pending_summary if status == "waiting_confirmation" else [],
                    "usage": session.meta.get("last_usage", {})})
                if status == "failed" and live.get("text"):
                    atomic_write_text(session.dir / "interrupted-live.json", json.dumps(live, ensure_ascii=False))
                return
        finally:
            session.on_message = None
            live["phase"] = "idle"
            flush(True)
            self.discover_results(session, agent)
            self.store.emit(sid, "session_changed", {"id": sid})

    def message_payload(self, session, message):
        value = copy.deepcopy(message)
        value["files"] = [self.store.register_file(path, session.id, "image")
                          for path in message.get("images", []) if Path(path).is_file()]
        for key in message.get("attachments", []):
            item = self.store.file(key)
            if item and not any(f["path"] == item["path"] for f in value["files"]):
                value["files"].append(self.store.register_file(item["path"], session.id, "attachment"))
        return value

    def discover_results(self, session, agent=None):
        directories = [session.dir / "exports"]
        if session.meta.get("workspace"):
            directories.append(Path(session.meta["workspace"]) / "exports")
        for directory in directories:
            if directory.is_dir():
                for path in directory.iterdir():
                    if path.is_file():
                        self.store.register_file(path, session.id)
        if agent:
            for item in agent.ctx.changes.summary().get("files", []):
                path = agent.ctx.workspace / item["path"]
                if item["changed"] and path.is_file():
                    self.store.register_file(path, session.id, "changed")

    def close(self):
        with self.wake:
            self.closed = True
            self.abort_reason = "stop"
            self.abort.set()
            self.wake.notify_all()
        self.worker.join(timeout=3)
