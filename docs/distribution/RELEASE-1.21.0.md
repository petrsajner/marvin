# Release record: Marvin 1.21.0

22 November 2026. Upgraded universal inference runtimes (`llama.cpp` v1.0.0 `b12359` and Strata `v0.2.17` with DFlash2), added measured 12 GB GPU profiles, retired low-intelligence models (`ornith_q5`, `nemotron_q4`, `nemotron_q5`), and added the Blackwell-accelerated **Infernix** backend (`windows-2026.11.20`) with greyed-out visibility on non-Blackwell GPUs.

## Highlights

- **Universal backends (RTX 20/30/40/50, 12 GB+ VRAM):**
  - `llama.cpp` upgraded from `b10935` to `v1.0.0` (`b12359`, CUDA 13.5).
  - Strata upgraded from `v0.1.39` to `v0.2.17` (engine `0.1.63`, bundled `cublas64_13.dll`, tuned DFlash2 drafter; drops ~500 MB of duplicate NVIDIA CUDA wheels from the Full installer).
  - Measured 12 GB GPU profiles added for `q2` (`Qwen3.8-27B Q2_K_XL`), `flash_next_strata`, and `flash_next_strata_iq2`.
  - Retired `ornith_q5`, `nemotron_q4`, and `nemotron_q5` with automatic migration to `q5` / `q4` in `REPLACED_MODELS`.
- **Infernix backend (NVIDIA RTX 50-series Blackwell, `sm_120+`, driver 580+):**
  - `qwen27b_infernix`: `Qwen3.8-27B-NVIDIA-NVFP4-QAD-Infernix-Exact` (22.2 GB, `--embedding-host --host-context-mib 4096`, DFlash2 + n-gram draft, 24-96 GB Blackwell GPUs).
  - `flash_next_infernix`: `Qwen3.8-Flash-Next-GSQ-RCO-IQ3_S-Infernix` (85.9 GB) + `Qwen3.8-Flash-Next-DFlash2-Infernix` (776 MB, `--expert-ram-layout exclusive`, 12-96 GB Blackwell GPUs).
  - On non-Blackwell GPUs, both Infernix entries stay visible as disabled (greyed-out) items in the Web UI model picker and Inno Setup wizard with a Blackwell hardware notice; API selection returns HTTP 400.

## Validation

- Full test suite: `tests/test_core.py` **365/365 OK**, `tests.test_localization` **13/13 OK**, `tests.test_infernix_backend` **19/19 OK**, and `unittest discover` **532/533 OK** (the single failure is the known headless desktop window enumeration check).
- Relocated Full runtime verification (`tests/check_full_runtime.py`): passed with system Python disabled, verifying private Python 3.12, locked packages, `llama.cpp` build `12359`, bundled Strata `0.2.17`, and bundled Infernix `2026.11.20` checksum.
- Installed copy (`%LOCALAPPDATA%\QwenHarness`) upgraded via `Marvin-Setup-1.21.0-Full.exe /VERYSILENT /NORESTART`, Strata `0.2.17` and Infernix `2026.11.20` installed completely offline from bundled payloads, and live 4-model smoke test passed on RTX 5090 (64 GB RAM):
  - `q5` (`llama.cpp b12359`): loaded in 17 s, answered `42`, clean stop.
  - `flash_next_strata` (`Strata 0.2.17` + `drafting=dflash2`): loaded in 29 s, answered `42`, clean unload & stop.
  - `qwen27b_infernix` (`Infernix 2026.11.20`): loaded in 7 s, answered `42`, clean stop.
  - `flash_next_infernix` (`Infernix 2026.11.20` + DFlash2): loaded in 25 s, answered `42`, clean stop.

## Release Assets

Staged in `dist/release-1.21.0/` and recorded in `release-1.21.0.json` (application build commit `40239db`):

| File | Bytes | SHA-256 |
|---|---:|---|
| Marvin-Setup-Minimal.exe | 54,159,652 | `5948c29ac29a2d7f5b3239728c2feea3d8c2de5b464941e67938ff19e80c95c0` |
| Marvin-Setup-Full.exe | 1,807,429,923 | `2384008439bdabd155150e47c53042f2ea7328dcea584b1e5aa62cf87f9cd439` |
| Marvin-Manual-EN.pdf | 227,680 | `7d8a6d30f729d92b1aaa4edd67812de021db271b80e62d3a611238db8ceb3680` |
| Marvin-Manual-CS.pdf | 223,081 | `3b7231d8c0c4f72903951c04c9b5f85abd26a09c76625c1f454d9e26e30f262e` |
| Marvin-Workspace.jpg | 136,523 | `41bdec06fd93e28ab17c53167777f566c9fda995860d93a0781c58ac3055652b` |
| SHA256SUMS.txt | 445 | `7f83ea17a3e25ee6e328cc671b0ae83d3e1ae21a70c09df6137b7d73601760a1` |

## Offline Package Refresh

`Marvin-Offline-Backup-1.20.0` was refreshed from the upgraded installation (`offline_backup.py refresh --runtime-root %LOCALAPPDATA%\QwenHarness --exclude-models strata/models/IQ2_XS,strata/packs/iq2_xs,strata/conversation-spill`) and renamed to `Marvin-Offline-Backup-1.21.0`:

- Replaced `Marvin-Setup-1.20.0-Full.exe` with `Marvin-Setup-1.21.0-Full.exe` and updated manuals and installation guides.
- Upgraded `payload/runtime/llama/` to `b12359` and `payload/runtime/strata/` to `0.2.17` (`0.1.63`).
- Added `payload/runtime/infernix/` (`2026.11.20`), `payload/runtime/models/strata/dflash2/`, and `payload/runtime/models/infernix/` (`qwen3.8-27b-nvfp4`, `flash-next-iq3_s`, `flash-next-dflash2` with verified receipts).
- Removed retired Nemotron and Ornith model weights (~76 GiB quarantined and deleted after verification).
- `offline_backup.py verify` passed for all **3,495** recorded files (**244.06 GiB**, 0 errors).

Old `1.20.0` installers, staged `dist/release-1.20.0/`, retired Nemotron/Ornith weights, quarantine folder, old runtime rollback folders, and `%LOCALAPPDATA%\EngineEval` were deleted after verification (~161 GiB reclaimed).

## GitHub publication verification

Published on 22 November 2026 (`02:30 UTC`) as the latest release:
[Marvin 1.21.0](https://github.com/petrsajner/marvin/releases/tag/v1.21.0).
The release tag points at `b032f88`; the application build commit is `40239db`.
All six uploaded assets are in state `uploaded`, and their sizes and GitHub
SHA-256 digests match `release-1.21.0.json`.
`releases/latest/download/SHA256SUMS.txt` serves the 1.21.0 checksums.
