# Release record: Marvin 1.23.0

27 November 2026. Single-agent local harness overhaul for faster prompt reuse, longer memory in large projects, dynamic setup-aware system prompts, resilient file editing, recovery guards, and live prompt-cache telemetry in the workspace UI.

## Highlights

- **Tool schema consolidation with 100% legacy alias compatibility:** Grouped related browser, task-plan, memory, context, and project-info actions into compact tools (`browser_inspect`, `browser_interact`, `task_plan`, `memory`, `manage_context`, `project_info`), trimming tool-schema overhead by ~1,500 tokens per request (`development`: 68 → 43 tools; `computer`: 77 → 52 tools) while keeping every legacy tool name callable as an alias.
- **Thinking continuity & KV-cache preservation:** Attached loop warnings and progress nudges inline to tool results instead of injecting synthetic `role: "user"` turns mid-loop, deduplicated `TASK_PROTOCOL_NOTE` across turns, and cached `RepoIndex` snapshots per task while keeping instant steering, Stop, and queued messages unchanged.
- **Non-destructive observation masking & smarter file reads:** Before triggering lossy summarization at 85% context, Marvin now masks only older bulky tool outputs (keeping recent outputs, user turns, replies, memory, decisions, task plans, and diffs intact, with full originals preserved on disk and via `read_chat_history`). `read_file` defaults to a 400-line / 30k-character window with continuation hints.
- **Resilient editing, syntax validation & recovery guards:** `apply_patch` adds safe whitespace/CRLF and indentation-shifted fallback matching when unique, stale-file detection against external disk edits, compact unified diffs, closest-line failure hints, and pre-write `.toml`/`.xml` validation. Added `ReasoningLoopGuard` and leaked `<tool_call>` retry recovery.
- **Dynamic setup-driven system prompt & memory upgrades:** Replaced hardcoded model/GPU/language text in `harness/prompts.py` with the active selected model, detected GPU/RAM, and configured UI language. Added memory deduplication plus `replace` and `remove`.
- **Incremental indexes, smarter shell & UI cache telemetry:** Per-file incremental `CodeIndex`, multi-language `RepoIndex` symbols, `.gitignore`-aware `git ls-files` search fallback, shell failure-line extraction + expanded safe read-only commands, and live **Prompt cache** hit-rate + **Masked tool outputs** display in the Context panel (EN/CS).
- **Updated English and Czech user manuals:** Refreshed both PDFs (`Marvin-Manual-EN.pdf`, 30 pages; `Marvin-Manual-CS.pdf`, 25 pages) to document moved-folder recovery, three-stage context compression, consolidated tools, and prompt-cache metrics.

## Validation

- Automated test suites: `tests/test_core.py` **365/365 OK**, `tests.test_harness_upgrades` **10/10 OK**, `tests.test_localization` **13/13 OK**, `tests.test_capabilities` **11/11 OK**, `tests.test_prompt_performance` **26/26 OK**, `tests.test_agent_protocol` **6/6 OK**, `tests.test_test_fix` **4/4 OK**, and `unittest discover -s tests` **553/554 OK** (sole failure is the expected headless `RealDesktopTests.test_the_open_windows_are_described_completely`).
- Relocated Full runtime verification (`tests/check_full_runtime.py`): passed with system Python disabled, verifying private Python 3.12, locked packages, `llama.cpp` build `12359`, bundled Strata `0.2.17`, and bundled Infernix `2026.11.20`.
- Local installation (`%LOCALAPPDATA%\QwenHarness`) upgraded via `Marvin-Setup-1.23.0-Full.exe /VERYSILENT /NORESTART`, verified private environment via `bootstrap_full.py`, and confirmed installed `APP_VERSION == "1.23.0"`.

## Release Assets

Staged in `dist/release-1.23.0/` and recorded in `release-1.23.0.json` (application build commit `e04a52b`):

| File | Bytes | SHA-256 |
|---|---:|---|
| Marvin-Setup-Minimal.exe | 54,184,942 | `7a053baffe40b7acad6c0afd28d8e782033af6da4aa24be1ce0c46fd288bbe8a` |
| Marvin-Setup-Full.exe | 1,807,466,732 | `7e7520a57103369428c3717b64fea26f7df57d04e114a6d5a03f8c301a023886` |
| Marvin-Manual-EN.pdf | 228,545 | `ca0a12b5d12989277485dc769a0f65ecad6b3ba8f4d8f73cd936a9d240267ae9` |
| Marvin-Manual-CS.pdf | 225,351 | `2f653cda5e17def78d81170a8216e158bf71826982dbd460112f1e293b9861fd` |
| Marvin-Workspace.jpg | 136,523 | `41bdec06fd93e28ab17c53167777f566c9fda995860d93a0781c58ac3055652b` |
| SHA256SUMS.txt | 445 | `961aaf9bf6839db8dcdddbb449bd856b5e1128e81df52728473cae937bf1a6dd` |

## Offline Package Refresh

`Marvin-Offline-Backup-1.22.0` was refreshed from the upgraded installation (`offline_backup.py refresh --runtime-root %LOCALAPPDATA%\QwenHarness --exclude-models strata/models/IQ2_XS,strata/packs/iq2_xs,strata/conversation-spill`) and automatically renamed to `Marvin-Offline-Backup-1.23.0`:

- Replaced `Marvin-Setup-1.22.0-Full.exe` with `Marvin-Setup-1.23.0-Full.exe` and updated manuals and installation guides.
- `offline_backup.py verify` passed for all **3,496** recorded files (0 errors).
- Superseded `1.22.0` local installers and staging directory were deleted after verification.

## GitHub publication verification

Published on 27 November 2026 (`02:01 UTC`) as the latest release:
[Marvin 1.23.0](https://github.com/petrsajner/marvin/releases/tag/v1.23.0).
The release tag points at `b49a27f`; the application build commit is `e04a52b`.
All six uploaded assets are in state `uploaded`, and their sizes and GitHub
SHA-256 digests match `release-1.23.0.json`.
`releases/latest/download/SHA256SUMS.txt` serves the 1.23.0 checksums.
