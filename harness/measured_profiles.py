"""Owner-approved profiles from the 2026-09-15 qualification (see docs/design).

GPU classes describe the menu, while min_vram_gb records measured model allocation.
The latter excludes desktop usage and is not an invented capacity reservation.
Smaller-card placements were measured on a 5090, not on physical 16/24 GB cards.
"""
from __future__ import annotations

import copy

MEASUREMENT_ID = "profile-remeasurement-2026-09-15"


def profile(context, gpu_class, measured, *, precision="q8_0", cpu_layers=0, cpu_vision=False):
    args = ["--fit", "off"]
    if cpu_layers:
        args += ["--n-cpu-moe", str(cpu_layers)]
    if cpu_vision:
        args += ["--no-mmproj-offload"]
    return {"cache_type": precision, "ctx_size": context * 1024,
            "gpu_class": gpu_class, "min_vram_gb": measured,
            "label": f"{'Q8' if precision == 'q8_0' else 'F16'} · {context}k",
            "server_args": args, "measurement_id": MEASUREMENT_ID}


PROFILES = {
    "q3": {
        "q8_0_64k": profile(64, 16, 13.617, cpu_vision=True),
        "q8_0": profile(48, 16, 13.008, cpu_vision=True),
        "q8_0_128k": profile(128, 24, 17.162),
        "q8_0_96k": profile(96, 24, 16.147),
    },
    "q4": {
        "q8_0": profile(256, 32, 26.137),
        "q8_0_192k": profile(192, 32, 23.502),
        "f16": profile(128, 32, 24.371, precision="f16"),
        "f16_96k": profile(96, 32, 22.363, precision="f16"),
        "q8_0_compact": profile(96, 24, 19.925),
        "q8_0_64k": profile(64, 24, 18.858),
    },
    "q5": {
        "q8_0": profile(192, 32, 26.580),
        "q8_0_128k": profile(128, 32, 24.189),
        "f16_128k": profile(128, 32, 27.654, precision="f16"),
        "f16": profile(96, 32, 25.441, precision="f16"),
        "q8_0_96k": profile(96, 24, 21.923, cpu_vision=True),
        "q8_0_compact": profile(64, 24, 20.723, cpu_vision=True),
    },
    "ornith_q5": {
        "q8_0_256k": profile(256, 32, 27.906),
        "q8_0_192k": profile(192, 32, 27.129),
    },
    "nemotron_q4": {
        "q8_0_512k": profile(512, 32, 25.420),
        "q8_0_256k": profile(256, 32, 24.311),
        "q8_0_512k_spill": profile(512, 24, 21.278, cpu_layers=14),
        "q8_0_256k_spill": profile(256, 24, 20.641, cpu_layers=12),
    },
    "nemotron_q5": {
        "q8_0_512k": profile(512, 32, 29.085, cpu_layers=2),
        "q8_0_256k": profile(256, 32, 28.883),
        "q8_0_512k_spill": profile(512, 24, 21.499, cpu_layers=21),
        "q8_0_256k_spill": profile(256, 24, 20.899, cpu_layers=18),
    },
}


def install_profiles(models):
    for key, profiles in PROFILES.items():
        models[key]["kv_cache_profiles"] = copy.deepcopy(profiles)
        models[key]["kv_cache"] = next(iter(profiles))
        models[key]["ctx_size"] = next(iter(profiles.values()))["ctx_size"]
    models["ornith_q5"]["alias"] = "Ornith 1.5 35B-A3B Abliterated Q5 (23.0 GB, reasoning)"


def gpu_class(capacity):
    # Reported usable capacity is slightly below the card's nominal size.
    return 32 if capacity >= 31 else 24 if capacity >= 23 else 16 if capacity >= 15 else 0


def placement(cfg, key=None):
    key = key or cfg.model_key()
    override = cfg.data.get("_recovery_placement", {})
    if override.get("model") == key:
        return copy.deepcopy(override)
    values = cfg.kv_cache_profiles(key).get(cfg.kv_cache_mode(key), {})
    result = {"model": key, "server_args": list(values.get("server_args", []))}
    active = cfg.data.get("_active_placement", {})
    if active.get("model") == key:
        result = copy.deepcopy(active)
    return result


def freeze_placement(cfg, key=None):
    """Recovery changes cache length only, even when the next preset offloads less."""
    cfg.data["_recovery_placement"] = placement(cfg, key)
