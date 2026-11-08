"""Next-step suggestions for the composer.

The model keeps a running guess of the user's next instruction and ends its replies
with it as <next_step>...</next_step>. The harness removes the tag from everything it
shows or keeps, remembers the latest guess per chat, and at the end of a task falls
back to the task's own state (a failing check, an unfinished plan step, the summary's
next steps) when the final reply offers none. No separate model request is made: the
single local model is never kept busy for a suggestion."""
from __future__ import annotations

import re

from harness.i18n import t

OPEN = "<next_step>"
CLOSE = "</next_step>"
MAX_CHARS = 300

_BLOCK_RE = re.compile(r"[ \t]*<next_step>(.*?)(?:</next_step>|\Z)[ \t]*\n?", re.S | re.I)
_NONE_RE = re.compile(r"^(?:none|n/?a|-+|\.+)$", re.I)
# The task protocol's "📋 Next steps" section, in whatever language the heading uses.
_NEXT_HEADING_RE = re.compile(r"^[ \t>#*_]*📋[^\n:]*:?[ \t*_]*(?P<inline>[^\n]*)$", re.M)
_BULLET_RE = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s+(?P<text>.+?)\s*$")


def clean_suggestion(text: str) -> str:
    """One line of plain text, or '' when the model offered nothing usable."""
    value = " ".join(str(text or "").split())
    value = value.strip().strip("\"'`“”„«»").strip()
    # Emphasis and code marks go; underscores stay, they belong to names like __init__.py.
    value = re.sub(r"[*`]+", "", value).strip()
    if not value or _NONE_RE.match(value):
        return ""
    if len(value) > MAX_CHARS:
        value = value[:MAX_CHARS].rsplit(" ", 1)[0].rstrip(",;:") + "…"
    return value


def split_next_step(text: str) -> tuple[str, str]:
    """Reply text without its next-step tags, and the last usable suggestion ('' when none)."""
    if not text or OPEN[:-1] not in text.lower():
        return text or "", ""
    found: list[str] = []

    def drop(match: re.Match) -> str:
        found.append(match.group(1))
        # A tag in the middle of a line leaves one space between the words around it.
        whole = match.group(0)
        before = text[match.start() - 1] if match.start() else ""
        after = text[match.end()] if match.end() < len(text) else ""
        spaced = whole[:1].isspace() or whole[-1:].isspace()
        return " " if spaced and before.strip() and after.strip() else ""

    clean = _BLOCK_RE.sub(drop, text).rstrip()
    suggestion = next((value for value in map(clean_suggestion, reversed(found)) if value), "")
    return clean, suggestion


def _partial_suffix(text: str, tag: str) -> int:
    """Length of the longest end of text that could still grow into tag."""
    lowered = text.lower()
    for size in range(min(len(tag) - 1, len(text)), 0, -1):
        if lowered.endswith(tag[:size]):
            return size
    return 0


class NextStepStreamFilter:
    """Hide next-step tags from streamed reply text, including tags split across chunks."""

    def __init__(self) -> None:
        self.buffer = ""
        self.inside = False

    def feed(self, chunk: str) -> str:
        self.buffer += chunk or ""
        out: list[str] = []
        while self.buffer:
            lowered = self.buffer.lower()
            if self.inside:
                end = lowered.find(CLOSE)
                if end < 0:
                    keep = _partial_suffix(self.buffer, CLOSE)
                    self.buffer = self.buffer[len(self.buffer) - keep:] if keep else ""
                    break
                self.buffer = self.buffer[end + len(CLOSE):]
                self.inside = False
                continue
            start = lowered.find(OPEN)
            if start >= 0:
                out.append(self.buffer[:start])
                self.buffer = self.buffer[start + len(OPEN):]
                self.inside = True
                continue
            keep = _partial_suffix(self.buffer, OPEN)
            out.append(self.buffer[:len(self.buffer) - keep])
            self.buffer = self.buffer[len(self.buffer) - keep:]
            break
        return "".join(out)

    def flush(self) -> str:
        """What was held back as a possible tag start; an unclosed tag stays hidden."""
        text = "" if self.inside else self.buffer
        self.buffer = ""
        self.inside = False
        return text


def summary_next_step(content: str) -> str:
    """The first item of the final summary's '📋 Next steps' section."""
    heading = None
    for heading in _NEXT_HEADING_RE.finditer(content or ""):
        pass
    if heading is None:
        return ""
    inline = clean_suggestion(heading.group("inline"))
    if inline:
        return inline
    for line in content[heading.end():].splitlines():
        if not line.strip():
            continue
        item = _BULLET_RE.match(line)
        return clean_suggestion(item.group("text")) if item else ""
    return ""


def derive_next_step(plan: dict | None, checks: list[dict] | None, content: str) -> str:
    """A next step from the task's own state, for a final reply that offered none."""
    for row in checks or []:
        if not row.get("ok") and str(row.get("what") or "").strip():
            return clean_suggestion(t("Fix the failing check: {what}", what=row["what"]))
    plan = plan or {}
    validations = plan.get("validations") or []
    if validations and validations[-1].get("status") == "failed" and str(validations[-1].get("label") or "").strip():
        return clean_suggestion(t("Fix the failing check: {what}", what=validations[-1]["label"]))
    unfinished = next((step for step in plan.get("steps") or []
                       if step.get("status") in ("in_progress", "pending") and str(step.get("text") or "").strip()),
                      None)
    if unfinished:
        return clean_suggestion(t("Continue with: {step}", step=unfinished["text"]))
    return summary_next_step(content)
