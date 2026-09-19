"""Start the Marvin workspace.

    .venv/Scripts/python marvin_web.py   ->  http://127.0.0.1:7860

This exists for one reason that is not obvious: the launcher starts it with
pythonw, which has no console, so sys.stdout and sys.stderr are None. Anything
that prints then raises and the process dies without saying why. The redirection
below has to happen before the first import that might print, which is why this
is a separate file rather than a __main__ block inside the package.

It replaced webapp.py, which had grown a second interface behind it. The Gradio
surface is gone; this serves the React workspace and the local API.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

if sys.stdout is None or sys.stderr is None:
    _logdir = ROOT / "runtime"
    _logdir.mkdir(parents=True, exist_ok=True)
    _lf = open(_logdir / "webapp.log", "a", buffering=1, encoding="utf-8")
    _lf.write(f"\n===== WORKSPACE {time.strftime('%Y-%m-%d %H:%M:%S')} =====\n")
    sys.stdout = _lf
    sys.stderr = _lf

if __name__ == "__main__":
    from harness.web_api import main
    main()
