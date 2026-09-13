"""Integrity and completeness for pinned multi-file model downloads."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import time
from urllib.parse import quote

from harness.changes import atomic_write_text


def local_model_dir(models_dir: Path, spec: dict) -> Path:
    base = Path(models_dir).resolve()
    target = (base / spec.get("download_dir", "")).resolve()
    if not target.is_relative_to(base):
        raise ValueError("Model directory is outside the models root")
    return target


def asset_path(directory: Path, name: str) -> Path:
    path = (directory / name).resolve()
    if not path.is_relative_to(directory.resolve()):
        raise ValueError("Model asset path is outside its directory")
    return path


def signature(spec: dict) -> str:
    value = {k: spec.get(k) for k in ("repo", "revision", "assets")}
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def read_receipt(directory: Path) -> dict:
    try:
        receipt = json.loads((directory / ".marvin-verified.json").read_text(encoding="utf-8"))
        return receipt if isinstance(receipt, dict) and isinstance(receipt.get("files"), dict) else {}
    except (OSError, ValueError):
        return {}


def asset_verified(directory: Path, asset: dict, receipt: dict) -> bool:
    path = asset_path(directory, asset["path"])
    try:
        stat = path.stat()
        record = receipt.get("files", {}).get(asset["path"], {})
        return (isinstance(record, dict) and path.is_file() and stat.st_size == asset["size"]
                and record.get("size") == stat.st_size
                and record.get("mtime_ns") == stat.st_mtime_ns
                and record.get("sha256") == asset["sha256"])
    except OSError:
        return False


def model_ready(models_dir: Path, spec: dict) -> bool:
    assets = spec.get("assets")
    if not assets:
        return (Path(models_dir) / spec["file"]).is_file()
    directory = local_model_dir(models_dir, spec)
    receipt = read_receipt(directory)
    return receipt.get("signature") == signature(spec) and all(asset_verified(directory, a, receipt) for a in assets)


def ranged_download(directory: Path, spec: dict, asset: dict, *, progress, should_stop=None, force=False, on_progress=None) -> Path:
    """Download contiguous ranges with explicit progress and resumable partial files."""
    import requests

    target = asset_path(directory, asset["path"])
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(target.name + ".marvin.part")
    if force and partial.exists():
        partial.unlink()
    offset = partial.stat().st_size if partial.exists() else 0
    if offset > asset["size"]:
        raise RuntimeError("Partial model download is larger than the expected file")
    url = f"https://huggingface.co/{spec['repo']}/resolve/{spec['revision']}/{quote(asset['path'])}"
    chunk_range = 256 * 1024**2
    last_report = time.monotonic()
    last_signal = last_report
    if on_progress:
        on_progress(offset, asset["size"])
    with requests.Session() as session, partial.open("ab") as output:
        while offset < asset["size"]:
            if should_stop and should_stop():
                raise InterruptedError("Model download cancelled")
            end = min(asset["size"] - 1, offset + chunk_range - 1)
            for attempt in range(4):
                try:
                    with session.get(url, headers={"Range": f"bytes={offset}-{end}"}, stream=True, timeout=(15, 30)) as response:
                        response.raise_for_status()
                        expected = f"bytes {offset}-{end}/{asset['size']}"
                        if response.status_code != 206 or response.headers.get("Content-Range") != expected:
                            raise RuntimeError("Model host returned an unexpected byte range")
                        remaining = end - offset + 1
                        for chunk in response.iter_content(64 * 1024):
                            if should_stop and should_stop():
                                raise InterruptedError("Model download cancelled")
                            if len(chunk) > remaining:
                                raise RuntimeError("Model host returned excess data")
                            output.write(chunk)
                            output.flush()
                            offset += len(chunk)
                            remaining -= len(chunk)
                            if on_progress and time.monotonic() - last_signal >= .5:
                                on_progress(offset, asset["size"])
                                last_signal = time.monotonic()
                            if time.monotonic() - last_report >= 20:
                                progress(f"[PROGRESS] {asset['path']}: {offset/1e9:.2f}/{asset['size']/1e9:.2f} GB")
                                last_report = time.monotonic()
                        if remaining:
                            raise requests.ConnectionError("Incomplete HTTP range")
                    break
                except requests.RequestException:
                    if offset > end:
                        break
                    if attempt == 3:
                        raise
                    time.sleep(attempt + 1)
    if on_progress:
        on_progress(offset, asset["size"])
    return partial


def download_pinned_model(models_dir: Path, spec: dict, *, force=False, progress=print, should_stop=None,
                          on_progress=None, on_phase=None):
    from filelock import FileLock, Timeout

    directory = local_model_dir(models_dir, spec)
    directory.mkdir(parents=True, exist_ok=True)
    lock = FileLock(directory / ".marvin-download.lock")
    while True:
        if should_stop and should_stop():
            raise InterruptedError("Model download cancelled")
        try:
            lock.acquire(timeout=.5)
            break
        except Timeout:
            continue
    try:
        return _download_pinned_model(models_dir, spec, force=force, progress=progress, should_stop=should_stop,
                                      on_progress=on_progress, on_phase=on_phase)
    finally:
        lock.release()


def _download_pinned_model(models_dir: Path, spec: dict, *, force=False, progress=print, should_stop=None,
                           on_progress=None, on_phase=None):
    from huggingface_hub import hf_hub_download
    from huggingface_hub.utils import disable_progress_bars

    disable_progress_bars()
    directory = local_model_dir(models_dir, spec)
    directory.mkdir(parents=True, exist_ok=True)
    receipt = read_receipt(directory)
    if receipt.get("signature") != signature(spec):
        receipt = {"signature": signature(spec), "files": {}}
    missing_bytes = 0
    for asset in spec["assets"]:
        target = asset_path(directory, asset["path"])
        if not force and target.is_file() and target.stat().st_size == asset["size"]:
            continue
        partial = target.with_name(target.name + ".marvin.part")
        resumed = (partial.stat().st_size if not force and
                   spec.get("download_transport") == "range" and partial.is_file() else 0)
        missing_bytes += max(0, asset["size"] - resumed)
    # Reserve metadata/runtime space in addition to bytes still to be transferred.
    if shutil.disk_usage(directory).free < missing_bytes + 2 * 1024**3:
        raise RuntimeError("Not enough disk space for the complete model download")
    total_bytes = sum(asset["size"] for asset in spec["assets"])
    completed_bytes = 0
    for index, asset in enumerate(spec["assets"], 1):
        if should_stop and should_stop():
            raise InterruptedError("Model download cancelled")
        target = asset_path(directory, asset["path"])
        if not force and asset_verified(directory, asset, receipt):
            progress(f"[VERIFIED {index}/{len(spec['assets'])}] {asset['path']}")
            completed_bytes += asset["size"]
            if on_progress:
                on_progress(completed_bytes, total_bytes)
            continue
        if on_phase:
            on_phase("downloading")
        started = time.monotonic()
        progress(f"[DOWNLOAD {index}/{len(spec['assets'])}] {asset['path']} ({asset['size']/1e9:.2f} GB)")
        if not force and target.is_file() and target.stat().st_size == asset["size"]:
            path = target
        elif spec.get("download_transport") == "range":
            path = ranged_download(directory, spec, asset, progress=progress, should_stop=should_stop, force=force,
                on_progress=(lambda done, _: on_progress(completed_bytes + done, total_bytes)) if on_progress else None)
        else:
            path = Path(hf_hub_download(repo_id=spec["repo"], revision=spec["revision"],
                filename=asset["path"], local_dir=str(directory), force_download=force))
        allowed = (target, target.with_name(target.name + ".marvin.part"))
        if path.resolve() not in allowed:
            raise RuntimeError("Download returned an unexpected local path")
        if path.stat().st_size != asset["size"]:
            raise RuntimeError(f"Incomplete model asset: {asset['path']}")
        progress(f"[CHECKSUM] {asset['path']}")
        if on_phase:
            on_phase("verifying")
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            while chunk := stream.read(8 * 1024**2):
                if should_stop and should_stop():
                    raise InterruptedError("Model verification cancelled")
                digest.update(chunk)
        actual = digest.hexdigest()
        if actual != asset["sha256"]:
            raise RuntimeError(f"Checksum mismatch: {asset['path']}; rerun with force=True to repair")
        if path != target:
            path.replace(target)
            path = target
        stat = path.stat()
        receipt["files"][asset["path"]] = {"size": stat.st_size, "mtime_ns": stat.st_mtime_ns, "sha256": actual}
        atomic_write_text(directory / ".marvin-verified.json", json.dumps(receipt, indent=2))
        progress(f"[DONE] {asset['path']} ({time.monotonic()-started:.1f}s)")
        completed_bytes += asset["size"]
        if on_progress:
            on_progress(completed_bytes, total_bytes)
    if not model_ready(models_dir, spec):
        raise RuntimeError("Downloaded model did not pass its complete manifest check")
    return directory
