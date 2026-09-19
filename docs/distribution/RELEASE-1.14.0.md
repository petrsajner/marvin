# Marvin 1.14.0 - a smaller model, a smaller cache, and nine new ways to run

19 September 2026.

## A 16 GB card gets eight options instead of two

It was offered the weakest quant at 64k or 48k, in both cases with the vision
projector on the processor, and nothing else fit. Measured under an explicit
budget, two findings opened it up.

**Quantising only the value half of the cache saves a gigabyte and costs no
speed.** IQ3_S at 128k needs 16.05 GB with a full Q8 cache and 15.04 GB with Q8
keys and Q4 values. Across twelve combinations, reading stayed between 2787 and
3101 tokens a second and generating between 85 and 96 - the type of cache changed
nothing measurable. Keys and values are therefore separate settings now, because
values tolerate quantisation far better than keys.

**Qwen3.8-27B Q2_K_XL is 2 GB smaller than the IQ3_S in use**, which is enough to
keep vision on the graphics card *and* have 96k of context. A 16 GB card could
not have the projector on the card at all before, so every screenshot was slow -
on the very configuration where computer control matters most.

| model | profile | context | measured |
|---|---|---|---|
| Q2_K_XL | Q8 · 64k · vision on GPU | 64k | 12.96 GB |
| Q2_K_XL | Q8 · 96k · vision on GPU | 96k | 14.19 GB |
| Q2_K_XL | Q8 · 128k | 128k | 14.31 GB |
| Q2_K_XL | Q4 · 192k | 192k | 13.73 GB |
| IQ3_S | Q8/Q4 cache · 96k | 96k | 14.08 GB |
| IQ3_S | Q4 · 128k | 128k | 14.05 GB |

The figures are what the server allocated with the desktop's own usage
subtracted. They stay inside the band the approved 16-class entries already
occupy - 13.0 to 13.6 GB - because that gap below the nominal 16 is the room a
desktop needs, not spare capacity.

## And a fast mode on a large card

Q2 is small enough that on a 32 GB card the context, not the weights, is what
fills it: **256k with vision on the GPU, 20.27 GB, 97 tokens a second**, against
62 for Q5 at 196k. A deliberate trade of weight quality for speed and room, for
work where the screen matters more than the prose.

384k and 512k were measured to fit and are deliberately not offered: no Qwen
profile here has been approved beyond 256k, and coherence past that was not
tested.

## Two decisions made on purpose

**Q2 is offered but never chosen automatically.** A two-bit 27B model is a real
drop in quality, worst on code and on following instructions exactly, and that
trade belongs to the owner. It is marked `optional_download`, which already meant
"do not fetch unless asked" and now also means "do not select unless asked" - so
a 16 GB card still starts on IQ3_S at 64k, and a 32 GB card still starts on Q5.

**A reduced value cache is never the default either.** Automatic selection
prefers a profile whose keys and values match. What a 4-bit cache costs is recall
over a long conversation - the model misremembering something from twenty steps
back - and nothing here measures that, so nothing here turns it on for you.

## What was left out, with the numbers

**Nemotron 30B with experts on the processor** fits a 16 GB card at 13.8 GB and
managed 66 to 80 tokens a second here. It was not added: it moves expert weights
across the link on every token, and on a 4060 Ti that link is half as wide
(PCIe 4.0 x8) with a fifth of the memory bandwidth. It would be the slowest
option on the very card it was meant for.

**A tempting 24 GB candidate** - Q4 at 192k with a Q4 value cache and vision on
the GPU, twice the current context at the same weights - measured 22.05 GB
against an approved maximum of 21.92. It was left out because neither machine
here has a 24 GB card to try it on, and the 0.13 GB it eats belongs to the
desktop. It is the first thing to measure if such a card appears.

## Also in this release

Every request now records a fingerprint - role, size and a hash per message, no
content - and `scripts/explain_prompt_cache.py` names the first message that
changed between two requests. Screenshots no longer reset the whole context, but
three requests in one session reused exactly 131746 tokens and reprocessed 44259,
and three explanations for that were measured and all three were wrong: media
chunks reuse at 99%, no image pruning happened, and the prompt-cache limit
changes nothing. The conversation on disk is provably append-only, which leaves
what replay cannot see - a message rewritten in place looks, afterwards, as
though it always was that way. One reproduction with the trace running will
answer it.

Dictation shows how far its download has got, instead of one sentence that never
changed. `press_key` accepts a window title and reaches a program without
bringing it forward. There is a skill for testing a running program, with or
without a window. And `scripts/explain_prompt_cache.py` aside, the housekeeping
that used to be manual - renaming the offline backup, following it afterwards -
now happens by itself.

## Upgrading

The installer replaces application code only. Conversations, projects, models and
settings are untouched. Q2_K_XL is 9.8 GB and is downloaded only if you select
it.

## Verification

372 checks in the core suite and 270 unit tests, green locally before the build.
The measurements are recorded in
[profiles-16gb-2026-09-19.md](../design/profiles-16gb-2026-09-19.md), including
what they cannot say: speed was measured on a 5090, and a 4060 Ti is a different
and slower card.
