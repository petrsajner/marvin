# Strata qualification of Qwen3.8-Flash-Next and proposed menu

6–7 October 2026. Measured for the owner's approval under the
[qualification plan](2026-10-06-strata-qualification-plan.md), with the method
of the [September remeasurement](profile-remeasurement-2026-09-15.md).
Production profiles are not changed until the owner approves the menu below.

Portable records: [JSON](measurements/2026-10-06-strata.json) and
[CSV](measurements/2026-10-06-strata.csv) for the matrix;
[JSON](measurements/2026-10-07-strata-iq2-agent.json) and
[CSV](measurements/2026-10-07-strata-iq2-agent.csv) for the IQ2_XS agent
re-test. Per-case server and engine logs and the half-second telemetry stay on
the measuring PC under `%LOCALAPPDATA%\StrataEval\qualify`.

## In brief

- Strata runs Flash-Next on every combination of 64, 48 and 32 GB of RAM with
  32, 24 and 16 GB cards. llama.cpp qualified only 32 GB card + 64 GB RAM in
  September; its 24 GB placement passed a short probe and its 16 GB placement
  did not start.
- On the owner's PC (64 GB, RTX 5090) IQ3_S on Strata decodes at 110 tok/s and
  answers a 254k-token input in 43 s. llama.cpp decoded at 24–27 tok/s, took
  1,054 s for a 122k-token input and about 44 minutes for 254k.
- 65 launches in the current matrix: 63 passed every check. One failed the
  long input at 128k (48 GB / 16 GB, resident, below), and one IQ2_XS case
  failed the agent task once with thinking off.
- On 48 and 32 GB of RAM the **resident** mode is the best expert mode
  everywhere. The fixed RAM budget leaves about 11 GiB unused; mapping from
  disk is the slowest.
- IQ2_XS is 2–3× faster than IQ3_S on 48 and 32 GB of RAM. Its agent task
  passed 63 of 64 runs with thinking off and 30 of 32 with thinking on; IQ3_S
  passed 33 of 33.

## Proposed menu

Decode is a short 256-token task with thinking off; *first answer* is the time
to the first answer for an input that fills the context (about 254k or 123k
tokens). *Cache* is the fixed `--expert-cache` budget for the smaller card
classes (auto on a 32 GB card). Every profile is int8 (Q8) KV with MTP, the
engine's own vision on the GPU, and the 256k → 128k recovery step that keeps
the expert cache.

### IQ3_S — default entry

| RAM | GPU | Expert mode | 256k: decode · first answer | 128k: decode · first answer | Cache 256k / 128k |
|---:|---:|---|---|---|---|
| 64 | 32 | all experts in RAM | 110.3 tok/s · 43 s | 127.5 tok/s · 20 s | auto |
| 64 | 24 | all experts in RAM | 91.7 tok/s · 43 s | 102.7 tok/s · 20 s | 4110 / 4882 |
| 64 | 16 | all experts in RAM, KV in RAM | 72.9 tok/s · 49 s | 75.2 tok/s · 22 s | 2240 / 2330 |
| 48 | 32 | resident | 72.2 tok/s · 56 s | 82.0 tok/s · 22 s | auto |
| 48 | 24 | resident | 41.0 tok/s · 71 s | 56.1 tok/s · 28 s | 4118 / 4890 |
| 48 | 16 | resident | 25.3 tok/s · 258 s | derived, see below | 1054 / 1054 |
| 32 | 32 | resident | 44.6 tok/s · 174 s | 44.4 tok/s · 82 s | auto |
| 32 | 24 | resident | 24.5 tok/s · 282 s | 24.8 tok/s · 136 s | 4129 / 4901 |
| 32 | 16 | resident | 13.4 tok/s · 617 s | 15.8 tok/s · 184 s | 1065 / 1837 |

### IQ2_XS — optional entry

Downloaded only on request, like the smallest llama.cpp quants: the user trades
weight quality for speed knowingly. The second shard and the projector are the
same files as IQ3_S's, so it adds 39 GB.

| RAM | GPU | Expert mode | 256k: decode · first answer | 128k: decode · first answer | Cache 256k / 128k |
|---:|---:|---|---|---|---|
| 64 | 32 | all experts in RAM | 106.7 tok/s · 45 s | 155.5 tok/s · 21 s | auto |
| 64 | 24 | all experts in RAM | 131.7 tok/s · 44 s | 147.1 tok/s · 21 s | 7921 / 9282 |
| 64 | 16 | all experts in RAM, KV in RAM | 114.9 tok/s · 47 s | 113.3 tok/s · 22 s | 4619 / 4780 |
| 48 | 32 | all experts in RAM | 114.1 tok/s · 44 s | 144.4 tok/s · 20 s | auto |
| 48 | 24 | all experts in RAM | 136.0 tok/s · 44 s | 145.7 tok/s · 21 s | 7921 / 9282 |
| 48 | 16 | all experts in RAM | 87.7 tok/s · 49 s | 107.4 tok/s · 21 s | 2517 / 3878 |
| 32 | 32 | resident | 119.1 tok/s · 48 s | 123.6 tok/s · 20 s | auto |
| 32 | 24 | resident | 71.0 tok/s · 77 s | 72.2 tok/s · 29 s | 7940 / 9300 |
| 32 | 16 | resident | 31.8 tok/s · 236 s | 36.3 tok/s · 89 s | 2535 / 3896 |

### How Marvin would offer it

- One model entry per weights; `flash_next_q3` (llama.cpp) is removed.
- A profile carries its GPU class and its RAM class. The RAM class comes from
  the installed RAM: 64 from about 60 GiB reported, 48 from 44, 32 from 30. A
  machine with more than 64 GB uses the 64 GB profiles.
- The resident mode is a profile option (`--resident-experts`), as are KV in
  RAM (`--kv-resident 32768`) and the cache budget (`expert_cache`).
- The measured server VRAM (`min_vram_gb`) is recorded per profile, as in
  September.

### 48 GB / 16 GB at 128k

With the 128k profile's own calibrated cache (1825) the engine ran out of
memory while reading the 123k-token input (`prefill mmq: gather_native_group:
out of memory`). The resident mode page-locks all RAM it finds free except
Strata's default 4 GiB (`STRATA_RESIDENT_HEADROOM_GIB`), and at that point the
RAM free including mapped files was 0.01 GiB. The owner chose not to remeasure
with a larger headroom: every configuration has lighter steps, so reaching the
ceiling moves Marvin to a lighter variant.

The proposed 128k profile keeps the 256k profile's cache (1054). That is
strictly lighter than the 256k case that passed (same cache, a quarter less
KV), and it is exactly what Marvin's recovery from 256k runs, since recovery
keeps the expert cache. It is derived, not measured.

## Comparison with llama.cpp

| | llama.cpp, September (64 GB, 32 GB card) | Strata IQ3_S, same PC |
|---|---|---|
| 122–123k-token input, first answer | 1,053.7 s | 20.2 s |
| 254k-token input, first answer | about 44 min | 43.1 s |
| Decode, short task | 24.5–27.3 tok/s | 110.3 (256k), 127.5 (128k) tok/s |
| Cached follow-up | 1.3–1.7 s | 0.5–1.0 s |
| Lowest free RAM at 256k | 6.2 GiB | 4.9 GiB |
| 24 GB card | short probe at 256k only | 91.7 tok/s, 43 s for 254k |
| 16 GB card | did not start (RAM) | 72.9 tok/s, 49 s for 254k |

## Findings

**Expert modes.** With 64 GB every expert fits in RAM, and that is the fastest
mode. Below that:

| IQ3_S, 256k | Mapped from disk | RAM budget | Resident |
|---|---|---|---|
| 48 GB, 32 GB card | 31.3 tok/s · 83 s | 76.6 tok/s · 103 s | 72.2 tok/s · 56 s |
| 48 GB, 24 GB card | 20.1 tok/s · 186 s | 33.0 tok/s · 219 s | 41.0 tok/s · 71 s |
| 48 GB, 16 GB card | 11.6 tok/s · 863 s | 17.4 tok/s · 511 s | 25.3 tok/s · 258 s |
| 32 GB, 32 GB card | 29.4 tok/s · 395 s | 24.3 tok/s · 317 s | 44.6 tok/s · 174 s |
| 32 GB, 24 GB card | 15.6 tok/s · 538 s | 11.4 tok/s · 433 s | 24.5 tok/s · 282 s |
| 32 GB, 16 GB card | 10.7 tok/s · 1039 s | 5.5 tok/s · 851 s | 13.4 tok/s · 617 s |

The RAM budget follows Strata setup's formula (RAM − 24 GB − KV in RAM, at
least 8 GiB) and left about 11 GiB of RAM unused in every IQ3_S case. The resident
mode sizes its page-locked share from the RAM it finds free and reads the rest
from the GGUF files in place.

**KV in RAM on 16 GB cards.** With 64 GB, keeping the whole KV cache in RAM
frees VRAM for the expert cache: IQ3_S 256k 72.9 instead of 56.5 tok/s, IQ2_XS
114.9 instead of 86.8. At 128k the two are about equal; the profiles use it for
both contexts.

**The RAM guard counted mapped files as used memory.** Marvin's emergency
guard ends a server after ten seconds under 512 MB of available RAM. Strata's
mapped, budget and resident modes keep GGUF pages in the server's working set,
where Windows drops them when memory runs short but does not count them as
available. The guard ended working servers, so all disk-mode cases were
measured again after the fix (`servermgmt.guard_available` adds the server
tree's shared working set back for a Strata server; private and page-locked
memory still count). The record shows the lowest free RAM with and without the
mapped pages; the first runs are kept as `superseded` (`guard-…`).

**IQ2_XS as an agent.** The application check (write a value with
`write_file`, check it with `read_file`, twice) ran 64 times with thinking off
and 32 times with thinking at `xhigh` across every IQ2_XS placement that
loaded (the matrix plus the re-test):

| Weights | Thinking off | Thinking xhigh |
|---|---|---|
| IQ3_S | 33 of 33 | — |
| IQ2_XS | 63 of 64 | 30 of 32 |

The failure with thinking off looped 148 times on `read_file` despite the loop
warning. Both failures with thinking on wrote the file correctly and then
reported without the requested `read_file` check ("Done. Now, I'll report the
value."). The model thinks briefly on this task (tens to hundreds of
characters), so thinking took no longer than without it. An earlier run in
which an IQ2_XS agent wandered for 142 turns ended with the RAM guard and is
superseded; the same placement passed every later run.

**Decode figures are short-task figures.** They come from one 256-token answer
with MTP speculation, whose acceptance varies; IQ2_XS on a 24 GB card
measuring faster than on a 32 GB card (131.7 against 106.7 tok/s) is that
variation, not the card. Prefill and first-answer times come from the long
input and are steadier.

**STOP** took under 0.02 s in every case, and every follow-up after it
answered.

## Measurement conditions

- One RTX 5090 (31.84 GiB), Core Ultra 7 265K, 64 GB RAM, driver 591.86,
  Windows 11. Data on the NVMe system drive (C:), where the installed Marvin
  runs.
- Strata v0.1.39 (commit `6f32ec0`, release engine 0.1.39, CUDA 13.0), launched
  through Marvin's own `servermgmt` with the Phase 2 integration. Weights
  checked against the Hub's SHA-256 before the matrix.
- **Smaller cards** are a calibrated fixed `--expert-cache N` (a byte budget):
  a probe gives the fixed part and the bytes per unit, and N is set so that the
  server tree holds at most 21.9 GiB (24 GB class) or 14.3 GiB (16 GB class) by
  Windows' per-process counters, then checked. A VRAM ballast and a calibrated
  `--vram-reserve-mib` were tried first and rejected (see the plan). Speed on a
  real smaller card can differ (PCIe, compute).
- **RAM classes** are a RAM ballast that page-locks the installed RAM less the
  class, so the engine, Marvin's guard and Windows see what a 48 or 32 GB
  machine has. Background programs on the measuring PC (the desktop, this
  session's tools) stayed running, as they would on a user's PC.
- Checks per case: chat ("95"), tool round trip, OCR of two receipts, STOP
  within 3 s with a working follow-up, Marvin's application agent task, and a
  long input with three markers at 10/50/90 % plus a cached follow-up.
- For the disk modes and the resident rows added on 7 October, 128k ran only
  when 256k failed; the 128k steps of the resident IQ3_S rows on 48/16 and
  32 GB were measured afterwards.

## Detailed cases

*Min RAM free* is the lowest available RAM during the case; in brackets the
same with the server's mapped file pages counted, for the modes that read the
GGUF in place.

| Weights | RAM | GPU | Expert mode | Context | Cache budget | Load s | Decode tok/s | Prefill tok/s | Long input | First answer s | Cached follow-up s | STOP s | Server GPU GiB | Min RAM free GiB (incl. mapped) | Result |
|---|---:|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| IQ3_S | 64 | 32 | all experts in RAM | 256k | auto | 30.7 | 110.29 | 6034 | 253842 | 43.063 | 0.953 | 0.0 | 30.535 | 4.9 | passed |
| IQ3_S | 64 | 32 | all experts in RAM | 128k | auto | 28.7 | 127.5 | 6248 | 122556 | 20.172 | 0.515 | 0.0 | 30.56 | 4.9 | passed |
| IQ3_S | 64 | 32 | resident | 256k | auto | 75.7 | 91.17 | 5513 | 253841 | 47.14 | 1.063 | 0.0 | 30.365 | 0.3 (17.3) | passed |
| IQ3_S | 64 | 24 | all experts in RAM | 256k | 4110 | 24.1 | 91.69 | 6043 | 253837 | 43.156 | 1.063 | 0.0 | 21.943 | 4.8 | passed |
| IQ3_S | 64 | 24 | all experts in RAM | 128k | 4882 | 23.6 | 102.66 | 6328 | 122761 | 20.0 | 0.531 | 0.0 | 21.945 | 4.7 | passed |
| IQ3_S | 64 | 16 | all experts in RAM | 256k | 1046 | 24.0 | 56.47 | 3662 | 253837 | 70.453 | 1.125 | 0.016 | 14.342 | 4.8 | passed |
| IQ3_S | 64 | 16 | all experts in RAM | 128k | 1818 | 23.6 | 74.52 | 6086 | 122761 | 20.891 | 0.64 | 0.0 | 14.346 | 6.1 | passed |
| IQ3_S | 64 | 16 | all experts in RAM, KV in RAM | 256k | 2240 | 27.1 | 72.86 | 5286 | 253837 | 49.14 | 1.079 | 0.0 | 14.344 | 2.4 | passed |
| IQ3_S | 64 | 16 | all experts in RAM, KV in RAM | 128k | 2330 | 24.1 | 75.2 | 5786 | 122761 | 21.906 | 0.719 | 0.0 | 14.345 | 4.2 | passed |
| IQ3_S | 48 | 32 | RAM budget 24 GiB | 256k | auto | 36.2 | 76.62 | 2483 | 253841 | 103.437 | 0.985 | 0.0 | 30.484 | 11.3 (11.4) | passed |
| IQ3_S | 48 | 32 | mapped from disk | 256k | auto | 54.9 | 31.27 | 3110 | 253841 | 83.422 | 1.391 | 0.0 | 30.323 | 0.3 (36.3) | passed |
| IQ3_S | 48 | 32 | resident | 256k | auto | 91.9 | 72.22 | 4614 | 253841 | 56.156 | 1.062 | 0.0 | 30.468 | 0.0 (4.8) | passed |
| IQ3_S | 48 | 32 | resident | 128k | auto | 91.4 | 81.99 | 5729 | 122759 | 22.094 | 0.578 | 0.0 | 30.346 | 0.0 (5.9) | passed |
| IQ3_S | 48 | 24 | RAM budget 24 GiB | 256k | 4127 | 24.1 | 32.97 | 1167 | 253841 | 219.204 | 1.375 | 0.0 | 21.945 | 11.5 (11.6) | passed |
| IQ3_S | 48 | 24 | mapped from disk | 256k | 4145 | 14.4 | 20.1 | 1387 | 253841 | 185.656 | 2.219 | 0.0 | 21.941 | 0.0 (36.9) | passed |
| IQ3_S | 48 | 24 | resident | 256k | 4118 | 68.7 | 41.0 | 3652 | 253841 | 70.875 | 1.64 | 0.0 | 21.941 | 0.0 (2.5) | passed |
| IQ3_S | 48 | 24 | resident | 128k | 4890 | 76.2 | 56.08 | 4573 | 122759 | 27.766 | 0.688 | 0.0 | 21.942 | 0.0 (2.3) | passed |
| IQ3_S | 48 | 16 | RAM budget 24 GiB | 256k | 1063 | 20.5 | 17.4 | 500 | 253841 | 510.812 | 2.343 | 0.0 | 14.348 | 11.2 (11.3) | passed |
| IQ3_S | 48 | 16 | mapped from disk | 256k | 1082 | 10.4 | 11.58 | 296 | 253841 | 862.5 | 6.062 | 0.0 | 14.347 | 0.0 (37.4) | passed |
| IQ3_S | 48 | 16 | resident | 256k | 1054 | 50.9 | 25.3 | 994 | 253964 | 258.078 | 2.031 | 0.016 | 14.349 | 0.0 (2.7) | passed |
| IQ3_S | 48 | 16 | resident | 128k | 1825 | 55.0 | 33.44 | — | — | — | — | 0.0 | 14.346 | 0.0 (0.0) | failed: RuntimeError: The model could not allocate memory for this context. |
| IQ3_S | 32 | 32 | RAM budget 8 GiB | 256k | auto | 28.7 | 24.29 | 806 | 253964 | 317.187 | 1.563 | 0.0 | 30.436 | 11.6 (11.8) | passed |
| IQ3_S | 32 | 32 | mapped from disk | 256k | auto | 56.4 | 29.4 | 646 | 253841 | 394.937 | 1.828 | 0.0 | 30.351 | 0.0 (19.8) | passed |
| IQ3_S | 32 | 32 | resident | 256k | auto | 75.2 | 44.59 | 1473 | 253964 | 174.422 | 1.641 | 0.015 | 30.469 | 0.0 (4.3) | passed |
| IQ3_S | 32 | 32 | resident | 128k | auto | 79.3 | 44.35 | 1517 | 122756 | 82.157 | 1.797 | 0.0 | 30.401 | 0.0 (4.0) | passed |
| IQ3_S | 32 | 24 | RAM budget 8 GiB | 256k | 4139 | 18.4 | 11.38 | 593 | 253964 | 432.797 | 2.828 | 0.016 | 21.945 | 11.4 (11.5) | passed |
| IQ3_S | 32 | 24 | mapped from disk | 256k | 4145 | 14.4 | 15.62 | 475 | 253964 | 538.016 | 2.234 | 0.0 | 21.941 | 0.0 (21.6) | passed |
| IQ3_S | 32 | 24 | resident | 256k | 4129 | 55.1 | 24.47 | 911 | 253964 | 281.719 | 2.172 | 0.015 | 21.94 | 0.0 (2.9) | passed |
| IQ3_S | 32 | 24 | resident | 128k | 4901 | 63.0 | 24.76 | 923 | 122756 | 135.75 | 1.594 | 0.0 | 21.941 | 0.0 (2.9) | passed |
| IQ3_S | 32 | 16 | RAM budget 8 GiB | 256k | 1075 | 14.4 | 5.51 | 301 | 253964 | 850.875 | 5.063 | 0.0 | 14.345 | 11.2 (11.3) | passed |
| IQ3_S | 32 | 16 | mapped from disk | 256k | 1082 | 10.4 | 10.65 | 246 | 253964 | 1039.109 | 3.5 | 0.0 | 14.345 | 0.0 (21.6) | passed |
| IQ3_S | 32 | 16 | resident | 256k | 1065 | 38.8 | 13.41 | 415 | 253964 | 616.593 | 3.25 | 0.0 | 14.345 | 0.0 (3.1) | passed |
| IQ3_S | 32 | 16 | resident | 128k | 1837 | 42.9 | 15.78 | 676 | 122756 | 184.39 | 2.094 | 0.0 | 14.344 | 0.0 (3.6) | passed |
| IQ2_XS | 64 | 32 | all experts in RAM | 256k | auto | 22.6 | 106.65 | 5727 | 253842 | 45.25 | 0.89 | 0.0 | 30.081 | 18.5 | passed |
| IQ2_XS | 64 | 32 | all experts in RAM | 128k | auto | 19.0 | 155.49 | 5967 | 122556 | 21.015 | 0.485 | 0.0 | 30.518 | 18.7 | passed |
| IQ2_XS | 64 | 24 | all experts in RAM | 256k | 7921 | 18.4 | 131.65 | 5902 | 253837 | 43.937 | 0.985 | 0.0 | 21.95 | 20.5 | passed |
| IQ2_XS | 64 | 24 | all experts in RAM | 128k | 9282 | 18.5 | 147.06 | 6143 | 122761 | 20.531 | 0.484 | 0.0 | 21.95 | 20.6 | passed |
| IQ2_XS | 64 | 16 | all experts in RAM | 256k | 2517 | 18.5 | 86.79 | 5174 | 253837 | 50.094 | 1.0 | 0.0 | 14.348 | 18.3 | passed |
| IQ2_XS | 64 | 16 | all experts in RAM | 128k | 3878 | 18.4 | 105.28 | 6008 | 122761 | 21.063 | 0.547 | 0.0 | 14.348 | 18.6 | passed |
| IQ2_XS | 64 | 16 | all experts in RAM, KV in RAM | 256k | 4619 | 18.4 | 114.92 | 5517 | 253837 | 47.188 | 1.125 | 0.0 | 14.349 | 15.0 | passed |
| IQ2_XS | 64 | 16 | all experts in RAM, KV in RAM | 128k | 4780 | 18.5 | 113.33 | 5819 | 122761 | 21.688 | 0.547 | 0.0 | 14.35 | 18.4 | passed |
| IQ2_XS | 48 | 32 | RAM budget 24 GiB | 256k | auto | 38.8 | 132.74 | 5264 | 253964 | 49.141 | 0.922 | 0.0 | 30.358 | 10.6 (21.4) | passed |
| IQ2_XS | 48 | 32 | mapped from disk | 256k | auto | 50.9 | 71.89 | 4073 | 253964 | 63.406 | 1.032 | 0.0 | 30.345 | 2.7 (35.9) | passed |
| IQ2_XS | 48 | 32 | all experts in RAM | 256k | auto | 20.5 | 114.09 | 5934 | 253837 | 43.641 | 0.859 | 0.0 | 0 | 3.0 | passed |
| IQ2_XS | 48 | 32 | all experts in RAM | 128k | auto | 22.6 | 144.39 | 6197 | 122761 | 20.297 | 0.468 | 0.0 | 30.411 | 3.2 | passed |
| IQ2_XS | 48 | 24 | RAM budget 24 GiB | 256k | 7933 | 60.5 | 89.19 | 4841 | 253964 | 53.531 | 0.953 | 0.0 | 21.942 | 0.4 (14.5) | passed |
| IQ2_XS | 48 | 24 | mapped from disk | 256k | 7967 | 13.2 | 41.63 | 3316 | 253964 | 78.125 | 1.266 | 0.0 | 21.95 | 2.3 (35.6) | passed |
| IQ2_XS | 48 | 24 | all experts in RAM | 256k | 7921 | 18.5 | 136.0 | 5889 | 253837 | 44.047 | 0.89 | 0.016 | 21.95 | 3.8 | passed |
| IQ2_XS | 48 | 24 | all experts in RAM | 128k | 9282 | 18.5 | 145.71 | 6143 | 122761 | 20.672 | 0.89 | 0.0 | 21.95 | 3.5 | passed |
| IQ2_XS | 48 | 16 | RAM budget 24 GiB | 256k | 2529 | 39.8 | 56.67 | 3514 | 253964 | 73.437 | 1.094 | 0.0 | 14.349 | 0.2 (13.6) | passed |
| IQ2_XS | 48 | 16 | mapped from disk | 256k | 2562 | 10.3 | 22.73 | 2442 | 253964 | 105.875 | 1.547 | 0.0 | 14.346 | 2.2 (35.5) | passed |
| IQ2_XS | 48 | 16 | all experts in RAM | 256k | 2517 | 18.4 | 87.72 | 5264 | 253837 | 49.406 | 1.281 | 0.0 | 14.348 | 3.9 | failed: application |
| IQ2_XS | 48 | 16 | all experts in RAM | 128k | 3878 | 18.5 | 107.37 | 6080 | 122761 | 20.843 | 0.547 | 0.0 | 14.348 | 3.8 | passed |
| IQ2_XS | 32 | 32 | RAM budget 8 GiB | 256k | auto | 30.7 | 88.2 | 1651 | 253964 | 154.89 | 0.969 | 0.0 | 30.333 | 12.4 (12.6) | passed |
| IQ2_XS | 32 | 32 | mapped from disk | 256k | auto | 52.9 | 60.67 | 4174 | 253964 | 62.016 | 0.968 | 0.0 | 30.345 | 0.4 (21.4) | passed |
| IQ2_XS | 32 | 32 | resident | 256k | auto | 79.2 | 119.1 | 5443 | 253841 | 47.656 | 0.985 | 0.0 | 30.332 | 0.1 (5.1) | passed |
| IQ2_XS | 32 | 32 | resident | 128k | auto | 83.3 | 123.61 | 6163 | 122759 | 20.437 | 0.485 | 0.0 | 30.342 | 0.4 (6.1) | passed |
| IQ2_XS | 32 | 24 | RAM budget 8 GiB | 256k | 7955 | 18.9 | 30.85 | 912 | 253964 | 280.781 | 1.406 | 0.0 | 21.95 | 12.4 (12.6) | passed |
| IQ2_XS | 32 | 24 | mapped from disk | 256k | 7967 | 14.5 | 31.2 | 1274 | 253964 | 201.39 | 1.609 | 0.0 | 21.95 | 0.0 (21.7) | passed |
| IQ2_XS | 32 | 24 | resident | 256k | 7940 | 60.0 | 70.97 | 3363 | 253841 | 77.109 | 1.937 | 0.0 | 21.952 | 0.0 (2.9) | passed |
| IQ2_XS | 32 | 24 | resident | 128k | 9300 | 63.1 | 72.22 | 4421 | 122759 | 29.141 | 0.812 | 0.0 | 21.946 | 0.0 (2.5) | passed |
| IQ2_XS | 32 | 16 | RAM budget 8 GiB | 256k | 2551 | 15.9 | 10.56 | 524 | 253964 | 488.265 | 2.89 | 0.0 | 14.347 | 12.1 (12.3) | passed |
| IQ2_XS | 32 | 16 | mapped from disk | 256k | 2562 | 10.4 | 20.05 | 517 | 253964 | 494.593 | 2.203 | 0.015 | 14.346 | 0.0 (22.4) | passed |
| IQ2_XS | 32 | 16 | resident | 256k | 2535 | 39.8 | 31.75 | 1085 | 253841 | 236.437 | 1.797 | 0.0 | 14.349 | 0.0 (2.7) | passed |
| IQ2_XS | 32 | 16 | resident | 128k | 3896 | 46.9 | 36.27 | 1402 | 122759 | 88.984 | 1.297 | 0.0 | 14.349 | 0.0 (2.9) | passed |

## IQ2_XS agent re-test

The same application task, thinking off and at `xhigh`, on every IQ2_XS
placement that loaded, with the smaller cards' calibrated caches reused.

| Case | Agent task, thinking off (s per task) | Agent task, thinking xhigh (s per task) |
|---|---|---|
| iq2_xs-ram64-gpu32-normal-256k | passed 4.938, 2.281 | passed 2.891, 2.109 |
| iq2_xs-ram64-gpu32-normal-128k | passed 3.89, 2.078 | passed 2.703, 2.078 |
| iq2_xs-ram64-gpu24-normal-256k | passed 4.109, 2.5 | passed 3.546, 2.704 |
| iq2_xs-ram64-gpu24-normal-128k | passed 3.891, 2.25 | passed 3.5, 2.5 |
| iq2_xs-ram64-gpu16-normal-256k | passed 4.781, 2.891 | passed 4.531, 3.547 |
| iq2_xs-ram64-gpu16-normal-128k | passed 4.719, 2.891 | passed 4.735, 4.312 |
| iq2_xs-ram64-gpu16-normal-kvres-256k | passed 4.516, 2.703 | passed 3.922, 3.485 |
| iq2_xs-ram64-gpu16-normal-kvres-128k | passed 4.531, 2.687 | passed 4.109, 4.297 |
| iq2_xs-ram48-gpu32-normal-256k | passed 3.906, 2.281 | passed 3.093, 2.735 |
| iq2_xs-ram48-gpu32-normal-128k | passed 4.109, 2.313 | passed 3.719, 2.469 |
| iq2_xs-ram48-gpu24-normal-256k | passed 4.125, 2.297 | passed 3.329, 2.484 |
| iq2_xs-ram48-gpu24-normal-128k | passed 3.937, 2.297 | passed 3.296, 3.079 |
| iq2_xs-ram48-gpu16-normal-256k | passed 4.719, 3.078 | passed 4.343, 3.719 |
| iq2_xs-ram48-gpu16-normal-128k | passed 5.375, 2.922 | passed 3.703, 5.141 |
| iq2_xs-ram32-gpu32-resident-256k | passed 4.531, 2.453 | passed 3.078, 2.891 |
| iq2_xs-ram32-gpu32-resident-128k | passed 4.157, 2.296 | passed 3.094, 2.281 |
| iq2_xs-ram32-gpu24-resident-256k | passed 9.234, 4.688 | passed 5.312, 4.094 |
| iq2_xs-ram32-gpu24-resident-128k | passed 6.781, 3.094 | failed: AssertionError: ['write_file'] |
| iq2_xs-ram32-gpu16-resident-256k | passed 20.687, 6.813 | passed 9.641, 13.14 |
| iq2_xs-ram32-gpu16-resident-128k | passed 18.453, 5.36 | passed 8.515, 7.532 |
| iq2_xs-ram48-gpu32-mmap-256k | passed 8.0, 3.5 | passed 4.313, 3.484 |
| iq2_xs-ram48-gpu24-mmap-256k | passed 14.953, 5.39 | passed 6.437, 5.344 |
| iq2_xs-ram48-gpu16-mmap-256k | passed 12.985, 8.39 | passed 11.984, 12.125 |
| iq2_xs-ram48-gpu32-budget-256k | passed 5.172, 2.5 | passed 3.125, 2.5 |
| iq2_xs-ram48-gpu24-budget-256k | passed 5.547, 3.078 | passed 4.328, 3.344 |
| iq2_xs-ram48-gpu16-budget-256k | passed 9.453, 4.094 | passed 7.359, 5.953 |
| iq2_xs-ram32-gpu32-mmap-256k | passed 11.141, 3.906 | passed 4.735, 3.703 |
| iq2_xs-ram32-gpu24-mmap-256k | passed 21.468, 6.172 | passed 14.156, 9.515 |
| iq2_xs-ram32-gpu16-mmap-256k | passed 32.016, 10.672 | passed 18.219, 12.875 |
| iq2_xs-ram32-gpu32-budget-256k | passed 13.25, 5.719 | passed 6.734, 4.485 |
| iq2_xs-ram32-gpu24-budget-256k | passed 24.843, 12.235 | failed: AssertionError: ['write_file'] |
| iq2_xs-ram32-gpu16-budget-256k | passed 45.828, 26.078 | passed 32.547, 25.297 |

## Superseded and discarded runs

Kept in the JSON record with their reasons:

- `superseded`: the first IQ3_S 64 GB runs (uncalibrated, and the 32 GB card
  right after Phase 0); the smaller cards measured with the engine's VRAM
  reserve (`reserve-…`) and with a VRAM ballast (`ballast-…`); and every
  disk-mode case before the RAM guard fix (`guard-…`).
- `discarded`: the two first VRAM-ballast runs that hit the commit limit, and
  one case whose RAM ballast could not lock its memory right after the
  previous server ended (error 1450), measured again.
