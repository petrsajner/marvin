"""Context management: token estimates, summarization, compression and handoff."""
from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

SUMMARIZE_PROMPT = """You are creating a technical handoff summary of a work session between a user and a coding agent.
Summarize the conversation below into a COMPACT markdown summary (max ~500 words) with these sections:
1. **Goal** - what the user is working on (project, task)
2. **Done** - completed steps, created/modified files (full paths), key commands and their outcomes
3. **Decisions & context** - important decisions, constraints, user preferences
4. **Pending** - what remains to be done, next intended steps
5. **Key facts** - versions, error messages, paths, anything needed to continue seamlessly

Be precise with file paths and technical details. Do not include pleasantries.

CONVERSATION TRANSCRIPT:
"""

# A tool-trained model sometimes answers a tool-less request with call markup;
# seen as a handoff "summary" that was just a read_file invocation
# (2026-09-22). The tags are matched by regex so this source file never
# contains one literally.
_TOOL_CALL_RE = re.compile(r"<(?:tool_call\b|function=|/function>)")

_SUMMARIZE_SYSTEM = ("Summarize faithfully; preserve requirements and references. "
                     "You have no tools and cannot call any.")
_CLOSING_NOTE = (
    "\n\nEND OF TRANSCRIPT. Write the continuation summary now, following the "
    "instructions above. Do not answer the messages, continue the transcript, "
    "or quote it - summarize it.")
_NO_TOOLS_NOTE = (
    "\n\nIMPORTANT: You have no tools. Never answer with tool-call XML tags, "
    "do not quote or continue the transcript. Reply with the markdown summary "
    "text only, using the section headings from the instructions.")


def looks_like_tool_call(text: str) -> bool:
    """True when a 'summary' is really tool-call markup instead of prose."""
    return bool(_TOOL_CALL_RE.search(text or ""))


def _looks_degenerate(summary: str, source: str) -> str | None:
    """Why a "summary" cannot be used; None when it looks like a real one.

    The degenerations seen on tool-heavy transcripts: call markup, a quoted
    transcript line as the whole answer, or a two-word sign-off ("Done.")."""
    if not summary:
        return "produced no summary"
    if looks_like_tool_call(summary):
        return "answered with tool-call markup"
    if "[Message " in source and len(summary) < 400 and summary in source:
        # Only against conversation lines: the map-reduce merge step re-reads
        # earlier summaries, where repeating one is legitimate.
        return "quoted a transcript line instead of summarizing"
    if len(summary) < 40:
        return "is too short to be a summary"
    return None


def render_messages_text(messages: list[dict], max_chars: int = 60_000) -> str:
    """Render messages as compact summarization text, with notes for images."""
    lines: list[str] = []
    for m in messages:
        role = m.get("role", "?").upper()
        content = m.get("content") or ""
        if not isinstance(content, str):
            content = " ".join(str(p.get("text", "")) for p in content if isinstance(p, dict))
        if m.get("tool_calls"):
            calls = ", ".join(
                f"{c['function']['name']}({(c['function'].get('arguments') or '')[:120]})"
                for c in m["tool_calls"])
            content = (content + f"\n[tool calls: {calls}]").strip()
        if m.get("images"):
            content += f" [+{len(m['images'])} image(s) attached]"
        lines.append(f"{role}: {content}")
    transcript = "\n\n".join(lines)
    if len(transcript) <= max_chars:
        return transcript
    marker = "\n\n[...older transcript middle truncated...]\n\n"
    head_chars = max_chars // 4
    tail_chars = max_chars - head_chars - len(marker)
    return transcript[:head_chars] + marker + transcript[-tail_chars:]


def summarize_messages(llm: Any, messages: list[dict], should_stop=None) -> str:
    """Summarize every part, retaining mode-specific facts and traceable message IDs."""
    mode = llm.cfg.data.get("work_mode", "discussion")
    focus = {
        "discussion": "goals, decisions, perspectives, unresolved questions and user preferences",
        "research": "claims, exact source IDs and URLs, contradictions, uncertainty and unanswered questions",
        "writing": "outline, voice, style, characters, chronology, continuity and approved wording",
        "development": "architecture, file paths, changes, test evidence, errors and next steps",
        "computer": "application state, completed actions, file paths and next steps",
    }.get(mode, "goals, decisions, facts and next steps")
    from harness.session import Session
    prompt = (f"Create a continuation summary for {mode}. Preserve {focus}. "
              "Structure it with these sections: **Goal**, **Done**, "
              "**Decisions & context**, **Pending**, **Key facts** - skip one "
              "only if it is completely empty. "
              "Keep explicit user requirements and accepted decisions, including negative constraints. "
              "Distinguish completed work from proposals. Preserve message references and source links "
              "so missing detail can be retrieved with read_chat_history. Be concise without losing "
              "relevant facts. Reply in the conversation language.\n\n")
    lines = []
    for i, message in enumerate(messages):
        body = message.get("content")
        if (message.get("role") == "user" and isinstance(body, str)
                and body.startswith(Session.INTERNAL_USER_PREFIXES)):
            continue  # harness protocols address the worker, not the summarizer
        reference = message.get("id", str(i))
        content = render_messages_text([message], max_chars=2**63 - 1)
        lines.append(f"[Message {reference}]\n{content}")
    transcript = "\n\n".join(lines)
    # A token budget turned into a character budget. Measured, not assumed: at the
    # old 3.6 this asked for 12% more text than 45% of the context can hold.
    budget = max(8000, int(llm.cfg.context_size() * 0.45 * Session.CHARS_PER_TOKEN))
    cache = llm.cfg.path("paths.runtime_dir") / "summary-cache"
    cache.mkdir(parents=True, exist_ok=True)

    def summarize(text):
        if should_stop and should_stop():
            raise RuntimeError("Summarization stopped by the user")
        key = hashlib.sha256((mode + prompt + text).encode()).hexdigest()
        path = cache / (key + ".md")
        if path.is_file():
            cached = path.read_text(encoding="utf-8")
            if not _looks_degenerate(cached, text):
                return cached
            # A bad cached answer from before validation: regenerate and
            # overwrite it below.
        request = prompt + text + _CLOSING_NOTE
        summary = ""
        reason = "produced no summary"
        for attempt in range(2):
            res = llm.stream([
                {"role": "system", "content": _SUMMARIZE_SYSTEM},
                {"role": "user", "content": request + (_NO_TOOLS_NOTE if attempt else "")}],
                sampling=llm.cfg.sampling(False), thinking=False, should_stop=should_stop)
            if res.stopped:
                raise RuntimeError("Summarization stopped by the user")
            summary = (res.content or "").strip()
            reason = _looks_degenerate(summary, text) or ""
            if not reason:
                break
        if reason:
            # A visible failure beats a continuation chat of nonsense.
            raise RuntimeError(f"The summarizer {reason}; nothing was saved")
        from harness.changes import atomic_write_text
        atomic_write_text(path, summary)
        return summary

    while len(transcript) > budget:
        merged = "\n\n".join(summarize(transcript[i:i + budget])
                              for i in range(0, len(transcript), budget))
        if len(merged) >= len(transcript):
            raise RuntimeError("The summary did not reduce the context; original sources remain saved")
        transcript = merged
    return summarize(transcript)
