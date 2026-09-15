# Marvin 1.9.0 - Windows Installation

Public downloads: **[Full](https://github.com/petrsajner/marvin/releases/latest/download/Marvin-Setup-Full.exe)** · **[Minimal](https://github.com/petrsajner/marvin/releases/latest/download/Marvin-Setup-Minimal.exe)**.
These links follow the latest release. Public assets keep the names `Marvin-Setup-Full.exe` and `Marvin-Setup-Minimal.exe`; local and offline builds also include the version number in their filenames.

## Minimal and Full

- `Marvin-Setup-1.9.0-Minimal.exe`: smaller installer. Requires separate 64-bit Python 3.12 with the Python Launcher (`py`); prepares packages and llama.cpp/CUDA during setup.
- `Marvin-Setup-1.9.0-Full.exe`: includes private Python 3.12, locked packages, and validated llama.cpp/CUDA b10935. No system Python is required. The EXE itself does not include model weights.
- `Marvin-Offline-Backup-1.9.0`: complete local bundle with Full Setup, all included models and projectors including Flash-Next, runtime, dependency snapshot, and checksum manifest.

Both variants require supported 64-bit Windows and a user-installed NVIDIA driver. WebView2 for the desktop window is detected and prepared automatically. Minimal downloads it if needed; Full includes the complete runtime for offline installation. No Microsoft website or separate WebView2 installation is required. Microsoft Edge is still required for the optional browser tools. A separate CUDA Toolkit or Node.js is not required.

## Steps

1. For Minimal only, install Python 3.12 and enable Add Python to PATH. Skip this step for Full.
2. Run the chosen installer and select language, directory and models appropriate for GPU memory.
3. Full creates a new isolated `.venv` using bundled Python. It does not register Python or change system PATH. Initial preparation can take a little time.
4. Leave model download enabled and finish setup.
5. Start Marvin from the desktop or Start menu. The model starts automatically.

To update, use the existing application directory and close running tasks and Marvin first. Conversations, projects, memories, skills and models remain in place. When replacing a venv with Full, the old environment is retained under `runtime/environment-history`; the new one is created from bundled packages.

## Offline Backup

Keep the complete offline folder together and run its Full installer directly beside `manifest.json`. Setup recognizes the backup and the first preparation restores local files first. No separate Python installation or repeat download of included models is needed. A complete restore copies all models in the bundle and requires over 200 GB of storage when those files are not already on the destination.

An existing installation can also select a backup through **Set up from offline backup** in the Start Menu or **Settings > Data and backups**. Ordinary online setup uses a registered backup as fallback. Models or components absent from the bundle still have to be obtained separately.

## Flash-Next

Flash-Next is optional in the wizard and is not automatically checked for a fresh online installation. It can also be selected later in **Model and device**. It downloads approximately 90.9 GB and uses Q3 weights, Q8 KV, and 128k to 256k context according to available RAM/VRAM. See the manual for measured results and limits. The general new-installation default remains Qwen Q5/Q8/192k.

The distribution and offline installation bundle contain no personal chats, projects, or memories. Back those up separately. Both updated PDF manuals are included in each installer. The NVIDIA driver remains user-managed.
