"""Single source of truth for harness-generated message prefixes.

The harness writes synthetic user messages (task protocols, loop warnings,
recovery notes, dynamic context). They must never count as real user turns: not
in compression boundaries, not in the history index, not in semantic search,
not in exports. Every place that filters them imports this list.

Three modules kept their own copies and they had drifted: loop warnings were
missing from the session and history filters, so they were indexed and exported
as genuine user content and counted as user turns when choosing a compression
cut."""
from __future__ import annotations

INTERNAL_USER_PREFIXES = (
    "[TASK PROTOCOL",
    "[WRITING PROTOCOL",
    "[PLAN FIRST",
    "[PROGRESS UPDATE",
    "[FINAL SUMMARY",
    "[WRITING SUMMARY",
    "[The following image",
    "[Interrupted by user]",
    "[RESEARCH PLAN",
    "[DYNAMIC TASK CONTEXT",
    "[HISTORY RECOVERY",
    "[LOOP WARNING",
)
