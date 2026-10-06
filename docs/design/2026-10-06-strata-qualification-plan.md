# Strata qualification plan (approved 6 October 2026)

Goal: qualify Qwen3.8-Flash-Next on Strata as completely as the other models,
for the owner's PC and for weaker machines. If it beats the llama.cpp entry
(`flash_next_q3`), that entry is removed.

## Method

The same as the 15 September remeasurement
([profile-remeasurement-2026-09-15.md](profile-remeasurement-2026-09-15.md)):

- every case is one launch with explicit settings on the RTX 5090 in this PC;
- each phase records peak GPU memory (total and the server's own), the server's
  working set and commit, the lowest available RAM, load time, prefill and
  decode speed;
- the same five checks run in every case (definitions from
  `tests/check_runtime_upgrade.py`):
  - chat ("95");
  - tool round trip (`{"sku":"BOLT-17","warehouse":"PRG"}`, then "73");
  - OCR of two receipts;
  - STOP within 3 s, then a working follow-up;
  - long input filling the context with three markers at 10/50/90 %, plus a
    cached follow-up;
- the record goes to `docs/design/measurements/` as JSON, CSV and a summary page;
  the owner approves the table before profiles change.

The llama.cpp Flash-Next numbers are not measured again (AGENTS.md); Strata is
compared with the September record. At 128k llama took 1,054 s to the first
answer and decoded at 27 tok/s; at 256k it took about 44 minutes and decoded at
24.5 tok/s.

### Two changes the engine forces (owner's choices)

- **Smaller GPUs are simulated with the engine's VRAM reserve.** Strata fills all
  free VRAM with its expert cache, so measuring on the 32 GB card and comparing
  with a budget afterwards would always "fit". Each case reads the free VRAM as
  CUDA reports it and sets `--vram-reserve-mib` so that the model uses what the
  real card leaves beside a desktop: about 21.9 GiB for the 24 GB class and
  14.3 GiB for the 16 GB class (the limits the earlier profiles used). Dense
  weights, KV, MTP and vision are the same on any card; only the expert cache
  shrinks.
  - The first plan used a VRAM ballast. Under Windows' display driver model every
    GPU allocation also costs system commit, so the ballast took 8–10 GB of commit
    a smaller card does not, and the 24 GB cases hit the commit limit (104 of
    106 GB). Those two runs are discarded (owner, 6 October).
- **RAM classes are simulated with a RAM ballast.** RAM decides which weights
  fit on Strata (the experts live in RAM; the GPU only caches the hot ones). A
  helper process locks RAM so that the server, its resident mode and Marvin's
  guard see what a 48 GB or 32 GB machine has. 64 GB is the real machine.

## Matrix

Weights: **IQ3_S** (best quality, experts 50.3 GB) and **IQ2_XS** (experts
35.5 GB). The 28.8 GB second shard is shared.

| Weights | RAM | GPU classes | Expert mode | Contexts |
|---|---|---|---|---|
| IQ3_S | 64 | 32, 24, 16 | normal (all in RAM) | 256k, 128k |
| IQ3_S | 64 | 32 | resident | 256k |
| IQ3_S | 48 | 32, 24 | resident | 256k, 128k |
| IQ2_XS | 64 | 32, 24, 16 | normal | 256k, 128k |
| IQ2_XS | 48 | 32, 24, 16 | normal | 256k, 128k |
| IQ2_XS | 32 | 32, 24, 16 | resident | 256k, 128k |

Added after the first IQ3_S results (owner, 6 October):

| Weights | RAM | GPU classes | Expert mode | Contexts |
|---|---|---|---|---|
| IQ3_S, IQ2_XS | 64 | 16 | normal, KV in RAM (`--kv-resident 32768`) | 256k, 128k |
| IQ3_S, IQ2_XS | 48, 32 | 32, 24, 16 | mapped from disk (`--mmap-experts`) | 256k (128k if 256k fails) |
| IQ3_S, IQ2_XS | 48, 32 | 32, 24, 16 | RAM budget (`--resident-budget-gib`) | 256k (128k if 256k fails) |

- The RAM budget follows Strata's setup: the machine's RAM less 24 GB, less a
  KV cache kept in RAM, at least 8 GiB.
- Smaller cards are calibrated: a short launch reads what the server tree
  really holds in dedicated VRAM (the September rule) and raises the reserve by
  the excess, up to four times. When a larger reserve no longer lowers the use,
  the engine is at its smallest expert cache and the case is recorded as not
  fitting the class.
- The first IQ3_S 64 GB runs (uncalibrated, and the 32 GB ones right after
  Phase 0) are kept as `superseded` in the results and run again.

81 entries in all (`python scripts/strata_qualify.py list`); the 128k disk
cases only run when their 256k case fails. A case that cannot load
ends at once and is recorded as rejected, like the September Flash 16 GB / 256k
case. Before the matrix, Phase 0 (`scripts/strata_eval.py run`) gives the first
IQ3_S numbers.

The resident mode reads the experts it does not keep straight from the GGUF
files (engine 0.1.31 and later), so it needs no extra `experts.bin` copy
(+35–50 GB); it is measured that way, as Marvin would ship it.

Tools: `scripts/strata_ballast.py` (VRAM and RAM ballasts) and
`scripts/strata_qualify.py` (the matrix, launched through Marvin's own
`servermgmt`, so the Phase 2 integration runs on the real engine too).
`scripts/strata_measure_all.ps1` runs the hash check, Phase 0 and the matrix in
one go.

Where things live (owner, 6 October): measurements run on the NVMe system drive
C:, where the installed Marvin runs; the repository on E: (a USB-attached SATA
SSD, the backup drive) keeps the code, the docs and the final record.

- Strata's data (weights, pack, MTP): `%LOCALAPPDATA%\QwenHarness\runtime\models\strata`,
  the installed Marvin's own `paths.strata_data_dir`.
- Strata's program and the raw results: `%LOCALAPPDATA%\StrataEval`.
- The September llama numbers were measured on the fast drive too, so they stay
  the comparison.

Phase 3 note: the second IQ3_S shard and the IQ2_XS one are the same file
(same SHA-256), and so is the projector. Strata's setup hard-links them; Marvin's
download receipts are per folder, so the catalog needs shared-asset support
before a second weights entry is added.

## After the matrix

In Marvin itself, with the Strata entry enabled:

- switching between Qwen 3.8 27B Q5 and Flash-Next both ways in the same chat;
- injected memory pressure: 256k to 128k with the frozen expert cache;
- prefix reuse (`tests/check_prompt_performance.py` style);
- `tests/e2e_smoke.py`, `tests/e2e_coding_workflow.py`, compression, STOP and
  steering.

Then the measured table goes to the owner. On approval:

- profiles with `min_vram_gb` and `min_ram_gb` go to
  `harness/measured_profiles.py`, one model entry per weights;
- the picker filters by RAM as well as GPU class;
- `flash_next_q3` is removed.
