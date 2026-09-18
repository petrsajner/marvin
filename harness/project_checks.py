"""Model-free project check runner with persistent per-project status.

Runs the project's detected or configured checks (tests/lint/typecheck/build)
sequentially in a background thread and records every outcome in
<workspace>/.qwen/check-status.json, following the decisions.json precedent.
The UI polls the status; the agent-driven repair flow reuses the same check
definitions through start_project_check."""
from __future__ import annotations

import json
import subprocess
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


def check_definitions(cfg, workspace: Path) -> list[dict]:
    from harness.project_profile import ProjectProfile, project_python
    return [item.as_dict()
            for item in ProjectProfile(workspace, project_python(workspace)).checks()]


# Outcome fields carried over from a persisted run onto the current definition.
_OUTCOME_FIELDS = ("state", "exit_code", "time", "duration", "summary")


def read_status(workspace: Path) -> dict:
    """Raw persisted status, without merging in the current check definitions."""
    try:
        data = json.loads(status_path(workspace).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def status(cfg, workspace: Path) -> dict:
    """Current check definitions merged with each check's persisted outcome.

    A check that has never run reports state "never" so the UI can list the
    detected checks before the first run; a stored outcome whose check no longer
    exists is dropped instead of lingering in the panel."""
    workspace = Path(workspace)
    definitions = check_definitions(cfg, workspace)
    stored = read_status(workspace)
    saved = {row.get("id"): row for row in stored.get("checks", [])}
    rows = []
    for definition in definitions:
        row = dict(definition)
        for field in _OUTCOME_FIELDS:
            if field in saved.get(definition["id"], {}):
                row[field] = saved[definition["id"]][field]
        row.setdefault("state", "never")
        rows.append(row)
    return {"updated": stored.get("updated", 0), "checks": rows,
            "running": is_running(workspace), "available": bool(definitions)}


def is_running(workspace: Path) -> bool:
    with _lock:
        return str(Path(workspace).resolve()).lower() in _running


def _write_status(workspace: Path, rows: list[dict]) -> None:
    """Persist the status, tolerating a concurrent reader.

    atomic_write_text already retries a replace that a reader is blocking.
    Losing the status anyway must still never abort the run itself."""
    from harness.changes import atomic_write_text
    payload = json.dumps({"updated": time.time(), "checks": rows},
                         ensure_ascii=False, indent=1)
    try:
        atomic_write_text(status_path(workspace), payload)
    except OSError:
        pass  # Already retried there; a lost status must never end the run.


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
    """Start a background run of all project checks; False if nothing can start.

    Detection runs before the slot is claimed: a failure while detecting would
    otherwise leave the project marked as running for the rest of the session,
    rejecting every later run."""
    workspace = Path(workspace).resolve()
    key = str(workspace).lower()
    definitions = check_definitions(cfg, workspace)
    if not definitions:
        return False
    with _lock:
        if key in _running:
            return False
        _running.add(key)

    def worker() -> None:
        try:
            # Every write carries all rows, so a poll during the run always sees
            # each detected check with its real state.
            rows = [{**definition, "state": "queued"} for definition in definitions]
            _write_status(workspace, rows)
            for index, definition in enumerate(definitions):
                rows[index] = {**definition, "state": "running", "time": time.time()}
                _write_status(workspace, rows)
                rows[index] = _run_one(workspace, definition)
                _write_status(workspace, rows)
        finally:
            with _lock:
                _running.discard(key)

    try:
        threading.Thread(target=worker, name="project-checks", daemon=True).start()
    except RuntimeError:
        with _lock:
            _running.discard(key)
        raise
    return True
