"""Model-free project check runner with persistent per-project status.

Runs the project's detected or configured checks (tests/lint/typecheck/build)
sequentially in a background thread and records every outcome in
<workspace>/.qwen/check-status.json, following the decisions.json precedent.
The UI polls the status; the agent-driven repair flow reuses the same check
definitions through start_project_check."""
from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
from pathlib import Path

NO_WINDOW = 0x08000000
SUMMARY_LINES = 30

_running: set[str] = set()
_lock = threading.Lock()

FIX_PROMPT = (
    "Run the project's primary checks with start_project_check and poll them to "
    "completion. Analyze every failure, fix the code, and re-run the checks until "
    "they all pass or you can explain exactly what still blocks them. Never weaken, "
    "skip or delete tests to make them pass. Finish with a clear summary of what you "
    "changed and the final check results.")


def status_path(workspace: Path) -> Path:
    return Path(workspace) / ".qwen" / "check-status.json"


def _python_for(workspace: Path) -> str:
    venv_python = Path(workspace) / ".venv" / "Scripts" / "python.exe"
    return str(venv_python) if venv_python.is_file() else sys.executable


def check_definitions(cfg, workspace: Path) -> list[dict]:
    from harness.project_profile import ProjectProfile
    python = _python_for(workspace)
    return [item.as_dict() for item in ProjectProfile(workspace, python).checks()]


def read_status(workspace: Path) -> dict:
    try:
        data = json.loads(status_path(workspace).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    key = str(Path(workspace).resolve()).lower()
    with _lock:
        running = key in _running
    for row in data.get("checks", []):
        if running and row.get("state") in ("pass", "fail", "timeout", "error", "never"):
            continue
    return {"updated": data.get("updated", 0), "checks": data.get("checks", []), "running": running}


def is_running(workspace: Path) -> bool:
    with _lock:
        return str(Path(workspace).resolve()).lower() in _running


def _write_status(workspace: Path, rows: list[dict]) -> None:
    from harness.changes import atomic_write_text
    atomic_write_text(status_path(workspace),
                      json.dumps({"updated": time.time(), "checks": rows}, ensure_ascii=False, indent=1))


def _run_one(workspace: Path, definition: dict) -> dict:
    from harness.processes import shell_argv
    started = time.time()
    try:
        proc = subprocess.run(
            shell_argv(definition["command"], definition.get("shell", "powershell")),
            cwd=workspace, capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=max(1, int(definition.get("timeout") or 900)),
            creationflags=NO_WINDOW)
        output = ((proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")).strip()
        state = "pass" if proc.returncode == 0 else "fail"
        exit_code = proc.returncode
    except subprocess.TimeoutExpired as exc:
        output = ((exc.stdout or b"").decode("utf-8", "replace") if isinstance(exc.stdout, bytes) else (exc.stdout or ""))
        state, exit_code = "timeout", None
    except OSError as exc:
        output, state, exit_code = str(exc), "error", None
    tail = "\n".join(output.splitlines()[-SUMMARY_LINES:])
    return {**definition, "state": state, "exit_code": exit_code,
            "time": started, "duration": round(time.time() - started, 1), "summary": tail[:4000]}


def run_checks(cfg, workspace: Path) -> bool:
    """Start a background run of all project checks; False if one is already running."""
    workspace = Path(workspace).resolve()
    key = str(workspace).lower()
    with _lock:
        if key in _running:
            return False
        _running.add(key)

    definitions = check_definitions(cfg, workspace)

    def worker() -> None:
        try:
            rows = []
            for definition in definitions:
                _write_status(workspace, rows + [{**definition, "state": "running", "time": time.time()}])
                rows.append(_run_one(workspace, definition))
            _write_status(workspace, rows)
        finally:
            with _lock:
                _running.discard(key)

    threading.Thread(target=worker, name="project-checks", daemon=True).start()
    return True
