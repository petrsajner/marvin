# Marvin 1.21.0 - Faster engines, 12 GB GPU support, and Infernix for Blackwell

## Highlights

- **Infernix backend for NVIDIA RTX 50-series (Blackwell, `sm_120+`, driver 580+):**
  - **Qwen 3.8 27B · NVFP4 (Infernix)** (22.2 GB, 24–96 GB VRAM): measured at **184–448 tok/s** decode, **5,087 tok/s** prefill, **6.6 s** load, and **8.6 GiB** RAM with full 256k context and DFlash2 + n-gram speculation.
  - **Qwen 3.8 Flash-Next · IQ3_S (Infernix)** (85.9 GB + 776 MB DFlash2 drafter, 12–96 GB VRAM): measured at **197–282 tok/s** decode, **7,288 tok/s** prefill, and **~7 GiB** free RAM on 64 GB machines via `--expert-ram-layout exclusive`.
  - On older NVIDIA GPUs (RTX 20/30/40 series), both Infernix models stay visible as disabled (greyed-out) items in the model picker and installer wizard with a clear Blackwell hardware notice, while every `llama.cpp` and Strata model remains fully supported.
- **Upgraded universal engines for all GPUs:**
  - **`llama.cpp` v1.0.0 (`b12359`, CUDA 13.5)** replaces `b10935`.
  - **Strata `v0.2.17`** (engine `0.1.63`) adds tuned **DFlash2** speculative decoding for Flash-Next (measured at **152–209 tok/s**, up from 105–169 tok/s) and drops ~500 MB of duplicate NVIDIA CUDA Python wheels from the Full installer.
- **12 GB GPU floor & streamlined model lineup:**
  - Measured 12 GB GPU profiles added for `Qwen3.8-27B Q2_K_XL` and `Flash-Next` (`IQ3_S` / `IQ2_XS`), plus `12 GB` in the GPU memory budget picker.
  - Retired low-intelligence models (`ornith_q5`, `nemotron_q4`, `nemotron_q5`), saving ~76 GiB in offline bundles. Existing saved selections automatically migrate to Qwen3.8-27B (`q5` / `q4`).

## Updating

- Conversations, projects, memories, skills and existing Qwen3.8 / Flash-Next models remain in place.
- The Full installer bundles Python 3.12, locked packages, `llama.cpp b12359`, Strata `0.2.17`, Infernix `2026.11.20`, and offline WebView2.
- The Offline Backup bundle (`Marvin-Offline-Backup-1.21.0`) includes the Full installer, all upgraded runtimes, and all active model weights (excluding retired Nemotron and Ornith) for complete air-gapped installation.
