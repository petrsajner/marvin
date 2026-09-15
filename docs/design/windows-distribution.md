# Marvin: Windows distribution

## Layout and isolation

- Minimal keeps the separate Python 3.12 prerequisite and network dependency setup.
- Full contains an app-private CPython 3.12.9 distribution under runtime/python, locked packages under runtime/python-packages and llama.cpp/CUDA under runtime/llama.
- App-local MSVC runtime DLLs are included for the launcher, Python and llama.cpp. No system Python registration, global package installation or system PATH edits are performed.
- Full creates .venv at its final installation path using the private interpreter, not a copied development venv. Bootstrap uses isolated Python (-I), strips conflicting Python environment variables for child validation and disables user-site imports. Desktop and CLI launches strip conflicting Python variables as well.
- An existing incompatible venv is retained in runtime/environment-history; application data and model files are not moved. A failed preparation restores the preceding venv and records runtime/full-setup-error.log.
- Full setup prepares dependencies without network access. Selected models are downloaded unless a complete offline backup is available. NVIDIA drivers remain user-managed. WebView2 is prepared automatically by the frozen launcher during Setup and on normal startup; Minimal includes the Evergreen bootstrapper and Full also includes the complete x64 standalone installer. Existing compatible runtimes are reused. Microsoft Edge remains required for the optional browser tools.
- The installer recognizes an offline manifest beside the EXE or inside a named child backup folder. The first setup restores the local payload before considering online downloads. This restores all models included in the backup, not just checked model choices. Silent installation skips interactive setup; automation explicitly invokes run_setup afterwards.
- Full and Minimal exclude model weights. The complete offline bundle adds models, runtime, one dependency ZIP, Full installer and manuals. Personal development data and rollback backups are excluded from distributable packages.
- An upgrade replaces packaged code and launcher directories while preserving configuration, conversations, projects, memory, user skills, models and environments. Nemotron is text-only and its download path does not require a projector.

## Build and verification

`installer/release.bat` builds both variants, builds the local dependency payload, and runs tests/check_full_runtime.py before compiling Full. package_distribution.ps1 can package both installers with the manuals and installation guides.

The Full runtime test relocates the payload into a fresh directory containing spaces, creates a new venv without system Python discovery, injects invalid PYTHONHOME/PYTHONPATH/PYTHONUSERBASE, and verifies private interpreter paths, disabled user-site packages, imports, Tcl, API/UI startup, pip dependency consistency and llama-server DLL loading. No model inference or download is required for this test.

The test is a relocated runtime check on the current Windows host, not a clean Windows VM installation. Models are intentionally excluded from both installer payloads. Offline backup files are not inputs or outputs of the Full build.

## Current artifacts and installation evidence

Version 1.9.0 adopts the [approved measured profiles](memory-profiles.md), refreshed bilingual manuals and context-only recovery. The existing offline set is updated in place and renamed; unchanged weights, runtime and dependency ZIP are retained.

The preceding 1.8.2 same-version refresh packaged recoverable memory budgets and the external Czech localization catalog. Its verification remains available as historical evidence. See [memory/localization release verification](../distribution/MEMORY-LOCALIZATION-1.8.2.md).

That 1.8.2 refresh also fixed Continue after a manual model/KV switch. See [resume model selection and regression verification](../distribution/CONTINUE-MODEL-1.8.2.md).

The refreshed 1.8.2 installers prepare WebView2 automatically. See [desktop runtime distribution and verification](../distribution/WEBVIEW2-1.8.2.md). Build-time payload signatures and runtime checksums are pinned in `installer/webview2.json`; `scripts/download_webview2.py --refresh` explicitly updates that pin.

The Full installation baseline is recorded in [release 1.8.0](../distribution/RELEASE-1.8.0.md), performance changes in [1.8.1](../distribution/PERFORMANCE-1.8.1.md), and earlier Minimal upgrade/startup checks in [1.8.2](../distribution/STARTUP-RECOVERY-1.8.2.md). Source build staging under `build/` and `dist/Marvin/` is reproducible and is not an installed runtime. Active development dependencies stay in `.venv` and `frontend/node_modules`; generated staging can be removed after final artifacts have been verified.

## Public GitHub downloads

Executable installers are attached to GitHub Releases. Git tracks the source, manuals, preview and release manifest; the Full installer exceeds GitHub's 100 MiB limit for ordinary Git files. See [GitHub's large-file policy](https://docs.github.com/en/repositories/working-with-files/managing-large-files/about-large-files-on-github).

Keep these public asset names across releases so website links remain stable:

- `Marvin-Setup-Full.exe` and `Marvin-Setup-Minimal.exe`
- `Marvin-Windows-x64.zip` (both installers, manuals, guides and checksums)
- `Marvin-Manual-EN.pdf` and `Marvin-Manual-CS.pdf`
- `Marvin-Workspace.jpg` and `SHA256SUMS.txt`

The public installer links use `/releases/latest/download/<asset-name>`. A version-specific link uses `/releases/download/v<version>/<asset-name>`. Create a draft against the application build commit, upload the verified artifacts, compare GitHub's asset digests with the local SHA-256 values, and publish as the latest release only when all assets are ready. Verify downloads without authentication after publication. The preview uses demonstration content, not personal conversations or diagnostic archives.

The [1.9.0 release manifest](../distribution/release-1.9.0.json) records the application commit, sizes, hashes and public URLs. Documentation-only publication commits may follow the application build commit without changing the installer bytes.
