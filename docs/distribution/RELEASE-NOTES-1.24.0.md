## What's New in Marvin 1.24.0

Marvin 1.24.0 makes **12 GB and 16 GB NVIDIA GPUs** dramatically more capable for coding and long-context work by adding **PrismML Ternary Bonsai 2.5 27B** alongside Qwen 3.8 Q2 — on the same built-in `llama.cpp` engine with zero extra runtime overhead.

- **New built-in model: Bonsai 2.5 27B Ternary (`Q2_0`, Apache 2.0, 8.6 GB incl. vision):**
  - Runs directly on Marvin's bundled `llama.cpp v1.0.0 (b12359)` with its own BF16 vision projector (`mmproj`) and pinned SHA-256 verification.
  - Uses ~1.7–2.4 GiB less VRAM than `Qwen3.8-27B Q2_K_XL` — unlocking **2× longer context on 12 GB GPUs** (**64k Q8** / **128k Q4** vs. 32k / 64k) and **full 256k Q4** (or **160k Q8** / **128k Q8 with GPU vision**) on **16 GB GPUs**.
  - Measured **+16–17% faster generation** (`111 tok/s` vs `95 tok/s` on RTX 5090), **+10% faster long-context prefill**, sharper screenshot OCR, and faster multi-step coding/tool-calling.
- **Clear model guidance for 12 GB & 16 GB GPUs (both models side by side):**
  - **Bonsai 2.5 27B** is the pick for **coding, agentic tool use, long repositories/documents, screenshots/OCR, and English work**.
  - **Qwen 3.8 27B · Q2** (`UD-Q2_K_XL`, 9.8 GB) stays right beside it for **clean, natural Czech prose and formal emails** (where extreme 1.76-bit ternary weights can occasionally sound rougher).
  - Keeping both installed takes only ~18.4 GB total (less than a single Q5 model) and lets you switch anytime inside the same chat.
  - Both the **English (31-page)** and **Czech (25-page)** PDF user manuals now include a dedicated side-by-side selection guide, and the README benchmark table has been refreshed with our latest November 2026 measurements across Infernix, Strata, and `llama.cpp`.
- **Includes all Marvin 1.23.0 harness upgrades:**
  - Compact consolidated tools with 100% legacy alias compatibility, preserved thinking continuity & KV cache, non-destructive observation masking before summarization, resilient `apply_patch` with compact diffs and stale-file protection, dynamic setup-aware system prompts, runaway thinking & leaked `<tool_call>` recovery, and live Prompt cache telemetry in the Context panel.

## Downloads & Updating

- **`Marvin-Setup-Full.exe`**: complete self-contained installer — private Python 3.12, locked packages, validated `llama.cpp v1.0.0 (b12359)`, offline Strata `0.2.17`, offline Infernix `2026.11.20`, and offline WebView2. Only model weights are downloaded when not already on disk.
- **`Marvin-Setup-Minimal.exe`**: lightweight installer (requires separately installed 64-bit Python 3.12); downloads packages, `llama.cpp`, and missing selected weights automatically.
- Updating over an existing installation keeps all conversations, projects, memories, skills, and downloaded models intact.
- See [SHA256SUMS.txt](https://github.com/petrsajner/marvin/releases/download/v1.24.0/SHA256SUMS.txt) and the updated English / Czech PDF manuals included in this release.
