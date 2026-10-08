# Marvin 1.19.0 - Qwen3.8-Flash-Next, fast and on smaller PCs

**Flash-Next is now one of Marvin's fastest models instead of its slowest.** On
an RTX 5090 with 64 GB of RAM it answers at about **110 tokens per second** and
reads an input that fills its 256k context in **43 seconds**. The previous build
answered at about 25 tokens per second and needed about 44 minutes for the same
input. A cached follow-up returns in about a second.

**And it is no longer a 32 GB-card, 64 GB-RAM model.** It now runs on NVIDIA
cards with **16, 24 or 32 GB** and on PCs with **32, 48 or 64 GB** of RAM, each
combination with its own measured profile for 256k and 128k of context.

## Two sizes of Flash-Next

- **Qwen 3.8 Flash-Next · IQ3_S** (84.5 GB) keeps the full model's quality. It
  is the one to choose when the PC has 64 GB of RAM, and it still runs with 48
  or 32 GB.
- **Qwen 3.8 Flash-Next · IQ2_XS** (69 GB, about 39 GB beside IQ3_S, with which
  it shares two files) has smaller weights and is two to three times faster on
  PCs with 48 or 32 GB of RAM. It is optional: you pick it knowingly.

Measured speed, short answer and the first answer to a full 256k input:

| IQ3_S | 32 GB card | 24 GB card | 16 GB card |
|---|---|---|---|
| 64 GB RAM | 110 tok/s, 43 s | 92 tok/s, 43 s | 73 tok/s, 49 s |
| 48 GB RAM | 72 tok/s, 56 s | 41 tok/s, 71 s | 25 tok/s, 4.3 min |
| 32 GB RAM | 45 tok/s, 2.9 min | 24 tok/s, 4.7 min | 13 tok/s, 10 min |

IQ2_XS answers at 107-136 tok/s with 64 or 48 GB of RAM on every card, and at
119 / 71 / 32 tok/s with 32 GB of RAM on a 32 / 24 / 16 GB card. The smaller
cards and RAM were simulated on an RTX 5090; a real smaller card can differ.

## Switch, and carry on

Choose Flash-Next in **Model and device** like any other model. The first time,
Marvin prepares everything it needs - the model's engine, the weights, the files
it reads them through and a draft layer that speeds up answers - with the usual
progress, once. After that it starts in 30 to 90 seconds. You can switch to
Flash-Next and back in the middle of a chat: the conversation, its files and
earlier answers carry over.

If memory runs short during a task, Marvin restarts the model at 128k with the
same settings and continues the task.

Updating keeps everything already downloaded: the installer verifies existing
models instead of downloading them again. An update from 1.18 prepares Flash-Next
once more on its first start (about 0.7 GB) and reuses the weights you have.

## Also in this release

- **Agents that go round in circles get told.** The loop warning now also
  notices a repeated cycle of a few different steps, not only one step repeated.
  It stays advice: nothing is stopped.
- **Code review without Git.** In a project folder that is not a Git repository,
  the task's own change journal counts as the review of the changes, so the
  agent no longer tries to tick a step it cannot finish.
- **Memory protection that reads Windows correctly.** Marvin's emergency memory
  guard now counts model files that Windows can drop at any moment as free, so it
  no longer stops a model that is reading part of its weights from the SSD.
- The installer lists both Flash-Next sizes (never checked automatically). The
  Full installer carries Flash-Next's model engine and its packages, so only the
  weights are downloaded; the offline backup carries IQ3_S ready to run and
  stores the shared file once.
