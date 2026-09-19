# Marvin 1.14.3 - every restart now says why

19 September 2026.

## The waiting was never the pause

Reading a prompt again is the difference between a step costing half a second and
costing a minute and a half, and almost all of the time ever spent reading
prompts went on the first request after a break. The obvious suspect was the
break itself. It is not.

Measured at 150k tokens in a 196,608 context - the profile in use here:

| step | time |
|---|---|
| first, cold | **96.0 s** |
| again, immediately | 0.3 s |
| **after a 25-minute pause** | **0.5 s** |
| an unrelated conversation takes the slot | 1.9 s |
| back to the 150k conversation | 1.0 s |

Twenty-five minutes of silence costs half a second. The server log shows it
structurally: the request after the pause has no `prompt processing` line at all,
so it read no new tokens, and nothing was evicted. That matches the settings -
the prompt cache is bounded by size, not age, and `--sleep-idle-seconds`, the
only time-based option, defaults to `-1` and is never passed.

`--cache-ram` was measured too and is not the lever. At the default 8192 MiB a
conversation survives both a pause and another conversation taking its slot;
disabling it (`0`) makes the return trip cost a full reprocess, which proves the
saving path works; unlimited is identical to the default. There is nothing to
raise.

## What it actually was

Matching each cold start's prompt size against the server log: **seven of nine
were `task 0`**, the first request of a freshly started server process, whose
cache is empty because the process is new. The log holds 134 separate server
processes, and **83 of those runs served no request at all** after loading
19.8 GB of weights.

A restart throws the prompt away because the cache lives inside the process being
replaced. No setting survives that.

## So the restarts explain themselves now

Four conditions can each trigger a restart - the KV profile changed, the recorded
hardware changed, the server did not answer `/health`, or a different model is
running - and the decision recorded none of them. The reason had to be
reconstructed days later from prompt sizes.

`harness/restart_log.py` now writes it down as the decision is taken: which
conditions fired, what was running, what was wanted, the profile and the context.
The memory-pressure retry records itself too.

```
python scripts/explain_model_restarts.py
```

reads it back and counts a switch you asked for apart from one the harness talked
itself into - only the second kind is a defect. Of the 134 restarts on this
machine, 26 were deliberate model switches; the remaining hundred-odd are the
question this release exists to answer.

The log holds no conversation, keeps the most recent 200 decisions, and cannot
raise - every lookup happens inside the guard, including `context_size`, which
throws for a model without a configured context. A diagnostic must not be able to
fail where the restart decision is being made.

## Upgrading

Application code only. Conversations, projects, models and settings are
untouched. Restarts are recorded from the next task onwards, so the file is empty
until then.

## Verification

372 checks in the core suite and 290 unit tests, green locally before the build,
10 of them new. The measurements are in
[context-accounting-2026-09-19.md](../design/context-accounting-2026-09-19.md),
including what the owner's own history could not settle: all thirteen long-gap
requests in it reused nothing, but every one of those gaps also contained a
restart, so time and restart were not separable there without measuring.
