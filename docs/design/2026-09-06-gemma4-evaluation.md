# Gemma 4 in Marvin: feasibility, memory and recommendation

Research date: 6 September 2026. This is retained research, not implementation or an approved roadmap. Gemma was neither downloaded nor run; memory and speed estimates are not local Gemma benchmarks. Translated and consolidated into English on September 15 without revalidating upstream claims.

**Owner decision: save the research; do not implement now.** Downloads, integration and experimental benchmarks remain deferred until an explicit request.

**Recommendation:** keep Qwen 3.8 27B Q5 as the 32 GB default. Investigate Gemma 4 26B A4B for 24–32 GB and Gemma 4 12B Unified for 16 GB, starting with official QAT Q4_0 files and optionally 12B Q5. Do not add 31B as another standard profile without a demonstrated benefit.

## 1. Environment at the time of research

Locally checked: RTX 5090 with 32,607 MiB VRAM (2,064 MiB occupied), Core Ultra 7 265K, about 64 GiB RAM, Windows, llama-server b10549 / `b2e5e9b28` / Clang 20.1.8 with CUDA 13. One model and slot (`-np 1`), Flash Attention, GGUF and a separate vision projector; preserve sequential operation.

The selected Qwen Q5 KV profile provided 196,608 tokens. The model-level `ctx_size: 98304` did not override that profile.

| Downloaded model | Weight file | Relevant context |
|---|---:|---|
| Qwen 3.8 27B Q5 | 18.414 GiB | 192k Q8 |
| Qwen 3.8 27B Q4 | 15.334 GiB | 128k F16 / 256k Q8 |
| Qwen 3.8 27B IQ3_S | 11.214 GiB | Small-GPU profiles |
| Ornith 1.5 35B-A3B Abliterated Q5 | 23.031 GiB | 128k Q8 |
| Nemotron 3.5 Lightning Q4_K_XL | 23.754 GiB | Multiple profiles |
| Nemotron 3.5 Lightning Q5_K_XL | 28.326 GiB | Multiple profiles |

Qwen/Ornith projectors added 0.864/0.841 GiB. At that date, YAML placed Nemotron definitions under `hardware`, while Python defaults also defined them; reading YAML alone would miss the effective catalog. This placement was corrected during the later source cleanup. The old million-token profile conflicted with product invariants and was not recommended; it has since been removed.

Inspected sources included `config.yaml`, configuration/server/client/session modules, the downloader and architecture guide. Pre-existing worktree changes were left untouched by the research. See [current memory profiles](memory-profiles.md) for later corrections to the existing small-card presets.

## 2. Gemma variants

| Variant | Parameters | Architecture | Native context | Inputs |
|---|---|---|---:|---|
| E2B | 2.3B effective / 5.1B including embeddings | Small dense + PLE | 128k | Text, image, audio |
| E4B | 4.5B effective / 8B including embeddings | Small dense + PLE | 128k | Text, image, audio |
| 12B Unified | 11.95B | Decoder without separate large multimodal encoders | 256k | Text, image, audio |
| 26B A4B | 25.2B total / 3.8B active | MoE | 256k | Text, image |
| 31B | 30.7B | Dense | 256k | Text, image |

Output is text; video is processed as frames. The family supports native tools, a system role and thinking control, and is published under Apache 2.0. That does not change licenses of other application components. [Google model card](https://ai.google.dev/gemma/docs/core/model_card_4), [model overview](https://ai.google.dev/gemma/docs/core).

12B is particularly relevant to 16 GB cards. E2B/E4B should be added only for a concrete workflow, not automatically with the entire family. Checkpoint capabilities do not prove that corresponding inputs work in Marvin's UI/runtime.

## 3. Quality compared with existing models

| Benchmark, higher is better | Qwen 3.8 27B | Ornith 1.5 35B-A3B | Gemma 4 31B | Gemma 4 26B A4B |
|---|---:|---:|---:|---:|
| GPQA Diamond | 89.2 | 89.2 | 84.3 | 82.3 |
| LiveCodeBench v6 | 90.3 | — | 80.0 | 77.1 |
| SWE-bench Pro | 61.7 | 59.6 | 35.7* | — |
| Terminal Bench 2.1, Terminus | 73.0 | 67.8 | 42.1* | — |

[Qwen card](https://huggingface.co/Qwen/Qwen3.8-27B), [Ornith card](https://huggingface.co/ornith-ai/Ornith-1.5-35B-A3B), [Google benchmarks](https://deepmind.google/models/gemma/gemma-4/). Asterisks identify Gemma figures quoted by Ornith's authors.

This is not a controlled independent A/B test. Harnesses, settings, budgets and benchmark revisions differ; Qwen reports a reevaluation of a corrected SWE-bench Pro set. Original Ornith scores cannot be assigned directly to the downloaded Abliterated Q5, nor full-precision scores to any GGUF quantization.

- **Development:** published evidence does not justify replacing Qwen/Ornith. LiveCodeBench performance is not equivalent to reliable real-project repair.
- **Research/Discussion:** 26B could be a faster general alternative; Czech quality, citation accuracy and long-document superiority remain unproven.
- **Writing:** compare style and instruction retention on representative work. A general chat ranking does not establish a better fit for the owner.
- **Computer/PDF/images:** vision is a concrete addition relative to Marvin's text-only Nemotron profiles, but already exists with Qwen/Ornith.

NVIDIA's own comparison lists Gemma 26B above Lightning on MMLU Pro (85.20 versus 81.94) and GPQA (79.61 versus 75.44), suggesting a candidate for a capable fast alternative. Different GPQA figures from Google illustrate methodology differences. [NVIDIA card](https://huggingface.co/nvidia/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-BF16).

## 4. What loading only necessary parts means

1. **MoE selects computation.** 26B selects eight of 128 experts per token plus a shared expert. Selection changes by token and layer. Fast GPU execution still needs access to all weights; VRAM is not simply 3.8B times the bit depth. [26B config](https://huggingface.co/google/gemma-4-26B-A4B-it/blob/main/config.json).
2. **RAM offload selects placement.** Existing `--n-cpu-moe` support can free VRAM for cache by computing experts on CPU, at the cost of CPU work/transfers. Recommended 26B/32 GB profiles do not inherently need it.
3. **PLE looks up token embeddings.** E2B/E4B have large row-addressed tables that can sensibly live outside VRAM. The inspected `src/models/gemma4.cpp` has a PLE path. 26B/31B have `hidden_size_per_layer_input=0` and do not use it.
4. **Sliding-window attention reduces KV.** Most layers retain only recent tokens while a minority attends globally. This is the principal natural KV saving in the larger Gemma variants.

The model does not itself load relevant repository/history fragments into VRAM. Marvin's indexes and retrieval tools choose documents. KV holds intermediate results for processed tokens. Native context includes instructions, tools, documents, images, reasoning and the answer, not a full-size document plus unlimited output.

## 5. KV calculation for the inspected runtime

Exact source references: [Gemma implementation](https://github.com/ggml-org/llama.cpp/blob/b2e5e9b28/src/models/gemma4.cpp), [SWA allocation](https://github.com/ggml-org/llama.cpp/blob/b2e5e9b28/src/llama-kv-cache-iswa.cpp), [K/V allocation](https://github.com/ggml-org/llama.cpp/blob/b2e5e9b28/src/llama-kv-cache.cpp).

26B has five global layers with two KV heads × 512, and 25 local layers with eight heads × 256. 31B has ten global layers with four heads × 512, and 50 local layers with 16 heads × 256. Both use a 1,024-token local window. [26B config](https://huggingface.co/google/gemma-4-26B-A4B-it/blob/main/config.json), [31B config](https://huggingface.co/google/gemma-4-31B-it/blob/main/config.json).

For one slot and microbatch 512, local cache has 1,536 cells, aligned to 256. Global cache grows with context:

`KV bytes = 2 × (global_layers × global_kv_heads × global_head_dim × context + local_layers × local_kv_heads × local_head_dim × 1536) × bytes_per_element`

F16 uses 2 bytes/element, Q8_0 uses 34/32, and Q4_0 uses 18/32 including block overhead. The factor two is K and V. Despite `attention_k_eq_v: true`, this runtime stores them separately after different normalization/RoPE; do not halve the estimate again.

| Model / KV | 64k | 128k | 192k | 256k |
|---|---:|---:|---:|---:|
| 26B F16 | 1.54 GiB | 2.79 GiB | 4.04 GiB | 5.29 GiB |
| 26B Q8_0 | 0.82 GiB | 1.48 GiB | 2.15 GiB | 2.81 GiB |
| 26B Q4_0 | 0.43 GiB | 0.79 GiB | 1.14 GiB | 1.49 GiB |
| 31B F16 | 6.17 GiB | 11.17 GiB | 16.17 GiB | 21.17 GiB |
| 31B Q8_0 | 3.28 GiB | 5.94 GiB | 8.59 GiB | 11.25 GiB |
| 31B Q4_0 | 1.74 GiB | 3.14 GiB | 4.55 GiB | 5.95 GiB |

These are calculated K/V tensors, not measured total VRAM. Add weights, projector, compute/CUDA buffers, other state and Windows. Microbatch changes affect local allocation. `--swa-full` would remove this saving; it was false by default and not added by Marvin.

Qwen 3.8 already has a hybrid architecture: 16 full-attention and 48 DeltaNet layers. Its global Q8 KV at 256k is approximately 8.50 GiB plus recurrent state. Gemma 26B's global per-token cache growth is about 3.2 times smaller; 31B's is about 25% larger. The benefit is model-specific. [Qwen config](https://huggingface.co/Qwen/Qwen3.8-27B/blob/main/config.json).

## 6. Weight precision and 32 GB budgets

Weight and KV quantization are independent. Q5 weights plus Q8 KV is ordinary. GGUF Q4/Q5 are not hardware NVFP4, and mixed tensor precision means the name does not specify exact file size.

Sizes were checked through public file-list APIs without downloading weights:

| Variant | Weights | Separate projector |
|---|---:|---:|
| 26B official QAT Q4_0 | 13.448 GiB | 1.113 GiB |
| 26B Unsloth UD Q5_K_M | 19.698 GiB | ~1.113 GiB |
| 26B Unsloth UD Q6_K | 21.581 GiB | ~1.113 GiB |
| 26B Q8_0 | 25.015 GiB | ~1.113 GiB |
| 31B official QAT Q4_0 | 16.439 GiB | 1.118 GiB |
| 31B Q5_K_M | 20.171 GiB | ~1.118 GiB |
| 31B Q6_K | 23.471 GiB | ~1.118 GiB |
| 31B Q8_0 | 30.394 GiB | ~1.118 GiB |

[Google 26B QAT](https://huggingface.co/google/gemma-4-26B-A4B-it-qat-q4_0-gguf/tree/main), [Google 31B QAT](https://huggingface.co/google/gemma-4-31B-it-qat-q4_0-gguf/tree/main), [Unsloth 26B](https://huggingface.co/unsloth/gemma-4-26B-A4B-it-GGUF/tree/main), [Unsloth 31B](https://huggingface.co/unsloth/gemma-4-31B-it-GGUF/tree/main).

QAT is quantization-aware training. Include it in evaluation rather than assuming every four-bit file is worse than every Q5 file. Vendor quality claims still require tool tests. [Google QAT overview](https://ai.google.dev/gemma/docs/core).

The following estimates add **4–6 GiB** for desktop, compute buffers and headroom to weights/projector/KV. This is not a guaranteed overhead; desktop/other processes occupied roughly 2 GiB during inspection.

| Candidate | Weights + projector + KV | Including reserve | Assessment |
|---|---:|---:|---|
| 26B QAT Q4 / F16 / 256k | 19.85 GiB | 23.9–25.9 GiB | Promising |
| 26B QAT Q4 / Q8 / 256k | 17.37 GiB | 21.4–23.4 GiB | Most headroom |
| 26B Q5 / Q8 / 256k | 23.62 GiB | 27.6–29.6 GiB | Balanced candidate |
| 26B Q6 / Q8 / 256k | 25.51 GiB | 29.5–31.5 GiB | Plausible; test vision peaks |
| 26B Q8 / Q8 / 128k | 27.61 GiB | 31.6–33.6 GiB | Needlessly tight |
| 31B QAT Q4 / Q8 / 128k | 23.49 GiB | 27.5–29.5 GiB | Practical 31B candidate |
| 31B QAT Q4 / Q8 / 256k | 28.80 GiB | 32.8–34.8 GiB | Not a safe default |
| 31B Q5 / Q8 / 64k | 24.57 GiB | 28.6–30.6 GiB | Smaller-window candidate |
| 31B Q5 / Q8 / 128k | 27.22 GiB | 31.2–33.2 GiB | Borderline |

Actual reported GPU capacity was 31.84 GiB. 26B does not need 3–4-bit weights solely to reach 256k: Q5/Q8 looks feasible and Q6/Q8 may fit. QAT Q4 offers a smaller file and room for F16 cache. Large BF16 variants do not fully fit.

31B can mathematically reach 256k with Q4 weights and Q4 KV, but cache precision is a separate compromise requiring long-context accuracy tests. Mixed K/V precisions and external cache-compression forks are unnecessary for the first 26B experiment.

## 7. Speed evidence and estimates

Historical local logs from August 22–28 reported Qwen Q5 around 56–66 tokens/s in short runs, with another at 39.8; Qwen Q4 around 60–75; Ornith Q5 around 85–236; and one 400-token Nemotron Q4 run at 266.86. These aliases/logs are not a fresh controlled comparison of current weights, occupied context and settings. Zero-output runs are not throughput samples.

An external RTX 5090 experiment reported Gemma 26B Q4_K_M `tg128=219.9` and `pp512=8744` tokens/s. It used a modified runtime and short synthetic inputs, not Marvin on Windows. [Original experiment](https://github.com/tlskinner26/llama-cpp-blackwell-optimization).

Planning estimates without speculative decoding, one stream, fully GPU-resident weights and a short occupied context:

| Variant | Estimated generation |
|---|---:|
| 26B QAT Q4 / comparable Q4 | 130–220 tokens/s |
| 26B Q5/Q6 | 110–190 tokens/s |
| 31B Q4/Q5 | 40–70 tokens/s |

None is a local measurement of the recommended files. The 31B range is a rough dense-weight/bandwidth analogy with high uncertainty. Filled 128k–256k contexts will be slower; MoE does not eliminate global attention. Do not extrapolate `pp512` linearly to a book.

Measure prefill, generation including reasoning, and whole-task completion separately. Allocating 256k is not filling it. Repeated agent steps depend on cached-prefix reuse. As an illustration only, 3,000 output tokens take 50 seconds at 60 tokens/s or 19 seconds at 160, excluding prefill/tools and tokenizer/reasoning-length differences.

Gemma also has MTP draft checkpoints, explaining some high online speeds. They are outside this baseline proposal and the single-model product architecture. [Google overview](https://ai.google.dev/gemma/docs/core).

## 8. Integration work if later authorized

The GGUF/CUDA/OpenAI-compatible path can retain FastAPI, UI and agent loop. Architecture code exists in the inspected commit, but the exact model/projector pair remains untested.

1. Register definitions and distribution settings, retaining Qwen Q5 as default. Publish only measured profiles/hardware limits.
2. Use a uniquely named projector. The then-current downloader checked file existence/size, not model family; another generic `mmproj-F16.gguf` could incorrectly reuse Qwen's file. Google's `gemma-4-26B-it-mmproj.gguf` avoids that collision.
3. Set `supports_reasoning_effort: false`; Gemma's template uses `enable_thinking` (default false), not Qwen's `xhigh`. Expose genuine On/Off behavior.
4. Override sampling in both modes: temperature 1.0, top_p 0.95, top_k 64, explicitly avoiding inherited Qwen non-thinking presence penalty 1.5. [Model settings](https://ai.google.dev/gemma/docs/core/model_card_4).
5. Verify API reasoning/tool normalization. LLMClient accepts `reasoning_content` and `reasoning`, but its fallback understands `<think>`, whereas Gemma uses channel tokens. Prefer server parsing. [Prompt format](https://ai.google.dev/gemma/docs/core/prompt-formatting-gemma4), [function calling](https://ai.google.dev/gemma/docs/capabilities/text/function-calling-gemma4).
6. Qualify thinking-history retention. The launcher adds `--reasoning-preserve`; Google distinguishes retention within a tool cycle from removal across completed user turns.
7. Verify projector, image/text ordering and image-token policy. Global `--image-min-tokens 1024` is not automatically appropriate. Use small-text screenshots and PDF pages.
8. Test STOP, switching, compression and subsequent long-context tool turns, including restoration of Qwen's own UI controls.

## 9. Decision experiment

Start with a technical 26B QAT Q4 smoke test at 32k: startup, Czech response, thinking on/off, one tool call, at least five chained tools, screenshot and STOP. Only then qualify 128k/256k and consider a second quantization.

Run at least 15 representative tasks twice: five code repairs with outcome/tests, four constrained Czech text/document tasks, three image/PDF tasks, and three long-context tasks with multiple facts near the beginning/middle/end. Score actual outcomes, not merely valid JSON or a quick first token.

Use identical inputs with occupied prefixes around 4k/32k/128k and near 256k, leaving answer space. Record exact model/projector hashes, runtime, sampling, KV, VRAM peak, prefill/decode rates, whole-task time and offload. Separate fresh prefill from cache reuse and respect each profile's limits.

Proposed initial decision rule: offer Gemma as an alternative if it retains core features and repeatedly finishes relevant tasks about 1.5 times faster without materially lower success. This small set is a filter, not proof of general superiority. Change the default only after clear benefit on difficult tasks.

## 10. Physical 24 GB and 16 GB targets

Capacity determines whether a model fits, not its speed. GPU model, bandwidth, power, desktop/laptop design, driver and RAM offload matter. The estimates below are candidates, not guarantees. Restricting a 5090's allocation is not a physical small-GPU qualification.

### 24 GB: 26B QAT Q4

Weights plus projector need about 14.56 GiB. With Q8 KV, subtotal is 16.04 GiB at 128k and 17.37 at 256k.

| Candidate | Including 4–6 GiB reserve | Assessment |
|---|---:|---|
| 26B QAT Q4 / Q8 / 128k | 20.0–22.0 GiB | Primary fully GPU-resident candidate |
| 26B QAT Q4 / Q8 / 256k | 21.4–23.4 GiB | Extended profile after peak validation |
| 26B QAT Q4 / F16 / 128k | 21.4–23.4 GiB | Higher-cache-precision alternative |
| 26B UD Q5 / Q8 / 64k | 25.6–27.6 GiB | Unsuitable universal profile without offload |

The Q5 row refers to the specific large Unsloth UD file, not every Q5 quantization. Recalculate from actual file sizes for alternatives. Gemma might outperform the existing Qwen Q4/Q8/96k compact profile in speed/window size, while Qwen may still solve difficult development tasks better. Keep both as task-dependent choices with one loaded model.

31B QAT/Q8/32k already needs about 19.51 GiB before reserve, making it a tight 24 GB candidate without a compelling benefit. It is not a standard 16 GB proposal.

### 16 GB: prefer 12B to further squeezing 26B

26B QAT/projector already needs 14.56 GiB, or about 14.88 with just 16k Q8 KV. Context reduction alone leaves too little for desktop, compute and vision. Lower weight precision, disabling vision or offload may be avoided by choosing 12B.

12B files: official QAT Q4 6.497 GiB, Q5_K_M 7.836, Q6_K 9.114, Q8_0 11.800; the projector adds 0.163 GiB. Encoder-free architecture still has a GGUF projector artifact and does not mean ignoring mmproj. [Google QAT files](https://huggingface.co/google/gemma-4-12B-it-qat-q4_0-gguf/tree/main), [Unsloth files](https://huggingface.co/unsloth/gemma-4-12b-it-GGUF/tree/main), [Google introduction](https://blog.google/innovation-and-ai/technology/developers-tools/introducing-gemma-4-12B/).

12B has eight global layers (one KV head × 512) and 40 local layers (eight heads × 256), with window 1024. For one slot/microbatch 512:

| 12B KV | 32k | 64k | 128k | 256k |
|---|---:|---:|---:|---:|
| F16 | 0.97 GiB | 1.47 GiB | 2.47 GiB | 4.47 GiB |
| Q8_0 | 0.51 GiB | 0.78 GiB | 1.31 GiB | 2.37 GiB |

Derived from [12B config](https://huggingface.co/google/gemma-4-12B-it/blob/main/config.json) and the SWA implementation above. `GEMMA4UV`/`GEMMA4UA` paths in the bundled commit are not end-to-end qualification of a particular file. Image-heavy input can have different compute demands.

| 16 GB candidate | Including 4–6 GiB reserve | Assessment |
|---|---:|---|
| 12B QAT Q4 / Q8 / 64k | 11.4–13.4 GiB | Conservative starting candidate |
| 12B QAT Q4 / Q8 / 128k | 12.0–14.0 GiB | Recommended target |
| 12B QAT Q4 / Q8 / 256k | 13.0–15.0 GiB | Promising, pending speed/vision tests |
| 12B Q5 / Q8 / 64k | 12.8–14.8 GiB | Second quality candidate |
| 12B Q5 / Q8 / 128k | 13.3–15.3 GiB | Possible; test device headroom |
| 12B Q6 / Q8 / 64k | 14.1–16.1 GiB | Avoid as a universal starting default |

This is much smaller than Qwen IQ3_S (11.214 GiB weights plus 0.864 projector and larger cache), but does not prove higher intelligence. Use Qwen IQ3 at a supported compact context as the realistic 16 GB reference, not Qwen Q5.

Google reports 12B GPQA 78.8%, LiveCodeBench v6 72.0%, and Tau2 three-domain average 69.0%. Corresponding 26B figures are 82.3%, 77.1%, 68.2%; E4B 58.6%, 52.0%, 42.2%. On these metrics 12B is closer to 26B than E4B. The Tau2 average is not the retail-only metric on the original large-model page. [12B card](https://huggingface.co/google/gemma-4-12B-it).

### E4B, offload and harness support

E4B QAT has 4.801 GiB weights and a 0.923 GiB projector before KV/buffers. It may suit lightweight discussion or sharing a 16 GB GPU with another application; do not prioritize it over 12B for difficult development without evidence. [E4B files](https://huggingface.co/google/gemma-4-E4B-it-qat-q4_0-gguf/tree/main). PLE allows embedding tables outside VRAM, but savings/prefill cost need logs and tensor-placement checks; specialized offload is unnecessary as a first step for this small Q4 file.

26B offload on 16 GB is a possible later compromise if its task success substantially exceeds 12B. Label CPU/RAM use honestly and do not imply fully GPU-resident speed. Initial planning suggested at least 32 GB system RAM, preferably 64 GB, with separate CPU/PCIe measurements. Successful loading alone is insufficient.

Retain core operations for smaller models while reducing context overhead: mode-specific tool schemas, bounded readable results with continuation, summaries and explicit plans. Existing indexes/history tools help. Measure bad arguments, lost requirements and repetition; never hide essential user constraints to shorten prompts.

Choose defaults using actual available VRAM and headroom. Prefer a smaller same-model context before another model, and make model identity changes visible. Download the selected recommended model rather than every individually compatible file.

There is no honest single speed number for all 16/24 GB cards. A fully resident 26B MoE can decode faster than a smaller 12B dense model. External modified-runtime measurements, including different-GPU examples, cannot be transferred to these files. Before publishing hardware claims, test a real 24 GB and a real 16 GB card and identify GPU, power limit and occupied context.

The strongest product rationale for Gemma is broader small-GPU support. The deferred experiment remains 26B QAT for 24 GB and 12B QAT/Q5 for 16 GB, with Qwen Q5 retained at 32 GB and 26B considered as a fast alternative. Add 31B, E2B or more quantizations only after a concrete demonstrated benefit.
