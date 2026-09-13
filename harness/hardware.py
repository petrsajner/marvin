"""Read local CPU topology and available memory without changing OS configuration."""
from __future__ import annotations

import ctypes
from dataclasses import asdict, dataclass
import hashlib
import json
import os
import platform
import struct
import subprocess
import time

import psutil

NO_WINDOW = 0x08000000 if os.name == "nt" else 0


@dataclass(frozen=True)
class Hardware:
    cpu_name: str
    physical_cores: int
    logical_cpus: int
    performance_cpus: tuple[int, ...]
    physical_cpus: tuple[int, ...]
    ram_total: int
    ram_available: int
    gpu_name: str = ""
    gpu_uuid: str = ""
    driver: str = ""
    vram_total: int = 0
    vram_available: int = 0

    def fingerprint(self) -> str:
        stable = asdict(self)
        stable.pop("ram_available")
        stable.pop("vram_available")
        return hashlib.sha256(json.dumps(stable, sort_keys=True).encode()).hexdigest()


def cpu_sets() -> tuple[tuple[int, ...], tuple[int, ...]]:
    if os.name != "nt":
        return (), ()
    try:
        fn = ctypes.windll.kernel32.GetSystemCpuSetInformation
        fn.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(ctypes.c_ulong), ctypes.c_void_p, ctypes.c_ulong]
        fn.restype = ctypes.c_bool
        required = ctypes.c_ulong()
        fn(None, 0, ctypes.byref(required), None, 0)
        if not 0 < required.value < 4 * 1024 * 1024:
            return (), ()
        buffer = ctypes.create_string_buffer(required.value)
        if not fn(buffer, required.value, ctypes.byref(required), None, 0):
            return (), ()
        rows = {}
        offset = 0
        while offset < required.value:
            size, kind = struct.unpack_from("<II", buffer, offset)
            if size < 20 or offset + size > required.value:
                return (), ()
            if kind == 0:
                group, logical, core, _, _, efficiency, flags = struct.unpack_from("<HBBBBBB", buffer, offset + 12)
                # Avoid CPU sets allocated exclusively to another process.
                if not flags & 2 or flags & 4:
                    rows.setdefault((group, core), (efficiency, group * 64 + logical))
            offset += size
        if not rows:
            return (), ()
        top = max(efficiency for efficiency, _ in rows.values())
        performance = tuple(sorted(cpu for efficiency, cpu in rows.values() if efficiency == top))
        physical = tuple(sorted(cpu for _, cpu in rows.values()))
        return performance, physical
    except (AttributeError, OSError, ValueError, struct.error):
        return (), ()


_gpu_cache = {"time": 0, "row": None}


def detect_hardware(*, fresh=False) -> Hardware:
    performance, physical = cpu_sets()
    memory = psutil.virtual_memory()
    physical_count = len(physical) or psutil.cpu_count(logical=False) or 1
    logical_count = psutil.cpu_count() or physical_count
    if fresh or time.monotonic() - _gpu_cache["time"] > 2:
        try:
            output = subprocess.run(["nvidia-smi", "--query-gpu=name,uuid,driver_version,memory.total,memory.free",
                "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=5,
                creationflags=NO_WINDOW)
            row = [s.strip() for s in output.stdout.splitlines()[0].split(",")]
            gpu = (row[0], row[1], row[2], int(row[3]) * 2**20, int(row[4]) * 2**20)
        except (OSError, ValueError, IndexError, subprocess.SubprocessError):
            gpu = ("", "", "", 0, 0)
        _gpu_cache.update(time=time.monotonic(), row=gpu)
    gpu = _gpu_cache["row"] or ("", "", "", 0, 0)
    return Hardware(platform.processor(), physical_count, logical_count, performance, physical,
                    memory.total, memory.available, *gpu)


def mask(cpus: tuple[int, ...]) -> str:
    return hex(sum(1 << cpu for cpu in cpus))
