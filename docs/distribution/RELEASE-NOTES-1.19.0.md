# Marvin 1.19.0 - Qwen3.8-Flash-Next, fast and on smaller PCs

## Highlights

- **Qwen 3.8 Flash-Next is several times faster.** On the same PC (RTX 5090,
  64 GB of RAM) it answers at **110-155 tokens per second instead of about 25**
  (4-6× faster) and reads long input **50-60× faster**: a full 256k context in
  **43 seconds instead of about 44 minutes**. A cached follow-up returns in
  about a second.
- **Flash-Next now runs on 24 GB and 16 GB cards**, and on PCs with 48 or 32 GB
  of RAM. Until now it needed a 32 GB card and 64 GB of RAM.
- **Smaller fixes:** one answer per task instead of a report followed by a
  second summary of the same thing, a loop warning that notices repeated
  cycles, code review without Git, and a memory guard that reads Windows
  correctly.

## Flash-Next: sizes and speed

- **Qwen 3.8 Flash-Next · IQ3_S** (84.5 GB) keeps the full model's quality. It
  is the one to choose when the PC has 64 GB of RAM, and it still runs with 48
  or 32 GB.
- **Qwen 3.8 Flash-Next · IQ2_XS** (69 GB, about 39 GB beside IQ3_S, with which
  it shares two files) has smaller weights and is two to three times faster on
  PCs with 48 or 32 GB of RAM. It is optional: you pick it knowingly.

| RAM | Card | IQ3_S answers | IQ3_S reads 256k | IQ2_XS answers | IQ2_XS reads 256k |
|---:|---:|---:|---:|---:|---:|
| 64 GB | 32 GB | **110 tok/s** | **43 s** | 107 tok/s | 45 s |
| 64 GB | 24 GB | 92 tok/s | 43 s | 132 tok/s | 44 s |
| 64 GB | 16 GB | 73 tok/s | 49 s | 115 tok/s | 47 s |
| 48 GB | 32 GB | 72 tok/s | 56 s | 114 tok/s | 44 s |
| 48 GB | 24 GB | 41 tok/s | 71 s | 136 tok/s | 44 s |
| 48 GB | 16 GB | 25 tok/s | 4.3 min | 88 tok/s | 49 s |
| 32 GB | 32 GB | 45 tok/s | 2.9 min | 119 tok/s | 48 s |
| 32 GB | 24 GB | 24 tok/s | 4.7 min | 71 tok/s | 77 s |
| 32 GB | 16 GB | 13 tok/s | 10 min | 32 tok/s | 3.9 min |
| *1.18: 64 GB* | *32 GB* | *about 25 tok/s* | *about 44 min* | | |

*Answers* is the speed of a short answer with thinking off. *Reads 256k* is the
time to the first answer for an input that fills the whole 256k context. Every
combination also has a 128k profile, which answers as fast or faster and reads
its full context in about half the time. Smaller cards and RAM were simulated on
an RTX 5090; a real smaller card can differ. 48 and 96 GB cards use the 32 GB
card's profiles (estimated, not measured).

## How smart is it

Artificial Analysis Intelligence Index, October 2026, higher is better. The two
models in bold run on your own PC in Marvin.

| Model | Index | | In Marvin |
|---|---:|---|:---:|
| Claude Opus 5.5 | 58 | ██████████████▌ | |
| Claude Sonnet 5.5 | 56 | ██████████████ | |
| Gemini 4 Argon ¹ | 53 | █████████████▎ | |
| GPT-6.1 Sol | 52 | █████████████ | |
| Grok 4.7 | 46 | ███████████▌ | |
| Qwen 3.8 Max | 45 | ███████████▎ | |
| GLM-5.3 | 45 | ███████████▎ | |
| Claude Haiku 5.5 | 43 | ██████████▊ | |
| GLM-5.3-Flash | 42 | ██████████▌ | |
| Gemini 3.8 Flash | 41 | ██████████▎ | |
| **Qwen 3.8 Flash-Next** | **40** | ██████████ | **yes** |
| DeepSeek V4.1 Flash | 39 | █████████▊ | |
| GPT-6 Luna | 38 | █████████▌ | |
| **Qwen 3.8 27B** | **34** | ████████▌ | **yes** |
| MiniMax-M3 | 29 | ███████▎ | |
| Nemotron 3 Ultra | 23 | █████▊ | |

Flash-Next on your own PC scores level with Gemini 3.8 Flash, just below Claude
Haiku 5.5 and above DeepSeek V4.1 Flash and GPT-6 Luna. The scores are measured
on the original models; Marvin runs them with quantized local weights, which can
score somewhat lower. ¹ Not publicly available. Source:
[artificialanalysis.ai](https://artificialanalysis.ai).

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

- **One answer per task.** A research task now ends with the model's own report
  instead of the report followed by a second summary of the same findings, and
  the closing summary of changes appears only when the task changed files.
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
