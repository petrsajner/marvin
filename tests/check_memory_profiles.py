"""Qualify existing model profiles under measured GPU budgets on this host.

This simulates GPU capacity on the current card, not the compute speed or driver
of a physical 16/24 GiB card. User settings/data are never used as test outputs.
"""
from pathlib import Path
import argparse
import json
import subprocess
import sys
import threading
import time

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import psutil
import requests
from harness import servermgmt
from harness.config import load_config
from tests.check_runtime_upgrade import Probes, make_config, save, stop_owned

CASES = [
    (16, "q3", "q8_0_32k"),
    (24, "q4", "q8_0_compact"), (24, "q4", "f16_compact"), (24, "q5", "q8_0_compact"),
    (24, "nemotron_q4", "q8_0_256k_spill"), (24, "nemotron_q4", "q8_0_512k_spill"),
    (32, "q3", "q8_0_256k"), (32, "q4", "q8_0"), (32, "q5", "q8_0"),
    (32, "ornith_q5", "q8_0"), (32, "nemotron_q4", "q8_0_512k"),
    (32, "nemotron_q5", "q8_0_256k"), (32, "flash_next_q3", "q8_0_256k"),
]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cap", type=int)
    parser.add_argument("--model")
    parser.add_argument("--profile")
    parser.add_argument("--ubatch", type=int)
    parser.add_argument("--only", default="chat,tool_roundtrip,vision,stop_stream")
    parser.add_argument("--input-tokens", type=int, default=0)
    args = parser.parse_args()
    if any((p.info["name"] or "").lower() == "llama-server.exe" for p in psutil.process_iter(["name"])):
        raise RuntimeError("Another model server is running; finish it before this qualification")
    output = args.output.resolve()
    if (output / "results.json").exists():
        raise RuntimeError("Use a new qualification output directory")
    original = load_config()
    original.data["server"].setdefault("extra_args", []).extend(["--fit", "off"])
    if args.ubatch:
        original.data["server"]["extra_args"].extend(["-b", "1024", "-ub", str(args.ubatch)])
    if args.input_tokens:
        original.data["_audit_input_tokens"] = args.input_tokens
    report = {"scope": "Measured total GPU usage under a simulated capacity limit on the current GPU; not a physical small-card test", "cases": {}}
    for cap, key, profile in CASES:
        if args.cap and cap != args.cap or args.model and key != args.model or args.profile and profile != args.profile:
            continue
        cid = f"{cap}/{key}/{profile}"
        cfg = make_config(original, output / str(cap) / key / profile,
                          original.path("paths.llama_dir"), key, profile, 8087)
        cfg.data["hardware"]["vram_gb"] = cap
        case = {"requested_context": cfg.context_size(), "checks": {}, "peak_vram_gib": 0,
                "minimum_free_ram_gib": psutil.virtual_memory().available / 1024**3}
        report["cases"][cid] = case
        finished = threading.Event()
        started = time.monotonic()
        def watch(cfg=cfg, case=case, cap=cap, finished=finished):
            while not finished.wait(.5):
                free = psutil.virtual_memory().available / 1024**3
                case["minimum_free_ram_gib"] = min(case["minimum_free_ram_gib"], free)
                try:
                    text = subprocess.check_output(["nvidia-smi", "--query-gpu=memory.total,memory.free,memory.used", "--format=csv,noheader,nounits"],
                                                   text=True, timeout=3, creationflags=0x08000000)
                    total, free_gpu, used_gpu = [float(x) / 1024 for x in text.strip().splitlines()[0].split(",")]
                    used = total - free_gpu
                    case["peak_vram_gib"] = max(case["peak_vram_gib"], used)
                    case["peak_reported_used_vram_gib"] = max(case.get("peak_reported_used_vram_gib", 0), used_gpu)
                except (ValueError, subprocess.SubprocessError):
                    used = 0
                if free < 4 or used > cap:
                    case["guard"] = f"Free RAM {free:.2f} GiB, total GPU {used:.2f} GiB, budget {cap} GiB"
                    stop_owned(cfg)
                    return
        watcher = threading.Thread(target=watch, daemon=True)
        watcher.start()
        print("START", cid, flush=True)
        probes = None
        try:
            if servermgmt.start(cfg, key) != 0:
                raise RuntimeError("Model did not start")
            case["load_seconds"] = time.monotonic() - started
            case["context"] = cfg.context_size()
            case["applied_profile"] = cfg.kv_cache_mode()
            props = requests.get(cfg.base_url + "/props", timeout=10).json()
            assert props.get("default_generation_settings", {}).get("n_ctx") == cfg.context_size()
            probes = Probes(cfg)
            for name in args.only.split(","):
                if name == "vision" and not cfg.mmproj_file():
                    continue
                evidence = getattr(probes, name)()
                case["checks"][name] = {"ok": True, "evidence": evidence}
                save(output / "results.json", report)
                print("PASS", cid, name, flush=True)
            case["ok"] = "guard" not in case
        except Exception as exc:
            case.update(ok=False, error=f"{type(exc).__name__}: {exc}")
            print("FAIL", cid, case["error"], flush=True)
        finally:
            if probes:
                probes.llm.client.close()
            finished.set()
            watcher.join(5)
            stop_owned(cfg)
            case["seconds"] = time.monotonic() - started
            plan = cfg.path("paths.runtime_dir") / "execution-plans" / (key + ".json")
            if plan.is_file():
                case["execution_plan"] = json.loads(plan.read_text())
            save(output / "results.json", report)
            print("END", cid, case["ok"], round(case["peak_vram_gib"], 2), flush=True)
    return 0 if report["cases"] and all(case["ok"] for case in report["cases"].values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
