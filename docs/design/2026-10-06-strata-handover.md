# Strata backend: session handover (6 October 2026)

This note lets a new session continue the Strata work without the earlier conversation.

- **Where the work happens:** on `main`, in the owner's home PC checkout
  (`E:\QWEN local`, RTX 5090 32 GB, 64 GB RAM). Tests, Phase 0 runs and the
  real engine all run there. The study branch `claude/gracious-archimedes-k0spl5`
  was fast-forwarded into `main` on 6 October and is no longer used.
- **Commits** (on `main`, after 1.18.2 `de6bc00`):
  - `a088fb8` adds the design note;
  - `b0fd45d` adds the Phase 0 script and records the owner's decisions;
  - `23c2362` adds this note;
  - `2d612de` Phase 1 (golden llama tests);
  - `4fc0bd5` Phase 2 (backend seam).
- **Git:** commit locally; push once a piece of work is finished and verified
  locally (GitHub is billed). No pull requests.

## The owner's requirement for the whole work (6 October 2026)

Switching to the Strata model must work exactly like switching models today:
pick it, keep working in the same chat. The user must not notice that more than
the model changed. So:

- nothing the user sees names an engine (names, labels, status, notices,
  errors); logs and diagnostics may;
- the same switch phases, STOP, steering, recovery and prefill indicator;
- Strata's preparation (engine, venv, pack, MTP) runs inside the normal
  download and prepare flow (Phase 3), never as manual steps;
- an existing chat continues on the new engine.

Ask the owner (AskUserQuestion, with a recommendation) before any choice that
changes what the user sees or departs from the design.

## Read first

1. `docs/design/2026-10-05-strata-backend.md`. It is the full design:
   - Strata's build, model files, resources, measured speed and API differences;
   - the integration design;
   - the phases;
   - the owner's decisions;
   - the Phase 0 procedure.
2. `AGENTS.md`. Its product invariants still apply: single sequential agent,
   no MCP or plugin host, measured profiles in `harness/measured_profiles.py`,
   recovery lowers only the context.
3. `scripts/strata_eval.py`, the Phase 0 tool.

## Goal

Add Strata ([Niko1221/Strata](https://github.com/Niko1221/Strata), pinned
v0.1.39 = `6f32ec070f23ced9f50e704d854d775da52591ab`) as a second inference
backend that runs Qwen3.8-Flash-Next much faster than llama.cpp b10935:

| | Prompt of ~128k tokens, first answer | Decode |
|---|---:|---:|
| Marvin today, llama.cpp | 1,054 s | 27 tok/s |
| Community result: RTX 5090, Linux, IQ2_XS | 22 s | 165–179 tok/s |

Every existing llama.cpp model must keep working unchanged.

## Owner decisions (6 October 2026)

- **Restrictions.** The September "binding requirements" (upstream llama.cpp
  only, UD-Q3_K_XL, Q8_0 KV) were never the owner's. They are now marked
  historical in `docs/design/2026-09-13-qwen38-flash-next-integration.md`. Do
  not add self-imposed restrictions.
- **Weights:** ISTA-DASLab GSQ-RCO **IQ3_S** first. Strata cannot run Unsloth
  UD-Q3_K_XL: it has no K-quant expert kernels, and setup refuses the files.
- **Context:** 256k and 128k profiles, switchable in the picker like other
  models.
- **llama.cpp Flash-Next (`flash_next_q3`):** it stays until the Strata entry
  works and is tested, then Strata replaces it.
- **Scope:**
  - first, the most from the owner's PC: RTX 5090 32 GB, Core Ultra 7 265K
    class, 64 GB RAM, Windows 11;
  - then measure configurations for smaller machines; the community runs
    Strata on 12 GB cards.

### Second round (6 October 2026, during Phase 2)

- **Visibility:** the Strata entry stays behind `strata.enabled` until Phase 3
  can download and prepare everything itself.
- **Malformed tool call:** retried silently with an internal note
  (`[TOOL CALL NOT READ`); after 3 unreadable replies in a row the step reports
  the error; any readable reply resets the count.
- **No API key:** the Strata server runs without a key, like llama-server
  (127.0.0.1 only). The design's per-launch key is dropped.
- **Labels:** the profiles read "Q8 · 256k" and "Q8 · 128k"; the model is
  "Qwen 3.8 Flash-Next · IQ3_S".

## Status

### Phase 0: done (6 October 2026)

Run with Marvin's `.venv` Python in `E:\QWEN local` (the home PC), with
Marvin's model stopped:

```
python scripts/strata_eval.py install
python scripts/strata_eval.py run --context 262144
python scripts/strata_eval.py run --context 131072
python scripts/strata_eval.py install --low-ram resident    (optional)
python scripts/strata_eval.py run --base resident --context 262144
python scripts/strata_eval.py report
```

- Results go to `%LOCALAPPDATA%\StrataEval`: `summary.md` plus
  `runs/*/results.json`.
- Use them to choose between all experts in RAM (normal) and resident, and to
  confirm the 256k and 128k profiles, effort position and tool-call reliability.

**Verified in the cloud** (Linux, no GPU), against Strata's own server with its
scripted `MockEngine`:

- Marvin's `LLMClient` gets separated reasoning, XML tool calls as OpenAI
  `tool_calls`, and `usage`.
- Marvin's real `Agent` completed a two-turn `read_file` task.
- A Hermes-JSON tool call returns `APIError: malformed tool call…`. Today the
  agent would end the task with `Status.ERROR` (`harness/agent.py:766-776`).

**Not verified:** Windows-specific parts of the script, real speed, vision and
`timings`. The mock has no clock or vision.

### Phase 1: done (`2d612de`)

`tests/test_server_launch.py` pins the llama path:

- the exact argv of all built-in llama profiles plus variants (42 and 9; 39 and 6 since the llama.cpp Flash-Next left on 7 October) (manual
  budget, frozen recovery placements, budget reselection, smaller card, extra
  arguments) in `tests/fixtures/llama_launch_golden.json`;
- launch side effects, early exits, failed readiness, identity, stop,
  `wait_health` and the `ensure` ladder.

The fixture is built from the built-in defaults only. An intentional argv change
regenerates it with `MARVIN_REGENERATE_GOLDEN=1` and is reviewed as a diff. The
golden tests passed unchanged after the Phase 2 refactor.

### Phase 2: done (committed locally)

- **Config:** `backend` field (`Config.backend`, closed list `BACKENDS`);
  `Config.model_root` puts a Strata model's files under `paths.strata_data_dir`.
  `strata.enabled` (default off) shows `flash_next_strata`. New paths:
  `paths.strata_dir` (default `runtime/strata`) and `paths.strata_data_dir`
  (default `runtime/models/strata`), laid out like Strata's own setup, so a
  folder from `scripts/strata_eval.py install` works as is.
- **Catalog:** `FLASH_NEXT_STRATA` with pinned ISTA IQ3_S shards and projector
  (sizes and SHA-256 from the Hub at `ed59f92…`). Profiles `int8_256k` and
  `int8_128k` in `measured_profiles.py` with `measurement_id`
  `strata-phase0-pending` and no allocation figures yet.
- **`harness/strata_backend.py`:** writes `runtime/strata-run/strata-<key>.json`
  in setup's format (pool workers like setup on a hybrid CPU, effort at the end,
  vision on the GPU), deletes the web page's shared settings, starts
  `<strata_dir>\.venv\Scripts\python.exe <strata_dir>\serve\server.py --engine strata …`,
  recognizes its process, waits for `loaded`, unloads, reads the expert-cache
  slot count from the engine log and reports why a start failed.
- **`servermgmt`:** the launch part of `_start_locked` is the shared `_launch`.
  Strata branches in `_start_locked` (runtime checked before the weights
  download), `_managed_process`, `stop` (`/unload`, then the tree), `wait_health`
  (`probe`), `record_allocation_failure` (only output after readiness counts for
  request errors), the memory guard and the failure path (whole tree).
  A recovery keeps the logged expert-cache size and the VRAM reserve.
- **`harness/winjob.py`:** a kill-on-close job for the Strata server.
  `scripts/server.py` turns it off, because the CLI exits after the start.
- **Client:** `max_tokens: -1` for Strata; prefill progress polled from
  `GET /metrics` (`live.prompt_read`, `prompt_total`, `prefill_tok_s_mean`)
  while the prompt is read; silent malformed-tool-call retry; `OVERFLOW_RE`
  knows "leaves no room to answer"; the picture estimate follows each run's model
  (`Session.image_token_cost`, set by the agent).
- **UI:** `vision` and `uses_system_ram` come from explicit model fields; the
  chat view hides `[TOOL CALL NOT READ`; the prefill indicator shows
  position/length when an engine does not report its reuse.
- **Fixes:** `scripts/strata_eval.py` now sends `/unload` as JSON (it got 415
  before and fell back to terminating the server).

**Verified on Windows (this PC, no GPU use):**

- the full suite (unit tests and `tests/test_core.py`);
- recorded SSE streams of Strata's real server (mock engine) in
  `tests/fixtures/strata_stream_*.sse`, replayed through `LLMClient`;
- Marvin's agent against Strata's server: an unreadable tool call, a readable
  one, the answer; and a conversation started on a llama model continued on it;
- the real launch path with a stand-in `server.py` that serves the mock engine
  after a 3 s "load": venv launcher plus interpreter in the job, readiness,
  identity, expert-cache record, reply, `/unload`, tree stop; and a crashed
  Marvin process (`os._exit`) took the whole server with it.

**Not verified:** the real engine (speed, `timings`, vision, memory, recovery
on real pressure). That needs Phase 0 data and then the owner's PC.

## Next work

### Qualification: done, menu approved (7 October 2026)

The record is [strata-qualification-2026-10-07.md](strata-qualification-2026-10-07.md)
with the JSON and CSV under `measurements/`. The owner approved its menu, and it
is installed (`bccdfda`):

- `flash_next_strata` (IQ3_S, default) and `flash_next_strata_iq2` (IQ2_XS,
  optional), both behind `strata.enabled` until Phase 3;
- a 256k and a 128k profile per RAM class (64/48/32) and GPU class (32/24/16):
  every expert in RAM on 64 GB (KV in RAM on a 16 GB card), resident below; a
  fixed `expert_cache` on the smaller cards; the picker matches the RAM class;
- the two entries share Strata's data folder with their own receipts; a file
  another entry verified is hard-linked instead of downloaded;
- the RAM guard counts the GGUF pages Strata maps as available (`d393736`).

The llama.cpp `flash_next_q3` is removed with the adaptive planner that served
only it (`runtime_plan.py`, `gguf_metadata.py`, the `adaptive_runtime` branches,
its installer row and golden records). A saved selection of it moves to
`flash_next_strata` where that entry is available.

### Integration in Marvin with the real engine (7 October 2026)

`tests/e2e_flash_next.py` runs the real application worker against the installed
Marvin's models and the prepared Strata, on its own port and runtime folder:

- **switch** (passed): one chat on Q5 (a file and a code word), then Flash-Next
  (read the file, recalled the code word, read an image, took a second word),
  then Q5 again (recalled both). The first Flash-Next start adopted Strata's
  data folder with a checksum instead of a download.
- **coding** (passed): `apply_patch`, the project check and a summary. With
  thinking at `xhigh` (the workspace's default) Flash-Next used 8 tools in
  62 s, like Q5 (6 tools, 39 s). With thinking off it twice kept checking its
  plan because the "Git diff reviewed" item cannot be ticked in a folder that is
  not a git repository: 22 tools once, 200 another time; the exact-repeat loop
  warning never fired, as the calls cycled through three tools. Fixed for every
  model (`b3a751e`): a repeated cycle of two to four steps gets the advisory
  warning, and outside Git the change journal is the diff review. The same task
  then took 8 tools in 62 s.
- **pressure** (passed): 48 GB of RAM, 16 GB card, 256k; another process took
  the free RAM, the engine ran out of memory reading a 120k-token input, Marvin
  restarted at 128k with the same expert cache (1054) and finished the task.
  On a 32 GB card the same pressure did not stop the engine.

### Phase 3: runtime and model preparation (design sections 2.7–2.9)

Everything inside the existing download, verify and prepare phases, so the
user sees only the usual progress:

- `harness/strata_runtime.py`: pinned source archive, `strata-windows-x64.zip`,
  hashed wheel lock with the two NVIDIA wheels, own venv from Marvin's Python,
  driver ≥ 580, staged and activated like `runtime_update.py`;
- pack (`tools/iq_pack.py`, needs llama.cpp's `gguf-py` at the commit setup
  pins), MTP (`mtp_fetch.py` at a pinned revision, `mtp_pack.py`, `mtp_rt.py`),
  each resumable, hash-checked and reported as "preparing";
- then show the entry (drop the `strata.enabled` gate) and remove the setup
  hint from `strata_backend.explain`;
- offline backup and installer include `runtime/strata` when installed; the
  backup must keep the hard-linked shard as one file, and the installer's model
  list gets the Flash-Next rows back (IQ3_S, IQ2_XS) with their RAM needs;
- the user manuals (EN and CS), the installation guides and the README still
  describe the removed llama.cpp Flash-Next (Q3, 90.9 GB, automatic planning)
  and are rewritten for IQ3_S/IQ2_XS when the entry becomes visible.

### Phase 4

Integration tests in Marvin with the real engine (switching to and from
Flash-Next in one chat, recovery under real pressure, prefix reuse, the e2e
smoke and coding workflows), release notes, release.

## Testing in the cloud without a GPU

1. **Clone Strata:**
   `GIT_LFS_SKIP_SMUDGE=1 git clone --depth 1 https://github.com/Niko1221/strata /home/user/niko1221/strata`
   (public; anonymous read works).
2. **Python environment.** Marvin needs Python 3.12; the system 3.11 fails on
   f-strings. Create a venv with `python3.12 -m venv` and install
   `requirements.txt`. Then pin `openai==3.3.1 httpx==0.28.1` from
   `requirements-windows-py312.lock`: the unpinned latest openai lacked httpx.
   Strata's server also needs `numpy jinja2 regex pyyaml pillow psutil requests`.
3. **Mock server:**
   `python -m serve.server --engine mock --port 18081 --script '<reply>'`,
   run from the Strata checkout.
   - Repeat `--script` for consecutive replies.
   - With thinking on, a script starts with reasoning text and `</think>`.
     Tool calls use Qwen XML:
     `<tool_call>\n<function=read_file>\n<parameter=path>\nnotes.txt\n</parameter>\n</function>\n</tool_call>`.
   - The mock's context is 32,768 and it uses a byte tokenizer, so Marvin's
     agent prompt overflows it. Patch `MockEngine.__init__.__defaults__ = (262144, 0.0)`
     in a small wrapper before calling `serve.server.main()`.
4. **Probe:** `python scripts/strata_eval.py probe --url http://127.0.0.1:18081 --context 32768 --scenarios warmup,chat,tool_calls`.
5. **Do not stop mocks with `pkill -f`/`pgrep -f` on a pattern that appears in
   your own command line.** It kills the calling shell (exit 144). Kill by PID.
6. **Known failure:** `python -m unittest tests.test_localization` has one
   failure on Linux: `locales\cs-custom.isl` is a Windows path. It predates this
   work; the other 12 tests pass.

## Key facts about Strata v0.1.39

- **Processes:** `python serve/server.py` →
  `strata.exe --serve` (stdin/stdout protocol), plus `strata-vision.exe`.
  - Children are in Strata's own kill-on-close job; the server process is not.
  - The port refuses connections until the model is loaded. After that
    `/health` always returns 200 with `loaded` and `service: "strata"`.
- **API:**
  - `/v1/chat/completions` streams `reasoning_content`, incremental `tool_calls`,
    and `usage` and llama-style `timings` in the final chunk.
  - `/slots` (`is_processing`), `/props`, `/v1/status`, `/status` (live
    `prompt_read`/`prompt_total`), `/unload`, `/load` and
    `/v1/messages/count_tokens`.
  - No `prompt_progress`, `/tokenize` or Prometheus metrics.
- **Ignored request fields:** `stop`, `tool_choice`, `cache_prompt`, `id_slot`
  and `n_probs`. `top_k` is capped at 64.
- **Hidden defaults:** missing fields are filled from
  `<config stem>.shared-settings.json`, which Strata's web page writes.
- **Effort sentence:** it sits at the top of the system turn unless the config
  has `"effort_position": "end"`.
- **Messages:** only message 0 stays a system message; later ones become user
  turns.
- **Prefix cache:** the live session plus up to six exact-prefix checkpoints
  (~118 MB each, RAM only).
- **Cancel:** a disconnect is noticed within 0.5 s. Prefill stops at the next
  chunk of up to 8,192 tokens.
- **Pinned files for IQ3_S:**
  - weights from HF `ISTA-DASLab/Qwen3.8-Flash-Next-GSQ-RCO-GGUF` at
    `ed59f92082b1e93c0e96d60a8b11aab089b52f09` (83.6 GB, 50.3 GB of experts
    pinned in RAM);
  - projector `mmproj-Qwen3.8-Flash-Next-BF16.gguf`;
  - MTP tensors from `Qwen/Qwen3.8-Flash-Next` at `de4b8e4…`. Setup itself uses
    `main`; Marvin should pin it.
- **Engine download and drivers:** release asset `strata-windows-x64.zip`.
  Driver ≥ 580. CUDA DLLs come from the pip wheels `nvidia-cublas==13.0.2.14`
  and `nvidia-cuda-runtime==13.0.96`.
