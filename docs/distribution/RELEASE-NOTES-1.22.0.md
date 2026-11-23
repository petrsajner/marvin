## Highlights

- **3-step moved project folder recovery & Git/GitHub restoration:**
  1. **Automatic discovery & redirection:** Marvin now records credential-free Git repository identity (`origin` URL, branch, and root commit hash) in `projects.json`. When a project directory is moved to another folder or another drive, Marvin automatically scans local fixed/removable drives and nearby project roots (skipping network shares and OS directories), verifies Git identity (rejecting same-name decoy folders and handling renames), and transparently redirects the project, all conversation histories, pinned files, and full-text SQLite search indexes.
  2. **Windows Explorer folder picker & creator:** If a moved folder cannot be found automatically, Marvin opens a guided recovery dialog (and inline workspace banner) letting you either choose an existing folder or select/create a new folder directly in Windows Explorer — also available proactively anytime via **Project actions → Change project folder…**.
  3. **Non-destructive GitHub & local Git restoration:** When setting up a new folder, Marvin pre-fills the saved GitHub/Git remote URL and restores both the remote connection and local repository safely without overwriting existing files (`git clone` into an empty folder; `git init` + `origin` + non-destructive `git fetch` into a non-empty folder; `git init` for local-only projects; or adding `origin` to an existing repo).
- **Speculative decoding status badges for Strata and Infernix:**
  - The top model status button and **Settings → Model and device** now clearly display active built-in speculative decoding (**`DFlash2`** on Strata and Flash-Next Infernix, **`DFlash2 + n-gram`** on Qwen 3.8 27B Infernix, and **`MTP`** on `llama.cpp`), so it is always visible what acceleration is active.
- **Includes everything from Marvin 1.21.0:**
  - `llama.cpp v1.0.0 (b12359)`, Strata `0.2.17` (`0.1.63` + DFlash2), Infernix `2026.11.20` for NVIDIA RTX 50-series (Blackwell), measured 12 GB GPU floor, and greyed-out Blackwell visibility on RTX 20/30/40 GPUs.

## Downloads & Updating

- **`Marvin-Setup-Full.exe`**: complete self-contained environment — private Python 3.12, locked packages, validated `llama.cpp v1.0.0 (b12359)`, offline Strata `0.2.17` bundle, offline Infernix `2026.11.20` archive, and offline WebView2. Only model weights are downloaded when not already on disk.
- **`Marvin-Setup-Minimal.exe`**: lightweight installer (requires separately installed 64-bit Python 3.12); downloads packages, `llama.cpp`, and missing selected weights automatically.
- Conversations, projects, memories, skills, and existing model weights remain intact on upgrade.
- See [SHA256SUMS.txt](https://github.com/petrsajner/marvin/releases/download/v1.22.0/SHA256SUMS.txt) and the included English / Czech PDF manuals.
