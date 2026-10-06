# Strata backend: session handover (6 October 2026)

This note lets a new session continue the Strata work without the earlier conversation.

- **Branch:** `claude/gracious-archimedes-k0spl5`. Base: `main` at `de6bc00` (Marvin 1.18.2).
- **Commits:**
  - `a088fb8` adds the design note;
  - `b0fd45d` adds the Phase 0 script and records the owner's decisions;
  - a later commit adds this note.
- **No pull request yet.** Create one only when the owner asks.

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

## Status

### Phase 0: ready, waiting on the owner's PC

The owner runs these with Marvin's `.venv` Python on the home PC, from a
checkout of this branch:

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

### Phases 1–4: not started

The next session can build Phases 1 and 2 in the cloud while the owner runs
Phase 0.

## Next work

### Phase 1: safety net (no behavior change)

Add golden tests for the llama path. No unit test asserts the full argv today.
`harness/servermgmt.py:_start_locked` (`:221-408`) depends on the following;
mock all of them:

- **Server state:** `health`, `running_model`, `stop`.
- **GPU fitting:** `harness.gpu.normalize_vram_setting`, plus `effective_vram_gb`,
  `fitting_profiles` and `fits` for non-adaptive models.
- **Model files:** `cfg.model_ready` and `harness.model_files.download_pinned_model`.
- **Runtime:** `harness.runtime_update.ensure_runtime`, which returns the exe
  path; `cfg.model_file(...).exists()` and `cfg.mmproj_file`.
- **Planning:** `harness.runtime_plan.plan_for`. Flash is adaptive and gets
  `plan.args` and `plan.context`.
- **MTP:** `_mtp_draft_args` for profiles with `speculative == "mtp"`.
- **Process launch:** `subprocess.Popen`, the PID file `runtime/llama-server.pid`
  (`model:pid`) and `runtime/model-run.json`.
- **Memory guard:** `harness.hardware.detect_hardware(fresh=True)` (`vram_total`)
  and the `watch_memory` guard thread.
- **Readiness:** `wait_health`.

Assert the exact argv for every built-in model and profile in
`harness/config.py` and `harness/measured_profiles.py`, including Flash
adaptive, MTP, `_recovery_placement` and a manual VRAM budget (`--fit off`).

Also cover:

- `_managed_process` identity (`:132-158`);
- `stop` (`:171-196`);
- the `ensure` recovery ladder (`:428-460`).

Existing helpers to reuse are in `tests/test_runtime_support.py` and
`tests/test_memory_profiles.py`.

### Phase 2: backend seam

Design section 2:

- **Model entry:** a `backend: "llama" | "strata"` field, default `llama`.
- **Catalog:** a `FLASH_NEXT_STRATA` entry in `harness/model_catalog.py`,
  registered like `FLASH_NEXT_Q3` (`harness/config.py:79-81`). It is hidden
  behind a config flag until Phase 4.
- **`harness/strata_backend.py`:**
  - writes the Strata config JSON (format: `strata-iq3_s.json` written by
    Strata setup);
  - spawns `<strata venv>\python.exe serve\server.py --engine strata --config … --host 127.0.0.1 --port <server.port>`
    with `STRATA_API_KEY` set to a per-launch key.
- **`servermgmt` dispatch** at:
  - `_start_locked`;
  - `_managed_process`: the Strata process is `python.exe`, so today's
    `llama-server.exe` name check would delete its PID file;
  - `wait_health`: require `service == "strata"` and `loaded`;
  - `stop`: `POST /unload`, then terminate the tree;
  - `record_allocation_failure`: Strata log markers.
- **Windows job object** (KILL_ON_JOB_CLOSE) for the Strata server. Marvin has
  none today.
- **Client:**
  - the per-launch API key;
  - send `max_tokens` explicitly;
  - one bounded advisory retry on "malformed tool call";
  - add `leaves no room to answer` to `OVERFLOW_RE` (`harness/agent.py:129`);
  - per-backend `IMAGE_TOKENS` (`harness/session.py:204`);
  - optional prefill progress by polling `GET /status` (`prompt_read`,
    `prompt_total`).
- **`harness/web_api.py:113-114`:** `vision` and `uses_system_ram` come from
  explicit fields, not `mmproj` or `--n-cpu-moe` greps.
- **Neutral wording:** `harness/model_switch.py:188` says "llama-server could
  not be prepared".

### Phases 3 and 4

Design sections 2.7–2.10 and 3: Strata runtime staging (pinned zip and wheel
lock, own venv, driver ≥ 580), pack and MTP preparation through the existing
download UI, picker, localization (EN and `harness/locales/cs.json`), manuals,
measurements, then smaller-machine profiles.

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
