# Marvin 1.18.2 - startup, MTP and desktop fixes

This release corrects the black startup window in 1.18.0 and fixes profile
selection during memory recovery. It also prevents a hidden graphics helper
from appearing beside the application in the taskbar.

![Marvin workspace](https://raw.githubusercontent.com/petrsajner/marvin/main/docs/images/Marvin-Workspace.jpg)

## Changes

- **The workspace opens safely.** It shows its loading screen while application
  state is arriving, then loads the selected conversation. A missing initial
  state no longer crashes the interface.
- **Profile changes apply to the intended task.** Memory recovery continues the
  current task with its captured selection. A different selection made during
  that task is applied to the next task.
- **New profile requests replace old recovery intent.** The model controller
  records the new selection correctly, including when it can reuse an already
  running matching profile without restarting.
- **Startup focuses the main window.** The launcher uses the created WebView's
  native handle. It no longer restores hidden graphics helpers or other windows
  whose titles happen to contain Marvin.

## Installation

Upgrade installations running 1.18.0 to 1.18.2. Existing chats and model files
are retained.

- **Full:** private Python 3.12, locked Python packages, llama.cpp/CUDA libraries
  and offline WebView2 setup. Model weights are downloaded separately or restored
  from an existing offline backup.
- **Minimal:** application update for a prepared environment; a fresh installation
  requires separately installed 64-bit Python 3.12 and environment setup.

English and Czech manuals, the workspace preview and `SHA256SUMS.txt` are included
with the release assets.

## Validation

371 unittest tests and 361 core checks passed, together with the production
frontend build and browser startup/MTP checks. A native WinForms probe verified
that the main window is restored while matching-title helper windows stay hidden.
The Full runtime passed its isolated private-Python and DLL checks. The updated
offline package restored locked dependencies into a fresh environment and served
the application API and compiled UI.
