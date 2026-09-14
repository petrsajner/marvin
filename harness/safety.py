"""Action-risk classification and autonomy policies.

Supervised mode requires confirmation for every WRITE action. Semi mode confirms the first WRITE action in a task. Auto mode runs without confirmation; the pyautogui failsafe remains enabled."""
from __future__ import annotations

from enum import Enum


class Risk(str, Enum):
    SAFE = "safe"      # Read, list or capture a screenshot without modifying state.
    WRITE = "write"    # Modify files, the system or a graphical application.


class SafetyPolicy:
    def __init__(self, autonomy: str = "supervised", max_steps: int = 0, semi_max_steps: int = 0):
        if autonomy not in ("supervised", "semi", "auto"):
            raise ValueError(f"Unknown autonomy mode: {autonomy}")
        self.autonomy = autonomy
        self.max_steps = max_steps
        self.semi_max_steps = semi_max_steps
        self._confirmed_this_task = False  # Confirmation state for semi-autonomous mode.

    # ------------------------------------------------------------------
    def new_task(self) -> None:
        """Reset the policy at the start of each user task."""
        self._confirmed_this_task = False

    def needs_confirmation(self, risk: Risk) -> bool:
        if risk == Risk.SAFE:
            return False
        if self.autonomy == "supervised":
            return True
        if self.autonomy == "semi":
            return not self._confirmed_this_task
        return False  # auto

    def mark_confirmed(self) -> None:
        self._confirmed_this_task = True

    def step_limit(self) -> int | None:
        value = self.semi_max_steps if self.autonomy == "semi" else self.max_steps
        return value if value > 0 else None

    def __repr__(self) -> str:  # pragma: no cover
        limit = self.step_limit()
        return f"SafetyPolicy(autonomy={self.autonomy!r}, max={limit or 'unlimited'})"
