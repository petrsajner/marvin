# GPU profile qualification and approved menu

15 September 2026. The owner approved this measured table for Marvin 1.9.0. Production profiles, recovery logic, installed settings and release assets were not changed during the audit itself. The subsequent implementation is described in [memory profiles](memory-profiles.md). The opt-in MTP speculative variants added later reuse these plain measurements plus a separately measured draft increment; see [mtp-profiles](mtp-profiles.md). No plain case was re-run.

Portable raw-result summaries: [JSON](measurements/2026-09-15.json) and [CSV](measurements/2026-09-15.csv). Full local evidence is retained as `runtime/archive/profile-remeasurement-2026-09-15.zip`, SHA-256 `a165eabebcffb886ec484969c28193e91e36ca58c40bb1a7590b42fbec03f9b0`. Reuse these results for the same weights/runtime/arguments; rerun only affected cases when an allocation or dependency changes.

A total of 55 launches were recorded. Fifty-two completed their functional checks; two early Flash attempts were stopped by the discarded commit-only guard and one 16 GiB placement reached sustained critical physical RAM during warmup. Passing a functional check on the 5090 is distinct from fitting a smaller comparison budget.

## Requested menu

Q8 below means Q8_0 KV cache; model weight quantization is a separate property. A k denotes 1,024 tokens. Show only the two highest relevant contexts per model/cache-precision group. IQ3 is not proposed for 32 GiB. F16 is confined to the requested 32 GiB Qwen options.

| GPU class | Model | KV precision | Proposed contexts | Placement / condition |
|---|---|---|---|---|
| 16 GiB | Qwen IQ3 | Q8 | 64k, 48k | CPU image projector; 64k is close to the capacity boundary and uses live availability |
| 24 GiB | Qwen IQ3 | Q8 | 128k, 96k | GPU image projector |
| 24 GiB | Qwen Q4 | Q8 | 96k, 64k | GPU image projector |
| 24 GiB | Qwen Q5 | Q8 | 96k, 64k | CPU image projector; 96k depends on memory available to the model |
| 32 GiB | Qwen Q4 | Q8 | 256k, 192k | GPU image projector |
| 32 GiB | Qwen Q4 | F16 | 128k, 96k | Explicit optional precision group |
| 32 GiB | Qwen Q5 | Q8 | 192k, 128k | GPU image projector |
| 32 GiB | Qwen Q5 | F16 | 128k, 96k | Explicit optional precision group |
| 32 GiB | Ornith Q5 | Q8 | 256k, 192k | Both within the GGUF native 262,144-token context |
| 24 GiB | Nemotron Q4 | Q8 | 512k, 256k | Some expert weights execute on CPU; exact measured settings below |
| 32 GiB | Nemotron Q4 | Q8 | 512k, 256k | Fully GPU-resident inference weights in these tests |
| 24 GiB | Nemotron Q5 | Q8 | 512k, 256k | More CPU expert execution; no invented R cache type |
| 32 GiB | Nemotron Q5 | Q8 | 512k, 256k | 512k with one CPU expert block; 256k passed fully on GPU |
| Flash-Next | Q3 weights | Q8 | Highest two feasible choices from 256k, 192k, 128k | Select using GPU placement, RAM and actual startup behavior together |

Recovery must keep the model, KV precision and already selected weight placement, changing only to the next lower context. Moving CPU experts back onto the GPU during recovery could consume the memory that the smaller cache just freed. Do not automatically alternate Q8/F16 or switch models.

## Measurement conditions

One RTX 5090 (31.84 GiB reported capacity), Core Ultra 7 265K with eight P and twelve E cores, 64 GiB-class RAM and the existing upstream runtime. Tests used one process/slot, P-core threads, Flash Attention, --fit off and the exact requested allocation. Production minimum-VRAM filters and automatic profile reduction were bypassed. This is not physical 16/24 GiB GPU validation.

The initial controlled matrix used batch1024/microbatch128 and a 256 MiB auxiliary prompt cache. Reference cases then used the original batch2048/microbatch512 and 8192 MiB auxiliary cache; every case records its command. Flash final cases use microbatch256, 256 MiB auxiliary cache and a fixed CPU-expert placement for clean context comparisons. This auxiliary cache is not the context size.

GPU totals include other programs and driver reservations. PID-specific Windows dedicated-memory counters are preferred where available; early cases use measured increases over baseline. Do not turn total desktop usage into a universal card-size minimum. Working set is physical RAM observed in the process, not its irreducible minimum: Windows may reclaim mapped file pages and page out inactive allocations. Private commit must not be added to VRAM as physical RAM.

Checks include deterministic short generation, a structured tool roundtrip, two distinct OCR images where supported, STOP, varied public-repository input and cached follow-up recall. The input-token column states actual coverage: a 512k allocation with a 32k input is not a filled 512k test. Decode rates use a short 256-token task with thinking off and are not whole-task performance promises.

## Detailed measured cases

| Case | KV / window | Total GPU GiB | PID GPU GiB | GPU increment GiB | Peak working set GiB | Decode tok/s | Long input tokens | Recall | Status |
|---|---|---:|---:|---:|---:|---:|---:|---|---|
| iq3-48-original | q8_0 / 48k | 16.904 | — | 14.253 | 13.254 | 86.32 | — | — | Passed functional checks |
| iq3-48-gpu-vision | q8_0 / 48k | 16.819 | — | 14.124 | 11.567 | 85.89 | — | — | Passed functional checks |
| iq3-48-cpu-vision | q8_0 / 48k | 15.604 | — | 12.95 | 12.977 | 87.27 | 40846 | True | Passed functional checks |
| iq3-64-cpu-vision | q8_0 / 64k | 16.212 | — | 13.566 | 12.988 | 88.2 | 57233 | True | Passed functional checks |
| iq3-32-cpu-vision | q8_0 / 32k | 15.091 | — | 12.431 | 12.812 | 85.43 | 24460 | True | Passed functional checks |
| q5-96-gpu-vision | q8_0 / 96k | 25.316 | — | 22.991 | 18.618 | 62.78 | — | — | Passed functional checks |
| q5-96-cpu-vision | q8_0 / 96k | 24.247 | — | 21.923 | 19.996 | 62.53 | 89998 | True | Passed functional checks |
| q5-64-cpu-vision | q8_0 / 64k | 23.044 | — | 20.723 | 19.98 | 62.29 | 57233 | True | Passed functional checks |
| q5-f16-128 | f16 / 128k | 29.97 | — | 27.654 | 19.033 | 62.78 | 122768 | True | Passed functional checks |
| ornith-256 | q8_0 / 256k | 30.227 | — | 27.906 | 24.237 | 239.89 | 253840 | True | Passed functional checks |
| ornith-192 | q8_0 / 192k | 29.453 | — | 27.129 | 24.031 | 226.67 | 188305 | True | Passed functional checks |
| iq3-24-128 | q8_0 / 128k | 19.521 | — | 17.162 | 12.038 | 87.27 | 122768 | True | Passed functional checks |
| iq3-24-96 | q8_0 / 96k | 18.506 | — | 16.147 | 12.017 | 86.82 | 89998 | True | Passed functional checks |
| q4-24-96 | q8_0 / 96k | 22.285 | — | 19.925 | 15.943 | 71.57 | 89998 | True | Passed functional checks |
| q4-24-64 | q8_0 / 64k | 21.216 | — | 18.858 | 15.641 | 71.57 | 57233 | True | Passed functional checks |
| q4-32-256 | q8_0 / 256k | 28.37 | 25.893 | 25.919 | 15.759 | 71.57 | 253840 | True | Passed functional checks |
| q4-32-192 | q8_0 / 192k | 25.952 | 23.502 | 23.514 | 16.0 | 71.59 | 188305 | True | Passed functional checks |
| q4-f16-128 | f16 / 128k | 26.877 | 24.371 | 24.447 | 15.97 | 72.53 | 122768 | True | Passed functional checks |
| q4-f16-96 | f16 / 96k | 24.807 | 22.363 | 22.376 | 15.793 | 73.85 | 89998 | True | Passed functional checks |
| q5-32-192 | q8_0 / 192k | 29.273 | 26.58 | 26.836 | 19.065 | 60.9 | 188305 | True | Passed functional checks |
| q5-32-128 | q8_0 / 128k | 26.713 | 24.189 | 24.188 | 19.03 | 61.82 | 122768 | True | Passed functional checks |
| q5-f16-96 | f16 / 96k | 27.906 | 25.441 | 25.44 | 19.014 | 62.53 | 89998 | True | Passed functional checks |
| nemo-q4-32-512 | q8_0 / 512k | 27.89 | 25.42 | 25.424 | 23.735 | 281.15 | 515996 | True | Passed functional checks |
| nemo-q4-32-256 | q8_0 / 256k | 26.775 | 24.311 | 24.31 | 23.742 | 263.16 | 253887 | True | Passed functional checks |
| nemo-q5-32-512-cpu8 | q8_0 / 512k | 29.596 | 26.926 | 27.13 | 28.11 | 118.27 | 65441 | True | Passed functional checks |
| nemo-q5-32-256-cpu8 | q8_0 / 256k | 28.417 | 26.066 | 26.065 | 27.956 | 122.71 | 65441 | True | Passed functional checks |
| nemo-q4-24-512-cpu14 | q8_0 / 512k | 23.083 | 20.52 | 20.731 | 23.691 | 70.64 | 65441 | True | Passed functional checks |
| nemo-q4-24-256-cpu12 | q8_0 / 256k | 22.929 | 20.578 | 20.577 | 23.615 | 103.28 | 65441 | True | Passed functional checks |
| nemo-q5-24-512-cpu24 | q8_0 / 512k | 21.944 | 19.381 | 19.593 | 28.132 | 55.14 | 65441 | True | Passed functional checks |
| nemo-q5-24-256-cpu22 | q8_0 / 256k | 21.952 | 19.6 | 19.604 | 27.922 | 63.01 | 65441 | True | Passed functional checks |
| iq3-64-default-batch | q8_0 / 64k | 15.968 | 13.617 | 13.619 | 16.534 | 90.17 | 32657 | True | Passed functional checks |
| iq3-48-default-batch | q8_0 / 48k | 15.355 | 13.008 | 13.008 | 16.218 | 89.66 | 32657 | True | Passed functional checks |
| q5-96-default-batch | q8_0 / 96k | 24.234 | 21.871 | 21.886 | 23.563 | 63.5 | 32657 | True | Passed functional checks |
| q5-f16-128-default-batch | f16 / 128k | 29.994 | 27.631 | 27.63 | 23.819 | 64.26 | 32657 | True | Passed functional checks |
| q4-256-default-batch | q8_0 / 256k | 28.5 | 26.137 | 26.136 | 19.467 | 74.17 | 32657 | True | Passed functional checks |
| nemo-q5-32-512-cpu2 | q8_0 / 512k | 31.374 | 29.085 | 29.01 | 29.184 | 199.06 | 32670 | True | Passed functional checks |
| nemo-q5-32-256-gpu | q8_0 / 256k | 31.174 | 28.883 | 28.883 | 28.557 | 272.15 | 32670 | True | Passed functional checks |
| nemo-q4-24-512-cpu10 | q8_0 / 512k | 25.354 | 22.989 | 22.967 | 24.346 | 97.7 | — | — | Passed functional checks |
| nemo-q4-24-256-cpu8 | q8_0 / 256k | 24.682 | 22.352 | 22.445 | 24.466 | 90.68 | 32670 | True | Passed functional checks |
| nemo-q5-24-512-cpu18 | q8_0 / 512k | 24.909 | 22.577 | 22.591 | 28.654 | 64.77 | — | — | Passed functional checks |
| nemo-q5-24-256-cpu16 | q8_0 / 256k | 24.299 | 21.977 | 21.983 | 28.947 | 73.19 | 32670 | True | Passed functional checks |
| flash-256-cpu31-ub256 | q8_0 / 256k | 31.713 | 29.853 | 29.534 | 37.162 | 25.7 | 8080 | True | Passed functional checks |
| flash-256-cpu34-retry | q8_0 / 256k | 28.976 | 27.178 | 27.248 | 39.834 | 20.92 | 8080 | True | Passed functional checks |
| flash-256-cpu32-retry | q8_0 / 256k | 31.269 | 29.25 | 29.589 | 37.755 | 16.52 | 8080 | True | Passed functional checks |
| nemo-q4-24-512-fast-confirm | q8_0 / 512k | 23.212 | 21.278 | 21.276 | 24.756 | 81.18 | 32670 | True | Passed functional checks |
| nemo-q4-24-256-fast-confirm | q8_0 / 256k | 22.576 | 20.641 | 20.641 | 24.466 | 107.37 | 32670 | True | Passed functional checks |
| nemo-q5-24-512-fast-confirm | q8_0 / 512k | 23.454 | 21.499 | 21.519 | 29.208 | 64.51 | 32670 | True | Passed functional checks |
| nemo-q5-24-256-fast-confirm | q8_0 / 256k | 22.841 | 20.899 | 20.911 | 28.808 | 60.89 | 32670 | True | Passed functional checks |
| flash-final-256-cpu32 | q8_0 / 256k | 31.717 | 29.25 | 29.811 | 41.394 | 24.47 | 253840 | True | Passed functional checks |
| flash-final-192-cpu32 | q8_0 / 192k | 30.168 | 28.307 | 28.312 | 38.579 | 17.59 | 32657 | True | Passed functional checks |
| flash-final-128-cpu32 | q8_0 / 128k | 29.549 | 27.363 | 27.7 | 38.523 | 23.65 | 32657 | True | Passed functional checks |
| flash-placement-24-256-cpu39 | q8_0 / 256k | 24.447 | 21.989 | 22.45 | 45.02 | 24.14 | 8080 | True | Passed functional checks |
| flash-placement-16-256-cpu47 | q8_0 / 256k | 13.833 | 11.883 | 11.734 | 49.543 | — | — | — | Sustained critical physical RAM pressure |

## Flash memory and Windows behavior

The first CPU34 and CPU32 Flash calibration attempts were stopped by an experimental commit-only guard while 37–40 GiB physical RAM was still available and Windows was expanding its system-managed pagefile. These are discarded guard artifacts, not native model failures. Both repeated successfully after removing that condition. Windows/pagefile settings were not modified by the audit.

CPU31 placed about 448 MiB more data in shared GPU memory than CPU32/34 and slowed post-prefill generation. CPU32 was selected for the final long test using measured behavior, not a blanket two-GiB reservation.

| Flash context | Actual long input | PID GPU peak GiB | Working-set peak GiB | Simultaneous GPU + working-set peak GiB | Lowest available physical RAM GiB |
|---|---:|---:|---:|---:|---:|
| 256k | 253840 | 29.250 | 41.394 | 70.645 | 6.223 |
| 192k | 32657 | 28.307 | 38.579 | 66.886 | 10.912 |
| 128k | 32657 | 27.363 | 38.523 | 65.887 | 10.046 |

Smaller-GPU RAM estimates use the measured fixed overhead and exact expert-weight bytes moved from GPU to CPU. They are estimates of the resulting working set, not a requirement that all that RAM already be free before startup. Live startup should allow Windows reclamation; an allocation failure or sustained unusable paging is different from low initial free RAM.

### Smaller-GPU placement probes on the same host

The 24 GiB placement (39 CPU expert layers, Q8/256k) passed short generation, tools, vision, about 8k input, cached follow-up and STOP. This directly checks the CPU/RAM placement, not a physical 24 GiB card or a filled 256k input at that placement.

The 16 GiB placement (47 CPU expert layers, Q8/256k) was stopped by the physical-pressure guard during warmup. Available RAM fell to about 13 MiB, with pressure sustained for ten seconds; the process working set had reached 49.54 GiB before initialization completed. Windows automatic pagefile management was enabled. This is an incomplete, critically pressured startup on this 64 GiB host, not proof that every 16 GiB GPU system is incapable of the model. It must not be labeled a qualified 16 GiB/64 GiB-RAM profile.

| Target GPU | Illustrative model GPU allowance | Estimated model RAM for the full tested 256k workload | Evidence |
|---|---|---|---|
| 32 GiB reference | 29.25 GiB measured | 41.39 GiB measured peak working set | Almost full 256k test passed |
| 24 GiB | 22–23 GiB available to the model | About 48.66 GiB | 7.26 GiB additional expert weights; short placement probe passed |
| 16 GiB | 14–15 GiB available to the model | About 55.92–57.35 GiB | 14.53–15.95 GiB additional expert weights; this host hit critical RAM during startup |

The allowance ranges vary other GPU use explicitly; they are not a fixed 1–2 GiB safety padding. System RAM still has to accommodate Windows and active applications. Reclaimable mapped/cold pages and pagefile capacity make actual startup behavior different from an initial available-RAM subtraction. The extrapolation assumes transferred weights remain resident and does not isolate every additional CPU-workspace change.

## Evidence

The local audit directory runtime/profile-remeasure-20260915 contains results/results.json, per-case server logs and telemetry CSV, Windows per-process telemetry, summary.csv, exact case manifests and the measurement runner. Test inputs contain public repository text and synthetic receipts; personal conversations were not used. The owner reviews this table before any production profile or installer change.

A verified local archive preserves 256 audit files: `runtime/archive/profile-remeasurement-2026-09-15.zip`, SHA-256 `a165eabebcffb886ec484969c28193e91e36ca58c40bb1a7590b42fbec03f9b0`. Its CRC and per-file hash manifest were checked. No production source/profile file was modified for this measurement request.
