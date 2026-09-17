# Measured memory profiles and recovery - Marvin 1.9.0

The owner-approved [September 15 qualification](profile-remeasurement-2026-09-15.md)
is the reusable source for this release. Its [JSON](measurements/2026-09-15.json)
and [CSV](measurements/2026-09-15.csv) retain all 55 cases, commands, resource peaks,
functional outcomes and long-input coverage. The full local archive is identified
by SHA-256 in that report. Reuse unchanged cases instead of repeating the matrix.

## Profile authority

`harness/measured_profiles.py` owns the built-in base-model profiles. GPU classes
control the menu; `min_vram_gb` records model allocation separately from desktop
usage. Reported capacity slightly below 16/24/32 GiB maps to its nominal class.
Larger cards use the 32 GB menu. Each precision group has two contexts. Q8 is the
default. F16 is optional only for Qwen Q4/Q5 on 32 GB-class GPUs. IQ3 appears only
on 16/24 GB. Ornith offers 256k/192k, and Nemotron Q4/Q5 offer 512k/256k.

The small-card Qwen placements retain vision using the CPU projector where
measured. Nemotron's CPU-expert settings are layer prefixes, not expert counts:
Q4 24 GB uses 14/12; Q5 24 GB uses 21/18. Q5 32 GB uses 2 for 512k and zero for
256k. Public labels show Q8 and context, never an invented R cache precision.

Qwen Q4/Q5 additionally offer opt-in speculative variants labeled "· MTP" next
to their plain Q8 counterparts. They generate roughly 2–3× faster through the
pinned MTP draft model at an extra 1.9–2.8 GiB measured VRAM cost; q4 has
24 GiB-class variants where that cost fits, q5 does not. F16 groups and IQ3
ship without variants. Their measurements and qualification are recorded in
[mtp-profiles](mtp-profiles.md); plain profiles are unchanged. Keeping the
draft in system RAM instead of VRAM was measured 33–40 % slower than plain and
was rejected for all classes.

An upgrade normalizes shipped profiles in memory, without rewriting config.yaml.
Existing valid UI choices are retained. Obsolete selections resolve to a current
profile for the hardware. Custom model keys/checkpoints remain independent.
The distributed config.yaml no longer duplicates the built-in model table.

## Flash-Next planning

The unchanged b10935 runtime uses Q3 weights, Q8 KV, lazy PLE reads, no-host mode,
batch 1024, microbatch 256 and a 256 MiB auxiliary prompt-state cache. This cache
budget is separate from the context window. CPU threads follow physical P cores
when available, without halving a processor that has no hyperthreading.

GPU and RAM estimates combine exact expert tensor sizes with measured residual
allocations. CPU32 is the 32 GB starting bound because CPU31 spilled into shared
GPU memory in qualification; CPU39/46 are the corresponding 24/16 GB placement
bounds. Startup may offload more if other programs occupy GPU memory. These are
Flash-specific measurements, not a general 2-4 GiB reserve on every model.

The picker offers the highest two feasible windows from 256k/192k/128k. The
planner compares estimated working set with installed physical RAM, not initial
free RAM; Windows may reclaim pages and grow its pagefile. Working set remains
an estimate, not an irreducible minimum or private-commit total. The measured
16 GB placement with 64 GB RAM failed during 256k warmup, so this combination
does not offer 256k. Smaller windows still require successful real startup.

No physical 16/24 GB GPU was tested. Do not present simulated placement or RAM
forecasts as hardware qualification. Flash's 253,883-token prompt passed at 256k
on the 5090 but took about 44 minutes; cached continuation returned in 1.73 s.

## Selection, persistence and recovery

- Manual capacity cannot exceed the physical GPU. Changing it stops the old
  model before loading the replacement and remembers successful settings by budget.
- A failed user-requested configuration change can restore the prior working
  configuration. Continue uses the currently selected model and context.
- An allocation failure retries only a strictly smaller context of the same
  model, KV precision and GPU class. Frozen placement retains CPU experts and
  projector placement, rather than refilling freed VRAM with weights.
- A session that started on an MTP variant recovers in this order: the same
  context without MTP, then the next lower context with MTP, then that context
  without MTP, continuing interleaved. Plain selections never gain MTP during
  recovery; an explicit profile choice resets that intent.
- Actual CUDA/host allocation errors are recognized at startup and on requests.
  High total VRAM usage alone does not kill an otherwise functioning model.
- The emergency physical-RAM guard requires available RAM below 512 MiB for ten
  successive one-second samples. Commit growth or a brief low-memory sample does
  not trigger it. This threshold is not added to profile requirements.
- Recovery retains history and completed tool results; unknown outcomes are
  marked before continuation. STOP remains authoritative. Retries are bounded by
  decreasing context and Flash never falls below 128k.
- Successful placement and recovered context are saved with the budget preset,
  allowing restart without immediately retrying a known failed larger window.

## Regression evidence

`tests/test_memory_profiles.py` covers the exact menu, defaults, migration,
budget normalization, allocation detection, unchanged precision/placement,
RAM reclamation, rollback and continuation without repeated completed tools.
`tests/check_memory_transitions.py` exercises real model switching on isolated
application data and injects a memory failure without exhausting host memory.
Runtime/installer qualification and published hashes are recorded separately
in the 1.9.0 release evidence. The inference runtime and dependency lock remain
unchanged from the measured baseline.
