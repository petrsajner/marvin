"""Phase 0 comparative evaluation of inference engines on this PC, outside Marvin.

Runs identical Marvin scenarios (chat, prose/code decode throughput, vision OCR,
full Development tool calls, multi-turn coding agent, near-ceiling long context
with cached follow-up, and STOP during prefill/decode) against:
  - llama-server (b10935 baseline or v1.0.0/b12359 candidate)
  - Strata (v0.1.39 baseline or v0.2.17/0.1.63 candidate)
  - Infernix (native Windows infernix-serve.exe)

Everything runs against Marvin's real LLMClient, prompts, tools and Agent while
sampling RAM, commit headroom, server RSS and GPU VRAM at 1 Hz. Marvin's own
runtime, models and settings are never modified.
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
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import psutil
import requests

DEFAULT_PORT = 18080
WINDOWS = os.name == "nt"
NO_WINDOW = 0x08000000 if WINDOWS else 0
SCENARIOS = (
    "warmup",
    "decode_bench",
    "chat",
    "image",
    "tool_calls",
    "agent",
    "long_context",
    "stop_prefill",
    "stop_decode",
)


def default_root() -> Path:
    base = os.environ.get("LOCALAPPDATA") if WINDOWS else None
    return Path(base or Path.home()) / "EngineEval"


def say(text: str) -> None:
    print(f"[engine-eval] {text}", flush=True)


# -- resource telemetry -------------------------------------------------------------------------------------------

def gpu_snapshot() -> dict:
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,driver_version,memory.total,memory.used",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5, creationflags=NO_WINDOW,
        ).stdout.strip().splitlines()
        name, driver, total, used = [x.strip() for x in out[0].split(",")]
        return {"name": name, "driver": driver, "total_mib": int(total), "used_mib": int(used)}
    except Exception:
        return {}


def commit_headroom_mib() -> int | None:
    try:
        from harness.hardware import commit_headroom
        val = commit_headroom()
        return int(val // 2**20) if val is not None else None
    except Exception:
        return None


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
    """1 Hz resource sampler: available RAM, commit headroom, server tree RSS and GPU VRAM."""

    def __init__(self):
        self.pid: int | None = None
        self.phase = "idle"
        self.samples: list[dict] = []
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="engine-eval-sampler", daemon=True)

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
            self.samples.append({
                "t": round(time.time(), 1),
                "phase": self.phase,
                "ram_available_mib": psutil.virtual_memory().available // 2**20,
                "commit_headroom_mib": commit_headroom_mib(),
                "server_rss_mib": tree_rss(self.pid) // 2**20,
                "vram_used_mib": gpu.get("used_mib"),
            })
            tick += 1
            self._stop.wait(1.0)

    def summary(self) -> dict:
        phases: dict[str, dict] = {}
        for s in self.samples:
            p = phases.setdefault(s["phase"], {
                "samples": 0,
                "min_ram_available_mib": None,
                "min_commit_headroom_mib": None,
                "max_server_rss_mib": 0,
                "max_vram_used_mib": None,
            })
            p["samples"] += 1
            p["min_ram_available_mib"] = min(
                x for x in (p["min_ram_available_mib"], s["ram_available_mib"]) if x is not None
            )
            if s["commit_headroom_mib"] is not None:
                p["min_commit_headroom_mib"] = min(
                    x for x in (p["min_commit_headroom_mib"], s["commit_headroom_mib"]) if x is not None
                )
            p["max_server_rss_mib"] = max(p["max_server_rss_mib"], s["server_rss_mib"])
            if s["vram_used_mib"] is not None:
                p["max_vram_used_mib"] = max(p["max_vram_used_mib"] or 0, s["vram_used_mib"])
        return phases


# -- Marvin client probe ------------------------------------------------------------------------------------------

def marvin_config(port: int, context: int, workdir: Path, engine_kind: str, model_family: str):
    from harness.config import Config, load_config
    from harness.model_catalog import FLASH_NEXT_STRATA
    data = copy.deepcopy(load_config().data)
    data["server"].update(host="127.0.0.1", port=port)
    # Use "llama" for llama/infernix (so LLMClient uses stream prompt_progress and omits Strata polling),
    # and "strata" for Strata servers.
    backend = "strata" if engine_kind == "strata" else "llama"
    sampling = (
        copy.deepcopy(FLASH_NEXT_STRATA["sampling"])
        if model_family == "qwen4exp"
        else copy.deepcopy(data["sampling"])
    )
    data["models"]["eval_model"] = {
        "backend": backend,
        "alias": f"Eval ({engine_kind} / {model_family})",
        "family": model_family,
        "read_timeout": 1800,
        "ctx_size": context,
        "sampling": sampling,
        "supports_reasoning_effort": True,
    }
    data["default_model"] = "eval_model"
    data["thinking"] = True
    data["reasoning_effort"] = "high"
    data["paths"]["sessions_dir"] = str(workdir / "sessions")
    data["agent"]["workspace"] = str(workdir / "workspace")
    return Config(data, root=ROOT)


class Probe:
    def __init__(
        self,
        url: str,
        context: int,
        workdir: Path,
        engine_kind: str,
        model_family: str,
        sampler: Sampler | None = None,
        long_tokens: int | None = None,
    ):
        self.url = url.rstrip("/")
        self.port = int(self.url.rsplit(":", 1)[1])
        self.context = context
        self.workdir = workdir
        self.engine_kind = engine_kind
        self.model_family = model_family
        self.sampler = sampler
        self.long_tokens = long_tokens
        self.cfg = marvin_config(self.port, context, workdir, engine_kind, model_family)
        self.results: dict[str, dict] = {}

    def client(self):
        from harness.llm import LLMClient
        return LLMClient(self.cfg)

    def call(
        self,
        messages,
        *,
        tools=None,
        thinking: bool | None = None,
        effort: str | None = None,
        track_progress: bool = False,
    ) -> dict:
        if effort:
            self.cfg.data["reasoning_effort"] = effort
        self.cfg.data["thinking"] = thinking is not False
        llm = self.client()
        first: dict = {}
        progress_events: list[dict] = []
        llm.on_generation_started = lambda: first.setdefault("t", time.perf_counter())
        if track_progress:
            llm.on_prompt_progress = lambda p: progress_events.append(p)
        started = time.perf_counter()
        error = None
        try:
            res = llm.stream(messages, tools=tools, thinking=thinking)
        except Exception as exc:
            res, error = None, f"{type(exc).__name__}: {exc}"
        wall = time.perf_counter() - started
        ttft = round(first["t"] - started, 3) if "t" in first else None
        out = {"wall_s": round(wall, 3), "ttft_s": ttft, "error": error}
        if track_progress:
            out["progress_events"] = len(progress_events)
        if res is not None:
            timings = (res.usage or {}).get("timings") or {}
            comp_toks = (res.usage or {}).get("completion_tokens")
            gen_s = (wall - ttft) if (ttft is not None and wall > ttft) else None
            client_tok_s = round(comp_toks / gen_s, 2) if (comp_toks and gen_s and gen_s > 0.05) else None
            out.update(
                content=res.content,
                reasoning_chars=len(res.reasoning),
                tool_calls=res.tool_calls,
                prompt_tokens=(res.usage or {}).get("prompt_tokens"),
                completion_tokens=comp_toks,
                cached_tokens=((res.usage or {}).get("prompt_tokens_details") or {}).get("cached_tokens"),
                client_decode_tok_s=client_tok_s,
                timings={
                    k: timings.get(k)
                    for k in (
                        "cache_n", "prompt_n", "prompt_ms", "prompt_per_second",
                        "predicted_n", "predicted_ms", "predicted_per_second",
                        "draft_n", "draft_n_accepted",
                    )
                },
            )
        return out

    def phase(self, name: str):
        if self.sampler:
            self.sampler.phase = name

    def count_tokens(self, text: str) -> int:
        # Try Anthropic count_tokens (Strata + Infernix), then llama.cpp /tokenize.
        try:
            r = requests.post(
                f"{self.url}/v1/messages/count_tokens",
                timeout=600,
                json={"model": "local-model", "messages": [{"role": "user", "content": text}]},
            )
            if r.status_code == 200 and "input_tokens" in r.json():
                return int(r.json()["input_tokens"])
        except Exception:
            pass
        r = requests.post(f"{self.url}/tokenize", timeout=600, json={"content": text})
        r.raise_for_status()
        body = r.json()
        if "tokens" in body:
            return len(body["tokens"])
        raise RuntimeError(f"Could not count tokens: {body}")

    def busy(self) -> bool | None:
        # llama.cpp & Strata expose /slots
        try:
            r = requests.get(f"{self.url}/slots", timeout=3)
            if r.status_code == 200:
                slots = r.json()
                if isinstance(slots, list):
                    return any(bool(s.get("is_processing")) for s in slots if isinstance(s, dict))
        except Exception:
            pass
        # Infernix exposes /monitor
        try:
            r = requests.get(f"{self.url}/monitor", timeout=3)
            if r.status_code == 200:
                body = r.json()
                active = sum(
                    len(body.get(k) or [])
                    for k in ("residents", "paused", "queued")
                )
                if body.get("binding"):
                    active += 1
                return active > 0
        except Exception:
            pass
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

    def decode_bench(self) -> dict:
        prompts = {
            "prose": (
                "Explain step by step how an HTTP/1.1 connection is established over TCP, "
                "how request headers and chunked transfer encoding work, and how persistent "
                "keep-alive connections differ from closing after each response. "
                "Write about 350 words of clear, continuous technical prose."
            ),
            "code": (
                "Write a self-contained Python 3.12 module implementing a thread-safe LRU cache "
                "with per-entry TTL expiration, using threading.RLock, cache statistics (hits, "
                "misses, evictions, expirations), a decorator helper, and a compact unittest suite. "
                "Output Python code only."
            ),
        }
        runs = {}
        for label, prompt in prompts.items():
            r = self.call([{"role": "user", "content": prompt}], thinking=False)
            toks = (r.get("timings") or {}).get("predicted_n") or r.get("completion_tokens") or 0
            r["ok"] = r["error"] is None and toks >= 100
            r["content"] = (r.get("content") or "")[:300]
            runs[label] = r
        return {"ok": all(r["ok"] for r in runs.values()), "runs": runs}

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
        messages = [{
            "role": "user",
            "content": [
                {"type": "text", "text": "What number is written in this image? Answer with the number only."},
                {"type": "image_url", "image_url": {"url": url}},
            ],
        }]
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
            r = self.call(
                [{"role": "system", "content": system}, {"role": "user", "content": asks[i % len(asks)]}],
                tools=schemas, effort="low",
            )
            calls = r.get("tool_calls") or []
            valid = []
            for call in calls:
                try:
                    json.loads(call["function"]["arguments"] or "{}")
                    valid.append(call["function"]["name"] in names)
                except ValueError:
                    valid.append(False)
            runs.append({
                "ask": asks[i % len(asks)],
                "error": r["error"],
                "calls": [c["function"]["name"] for c in calls],
                "valid": all(valid) and bool(calls),
                "wall_s": r["wall_s"],
                "ttft_s": r["ttft_s"],
                "prompt_tokens": r.get("prompt_tokens"),
                "cached_tokens": r.get("cached_tokens"),
                "timings": r.get("timings"),
            })
        malformed = sum(1 for r in runs if r["error"] and "malformed tool call" in r["error"].lower())
        return {
            "ok": all(r["valid"] for r in runs),
            "valid_calls": sum(r["valid"] for r in runs),
            "requests": len(runs),
            "malformed_errors": malformed,
            "tool_count": len(schemas),
            "runs": runs,
        }

    def agent(self) -> dict:
        from harness.agent import Agent, Status, build_registry
        from harness.llm import LLMClient
        from harness.prompts import system_prompt
        from harness.safety import SafetyPolicy
        from harness.session import Session
        workspace = Path(tempfile.mkdtemp(prefix="eval-agent-", dir=self.workdir))
        (workspace / "target.py").write_text('VALUE = "before"\n', encoding="utf-8")
        (workspace / "tests").mkdir()
        (workspace / "tests" / "test_core.py").write_text(
            "from pathlib import Path\n"
            "text = Path('target.py').read_text(encoding='utf-8')\n"
            "assert 'VALUE = \"after\"' in text, text\n"
            "print('CODING-WORKFLOW-TEST-OK')\n",
            encoding="utf-8",
        )
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
                calls_made.append({
                    "wall_s": round(time.perf_counter() - started, 3),
                    "prompt_tokens": (res.usage or {}).get("prompt_tokens"),
                    "cached_tokens": ((res.usage or {}).get("prompt_tokens_details") or {}).get("cached_tokens"),
                    "timings": (res.usage or {}).get("timings"),
                    "tools": [c["function"]["name"] for c in res.tool_calls],
                })
                return res

        session = Session(self.cfg, system_prompt=system_prompt("agent"), workspace=str(workspace))
        agent = Agent(
            self.cfg, Recording(self.cfg), session, build_registry("agent"),
            SafetyPolicy("auto", max_steps=20), mode="agent",
        )
        agent.new_task(
            'In target.py, replace exactly VALUE = "before" with VALUE = "after". '
            "Use apply_patch; do not use write_file or run_command. "
            "Then call start_project_check and poll_command until the check finishes. "
            "Finally, briefly confirm the result."
        )
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
        ok = (
            final is not None
            and final.status is Status.FINAL
            and {"apply_patch", "start_project_check", "poll_command"}.issubset(calls)
            and 'VALUE = "after"' in target
            and "CODING-WORKFLOW-TEST-OK" in tool_text
        )
        return {
            "ok": ok,
            "status": getattr(getattr(final, "status", None), "name", None),
            "final_text": (getattr(final, "text", None) or "")[:300],
            "tools": calls,
            "wall_s": round(time.perf_counter() - started, 3),
            "requests": calls_made,
        }

    def _filler(self, target_tokens: int, needles: dict[float, str], nonce: str) -> tuple[str, int]:
        rng = random.Random(nonce)
        nouns = ["valve", "ledger", "harbor", "orchard", "turbine", "archive", "lantern", "quarry", "canal", "relay"]
        verbs = ["measured", "recorded", "shipped", "inspected", "logged", "replaced", "sealed", "counted"]

        def line(i):
            return (
                f"Entry {i:06d}: the {rng.choice(nouns)} near sector {rng.randint(1, 999)} "
                f"{rng.choice(verbs)} {rng.randint(10, 99999)} units on day {rng.randint(1, 365)}.\n"
            )

        sample = "".join(line(i) for i in range(2000))
        per_line = max(1.0, self.count_tokens(sample) / 2000)
        total_lines = max(10, int(target_tokens / per_line))
        lines = [line(i) for i in range(total_lines)]
        for depth, fact in needles.items():
            lines.insert(int(total_lines * depth), fact + "\n")
        text = f"Session {nonce}.\n" + "".join(lines)
        return text, self.count_tokens(text)

    def long_context(self) -> dict:
        target = self.long_tokens or max(4096, self.context - 16384)
        nonce = f"{random.getrandbits(48):012x}"
        codes = {0.1: "ORCHID-7731", 0.5: "GRANITE-2468", 0.9: "COMET-9054"}
        needles = {
            depth: f"Important: secret code number {i + 1} is {code}."
            for i, (depth, code) in enumerate(codes.items())
        }
        text, tokens = self._filler(target, needles, nonce)
        question = (
            "\n\nList secret code number 1, number 2 and number 3 from the text above, "
            "one per line, nothing else."
        )
        messages = [{"role": "user", "content": text + question}]
        first = self.call(messages, thinking=False, track_progress=True)
        found = [c for c in codes.values() if c in (first.get("content") or "")]
        messages += [
            {"role": "assistant", "content": first.get("content") or ""},
            {"role": "user", "content": "Now write the same three codes in reverse order, one per line."},
        ]
        follow = self.call(messages, thinking=False)
        follow_found = [c for c in codes.values() if c in (follow.get("content") or "")]
        for r in (first, follow):
            r["content"] = (r.get("content") or "")[:500]
        return {
            "ok": len(found) == 3 and len(follow_found) == 3,
            "input_tokens": tokens,
            "codes_found": found,
            "follow_up_codes_found": follow_found,
            "first": first,
            "follow_up": follow,
        }

    def _raw_stream(self, body: dict, close_when) -> dict:
        started = time.perf_counter()
        content = ""
        closed_at = None
        payload = {"model": "local-model", **body, "stream": True}
        with requests.post(
            f"{self.url}/v1/chat/completions",
            json=payload,
            stream=True,
            timeout=(10, 1800),
        ) as response:
            response.raise_for_status()
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
        err: list[str] = []

        def run():
            try:
                state.update(self._raw_stream(
                    {
                        "messages": [{"role": "user", "content": text + "\n\nSummarize the entries."}],
                        "chat_template_kwargs": {"enable_thinking": False},
                        "max_tokens": 64,
                    },
                    lambda elapsed, content: elapsed >= 3.0,
                ))
            except Exception as exc:
                err.append(f"{type(exc).__name__}: {exc}")

        worker = threading.Thread(target=run, daemon=True)
        worker.start()
        worker.join(timeout=60)
        idle_after = self.wait_idle()
        short = self.call([{"role": "user", "content": "Reply with the single word OK."}], thinking=False)
        return {
            "ok": idle_after is not None and short["error"] is None and not err,
            "prompt_tokens": tokens,
            "stream_error": err[0] if err else None,
            **state,
            "idle_after_close_s": idle_after,
            "next_request_wall_s": short["wall_s"],
        }

    def stop_decode(self) -> dict:
        state = self._raw_stream(
            {
                "messages": [{"role": "user", "content": "Write a detailed 3000-word essay about the history of canals."}],
                "chat_template_kwargs": {"enable_thinking": False},
                "max_tokens": 6000,
            },
            lambda elapsed, content: len(content) >= 400,
        )
        idle_after = self.wait_idle()
        short = self.call([{"role": "user", "content": "Reply with the single word OK."}], thinking=False)
        return {
            "ok": idle_after is not None and short["error"] is None,
            **state,
            "idle_after_close_s": idle_after,
            "next_request_wall_s": short["wall_s"],
        }

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


# -- server lifecycle ---------------------------------------------------------------------------------------------

def environment() -> dict:
    vm = psutil.virtual_memory()
    return {
        "os": platform.platform(),
        "cpu": platform.processor(),
        "logical_cpus": psutil.cpu_count(),
        "physical_cpus": psutil.cpu_count(logical=False),
        "ram_total_mib": vm.total // 2**20,
        "ram_available_mib_at_start": vm.available // 2**20,
        "commit_headroom_mib_at_start": commit_headroom_mib(),
        "gpu": gpu_snapshot(),
        "python": sys.version.split()[0],
    }


def wait_ready(url: str, engine_kind: str, proc: subprocess.Popen, limit: float) -> float:
    started = time.perf_counter()
    while time.perf_counter() - started < limit:
        if proc.poll() is not None:
            raise RuntimeError(f"server exited with code {proc.returncode} before ready")
        try:
            r = requests.get(f"{url}/health", timeout=3)
            if r.status_code == 200:
                if engine_kind == "strata":
                    body = r.json()
                    if body.get("service") == "strata" and body.get("loaded") is True:
                        return round(time.perf_counter() - started, 1)
                elif engine_kind == "infernix":
                    body = r.json()
                    if body.get("status") == "ok":
                        return round(time.perf_counter() - started, 1)
                else:
                    return round(time.perf_counter() - started, 1)
        except Exception:
            pass
        time.sleep(1.0)
    raise RuntimeError(f"server not ready after {limit:.0f} s")


def stop_server(url: str, engine_kind: str, proc: subprocess.Popen) -> dict:
    started = time.perf_counter()
    unload = None
    if engine_kind == "strata":
        try:
            unload = requests.post(f"{url}/unload", json={}, timeout=180).json()
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
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            pass
    for child in children:
        try:
            child.kill()
        except psutil.Error:
            pass
    # Wait briefly for GPU memory to settle
    for _ in range(15):
        g = gpu_snapshot()
        if g and g.get("used_mib", 0) < 5000:
            break
        time.sleep(1.0)
    return {"unload": unload, "stop_s": round(time.perf_counter() - started, 1)}


def _rate(timings: dict | None, key: str, fallback=None) -> str:
    value = (timings or {}).get(key)
    if isinstance(value, (int, float)):
        return f"{value:.1f}"
    if isinstance(fallback, (int, float)):
        return f"{fallback:.1f}*"
    return "-"


def summarize(report: dict) -> str:
    lines = [f"# Engine evaluation: {report.get('label')}", ""]
    env = report.get("environment") or {}
    if env:
        gpu = env.get("gpu") or {}
        lines += [
            f"- PC: {env.get('cpu')}, {env.get('ram_total_mib', 0) / 1024:.1f} GiB RAM "
            f"(avail {env.get('ram_available_mib_at_start', 0) / 1024:.1f} GiB at start), "
            f"{gpu.get('name')} {gpu.get('total_mib')} MiB, driver {gpu.get('driver')}, {env.get('os')}",
        ]
    lines += [
        f"- Engine: `{report.get('engine')}` | Model: `{report.get('model_family')}` | Context: {report.get('context')}",
        f"- Load: {report.get('load_s', '-')} s" + (f"; error: {report['error']}" if report.get("error") else ""),
    ]
    scenarios = report.get("scenarios") or {}
    if scenarios:
        lines += ["", "| Scenario | Result | Details |", "|---|---|---|"]
    for name, r in scenarios.items():
        detail = r.get("error") or ""
        if set(r) <= {"ok", "error", "scenario_wall_s"}:
            pass
        elif name == "decode_bench":
            parts = []
            for k, v in (r.get("runs") or {}).items():
                t = v.get("timings") or {}
                draft_str = ""
                if t.get("draft_n"):
                    acc = 100.0 * (t.get("draft_n_accepted") or 0) / t["draft_n"]
                    draft_str = f", draft {acc:.0f}%"
                parts.append(
                    f"{k}: {_rate(t, 'predicted_per_second', v.get('client_decode_tok_s'))} tok/s "
                    f"({t.get('predicted_n') or v.get('completion_tokens')} tok, ttft {v.get('ttft_s')} s{draft_str})"
                )
            detail = "; ".join(parts)
        elif name == "chat":
            detail = "; ".join(
                f"{k}: {v.get('wall_s')} s, reasoning {v.get('reasoning_chars')} ch"
                + ("" if v.get("reasoning_separate") else " [LEAK]")
                + (f", {v['error']}" if v.get("error") else "")
                for k, v in (r.get("runs") or {}).items()
            )
        elif name == "long_context":
            first, follow = r.get("first") or {}, r.get("follow_up") or {}
            ft, lt = first.get("timings") or {}, follow.get("timings") or {}
            reused = lt.get("cache_n") if lt.get("cache_n") is not None else follow.get("cached_tokens")
            detail = (
                f"{r.get('input_tokens')} tok, first {first.get('wall_s')} s (ttft {first.get('ttft_s')} s, "
                f"prefill {_rate(ft, 'prompt_per_second')} tok/s, progress {first.get('progress_events')} ev), "
                f"codes {len(r.get('codes_found') or [])}/3; follow-up {follow.get('wall_s')} s "
                f"(ttft {follow.get('ttft_s')} s, cached {reused})"
            )
        elif name == "tool_calls":
            cached_list = [
                (x.get("timings") or {}).get("cache_n") or x.get("cached_tokens") or 0
                for x in (r.get("runs") or [])[1:]
            ]
            avg_ttft = sum((x.get("ttft_s") or 0) for x in (r.get("runs") or [])) / max(1, len(r.get("runs") or []))
            detail = (
                f"{r.get('valid_calls')}/{r.get('requests')} valid, {r.get('malformed_errors')} malformed, "
                f"{r.get('tool_count')} tools, avg ttft {avg_ttft:.2f} s, follow cached {cached_list}"
            )
        elif name == "agent":
            detail = f"{r.get('status')}, {len(r.get('requests') or [])} reqs, {r.get('wall_s')} s, tools {r.get('tools')}"
        elif name in ("stop_prefill", "stop_decode"):
            detail = (
                f"closed {r.get('closed_after_s')} s, idle +{r.get('idle_after_close_s')} s, "
                f"next {r.get('next_request_wall_s')} s"
            )
        elif "wall_s" in r:
            detail = (
                f"{r.get('wall_s')} s, ttft {r.get('ttft_s')} s, "
                f"decode {_rate(r.get('timings'), 'predicted_per_second', r.get('client_decode_tok_s'))} tok/s"
                + (f"; {r['error']}" if r.get("error") else "")
            )
        lines.append(f"| {name} | {'ok' if r.get('ok') else 'FAILED'} | {detail} |")
    resources = report.get("resources") or {}
    if resources:
        lines += [
            "",
            "| Phase | Min RAM avail MiB | Min Commit headroom MiB | Max Server RSS MiB | Max VRAM used MiB |",
            "|---|---:|---:|---:|---:|",
        ]
        for phase, p in resources.items():
            lines.append(
                f"| {phase} | {p.get('min_ram_available_mib')} | {p.get('min_commit_headroom_mib')} | "
                f"{p.get('max_server_rss_mib')} | {p.get('max_vram_used_mib')} |"
            )
    return "\n".join(lines) + "\n"


def run_command_spec(args) -> int:
    root = args.root.resolve()
    spec = json.loads(Path(args.spec_file).read_text(encoding="utf-8-sig")) if args.spec_file else {}
    label = args.label or spec["label"]
    engine = args.engine or spec["engine"]
    family = args.family or spec.get("family", "qwen4exp")
    context = args.context or int(spec["context"])
    long_tokens = args.long_tokens if args.long_tokens is not None else spec.get("long_tokens")
    port = args.port or int(spec.get("port", DEFAULT_PORT))
    argv = json.loads(args.argv_json) if args.argv_json else list(spec["argv"])
    cwd_val = args.cwd or spec.get("cwd")
    extra_env = json.loads(args.env_json) if args.env_json else (spec.get("env") or {})
    scenarios = args.scenarios or spec.get("scenarios")
    load_timeout = args.load_timeout if args.load_timeout is not None else float(spec.get("load_timeout", 900))

    run_dir = root / "runs" / label
    if run_dir.exists():
        shutil.rmtree(run_dir)
    run_dir.mkdir(parents=True)

    cwd = Path(cwd_val) if cwd_val else run_dir
    env = dict(os.environ)
    env.update(PYTHONUTF8="1", PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1")
    env.pop("STRATA_API_KEY", None)
    env.update({str(k): str(v) for k, v in extra_env.items()})

    url = f"http://127.0.0.1:{port}"
    report = {
        "label": label,
        "engine": engine,
        "model_family": family,
        "context": context,
        "argv": argv,
        "cwd": str(cwd),
        "environment": environment(),
    }
    sampler = Sampler().start()
    sampler.phase = "load"
    say(f"starting {label} ({engine}, ctx={context})")
    with open(run_dir / "server.log", "w", encoding="utf-8") as log:
        proc = subprocess.Popen(
            argv,
            cwd=str(cwd),
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            creationflags=NO_WINDOW,
        )
    sampler.pid = proc.pid
    names = [s for s in (scenarios.split(",") if isinstance(scenarios, str) else (scenarios or SCENARIOS))]
    try:
        report["load_s"] = wait_ready(url, engine, proc, load_timeout)
        say(f"ready after {report['load_s']} s")
        try:
            report["health"] = requests.get(f"{url}/health", timeout=5).json()
        except Exception:
            pass
        try:
            report["models"] = requests.get(f"{url}/v1/models", timeout=5).json()
        except Exception:
            pass
        probe = Probe(
            url, context, run_dir, engine, family,
            sampler=sampler, long_tokens=long_tokens,
        )
        report["scenarios"] = probe.run(names)
    except Exception as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
        say(report["error"])
    finally:
        sampler.phase = "stop"
        if proc.poll() is None:
            report["stop"] = stop_server(url, engine, proc)
        sampler.stop()
        report["resources"] = sampler.summary()
        (run_dir / "samples.json").write_text(json.dumps(sampler.samples), encoding="utf-8")
        (run_dir / "results.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        (run_dir / "summary.md").write_text(summarize(report), encoding="utf-8")
    say(f"results saved in {run_dir}")
    print(summarize(report))
    return 0 if not report.get("error") and all(r.get("ok") for r in report.get("scenarios", {}).values()) else 2


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("run", help="launch a server spec, run all Marvin scenarios, stop and summarize")
    p.add_argument("--root", type=Path, default=default_root())
    p.add_argument("--spec-file", default=None)
    p.add_argument("--label", default=None)
    p.add_argument("--engine", choices=("llama", "strata", "infernix"), default=None)
    p.add_argument("--family", default=None)
    p.add_argument("--context", type=int, default=None)
    p.add_argument("--long-tokens", type=int, default=None)
    p.add_argument("--port", type=int, default=None)
    p.add_argument("--argv-json", default=None)
    p.add_argument("--cwd", default=None)
    p.add_argument("--env-json", default=None)
    p.add_argument("--scenarios", default=None)
    p.add_argument("--load-timeout", type=float, default=None)
    p.set_defaults(func=run_command_spec)
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
