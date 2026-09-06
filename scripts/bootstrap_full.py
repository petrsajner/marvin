"""Prepare Full's private venv locally; never uses system Python or the network."""
from pathlib import Path
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import venv

ROOT = Path(__file__).resolve().parent.parent


def prepare(root=ROOT):
    root = Path(root).resolve()
    private = root / "runtime/python"
    if Path(sys.base_prefix).resolve() != private.resolve():
        raise RuntimeError("Full bootstrap must run with runtime/python/python.exe -I")
    manifest = json.loads((root / "runtime/full-manifest.json").read_text(encoding="utf-8"))
    content = (root / "requirements.txt").read_bytes() + b"\nLOCK\n" + (root / "requirements-windows-py312.lock").read_bytes()
    digest = hashlib.sha256(content).hexdigest()
    if digest != manifest["requirements_digest"]:
        raise RuntimeError("Full payload does not match application dependencies")
    environment = root / ".venv"
    marker = environment / ".full-runtime.json"
    if marker.exists():
        stamp = json.loads(marker.read_text())
        if stamp == {"home": str(private), "digest": digest} and (environment / "Scripts/python.exe").is_file():
            print("[FULL] Private environment is ready.")
            return
    previous = None
    if environment.exists():
        previous = root / "runtime" / "environment-history" / str(time.time_ns())
        previous.parent.mkdir(parents=True, exist_ok=True)
        environment.rename(previous)
    try:
        print("[FULL] Creating isolated Python environment...", flush=True)
        venv.EnvBuilder(with_pip=True).create(environment)
        for pattern in ("msvcp140*.dll", "vcruntime140*.dll", "concrt140.dll"):
            for source in private.glob(pattern):
                shutil.copy2(source, environment / "Scripts" / source.name)
        print("[FULL] Installing bundled packages locally...", flush=True)
        shutil.copytree(root / "runtime/python-packages", environment / "Lib/site-packages", dirs_exist_ok=True)
        env = dict(os.environ)
        for key in ("PYTHONHOME", "PYTHONPATH", "PYTHONUSERBASE", "PYTHONSTARTUP"):
            env.pop(key, None)
        env["PYTHONNOUSERSITE"] = "1"
        subprocess.run([str(environment / "Scripts/python.exe"), "-I", "-c",
                        "import fastapi,uvicorn,openai,pypdfium2,gradio,webview,tkinter; print('FULL_IMPORTS_OK')"],
                       check=True, env=env, cwd=root)
        (environment / ".requirements.sha256").write_text(digest + "\n", encoding="ascii")
        marker.write_text(json.dumps({"home": str(private), "digest": digest}), encoding="utf-8")
        print("[FULL] Ready. Only model downloads remain.", flush=True)
    except BaseException:
        failed = root / "runtime" / ("failed-environment-" + str(time.time_ns()))
        if environment.exists():
            environment.rename(failed)
        if previous:
            previous.rename(environment)
        raise


if __name__ == "__main__":
    try:
        prepare()
    except BaseException:
        import traceback
        (ROOT / "runtime/full-setup-error.log").write_text(traceback.format_exc(), encoding="utf-8")
        raise
