# Marvin 1.14.2 - the context figure is now measured

19 September 2026.

## Two numbers for one conversation

The composer said `Context: ~132k / 197k` while the server, reading that very
prompt, reported `reused 0/144k`. Neither display was broken. One number was
measured by the server's tokeniser and the other was estimated from characters,
and the estimate was low.

It assumed 3.6 characters per token and 1,400 tokens per screenshot. Measured
against what the server actually counted, in the two conversations that had the
server's own figure on disk:

| conversation | server | old estimate | |
|---|---|---|---|
| no pictures | 89,670 | 79,753 | 11% low |
| seven pictures | 90,751 | 75,516 | 17% low |

The image-free one fixes the ratio by itself: 287,114 characters were 89,670
tokens, so **3.20 characters per token**. Czech prose and JSON tool output both
tokenise worse than the English that 3.6 suited. At that ratio the conversation
with pictures had 18,087 tokens unaccounted for across seven of them - **about
2,580 per screenshot, not 1,400**.

Both errors ran the same way, so Marvin believed the context was emptier than it
was.

## That was more than a confusing display

Compression fires at 85% of the estimate. At a 17% undercount that is **102% of
the real context limit** - the safety margin had gone. No overflow had happened
yet; it was waiting to. The same 3.6 turned a token budget into a character
budget for summarisation, asking for 12% more text than would fit.

## The fix

The constants are the measured ones, and characters and pictures become tokens in
exactly one place.

More usefully, the server reports the exact prompt length with every response, so
the estimate no longer has to keep guessing: it is corrected towards the
measurement after each reply, smoothed so a single odd request cannot swing it,
and implausible ratios are ignored because a truncated or retried request teaches
nothing. A conversation of Czech discussion, one of Python and one of screenshots
each settle on their own ratio instead of sharing a compromise - which matters,
because the gap was never constant: 20% in one measured state, 8% in another.

Verified against a state photographed while it was happening, and outside the
data the constants came from:

| | tokens |
|---|---|
| server, measured | 144,074 |
| shown by 1.14.1 | ~132,000 (8.4% low) |
| 1.14.2 | 143,860 (0.1% off) |

**The percentage while the prompt is read is now labelled.** A bare `39%` after
the words "Reading context" read as how full the context was. It is progress
through the part the server does not already hold, and it now says `new 39%`.

## What this does not fix, with the numbers

The event log holds the server's own progress for 357 requests:

- **Later steps within a task: 327 of 340 reused the prompt** - 96%, mostly 99%,
  a tenth of a second each. The 1.14.0 and 1.14.1 work holds.
- **First request of a task: 13 of 17 reprocessed everything** - 70k to 161k
  tokens, 33 to 120 seconds each.

Those 13 account for **66% of all prefill time ever spent** (3,612 of 5,435
seconds).

Matching each one's prompt size against the server log shows why: seven of nine
checked were `task 0`, the first request of a **freshly started server process**,
whose cache is empty because the process is new. The log holds 134 separate
server processes, and **83 of those runs served no request at all** after loading
19.8 GB of weights. So this is restart churn, not a cache that expires with time,
and `--cache-ram` cannot help - that cache lives inside the process being
replaced. Why there are 134 restarts is the next thing to find out; 26 are model
switches the owner made deliberately.

One mid-task reprocess in the trace was not a defect: the system prompt grew by
exactly 462 characters - the Ornith reasoning-effort block - when the model was
switched to `ornith_q5`. A changed prefix must be read again.

## Upgrading

Application code only. Conversations, projects, models and settings are
untouched. Existing conversations start from the measured constants and calibrate
themselves from the next reply onwards.

## Verification

372 checks in the core suite and 280 unit tests, green locally before the build,
plus a frontend type-check and build. Seven of the unit tests are new and cover
the two counting paths agreeing with each other, calibration converging on a
measurement, and an implausible measurement being ignored. Recorded in
[context-accounting-2026-09-19.md](../design/context-accounting-2026-09-19.md).
