# Marvin Architecture & Intelligence Reference (v1.6 – v1.7)

This document provides a comprehensive technical overview of Marvin's architecture, UI/UX design, and harness intelligence capabilities.

---

## 1. Product Invariants & Non-Goals

Marvin is a personal, single-user Windows application. It is designed around a single local model occupying the GPU and executing tasks sequentially.

### Permanent Non-Goals
The following features are explicit non-goals and must not be proposed or introduced:
- **No LSP runtime or language-server distribution layer**: Marvin uses its built-in lightweight symbol index and ripgrep/FTS5 search instead.
- **No persistent interactive terminal as a primary workflow**: Bounded background processes and shell tools serve strictly as an automation fallback.
- **No parallel model agents, subagents, or multi-model orchestration**: A single sequential agent executes work without background model cascades.
- **No one-million-token context profiles**: Context remains within practical local GPU footprints (typically 96k–256k tokens on an RTX 5090 32 GB).
- **No general plugin host, MCP ecosystem, or broad integration framework**: Capabilities are provided through direct, maintainable built-in tools and SKILL.md modules.

---

## 2. System Architecture

```text
┌──────────────────────────────────────────────────────────────┐
│  Desktop Host (WebView2 via Marvin.exe / Native Browser)     │
└──────────────────────────────┬───────────────────────────────┘
                               │ HTTP / SSE Events
┌──────────────────────────────▼───────────────────────────────┐
│  Workspace Frontend (React 18 + TypeScript + Vite)           │
│  - 3-column resizable layout (ResizeHandle)                  │
│  - Navigation, Composer, ActivityFeedback, OperationProgress │
│  - Right panels: Results, Progress, Context, Sources         │
└──────────────────────────────┬───────────────────────────────┘
                               │ FastAPI REST / EventStream
┌──────────────────────────────▼───────────────────────────────┐
│  ApplicationService (harness/application.py, web_api.py)     │
│  - Decoupled from browser connections and UI frameworks      │
│  - Single background model worker (marvin-run-controller)    │
│  - SQLite EventStore (durable jobs, sequence IDs, drafts)    │
│  - SessionStore & Projects management                        │
│  - ModelSwitchController (autostart, VRAM, KV cache, GPU)    │
└──────────────────────────────┬───────────────────────────────┘
                               │ Tool Calls & Agent Loop
┌──────────────────────────────▼───────────────────────────────┐
│  Agent & Intelligence Layer (harness/agent.py)               │
│  - Single sequential agent loop                              │
│  - Mode-aware context compression (harness/context.py)       │
│  - History retrieval (search_chat_history, read_chat_history)│
│  - DecisionStore (.qwen/decisions.json)                      │
│  - In-place document tools (DOCX, PDF vision, XLSX ranges)   │
│  - Multi-turn TaskPlanStore & ChangeJournal restore points   │
│  - Persistent incremental FTS5 file index & RepoIndex        │
└──────────────────────────────┬───────────────────────────────┘
                               │ OpenAI-compatible HTTP Stream
┌──────────────────────────────▼───────────────────────────────┐
│  Local Inference Server (llama-server / llama.cpp)           │
│  - Models: Qwen3.8-27B (Q5/Q4), Ornith 1.5 35B-A3B (Q5)      │
│  - Native vision projection (mmproj)                         │
│  - KV cache precision: F16 (accuracy) or Q8 (double context) │
│  - Native reasoning / thinking effort control                │
└──────────────────────────────────────────────────────────────┘
```

---

## 3. UI/UX Paradigm

### 3.1 Three-Column Resizable Layout
The modern frontend (`frontend/src/App.tsx`) is structured into three clear columns with interactive drag handles (`ResizeHandle.tsx`):
1. **Left Navigation (Sidebar)**:
   - Project dropdown with creation, folder attachment, and project deletion.
   - **New Chat** button and search query input.
   - Conversation history list with pagination (initially 20 chats, expandable via "Show older"), multiline previews, and active selection.
   - Chat action menu: rename (in-place or via menu), move to another project, undo round, fork, export (Markdown / JSONL), delete.
2. **Center Conversation & Composer**:
   - Header: Editable chat title, current project indicator, work mode selector, real-time `ModelStatus` badge, and Settings button.
   - Message Thread (`Messages.tsx`):
     - Distinct styling for user and assistant messages without visual clutter.
     - Collapsible thought/reasoning boxes with duration timer.
     - Collapsible tool execution blocks showing tool name, arguments, and formatted results.
     - Inline thumbnails for all attached images and documents with click-to-zoom modal view.
   - Unified Composer:
     - Prominent **Attach** button with paperclip icon for disk selection.
     - Drag-and-drop file support directly onto the composer area.
     - **Ctrl+V clipboard paste** supporting multiple images and files simultaneously.
     - Detachable preview chips with individual removal (X) buttons.
     - Textarea supporting Enter / Ctrl+Enter to send, Shift+Enter for new line.
     - Thinking depth selector (`xhigh`, `medium`, `low`, `off`) positioned next to prompt.
     - Autonomy level badge (`supervised`, `semi`, `auto`).
     - Dynamic action during active runs: **Clarify now** (live steering) vs **After completion** (durable queue).
     - Responsive **STOP** button active during reasoning, tool execution, and generation.
3. **Right Detail Panels**:
   - **Results**: Produced documents (PDF, DOCX, Markdown), modified files, verification test statuses, export options, folder navigation, and app launcher.
   - **Progress**: Visible multi-turn task plan, background processes with streaming stdout/stderr and termination controls, headless browser viewport and interaction log.
   - **Context**: 3-tier memory inspection (Global, Mode, Project), pinned files list, loaded skills catalog, and live token usage (estimated/measured vs physical context limit).
   - **Sources** (in Research mode): Complete research ledger with URLs, query plans, search candidates, extracted texts, and citations.

### 3.2 Five Ordered Work Modes
Work modes always maintain a strict canonical order:
1. **Discussion (Diskuze)**: Everyday conversations, brainstorming, conceptual exploration; no coding rules or build tools.
2. **Research (Výzkum)**: Web search, page fetching, research ledger recording, mandatory structured synthesis.
3. **Writing (Psaní)**: Document creation and revision, text editing, creative drafting, checkpointing, and rollback.
4. **Development (Vývoj)**: Coding agent with file patch/write tools, Git, shell execution, test profiles, symbol navigation, and repo map.
5. **Computer (Počítač)**: Development capabilities plus full desktop control (MSS screenshots, PyAutoGUI mouse and keyboard automation).

### 3.3 Categorized Settings Modal
Settings are organized into dedicated tabs (`Dialogs.tsx`):
- **Model and Device**: Model selection, KV cache precision, GPU VRAM allocation, llama-server lifecycle (Start / Stop / Restart), runtime diagnostics.
- **Behavior**: Autonomy setting, default steering vs queueing behavior.
- **Memory and Skills**: Interactive editor for Global, Mode, and Project memories; skill catalog viewer, skill designer, and quick links to user & project skills folders.
- **Data and Backups**: Project export/import archives, JSONL chat imports, offline backup creation and verification.
- **Appearance and Language**: Theme selection (Dark / Light / System), layout density (Comfortable / Compact), UI language (English / Czech).
- **Help and Manuals**: Access to English (24 pages) and Czech (18 pages) PDF manuals, slash commands reference.

---

## 4. Harness Intelligence & Tooling

### 4.1 Single-Worker Run Controller & Durability
- `ApplicationService` maintains a single background thread (`marvin-run-controller`) that owns all inference and tool operations sequentially.
- State, jobs, and drafts are durably persisted in SQLite (`EventStore`). If a browser tab is reloaded, closed, or network disconnects, the task continues uninterrupted and client reconnects replay events seamlessly.
- Draft prompts and pending attachments are saved per chat and persist across project and chat navigation.

### 4.2 Non-Blocking STOP and Live Steering
- **Immediate STOP**: Halts generation cleanly during thinking/reasoning, tool argument streaming, or tool execution. Unlike earlier versions, it does not wait for visible text tokens.
- **Steering vs Queueing**:
  - *Clarify now*: Modifies the prompt in-flight at sentence boundary without discarding work completed so far.
  - *After completion*: Enqueues a subsequent task that automatically executes once the current task finishes.

### 4.3 Advisory Repetition Guidance
- Eliminates hard termination after arbitrary loop counts.
- When identical tool signatures repeat, the agent receives an advisory prompt nudge (`[LOOP WARNING]`), prompting the model to compare results, recognize whether it is legitimately polling a process, or try a different approach.
- Forward progress is assessed through tangible changes: output stream bytes, modified files, and process state changes.

### 4.4 Mode-Aware Chunked Context Compression
When conversation length approaches context limits (~85%), `harness/context.py` performs non-destructive compression:
- The full transcript remains intact on disk in JSONL format.
- A technical continuation summary is generated specifically tailored to the active work mode:
  - *Development*: Architecture, file changes, test evidence, errors, next steps.
  - *Research*: Claims, source URLs, contradictions, uncertainties.
  - *Writing*: Outline, voice, characters, chronology, approved wording.
  - *Discussion*: Goals, decisions, unresolved questions, user preferences.
- Summaries preserve message references and source links.

### 4.5 Historical Retrieval Tools
When older messages are compressed out of active context, the model can actively retrieve them:
- `search_chat_history(query)`: Searches across session history via persistent SQLite FTS5 index.
- `read_chat_history(session_id, start, count, query)`: Reads original stored messages with pagination, bringing specific details back into active reasoning.

### 4.6 Document Connectors & In-Place Editing
- **DOCX**:
  - `read_document_content`: Block-by-block reading preserving natural sequence of paragraphs and tables.
  - `edit_word_document`: Performs targeted in-place text replacements directly in the document XML, strictly preserving existing formatting, styles, tables, and runs.
- **PDF**:
  - `read_document_content`: Extracts page-by-page text with explicit detection of scanned pages lacking a text layer.
  - `view_document_page`: Renders any individual PDF page to an image and attaches it directly to the model context for visual inspection via `mmproj`.
- **XLSX**:
  - `read_document_content`: Sheet selection, cell range addressing (e.g. `A1:D20`), and dual-mode inspection (`formulas=True` to inspect underlying formulas vs `formulas=False` for cached values).
  - `edit_spreadsheet`: Reads, edits, and creates Excel spreadsheets.

### 4.7 Cross-Chat Decision Ledger
- Project decisions are tracked in `.qwen/decisions.json` via `project_decisions` tool and `DecisionStore`.
- Decisions have distinct statuses: `proposed`, `accepted`, `retired`, linked to their source session ID.
- Only explicitly **accepted** decisions are automatically injected into the project context header (`## ACCEPTED PROJECT DECISIONS`), preventing unreviewed ideas from leaking across chats as established truth.

### 4.8 Persistent Project File Index & Search
- `harness/file_index.py` provides persistent SQLite WAL FTS5 indexing with file mtime/size invalidation.
- Shared file discovery caches project file trees across tools to eliminate redundant disk scans.
- Ripgrep literal/regex search complements FTS5 for exact code lookups.

---

## 5. Runtime, Packaging & Installers (v1.7.0)

Marvin provides two distinct installer options:
1. **Minimal Installer** (`dist/Marvin-Setup-<version>.exe`, ~15 MB):
   - Requires 64-bit Python 3.12 pre-installed on the host system.
   - Creates a dedicated `.venv` and downloads pip dependencies and llama.cpp binaries during setup.
2. **Full Installer** (`dist/Marvin-Setup-<version>-Full.exe`, ~678 MB):
   - Fully self-contained offline runtime.
   - Bundles a private CPython 3.12.9 distribution (`runtime/python`), locked wheels (`runtime/python-packages`), and CUDA-accelerated llama.cpp (`runtime/llama`).
   - Completely isolated: does not modify system PATH, system Python, or global environment variables.
   - Safe against conflicting system `PYTHONHOME`, `PYTHONPATH`, or `PYTHONUSERBASE`.
3. **Model Management**:
   - Model weights (~59 GiB) are downloaded on demand or restored from `QwenHarness-Offline-Backup`.
   - The application automatically remembers and autostarts the last active model and KV profile upon launch.
