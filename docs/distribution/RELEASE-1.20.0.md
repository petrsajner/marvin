# Release record: Marvin 1.20.0

8 November 2026. Marvin suggests the user's next step in the composer. A
cloud session prepared the feature and the version on `main`
([handoff](../design/2026-11-08-release-1.20.0-handoff.md)); this local
session checked it against the real models on the owner's PC, fixed what the
models showed, built the installers, updated the installation and the offline
backup, and published the release.

## Behavior

- The system prompt of every work mode asks the model to end each reply with
  `<next_step>…</next_step>`: its running guess of the user's next instruction,
  written as the user's own next message in the user's language.
- The tag is hidden from the streamed reply, the saved reply and the model's
  reasoning (`NextStepStreamFilter`, `split_next_step`). The latest guess is
  kept in `session.meta["next_step"]` and sent as the `next_step` event.
- A final reply without a guess leaves one from the task's state: a failing
  check, then an unfinished plan step, then the summary's "📋" next steps, then
  the latest earlier guess of the same task.
- The composer shows the suggestion as its placeholder when the chat is idle and
  the field is empty; → or Tab takes it. **Settings > Behavior > Suggest the
  next step** (`next_step_suggestions`, on by default) removes the request from
  the prompt and hides the suggestion.

### Changes from the check with real models

- Qwen 3.8 27B wrote no tag in Development: the task protocol and the summary
  request say the reply ends with the `CHANGES:` list, and the model followed
  them. Both notes now name the next-step line as the last line while
  suggestions are on (`de9161c`).
- Nemotron drafts the tag in its reasoning, which the thinking panel showed.
  The reasoning is filtered like the reply; only the reply's tag counts.
- The prompt gives an example and rules out describing the user ("The user may
  ask…"), speaking as the model and asking the user for something; with no
  sensible step the tag is left out instead of saying so inside it.
- Cleaning a suggestion keeps underscores (`tests/__init__.py`) and a quoted
  part inside it (`a9c854d`); only quotes around the whole suggestion go.

## Validation

- 511 unittest tests and the core checks passed on the release commit;
  localization checks passed.
- `installer/release.bat` built both installers with all tests and the Full
  runtime check passing.
- Real models on this PC (RTX 5090 32 GB), the application service from the
  checkout with the installed weights, thinking at xhigh, Czech requests: two
  Discussion requests (a cycling trip, then cheap lodging) and one Development
  task (guard `divide(a, 0)`, add a test, run the tests).

  Requests that ended with a suggestion:

  | Model | Before the changes (one run) | After the changes |
  |---|---|---|
  | Qwen 3.8 27B Q5 | Discussion 2/2; Development 0/1 | two runs: Discussion 4/4; Development 2/2 |
  | Flash-Next IQ3_S | Discussion 1/2; Development 1/1 | two runs: Discussion 3/4 (missed once after a web search); Development 2/2 |
  | Nemotron 3.5 Q5 | Discussion 1/2, in English; Development "no further steps"; tag in the thinking panel | one run: Discussion 1/2; Development 1/1, the last guess in English |

  No `<next_step>` text reached a reply, the reasoning or the live progress in
  any run after the changes. Example suggestions, translated here from Czech:
  "Add a test that checks the exact text of the exception message", "Find a
  specific guest house in Bechyne for up to 1,500 CZK per double room for
  Saturday night". Nemotron still sometimes writes the guess in English; the
  public notes say that how often and how well a model suggests varies.
- The workspace from the checkout with Flash-Next, in the built-in browser: the
  suggestion appeared as the grey placeholder after the reply, → and Tab each
  turned it into editable text, and turning **Suggest the next step** off left
  the usual placeholder and → did nothing.
- The owner's installation (`%LOCALAPPDATA%\QwenHarness`) was updated with the
  Full installer (`/VERYSILENT`, exit 0); its application code and workspace
  match the release commit. A short check with the installation's own Python:
  Flash-Next and Qwen 3.8 27B each answered one Discussion request and one
  Development task with a suggestion, and no tag showed anywhere.

The assets are staged in `dist/release-1.20.0/` with the established public
filenames. The exact hashes and download URLs are recorded in
`release-1.20.0.json`. The application build commit is `834ef3b`; later
commits change only documentation and the rebuilt manuals.

| File | Bytes | SHA-256 |
|---|---:|---|
| Marvin-Setup-Minimal.exe | 54,138,159 | `90db389cb93a37976889123c23f754b4ec8b36637bc00bf75af45c8926a765e7` |
| Marvin-Setup-Full.exe | 1,515,031,259 | `224f099b987079f996718336f6e20de1407fcdfd5d5e1a29afb1ca22ddcdae0d` |
| Marvin-Manual-EN.pdf | 227,298 | `17e0945da7769941b0e0fcf9d5022f0fe18809eef9ce8c34e9b8810a3acd0017` |
| Marvin-Manual-CS.pdf | 222,572 | `7af8336d15952917bfb84255741c8236e341fed2de14f1145a11c25be71d5286` |
| Marvin-Workspace.jpg | 136,523 | `41bdec06fd93e28ab17c53167777f566c9fda995860d93a0781c58ac3055652b` |

## Offline package refresh

`Marvin-Offline-Backup-1.19.0` was refreshed from the installation
(`offline_backup.py refresh --runtime-root %LOCALAPPDATA%\QwenHarness
--exclude-models strata/models/IQ2_XS,strata/packs/iq2_xs --quarantine …`)
and renamed to `Marvin-Offline-Backup-1.20.0`. Only the application files
changed: the 1.20.0 Full installer replaced the 1.19.0 one, and the manuals and
installation guides were updated. The runtime payload (models, llama.cpp, the
prepared Flash-Next engine, its pack and draft layer) was unchanged and nothing
was set aside. The refresh takes the installer from `dist/`, so it already
carries the 1.20.0 Full installer (its digest matches the staged asset) and no
separate `attach-installer` was needed. `offline_backup.py verify` passed for
all 2,948 recorded files (217.8 GiB). The 1.19.0 offline backup does not
exist separately any more: it became this folder.

The public description is `RELEASE-NOTES-1.20.0.md`.

The installers and staged folders of 1.18.2 and 1.19.0 were deleted from
`dist/`; their releases stay on GitHub.

## GitHub publication verification

Published on 8 November 2026 (08:22 UTC) as the latest release:
[Marvin 1.20.0](https://github.com/petrsajner/marvin/releases/tag/v1.20.0).
The release tag points at `e769722`; the application build remains `834ef3b`.
All six uploaded assets are in state `uploaded`, and their sizes and GitHub
SHA-256 digests match `release-1.20.0.json`.
`releases/latest/download/SHA256SUMS.txt` serves the 1.20.0 checksums.
Complete anonymous downloads of the installers were not repeated.
