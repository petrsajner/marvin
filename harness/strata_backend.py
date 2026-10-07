"""Run Qwen3.8-Flash-Next on the Strata engine: paths, config, launch, identity, readiness and stop.

servermgmt dispatches here for a model whose entry names `backend: strata`
(docs/design/2026-10-05-strata-backend.md, section 2.3). Strata is a Python
server (serve/server.py, in its own venv) that starts the C++/CUDA engine and the
image encoder as its children. Marvin writes the server's config itself for every
launch, so Strata's interactive setup, web page and shared chat settings never
decide what a launch does.

Layout, as Strata's own setup creates it, so a folder it prepared works as is:

    paths.strata_dir       serve/  tools/  data/expert-profile.bin  engine/  .venv/
    paths.strata_data_dir  models/IQ3_S/*.gguf  models/mmproj-*.gguf  packs/iq3_s/  mtp/rt/
"""
from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import re

import requests

from harness.config import Config

WINDOWS = os.name == "nt"
# Fatal memory failures in Strata's logs, in addition to the allocator markers
# servermgmt already looks for ("out of memory", "failed to allocate", ...).
MEMORY_MARKERS = ("does not fit", "cannot pin")
# "expert cache auto: 21.28 GiB free, 700 MiB reserved (...) -> 9856 slots": the budget the engine sized,
# in largest-expert units, which is what --expert-cache takes. The slot count it reports afterwards is
# higher (smaller experts share the budget), so it must not be fed back as a size.
EXPERT_CACHE_RE = re.compile(r"expert cache auto: [^\n]*?-> (\d+) slots")
UNLOAD_TIMEOUT = 120   # Seconds; the engine frees tens of gigabytes of pinned RAM.
LOG_TAIL_BYTES = 65536


def program_dir(cfg: Config) -> Path:
    return cfg.path("paths.strata_dir")


def data_dir(cfg: Config) -> Path:
    return cfg.path("paths.strata_data_dir")


def python_exe(cfg: Config) -> Path:
    venv = program_dir(cfg) / ".venv"
    return venv / ("Scripts/python.exe" if WINDOWS else "bin/python")


def server_script(cfg: Config) -> Path:
    return program_dir(cfg) / "serve" / "server.py"


def engine_exe(cfg: Config) -> Path:
    return program_dir(cfg) / "engine" / ("strata.exe" if WINDOWS else "strata")


def vision_exe(cfg: Config) -> Path:
    return program_dir(cfg) / "engine" / ("strata-vision.exe" if WINDOWS else "strata-vision")


def run_dir(cfg: Config) -> Path:
    """Marvin's generated configs and engine logs, outside Strata's program folder."""
    return cfg.path("paths.runtime_dir") / "strata-run"


def config_path(cfg: Config, key: str) -> Path:
    return run_dir(cfg) / f"strata-{key}.json"


def shared_settings_path(cfg: Config, key: str) -> Path:
    """Where Strata's web page keeps chat defaults it applies to every API request."""
    return config_path(cfg, key).with_suffix(".shared-settings.json")


def engine_log(cfg: Config, key: str) -> Path:
    return run_dir(cfg) / f"strata-{key}.log"


def server_log(cfg: Config) -> Path:
    return cfg.path("paths.runtime_dir") / "strata-server.log"


def settings(cfg: Config, key: str) -> dict:
    return cfg.model(key).get("strata") or {}


def lib_dirs(cfg: Config) -> list[str]:
    """Folders with the CUDA libraries the prebuilt engine loads: its BUILD.json's, else the venv's NVIDIA wheels."""
    engine = engine_exe(cfg).parent
    try:
        meta = json.loads((engine / "BUILD.json").read_text(encoding="utf-8"))
        listed = meta.get("lib_dirs") or meta.get("cuda_dirs") or []
        if listed:
            return [str(Path(d) if Path(d).is_absolute() else engine / d) for d in listed]
    except (OSError, ValueError, TypeError, AttributeError):
        pass
    venv = program_dir(cfg) / ".venv"
    pattern = "cublas64_13.dll" if WINDOWS else "libcublas.so.13*"
    dirs: list[str] = []
    for site in (venv / "Lib" / "site-packages", *sorted((venv / "lib").glob("python3*/site-packages"))):
        nvidia = site / "nvidia"
        if nvidia.is_dir():
            for hit in sorted(nvidia.rglob(pattern)):
                if str(hit.parent) not in dirs:
                    dirs.append(str(hit.parent))
    return dirs


def pool_workers(hardware) -> int | None:
    """Strata setup's CPU expert workers for a hybrid CPU with more efficiency than performance cores.

    The performance cores but the host loop's one, plus half of the efficiency
    cores; on other CPUs the engine's own count stays (Strata issue #642)."""
    if hardware is None:
        return None
    performance = len(hardware.performance_cpus)
    efficiency = len(hardware.physical_cpus) - performance
    if not performance or efficiency <= performance:
        return None
    return max(1, performance - 1 + efficiency // 2)


def uses_vision(cfg: Config, key: str) -> bool:
    mmproj = cfg.mmproj_file(key)
    return settings(cfg, key).get("vision", "gpu") in ("gpu", "cpu") and mmproj is not None and mmproj.exists()


def runtime_problems(cfg: Config, key: str) -> list[str]:
    """What the Strata program folder lacks for a launch; checked before any model download."""
    needed = [("the Python environment", python_exe(cfg)), ("the server", server_script(cfg)),
              ("the engine", engine_exe(cfg)),
              ("the expert profile", program_dir(cfg) / settings(cfg, key).get("expert_profile",
                                                                                "data/expert-profile.bin"))]
    return [f"{label}: {path}" for label, path in needed if not path.exists()]


def model_problems(cfg: Config, key: str) -> list[str]:
    """What the Strata data folder lacks for a launch, once the weights are verified."""
    s, data = settings(cfg, key), data_dir(cfg)
    needed = [("the model weights", cfg.model_file(key)), ("the n-gram table", data / s["ple_gguf"]),
              ("the prepared weights index", data / s["pack"] / "native_experts.txt"),
              ("the pack's tokenizer", data / s["pack"] / "tokenizer" / "vocab.json"),
              ("the MTP draft layer", data / s["mtp"] / "experts.bin")]
    return [f"{label}: {path}" for label, path in needed if not path.exists()]


def explain(cfg: Config, key: str, problems: list[str]) -> str:
    """What a launch lacks, worded like any other model's missing files; the paths say the rest."""
    name = cfg.model(key).get("status_label") or cfg.model(key).get("alias") or key
    return (f"{name} cannot start: some of its files are missing after preparation: " + "; ".join(problems)
            + ". Selecting the model again prepares what is missing.")


def placement(cfg: Config, key: str) -> dict:
    """The expert-cache size and VRAM reserve for this launch; a recovery keeps the failed run's.

    A profile for a smaller card names its cache size (`expert_cache`, the engine's
    budget in largest-expert units): Windows' display driver lets one process take
    memory from another, so "fill the free VRAM" is not a size a measurement can
    pin; a fixed cache is."""
    frozen = cfg.data.get("_recovery_placement", {})
    profile = cfg.kv_cache_profiles(key).get(cfg.kv_cache_mode(key), {})
    reserve = int(profile.get("vram_reserve_mib") or settings(cfg, key).get("vram_reserve_mib", 700))
    if frozen.get("model") == key:
        cache = frozen.get("expert_cache_slots") or frozen.get("expert_cache") or "auto"
        return {"model": key, "expert_cache": cache, "vram_reserve_mib": int(frozen.get("vram_reserve_mib", reserve))}
    return {"model": key, "expert_cache": profile.get("expert_cache") or "auto", "vram_reserve_mib": reserve}


def engine_args(cfg: Config, key: str, context: int, where: dict, hardware=None) -> list[str]:
    s, data = settings(cfg, key), data_dir(cfg)
    args = ["--pack", str(data / s["pack"]),
            "--native", str(cfg.model_file(key)),
            "--ple-gguf", str(data / s["ple_gguf"]),
            "--expert-profile", str(program_dir(cfg) / s.get("expert_profile", "data/expert-profile.bin")),
            "--expert-cache", str(where.get("expert_cache", "auto")),
            "--prefill", "auto",
            "--spec", str(s.get("spec", 4)),
            "--spec-min-p", str(s.get("spec_min_p", 0.5)),
            "--mtp", str(data / s["mtp"]),
            "--max-context", str(int(context)),
            "--kv", str(s.get("kv", "int8"))]
    if s.get("resident_experts"):
        args.append("--resident-experts")
    profile = cfg.kv_cache_profiles(key).get(cfg.kv_cache_mode(key), {})
    args += [str(a) for a in profile.get("engine_args", [])]
    if uses_vision(cfg, key):
        args.append("--vision")
    args += ["--vram-reserve-mib", str(where.get("vram_reserve_mib", s.get("vram_reserve_mib", 700)))]
    workers = pool_workers(hardware)
    if workers:
        args += ["--pool-workers", str(workers)]
    return args


def build_config(cfg: Config, key: str, context: int, where: dict, hardware=None) -> dict:
    """The server config, in the format of the strata-<model>.json Strata's setup writes."""
    s, data = settings(cfg, key), data_dir(cfg)
    config = {"exe": str(engine_exe(cfg)),
              "args": engine_args(cfg, key, context, where, hardware),
              "cwd": str(program_dir(cfg)),
              "tokenizer": str(data / s["pack"] / "tokenizer"),
              "model_name": s.get("model_name", key),
              "log": str(engine_log(cfg, key)),
              "lib_dirs": lib_dirs(cfg),
              "port": int(cfg.data["server"]["port"]),
              "open_browser": False}
    if s.get("effort_position"):
        config["effort_position"] = s["effort_position"]
    if uses_vision(cfg, key):
        config["vision"] = {"exe": str(vision_exe(cfg)), "mmproj": str(cfg.mmproj_file(key)),
                            "model": str(cfg.model_file(key)), "gpu": s.get("vision", "gpu") == "gpu",
                            "max_tokens": int(s.get("vision_max_tokens", 1024))}
        if s.get("vision") == "cpu":
            config["vision"]["threads"] = max(1, (os.cpu_count() or 8) // 2)
    return config


def server_argv(cfg: Config, key: str) -> list[str]:
    srv = cfg.data["server"]
    return [str(python_exe(cfg)), str(server_script(cfg)), "--engine", "strata",
            "--config", str(config_path(cfg, key)), "--host", str(srv["host"]), "--port", str(srv["port"])]


def server_env() -> dict:
    env = dict(os.environ)
    # The server's console output goes to a log file, which would otherwise use the
    # ANSI code page and fail on the first character outside it.
    env.update(PYTHONUTF8="1", PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1")
    # An inherited key would lock Marvin's own requests out; an empty one stops the server.
    env.pop("STRATA_API_KEY", None)
    return env


@dataclass
class Prepared:
    argv: list[str]
    cwd: Path
    env: dict
    config: dict
    placement: dict
    run: dict = field(default_factory=dict)


def prepare(cfg: Config, key: str, context: int, hardware=None) -> Prepared:
    """Write this launch's config and return how to start the server; RuntimeError says what is missing."""
    problems = runtime_problems(cfg, key) + model_problems(cfg, key)
    if problems:
        raise RuntimeError(explain(cfg, key, problems))
    where = placement(cfg, key)
    config = build_config(cfg, key, context, where, hardware)
    from harness.changes import atomic_write_text
    path = config_path(cfg, key)
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(path, json.dumps(config, indent=1))
    # Defaults saved from Strata's web page would fill in what Marvin's requests leave out.
    shared_settings_path(cfg, key).unlink(missing_ok=True)
    log = engine_log(cfg, key)
    return Prepared(server_argv(cfg, key), program_dir(cfg), server_env(), config, where,
                    run={"backend": "strata", "engine_log": str(log),
                         "engine_log_offset": log.stat().st_size if log.exists() else 0})


def _same_path(value, expected: Path) -> bool:
    if not value:
        return False
    try:
        return os.path.normcase(str(Path(value).resolve())) == os.path.normcase(str(expected.resolve()))
    except (OSError, ValueError):
        return False


def owns_process(cfg: Config, key: str, proc) -> bool:
    """A live process is Marvin's Strata server for `key`: its venv Python running serve/server.py with this config and port."""
    try:
        exe, argv = proc.exe(), list(proc.cmdline())
    except Exception:
        return False

    def value(flag):
        index = argv.index(flag) if flag in argv else -1
        return argv[index + 1] if 0 <= index < len(argv) - 1 else None

    return (_same_path(exe, python_exe(cfg))
            and any(_same_path(arg, server_script(cfg)) for arg in argv[1:])
            and _same_path(value("--config"), config_path(cfg, key))
            and value("--port") == str(cfg.data["server"]["port"]))


def ready(cfg: Config, timeout: float = 3.0) -> bool:
    """Strata opens its port only once the model is loaded; /health then also says whether it still is."""
    try:
        response = requests.get(f"{cfg.base_url}/health", timeout=timeout)
        body = response.json() if response.status_code == 200 else {}
        return isinstance(body, dict) and body.get("service") == "strata" and body.get("loaded") is True
    except (requests.RequestException, ValueError):
        return False


def prompt_progress(cfg: Config, timeout: float = 2.0) -> dict | None:
    """How far the prompt has been read, in the shape llama-server streams it; None outside a prompt read.

    Strata streams no progress, but its monitor data has the position reached
    (a reused prefix counts as read), the prompt length and the mean read rate.
    It does not say how much was reused, so `cache` is left out."""
    try:
        body = requests.get(f"{cfg.base_url}/metrics", timeout=timeout).json()
        live = body.get("live") or {}
        if live.get("state") != "reading" or not live.get("prompt_total"):
            return None
        progress = {"total": int(live["prompt_total"]), "processed": int(live.get("prompt_read") or 0),
                    "time_ms": int(float(live.get("elapsed_s") or 0) * 1000)}
        if live.get("prefill_tok_s_mean"):
            progress["rate"] = float(live["prefill_tok_s_mean"])
        return progress
    except (requests.RequestException, ValueError, TypeError, AttributeError):
        return None


def unload(cfg: Config, timeout: float = UNLOAD_TIMEOUT) -> str:
    """Ask the engine to quit and give back its GPU memory and pinned RAM; returns the outcome as text."""
    try:
        response = requests.post(f"{cfg.base_url}/unload", json={}, timeout=timeout)
        try:
            body = response.json()
        except ValueError:
            body = {}
        status = body.get("status") if isinstance(body, dict) else None
        return str(status or f"HTTP {response.status_code}")
    except requests.RequestException as exc:
        return f"{type(exc).__name__}: {exc}"


def _read_from(path: Path, offset: int) -> str:
    try:
        with path.open("rb") as stream:
            size = path.stat().st_size
            stream.seek(max(int(offset or 0), size - LOG_TAIL_BYTES))
            return stream.read().decode(errors="replace")
    except (OSError, ValueError):
        return ""


def log_offsets(cfg: Config, run: dict) -> dict:
    """Where each log ends now; recorded once the model is ready."""
    out = {}
    for name, path in (("ready_log_offset", server_log(cfg)), ("ready_engine_log_offset", Path(run["engine_log"]))):
        try:
            out[name] = path.stat().st_size
        except OSError:
            out[name] = 0
    return out


def recent_log_text(cfg: Config, run: dict) -> str:
    """The server and engine output since the model became ready, or since the launch when it never did."""
    server_from = run.get("ready_log_offset", run.get("log_offset", 0))
    engine_from = run.get("ready_engine_log_offset", run.get("engine_log_offset", 0))
    return (_read_from(server_log(cfg), server_from) + "\n"
            + _read_from(Path(run.get("engine_log", "")), engine_from))


def start_failure(cfg: Config, run: dict) -> str:
    """Why a launch ended before the model was ready: the server's last words, which name the cause."""
    lines = [line.strip() for line in _read_from(server_log(cfg), run.get("log_offset", 0)).splitlines()]
    reason = next((line for line in reversed(lines) if line and not line.startswith(("File ", "^", "=====",
                                                                                      "Traceback", "~"))), "")
    return ("The model stopped before it was ready"
            + (f": {reason}" if reason else "")
            + f". Logs: {server_log(cfg)}; {run.get('engine_log', '')}")


def observed_expert_cache(run: dict) -> int | None:
    """The expert-cache budget the engine sized in this launch; None when the size was given explicitly."""
    hits = EXPERT_CACHE_RE.findall(_read_from(Path(run.get("engine_log", "")), run.get("engine_log_offset", 0)))
    return int(hits[-1]) if hits else None
