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

- **Smaller GPUs are simulated with a VRAM ballast.** Strata fills all free VRAM
  with its expert cache, so measuring on the 32 GB card and comparing with a
  budget afterwards would always "fit". A helper process allocates VRAM until
  what is left matches the usable memory of the real card beside a desktop:
  about 21.9 GiB for the 24 GB class and 14.3 GiB for the 16 GB class (the limits
  the earlier profiles used). The engine then sizes itself as on that card.
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

About 35 launches. A case that cannot load ends at once and is recorded as
rejected, like the September Flash 16 GB / 256k case. Before the matrix,
Phase 0 (`scripts/strata_eval.py run`) gives the first IQ3_S numbers.

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
