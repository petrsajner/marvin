"""Validate the release ZIP and restore backup dependencies into a fresh venv."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from scripts.offline_backup import load_manifest, restore_backup


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backup", type=Path, required=True)
    args = parser.parse_args()
    version = (ROOT / "installer/version.txt").read_text().strip()
    archive_path = ROOT / "dist" / f"Marvin-{version}-Windows-x64.zip"
    with zipfile.ZipFile(archive_path) as archive:
        assert archive.testzip() is None, "Release ZIP CRC failure"
        for line in archive.read("SHA256SUMS.txt").decode("ascii").splitlines():
            digest, filename = line.split("  ", 1)
            assert hashlib.sha256(archive.read(filename)).hexdigest() == digest, filename
        assert len(archive.namelist()) == 7, "Unexpected distribution payload"
    manifest = load_manifest(args.backup)
    assert manifest["requirements_sha256"] == hashlib.sha256((ROOT / "requirements.txt").read_bytes()).hexdigest()
    assert manifest.get("lock_sha256"), "Backup must include the current dependency lock"

    with tempfile.TemporaryDirectory(prefix="fresh-install-", dir=ROOT / "runtime") as temporary:
        stage = Path(temporary).resolve()
        assert stage.is_relative_to((ROOT / "runtime").resolve())
        for name in ("requirements.txt", "requirements-windows-py312.lock", "config.yaml", "app_icon.ico"):
            shutil.copy2(ROOT / name, stage / name)
        shutil.copy2(ROOT / "installer/version.txt", stage / "version.txt")
        for folder in ("harness", "ui_dist", "memory", "skills"):
            shutil.copytree(ROOT / folder, stage / folder, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        subprocess.run([sys.executable, "-m", "venv", str(stage / ".venv")], check=True)
        result = restore_backup(stage, args.backup, {"python-dependencies"})
        assert result["dependencies"] == "restored"
        probe = r'''
import json
from pathlib import Path
from importlib.metadata import version
import fastapi, uvicorn, pypdfium2, webview, gradio
from fastapi.testclient import TestClient
from packaging.requirements import Requirement
from harness.config import Config, load_config
from harness.application import ApplicationService
from harness.dependencies import dependencies_current
from harness.web_api import create_app
root = Path.cwd()
assert Path(fastapi.__file__).is_relative_to(root / '.venv')
assert dependencies_current(root / 'requirements.txt', root / '.venv')
for line in (root / 'requirements-windows-py312.lock').read_text().splitlines():
    if line.strip() and not line.startswith('#'):
        requirement = Requirement(line)
        assert version(requirement.name) in requirement.specifier, requirement.name
cfg = Config(load_config().data, root)
service = ApplicationService(cfg, manage_model=False)
with TestClient(create_app(cfg, service=service)) as client:
    assert client.get('/').status_code == 200
    data = client.get('/api/state').json()
    assert data['projects'] == []
    assert len(data['sessions']) <= 1
    assert client.get('/config').json()['data_root'] == str(root)
    response = client.post('/api/sessions', json={})
    assert response.status_code == 200
    session_id = response.json()['session_id']
    assert client.get('/api/sessions/' + session_id).status_code == 200
print(json.dumps({'clean_venv': True, 'locked_packages': True, 'api': True, 'compiled_ui': True, 'no_personal_data': True}))
'''
        completed = subprocess.run([str(stage / ".venv/Scripts/python.exe"), "-c", probe],
                                   cwd=stage, text=True, capture_output=True, check=True)
        print(completed.stdout)
        report = {"version": version, "distribution_zip": "verified", "backup_dependencies": "restored",
                  "fresh_environment": json.loads(completed.stdout.strip().splitlines()[-1]),
                  "scope": "Fresh venv and staged app API, not a clean Windows VM or actual installer execution"}
        (ROOT / "runtime" / f"distribution-check-{version}.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
