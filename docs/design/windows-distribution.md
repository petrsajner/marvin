# Marvin 1.8.0: Windows distribution

## Layout and isolation

- Minimal keeps the separate Python 3.12 prerequisite and network dependency setup.
- Full contains an app-private CPython 3.12.9 distribution under runtime/python, locked packages under runtime/python-packages and llama.cpp/CUDA under runtime/llama.
- App-local MSVC runtime DLLs are included for the launcher, Python and llama.cpp. No system Python registration, global package installation or system PATH edits are performed.
- Full creates .venv at its final installation path using the private interpreter, not a copied development venv. Bootstrap uses isolated Python (-I), strips conflicting Python environment variables for child validation and disables user-site imports. Desktop and CLI launches strip conflicting Python variables as well.
- An existing incompatible venv is retained in runtime/environment-history; application data and model files are not moved. A failed preparation restores the preceding venv and records runtime/full-setup-error.log.
- Full setup prepares dependencies without network access. Selected models are downloaded unless a complete offline backup is available. NVIDIA drivers remain user-managed; supported Windows with Edge/WebView2 is the desktop/browser baseline.
- The installer recognizes an offline manifest beside the EXE or inside a named child backup folder. The first setup restores the local payload before considering online downloads. This restores all models included in the backup, not just checked model choices. Silent installation skips interactive setup; automation explicitly invokes run_setup afterwards.
- Full and Minimal exclude model weights. The complete offline bundle adds models, runtime, one dependency ZIP, Full installer and manuals. Personal development data and rollback backups are excluded from distributable packages.
- An upgrade replaces packaged code and launcher directories while preserving configuration, conversations, projects, memory, user skills, models and environments. Nemotron is text-only and its download path does not require a projector.

## Build and verification

`installer/release.bat` builds both variants, builds the local dependency payload, and runs tests/check_full_runtime.py before compiling Full. package_distribution.ps1 can package both installers with the manuals and installation guides.

The Full runtime test relocates the payload into a fresh directory containing spaces, creates a new venv without system Python discovery, injects invalid PYTHONHOME/PYTHONPATH/PYTHONUSERBASE, and verifies private interpreter paths, disabled user-site packages, imports, Tcl, API/UI startup, pip dependency consistency and llama-server DLL loading. No model inference or download is required for this test.

The test is a relocated runtime check on the current Windows host, not a clean Windows VM installation. Models are intentionally excluded from both installer payloads. Offline backup files are not inputs or outputs of the Full build.

## Current artifacts and installation evidence

The current artifact hashes, actual upgrade outcome and offline checks are recorded in [release 1.8.0](../distribution/RELEASE-1.8.0.md). Source build staging under `build/` and `dist/Marvin/` is reproducible and is not an installed runtime. Active development dependencies stay in `.venv` and `frontend/node_modules`; generated staging can be removed after final artifacts have been verified.
