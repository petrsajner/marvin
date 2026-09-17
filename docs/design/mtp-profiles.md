# MTP speculative profiles for Qwen Q4/Q5

17 September 2026. This note records the measurement and qualification behind the
speculative ("MTP") profile variants shipped in `harness/measured_profiles.py`.
The plain profiles and their 2026-09-15 measurements are unchanged; every MTP
`min_vram_gb` below is the approved plain allocation plus a measured draft-model
increment. No blanket reserves were added.

## Mechanism

llama-server b10935 supports lossless speculative decoding with a draft model.
The draft is `MTP/mtp-Qwen3.8-27B-Q4_0.gguf` (1,369,590,656 bytes, SHA-256
`50d9ce5a6da381bbcfb31061cf73df94a90e6faf8efeddee379a9cb8f1501c6e`) from the
same pinned repository as the Qwen weights (`unsloth/Qwen3.8-27B-GGUF`,
revision `4ca720788d1e01f1bff70c033e0d0028fd02e502`), so the tokenizer matches
both target models. Verification preserves the target distribution: a poor draft
only lowers the acceptance rate, never correctness. The default draft depth
(`--spec-draft-n-max 3`) is used; depth 8 measured slower on natural text
(acceptance 28 %, decode below baseline) and is not shipped.

Exploratory measurements on the same host rejected llama.cpp n-gram speculation
(`ngram-simple`, `ngram-cache`): acceptance about 7 % and no server-side gain.

## Measured cases

Method: each plain/MTP pair was launched back-to-back with identical harness
arguments (`-fa on`, `--fit off`, Q8_0 KV, `-np 1`, mmproj attached, thinking
off for decode) on the RTX 5090 host with an unchanged desktop. `min_vram_gb` is
the approved plain PID measurement from 2026-09-15 plus the pair's total-GPU
delta. Decode columns are the benchmark generation task (numbers 1–300, client)
and the summary task (server-side eval). These are per-case measurements, not
promises for other machines.

| Case | Plain total MiB | MTP total MiB | Delta GiB | min_vram (plain + delta) | Numbers plain → MTP | Summary plain → MTP |
|---|---:|---:|---:|---:|---|---|
| q5 Q8 192k | 29283 | 31890 | 2.546 | 26.580 + 2.546 = 29.126 | 62.3 → 179.4 tok/s (2.9×) | 59.7 → 108.5 tok/s (1.8×) |
| q5 Q8 128k | 26477 | 28656 | 2.128 | 24.189 + 2.128 = 26.317 | 64.5 → 188.0 tok/s (2.9×) | 58.3 → 103.0 tok/s (1.8×) |
| q4 Q8 256k | 28164 | 31077 | 2.845 | 26.137 + 2.845 = 28.982 | 91.6 → 201.7 tok/s (2.2×) | 70.4 → 112.8 tok/s (1.6×) |
| q4 Q8 192k | 25777 | 28369 | 2.531 | 23.502 + 2.531 = 26.033 | 80.6 → 199.3 tok/s (2.5×) | 73.9 → 132.4 tok/s (1.8×) |
| q4 Q8 96k (24 GiB class) | 22033 | 24056 | 1.976 | 19.925 + 1.976 = 21.901 | 80.7 → 202.8 tok/s (2.5×) | 69.7 → 121.4 tok/s (1.7×) |
| q4 Q8 64k (24 GiB class) | 20681 | 22618 | 1.892 | 18.858 + 1.892 = 20.750 | 89.6 → 197.9 tok/s (2.2×) | 69.9 → 117.2 tok/s (1.7×) |

Acceptance on the structured task was 0.89–0.96 (mean accepted length
3.67–3.89); on the natural-text summary 0.50–0.63. Thinking mode measured
comparable (92 % acceptance on the structured task). Raw records:
`runtime/spec-test/results.jsonl`.

## Functional qualification

The full agent smoke suite (`tests/e2e_smoke.py --skip-server-start`) passed
4/4 under MTP on both gated cases (q5 Q8 192k and q4 Q8 256k): chat response,
`write_file` tool call reproducing the exact requested content, actual tool-call
usage, and vision OCR reading the test image through the mmproj projector.
Structured tool calling and vision therefore work unchanged under speculative
decoding. Remaining untested surfaces: long-running sessions with context
compression and the 24 GiB-class placements on physical 24 GB cards (the
placements were measured on the 5090, as with the plain profiles).

## Product behavior

- Menu: every Q8 group of q4/q5 shows plain and MTP variants side by side
  (for example "Q8 · 192k" and "Q8 · 192k · MTP"). F16 groups and Qwen IQ3 have
  no MTP variants; the q5 24 GiB-class profiles do not fit the draft allocation
  and ship without variants.
- Defaults stay plain; MTP is opt-in. The first MTP start downloads and
  SHA-256-verifies the pinned draft into `runtime/models/Qwen3.8-27B/MTP/` and
  shows ordinary download progress. Offline backups include the file
  automatically.
- Recovery ladder for a session that started on an MTP profile: first the same
  context without MTP, then the next lower context with MTP, then that context
  without MTP, continuing interleaved. Plain selections never gain MTP during
  recovery. See [memory profiles](memory-profiles.md).
