"""Hold GPU or system memory so this PC behaves like a machine with less of it (Strata qualification).

    python scripts/strata_ballast.py vram --leave-gib 14.3 --cudart <cudart64_13.dll>
    python scripts/strata_ballast.py ram --lock-gib 32

Strata sizes its expert cache from the free VRAM and its resident mode from the
free RAM, so a smaller card or less RAM has to be real for the engine to see it.
The process prints one JSON line starting with READY once the memory is held,
keeps it resident (VRAM is touched every few seconds, RAM is locked) and frees it
when its input closes or it is ended. See docs/design/2026-10-06-strata-qualification-plan.md.
"""
from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
import json
import sys
import threading

GIB = 1024**3
CHUNK = 256 * 1024**2


def hold_vram(leave_gib: float, cudart_path: str, device: int = 0) -> int:
    cudart = ctypes.CDLL(cudart_path)
    cudart.cudaMalloc.argtypes = [ctypes.POINTER(ctypes.c_void_p), ctypes.c_size_t]
    cudart.cudaMemset.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_size_t]
    cudart.cudaMemGetInfo.argtypes = [ctypes.POINTER(ctypes.c_size_t), ctypes.POINTER(ctypes.c_size_t)]
    if cudart.cudaSetDevice(device):
        print(json.dumps({"error": f"cudaSetDevice({device}) failed"}), flush=True)
        return 1
    free, total = ctypes.c_size_t(), ctypes.c_size_t()
    cudart.cudaMemGetInfo(ctypes.byref(free), ctypes.byref(total))
    target = int(leave_gib * GIB)
    blocks: list[tuple[ctypes.c_void_p, int]] = []
    size = CHUNK
    while free.value > target and size >= 16 * 1024**2:
        want = min(size, free.value - target)
        pointer = ctypes.c_void_p()
        if cudart.cudaMalloc(ctypes.byref(pointer), want) == 0:
            cudart.cudaMemset(pointer, 0, want)          # committed and resident, not only reserved
            blocks.append((pointer, want))
        else:
            size //= 2
        cudart.cudaDeviceSynchronize()
        cudart.cudaMemGetInfo(ctypes.byref(free), ctypes.byref(total))
    held = sum(n for _, n in blocks)
    print("READY " + json.dumps({"kind": "vram", "held_gib": round(held / GIB, 3),
                                 "free_gib": round(free.value / GIB, 3), "total_gib": round(total.value / GIB, 3),
                                 "target_free_gib": leave_gib}), flush=True)
    done = threading.Event()
    threading.Thread(target=lambda: (sys.stdin.read(), done.set()), daemon=True).start()
    while not done.wait(3.0):
        # Touching the blocks keeps them in dedicated memory instead of letting the
        # driver move an idle process's allocations out to shared memory.
        for pointer, n in blocks:
            cudart.cudaMemset(pointer, 1, min(n, 1024**2))
        cudart.cudaDeviceSynchronize()
    return 0


def hold_ram(lock_gib: float) -> int:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.VirtualAlloc.restype = ctypes.c_void_p
    kernel32.VirtualAlloc.argtypes = [ctypes.c_void_p, ctypes.c_size_t, wintypes.DWORD, wintypes.DWORD]
    kernel32.VirtualLock.argtypes = [ctypes.c_void_p, ctypes.c_size_t]
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    kernel32.SetProcessWorkingSetSizeEx.argtypes = [wintypes.HANDLE, ctypes.c_size_t, ctypes.c_size_t, wintypes.DWORD]
    size = int(lock_gib * GIB)
    slack = 256 * 1024**2
    # A hard minimum working set this large is what lets VirtualLock keep it all.
    if not kernel32.SetProcessWorkingSetSizeEx(kernel32.GetCurrentProcess(), size + slack, size + 2 * slack, 0x1):
        print(json.dumps({"error": f"SetProcessWorkingSetSizeEx failed ({ctypes.get_last_error()})"}), flush=True)
        return 1
    pointer = kernel32.VirtualAlloc(None, size, 0x3000, 0x04)   # MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE
    if not pointer:
        print(json.dumps({"error": f"VirtualAlloc failed ({ctypes.get_last_error()})"}), flush=True)
        return 1
    ctypes.memset(pointer, 1, size)
    if not kernel32.VirtualLock(pointer, size):
        print(json.dumps({"error": f"VirtualLock failed ({ctypes.get_last_error()})"}), flush=True)
        return 1
    import psutil
    print("READY " + json.dumps({"kind": "ram", "locked_gib": round(size / GIB, 3),
                                 "available_gib": round(psutil.virtual_memory().available / GIB, 3)}), flush=True)
    sys.stdin.read()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="kind", required=True)
    vram = sub.add_parser("vram")
    vram.add_argument("--leave-gib", type=float, required=True, help="free VRAM to leave for the model")
    vram.add_argument("--cudart", required=True, help="path to cudart64_13.dll")
    vram.add_argument("--device", type=int, default=0)
    ram = sub.add_parser("ram")
    ram.add_argument("--lock-gib", type=float, required=True, help="system RAM to lock away")
    args = parser.parse_args()
    if args.kind == "vram":
        return hold_vram(args.leave_gib, args.cudart, args.device)
    return hold_ram(args.lock_gib)


if __name__ == "__main__":
    raise SystemExit(main())
