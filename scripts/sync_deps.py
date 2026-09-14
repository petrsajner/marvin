"""Install dependencies only when the requirements content changes."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from harness.dependencies import dependencies_current, sync_dependencies


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true",
                        help="Check the marker without installing anything")
    parser.add_argument("--force", action="store_true",
                        help="Force pip install even when the marker is current")
    args = parser.parse_args()

    requirements = ROOT / "requirements.txt"
    venv_dir = ROOT / ".venv"
    if args.check:
        return 0 if dependencies_current(requirements, venv_dir) else 1
    return sync_dependencies(requirements, venv_dir, force=args.force)


if __name__ == "__main__":
    raise SystemExit(main())
