# Marvin 1.8.0: completion and verification

13 September 2026. Windows, RTX 5090 32 GiB, 64 GiB RAM, Core Ultra 7 265K (8 P + 12 E, no HT). This is a historical release record, not the current package manifest.

## Delivered behavior

- Flash-Next Q3_K_XL entered the normal model picker with vision, tools and the agent loop. Preparation checks the model, upstream runtime, CPU topology and free memory. Q8 context selection is bounded to 256k, 192k or 128k.
- The completion race no longer strands rapidly arriving clarification messages. STOP still pauses the queue.
- Startup and the fixed bottom of the right column show © Petr Sajner 2026. Real web UI scrolling and launcher startup HTML were visually checked; the native Tk window was not visually inspected.
- Czech/English manuals describe the current UI, models, task control and offline setup. They had 20/26 pages respectively; changed pages were rendered and visually checked.
- Full 1.8.0 upgraded the real 1.6.2 installation in `%LOCALAPPDATA%/QwenHarness`. Installation and offline preparation exited 0. All 369 checked user-data files were unchanged and the last selected Ornith model was retained.
- The installed launcher loaded the model and UI, then stopped both servers and released GPU memory on exit (code 0). All 50 installed service/runtime tests passed; installed Python source and manuals matched the final package.

## Historical distribution

| File in `dist/` | Bytes | SHA-256 |
|---|---:|---|
| `Marvin-Setup-1.8.0-Minimal.exe` | 52,343,903 | `4029a02813664fe7259c8431b3adfbf684e63ac84fb3b6b573c799cb0524b469` |
| `Marvin-Setup-1.8.0-Full.exe` | 727,119,209 | `b4670692706e65d0d85b154e029a4f820ec6a0f0ac93d059b58927fe1ece762f` |
| `Marvin-1.8.0-Windows-x64.zip` | 778,611,911 | `134edb93476fa43cc826bb67a9cb0108f4bc59c58f9b945647c1ea878b5894b0` |

The ZIP's seven entries were two installers, two PDFs, two install guides and checksums. All CRC/SHA checks passed. A clean temporary environment restored offline dependencies and served API/UI without personal data. Full also passed private-Python checks without system Python and with conflicting environment variables. This was not a clean Windows VM test.

`Marvin-Offline-Backup-1.8.0/` contained 79 manifest entries totaling 223,518,387,092 bytes (208.17 GiB): all seven model variants, projectors, llama.cpp, Python packages and the latest Full installer. All 79 hashes passed. After the final installer-only change, all sizes and 65 non-model hashes were rechecked; weights remained unchanged since full verification. Manifest SHA-256: `dfb74277d40f2def1984393a2129eefda9a22c20e78271ae222b1ca0f6d3c8bd`.

## Model qualification and limits

366 core checks and 50 service/runtime tests passed in the source environment. The runtime audit compared 22 existing model/profile combinations on each runtime (44 total) with chat, tools, supported vision, STOP and long context. See [b10935 qualification](LLAMA-b10935-VALIDATION.md).

Flash-Next's practical 128k test processed 122,397 input tokens and recovered three facts. First response: 1,053.687 seconds; cached follow-up: 1.266 seconds. A separate short run measured 27.29 generated tokens/s. The 256k profile passed chat, tools, vision, STOP and 24,101 input tokens, but its entire window was not filled. A separate long 192k run and physical 16/24 GB cards were not qualified.

All 95 Python package versions stayed locked. Upstream b10935 was pinned, b10549 retained for rollback, and no community expert-cache fork used. See [Flash-Next integration](../design/2026-09-13-qwen38-flash-next-integration.md). The Mac assessment remained deferred research.

## Workspace organization at this release

| Location | Purpose |
|---|---|
| `harness/`, `frontend/`, `launcher/` | Current application source |
| `scripts/`, `installer/`, `tests/` | Build/setup tools and repeatable tests |
| `docs/`, `output/pdf/` | Documentation, retained research and distributed manuals |
| `.venv/`, `frontend/node_modules/`, `ui_dist/` | Active development dependencies and built UI |
| `runtime/models/`, `runtime/llama/`, staged/rollback runtime | Weights and inference environments |
| `dist/` | Current installers and distribution ZIP |
| `Marvin-Offline-Backup-1.8.0/` | Verified complete offline set for this version |
| `runtime/archive/` | Verification evidence and cleanup record |
| `runtime/KE-SMAZANI/` | Files marked for the owner's manual removal |

`runtime/archive/verification-1.8.0.zip` preserved 570 files (82,017,664 bytes). Each original file was checked against archive CRC/SHA. Archive SHA-256: `f5b18420186b118ffc3a69b5d701b155adb5b2337cd6c8caeb375b4b9ef7c1ea`. Historical `runtime/validation/...` paths now refer to entries inside this ZIP. It includes a private installation backup and remains local/Git-ignored.

More than 18,500 files were moved to `KE-SMAZANI` for manual removal: build copies, old installers, unpacked test outputs, identified test chats, bytecode and incomplete download caches. Active dependencies, complete GGUFs, actual installed user data and current distribution were excluded. Automatic approval review had rejected deletion without a specific reason, and the owner took responsibility for final removal. The files were still physically present when this report was written.
