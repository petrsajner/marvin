# Marvin 1.7.0 - Windows Installation

## Minimal and Full

- `Marvin-Setup-1.7.0-Minimal.exe`: small installer. Requires separate 64-bit Python 3.12 with the Python Launcher (`py`). Downloads Python packages and llama.cpp/CUDA during setup.
- `Marvin-Setup-1.7.0-Full.exe`: includes private Python 3.12, locked packages and llama.cpp/CUDA. Does not require system Python. Model weights are not included.

Both variants require supported 64-bit Windows and a user-installed NVIDIA driver. Have Microsoft Edge/WebView2 available for the desktop window and browser tools. A separate CUDA Toolkit or Node.js is not required.

## Steps

1. For Minimal only, install Python 3.12 and enable Add Python to PATH. Skip this step for Full.
2. Run the chosen installer and select language, directory and models appropriate for GPU memory.
3. Full creates a new isolated `.venv` using bundled Python. It does not register Python or change system PATH. Initial preparation can take a little time.
4. Leave model download enabled and finish setup.
5. Start Marvin from the desktop or Start menu. The model starts automatically.

To update, use the existing application directory and close running tasks and Marvin first. Conversations, projects, memories, skills and models remain in place. When replacing a venv with Full, the old environment is retained under `runtime/environment-history`; the new one is created from bundled packages.

## Offline Backup

`QwenHarness-Offline-Backup` remains a separate, unchanged package. Neither installer includes it. Normal model retrieval prefers internet sources; a configured backup is a fallback. Explicit offline-backup setup restores local files first.

The distribution contains no personal data. Both PDF manuals are included in each installer. Both variants download models; the NVIDIA driver remains user-managed.
