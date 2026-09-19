"""Record what each request looked like, so a lost prompt cache can be explained.

Reusing a processed prompt is the difference between a step costing half a second
and costing a minute, and when reuse breaks the only honest way to find out why is
to compare the request that broke with the one before it. The conversation on disk
is not enough: it shows the final state, so anything rewritten in place looks as
if it was always that way.

This writes a fingerprint per request - one line per message, with its role, size
and a hash of exactly what was sent - and keeps the last few dozen. Nothing of the
content is stored, so a trace can be read without reading the conversation.
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

KEEP = 40                    # A few dozen steps is enough to see a pattern.


def _digest(value) -> str:
    if isinstance(value, str):
        payload = value.encode("utf-8", "replace")
    else:
        payload = json.dumps(value, ensure_ascii=False, sort_keys=True).encode()
    return hashlib.sha1(payload).hexdigest()[:10]


def fingerprint(messages: list[dict]) -> list[dict]:
    """One entry per message: what it is, how big, and exactly which bytes."""
    entries = []
    for index, message in enumerate(messages):
        content = message.get("content")
        images = 0
        if isinstance(content, list):
            images = sum(1 for part in content
                         if isinstance(part, dict) and part.get("type") == "image_url")
            size = sum(len(str(part.get("text", ""))) for part in content
                       if isinstance(part, dict) and part.get("type") == "text")
        else:
            size = len(str(content or ""))
        entries.append({
            "i": index,
            "role": message.get("role", "?"),
            "chars": size,
            "images": images,
            "reasoning": len(str(message.get("reasoning_content") or "")),
            "tools": len(json.dumps(message.get("tool_calls") or [], ensure_ascii=False)),
            "sha": _digest(message),
        })
    return entries


def record(directory: Path, messages: list[dict], *, step: int | None = None) -> None:
    """Append a request fingerprint, keeping only the most recent ones."""
    try:
        directory.mkdir(parents=True, exist_ok=True)
        # Nanoseconds: two requests in the same millisecond would otherwise share
        # a name, and the second would quietly replace the first.
        path = directory / ("request-%019d.json" % time.time_ns())
        path.write_text(json.dumps({
            "created": time.time(), "step": step,
            "messages": len(messages), "entries": fingerprint(messages),
        }, ensure_ascii=False), encoding="utf-8")
        traces = sorted(directory.glob("request-*.json"))
        for stale in traces[:max(0, len(traces) - KEEP)]:
            stale.unlink(missing_ok=True)
    except OSError:
        pass                 # Diagnostics must never be the thing that fails.


def compare(directory: Path) -> list[dict]:
    """Where consecutive requests stopped agreeing, which is what breaks reuse."""
    traces = []
    for path in sorted(Path(directory).glob("request-*.json")):
        try:
            traces.append((path.name, json.loads(path.read_text(encoding="utf-8"))))
        except (OSError, ValueError):
            continue
    report = []
    for (before_name, before), (after_name, after) in zip(traces, traces[1:]):
        first = before["entries"]
        second = after["entries"]
        index = 0
        while (index < len(first) and index < len(second)
               and first[index]["sha"] == second[index]["sha"]):
            index += 1
        kept = sum(item["chars"] + item["reasoning"] + item["tools"] for item in first[:index])
        total = sum(item["chars"] + item["reasoning"] + item["tools"] for item in first) or 1
        report.append({
            "from": before_name, "to": after_name,
            "messages_before": len(first), "messages_after": len(second),
            "agreed_for": index,
            "share": round(100 * kept / total),
            "appended_only": index >= len(first),
            "first_difference": (
                {"before": first[index], "after": second[index] if index < len(second) else None}
                if index < len(first) else None),
        })
    return report
