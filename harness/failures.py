"""Plain-language next steps for failures the user can act on.

A failed task used to reach the user as a toast that faded, leaving someone who
does not program with an error string and nowhere to go. Known failures get a
concrete step here; everything else is handed to the model, which can usually
work out what happened. Hints are English source strings and are translated in
the interface like every other message.

See docs/design/failure-advice.md."""
from __future__ import annotations

# Matched against the failure text in order, so put the specific ones first.
HINTS: tuple[tuple[str, str], ...] = (
    ("no module named",
     "The project has no environment of its own, so the packages it needs are "
     "missing. Let the agent set one up."),
    ("selected model has no vision",
     "This model cannot see pictures. Switch to a model marked as vision-capable "
     "and send the attachment again."),
    ("model server is not ready",
     "The model did not start. Check the model and the memory budget in Settings, "
     "then start it again."),
    ("no model profile fits",
     "No model fits the current memory budget. Raise the budget in Settings or "
     "choose a smaller model."),
    ("model connection stalled",
     "The model stopped responding. Restarting it in Settings usually clears this."),
    ("project folder is unavailable",
     "The project folder was moved or removed. Attach it again, or pick another "
     "project."),
    ("ram_pressure",
     "The machine ran out of memory for this model. A smaller context or a smaller "
     "model will finish the task."),
    ("vram_pressure",
     "The graphics card ran out of memory. A smaller context or a smaller model "
     "will finish the task."),
    ("no project checks detected",
     "This project has no tests Marvin can recognise. The agent can add them, or "
     "you can name your own in .qwen/project.yaml."),
)


def advise(error: str) -> str:
    """The known next step for a failure, or an empty string when there is none."""
    text = (error or "").lower()
    for fragment, hint in HINTS:
        if fragment in text:
            return hint
    return ""


def failure_notice(error: str, run_id: str, created: float) -> dict:
    """The durable notice a failed task leaves behind in the conversation."""
    return {"kind": "failure", "text": (error or "").strip()[:2000],
            "hint": advise(error), "run_id": run_id, "created": created}
