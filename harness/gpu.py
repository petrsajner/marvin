"""Detekce VRAM a výběr model/KV kombinace, která se vejde na kartu.

Profil v configu může nést `min_vram_gb` (konzervativní odhad potřebné VRAM
včetně KV cache a rezervy). `hardware.vram_gb` v configu přepisuje detekci
(auto | číslo) - to je ruční přepínač grafické karty.
"""
from __future__ import annotations

import subprocess
import time
import math

NO_WINDOW = 0x08000000

_total_cache: dict = {"ts": 0.0, "value": None}


def vram_total_gb() -> float | None:
    """Celková VRAM první GPU v GB (nvidia-smi, 60 s cache); None = nedostupné."""
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
    """VRAM podle configu: hardware.vram_gb (auto|číslo) s fallbackem na detekci."""
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
    """Potřebná VRAM profilu; bez min_vram_gb považuj profil za neomezený (1e9)."""
    try:
        return float(profile.get("min_vram_gb", 1e9))
    except (TypeError, ValueError):
        return 1e9


def fitting_profiles(cfg, model_key: str, vram_gb: float | None) -> dict[str, dict]:
    """KV profily modelu, které se vejdou (bez min_vram_gb = legacy, povolené)."""
    profiles = cfg.kv_cache_profiles(model_key)
    if vram_gb is None:
        return profiles
    return {key: prof for key, prof in profiles.items()
            if profile_min_vram(prof) <= vram_gb}


def best_fit(cfg, vram_gb: float | None) -> tuple[str, str] | None:
    """Nejlepší (model, kv profil) pro danou VRAM.

    Pořadí: výchozí model má přednost; u něj největší kontext, který se vejde.
    Když výchozí model nemá nic, zkusí se ostatní modely (největší kontext).
    None = nic nevyhovuje (nebo VRAM neznámá).
    """
    if vram_gb is None:
        return None
    default_key = cfg.model_key()
    def family(key):
        return cfg.model(key).get("family", "qwen" if key in ("q3", "q4", "q5") else key)
    related = [k for k in cfg.data["models"] if k != default_key and family(k) == family(default_key)]
    ordered = [default_key] + related + [k for k in cfg.data["models"] if k != default_key and k not in related]
    best: tuple | None = None  # (order, ctx, has_limit, model, profile)
    for order, key in enumerate(ordered):
        for prof_key, prof in fitting_profiles(cfg, key, vram_gb).items():
            candidate = (-order, int(prof.get("ctx_size", 0)),
                         "min_vram_gb" in prof, key, prof_key)
            if best is None or candidate > best:
                best = candidate
    if best is None:
        return None
    return best[3], best[4]


def fits(cfg, model_key: str, profile_key: str, vram_gb: float | None) -> bool:
    """Vejde se konkrétní kombinace? (bez údaje o VRAM nebo legacy profil = True)."""
    if vram_gb is None:
        return True
    profile = cfg.kv_cache_profiles(model_key).get(profile_key)
    if profile is None:
        return True
    return profile_min_vram(profile) <= vram_gb


def lower_memory_profiles(cfg, model_key=None):
    key = model_key or cfg.model_key()
    profiles = cfg.kv_cache_profiles(key)
    current_key = cfg.kv_cache_mode(key)
    current = profiles.get(current_key, {})
    context = cfg.context_size(key)
    minimum = 131072 if cfg.model(key).get("adaptive_runtime") else 0
    current_gpu = profile_min_vram(current)
    candidates = []
    for name, profile in profiles.items():
        size = int(profile.get("ctx_size", 0))
        gpu = profile_min_vram(profile)
        if (name != current_key and minimum <= size <= context and gpu <= current_gpu
                and (size < context or gpu < current_gpu)):
            candidates.append((size, gpu, name))
    return [name for _, _, name in sorted(candidates, reverse=True)]


def download_keys(cfg, vram_gb: float | None) -> list[str]:
    """Modely ke stažení: aspoň jeden profil se vejde (bez VRAM dat = všechny)."""
    keys = [key for key, model in cfg.data["models"].items()
            if not model.get("optional_download") or key == cfg.model_key()]
    if vram_gb is None:
        return keys
    fitting = [k for k in keys if fitting_profiles(cfg, k, vram_gb)]
    return fitting or keys
