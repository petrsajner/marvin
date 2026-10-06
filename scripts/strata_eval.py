"""Phase 0 evaluation of the Strata engine on this PC, outside Marvin's model management.

Installs a pinned Strata release in its own folder, starts its server with
derived configurations and drives it with Marvin's real client, prompts and
tools while sampling RAM and VRAM. Marvin's runtime, models and settings are
not changed. See docs/design/2026-10-05-strata-backend.md.

    python scripts/strata_eval.py install                    # IQ3_S, all experts in RAM
    python scripts/strata_eval.py install --low-ram resident # adds the resident variant
    python scripts/strata_eval.py run --context 262144
    python scripts/strata_eval.py run --context 131072
    python scripts/strata_eval.py report
    python scripts/strata_eval.py probe --url http://127.0.0.1:18080 --context 131072
"""
from __future__ import annotations

import argparse
import base64
import copy
import io
import json
import os
import platform
import random
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import psutil
import requests

STRATA_TAG = "v0.1.39"
STRATA_COMMIT = "6f32ec070f23ced9f50e704d854d775da52591ab"
STRATA_ARCHIVE = f"https://github.com/Niko1221/Strata/archive/refs/tags/{STRATA_TAG}.zip"
DEFAULT_PORT = 18080
WINDOWS = os.name == "nt"
NO_WINDOW = 0x08000000 if WINDOWS else 0
SCENARIOS = ("warmup", "chat", "image", "tool_calls", "agent", "long_context", "stop_prefill", "stop_decode")


def default_root() -> Path:
    base = os.environ.get("LOCALAPPDATA") if WINDOWS else None
    return Path(base or Path.home()) / "StrataEval"


def say(text: str) -> None:
    print(f"[strata-eval] {text}", flush=True)


# -- installation -------------------------------------------------------------------------------------------------

def strata_dir(root: Path) -> Path:
    return root / "Strata"


def strata_python(root: Path) -> Path:
    venv = strata_dir(root) / ".venv"
    return venv / ("Scripts/python.exe" if WINDOWS else "bin/python")


def fetch_strata(root: Path) -> dict:
    """Download the pinned release's source archive once; Strata's own setup fetches the engine and models."""
    target = strata_dir(root)
    marker = target / ".marvin-eval-source.json"
    if marker.exists():
        return json.loads(marker.read_text(encoding="utf-8"))
    root.mkdir(parents=True, exist_ok=True)
    say(f"downloading Strata {STRATA_TAG} source")
    response = requests.get(STRATA_ARCHIVE, timeout=120)
    response.raise_for_status()
    digest = __import__("hashlib").sha256(response.content).hexdigest()
    staging = Path(tempfile.mkdtemp(prefix="strata-src-", dir=root))
    try:
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            archive.extractall(staging)
        (top,) = [p for p in staging.iterdir() if p.is_dir()]
        if target.exists():
            raise RuntimeError(f"{target} exists without a source marker; move it away first")
        shutil.move(str(top), str(target))
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    record = {"tag": STRATA_TAG, "commit": STRATA_COMMIT, "archive": STRATA_ARCHIVE, "archive_sha256": digest}
    marker.write_text(json.dumps(record, indent=2), encoding="utf-8")
    return record


def ensure_venv(root: Path) -> Path:
    python = strata_python(root)
    if not python.exists():
        base = getattr(sys, "_base_executable", None) or sys.executable
        say(f"creating Strata's private environment with {base}")
        subprocess.run([base, "-m", "venv", str(strata_dir(root) / ".venv")], check=True)
    return python


def install(args) -> int:
    root = args.root.resolve()
    source = fetch_strata(root)
    python = ensure_venv(root)
    command = [str(python), "setup.py", "--family", "qwen", "--model", args.model, "--context", str(args.context),
               "--kv", "int8", "--vision", "gpu", "--low-ram", args.low_ram, "--experimental-speed-projection", "off",
               "--port", str(DEFAULT_PORT), "--data-dir", str(root / "Strata-data"),
               "--yes", "--no-start", "--no-browser"]
    if (strata_dir(root) / f"strata-{args.model.lower()}.json").exists():
        command.append("--setup")
    say("running Strata setup: " + " ".join(command[1:]))
    code = subprocess.call(command, cwd=strata_dir(root), stdin=subprocess.DEVNULL)
    if code:
        say(f"Strata setup failed with exit code {code}; rerun the same command to resume")
        return code
    produced = strata_dir(root) / f"strata-{args.model.lower()}.json"
    if not produced.exists():
        say(f"setup finished without {produced.name}")
        return 1
    base = "resident" if args.low_ram in ("on", "resident") else "normal"
    configs = root / "configs"
    configs.mkdir(parents=True, exist_ok=True)
    data = json.loads(produced.read_text(encoding="utf-8"))
    data["marvin_eval"] = {"source": source, "model": args.model, "low_ram": args.low_ram,
                           "installed": time.strftime("%Y-%m-%d %H:%M:%S")}
    (configs / f"base-{base}.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
    say(f"saved configs/base-{base}.json; engine args: {' '.join(data.get('args', []))}")
    return 0


# -- resource sampling --------------------------------------------------------------------------------------------

def gpu_snapshot() -> dict:
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=name,driver_version,memory.total,memory.used",
                              "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=5,
                             creationflags=NO_WINDOW).stdout.strip().splitlines()
        name, driver, total, used = [x.strip() for x in out[0].split(",")]
        return {"name": name, "driver": driver, "total_mib": int(total), "used_mib": int(used)}
    except Exception:
        return {}


def tree_rss(pid: int | None) -> int:
    if not pid:
        return 0
    try:
        proc = psutil.Process(pid)
        procs = [proc, *proc.children(recursive=True)]
    except psutil.Error:
        return 0
    total = 0
    for p in procs:
        try:
            total += p.memory_info().rss
        except psutil.Error:
            pass
    return total


class Sampler:
    """One sample per second: available RAM, the server tree's resident memory and GPU memory in use."""

    def __init__(self):
        self.pid: int | None = None
        self.phase = "idle"
        self.samples: list[dict] = []
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="strata-eval-sampler", daemon=True)

    def start(self):
        self._thread.start()
        return self

    def stop(self):
        self._stop.set()
        self._thread.join(timeout=10)

    def _run(self):
        tick = 0
        gpu: dict = {}
        while not self._stop.is_set():
            if tick % 2 == 0:
                gpu = gpu_snapshot() or gpu
            self.samples.append({"t": round(time.time(), 1), "phase": self.phase,
                                 "ram_available_mib": psutil.virtual_memory().available // 2**20,
                                 "server_rss_mib": tree_rss(self.pid) // 2**20,
                                 "vram_used_mib": gpu.get("used_mib")})
            tick += 1
            self._stop.wait(1.0)

    def summary(self) -> dict:
        phases: dict[str, dict] = {}
        for s in self.samples:
            p = phases.setdefault(s["phase"], {"samples": 0, "min_ram_available_mib": None,
                                               "max_server_rss_mib": 0, "max_vram_used_mib": None})
            p["samples"] += 1
            p["min_ram_available_mib"] = min(x for x in (p["min_ram_available_mib"], s["ram_available_mib"])
                                             if x is not None)
            p["max_server_rss_mib"] = max(p["max_server_rss_mib"], s["server_rss_mib"])
            if s["vram_used_mib"] is not None:
                p["max_vram_used_mib"] = max(p["max_vram_used_mib"] or 0, s["vram_used_mib"])
        return phases


# -- Marvin client against the Strata server ---------------------------------------------------------------------

def marvin_config(port: int, context: int, workdir: Path):
    from harness.config import Config, load_config
    from harness.model_catalog import FLASH_NEXT_Q3
    data = copy.deepcopy(load_config().data)
    data["server"].update(host="127.0.0.1", port=port)
    data["models"]["strata_eval"] = {
        "alias": "Qwen3.8-Flash-Next (Strata evaluation)", "family": "qwen4exp", "read_timeout": 1800,
        "ctx_size": context, "sampling": copy.deepcopy(FLASH_NEXT_Q3["sampling"]),
        "supports_reasoning_effort": True,
    }
    data["default_model"] = "strata_eval"
    data["thinking"] = True
    data["reasoning_effort"] = "high"
    data["paths"]["sessions_dir"] = str(workdir / "sessions")
    data["agent"]["workspace"] = str(workdir / "workspace")
    return Config(data, root=ROOT)


class Probe:
    def __init__(self, url: str, context: int, workdir: Path, sampler: Sampler | None = None):
        self.url = url.rstrip("/")
        self.port = int(self.url.rsplit(":", 1)[1])
        self.context = context
        self.workdir = workdir
        self.sampler = sampler
        self.cfg = marvin_config(self.port, context, workdir)
        self.results: dict[str, dict] = {}

    def client(self):
        from harness.llm import LLMClient
        return LLMClient(self.cfg)

    def call(self, messages, *, tools=None, thinking: bool | None = None, effort: str | None = None) -> dict:
        """One streamed request through Marvin's LLMClient; returns timings and the parsed result."""
        if effort:
            self.cfg.data["reasoning_effort"] = effort
        self.cfg.data["thinking"] = thinking is not False
        llm = self.client()
        first: dict = {}
        llm.on_generation_started = lambda: first.setdefault("t", time.perf_counter())
        started = time.perf_counter()
        error = None
        try:
            res = llm.stream(messages, tools=tools, thinking=thinking)
        except Exception as exc:
            res, error = None, f"{type(exc).__name__}: {exc}"
        wall = time.perf_counter() - started
        out = {"wall_s": round(wall, 3), "ttft_s": round(first["t"] - started, 3) if "t" in first else None,
               "error": error}
        if res is not None:
            timings = (res.usage or {}).get("timings") or {}
            out.update(content=res.content, reasoning_chars=len(res.reasoning), tool_calls=res.tool_calls,
                       prompt_tokens=(res.usage or {}).get("prompt_tokens"),
                       completion_tokens=(res.usage or {}).get("completion_tokens"),
                       cached_tokens=((res.usage or {}).get("prompt_tokens_details") or {}).get("cached_tokens"),
                       timings={k: timings.get(k) for k in ("cache_n", "prompt_n", "prompt_ms", "prompt_per_second",
                                                           "predicted_n", "predicted_ms", "predicted_per_second",
                                                           "draft_n", "draft_n_accepted")})
        return out

    def phase(self, name: str):
        if self.sampler:
            self.sampler.phase = name

    def count_tokens(self, text: str) -> int:
        r = requests.post(f"{self.url}/v1/messages/count_tokens", timeout=600,
                          json={"model": "qwen", "messages": [{"role": "user", "content": text}]})
        r.raise_for_status()
        return int(r.json()["input_tokens"])

    def busy(self) -> bool | None:
        try:
            return any(bool(s.get("is_processing")) for s in requests.get(f"{self.url}/slots", timeout=3).json())
        except Exception:
            return None

    def wait_idle(self, limit: float = 120.0) -> float | None:
        started = time.perf_counter()
        while time.perf_counter() - started < limit:
            if self.busy() is False:
                return round(time.perf_counter() - started, 3)
            time.sleep(0.1)
        return None

    # -- scenarios ----------------------------------------------------------------------------------------------

    def warmup(self) -> dict:
        r = self.call([{"role": "user", "content": "Reply with the single word OK."}], thinking=False)
        return {"ok": r["error"] is None and "ok" in (r.get("content") or "").lower(), **r}

    def chat(self) -> dict:
        question = [{"role": "user", "content": "What is 17 * 23? Answer with the number only."}]
        runs = {}
        for label, thinking, effort in (("off", False, None), ("low", True, "low"), ("high", True, "high")):
            r = self.call(question, thinking=thinking, effort=effort)
            r["ok"] = r["error"] is None and "391" in (r.get("content") or "")
            r["reasoning_separate"] = "<think>" not in (r.get("content") or "")
            runs[label] = r
        return {"ok": all(r["ok"] for r in runs.values()), "runs": runs}

    def image(self) -> dict:
        from PIL import Image, ImageDraw, ImageFont
        img = Image.new("RGB", (900, 360), "white")
        draw = ImageDraw.Draw(img)
        try:
            font = ImageFont.load_default(size=96)
        except TypeError:
            font = ImageFont.load_default()
        draw.text((40, 120), "STRATA 4271", fill="black", font=font)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        url = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
        messages = [{"role": "user", "content": [
            {"type": "text", "text": "What number is written in this image? Answer with the number only."},
            {"type": "image_url", "image_url": {"url": url}}]}]
        r = self.call(messages, thinking=False)
        return {"ok": r["error"] is None and "4271" in (r.get("content") or ""), **r}

    def tool_calls(self, repeats: int = 8) -> dict:
        from harness.agent import build_registry
        from harness.prompts import build_system_prompt
        workspace = self.workdir / "workspace"
        workspace.mkdir(parents=True, exist_ok=True)
        (workspace / "notes.txt").write_text("alpha\nbeta\n", encoding="utf-8")
        registry = build_registry("agent", "development", self.cfg)
        schemas = registry.schemas()
        names = {s["function"]["name"] for s in schemas}
        system = build_system_prompt("agent", self.cfg, str(workspace), "development")
        asks = [
            "Read notes.txt and tell me its second line.",
            "List the files in the project root.",
            "Run the shell command `python --version` and report the version.",
            "Create a file hello.txt containing exactly: strata ok",
            "Search the project for the word beta.",
            "Show the git status of the project.",
            "Read notes.txt.",
            "Write a file numbers.txt with the numbers 1 to 5, one per line.",
        ]
        runs = []
        for i in range(repeats):
            r = self.call([{"role": "system", "content": system}, {"role": "user", "content": asks[i % len(asks)]}],
                          tools=schemas, effort="low")
            calls = r.get("tool_calls") or []
            valid = []
            for call in calls:
                try:
                    json.loads(call["function"]["arguments"] or "{}")
                    valid.append(call["function"]["name"] in names)
                except ValueError:
                    valid.append(False)
            runs.append({"ask": asks[i % len(asks)], "error": r["error"], "calls": [c["function"]["name"] for c in calls],
                         "valid": all(valid) and bool(calls), "wall_s": r["wall_s"], "ttft_s": r["ttft_s"],
                         "prompt_tokens": r.get("prompt_tokens"), "timings": r.get("timings")})
        malformed = sum(1 for r in runs if r["error"] and "malformed tool call" in r["error"].lower())
        return {"ok": all(r["valid"] for r in runs), "valid_calls": sum(r["valid"] for r in runs),
                "requests": len(runs), "malformed_errors": malformed, "tool_count": len(schemas), "runs": runs}

    def agent(self) -> dict:
        """Marvin's GPU e2e coding workflow (tests/e2e_coding_workflow.py) against this server."""
        from harness.agent import Agent, Status, build_registry
        from harness.llm import LLMClient
        from harness.prompts import system_prompt
        from harness.safety import SafetyPolicy
        from harness.session import Session
        workspace = Path(tempfile.mkdtemp(prefix="strata-agent-", dir=self.workdir))
        (workspace / "target.py").write_text('VALUE = "before"\n', encoding="utf-8")
        (workspace / "tests").mkdir()
        (workspace / "tests" / "test_core.py").write_text(
            "from pathlib import Path\n"
            "text = Path('target.py').read_text(encoding='utf-8')\n"
            "assert 'VALUE = \"after\"' in text, text\n"
            "print('CODING-WORKFLOW-TEST-OK')\n", encoding="utf-8")
        self.cfg.data["agent"]["workspace"] = str(workspace)
        self.cfg.data["agent"]["max_steps"] = 20
        self.cfg.data["thinking"] = True
        self.cfg.data["reasoning_effort"] = "high"
        calls_made: list[dict] = []

        class Recording(LLMClient):
            def stream(inner, messages, **kwargs):
                started = time.perf_counter()
                try:
                    res = LLMClient.stream(inner, messages, **kwargs)
                except Exception as exc:
                    calls_made.append({"wall_s": round(time.perf_counter() - started, 3),
                                       "error": f"{type(exc).__name__}: {exc}"})
                    raise
                calls_made.append({"wall_s": round(time.perf_counter() - started, 3),
                                   "prompt_tokens": (res.usage or {}).get("prompt_tokens"),
                                   "timings": (res.usage or {}).get("timings"),
                                   "tools": [c["function"]["name"] for c in res.tool_calls]})
                return res

        session = Session(self.cfg, system_prompt=system_prompt("agent"), workspace=str(workspace))
        agent = Agent(self.cfg, Recording(self.cfg), session, build_registry("agent"),
                      SafetyPolicy("auto", max_steps=20), mode="agent")
        agent.new_task("In target.py, replace exactly VALUE = \"before\" with VALUE = \"after\". "
                       "Use apply_patch; do not use write_file or run_command. "
                       "Then call start_project_check and poll_command until the check finishes. "
                       "Finally, briefly confirm the result.")
        started = time.perf_counter()
        final = None
        for _ in range(30):
            result = agent.step()
            if result.status is Status.NEEDS_CONFIRMATION:
                result = agent.step(approve=True)
            if result.status is not Status.CONTINUE:
                final = result
                break
        calls = [c["function"]["name"] for m in session.messages for c in m.get("tool_calls", [])]
        tool_text = "\n".join(str(m.get("content", "")) for m in session.messages if m.get("role") == "tool")
        target = (workspace / "target.py").read_text(encoding="utf-8")
        ok = (final is not None and final.status is Status.FINAL
              and {"apply_patch", "start_project_check", "poll_command"}.issubset(calls)
              and 'VALUE = "after"' in target and "CODING-WORKFLOW-TEST-OK" in tool_text)
        return {"ok": ok, "status": getattr(getattr(final, "status", None), "name", None),
                "final_text": getattr(final, "text", None), "tools": calls, "wall_s": round(time.perf_counter() - started, 3),
                "requests": calls_made}

    def _filler(self, target_tokens: int, needles: dict[float, str], nonce: str) -> tuple[str, int]:
        rng = random.Random(nonce)
        nouns = ["valve", "ledger", "harbor", "orchard", "turbine", "archive", "lantern", "quarry", "canal", "relay"]
        verbs = ["measured", "recorded", "shipped", "inspected", "logged", "replaced", "sealed", "counted"]

        def line(i):
            return (f"Entry {i:06d}: the {rng.choice(nouns)} near sector {rng.randint(1, 999)} "
                    f"{rng.choice(verbs)} {rng.randint(10, 99999)} units on day {rng.randint(1, 365)}.\n")

        sample = "".join(line(i) for i in range(2000))
        per_line = max(1.0, self.count_tokens(sample) / 2000)
        total_lines = max(10, int(target_tokens / per_line))
        lines = [line(i) for i in range(total_lines)]
        for depth, fact in needles.items():
            lines.insert(int(total_lines * depth), fact + "\n")
        text = f"Session {nonce}.\n" + "".join(lines)
        return text, self.count_tokens(text)

    def long_context(self) -> dict:
        target = max(4096, self.context - 16384)
        nonce = f"{random.getrandbits(48):012x}"
        codes = {0.1: "ORCHID-7731", 0.5: "GRANITE-2468", 0.9: "COMET-9054"}
        needles = {depth: f"Important: secret code number {i + 1} is {code}."
                   for i, (depth, code) in enumerate(codes.items())}
        text, tokens = self._filler(target, needles, nonce)
        question = ("\n\nList secret code number 1, number 2 and number 3 from the text above, "
                    "one per line, nothing else.")
        messages = [{"role": "user", "content": text + question}]
        first = self.call(messages, thinking=False)
        found = [c for c in codes.values() if c in (first.get("content") or "")]
        messages += [{"role": "assistant", "content": first.get("content") or ""},
                     {"role": "user", "content": "Now write the same three codes in reverse order, one per line."}]
        follow = self.call(messages, thinking=False)
        follow_found = [c for c in codes.values() if c in (follow.get("content") or "")]
        for r in (first, follow):
            r["content"] = (r.get("content") or "")[:500]
        return {"ok": len(found) == 3 and len(follow_found) == 3, "input_tokens": tokens, "codes_found": found,
                "follow_up_codes_found": follow_found, "first": first, "follow_up": follow}

    def _raw_stream(self, body: dict, close_when) -> dict:
        """Stream without Marvin's client and drop the connection when close_when(elapsed, content) is true."""
        started = time.perf_counter()
        content = ""
        closed_at = None
        with requests.post(f"{self.url}/v1/chat/completions", json={**body, "stream": True}, stream=True,
                           timeout=(10, 1800)) as response:
            for raw in response.iter_lines(decode_unicode=True):
                if raw and raw.startswith("data: ") and raw != "data: [DONE]":
                    try:
                        delta = json.loads(raw[6:])["choices"][0]["delta"]
                        content += delta.get("content") or ""
                    except (ValueError, KeyError, IndexError):
                        pass
                if close_when(time.perf_counter() - started, content):
                    closed_at = time.perf_counter() - started
                    break
        return {"closed_after_s": round(closed_at, 3) if closed_at else None, "content_chars": len(content)}

    def stop_prefill(self) -> dict:
        target = min(65536, max(4096, self.context // 2))
        text, tokens = self._filler(target, {}, f"{random.getrandbits(48):012x}")
        state: dict = {}

        def run():
            state.update(self._raw_stream(
                {"messages": [{"role": "user", "content": text + "\n\nSummarize the entries."}],
                 "reasoning_effort": "none", "max_tokens": 64},
                lambda elapsed, content: elapsed >= 3.0))

        worker = threading.Thread(target=run, daemon=True)
        worker.start()
        worker.join(timeout=60)
        idle_after = self.wait_idle()
        short = self.call([{"role": "user", "content": "Reply with the single word OK."}], thinking=False)
        return {"ok": idle_after is not None and short["error"] is None, "prompt_tokens": tokens, **state,
                "idle_after_close_s": idle_after, "next_request_wall_s": short["wall_s"]}

    def stop_decode(self) -> dict:
        state = self._raw_stream(
            {"messages": [{"role": "user", "content": "Write a detailed 3000-word essay about the history of canals."}],
             "reasoning_effort": "none", "max_tokens": 6000},
            lambda elapsed, content: len(content) >= 400)
        idle_after = self.wait_idle()
        short = self.call([{"role": "user", "content": "Reply with the single word OK."}], thinking=False)
        return {"ok": idle_after is not None and short["error"] is None, **state,
                "idle_after_close_s": idle_after, "next_request_wall_s": short["wall_s"]}

    def run(self, names) -> dict:
        for name in names:
            self.phase(name)
            say(f"scenario {name}")
            started = time.perf_counter()
            try:
                result = getattr(self, name)()
            except Exception as exc:
                result = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
            result["scenario_wall_s"] = round(time.perf_counter() - started, 3)
            self.results[name] = result
            say(f"  {name}: {'ok' if result.get('ok') else 'FAILED'} in {result['scenario_wall_s']} s")
        self.phase("idle")
        return self.results


# -- running a configuration --------------------------------------------------------------------------------------

def set_arg(args: list[str], flag: str, value: str | None) -> None:
    if flag in args:
        i = args.index(flag)
        if value is None:
            del args[i:i + 2]
        else:
            args[i + 1] = value
    elif value is not None:
        args += [flag, value]


def derive_config(base: dict, context: int, port: int, run_dir: Path, effort_end: bool) -> dict:
    cfg = copy.deepcopy(base)
    cfg.pop("marvin_eval", None)
    args = cfg["args"]
    set_arg(args, "--max-context", str(context))
    if context < 65536:
        set_arg(args, "--kv-resident", None)
    cfg.update(port=port, log=str(run_dir / "engine.log"))
    if effort_end:
        cfg["effort_position"] = "end"
    return cfg


def environment() -> dict:
    vm = psutil.virtual_memory()
    return {"os": platform.platform(), "cpu": platform.processor(), "logical_cpus": psutil.cpu_count(),
            "physical_cpus": psutil.cpu_count(logical=False), "ram_total_mib": vm.total // 2**20,
            "ram_available_mib_at_start": vm.available // 2**20, "gpu": gpu_snapshot(),
            "python": sys.version.split()[0]}


def owned_servers_running() -> list[str]:
    names = []
    for p in psutil.process_iter(["name", "cmdline"]):
        name = (p.info.get("name") or "").lower()
        cmd = " ".join(p.info.get("cmdline") or [])
        if name == "llama-server.exe" and "--embeddings" not in cmd:
            names.append(f"llama-server pid {p.pid}")
        elif "serve" in cmd and "server.py" in cmd and "--engine" in cmd:
            names.append(f"Strata server pid {p.pid}")
    return names


def wait_ready(url: str, proc: subprocess.Popen, limit: float) -> float:
    started = time.perf_counter()
    while time.perf_counter() - started < limit:
        if proc.poll() is not None:
            raise RuntimeError(f"the Strata server exited with code {proc.returncode} before it was ready")
        try:
            health = requests.get(f"{url}/health", timeout=3).json()
            if health.get("service") == "strata" and health.get("loaded"):
                return round(time.perf_counter() - started, 1)
        except Exception:
            pass
        time.sleep(1.0)
    raise RuntimeError(f"the Strata server was not ready after {limit:.0f} s")


def stop_server(url: str, proc: subprocess.Popen) -> dict:
    started = time.perf_counter()
    try:
        unload = requests.post(f"{url}/unload", timeout=180).json()
    except Exception as exc:
        unload = {"error": f"{type(exc).__name__}: {exc}"}
    try:
        children = psutil.Process(proc.pid).children(recursive=True)
    except psutil.Error:
        children = []
    proc.terminate()
    try:
        proc.wait(timeout=30)
    except subprocess.TimeoutExpired:
        proc.kill()
    for child in children:
        try:
            child.kill()
        except psutil.Error:
            pass
    return {"unload": unload, "stop_s": round(time.perf_counter() - started, 1)}


def run(args) -> int:
    root = args.root.resolve()
    base_path = root / "configs" / f"base-{args.base}.json"
    if not base_path.exists():
        say(f"{base_path} is missing; run install first")
        return 1
    busy = owned_servers_running()
    if busy and not args.force:
        say("stop the running model servers first (Marvin: stop the model) or pass --force: " + ", ".join(busy))
        return 1
    label = args.label or f"{time.strftime('%Y%m%d-%H%M%S')}-{args.base}-{args.context // 1024}k"
    run_dir = root / "runs" / label
    run_dir.mkdir(parents=True, exist_ok=False)
    cfg = derive_config(json.loads(base_path.read_text(encoding="utf-8")), args.context, args.port, run_dir,
                        args.effort_end)
    config_path = run_dir / "strata.json"
    config_path.write_text(json.dumps(cfg, indent=1), encoding="utf-8")
    url = f"http://127.0.0.1:{args.port}"
    report = {"label": label, "base": args.base, "context": args.context, "effort_end": args.effort_end,
              "engine_args": cfg["args"], "environment": environment(),
              "source": json.loads(base_path.read_text(encoding="utf-8")).get("marvin_eval")}
    sampler = Sampler().start()
    sampler.phase = "load"
    command = [str(strata_python(root)), "serve/server.py", "--engine", "strata", "--config", str(config_path),
               "--host", "127.0.0.1", "--port", str(args.port)]
    say(f"starting Strata ({args.base}, context {args.context}); the PC may be slow for a few minutes")
    with open(run_dir / "server.log", "w", encoding="utf-8") as log:
        proc = subprocess.Popen(command, cwd=strata_dir(root), stdout=log, stderr=subprocess.STDOUT,
                                stdin=subprocess.DEVNULL, creationflags=NO_WINDOW)
    sampler.pid = proc.pid
    names = [s for s in (args.scenarios.split(",") if args.scenarios else SCENARIOS)]
    try:
        report["load_s"] = wait_ready(url, proc, args.load_timeout)
        say(f"ready after {report['load_s']} s")
        report["health"] = requests.get(f"{url}/health", timeout=5).json()
        report["status_after_load"] = requests.get(f"{url}/v1/status", timeout=5).json()
        report["scenarios"] = Probe(url, args.context, run_dir, sampler).run(names)
    except Exception as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
        say(report["error"])
    finally:
        sampler.phase = "stop"
        if proc.poll() is None:
            report["stop"] = stop_server(url, proc)
        sampler.stop()
        report["resources"] = sampler.summary()
        (run_dir / "samples.json").write_text(json.dumps(sampler.samples), encoding="utf-8")
        (run_dir / "results.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        (run_dir / "summary.md").write_text(summarize(report), encoding="utf-8")
    say(f"results in {run_dir}")
    print(summarize(report))
    return 0 if not report.get("error") and all(r.get("ok") for r in report.get("scenarios", {}).values()) else 2


def probe(args) -> int:
    workdir = Path(tempfile.mkdtemp(prefix="strata-probe-"))
    names = args.scenarios.split(",") if args.scenarios else SCENARIOS
    results = Probe(args.url, args.context, workdir).run(names)
    report = {"label": "probe", "url": args.url, "context": args.context, "scenarios": results}
    out = args.output or workdir / "results.json"
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(summarize(report))
    say(f"results in {out}")
    return 0 if all(r.get("ok") for r in results.values()) else 2


# -- reporting ----------------------------------------------------------------------------------------------------

def _rate(timings: dict | None, key: str) -> str:
    value = (timings or {}).get(key)
    return f"{value:.0f}" if isinstance(value, (int, float)) else "-"


def summarize(report: dict) -> str:
    lines = [f"# Strata evaluation {report.get('label')}", ""]
    env = report.get("environment") or {}
    if env:
        gpu = env.get("gpu") or {}
        lines += [f"- PC: {env.get('cpu')}, {env.get('ram_total_mib', 0) / 1024:.1f} GiB RAM, "
                  f"{gpu.get('name')} {gpu.get('total_mib')} MiB, driver {gpu.get('driver')}, {env.get('os')}"]
    lines += [f"- Base: {report.get('base', '-')}, context {report.get('context')}, "
              f"effort at end: {report.get('effort_end', False)}",
              f"- Load: {report.get('load_s', '-')} s" + (f"; error: {report['error']}" if report.get("error") else "")]
    scenarios = report.get("scenarios") or {}
    if scenarios:
        lines += ["", "| Scenario | Result | Details |", "|---|---|---|"]
    for name, r in scenarios.items():
        detail = r.get("error") or ""
        if set(r) <= {"ok", "error", "scenario_wall_s"}:
            pass
        elif name == "chat":
            detail = "; ".join(f"{k}: {v.get('wall_s')} s, decode {_rate(v.get('timings'), 'predicted_per_second')} "
                               f"tok/s, reasoning {v.get('reasoning_chars')} chars"
                               + (f", {v['error']}" if v.get("error") else "")
                               for k, v in (r.get("runs") or {}).items())
        elif name == "long_context":
            first, follow = r.get("first") or {}, r.get("follow_up") or {}
            detail = (f"{r.get('input_tokens')} tokens, first answer {first.get('wall_s')} s "
                      f"(prefill {_rate(first.get('timings'), 'prompt_per_second')} tok/s), codes "
                      f"{len(r.get('codes_found') or [])}/3; follow-up {follow.get('wall_s')} s, "
                      f"reused {(follow.get('timings') or {}).get('cache_n')} tokens")
        elif name == "tool_calls":
            detail = (f"{r.get('valid_calls')}/{r.get('requests')} valid calls, {r.get('malformed_errors')} "
                      f"malformed, {r.get('tool_count')} tools")
        elif name == "agent":
            detail = f"{r.get('status')}, {len(r.get('requests') or [])} requests, {r.get('wall_s')} s, tools {r.get('tools')}"
        elif name in ("stop_prefill", "stop_decode"):
            detail = (f"closed after {r.get('closed_after_s')} s, idle {r.get('idle_after_close_s')} s later, "
                      f"next request {r.get('next_request_wall_s')} s")
        elif "wall_s" in r:
            detail = (f"{r.get('wall_s')} s, decode {_rate(r.get('timings'), 'predicted_per_second')} tok/s"
                      + (f"; {r['error']}" if r.get("error") else ""))
        lines.append(f"| {name} | {'ok' if r.get('ok') else 'FAILED'} | {detail} |")
    resources = report.get("resources") or {}
    if resources:
        lines += ["", "| Phase | Min RAM available MiB | Max server RSS MiB | Max VRAM used MiB |", "|---|---:|---:|---:|"]
        for phase, p in resources.items():
            lines.append(f"| {phase} | {p.get('min_ram_available_mib')} | {p.get('max_server_rss_mib')} | "
                         f"{p.get('max_vram_used_mib')} |")
    return "\n".join(lines) + "\n"


def report_all(args) -> int:
    root = args.root.resolve()
    parts = []
    for path in sorted((root / "runs").glob("*/results.json")):
        parts.append(summarize(json.loads(path.read_text(encoding="utf-8"))))
    if not parts:
        say("no runs yet")
        return 1
    out = root / "summary.md"
    out.write_text("\n".join(parts), encoding="utf-8")
    print("\n".join(parts))
    say(f"written {out}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("install", help="install the pinned Strata release, IQ3_S weights and MTP via Strata's setup")
    p.add_argument("--root", type=Path, default=default_root())
    p.add_argument("--model", default="IQ3_S")
    p.add_argument("--context", type=int, default=262144)
    p.add_argument("--low-ram", choices=["off", "resident"], default="off")
    p.set_defaults(func=install)
    p = sub.add_parser("run", help="start one configuration, run the scenarios and stop it")
    p.add_argument("--root", type=Path, default=default_root())
    p.add_argument("--base", choices=["normal", "resident"], default="normal")
    p.add_argument("--context", type=int, default=262144)
    p.add_argument("--port", type=int, default=DEFAULT_PORT)
    p.add_argument("--scenarios", help="comma-separated subset of: " + ",".join(SCENARIOS))
    p.add_argument("--effort-end", action="store_true", help="put the reasoning-effort sentence at the prompt's end")
    p.add_argument("--label")
    p.add_argument("--load-timeout", type=float, default=1800)
    p.add_argument("--force", action="store_true", help="run even when another model server is running")
    p.set_defaults(func=run)
    p = sub.add_parser("probe", help="run the scenarios against an already running Strata server")
    p.add_argument("--url", default=f"http://127.0.0.1:{DEFAULT_PORT}")
    p.add_argument("--context", type=int, required=True)
    p.add_argument("--scenarios")
    p.add_argument("--output", type=Path)
    p.set_defaults(func=probe)
    p = sub.add_parser("report", help="collect every run's summary into one file")
    p.add_argument("--root", type=Path, default=default_root())
    p.set_defaults(func=report_all)
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
