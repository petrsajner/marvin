# Marvin 1.19.0 - Windows Installation

Public downloads: **[Full](https://github.com/petrsajner/marvin/releases/latest/download/Marvin-Setup-Full.exe)** · **[Minimal](https://github.com/petrsajner/marvin/releases/latest/download/Marvin-Setup-Minimal.exe)**.
These links follow the latest release. Public assets keep the names `Marvin-Setup-Full.exe` and `Marvin-Setup-Minimal.exe`; local and offline builds also include the version number in their filenames.

## Minimal and Full

- `Marvin-Setup-1.19.0-Minimal.exe`: smaller installer. Requires separate 64-bit Python 3.12 with the Python Launcher (`py`); prepares packages and llama.cpp/CUDA during setup.
- `Marvin-Setup-1.19.0-Full.exe`: includes private Python 3.12, locked packages, and validated llama.cpp/CUDA b10935 and Flash-Next's model engine with its packages, so Flash-Next is prepared without downloading them. No system Python is required. The EXE itself does not include model weights.
- `Marvin-Offline-Backup-1.19.0`: complete local bundle with Full Setup, all included models and projectors including Flash-Next and its model engine, runtime, dependency snapshot, and checksum manifest.

Both variants require supported 64-bit Windows and a user-installed NVIDIA driver. WebView2 for the desktop window is detected and prepared automatically. Minimal downloads it if needed; Full includes the complete runtime for offline installation. No Microsoft website or separate WebView2 installation is required. Microsoft Edge is still required for the optional browser tools. A separate CUDA Toolkit or Node.js is not required.

## Steps

1. For Minimal only, install Python 3.12 and enable Add Python to PATH. Skip this step for Full.
2. Run the chosen installer and select language, directory and models appropriate for GPU memory.
3. Full creates a new isolated `.venv` using bundled Python. It does not register Python or change system PATH. Initial preparation can take a little time.
4. Leave model download enabled and finish setup.
5. Start Marvin from the desktop or Start menu. The model starts automatically.

To update, use the existing application directory and close running tasks and Marvin first. Conversations, projects, memories, skills and models remain in place, including Flash-Next's weights and prepared files: the wizard keeps already downloaded models checked, the setup verifies them instead of downloading them again, and Marvin prepares only what is still missing (for an update from 1.18 or earlier, Flash-Next's model engine, about 0.7 GB, on its first start). When replacing a venv with Full, the old environment is retained under `runtime/environment-history`; the new one is created from bundled packages.

## Offline Backup

Keep the complete offline folder together and run its Full installer directly beside `manifest.json`. Setup recognizes the backup and the first preparation restores local files first. No separate Python installation or repeat download of included models is needed. A complete restore copies all models in the bundle and requires over 200 GB of storage when those files are not already on the destination.

An existing installation can also select a backup through **Set up from offline backup** in the Start Menu or **Settings > Data and backups**. Ordinary online setup uses a registered backup as fallback. Models or components absent from the bundle still have to be obtained separately.

## Flash-Next

Flash-Next is optional in the wizard and is never checked automatically. It can also be selected later in **Model and device**. **IQ3_S** downloads 84.5 GB; **IQ2_XS** downloads 69 GB (about 39 GB beside IQ3_S, with which it shares two files) and answers faster on PCs with 48 or 32 GB of RAM. Both need an NVIDIA card with 16 GB or more, 32 GB of RAM or more and driver 580 or newer, and offer 256k and 128k context. On its first start Marvin prepares the model's engine and files (about 7 GB more, including a 5 GB download). See the manual for measured speeds. The general new-installation default remains Qwen Q5/Q8/192k.

The distribution and offline installation bundle contain no personal chats, projects, or memories. Back those up separately. Both updated PDF manuals are included in each installer. The NVIDIA driver remains user-managed.
