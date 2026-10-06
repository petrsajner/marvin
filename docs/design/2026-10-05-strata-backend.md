# Strata as a second inference backend for Qwen3.8-Flash-Next

Research date: 5 October 2026. Baseline: Marvin 1.18.2 (`de6bc00`) and Strata
v0.1.39 ([Niko1221/Strata](https://github.com/Niko1221/Strata) `6f32ec0`).
Status: **design approved for Phase 0** (owner decisions of 6 October 2026 in
section 5). Phase 0 tooling: `scripts/strata_eval.py`.

Strata is a C++/CUDA engine that runs only Qwen3.8-Flash-Next, plus a Python
server with an OpenAI-compatible API. Marvin already runs Flash-Next through
upstream llama.cpp b10935 ([integration record](2026-09-13-qwen38-flash-next-integration.md)).
This note covers two things:

- what Strata needs, and what its published measurements show;
- what Marvin must change to run Flash-Next on Strata without changing how
  every other model behaves.

## Summary

- **Speed.** Strata's published results are far beyond what Marvin measured
  with llama.cpp. They come from a different OS and a different quantization,
  so they are not a controlled comparison (section 1.5):
  - A 122k-token first prompt took Marvin 1,054 s. A comparable prompt on an
    RTX 5090 + Core Ultra 9 285K took Strata about 22 s.
  - Marvin decodes at 27 tok/s. That machine decoded at 165–179 tok/s.
- **Different weight files.** Strata cannot run the Unsloth UD-Q3_K_XL files
  Marvin downloads today. Its GPU expert kernels do not cover K-quant experts,
  and its setup refuses those files by name. Strata needs ISTA-DASLab GSQ-RCO
  files (IQ3_S, IQ3_XXS, IQ2_XS, Q2_0), plus a small extracted MTP pack and a
  BF16 projector.
- **The API is close to what Marvin uses.** Streamed `reasoning_content`,
  incremental `tool_calls`, `usage`, llama-style `timings`, `/slots` and
  `/props` all exist. The differences that matter:
  - `/health` does not signal loading.
  - There is no `prompt_progress` in the stream.
  - A malformed tool call is an SSE error, not text.
  - The reasoning-effort sentence sits at the top of the prompt.
  - Strata's own web page can inject sampling defaults.
- **Marvin has no backend seam.** `harness/servermgmt.py` is written for
  llama-server: process identity, argv, log scanning, recovery placement and
  runtime installation. The design adds a closed two-value `backend` field
  (`llama` | `strata`) and branches at the few places that touch the process.
  Every existing llama path stays byte-identical, and new tests pin it first.
- **Delivery is phased.** First a feasibility run on the owner's PC with no
  Marvin changes. Then safety-net tests. Then the backend branch, runtime
  staging and qualification.

## 1. What Strata is and what it needs

### 1.1 Processes

- **Process chain:**
  `python serve/server.py --engine strata --config <json>` →
  `engine/strata.exe --serve <args>`, plus optional `engine/strata-vision.exe`
  for images (`serve/server.py:454-466`, `1284`).
- **Engine protocol:** the server talks to the engine over a stdin/stdout line
  protocol (`READY`, `STOP`, `QUIT`).
- **Child processes:** the server puts the engine, vision and MCP children in a
  kill-on-close Windows job (`serve/winjob.py:48-74`). The server process itself
  is not in that job and does not watch its parent.
- **Python:** 3.10+ in a private venv. Packages are pinned in
  `requirements.txt`: numpy, jinja2, regex, pyyaml, tqdm, requests, cmake,
  ninja, pillow, psutil.
- **CUDA DLLs:** they come from pip wheels (`nvidia-cublas==13.0.2.14`,
  `nvidia-cuda-runtime==13.0.96`) and reach the engine through the config's
  `lib_dirs` (`setup.py:105`, `serve/server.py:1560-1575`).
- **Configuration:** one JSON file holds the engine `exe`, `args`, `cwd`,
  `tokenizer`, `log`, `lib_dirs`, `port`, `gpu` and a `vision` block.
  `bench/results/2026-09-30-community-rtx-5090/strata-iq2_xs.json` is a complete
  example. Marvin can write this file itself.

### 1.2 Distribution and toolchain

- **Prebuilt engine:** `strata-windows-x64.zip` from the GitHub release `v<version>`
  (`setup.py:101-112`). It contains `strata.exe`, `strata-vision.exe` and
  `BUILD.json`.
- **Driver:** NVIDIA 580 or newer, for CUDA 13.0 (`setup.py:106`).
- **GPU support:** sm_120 (RTX 50) is the default and best-measured architecture
  (`CMakeLists.txt:139-146`).
- **Source build:** a fallback that needs VS 2019/2022 Build Tools and the
  CUDA 13.0 toolkit, which setup installs through winget with a UAC prompt
  (`setup.py:988-997`, `2132-2205`). Marvin ships the pinned prebuilt engine.
  A source build stays available for development and experiments.
- **Release pace:** the project is young and moves fast; v0.1.19 through v0.1.39
  are all listed in `setup.py:118`. Marvin pins one version and upgrades only
  after qualification, the same policy as llama.cpp. Strata's `UPDATE.bat`
  (git pull) is not used.
- **License:** the engine is MIT. Each model's own license applies.

### 1.3 Model files

| Size (setup name) | Download | Experts pinned in RAM | Strata's quality note |
|---|---:|---:|---|
| ISTA GSQ-RCO IQ3_S | 83.6 GB | 50.3 GB | "matches the full model" on the authors' published benchmarks; slowest |
| IQ3_XXS | 75.8 GB | 42.9 GB | better than 2-bit |
| IQ2_XS | 68.0 GB | 35.5 GB | measured on a 5090 (section 1.5) |
| Q2_0 | 66.4 GB | 34.0 GB | fastest |
| Unsloth UD-IQ4_XS | 93.7 GB | 59.5 GB | part read from SSD on 64 GB |
| Unsloth UD-Q4_K_XL | 111.3 GB | 77 GB | experimental, 7–8.5 tok/s on 64 GB |

Sources: `setup.py:122-153`, pinned Hugging Face revisions at `setup.py:65-70`
(ISTA `ed59f92…`).

- **UD-Q3_K_XL is refused:**
  - The `SUPPORTED_GGUFS` message refuses K-quant files other than UD-Q4_K_XL
    (`setup.py:1137-1148`).
  - The gate/up and down expert kernel lists contain no Q3_K or Q6_K
    (`src/kernels/cuda/iq_kernels.cu:525-526`).
  - The engine stops at start with "no GPU kernels" (`src/program/generate.cpp:2001-2012`).
  - So the 90 GB Marvin already holds cannot be reused.
- **Pack:**
  - `tools/iq_pack.py` writes a small pack next to the GGUF: `index.txt`,
    `dense.bin` (~1.4 GB), `native_experts.txt`, `tokenizer/` and
    `conversions.json`. It takes seconds to about 30 s.
  - The GGUF experts are read in place (`--native <shard1>`).
  - Shard 2 is the 28.8 GB PLE table, read lazily from SSD (`--ple-gguf`).
- **MTP draft:** `tools/mtp_fetch.py` range-downloads the 31 `mtp.*` tensors
  (~5 GB) from `Qwen/Qwen3.8-Flash-Next`. Then `mtp_pack.py` and `mtp_rt.py`
  build `mtp/rt/`. **Setup fetches these from `main`**, not from a pinned
  revision. Marvin must pin the revision and record output hashes.
- **Vision:** ISTA's `mmproj-Qwen3.8-Flash-Next-BF16.gguf` (0.9 GB). It runs in
  `strata-vision.exe` and needs about 1.4 GB VRAM on the GPU path.
- **Bundled data:** `data/expert-profile.bin` is a ranking of all 24,576
  (layer, expert) pairs that seeds the GPU expert cache. `data/draft_vocab*.bin`
  are token subsets for the draft head.
- **Low-RAM resident mode** (`--resident-experts`) needs an extra `experts.bin`
  copy, as large as the experts (+43–50 GB of disk).

### 1.4 Resource model on the owner's machine class (32 GB GPU, 64 GB RAM)

- **Placement:**
  - The GPU holds the dense weights, KV (or its hot window), the MTP layer and
    an expert cache. The cache fills free VRAM minus `--vram-reserve-mib`
    (default 700).
  - RAM holds every expert, page-locked: large pages if `SeLockMemoryPrivilege`
    is available, otherwise `cudaHostRegister` or `VirtualLock` on 4 KB pages
    (`src/core/pinned.cu`, `src/platform/memory.cpp`). No administrator rights
    are needed. The Windows page file must be enabled.
- **IQ3_S on 64 GB:**
  - It pins 50.3 GB. Setup marks it "needs a 64 GB PC with little else running"
    (`setup.py:131-133`).
  - The resident low-RAM variant would keep only the experts the GPU does not
    cache in RAM. That is about 27 GB, an **estimate** from the 23.4 GiB cache
    measured with IQ2_XS on a 5090.
  - Either variant must be measured with Marvin, WebView2 and a browser open.
- **Start:**
  - The PC may stall for 1–3 minutes while the pinned arena is filled (first
    start). Later starts take 30–90 s (`docs/INSTALL.md:40-42`,
    `docs/DETAILS.md:345`).
  - A process started at below-normal priority or with a limited token loads
    about 24× slower (`docs/DETAILS.md:372-389`).
- **Context:**
  - The setup default is 131,072 on a 24 GB+ card.
  - From 64k, `--kv-resident 32768` keeps the full KV in RAM (~13.7 KB per token,
    ~3.5 GB at 256k) and only the attention window in VRAM.
  - 262,144 is the trained limit. Above it, YaRN applies. Marvin stays at or
    below 262,144.
  - Strata did not measure IQ3_S at 256k on 64 GB, but users reported that it
    ran (`docs/DETAILS.md:63-67`).
- **CPU:**
  - `--pool-workers` defaults to P-cores plus half of the E-cores
    (`setup.py:375-398`).
  - Marvin's CPU-only embeddings sidecar (llama-server, bge-m3) still runs
    alongside Strata and competes for CPU and RAM.

### 1.5 Published speed evidence

| Measurement | Engine / weights / OS | Prompt | First answer | Decode |
|---|---|---:|---:|---:|
| Marvin, 13 Sep (`qualified-128k`) | llama.cpp b10935, UD-Q3_K_XL, Q8 KV 128k, Windows | 122,397 tok | 1,053.7 s | 27.3 tok/s |
| Marvin, Flash 256k | same, 256k | 253,883 tok | ~44 min | — |
| Strata community, 30 Sep | Strata 0.1.29, IQ2_XS, int8 KV 128k, **Linux** | 128,000 tok | 22.3 s (5,779 tok/s) | 165.0 tok/s |
| same | same | 4,096 tok | 0.97 s | 179.4 tok/s |
| Strata DETAILS | IQ3_S, RTX 5090 (reporter, French text) | — | — | 141–158 tok/s |

Sources: [integration record](2026-09-13-qwen38-flash-next-integration.md)
section 10, [memory profiles](memory-profiles.md),
`bench/results/2026-09-30-community-rtx-5090/README.md` and `docs/DETAILS.md:109-114`
in the Strata checkout.

**Limits of these numbers:**

- The Strata runs used reasoning off, greedy decoding and 256 output tokens, on
  Linux, without vision or tool use in the timed requests.
- Different weights and OS mean this is not a controlled comparison. It
  justifies a feasibility run, not a release claim.
- Marvin measures its own profile on the owner's Windows PC (Phase 0).

### 1.6 API compared with what Marvin uses

| What Marvin uses | llama-server (today) | Strata v0.1.39 | Consequence |
|---|---|---|---|
| `GET /health` for readiness (`servermgmt.py:64`) | 503 while loading | Port closed while loading; then always 200 with `loaded`, `service:"strata"` | Readiness must also require `loaded: true` and `service == "strata"` |
| `/slots` stall probe (`llm.py:250`) | `is_processing` | Single entry with `is_processing` | Compatible |
| Streamed `reasoning_content`, incremental `tool_calls`, `usage`, `timings` | yes | yes, same names | Compatible |
| `stream_options.include_usage` | honored | ignored; usage is always in the final chunk | Compatible |
| `return_progress` → `prompt_progress` (`llm.py:169`) | yes | absent. Only `: keep-alive` SSE comments; live progress in `GET /status` (`prompt_read`, `prompt_total`) | No prefill bar unless Marvin polls `/status` |
| `chat_template_kwargs.enable_thinking` / `reasoning_effort` (`llm.py:33-42`) | Jinja kwargs | honored; default effort is the highest when unspecified | Compatible. The effort sentence sits at the **top** of the system turn unless the config sets `"effort_position": "end"` |
| `reasoning_content` sent back in history (`session.py:153`) | `--reasoning-preserve` | accepted and re-rendered | Compatible; prefix reuse needs qualification |
| Several system messages | rendered | only index 0 stays system; later ones become user turns | Marvin sends one system message at index 0 (`session.py:129`) |
| `tool_call_id` on tool results | used | dropped; results are matched by order | Fine for Marvin's sequential tools |
| Malformed tool-call text | usually returned as text | SSE `error` event, then `[DONE]` (`frontend.py:436`) | The OpenAI SDK raises; today the agent ends with `Status.ERROR` (`agent.py:766-776`). Needs a bounded retry |
| Overflow error text (`agent.py:129`) | `exceed_context_size_error` | "…exceeds the context…" or "…leaves no room to answer in the context…" | The second message does not match `OVERFLOW_RE` |
| Absent `max_tokens`, `seed`, `top_k` | server defaults | filled from `strata-<model>.shared-settings.json` (Strata's web page) | Marvin must own this file (keep it empty) or send every field |
| `stop`, `tool_choice`, `n_probs`, `cache_prompt`, `id_slot` | honored | ignored | Marvin sends none of them |
| `top_k` | any | capped at 64 | Marvin's values are lower |
| Image tokens (`session.py:204`, 2,600 estimate) | llama mmproj, `--image-min-tokens 1024` | ≤1,024 per image by default | Calibration corrects it; make the estimate per-backend |
| Concurrency | `-np 1` | one request at a time (a lock), queued silently | Matches Marvin's single worker |
| Cancel on disconnect | yes | socket watcher every 0.5 s; prefill stops at the next chunk (≤8,192 tokens) | Compatible; measure STOP latency in prefill |
| Prefix cache | slot cache + `--cache-ram` | live session plus up to 6 exact-prefix checkpoints (~118 MB each, RAM only); opt-in `--conversation-cache-mib` | Changing the system turn or the tool list rereads everything; at the published prefill speed that costs seconds, not minutes |

Strata server line references are to `serve/server.py` unless another file is named.

### 1.7 Strata parts Marvin does not use in production

- **`setup.py`.** It is interactive and can install Python with `PrependPath=1`.
  It can also install VS Build Tools and CUDA through winget, opens a browser,
  writes `%APPDATA%\Strata` and a data folder beside its install, and moves
  model files from earlier Strata folders. Marvin performs only the minimal
  steps itself (section 2.7). Phase 0 uses setup non-interactively in its own
  folder, which is simpler for an evaluation.
- **The `parallel` batching mode, the MCP client (`--mcp-config`, `strata_mcp`),
  the MCP server (`tools/strata_mcp.py`) and the experimental speed projection.**
  The first two fall under the single-agent and no-MCP non-goals in
  `AGENTS.md`; the speed projection is experimental. Marvin does not enable or
  send them.
- **Strata's web page and `/settings`.** The server always serves them on its
  port. Marvin binds 127.0.0.1, uses a per-launch API key, and never links the
  page.
- **Image URL and local path inputs.** Marvin sends only `data:` URLs.

## 2. Integration design

### 2.1 Principles

1. **One closed field.** `backend: "llama" | "strata"` on a model entry,
   defaulting to `llama`. It is not a plugin registry. Unknown values are
   rejected.
2. **The llama path stays byte-identical.** Before any refactor, tests pin the
   full llama argv, identity check, readiness, stop and recovery for every
   built-in model (section 2.10). Afterwards those tests must pass unchanged.
3. **Users choose a model and a profile, as for every other model.** The
   Strata entry is a separate Flash-Next model (for example "Qwen3.8 Flash-Next
   IQ3_S"). Its 256k and 128k profiles appear in the same picker as the other
   models' profiles. Runtime and placement stay internal.
4. **One model and one sequential agent.** Starting Strata stops llama-server
   first and the reverse; both use the same `server.port`. The embeddings
   sidecar is CPU-only and unchanged.
5. **Recovery keeps the model, KV precision and placement and lowers only the
   context.** For Strata, placement means the expert-cache size and the VRAM
   reserve. Those are frozen from the failed run (section 2.6).

### 2.2 Model catalog (`harness/model_catalog.py`, `harness/config.py`)

- **Add `FLASH_NEXT_STRATA` beside `FLASH_NEXT_Q3`**, registered in
  `BUILTIN_MODELS` the same way (`config.py:79-81`).
- **Generic fields, unchanged meaning:**
  - `alias`, `family`, `sampling`, `supports_reasoning_effort`, `read_timeout`;
  - `optional_download: True`;
  - `assets` with the pinned ISTA revision `ed59f92…`, the GGUF shards,
    `mmproj-…-BF16.gguf` and SHA-256 values.
- **New `strata` block:**
  - `pack` (output directory name and expected file list);
  - `mtp` (pinned `Qwen/Qwen3.8-Flash-Next` revision and output hashes);
  - `expert_profile`, `kv: "int8"`, `spec: 4`, `spec_min_p: 0.5`;
  - `vision: "gpu"`, `vram_reserve_mib`;
  - `resident_experts` (bool, decided by Phase 0).
- **No llama fields:** no `server_args`, `adaptive_runtime`,
  `minimum_runtime_build` or `layout_hint`. As a result, `runtime_plan`,
  `gguf_metadata.model_memory_layout` and the hard-coded `FLASH_NEXT_Q3`
  fallback in `gpu.fitting_profiles` (`gpu.py:74-90`) never see this entry.
- **Profiles go in `harness/measured_profiles.py`**, the profile authority, with
  new measurement IDs. Each profile holds `ctx_size`, `gpu_class`,
  `min_vram_gb`, `min_ram_gb`, `label` and `measurement_id`, plus a `strata`
  override (for example `kv_resident`). The first profiles come from the
  owner's PC: 256k and 128k on the 32 GB class. Profiles for smaller GPU and RAM
  classes follow from their own measurements (section 3).

### 2.3 Process management (`harness/servermgmt.py`, new `harness/strata_backend.py`)

`servermgmt` keeps its public functions. Each function that touches the process
dispatches once on `cfg.model(key).get("backend", "llama")`:

| Function | llama (unchanged) | strata |
|---|---|---|
| `_start_locked` (`:221`) | current code | verify runtime and pack; write `runtime/strata/strata-<key>.json`; spawn `<strata venv>\python.exe serve\server.py --engine strata --config … --host 127.0.0.1 --port <server.port>` with `STRATA_API_KEY` set, `CREATE_NO_WINDOW`, `cwd=<strata root>`; log to `runtime/strata-server.log` |
| `_managed_process` (`:132`) | `llama-server.exe` name, exe and `--port` | `python.exe` from the Strata venv, argv contains `serve\server.py`, `--config <expected>` and `--port <port>` |
| `wait_health` (`:64`) | 200 | 200 **and** `service == "strata"` **and** `loaded == true`; the process must still be alive |
| `stop` (`:171`) | kill tree | `POST /unload` with the key (engine `QUIT`, GPU freed), then terminate the Python process and kill the tree after a timeout |
| `record_allocation_failure` (`:32`) | llama log markers | Strata markers in `strata-server.log` and `strata-<key>.log` (CUDA out-of-memory, "does not fit", "the engine stopped unexpectedly"), mapped to the existing `vram_pressure` and `ram_pressure` codes |
| `ensure_runtime` (`:268`) | llama b10935 | Strata runtime staging (section 2.7) |

- **Windows job object.** It is new and backend-neutral, but enabled only for
  Strata at first. Marvin assigns the spawned server to its own
  KILL_ON_JOB_CLOSE job, so a crashed `marvin_web` cannot leave 50 GB pinned.
  Nested jobs are supported on Windows 8 and later. Strata's own job still
  covers its children.
- **The 512 MiB RAM guard** (`:349-385`) applies to both backends unchanged.
- **Pinned-arena load stall.** The loading phase must tolerate a 1–3 minute
  stall without treating it as a hang. `HEALTH_TIMEOUT = 900` already covers it.
- **Priority.** The server is spawned at normal priority, never below-normal.
- **Error text.** `ModelSwitchController` keeps its phases. Only the message
  "llama-server could not be prepared" (`model_switch.py:188`) becomes neutral.

### 2.4 Client (`harness/llm.py`, `harness/agent.py`, `harness/session.py`)

1. **API key.** `LLMClient` uses the per-launch key for a Strata model. Today it
   always sends `api_key="local"`.
2. **Effort position.** The generated config sets `"effort_position": "end"`,
   so a per-request effort change does not invalidate the whole prompt. Its
   quality effect is checked in qualification.
3. **Shared settings.** Strata's `shared-settings.json` stays absent or empty
   under Marvin's runtime folder. Marvin also sends `max_tokens` explicitly for
   Strata models, so no web-page default can apply.
4. **Malformed tool call.** An SSE error whose message starts with
   "malformed tool call" becomes one advisory retry, like the overflow path at
   `agent.py:766-773`. The retry is a `CONTINUE` with guidance to repeat the
   call in the documented format, not `Status.ERROR`. It is bounded per task.
5. **Overflow.** Extend `OVERFLOW_RE` with `leaves no room to answer`.
6. **Image estimate.** `IMAGE_TOKENS` becomes per-backend. Strata's value is
   measured; its default cap is 1,024 tokens.
7. **Prefill progress.** Optional, phase 3. While a Strata request is reading
   its prompt, poll `GET /status` about once a second and translate
   `prompt_read`/`prompt_total` into the existing `prompt_progress` callback.
   Without it the UI shows the generic reading state. At the published prefill
   speed this only matters above about 50k new tokens.
8. **Unchanged:** sampling, `chat_template_kwargs`, `reasoning_content`, tool
   accumulation, the `/slots` stall probe, cancel by closing the stream, and
   `usage.prompt_tokens` calibration.

### 2.5 Prompt-cache continuity

- **What Strata reuses:** the live session, when the previous prompt and its
  reply are an exact prefix, or else the longest matching checkpoint.
  Checkpoints are taken at each request's last `<|im_start|>`, every 16,384 new
  tokens, and at the end of a system prompt of 2,048 tokens or more.
- **Summarization and research.** These calls use a different system prompt.
  They displace the live session but not the main chat's checkpoints. The next
  agent step then rereads at most the last turn.
- **Work-mode changes.** These change the tool list in the system turn, so the
  whole prompt is reread. That is acceptable at the published prefill speed.
- **`request_trace`.** It already fingerprints prefixes. For Strata it also
  records `timings.cache_n` against `prompt_n`, so qualification can show the
  real reuse.

### 2.6 Profiles, memory and recovery

- **Planning compares with installed physical RAM**, as the current Flash
  planner does ([memory profiles](memory-profiles.md)):
  - the pinned experts (all of them, or only the non-cached ones in resident
    mode);
  - plus the KV RAM share;
  - plus the measured residual.

  Each profile records `min_ram_gb` from measurement, never from a blanket
  reserve.
- **Recovery ladder:**
  - It keeps the same pack, `int8` KV and vision placement, and moves only to
    the next lower measured context (256k → 192k → 128k).
  - Before restart, the frozen placement replaces `--expert-cache auto` with
    the slot count the failed run logged, and keeps `--vram-reserve-mib`.
    Freed VRAM is not refilled with experts.
  - MTP is integral to every Strata profile, so this ladder has no MTP-off step
    of its own.
- **`gpu.fitting_profiles` and `best_fit`** read `min_vram_gb`/`gpu_class` as
  today. The `adaptive_runtime` branch is not taken.

### 2.7 Runtime and model preparation (new `harness/strata_runtime.py`, mirrors `harness/runtime_update.py`)

- **Pinned inputs:**
  - the Strata source tag archive (only `serve/`, `tools/`, `data/` and `LICENSE`
    are used);
  - `strata-windows-x64.zip`;
  - a hashed wheel lock `requirements-strata-py312.lock`, which includes the
    two NVIDIA wheels.

  Each input has a SHA-256 value.
- **Staging:**
  - Stage into `runtime/strata-candidates/<version>/` and create the venv from
    the Python 3.12 Marvin already uses: `runtime/python` in Full, the required
    system 3.12 in Minimal. There is no winget, PATH change, source build or
    `%APPDATA%` write.
  - Validate: `BUILD.json` version, `strata.exe` device probe, driver ≥ 580 from
    `nvidia-smi`.
  - Activate by rename, keeping `strata-previous-<ns>` as `runtime_update.py`
    does.
- **Model preparation.** It runs only after the explicit model selection,
  through the existing download, verify and progress UI:
  1. GGUF shards and the projector, using the existing ranged download and the
     `.marvin-verified.json` receipts (`harness/model_files.py`).
  2. `iq_pack.py`, which writes the pack with its own receipt.
  3. `mtp_fetch.py` at the pinned revision, then `mtp_pack.py` and `mtp_rt.py`;
     outputs are hash-checked.
  4. Optionally the resident `experts.bin`, if Phase 0 selects that variant.
  - Each step is resumable. A failure never deletes user data, never touches the
    llama runtime and restores the previous model, as now.
- **Paths:** `runtime/models/strata/<pack>/…` and `runtime/strata/…`, never a
  folder beside the installation.

### 2.8 UI, web API and localization

- **`web_api.py:107-116`:**
  - `vision` comes from an explicit capability rather than `bool(mmproj)`; for
    Strata the projector is still an asset.
  - `uses_system_ram` comes from a profile field instead of grepping
    `--n-cpu-moe`.
  - Raw `server_args` stop being sent for Strata profiles.
- **Picker and status:**
  - The picker shows the new model with its download size and RAM need.
  - Model status shows the existing phases, plus a short "preparing model
    files" phase for packing.
  - Diagnostics show the backend and engine version; the main UI does not.
- **Speed display.** `timings.predicted_per_second` can replace the client-side
  character estimate for both backends. This is optional.
- **Strings** go to `harness/locales/` (English plus `cs.json`). Run
  `python -m unittest tests.test_localization`.

### 2.9 Launcher, installer, backups

- **Launcher.** It still requires `llama-server.exe`, because the embeddings
  sidecar and the other models need it. It must also stop Strata on exit
  through the same `scripts/server.py stop` path (`launcher/launcher_app.py:436-442`).
- **Full/offline installer and `scripts/offline_backup.py`.** They include
  `runtime/strata` only when it is installed. Model packs follow the existing
  model backup rules.
- **The user manuals (EN/CS)** gain one section on the new Flash-Next model:
  - what it needs;
  - the first-start stall;
  - disk use;
  - that the llama Flash-Next entry remains available.

### 2.10 Tests

- **Before the refactor** (new; current tests do not assert the full llama argv):
  - a golden argv for every built-in model and profile, including Flash adaptive
    and MTP;
  - the identity check, readiness, stop and recovery placement.
- **Strata unit tests:**
  - config and argv generation;
  - the identity check on a fake `python.exe` process;
  - readiness on `loaded`;
  - the stop sequence;
  - log failure classification from captured Strata log fixtures;
  - profile fitting and recovery freezing;
  - malformed-tool-call retry;
  - overflow text;
  - an `httpx.MockTransport` replay of a real captured Strata SSE stream
    (reasoning, tool calls, usage, timings, error event).
- **Live GPU scripts** next to the existing ones:
  - `tests/check_strata_memory.py`, `tests/check_strata_prompt_performance.py`;
  - `tests/e2e_model_switch.py` extended to switch llama Q5 → Strata → llama
    Flash → Q5.

## 3. Delivery phases and gates

| Phase | Work | Gate |
|---|---|---|
| 0 Feasibility (no Marvin runtime changes) | `scripts/strata_eval.py` (section 6): Strata v0.1.39 in its own folder, IQ3_S at 256k and 128k, normal and resident, with vision, driven by Marvin's client, prompts and tools. | Measured load, prefill and decode on Windows. Peak RAM/VRAM with Marvin and a browser open. Tool-call success on Marvin's schemas. Choice between the normal and resident variants. |
| 1 Safety net | Golden llama tests (section 2.10). No behavior change. | Full unit suite green. |
| 2 Backend seam | `backend` field, `servermgmt` dispatch, `strata_backend.py`, client changes, job object. The Strata entry is hidden behind a config flag. | Golden tests unchanged; Strata unit tests green. |
| 3 Runtime and models | `strata_runtime.py` staging, pack/MTP preparation, picker entry, status, localization, optional progress polling. | Clean install and switch on the owner's PC; failed preparation restores the prior model. |
| 4 Qualification | New measurement record under `docs/design/measurements/`; profiles in `measured_profiles.py`. Existing 55 cases are reused unchanged. Chat, thinking levels, tool rounds, images, long input at each offered context, STOP and steering, compression, model switches both ways, low-memory recovery. Then the configurations for smaller GPU and RAM classes. | All pass on the owner's PC; release notes; manuals; the Strata entry replaces the llama.cpp Flash-Next entry. |

The complete measurement matrix is not repeated for existing models. Only the
new Strata profiles are measured, because they are new weights and a new runtime.

## 4. Risks

- **Young upstream with frequent releases.** Pin it, qualify upgrades, and keep
  the llama Flash entry as a fallback.
- **Pinned RAM on a 64 GB desktop.** The IQ3_S normal mode leaves about 12 GB
  for Windows, Marvin, WebView2 and the browser. This is the main Phase 0
  question.
- **Tool-call robustness.** Parsing accepts only the Qwen XML format, with no
  grammar. Malformed output fails the request, and section 2.4 adds a bounded
  retry. Measure the failure rate on Marvin's real tools.
- **Run-to-run determinism.** IQ kernels and expert-cache adaptation are not
  deterministic by default (`docs/DETAILS.md:87-95`). This does not matter for
  use, but qualification compares outputs by checks, not byte equality.
- **Disk.** IQ3_S needs 83.6 GB, plus ~6 GB MTP, plus 0.9 GB projector, plus
  optionally 50 GB `experts.bin`. That is in addition to the 90 GB llama
  Flash-Next files, unless the owner retires them.

## 5. Owner decisions (6 October 2026)

1. **No inherited restrictions.** The "binding requirements" in the
   [September 13 integration record](2026-09-13-qwen38-flash-next-integration.md)
   were never the owner's requirements: no upstream-only rule, no fixed
   UD-Q3_K_XL target, no fixed Q8_0 KV. That record is historical.
2. **Weights:** start with ISTA GSQ-RCO IQ3_S.
3. **Context:** both 256k and 128k, switchable in the picker like the other
   models' profiles.
4. **llama.cpp Flash-Next:** it stays until the Strata entry is working and
   tested, then the Strata entry replaces it.
5. **Scope:** first get the most out of the owner's PC (RTX 5090 32 GB, 64 GB
   RAM). Then measure which configurations to offer on smaller machines; the
   community runs Strata on 12 GB cards.

## 6. Phase 0 procedure

Phase 0 does not touch Marvin's runtime, models or settings. It uses
`scripts/strata_eval.py` from a Marvin checkout, run with Marvin's Python.

1. **Stop Marvin's model** in the UI, or close Marvin. The script refuses to run
   beside a main llama-server; the CPU embeddings sidecar is ignored.
2. **Install.** `python scripts/strata_eval.py install` installs Strata
   v0.1.39 into `%LOCALAPPDATA%\StrataEval`. It runs Strata's own setup
   non-interactively:
   - IQ3_S, int8 KV, 256k, GPU vision, all experts in RAM, port 18080, no
     browser;
   - it downloads ~84 GB of weights, the MTP tensors and the projector;
   - a rerun resumes.

   `install --low-ram resident` then adds the resident variant, which writes an
   extra ~50 GB `experts.bin`.
3. **Run.** `python scripts/strata_eval.py run --context 262144` and
   `run --context 131072`, each optionally with `--base resident`. Each run:
   - derives a config from the installed one and starts the server;
   - measures load time and samples RAM, server RSS and VRAM every second;
   - runs these scenarios through Marvin's own `LLMClient`, tools and prompts:
     - chat at thinking off/low/high;
     - image reading;
     - eight tool-call requests with the full Development toolset;
     - the e2e coding workflow agent task;
     - a needle test filling the context, plus a cached follow-up;
     - STOP during prefill and during decode.
   - `--effort-end` repeats a run with the effort sentence at the prompt's end.
4. **Report.** `python scripts/strata_eval.py report` writes `summary.md` from
   every run. Each run folder keeps `results.json`, `samples.json`, the engine
   log and the exact config.

**Checked before handing over (Linux, no GPU), against Strata's own server with
its scripted mock engine:**

- Marvin's `LLMClient` received separated reasoning, streamed XML tool calls as
  OpenAI `tool_calls`, and `usage`.
- A Hermes-style JSON tool call came back as `APIError: malformed tool call`,
  confirming the retry need in section 2.4.
- Marvin's real `Agent` completed a two-turn `read_file` task.

The mock has no clock or vision, so speed, timings and images need the real
engine.
