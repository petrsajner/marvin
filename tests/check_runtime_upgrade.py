"""Compare a staged llama.cpp with the installed runtime, one local model at a time.

Uses existing weights, Config/LLMClient/ApplicationService and isolated task data.
Never downloads a model, updates the active runtime, or changes user settings.
Example: python -B tests/check_runtime_upgrade.py --candidate runtime/candidates/llama-b10935-cuda13.3/bin
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
import re
import platform
import subprocess
import sys
import threading
import time

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")

import psutil
import requests
from PIL import Image, ImageDraw, ImageFont

from harness.application import ApplicationService
from harness.config import Config, load_config
from harness.llm import LLMClient
from harness.session import Session
from harness import servermgmt


def digest(path: Path) -> str:
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def save(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    pending = path.with_suffix(".pending")
    pending.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    pending.replace(path)


def require(condition, detail):
    if not condition:
        raise AssertionError(detail)


def stop_owned(cfg):
    """Verify executable ownership before stopping this isolated audit's server."""
    pf = servermgmt.pid_file(cfg)
    if not pf.exists():
        return
    try:
        pid = int(pf.read_text().split(":")[1])
        process = psutil.Process(pid)
        expected = cfg.llama_server_exe().resolve()
        require(Path(process.exe()).resolve() == expected, "Audit PID belongs to a different executable")
    except psutil.NoSuchProcess:
        pf.unlink(missing_ok=True)
        return
    servermgmt.stop(cfg, quiet=True)


class ResourceWatch:
    """Record host pressure; stop only this audit's server before host RAM exhaustion."""
    def __init__(self, cfg):
        self.cfg = cfg
        self.done = threading.Event()
        self.stats = {"min_available_ram_mib": None, "peak_device_used_mib": 0,
                      "peak_server_private_mib": 0, "peak_server_rss_mib": 0}
        self.thread = threading.Thread(target=self.run, name="runtime-audit-memory", daemon=True)

    def run(self):
        low = 0
        while not self.done.is_set():
            available = psutil.virtual_memory().available / 2**20
            old = self.stats["min_available_ram_mib"]
            self.stats["min_available_ram_mib"] = round(min(available, old) if old is not None else available)
            low = low + 1 if available < 2048 else 0
            if low >= 2:
                self.stats["guard_stop"] = "Available host RAM below 2 GiB"
                stop_owned(self.cfg)
                return
            try:
                pid = int(servermgmt.pid_file(self.cfg).read_text().split(":")[1])
                memory = psutil.Process(pid).memory_info()
                self.stats["peak_server_private_mib"] = max(self.stats["peak_server_private_mib"],
                    round(getattr(memory, "private", memory.vms) / 2**20))
                self.stats["peak_server_rss_mib"] = max(self.stats["peak_server_rss_mib"], round(memory.rss / 2**20))
            except (OSError, ValueError, IndexError, psutil.Error):
                pass
            try:
                result = subprocess.run(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
                    capture_output=True, text=True, timeout=3, creationflags=servermgmt.NO_WINDOW)
                value = int(result.stdout.strip().splitlines()[0])
                self.stats["peak_device_used_mib"] = max(value, self.stats["peak_device_used_mib"])
            except Exception:
                pass
            self.done.wait(2)

    def start(self):
        self.thread.start()

    def close(self):
        self.done.set()
        self.thread.join(timeout=5)


class Probes:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.llm = LLMClient(cfg)
        self.last = {}

    def call(self, messages, *, thinking=False, tools=None, max_tokens=256, seconds=90, stop=None):
        if self.cfg.model().get("adaptive_runtime"):
            seconds = max(seconds, 180)
        abort = stop or threading.Event()
        timer = threading.Timer(seconds, abort.set)
        timer.daemon = True
        started = time.monotonic()
        first = []

        def received(text):
            if text and not first:
                first.append(time.monotonic())

        sampling = dict(self.cfg.sampling(thinking))
        sampling.update(temperature=0, top_p=1, top_k=1, presence_penalty=0,
                        max_tokens=max_tokens, seed=1729)
        timer.start()
        try:
            result = self.llm.stream(messages, tools=tools, sampling=sampling,
                                     thinking=thinking, on_text=received,
                                     on_reasoning=received, should_stop=abort.is_set)
            self.last = {
                "seconds": round(time.monotonic() - started, 3),
                "first_token_seconds": round(first[0] - started, 3) if first else None,
                "content": result.content, "reasoning_chars": len(result.reasoning),
                "tool_calls": result.tool_calls, "usage": result.usage,
                "stopped": result.stopped,
            }
            require(not result.stopped or stop is not None, "Probe deadline/cancellation reached")
            return result
        finally:
            timer.cancel()

    def chat(self):
        r = self.call([{"role": "user", "content": "Kolik je 37 + 58? Odpověz pouze číslem."}])
        require(re.search(r"\b95\b", r.content), repr(r.content))
        return self.last

    def decode(self):
        self.call([{"role": "user", "content":
            "Write a numbered list of 100 practical tips for organizing a personal library. "
            "Use one complete sentence per tip. Keep going until all 100 are written."}],
            max_tokens=256, seconds=180)
        tokens = self.last.get("usage", {}).get("completion_tokens", 0)
        elapsed = self.last["seconds"] - (self.last["first_token_seconds"] or 0)
        require(tokens >= 128, "Insufficient generated tokens for a decode measurement")
        return {**self.last, "decode_tokens_per_second": round((tokens - 1) / max(.001, elapsed), 2)}

    def thinking(self):
        r = self.call([{"role": "user", "content": "Check 37 + 58 carefully and give the result."}],
                      thinking=True, max_tokens=768)
        require(re.search(r"\b95\b", r.content), repr(r.content))
        require(bool(r.reasoning), "No reasoning field was delivered to Marvin")
        return self.last

    def tool_roundtrip(self):
        tools = [{"type": "function", "function": {
            "name": "lookup_inventory", "description": "Return current inventory from the live warehouse.",
            "parameters": {"type": "object", "properties": {
                "sku": {"type": "string"}, "warehouse": {"type": "string"}},
                "required": ["sku", "warehouse"], "additionalProperties": False}}}]
        messages = [{"role": "system", "content": "Use the provided inventory tool. Never invent stock values."},
                    {"role": "user", "content": "Find current stock of SKU BOLT-17 in warehouse PRG. Call lookup_inventory, then report the returned count."}]
        r = self.call(messages, tools=tools)
        first = copy.deepcopy(self.last)
        require(len(r.tool_calls) == 1, repr(r.tool_calls))
        tc = r.tool_calls[0]
        require(tc["function"]["name"] == "lookup_inventory", repr(tc))
        args = json.loads(tc["function"]["arguments"])
        require(args == {"sku": "BOLT-17", "warehouse": "PRG"}, repr(args))
        messages.append({"role": "assistant", "content": r.content, "tool_calls": r.tool_calls})
        messages.append({"role": "tool", "tool_call_id": tc["id"],
                         "content": json.dumps({"available": 73, "source": "runtime-audit"})})
        answer = self.call(messages, tools=tools)
        require("73" in answer.content and not answer.tool_calls, repr(answer.content))
        return {"request": first, "continuation": self.last}

    def vision(self):
        records = []
        messages = []
        font = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 42)
        for index, (code, amount) in enumerate((("K7M-482", "731.42"), ("V9P-615", "284.73"))):
            img = Image.new("RGB", (1000, 420), "white")
            draw = ImageDraw.Draw(img)
            draw.text((40, 35), "WAREHOUSE RECEIPT", font=font, fill="black")
            draw.text((40, 135), "ITEM: " + code, font=font, fill="black")
            draw.text((40, 235), "TOTAL: " + amount + " CZK", font=font, fill="black")
            path = self.cfg.root / f"receipt-{index}.png"
            img.save(path)
            messages.append({"role": "user", "content": [
                {"type": "text", "text": "Read the ITEM code and TOTAL amount in this new receipt. Answer briefly."},
                {"type": "image_url", "image_url": {"url": Session._data_url(path)}}]})
            r = self.call(messages)
            require(code in r.content and amount in r.content.replace(",", "."), repr(r.content))
            records.append(copy.deepcopy(self.last))
            messages.append({"role": "assistant", "content": r.content})
        return records

    def stop_stream(self):
        abort = threading.Event()
        stop_at = []

        def callback(text):
            if text and not abort.is_set():
                stop_at.append(time.monotonic())
                abort.set()

        started = time.monotonic()
        timer = threading.Timer(35, abort.set)
        timer.daemon = True
        timer.start()
        try:
            sampling = dict(self.cfg.sampling(True))
            sampling.update(max_tokens=2048, temperature=0)
            r = self.llm.stream([{"role": "user", "content": "Derive a detailed proof of the infinitude of primes, step by step."}],
                thinking=True, sampling=sampling, on_text=callback, on_reasoning=callback,
                should_stop=abort.is_set)
            latency = time.monotonic() - (stop_at[0] if stop_at else started)
            require(stop_at and r.stopped and latency < 3, f"STOP result={r.stopped}, latency={latency}")
        finally:
            timer.cancel()
        deadline = time.monotonic() + 15
        while servermgmt.slots_processing(self.cfg) and time.monotonic() < deadline:
            time.sleep(.2)
        follow = self.chat()
        return {"stop_seconds": round(latency, 3), "followup": follow}

    def long_context(self):
        # Explicit record IDs avoid measuring just attention over one repeated token.
        target = min(self.cfg.data.get("_audit_input_tokens", 122880), self.cfg.context_size() - 5000)
        sample = "\n".join(f"Record {i:06d}: routine inventory record, status unchanged, no special access phrase." for i in range(1000))
        tokenized = requests.post(self.cfg.base_url + "/tokenize", json={"content": sample}, timeout=30).json()
        per_line = len(tokenized["tokens"]) / 1000
        count = max(100, int((target - 500) / per_line))
        lines = [f"Record {i:06d}: routine inventory record, status unchanged, no special access phrase." for i in range(count)]
        for fraction, name, value in ((.1, "Cedar", "OPAL-6291"), (.5, "Birch", "MICA-8537"), (.9, "Maple", "JADE-4176")):
            lines[int(count * fraction)] = f"Special record: Project {name} has access phrase {value}."
        messages = [{"role": "system", "content": "Read the supplied records and answer only the requested question. Ignore routine records."},
                    {"role": "user", "content": "\n".join(lines) + "\nList the access phrases for Cedar, Birch and Maple. Give all three exactly."}]
        deadline = 1800 if self.cfg.model().get("adaptive_runtime") else 590
        r = self.call(messages, max_tokens=128, seconds=deadline)
        first = copy.deepcopy(self.last)
        require(all(x in r.content for x in ("OPAL-6291", "MICA-8537", "JADE-4176")), repr(r.content))
        messages.append({"role": "assistant", "content": r.content})
        messages.append({"role": "user", "content": "Now give only the phrase for Birch."})
        follow = self.call(messages, max_tokens=64, seconds=deadline)
        require("MICA-8537" in follow.content, repr(follow.content))
        return {"target_input_tokens": target, "first": first, "followup": self.last}

    def max_context(self):
        self.cfg.data["_audit_input_tokens"] = self.cfg.context_size() - 5000
        try:
            return self.long_context()
        finally:
            self.cfg.data.pop("_audit_input_tokens", None)

    def stop_prefill(self):
        abort = threading.Event()
        done = threading.Event()
        stop_at = []

        def interrupt_processing():
            deadline = time.monotonic() + 20
            while not done.wait(.05) and time.monotonic() < deadline:
                if servermgmt.slots_processing(self.cfg):
                    stop_at.append(time.monotonic())
                    abort.set()
                    return
            abort.set()

        thread = threading.Thread(target=interrupt_processing, daemon=True)
        thread.start()
        try:
            messages = [{"role": "user", "content":
                "Audit cancellation during prompt evaluation.\n" +
                "\n".join(f"Line {i}: industrial inventory record pending verification." for i in range(2400)) +
                "\nSummarize all records in detail."}]
            r = self.call(messages, max_tokens=256, seconds=45, stop=abort)
            require(stop_at and r.stopped, "Did not cancel an actively processing request")
            latency = time.monotonic() - stop_at[0]
            require(latency < 3, f"Prefill cancellation took {latency:.2f}s")
            deadline = time.monotonic() + 15
            while servermgmt.slots_processing(self.cfg) and time.monotonic() < deadline:
                time.sleep(.2)
            return {"stop_seconds": round(latency, 3), "followup": self.chat()}
        finally:
            done.set()
            thread.join(timeout=1)

    def saved_baseline_history(self):
        # cfg.root = .../cases/{runtime}/{model}/{profile}; read only synthetic audit data.
        sessions = self.cfg.root.parents[2] / "baseline" / self.cfg.model_key() / self.cfg.kv_cache_mode() / "sessions"
        candidates = sorted(sessions.glob("*/messages.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
        require(candidates, "No saved baseline history for this model/profile")
        data = copy.deepcopy(self.cfg.data)
        data["paths"]["sessions_dir"] = str(sessions)
        history = Session.load(Config(data, self.cfg.root), candidates[0].parent.name)
        messages = history.to_api_messages(include_pins=False)
        messages.append({"role": "user", "content": "From this conversation, what exact text was finally saved in proof.txt? Reply with that text only. Do not call tools."})
        r = self.call(messages, max_tokens=128)
        require("MARVIN_AUDIT_9264" in r.content, repr(r.content))
        return {"source": str(candidates[0]), "response": self.last}

    def application(self):
        service = ApplicationService(self.cfg, manage_model=False)
        service.preferences.update(model=self.cfg.model_key(), thinking="off", autonomy="auto")
        project = self.cfg.root / "project"
        project.mkdir(exist_ok=True)
        checks = []
        try:
            session = service.new_session(str(project), "discussion")
            for index, value in enumerate(("MARVIN_AUDIT_5837", "MARVIN_AUDIT_9264")):
                key = f"app-probe-{session.id}-{index}"
                started = time.monotonic()
                message_start = len(session.messages)
                service.submit(session.id, "Use write_file to write exactly " + value +
                    " into proof.txt in the current project. Then call read_file to check it and report the value. "
                    "Do only this small task. Do not ask questions.", request_id=key)
                deadline = started + (600 if self.cfg.model().get("adaptive_runtime") else 150)
                while time.monotonic() < deadline:
                    job = service.store.job(key)
                    if job["status"] in ("complete", "failed", "stopped"):
                        break
                    time.sleep(.2)
                else:
                    service.stop(session.id)
                    raise AssertionError("ApplicationService job timed out")
                target = project / "proof.txt"
                recent = [m for m in session.messages[message_start:] if m.get("role") == "tool"]
                names = [m.get("name") for m in recent]
                require(job["status"] == "complete" and target.exists() and target.read_text().strip() == value,
                        str({"job": job, "tool_names": names}))
                require("write_file" in names and "read_file" in names, repr(names))
                checks.append({"job": key, "seconds": round(time.monotonic() - started, 3),
                    "tool_names": names, "file_content": target.read_text(),
                    "usage": session.meta.get("last_usage")})
            return checks
        finally:
            service.close()

    def vision_application(self):
        """An actual agent reads an attachment, writes its unseen values, and checks the file."""
        service = ApplicationService(self.cfg, manage_model=False)
        service.preferences.update(model=self.cfg.model_key(), thinking="off", autonomy="auto")
        project = self.cfg.root / "vision-project"
        project.mkdir(exist_ok=True)
        started = time.monotonic()
        try:
            session = service.new_session(str(project), "discussion")
            picture = session.dir / "attachments" / "receipt.png"
            picture.parent.mkdir(parents=True, exist_ok=True)
            image = Image.new("RGB", (1000, 420), "white")
            draw = ImageDraw.Draw(image)
            font = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 48)
            draw.text((40, 40), "WAREHOUSE RECEIPT", font=font, fill="black")
            draw.text((40, 150), "ITEM: P9K-274", font=font, fill="black")
            draw.text((40, 260), "TOTAL: 831.62 CZK", font=font, fill="black")
            image.save(picture)
            attachment = service.store.register_file(picture, session.id, "attachment", picture.name)
            request_id = "vision-agent-" + session.id
            service.submit(session.id,
                "Read the ITEM and TOTAL from the attached receipt. Use write_file to save both exact "
                "values into image-proof.txt in the current project. Then use read_file to verify the file "
                "and report its contents. Do only this test; no questions.",
                attachments=[attachment["id"]], request_id=request_id)
            deadline = started + 600
            while time.monotonic() < deadline:
                job = service.store.job(request_id)
                if job["status"] in ("complete", "failed", "stopped"):
                    break
                time.sleep(.2)
            else:
                service.stop(session.id)
                raise AssertionError("Vision agent task timed out")
            path = project / "image-proof.txt"
            require(job["status"] == "complete" and path.is_file(), str(job))
            content = path.read_text(encoding="utf-8")
            require("P9K-274" in content and "831.62" in content.replace(",", "."), repr(content))
            names = [message.get("name") for message in session.messages if message.get("role") == "tool"]
            require("write_file" in names and "read_file" in names, repr(names))
            return {"seconds": round(time.monotonic()-started, 3), "session": session.id,
                    "file": str(path), "content": content, "tools": names,
                    "usage": session.meta.get("last_usage")}
        finally:
            service.close()


def make_config(original, root, runtime, key, profile, port):
    data = copy.deepcopy(original.data)
    data["default_model"] = key
    data["paths"].update(models_dir=str(original.path("paths.models_dir")),
        llama_dir=str(runtime), runtime_dir=str(root / "runtime"), sessions_dir=str(root / "sessions"))
    data["skills"]["directory"] = str(ROOT / "skills")
    data["server"].update(port=port)
    data["agent"].update(workspace=None, autonomy="auto", max_steps=10)
    data["thinking"] = False
    data["reasoning_effort"] = "low"
    data["work_mode"] = "discussion"
    for mode in ("thinking", "non_thinking"):
        data["sampling"][mode]["max_tokens"] = 1024
    root.mkdir(parents=True, exist_ok=True)
    cfg = Config(data, root)
    cfg.set_kv_cache_mode(key, profile)
    return cfg


def diagnose_completion_handoff(output: Path):
    """Reproduce the observed service race without any inference runtime involved."""
    from tests.test_workspace import Model
    completed = threading.Event()
    release = threading.Event()
    first_id = f"handoff-first-{time.time_ns()}"
    second_id = first_id.replace("first", "second")

    class HeldCompletion(ApplicationService):
        def _drive(self, job):
            super()._drive(job)
            if job["id"] == first_id:
                completed.set()
                release.wait(5)

    original = load_config()
    cfg = make_config(original, (output / "handoff-data").resolve(),
                      original.path("paths.llama_dir"), "q5", "q8_0", 8089)
    service = HeldCompletion(cfg, llm_factory=Model, manage_model=False)
    try:
        session = service.new_session(work_mode="discussion")
        service.submit(session.id, "Reply briefly.", request_id=first_id)
        require(completed.wait(5), "First deterministic service job did not complete")
        second = service.submit(session.id, "New independent question.", request_id=second_id)
        release.set()
        deadline = time.monotonic() + 2
        while service.active is not None and time.monotonic() < deadline:
            time.sleep(.01)
        result = {"no_llama_runtime_used": True,
                  "first_status": service.store.job(first_id)["status"],
                  "second_submission_status": second["status"],
                  "second_final_status": service.store.job(second_id)["status"],
                  "active": service.active}
        save(output / "completion-handoff.json", result)
        print(json.dumps(result), flush=True)
        return result
    finally:
        release.set()
        service.close()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--candidate", type=Path, required=True)
    ap.add_argument("--models", default="q5,q4,q3,ornith_q5,nemotron_q4,nemotron_q5")
    ap.add_argument("--runtimes", default="baseline,candidate")
    ap.add_argument("--profiles", choices=("primary", "all"), default="primary")
    ap.add_argument("--profile", help="Explicit profile for a single selected model")
    ap.add_argument("--long-context", action="store_true")
    ap.add_argument("--only", help="comma-separated probe names")
    ap.add_argument("--output", type=Path, default=ROOT / "runtime/validation/llama-b10935")
    ap.add_argument("--port", type=int, default=8087)
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--diagnose-handoff", action="store_true")
    ap.add_argument("--experimental-flash", action="store_true",
                    help="Validate the pinned optional Flash-Next before adding it to the product catalog")
    ap.add_argument("--trace-load", action="store_true", help="Include detailed upstream allocation diagnostics")
    ap.add_argument("--input-tokens", type=int, help="Smaller prefill sample for hardware calibration")
    ap.add_argument("--batch-pool", choices=("auto", "all", "performance"), default="auto")
    args = ap.parse_args()
    if args.diagnose_handoff:
        diagnose_completion_handoff(args.output)
        return 0
    original = load_config()
    if args.trace_load:
        original.data["server"].setdefault("extra_args", []).extend(["-lv", "4"])
    if args.input_tokens:
        original.data["_audit_input_tokens"] = args.input_tokens
    if args.batch_pool != "auto":
        from harness.hardware import detect_hardware, mask
        hw = detect_hardware()
        cpus = hw.performance_cpus if args.batch_pool == "performance" else hw.physical_cpus
        require(cpus, "No CPU pool could be detected")
        original.data["server"].setdefault("extra_args", []).extend([
            "-tb", str(len(cpus)), "--cpu-mask-batch", mask(cpus), "--cpu-strict-batch", "1"])
    if args.experimental_flash:
        from harness.model_catalog import FLASH_NEXT_Q3
        require(args.models == "flash_next_q3" and args.runtimes == "candidate",
                "Experimental Flash validation requires --models flash_next_q3 --runtimes candidate")
        original.data["models"]["flash_next_q3"] = copy.deepcopy(FLASH_NEXT_Q3)
        require(original.model_ready("flash_next_q3"), "The complete Flash-Next manifest is not verified yet")
    require(not servermgmt.health(original), "Stop the user's active model before starting an isolated GPU audit")
    try:
        occupied = requests.get(f"http://127.0.0.1:{args.port}/health", timeout=1)
    except requests.RequestException:
        occupied = None
    require(occupied is None, "Audit port is already occupied")
    runtimes = {"baseline": original.path("paths.llama_dir"), "candidate": args.candidate.resolve()}
    report_path = args.output / "results.json"
    report = json.loads(report_path.read_text(encoding="utf-8")) if args.resume and report_path.exists() else {"cases": {}}
    report["activation_status"] = "staged_only"
    report["scope"] = ("Isolated pinned Flash-Next validation; product catalog not activated" if args.experimental_flash
                       else "Existing model files on this host; no model download or production-runtime update")
    handoff = args.output / "completion-handoff.json"
    if handoff.exists():
        report["existing_application_handoff_finding"] = json.loads(handoff.read_text(encoding="utf-8"))
    report["requirements_lock_sha256"] = digest(ROOT / "requirements-windows-py312.lock")
    report["hardware"] = {"platform": platform.platform(), "python": sys.version,
        "physical_cores": psutil.cpu_count(logical=False), "logical_cpus": psutil.cpu_count(),
        "ram_total_bytes": psutil.virtual_memory().total}
    report["runtime_info"] = {}
    for label, directory in runtimes.items():
        exe = next(directory.rglob("llama-server.exe"))
        version = subprocess.run([str(exe), "--version"], capture_output=True, text=True,
                                 creationflags=servermgmt.NO_WINDOW, timeout=20)
        report["runtime_info"][label] = {"path": str(exe), "sha256": digest(exe),
            "version": version.stdout + version.stderr}
    names = args.only.split(",") if args.only else ["chat", "thinking", "tool_roundtrip", "vision", "stop_stream", "application"]
    if args.long_context and "long_context" not in names:
        names.append("long_context")
    for key in args.models.split(","):
        primary = original.kv_cache_mode(key)
        profiles = original.kv_cache_profiles(key) if args.profiles == "all" else {primary: original.kv_cache_profiles(key)[primary]}
        if args.profile:
            profiles = {args.profile: original.kv_cache_profiles(key)[args.profile]}
        for profile, spec in profiles.items():
            if spec["ctx_size"] > 524288:
                continue  # Explicit product non-goal: no million-token profiles.
            for label in args.runtimes.split(","):
                case_id = f"{label}/{key}/{profile}"
                previous = report["cases"].get(case_id, {})
                if args.resume and previous.get("finished") and all(name in previous.get("checks", {}) for name in names if name != "vision" or original.mmproj_file(key)):
                    continue
                root = args.output / "cases" / label / key / profile
                cfg = make_config(original, root.resolve(), runtimes[label], key, profile, args.port)
                case = {"model": key, "profile": profile, "context": cfg.context_size(),
                        "cache_args": cfg.kv_cache_server_args(), "checks": copy.deepcopy(previous.get("checks", {})),
                        "model_file": str(cfg.model_file()), "model_bytes": cfg.model_file().stat().st_size,
                        "model_server_args": cfg.model().get("server_args", []),
                        "runtime_server_args": cfg.data["server"].get("extra_args", []),
                        "profile_server_args": spec.get("server_args", [])}
                case["previous_attempts"] = copy.deepcopy(previous.get("previous_attempts", []))
                if previous:
                    case["previous_attempts"].append({k: v for k, v in previous.items() if k != "previous_attempts"})
                report["cases"][case_id] = case
                print(f"START {case_id} ctx={cfg.context_size()}", flush=True)
                started = time.monotonic()
                watch = ResourceWatch(cfg)
                watch.start()
                try:
                    require(servermgmt.start(cfg) == 0, "Runtime failed to load model/profile")
                    case["load_seconds"] = round(time.monotonic() - started, 3)
                    case["vram_loaded"] = servermgmt.vram_str()
                    props = requests.get(cfg.base_url + "/props", timeout=10).json()
                    case["server_context"] = props.get("default_generation_settings", {}).get("n_ctx")
                    case["server_model_path"] = props.get("model_path")
                    plan_path = cfg.path("paths.runtime_dir") / "execution-plans" / (key + ".json")
                    if plan_path.is_file():
                        case["execution_plan"] = json.loads(plan_path.read_text(encoding="utf-8"))
                    require(case["server_context"] == cfg.context_size(), "Server silently changed requested context")
                    probes = Probes(cfg)
                    try:
                        for name in names:
                            if name == "vision" and cfg.mmproj_file() is None:
                                continue
                            t0 = time.monotonic()
                            try:
                                evidence = getattr(probes, name)()
                                case["checks"][name] = {"ok": True, "evidence": evidence}
                                print(f"  PASS {name} {time.monotonic()-t0:.1f}s", flush=True)
                            except Exception as exc:
                                case["checks"][name] = {"ok": False, "error": f"{type(exc).__name__}: {exc}",
                                                        "last_response": probes.last}
                                print(f"  FAIL {name}: {type(exc).__name__}: {str(exc)[:250]}", flush=True)
                                if not servermgmt.health(cfg):
                                    break
                            save(report_path, report)
                    finally:
                        probes.llm.client.close()
                    case["ok"] = all(c["ok"] for c in case["checks"].values())
                except Exception as exc:
                    case.update(ok=False, load_error=f"{type(exc).__name__}: {exc}")
                    print(f"  LOAD FAIL {exc}", flush=True)
                finally:
                    stop_owned(cfg)
                    watch.close()
                    case["resources"] = watch.stats
                    case["finished"] = True
                    case["seconds"] = round(time.monotonic() - started, 3)
                    log = cfg.path("paths.runtime_dir") / "llama-server.log"
                    if log.exists():
                        case["server_log"] = str(log)
                    save(report_path, report)
                print(f"END {case_id} ok={case['ok']} {case['seconds']}s", flush=True)
    return 0 if all(c.get("ok") for c in report["cases"].values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
