"""Hybrid semantic search tool over project files and chat history."""
from __future__ import annotations

import time

from harness.tools.base import Risk, Tool, truncate
from harness.tools.search import TEXT_EXTENSIONS, _sanitize_fts_query

FIRST_INDEX_WAIT = 8.0


def _wait_for_results(probe, timeout: float = FIRST_INDEX_WAIT) -> None:
    """Give a freshly started background indexer a bounded head start.

    The first search in a workspace would otherwise race the worker and report
    nothing even though results are seconds away."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if probe():
            return
        time.sleep(0.25)


def _search_when_ready(search, is_complete) -> list[dict]:
    """Run search repeatedly until it yields hits or the index is complete."""
    hits: list[dict] = []

    def probe() -> bool:
        nonlocal hits
        hits = search()
        return bool(hits) or is_complete()

    _wait_for_results(probe)
    return hits


class SemanticSearchTool(Tool):
    name = "semantic_search"
    description = (
        "Search the project files and past conversations by meaning, not just keywords. "
        "Understands Czech and English, paraphrasing and concepts. Use it to find code by "
        "description, past discussions or decisions that keyword search would miss. "
        "Results are labeled [semantic] or [keyword]; combine with search_files when exact "
        "identifiers are known.")
    parameters = {
        "query": {"type": "string", "description": "What to look for, described in any language."},
        "scope": {"type": "string", "enum": ["files", "history", "both"],
                  "description": "Search project files, past chat history, or both (default both)."},
        "max_results": {"type": "integer", "description": "Maximum results per scope (default 8)."},
    }
    risk = Risk.SAFE
    parallel_safe = True
    required = ["query"]

    def run(self, ctx, query: str, scope: str = "both", max_results: int = 8) -> str:
        if not ctx.cfg.data.get("_semantic_search"):
            return ("Semantic search is disabled in this installation. Ask the user to enable it in "
                    "Settings > Model and device (it downloads a small CPU-only embedding model). "
                    "Use search_files and search_chat_history meanwhile.")
        from harness import embedding_server, semantic_index
        try:
            query_vec = embedding_server.embed_texts(ctx.cfg, [query])[0]
        except RuntimeError as exc:
            return f"Semantic search is unavailable: {exc}"
        limit = max(1, min(int(max_results or 8), 20))
        sections: list[str] = []
        if scope in ("files", "both") and ctx.workspace:
            sections.append(self._files_section(ctx, semantic_index, query, query_vec, limit))
        if scope in ("history", "both"):
            sections.append(self._history_section(ctx, semantic_index, query, query_vec, limit))
        if not sections:
            return "No workspace is selected; use scope='history' for conversations."
        return truncate("\n\n".join(sections), limit=30_000)

    def _files_section(self, ctx, semantic_index, query, query_vec, limit) -> str:
        import hashlib

        from harness.file_index import search_index
        from harness.semantic_index import SemanticFileIndex
        semantic_index.request_files_indexing(ctx.cfg, ctx.workspace)
        index = SemanticFileIndex(ctx.cfg, ctx.workspace)
        hits = _search_when_ready(lambda: index.search(query_vec, limit),
                                  lambda: index.progress()["pending"] == 0)
        key = hashlib.sha256(str(ctx.workspace.resolve()).encode()).hexdigest()[:24]
        fts_db = ctx.cfg.path("paths.runtime_dir") / "indexes" / f"{key}.sqlite3"
        keyword, file_count = search_index(ctx.workspace, fts_db,
                                           _sanitize_fts_query(query), TEXT_EXTENSIONS, limit)
        semantic_paths = {hit["path"] for hit in hits}
        lines = [f"Project files for '{query}':"]
        for hit in hits:
            excerpt = hit["text"][:220].replace("\n", " ")
            lines.append(f"- [semantic {hit['score']:.2f}] `{hit['path']}`: {excerpt}")
        for rel_path, snippet_text, _score in keyword:
            if rel_path in semantic_paths:
                continue
            lines.append(f"- [keyword] `{rel_path}`: {snippet_text.replace(chr(10), ' ')[:180]}")
        progress = index.progress()
        if progress["pending"]:
            lines.append(f"(semantic index still building in the background: {progress['done']} indexed, "
                         f"{progress['pending']} pending of {progress['total']} — repeat the search shortly "
                         "for fuller results)")
        if len(lines) == 1:
            return f"Project files for '{query}': no matches across {file_count} files."
        return "\n".join(lines)

    def _history_section(self, ctx, semantic_index, query, query_vec, limit) -> str:
        from harness.history_index import HistoryIndex
        from harness.semantic_index import SemanticHistoryIndex
        semantic_index.request_history_indexing(ctx.cfg)
        index = SemanticHistoryIndex(ctx.cfg)
        hits = _search_when_ready(lambda: index.search(query_vec, limit),
                                  lambda: index.pending_sessions() == 0)
        keyword = HistoryIndex(ctx.cfg.path("paths.sessions_dir")).search(query, limit=limit)
        semantic_sessions = {hit["session_id"] for hit in hits}
        lines = [f"Past conversations for '{query}':"]
        for hit in hits:
            excerpt = hit["text"][:200].replace("\n", " ")
            lines.append(f"- [semantic {hit['score']:.2f}] {hit['session_id']} ({hit['role']}): {excerpt}")
        for row in keyword:
            if row.get("id") in semantic_sessions:
                continue
            lines.append(f"- [keyword] {row.get('id')}: {row.get('snippet')}")
        pending = index.pending_sessions()
        if pending:
            lines.append(f"(history semantic index still building: {pending} sessions pending — "
                         "repeat the search shortly for fuller results)")
        if len(lines) == 1:
            return f"Past conversations for '{query}': no matches."
        return "\n".join(lines)


def register_semantic_tools(registry) -> None:
    registry.register(SemanticSearchTool())
