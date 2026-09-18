"""CPU-only llama-server sidecar serving /v1/embeddings for semantic search.

The GPU always belongs to the main model, so this helper process runs with
-ngl 0 on CPU threads only. It is started lazily on the first semantic search
and stopped when the application closes. The pid file records a plain pid that
is re-validated against the executable and the sidecar port, so it can never be
confused with the main llama-server."""
from __future__ import annotations

import atexit
import json
import subprocess
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import psutil

from harness.config import Config

_start_lock = threading.Lock()
HEALTH_TIMEOUT = 180.0  # A small CPU model loads in seconds; this is the ceiling.
EMBED_BATCH = 32
_registered_atexit = False


def _pid_file(cfg: Config) -> Path:
    return cfg.path("paths.runtime_dir") / "llama-embeddings.pid"


def _port(cfg: Config) -> int:
    return int(cfg.data["server"].get("embeddings_port", 8091))


def health(cfg: Config, timeout: float = 2.0) -> bool:
    try:
        with urllib.request.urlopen(f"{cfg.embeddings_url}/health", timeout=timeout) as r:
            return r.status == 200
    except (OSError, urllib.error.URLError):
        return False


_status_cache: dict = {"at": 0.0, "ok": False}


def status(cfg: Config) -> bool:
    """Cheap sidecar status for UI polls: no pid file means no probe at all.

    A network health check must never sit on the /api/state hot path — waiting
    out the timeout on a closed port stalled the whole interface."""
    if _sidecar_process(cfg) is None:
        _status_cache.update(at=time.monotonic(), ok=False)
        return False
    now = time.monotonic()
    if now - _status_cache["at"] < 10:
        return _status_cache["ok"]
    ok = health(cfg, timeout=0.5)
    _status_cache.update(at=now, ok=ok)
    return ok


def _sidecar_process(cfg: Config) -> psutil.Process | None:
    """Return the running sidecar recorded in the pid file, or None."""
    try:
        pid = int(_pid_file(cfg).read_text(encoding="utf-8").strip())
        proc = psutil.Process(pid)
        if proc.name() != "llama-server.exe":
            raise ValueError("not llama-server")
        exe = proc.exe()
        if not exe or Path(exe).resolve() != cfg.llama_server_exe().resolve():
            raise ValueError("different executable")
        cmdline = proc.cmdline()
        if str(_port(cfg)) not in cmdline or "--embeddings" not in cmdline:
            raise ValueError("different server")
        return proc
    except (OSError, ValueError, psutil.Error):
        _pid_file(cfg).unlink(missing_ok=True)
        return None


def _wait_health(cfg: Config, proc: subprocess.Popen, timeout: float = HEALTH_TIMEOUT) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            return False
        if health(cfg):
            return True
        time.sleep(1.0)
    return False


def ensure_started(cfg: Config, *, on_progress=None) -> bool:
    """Start (or adopt) the embeddings sidecar; download the model on first use."""
    global _registered_atexit
    if health(cfg):
        return True
    with _start_lock:
        if health(cfg):
            return True
        running = _sidecar_process(cfg)
        if running is not None:
            deadline = time.monotonic() + HEALTH_TIMEOUT
            while time.monotonic() < deadline and running.is_running():
                if health(cfg):
                    break
                time.sleep(1.0)
            return health(cfg)
        if not cfg.embeddings_model_ready():
            from harness.model_catalog import EMBEDDINGS_BGE_M3
            from harness.model_files import download_pinned_model
            download_pinned_model(cfg.path("paths.models_dir"), EMBEDDINGS_BGE_M3,
                                  on_progress=on_progress)
        exe = cfg.llama_server_exe()
        model = cfg.embeddings_model_file()
        if not exe.is_file() or not model.is_file():
            raise RuntimeError("The embedding model or llama-server executable is unavailable")
        argv = [
            str(exe), "-m", str(model),
            "-dev", "none",                 # No GPU backend at all: the GPU belongs to the main model.
            "-b", "2048", "-ub", "2048",    # Long Czech history chunks reach ~1600 tokens.
            "--embeddings",
            "--host", str(cfg.data["server"]["host"]),
            "--port", str(_port(cfg)),
            "-a", "embeddings",
        ]
        _pid_file(cfg).parent.mkdir(parents=True, exist_ok=True)
        log = _pid_file(cfg).parent / "embeddings-server.log"
        with open(log, "ab", buffering=0) as logf:
            logf.write(f"\n===== EMBEDDINGS START {time.strftime('%Y-%m-%d %H:%M:%S')} =====\n".encode())
            proc = subprocess.Popen(argv, stdout=logf, stderr=subprocess.STDOUT,
                                    creationflags=subprocess.CREATE_NO_WINDOW, cwd=str(exe.parent))
        _pid_file(cfg).write_text(str(proc.pid), encoding="utf-8")
        if not _wait_health(cfg, proc):
            proc.kill()
            _pid_file(cfg).unlink(missing_ok=True)
            raise RuntimeError("The embeddings sidecar did not become healthy; see runtime/embeddings-server.log")
        if not _registered_atexit:
            atexit.register(lambda: stop(cfg))
            _registered_atexit = True
        return True


def stop(cfg: Config) -> None:
    """Stop the sidecar if it is running. Idempotent."""
    proc = _sidecar_process(cfg)
    _pid_file(cfg).unlink(missing_ok=True)
    if proc is None:
        return
    try:
        children = proc.children(recursive=True)
        proc.kill()
        psutil.wait_procs(children + [proc], timeout=5)
    except psutil.Error:
        pass
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline and health(cfg, timeout=1.0):
        time.sleep(0.5)


def embed_texts(cfg: Config, texts: list[str], *, timeout: float = 300.0):
    """Embed texts through the sidecar; returns a normalized float32 matrix."""
    import numpy as np

    ensure_started(cfg)
    texts = [text or " " for text in texts]
    parts = []
    for start in range(0, len(texts), EMBED_BATCH):
        batch = texts[start:start + EMBED_BATCH]
        body = json.dumps({"model": "embeddings", "input": batch}).encode()
        req = urllib.request.Request(f"{cfg.embeddings_url}/v1/embeddings", data=body,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode())
        matrix = np.asarray([item["embedding"] for item in data["data"]], dtype=np.float32)
        norm = np.linalg.norm(matrix, axis=1, keepdims=True)
        parts.append(matrix / np.maximum(norm, 1e-12))
    if not parts:
        return np.zeros((0, 1), dtype=np.float32)
    return np.concatenate(parts)
