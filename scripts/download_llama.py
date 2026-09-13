"""Install the validated upstream Windows CUDA runtime, preserving a rollback copy."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from harness.config import load_config
from harness.runtime_update import BUILD, RELEASE, install_runtime, runtime_build


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="reinstall the validated runtime")
    args = parser.parse_args()
    cfg = load_config()
    if not args.force and runtime_build(cfg.llama_server_exe()) == BUILD:
        print(f"[OK] Validated llama.cpp {RELEASE} is already installed")
        return 0
    try:
        from harness import servermgmt
        if servermgmt._managed_process(cfg) is not None:
            print("[ERROR] Stop the model before updating its runtime.")
            return 1
        server = install_runtime(cfg.path("paths.llama_dir"), cfg.path("paths.runtime_dir"))
        print(f"[DONE] Validated llama.cpp {RELEASE}: {server}")
        return 0
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"[ERROR] Runtime installation failed: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
