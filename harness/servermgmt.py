"""Manage the inference server: start, stop, switch and status.

llama-server runs every model except those whose entry names `backend: strata`;
those run on the Strata engine (harness/strata_backend.py). Each function that
touches the server process branches once on the backend.

Shared by the CLI, TUI and web application."""
from __future__ import annotations

import subprocess
import json
import threading
import time
from pathlib import Path

import requests

from harness.config import Config

HEALTH_TIMEOUT = 900  # Seconds; the initial load of a large model can take time.
_start_lock = threading.Lock()
# A Strata server pins tens of gigabytes of RAM, so it ends with this process
# however it ends (harness/winjob.py). The CLI, which starts a server and exits,
# turns this off.
BIND_SERVER_TO_PROCESS = True
MEMORY_MARKERS = ("out of memory", "cudaerrormemoryallocation", "failed to allocate",
                  "cannot allocate memory", "std::bad_alloc")
# The emergency guard ends a server after ten seconds below this much available RAM.
GUARD_RAM_BYTES = 512 * 1024**2
GUARD_SECONDS = 10
# A Strata server keeps most experts in pageable RAM: when RAM runs short, Windows
# pages cold ones out, which took about eight seconds on the owner's desktop at
# 256k (2026-10-08). While commit room remains for that, the guard waits a minute.
GUARD_PAGING_SECONDS = 60
GUARD_COMMIT_BYTES = 2 * 1024**3


def pid_file(cfg: Config) -> Path:
    return cfg.path("paths.runtime_dir") / "llama-server.pid"


def _backend_of(cfg: Config, model: str) -> str:
    """The backend of a recorded model, from its entry or, once the entry is gone, from its launch record."""
    entry = cfg.data.get("models", {}).get(model)
    if isinstance(entry, dict):
        return entry.get("backend", "llama")
    try:
        run = json.loads((cfg.path("paths.runtime_dir") / "model-run.json").read_text(encoding="utf-8"))
        return run.get("backend", "llama") if run.get("model") == model else "llama"
    except (OSError, ValueError, AttributeError):
        return "llama"


def last_failure(cfg: Config) -> dict:
    try:
        value = json.loads((cfg.path("paths.runtime_dir") / "model-failure.json").read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def record_allocation_failure(cfg, error=""):
    """Recognize actual allocator failures, including request-time CUDA errors."""
    try:
        record = json.loads((cfg.path("paths.runtime_dir") / "model-run.json").read_text(encoding="utf-8"))
        if record.get("model") != cfg.model_key():
            return
        markers = MEMORY_MARKERS
        if record.get("backend") == "strata":
            from harness import strata_backend
            tail = strata_backend.recent_log_text(cfg, record)
            markers += strata_backend.MEMORY_MARKERS
        else:
            path = cfg.path("paths.runtime_dir") / "llama-server.log"
            with path.open("rb") as stream:
                stream.seek(max(record.get("log_offset", 0), path.stat().st_size - 65536))
                tail = stream.read().decode(errors="replace")
        message = (str(error) + "\n" + tail).lower()
        if not any(marker in message for marker in markers):
            return
        from harness.changes import atomic_write_text
        atomic_write_text(cfg.path("paths.runtime_dir") / "model-failure.json", json.dumps({
            "model": record["model"], "context": record["context"], "time": time.time(),
            "code": "vram_pressure" if "cuda" in message else "ram_pressure",
            "error": "The model could not allocate memory for this context."}))
    except (OSError, ValueError):
        return


def health(cfg: Config, timeout: float = 3.0) -> bool:
    try:
        r = requests.get(f"{cfg.base_url}/health", timeout=timeout)
        return r.status_code == 200
    except requests.RequestException:
        return False


def wait_health(cfg: Config, timeout: float = HEALTH_TIMEOUT,
                proc: subprocess.Popen | None = None, cancelled=None, probe=None) -> bool:
    """Wait until the server answers `probe` (default: /health with status 200)."""
    t0 = time.time()
    while time.time() - t0 < timeout:
        if cancelled and cancelled():
            return False
        if (probe or health)(cfg):
            return True
        if proc is not None and proc.poll() is not None:
            return False
        time.sleep(2)
    return False


NO_WINDOW = 0x08000000  # CREATE_NO_WINDOW prevents console flashes.

_vram_cache: dict = {"ts": 0.0, "value": ""}


def vram_str() -> str:
    """Format GPU memory usage with a 10-second cache for the nvidia-smi subprocess."""
    import time as _t
    now = _t.time()
    if now - _vram_cache["ts"] < 10 and _vram_cache["value"]:
        return _vram_cache["value"]
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used,memory.total", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5,
            creationflags=NO_WINDOW,
        ).stdout.strip().splitlines()[0]
        used, total = [x.strip() for x in out.split(",")]
        val = f"GPU VRAM: {int(used) / 1024:.1f} / {int(total) / 1024:.1f} GB"
    except Exception:
        val = "GPU VRAM: (nvidia-smi unavailable)"
    _vram_cache.update(ts=now, value=val)
    return val


def vram_value() -> str:
    """Return GPU memory usage without the label, for composite UI rows."""
    return vram_str().removeprefix("GPU VRAM: ")


def server_state(cfg: Config) -> str:
    """Return down, starting or running.

    Starting means the managed process exists but its health endpoint is not yet ready, typically while model weights are loading."""
    if health(cfg):
        return "running"
    if _managed_process(cfg) is not None:
        return "starting"
    return "down"


def running_model(cfg: Config) -> str | None:
    record = _pid_record(cfg)
    return record[0] if record and _managed_process(cfg) is not None else None


def _pid_record(cfg: Config) -> tuple[str, int] | None:
    try:
        model, raw_pid = pid_file(cfg).read_text(encoding="utf-8").strip().split(":", 1)
        return model, int(raw_pid)
    except (OSError, ValueError, IndexError):
        return None


def _managed_process(cfg: Config):
    """Resolve a live owned server from its PID file, removing stale records."""
    record = _pid_record(cfg)
    if record is None:
        pid_file(cfg).unlink(missing_ok=True)
        return None
    model, pid = record
    try:
        import psutil
        proc = psutil.Process(pid)
        if not proc.is_running() or proc.status() == psutil.STATUS_ZOMBIE:
            raise psutil.NoSuchProcess(pid)
        if _backend_of(cfg, model) == "strata":
            from harness import strata_backend
            if not strata_backend.owns_process(cfg, model, proc):
                pid_file(cfg).unlink(missing_ok=True)
                return None
            return proc
        if (proc.name() or "").lower() != "llama-server.exe":
            pid_file(cfg).unlink(missing_ok=True)
            return None
        expected = cfg.llama_server_exe()
        argv = proc.cmdline()
        port_index = argv.index("--port") if "--port" in argv else -1
        if (expected is None or Path(proc.exe()).resolve() != expected.resolve()
                or port_index < 0 or port_index + 1 >= len(argv)
                or argv[port_index + 1] != str(cfg.data["server"]["port"])):
            pid_file(cfg).unlink(missing_ok=True)
            return None
        return proc
    except Exception:
        pid_file(cfg).unlink(missing_ok=True)
        return None


def slots_processing(cfg: Config) -> bool | None:
    """Check whether the server is processing a request; None means unavailable."""
    try:
        r = requests.get(f"{cfg.base_url}/slots", timeout=3)
        slots = r.json()
        return any(bool(s.get("is_processing")) for s in slots if isinstance(s, dict))
    except Exception:
        return None


def stop(cfg: Config, quiet: bool = False) -> bool:
    import psutil
    pf = pid_file(cfg)
    record = _pid_record(cfg)
    strata = record is not None and _backend_of(cfg, record[0]) == "strata"
    proc = _managed_process(cfg)
    killed = False
    if proc is not None:
        if strata:
            # The engine quits and frees the GPU and its pinned RAM itself; the
            # process tree is ended below either way.
            from harness import strata_backend
            outcome = strata_backend.unload(cfg)
            if not quiet:
                print(f"[INFO] Strata unload: {outcome}")
        try:
            children = proc.children(recursive=True)
            for c in children:
                c.kill()
            proc.kill()
            _, alive = psutil.wait_procs(children + [proc], timeout=5)
            if alive:
                return False
            killed = True
        except psutil.NoSuchProcess:
            pass
        pf.unlink(missing_ok=True)
        for _ in range(15):
            if not health(cfg, timeout=1.0):
                break
            time.sleep(1)
    pf.unlink(missing_ok=True)
    if not quiet:
        name = "Strata server" if strata else "llama-server"
        print(f"[OK] {name} stopped." if killed else f"[INFO] {name} was not running.")
    return True


def start(cfg: Config, model_key: str | None = None, ctx_size: int | None = None,
          *, cancelled=None, on_phase=None, on_download_progress=None) -> int:
    with _start_lock:
        return _start_locked(cfg, model_key, ctx_size, cancelled=cancelled, on_phase=on_phase,
                             on_download_progress=on_download_progress)


def _mtp_draft_args(cfg: Config, *, cancelled=None, on_phase=None, on_download_progress=None) -> list[str]:
    """Resolve, and download when necessary, the pinned MTP draft for speculative profiles."""
    if not cfg.mtp_draft_ready():
        from harness.model_catalog import QWEN27B_MTP_DRAFT
        from harness.model_files import download_pinned_model
        if on_phase:
            on_phase("downloading")
        download_pinned_model(cfg.path("paths.models_dir"), QWEN27B_MTP_DRAFT,
                              should_stop=cancelled, on_progress=on_download_progress, on_phase=on_phase)
    draft = cfg.mtp_draft_file()
    if not draft.is_file():
        raise RuntimeError(f"The MTP draft model is unavailable: {draft}")
    return ["--spec-type", "draft-mtp", "--spec-draft-model", str(draft)]


def _start_locked(cfg: Config, model_key: str | None = None,
                  ctx_size: int | None = None, *, cancelled=None, on_phase=None, on_download_progress=None) -> int:
    model_key = model_key or cfg.model_key()
    if cancelled and cancelled():
        return 1
    if model_key not in cfg.data["models"]:
        print(f"[ERROR] Unknown model '{model_key}'. Available: {', '.join(cfg.data['models'])}")
        return 1
    from harness.gpu import normalize_vram_setting
    cfg.data.setdefault("hardware", {})["vram_gb"] = normalize_vram_setting(
        cfg.data.get("hardware", {}).get("vram_gb", "auto"))
    strata = cfg.backend(model_key) == "strata"

    if health(cfg):
        current = running_model(cfg)
        if current == model_key:
            print(f"[OK] {'Strata server' if strata else 'llama-server'} already running "
                  f"with model '{model_key}' ({cfg.base_url})")
            print("   ", vram_str())
            return 0
        print(f"[INFO] Model '{current}' is running, switching to '{model_key}' ...")
        if not stop(cfg, quiet=True):
            raise RuntimeError("The previous model has not released its memory")

    model = cfg.model(model_key)
    from harness.gpu import effective_vram_gb, fitting_profiles, fits
    budget = effective_vram_gb(cfg)
    if not fits(cfg, model_key, cfg.kv_cache_mode(model_key), budget):
        profiles = fitting_profiles(cfg, model_key, budget)
        if not profiles:
            raise RuntimeError(f"This model has no supported profile for the {budget:g} GiB GPU budget. Choose a smaller model.")
        selected = max(profiles, key=lambda name: (profiles[name].get("cache_type") == "q8_0",
                                                   int(profiles[name].get("ctx_size", 0)),
                                                   profiles[name].get("speculative") is None))
        cfg.set_kv_cache_mode(model_key, selected)
    requested_context = ctx_size or cfg.context_size(model_key)
    (cfg.path("paths.runtime_dir") / "model-failure.json").unlink(missing_ok=True)
    if strata:
        # The engine first: the weights are of no use without it, and it is the smaller download.
        from harness import strata_runtime
        strata_runtime.ensure_runtime(cfg, model_key, cancelled=cancelled, on_phase=on_phase)
    if model.get("assets") and not cfg.model_ready(model_key):
        from harness.model_files import download_pinned_model
        if on_phase:
            on_phase("downloading")
        download_pinned_model(cfg.model_root(model_key), model, should_stop=cancelled,
                              on_progress=on_download_progress, on_phase=on_phase)
    if on_phase:
        on_phase("preparing")
    if strata:
        from harness import strata_runtime
        strata_runtime.prepare_model(cfg, model_key, cancelled=cancelled, on_phase=on_phase)
        return _start_strata(cfg, model_key, requested_context, cancelled=cancelled, on_phase=on_phase)
    from harness.runtime_update import ensure_runtime
    exe = ensure_runtime(cfg, model_key, cancelled=cancelled)
    if exe is None:
        print("[ERROR] llama-server.exe not found. Run first: python scripts/download_llama.py")
        return 1
    mfile = cfg.model_file(model_key)
    mmproj = cfg.mmproj_file(model_key)
    if not mfile.exists():
        print(f"[ERROR] Model not found: {mfile}")
        print("        Download it: python scripts/download_models.py --model", model_key)
        return 1

    srv = cfg.data["server"]
    ctx = requested_context
    if cancelled and cancelled():
        return 1
    argv = [
        str(exe),
        "-m", str(mfile),
        "-ngl", str(srv.get("n_gpu_layers", 999)),
        "-c", str(ctx),
        "-np", "1",              # One slot assigns the entire context to the single user stream.
        "--host", srv["host"],
        "--port", str(srv["port"]),
        "--jinja",               # Enable the model chat template and tool calling.
        "--reasoning-preserve",  # Preserve reasoning between tool-call rounds.
        "--image-min-tokens", "1024",  # Use sufficient image tokens for precise computer-use grounding.
        "--alias", model_key,
    ]
    if mmproj is None:
        pass  # Text-only models do not need a multimodal projector.
    elif mmproj.exists():
        argv += ["--mmproj", str(mmproj)]
    else:
        print(f"[WARNING] mmproj not found ({mmproj}) - vision (images) will not work!")
    argv += cfg.kv_cache_server_args(model_key)
    argv += [str(x) for x in cfg.model(model_key).get("server_args", [])]
    # Profiles may supply server arguments, such as --n-cpu-moe for a specific GPU budget
    profile = cfg.kv_cache_profiles(model_key).get(cfg.kv_cache_mode(model_key), {})
    frozen = cfg.data.get("_recovery_placement", {})
    profile_args = frozen.get("server_args", []) if frozen.get("model") == model_key else profile.get("server_args", [])
    argv += [str(x) for x in profile_args]
    active_placement = {"model": model_key, "server_args": list(profile_args)}
    if cfg.data.get("hardware", {}).get("vram_gb", "auto") != "auto":
        argv += ["--fit", "off"]
    if profile.get("speculative") == "mtp":
        argv += _mtp_draft_args(cfg, cancelled=cancelled, on_phase=on_phase,
                                on_download_progress=on_download_progress)
    argv += [str(x) for x in srv.get("extra_args", [])]
    cfg.data["_active_placement"] = active_placement
    return _launch(cfg, model_key, argv, cwd=exe.parent,
                   log_path=cfg.path("paths.runtime_dir") / "llama-server.log",
                   ctx=ctx, placement=active_placement, cancelled=cancelled, on_phase=on_phase)


def _start_strata(cfg: Config, model_key: str, ctx: int, *, cancelled=None, on_phase=None) -> int:
    from harness import strata_backend
    from harness.hardware import detect_hardware
    prepared = strata_backend.prepare(cfg, model_key, ctx, hardware=detect_hardware(fresh=True))
    if cancelled and cancelled():
        return 1
    cfg.data["_active_placement"] = prepared.placement
    return _launch(cfg, model_key, prepared.argv, cwd=prepared.cwd, log_path=strata_backend.server_log(cfg),
                   ctx=ctx, placement=prepared.placement, cancelled=cancelled, on_phase=on_phase,
                   strata=prepared)


def guard_available(proc, *, strata: bool) -> int:
    """Available RAM as the emergency memory guard counts it while a server runs.

    Strata reads the experts it does not keep straight from the GGUF files. Those
    pages stay in its working set, where Windows drops them when memory runs short
    but does not count them as available, so they are added back."""
    import psutil
    from harness.hardware import shared_working_set
    available = psutil.virtual_memory().available
    if strata and available < GUARD_RAM_BYTES:
        try:
            pids = [proc.pid] + [p.pid for p in psutil.Process(proc.pid).children(recursive=True)]
            available += shared_working_set(pids)
        except psutil.Error:
            pass
    return available


def guard_patience(*, strata: bool) -> int:
    """Seconds of too little available RAM before the guard ends the server.

    A Strata server gets a minute while Windows can still page its cold experts out;
    once commit runs out, or for llama.cpp, the usual ten seconds."""
    if not strata:
        return GUARD_SECONDS
    from harness.hardware import commit_headroom
    headroom = commit_headroom()
    return GUARD_SECONDS if headroom is not None and headroom < GUARD_COMMIT_BYTES else GUARD_PAGING_SECONDS


def _end_tree(proc) -> None:
    """End a process's children; the Strata server runs its engine and image encoder as children."""
    try:
        import psutil
        children = psutil.Process(proc.pid).children(recursive=True)
    except Exception:
        return
    for child in children:
        try:
            child.kill()
        except Exception:
            pass


def _settle_strata(cfg: Config, run: dict, *, ready: bool) -> None:
    """Record what the engine settled on, so a recovery keeps the same expert cache and only shrinks the context."""
    from harness import strata_backend
    from harness.changes import atomic_write_text
    slots = strata_backend.observed_expert_cache(run)
    if slots:
        run["placement"]["expert_cache_slots"] = slots
    if ready:
        run.update(strata_backend.log_offsets(cfg, run))
    atomic_write_text(cfg.path("paths.runtime_dir") / "model-run.json", json.dumps(run))


def _launch(cfg: Config, model_key: str, argv: list[str], *, cwd: Path, log_path: Path, ctx: int,
            placement: dict, cancelled=None, on_phase=None, strata=None) -> int:
    """Start the server process, record it, guard host memory and wait until it is ready."""
    if on_phase:
        on_phase("loading")

    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_offset = log_path.stat().st_size if log_path.exists() else 0
    logf = open(log_path, "ab", buffering=0)
    logf.write(f"\n===== START {model_key} {time.strftime('%Y-%m-%d %H:%M:%S')} =====\n".encode())
    # Strata's server is Python: it gets its own environment and no console input.
    options = {"stdin": subprocess.DEVNULL, "env": strata.env} if strata else {}
    try:
        proc = subprocess.Popen(
            argv, stdout=logf, stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW,
            cwd=str(cwd), **options,
        )
    finally:
        logf.close()
    if strata and BIND_SERVER_TO_PROCESS:
        from harness.winjob import contain
        contain(proc)
    pid_file(cfg).write_text(f"{model_key}:{proc.pid}", encoding="utf-8")
    from harness.changes import atomic_write_text
    run = {"model": model_key, "pid": proc.pid, "context": ctx, "placement": placement,
           "log_offset": log_offset, "started": time.time()}
    if strata:
        run.update(strata.run)
    atomic_write_text(cfg.path("paths.runtime_dir") / "model-run.json", json.dumps(run))
    loaded = threading.Event()
    memory_failure = []
    requested_budget = cfg.data.get("hardware", {}).get("vram_gb", "auto")
    from harness.hardware import detect_hardware
    hw = detect_hardware(fresh=True)
    capacity = min(hw.vram_total, int(float(requested_budget) * 1024**3)) if requested_budget != "auto" else hw.vram_total
    if capacity:
        def watch_memory():
            low_samples = 0
            gpu_used = 0
            while proc.poll() is None:
                available = guard_available(proc, strata=bool(strata))
                # Emergency host protection, not a profile reserve. Allow Windows
                # to reclaim pages; never fail merely because commit/pagefile grew.
                low_samples = low_samples + 1 if available < GUARD_RAM_BYTES else 0
                stop_loading = not loaded.is_set() and cancelled and cancelled()
                exhausted = low_samples >= GUARD_SECONDS and low_samples >= guard_patience(strata=bool(strata))
                if exhausted or stop_loading:
                    if exhausted:
                        code = "ram_pressure"
                        memory_failure.append("The model needs more system RAM for the current memory profile." if code == "ram_pressure"
                                              else "The selected GPU memory budget is not sufficient for this profile and other running programs.")
                        from harness.changes import atomic_write_text
                        atomic_write_text(cfg.path("paths.runtime_dir") / "model-failure.json",
                            json.dumps({"model": model_key, "error": memory_failure[0], "time": time.time(),
                                        "code": code, "context": ctx, "vram_used_bytes": gpu_used,
                                        "available_ram_bytes": available,
                                        "vram_gb": cfg.data.get("hardware", {}).get("vram_gb", "auto")}))
                        with log_path.open("ab") as log:
                            log.write(f"\n[MEMORY GUARD] {code}; requesting a safer profile.\n".encode())
                    if strata:
                        _end_tree(proc)
                    try:
                        proc.terminate()
                    except OSError:
                        pass
                    return
                time.sleep(1)
            if not (cancelled and cancelled()):
                record_allocation_failure(cfg)
        threading.Thread(target=watch_memory, name="model-memory-guard", daemon=True).start()
    print(f"[START] model={model_key}  ctx={ctx}  pid={proc.pid}  -> {cfg.base_url}")
    print(f"        log: {log_path}")
    print("[WAIT] loading the model into VRAM ...", end="", flush=True)
    t0 = time.time()
    readiness = {}
    if strata:
        from harness import strata_backend
        # Its port opens once the model is loaded, and /health then answers 200 even unloaded.
        readiness["probe"] = strata_backend.ready
    if not wait_health(cfg, proc=proc, cancelled=cancelled, **readiness):
        print(f"\n[ERROR] Server startup failed after {time.time() - t0:.0f}s. Last log lines:")
        print(log_path.read_bytes()[-2000:].decode(errors="replace"))
        if strata:
            _end_tree(proc)
        if proc.poll() is None:
            proc.kill()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            raise RuntimeError("The stopped model has not released its memory yet")
        pid_file(cfg).unlink(missing_ok=True)
        if strata:
            _settle_strata(cfg, run, ready=False)
        if not (cancelled and cancelled()):
            record_allocation_failure(cfg)
        if memory_failure:
            raise RuntimeError(memory_failure[0])
        if strata and not (cancelled and cancelled()):
            # Strata says why it stopped (driver, CUDA libraries, files); the
            # recovery ladder still takes over when that was memory.
            raise RuntimeError(strata_backend.start_failure(cfg, run))
        return 1
    loaded.set()
    if strata:
        _settle_strata(cfg, run, ready=True)
    print(f" OK ({time.time() - t0:.0f}s)")
    print("   ", vram_str())
    return 0


def status(cfg: Config) -> int:
    if health(cfg):
        info = ""
        try:
            r = requests.get(f"{cfg.base_url}/props", timeout=3).json()
            info = str(r.get("model_path", ""))
        except Exception:
            pass
        print(f"[RUNNING] {cfg.base_url}  (model from pidfile: {running_model(cfg)})")
        if info:
            print(f"        {info}")
        print("   ", vram_str())
        return 0
    print(f"[DOWN] {cfg.base_url} not responding. Start: python scripts/server.py start")
    return 1


def ensure(cfg: Config, model_key: str | None = None, *, cancelled=None, on_phase=None, on_download_progress=None) -> bool:
    """Ensure the requested model is running, starting or switching it as needed."""
    if health(cfg) and (model_key is None or running_model(cfg) == model_key):
        return True
    key = model_key or cfg.model_key()
    while True:
        try:
            if start(cfg, key, cancelled=cancelled, on_phase=on_phase,
                     on_download_progress=on_download_progress) == 0:
                return True
        except RuntimeError:
            if last_failure(cfg).get("code") not in ("ram_pressure", "vram_pressure"):
                raise
        if cancelled and cancelled():
            return False
        failure = last_failure(cfg)
        if failure.get("code") not in ("ram_pressure", "vram_pressure") or failure.get("model") != key:
            return False
        from harness.gpu import lower_memory_profiles
        lower = lower_memory_profiles(cfg, key)
        if not lower:
            raise RuntimeError(failure.get("error") or "There is not enough free system RAM")
        if cfg.kv_cache_profiles(key).get(cfg.kv_cache_mode(key), {}).get("speculative") == "mtp":
            # The recovery ladder interleaves MTP/plain variants only for sessions
            # that started on a speculative profile; plain selections stay plain.
            cfg.data.setdefault("_recovery_origin_mtp", {})[key] = True
        from harness.measured_profiles import freeze_placement
        freeze_placement(cfg, key)
        cfg.set_kv_cache_mode(key, lower[0])
        cfg.data.setdefault("_recovered_contexts", {})[key] = cfg.context_size(key)
        cfg.data["_memory_profile_recovered"] = True
        if on_phase:
            on_phase("preparing")
