# Edge0-145B: research and integration proposal

Research date: 15 November 2026. Baseline: Marvin 1.20.0 (`668c9d3`), which pins Strata 0.1.39.
Status: **proposal**. Nothing was built, downloaded or measured. The owner chose to record the
proposal first; Phase 0 (section 4) has not started and the decisions in section 6 are open.

Edge0-145B is a 145B-parameter model derived from Qwen3.8-Flash-Next, released on 12 November 2026.
This note covers what is known about running it and how Marvin would run it. Figures from Edge0 are
marked as the vendor's; nothing here is a Marvin measurement except the Flash-Next rows in
section 1.5.

## Summary

- **The engine is a fork of Strata.** Edge0-145B runs on `edge0-strata`, a fork of
  [Niko1221/Strata](https://github.com/Niko1221/Strata) with support for Edge0's "latent MoE"
  weights. It keeps Strata's server (`serve/server.py --engine strata --config <json>`) and config
  format. Marvin already runs Flash-Next on Strata (`harness/strata_backend.py`), so the integration
  is a second engine build behind the existing `strata` backend, not a third backend.
- **Speed is not the gain on the owner's PC.** About 100 tok/s is the vendor's figure for 24 GB
  cards. Marvin's Flash-Next already decodes at 110-127 tok/s on the owner's PC and reads prompts
  faster than Edge0 reports. The gain is lower memory need: the vendor reports 37-45 tok/s within
  16 GiB of VRAM and 20 GiB of RAM, where Marvin's Flash-Next IQ3_S measured 13-16 tok/s with 32 GB
  of RAM.
- **Text only.** The released folders hold no vision projector. Flash-Next in Marvin reads images.
- **Three days old.** There is one independent Windows measurement, no independent quality score,
  and open engine bugs on RTX 50 cards.
- **Upstream alternatives do not exist yet.** Upstream Strata does not run Edge0 models and shows no
  plan to. llama.cpp has only a feature request (#29061). Ollama and LM Studio cannot load the files.
- **Proposed order:** measure on the owner's PC with no Marvin changes (Phase 0), then decide.

## 1. What is known

### 1.1 Model

| | |
|---|---|
| Release | 12 November 2026, with Edge0-120B |
| Base model | Qwen/Qwen3.8-Flash-Next (the Hub lists architecture `qwen4exp`, Marvin's `family` for Flash-Next) |
| Architecture | 145B total; 48 layers; 512 experts per layer, 10 routed and 1 shared per token; experts share two projection matrices per layer at latent width 1792 |
| Active parameters | 10.12 B per token on the model card; the folder's `model.json` says 6.6 B |
| Context | 256k trained; the engine template starts at 131,072; int8 KV with a 32k window in VRAM |
| Speculative decoding | A 1.26 B MTP draft head, `--spec 4` |
| Inputs | Text. No projector in either repository; Edge0 does not state modalities |
| Thinking, tool format, sampling | Not documented for this model. The CLI has thinking on by default. The server parses `<tool_call>` with `<function=NAME>` and `<parameter=NAME>`, as for Flash-Next |
| Licenses | Weights: Edge0 Community Model License 1.0 plus the Qwen Community License. Engine fork: MIT. `edge0-infer`: Apache-2.0 |

### 1.2 Engine and processes

- **`edge0-strata`** was imported from a Strata fork at `f1933b1`; its merge base with upstream is
  `c62d5e3` (31 October 2026). Users report it as engine 0.1.55. Upstream is at 0.1.59 (app v0.2.13,
  9 November). The fork removed the desktop app, packaging, Docker and SYCL and kept `serve/`,
  `tools/` and the docs.
- **`edge0-infer`** is Edge0's own runner. For 145B it only delegates:
  `edge0-infer serve --model <folder>` starts
  `<edge0-strata>\.venv\Scripts\python.exe serve/server.py --engine strata --config <file> --host 127.0.0.1 --port 0 --ready-file <file>`
  and proxies it on port 8000. It forwards `/v1/chat/completions`, `/v1/messages`, `/metrics` and
  `/props`; `/slots` and `/unload` are not listed, and the engine's own output is hidden.
- **Direct launch works.** The model folder's `start.sh` runs
  `serve/server.py --engine strata --config ./model.json --port N` without `edge0-infer`.
- **Requirements:** Windows or Linux, an NVIDIA GPU of compute capability 7.5 or newer, CUDA 13.
  The release notes name 16 GiB of VRAM and 20 GiB of RAM; the model page calls those test limits,
  not a minimum. Upstream's install guide says the CUDA 13 packages need driver 580 or newer.
- **Windows binaries:** release v0.2.0 has `edge0-chat-0.2.0-windows-x64.zip` (264 MB, SHA-256
  `c7146b76d51c7986723b81a3643893e1ccbb09ce4f365a5090dc99e476bb31b9`). Its contents are not
  documented, and the repository holds no Windows packaging script. Whether it carries a ready
  `strata.exe` is **not confirmed**; two issue reporters built the engine from source.
- **Source build:** Visual Studio 2022 with the C++ workload (CUDA 13.0-13.2 require VS 2022),
  CUDA Toolkit 13, CMake 3.24 or newer, Ninja, Python 3.10 or newer and uv. ggml comes from
  llama.cpp at `3cf0325`, the commit Marvin already pins for gguf-py. Output: `build\strata.exe`.

### 1.3 Model files

`Edge0/Edge0-145B-q3k` at `2d80116` (105 GB) and `Edge0/Edge0-145B-NVFP4` at `cf9b367` (113 GB).
The folder is already a Strata pack: there is no packing step and no separate MTP download.

| File (Q3_K) | Size | Role |
|---|---:|---|
| `ple-fp8.gguf` | 51.2 GB | n-gram embedding table, read from the SSD (`--ple-io direct`) |
| `experts.bin` | 40.1 GB | the experts (47.6 GB in NVFP4) |
| `model-skeleton.gguf` | 5.99 GB | attention, routing, shared experts, embeddings, output |
| `latent_dense_q8.bin` | 3.74 GB | per-layer projections at 8 bits (the default) |
| `latent_dense_q4.bin` | 1.98 GB | the same at 4 bits; needed only for `du=q4` |
| `dense.bin` | 1.54 GB | rest of the pack |
| `profile.bin`, `labels.bin`, `index.txt`, `native_experts.txt`, `model.json` | small | expert ranking, labels, pack index |
| `mtp/`, `scales/`, `tokenizer/` | not listed | draft layer, Q3_K scales, tokenizer |

The engine may write `mtp-q2_0.gguf` into the folder on the first start, so the folder must be
writable. Edge0's docs tie that step to the Metal build; on Windows it is unverified.

### 1.4 Engine arguments

The template `edge0-strata/edge0/models/edge0-145b.json` differs from what `strata_backend.engine_args`
writes for Flash-Next in four ways: `--native-dense-gguf`, `--ple-io`, an `env` block, and the expert
profile living in the model folder.

```
--pack <dir> --native <dir>/model-skeleton.gguf --native-dense-gguf <dir>/model-skeleton.gguf
--ple-gguf <dir>/ple-fp8.gguf --ple-io direct --expert-profile <dir>/profile.bin
--expert-cache auto --prefill auto --spec 4 --spec-min-p 0.5 --mtp <dir>/mtp
--max-context 131072 --kv int8
```

```
STRATA_LATENT_A=<dir>/experts.bin          STRATA_LATENT_LABELS=<dir>/labels.bin
STRATA_LATENT_DENSE=<dir>/latent_dense_q8.bin   STRATA_LATENT_DENSE_FMT=8
STRATA_LAT_FUSED_Q3K=1 (0 for NVFP4)       STRATA_EMBED_VRAM=1
STRATA_LATENT_FUSED=1   STRATA_LATENT_FUSED_DU=1   STRATA_LATENT_U_GPU=1
```

The folder's own `model.json` adds
`--kv-resident 32768 --vram-reserve-mib 700 --pool-workers 24 --pcie-frac 0.1 --pcie-mode dma`.
The two `--pcie-*` options are not documented anywhere. Memory options match Strata's:
`--resident-budget-gib N` (needs the static profile), `--resident-experts`, `--mmap-experts`,
`--conversation-cache-mib N`.

### 1.5 Speed and memory evidence

| Configuration | Edge0-145B Q3_K | Flash-Next IQ3_S in Marvin (7 October qualification) |
|---|---|---|
| 32 GB card, 64 GB RAM | not measured by anyone | 110.3 tok/s at 256k, 127.5 at 128k; prompt read about 6,000 tok/s |
| 24 GB card, enough RAM | vendor, RTX 5090 D 24 GB: 99.7 chat, 121.2 agent; RTX 4090: 69.9 and 91.7 | 91.7 (256k), 102.7 (128k) |
| RTX 4090, 64 GB RAM, Windows | independent (issue #208): 61.3 chat, 75.3 agent | not applicable |
| 16 GB of VRAM, little RAM | vendor, a 5090 D capped at 16 GiB and 20 GiB RAM: 36.8 chat, 44.9 agent | 32 GB RAM, 16 GB card: 13.4-15.8 (IQ2_XS: 31.8-36.3) |
| Prompt read | vendor: 2,170 (4k) and 3,555 (16k) tok/s on 24 GB; 249 and 335 on the 16 GiB limit | 6,034 tok/s at 256k on the owner's PC |

- **Vendor conditions are mostly unstated:** OS, reasoning, output length and context for the speed
  rows, and what "chat decode" and "agent decode" mean.
- **Memory, vendor:** 23.14 GiB of VRAM plus 31.28 GiB of RAM on the 24 GB card with residency on;
  29 GB peak on a 48 GB MacBook Pro in the announcement.
- **Memory, independent (issue #208, RTX 4090, 64 GB, Windows):** the default arena committed
  78.70 GiB on 63.91 GiB of RAM; the page file peaked at 39 GB and the PC froze. `--mmap-experts`
  cut the commit to 37.64 GiB and the 4k prompt read to 1,358 tok/s. The maintainer puts the model
  at about 46 GiB at 64k and recommends `--resident-budget-gib 40` with the static profile.
- **A community port to another engine** (`infosave/Edge0-145B-cmf`, Linux, RTX PRO 6000 with VRAM
  held back to simulate smaller cards) reports 102-110 tok/s at 32 GB, 78-81 at 24 GB, 50 at 16 GB
  and 36 at 12 GB. It is a different engine and says nothing about `edge0-strata` on Windows.
- **Quality, vendor only:** mean of six benchmarks 72.8 against 71.7 for Flash-Next; DeepSWE 1.1
  64.6 against 58.7; Terminal-Bench 2.1 86.5 against 83.3; slightly lower on HLE, GPQA-Diamond and
  IFBench. No Artificial Analysis Intelligence Index was found. One Hugging Face user reports it
  weaker than Flash-Next on a configuration task.
- **Open engine issues:** corrupted short prompts on an RTX 5070 Ti (#206), an NVFP4 prompt-read
  hang on an RTX PRO 6000 (#200), an abort on an RTX 5080 behind a Smart App Control report (#207),
  and two-card modes that fail. Edge0 says its build runs the model on a 5090 D.

### 1.6 Server compared with what Marvin uses on Strata 0.1.39

Read from the fork's copy of Strata's docs; each row is to be confirmed in Phase 0.

| What Marvin uses | Strata 0.1.39 | `edge0-strata` | Consequence |
|---|---|---|---|
| Readiness (`strata_backend.ready`) | port closed while loading; `/health` has `loaded` and `service: "strata"` | `loaded` documented; `service` value and the closed port not documented; a `--lazy` start exists | Confirm both before reusing the probe |
| Stop | `POST /unload` | documented; answers 409 while a request runs, `?wait=1` waits | Marvin stops after cancelling; check the 409 case |
| Stall probe | `/slots` | documented | Compatible |
| Prompt-read progress | polled from `/metrics` `live.*` | `live.*` not found in the docs; `"return_progress": true` adds llama.cpp's `prompt_progress`, one update per prompt chunk | Use the stream, as for llama.cpp models |
| Malformed tool call | SSE error, retried silently | "Only a declared tool's call is ever recovered; anything else stays text" | The call may arrive as text instead of an error; measure and adjust the retry |
| `effort_position: "end"` | config key | documented | Compatible |
| Images | `vision` config entry | the entry exists in the server; the model has no projector | Text only |
| Determinism | not deterministic by default | "Identical requests at temperature 0 can produce different answers" | Qualification compares by checks |

## 2. Integration design

### 2.1 Principles

1. **`BACKENDS` stays `("llama", "strata")`.** The process chain, identity check, readiness, stop,
   memory guard, recovery and client behaviour are Strata's. A model's `strata` block names which
   engine build serves it.
2. **Flash-Next stays byte-identical.** Tests pin its generated config and argv before the refactor
   and must pass unchanged afterwards, as the llama golden tests did for the Strata work.
3. **The engine stays invisible** (owner, 6 October 2026): model and profile names only, the usual
   download, verify, prepare and load phases, the same STOP, steering and recovery.
4. **Marvin launches the server itself.** `edge0-infer serve` would add a proxy that hides the
   engine log and does not list `/unload` or `/slots`. Its template and `edge0/CONTRACT` (version 5)
   are the reference for what Marvin writes.
5. **Profiles come from measurement** on the owner's PC, under a new measurement ID.

### 2.2 Changes by file

- **`harness/model_catalog.py`, `harness/config.py`:** an `EDGE0_145B` entry with `backend: "strata"`,
  the pinned repository revision, assets with sizes and SHA-256, `vision: False`,
  `uses_system_ram: True`, Flash-Next's sampling until measured otherwise, and a `strata` block with
  `engine: "edge0"`, `layout: "latent"`, `kv`, `spec`, `spec_min_p`, `du`, `ple_io` and
  `vram_reserve_mib`. New path `paths.strata_edge0_dir` (default `runtime/strata-edge0`); the model
  folder goes under `paths.strata_data_dir`.
- **`harness/strata_backend.py`:** `program_dir`, `python_exe`, `server_script`, `engine_exe`,
  `lib_dirs` and `runtime_problems` take the model key and resolve its engine's folder
  (`build\strata.exe` for this engine). `engine_args` gains the latent layout of section 1.4;
  `build_config` writes the `env` block and `gpus_asked` and no `vision` entry; `model_problems`
  checks the latent folder's files. `owns_process` already compares the interpreter, script, config
  and port, so it works once the paths are per model.
- **`harness/strata_runtime.py`:** a second pinned engine staged under its own candidates folder and
  swapped in with the previous one kept: Edge0's source at a pinned commit (only `edge0-strata/`),
  the engine binary, and a hashed lock for its `requirements.txt`. `prepare_model` only verifies this
  model's folder. Where the binary comes from depends on Phase 0 (section 5).
- **`harness/measured_profiles.py`:** a 256k and a 128k profile per RAM and GPU class through
  `strata_menu`, with modes mapped to `--resident-budget-gib`, `--mmap-experts` and
  `--kv-resident 32768`, and a fixed `expert_cache` on the smaller cards.
- **`harness/llm.py`:** prompt-read progress from the stream for this engine. `max_tokens: -1`, the
  overflow pattern and the tool-call retry stay, adjusted to what Phase 0 shows.
- **`harness/servermgmt.py`:** the dispatch is unchanged. The memory markers and the RAM guard's
  count of mapped GGUF pages are checked against this engine's log and its 51 GB mapped table.
- **`harness/web_api.py`, locales, manuals:** the picker entry, its download size and RAM need, and
  one manual section in English and Czech. Images in a chat behave as on Nemotron, the existing
  text-only model.

### 2.3 Alternatives considered

- **Through `edge0-infer serve`:** the vendor's supported path, but a proxy without a documented
  stop or stall probe. Not proposed.
- **Wait for upstream Strata:** one engine for both models would be the cleanest result. Upstream
  has no issue, pull request or roadmap note for it; its 0.2.13 notes mention only "Qwen4
  groundwork".
- **Run Flash-Next on the fork as well:** it would retire the pinned 0.1.39, but it needs a full
  requalification of Flash-Next on an engine whose maintainers stripped parts of it. Not now.

## 3. Phases and gates

| Phase | Work | Gate |
|---|---|---|
| 0 Feasibility, no Marvin runtime changes | Section 4 | Measured load, prompt read, decode and peak RAM/VRAM on Windows; tool-call success on Marvin's schemas; the rows of section 1.6 confirmed; a comparison with Flash-Next on the same scenarios |
| 1 Safety net | Golden config and argv tests for the two Flash-Next entries | Full unit suite green, no behaviour change |
| 2 Backend | Per-model engine folder, latent layout, client progress; the entry hidden until Phase 3 | Golden tests unchanged; new unit tests green |
| 3 Runtime and model | Engine staging, download and verification, picker entry, localization | Clean install and a switch in one chat on the owner's PC; a failed preparation restores the prior model |
| 4 Qualification | Measurement record under `docs/design/measurements/`, profiles, the existing cases, manuals, release notes | All pass on the owner's PC |

## 4. Phase 0 procedure (proposed)

1. **Engine in its own folder** (`%LOCALAPPDATA%\Edge0Eval`). First read the README inside
   `edge0-chat-0.2.0-windows-x64.zip`: if it carries the CUDA engine, use it; otherwise build
   `edge0-strata` from source.
2. **Weights:** `Edge0/Edge0-145B-q3k` to the C: drive (105 GB; 337 GiB are free).
3. **Run** `scripts/edge0_eval.py`, modelled on `scripts/strata_eval.py`, whose `probe` command
   already drives any server URL with Marvin's `LLMClient`, tools and prompts. Scenarios: chat at
   each thinking level, eight tool-call requests with the Development toolset, the e2e coding task,
   a context-filling needle test with a cached follow-up, STOP during the prompt read and during
   decoding; RAM, commit and VRAM sampled every second. Contexts 256k and 128k.
4. **Memory modes:** start with `--resident-budget-gib` and the static profile, never the default
   arena (section 1.5). Then simulate 24 and 16 GB cards with `--vram-reserve-mib` and smaller RAM
   classes, as the Strata qualification did.
5. **Compare** with Flash-Next IQ3_S from the same scenarios on the same day.

**The owner's PC on 15 November 2026:** RTX 5090 32 GB, driver 610.88, 63.7 GiB RAM, Core Ultra 7
265K, a fixed 64 GB page file. It has CUDA Toolkit 12.9 and Visual Studio Build Tools 2019; CMake
and Ninja are not on PATH; uv and Git are present. A source build therefore needs VS 2022 Build
Tools, CUDA Toolkit 13, CMake and Ninja first. A prebuilt engine might load its CUDA libraries from
NVIDIA's pip wheels, as Marvin's Strata does through `lib_dirs`; that is untested.

## 5. Risks and unknowns

- **No confirmed Windows engine binary.** If the release zip has none, end users cannot be asked to
  build one; Marvin would need a binary from a source Edge0 publishes or one built for Marvin.
- **Memory on Windows.** The one independent report froze a 64 GB PC with default settings.
  Nobody has measured a 32 GB card.
- **Young fork.** Three days after release, with open bugs on RTX 50 cards and no version file.
  It branched from upstream before upstream's 0.2.12 tool-call fixes.
- **Quality is unproven.** Only the vendor's numbers exist, and the technical report is not out.
- **No images.** Offering the model beside Flash-Next keeps image reading available.
- **Undocumented behaviour:** sampling, thinking control, `service` in `/health`, `/metrics`
  `live.*`, and the two `--pcie-*` options.
- **Disk.** 105 GB beside Flash-Next's 85 GB; the two share no files.
- **Conflicts inside Edge0's own material:** active parameters (10.12 B or 6.6 B), the expert
  profile's name (`profile.bin` or `expert-profile.bin`), whether `model.json` arguments are read,
  and the 16 GiB plus 20 GiB figure as a minimum or a test limit.

## 6. Open owner decisions

1. **Whether to run Phase 0.** Recommended: yes, since it changes nothing in Marvin.
2. **Weights:** Q3_K (recommended: faster on 24 GB cards, 7 GiB smaller, quality "about the same"
   per Edge0) or NVFP4.
3. **Beside Flash-Next or instead of it.** Recommended: beside, because of images.
4. **Labels.** Proposed: "Edge0 145B · Q3_K" with profiles "Q8 · 256k" and "Q8 · 128k".
5. **Where the engine binary comes from,** once Phase 0 shows what the release zip contains.

## Sources

Read on 15 November 2026 through page fetches; none of it was reproduced locally.

- Edge0: [announcement](https://edge0.ai/blog/introducing-edge0-145b-frontier-ai-capabilities-on-your-own-computer),
  [repository](https://github.com/Edge0-AI/Edge0), [release v0.2.0](https://github.com/Edge0-AI/Edge0/releases/tag/v0.2.0),
  [`edge0-strata/EDGE0.md`](https://raw.githubusercontent.com/Edge0-AI/Edge0/main/edge0-strata/EDGE0.md),
  [`edge0-infer/docs/edge0-145b.md`](https://raw.githubusercontent.com/Edge0-AI/Edge0/main/edge0-infer/docs/edge0-145b.md),
  [`docs/models/edge0-145b.md`](https://raw.githubusercontent.com/Edge0-AI/Edge0/main/docs/models/edge0-145b.md),
  [issues on 145B](https://github.com/Edge0-AI/Edge0/issues?q=is%3Aissue+145B) (#200, #206, #207, #208, #209).
- Hugging Face: [Edge0-145B-q3k](https://huggingface.co/Edge0/Edge0-145B-q3k),
  [Edge0-145B-NVFP4](https://huggingface.co/Edge0/Edge0-145B-NVFP4) and their discussions,
  [infosave/Edge0-145B-cmf](https://huggingface.co/infosave/Edge0-145B-cmf).
- Upstream: [Niko1221/Strata](https://github.com/Niko1221/Strata) releases and issue #5936,
  [llama.cpp issue #29061](https://github.com/ggml-org/llama.cpp/issues/29061).
- Marvin: [Strata backend design](2026-10-05-strata-backend.md),
  [Strata qualification](strata-qualification-2026-10-07.md), [model watch list](model-watchlist.md).
