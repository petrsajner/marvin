# Marvin 1.6.2 - Windows Installation

## New computer

1. Install 64-bit Python 3.12, including the Python Launcher (`py`) and Add Python to PATH. Python is a separate prerequisite, not included in this package.
2. Install a current NVIDIA Windows driver. Use a GPU supported by the model profile selected in Setup. No separate CUDA Toolkit or Node.js installation is required for normal use.
3. Run `Marvin-Setup-1.6.2.exe`. Select the language, destination and models appropriate for the GPU. The default destination is `%LOCALAPPDATA%\QwenHarness`.
4. Leave environment/model setup enabled on a new computer. It creates the Python environment and obtains the selected models and llama.cpp runtime. Internet access is needed unless the matching local backup is used.
5. Start Marvin from the desktop or Start menu. The selected model starts automatically; later launches use the last successfully used model and KV profile.

Start with Qwen Q5 and 8-bit KV on a 32 GB GPU. Model selection in the installer supports smaller GPU profiles. Leave enough free space for the models selected, the application environment and your projects.

## Using the local backup

The separate `QwenHarness-Offline-Backup` directory contains the 1.6.2 installer, all locally available models/projectors, llama.cpp/CUDA runtime and a matching Python package snapshot. Keep the entire folder and its `manifest.json` together. The full backup is approximately 123 GiB; installation size depends on the models restored or selected.

- Run the installer directly from inside the backup directory so it can discover `manifest.json` beside itself.
- Normal setup tries the network first and uses the backup if a component is unavailable online. The backup does not disable internet access.
- To restore the local files first, finish the application installation, then use **Marvin > Set up from offline backup** in the Start menu and select the backup directory.
- Python 3.12 and the NVIDIA driver still need to be installed separately. Have their installers available beforehand if the new computer has no internet access.

## Existing computer

Install over the existing Marvin directory. Existing conversations, projects, memories, user skills and downloaded models remain in place. Do not uninstall or delete the data directory to update. Close Marvin and any running tasks before upgrading.

## Included files

- `Marvin-Setup-1.6.2.exe`: the same installer supports both new installations and updates.
- `Marvin-Manual-EN.pdf` and `Marvin-Manual-CS.pdf`: complete user manuals.
- `INSTALL-EN.md` and `INSTALL-CS.md`: installation instructions.
- `SHA256SUMS.txt`: checksums for the files above.

This distribution does not contain the owner's conversations, projects, personal memories or user skills. Its small ZIP does not contain model weights; those are downloaded or restored from the separate backup.
