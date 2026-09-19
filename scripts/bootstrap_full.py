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


def _forget_old_environments(root: Path, keep: int = 1) -> None:
    """One previous environment is a safety net; a collection is just disk use.

    Each rebuild moved the old environment aside and kept it for ever, so a
    machine that had been through a few releases carried several gigabytes of
    environments nobody would ever look at."""
    history = root / "runtime" / "environment-history"
    if history.is_dir():
        # The directory name is a timestamp, so newest sorts last.
        stale = sorted(item for item in history.iterdir() if item.is_dir())
        for item in stale[:max(0, len(stale) - keep)]:
            shutil.rmtree(item, ignore_errors=True)
    failed = sorted((root / "runtime").glob("failed-environment-*"))
    for item in failed[:max(0, len(failed) - keep)]:
        shutil.rmtree(item, ignore_errors=True)


def prepare(root=ROOT):
    root = Path(root).resolve()
    private = root / "runtime/python"
    if Path(sys.base_prefix).resolve() != private.resolve():
        raise RuntimeError("Full bootstrap must run with runtime/python/python.exe -I")
    manifest = json.loads((root / "runtime/full-manifest.json").read_text(encoding="utf-8"))
    content = (root / "requirements.txt").read_bytes() + b"\nLOCK\n" + (root / "requirements-windows-py312.lock").read_bytes()
    digest = hashlib.sha256(content).hexdigest()
    payload_current = digest == manifest["requirements_digest"]
    environment = root / ".venv"
    marker = environment / ".full-runtime.json"
    interpreter = environment / "Scripts/python.exe"
    if marker.exists():
        stamp = json.loads(marker.read_text())
        if stamp == {"home": str(private), "digest": digest} and interpreter.is_file():
            print("[FULL] Private environment is ready.")
            return
    # An application update can add a package while the bundled payload stays at
    # the version that shipped with Full. If the environment already satisfies the
    # current requirements there is nothing to prepare, and refusing to start over
    # an old payload would be absurd.
    installed = environment / ".requirements.sha256"
    if interpreter.is_file() and installed.is_file() \
            and installed.read_text(encoding="ascii").strip() == digest:
        print("[FULL] Private environment already satisfies the current requirements.")
        if not payload_current:
            print("[FULL] The bundled package payload is older than these requirements; "
                  "install the Full package for this version to refresh it.")
        marker.write_text(json.dumps({"home": str(private), "digest": digest}), encoding="utf-8")
        return
    # An environment that works but was installed for older requirements only needs
    # the difference. Demolishing it and rebuilding from a payload that is itself
    # older would throw away a working installation to no purpose.
    if interpreter.is_file() and not payload_current:
        source = root / "requirements-windows-py312.lock"
        if not source.is_file():
            source = root / "requirements.txt"
        print("[FULL] Updating the existing environment to the current requirements ...",
              flush=True)
        env = dict(os.environ)
        for key in ("PYTHONHOME", "PYTHONPATH", "PYTHONUSERBASE", "PYTHONSTARTUP"):
            env.pop(key, None)
        env["PYTHONNOUSERSITE"] = "1"
        completed = subprocess.run([str(interpreter), "-I", "-m", "pip", "install",
                                    "-r", str(source)], env=env, cwd=root)
        if completed.returncode == 0:
            installed.write_text(digest + "\n", encoding="ascii")
            marker.write_text(json.dumps({"home": str(private), "digest": digest}),
                              encoding="utf-8")
            print("[FULL] Environment updated in place.", flush=True)
            return
        print("[FULL] Could not update in place; rebuilding from the bundled payload.",
              flush=True)
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
        if not payload_current:
            # The payload predates these requirements, so fetch only the
            # difference. Offline this fails, and the caller says what to install.
            print("[FULL] Bundled payload is older than the requirements; "
                  "fetching the difference ...", flush=True)
            source = root / "requirements-windows-py312.lock"
            if not source.is_file():
                source = root / "requirements.txt"
            completed = subprocess.run(
                [str(environment / "Scripts/python.exe"), "-I", "-m", "pip", "install",
                 "-r", str(source)], env=env, cwd=root)
            if completed.returncode:
                raise RuntimeError(
                    "The bundled packages are older than this version needs, and the "
                    "missing ones could not be downloaded. Connect to the internet and "
                    "start Marvin again, or install the Full package for this version.")
        subprocess.run([str(environment / "Scripts/python.exe"), "-I", "-c",
                        "import fastapi,uvicorn,openai,pypdfium2,gradio,webview,tkinter; print('FULL_IMPORTS_OK')"],
                       check=True, env=env, cwd=root)
        (environment / ".requirements.sha256").write_text(digest + "\n", encoding="ascii")
        marker.write_text(json.dumps({"home": str(private), "digest": digest}), encoding="utf-8")
        _forget_old_environments(root)
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
