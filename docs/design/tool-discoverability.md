# Tool discoverability - a capability catalogue for a user who does not program

18 September 2026. Implementation design for item A of the
[harness parity roadmap](harness-parity-roadmap.md).

## Problem

The harness registers 33 tools in Discussion and Research, 37 in Writing, 68 in
Development and 75 in Computer. The model sees all of them. The user sees none.

The only user-facing catalogue today is section 20 of the manual - a PDF the user
has to open, and which lists tool names - plus the optional skills list in
Settings. Neither is reachable from where work happens.

Tool `description` fields cannot be shown to the user. They are written for the
model and they read like it:

> Apply exact text replacements to one file atomically. Each edit must match the
> expected number of occurrences; no partial change is written on failure.

> Replace exact text in an existing DOCX while preserving paragraphs, tables and
> run styles. Specify old_text and new_text.

A person who does not program does not want to know that `find_files` and
`search_files` are different functions. They want to know that they can ask Marvin
to find something in their project, and roughly how to ask.

## Decision

Introduce a **capability catalogue**: a curated, user-facing layer above the tool
registry, of about twenty entries rather than seventy-five. Curation is the
feature - a complete list of tools would reproduce the problem in a new place.

The unit is a thing the user can ask for, not a function the model can call. One
capability may cover several tools, and some tools are never advertised because
they are not user actions.

Each entry carries:

| Field | Purpose |
|---|---|
| `id` | Stable key for translations and tests |
| `title` | Plain language, e.g. "Find something in your project" |
| `summary` | One sentence, no tool names, no jargon |
| `example` | A ready prompt the user can put straight into the composer |
| `category` | Grouping in the dialog |
| `modes` | Work modes where it applies |
| `tools` | Underlying tool names - not shown by default, and the anchor for tests |

The `example` field is the part that actually solves the problem. Discoverability
for this user is not a list of names; it is knowing how to phrase the request. A
click puts the example in the composer, where it can be edited before sending.

## Keeping it honest

A curated layer drifts from the code. That failure mode has already happened in
this project this month, so the catalogue is tied to reality by tests rather than
by discipline:

1. Every tool named in a capability must exist in the registry of every mode the
   capability claims.
2. Every registered tool must be either mapped to a capability or listed
   explicitly in `INTERNAL_TOOLS` with a reason. A new tool therefore fails the
   suite until someone decides whether users should hear about it.
3. Every capability string must have a Czech translation, checked the same way
   `test_localization` checks the rest.

Rule 2 is the important one. It converts "we forgot to advertise the new feature"
from an invisible omission into a failing test.

Availability is computed against `build_registry` at request time, not stored, so
an entry whose tools are missing reports as unavailable instead of lying.

**What the tests do not catch.** They detect structural drift - a tool vanishing,
or a new tool nobody decided to advertise. They cannot detect semantic drift: a
tool that still exists but now behaves differently, leaving the description
quietly wrong. No test can. The mitigation is editorial: entries describe an
outcome ("find something in your files"), never a mechanism ("hybrid FTS5 and
vector retrieval"). Outcomes age far more slowly.

## A directory, not a second door

Where a capability already has its own place in the interface, the entry links to
it and never reimplements it. Memory has its editor in Settings; task changes and
restore points have the Results and Progress panels; skills have their list in
Settings. The catalogue points at those.

This is what keeps the catalogue from colliding with what already works: a second
implementation never appears, so there is nothing for the existing one to fight
with. The `opens` field on an entry carries that target.

## Capabilities that are really modes

Some capabilities are not produced by phrasing a request differently - they are
produced by the work mode. Research is the clear case. Asking for research in
Discussion yields web search and a good answer; Research mode additionally opens a
source ledger, plans sub-questions *before* the first search, and forces a final
synthesis that must cite every source it loaded (`agent.py` lines 351, 613, 728).

An entry whose modes exclude the current one therefore must not insert a prompt -
that would promise a result the current mode cannot deliver. It offers the mode
switch instead.

This falls out of the availability rule rather than needing a special case, and it
turns the overlap into the most useful entry in the catalogue: work modes are
themselves undiscovered, and a user who does not program has no reason to guess
why they would leave Discussion.

## Backend

`harness/capabilities.py`

```python
CAPABILITIES = (
    Capability(
        id="find_in_project",
        title="Find something in your project",
        summary="Search your files by words or by meaning, including documents.",
        example="Find every place in this project that mentions the delivery date.",
        category="project",
        modes=("discussion", "research", "writing", "development", "computer"),
        tools=("search_files", "find_files", "semantic_search"),
    ),
    ...
)

INTERNAL_TOOLS = {
    "undo_task_changes": "Offered as a button, not as a request",
    "poll_command": "Step of a longer operation, never asked for directly",
    ...
}

def for_mode(mode: str) -> list[dict]:
    """Catalogue for one work mode with availability resolved against the registry."""
```

`GET /api/capabilities?mode=<mode>` returns every entry with `available: bool` and
`modes`, so the dialog can show what the current mode does not offer and where it
lives instead.

No new dependency, no change to tool descriptions, no change to what the model
sees.

## Interface

**Entry point.** A button in the composer toolbar beside Attach, labelled
"What can I ask for?". The composer is where a non-programmer is already looking
when they do not know what to type. Nothing else in the interface is a plausible
first stop.

**Dialog.** The existing dialog pattern (`setDialog({type: "capabilities"})`),
grouped by category, filtered to the current work mode by default with a toggle
for everything. Each row: title, summary, and a **Use this** action that inserts
the example into the composer and closes the dialog. Existing classes only -
`skill-list`, `file-row`, `wide`, `muted`.

**Modes.** An entry belonging to another mode is shown muted with "Available in
Development" and a one-click switch, reusing `act("mode", {mode})`. This is the
"availability of all tools" half of the goal: the user learns both that the
capability exists and how to reach it.

**Skills.** Optional skills are a category in the same dialog rather than a
separate concept in a separate place. They already carry a user-facing name and
description, so they need no curation.

**Context panel.** The existing "Loaded skills" section gets a link to the
catalogue. No new concept.

## Localization

Titles, summaries and examples live in English in the source and in `cs.json`, as
everything else does. The examples must be genuinely translated, not transliterated
- a Czech user has to receive a Czech prompt they would actually send. Roughly
twenty entries times three strings in two languages is the real cost of this
feature, and it is content work, not code.

**Prerequisite fix:** [App.tsx:1091](../../frontend/src/App.tsx) renders the
composer's Attach label as a bare literal instead of `tr("Attach")`, so the Czech
interface shows an English button even though `cs.json` already carries the
translation for it. The new button sits next to it; fix the existing one in the
same change.

## Tests

`tests/test_capabilities.py`

- Every capability's tools exist in the registry of each mode it claims.
- Every registered tool across all five modes is mapped or explicitly internal.
- `for_mode` marks an entry unavailable when a tool is missing.
- The endpoint returns per-mode availability for each mode.
- Every capability string has a Czech translation.

Regression: `test_core`, `test_workspace`, `test_localization`.

## Scope

**In:** the catalogue, the dialog, the composer entry point, the mode hint and
switch, skills as a category, the `tr("Attach")` fix.

**Out:** the command palette (roadmap item E - keyboard-driven, a different
problem and a different user), contextual suggestions based on what the user is
typing, and any change to how tools are described to the model.

## Effort

The code is small: one data module, one endpoint, one dialog, one button. The
work is curation and translation - deciding which twenty things a non-programmer
should be told about, and phrasing each so it can be used without asking what a
word means. Budget accordingly: writing the entries will take longer than
building the surface that shows them.
