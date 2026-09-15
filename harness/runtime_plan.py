"""Per-machine execution planning for large offloaded models; legacy profiles are unchanged."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import copy
import json
from pathlib import Path

from harness.changes import atomic_write_text
from harness.gguf_metadata import model_memory_layout
from harness.hardware import Hardware, detect_hardware, mask
from harness.model_files import local_model_dir, model_ready, signature

GIB = 1024**3
PLANNER_VERSION = 4
# Residual allocations measured with b10935, Q3 weights and microbatch 256.
# Provenance: docs/design/measurements/2026-09-15.json, flash-final-*-cpu32.
GPU_WORKSPACE_BYTES = round(2.4552589058876038 * GIB)
HOST_WORKSPACE_GIB = {131072: 3.91606640625, 196608: 3.97206640625, 262144: 6.78706640625}


@dataclass(frozen=True)
class RuntimePlan:
    context: int
    cpu_expert_layers: int
    threads: int
    batch_threads: int
    estimated_gpu_bytes: int
    estimated_host_bytes: int
    hardware_fingerprint: str
    args: tuple[str, ...]
    vram_budget_bytes: int = 0
    required_available_ram_bytes: int = 0


def choose_plan(hardware: Hardware, layout: dict, context: int, *, vram_limit=None,
                cpu_expert_layers=None) -> RuntimePlan:
    if context not in (131072, 196608, 262144):
        raise ValueError("Flash-Next requires a supported context of at least 128k")
    if hardware.vram_total <= 0:
        raise RuntimeError("This model needs a supported NVIDIA graphics card.")
    capacity = hardware.vram_total
    available = hardware.vram_available
    try:
        vram_limit = float(vram_limit)
    except (TypeError, ValueError):
        vram_limit = 0
    if vram_limit > 0:
        # A manual setting may constrain the real card, never invent more memory.
        other_usage = max(0, hardware.vram_total - hardware.vram_available)
        capacity = min(capacity, int(vram_limit * GIB))
        available = min(available, max(0, capacity - other_usage))
    if capacity < 15 * GIB:
        raise RuntimeError("Flash-Next requires a supported GPU memory profile (16 GB or larger).")
    # Q8 attention + indexer, plus the measured recurrent/compute/vision residual.
    kv = int(12 * (2 * 2 * 256 + 128) * context * 34 / 32)
    common = layout["common_bytes"] + layout["projector_bytes"] + kv + GPU_WORKSPACE_BYTES
    expert_bytes = layout["expert_layer_bytes"]
    if len(expert_bytes) != 48:
        raise ValueError("Unsupported expert-layer layout")
    cpu_layers = None
    gpu_bytes = 0
    # CPU31 spilled into shared GPU memory in the 32 GB qualification. The
    # measured CPU32/39/46 placements are starting bounds, not generic reserves.
    floor = 32 if capacity <= 32 * GIB else 0
    if capacity < 31 * GIB:
        floor = 39 if capacity >= 23 * GIB else 46
    counts = [cpu_expert_layers] if cpu_expert_layers is not None else range(floor, len(expert_bytes) + 1)
    for count in counts:
        if not 0 <= count <= len(expert_bytes):
            raise ValueError("Invalid CPU expert placement")
        predicted = common + sum(expert_bytes[count:])
        if predicted <= available:
            cpu_layers, gpu_bytes = count, predicted
            break
    if cpu_layers is None:
        raise RuntimeError(f"Flash-Next needs more free GPU memory for {context // 1024}k context. "
                           f"The selected GPU budget has {available / GIB:.1f} GiB free.")
    # Working-set estimates are not initial-free-RAM requirements. Windows can
    # reclaim mapped pages and page out inactive applications before/while loading.
    working_ram = round(HOST_WORKSPACE_GIB[context] * GIB)
    host_bytes = sum(expert_bytes[:cpu_layers]) + working_ram
    if host_bytes > hardware.ram_total:
        raise RuntimeError(f"Not enough installed system memory for this Flash-Next placement: "
                           f"estimated model working set {host_bytes / GIB:.1f} GiB, "
                           f"installed {hardware.ram_total / GIB:.1f} GiB.")
    if capacity < 23 * GIB and hardware.ram_total <= 64 * GIB and context == 262144:
        raise RuntimeError("Flash-Next 256k with a 16 GB GPU and 64 GB RAM reached critical physical "
                           "memory in qualification. Try the next smaller context.")
    p_cpus = hardware.performance_cpus
    physical = hardware.physical_cpus
    batch_cpus = p_cpus or physical
    threads = min(len(p_cpus) or hardware.physical_cores, 16)
    batch_threads = min(len(batch_cpus) or hardware.physical_cores, 32)
    args = ["--n-cpu-moe", str(cpu_layers), "-t", str(max(1, threads)),
            "-tb", str(max(1, batch_threads)), "-b", "1024", "-ub", "256",
            "--fit", "off", "--cache-ram", "256"]
    if p_cpus:
        args += ["--cpu-mask", mask(p_cpus[:threads]), "--cpu-strict", "1"]
    if batch_cpus:
        args += ["--cpu-mask-batch", mask(batch_cpus[:batch_threads]), "--cpu-strict-batch", "1"]
    return RuntimePlan(context, cpu_layers, threads, batch_threads, gpu_bytes, host_bytes,
                       hardware.fingerprint(), tuple(args), capacity, 0)


def inspect_layout(models_dir: Path, spec: dict) -> dict:
    if not model_ready(models_dir, spec):
        hint = spec.get("layout_hint", {})
        if hint.get("manifest_signature") == signature(spec) and hint.get("layout"):
            return copy.deepcopy(hint["layout"])
        raise RuntimeError("The complete model and its image support files must be downloaded first.")
    directory = local_model_dir(models_dir, spec)
    cache = directory / ".marvin-memory-layout.json"
    try:
        data = json.loads(cache.read_text(encoding="utf-8"))
        if data.get("signature") == signature(spec) and data.get("version") == PLANNER_VERSION:
            return data["layout"]
    except (OSError, ValueError, KeyError):
        pass
    layout = model_memory_layout(models_dir, spec)
    atomic_write_text(cache, json.dumps({"signature": signature(spec), "version": PLANNER_VERSION, "layout": layout}, indent=2))
    return layout


def plan_for(cfg, key=None, context=None, *, hardware=None) -> RuntimePlan | None:
    key = key or cfg.model_key()
    spec = cfg.model(key)
    if not spec.get("adaptive_runtime"):
        return None
    layout = inspect_layout(cfg.path("paths.models_dir"), spec)
    hw = hardware or detect_hardware(fresh=True)
    requested = context or cfg.context_size(key)
    candidates = sorted({p["ctx_size"] for p in cfg.kv_cache_profiles(key).values()
                         if 131072 <= p["ctx_size"] <= requested}, reverse=True)
    failure = None
    plan = None
    for candidate in candidates:
        try:
            frozen = cfg.data.get("_recovery_placement", {})
            plan = choose_plan(hw, layout, candidate,
                               vram_limit=cfg.data.get("hardware", {}).get("vram_gb"),
                               cpu_expert_layers=frozen.get("cpu_expert_layers") if frozen.get("model") == key else None)
            break
        except RuntimeError as exc:
            failure = exc
    if plan is None:
        raise failure or ValueError("Flash-Next requires at least 128k context")
    for profile, values in cfg.kv_cache_profiles(key).items():
        if values["ctx_size"] == plan.context and values.get("cache_type") == "q8_0":
            cfg.set_kv_cache_mode(key, profile)
            break
    # This record is diagnostic. Available RAM/VRAM is always re-read on the next start.
    record = {"version": PLANNER_VERSION, "model": key, "requested_context": requested,
              "weights_verified": cfg.model_ready(key),
              "model_signature": signature(spec), **asdict(plan)}
    target = cfg.path("paths.runtime_dir") / "execution-plans" / (key + ".json")
    atomic_write_text(target, json.dumps(record, indent=2))
    return plan
