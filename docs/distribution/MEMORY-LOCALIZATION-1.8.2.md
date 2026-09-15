# Marvin 1.8.2: memory and localization installer refresh

15 September 2026. Application source: `ed6daf56436b831fcf967a553b220e756edb526c`, including memory-profile commit `e7e0fa7` and English-source/localization commit `a4b233e`. The owner requested all installers and packages while retaining the existing version number.

## Delivered packages

Minimal, Full and the combined Windows ZIP were rebuilt. Both manuals describe memory-budget switching, compact profiles, pressure recovery and the measured Flash-Next limits. The English manual has 26 pages and the Czech manual 21. Updated tables and memory sections on pages 7–8 were rendered and visually checked in both languages.

| Local file in `dist/` | Bytes | SHA-256 |
|---|---:|---|
| `Marvin-Setup-1.8.2-Minimal.exe` | 54,025,679 | `6254f7fc94c07fafcd51d72a7073acd95fba96568f714af16eb7cbce0a485d22` |
| `Marvin-Setup-1.8.2-Full.exe` | 941,475,299 | `46d47f52804f27b516a29259a40ab727d7617cfa77277b4e3319123266aa83a1` |
| `Marvin-1.8.2-Windows-x64.zip` | 994,721,379 | `84d5015403687a9a9de5dce3408eb3e80cd2884fe9d6e906a697ca6c04d8f88b` |

The ZIP contains seven entries: both installers, both manuals, both installation guides and its checksum list. All entry CRCs and SHA-256 values passed verification. The [release manifest](release-1.8.2.json) maps public asset names to these artifacts and identifies the exact source commit for the refreshed binaries. The existing release tag and version number are retained; the manifest and release description identify the newer build commit explicitly.

## Build and installation evidence

- The production frontend built successfully. All 366 core checks and 102 service/localization tests passed in the source environment.
- Full contains a private Python 3.12.9 runtime and 11,533 locked package files. A relocated environment with spaces in its path passed bootstrap, repeated bootstrap, imports, API/UI startup, dependency checks and llama.cpp DLL loading, with system Python discovery disabled and conflicting Python environment variables injected.
- Real upgrades of the existing installation exited 0: Minimal in 8.67 seconds and Full in 61.39 seconds.
- After each upgrade, all 706 recorded user-data files were byte-identical. Ninety-nine Python source files, the launcher, compiled frontend, both PDFs and the shared localization catalog matched the build. The catalog was present in both the normal package and frozen launcher resources.
- Each installed variant passed the service suite: 102 discovered tests, 99 executed successfully and three source-tree-only checks correctly skipped. Installed tests do not require the repository's frontend sources or installer build definitions.
- The installed application started normally with Qwen Q5/Q8/192k. Read-only checks returned HTTP 200 for application state, runtime state and the selected conversation. Because the normal application was already running, the separate smoke launcher was not invoked; the existing application was left running.
- A fresh temporary environment restored the offline dependency snapshot, matched the lock, and opened the API/compiled UI without personal data.

These checks used the current Windows host, not a clean Windows VM. Physical 16/24 GB GPU performance is not newly qualified by this packaging run. See [memory profiles](../design/memory-profiles.md) for actual model tests and their limits. Python dependency versions, llama.cpp, model weights, Q3 precision and Q8 KV policy were not changed during packaging.

## Offline update

`Marvin-Offline-Backup-1.8.2/` retains all 82 manifest entries. Four files changed: the Full installer, English PDF, Czech PDF and offline README. The manifest was updated atomically and now records the application commit. All four changed files passed complete SHA-256 verification. The other 78 entries retained their sizes, modification times and stored hashes; weights, inference runtime, WebView2 payloads and the Python snapshot were not recopied or repacked.

Updated offline manifest SHA-256: `bc581d6cfed890e1f6b9c11c0d86a525ec659422578b4798867e9daaf03c93a1`. The dependency archive was actually restored during distribution validation. Unchanged model weights were not rehashed in this refresh; their prior verification records and unchanged file metadata were retained.

The offline folder contains model weights and is intended for copying to another drive or PC. It is separate from the smaller public Windows ZIP, whose installers download or restore weights during setup.
