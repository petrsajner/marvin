# Marvin 1.8.2: automatic WebView2 setup

At the owner's request, installers were updated under the same 1.8.2 version and public links. The [release manifest](release-1.8.2.json) records current files and SHA-256 values.

## Installation and startup

- Minimal includes Microsoft's Evergreen Bootstrapper (1,783,000 bytes), which downloads and installs WebView2 automatically when a compatible runtime is absent.
- Full also includes the complete Evergreen x64 Standalone Installer (212,745,424 bytes), enabling offline desktop-window setup. Model weights remain separate.
- Existing compatible runtimes are reused. Installation uses the current user context without a separate Microsoft wizard.
- After copying the application, Setup runs the packaged `Marvin.exe --prepare-webview2`. This mode needs no system Python, prepared virtual environment, backend or model. Normal startup calls the same preparation function before creating a window.
- If WebView2 is later removed, recovery prefers the local standalone payload or registered offline backup, then the bootstrapper. A missing/corrupt bootstrapper is downloaded from the pinned source and verified.
- Optional browser tools still require Microsoft Edge. Edge and desktop WebView2 are separate components.

## Implementation and evidence

`harness/webview_runtime.py` checks the stable runtime's `pv` version in both HKCU/HKLM registry views. The minimum version follows the packaged pywebview. Microsoft installers run hidden with `/silent /install`. A process exit code alone does not prove success: a usable registered runtime must appear. A short registration wait covers another updater completing its work; a timeout does not forcibly kill that updater.

`scripts/download_webview2.py` verifies SHA-256 and a valid Microsoft Corporation Authenticode signature at build time. Pinned sources, sizes and signatures are in `installer/webview2.json`. Ordinary builds do not silently substitute a newer payload under an old hash; repinning requires `--refresh`. Hashes are checked again before execution.

366 core checks and 80 service tests passed. Fifteen new tests covered registry detection, reuse without network/payload, offline precedence, Minimal, corrupt files, verified downloads, hidden process flags, delayed registration, false process success, timeout, standalone launcher mode and offline restoration.

Missing-runtime scenarios use controlled tests without modifying shared system WebView2. This host had WebView2 152.0.4191.66; real launcher/installer runs exercised reuse. A clean Windows VM without WebView2 was unavailable, and is not claimed as tested.

Both real upgrades exited 0 (Minimal 21 seconds, Full 76 seconds). All 80 service tests passed in the installed app. Its 75 Python sources, both PDF manuals and both Microsoft payloads matched the distribution. Normal `Marvin.exe` opened the 1.8.2 workspace. Full also passed relocated private-Python checks without system Python, including API startup and llama.cpp DLL loading.

The distribution ZIP contained seven entries with verified CRC/SHA-256. The offline set contained 82 entries; 73 original entries retained sizes, modification times and stored hashes. Offline manifest SHA-256: `0e619dd2e229be830e93a669728faeeddadc7a2af1fe481c096035eb4a24832c`.

[Microsoft's distribution, detection and silent-install guidance](https://learn.microsoft.com/en-us/microsoft-edge/webview2/concepts/distribution).

Inference dependencies, pinned Python packages, llama.cpp, Q3 weights and Q8 KV were unchanged. The offline update replaced the Full installer, guides, manuals, three WebView2 files and manifest; it did not repack weights or the Python snapshot.
