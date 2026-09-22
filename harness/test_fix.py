"""Test-and-fix protocol: run the app, find problems, fix them, verify the fixes.

One bounded sequential loop, driven by the agent through the existing isolated
browser and background-process tools - the permanent non-goal is parallel
agents, not iteration. This module holds the prompt and the machine-readable
report parsing; it registers no tools and touches no session state. See
docs/design/consumer-parity-review-2026-09-22.md (R7)."""
from __future__ import annotations

import re

MAX_ROUNDS = 3

TEST_FIX_PROMPT = (
    "[TEST AND FIX PROTOCOL] "
    "Test the app or page from this conversation, fix what is broken, and verify "
    "each fix. Target: {target}\n"
    "Work in at most {rounds} test rounds, then stop:\n"
    "(1) RUN IT - open it in your isolated browser (browser_open on the file, or "
    "start a small server first with start_command and open its URL); "
    "(2) CHECK IT - browser_screenshot, browser_console and browser_network, and "
    "click through the main controls (browser_click, browser_fill) the way a user "
    "would; "
    "(3) FIX what you found with file edits; "
    "(4) repeat from (2) to confirm each fix.\n"
    "Record every check result with record_task_validation as you go. Never delete "
    "or weaken the user's content to make a check pass. If something is still "
    "broken after {rounds} rounds, say so plainly - a truthful failure report is "
    "the right result. Finish with the structured summary (including its CHANGES "
    "block) and then one block under the exact heading 'TESTREPORT:' (keep this "
    "heading in English even when writing another language), one line per check as "
    "'- <what I checked> | ok' or '- <what I checked> | problem: <plain sentence>'."
)

REPORT_HEADING_RE = re.compile(r"(?im)^\s*TESTREPORT\s*:\s*$")
REPORT_LINE_RE = re.compile(
    r"^\s*[-*]\s*(?P<what>[^|]+?)\s*\|\s*(?P<status>ok|problem\s*:.+?)\s*$",
    re.IGNORECASE)


def build_test_fix_prompt(target: str = "") -> str:
    return TEST_FIX_PROMPT.format(
        target=(target.strip() or "the app built in this conversation")[:500],
        rounds=MAX_ROUNDS)


def split_test_report(text: str) -> tuple[str, list[dict]]:
    """Final answer text without its TESTREPORT block, plus check rows for the UI.

    The block is the last thing the protocol asks for, so it runs to the end of
    the answer. Rows survive only from well-formed '- what | status' lines."""
    kept = text or ""
    heading = REPORT_HEADING_RE.search(kept)
    if not heading:
        return kept, []
    rows: list[dict] = []
    for line in kept[heading.end():].splitlines():
        item = REPORT_LINE_RE.match(line)
        if not item:
            continue
        status = item.group("status").strip()
        ok = status.lower() == "ok"
        rows.append({
            "what": item.group("what").strip(),
            "ok": ok,
            "note": "" if ok else re.sub(r"(?i)^problem\s*:\s*", "", status),
        })
    if not rows:
        return kept, []
    return kept[:heading.start()].rstrip(), rows
