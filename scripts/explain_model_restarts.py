"""Say why the model server was restarted, and what each restart cost.

A restart throws away the processed prompt, because the prompt cache lives inside
the process. Reuse within a task runs at 96%; almost all of the time ever spent
reading prompts goes on the first request after a restart. Switching model is a
cost worth paying. The others are worth knowing about.

    python scripts/explain_model_restarts.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from harness import restart_log                  # noqa: E402
from harness.config import load_config           # noqa: E402

EXPLANATIONS = {
    "different_model_running": "a different model was loaded - a switch you asked for",
    "no_server_running": "no server was running at all",
    "server_unhealthy": "the server did not answer /health",
    "profile_changed": "the KV cache profile changed",
    "hardware_changed": "the recorded hardware changed",
    "memory_pressure_recovery": "retried with a smaller context after memory pressure",
}


def main() -> int:
    cfg = load_config()
    runtime = cfg.path("paths.runtime_dir")
    report = restart_log.summary(runtime)
    if not report["restarts"]:
        print("No restart has been recorded yet.")
        print("Restarts are recorded from the next task onwards.")
        return 0

    print("restarts recorded:", report["restarts"], "   from", report["first"], "to", report["last"])
    print()
    print("%-28s %6s  %s" % ("reason", "count", "what it means"))
    for name, count in sorted(report["by_reason"].items(), key=lambda item: -item[1]):
        print("%-28s %6d  %s" % (name, count, EXPLANATIONS.get(name, "")))
    print()
    print("restarts caused only by a model switch: %d of %d"
          % (report["model_switch_only"], report["restarts"]))
    print()
    print("the most recent:")
    print("%-21s %-26s %-10s %-10s %s" % ("when", "reason", "running", "wanted", "context"))
    for row in restart_log.entries(runtime)[-15:]:
        print("%-21s %-26s %-10s %-10s %s"
              % (row.get("when"), ",".join(row.get("reason") or []),
                 row.get("running") or "-", row.get("wanted") or "-", row.get("context") or "-"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
