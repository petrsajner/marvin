# Inference Engine Evaluation and Phase 0 Benchmarks (2026-11-22)

Date: 2026-11-22  
Measurement record: `docs/design/measurements/2026-11-22-engine-eval.json`  
Harness script: `scripts/engine_eval.py`

## 1. Purpose and Constraints

This document records the inference-engine landscape survey and isolated Phase 0
benchmarks conducted on the owner's reference Windows workstation to evaluate
faster, lower-memory, and more reliable ways to run Marvin's local Qwen models.

Constraints observed throughout evaluation:

- Single sequential local model on native Windows (no WSL2, Docker, or parallel
  multi-model orchestration).
- Vision (`image_url` / multimodal screenshots and PDF page views), Marvin tool
  calling (68-tool Development toolset), reasoning effort controls, prompt
  progress reporting, and non-blocking STOP cancellation must work through
  Marvin's real `LLMClient` and `Agent`.
- Broad GPU support (12 GB minimum GPU target across NVIDIA RTX 20/30/40/50 and
  other supported cards) and user quantization selection must remain intact.
  Blackwell-only acceleration (`sm_120`) can only be an opt-in / hardware-gated
  backend alongside universal engines.
- All Phase 0 downloads, staged binaries, and runs were isolated under
  `%LOCALAPPDATA%\EngineEval`; Marvin's installed `%LOCALAPPDATA%\QwenHarness`
  and repository `runtime/` directories were not modified.

## 2. Reference Machine

- **CPU:** Intel Core Ultra 7 265K (`Intel64 Family 6 Model 198 Stepping 2`, 20 cores)
- **RAM:** 63.7 GiB total (~47–52 GiB available at test start)
- **GPU:** NVIDIA GeForce RTX 5090 (32,607 MiB VRAM, Blackwell `sm_120`, PCIe x16, driver `610.88`)
- **OS:** Windows 11 (`Windows-11-10.0.26200-SP0`), Python `3.12.9`

## 3. Candidate Landscape Summary

| Candidate | Scope & Hardware | Status / Fit for Marvin |
|---|---|---|
| **`llama.cpp` v1.0.0 (`b12359`)** | Universal (NVIDIA CUDA, Vulkan, ROCm, SYCL, CPU); all GGUF quantizations | **Strong universal upgrade** over pinned `b10935`; drop-in on existing GGUF weights. |
| **`Strata` v0.2.17 (engine `0.1.63`)** | Broad GPU support (NVIDIA RTX 20/30/40/50, AMD RX 7000/9000 & Strix Halo, Intel Arc, Apple Silicon); ISTA-DASLab / Unsloth / NVFP4 packs | **Strong universal upgrade** over pinned `v0.1.39`; adds tuned DFlash2 drafter, bundles CUDA 13 cuBLAS DLLs (no NVIDIA pip wheels), defaults `STRATA_ROUTE_TAIL_SKIP` off, adds elastic vision and `/props` + `/slots`. |
| **`Infernix` (`windows-2026.11.20`)** | **Blackwell-only (`sm_120`, RTX 50-series, driver 580+)**; native C++/CUDA server, self-contained (~279 MB unpacked), no Python runtime | **Best measured performance & RAM efficiency on Blackwell** for both Qwen3.8-27B (NVFP4-QAD + DFlash2) and Qwen3.8-Flash-Next (bit-exact IQ3_S GGUF import + DFlash2, plus NVFP4-QAD / FP4-Local / FP8). Opt-in Blackwell backend only. |
| **`Basalt`** | Fast MoE engine with 6-bit dense / 8-bit activations / 2-bit head screen | **Rejected as primary:** coarser arithmetic (+0.47% PPL on IQ3_S, +10% KLD on NVFP4 dense layers), weak SSD n-gram prefill, less mature Windows/vision server fit. |
| **`NInfer`** | Upstream ancestor of Infernix (`sm_120`) | **Superseded by Infernix** (Infernix adds native Windows releases, hybrid prefix cache, Flash-Next support, DFlash2, vision, and active maintenance). |
| **`vLLM` / `SGLang` / `TensorRT-LLM` / `Colibri`** | Linux/WSL2-centric or missing Flash-Next / Windows native packaging | **Out of scope** for Marvin's single-user native Windows desktop installer. |

## 4. Phase 0 Benchmark Methodology

All eight runs executed the same nine Marvin scenarios via
`scripts/engine_eval.py` against a live HTTP server on `127.0.0.1:18080` using
Marvin's real `LLMClient` and `Agent` loop, with 1 Hz sampling of system RAM
available, Windows commit headroom, server RSS, and GPU VRAM (`nvidia-smi`):

1. `warmup` — minimal non-thinking check.
2. `decode_bench` — fixed prose (~450–550 tok) and Python code (~1,300–3,100 tok) prompts.
3. `chat` — thinking `off`, `low`, and `high` effort verification.
4. `image` — real PNG OCR check through `image_url`.
5. `tool_calls` — 8 sequential tool-selection requests with Marvin's full 68-tool Development toolset (validates strict JSON/schema calls and prompt prefix reuse).
6. `agent` — real Marvin `Agent` end-to-end coding task (`read_file`, `apply_patch`, `start_project_check`, `poll_command`, `list_task_changes`).
7. `long_context` — near-ceiling needle-in-a-haystack (~180k for 192k profiles; ~246k for 256k profiles) with 3 embedded codes, prompt progress events, and a cached follow-up turn.
8. `stop_prefill` — client disconnect mid-prefill (64k prompt), measuring idle recovery and immediate follow-up request latency.
9. `stop_decode` — client disconnect mid-decode, measuring idle recovery and follow-up request latency.

All 8 runs passed **9/9 scenarios** with **0 malformed tool calls** and **3/3 long-context needles**.

## 5. Track B Results: Qwen3.8-27B

| Run | Engine / Weights / Context | Load | Prose / Code Decode | Image OCR | Tool Calls (8/8, avg TTFT) | Agent e2e | Long Ctx Prefill (Follow-up) | STOP Prefill / Decode (idle) | Peak VRAM | Peak RSS / Min Avail RAM |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| **B1** | `llama.cpp b10935` (baseline), Q5_K_M + MTP, 192k Q8 | 72.6 s | 100.9 / 139.5 tok/s | 1.05 s | 8/8 (0.62 s) | 22.5 s (8 reqs) | 1,333 tok/s @ 180k (1.71 s) | 28.5s (+0.14s) / 1.11s (+0.15s) | 32,008 MiB | 31,734 / 17,881 MiB |
| **B2** | `llama.cpp v1.0.0 (b12359)`, Q5_K_M + MTP, 192k Q8 | 22.9 s | 112.8 / 150.2 tok/s | 0.70 s | 8/8 (0.46 s) | 19.3 s (9 reqs) | 1,477 tok/s @ 180k (0.72 s) | 26.8s (+0.12s) / 0.82s (+0.12s) | 31,784 MiB | 28,327 / 21,285 MiB |
| **B3** | `Infernix 2026.11.20`, NVFP4-QAD-Exact + DFlash2 + `--embedding-host`, **256k INT8** (auto prefix cache) | 13.9 s | 189.8 / 452.7 tok/s | 0.145 s | 8/8 (0.12 s) | 13.0 s (9 reqs) | 5,117 tok/s @ 246k (0.151 s) | 5.05s (+0.021s) / 0.50s (+0.039s) | 31,645 MiB | 46,007 / 5,114 MiB |
| **B3b** | Same as B3 + **`--host-context-mib 4096`** | **6.6 s** | **184.3 / 448.3 tok/s** | **0.118 s** | **8/8 (0.13 s)** | **11.6 s** (8 reqs) | **5,087 tok/s** @ 246k (**0.144 s**) | **5.07s (+0.002s) / 0.50s (+0.019s)** | **31,467 MiB** | **8,594 / 39,648 MiB** |

### Track B Takeaways

- **`llama.cpp` `b10935` -> `b12359` (universal win):** Zero weight changes; delivers **3.2x faster startup**, **+8–12% throughput**, **−3.4 GiB peak RAM**, and **2.4x faster cached long-context follow-up** on every GPU and GGUF quant.
- **`Infernix` with `--host-context-mib 4096` (B3b, Blackwell):** Delivers **1.8x prose decode**, **3.2x code decode (448 tok/s)**, **3.8x prefill**, **8.9x faster image OCR**, **11x faster load**, and **full 256k INT8 context** in **less VRAM** than `llama.cpp` at 192k, while cutting server RAM from 31.7 GiB to **8.6 GiB** (38.7 GiB RAM free on 64 GiB).
- **Mandatory Infernix flags discovered on 27B:**
  - `--host-context-mib 4096` (or similar explicit bound) is mandatory; without it (`B3`), Infernix's automatic host prefix cache pins nearly all free RAM down to `--ram-free-mib 4096` (46 GiB RSS).
  - `--embedding-host` moves the 2.54 GiB token embedding to pinned RAM (bit-identical output) and unlocks the full 262,144 INT8 KV context on 32 GB VRAM (`--plan` fits 295,552 KV tokens).

## 6. Track A Results: Qwen3.8-Flash-Next (ISTA-DASLab `IQ3_S`, 256k INT8 KV)

All four runs use the exact same `ISTA-DASLab/Qwen3.8-Flash-Next-GSQ-RCO-GGUF` `IQ3_S` weights (`A3` runs Infernix's bit-exact import with 16-bit exact activations; Strata runs 8-bit activations with `STRATA_ROUTE_TAIL_SKIP` off in `0.2.17`).

| Run | Engine / Drafter | Load | Prose / Code Decode | Image OCR | Tool Calls (8/8, avg TTFT) | Agent e2e | Long Ctx 246k Prefill (Follow-up) | STOP Prefill / Decode (idle) | Peak VRAM | Peak RSS / Min Avail RAM |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| **A1** | `Strata v0.1.39` (baseline), MTP | 30.5 s | 104.5 / 168.7 tok/s | 0.811 s | 8/8 (0.55 s) | 17.04 s (8 reqs) | 6,082 tok/s, 41.0 s (1.07 s) | 10.39s (+0.11s) / 1.73s (+0.15s) | 31,827 MiB | 51,391 / **416 MiB** |
| **A2** | `Strata v0.2.17 (0.1.63)`, no drafter *(see note 1)* | 25.5 s | 112.7 / 118.3 tok/s | 2.635 s *(cold)* | 8/8 (0.48 s) | 13.93 s (6 reqs) | 7,069 tok/s, 35.2 s (0.50 s) | 8.56s (+0.14s) / 1.62s (+0.14s) | 31,984 MiB | 51,730 / **758 MiB** |
| **A2b** | `Strata v0.2.17 (0.1.63)`, **tuned DFlash2** | 24.4 s | 152.4 / 208.8 tok/s | 2.579 s *(cold)* | 8/8 (0.53 s) | 16.74 s (8 reqs) | 6,810 tok/s, 36.6 s (**0.56 s**) | 9.08s (+0.03s) / 1.21s (+0.14s) | 31,952 MiB | 51,706 / **678 MiB** |
| **A3** | `Infernix 2026.11.20`, **IQ3_S bit-exact + DFlash2** (`--expert-ram-layout exclusive`) | **22.1 s** | **197.4 / 281.8 tok/s** | **0.445 s** | **8/8 (0.27 s)** | **11.35 s** (7 reqs) | **7,288 tok/s**, **34.0 s** (5.15 s *(note 2)*) | **5.02s (+0.04s) / 0.90s (+0.03s)** | **31,579 MiB** | **45,275 / 6,918 MiB** |

### Track A Takeaways and Integration Caveats

1. **Strata `0.1.39` -> `0.2.17` (universal win across all GPUs):**
   - With its tuned DFlash2 drafter active (`A2b`), prose decode jumps **+46%** (`104.5 -> 152.4 tok/s`), code decode **+24%** (`168.7 -> 208.8 tok/s`), 246k prefill **+12%** (`6,082 -> 6,810 tok/s`), cached follow-up **1.9x faster** (`1.07 -> 0.56 s`), and startup **20% faster** (`30.5 -> 24.4 s`), on the exact same `packs/iq3_s` files.
   - **Packaging simplification:** `strata-engine-0.1.63-windows-x86_64-cuda-cuda13.tar.gz` now bundles `cublas64_13.dll` and `cublasLt64_13.dll`, removing the ~500 MB NVIDIA CUDA pip wheels from the Full installer payload.
   - **Config & API caveats found during testing:**
     - Repository layout moved under `terminal/` (`terminal/serve/server.py`, `terminal/data/`).
     - `strata_control/drafting.py` ignores `--draft-model` in `cfg["args"]` unless it is placed in `cfg["user_args"]` or under `<data_dir>/dflash2/` (caused `A2` to silently run without a drafter until fixed in `A2b`).
     - In `0.2.17`, `strata-vision` starts lazily on the first image (`~1.6 s` cold start, hence `2.58 s` first image OCR vs `0.81 s` preloaded) and stops after 120 s idle to keep VRAM free for experts.
     - Streamed OpenAI SSE final chunks in `0.2.17` returned `usage` cleanly, but omitted `timings` (client fallback or `/v1/status` / `/metrics` is needed if Marvin displays server-side tok/s).
2. **Infernix on Flash-Next `IQ3_S` (`A3`, Blackwell):**
   - On identical `IQ3_S` weights — and using **exact 16-bit activations** instead of Strata's 8-bit activations — Infernix beats `Strata 0.2.17 + DFlash2` across the board: **+29% prose decode (197.4 tok/s)**, **+35% code decode (281.8 tok/s)**, **+7% 246k prefill (7,288 tok/s)**, **2x faster tool calls**, **1.5x faster end-to-end agent**, and **5.8x faster image OCR**.
   - **Major 64 GiB RAM relief:** With `--expert-ram-layout exclusive`, Infernix places 12,393 experts in VRAM (23.6 GiB) and 18,347 non-overlapping experts in RAM (only 37 of 24,576 left on NVMe), keeping **6.9 GiB of RAM free** (`45.3 GiB` RSS) where Strata `0.1.39` and `0.2.17` dropped available RAM to **416–678 MiB** (`51.4–51.7 GiB` RSS).
   - **Integration caveats discovered for Infernix:**
     - *Note 2 (246k follow-up cache):* At default `--host-context-mib auto` (1.0 GiB on 64 GiB RAM), a 246k conversation's endpoint snapshot + KV exceeded 1.0 GiB, so the follow-up resumed from an earlier snapshot at `212,992` tokens (`5.15 s` to re-prefill the 32k tail). Setting `--host-context-mib 4096` avoids tail re-prefill on long conversations at the cost of ~3 GiB of expert RAM.
     - *Status / stall probe:* Infernix exposes `GET /monitor` and `GET /metrics` rather than `llama.cpp`'s `GET /slots`. Marvin's `servermgmt.slots_processing` / stall probe needs an Infernix branch reading `/monitor`.
     - *Output token limit:* Infernix defaults `--default-max-tokens` to `8192` when a request omits `max_tokens`; Marvin should pass explicit `max_tokens` or configure `--default-max-tokens`.
     - *Chat template:* Pass `--chat-template <infernix_dir>/chat_templates/qwen3_8.jinja` for Flash-Next artifacts so mid-conversation system/developer messages render under their real roles.
     - *Hardware gate:* Infernix requires NVIDIA Blackwell (`sm_120`, RTX 50-series) and NVIDIA driver 580+. Marvin must detect compute capability (`nvidia-smi --query-gpu=compute_cap`) and only offer Infernix models/profiles on Blackwell GPUs.

## 7. Recommended Integration Plan

Based on Phase 0 measurements and the owner's direction (minimum 12 GB GPU floor,
keeping broad hardware support and quantization choice, removing low-utility
models `Nemotron` and `Ornith`, and adding `Infernix` for Blackwell):

1. **Model Catalog Cleanup (all GPUs):**
   - Remove `ornith_q5`, `nemotron_q4`, and `nemotron_q5` from `BUILTIN_MODELS`, `measured_profiles.py`, `installer/marvin.iss`, offline backups, and user manuals. Add migration mappings in `REPLACED_MODELS` (`ornith_q5 -> q5`, `nemotron_q4 -> q4`, `nemotron_q5 -> q5`) so existing user configs and sessions migrate cleanly.
   - Saves **~79.8 GB** in offline backups with zero loss of 12–16 GB GPU coverage (Ornith required 32 GB; Nemotron required 24–32 GB).
   - Add and measure a **12 GB GPU class (`gpu_class = 12`)** for the remaining main models (`Qwen3.8-27B Q2_K_XL` and `Flash-Next` via Strata `0.2.17` 12 GB placement) so the 12 GB minimum target is backed by real measurements.
2. **Universal Backend Upgrades (all GPUs):**
   - Upgrade pinned `llama.cpp` from `b10935` to `v1.0.0` (`b12359`).
   - Upgrade pinned `Strata` from `v0.1.39` to `v0.2.17` (`0.1.63`), bundling the tuned DFlash2 drafter fetch/config (`user_args` / `dflash2/`), switching to the self-contained CUDA 13 engine tarball (saving ~500 MB of NVIDIA pip wheels in the Full installer), and handling missing SSE `timings`.
3. **Optional Blackwell Backend (`Infernix 2026.11.20`):**
   - Add `"infernix"` to `BACKENDS` (`harness/infernix_backend.py`, `harness/infernix_runtime.py`, `/monitor` stall probe, compute capability `>= 12.0` gate in `harness/gpu.py`).
   - Bundle `infernix-serve.exe` + required DLLs (~279 MB unpacked, ~80 MB compressed in the Full installer — net installer size shrinks thanks to dropping Strata's NVIDIA CUDA wheels).
   - Offer Blackwell-gated model entries alongside existing GGUF/Strata entries:
     - `qwen27b_infernix` (`Qwen3.8-27B-NVIDIA-NVFP4-QAD-Infernix-Exact`, 22.2 GB, `--embedding-host --host-context-mib 4096`)
     - `flash_next_infernix` (`Qwen3.8-Flash-Next-GSQ-RCO-IQ3_S-Infernix`, 85.9 GB + `Qwen3.8-Flash-Next-DFlash2-Infernix`, 0.78 GB, `--expert-ram-layout exclusive`), optionally complemented on >= 96 GB RAM machines by `NVFP4-QAD-Dense8`.
   - Before making `qwen27b_infernix` default on Blackwell, run a brief blind quality spot-check comparing `NVFP4-QAD` vs `Q5_K_M` on representative Czech and coding prompts.
