"""Owner-approved profiles from the 2026-09-15 qualification (see docs/design).

GPU classes describe the menu, while min_vram_gb records measured model allocation.
The latter excludes desktop usage and is not an invented capacity reservation.
Smaller-card placements were measured on a 5090, not on physical 16/24 GB cards.

Speculative ("MTP") variants reuse the 2026-09-15 plain measurements plus the
draft-model allocation measured on 2026-09-17; see docs/design/mtp-profiles.md.
"""
from __future__ import annotations

import copy

MEASUREMENT_ID = "profile-remeasurement-2026-09-15"
MTP_MEASUREMENT_ID = "mtp-speculative-2026-09-17"


SHORT = {"q8_0": "Q8", "f16": "F16", "q5_1": "Q5", "q4_0": "Q4"}


def profile(context, gpu_class, measured, *, precision="q8_0", value_precision=None,
            cpu_layers=0, cpu_vision=False, speculative=False, gpu_vision=False,
            measurement=None):
    """One approved placement. `measured` is what it really allocated on a GPU.

    Keys and values are separate because they do not tolerate quantisation
    equally: values take it far better, so a q8_0 key with a q4_0 value is a real
    middle step rather than a compromise in name only."""
    args = ["--fit", "off"]
    if cpu_layers:
        args += ["--n-cpu-moe", str(cpu_layers)]
    if cpu_vision:
        args += ["--no-mmproj-offload"]
    values = value_precision or precision
    label = SHORT.get(precision, precision)
    if values != precision:
        label += "/" + SHORT.get(values, values)
        label += " cache"
    label += f" · {context}k"
    if gpu_vision:
        # Worth saying only where the alternative is the processor, which is the
        # case on a 16 GB card and nowhere else.
        label += " · vision on GPU"
    if speculative:
        label += " · MTP"
    spec = {"cache_type": precision, "ctx_size": context * 1024,
            "gpu_class": gpu_class, "min_vram_gb": measured,
            "label": label, "server_args": args,
            "measurement_id": (measurement or
                               (MTP_MEASUREMENT_ID if speculative else MEASUREMENT_ID))}
    if values != precision:
        spec["value_cache_type"] = values
    if speculative:
        # The draft model is resolved and verified by servermgmt at launch time;
        # it is deliberately not part of server_args so recovery can toggle it.
        spec["speculative"] = "mtp"
    return spec


SMALL_CARD_MEASUREMENT = "profiles-16gb-2026-09-19"

# Strata (docs/design/2026-10-05-strata-backend.md), approved by the owner on
# 2026-10-07 from docs/design/strata-qualification-2026-10-07.md. The model
# entries stay behind the strata.enabled setting until Marvin prepares the engine.
STRATA_MEASUREMENT_ID = "strata-qualification-2026-10-07"


def strata_profile(context, gpu_class, ram_class, measured, *, mode="normal", kv_resident=False,
                   expert_cache=None, measurement=STRATA_MEASUREMENT_ID):
    """One Strata placement: int8 KV with MTP, for one GPU class and one RAM class.

    Modes: "normal" keeps every expert in RAM; "resident" page-locks the experts
    the GPU does not hold, as far as the free RAM allows, and reads the rest from
    the GGUF files in place. `kv_resident` keeps the whole KV cache in RAM, which
    leaves a 16 GB card more room for experts. `expert_cache` fixes the GPU's
    expert cache (a byte budget in largest-expert units) at what was measured to
    fit the class; without it the engine fills the free VRAM.

    The label reads like any other 8-bit cache profile in the picker (owner's
    choice, 2026-10-06); cache_type keeps the engine's own name."""
    engine_args = ["--resident-experts"] if mode == "resident" else []
    if kv_resident:
        engine_args += ["--kv-resident", "32768"]
    spec = {"cache_type": "int8", "ctx_size": context * 1024, "gpu_class": gpu_class, "ram_class": ram_class,
            "min_vram_gb": measured, "label": f"Q8 · {context}k", "measurement_id": measurement,
            "engine_args": engine_args}
    if expert_cache:
        spec["expert_cache"] = expert_cache
    return spec


def strata_menu(rows):
    """Profiles from (RAM class, GPU class, mode, KV in RAM, ((context, measured GiB, cache), ...)) rows."""
    menu = {}
    for ram, gpu, mode, kv_resident, contexts in rows:
        for context, measured, cache in contexts:
            menu[f"int8_{context}k_r{ram}g{gpu}"] = strata_profile(
                context, gpu, ram, measured, mode=mode, kv_resident=kv_resident, expert_cache=cache)
    return menu

PROFILES = {
    # The smallest quant. Two gigabytes less than IQ3_S, which buys either twice
    # the context or the vision projector back on the graphics card.
    "q2": {
        "q8_0_96k_vision": profile(96, 16, 14.19, gpu_vision=True,
                                   measurement=SMALL_CARD_MEASUREMENT),
        "q8_0_64k_vision": profile(64, 16, 12.96, gpu_vision=True,
                                   measurement=SMALL_CARD_MEASUREMENT),
        "q8_0_128k": profile(128, 16, 14.31, cpu_vision=True,
                             measurement=SMALL_CARD_MEASUREMENT),
        "q4_0_192k": profile(192, 16, 13.73, precision="q4_0", cpu_vision=True,
                             measurement=SMALL_CARD_MEASUREMENT),
        # On a large card the weights are small and the context fills it instead:
        # 256k with the projector on the GPU, at 97 tokens a second against 62 for
        # Q5. 384k and 512k were measured to fit and are deliberately not offered,
        # because no Qwen profile here has been approved beyond 256k.
        "q8_0_256k": profile(256, 32, 20.27, gpu_vision=True,
                             measurement=SMALL_CARD_MEASUREMENT),
    },
    "q3": {
        "q8_0_64k": profile(64, 16, 13.617, cpu_vision=True),
        "q8_0": profile(48, 16, 13.008, cpu_vision=True),
        "q8_0v4_96k": profile(96, 16, 14.08, value_precision="q4_0", cpu_vision=True,
                              measurement=SMALL_CARD_MEASUREMENT),
        "q4_0_128k": profile(128, 16, 14.05, precision="q4_0", cpu_vision=True,
                             measurement=SMALL_CARD_MEASUREMENT),
        "q8_0_128k": profile(128, 24, 17.162),
        "q8_0_96k": profile(96, 24, 16.147),
    },
    "q4": {
        "q8_0": profile(256, 32, 26.137),
        "q8_0_mtp": profile(256, 32, 28.982, speculative=True),
        "q8_0_192k": profile(192, 32, 23.502),
        "q8_0_192k_mtp": profile(192, 32, 26.033, speculative=True),
        "f16": profile(128, 32, 24.371, precision="f16"),
        "f16_96k": profile(96, 32, 22.363, precision="f16"),
        "q8_0_compact": profile(96, 24, 19.925),
        "q8_0_compact_mtp": profile(96, 24, 21.901, speculative=True),
        "q8_0_64k": profile(64, 24, 18.858),
        "q8_0_64k_mtp": profile(64, 24, 20.750, speculative=True),
    },
    "q5": {
        "q8_0": profile(192, 32, 26.580),
        "q8_0_mtp": profile(192, 32, 29.126, speculative=True),
        "q8_0_128k": profile(128, 32, 24.189),
        "q8_0_128k_mtp": profile(128, 32, 26.317, speculative=True),
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
    # Measured server VRAM and the cache budgets of the 2026-10-07 record. Below
    # 64 GB of RAM the resident mode won everywhere; with 64 GB a 16 GB card keeps
    # the KV cache in RAM.
    "flash_next_strata": strata_menu([
        (64, 32, "normal", False, ((256, 30.535, None), (128, 30.56, None))),
        (64, 24, "normal", False, ((256, 21.943, 4110), (128, 21.945, 4882))),
        (64, 16, "normal", True, ((256, 14.344, 2240), (128, 14.345, 2330))),
        (48, 32, "resident", False, ((256, 30.468, None), (128, 30.346, None))),
        (48, 24, "resident", False, ((256, 21.941, 4118), (128, 21.942, 4890))),
        # 128k with its own larger cache ran out of memory on the long input; this
        # is the 256k placement with a smaller KV, as recovery from 256k runs it.
        (48, 16, "resident", False, ((256, 14.349, 1054), (128, 14.349, 1054))),
        (32, 32, "resident", False, ((256, 30.469, None), (128, 30.401, None))),
        (32, 24, "resident", False, ((256, 21.94, 4129), (128, 21.941, 4901))),
        (32, 16, "resident", False, ((256, 14.345, 1065), (128, 14.344, 1837))),
    ]),
    "flash_next_strata_iq2": strata_menu([
        (64, 32, "normal", False, ((256, 30.081, None), (128, 30.518, None))),
        (64, 24, "normal", False, ((256, 21.95, 7921), (128, 21.95, 9282))),
        (64, 16, "normal", True, ((256, 14.349, 4619), (128, 14.35, 4780))),
        # The 48 GB / 256k run lost its server's VRAM counter; the placement is the
        # 64 GB one, which RAM does not change.
        (48, 32, "normal", False, ((256, 30.081, None), (128, 30.411, None))),
        (48, 24, "normal", False, ((256, 21.95, 7921), (128, 21.95, 9282))),
        (48, 16, "normal", False, ((256, 14.348, 2517), (128, 14.348, 3878))),
        (32, 32, "resident", False, ((256, 30.332, None), (128, 30.342, None))),
        (32, 24, "resident", False, ((256, 21.952, 7940), (128, 21.946, 9300))),
        (32, 16, "resident", False, ((256, 14.349, 2535), (128, 14.349, 3896))),
    ]),
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


def ram_class(installed_gib):
    """The RAM class of the installed memory; Windows reports a little less than the modules' size.
    More than 64 GB uses the 64 GB profiles."""
    return 64 if installed_gib >= 60 else 48 if installed_gib >= 44 else 32 if installed_gib >= 30 else 0


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
