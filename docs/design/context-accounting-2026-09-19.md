# The context figure, measured instead of assumed

19 September 2026. Two displays disagreed about the same conversation at the same
moment: the composer said `Context: ~56k / 197k` while the server, reading that
very prompt, reported `reused 0/70k`. Neither was a rendering bug. One number was
measured and the other was guessed, and the guess was low.

## What each number was

| shown | where from |
|---|---|
| `reused 0/70k (0%)` | `prompt_progress` - the server's own tokeniser |
| `52%` | progress through the part *not* in cache, not how full the context is |
| `~56k / 197k` | a character estimate: characters ÷ 3.6, plus 1400 per picture |

The bare `52%` sat right after the words "Reading context", so it read as
occupancy. It is now labelled `new 52%`.

## The estimate was wrong, and always in the same direction

Two conversations had the server's own count recorded in `meta.json`:

| conversation | server | estimate | |
|---|---|---|---|
| 20260913 (no pictures) | 89,670 | 79,753 | 11% low |
| 20260918 (7 pictures) | 90,751 | 75,516 | 17% low |

The image-free one fixes the ratio on its own: 287,114 characters were 89,670
tokens, so **3.20 characters per token, not 3.6**. Czech prose and JSON tool
output both tokenise worse than the English the old figure suited.

Given that ratio, the conversation carrying pictures had 18,087 tokens
unaccounted for across 7 of them: **about 2,580 per screenshot, not 1,400**.

A third, independent reading confirmed the ratio rather than assuming it. One
request in that session was measured by the server at `total: 72,663` with no
images in the prompt; 232,661 characters ÷ 3.202 is 72,663.

The image cost is the weaker of the two numbers - it is a remainder, derived from
one conversation once the ratio was fixed elsewhere, so it carries whatever that
conversation's own mix costs. The ratio is the solid one.

## What that cost, beyond a confusing display

Compression runs at `COMPRESS_AT = 0.85` of the estimate. An estimate 17% low
means it fires when the real prompt is at **102% of the context limit** - the
safety margin was gone. The event log shows no overflow yet, so this had not bitten,
but it was waiting to. The same estimate also decided when giving up screenshots
was worth a rewrite, and `harness/context.py` used 3.6 to turn a token budget
into a character budget, asking summarisation for 12% more text than would fit.

## The fix: stop guessing where a measurement exists

The constants are now the measured ones, and there is one place - `tokens_for` -
where characters and pictures become tokens.

Better than any constant: the server reports the exact prompt length with every
response, so `calibrate_tokens` corrects the estimate towards what was actually
measured, smoothed at 0.3 so one odd request cannot swing it, and ignoring any
ratio outside 0.5-2.0 because a truncated or retried request teaches nothing. A
conversation of Czech prose, one of Python and one of screenshots each settle on
their own ratio instead of sharing a compromise.

Verified against a state the owner photographed while it was happening - a
request the server measured at 144,074 tokens:

| | tokens | |
|---|---|---|
| server, measured | 144,074 | |
| shown by 1.14.1 | ~132,000 | 8.4% low |
| new estimator | 143,860 | 0.1% off |

That is out of sample: the constants come from the two conversations above, not
from this one.

## What this did not fix, and the numbers for it

The event log holds `prompt_progress` for 357 requests. Reuse is not the problem
it was:

- **Later steps within a task: 327 of 340 reused the prompt** - 96%, mostly at
  99%, costing a tenth of a second.
- **First request of a task: 13 of 17 reprocessed everything.**

Those 13 cost 70k to 161k tokens each, 33 to 120 seconds, and they account for
**66% of all prefill time ever spent** (3,612 of 5,435 seconds).

Every one of them was the *same* conversation as the request before it, with no
model reload in between - only a pause. Four minutes was enough to lose it:

| gap before the next message | reuse |
|---|---|
| 4 min | 0% |
| 5 min | 0% |
| 16 min | 0% |
| 88 min | 0% |
| 236 min | 0% |

**Correction, same day.** The paragraph here first blamed a pause and named
`--cache-ram 256` as the likely cause. Both were wrong. That argument is only on
the Flash-Next path in `harness/runtime_plan.py`; a Qwen server never receives it
and runs at the default 8192 MiB. And the check behind "no model reload in
between" was the `loading_model` UI phase in the event store, which appears
**once** in the entire store - so it proved nothing.

Matching each cold start's prompt size against the server log answers it
properly. Seven of nine were `task 0` - the first request of a **freshly started
server**, whose cache is empty because the process is new:

| prompt | found in the log as |
|---|---|
| 70,449 | run 130, task 0, 33 s |
| 144,074 | run 133, task 0, 99 s |
| 161,250 | run 128, task 0, 118 s |
| 125,510 | run 125, task 0, 78 s |
| 88,505 | run 106, task 0, 67 s |
| 140,765 | run 125, task 3332, 98 s - a genuine mid-run loss |
| 113,239 | run 103, task 127, 64 s - a genuine mid-run loss |

The server log holds **134 `listening on http` lines**, so 134 separate server
processes. **83 of those runs served no request at all** - each loaded 19.8 GB of
weights fully (all 83 reached "model loaded", only one logged an error) and was
then replaced without being asked anything.

So the cost is restart churn, not cache eviction, and `--cache-ram` cannot help:
the prompt cache lives inside the process that is being replaced.

## `--cache-ram` measured, and it is not the lever

Measured directly rather than argued about. A Qwen Q5 server, `q8_0` cache, asked
the same conversation before and after a pause, and before and after a *different*
conversation took its single slot - because those are two different mechanisms and
only the second is what `--cache-ram` governs.

At 15k tokens, 32k context:

| `--cache-ram` | cold | immediately | after a 300 s pause | after another conversation |
|---|---|---|---|---|
| 8192 (default) | 4.80 s | 0.30 s | **0.40 s** | **0.40 s** |
| -1 (unlimited) | 4.70 s | 0.20 s | - | **0.40 s** |
| 0 (disabled) | 4.70 s | 0.20 s | - | **4.80 s** |

Three things, and the third is the answer:

1. **A pause costs nothing.** Five minutes of silence, then 0.40 s and no prefill
   line in the server log at all. Time does not evict a prompt.
2. **Another conversation costs nothing either** - as long as the cache is on.
   Turning it off (`0`) makes the return trip cost a full reprocess, the same
   4.80 s as cold, which is what proves the saving path is real and working.
3. **Raising it above the default buys nothing.** Unlimited and 8192 are the same
   number to two decimal places.

The obvious objection is that a 15k entry is small and his conversations are ten
times that, so the test was repeated at the real size - 150k tokens in a 196,608
context, the profile he runs:

| step | time |
|---|---|
| first, cold | **92.4 s** |
| again, immediately | 0.3 s |
| an unrelated conversation takes the slot | 2.1 s |
| back to the 150k conversation | **1.2 s** |

Ninety-two seconds becomes one. The default 8192 MiB holds a 150k-token
conversation across an interruption, so there is nothing to raise.

## What to do instead

The first question is why there are 134 restarts. 26 are real model switches the
owner made, including the one back to `q5` at 18:47:59 that made the photographed
18:52 request cold - those are correct and unavoidable. The rest are not
explained: `kv_cache_modes` changed 9 times and `vram_gb` 7 times, which does not
cover them.

`application.py:771` restarts when any of four conditions holds - profile changed,
hardware changed, the server is unhealthy, or `running_model(cfg) != key` - and
records **which** of them decided. A bare `except Exception` in
`servermgmt._managed_process` deletes the PID file on any psutil failure, which
would make the harness think its own server is gone; tested against the live
process, psutil answered `name`, `exe`, `cmdline` and `status` without raising, so
that is not it either.

The cheap next step is the one that worked for the prompt cache itself: log the
reason. One line naming which condition triggered each restart, and the next
occurrence explains itself instead of being reconstructed from a log six days
later.

The one mid-task break still in the trace window was not a defect: the system
prompt grew by exactly 462 characters, the length of the Ornith reasoning-effort
block, when the model was switched to `ornith_q5` at 18:41:38. A changed system
prompt is a changed prefix, and reprocessing it is correct.

## What is not measured here

Nothing here says what a calibrated estimate does over a conversation that
changes character halfway - Czech discussion that turns into a long Python file.
The correction follows it, smoothed over roughly three requests, so the figure
lags a shift rather than tracking it exactly. It is an estimate between requests
by necessity: only a request that has been sent has been counted.
