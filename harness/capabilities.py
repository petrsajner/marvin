"""User-facing capability catalogue.

A curated layer above the tool registry. The registry offers 33 to 75 tools
depending on the work mode and their descriptions are written for the model, down
to parameter names; neither is usable by someone who does not program. Entries
here are keyed on what a person can ask for, carry a ready example prompt, and
name the tools behind them only so tests can keep the catalogue honest.

This module describes; it never registers a tool, changes a prompt or touches the
agent loop. See docs/design/tool-discoverability.md."""
from __future__ import annotations

from dataclasses import dataclass, field

from harness.work_modes import WORK_MODES

ALL_MODES = tuple(WORK_MODES)
EVERY_MODE = ALL_MODES


@dataclass(frozen=True)
class Capability:
    id: str
    title: str
    summary: str
    example: str
    category: str
    modes: tuple[str, ...]
    tools: tuple[str, ...]
    # Existing interface surface for this capability, when it already has one.
    # The catalogue points at it instead of becoming a second way in.
    opens: str = ""

    def as_dict(self) -> dict:
        return {"id": self.id, "title": self.title, "summary": self.summary,
                "example": self.example, "category": self.category,
                "modes": list(self.modes), "tools": list(self.tools),
                "opens": self.opens}


CATEGORIES = ("documents", "finding", "web", "images", "project", "long_work", "skills")

CAPABILITIES: tuple[Capability, ...] = (
    # --- documents ---------------------------------------------------------
    Capability(
        id="read_documents",
        title="Read a document",
        summary="Word, PDF, Excel and CSV, including scanned pages that have to be looked at.",
        example="Read the contract in this project and summarise the main points for me.",
        category="documents", modes=EVERY_MODE,
        tools=("read_document", "read_project_document", "list_project_documents",
               "view_document_page", "read_file"),
    ),
    Capability(
        id="edit_word",
        title="Edit a Word document without losing its formatting",
        summary="Replaces the text inside; tables and styles stay as they are.",
        example="In report.docx replace every mention of 2025 with 2026.",
        category="documents", modes=EVERY_MODE,
        tools=("edit_word_document",),
    ),
    Capability(
        id="edit_spreadsheet",
        title="Work with a spreadsheet",
        summary="Reads formulas as well as values and can change cells.",
        example="Add a VAT column to the budget spreadsheet and fill it in.",
        category="documents", modes=EVERY_MODE,
        tools=("edit_spreadsheet",),
    ),
    Capability(
        id="export_document",
        title="Save the result as PDF, Word or Markdown",
        summary="Turns the finished text into a file you can send.",
        example="Save this as a PDF.",
        category="documents", modes=EVERY_MODE,
        tools=("export_document",),
    ),
    # --- finding and memory ------------------------------------------------
    Capability(
        id="find_in_project",
        title="Find something in your own files",
        summary="Searches by words and by meaning, documents included.",
        example="Find everywhere in this project that talks about the delivery date.",
        category="finding", modes=EVERY_MODE,
        tools=("search_files", "find_files", "search_project", "semantic_search", "list_dir"),
    ),
    Capability(
        id="find_in_history",
        title="Find something in older conversations",
        summary="Reaches chats that are long out of the current context.",
        example="What did we agree about the colours a month ago?",
        category="finding", modes=EVERY_MODE,
        tools=("search_chat_history", "read_chat_history"),
    ),
    Capability(
        id="remember_fact",
        title="Remember a fact for good",
        summary="For this project, for this kind of work, or everywhere. You can read and edit what is stored.",
        example="Remember for this project that we use metric units.",
        category="finding", modes=EVERY_MODE,
        tools=("save_memory", "read_memory"), opens="settings:memory",
    ),
    Capability(
        id="pin_file",
        title="Keep a file always at hand",
        summary="A pinned file stays in view for every answer in this chat.",
        example="Pin brief.md so you have it with every answer.",
        category="finding", modes=EVERY_MODE,
        tools=("pin_context_file", "unpin_context_file"), opens="panel:context",
    ),
    Capability(
        id="record_decision",
        title="Record a decision that holds across chats",
        summary="Accepted decisions follow the project into every new conversation.",
        example="Record as a decision that the site will be in Czech only.",
        category="finding", modes=EVERY_MODE,
        tools=("project_decisions",), opens="dialog:decisions",
    ),
    # --- web ---------------------------------------------------------------
    Capability(
        id="web_lookup",
        title="Look something up online and read the page",
        summary="Ordinary web use whenever an answer needs current information.",
        example="Find out what these cards currently cost.",
        category="web", modes=EVERY_MODE,
        tools=("web_search", "web_fetch"),
    ),
    Capability(
        id="research_run",
        title="Run proper research with sources and a conclusion",
        summary="Plans the sub-questions first, keeps every source, and the conclusion has to use all of them.",
        example="Research how one can license this font today.",
        category="web", modes=("research",),
        tools=("web_search", "web_fetch"), opens="dialog:sources",
    ),
    # --- images and screen -------------------------------------------------
    Capability(
        id="look_at_image",
        title="Look at a picture or a screenshot",
        summary="Reads what is in the image and can describe or judge it.",
        example="Look at this screenshot and tell me what is wrong.",
        category="images", modes=EVERY_MODE,
        tools=("view_image",),
    ),
    Capability(
        id="control_computer",
        title="Operate the computer for you",
        summary="Sees the screen, clicks and types. Moving the mouse into the top-left corner stops it.",
        example="Open that program and export the list to CSV.",
        category="images", modes=("computer",),
        tools=("screenshot", "click", "type_text", "press_key", "scroll",
               "move_mouse", "get_screen_info"),
    ),
    Capability(
        id="watch_a_program",
        title="Watch a program you are testing",
        summary="Finds the program's own window and photographs it even when something else is "
                "in front, so your other work is not disturbed.",
        example="Start my game and watch what happens when you press enter.",
        category="images", modes=("computer",),
        tools=("list_windows", "focus_window"),
    ),
    # --- project work ------------------------------------------------------
    Capability(
        id="write_program",
        title="Write or change a program",
        summary="Edits are atomic and the whole task can be taken back.",
        example="Add a pause to the game when the space bar is pressed.",
        category="project", modes=EVERY_MODE,
        tools=("write_file", "apply_patch"),
    ),
    Capability(
        id="organise_files",
        title="Tidy up files in the project",
        summary="Create, move, rename and delete, all inside the task journal.",
        example="Move those images into an assets folder.",
        category="project", modes=EVERY_MODE,
        tools=("make_directory", "move_file", "delete_file"),
    ),
    Capability(
        id="run_project_checks",
        title="Run the project's checks and fix what fails",
        summary="Finds the project's own tests, runs them and repairs the failures.",
        example="Run the tests and fix whatever fails.",
        category="project", modes=("development", "computer"),
        tools=("start_project_check", "project_validation_profile", "run_command"),
        opens="panel:progress",
    ),
    Capability(
        id="show_changes",
        title="Show what changed and take it back",
        summary="Every file the task touched, with a diff and a one-click revert.",
        example="What did you just change? Put it back.",
        category="project", modes=EVERY_MODE,
        tools=("list_task_changes", "undo_task_changes"), opens="panel:results",
    ),
    Capability(
        id="save_version",
        title="Save a version into the project's history",
        summary="A local commit with a description. Nothing is ever pushed on its own.",
        example="Save this version with a description of what is new.",
        category="project", modes=("development", "computer"),
        tools=("git_status", "git_diff", "git_commit"),
    ),
    Capability(
        id="try_web_app",
        title="Try out a web page or application",
        summary="Opens it in a separate browser of its own, clicks through it and reports what it saw.",
        example="Open that page and check whether the form works.",
        category="project", modes=("development", "computer"),
        tools=("browser_open", "browser_snapshot", "browser_click", "browser_fill",
               "browser_screenshot", "browser_press", "browser_select", "browser_scroll",
               "browser_hover", "browser_wait", "browser_upload", "browser_download",
               "browser_viewport", "browser_console", "browser_network", "browser_close"),
        opens="panel:progress",
    ),
    # --- long work ---------------------------------------------------------
    Capability(
        id="plan_long_task",
        title="Break a bigger task into steps and show progress",
        summary="A visible plan that survives a restart.",
        example="Split this into steps and keep showing me where you are.",
        category="long_work", modes=("writing", "development", "computer"),
        tools=("set_task_plan", "update_task_step", "task_plan_status",
               "record_task_validation"), opens="panel:progress",
    ),
    Capability(
        id="background_work",
        title="Run something long in the background",
        summary="Keeps an eye on it and reports when it finishes.",
        example="Run it in the background and tell me when it is done.",
        category="long_work", modes=("development", "computer"),
        tools=("start_command", "poll_command", "terminate_command", "send_stdin"),
        opens="panel:progress",
    ),
    # --- skills ------------------------------------------------------------
    Capability(
        id="use_skill",
        title="Use a prepared procedure",
        summary="Optional skills hold worked-out procedures; one is loaded only when it fits.",
        example="Is there a skill for this? Use it if it fits.",
        category="skills", modes=EVERY_MODE,
        tools=("list_skills", "read_skill"), opens="settings:memory",
    ),
)

# Tools the catalogue deliberately does not advertise. A new tool that is neither
# mapped to a capability nor listed here fails the suite, so "we forgot to tell
# users about it" is a failing test rather than a silent omission.
INTERNAL_TOOLS: dict[str, str] = {
    "context_status": "Already shown in the Context panel; not something to ask for",
    "repo_overview": "The model orients itself with it; not a user request",
    "project_instructions": "Applied automatically from AGENTS.md and friends",
    "find_symbol": "Code navigation the model uses while working",
    "document_symbols": "Code navigation the model uses while working",
    "find_references": "Code navigation the model uses while working",
}


def registry_tools(mode: str) -> set[str]:
    from harness.agent import build_registry
    spec = WORK_MODES[mode]
    return set(build_registry(spec.agent_mode, mode).names())


def for_mode(mode: str) -> list[dict]:
    """The catalogue with availability resolved against the real registry.

    An entry is available when the mode offers it and every tool behind it is
    actually registered, so a capability whose tools disappeared reports as
    unavailable rather than promising something the harness cannot do."""
    if mode not in WORK_MODES:
        raise ValueError(f"Unknown work mode: {mode}")
    present = registry_tools(mode)
    rows = []
    for item in CAPABILITIES:
        row = item.as_dict()
        row["available"] = mode in item.modes and present.issuperset(item.tools)
        rows.append(row)
    return rows


def catalogue(mode: str) -> dict:
    return {"mode": mode, "categories": list(CATEGORIES), "capabilities": for_mode(mode)}
