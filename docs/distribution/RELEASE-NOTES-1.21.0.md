## Highlights

- **Faster universal engines for every NVIDIA GPU (RTX 20 / 30 / 40 / 50):**
  - **`llama.cpp` upgraded from `b10935` to `v1.0.0` (`b12359`, CUDA 13.5):** 3.2x faster model startup, +8-12% faster generation, 2.4x faster cached long-context follow-ups, and 3.4 GiB lower RAM use on existing GGUF weights — no model re-download required.
  - **Strata upgraded from `v0.1.39` to `v0.2.17` (engine `0.1.63` + tuned DFlash2):** Flash-Next prose generation jumps by **+46%** (`104.5 -> 152.4 tok/s`), code generation by **+24%** (`168.7 -> 208.8 tok/s`), 246k prefill by **+12%**, and cached follow-ups are **1.9x faster** (`1.07 s -> 0.56 s`). The new CUDA 13 engine bundles cuBLAS directly, removing ~500 MB of duplicate NVIDIA Python wheels.
- **New Infernix backend for NVIDIA RTX 50-series (Blackwell, `sm_120+`, driver 580+):**
  - **Qwen 3.8 27B · NVFP4 (Infernix)** (22.2 GB, 24-96 GB VRAM): full **256k** INT8 context with built-in DFlash2 + n-gram speculation, loading in **6.6 s** (**11x faster** than v1.20.0), generating up to **448 tok/s** on code (**3.2x faster**), and cutting host RAM from 31.7 GiB to **8.6 GiB**.
  - **Qwen 3.8 Flash-Next · IQ3_S (Infernix)** (85.9 GB + 776 MB DFlash2 drafter, 12-96 GB VRAM): bit-exact 16-bit activations with `--expert-ram-layout exclusive`, reaching **197-282 tok/s** (**+67-89%** over v1.20.0) while leaving **6.9 GiB of free RAM** on 64 GB PCs (vs ~0.4 GiB on v1.20.0).
  - **Broad GPU compatibility kept intact:** on older NVIDIA GPUs (RTX 20/30/40), both Infernix entries stay visible as greyed-out (disabled) options in Settings and the installer wizard with a Blackwell hardware notice, while all `llama.cpp` (Q2/IQ3/Q4/Q5) and Strata models continue working normally.
- **12 GB GPU floor & leaner model lineup:**
  - Added measured **12 GB GPU** profiles for `Qwen3.8-27B Q2_K_XL` and `Flash-Next` (`IQ3_S` / `IQ2_XS`), plus `12 GB` in the GPU memory budget picker.
  - Retired low-intelligence models (`ornith_q5`, `nemotron_q4`, `nemotron_q5`), saving ~76 GiB in offline bundles. Existing saved selections migrate automatically to Qwen3.8-27B (`q5` / `q4`).

## Speed & Memory Comparison: v1.20.0 vs v1.21.0

Measured with Marvin's real `LLMClient` and `Agent` across 9 scenarios (0 malformed tool calls, 3/3 long-context needles) on Windows 11, RTX 5090 32 GB, Intel Core Ultra 7 265K, 64 GB RAM.

### Qwen3.8-27B

| Metric | v1.20.0 (`llama b10935`, Q5 + MTP, 192k) | v1.21.0 (`llama b12359`, Q5 + MTP, 192k, all GPUs) | v1.21.0 (`Infernix`, NVFP4 + DFlash2, **256k**, RTX 50) |
|---|---:|---:|---:|
| Model load time | 72.6 s | **22.9 s** (3.2x faster) | **6.6 s** (11.0x faster) |
| Prose decode | 100.9 tok/s | **112.8 tok/s** (+12%) | **184.3 tok/s** (1.8x) |
| Code decode | 139.5 tok/s | **150.2 tok/s** (+8%) | **448.3 tok/s** (3.2x) |
| Image OCR | 1.05 s | **0.70 s** (1.5x faster) | **0.12 s** (8.9x faster) |
| Long-context prefill | 1,333 tok/s (180k) | **1,477 tok/s** (180k, +11%) | **5,087 tok/s** (246k, 3.8x) |
| Cached follow-up | 1.71 s | **0.72 s** (2.4x faster) | **0.14 s** (11.9x faster) |
| End-to-end agent task | 22.5 s | **19.3 s** (1.2x faster) | **11.6 s** (1.9x faster) |
| Peak host RAM / min free | 31.7 / 17.9 GiB | **28.3 / 21.3 GiB** | **8.6 / 39.6 GiB** |

### Qwen3.8-Flash-Next (`IQ3_S`, 256k INT8)

| Metric | v1.20.0 (`Strata 0.1.39` + MTP) | v1.21.0 (`Strata 0.2.17` + DFlash2, all GPUs) | v1.21.0 (`Infernix` + DFlash2, RTX 50) |
|---|---:|---:|---:|
| Model load time | 30.5 s | **24.4 s** (20% faster) | **22.1 s** (28% faster) |
| Prose decode | 104.5 tok/s | **152.4 tok/s** (+46%) | **197.4 tok/s** (+89%) |
| Code decode | 168.7 tok/s | **208.8 tok/s** (+24%) | **281.8 tok/s** (+67%) |
| Image OCR | 0.81 s | 2.58 s *(lazy vision start)* | **0.45 s** (1.8x faster) |
| 246k prompt prefill | 6,082 tok/s (41.0 s) | **6,810 tok/s** (36.6 s, +12%) | **7,288 tok/s** (34.0 s, +20%) |
| Cached follow-up | 1.07 s | **0.56 s** (1.9x faster) | 5.15 s *(1 GiB host cache)* |
| End-to-end agent task | 17.0 s | 16.7 s | **11.4 s** (1.5x faster) |
| Min available RAM (64 GB PC) | 416 MiB | 678 MiB | **6,918 MiB** (16x headroom) |

## Downloads & Updating

- **`Marvin-Setup-Full.exe`** (1.68 GiB): complete environment — private Python 3.12, locked packages, validated `llama.cpp v1.0.0 (b12359)`, offline Strata `0.2.17` bundle, offline Infernix `2026.11.20` archive, and offline WebView2. Only model weights are downloaded when not already on disk.
- **`Marvin-Setup-Minimal.exe`** (51.6 MB): lightweight installer (requires separately installed 64-bit Python 3.12); downloads packages, `llama.cpp`, and missing selected weights automatically.
- Conversations, projects, memories, skills, and existing Qwen3.8 / Flash-Next weights remain intact on upgrade. Any saved Nemotron or Ornith selection migrates automatically to Qwen3.8-27B.
- See [SHA256SUMS.txt](https://github.com/petrsajner/marvin/releases/download/v1.21.0/SHA256SUMS.txt) and the included English / Czech PDF manuals.
