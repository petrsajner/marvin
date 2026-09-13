"""Prepare the stable WebView2 runtime without Python packages or a browser UI."""
from __future__ import annotations

import ctypes
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.request

CLIENT_KEY = r"Software\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
MIN_VERSION = (86, 0, 622, 0)  # Same minimum as the bundled pywebview backend.
SILENT_FLAGS = ["/silent", "/install"]


def installed_version() -> str | None:
    if sys.platform != "win32":
        return None
    import winreg
    versions = []
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        for view in (winreg.KEY_WOW64_32KEY, winreg.KEY_WOW64_64KEY):
            try:
                with winreg.OpenKey(hive, CLIENT_KEY, 0, winreg.KEY_READ | view) as key:
                    value = winreg.QueryValueEx(key, "pv")[0]
                parts = tuple(int(part) for part in value.split("."))
                if len(parts) == 4 and parts >= MIN_VERSION:
                    versions.append((parts, value))
            except (OSError, ValueError, TypeError, AttributeError):
                continue
    return max(versions)[1] if versions else None


def payload_valid(path: Path, item: dict) -> bool:
    try:
        if path.stat().st_size != item["size"]:
            return False
        with path.open("rb") as handle:
            return hashlib.file_digest(handle, "sha256").hexdigest() == item["sha256"]
    except OSError:
        return False


def _start_installer(path: Path):
    env = dict(os.environ)
    for key in ("PYTHONHOME", "PYTHONPATH", "PYTHONUSERBASE", "PYTHONSTARTUP"):
        env.pop(key, None)
    # PyInstaller's DLL directory must not affect Microsoft's separate process.
    frozen = sys.platform == "win32" and getattr(sys, "frozen", False)
    previous = ctypes.create_unicode_buffer(32768)
    if frozen:
        ctypes.windll.kernel32.GetDllDirectoryW(len(previous), previous)
        ctypes.windll.kernel32.SetDllDirectoryW(None)
    try:
        return subprocess.Popen([str(path), *SILENT_FLAGS], cwd=str(path.parent),
                                env=env, creationflags=0x08000000 if sys.platform == "win32" else 0)
    finally:
        if frozen:
            ctypes.windll.kernel32.SetDllDirectoryW(previous.value or None)


def _install(path: Path, log, timeout: float = 600) -> bool:
    log(f"Preparing WebView2 using {path.name}")
    process = _start_installer(path)
    deadline = time.monotonic() + timeout
    while process.poll() is None:
        if time.monotonic() >= deadline:
            # Do not interrupt an updater that may still be committing files.
            raise TimeoutError("WebView2 setup is still running; startup can retry after it finishes")
        time.sleep(0.25)
    log(f"WebView2 installer exit code: {process.returncode}")
    # Another Edge updater may complete registration after the parent exits.
    for _ in range(41):
        version = installed_version()
        if version:
            log(f"WebView2 ready: {version}")
            return True
        time.sleep(0.5)
    return False


def ensure_webview2(root: Path, log=print) -> str:
    """Reuse a compatible runtime; prefer offline payload, then bootstrap online.

    Only pinned Microsoft payloads are executed. An installer exit code alone is
    insufficient: the same runtime detection used before setup must pass after it.
    """
    if sys.platform != "win32":
        return "not-required"
    version = installed_version()
    if version:
        log(f"Reusing WebView2 {version}")
        return "present"
    payload_dir = root / "runtime" / "webview2"
    manifest_path = payload_dir / "webview2.json"
    if not manifest_path.is_file():
        manifest_path = root / "installer" / "webview2.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    directories = [payload_dir]
    try:
        backup = (root / "runtime/offline-backup-path.txt").read_text(encoding="utf-8").strip()
        if backup:
            directories.append(Path(backup) / "payload/runtime/webview2")
    except OSError:
        pass
    attempted = set()
    for kind in ("standalone", "bootstrapper"):
        item = manifest[kind]
        for directory in directories:
            path = directory / item["filename"]
            if payload_valid(path, item):
                attempted.add(kind)
                if _install(path, log):
                    return "installed"
                break
    # Repairs a removed/damaged payload as well as source/portable launches.
    if "bootstrapper" not in attempted:
        item = manifest["bootstrapper"]
        payload_dir.mkdir(parents=True, exist_ok=True)
        target = payload_dir / item["filename"]
        temporary = target.with_suffix(".download")
        try:
            log("Downloading the desktop component setup")
            with urllib.request.urlopen(item["url"], timeout=60) as response, temporary.open("wb") as output:
                while chunk := response.read(1024 * 1024):
                    output.write(chunk)
                    if output.tell() > item["size"]:
                        raise ValueError("WebView2 payload exceeds its pinned size")
            if not payload_valid(temporary, item):
                raise ValueError("WebView2 payload does not match the packaged checksum")
            os.replace(temporary, target)
            if _install(target, log):
                return "installed"
        finally:
            temporary.unlink(missing_ok=True)
    raise RuntimeError("Desktop components could not be prepared. Retry Marvin after connecting "
                       "to the internet, or run the Full installer for offline setup.")
