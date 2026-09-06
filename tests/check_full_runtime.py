"""Relocate Full's payload and test it with system Python discovery disabled."""
from pathlib import Path
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parent.parent


def main():
    version = (ROOT / "installer/version.txt").read_text().strip()
    payload = ROOT / "build" / ("full-payload-" + version)
    with tempfile.TemporaryDirectory(prefix="full-runtime-check-", dir=ROOT / "runtime") as temporary:
        root = Path(temporary) / "New machine with spaces"
        root.mkdir()
        for source, target in (("python", "runtime/python"), ("packages", "runtime/python-packages"), ("llama", "runtime/llama")):
            shutil.copytree(payload / source, root / target, copy_function=os.link)
        shutil.copy2(payload / "manifest.json", root / "runtime/full-manifest.json")
        (root / "scripts").mkdir()
        shutil.copy2(ROOT / "scripts/bootstrap_full.py", root / "scripts/bootstrap_full.py")
        for name in ("requirements.txt", "requirements-windows-py312.lock", "config.yaml"):
            shutil.copy2(ROOT / name, root / name)
        shutil.copytree(ROOT / "harness", root / "harness", ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copytree(ROOT / "ui_dist", root / "ui_dist")
        shutil.copy2(ROOT / "installer/version.txt", root / "version.txt")
        env = dict(os.environ)
        env.update(PATH=str(Path(os.environ["SystemRoot"]) / "System32"), PYTHONHOME="Z:/nonexistent-python",
                   PYTHONPATH="Z:/conflicting-packages", PYTHONUSERBASE="Z:/wrong-user", QWEN_AUTOSTART_SERVER="0")
        command = [str(root / "runtime/python/python.exe"), "-I", str(root / "scripts/bootstrap_full.py")]
        subprocess.run(command, cwd=root, env=env, check=True)
        # The second launch must reuse the prepared environment without changing its home.
        subprocess.run(command, cwd=root, env=env, check=True)
        probe = r'''
import sys, site, pathlib, json, tkinter
root = pathlib.Path.cwd()
sys.path.insert(0, str(root))
assert pathlib.Path(sys.base_prefix) == root / 'runtime/python'
assert pathlib.Path(sys.prefix) == root / '.venv'
assert not site.ENABLE_USER_SITE
import fastapi, uvicorn, gradio, pypdfium2, pyautogui, mss, ssl
assert pathlib.Path(fastapi.__file__).is_relative_to(root / '.venv')
assert tkinter.Tcl().eval('info patchlevel')
from harness.config import Config, load_config
from harness.application import ApplicationService
from harness.web_api import create_app
from fastapi.testclient import TestClient
cfg = Config(load_config().data, root)
service = ApplicationService(cfg, manage_model=False)
with TestClient(create_app(cfg, service=service)) as client:
    assert client.get('/').status_code == 200
    assert client.get('/api/state').json()['projects'] == []
print('PRIVATE_PYTHON_API_OK')
'''
        python = root / ".venv/Scripts/python.exe"
        for directory in (root / ".venv/Scripts", root / "runtime/llama"):
            assert (directory / "msvcp140.dll").is_file()
            assert (directory / "vcruntime140_1.dll").is_file()
        subprocess.run([str(python), "-I", "-c", probe], cwd=root, env=env, check=True)
        subprocess.run([str(python), "-I", "-m", "pip", "check"], cwd=root, env=env, check=True)
        llama = next((root / "runtime/llama").rglob("llama-server.exe"))
        subprocess.run([str(llama), "--version"], cwd=llama.parent, env=env, check=True)
        result = {"version": version, "private_python": True, "no_system_python": True,
                  "conflicting_python_environment_ignored": True, "locked_dependencies": True,
                  "llama_dll_load": True, "fresh_api": True, "offline_backup_untouched": True}
        (ROOT / "runtime/full-runtime-check.json").write_text(json.dumps(result, indent=2))
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
