# English source and optional Czech localization

Source update after the published 1.8.2 build, 15 September 2026. No installers or release assets were rebuilt for this change. The published tag, version number, offline set and installed application remain separate from these source changes.

## Boundaries

Source code, identifiers, comments, docstrings, internal messages, model/tool prompts, tests, build scripts, memory templates and contributor/research documentation use English. Historical research retains its original dates, measurements, sources and limitations; translation is not a new upstream verification.

English is the default UI language. `harness/locales/cs.json` contains optional Czech messages, native language names and compatibility data for old Czech settings/history. Both Python and React consume this catalog. English messages are lookup keys and safe fallbacks. Installer messages live in `installer/locales/cs-custom.isl` and `cs-messages.isl`; build definitions include the application catalog in source installs and frozen launchers.

The English and Czech user manuals remain available, along with both installation guides. User conversations, personal memory and Git history are not rewritten as part of the language policy. Repository memory files are empty templates, not personal factual memory.

## Compatibility and startup

Language detection prefers current workspace preferences, then legacy UI preferences, then the installer choice; a new installation defaults to English. A missing, invalid or wrongly typed optional catalog does not prevent startup. Missing translations and invalid formatting placeholders fall back to the original English message. Invalid optional document-operation patterns are ignored while English recognition remains available.

Legacy Czech KV labels still migrate correctly, old memory headings still identify the original development memory, and old confirmation messages remain recognizable. Localized document-export requests remain supported independently of the UI language. Model definitions and YAML now keep English labels; the API adds translated display labels from the catalog. The formerly misplaced Nemotron YAML entries now live in the models section with the same effective values as the built-in definitions.

## Verification

- 366 core checks and 102 service/localization tests passed, covering history recovery, model switching, memory budgets, queues, runtime preparation and WebView2.
- TypeScript and the production Vite build passed. A disposable application instance was checked in the browser: English startup, Czech settings/model/KV labels, persistence after reload, restoration of the same conversation, and return to English. Both manual links remained present.
- Both PDFs were generated into a temporary audit directory. English retained 26 pages and Czech 20; extracted text matched the distributed PDF on every page. Existing distributed manuals were not replaced.
- The language tests check optional-catalog failures, language precedence, legacy data, placeholder consistency, frontend keys, profile labels, packaging resources, and Czech characters outside the approved localization/user-document paths. Manual review also covers Czech written without accents; the automated character check is not a full language detector.

Repeat the service checks with the project interpreter:

```text
python -m unittest tests.test_workspace tests.test_runtime_support tests.test_prompt_performance tests.test_history_recovery tests.test_webview_runtime tests.test_memory_profiles tests.test_localization
```

`installer/release.bat` includes the new memory/localization tests for the next authorized build. The script itself was not run in this source-only update. Memory qualification and physical small-GPU limitations are recorded separately in [memory profiles](memory-profiles.md).

Local evidence is consolidated in `runtime/archive/verification-source-2026-09-15.zip`: 195 files with verified CRC and per-file SHA-256, including memory audit results, test logs, translation review inputs and disposable UI data. Archive SHA-256: `218ecc0c9dac8e1cf4355ed78dc9a7a4c2bfafbafb90ae27e62e998a152cc436`. Reproducible unpacked copies are marked for manual removal under `runtime/KE-SMAZANI/after-source-2026-09-15/`. Weights, active runtimes, dependencies and release packages are outside that cleanup.
