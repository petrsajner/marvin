# Release record: Marvin 1.22.0

23 November 2026. Added 3-step moved project folder recovery with automatic discovery, native Windows Explorer selection/creation, and non-destructive Git/GitHub restoration, plus speculative decoding status badges (`DFlash2` / `DFlash2 + n-gram` / `MTP`) for Strata and Infernix models.

## Highlights

- **3-step moved project folder recovery (`harness/projects.py`, `harness/application.py`, `harness/web_api.py`, React UI):**
  - Stores credential-free Git repository identity (`git_remote`, `git_branch`, `git_root_commit`) in `projects.json`.
  - **Step 1 (Automatic discovery):** Scans local fixed/removable drives and nearby project roots (skipping network shares and OS/cache trees), verifies Git identity (rejecting decoy same-name repos and supporting folder renames), and automatically redirects `projects.json`, all `sessions/*/meta.json` (including pinned files), and the SQLite FTS `HistoryIndex`.
  - **Step 2 (Windows Explorer picker):** When automatic discovery cannot find the moved folder, opens a guided recovery modal (plus inline banner above the composer and proactive **Change project folder…** action) backed by the native Windows Explorer dialog to choose an existing folder or create a new one.
  - **Step 3 (Git/GitHub restoration):** Non-destructively restores GitHub/remote connectivity and local Git in a new folder (`git clone` into empty folders; `git init` + `remote add origin` + `git fetch` in non-empty folders; `git init` for local-only projects; or adding `origin` to an existing repo).
- **Speculative decoding visibility (`e9fc8c7`):**
  - Displays active built-in speculative decoding (`DFlash2`, `DFlash2 + n-gram`, or `MTP`) in the header model status button and in **Settings -> Model and device** for Strata and Infernix models.

## Validation

- Automated test suites: `tests/test_core.py` **365/365 OK**, `tests.test_project_relocation` **10/10 OK**, `tests.test_localization` **13/13 OK**, `tests.test_infernix_backend` **20/20 OK**, plus `tests.test_workspace`, `tests.test_autocommit`, and `tests.test_history_recovery` all passed.
- Relocated Full runtime verification (`tests/check_full_runtime.py`): passed with system Python disabled, verifying private Python 3.12, locked packages, `llama.cpp` build `12359`, bundled Strata `0.2.17`, and bundled Infernix `2026.11.20`.
- Local installation (`%LOCALAPPDATA%\QwenHarness`) upgraded via `Marvin-Setup-1.22.0-Full.exe /VERYSILENT /NORESTART`, Strata `0.2.17` and Infernix `2026.11.20` unpacked offline from bundled payloads, and verified `APP_VERSION == "1.22.0"`.

## Release Assets

Staged in `dist/release-1.22.0/` and recorded in `release-1.22.0.json` (application build commit `74660a2`):

| File | Bytes | SHA-256 |
|---|---:|---|
| Marvin-Setup-Minimal.exe | 54,171,148 | `5b58b2f68d748dea2e4a41ff59a847d601cb03b9b564cc9337f697a0a8f67491` |
| Marvin-Setup-Full.exe | 1,807,447,589 | `2b3ebd99ce6054b77ca1f5ab9bf76cbf57c86382495e5562f278015e1f073795` |
| Marvin-Manual-EN.pdf | 227,679 | `542a91a44af7038ece4987bf05cbdc7e5ec972825ac32acf1e59adfcfffa68da` |
| Marvin-Manual-CS.pdf | 223,080 | `10f0c352693ee7b4c680240606d8dd5a0c1b72543674eed9e8aa775f4783e4d2` |
| Marvin-Workspace.jpg | 136,523 | `41bdec06fd93e28ab17c53167777f566c9fda995860d93a0781c58ac3055652b` |
| SHA256SUMS.txt | 445 | `1703537e6c57c649d3f019e1d030215c46f87828587e358ccbfe1cbc07dd216b` |

## Offline Package Refresh

`Marvin-Offline-Backup-1.21.0` was refreshed from the upgraded installation (`offline_backup.py refresh --runtime-root %LOCALAPPDATA%\QwenHarness --exclude-models strata/models/IQ2_XS,strata/packs/iq2_xs,strata/conversation-spill`) and automatically renamed to `Marvin-Offline-Backup-1.22.0`:

- Replaced `Marvin-Setup-1.21.0-Full.exe` with `Marvin-Setup-1.22.0-Full.exe` and updated manuals and installation guides.
- `offline_backup.py verify` passed for all **3,496** recorded files (0 errors).
- Superseded `1.21.0` installers and staging directory were deleted after verification.
