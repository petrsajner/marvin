# Marvin 1.16.1

Everything since 1.12.1: versions 1.13.0 through 1.16.1 in one release.

## What matters most: many more ways to run a model

A graphics card used to leave most of its options untested, so Marvin offered the
few that had been measured and nothing else. **The catalogue is now 39 measured
configurations across three card classes**, and the smallest card gained the most:
it had two, and has eight.

Every figure below is what the server actually allocated with the desktop's own
usage subtracted - not a specification, not a calculation. Marvin picks from these
automatically, and you can choose a different one yourself.

---

### 32 GB — 19 configurations

| model | cache · context | vision | measured |
|---|---|---|---|
| Qwen3.8-27B Q2_K_XL | Q8 · 256k | on GPU | **20.27 GB** |
| Qwen3.8-27B Q4_K_M | F16 · 96k | on GPU | 22.36 GB |
| Qwen3.8-27B Q4_K_M | Q8 · 192k | on GPU | 23.50 GB |
| Qwen3.8-27B Q5_K_M | Q8 · 128k | on GPU | 24.19 GB |
| Nemotron 3.5 Lightning Q4_K_XL | Q8 · 256k | on GPU | 24.31 GB |
| Qwen3.8-27B Q4_K_M | F16 · 128k | on GPU | 24.37 GB |
| Nemotron 3.5 Lightning Q4_K_XL | Q8 · 512k | on GPU | 25.42 GB |
| Qwen3.8-27B Q5_K_M | F16 · 96k | on GPU | 25.44 GB |
| Qwen3.8-27B Q4_K_M | Q8 · 192k · MTP | on GPU | 26.03 GB |
| Qwen3.8-27B Q4_K_M | Q8 · 256k | on GPU | 26.14 GB |
| Qwen3.8-27B Q5_K_M | Q8 · 128k · MTP | on GPU | 26.32 GB |
| Qwen3.8-27B Q5_K_M | Q8 · 192k | on GPU | 26.58 GB |
| Ornith 1.5 35B-A3B Q5_K_M | Q8 · 192k | on GPU | 27.13 GB |
| Qwen3.8-27B Q5_K_M | F16 · 128k | on GPU | 27.65 GB |
| Ornith 1.5 35B-A3B Q5_K_M | Q8 · 256k | on GPU | 27.91 GB |
| Nemotron 3.5 Lightning Q5_K_XL | Q8 · 256k | on GPU | 28.88 GB |
| Qwen3.8-27B Q4_K_M | Q8 · 256k · MTP | on GPU | 28.98 GB |
| Nemotron 3.5 Lightning Q5_K_XL | Q8 · 512k | on GPU | 29.09 GB |
| Qwen3.8-27B Q5_K_M | Q8 · 192k · MTP | on GPU | 29.13 GB |

New here: **Q2 at 256k with vision on the card, at 20.27 GB** - a deliberate fast
mode. Two bits is a real drop in weight quality, but the model is small enough
that the context, not the weights, is what fills the card: 97 tokens a second
against 62 for Q5 at 192k. For work where the screen matters more than the prose.

---

### 24 GB — 12 configurations

| model | cache · context | vision | measured |
|---|---|---|---|
| Qwen3.8-27B IQ3_S | Q8 · 96k | on GPU | **16.15 GB** |
| Qwen3.8-27B IQ3_S | Q8 · 128k | on GPU | 17.16 GB |
| Qwen3.8-27B Q4_K_M | Q8 · 64k | on GPU | 18.86 GB |
| Qwen3.8-27B Q4_K_M | Q8 · 96k | on GPU | 19.93 GB |
| Nemotron 3.5 Lightning Q4_K_XL | Q8 · 256k | on GPU | 20.64 GB |
| Qwen3.8-27B Q5_K_M | Q8 · 64k | on processor | 20.72 GB |
| Qwen3.8-27B Q4_K_M | Q8 · 64k · MTP | on GPU | 20.75 GB |
| Nemotron 3.5 Lightning Q5_K_XL | Q8 · 256k | on GPU | 20.90 GB |
| Nemotron 3.5 Lightning Q4_K_XL | Q8 · 512k | on GPU | 21.28 GB |
| Nemotron 3.5 Lightning Q5_K_XL | Q8 · 512k | on GPU | 21.50 GB |
| Qwen3.8-27B Q4_K_M | Q8 · 96k · MTP | on GPU | 21.90 GB |
| Qwen3.8-27B Q5_K_M | Q8 · 96k | on processor | 21.92 GB |

One tempting entry was measured and **left out**: Q4 at 192k with a Q4 value
cache and vision on the card - twice the context at the same weights - came to
22.05 GB against an approved ceiling of 21.92. It sits within the noise, and the
0.13 GB it eats belongs to the desktop. Neither machine here has a 24 GB card to
try it on, so it was not added on a guess. It is the first thing to measure if
one appears.

---

### 16 GB — 8 configurations, up from 2

| model | cache · context | vision | measured |
|---|---|---|---|
| Qwen3.8-27B Q2_K_XL | Q8 · 64k | **on GPU** | **12.96 GB** |
| Qwen3.8-27B IQ3_S | Q8 · 48k | on processor | 13.01 GB |
| Qwen3.8-27B IQ3_S | Q8 · 64k | on processor | 13.62 GB |
| Qwen3.8-27B Q2_K_XL | Q4 · 192k | on processor | 13.73 GB |
| Qwen3.8-27B IQ3_S | Q4 · 128k | on processor | 14.05 GB |
| Qwen3.8-27B IQ3_S | Q8 keys / Q4 values · 96k | on processor | 14.08 GB |
| Qwen3.8-27B Q2_K_XL | Q8 · 96k | **on GPU** | 14.19 GB |
| Qwen3.8-27B Q2_K_XL | Q8 · 128k | on processor | 14.31 GB |

Before this release a 16 GB card was offered the weakest quant at 64k or 48k, and
in both the vision projector had to sit on the processor - so looking at a
screenshot was slow, on the card where computer control matters most. Two findings
opened it up:

**Quantising only the value half of the cache is worth a gigabyte and costs no
speed.** IQ3_S at 128k needs 16.05 GB with a full Q8 cache and 15.04 GB with Q8
keys and Q4 values. Across twelve combinations, reading stayed between 2787 and
3101 tokens a second and generating between 85 and 96 - the type of cache changed
nothing measurable. Keys and values are separate settings now, because values
tolerate quantisation far better than keys.

**Two bits buys the projector back.** Q2_K_XL is 2 GB smaller than the IQ3_S in
use, which is enough to keep vision on the card *and* have 96k of context -
something a 16 GB card could not have at all before.

### Two decisions made on purpose

**Q2 is offered but never chosen for you.** A two-bit 27B model is a real drop in
quality, worst on code and on following instructions exactly, and that trade is
yours to make. A 16 GB card still starts on IQ3_S at 64k.

**A reduced value cache is never the default either.** What a 4-bit cache costs is
recall over a long conversation, and nothing here measures that - so nothing here
turns it on for you.

What these numbers do not say: speed was measured on a 5090. On a 4060 Ti, a
128-bit bus at roughly 288 GB/s against the 5090's ~1800, expect a fraction of the
tokens per second recorded here. That is reasoning from the hardware, not a
measurement.

---

## The context figure is now measured, not guessed

The number beside the composer disagreed with the server's own: 132k against
144k. It was a character estimate at 3.6 characters per token and 1400 tokens per
picture. Measured against what the server actually counted: **3.20 characters per
token** - Czech prose and JSON tool output both tokenise worse than English - and
**about 2,580 tokens per screenshot**. Both errors ran the same way, so Marvin
believed the context was emptier than it was, by 11% and 17% in two conversations.

That was not only a confusing display. Compression fires at 85% of the estimate,
which at a 17% undercount is **102% of the real limit** - the margin was gone.

The estimate now corrects itself against the server's count after every reply, so
a conversation of Czech discussion, one of Python and one of screenshots each
settle on their own ratio. Verified against a state photographed while it was
happening: 143,860 where the server said 144,074.

## Screenshots stop throwing the conversation away

Three separate causes, each found by measurement and each fixed:

- **Saved memory rewrote the system prompt**, so the first tokens of every request
  changed and the whole conversation was re-read. Memory and skills moved to an
  appended block.
- **The image window was recomputed per request**, breaking the prefix 11 times in
  one session. The decision is now persisted.
- **Pruning charged for nothing.** After a first prune, every later screenshot made
  exactly one picture prunable again, and each rewrote the prompt from that
  picture onwards - some 45k tokens, about fifty seconds - to free 1400. Pruning
  now has to free 5% of the context to earn its rewrite.

Measured afterwards: **327 of 340 requests within a task reuse the prompt**, mostly
at 99%, a tenth of a second each.

Every restart of the model server now records why it happened, because a restart
throws the processed prompt away and the reason used to be unrecorded. And a
25-minute break costs nothing - that was measured too, at 150k tokens: 96 seconds
cold, half a second after the pause.

## Dictation

Speak instead of typing, in Czech or English, running on the processor with
nothing leaving the computer. The model choice, the silence handling and the
language setting were each decided by measurement - including that stating the
language is roughly twice as fast as letting it be detected, at identical
accuracy.

## The model can generate a picture

Off until you turn it on, in Settings → Behavior. It generates through OpenArt on
your account, for credits, using Google Nano Banana 2, OpenAI GPT Image 2.5 and
three others. There is no API key to paste, because OpenArt does not use one: you
sign in through your browser and the credential never reaches Marvin. Pictures are
saved in the current project.

## One interface

The Gradio surface is gone, with its two entry points and its dependency - 75.9 MB
out of every installation. It had not been reachable in normal use for some time.
The React workspace is the only interface.

## Also

- **Search across everything** - conversations, files, memory and decisions - and a
  command palette.
- **A window can be driven without bringing it to the front**, and a program can be
  tested with no window at all.
- **Results holds the results**: every task of the conversation rather than the
  last one, and files produced by a program or a service, not only ones the model
  wrote.
- Toasts appear only when they are the only place the information exists, and
  clear themselves after eight seconds.

## Upgrading

The installer replaces application code only. Conversations, projects, models and
settings are untouched.

## Verification

361 checks in the core suite, 330 unit tests and 13 localization checks, green
before the build. The model figures are recorded in
[profiles-16gb-2026-09-19.md](../design/profiles-16gb-2026-09-19.md) and
[profile-remeasurement-2026-09-15.md](../design/profile-remeasurement-2026-09-15.md),
including what they cannot say.
