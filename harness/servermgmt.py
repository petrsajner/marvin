"""Správa llama-serveru (inference backend) - start/stop/switch/status.

Používá se z CLI (scripts/server.py), TUI i web UI.
"""
from __future__ import annotations

import subprocess
import json
import threading
import time
from pathlib import Path

import requests

from harness.config import Config

HEALTH_TIMEOUT = 900  # s - první načtení ~17-20GB modelu z disku chvíli trvá
_start_lock = threading.Lock()


def pid_file(cfg: Config) -> Path:
    return cfg.path("paths.runtime_dir") / "llama-server.pid"


def last_failure(cfg: Config) -> dict:
    try:
        value = json.loads((cfg.path("paths.runtime_dir") / "model-failure.json").read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def health(cfg: Config, timeout: float = 3.0) -> bool:
    try:
        r = requests.get(f"{cfg.base_url}/health", timeout=timeout)
        return r.status_code == 200
    except requests.RequestException:
        return False


def wait_health(cfg: Config, timeout: float = HEALTH_TIMEOUT,
                proc: subprocess.Popen | None = None, cancelled=None) -> bool:
    t0 = time.time()
    while time.time() - t0 < timeout:
        if cancelled and cancelled():
            return False
        if health(cfg):
            return True
        if proc is not None and proc.poll() is not None:
            return False
        time.sleep(2)
    return False


NO_WINDOW = 0x08000000  # CREATE_NO_WINDOW - žádné problikávající konzole

_vram_cache: dict = {"ts": 0.0, "value": ""}


def vram_str() -> str:
    """VRAM řetězec s 10s cache (nvidia-smi subprocess je drahý)."""
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
    """Samotná hodnota VRAM bez "GPU VRAM:" prefixu (pro složené UI řádky)."""
    return vram_str().removeprefix("GPU VRAM: ")


def server_state(cfg: Config) -> str:
    """Stav serveru: 'down' | 'starting' | 'running'.

    'starting' = pidfile existuje, ale health ještě neodpovídá
    (typicky načítání modelu do VRAM).
    """
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
    """Vrátí živý llama-server z PID souboru; stale záznam rovnou uklidí."""
    record = _pid_record(cfg)
    if record is None:
        pid_file(cfg).unlink(missing_ok=True)
        return None
    _, pid = record
    try:
        import psutil
        proc = psutil.Process(pid)
        if not proc.is_running() or proc.status() == psutil.STATUS_ZOMBIE:
            raise psutil.NoSuchProcess(pid)
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
    """Zpracovává server právě nějaký požadavek? (None = endpoint nedostupný)."""
    try:
        r = requests.get(f"{cfg.base_url}/slots", timeout=3)
        slots = r.json()
        return any(bool(s.get("is_processing")) for s in slots if isinstance(s, dict))
    except Exception:
        return None


def stop(cfg: Config, quiet: bool = False) -> bool:
    import psutil
    pf = pid_file(cfg)
    proc = _managed_process(cfg)
    killed = False
    if proc is not None:
        try:
            children = proc.children(recursive=True)
            for c in children:
                c.kill()
            proc.kill()
            psutil.wait_procs(children + [proc], timeout=5)
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
        print("[OK] llama-server stopped." if killed else "[INFO] llama-server was not running.")
    return True


def start(cfg: Config, model_key: str | None = None, ctx_size: int | None = None,
          *, cancelled=None, on_phase=None, on_download_progress=None) -> int:
    with _start_lock:
        return _start_locked(cfg, model_key, ctx_size, cancelled=cancelled, on_phase=on_phase,
                              on_download_progress=on_download_progress)


def _start_locked(cfg: Config, model_key: str | None = None,
                  ctx_size: int | None = None, *, cancelled=None, on_phase=None, on_download_progress=None) -> int:
    model_key = model_key or cfg.model_key()
    if cancelled and cancelled():
        return 1
    if model_key not in cfg.data["models"]:
        print(f"[ERROR] Unknown model '{model_key}'. Available: {', '.join(cfg.data['models'])}")
        return 1

    if health(cfg):
        current = running_model(cfg)
        if current == model_key:
            print(f"[OK] llama-server already running with model '{model_key}' ({cfg.base_url})")
            print("   ", vram_str())
            return 0
        print(f"[INFO] Model '{current}' is running, switching to '{model_key}' ...")
        stop(cfg, quiet=True)

    model = cfg.model(model_key)
    requested_context = ctx_size or cfg.context_size(model_key)
    (cfg.path("paths.runtime_dir") / "model-failure.json").unlink(missing_ok=True)
    if model.get("assets") and not cfg.model_ready(model_key):
        if model.get("adaptive_runtime"):
            from harness.runtime_plan import plan_for
            plan_for(cfg, model_key, requested_context)
        from harness.model_files import download_pinned_model
        if on_phase:
            on_phase("downloading")
        download_pinned_model(cfg.path("paths.models_dir"), model, should_stop=cancelled,
                              on_progress=on_download_progress, on_phase=on_phase)
    if on_phase:
        on_phase("preparing")
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
    from harness.runtime_plan import plan_for
    plan = plan_for(cfg, model_key, ctx)
    if plan:
        ctx = plan.context
    if cancelled and cancelled():
        return 1
    argv = [
        str(exe),
        "-m", str(mfile),
        "-ngl", str(srv.get("n_gpu_layers", 999)),
        "-c", str(ctx),
        "-np", "1",              # jeden slot = celý kontext jedinému proudu (single-user)
        "--host", srv["host"],
        "--port", str(srv["port"]),
        "--jinja",               # plná chat template + tool calling
        "--reasoning-preserve",  # zachování reasoning mezi tool-call koly
        "--image-min-tokens", "1024",  # přesnější vision grounding (computer use)
        "--alias", model_key,
    ]
    if mmproj is None:
        pass  # text-only model (bez vision) - mmproj neni treba
    elif mmproj.exists():
        argv += ["--mmproj", str(mmproj)]
    else:
        print(f"[WARNING] mmproj not found ({mmproj}) - vision (images) will not work!")
    argv += cfg.kv_cache_server_args(model_key)
    argv += [str(x) for x in cfg.model(model_key).get("server_args", [])]
    # profil muze nesit vlastni server args (napr. --n-cpu-moe pretok pro danou kartu)
    profile = cfg.kv_cache_profiles(model_key).get(cfg.kv_cache_mode(model_key), {})
    argv += [str(x) for x in profile.get("server_args", [])]
    if plan:
        argv += list(plan.args)
    argv += [str(x) for x in srv.get("extra_args", [])]

    if on_phase:
        on_phase("loading")

    log_path = cfg.path("paths.runtime_dir") / "llama-server.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logf = open(log_path, "ab", buffering=0)
    logf.write(f"\n===== START {model_key} {time.strftime('%Y-%m-%d %H:%M:%S')} =====\n".encode())
    try:
        proc = subprocess.Popen(
            argv, stdout=logf, stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW,
            cwd=str(exe.parent),
        )
    finally:
        logf.close()
    pid_file(cfg).write_text(f"{model_key}:{proc.pid}", encoding="utf-8")
    loaded = threading.Event()
    memory_failure = []
    if plan:
        def watch_memory():
            import psutil
            low_samples = 0
            while proc.poll() is None:
                available = psutil.virtual_memory().available
                low_samples = low_samples + 1 if available < 2 * 1024**3 else 0
                stop_loading = not loaded.is_set() and cancelled and cancelled()
                if low_samples >= 2 or stop_loading:
                    if low_samples >= 2:
                        memory_failure.append("Model stopped because system memory became critically low.")
                        from harness.changes import atomic_write_text
                        atomic_write_text(cfg.path("paths.runtime_dir") / "model-failure.json",
                            json.dumps({"model": model_key, "error": memory_failure[0], "time": time.time()}))
                        with log_path.open("ab") as log:
                            log.write(b"\n[MEMORY GUARD] Available RAM below 2 GiB; stopping this model.\n")
                    try:
                        proc.terminate()
                    except OSError:
                        pass
                    return
                time.sleep(1)
        threading.Thread(target=watch_memory, name="model-memory-guard", daemon=True).start()
    print(f"[START] model={model_key}  ctx={ctx}  pid={proc.pid}  -> {cfg.base_url}")
    print(f"        log: {log_path}")
    print("[WAIT] loading the model into VRAM ...", end="", flush=True)
    t0 = time.time()
    if not wait_health(cfg, proc=proc, cancelled=cancelled):
        print(f"\n[ERROR] Server startup failed after {time.time() - t0:.0f}s. Last log lines:")
        print(log_path.read_bytes()[-2000:].decode(errors="replace"))
        if proc.poll() is None:
            proc.kill()
        pid_file(cfg).unlink(missing_ok=True)
        if memory_failure:
            raise RuntimeError(memory_failure[0])
        return 1
    loaded.set()
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
    """Zajišť běžící server se zadaným modelem (případně start/switch)."""
    if health(cfg) and (model_key is None or running_model(cfg) == model_key):
        return True
    return start(cfg, model_key, cancelled=cancelled, on_phase=on_phase,
                  on_download_progress=on_download_progress) == 0
