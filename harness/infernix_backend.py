"""Run Blackwell-accelerated Qwen3.8 models on the Infernix engine.

servermgmt dispatches here for a model whose entry names `backend: infernix`.
Infernix is a native C++/CUDA HTTP server (infernix-serve.exe) with built-in
OpenAI Chat Completions, vision, DFlash2 speculative decoding, hybrid prefix
cache and automatic Windows DXGI/RAM sizing. It requires an NVIDIA RTX
50-series (Blackwell, sm_120+) GPU and NVIDIA driver 580 or newer.

Layout:
    paths.infernix_dir         infernix-serve.exe  *.dll  chat_templates/qwen3_8.jinja
    paths.infernix_models_dir  qwen3.8-27b-nvfp4/*.infernix
                               flash-next-iq3_s/*.infernix  *.ngram
                               flash-next-dflash2/*.infernix
"""
from __future__ import annotations

from dataclasses import dataclass, field
import os
from pathlib import Path

import requests

from harness.config import Config

WINDOWS = os.name == "nt"
# Allocator / sizing refusal markers in infernix-serve logs, beyond servermgmt's generic set.
MEMORY_MARKERS = (
    "does not fit",
    "out of device memory",
    "not enough",
    "insufficient",
    "ram ledger",
    "cannot fit",
)
LOG_TAIL_BYTES = 65536


def program_dir(cfg: Config) -> Path:
    return cfg.path("paths.infernix_dir")


def models_dir(cfg: Config) -> Path:
    return cfg.path("paths.infernix_models_dir")


def server_exe(cfg: Config) -> Path:
    return program_dir(cfg) / ("infernix-serve.exe" if WINDOWS else "infernix-serve")


def server_log(cfg: Config) -> Path:
    return cfg.path("paths.runtime_dir") / "infernix-server.log"


def settings(cfg: Config, key: str) -> dict:
    return cfg.model(key).get("infernix") or {}


def chat_template_path(cfg: Config, key: str) -> Path | None:
    rel = settings(cfg, key).get("chat_template")
    if not rel:
        return None
    path = Path(rel)
    return path if path.is_absolute() else program_dir(cfg) / path


def ngram_volume_path(cfg: Config, key: str) -> Path | None:
    rel = settings(cfg, key).get("ngram_volume")
    if not rel:
        return None
    path = Path(rel)
    return path if path.is_absolute() else cfg.model_root(key) / path


def draft_model_path(cfg: Config, key: str) -> Path | None:
    rel = settings(cfg, key).get("draft_model")
    if not rel:
        return None
    path = Path(rel)
    return path if path.is_absolute() else cfg.model_root(key) / path


def runtime_problems(cfg: Config, key: str) -> list[str]:
    """What the Infernix program folder lacks for a launch; checked before any model download."""
    needed: list[tuple[str, Path]] = [("the Infernix server", server_exe(cfg))]
    template = chat_template_path(cfg, key)
    if template is not None:
        needed.append(("the chat template", template))
    return [f"{label}: {path}" for label, path in needed if not path.is_file()]


def model_problems(cfg: Config, key: str) -> list[str]:
    """What the Infernix model folder lacks for a launch, once weights are verified."""
    needed: list[tuple[str, Path]] = [("the model weights", cfg.model_file(key))]
    ngram = ngram_volume_path(cfg, key)
    if ngram is not None:
        needed.append(("the n-gram volume", ngram))
    draft = draft_model_path(cfg, key)
    if draft is not None:
        needed.append(("the DFlash2 drafter", draft))
    return [f"{label}: {path}" for label, path in needed if not path.is_file()]


def explain(cfg: Config, key: str, problems: list[str]) -> str:
    name = cfg.model(key).get("status_label") or cfg.model(key).get("alias") or key
    return (
        f"{name} cannot start: some of its files are missing after preparation: "
        + "; ".join(problems)
        + ". Selecting the model again prepares what is missing."
    )


def server_argv(cfg: Config, key: str, context: int) -> list[str]:
    """Build the command line for infernix-serve.exe."""
    srv = cfg.data["server"]
    s = settings(cfg, key)
    profile = cfg.kv_cache_profiles(key).get(cfg.kv_cache_mode(key), {})
    ctx = int(context)
    argv = [str(server_exe(cfg)), str(cfg.model_file(key))]
    ngram = ngram_volume_path(cfg, key)
    if ngram is not None:
        argv += ["--ngram-volume", str(ngram)]
    argv += [
        "--model-id", str(s.get("model_id", "local-model")),
        "--any-model-name",
        "--host", str(srv["host"]),
        "--port", str(srv["port"]),
        "--max-context", str(ctx),
        "--default-max-tokens", str(ctx),
        "--max-concurrency", "1",
        "--kv-dtype", str(profile.get("cache_type") or s.get("kv_dtype", "int8")),
    ]
    kv_cap = profile.get("kv_capacity")
    if kv_cap == "exact":
        argv += ["--kv-capacity", str(ctx)]
    elif isinstance(kv_cap, int) and kv_cap > 0:
        argv += ["--kv-capacity", str(kv_cap)]
    spec = s.get("spec")
    if spec:
        argv += ["--spec", str(spec)]
        draft = draft_model_path(cfg, key)
        if draft is not None and draft.is_file():
            argv += ["--draft-model", str(draft)]
        if s.get("draft_tokens") is not None:
            argv += ["--draft-tokens", str(s["draft_tokens"])]
        if s.get("lm_head_draft"):
            argv.append("--lm-head-draft")
    if s.get("ngram_draft_tokens") is not None:
        argv += ["--ngram-draft-tokens", str(s["ngram_draft_tokens"])]
    if s.get("embedding_host"):
        argv.append("--embedding-host")
    if s.get("expert_ram_layout"):
        argv += ["--expert-ram-layout", str(s["expert_ram_layout"])]
    host_ctx = profile.get("host_context_mib", s.get("host_context_mib"))
    if host_ctx is not None:
        argv += ["--host-context-mib", str(host_ctx)]
    template = chat_template_path(cfg, key)
    if template is not None and template.is_file():
        argv += ["--chat-template", str(template)]
    argv += ["--preserve-thinking", "--tolerant-tool-calls"]
    if s.get("vision", True):
        argv.append("--vision")
    argv += [str(a) for a in profile.get("infernix_args", [])]
    argv += [str(x) for x in srv.get("extra_args", [])]
    return argv


@dataclass(frozen=True)
class PreparedLaunch:
    argv: list[str]
    cwd: Path
    placement: dict
    run: dict = field(default_factory=dict)


def prepare(cfg: Config, key: str, context: int) -> PreparedLaunch:
    """Validate runtime and model files and return the launch parameters for servermgmt."""
    problems = runtime_problems(cfg, key) + model_problems(cfg, key)
    if problems:
        raise RuntimeError(explain(cfg, key, problems))
    profile = cfg.kv_cache_profiles(key).get(cfg.kv_cache_mode(key), {})
    placement = {
        "model": key,
        "kv_dtype": str(profile.get("cache_type") or settings(cfg, key).get("kv_dtype", "int8")),
        "kv_capacity": profile.get("kv_capacity", "auto"),
    }
    return PreparedLaunch(
        argv=server_argv(cfg, key, context),
        cwd=program_dir(cfg),
        placement=placement,
        run={"backend": "infernix"},
    )


def owns_process(cfg: Config, key: str, proc) -> bool:
    """True when `proc` is the Infernix server Marvin started on its configured port."""
    expected_name = "infernix-serve.exe" if WINDOWS else "infernix-serve"
    try:
        if (proc.name() or "").lower() != expected_name:
            return False
        expected_exe = server_exe(cfg)
        if not expected_exe.exists() or Path(proc.exe()).resolve() != expected_exe.resolve():
            return False
        argv = proc.cmdline()
        port_index = argv.index("--port") if "--port" in argv else -1
        return (
            port_index >= 0
            and port_index + 1 < len(argv)
            and argv[port_index + 1] == str(cfg.data["server"]["port"])
        )
    except Exception:
        return False


def ready(cfg: Config, timeout: float = 3.0) -> bool:
    """True when Infernix is listening and ready to accept requests."""
    try:
        r = requests.get(f"{cfg.base_url}/health", timeout=timeout)
        return r.status_code == 200
    except requests.RequestException:
        return False


def slots_processing(cfg: Config, timeout: float = 3.0) -> bool | None:
    """Check GET /monitor to determine whether Infernix is actively serving a client request."""
    try:
        r = requests.get(f"{cfg.base_url}/monitor", timeout=timeout)
        if r.status_code != 200:
            return None
        data = r.json()
        if not isinstance(data, dict):
            return None
        reqs = data.get("requests")
        if not isinstance(reqs, list):
            return False
        return any(not bool(item.get("background")) for item in reqs if isinstance(item, dict))
    except Exception:
        return None


def _tail(path: Path, start: int = 0) -> str:
    try:
        with path.open("rb") as stream:
            size = path.stat().st_size
            stream.seek(max(int(start or 0), size - LOG_TAIL_BYTES))
            return stream.read().decode(errors="replace")
    except OSError:
        return ""


def recent_log_text(cfg: Config, run: dict) -> str:
    return _tail(server_log(cfg), run.get("log_offset", 0))


def start_failure(cfg: Config, run: dict) -> str:
    """Summarize why an Infernix launch failed from the recent log tail."""
    lines = [line.strip() for line in recent_log_text(cfg, run).splitlines() if line.strip()]
    detail = ""
    for line in reversed(lines):
        low = line.lower()
        if any(k in low for k in ("error", "failed", "cannot", "refused", "does not fit", "unsupported", "cuda")):
            detail = line
            break
    if not detail and lines:
        detail = lines[-1]
    if detail:
        return f"Infernix could not start the model: {detail}"
    return f"Infernix could not start the model. Details: {server_log(cfg)}"
