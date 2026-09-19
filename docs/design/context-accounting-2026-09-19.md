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

So the processed prompt does not survive the time the owner spends reading an
answer and typing the next message. `harness/runtime_plan.py` passes
`--cache-ram 256`, which is 256 MiB for a cache that is gigabytes at 144k tokens.
Raising it, or keeping the slot on disk, is the next thing to measure - and it is
worth more than everything in this document, because it is two thirds of the
waiting.

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
