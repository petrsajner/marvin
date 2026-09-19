# Marvin 1.14.1 - pruning stops charging for nothing

19 September 2026. A fix for the screenshot behaviour in 1.14.0 and earlier.

## Why

Taking a screenshot in a long conversation kept dropping the reuse of the
processed prompt, and the request trace added in 1.14.0 named it on the first
reading: an image was being removed from a message the server had already
processed - `was: 87 chars, 1 images / now: 87 chars, 0 images`, four times,
agreeing for 40%, 86%, 87% and 89% of the request.

The harness's own notices had been recording the cause all along:

```
16:00:46   count: 21   context ~135442     <- worth it
16:11:52   count: 1    context ~165616     <- one picture, one rewrite
16:13:04   count: 1    context ~166699     <- one picture, one rewrite
```

The first prune gives up 21 pictures and buys 30k tokens. Only four then remain,
so every later screenshot makes exactly one prunable again, crosses the threshold
again, and rewrites the prompt from that picture onwards: about 45k tokens and
fifty seconds of reprocessing, to free 1400.

## What changed

Pruning now runs only when it would free at least 5% of the context - about seven
pictures. Below that, the conversation is summarised instead, because summarising
is what actually reclaims space at that point. Nothing else about screenshots
changed: they are still kept in full until there is real pressure.

## Verification

372 checks in the core suite and 273 unit tests, green locally before the build.
The tests encode the measured sequence: 21 droppable pictures are pruned, one is
not. The correction, and how the first investigation missed this, are recorded in
[prompt-cache-cost.md](../design/prompt-cache-cost.md).
