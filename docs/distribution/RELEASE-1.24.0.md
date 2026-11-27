# Release record: Marvin 1.24.0

27 November 2026. Added **PrismML Ternary Bonsai 2.5 27B (`Q2_0`, Apache 2.0)** alongside `Qwen3.8-27B Q2_K_XL` on stock `llama.cpp v1.0.0 (b12359)`, with measured 12–96 GB VRAM profiles, updated EN/CS manuals explaining when to pick each model on 12–16 GB GPUs, and refreshed README benchmarks.

## Highlights

- **Bonsai 2.5 27B Ternary (`bonsai25`, 7.67 GB + 0.93 GB BF16 vision projector):**
  - Pinned SHA-256 download from `prism-ml/Ternary-Bonsai-2.5-27B-GGUF` (revision `28a7093cc25bc151cc2b284c5570f12ce343fdcf`), running directly on bundled stock `llama.cpp b12359` without adding another engine.
  - Measured VRAM savings of ~1.7–2.4 GiB over `Qwen3.8-27B UD-Q2_K_XL` (`docs/design/measurements/2026-11-27-bonsai25-profiles.json`): unlocks **2× context on 12 GB GPUs** (`64k Q8` at 10.10 GiB, `128k Q4` at 10.53 GiB) and **full 256k Q4** (`13.41 GiB`) or **160k Q8** / **128k Q8 with GPU vision** on **16 GB GPUs**.
  - Head-to-head measured +16–17% faster decode (`111 tok/s` vs `95 tok/s`), +10% faster long-context prefill (`3,177` vs `2,894 tok/s`), sharper screenshot OCR, and faster multi-step coding/tool-calling (`55.0 s` / 12 steps vs `67.3 s` / 15 steps on 3-bug `pricing.py` agent test).
  - Added reasoning-effort compatibility mapping (`high -> xhigh`) in `harness/llm.py` for models whose Jinja templates strictly allow `xhigh/medium/low`.
- **Dual 12/16 GB model guidance in both PDF manuals & installer:**
  - Dedicated side-by-side comparison chapter in `Marvin-Manual-EN.pdf` (31 pages) and `Marvin-Manual-CS.pdf` (25 pages): **Bonsai 2.5 27B** for coding, agentic tool use, long repositories/documents, OCR, and English; **Qwen 3.8 27B · Q2** (`UD-Q2_K_XL`) for cleaner, more natural Czech prose and formal emails.
  - Updated `installer/marvin.iss` model wizard (Bonsai 2.5 listed beside Q2), `harness/locales/cs.json` profile labels, and `README.md` with November 2026 engine benchmarks.

## Validation

- Automated test suites: `tests/test_core.py` **365/365 OK**, `tests.test_server_launch` **39/39 OK** (updated golden fixture with +14 `bonsai25` profiles, 0 changes to existing models), `tests.test_memory_profiles` **28/28 OK**, `tests.test_localization` **13/13 OK**, `tests.test_harness_upgrades` **11/11 OK**, `tests.test_capabilities` **11/11 OK**.
- Relocated Full runtime verification (`tests/check_full_runtime.py`): passed with system Python disabled, verifying private Python 3.12, locked packages, `llama.cpp` build `12359`, bundled Strata `0.2.17`, and bundled Infernix `2026.11.20`.
- Local installation (`%LOCALAPPDATA%\QwenHarness`) upgraded via `Marvin-Setup-1.24.0-Full.exe /VERYSILENT /NORESTART`, verified private environment via `bootstrap_full.py`, and confirmed installed `APP_VERSION == "1.24.0"` and `cfg.model_ready("bonsai25") == True`.

## Release Assets

Staged in `dist/release-1.24.0/` and recorded in `release-1.24.0.json` (application build commit `581d4536`):

| File | Bytes | SHA-256 |
|---|---:|---|
| Marvin-Setup-Minimal.exe | 54,190,657 | `ef94c3cd8cfa3f589b9796f13a12d47c0ebb2d4236725cabf268a8abc89f3d48` |
| Marvin-Setup-Full.exe | 1,807,475,756 | `f8506bab2889187272da591bea9124b24d3c292db3a3d49e38d0a0cfd5d169e5` |
| Marvin-Manual-EN.pdf | 232,114 | `6e3e0576bced0987e5a7ceb58b50123cac4c8e0caac19ed4e8b4e2f53cc07f87` |
| Marvin-Manual-CS.pdf | 229,122 | `8f8abc130e14805392dcd6f86dac55492c721bf79a9deec2ce50bc4a95b3e77f` |
| Marvin-Workspace.jpg | 136,523 | `41bdec06fd93e28ab17c53167777f566c9fda995860d93a0781c58ac3055652b` |
| SHA256SUMS.txt | 445 | `a104483d836957508f8be63cdc32f8091d30fb515140cf38fd859703d13c8854` |

## Offline Package Refresh

`Marvin-Offline-Backup-1.23.0` was refreshed from the upgraded installation (`offline_backup.py refresh --runtime-root %LOCALAPPDATA%\QwenHarness --exclude-models strata/models/IQ2_XS,strata/packs/iq2_xs,strata/conversation-spill`) and automatically renamed to `Marvin-Offline-Backup-1.24.0`:

- Replaced `Marvin-Setup-1.23.0-Full.exe` with `Marvin-Setup-1.24.0-Full.exe`, updated manuals and installation guides, and packed the verified `Bonsai-2.5-27B` model (`Ternary-Bonsai-2.5-27B-Q2_0.gguf`, `Ternary-Bonsai-2.5-27B-mmproj-BF16.gguf`, and `.marvin-verified.json`).
- `offline_backup.py verify` passed for all **3,499** recorded files (0 errors).
- Superseded `1.23.0` local installers and staging directory were deleted after verification.

## GitHub publication verification

- Published as latest release [`v1.24.0`](https://github.com/petrsajner/marvin/releases/tag/v1.24.0) on `2026-11-27T07:51:23Z`.
- Release tag target commit: `c96c1dab` (application build commit: `581d4536`).
- Verified all 6 uploaded GitHub release asset sizes and SHA-256 digests against `docs/distribution/release-1.24.0.json` — all 6 matched exactly.
- Verified `https://github.com/petrsajner/marvin/releases/latest/download/SHA256SUMS.txt` resolves to `v1.24.0` and matches `dist/release-1.24.0/SHA256SUMS.txt` byte-for-byte (`Marvin-Setup-Full.exe` SHA-256 `f8506bab2889187272da591bea9124b24d3c292db3a3d49e38d0a0cfd5d169e5`).
