"""Configuration loading and access: config.yaml merged with defaults."""
from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import yaml

from .i18n import locale_data, translate

ROOT = Path(__file__).resolve().parent.parent

BUILTIN_MODELS: dict[str, dict[str, Any]] = {'q4': {'alias': 'Qwen3.8-27B Q4_K_M (16.5 GB, fast)',
        'status_label': 'Qwen 3.8 27B · Q4',
        'repo': 'unsloth/Qwen3.8-27B-GGUF',
        'file': 'Qwen3.8-27B-UD-Q4_K_M.gguf',
        'mmproj': 'mmproj-F16.gguf',
        'server_args': ['-fa', 'on']},
 'q2': {'alias': 'Qwen3.8-27B Q2_K_XL (9.8 GB, smallest quant - the most context on a 16 GB GPU)',
        'status_label': 'Qwen 3.8 27B · Q2',
        # Offered, never chosen for the owner: it trades weight quality for room.
        'optional_download': True,
        'repo': 'unsloth/Qwen3.8-27B-GGUF',
        'file': 'Qwen3.8-27B-UD-Q2_K_XL.gguf',
        'mmproj': 'mmproj-F16.gguf',
        'server_args': ['-fa', 'on']},
 'q3': {'alias': 'Qwen3.8-27B IQ3_S (12.0 GB, borderline quality - for 16 GB GPUs)',
        'status_label': 'Qwen 3.8 27B · IQ3_S',
        'repo': 'unsloth/Qwen3.8-27B-GGUF',
        'file': 'Qwen3.8-27B-UD-IQ3_S.gguf',
        'mmproj': 'mmproj-F16.gguf',
        'server_args': ['-fa', 'on']},
 'q5': {'alias': 'Qwen3.8-27B Q5_K_M (19.8 GB, high quality)',
        'status_label': 'Qwen 3.8 27B · Q5',
        'repo': 'unsloth/Qwen3.8-27B-GGUF',
        'file': 'Qwen3.8-27B-UD-Q5_K_M.gguf',
        'mmproj': 'mmproj-F16.gguf',
        'server_args': ['-fa', 'on']},
 'ornith_q5': {'alias': 'Ornith 1.5 35B-A3B Abliterated Q5 (23.0 GB, reasoning, context 128k)',
               'status_label': 'Ornith 1.5 35B-A3B · Abliterated Q5',
               'family': 'ornith',
               'repo': 'alztrk/Ornith-1.5-35B-A3B-Abliterated-GGUF',
               'file': 'Ornith-1.5-35B-Abliterated-Dynamic-Q5_K_M.gguf',
               'mmproj_repo': 'ornith-ai/Ornith-1.5-35B-A3B-GGUF',
               'mmproj': 'mmproj-Ornith-1.5-35B-BF16.gguf',
               'server_args': ['-fa', 'on'],
               'sampling': {'thinking': {'temperature': 0.6,
                                         'top_p': 0.95,
                                         'top_k': 20,
                                         'presence_penalty': 0.0},
                            'non_thinking': {'temperature': 0.7,
                                             'top_p': 0.8,
                                             'top_k': 20,
                                             'presence_penalty': 1.5}},
               'supports_reasoning_effort': False},
 'nemotron_q4': {'alias': 'Nemotron 3.5 Lightning 30B-A3B Q4_K_XL (25.5 GB, hybrid MoE, ~210 tok/s)',
                 'status_label': 'Nemotron 3.5 Lightning · Q4_XL',
                 'family': 'nemotron',
                 'repo': 'unsloth/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-GGUF',
                 'file': 'NVIDIA-Nemotron-3.5-Lightning-30B-A3B-UD-Q4_K_XL.gguf',
                 'server_args': ['-fa', 'on'],
                 'supports_reasoning_effort': False,
                 'sampling': {'thinking': {'temperature': 0.6, 'top_p': 0.95, 'min_p': 0.01},
                              'non_thinking': {'temperature': 0.2}}},
 'nemotron_q5': {'alias': 'Nemotron 3.5 Lightning 30B-A3B Q5_K_XL (30.4 GB, hybrid MoE, top quality)',
                 'status_label': 'Nemotron 3.5 Lightning · Q5_KXL',
                 'family': 'nemotron',
                 'repo': 'unsloth/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-GGUF',
                 'file': 'NVIDIA-Nemotron-3.5-Lightning-30B-A3B-UD-Q5_K_XL.gguf',
                 'server_args': ['-fa', 'on'],
                 'supports_reasoning_effort': False,
                 'sampling': {'thinking': {'temperature': 0.6, 'top_p': 0.95, 'min_p': 0.01},
                              'non_thinking': {'temperature': 0.2}}}}

from harness.measured_profiles import install_profiles
install_profiles(BUILTIN_MODELS)

from harness.model_catalog import FLASH_NEXT_Q3

BUILTIN_MODELS["flash_next_q3"] = copy.deepcopy(FLASH_NEXT_Q3)

DEFAULTS: dict[str, Any] = {
    "server": {
        "host": "127.0.0.1",
        "port": 8080,
        "embeddings_port": 8091,
        "n_gpu_layers": 999,
        "extra_args": [],
    },
    # Built-ins live in code too: an installer update preserves config.yaml, but
    # still needs to introduce newly supported models.
    "models": BUILTIN_MODELS,
    "default_model": "q5",
    "sampling": {
        "thinking": {"temperature": 1.0, "top_p": 0.95, "top_k": 20, "presence_penalty": 0.0},
        "non_thinking": {"temperature": 0.7, "top_p": 0.8, "top_k": 20, "presence_penalty": 1.5},
    },
    "thinking": True,
    "reasoning_effort": "xhigh",   # xhigh | medium | low (Qwen reasoning effort)
    "agent": {
        "mode": "agent",
        "autonomy": "supervised",
        "max_steps": 0,
        "semi_max_steps": 0,
        "shell_timeout": 60,
        "workspace": None,
    },
    "computer": {
        "screenshot_max_edge": 1920,
        "screenshot_grayscale": False,
        "failsafe": True,
        "pause_between_actions": 0.15,
    },
    # Dictation. Listed here and not only in config.yaml: an upgrade keeps the
    # user's file, so a new section reaches an existing installation only through
    # these defaults.
    "speech": {
        "enabled": False,
        "language": "auto",
        "device": None,
        "threads": 0,
        "max_seconds": 300,
    },
    # Image generation is the one feature that calls out to a paid service, so it
    # is off until the owner turns it on, and off means off even when the CLI is
    # installed and signed in. No credential lives here: the OpenArt CLI keeps its
    # own in the user profile, so nothing reaches this file, an export or a backup.
    "openart": {
        "enabled": False,
    },
    "memory": {
        "directory": "memory",
        "global_filename": "GLOBAL.md",
        "modes_directory": "modes",
        "development_filename": "MEMORY.md",
        "project_filename": "QWEN_MEMORY.md",
    },
    "web": {"host": "127.0.0.1", "port": 7860},
    "hardware": {"vram_gb": "auto"},
    "skills": {
        "directory": "skills",
        "user_directory": "user-skills",
        "project_directory": ".qwen-skills",
    },
    "paths": {
        "runtime_dir": "runtime",
        "llama_dir": "runtime/llama",
        "models_dir": "runtime/models",
        "sessions_dir": "sessions",
    },
}


def _deep_merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def _migrate_builtin_models(user: dict[str, Any]) -> None:
    """Convert the short-lived fixed-Q8 presets to selectable KV profiles."""
    q8_args = ["--cache-type-k", "q8_0", "--cache-type-v", "q8_0", "-fa", "on"]
    q8_ctx = {"q4": 262144, "q5": 196608}
    f16_ctx = {"q4": 131072, "q5": 98304}
    models = user.get("models")
    if not isinstance(models, dict):
        return
    for key, large_ctx in q8_ctx.items():
        model = models.get(key)
        if (isinstance(model, dict) and model.get("ctx_size") == large_ctx
                and model.get("server_args") == q8_args):
            model["ctx_size"] = f16_ctx[key]
            model.pop("server_args", None)


# Legacy Czech labels from releases before English became the default in 1.3.0.
_LEGACY_KV_LABELS = locale_data("legacy_profile_labels", {})


def _migrate_kv_labels(user: dict[str, Any]) -> None:
    """Migrate legacy profile labels to English keys and optional UI translations.

    Upgrades preserve config.yaml, so old labels must be normalized in memory rather than rewriting the user's file."""
    models = user.get("models")
    if not isinstance(models, dict):
        return
    for model in models.values():
        if not isinstance(model, dict):
            continue
        profiles = model.get("kv_cache_profiles")
        if not isinstance(profiles, dict):
            continue
        for profile in profiles.values():
            if not isinstance(profile, dict):
                continue
            label = profile.get("label")
            if isinstance(label, str) and label in _LEGACY_KV_LABELS:
                profile["label_cs"] = label
                profile["label"] = _LEGACY_KV_LABELS[label]


def _remove_legacy_agent_limits(user: dict[str, Any]) -> None:
    agent = user.get("agent")
    if isinstance(agent, dict):
        agent["max_steps"] = 0
        agent["semi_max_steps"] = 0


def _migrate_memory_profiles(user: dict[str, Any]) -> None:
    """Refresh shipped profiles while retaining unrelated custom model definitions.

    The original file stays intact. Built-in IDs are release-owned; custom models
    should use their own key or checkpoint file to keep independent profiles.
    """
    for key, model in user.get("models", {}).items():
        builtin = BUILTIN_MODELS.get(key)
        if not isinstance(model, dict) or not builtin:
            continue
        if model.get("file", builtin["file"]) != builtin["file"]:
            continue
        model["kv_cache_profiles"] = copy.deepcopy(builtin["kv_cache_profiles"])
        model["kv_cache"] = builtin["kv_cache"]
        model["ctx_size"] = builtin["ctx_size"]
        model["alias"] = builtin["alias"]


class Config:
    """Configuration with path and model helpers."""

    def __init__(self, data: dict[str, Any], root: Path = ROOT):
        self.data = data
        self.root = root

    # -- paths -------------------------------------------------------------
    def path(self, dotted: str) -> Path:
        """Resolve a paths.* setting to an absolute path relative to the project root."""
        node: Any = self.data
        for part in dotted.split("."):
            node = node[part]
        p = Path(str(node))
        return p if p.is_absolute() else (self.root / p)

    # -- models ------------------------------------------------------------
    def model_key(self) -> str:
        key = self.data.get("default_model", "q4")
        return key if key in self.data.get("models", {}) else next(iter(self.data["models"]), "q4")

    def model(self, key: str | None = None) -> dict:
        key = key or self.model_key()
        return self.data["models"][key]

    def model_file(self, key: str | None = None) -> Path:
        return self.path("paths.models_dir") / self.model(key)["file"]

    def model_ready(self, key: str | None = None) -> bool:
        from harness.model_files import model_ready
        return model_ready(self.path("paths.models_dir"), self.model(key))

    def mmproj_file(self, key: str | None = None) -> Path | None:
        """Path to the vision projector; None for text-only models without mmproj."""
        mmproj = self.model(key).get("mmproj")
        if not mmproj:
            return None
        return self.path("paths.models_dir") / mmproj

    def mmproj_repo(self, key: str | None = None) -> str:
        model = self.model(key)
        return str(model.get("mmproj_repo") or model["repo"])

    def mtp_draft_file(self) -> Path:
        """Path to the pinned MTP draft model used by speculative profiles."""
        from harness.model_catalog import QWEN27B_MTP_DRAFT
        from harness.model_files import asset_path, local_model_dir
        spec = QWEN27B_MTP_DRAFT
        return asset_path(local_model_dir(self.path("paths.models_dir"), spec), spec["assets"][0]["path"])

    def mtp_draft_ready(self) -> bool:
        from harness.model_catalog import QWEN27B_MTP_DRAFT
        from harness.model_files import model_ready
        return model_ready(self.path("paths.models_dir"), QWEN27B_MTP_DRAFT)

    def embeddings_model_file(self) -> Path:
        """Path to the pinned CPU embedding model used by semantic search."""
        from harness.model_catalog import EMBEDDINGS_BGE_M3
        from harness.model_files import asset_path, local_model_dir
        spec = EMBEDDINGS_BGE_M3
        return asset_path(local_model_dir(self.path("paths.models_dir"), spec), spec["assets"][0]["path"])

    def embeddings_model_ready(self) -> bool:
        from harness.model_catalog import EMBEDDINGS_BGE_M3
        from harness.model_files import model_ready
        return model_ready(self.path("paths.models_dir"), EMBEDDINGS_BGE_M3)

    @property
    def embeddings_url(self) -> str:
        s = self.data["server"]
        return f"http://{s['host']}:{s.get('embeddings_port', 8091)}"

    def kv_cache_profiles(self, key: str | None = None) -> dict[str, dict[str, Any]]:
        profiles = self.model(key).get("kv_cache_profiles") or {}
        return {name: {**profile, "label_cs": profile.get("label_cs") or translate(str(profile.get("label", name)), "cs")}
                for name, profile in profiles.items()}

    def kv_cache_mode(self, key: str | None = None) -> str:
        model = self.model(key)
        profiles = self.kv_cache_profiles(key)
        selected = str(model.get("kv_cache", "f16"))
        return selected if selected in profiles else next(iter(profiles), selected)

    def set_kv_cache_mode(self, key: str, mode: str) -> None:
        if mode not in self.kv_cache_profiles(key):
            raise ValueError(f"Model '{key}' does not support KV cache '{mode}'")
        self.model(key)["kv_cache"] = mode

    def context_size(self, key: str | None = None) -> int:
        model = self.model(key)
        profile = self.kv_cache_profiles(key).get(self.kv_cache_mode(key), {})
        return int(profile.get("ctx_size", model.get("ctx_size", 32768)))

    def kv_cache_server_args(self, key: str | None = None) -> list[str]:
        mode = self.kv_cache_mode(key)
        # Compact profiles can override the actual cache_type independently of their key.
        values = self.kv_cache_profiles(key).get(mode, {})
        cache_type = str(values.get("cache_type") or mode)
        # Keys and values can differ: values tolerate quantisation far better, so
        # a smaller value cache buys context without touching the sensitive half.
        value_type = str(values.get("value_cache_type") or cache_type)
        return ["--cache-type-k", cache_type, "--cache-type-v", value_type]

    # -- server ------------------------------------------------------------
    @property
    def base_url(self) -> str:
        s = self.data["server"]
        return f"http://{s['host']}:{s['port']}"

    def llama_server_exe(self) -> Path | None:
        """Find llama-server.exe under runtime/llama, including nested CUDA directories."""
        llama_dir = self.path("paths.llama_dir")
        if not llama_dir.exists():
            return None
        return next(iter(sorted(llama_dir.rglob("llama-server.exe"))), None)

    # -- sampling ----------------------------------------------------------
    def sampling(self, thinking: bool | None = None) -> dict:
        if thinking is None:
            thinking = self.data.get("thinking", True)
        key = "thinking" if thinking else "non_thinking"
        sampling = self.data["sampling"][key]
        model_sampling = self.model().get("sampling", {}).get(key, {})
        return _deep_merge(sampling, model_sampling)

    # -- convenience accessors ---------------------------------------------
    @property
    def agent(self) -> dict:
        return self.data["agent"]

    @property
    def computer(self) -> dict:
        return self.data["computer"]

    @property
    def web(self) -> dict:
        return self.data["web"]


def load_config(path: Path | None = None, *, root: Path | None = None) -> Config:
    """Load a config file; relative paths.* entries resolve against `root`.

    `root` defaults to the config file's own directory, so an installed copy
    loading its data directory keeps its data there instead of scattering it
    into the code root. Pass `root` explicitly only when the two differ."""
    path = path or (ROOT / "config.yaml")
    user: dict = {}
    if path.exists():
        with open(path, encoding="utf-8") as f:
            user = yaml.safe_load(f) or {}
    _migrate_builtin_models(user)
    _migrate_kv_labels(user)
    _migrate_memory_profiles(user)
    _remove_legacy_agent_limits(user)
    return Config(_deep_merge(DEFAULTS, user), root or path.parent)
