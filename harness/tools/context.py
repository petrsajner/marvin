"""Tools for visible and pinned model context."""
from __future__ import annotations

import json
from pathlib import Path

from harness.safety import Risk
from harness.tools.base import AgentContext, Tool


class ContextStatusTool(Tool):
    name = "context_status"
    parallel_safe = True
    description = "Show what currently consumes model context, including pinned files and compression."
    parameters = {}

    def run(self, ctx: AgentContext) -> str:
        return json.dumps(ctx.session.context_breakdown(), ensure_ascii=False, indent=2)


class PinContextFileTool(Tool):
    name = "pin_context_file"
    description = "Keep one text file in model context on every subsequent request in this chat."
    parameters = {"path": {"type": "string"}}
    required = ["path"]

    def run(self, ctx: AgentContext, path: str) -> str:
        target = ctx.resolve(path)
        if not target.is_file():
            return f"ERROR: File not found: {target}"
        added = ctx.session.pin_context_file(target)
        return f"{'OK: pinned' if added else 'Already pinned'} {target}"


class UnpinContextFileTool(Tool):
    name = "unpin_context_file"
    description = "Remove one previously pinned file from persistent chat context."
    parameters = {"path": {"type": "string"}}
    required = ["path"]

    def run(self, ctx: AgentContext, path: str) -> str:
        target = ctx.resolve(path)
        removed = ctx.session.unpin_context_file(target)
        return f"{'OK: unpinned' if removed else 'Not pinned'} {target}"


class RepoOverviewTool(Tool):
    name = "repo_overview"
    parallel_safe = True
    description = "Return the automatically generated workspace map, key files, and Python symbols."
    parameters = {}

    def run(self, ctx: AgentContext) -> str:
        if not ctx.repo_index:
            return "ERROR: repo index unavailable"
        return ctx.repo_index.summary()


class ProjectInstructionsTool(Tool):
    name = "project_instructions"
    parallel_safe = True
    description = ("Show the automatically discovered AGENTS.md, QWEN.md, and CLAUDE.md "
                   "guidance applying to a project path, from project root to the nearest file.")
    parameters = {
        "path": {"type": "string", "description": "Optional project-relative file or directory"},
    }

    def run(self, ctx: AgentContext, path: str = ".") -> str:
        if not ctx.repo_index:
            return "ERROR: repo index unavailable"
        target = ctx.resolve(path)
        text = ctx.repo_index.instruction_context([target])
        return text or "No AGENTS.md, QWEN.md, or CLAUDE.md instructions found."


class ListProjectDocumentsTool(Tool):
    name = "list_project_documents"
    parallel_safe = True
    description = "List readable documents in the current project without exposing source code."
    parameters = {}

    def run(self, ctx: AgentContext) -> str:
        if not ctx.repo_index:
            return "ERROR: project library unavailable"
        return ctx.repo_index.document_catalog()


class ReadProjectDocumentTool(Tool):
    name = "read_project_document"
    description = "Read a project document (text, Markdown, PDF, DOCX, JSON, YAML, or CSV)."
    parameters = {
        "path": {"type": "string", "description": "Project-relative document path"},
        "max_chars": {"type": "integer", "description": "Maximum returned characters"},
    }
    required = ["path"]

    def run(self, ctx: AgentContext, path: str, max_chars: int = 50_000) -> str:
        if not ctx.repo_index:
            return "ERROR: project library unavailable"
        try:
            source, text = ctx.repo_index.read_document(path, max_chars=max(100, int(max_chars)))
        except (OSError, ValueError, ImportError) as exc:
            return f"ERROR: cannot read project document: {exc}"
        if getattr(ctx, "research", None):
            ctx.research.record_source(
                source.as_uri(), source.name, text,
                content_type=f"local/{source.suffix.lower().lstrip('.') or 'text'}",
            )
        return f"{source}\n\n{text}"


def detect_project_check(workspace: Path) -> tuple[str, str] | None:
    workspace = workspace.resolve()
    from harness.project_profile import ProjectProfile, project_python
    python = project_python(workspace)
    selected = ProjectProfile(workspace, python).select()
    return (selected.shell, selected.command) if selected else None


class ProjectValidationProfileTool(Tool):
    name = "project_validation_profile"
    parallel_safe = True
    description = ("List detected or project-configured test, lint, typecheck, and build commands. "
                   "Use the returned id with start_project_check.")
    parameters = {}

    def run(self, ctx: AgentContext) -> str:
        if ctx.project_workspace is None:
            return "ERROR: no project selected"
        from harness.project_profile import ProjectProfile, project_python
        python = project_python(ctx.workspace)
        return ProjectProfile(ctx.workspace, python).describe()


class StartProjectCheckTool(Tool):
    name = "start_project_check"
    description = ("Detect and start the project's primary automated test/check command in the "
                   "background. Poll the returned process_id until it finishes.")
    risk = Risk.WRITE

    parameters = {
        "check": {"type": "string", "description": "Check id/kind, or 'primary' (default)"},
        "timeout": {"type": "integer", "description": "Optional timeout override"},
    }

    def run(self, ctx: AgentContext, timeout: int | None = None,
            check: str = "primary") -> str:
        if ctx.project_workspace is None:
            return "ERROR: no project selected"
        from harness.project_profile import ProjectProfile, project_python
        python = project_python(ctx.workspace)
        selected = ProjectProfile(ctx.workspace, python).select(check)
        if selected is None:
            return "ERROR: no supported project test command detected"
        shell, command = selected.shell, selected.command
        effective_timeout = max(1, int(timeout if timeout is not None else selected.timeout))
        try:
            item = ctx.processes.start(command, shell, ctx.workspace, effective_timeout)
            if ctx.task_plan:
                ctx.task_plan.track_validation_process(
                    item.id, f"{selected.label}: {command}")
            return json.dumps({"process_id": item.id, "status": "running",
                               "check": selected.id, "command": command}, ensure_ascii=False)
        except OSError as exc:
            return f"ERROR: cannot start project check: {exc}"


class ManageContextTool(Tool):
    name = "manage_context"
    parallel_safe = False
    description = (
        "Inspect context usage or pin/unpin a text file in persistent chat context. "
        "Actions: 'status', 'pin' (requires path), 'unpin' (requires path)."
    )
    parameters = {
        "action": {"type": "string", "enum": ["status", "pin", "unpin"]},
        "path": {"type": "string", "description": "File path (for pin/unpin)"},
    }
    required = ["action"]

    def run(self, ctx: AgentContext, action: str, path: str = "") -> str:
        act = str(action or "").strip().lower()
        if act == "status":
            return ContextStatusTool().run(ctx)
        if act == "pin":
            if not path:
                return "ERROR: manage_context(action='pin') requires 'path'"
            return PinContextFileTool().run(ctx, path=path)
        if act == "unpin":
            if not path:
                return "ERROR: manage_context(action='unpin') requires 'path'"
            return UnpinContextFileTool().run(ctx, path=path)
        return f"ERROR: Unknown manage_context action: {action!r}"


class ProjectInfoTool(Tool):
    name = "project_info"
    parallel_safe = True
    description = (
        "Inspect project metadata: 'overview' (workspace map & symbols), "
        "'instructions' (hierarchical AGENTS.md/QWEN.md/CLAUDE.md for path), "
        "or 'checks' (detected test/lint/build commands for start_project_check)."
    )
    parameters = {
        "kind": {"type": "string", "enum": ["overview", "instructions", "checks"]},
        "path": {"type": "string", "description": "Optional relative path (for kind='instructions')"},
    }
    required = ["kind"]

    def run(self, ctx: AgentContext, kind: str, path: str = ".") -> str:
        k = str(kind or "").strip().lower()
        if k == "overview":
            return RepoOverviewTool().run(ctx)
        if k == "instructions":
            return ProjectInstructionsTool().run(ctx, path=path)
        if k == "checks":
            return ProjectValidationProfileTool().run(ctx)
        return f"ERROR: Unknown project_info kind: {kind!r}"


def register_context_tools(registry, *, include_project_docs: bool = True) -> None:
    registry.register(ManageContextTool())
    registry.register_alias("context_status", ContextStatusTool())
    registry.register_alias("pin_context_file", PinContextFileTool())
    registry.register_alias("unpin_context_file", UnpinContextFileTool())
    if include_project_docs:
        registry.register(ListProjectDocumentsTool())
        registry.register(ReadProjectDocumentTool())
    else:
        registry.register_alias("list_project_documents", ListProjectDocumentsTool())
        registry.register_alias("read_project_document", ReadProjectDocumentTool())


def register_coding_context_tools(registry) -> None:
    registry.register(ProjectInfoTool())
    registry.register(StartProjectCheckTool())
    registry.register_alias("repo_overview", RepoOverviewTool())
    registry.register_alias("project_instructions", ProjectInstructionsTool())
    registry.register_alias("project_validation_profile", ProjectValidationProfileTool())
