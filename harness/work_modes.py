"""Work modes and their capability mappings.

Labels use English by default and are translated by the optional UI localization."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class WorkModeSpec:
    id: str
    label: str
    agent_mode: str
    repo_snapshot: bool = False
    task_protocol: bool = False


WORK_MODES = {
    "discussion": WorkModeSpec("discussion", "Discussion", "chat"),
    "research": WorkModeSpec("research", "Research", "chat"),
    "writing": WorkModeSpec("writing", "Writing", "agent", task_protocol=True),
    "development": WorkModeSpec(
        "development", "Development", "agent", repo_snapshot=True, task_protocol=True),
    "computer": WorkModeSpec("computer", "Computer", "computer", task_protocol=True),
}


def normalize_work_mode(value: str | None, legacy_mode: str | None = None) -> str:
    if value in WORK_MODES:
        return str(value)
    return {"chat": "discussion", "computer": "computer"}.get(
        str(legacy_mode), "development")


def mode_choices() -> list[tuple[str, str]]:
    return [(spec.label, spec.id) for spec in WORK_MODES.values()]
