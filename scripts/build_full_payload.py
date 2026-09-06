"""Build an app-private CPython and locked package payload from local installations."""
from pathlib import Path
import hashlib
import importlib.metadata as metadata
import json
import os
import shutil
import sys
import tempfile
import time
from packaging.requirements import Requirement

ROOT = Path(__file__).resolve().parent.parent


def build():
    if sys.version_info[:2] != (3, 12) or sys.maxsize < 2**32:
        raise RuntimeError("Full must be built using 64-bit Python 3.12")
    version = (ROOT / "installer/version.txt").read_text().strip()
    destination = ROOT / "build" / ("full-payload-" + version)
    destination.parent.mkdir(parents=True, exist_ok=True)
    target = Path(tempfile.mkdtemp(prefix="full-payload-building-", dir=destination.parent))
    base = Path(sys.base_prefix)
    python = target / "python"
    python.mkdir(exist_ok=True)
    for pattern in ("python*.exe", "python*.dll", "vcruntime*.dll", "LICENSE.txt"):
        for source in base.glob(pattern):
            shutil.copy2(source, python / source.name)
    for folder in ("DLLs", "Lib", "tcl"):
        shutil.copytree(base / folder, python / folder, dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns("site-packages", "__pycache__", "*.pyc"))
    packages = target / "packages"
    packages.mkdir(exist_ok=True)
    copied = set()
    for line in (ROOT / "requirements-windows-py312.lock").read_text().splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        requirement = Requirement(line)
        distribution = metadata.distribution(requirement.name)
        if distribution.version not in requirement.specifier:
            raise ValueError(f"Installed version does not match lock: {requirement}")
        site = Path(distribution.locate_file("")).resolve()
        for item in distribution.files or []:
            source = Path(distribution.locate_file(item)).resolve()
            if not source.is_relative_to(site) or not source.is_file() or source.suffix in (".pyc", ".pyo"):
                continue
            relative = source.relative_to(site)
            if relative in copied:
                continue
            package_file = packages / relative
            package_file.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, package_file)
            copied.add(relative)
    shutil.copytree(ROOT / "runtime/llama", target / "llama", dirs_exist_ok=True)
    # App-local MSVC runtime: do not rely on a machine-wide VC++ installation.
    crt = target / "crt"
    crt.mkdir()
    system = Path(os.environ["SystemRoot"]) / "System32"
    release_crt = ("msvcp140.dll", "msvcp140_1.dll", "msvcp140_2.dll", "msvcp140_atomic_wait.dll",
                   "msvcp140_codecvt_ids.dll", "vcruntime140.dll", "vcruntime140_1.dll",
                   "vcruntime140_threads.dll", "concrt140.dll")
    for name in release_crt:
        source = system / name
        if source.is_file():
            for directory in (crt, python, target / "llama"):
                shutil.copy2(source, directory / name)
    for name in ("msvcp140.dll", "vcruntime140.dll", "vcruntime140_1.dll"):
        if not (crt / name).exists():
            raise FileNotFoundError(f"Required app-local runtime missing: {name}")
    content = (ROOT / "requirements.txt").read_bytes() + b"\nLOCK\n" + (ROOT / "requirements-windows-py312.lock").read_bytes()
    manifest = {"app_version": version, "python": sys.version.split()[0], "packages_files": len(copied),
                "requirements_digest": hashlib.sha256(content).hexdigest()}
    (target / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    if destination.exists():
        destination.rename(destination.with_name(destination.name + "-previous-" + str(time.time_ns())))
    target.rename(destination)
    print(json.dumps({"path": str(destination), **manifest}, indent=2))


if __name__ == "__main__":
    build()
