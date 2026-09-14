# Marvin 1.8.1: delays between Flash-Next steps

Measured 13 September 2026 on RTX 5090 32 GiB, Core Ultra 7 265K (8 P + 12 E) and 64 GiB RAM. Baseline: `9d8bf49`, Marvin 1.8.0. These are historical measurements; current memory changes are described in [memory profiles](../design/memory-profiles.md).

## Cause and limits

The running research task generated about 23–27 tokens/s and processed new input at about 85–130 tokens/s. For example, 7,796 new tokens took 66 seconds despite reusing 13,047 cached tokens. A later request reused over 49k tokens, so caching was not globally disabled.

The then-current 256k Q8 plan placed experts from 34 of 48 layers on CPU/RAM. VRAM was nearly full despite low GPU compute utilization. Utilization alone does not imply that more threads or GPU power would help. Earlier prefill comparison favored eight P cores over all 20 physical cores.

A diagnostic sampled only after the first reasoning token: all eight P cores showed 95.2–100%, the process consumed about 7.7 CPU cores, and GPU utilization was 25–26% at 142 W with 29,865 MiB VRAM used. Short generation measured 29.04 tokens/s with xhigh. Process read counters showed 0 MiB/s; total system physical reads of 13–23 MiB/s could not be attributed solely to the model. The sample supports CPU/memory-service limitations but does not isolate computation from RAM latency/bandwidth or promise full-context throughput.

A separate 20-thread decode test, retaining eight P cores for prefill, hit the then-current 2 GiB free-RAM guard. It produced no valid speed comparison. The additional memory demand was not independently profiled, and production remained on eight P cores. Evidence: `decode-all-cores/outcome.json` and server log.

A second defect affected changing project/plan context: the harness appended a snapshot before one response, then removed and moved it to the end on the next step, invalidating the prefix preceding the generated answer/reasoning. It was not the primary delay in the observed projectless research task without pins.

## Changes

- Actual context changes are persisted as internal messages before the response they belong to. Project, instructions, decisions, plan and pinned files are compared independently, avoiding retransmission of a large unchanged document when one plan item changes. Latest values replace a section; empty values clear it. Internal records are hidden from user messages, create no new task boundaries and are not written by request previews. Normal compression and undo/retry still manage history.
- Native llama.cpp `prompt_progress` drives Reading context. Percentages cover new input separately from cached tokens, including helper planning, synthesis and compression. Timers are phase-specific and STOP remains available.
- `web_fetch` supports literal passage `query` (alternatives separated by `|`), `start` pagination and explicit `refresh`. A source is not repeatedly downloaded within a task. Full fetched text remains in research evidence up to its existing limit; a returned excerpt does not replace the stored source or filter it by credibility.
- Q3_K_XL weights, Q8 KV, requested 256k context, xhigh, reasoning preservation, b10935 and dependency versions were unchanged. IQ3 was neither downloaded nor enabled.

## Comparisons

`tests/check_prompt_performance.py` owns one isolated server on port 8081, rejects concurrent model servers, and stops its process in cleanup. Historical output `runtime/validation/performance-1.8.1/` is now in the local archive.

| Follow-up test | Old behavior | Preserved prefix |
|---|---:|---:|
| First output, measurement 1 | 5.543 s | 1.030 s |
| First output, measurement 2 | 5.886 s | 1.016 s |
| Cached tokens | 68 | 606 |
| Reprocessed tokens | 560 | 44 |

Order was ABBA, with identical sampling and 512-token output limits; effort `low` applied only to the synthetic comparison. This measures latency, not intelligence or whole-task performance. All four prefix comparisons in `flash-abba/results.json` completed. A later numeric-answer attempt exhausted an insufficient reasoning budget and was repeated separately.

| Same occupation-list query | Whole source | Targeted passage |
|---|---:|---:|
| Source tokens | 6,710 | 310 |
| First output | 53.037 s | 4.138 s |
| ANZSCO code returned | 261211 | 261211 |

`source-compare/results.json` records `complete=true`. Thinking was off in both branches for this simple extraction; installed settings were unchanged. A specific query selected the excerpt. This does not prove that one passage can replace broad research. New long evidence and the first history read after restart remain costly.

## IQ3 versus the chosen Q3

The checkpoint has Unsloth `UD-IQ3_XXS` and `UD-Q3_K_XL` variants, not two separately trained models. Published quantization analysis:

| Variant | Weights excluding projector | Top-1 agreement | Mean KLD |
|---|---:|---:|---:|
| UD-Q3_K_XL | 90.0 GB | 88.315% | 0.106504 |
| UD-IQ3_XXS | 82.0 GB | 85.414% | 0.165120 |

Top-1 agreement is not a percentage of intelligence, and KLD is not an agent benchmark. The smaller IQ3 deviates further from the reference distribution. Approximately 9% weight savings do not prove faster execution: kernels and expert placement matter. Given the owner's priority of answer depth, Q3 remained recommended. Local IQ3 speed/quality were not measured. [Unsloth analysis](https://unsloth.ai/docs/models/qwen3.8-next#quantization-analysis), [checkpoint files](https://huggingface.co/unsloth/Qwen3.8-Flash-Next-GGUF/tree/main).

[Exact llama.cpp build documentation](https://github.com/ggml-org/llama.cpp/blob/8e330954adb6e86c329c9d7e338f01f93ffe4b88/tools/server/README.md) describes prefix reuse and progress events.

## Release verification

366 core checks and 56 service/runtime tests passed, including prefix retention, pin deduplication, history recovery, native progress, STOP and targeted excerpts. All 56 also passed in the installed environment.

The compiled UI was opened with an isolated deterministic model, displaying 50% new-input progress and 10k cached tokens. STOP left a resumable task. Updated PDF pages were rendered and checked (CS page 11, EN page 15).

The real 1.8.1 upgrade and private-environment preparation exited 0. All 699 checked user-data files matched the prior state, and installed Python sources matched distribution. Flash-Next, xhigh and 256k Q8 remained selected. Installed `Marvin.exe --smoke` started UI/model, stopped both and freed VRAM, exiting 0.

All seven distribution-ZIP entries passed CRC/SHA-256. Offline dependency restoration into a clean temporary environment and API startup passed; no clean Windows VM is claimed. The offline update replaced installer/manuals/guides/manifest while 73 unchanged entries retained size, mtime and hash. Weights and environment were not repacked. The then-current folder was `Marvin-Offline-Backup-1.8.1/`, registered with the installed app.

| Historical file in `dist/` | Bytes | SHA-256 |
|---|---:|---|
| `Marvin-Setup-1.8.1-Minimal.exe` | 52,346,422 | `c686c0b5f4dde718f986a372f38b24fa08c22b7d808335ee9888628b1006eeab` |
| `Marvin-Setup-1.8.1-Full.exe` | 727,131,861 | `1d15613b71dd36607c6973b3a9107f86c7fcf2435840f50f5a00a00ccdbc9864` |
| `Marvin-1.8.1-Windows-x64.zip` | 778,627,972 | `0d50e2ed009f4bb926a2de9d68fdd9034e6d8319cc73c85662f9d8e9a431eff3` |

Offline manifest SHA-256: `64f9edf4dfd6bb395476aa16322dde3b45ca7c0710e68f6242259212d484b010`.

`runtime/archive/verification-1.8.1.zip` holds 103 files with verified per-file CRC/SHA, archive SHA `4af2481d648dd995ff1853735c5e856a18a1ec6d55240f43eb2c39572e157318`. Private backups keep it out of Git/distribution. Reproducible build/test leftovers were marked for manual removal under `runtime/KE-SMAZANI/after-1.8.1/`; active models and dependencies were retained.
