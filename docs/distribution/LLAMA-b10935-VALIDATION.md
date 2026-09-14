# llama.cpp b10935 qualification against the existing runtime

13 September 2026. Marvin 1.7.0 baseline: `6b687458ca09879ceac81baa72bd53f9b52fad65`.

No functional regression was demonstrated in the tested scenarios. All 22 practical existing model/context combinations passed on both runtimes: 44 combinations on a physical RTX 5090. Initially the new runtime remained staged; Flash-Next was not yet downloaded or integrated. Later activation is recorded below.

The audit also reproduced an existing ApplicationService completion/steering race, independent of llama.cpp. It was fixed in the subsequent integration stage.

## Exact environment

| Component | Baseline | Candidate |
|---|---|---|
| llama.cpp | b10549, `b2e5e9b28`, 0.1.2-dev | b10935, `8e330954a`, 0.4.0-dev |
| Directory | `runtime/llama` | `runtime/candidates/llama-b10935-cuda13.3/bin` |
| GPU | RTX 5090, 32,607 MiB, Windows WDDM | Same device |
| Driver | NVIDIA 591.86 | Unchanged |
| CPU | Core Ultra 7 265K, 8 P + 12 E, no SMT | Unchanged |
| RAM | 64 GB class | Unchanged |
| Python | Existing `.venv`, 95 locked packages | Same environment; no package updates |

Only one model ran at a time, on isolated port 8087. Test data was separate from user projects/chats. Model and KV definitions, NP1, Flash Attention and projectors were retained. Direct comparisons used deterministic sampling; real ApplicationService tasks used model sampling and existing tools.

Official Windows x64 CUDA 13.3 archives were checked against release digests before extraction:

- `llama-b10935-bin-win-cuda-13.3-x64.zip`: `9ece1d33916caefe2ed1f74092dabe05cf955b112f9afdabc2de5c5e2b7285ad`
- `cudart-llama-bin-win-cuda-13.3-x64.zip`: `1462a050eb4c684921ba51dcc4cc488a036674c3e73e9945ee705b854808d03e`

`cublas64_13.dll`, `cublasLt64_13.dll` and `cudart64_13.dll` had identical hashes in both directories. The substantive change was llama.cpp/GGML, not those CUDA libraries, Python, driver or PATH.

Server executable hashes:

- Baseline: `c8b1e5a66e1bb45854bed3daaab116c37e74526e30143d737c67557bab822359`
- Candidate: `3e17f28f693dfcbca90d4aa7f04cf9eb389300aa228b28b69d00271d3c4bd451`

## Coverage

| Model | KV profiles | Baseline | Candidate |
|---|---:|---|---|
| Qwen3.8-27B Q5_K_M | 2 | Passed | Passed |
| Qwen3.8-27B Q4_K_M | 4 | Passed | Passed |
| Qwen3.8-27B IQ3_S | 6 | Passed | Passed |
| Ornith 1.5 35B-A3B Abliterated Q5 | 1 | Passed | Passed |
| Nemotron 3.5 Lightning Q4_K_XL | 5 | Passed | Passed |
| Nemotron 3.5 Lightning Q5_K_XL | 4 | Passed | Passed |

Each profile passed loading, reported capacity without silent reduction, a reply, a structured tool call with checked arguments and a follow-up based on the actual tool result. Vision profiles read two different images containing item codes and amounts; the second image could not reuse the first image's values.

Each model's primary profile also passed reasoning transport through LLMClient, STOP during generation and prefill followed by another working request, two real ApplicationService write/read tasks, three-marker recall across a long input, and a cached follow-up.

After the completion race was found, initial ApplicationService comparisons used explicit `delivery="queue"`. This qualified queueing and agent behavior, not the default steering race. The original failed attempt remains in `previous_attempts`.

Additional checks: 366 core checks, 21 service tests, `pip check`, exact agreement of all 95 installed packages with `requirements-windows-py312.lock`, and Qwen Q5 answers from baseline history including prior tool-call messages. All passed.

The one-million-token Nemotron profile was excluded as a product non-goal. Tested allocations reached 512k; not every allocation was filled. Testing compact profiles on a 5090 does not qualify physical 16/24 GB cards.

## Long-context measurements

Times include prefill and a short LLMClient response. These are individual paired measurements, not a statistical benchmark. OS/file caches were not reset; this is not a cold-SSD test. Each pair used identical local weights and requests.

| Model/profile | Input tokens | Baseline | Candidate |
|---|---:|---:|---:|
| Qwen Q5 / Q8 192k, repeat | 122,397 | 72.61 s | 73.09 s |
| Qwen Q4 / F16 128k | 122,397 | 66.03 s | 65.06 s |
| Qwen IQ3 / Q8 48k | 43,681 | 15.53 s | 15.38 s |
| Ornith Q5 / Q8 128k | 122,397 | 24.53 s | 24.70 s |
| Nemotron Q4 / Q8 512k | 122,402 | 14.84 s | 14.44 s |
| Nemotron Q5 / Q8 128k | 122,402 | 14.88 s | 14.39 s |

The first Q5 pair was 71.52 versus 89.55 seconds. Fresh-process repetition in reversed runtime order reduced the difference to about half a second. A persistent 25% regression was not reproduced; the initial outlier's exact cause was not isolated.

| Qwen Q5 / Q8, allocation 196,608 | Baseline | Candidate |
|---|---:|---:|
| 191,147 input tokens and correct answer | 153.61 s | 151.84 s |
| Follow-up | 0.64 s | 0.69 s |

Follow-ups actually used cached tokens: a 122k Qwen request reused 122,429 tokens and evaluated only 22 new input tokens. This qualifies continuity beyond allocation alone.

The repeated Q5 run peaked at approximately 34,586 MiB baseline versus 35,047 MiB candidate server private memory. Windows private commit, working set and GPU allocation cannot be added as independent physical allocations. Device-wide GPU values include the desktop and other processes. No protective memory stop occurred in these runs. In particular, a 512k Nemotron allocation is not a filled 512k prefill test.

## Completion race and subsequent fix

The first job could already be `complete` in SQLite while `ApplicationService.active` still referenced it during worker shutdown. A new default `delivery="steer"` message became `steering`; the worker then cleared `active` without consuming it. The result was a stranded message with no active worker.

A deterministic test without llama.cpp held that completion boundary and reproduced `first_status=complete`, `second_final_status=steering`, `active=null`. The defect belonged to `ApplicationService.submit` / `_work` coordination.

The initial audit did not edit production application code. The September 13 implementation then moved late messages into the queue under the same lock before releasing the active task, retaining STOP's queue pause. Two regression tests cover two rapid messages and STOP at this boundary. The next suite passed 23 service tests, 19 model/runtime preparation tests and 366 core checks.

Real Qwen Q5 on b10935 subsequently passed chat, tool roundtrip, two images, two tasks using default steering, and STOP during prefill. The five checks took 48.05 seconds including model loading; evidence: `runtime/validation/flash-next/regression/results.json`.

## Evidence and reproduction

- `tests/check_runtime_upgrade.py`: repeatable isolated test; selects runtime, models, profiles and checks, with one model at a time.
- `runtime/validation/llama-b10935/results.json`: all 44 combinations, answers, usage, latency, memory and earlier attempts.
- `q5-repeat/results.json`: reversed-order repeat and nearly full 192k Q5 window.
- `completion-handoff.json`: model-independent completion-race reproduction.
- `cases/`: test files, images, SQLite data and server logs.
- `core-tests.log`: core-check results.

These historical `runtime/validation` paths are now preserved inside the local verification archive described in [release 1.8.0](RELEASE-1.8.0.md).

```text
.venv/Scripts/python.exe -B tests/check_runtime_upgrade.py --candidate runtime/candidates/llama-b10935-cuda13.3/bin --output runtime/validation/new-audit
```

Useful selections: `--profiles all --only chat,tool_roundtrip,vision`, `--only stop_prefill,long_context`, `--models q5 --only long_context,max_context`, `--diagnose-handoff`. `--resume` skips completed recorded checks; use a new output directory for a new comparison. `saved_baseline_history` requires a baseline history already saved by that audit.

After qualification on September 13, pinned b10935 was activated in `runtime/llama` with verified package hashes/GPU libraries. b10549 was retained in `runtime/llama-previous-1789275410529156700`. The active EXE matched the candidate hash. `runtime/validation/flash-next/runtime-activation.json` records activation. Python package versions were unchanged. Flash-Next and distribution completion are covered in the release report; physical smaller GPUs remained unqualified.
