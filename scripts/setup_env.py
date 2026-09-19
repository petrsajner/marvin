"""Prepare Python dependencies, llama.cpp and configured GGUF models.

Run with the virtual environment's Python. --skip-models keeps existing weights; --model all selects every model instead of the configured default."""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def pip_install() -> int:
    print("=" * 60)
    print("[1/3] Installing Python dependencies (requirements.txt) ...")
    print("=" * 60)
    from harness.dependencies import sync_dependencies
    return sync_dependencies(ROOT / "requirements.txt", ROOT / ".venv")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--skip-models", action="store_true")
    ap.add_argument("--model", default="default")
    args = ap.parse_args()

    rc = pip_install()
    if rc:
        return rc

    # Import these modules after dependency installation because they require third-party packages.
    import download_llama
    import download_models

    print()
    print("=" * 60)
    print("[2/3] llama.cpp CUDA binaries ...")
    print("=" * 60)
    sys.argv = [sys.argv[0]]  # isolate argv for argparse in child scripts
    rc = download_llama.main()
    if rc:
        return rc

    if args.skip_models:
        print("\n[3/3] Models skipped (--skip-models).")
        return 0

    print()
    print("=" * 60)
    print("[3/3] GGUF models from Hugging Face (unsloth/Qwen3.8-27B-GGUF) ...")
    print("=" * 60)
    sys.argv = [sys.argv[0], "--model", args.model]
    rc = download_models.main()
    if rc:
        return rc

    print()
    print("=" * 60)
    print("DONE! Next steps:")
    print("  1) start server:  .venv/Scripts/python scripts/server.py start")
    print("  2) TUI:           .venv/Scripts/python tui.py")
    print("     Workspace:     .venv/Scripts/python marvin_web.py  → http://127.0.0.1:7860")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
