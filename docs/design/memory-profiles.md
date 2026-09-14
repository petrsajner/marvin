# Memory budgets, profiles and recovery

This describes the source changes after the published 1.8.2 build. Installers and release assets have not been rebuilt for these changes.

## Runtime contract

- A manual GPU budget is capped by the real device capacity. It describes a smaller capacity budget; it cannot create additional VRAM.
- Model memory is released before preparing another configuration. A failed stop must not start a competing allocation.
- Each successful GPU-budget selection remembers its model and context profile. Returning from a 16 GiB budget to automatic detection restores the previous automatic configuration.
- Equivalent automatic/manual capacity selections reuse an already matching server. Explicit Restart still reloads it.
- Base models select compatible profiles and prefer the same model family before considering other models.
- A failed change restores the previous working model, context and budget, including a previously successful configuration retained across application restarts.
- Queued work uses the current device budget and current profile definitions. Conversation content, work mode, reasoning settings and approval policy remain attached to the task.

## Corrected small-card profiles

The old 48k Qwen IQ3 profile exceeded a 16 GiB capacity budget. The old Qwen Q5 F16/96k profile exceeded 26 GiB despite being labelled for 24 GiB cards.

The compact Qwen IQ3 profile now uses Q8/32k with a smaller microbatch and CPU execution of the vision projector. Qwen Q5 has a Q8/64k compact profile with the same projector placement. Vision remains available, but image processing can take longer. Weight quantization is unchanged.

The active model catalog no longer offers the obsolete one-million-token profile. Existing configuration files are normalized in memory without rewriting user files. Unsupported profile choices are not offered for the selected GPU budget.

## Flash-Next

Flash-Next remains Q3 with Q8 KV and a minimum context of 128k. The planner chooses 256k, 192k or 128k after the previous model has stopped and available memory has been measured again.

The planner reserves working RAM separately from CPU expert weights and the RAM kept free for Windows. Working reserves increase with the context size. The microbatch is 128 and the auxiliary prompt-cache budget is 256 MiB. GPU placement still accounts for common weights, the projector, attention/indexer cache and working buffers.

Reducing GPU capacity moves more expert weights into system RAM. On this machine, representative estimates require roughly 52 GiB of free RAM for a 24 GiB GPU budget and roughly 60 GiB for a 16 GiB budget. These are available-memory requirements, not installed-memory specifications. A 64 GiB computer running other applications may not meet them.

Map-based loading variants were investigated but were not accepted: they reached the protective RAM floor during prefill. Their shorter startup time was insufficient evidence of a usable configuration.

## Pressure recovery

The managed process is stopped before critical RAM pressure or sustained exhaustion of the effective GPU budget can continue. GPU accounting includes driver-reserved memory, which is why `memory.total - memory.free` can exceed the displayed `memory.used` figure.

During an active task, a matching pressure failure triggers a bounded retry with a smaller supported memory profile. The existing transcript is retained; completed tool results are not repeated, and missing results are marked as unknown before retrying. STOP remains authoritative. Flash-Next never falls below 128k. A successfully reduced Flash-Next profile is remembered instead of immediately requesting the failed larger profile again.

If no supported smaller profile remains, the task stops with the identified RAM/VRAM reason. The program cannot guarantee operation when the physical memory required by the selected weights and minimum context is unavailable.

## Verification

`tests/check_memory_profiles.py` tests real inference, tool calls, vision where supported, and STOP under measured capacity budgets. `tests/check_memory_transitions.py` exercises the actual application path across automatic, 24 GiB, 16 GiB and automatic configurations, then injects a memory failure without exhausting the host and checks restart/continuation without duplicating the user message.

Completed capacity checks on the RTX 5090 / 64 GiB RAM host:

| Capacity budget | Model/profile | Result |
|---|---|---|
| 16 GiB | Qwen IQ3 / Q8 / 32k, CPU vision projector | Passed text, tool roundtrip, vision and STOP; peak unavailable VRAM about 14.78 GiB |
| 24 GiB | Qwen Q5 / Q8 / 64k, CPU vision projector | Passed the same checks; peak unavailable VRAM about 23.33 GiB |
| 24 GiB | Qwen Q4 / Q8 96k and F16 64k | Passed text, tools, vision and STOP |
| 24 GiB | Nemotron Q4 / Q8 256k and 512k with CPU experts | Passed text, tools and STOP |
| 32 GiB | Existing six base model variants at their primary profiles | Passed applicable text, tool, vision and STOP checks |
| 32 GiB | Flash-Next Q3 with planner-selected 192k | Passed text, tools, vision and STOP |

These are capacity simulations on a 32 GiB card. They do not measure the performance or driver behavior of a physical 16/24 GiB GPU. Positive Flash-Next results on physical 16/24 GiB cards are not claimed.

A separate diverse-text qualification (`tests/check_flash_memory.py`) passed with Q3 weights, Q8 KV and a 128k context. The request contained 98,124 prompt tokens from 129 public repository files. It recovered markers at the beginning, middle and end. Prefill took 1,432 seconds (68.5 tokens/s); this remains a slow first read, not a solved throughput problem. The follow-up reused 98,148 cached tokens and returned in 1.38 seconds, with its first token after 0.92 seconds.

During that run, available RAM stayed above 7.07 GiB and server resident memory peaked at 40.93 GiB. This is evidence for the tested 128k configuration, not a full-window qualification of 192k or 256k. Repeated long-context runs and physical small-card qualification remain useful follow-up work.

The detailed `runtime/memory-audit/` reports are preserved inside `runtime/archive/verification-source-2026-09-15.zip`, together with the source-language verification. The archive includes a per-file hash manifest; unpacked test copies are marked for manual removal.
