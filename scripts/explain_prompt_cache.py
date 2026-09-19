"""Say why a conversation stopped reusing its processed prompt.

Every request records a fingerprint - one line per message, with a hash of exactly
what was sent. This compares consecutive requests and names the first message that
changed, which is the point from which the server has to start again.

    python scripts/explain_prompt_cache.py                 # the newest conversation
    python scripts/explain_prompt_cache.py <session-id>
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from harness.config import load_config          # noqa: E402
from harness import request_trace               # noqa: E402


def main() -> int:
    cfg = load_config()
    sessions = cfg.path("paths.sessions_dir")
    if len(sys.argv) > 1:
        directory = sessions / sys.argv[1]
    else:
        candidates = [item for item in sessions.iterdir()
                      if item.is_dir() and (item / "requests").is_dir()]
        if not candidates:
            print("No conversation has recorded any requests yet.")
            print("Requests are recorded from the next task onwards.")
            return 0
        directory = max(candidates, key=lambda item: (item / "requests").stat().st_mtime)
    traces = directory / "requests"
    if not traces.is_dir():
        print("No requests recorded for", directory.name)
        return 0

    print("conversation:", directory.name)
    report = request_trace.compare(traces)
    if not report:
        print("Only one request recorded so far; nothing to compare.")
        return 0
    clean = [row for row in report if row["appended_only"]]
    print("compared %d consecutive pairs: %d appended only, %d rewrote something\n"
          % (len(report), len(clean), len(report) - len(clean)))
    for row in report:
        if row["appended_only"]:
            continue
        print("%s -> %s" % (row["from"], row["to"]))
        print("   agreed for %d of %d messages (~%d%% of the request)"
              % (row["agreed_for"], row["messages_before"], row["share"]))
        difference = row["first_difference"]
        if difference:
            before, after = difference["before"], difference["after"]
            print("   first change at message %d, role %s" % (before["i"], before["role"]))
            print("      was: %d chars, %d images, %d reasoning, %d tool chars"
                  % (before["chars"], before["images"], before["reasoning"], before["tools"]))
            if after:
                print("      now: %d chars, %d images, %d reasoning, %d tool chars"
                      % (after["chars"], after["images"], after["reasoning"], after["tools"]))
            else:
                print("      now: the message is gone")
        print()
    if len(clean) == len(report):
        print("Every request only appended to the one before it, which is what keeps")
        print("the processed prompt. A lost cache with traces like these is the")
        print("server's doing, not the conversation's.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
