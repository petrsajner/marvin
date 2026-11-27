"""Tools for a visible, persistent operational task plan."""
from __future__ import annotations

import json

from harness.tools.base import AgentContext, Tool


class TaskPlanStatusTool(Tool):
    name = "task_plan_status"
    parallel_safe = True
    description = "Read the current persistent task plan, step states, and validation status."
    parameters = {}

    def run(self, ctx: AgentContext) -> str:
        if not ctx.task_plan:
            return "ERROR: task plan unavailable"
        return json.dumps(ctx.task_plan.load(), ensure_ascii=False, indent=2)


class SetTaskPlanTool(Tool):
    name = "set_task_plan"
    description = ("Create or replace the operational plan for a multi-step task. Keep steps "
                   "concrete and outcome-oriented; the first step becomes in_progress.")
    parameters = {
        "goal": {"type": "string", "description": "Concise task goal"},
        "steps": {
            "type": "array", "items": {"type": "string"},
            "description": "Ordered implementation and verification steps",
        },
    }
    required = ["goal", "steps"]

    def run(self, ctx: AgentContext, goal: str, steps: list[str]) -> str:
        if not ctx.task_plan:
            return "ERROR: task plan unavailable"
        return json.dumps(ctx.task_plan.set_plan(goal, steps), ensure_ascii=False, indent=2)


class UpdateTaskStepTool(Tool):
    name = "update_task_step"
    description = ("Update one task-plan step after meaningful progress. Completing a step "
                   "automatically starts the next pending step.")
    parameters = {
        "step_id": {"type": "integer"},
        "status": {
            "type": "string",
            "enum": ["pending", "in_progress", "completed", "skipped"],
        },
        "note": {"type": "string", "description": "Optional result or reason"},
    }
    required = ["step_id", "status"]

    def run(self, ctx: AgentContext, step_id: int, status: str,
            note: str = "") -> str:
        if not ctx.task_plan:
            return "ERROR: task plan unavailable"
        return json.dumps(
            ctx.task_plan.update_step(step_id, status, note),
            ensure_ascii=False, indent=2)


class RecordTaskValidationTool(Tool):
    name = "record_task_validation"
    description = ("Record a validation result that was inspected outside the automatic project "
                   "check tools, including a concise result summary.")
    parameters = {
        "label": {"type": "string"},
        "status": {"type": "string", "enum": ["passed", "failed", "skipped"]},
        "summary": {"type": "string"},
    }
    required = ["label", "status"]

    def run(self, ctx: AgentContext, label: str, status: str,
            summary: str = "") -> str:
        if not ctx.task_plan:
            return "ERROR: task plan unavailable"
        ctx.task_plan.record_validation(label, status, summary)
        return "OK: validation recorded"


class TaskPlanTool(Tool):
    name = "task_plan"
    parallel_safe = False
    description = (
        "Manage the visible operational task plan. "
        "Actions: 'status' (read plan), 'set' (create/replace plan with goal + steps), "
        "'update_step' (step_id + status + optional note), "
        "'record_validation' (label + status passed|failed|skipped + summary)."
    )
    parameters = {
        "action": {
            "type": "string",
            "enum": ["status", "set", "update_step", "record_validation"],
            "description": "Task plan action",
        },
        "goal": {"type": "string", "description": "Concise task goal (for action='set')"},
        "steps": {
            "type": "array", "items": {"type": "string"},
            "description": "Ordered steps (for action='set')",
        },
        "step_id": {"type": "integer", "description": "Step number (for action='update_step')"},
        "status": {
            "type": "string",
            "enum": ["pending", "in_progress", "completed", "skipped", "passed", "failed"],
            "description": "Step status (for update_step) or check status (for record_validation)",
        },
        "note": {"type": "string", "description": "Optional progress note (for update_step)"},
        "label": {"type": "string", "description": "Validation check label (for record_validation)"},
        "summary": {"type": "string", "description": "Validation summary (for record_validation)"},
    }
    required = ["action"]

    def run(self, ctx: AgentContext, action: str, goal: str | None = None,
            steps: list[str] | None = None, step_id: int | None = None,
            status: str | None = None, note: str = "",
            label: str | None = None, summary: str = "") -> str:
        act = str(action or "").strip().lower()
        if act == "status":
            return TaskPlanStatusTool().run(ctx)
        if act == "set":
            if not goal or not steps:
                return "ERROR: task_plan(action='set') requires 'goal' and 'steps'"
            return SetTaskPlanTool().run(ctx, goal=goal, steps=steps)
        if act == "update_step":
            if step_id is None or not status:
                return "ERROR: task_plan(action='update_step') requires 'step_id' and 'status'"
            return UpdateTaskStepTool().run(ctx, step_id=step_id, status=status, note=note)
        if act == "record_validation":
            if not label or not status:
                return "ERROR: task_plan(action='record_validation') requires 'label' and 'status'"
            return RecordTaskValidationTool().run(ctx, label=label, status=status, summary=summary)
        return f"ERROR: Unknown task_plan action: {action!r}"


def register_task_tools(registry) -> None:
    registry.register(TaskPlanTool())
    for legacy in (
        TaskPlanStatusTool(),
        SetTaskPlanTool(),
        UpdateTaskStepTool(),
        RecordTaskValidationTool(),
    ):
        registry.register_alias(legacy.name, legacy)
