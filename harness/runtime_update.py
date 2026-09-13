"""Install a pinned upstream runtime with staged validation and a recoverable swap."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import tempfile
import time
import zipfile

RELEASE = "b10935"
BUILD = 10935
ASSETS = (
    ("llama-b10935-bin-win-cuda-13.3-x64.zip", "llama.zip",
     "9ece1d33916caefe2ed1f74092dabe05cf955b112f9afdabc2de5c5e2b7285ad"),
    ("cudart-llama-bin-win-cuda-13.3-x64.zip", "cudart.zip",
     "1462a050eb4c684921ba51dcc4cc488a036674c3e73e9945ee705b854808d03e"),
)
NO_WINDOW = 0x08000000 if os.name == "nt" else 0
_versions = {}


def sha256(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def runtime_build(exe: Path | None) -> int:
    if exe is None or not exe.is_file():
        return 0
    relevant = [exe, exe.parent / "llama.dll", exe.parent / "llama-server-impl.dll"]
    key = tuple((str(p), p.stat().st_size, p.stat().st_mtime_ns) for p in relevant if p.is_file())
    if key not in _versions:
        try:
            result = subprocess.run([str(exe), "--version"], capture_output=True, text=True,
                                    timeout=15, creationflags=NO_WINDOW, cwd=exe.parent)
            match = re.search(r"\bbuild\s+(\d+)", result.stdout + result.stderr)
            _versions[key] = int(match.group(1)) if result.returncode == 0 and match else 0
        except (OSError, subprocess.SubprocessError):
            _versions[key] = 0
    return _versions[key]


def validate_runtime(directory: Path) -> Path:
    executables = list(directory.rglob("llama-server.exe"))
    if len(executables) != 1 or runtime_build(executables[0]) != BUILD:
        raise RuntimeError("The downloaded model runtime did not pass version validation.")
    exe = executables[0]
    devices = subprocess.run([str(exe), "--list-devices"], capture_output=True, text=True,
                             timeout=25, creationflags=NO_WINDOW, cwd=exe.parent)
    if devices.returncode or not re.search(r"\bCUDA\d+:", devices.stdout):
        raise RuntimeError("The downloaded model runtime could not load its GPU libraries.")
    return exe


def extract_archive(archive: Path, directory: Path):
    directory = directory.resolve()
    with zipfile.ZipFile(archive) as package:
        for member in package.infolist():
            target = (directory / member.filename).resolve()
            if not target.is_relative_to(directory) or stat.S_ISLNK(member.external_attr >> 16):
                raise ValueError("Unsafe path in runtime archive")
        package.extractall(directory)


def activate_runtime(staged: Path, target: Path) -> Path | None:
    staged, target = staged.resolve(), target.resolve()
    if target == target.parent or target == staged or not staged.is_dir():
        raise ValueError("Invalid runtime activation target")
    backup = None
    if target.exists():
        backup = target.with_name(target.name + "-previous-" + str(time.time_ns()))
        target.rename(backup)
    try:
        staged.rename(target)
    except BaseException:
        if backup and backup.exists() and not target.exists():
            backup.rename(target)
        raise
    return backup


def install_runtime(target: Path, runtime_root: Path, *, cancelled=None, progress=print) -> Path:
    import requests

    target = target.resolve()
    runtime_root = runtime_root.resolve()
    if target == runtime_root or target == target.parent:
        raise ValueError("The model runtime must have its own directory")
    cache = runtime_root / "runtime-archives" / RELEASE
    cache.mkdir(parents=True, exist_ok=True)
    archives = []
    for name, cached_name, expected in ASSETS:
        if cancelled and cancelled():
            raise InterruptedError("Runtime preparation cancelled")
        path = cache / cached_name
        existing = runtime_root / "candidates" / "llama-b10935-cuda13.3" / cached_name
        if not path.exists() and existing.is_file() and sha256(existing) == expected:
            shutil.copy2(existing, path)
        if not path.is_file() or sha256(path) != expected:
            progress(f"Preparing model runtime {RELEASE}: {name}")
            partial = path.with_suffix(".part")
            url = f"https://github.com/ggml-org/llama.cpp/releases/download/{RELEASE}/{name}"
            with requests.get(url, stream=True, timeout=(15, 30)) as response, partial.open("wb") as output:
                response.raise_for_status()
                for chunk in response.iter_content(4 * 1024**2):
                    if cancelled and cancelled():
                        raise InterruptedError("Runtime preparation cancelled")
                    output.write(chunk)
            if sha256(partial) != expected:
                raise RuntimeError("Downloaded runtime checksum does not match the pinned release.")
            partial.replace(path)
        archives.append(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="llama-stage-", dir=target.parent) as temporary:
        stage = Path(temporary) / "bin"
        stage.mkdir()
        for archive in archives:
            extract_archive(archive, stage)
        staged_exe = validate_runtime(stage)
        relative_exe = staged_exe.relative_to(stage)
        if cancelled and cancelled():
            raise InterruptedError("Runtime preparation cancelled")
        backup = activate_runtime(stage, target)
        if backup:
            progress(f"Previous model runtime preserved at {backup}")
    return target / relative_exe


def ensure_runtime(cfg, key=None, *, cancelled=None, progress=print) -> Path | None:
    key = key or cfg.model_key()
    exe = cfg.llama_server_exe()
    required = cfg.model(key).get("minimum_runtime_build", 0)
    if not required or runtime_build(exe) >= required:
        return exe
    if required > BUILD:
        raise RuntimeError("No validated runtime is available for the selected model.")
    return install_runtime(cfg.path("paths.llama_dir"), cfg.path("paths.runtime_dir"),
                           cancelled=cancelled, progress=progress)
