"""One search across everything the owner has: chats, files, memory, decisions.

Each of these was already searchable, and each from a different place. Chats had
the box above the conversation list, project files had a model tool, memory had a
settings panel you read by eye, decisions had a panel of their own. Someone who
remembers a sentence but not where they wrote it had to guess which of the four
to look in, which is the same obstacle as not knowing a tool exists - approached
from the other side.

Every result says what it is and where it leads, so the interface can open the
right thing rather than describing it.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from harness.config import Config
from harness.file_index import TEXT_EXTENSIONS, sanitize_query

PER_SOURCE = 8              # No single source may drown out the others.
SNIPPET_CHARS = 160


def _snippet(text: str, words: list[str]) -> str:
    """The part of a document worth showing: around the first word that matched."""
    lowered = text.lower()
    at = min((lowered.find(word) for word in words if word in lowered), default=-1)
    if at < 0:
        return " ".join(text.split())[:SNIPPET_CHARS]
    start = max(0, at - SNIPPET_CHARS // 3)
    piece = " ".join(text[start:start + SNIPPET_CHARS].split())
    return ("…" if start else "") + piece + ("…" if start + SNIPPET_CHARS < len(text) else "")


def _chats(cfg: Config, query: str) -> list[dict]:
    from harness.history_index import HistoryIndex
    found = []
    for row in HistoryIndex(cfg.path("paths.sessions_dir")).search(query, limit=PER_SOURCE * 2):
        found.append({
            "kind": "chat",
            "title": row.get("title") or "Untitled conversation",
            "snippet": " ".join(str(row.get("snippet") or "").split()),
            "open": {"what": "chat", "session_id": row.get("id")},
            "workspace": row.get("workspace") or "",
        })
        if len(found) >= PER_SOURCE:
            break
    return found


def _files(cfg: Config, workspace: Path | None, query: str) -> list[dict]:
    if not workspace or not workspace.is_dir():
        return []
    from harness.file_index import search_index
    clean = sanitize_query(query)
    if not clean:
        return []
    key = hashlib.sha256(str(workspace.resolve()).encode()).hexdigest()[:24]
    database = cfg.path("paths.runtime_dir") / "indexes" / f"{key}.sqlite3"
    try:
        hits, _ = search_index(workspace, database, clean, TEXT_EXTENSIONS, PER_SOURCE)
    except Exception:
        return []                       # A search must never be the thing that fails.
    return [{
        "kind": "file",
        "title": relative,
        "snippet": " ".join(str(snippet).replace("**", "").split()),
        "open": {"what": "file", "path": str((workspace / relative).resolve())},
    } for relative, snippet, _score in hits if not _harness_state(relative)]


# The project's own bookkeeping is searched as memory and decisions, with entries
# that open the right panel. Listing the files again would be the same hit twice.
STATE_FILES = ("QWEN_MEMORY.md",)
STATE_DIRS = (".qwen", ".qwen-skills")


def _harness_state(relative: str) -> bool:
    parts = Path(relative).parts
    return bool(parts) and (parts[0] in STATE_DIRS or parts[-1] in STATE_FILES)


def _memory(cfg: Config, workspace: Path | None, work_mode: str | None,
            words: list[str]) -> list[dict]:
    from harness.memory import MemoryStore
    store = MemoryStore(cfg, workspace, work_mode)
    found = []
    for scope in ("global", "mode", "project"):
        try:
            text = store.read(scope)
        except Exception:
            continue
        if not text:
            continue
        for line in text.splitlines():
            stripped = line.strip(" -\t")
            if stripped and all(word in line.lower() for word in words):
                found.append({
                    "kind": "memory",
                    "title": stripped[:90],
                    "snippet": scope,
                    "open": {"what": "memory", "scope": scope},
                })
                if len(found) >= PER_SOURCE:
                    return found
    return found


def _decisions(workspace: Path | None, words: list[str]) -> list[dict]:
    if not workspace:
        return []
    from harness.decisions import DecisionStore
    found = []
    try:
        items = DecisionStore(workspace).list()
    except Exception:
        return []
    for item in items:
        text = str(item.get("text") or "")
        if all(word in text.lower() for word in words):
            found.append({
                "kind": "decision",
                "title": _snippet(text, words),
                "snippet": str(item.get("status") or ""),
                "open": {"what": "decisions"},
            })
            if len(found) >= PER_SOURCE:
                break
    return found


def find(cfg: Config, query: str, *, workspace: Path | None = None,
         work_mode: str | None = None) -> dict:
    """Search every place the owner keeps things, and say where each hit lives."""
    query = (query or "").strip()
    words = [word.lower() for word in sanitize_query(query).replace('"', "").split(" OR ") if word]
    if not query or not words:
        return {"query": query, "groups": [], "total": 0}
    groups = [
        {"kind": "chat", "items": _chats(cfg, query)},
        {"kind": "file", "items": _files(cfg, workspace, query)},
        {"kind": "memory", "items": _memory(cfg, workspace, work_mode, words)},
        {"kind": "decision", "items": _decisions(workspace, words)},
    ]
    groups = [group for group in groups if group["items"]]
    return {"query": query, "groups": groups,
            "total": sum(len(group["items"]) for group in groups)}
