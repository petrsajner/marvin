# Marvin Product Invariants

This repository builds a personal, single-user Windows application. The web UI is
the primary product surface. Shell access exists only as a backup capability for
the model. One local model occupies the GPU and performs the work sequentially.

## Permanent Non-Goals

The following features do not belong in this product and must not be proposed,
planned, or implemented unless the owner explicitly reverses this decision:

- Language servers or an LSP runtime/distribution layer.
- A persistent interactive terminal as a primary workflow.
- Parallel model agents, subagents, or multi-model orchestration.
- One-million-token context profiles or context expansion beyond practical GPU profiles.
- A general plugin host, MCP ecosystem, or broad third-party integration framework.

Use the built-in lightweight symbol index instead of LSP. Keep the current bounded
background process tools as the shell fallback. Improve the single-agent web
experience, reliability, context quality, and practical local tools rather than
expanding into these non-goals.

## Source language and localization

- Reuse the approved September 15, 2026 model measurements in
  `docs/design/profile-remeasurement-2026-09-15.md` and `docs/design/measurements/`.
  `harness/measured_profiles.py` is the built-in profile authority. Do not infer
  model minima from total desktop VRAM or initial free RAM, add blanket reserves,
  change KV precision during recovery, or repeat the complete benchmark matrix
  without a relevant weights/runtime/allocation change. Recovery keeps the same
  model, cache precision and weight placement and only lowers context.

- Write code, identifiers, comments, docstrings, model/tool prompts, test fixtures,
  scripts and contributor documentation in English.
- English is the default UI language. Keep optional Czech UI text and legacy
  Czech compatibility data in `harness/locales/cs.json`; installer translations
  belong in `installer/locales/`. Both Python and React use the shared catalog.
- Keep the English and Czech user manuals and installation guides. These user
  documents are the intentional documentation exceptions. Do not rewrite user
  conversations, personal memory or Git history to enforce source language.
- Run `python -m unittest tests.test_localization` when changing localization,
  templates or packaging. Its character scan supplements manual review; it is
  not a complete natural-language detector.

## Current Architecture & UI/UX Model (v1.6+)

- **Workspace Frontend**: React + TypeScript workspace (`frontend/src/` -> `ui_dist/`)
  embedded via desktop WebView2 launcher or browser. Features a 3-column layout with
  resizable handles (`ResizeHandle`), instant activity feedback (`ActivityFeedback`),
  optimistic model status indicators (`ModelStatus`), and categorized Settings dialogs.
- **Application Layer**: Local FastAPI + `ApplicationService` (`harness/application.py`,
  `harness/web_api.py`). Decoupled from browser connections. Uses a single background
  worker (`marvin-run-controller`), durable SQLite event store (`EventStore`), replayable
  SSE streams, and persistent draft / queued task storage.
- **5 Ordered Work Modes**: Always ordered as `Discussion → Research → Writing → Development → Computer`.
  Each chat owns its work mode; changing mode changes prompt framing and toolsets.
- **Composer & Attachments**: Attach button, drag-and-drop, and Ctrl+V clipboard paste.
  Accepts multiple images and documents (PDF, DOCX, XLSX, CSV, txt). Inline previews in
  composer with removal buttons, real thumbnails in sent messages, and full-size modal viewing.
  Images and documents are passed directly into model payloads.
- **Task Control & Execution**: Non-blocking STOP during reasoning, tool preparation, or
  execution. Live steering ("Clarify now") redirects the active run; "After completion" queues
  the next task durably.
- **Legacy UI**: The Gradio UI remains accessible solely as a fallback compatibility surface
  via `MARVIN_LEGACY_UI=1`.

## Harness Intelligence & Tooling

- **Sequential Single-Agent Loop**: `harness/agent.py` manages execution with structured
  statuses (`FINAL`, `CONTINUE`, `NEEDS_CONFIRMATION`, `ABORTED`, `ERROR`).
- **Advisory Repetition Detection**: Does not forcefully terminate after repeated calls.
  Instead, emits advisory guidance (`[LOOP WARNING]`), encouraging the model to check
  actual progress (output bytes, file diffs, process status) or try an alternate approach.
- **Mode-Aware Chunked Compression**: `harness/context.py` summarizes transcripts by domain:
  architecture and test evidence for Development; claims, sources, and contradictions for Research;
  outline, voice, and continuity for Writing; goals and decisions for Discussion.
- **Original History Retrieval**: Tools `search_chat_history` and `read_chat_history` allow the
  model to search and read earlier transcript parts and older chats even after context compression.
- **Document Intelligence**:
  - Word: In-place text edits (`edit_word_document`) preserving formatting, tables, and runs.
  - PDF: Page-by-page text extraction with on-demand vision rendering (`view_document_page`).
  - Excel: Formula vs cached value inspection, range/sheet addressing, cell editing.
- **Cross-Chat Project Decisions**: `project_decisions` tool and `DecisionStore` track
  accepted decisions in `.qwen/decisions.json`, injecting only explicitly accepted decisions
  into the project context.
- **Project Indexing**: Persistent incremental FTS5 file index (`harness/file_index.py`),
  lightweight multi-language symbol index, and cached repo snapshots.
- **Verification Protocols**: Task protocols encourage proportionate validation (plan tracking,
  git diff inspection, test execution) before final structured summaries without hard gates.
