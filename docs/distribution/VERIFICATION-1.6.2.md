# Distribution verification: Marvin 1.6.2

Date: 2026-09-06.

## Distribution

- `dist/Marvin-1.6.2-Windows-x64.zip`, 15,418,841 bytes.
- SHA256: `e8ee047ed6cb33eeaf02f5c3671c381989aa8f6b5c19d18d1272ffa806ed2ca9`.
- Six files: installer, Czech/English manuals, Czech/English installation guides, SHA256SUMS.txt.
- ZIP CRC and all five payload checksums passed.
- Installer 1.6.2 was built by the release pipeline: 366 core tests, 21 workspace tests, TypeScript/Vite, PDF generation, PyInstaller and Inno Setup.

## Refreshed local backup

- `QwenHarness-Offline-Backup/manifest.json`: format 2, app version 1.6.2.
- 70 tracked files, 131,913,972,302 bytes (approximately 122.85 GiB).
- All eight existing GGUF models/projectors, llama.cpp/CUDA runtime, current installer, requirements and Windows/Python 3.12 dependency lock.
- Python snapshot refreshed from the local environment: 13,853 files.
- Every file passed SHA-256 verification; no missing or mismatched files.
- No model or package download was needed for backup creation or restore validation.
- The replacement was built and verified beside the original, then moved to the original backup path. The old copy remains in `QwenHarness-Offline-Backup-previous-1.5.3` because removal was blocked by the execution environment.

## Fresh environment check

`tests/check_distribution.py` created an empty Python 3.12 virtual environment, restored only the backed-up dependencies, checked all locked package versions, loaded the staged application API and compiled frontend, and confirmed that no owner projects or conversations were present. All checks passed; temporary test data was cleaned up.

This is a clean virtual-environment/staged-application check on the current Windows host, not an installation run inside a clean Windows virtual machine. Python 3.12 and the NVIDIA driver remain separate prerequisites.

## Reproduction

- Build application and installer: `installer/release.bat`.
- Package the small distribution: `scripts/package_distribution.ps1`.
- Verify backup: `python scripts/offline_backup.py verify --backup QwenHarness-Offline-Backup`.
- Verify ZIP and fresh dependency restoration: `python tests/check_distribution.py --backup QwenHarness-Offline-Backup`.

Installers, ZIP files, model weights, dependency archives and user data remain local and are intentionally excluded from Git.
