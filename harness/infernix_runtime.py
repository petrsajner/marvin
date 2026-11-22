"""Prepare the Infernix engine and companion model artifacts inside Marvin.

Infernix ships as a self-contained Windows x64 archive (C++/CUDA binary +
chat_templates/qwen3_8.jinja, zero Python runtime). Like llama.cpp and Strata,
it is downloaded on first selection (or unpacked from runtime/infernix-offline
in a Full installation), checksum-verified, validated with `infernix-serve --help`,
and swapped into runtime/infernix atomically.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import time
import zipfile

from harness import infernix_backend
from harness.config import ROOT, Config
from harness.runtime_update import activate_runtime, sha256

VERSION = "2026.11.20"
RELEASE_TAG = f"windows-{VERSION}"
ENGINE = {
    "url": f"https://github.com/Wallawalla47/Infernix/releases/download/{RELEASE_TAG}/infernix-{VERSION}-windows-x64.zip",
    "name": f"infernix-{VERSION}-windows-x64.zip",
    "sha256": "bedf320786ae919b2122fd8e942c9d0ef78a36bb4d485fc97b613daa939499b9",
}
# The Full installer's offline copy of the pinned release archive (scripts/build_full_payload.py).
BUNDLED = ROOT / "runtime" / "infernix-offline"
MARKER = ".marvin-infernix.json"
NO_WINDOW = 0x08000000 if os.name == "nt" else 0


def _check(path: Path, spec: dict) -> bool:
    try:
        return sha256(path) == spec["sha256"]
    except OSError:
        return False


def _fetch(spec: dict, cache: Path, *, cancelled=None, progress=print) -> Path:
    import requests
    path = cache / spec["name"]
    if path.is_file() and _check(path, spec):
        return path
    bundled = BUNDLED / spec["name"]
    if bundled.is_file() and _check(bundled, spec):
        return bundled
    progress(f"Downloading {spec['url']}")
    partial = path.with_name(path.name + ".part")
    with requests.get(spec["url"], stream=True, timeout=(15, 60)) as response, partial.open("wb") as output:
        response.raise_for_status()
        for chunk in response.iter_content(4 * 1024**2):
            if cancelled and cancelled():
                raise InterruptedError("Model preparation cancelled")
            output.write(chunk)
    if not _check(partial, spec):
        partial.unlink(missing_ok=True)
        raise RuntimeError(f"The download of {spec['url']} does not match its pinned checksum.")
    partial.replace(path)
    return path


def _extract_stripped(archive_path: Path, target: Path) -> None:
    """Extract a release zip into `target`, stripping a single top-level directory safely."""
    target_resolved = target.resolve()
    with zipfile.ZipFile(archive_path) as archive:
        infos = archive.infolist()
        tops = {info.filename.split("/", 1)[0] for info in infos if "/" in info.filename}
        single = len(tops) == 1 and all("/" in info.filename for info in infos)
        # Validate every destination path before writing anything.
        entries: list[tuple[zipfile.ZipInfo, Path]] = []
        for info in infos:
            name = info.filename.split("/", 1)[1] if single else info.filename
            if not name:
                continue
            destination = (target_resolved / name).resolve()
            if not destination.is_relative_to(target_resolved):
                raise ValueError(f"Unexpected path in {archive_path.name}: {info.filename}")
            entries.append((info, destination))
        for info, destination in entries:
            if info.is_dir():
                destination.mkdir(parents=True, exist_ok=True)
                continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info) as source, destination.open("wb") as output:
                shutil.copyfileobj(source, output)


def validate_runtime(stage: Path) -> None:
    """Confirm the unpacked Infernix binary exists and responds to --help."""
    exe = stage / ("infernix-serve.exe" if infernix_backend.WINDOWS else "infernix-serve")
    if not exe.is_file():
        raise RuntimeError(f"infernix-serve binary missing after extraction: {exe}")
    result = subprocess.run(
        [str(exe), "--help"],
        cwd=str(stage),
        capture_output=True,
        text=True,
        timeout=20,
        creationflags=NO_WINDOW,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()[-300:]
        raise RuntimeError(f"Infernix runtime validation failed (exit code {result.returncode}): {detail}")


def installed_record(cfg: Config) -> dict:
    try:
        return json.loads((infernix_backend.program_dir(cfg) / MARKER).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def runtime_current(cfg: Config, key: str) -> bool:
    """Whether the Infernix program folder is ready and at the pinned version."""
    if infernix_backend.runtime_problems(cfg, key):
        return False
    record = installed_record(cfg)
    return not record or record.get("version") == VERSION


def install(cfg: Config, *, cancelled=None, progress=print, on_phase=None) -> Path:
    """Download/unpack the pinned Infernix release, validate it, and swap it in atomically."""
    target = infernix_backend.program_dir(cfg)
    runtime = cfg.path("paths.runtime_dir")
    cache = runtime / "runtime-archives" / f"infernix-{VERSION}"
    cache.mkdir(parents=True, exist_ok=True)
    if on_phase:
        on_phase("downloading")
    archive = _fetch(ENGINE, cache, cancelled=cancelled, progress=progress)
    if on_phase:
        on_phase("preparing")
    stage = runtime / "infernix-candidates" / f"{VERSION}-{time.time_ns()}"
    stage.mkdir(parents=True)
    try:
        progress(f"Preparing Infernix {VERSION}")
        _extract_stripped(archive, stage)
        validate_runtime(stage)
        (stage / MARKER).write_text(json.dumps({
            "version": VERSION,
            "release": RELEASE_TAG,
            "engine": ENGINE["sha256"],
            "installed": time.strftime("%Y-%m-%d %H:%M:%S"),
        }, indent=2), encoding="utf-8")
        if cancelled and cancelled():
            raise InterruptedError("Model preparation cancelled")
        target.parent.mkdir(parents=True, exist_ok=True)
        backup = activate_runtime(stage, target)
        if backup:
            progress(f"Previous Infernix runtime preserved at {backup}")
    except BaseException:
        shutil.rmtree(stage, ignore_errors=True)
        raise
    return target


def ensure_runtime(cfg: Config, key: str, *, cancelled=None, progress=print, on_phase=None) -> None:
    if not runtime_current(cfg, key):
        install(cfg, cancelled=cancelled, progress=progress, on_phase=on_phase)


def prepare_model(cfg: Config, key: str, *, cancelled=None, progress=print,
                  on_phase=None, on_download_progress=None) -> None:
    """Ensure any companion Infernix artifacts (such as Flash-Next's DFlash2 drafter) are present."""
    catalog_name = infernix_backend.settings(cfg, key).get("draft_catalog")
    if not catalog_name:
        return
    from harness import model_catalog
    from harness.model_files import download_pinned_model, model_ready
    spec = getattr(model_catalog, catalog_name, None)
    if not isinstance(spec, dict):
        return
    root = cfg.model_root(key)
    if model_ready(root, spec):
        return
    if on_phase:
        on_phase("downloading")
    progress(f"Downloading {spec.get('alias', catalog_name)}")
    download_pinned_model(
        root,
        spec,
        should_stop=cancelled,
        on_progress=on_download_progress,
        on_phase=on_phase,
    )
