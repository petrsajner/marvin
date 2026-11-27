# Marvin 1.23.0 - Windows Installation

Public downloads: **[Full](https://github.com/petrsajner/marvin/releases/latest/download/Marvin-Setup-Full.exe)** · **[Minimal](https://github.com/petrsajner/marvin/releases/latest/download/Marvin-Setup-Minimal.exe)**.
These links follow the latest release. Public assets keep the names `Marvin-Setup-Full.exe` and `Marvin-Setup-Minimal.exe`; local and offline builds also include the version number in their filenames.

## Minimal and Full

- `Marvin-Setup-1.23.0-Minimal.exe`: smaller installer. Requires separate 64-bit Python 3.12 with the Python Launcher (`py`); downloads Python packages, llama.cpp/CUDA, and any missing selected model weights during setup.
- `Marvin-Setup-1.23.0-Full.exe`: includes private Python 3.12, locked packages, validated `llama.cpp` v1.0.0 (`b12359`, CUDA 13.5), Flash-Next's Strata `0.2.17` engine bundle with its packages, and Infernix `2026.11.20` for RTX 50-series GPUs, plus the offline WebView2 runtime. No system Python is required. Only model weights are outside the EXE and downloaded when not already on disk.
- `Marvin-Offline-Backup-1.23.0`: complete local bundle with Full Setup, all included model weights and projectors (Qwen3.8-27B Q2/IQ3/Q4/Q5 + MTP, Flash-Next IQ3_S on Strata + DFlash2, Qwen3.8-27B NVFP4 and Flash-Next IQ3_S on Infernix + DFlash2, speech & semantic-search models), all engines, dependency snapshot, and SHA-256 checksum manifest — installs completely without internet.

Both variants require supported 64-bit Windows and a user-installed NVIDIA driver (580 or newer for Strata and Infernix). WebView2 for the desktop window is detected and prepared automatically. Minimal downloads it if needed; Full includes the complete runtime for offline installation. Microsoft Edge is still required for the optional browser tools. A separate CUDA Toolkit or Node.js is not required.

## Steps

1. For Minimal only, install Python 3.12 and enable Add Python to PATH. Skip this step for Full.
2. Run the chosen installer and select language, directory and models appropriate for GPU memory (12 GB VRAM minimum).
3. Full creates a new isolated `.venv` using bundled Python. It does not register Python or change system PATH. Initial preparation can take a little time.
4. Leave model download enabled and finish setup. Already-downloaded models on disk are kept and verified without re-downloading.
5. Start Marvin from the desktop or Start menu. The model starts automatically.

To update, use the existing application directory and close running tasks and Marvin first. Conversations, projects, memories, skills and models remain in place. Any saved selection of retired Nemotron or Ornith models automatically migrates to Qwen3.8-27B (`q4` / `q5`). When replacing a venv with Full, the old environment is retained under `runtime/environment-history`; the new one is created from bundled packages.

## Offline Backup

Keep the complete offline folder together and run its Full installer directly beside `manifest.json`. Setup recognizes the backup and the first preparation restores local files first. No internet connection, separate Python installation, or repeat download of included models is needed. A complete restore copies all models in the bundle and requires about 250 GB of storage when those files are not already on the destination.

An existing installation can also select a backup through **Set up from offline backup** in the Start Menu or **Settings > Data and backups**. Ordinary online setup uses a registered backup as fallback. Models or components absent from the bundle still have to be obtained separately.

## Flash-Next & Infernix (RTX 50-series / Blackwell)

- **Flash-Next on Strata (all NVIDIA GPUs, 12 GB+ VRAM, 32 GB+ RAM, driver 580+):** optional in the wizard and in **Settings > Model and device**. **IQ3_S** downloads 84.5 GB; **IQ2_XS** downloads 69 GB (~39 GB beside IQ3_S). Marvin uses Strata `0.2.17` with tuned DFlash2 speculative decoding.
- **Infernix (NVIDIA RTX 50-series Blackwell only, `sm_120+`, driver 580+):** optional high-speed models (**Qwen 3.8 27B · NVFP4** at 22.2 GB for 24 GB+ VRAM, and **Qwen 3.8 Flash-Next · IQ3_S** at 85.9 GB + 776 MB drafter for 12 GB+ VRAM). On older NVIDIA GPUs (RTX 20/30/40), these entries stay visible as disabled (greyed-out) items with a Blackwell hardware notice while all `llama.cpp` and Strata models work normally.

The general new-installation default remains Qwen3.8-27B Q5/Q8/192k (automatically stepping down to Q4, IQ3 or Q2 on 24/16/12 GB GPUs). The distribution and offline installation bundle contain no personal chats, projects, or memories. Back those up separately. Both updated PDF manuals are included in each installer. The NVIDIA driver remains user-managed.
