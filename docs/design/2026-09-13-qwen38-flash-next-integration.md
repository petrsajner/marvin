# Qwen3.8-Flash-Next: integration research and qualification

Historical update: 13 September 2026, Marvin 1.8.0. Flash-Next was integrated and installed; measurements and limits appear in section 10 and the [release report](../distribution/RELEASE-1.8.0.md). Sections 1–9 retain the research/design baseline of Marvin 1.7.0, commit `6b687458ca09879ceac81baa72bd53f9b52fad65`. Existing-model comparison preceded runtime activation: [b10935 qualification](../distribution/LLAMA-b10935-VALIDATION.md).

Translated and consolidated on September 15. Later changes supersede historical tuning values where noted: [prefix performance](../distribution/PERFORMANCE-1.8.1.md), [Continue model selection](../distribution/CONTINUE-MODEL-1.8.2.md), [current memory profiles and recovery](memory-profiles.md).

## Binding requirements

- Use standard upstream llama.cpp. **Do not use GenerelSchwerz.** The owner clarified that the video author explicitly discouraged it after no performance benefit and a system freeze. A link in a video description was not a recommendation.
- Target Q3 weights, specifically **UD-Q3_K_XL**. The video's IQ3_XXS is a reference, not an automatic substitute.
- Use **Q8_0 KV**, at least **131,072 tokens**. Prefer 196,608 or 262,144 only when memory, performance and quality permit. A 16k/32k smoke test does not qualify a completed Flash-Next integration.
- Users select a model normally. Runtime, threads, CPU/GPU placement, shards and projector configuration are internal.
- Dependency upgrades must preserve all existing models and features, established with real regression runs rather than imports or mock models alone.
- Adapt to actual CPU topology, RAM, VRAM, driver and storage. Do not hardcode the 5090/265K configuration for other machines.
- Keep one model and one sequential agent. Vision belongs to that selected model.

## 1. Sources and model identity

Video: Codacus, [Is Frontier Class Local AI Finally Practical?](https://www.youtube.com/watch?v=IH8XmxiwliQ). Its description identified RTX 3060 12 GB, Ryzen 5 5600X, 64 GB DDR4, `unsloth/Qwen3.8-Flash-Next-GGUF`, UD-IQ3_XXS, about 82 GB. The author reported 13.6 versus 24.4 tokens/s with 12 versus six threads. The 24/40 GB RAM observations and negative fork experience came from the owner's account of the video; they are not reproduced local benchmarks.

In [spec-wins](https://github.com/thecodacus/spec-wins), the author described the Pi agent harness, shell/SSH sandbox access and 17/17 checks across three tasks using IQ3_XXS. This is limited evidence of agent use, without vision qualification or proof of general superiority over cloud models.

The open checkpoint is **Qwen3.8-Flash-Next**: `qwen4_exp` in Transformers and `qwen4exp` in llama.cpp. It has approximately 125B main-network parameters, 6B active per token and 51B n-gram embeddings; MTP is listed separately. It is natively multimodal, with 48 layers, hybrid Gated DeltaNet/Qwen Sparse Attention, ten of 512 routed experts plus a shared expert. [Technical report](https://arxiv.org/abs/2608.30320), [configuration](https://huggingface.co/Qwen/Qwen3.8-Flash-Next/blob/main/config.json).

## 2. What the memory saving means

| Component | Placement/work | Constraint |
|---|---|---|
| PLE/n-gram table | Learned vectors loaded by selected file rows | Uses RAM/page cache; not zero RAM |
| Routed experts | CPU/GPU placement; selected experts compute each token | Active parameters are not total required weights |
| Dense/shared weights and vision | Prefer GPU when feasible | Need image/compute headroom |
| KV, QSA indexer, recurrent state | Processed-prefix state | Must survive tool calls, STOP, steering and compression correctly |
| Marvin file indexes/history | Retrieve relevant inputs | Not replaced by the lookup table |

The lookup table is not a database of finished answers. Random-read latency can constrain SSD access even at low aggregate MB/s.

Upstream marks `per_layer_tok_embd` as `TENSOR_READ_LAZY`. The loader creates mappings for these tensors alongside a different loading mode for regular weights. **Lazy PLE and whole-model mmap are separate mechanisms.** No experimental expert cache is used. [Model](https://github.com/ggml-org/llama.cpp/blob/b10935/src/models/qwen4exp.cpp), [loader](https://github.com/ggml-org/llama.cpp/blob/b10935/src/llama-model-loader.cpp).

The research direction was lazy PLE plus normal CPU/GPU offload, choosing loading mode from measured RAM pressure. Blanket mlock or consuming nearly all desktop RAM was not acceptable.

## 3. Q3 files and 128k–256k context

Inspected Unsloth revision: `38bb39ee97821de2c9009abb7e93950eec396e66`.

| Variant | Disk weights | Shards | Role |
|---|---:|---:|---|
| **UD-Q3_K_XL** | **89.986 GB / 83.806 GiB** | 3 | Selected target |
| UD-IQ3_XXS | 81.962 GB / 76.333 GiB | 3 | Video reference; optional later evaluation |
| UD-IQ4_XS | 93.683 GB / 87.249 GiB | 3 | Outside initial scope |
| UD-Q4_K_XL | 111.335 GB / 103.688 GiB | 4 | Outside initial scope |

`mmproj-F16.gguf` adds 904,004,000 bytes (~0.842 GiB). All shards are required and the server receives the first, which is only 10,946,624 bytes. [Pinned file list](https://huggingface.co/unsloth/Qwen3.8-Flash-Next-GGUF/tree/38bb39ee97821de2c9009abb7e93950eec396e66). Quantization scores are not retained-intelligence percentages; validate tools, tasks and images. [Quantization analysis](https://unsloth.ai/docs/models/qwen3.8-next).

For 12 QSA layers, two KV heads × 256 and one indexer key head × 128, b10935 gives:

`attention + indexer bytes = 12 × (2 × 2 × 256 + 128) × context × (34 / 32)`

| Context | Calculated Q8 attention + indexer tensors |
|---|---:|
| 128k / 131,072 | 1.793 GiB |
| 192k / 196,608 | 2.689 GiB |
| 256k / 262,144 | 3.586 GiB |

This excludes weights, recurrent state/checkpoints, compute buffers, vision and desktop. QSA selection does not permit throwing away the remaining KV. [Hybrid indexer cache](https://github.com/ggml-org/llama.cpp/blob/b10935/src/llama-memory-hybrid-idx.cpp). The 128k-to-256k tensor increase is about 1.79 GiB, a reason to test rather than proof of acceptable performance.

At research time, [QSA gather #28213](https://github.com/ggml-org/llama.cpp/pull/28213), [pooled indexer #28699](https://github.com/ggml-org/llama.cpp/pull/28699) and [CUDA sparse FA #28770](https://github.com/ggml-org/llama.cpp/pull/28770) were open proposals. Their potential gains were not release features; no unqualified cherry-picks were part of integration.

Acceptance requires usable long context, not allocation alone. A 128k test should process roughly 120k input tokens with output reserve; larger profiles need equivalent qualification. Context includes system instructions, tool schemas, image tokens, history, reasoning and answers.

## 4. Hardware adaptation design

The original GPU helper mainly used total VRAM. The new internal plan separates hardware execution from the user's model selection.

Detection covers physical/logical CPU topology, usable processor groups, performance classes and optionally NUMA; physical/available RAM and commit pressure; GPU identity/architecture/driver and total/free VRAM; local storage and complete-file space; and exact runtime/model tensor metadata. Pagefile commit is not fast physical RAM. [Windows CPU sets](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-getsystemcpusetinformation), [memory status](https://learn.microsoft.com/en-us/windows/win32/api/sysinfoapi/ns-sysinfoapi-memorystatusex).

The 265K probe found eight physical/logical P cores at EfficiencyClass 1 and 12 E cores at class 0, with no Hyper-Threading. Do not divide logical CPUs by two or assume P cores are the first eight IDs. Decode/prefill thread counts and affinity are separate settings, scoped to the inference process rather than Windows globally.

The planned execution record includes runtime/model identity, actual context, K/V types, decode/prefill pools, affinity, CPU expert-layer count, GPU placement, load/lazy modes, batch/microbatch, reserves and hardware/runtime calibration identity.

Selection principles:

1. Respect the chosen weights, targeting Q3_K_XL here.
2. Evaluate Q8 contexts from 256k through 192k to 128k with usable headroom.
3. Consider legal placements and batch sizes; maximum VRAM occupation is not necessarily fastest.
4. Budget physical RAM, commit and working buffers separately and monitor loading too.
5. Keep calibration bounded; do not run a full benchmark or 128k warmup on every selection.
6. Invalidate hardware/runtime/model-specific cached plans when their identity changes.
7. Recheck dynamic availability before every start, release the previous owned model, then measure again.

These are design requirements, not a claim that every calibration or I/O probe was implemented. Current implemented behavior is documented in [memory profiles](memory-profiles.md). A Flash profile that cannot maintain 128k with vision and the agent loop is not fully supported. The 128k floor applies to Flash-Next; older small models retain their own practical contexts.

Protect ordinary browser/PDF/image work. Stop only Marvin's owned load/run before critical pressure, restore a working state, and never terminate unrelated applications. Slow prefill is not by itself evidence of a dead process.

## 5. User-facing contract

Selecting a model verifies complete weights/projector, selects a compatible runtime and hardware plan, releases the prior model, reloads with fresh memory measurements, configures thinking/tools and continues in the existing chat/work mode.

No fork, CPU-layer, affinity, mmap or shell tuning is required from the user. Preparation uses existing progress and STOP controls; technical details belong in diagnostics. Do not report Ready with missing shards or a broken projector. UI/client context limits must match the actual profile. Never silently assign Flash-Next less than 128k or substitute another identity for an explicit Flash selection. If it cannot run, restore the prior working state with a short reason.

Manual switch, autostart, restart, Continue and configuration changes must share the same effective plan. The original paths did not fully share this logic and `fit_hardware` could change model identity; subsequent fixes address consistency and recovery.

## 6. Agent continuity and vision

The agent loop needs no second copy of weights. It needs valid cached-prefix and hybrid-state continuity. The original dynamic project-context tail could change between tool turns; later [prefix retention](../distribution/PERFORMANCE-1.8.1.md) addressed that defect.

Qualification should cover chained tool rounds over long prefixes, file/instruction changes, STOP/Continue, steering, queueing, chat reload/switches, same-model compression, screenshot/tool/screenshot sequences, PDF OCR, microbatch boundaries, prefix rollback, PLE history, recurrent state and QSA indexer. [Issue 28425](https://github.com/ggml-org/llama.cpp/issues/28425) was external evidence of hybrid partial-rollback risk, not a locally reproduced bug.

Measure actual newly evaluated prompt tokens. At an illustrative 200 prompt tokens/s, reprocessing 120k would take ten minutes; a short tool result should not unnecessarily trigger that work. `--cache-ram` is server prompt/state cache, not expert cache or the OS page cache, and must be budgeted.

Flash-Next's generic projector filename collides with Qwen 27B's despite different output dimensions. Separate model directories/manifests prevent reuse of the wrong file. A color-image smoke test is insufficient: verify text extraction and a subsequent real tool action in the UI. Thinking/effort and structured tools should retain existing controls and use server-parsed API outputs, not guessed repairs to invalid arguments. [Checkpoint/settings](https://huggingface.co/Qwen/Qwen3.8-Flash-Next).

## 7. Runtime upgrade and regression matrix

b10549 / `b2e5e9b28` lacked this architecture. Upstream added it in [PR 27742](https://github.com/ggml-org/llama.cpp/pull/27742). Candidate b10935 / `8e330954adb6e86c329c9d7e338f01f93ffe4b88` was activated on September 13 only after existing-model comparison, retaining b10549.

The old downloader selected the latest release and deleted the current directory before extraction. The implementation replaced that with pinned staging, verified CUDA payloads/hashes and recoverable activation. Retain the last working runtime and exact Python lock; validate relevant behavior before promotion. Failed preparation must not overwrite user data or weights. Update only necessary packages, not every available dependency, and do not modify the system driver, Python or PATH. Minimal/Full distribution need their own verification when rebuilt.

Users do not choose runtimes. Prefer one qualified set for every supported model; an internal compatibility fallback would still require real testing of both paths.

| Variant | Required coverage |
|---|---|
| Qwen IQ3_S | Own KV profiles, chat, thinking, tools, vision |
| Qwen Q4_K_M | F16/Q8 profiles and the same features |
| Qwen Q5_K_M | Existing long-context work, effort, tools, vision |
| Ornith Abliterated Q5 | Its sampling/template, thinking, tools, vision |
| Nemotron Q4_K_XL | Text, thinking on/off, tools, long context, CPU spill |
| Nemotron Q5_K_XL | Same, with particular attention to tight memory profiles |
| Flash-Next Q3_K_XL | Applicable features plus vision and practical context of at least 128k |

Nemotron is text-only in this catalog; absent vision is not a regression. Compare old/new runtimes with identical files and settings, real outputs/arguments, cold/warm prefill, follow-ups, decode, memory and restart/switch cycles. Separately test incomplete downloads, missing DLL/projector, recovery and application restart. Capacity limits on a 5090 do not replace physical smaller-GPU/CPU/RAM-bandwidth tests.

The first stage passed 366 core checks and 21 service tests plus 22 profiles on both runtimes, long inputs and a nearly full 192k Qwen Q5 window. That initial stage alone did not qualify Flash-Next, different hardware or a new installer. [Detailed runtime evidence](../distribution/LLAMA-b10935-VALIDATION.md).

## 8. Implementation surfaces

| Area | Responsibility |
|---|---|
| GPU/hardware planning | CPU topology, RAM/commit, GPU/driver and per-machine plan |
| Configuration | Model definition, requested context and effective startup settings |
| Application/model switch | Consistent start paths, current configuration and rollback |
| Server management | Runtime selection, planned arguments, load/run pressure monitoring |
| Model download/setup/backup | Complete shard/projector manifest, revision/hash/size and completion marker |
| Runtime download/dependencies | Pinned staging, validation, activation and prior working set |
| Web API/settings | Actual model completeness/context with simple controls |
| Client/agent/session/context | Prefix/state continuity and interruptible long prefill |
| Tests/distribution | Model matrix, real long input/vision, portability qualification |

The earlier installed check used only one file's existence and configured vision capability. A sharded model needs a complete validated manifest, especially since its 11 MB first shard is below the old downloader's 1 GiB heuristic. No rewrite of the web app, SSE or agent loop was necessary.

## 9. Delivery sequence and acceptance

Record the six-variant baseline, stage and qualify upstream, implement manifests/hardware planning/switching, then test Q3/Q8 at 128k followed by larger contexts. Qualify tool/vision/STOP/steering/compression and low-memory recovery, then physical smaller machines. Only qualified results justify a distribution release. Keep diagnostics bounded instead of accumulating many experimental environments.

Acceptance means a normal model selection provides working Marvin features with at least 128k Q8 and no existing-model regression. Actual qualification limits are explicit below, rather than treating every original design test as completed.

## 10. Implementation and measured results on September 13

All four Q3 files were downloaded and checked against pinned SHA-256 values: 90,890,357,824 bytes including the dedicated projector. GGUF inspection found 26.822 GiB lookup tables, 51.990 GiB experts, 4.984 GiB shared weights and 0.842 GiB projector. The manifest ties derived memory metadata to the exact revision/hashes, allowing preflight checks before a 90 GB transfer and rechecking actual files/resources afterward.

| Q3 / Q8 / 128k load settings | Observed result |
|---|---|
| `--lazy-mode on --load-mode mmap` | Short reply/reasoning at 17.34 tokens/s, then a later request hit the old 2 GiB free-RAM guard; rejected |
| `--lazy-mode on --load-mode none` | CUDA initialization failed on this PC; rejected |
| `--lazy-mode on --load-mode none --no-host` | Loaded in ~40 seconds, generated 27.29 tokens/s; passed chat, reasoning, tool roundtrip, two images, STOP in decode/prefill and two real write/read agent tasks; a sample retained ~12 GiB free RAM |

In this build, partial unmapping on Windows is a no-op. Lazy tensors can still be mapped independently with `load-mode none`. `no-host` avoids CUDA host buffers for CPU weights and permits CPU buffers/repacking. These observations support the selected combination but do not isolate every memory difference experimentally. [Windows mmap](https://github.com/ggml-org/llama.cpp/blob/8e330954adb6e86c329c9d7e338f01f93ffe4b88/src/llama-mmap.cpp#L577), [lazy mapping](https://github.com/ggml-org/llama.cpp/blob/8e330954adb6e86c329c9d7e338f01f93ffe4b88/src/llama-model-loader.cpp#L1289), [CPU buffers](https://github.com/ggml-org/llama.cpp/blob/8e330954adb6e86c329c9d7e338f01f93ffe4b88/src/llama-model.cpp#L994).

A successful log recorded 27,465 MiB lazy PLE, 1,632 MiB Q8 attention cache and 204 MiB indexer cache at 131,072 cells, approximately 1,859 MiB GPU compute buffer and 113 MiB recurrent state. Actual allocation and functional checks remain authoritative over estimates.

The eight P cores had logical IDs `0,1,6,7,8,9,18,19`, not the first eight IDs. With the same 7,711-token three-marker input, 32 CPU expert layers and Q8/128k:

| Prefill CPU pool | First answer | Follow-up |
|---|---:|---:|
| Eight P cores | 68.437 s | 1.219 s |
| All 20 physical cores | 85.829 s | 1.312 s |

The planner therefore preferred detected P cores for decode/prefill and physical cores on homogeneous CPUs. This is a measured choice for this hybrid CPU, not a universal claim.

The completion race was fixed and tested. Existing Qwen Q5 passed the new web startup/reply/write/read/STOP path. All 95 Python versions were unchanged; `filelock` was merely declared explicitly as a direct dependency.

Historical evidence under `runtime/validation/flash-next/` includes `preparation.json`, `memory-preflight.json`, `regression/results.json`, `initial-128k/results.json`, `resident-128k/results.json`, `no-host-128k/results.json`, `batch-p-128k/results.json`, and `batch-all-128k/results.json`. The long `no-host-128k` attempt was intentionally interrupted to compare CPU pools and is marked accordingly. These paths are retained in the local release archive.

### Completed qualification

| Profile | Actual input | First answer | Follow-up | Result |
|---|---:|---:|---:|---|
| Q8 / 128k | 122,397 tokens | 1,053.687 s | 1.266 s | All three facts correct; 122,429 cached tokens reused |
| Q8 / 256k | 24,101 tokens | 200.516 s | 1.187 s | All facts correct; server confirmed 262,144 capacity |

Both also passed image → write_file → read_file with exact file-value checks. `qualified-128k/results.json` and `functional-256k/results.json` report success. Minimum free RAM was about 11.56 and 9.74 GiB respectively. Device GPU values include desktop/other processes.

`flash_next_q3` entered the 1.8.0 picker with a default request of 256k Q8 and adaptive selection of 256k/192k/128k. It was excluded from ordinary automatic model downloads until explicitly selected. Existing variants kept their own policies.

Real web UI switching Qwen Q5 → Flash-Next selected 256k, answered from prior history, and processed an uploaded image followed by file write/read. Insufficient pre-download memory prevented an unsupported transfer; failed switching restored the prior model/settings. Download progress displayed bytes/percentages, and the launcher recognized installations containing nested Flash shards only.

**Limits:** the complete 256k window was not filled. 192k was an intermediate planned profile, not a separately qualified long run. `portability-estimates.json` was not a physical 16/24 GB test. One old estimate for 16 GB/128k with 2 GiB occupied VRAM needed almost 56 GiB free system RAM; installed 64 GB alone was insufficient. Later reserves/pressure recovery supersede those old estimates; see [current memory report](memory-profiles.md).

The real `%LOCALAPPDATA%/QwenHarness` installation upgraded from 1.6.2 to 1.8.0 via Full/offline setup. Fifty installed tests and startup/shutdown of the retained Ornith selection passed. All 369 checked user-data files were byte-identical; installed source/manuals matched distribution.
