# Model watch list

This list records models the owner reviewed but did not adopt. Each entry says what would make it worth a new
look. Scores are the Artificial Analysis Intelligence Index from public sources at the time of review, not
measurements in Marvin. For comparison, Marvin 1.19.0 ships:

- Qwen 3.8 Flash-Next on Strata, index 40, about 110 tok/s on an RTX 5090 with 64 GB RAM;
- Qwen 3.8 27B, index 34;
- Nemotron 3.5 Lightning, index 24.

## Watching

### GLM-5.3-Flash on Project Maya (reviewed 20 October 2026)

The owner marked this as an interesting variant whose development should be followed.

- **Model:** Z.ai GLM-5.3-Flash, 321B total, about 18B active per token, MIT license, text and images.
  Index 42, two points above Flash-Next.
- **Engine:** [Project Maya](https://github.com/mw00/project-maya), MIT, v1.1.16 (`abc09c7`, 19 October 2026).
  - It is built on Strata, and its server keeps Strata's command line
    (`serve/server.py --engine strata --config`). `/health` reports `"service": "maya"`.
  - It adds `return_progress` prefill progress.
  - Marvin's Strata backend is therefore the likely integration path.
  - Maya also runs DeepSeek-V4.1-Flash-1017 on a separate engine, `maya-ds4`.
- **Weights:** Maya's own GGUF quants (Hugging Face `peasantsmith/GLM-5.3-Flash-Maya-GGUF`):
  - Maya-S: 96.5 GB, 97.9% of the FP8 model's zero-shot accuracy;
  - Maya-M: 116 GB;
  - Maya-L: 156.3 GB, 99.2%.
- **Closest reported machine:** a user report in Maya's README (#139, v1.1.3): RTX 5090 32 GB, i9-13900K,
  64 GB RAM, Windows 11, Maya-S at 128k. It wrote answers at **23 tok/s** and read prompts at **2,173 tok/s**.
  Against Flash-Next on the owner's PC that is about 5x slower to answer and 2-3x slower to read.
- **Why it was not adopted yet:**
  - Windows is experimental, with no prebuilt binaries. It needs a source build with VS 2022 and the CUDA toolkit.
  - The engine pins all free RAM except about 6 GB.
  - Two index points do not yet justify the speed loss.
- **Look again when any of these happens:**
  - Maya publishes Windows release binaries, or its Windows support leaves experimental status;
  - a measured RTX 5090 + 64 GB result reaches roughly 40 tok/s or more;
  - a newer GLM Flash, or a Maya quant, widens the quality gap over Flash-Next;
  - mainline llama.cpp runs it (PR #27754 status was unclear).
- **First step:** an evaluation script in the style of `scripts/strata_eval.py`, run on the owner's PC with
  Marvin's client, tools and images, before any change to Marvin.

## Reviewed, not adopted

| Model | Reviewed | Decision | Revisit when |
|---|---|---|---|
| Liquid LFM2.5-24B-A2B (24B, 2.45B active, text only) | 15 Oct 2026 | Wait | An independent index score above 34 |
| NVIDIA Nemotron 3.5 Super VL (120B-A12B, index 26), Bolt 74B-A9B (21.4) | 17 Oct 2026 | Keep Nemotron 3.5 Lightning | A Nemotron above the Qwen models |
| DeepSeek-V4.1-Flash-1017 (748B, 16B active, index 45) | 18 Oct / 27 Nov 2026 | Wait | Even with ISTA-DASLab IQ2_XXS (~100 GB) + Engram (~103 GB), 64 GB RAM forces heavy NVMe streaming (~10–25 tok/s). Revisit on 128–256 GB RAM or for a smaller successor. |
| PrismML Ternary Bonsai 2.5 27B (`Q2_0`, 7.67 GB + 0.93 GB vision, Apache 2.0) | 27 Nov 2026 | **Adopted as `bonsai25`** | Added alongside `q2` (`UD-Q2_K_XL`): 2× context on 12 GB (64k Q8 / 128k Q4), full 256k Q4 on 16 GB, +16–17% faster decode, better agentic coding & OCR; `q2` stays beside it for cleaner free-form Czech prose. Revisit `PTQ1_0` (5.93 GB) when merged into upstream `llama.cpp`. |
| Mistral Large 4 (~1T, index ~38, weights due late October), Small 4 119B-A6B (index ~20) | 20 Oct 2026 | Not adopted | A Mistral that beats Flash-Next and fits the PC |
| Xiaomi MiMo-V2.6-Flash (309B, 15B active, index 38) | 20 Oct 2026 | Not adopted | A version above Flash-Next |
