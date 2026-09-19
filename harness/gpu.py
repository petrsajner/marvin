"""Detect GPU memory and select compatible model/context profiles.

Measured profiles use approved GPU classes, with allocation recorded separately.
hardware.vram_gb can constrain capacity but cannot invent additional memory."""
from __future__ import annotations

import subprocess
import time
import math

NO_WINDOW = 0x08000000

_total_cache: dict = {"ts": 0.0, "value": None}


def vram_total_gb() -> float | None:
    """Return the first GPU's memory capacity in GiB, cached for 60 seconds, or None."""
    now = time.time()
    if _total_cache["value"] is not None and now - _total_cache["ts"] < 60:
        return _total_cache["value"]
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.total", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5,
            creationflags=NO_WINDOW,
        ).stdout.strip().splitlines()[0]
        value = round(int(out.strip()) / 1024, 1)
    except Exception:
        value = None
    _total_cache.update(ts=now, value=value)
    return value


def normalize_vram_setting(value):
    if value == "auto":
        return "auto"
    if isinstance(value, bool):
        raise ValueError("GPU memory must be automatic or a positive number of GiB")
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError("GPU memory must be automatic or a positive number of GiB") from None
    if not math.isfinite(number) or number <= 0:
        raise ValueError("GPU memory must be automatic or a positive number of GiB")
    return number


def effective_vram_gb(cfg) -> float | None:
    """Resolve the configured GPU budget, bounded by the detected card capacity."""
    setting = (cfg.data.get("hardware", {}) or {}).get("vram_gb", "auto")
    detected = vram_total_gb()
    try:
        setting = normalize_vram_setting(setting)
    except ValueError:
        setting = "auto"
    if setting == "auto":
        return detected
    return min(setting, detected) if detected else setting


def profile_min_vram(profile: dict) -> float:
    """Return the profile requirement; unknown requirements use a prohibitive default."""
    try:
        return float(profile.get("min_vram_gb", 1e9))
    except (TypeError, ValueError):
        return 1e9


def fitting_profiles(cfg, model_key: str, vram_gb: float | None) -> dict[str, dict]:
    """Return profiles compatible with a known GPU capacity budget."""
    profiles = cfg.kv_cache_profiles(model_key)
    if vram_gb is None:
        return profiles
    if cfg.model(model_key).get("adaptive_runtime"):
        from dataclasses import replace
        from harness.hardware import detect_hardware
        from harness.runtime_plan import choose_plan, GIB
        from harness.model_catalog import FLASH_NEXT_Q3
        hw = detect_hardware()
        # The picker must not count the currently running model as another app.
        hw = replace(hw, vram_total=int(vram_gb * GIB), vram_available=int(vram_gb * GIB))
        layout = cfg.model(model_key).get("layout_hint", {}).get("layout", FLASH_NEXT_Q3["layout_hint"]["layout"])
        result = {}
        for key, prof in profiles.items():
            try:
                choose_plan(hw, layout, prof["ctx_size"])
                result[key] = prof
            except RuntimeError:
                pass
        return result
    from harness.measured_profiles import gpu_class
    return {key: prof for key, prof in profiles.items()
            if (prof["gpu_class"] == gpu_class(vram_gb) if "gpu_class" in prof
                else profile_min_vram(prof) <= vram_gb)}


def offered_profiles(cfg, model_key, vram_gb):
    profiles = fitting_profiles(cfg, model_key, vram_gb)
    if cfg.model(model_key).get("adaptive_runtime"):
        ceiling = cfg.data.get("_recovered_contexts", {}).get(model_key, 262144)
        ordered = sorted(profiles, key=lambda key: profiles[key]["ctx_size"], reverse=True)
        ordered = [key for key in ordered if profiles[key]["ctx_size"] <= ceiling]
        return {key: profiles[key] for key in ordered[:2]}
    return profiles


def best_fit(cfg, vram_gb: float | None) -> tuple[str, str] | None:
    """Choose a model and context profile for the available capacity.

    Prefer the requested model, then its family, followed by other models. Within that priority, prefer the largest compatible context. Return None if no profile fits or capacity is unknown."""
    if vram_gb is None:
        return None
    default_key = cfg.model_key()
    def family(key):
        return cfg.model(key).get("family", "qwen" if key in ("q3", "q4", "q5") else key)
    related = [k for k in cfg.data["models"] if k != default_key and family(k) == family(default_key)]
    ordered = [default_key] + related + [k for k in cfg.data["models"] if k != default_key and k not in related]
    # A model that is not downloaded by default is not chosen by default either.
    # The smallest quant buys context by giving up weight quality, and that is a
    # trade the owner makes deliberately, not one made quietly on their behalf.
    ordered = [k for k in ordered
               if k == default_key or not cfg.model(k).get("optional_download")]
    best: tuple | None = None  # (order, Q8, full cache, context, plain, has_limit, model, profile)
    for order, key in enumerate(ordered):
        for prof_key, prof in fitting_profiles(cfg, key, vram_gb).items():
            candidate = (-order, prof.get("cache_type", prof_key) == "q8_0",
                         # A reduced value cache is an option, never the default:
                         # it costs recall over a long conversation, unmeasurably.
                         not prof.get("value_cache_type"),
                         int(prof.get("ctx_size", 0)),
                         prof.get("speculative") is None, "min_vram_gb" in prof, key, prof_key)
            if best is None or candidate > best:
                best = candidate
    if best is None:
        return None
    return best[6], best[7]


def fits(cfg, model_key: str, profile_key: str, vram_gb: float | None) -> bool:
    """Check profile compatibility; unknown capacity retains known profiles."""
    return profile_key in fitting_profiles(cfg, model_key, vram_gb)


def lower_memory_profiles(cfg, model_key=None):
    """Ordered fallback ladder under memory pressure.

    The ladder keeps the model, cache precision and weight placement (GPU class).
    A session that started on a speculative (MTP) profile first drops the draft
    at the same context, then interleaves lower contexts as MTP/plain pairs.
    Plain selections never gain MTP during recovery; ``_recovery_origin_mtp``
    preserves the original intent between the ladder's steps.
    """
    key = model_key or cfg.model_key()
    profiles = cfg.kv_cache_profiles(key)
    current_key = cfg.kv_cache_mode(key)
    current = profiles.get(current_key, {})
    context = cfg.context_size(key)
    minimum = 131072 if cfg.model(key).get("adaptive_runtime") else 0
    precision = current.get("cache_type", current_key)
    group = {name: profile for name, profile in profiles.items()
             if profile.get("cache_type", name) == precision
             and profile.get("gpu_class") == current.get("gpu_class")}
    current_mtp = current.get("speculative") == "mtp"
    keep_mtp = current_mtp or key in cfg.data.get("_recovery_origin_mtp", ())
    ladder: list[str] = []
    if current_mtp:
        twin = next((n for n, p in group.items()
                     if not p.get("speculative") and int(p.get("ctx_size", 0)) == context), None)
        if twin:
            ladder.append(twin)
    for size in sorted({int(p.get("ctx_size", 0)) for p in group.values()
                        if minimum <= int(p.get("ctx_size", 0)) < context}, reverse=True):
        at_size = [(n, p) for n, p in group.items() if int(p.get("ctx_size", 0)) == size]
        if keep_mtp:
            ladder += [n for n, p in at_size if p.get("speculative")]
        ladder += [n for n, p in at_size if not p.get("speculative")]
    return ladder


def download_keys(cfg, vram_gb: float | None) -> list[str]:
    """Select models with a compatible profile; unknown GPU capacity keeps all candidates."""
    keys = [key for key, model in cfg.data["models"].items()
            if not model.get("optional_download") or key == cfg.model_key()]
    if vram_gb is None:
        return keys
    fitting = [k for k in keys if fitting_profiles(cfg, k, vram_gb)]
    return fitting
