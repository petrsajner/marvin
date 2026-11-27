"""Tools for global, work-mode and project memory."""
from __future__ import annotations

from harness.safety import Risk
from harness.tools.base import AgentContext, Tool


class ReadMemoryTool(Tool):
    name = "read_memory"
    parallel_safe = True
    description = ("Read one full persistent memory layer. scope: 'global' = all work modes "
                   "and projects; 'mode' = the current work mode across projects; "
                   "'project' = the current project's facts. All active layers are already "
                   "included in the system prompt.")
    parameters = {
        "scope": {"type": "string", "enum": ["global", "mode", "project"],
                  "description": "Which memory to read"},
    }
    required = ["scope"]
    risk = Risk.SAFE

    def run(self, ctx: AgentContext, scope: str = "mode") -> str:
        from harness.memory import MemoryStore
        store = MemoryStore(ctx.cfg, ctx.project_workspace, ctx.work_mode)
        return store.read(scope) or "(empty)"


class SaveMemoryTool(Tool):
    name = "save_memory"
    description = ("Save a durable fact to persistent memory (one concise line). "
                   "scope 'project' = facts valid for this workspace; scope 'mode' = facts shared "
                   "by the current kind of work; scope 'global' = universal user facts and rules. "
                   "Use when the user asks to remember something, or when a fact is clearly worth "
                   "persisting for future sessions.")
    parameters = {
        "fact": {"type": "string", "description": "The fact to remember (one concise line)"},
        "scope": {"type": "string", "enum": ["global", "mode", "project"],
                  "description": "Which memory layer should own the fact"},
    }
    required = ["fact", "scope"]
    risk = Risk.SAFE  # Append only to the fixed memory path outside ordinary user files.

    def run(self, ctx: AgentContext, fact: str, scope: str = "mode") -> str:
        from harness.memory import MemoryStore
        store = MemoryStore(ctx.cfg, ctx.project_workspace, ctx.work_mode)
        return store.append(fact, scope)


class MemoryTool(Tool):
    name = "memory"
    parallel_safe = False
    description = (
        "Read or update persistent memory layers ('global' = all modes/projects, "
        "'mode' = current work mode across projects, 'project' = current workspace). "
        "Actions: 'save' (add one concise fact, deduplicated), 'replace' (update outdated fact "
        "matching old_text with fact), 'remove' (delete fact matching old_text), 'read' (show full layer)."
    )
    parameters = {
        "action": {
            "type": "string",
            "enum": ["save", "replace", "remove", "read"],
            "description": "Memory operation",
        },
        "scope": {
            "type": "string",
            "enum": ["global", "mode", "project"],
            "description": "Which memory layer owns this fact",
        },
        "fact": {"type": "string", "description": "Concise fact to save or replacement text"},
        "old_text": {"type": "string", "description": "Text identifying an existing fact (for replace/remove)"},
    }
    required = ["action", "scope"]
    risk = Risk.SAFE

    def run(self, ctx: AgentContext, action: str, scope: str = "mode",
            fact: str = "", old_text: str = "") -> str:
        from harness.memory import MemoryStore
        store = MemoryStore(ctx.cfg, ctx.project_workspace, ctx.work_mode)
        act = str(action or "").strip().lower()
        if act == "read":
            return store.read(scope) or "(empty)"
        if act == "save":
            return store.append(fact, scope)
        if act == "replace":
            return store.replace(old_text, fact, scope)
        if act == "remove":
            return store.remove(old_text or fact, scope)
        return f"ERROR: Unknown memory action: {action!r}"


def register_memory_tools(registry) -> None:
    registry.register(MemoryTool())
    registry.register_alias("read_memory", ReadMemoryTool())
    registry.register_alias("save_memory", SaveMemoryTool())
