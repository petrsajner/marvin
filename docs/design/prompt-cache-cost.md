# What a changed prompt costs, and how the harness stopped paying it

19 September 2026. Measured from one Computer-mode session, fixed, and verified
against a live server.

## Complaint

A Computer-mode task reported by the owner: give the command, the context loads
for about a minute; the model says ok and starts the game, the context loads from
zero again; it presses Enter, takes a screenshot, the context loads from zero
again. Every step appeared to re-read the whole conversation.

## Evidence

`prompt_progress` is recorded in the event store for every request, so the
session could be replayed exactly. 92 requests, and the prompt reached 141k
tokens. Two shapes alternated:

| clock | total | reused from cache | prefill |
|---|---|---|---|
| 11:53:48 | 127 983 | 127 941 | 0.5 s |
| 11:53:54 | 129 287 | 87 662 | 40 s |
| 11:54:44 | 131 453 | 129 283 | 2.7 s |
| 11:54:50 | 131 638 | 87 662 | 42 s |
| 12:04:44 | 140 765 | 0 | 98 s |

Total prefill across the session: 13 minutes. About 12 of those were avoidable.

### Cause 1 - memory lived in the system prompt

`build_system_prompt` appended `MemoryStore.context_block()`, so memory sat in
the first message of every request. The three requests that reused *nothing*
(65 s, 78 s, 98 s) each followed a run in which the model had saved a fact. The
per-run context snapshots confirm it directly: the system prompt grew from 8307
to 8787 to 9066 characters and diverged at character 4955, then 5435 - inside the
memory block. The run whose prompt was byte-identical to the previous one reused
116 918 tokens.

One saved line therefore cost a full reprocess of the entire conversation.

### Cause 2 - the image window rewrote already-sent history

`to_api_messages` encoded only the newest 8 images and recomputed that set on
every request. The ninth screenshot silently removed the first one from a message
the server had already processed, which changes the prompt prefix.

Replaying the prompt assembly message by message over the stored session found
**11 such breaks**, each costing 38-62 s. In Computer mode, where a screenshot
follows every action, this hit roughly every second step.

## What the server can and cannot reuse

Measured with `llama-server` from `runtime/llama`, Qwen3.8-27B-UD-IQ3_S, 32k
context, `/v1/chat/completions` with `return_progress` - the same path the
harness uses. Each shape is sent against the cache left by the previous request:

| shape | total | reused | prefill |
|---|---|---|---|
| identical request again | 4 969 | 4 965 (99%) | 95 ms |
| one turn appended | 5 527 | 4 969 (89%) | 355 ms |
| one line added to the system prompt | 5 540 | **0 (0%)** | 1 685 ms |
| a middle turn removed | 5 093 | 1 499 (29%) | 1 183 ms |

Appending is free. Editing the front is total loss. Removing something in the
middle keeps only what precedes it. There is no partial credit beyond the first
difference.

### `--cache-reuse` is not available to us

`--cache-reuse N` asks the server to reuse cached tokens past a divergence by
shifting the KV cache. Measured in four configurations - default, with `q8_0` KV,
with `f16` KV, and with `--kv-unified` - the server answered identically each
time, at load:

```
W srv load_model: cache_reuse is not supported by this context, it will be disabled
```

Every shape produced the same numbers as the table above. It is not the KV
quantization and not the unified cache; this context cannot shift its KV. The
flag was therefore not adopted: it would only add a warning to the log.

## Decisions

1. **Memory and the skill catalogue moved out of the system prompt** into the
   dynamic context block, which already sends only changed sections and appends
   them. `build_system_prompt` now returns the mode prompt and the workspace
   line only, and is deliberately byte-stable for a whole session.
2. **Image retention became a persisted property of the message.** A new
   screenshot never changes what earlier messages send. `Session.prune_images`
   is the single place allowed to give images up, the decision is written to
   `messages.jsonl`, and it survives a reload - otherwise the prefix would break
   again on the next start.
3. **Pruning runs only under context pressure, ahead of summarizing.** Images are
   the largest items in a Computer-mode conversation and the cheapest to lose, so
   `_maybe_compress` drops all but the four newest and only summarizes if that is
   not enough. Both rewrite the processed prompt; this one keeps the text.
4. **The activity line reports reuse**, because a cached prompt and a full
   reprocess were previously indistinguishable while waiting: the share reused,
   and an estimate of the time left from the observed rate.

The accepted trade-off for 2 and 3: keeping every screenshot costs roughly 1-2.5k
tokens each, so compression arrives sooner. One deliberate rewrite when the
context fills replaces ten accidental ones per session.

## Verification

The real `Agent`, `Session` and `LLMClient` driven against a live server with the
multimodal projector loaded and `--image-min-tokens 1024`: a Computer-mode task,
a screenshot per step, and a memory fact saved after step 4.

| step | total | reused | share | prefill |
|---|---|---|---|---|
| 0 | 1 995 | 0 | 0% | 1 112 ms |
| 4 | 6 283 | 5 207 | 82% | 619 ms |
| *memory saved* | | | | |
| 5 | 7 587 | 6 279 | 82% | 667 ms |
| 9 | 11 875 | 10 799 | 90% | 660 ms |

Every step reuses the whole previous prompt, including the step after the memory
write, which cost the 232 tokens the fact actually is. Prefill stays around
650 ms per step instead of growing to 40-98 s. The share rises only because the
appended part is constant while the total grows - the signature of an append-only
prompt.

Regression cover lives in `tests/test_prompt_performance.py`: saving a fact must
not change the system prompt, a new screenshot must not rewrite the prefix,
pruning must persist across a reload, and context pressure must give up
screenshots before summarizing.

## Left open

Compression and image pruning still break the prefix once each, by construction -
they exist to remove what the model has already seen. With `--cache-reuse`
unavailable, the only lever is frequency, which is why pruning is now tied to
context pressure rather than to taking a screenshot.
