# Consumer parity review - what to fix to be top-tier for a non-programmer

22 September 2026. Architecture and functionality audit of the tree at 1.16.1
(`404a5ad`), benchmarked against consumer vibe-coding tools rather than
developer harnesses.

This review extends [harness-parity-roadmap.md](harness-parity-roadmap.md) on
purpose. That document compared Marvin with Open WebUI / AnythingLLM, Aider,
Continue, Cline and Claude Code, and said so explicitly: *"every competitor
above is aimed at developers, so copying their ordering would optimise for the
wrong person."* It then closed gaps A-E within days. The comparison set here is
the one that actually serves the stated target user - **Lovable, Replit Agent,
v0, Bolt.new / bolt.diy, ChatGPT Sites, Base44, Dyad, Onlook** - tools for
ordinary people doing vibe coding. The two documents share the target user and
the boundaries; only the yardstick differs.

Method: survey of `harness/` (75 modules, ~16.4k lines), `frontend/src/`,
`installer/`, `launcher/`, `tests/` and `docs/`; web research on the competitor
set (primary docs and changelogs, sources at the end); spot-checks of every
claim that became a recommendation.

Boundaries from [AGENTS.md](../../AGENTS.md) are fixed constraints, as in the
parity roadmap: no LSP layer, no persistent terminal as primary workflow, no
parallel agents/subagents, no 1M-token contexts, no plugin/MCP host or broad
integration framework. The benchmark's features that map to those are listed in
"Do not copy" at the end - they are recorded as decisions, not proposed.

## Executive summary

Marvin is stronger than the consumer leaders on the engine floor: measured GPU
profiles with an honest recovery ladder, MTP speculative decoding, crash-safe
durable jobs, live steering with prompt-cache awareness, checkpointed file
changes with per-file restore, document intelligence (DOCX-in-place, PDF, XLSX),
a research ledger with citations, cross-chat decisions and memory, dictation,
and an offline installer with a verified backup story. None of Lovable, Replit
or v0 can run at all without their cloud.

What separates this from "top-tier" is not engine capability. It is the three
loops a non-programmer experiences:

1. **The trust loop** ("can I let this thing touch my project?"). The diff
   viewer shows raw unified diffs with raw filesystem paths; "Revert task
   changes" fires with no confirmation; restore scope is never spelled out.
   Lovable's whole 2026 lead is here (Drafts with one-line plain-language change
   summaries, Bookmarks, honest "code yes, database no" restore messaging).
2. **The result loop** ("I asked for an app - where is it running?"). Preview is
   buried in a file modal; there is no live preview panel, no dev-server
   lifecycle in the UI, no runtime-error capture feeding a one-tap fix. This is
   the core of vibe coding and the largest functional gap.
3. **The first-ten-minutes loop** ("what do I even type?"). A blank chat and one
   sentence. The capability catalogue and its example prompts are excellent and
   hidden behind a lightbulb icon.

Underneath, a short list of engineering defects actively costs user trust today:
orphaned processes after exit, background timeouts only enforced on poll,
silent download failures, a localization test that is currently red because of
a stray file, a latent message-prefix drift that leaks internal prompts into
search and export, and zero frontend tests around the most fragile logic (SSE
reconciliation).

Recommended sequencing: one quick-wins release, then the trust layer, then the
result loop, then onboarding; the self-verifying fix loop and publishing after
that. Details with file anchors below.

## Where Marvin already leads (keep and extend)

Carried over from the parity roadmap (measured profiles + recovery ladder, MTP,
offline installer + backup, mode-aware compression, research ledger, decision
ledger, DOCX-in-place, computer control, history retrieval, tok/s and context
accounting), plus consumer-relevant leads the developer benchmark could not
see:

- **Document outputs for non-programmers.** `export_document` (MD/DOCX/PDF),
  spreadsheet editing, live document preview while writing. Lovable only
  shipped `generate-files` in 2026; Marvin's in-place DOCX editing is ahead.
- **Dictation.** whisper.cpp, Czech + English, text lands in the composer for
  review. Dyad and bolt.diy only have voice prompting; nothing local matches it.
- **Honest failure handling.** `failures.py` plain-language hints, the
  "Work out what to do" repair prompt, advisory loop warnings, and the
  interrupted-tool sealing on resume ("outcome unknown, inspect before
  retrying") are exactly the trust vocabulary the leaders use.
- **Durable queue + live steering.** "After completion" and "Clarify now" with
  prompt-cache-preserving prefill handling are better thought through than
  Lovable's follow-up queue.
- **Ownership.** Files on disk, ZIP export/import, per-task git auto-commit,
  never deleting attached folders (`projects.py:143-172`). Dyad's whole pitch
  is this; Marvin already lives it.

## Architecture assessment

### Strengths worth protecting

- **Single-writer application layer.** One `marvin-run-controller` worker with a
  durable SQLite `EventStore` (append-only events, job snapshots, file
  registry) and SSE replay by sequence number (`web_api.py:275-290`) is the
  right shape for a single-user app. Crash recovery is genuinely good: interrupted
  jobs recovered at boot, interrupted tool calls sealed rather than replayed,
  damaged JSONL resurrected from the event store (`jsonl.py:70-121`).
- **Change safety.** `ChangeJournal` (`changes.py`) with journaled atomic
  writes, per-task `.bak` manifests, hash-guarded undo, whole-workspace
  checkpoints with drift inspection. The substrate for the whole trust layer
  already exists; it is a presentation problem more than an engineering one.
- **Context engineering.** Stable system prompt (byte-identical per session to
  preserve the llama.cpp prompt cache), dynamic deltas in a user message,
  mode-aware compression with calibrated token accounting. Do not restructure
  this.

### Structural risks (with anchors)

1. **Shared mutable state without consistent locking.** The worker mutates
   `Session.messages`, `session.meta`, `AgentContext` and `service.live[sid]`
   during `agent.step()` while HTTP handlers read them under `service.lock`
   (`application.py` `_drive` vs `get_session`/`message_payload`). Iterating a
   list or dict the worker is appending to is a latent
   `RuntimeError: dictionary changed size` class of bug, most likely under
   steering + SSE polling - i.e. exactly when the product is being used hardest.
2. **No shutdown cleanup.** `ProcessManager.terminate_all` (`processes.py:223`)
   is called only from tests. `ApplicationService.close()`
   (`application.py:1022`) joins the worker and nothing else; user-launched
   `start_command` processes, project checks and headless Edge survive the app.
3. **Background-process timeouts are lazy.** The hard timeout is enforced inside
   `poll()` (`processes.py:148-151`): an unpolled process runs forever.
4. **`load_config(path)` root pitfall.** `path` selects the YAML but `Config`
   resolves all `paths.*` against the code root (`config.py:12,235,371-381`).
   Only `web_api.py:775` and `launcher_app.py:142` re-root correctly; any new
   entry point silently scatters user data into the install directory.
5. **Internal-prefix drift (real bug).** `INTERNAL_USER_PREFIXES`
   (`session.py:103-108`), the `history_index` tuple and
   `semantic_index._INTERNAL_PREFIXES` have diverged: `"[LOOP WARNING"` is
   missing from the first two. Loop-warning pseudo-user messages therefore
   count as real user turns for compression boundaries and are indexed and
   exported as genuine user content.
6. **Silent swallows in user-visible paths + no logging framework.**
   `web_api.py:48-49` (semantic-model download failure is invisible),
   `session.py:593-594` (title/meta loss), broad `except Exception` in
   `servermgmt` probes. `harness/` has no logging framework at all - field
   diagnosis for a non-technical user is currently impossible.
7. **Runtime `pip install ddgs` inside `web_search`** (`tools/web.py:83-104`):
   unconsented venv mutation at tool time, breaks the pinned-lock
   reproducibility story and fails confusingly offline.
8. **Monoliths.** `application.py` (1028 lines, `_drive` ~250),
   `web_api.create_app` (~700-line closure with undeclared dynamic service
   attributes `service.maintenance`, `service.backup_targets`),
   `perform_action` 160-line dispatcher, dead `harness/streaming.py`.
9. **Unbounded growth.** `events`/`jobs` never pruned; checkpoint capture copies
   the whole project tree per task (`changes.py:371-379`) with no retention;
   `list_sessions(limit=100000)` scans every session (with per-file JSONL title
   scans) on each `/api/state` call; `history_index.search` runs a full stat
   sweep per call.

## Functionality and UX assessment (non-programmer lens)

Ordered by how much each one costs the target user.

1. **Change review is programmer-native.** The diff dialog
   (`Dialogs.tsx:1814-1941`) is a raw side-by-side/unified diff with raw paths.
   This is the moment a non-programmer decides whether to trust the tool, and it
   is the least friendly screen in the product.
2. **Destructive actions are inconsistent.** "Revert task changes"
   (`App.tsx:1673-1679`) and "Unpin all" run with no confirmation; restores use
   native `window.confirm` while chat/project deletes use styled dialogs. Both
   an accidental-loss risk and a trust risk.
3. **No live preview of a running app.** HTML preview exists only inside the
   file-preview modal's sandboxed iframe (`Dialogs.tsx:1396-1407`), asset-limited
   to siblings of the file; no side panel, no auto-refresh while the agent
   iterates (the 1.5 s preview refresh covers text previews only), no
   dev-server lifecycle in the UI (only the generic Processes panel).
4. **No onboarding.** Empty chat says "What shall we work on?" and nothing else
   (`App.tsx:1003-1010`). The capability catalogue (`capabilities.py` with
   ready example prompts) is hidden behind the lightbulb button
   (`App.tsx:1311-1317`).
5. **First-run vocabulary leaks.** Raw enums exposed to users: thinking level
   `xhigh/medium/low/off` (`App.tsx:1325-1329`), autonomy
   `supervised/semi/auto` (`Dialogs.tsx:615-617`), raw status echoes
   (`App.tsx:1514,1596`); model settings speak enthusiast ("KV cache profile",
   "MTP", "GPU memory budget"); untranslated strings in Czech mode ("Loading
   workspace...", "Browser", "English PDF", "Task failed"); Czech strings leak
   into English-source tool output (`memory.py:141`, `documents.py:254,326,338`,
   `session.py:526`, `projects.py:48`).
6. **Work modes are unexplained.** A bare `<select>` (`App.tsx:924-938`) whose
   switch visibly changes almost nothing; the real differences are hidden by
   design (`api.ts:79-86` filters protocols).
7. **Ctrl+V accepts images only** (`App.tsx:1186-1197`) while attach and
   drag-drop accept PDF/DOCX/XLSX/CSV - a classic "it is broken" moment.
8. **Code output is the least polished content type.** Plain `<pre>`, no syntax
   highlighting, no language badge, no per-block copy button
   (`styles.css:631-636`, `Messages.tsx:122-143`).
9. **Outputs are file rows, not artifacts.** The Results tab lists names and
   kinds (`App.tsx:1410-1458`); no document thumbnails, no "open the app" card,
   no result naming conventions like `report_v2.pdf`.
10. **Repair loop is one-shot and prompt-only.** `checks/fix` queues a single
    `FIX_PROMPT` job (`web_api.py:435-448`) with no attempt cap and no
    machine-readable verdict back to the UI.

## Benchmark summary (September 2026)

Baseline every serious consumer tool now has: live preview of the running app;
automatic version history with one-click restore; one-click publish/share; at
least image attachments; templates or starter prompts; a one-tap fix on errors;
chat memory/instructions.

Top-tier differentiators: (1) a real trust layer - Lovable Drafts (isolated
changes with one-line plain-language summaries and explicit Accept), Bookmarks,
honest restore scope; Replit checkpoints covering files + AI context + database
state; (2) runtime-error capture and a fix-verify loop (Lovable browser testing
reads console and network and verifies fixes; "Try to fix" on error cards); (3)
visual click-to-edit (Lovable preview toolbar, v0 Design Mode); (4) plan-first
mode gating implementation (Lovable Plan Mode with an editable, versioned plan
document); (5) multimodal richness (documents, voice, annotated screenshots);
(6) artifact outputs beyond web apps; (7) guided backends; (8) plain-language
security guardrails; (9) onboarding that teaches the loop - Replit's 10-minute
guided build with growth cards, Lovable's worked example teaching "one change
per prompt, verify, then move on"; (10) product analytics after publish.

Local-first subset (Dyad, bolt.diy + Ollama, Onlook): ownership/export,
privacy, unlimited work, transparency into every diff - and the same weak spots:
instruction-following limits of small models answered only with "smaller models
may struggle", silent context-window misconfiguration, toolchain prerequisites,
no managed publish. **Nobody in the local subset has a degradation-aware UX or
a self-verifying run-fix loop.** Those two are the open opportunities that fit
Marvin exactly.

Market notes: GitHub Spark shut down (Aug 2026) - its consumer design (instant
preview, one-click restore, remixable starts) was right, the platform was the
risk. Windsurf became Devin Desktop and left the consumer market. Firebase
Studio sunsets in March 2027. The consumer field is consolidating around
Lovable, Replit Agent, v0 and ChatGPT Sites.

Condensed matrix (Y verified, P partial, N absent, - not applicable):

| Capability | Lovable | Replit Agent | v0 | Dyad | bolt.diy | **Marvin today** |
|---|---|---|---|---|---|---|
| Live app preview + refresh | Y | Y | Y | Y | Y | **P** (file-modal iframe) |
| Auto version history + 1-click restore | Y | Y (files+AI+DB) | Y | Y | Y | **P** (exists, manual, raw UI) |
| Runtime-error capture + fix loop | Y | P | Y | P | P | **N** (ingredients exist) |
| Plain-language change review | Y (Drafts) | P | P | P | P | **N** (raw diff) |
| Plan-first, editable plan | Y | Y | P | N | P | **P** (plan panel, no gate) |
| One-click publish / share | Y | Y | Y | P | Y | **N** (ZIP/folder export) |
| Starter templates / onboarding | Y | Y | Y | P | P | **P** (catalogue, hidden) |
| Project knowledge / memory | Y | Y | P | P | P | **Y** (3 layers + decisions) |
| Docs & multimodal input | Y | P | Y | P | P | **Y** (docs + dictation) |
| Document/artifact outputs | Y | Y | P | N | P | **Y** (weak presentation) |
| Voice input | Y | N | N | N | Y | **Y** (whisper, CZ+EN) |
| Offline / local model | N | N | N | Y | Y | **Y** (whole product) |
| Checkpoint of data (DB etc.) | N (warned) | Y | N | N | N | **-** (files only, must say so) |

## Recommendations

Effort: **S** (hours), **M** (days), **L** (a release cycle or more).

### R1. Plain-language change review - the trust layer (P0, S-M)

*Problem:* `Dialogs.tsx:1814-1941` raw diff is the trust-decision screen.
*Target:* Lovable Drafts: every change carries a one-line plain-language summary,
reviewable before accept; the raw diff stays available as a second level.
*Proposal:* after each task, show "What I changed" first: one plain sentence per
changed file ("I added the Start button to `index.html`") with Restore
prominent per file and "Show technical diff" folding to the existing view.
The `ChangeJournal` manifest already knows the file set; the summary can be
produced by the model as part of the task's structured summary (it already owes
one per `TASK_PROTOCOL_NOTE`) and stored next to the manifest. Add confirmation
dialogs to "Revert task changes" and "Unpin all" (`App.tsx:1673-1679, 1868-1872`)
and replace `window.confirm` with the styled dialog.
*Also:* state restore scope honestly wherever restore appears ("restores the
project's files; it never touches your chat history or anything outside the
project"). Lovable's own beginner
guide names *skipping bookmarks / misunderstanding restore scope* as its #1
pitfall.
*Anchors:* `changes.py` (file_diff, manifest), `app_operations.perform_action`
"revert", diff dialog, `Messages.tsx` failure cards.

### R2. Live preview of the running app (P0-P1, M-L)

*Problem:* the vibe-coding core loop "prompt -> see it running" has no surface.
*Target:* every leader has a preview pane; Lovable keeps selection across edits
and reduced reloads in Sep 2026.
*Proposal (staged):*
1. **Preview panel now (M):** a "Preview" tab in the right column (next to
   Results/Progress/Context) rendering the newest previewable result
   (`/api/preview/{id}/{path}` already serves files with sibling assets) in a
   sandboxed iframe, auto-refreshing while the owning run is active - reuse the
   1.5 s refresh logic from `Dialogs.tsx:294-308`. An "Open in browser" button
   next to it.
2. **Managed served apps (L):** a first-class "app" concept over
   `ProcessManager`: start the project's dev server (or a static server for
   generated folders) on a registered port, show a persistent card "The app is
   running at http://localhost:xxxx" with Open/Stop, bind its lifecycle to the
   session, and kill it on shutdown (see R6). This is the seam the backend
   lacks today (port registry + lifecycle binding + presentation), and it also
   gives the fix loop in R7 its runtime.
*Note:* do not rebuild WebContainers-style in-browser execution; running the
user's real project on disk is the local product's advantage.

### R3. Onboarding and the first ten minutes (P0, S-M)

*Problem:* blank chat, one sentence; the capability catalogue is hidden
(`App.tsx:1311-1317`).
*Target:* Replit's guided 10-minute build (copyable starter prompt with explicit
non-goals + growth cards) and Lovable's taught habits ("one change per prompt,
verify, then move on"; "request empty/loading/error states").
*Proposal:* (a) first-run welcome state with 4-6 concrete starter tasks drawn
from `capabilities.py` examples ("Summarise this document for me", "Make me a
simple web page with ...", "Write a short story...") inserting into the
composer like `useExample` already does; (b) surface the catalogue in the empty
state, not only behind the lightbulb; (c) one short how-to hint after the
first success ("send one change at a time and check what changed after each");
(d) after a first project task, suggest 2-3 next steps (Replit
growth cards pattern) - "Test the app", "Add a button", "Back up the
project". Templates beyond prompts can wait; example prompts cost nothing.

### R4. Legible modes and settings in user language (P0, S)

*Problem:* raw enums and enthusiast vocabulary (finding 5, 6).
*Proposal:* friendly labels + short explanation per work mode in the selector
("Development - Marvin can edit files and run tests"), thinking levels as
"Deep / Balanced / Light / None", autonomy as "Ask me first /
Small changes alone / Work on its own"; move "KV cache profile / MTP / GPU budget"
figures behind an "Advanced" disclosure (keep them - the owner and power users
want them; the default view should not require them). Fix the localization
leaks listed in finding 5 and extend `tests/test_localization.py` to catch
Czech in tool output strings (it apparently covers packaging, not
`harness/*.py` message strings).

### R5. Quick wins (P0, S - one small release)

- Delete the stray root file `et --soft HEAD` - it is git junk (a mangled
  `git reset` output redirected into a filename) and it currently **turns
  `tests.test_localization` red** (Czech diacritics scan picks it up).
- Add `"[LOOP WARNING"` to `Session.INTERNAL_USER_PREFIXES` and the
  `history_index` tuple; better: one shared constant imported by all three
  (`session.py:103`, `history_index.py:55`, `semantic_index.py:29`).
- Bundle `ddgs` in requirements and delete the runtime `pip install`
  (`tools/web.py:83-104`).
- Ctrl+V: accept documents like attach/drag-drop do (`App.tsx:1186-1197`).
- Code blocks: syntax highlighting, language badge, per-block copy button.
- Styled confirmation for "Revert task changes" and "Unpin all".
- `web_api.py:48-49`: surface semantic-download failure instead of `pass`.
- PDF export: the hardcoded `C:\Windows\Fonts\arial*.ttf` lookup
  (`documents.py:100-105`) silently degrades to Helvetica and breaks Czech
  diacritics - probe the font properly or embed one.
- Version single-source: `frontend/package.json` (1.9.0) and `marvin.iss`
  fallback (1.14.1) disagree with `installer/version.txt` (1.16.1);
  `INSTALL-EN.md` header still says 1.9.0.
- Release gate: `installer/release.bat:41` omits four existing test modules
  (`test_commands`, `test_openart`, `test_restart_log`, `test_results`).
- Tracked junk/state: remove `test_hook.txt`; consider gitignoring
  `projects.json` (it is committed app state carrying a personal path) in
  favour of a seed file.

### R6. Consumer-grade reliability (P0-P1, M)

- **Shutdown cleanup:** call `ProcessManager.terminate_all` and close live
  browsers from `ApplicationService.close()` and the FastAPI lifespan
  (`application.py:1022`, `web_api.py:66-68`). "Close Marvin" must not leave
  npm servers and headless Edge alive.
- **Process watchdog:** enforce `ManagedProcess` hard timeouts from a timer
  thread, not lazily in `poll()` (`processes.py:148-151`).
- **Logging + diagnostics bundle:** add a real logging setup writing to
  `runtime/webapp.log` (levels, rotation) and a Settings > Data "Export
  diagnostics" that zips recent logs + versions + `model-failure.json` +
  `model-restarts.log` (scrub personal paths). This is how one person supports
  non-technical users remotely.
- **`load_config` root fix:** make the data root an explicit parameter with one
  resolution helper (or resolve `paths.*` against the config file's root), and
  add a regression test. Silent data scatter in installed copies is the worst
  possible failure mode for a personal-memory product.
- **Locking discipline:** snapshot-on-read (`list(session.messages)`,
  `dict(service.live)`) in HTTP handlers now; longer-term give the worker sole
  write ownership with message passing.
- **Retention:** prune `events`/`jobs` by age, cap checkpoint storage (keep N
  task backups + named checkpoints), and stop `list_sessions` full scans on
  `/api/state` (index or bound it).

### R7. Self-verifying run-fix loop - the open differentiator (P1, L)

*Problem:* `checks/fix` is one prompt-shot with no cap and no verdict; runtime
errors in generated apps can only be noticed by the model polling
`browser_console` on its own initiative.
*Target:* Lovable "Try to fix" on error cards + browser testing that reproduces,
fixes and verifies; the known category weakness (HN: fixed bugs "return on
another screen") argues for **regression memory**, not one-shot fixes.
*Proposal:* a "Test and fix" action (button on the preview/app card and on
failure cards) that runs one bounded sequential loop - the non-goal is parallel
agents, not iteration: (1) open the app in the existing isolated browser,
(2) capture console/network errors and a screenshot,
(3) feed them to the agent as a structured repair prompt (the `FIX_PROMPT`
pattern), (4) re-run the same probe, (5) stop after N attempts (default 3) with
a plain-language verdict ("Tested: the Start button works; 2 errors in the
console"). Record each probe's verdict in `TaskPlanStore` validations and write
recurring failures into the change summary so regressions are visible. Surface
progress as "Starting the app... Testing the button... Fixing...".

### R8. Planning: available and recommended, never forced (P1, M)

Owner guidance (22 September 2026): planning must be a distinguishable,
switchable way of starting work - a plan mode the owner turns on at the
beginning of a task, or an explicit "plan this first" request in chat - and
**never a mandatory step forced on every request**. Advanced users know when
they want it and per-request gating would only annoy them.

*Target:* Lovable Plan Mode (editable plan document, Approve -> Build) and
Replit Plan/Build, minus any automatic gating; the beginner failure mode these
address is "big prompt collapse", which the *option* solves without taxing
users who do not need it.
*Proposal:* (a) a "Plan first" switch near the work mode selector - on for the
conversation until turned off - which makes the agent propose a plan through
the existing `TaskPlanStore` and pause in `NEEDS_CONFIRMATION` before the first
write until the owner approves or strikes steps ("this step does not suit me");
(b) without the switch, asking "plan this first" in chat produces the same flow
through the task protocol; (c) ordinary requests keep today's behavior - soft
planning nudges for multi-step work, no gates. All the machinery exists (task
plan panel, `resume(approve=)`, readiness nudges); this is flow design, not new
infrastructure.

### R9. Artifacts and outputs for non-programmers (P1, S-M)

Promote the `files` registry/`discover_results` inventory into artifact cards:
document cards with first-page thumbnails, image cards with lightbox, an
"app card" for previewable results (Open / Preview / Send to chat), version-ish
export naming (`report_v2.pdf` pattern, Lovable's Files tab). The Results tab
rows (`App.tsx:1410-1458`) become the launch point.

### R10. Memory made visible (P1, S)

Marvin's 3-layer memory + decisions are a lead (benchmark row: Y). What is
missing is legibility: a visible "Marvin si to pamatuje" moment when a memory
or decision is consulted or saved (the `DYNAMIC TASK CONTEXT` deltas already
carry this information internally), and one-click "Zapamatuj si tohle" on any
message. Lovable Knowledge and Replit Memories are exactly this.

### R11. Publishing and sharing (P2, S then owner decision)

Local-safe first: **single-file HTML export** (inline assets - a shareable
artifact with zero third-party involvement) and "Open project folder / ZIP"
which already exist. A one-click publish to a static host is *not* barred by
the invariants (it is not a plugin host), but it is a broad third-party
integration by nature - treat it as an owner decision with a deliberately
narrow scope (one built-in target, like Lovable's non-MCP connectors), or skip
it and keep the ownership pitch (Dyad's "owner, not a renter") intact. Publish
semantics must be taught if added: preview is not published.

### R12. Engineering quality floor (P1-P2, M)

- **Frontend:** split `App.tsx` (2080) / `Dialogs.tsx` (1984); replace `any`
  at the API boundary with the types already implied by `api.ts`; add vitest
  for the pure logic that is currently untested and fragile - `mergeMessages`
  ordering, `reconcileMessages` stitching, live-buffer dedupe (`App.tsx:2007-2026,
  660-665`); wire `tsc --noEmit` + ESLint as their own npm scripts and run them
  in `release.bat` (today typecheck only happens as a build side effect).
- **Tests:** a deterministic fake-model unit test for `agent.step()` (the
  fixture-server pattern exists in `tests/serve_workspace_fixture.py` but is not
  wired into unittest); frontend SSE reconnect/resync test; run the suite
  routinely - the red localization test over a junk file proves it is not run
  between commits.
- **CI:** even a minimal GitHub Actions job (unittest + tsc on push) removes the
  single-maintainer blind spot. Release provenance: local tags stop at
  `v1.11.0` while `release-*.json` reference `v1.16.1` and their
  `application_commit` SHAs were orphaned by the 19 Sep history rewrite - stop
  rewriting `main`, keep tags in sync with manifests.
- **Dead code and duplication:** remove `harness/streaming.py` (imported only by
  `tests/test_core.py`); unify `IGNORED_DIRS` (3 copies with drift,
  `tools/fs.py:15`, `tools/search.py:16`, `file_index.py:11`); dedupe the
  duplicated UI blocks (semantic-search paragraph `Dialogs.tsx:548-558` vs
  `591-601`, mode labels, checks buttons); declare `service.maintenance` /
  `service.backup_targets` on `ApplicationService`.
- **Legacy surface:** `tui.py` and `run_cli.bat` are legacy while the web UI is
  the product; retiring them (or freezing them as unsupported) reduces the
  surface that must keep working through refactors.

### R13. Consumer documentation set (P2, S-M)

- **"What's new"** in-app or in Settings > Help (today: 17 developer
  `RELEASE-*.md` records, nothing a user browses).
- **FAQ / troubleshooting**: SmartScreen warnings on the unsigned installer,
  WebView2 recovery, model download failures, "the window is blank", "where are
  my files" - `failures.py` hints exist in-app but no doc backs them.
- **"Move Marvin to another PC"** user guide for the offline backup flow
  (`run_setup_from_backup.bat`) - powerful and currently documented only in
  script comments. While at it: unify the backup prefix
  (`offline_backup.py` still says `QwenHarness-Offline-Backup` while reality is
  `Marvin-Offline-Backup*`).
- **Privacy statement** in one paragraph (local data, what leaves the machine
  when web tools are used) - README touches it; a manual chapter would carry it.

## Do not copy (recorded decisions, not gaps)

- **Parallel agents / sub-agents / agent fleets** (Replit Agent 4, Cursor fleets,
  Lovable subagents + `/goal`, Devin Desktop, Antigravity). Permanent non-goal.
  Evidence from the benchmark: Lovable leads the category on serial chat + trust
  layer; iteration within one sequential loop (R7) covers the consumer need.
- **MCP/plugin hosts** (bolt.diy, Dyad, Lovable, Replit, Cursor, Devin). Permanent
  non-goal. The consumer need is "connect my stuff"; if that ever matters, the
  answer is a few built-in connectors, not an ecosystem.
- **Persistent terminal / IDE surfaces** (all pro tools, bolt.diy). Permanent
  non-goal. Nothing in the consumer top-10 requires it.
- **LSP-grade code intelligence.** Permanent non-goal; the symbol index is the
  substitute, and the target user does not miss it.
- **1M-token contexts.** Permanent non-goal; the recovery ladder and
  mode-aware compression are the better answer to long work.
- **SaaS mechanics**: credits, daily free quotas, hosted multi-tenant anything.
  The local product's answer to "usage" is at most a plain history (parity
  roadmap gap F) - stay deferred unless a consumer signal appears.
- **Docker sandboxing** (OpenHands) - already excluded in the parity roadmap;
  supervised mode + checkpoints are the substitute for a personal machine.

## Suggested sequencing

1. **R5 quick wins + R4 legibility** - one small release; restores the green
   test gate and removes the loudest "unfinished" signals.
2. **R1 trust layer** (+ confirmations, honest restore scope).
3. **R2.1 preview panel** -> **R6 reliability** (the pair that makes R2.2 and R7
   safe to build).
4. **R3 onboarding** (can ship as early as item 1 allows - it is cheap).
5. **R7 run-fix loop** and **R2.2 managed served apps** together.
6. **R8 plan-first**, **R9 artifacts**, **R10 memory visibility**.
7. **R12 engineering floor** continuously (front-load the test/CI parts).
8. **R11 publishing** as an owner decision; **R13 docs** alongside each release.

## Sources (accessed 22 September 2026)

- Lovable: changelog (Jul-Sep 2026), Drafts, History/restore, Plan mode, Preview
  toolbar, Browser testing, Project chat ("Try to fix"), Knowledge, Generate
  files, Mobile app, "From idea to app" - https://docs.lovable.dev/
- Replit: "Build your first app" (growth cards), Version control (Agent
  Checkpoints: files + AI context + DB), Memories - https://docs.replit.com/
- v0: Design Mode, templates, quickstart - https://v0.app/docs/
- ChatGPT Sites (public beta; save-version/deploy-version, custom domains,
  analytics) - https://learn.chatgpt.com/docs/sites
- bolt.diy (local models via Ollama/LM Studio; known local-model reliability
  issues #1825, #2047, #1732) - https://github.com/stackblitz-labs/bolt.diy
- Dyad (local Lovable alternative; ownership pitch, Supabase/Neon wizards,
  security review; local-model caveats #4472, #4552, #4553) -
  https://www.dyad.sh , https://github.com/dyad-sh/dyad
- Onlook (visual click-to-edit; checkpoints/templates still roadmap) -
  https://onlook.com , https://github.com/onlook-dev/onlook
- GitHub Spark deprecation (4 Aug 2026) -
  https://github.blog/changelog/2026-08-04-upcoming-deprecation-of-github-spark-on-github-com/
- Devin Desktop (formerly Windsurf) - https://devin.ai/desktop
- Firebase Studio sunset (22 Mar 2027) - https://firebase.studio
- Sentiment: HN "I'm going back to coding by hand" (9 Sep 2026, regression
  complaints), HN "Show HN: Dyad" thread (ownership/export motivation) -
  hn.algolia.com
