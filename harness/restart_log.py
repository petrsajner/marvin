"""Record why the model server was restarted, because a restart is expensive.

Restarting llama-server throws away the processed prompt: the cache lives inside
the process, so the next request pays for the whole conversation again - 92
seconds for 150k tokens, measured. Reuse within a task runs at 96%, and almost
all of the time ever spent reading prompts goes on the first request after a
restart.

The server log shows that restarts happen - 134 separate processes in one log,
83 of which loaded 19.8 GB of weights and then served nothing - but not why. Four
conditions can each trigger one and the decision recorded none of them, so the
reason had to be reconstructed days later from prompt sizes. This writes it down
at the moment it is taken.

Nothing here is a conversation: the reason, the models involved, the profile and
the context. See scripts/explain_model_restarts.py.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

KEEP = 200               # Enough to see a pattern across several days of work.
FILENAME = "model-restarts.log"


def reasons(*, profile_changed: bool, hardware_changed: bool,
            healthy: bool, running: str | None, wanted: str) -> list[str]:
    """Name every condition that argued for a restart, not just the first.

    They are not exclusive, and which of them fires is the whole question: a
    model the owner chose is a restart worth paying for, an unhealthy server or a
    model that only looks wrong is not."""
    found = []
    if profile_changed:
        found.append("profile_changed")
    if hardware_changed:
        found.append("hardware_changed")
    if not healthy:
        found.append("server_unhealthy")
    if running != wanted:
        found.append("no_server_running" if running is None else "different_model_running")
    return found


def record(runtime_dir: Path, *, reason: list[str] | str, wanted: str,
           running: str | None = None, profile: str | None = None,
           context: int | None = None, note: str | None = None) -> None:
    """Append one line for one restart decision. Never raises."""
    try:
        path = Path(runtime_dir) / FILENAME
        path.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "at": time.time(),
            "when": time.strftime("%Y-%m-%d %H:%M:%S"),
            "reason": [reason] if isinstance(reason, str) else list(reason),
            "wanted": wanted,
            "running": running,
            "profile": profile,
            "context": context,
        }
        if note:
            entry["note"] = note
        lines = []
        if path.is_file():
            lines = path.read_text(encoding="utf-8").splitlines()[-(KEEP - 1):]
        lines.append(json.dumps(entry, ensure_ascii=False))
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    except Exception:
        pass         # A diagnostic must never be able to stop a task.


def record_for(cfg, *, reason: list[str] | str, wanted: str, running: str | None = None,
               profile: str | None = None, context: int | None = None,
               note: str | None = None) -> None:
    """Record a decision, reading the runtime path and context from cfg itself.

    Every lookup happens inside the try, including `context_size`, which raises
    for a model without a configured context. A diagnostic must not be able to
    fail where the restart decision is being made."""
    try:
        if context is None:
            try:
                context = cfg.context_size(wanted)
            except Exception:
                context = None
        record(cfg.path("paths.runtime_dir"), reason=reason, wanted=wanted,
               running=running, profile=profile, context=context, note=note)
    except Exception:
        pass


def entries(runtime_dir: Path) -> list[dict]:
    """Every recorded decision, oldest first."""
    path = Path(runtime_dir) / FILENAME
    if not path.is_file():
        return []
    out = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


def summary(runtime_dir: Path) -> dict:
    """How many restarts, and how they divide by reason.

    A restart the owner asked for by switching model is not the same finding as
    one the harness talked itself into, so they are counted apart."""
    rows = entries(runtime_dir)
    counts: dict[str, int] = {}
    for row in rows:
        for name in row.get("reason") or ["unknown"]:
            counts[name] = counts.get(name, 0) + 1
    chosen = sum(1 for row in rows
                 if set(row.get("reason") or []) <= {"different_model_running"} and row.get("reason"))
    return {"restarts": len(rows), "by_reason": counts, "model_switch_only": chosen,
            "first": rows[0].get("when") if rows else None,
            "last": rows[-1].get("when") if rows else None}
