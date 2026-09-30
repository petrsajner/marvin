# Marvin 1.18.2 - a complete local AI workstation

**Marvin is built around a top-tier local AI engine:** measured GPU profiles
with an honest recovery ladder, MTP speculative decoding, durable jobs that
survive interruptions, live steering that protects the prompt cache, a per-file
change journal with one-click restore, document intelligence for Word, PDF and
Excel, a research ledger with citations, memory and decisions that follow you
across chats, dictation, and an offline installer with a verified backup.

**That engine comes with the tools to finish real work.** One Windows workspace
brings together **Discussion → Research → Writing → Development → Computer**.
Read a document, research a question, write a finished result, build an
application or work with the screen, while keeping the conversation, files,
progress and results together.

This release carries forward the complete workstation described in **1.17.4**
and adds all changes through **1.18.2**. **Upgrade 1.18.0 installations to this
version:** it corrects the black startup window and the recovery issues found
during the review of that update.

![Marvin 1.18.2 workspace](https://raw.githubusercontent.com/petrsajner/marvin/v1.18.2/docs/images/Marvin-Workspace.jpg)

## See the work, trust the changes, keep control

### Know what changed

Finished work can include a **What I changed** card: a plain sentence for each
file, a **Restore** button, and the technical diff when you want it. Restore
points and the task journal keep file recovery close to the work. Destructive
workspace actions such as reverting a task use the application's confirmation
dialog.

![A file change card](https://raw.githubusercontent.com/petrsajner/marvin/v1.18.2/docs/images/Marvin-ChangeCard.jpg)

### See the result while Marvin builds it

The **Preview** panel shows a generated web page or application live and
refreshes as the work changes. A background process that announces its address
gets a **The app is running at …** card with Open and Stop controls.

**Test and fix** completes the loop: open the application, exercise its main
controls, inspect console and network errors, attempt repairs and verify them,
then present a test report with pass/fail checks. The protocol allows up to
three repair rounds.

![Live application preview](https://raw.githubusercontent.com/petrsajner/marvin/v1.18.2/docs/images/Marvin-Preview.jpg)

### Start with a useful task

An empty conversation offers **ready tasks** for documents, pictures, research,
programming and exporting a result. The capability catalogue is beside Attach.
Dictation puts spoken words in the composer. **Plan first** lets you ask for a
plan and approve it before the first file change. **Simple** settings hold the
everyday controls; **Advanced** adds the technical ones.

![Ready tasks in a new conversation](https://raw.githubusercontent.com/petrsajner/marvin/v1.18.2/docs/images/Marvin-Welcome.jpg)

## Everything added since 1.17.4

### Faster answers, with an MTP switch you can see

**Speculative decoding (MTP)** now has a dedicated switch in **both Simple and
Advanced settings**. The KV cache menu lists the base profiles; the switch
adds or removes the matching MTP variant. Profiles without a supported variant
show that MTP is unavailable.

The small draft model is downloaded and SHA-256 verified on first use. On the
measured RTX 5090 cases, MTP delivered **2.2–2.9× faster structured output** and
**1.6–1.8× faster natural-text decoding**, with roughly **1.9–2.9 GiB** of extra
GPU allocation depending on the profile. These are measured cases, not a
guarantee for every task or machine. MTP remains opt-in.

![The visible MTP switch](https://raw.githubusercontent.com/petrsajner/marvin/v1.18.2/docs/images/Marvin-MTP.jpg)

[Measurement details and supported profiles](https://github.com/petrsajner/marvin/blob/v1.18.2/docs/design/mtp-profiles.md)

### A memory event no longer changes your selection

- The selected profile and the profile that actually runs are recorded
  separately. Recovery can drop the draft or reduce context while keeping
  your original choice for a later model start.
- If recovery turns MTP off, the activity history explains it and offers
  **Turn MTP back on**. With a task running, that selection applies to the next
  task; with no task running, the model can start with it immediately.
- Following tasks continue with the working recovery profile instead of
  repeatedly restarting just because it differs from the original request.
- Changing the GPU budget and switching back recalls the requested profile.
  An explicit profile selection in the same settings update takes priority.

### Profile changes during a task are respected

The review also found two edge cases in the first MTP update. Recovery could
mistake a selection changed during the task for the request it was already
serving; a new model start could retain an obsolete request marker.

**1.18.2 fixes both.** Recovery follows the active task's captured request, the
next task applies your new choice, and an explicit model request records the
new selection correctly. A matching running profile can still be reused without
an unnecessary restart. Invalid model requests also reach a failure state
instead of leaving startup permanently in progress.

### The workspace opens reliably

The black window in 1.18.0 came from reading application state before it had
arrived. The interface now renders its loading screen safely, opens the selected
conversation when ready, and can show an API error instead of crashing to an
empty window. Browser checks cover a delayed response, an API failure and a
successful reload.

### One application window in the taskbar

Startup used to restore every desktop window whose title contained Marvin.
That could expose the normally hidden **GDI+ Window** and raise unrelated
windows. The launcher now focuses the exact WebView window it created, using
its native Windows handle. The hidden helper stays hidden.

### Distribution and offline recovery

- Release staging and Full-runtime checks work on filesystems such as exFAT
  that do not support hard links.
- Application, installer, npm version metadata and manual versions agree on
  **1.18.2**.
- The offline package is refreshed as **Marvin-Offline-Backup-1.18.2** with the
  new Full installer and both manuals. The old 1.18.0 installer was removed.
- The recorded backup path now follows the renamed folder, including the
  installed application's path after the project moved to a different drive.
- All **97 retained payload files** matched their previous records, sizes and
  modification times. Updated-file hashes were checked, and the dependency
  archive successfully restored into a fresh environment.
- The gallery was refreshed with English demonstration content from 1.18.2.

<details>
<summary><strong>Simple and Advanced settings</strong></summary>

![Simple settings](https://raw.githubusercontent.com/petrsajner/marvin/v1.18.2/docs/images/Marvin-Settings.jpg)

![Advanced settings](https://raw.githubusercontent.com/petrsajner/marvin/v1.18.2/docs/images/Marvin-SettingsAdvanced.jpg)

</details>

## Installing

- **Full - recommended for a new PC:** private Python 3.12, locked Python
  packages, llama.cpp/CUDA libraries and offline WebView2 setup. Model weights
  are downloaded separately or restored from an offline backup.
- **Minimal:** application update for an existing prepared environment. A fresh
  installation requires separately installed 64-bit Python 3.12 and environment
  setup.
- Installer upgrades preserve existing chats, projects, models and preferences.

The release includes both installers, **English and Czech manuals**, the
workspace preview and **SHA256SUMS.txt**. The gallery above shows demonstration
content in the actual application interface.

## Verification

**371 unittest tests and 361 core checks passed**, together with localization
checks and the production frontend build. Browser checks cover startup and the
MTP controls. A probe with real WinForms windows verified that only the main
window is restored while matching-title helpers remain hidden.

The Full runtime passed its isolated private-Python, locked-dependency and DLL
checks. The refreshed offline package restored dependencies into a fresh venv
and served the application API and compiled UI. An actual Minimal upgrade
completed successfully; all **15 original conversation files** kept their
pre-upgrade SHA-256 values.
