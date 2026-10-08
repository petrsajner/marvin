"""Create, verify, inspect, and restore a portable Marvin offline backup.

The script deliberately uses only the Python standard library so restore can run
before project dependencies are installed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import sys
import time
import zipfile
from pathlib import Path
from typing import Any

FORMAT_VERSION = 2
MANIFEST_NAME = "manifest.json"
MARKER_NAME = "offline-backup-path.txt"
BACKUP_PREFIX = "QwenHarness-Offline-Backup"
DEPENDENCY_ARCHIVE = Path("python-dependencies/site-packages.zip")
CHUNK_SIZE = 16 * 1024 * 1024


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_relative(raw: str) -> Path:
    path = Path(raw)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"Unsafe manifest path: {raw}")
    return path


def _copy_with_hash(source: Path, target: Path) -> str:
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".partial")
    digest = hashlib.sha256()
    total = source.stat().st_size
    copied = 0
    last_report = time.monotonic()
    try:
        with open(source, "rb") as src, open(temporary, "wb") as dst:
            for chunk in iter(lambda: src.read(CHUNK_SIZE), b""):
                digest.update(chunk)
                dst.write(chunk)
                copied += len(chunk)
                if time.monotonic() - last_report >= 20:
                    print(f"    {target.name}: {copied / 2**30:.1f} / {total / 2**30:.1f} GiB", flush=True)
                    last_report = time.monotonic()
        shutil.copystat(source, temporary)
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return digest.hexdigest()


def _version(root: Path) -> str:
    for path in (root / "version.txt", root / "installer" / "version.txt"):
        try:
            value = path.read_text(encoding="utf-8").strip()
            if value:
                return value
        except OSError:
            pass
    return "unknown"


# Flash-Next's draft layer is used from mtp/rt; the downloaded BF16 tensors and the
# packed GGUF it was built from (about 5.7 GB) are only intermediates.
MTP_INTERMEDIATES = ("tensors", "mtp-q2_0.gguf", "mtp-q2_0.gguf.report.json", "mtp-inventory.json",
                     "mtp-inventory.md", "mtp-manifest.json")


def _skipped_model_file(relative: Path, exclude: tuple[str, ...]) -> bool:
    parts = relative.parts
    if "mtp" in parts:
        after = parts[parts.index("mtp") + 1:]
        if after and (after[0] in MTP_INTERMEDIATES or after[0].startswith(("rt-incomplete-", "rt.partial"))):
            return True
    text = relative.as_posix()
    return any(text == item or text.startswith(item.rstrip("/") + "/") for item in exclude)


def _runtime_sources(root: Path, exclude: tuple[str, ...] = ()) -> list[tuple[Path, Path, str]]:
    """What a backup carries from an installation; `exclude` names paths under runtime/models to leave out."""
    runtime = root / "runtime"
    sources: list[tuple[Path, Path, str]] = []
    models = runtime / "models"
    if models.is_dir():
        for source in sorted(models.rglob("*")):
            if (source.is_file() and ".cache" not in source.parts
                    and not source.name.endswith((".partial", ".incomplete", ".part", ".lock"))
                    and not _skipped_model_file(source.relative_to(models), exclude)):
                rel = Path("payload") / "runtime" / "models" / source.relative_to(models)
                sources.append((source, rel, "models"))
    llama = runtime / "llama"
    if llama.is_dir():
        for source in sorted(llama.rglob("*")):
            if source.is_file():
                rel = Path("payload") / "runtime" / "llama" / source.relative_to(llama)
                sources.append((source, rel, "llama"))
    whisper = runtime / "whisper"
    if whisper.is_dir():
        # The dictation program. Its models live under runtime/models and are
        # already collected above.
        for source in sorted(whisper.rglob("*")):
            if source.is_file():
                rel = Path("payload") / "runtime" / "whisper" / source.relative_to(whisper)
                sources.append((source, rel, "whisper"))
    openart = runtime / "openart"
    if openart.is_dir():
        # The image-generation program. It cannot reach its service without a
        # connection, so it does nothing on an offline machine - but a machine
        # set up from this backup should be complete, not complete except for one
        # download it has to make later.
        for source in sorted(openart.rglob("*")):
            if source.is_file():
                rel = Path("payload") / "runtime" / "openart" / source.relative_to(openart)
                sources.append((source, rel, "openart"))
    strata = runtime / "strata"
    if strata.is_dir():
        # Flash-Next's engine with its private Python environment, once prepared.
        for source in sorted(strata.rglob("*")):
            if source.is_file() and "__pycache__" not in source.parts:
                rel = Path("payload") / "runtime" / "strata" / source.relative_to(strata)
                sources.append((source, rel, "strata"))
    webview = runtime / "webview2"
    if webview.is_dir():
        for source in sorted(webview.iterdir()):
            if source.is_file() and source.suffix.lower() in {".exe", ".json"}:
                sources.append((source, Path("payload/runtime/webview2") / source.name, "webview2"))
    selection = runtime / "model-selection.txt"
    if selection.is_file():
        sources.append((selection, Path("payload/runtime/model-selection.txt"), "settings"))
    version = _version(root)
    installer = root / "dist" / f"Marvin-Setup-{version}-Full.exe"
    if not installer.is_file():
        installer = root / "dist" / f"Marvin-Setup-{version}-Minimal.exe"
    if not installer.is_file():
        installer = root / "dist" / f"Marvin-Setup-{version}.exe"
    if installer.is_file():
        sources.append((installer, Path(installer.name), "installer"))
    return sources


def _same_file_key(path: Path) -> tuple[int, int] | None:
    """The identity of a file with more than one name (a hard link), else None."""
    stat = path.stat()
    return (stat.st_dev, stat.st_ino) if stat.st_nlink > 1 and stat.st_ino else None


def _payload_target(root: Path, relative: str) -> Path:
    return root / Path(*_safe_relative(relative).parts[1:])


def _fix_strata_environment(root: Path) -> str:
    """A restored engine environment points at the Python it was made from; point it at this one's."""
    config = root / "runtime" / "strata" / ".venv" / "pyvenv.cfg"
    base = root / "runtime" / "python"
    if not config.is_file() or not (base / "python.exe").is_file():
        return "unchanged"
    lines = config.read_text(encoding="utf-8").splitlines()
    fixed = [f"home = {base}" if line.split("=", 1)[0].strip() == "home" else line for line in lines]
    config.write_text("\n".join(fixed) + "\n", encoding="utf-8")
    return f"home = {base}"


def _write_readme(path: Path) -> None:
    path.write_text(
        "MARVIN OFFLINE BACKUP\n"
        "===========================\n\n"
        "This folder contains local model files, vision projectors, llama.cpp/CUDA\n"
        "runtime files, and a snapshot of the already installed Python packages.\n"
        "Keep manifest.json with the payload and python-dependencies folders.\n\n"
        "On another Windows PC:\n"
        "1. Run the Marvin-Setup executable included in this folder.\n"
        "   The Full installer includes private Python; no system Python is needed.\n"
        "   WebView2 is prepared automatically; Full includes it for offline setup.\n"
        "   Only when using a Minimal installer, prepare 64-bit Python 3.12 first.\n"
        "   The installer detects manifest.json beside itself automatically.\n"
        "   With another compatible Setup.exe, use the Start Menu command\n"
        "   'Set up from offline backup' and select this folder.\n"
        "2. A matching backup beside Setup is selected for local restore first.\n"
        "   The complete offline restore copies all models included in this backup.\n"
        "3. Normal setup without that selection uses internet sources first. If a model, llama.cpp, or\n"
        "   Python package cannot be obtained online, it restores that component\n"
        "   from this backup. The explicit Start Menu offline command restores\n"
        "   this backup first instead.\n\n"
        "Run `python scripts/offline_backup.py verify --backup <this-folder>`\n"
        "from an installed/source Marvin copy to verify every SHA-256.\n",
        encoding="utf-8")


def _create_dependency_archive(source: Path, target: Path) -> tuple[int, str]:
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".partial")
    files = [path for path in sorted(source.rglob("*"))
             if path.is_file() and "__pycache__" not in path.parts
             and path.suffix.lower() not in {".pyc", ".pyo"}]
    try:
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_STORED,
                             allowZip64=True) as archive:
            for index, path in enumerate(files, 1):
                if index == 1 or index % 1000 == 0 or index == len(files):
                    print(f"  Python dependencies: {index}/{len(files)} files")
                archive.write(path, path.relative_to(source).as_posix())
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return target.stat().st_size, sha256_file(target)


def create_backup(root: Path, output: Path) -> dict[str, Any]:
    root = root.resolve()
    output = output.resolve()
    if output.exists():
        raise FileExistsError(f"Backup target already exists: {output}")
    sources = _runtime_sources(root)
    model_sources = [item for item in sources if item[2] == "models"
                     and item[0].suffix.lower() == ".gguf"]
    if not model_sources:
        raise FileNotFoundError(f"No downloaded GGUF files found in {root / 'runtime/models'}")
    if not any(item[0].name.lower() == "llama-server.exe" for item in sources):
        raise FileNotFoundError(f"llama-server.exe not found in {root / 'runtime/llama'}")
    try:
        output.relative_to(root / "runtime")
    except ValueError:
        pass
    else:
        raise ValueError("Backup target must not be inside runtime")

    site_packages = root / ".venv" / "Lib" / "site-packages"
    if not site_packages.is_dir():
        raise FileNotFoundError(
            f"Installed Python dependencies not found: {site_packages}")

    output.parent.mkdir(parents=True, exist_ok=True)
    runtime_bytes = sum(source.stat().st_size for source, _, _ in
                        {(_same_file_key(s) or s): (s, r, c) for s, r, c in sources}.values())
    dependency_bytes = sum(path.stat().st_size for path in site_packages.rglob("*")
                           if path.is_file() and "__pycache__" not in path.parts
                           and path.suffix.lower() not in {".pyc", ".pyo"})
    total_bytes = runtime_bytes + dependency_bytes
    reserve = 256 * 2**20
    free = shutil.disk_usage(output.parent).free
    if free < total_bytes + reserve:
        raise OSError(
            f"Not enough free space on {output.parent}: need about "
            f"{(total_bytes + reserve) / 2**30:.1f} GiB, available {free / 2**30:.1f} GiB")

    building = output.with_name(output.name + ".building")
    if building.exists():
        shutil.rmtree(building)
    building.mkdir(parents=True)
    records: list[dict[str, Any]] = []
    try:
        requirements = root / "requirements.txt"
        if not requirements.is_file():
            raise FileNotFoundError(f"Missing requirements.txt: {requirements}")
        shutil.copy2(requirements, building / "requirements.txt")
        lock = root / "requirements-windows-py312.lock"
        if lock.is_file():
            shutil.copy2(lock, building / lock.name)
        _write_readme(building / "README-OFFLINE.txt")
        print(f"[BACKUP] Copying {len(sources)} runtime files ({runtime_bytes / 2**30:.1f} GiB)")
        # Two weights share their second shard as one file under two names: it is
        # copied once, and the restore links the second name again.
        first_name: dict[tuple[int, int], dict[str, Any]] = {}
        for index, (source, relative, component) in enumerate(sources, 1):
            size = source.stat().st_size
            key = _same_file_key(source)
            if key in first_name:
                first = first_name[key]
                print(f"  [{index}/{len(sources)}] {relative} (the same file as {first['path']})")
                records.append({"path": relative.as_posix(), "size": size, "sha256": first["sha256"],
                                "component": component, "link_to": first["path"]})
                continue
            print(f"  [{index}/{len(sources)}] {relative} ({size / 2**20:.1f} MiB)")
            digest = _copy_with_hash(source, building / relative)
            records.append({"path": relative.as_posix(), "size": size,
                            "sha256": digest, "component": component})
            if key:
                first_name[key] = records[-1]

        print("[BACKUP] Copying installed Python dependencies from .venv ...")
        dependency_target = building / DEPENDENCY_ARCHIVE
        size, digest = _create_dependency_archive(site_packages, dependency_target)
        records.append({"path": DEPENDENCY_ARCHIVE.as_posix(), "size": size,
                        "sha256": digest, "component": "python-dependencies"})

        for path in sorted(building.rglob("*")):
            if not path.is_file() or path.name == MANIFEST_NAME:
                continue
            relative = path.relative_to(building)
            if relative.as_posix() in {item["path"] for item in records}:
                continue
            records.append({"path": relative.as_posix(), "size": path.stat().st_size,
                            "sha256": sha256_file(path),
                            "component": "metadata"})
        manifest = {
            "format_version": FORMAT_VERSION,
            "app_version": _version(root),
            "created": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "platform": platform.platform(),
            "python": platform.python_version(),
            "python_major_minor": f"{sys.version_info.major}.{sys.version_info.minor}",
            "python_architecture": platform.architecture()[0],
            "requirements_sha256": sha256_file(requirements),
            "lock_sha256": sha256_file(lock) if lock.is_file() else None,
            "files": records,
        }
        (building / MANIFEST_NAME).write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        building.rename(output)
        print(f"[DONE] Offline backup: {output}")
        return manifest
    except BaseException:
        shutil.rmtree(building, ignore_errors=True)
        raise


def load_manifest(backup: Path) -> dict[str, Any]:
    backup = backup.resolve()
    path = backup / MANIFEST_NAME
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("format_version") != FORMAT_VERSION or not isinstance(data.get("files"), list):
        raise ValueError(f"Unsupported or invalid backup manifest: {path}")
    return data


def verify_backup(backup: Path) -> dict[str, Any]:
    backup = backup.resolve()
    manifest = load_manifest(backup)
    errors: list[str] = []
    files = manifest["files"]
    for index, item in enumerate(files, 1):
        relative = _safe_relative(str(item["path"]))
        path = backup / _safe_relative(str(item.get("link_to") or item["path"]))
        print(f"  [{index}/{len(files)}] verify {relative}")
        if not path.is_file():
            errors.append(f"missing: {relative}")
            continue
        if path.stat().st_size != int(item["size"]):
            errors.append(f"size mismatch: {relative}")
            continue
        if sha256_file(path) != item["sha256"]:
            errors.append(f"sha256 mismatch: {relative}")
    result = {"ok": not errors, "files": len(files), "errors": errors,
              "app_version": manifest.get("app_version")}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return result


def restore_backup(root: Path, backup: Path,
                   components: set[str] | None = None) -> dict[str, Any]:
    root = root.resolve()
    backup = backup.resolve()
    manifest = load_manifest(backup)
    restored: list[str] = []
    skipped: list[str] = []
    for item in manifest["files"]:
        component = str(item.get("component") or "")
        if components is not None and component not in components:
            continue
        relative = _safe_relative(str(item["path"]))
        if not relative.parts or relative.parts[0] != "payload":
            continue
        payload_rel = Path(*relative.parts[1:])
        source = backup / _safe_relative(str(item.get("link_to") or item["path"]))
        target = root / payload_rel
        expected_size = int(item["size"])
        expected_hash = str(item["sha256"])
        if not source.is_file() or source.stat().st_size != expected_size:
            raise FileNotFoundError(f"Backup payload missing or damaged: {relative}")
        if target.is_file() and target.stat().st_size == expected_size \
                and sha256_file(target) == expected_hash:
            skipped.append(str(payload_rel))
            continue
        print(f"  restore {payload_rel} ({expected_size / 2**20:.1f} MiB)")
        if item.get("link_to"):
            twin = _payload_target(root, str(item["link_to"]))
            if twin.is_file() and twin.stat().st_size == expected_size:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.unlink(missing_ok=True)
                try:
                    os.link(twin, target)
                    restored.append(str(payload_rel))
                    continue
                except OSError as exc:
                    print(f"  (no hard link for {payload_rel}: {exc}; copying)")
        digest = _copy_with_hash(source, target)
        if digest != expected_hash:
            target.unlink(missing_ok=True)
            raise ValueError(f"SHA-256 mismatch while restoring {relative}")
        restored.append(str(payload_rel))
    dependency_state = "not-requested"
    if components is None or "python-dependencies" in components:
        dependency_state = _restore_dependencies(root, backup, manifest)
    engine = _fix_strata_environment(root) if any(
        str(path).replace("\\", "/").startswith("runtime/strata/") for path in restored) else "not-restored"
    result = {"ok": True, "restored": restored, "skipped": skipped,
              "dependencies": dependency_state, "strata_environment": engine,
              "app_version": manifest.get("app_version")}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return result


def _restore_dependencies(root: Path, backup: Path, manifest: dict[str, Any]) -> str:
    current_python = f"{sys.version_info.major}.{sys.version_info.minor}"
    current_arch = platform.architecture()[0]
    requirements = root / "requirements.txt"
    lock = root / "requirements-windows-py312.lock"
    compatible = (
        current_python == manifest.get("python_major_minor")
        and current_arch == manifest.get("python_architecture")
        and requirements.is_file()
        and sha256_file(requirements) == manifest.get("requirements_sha256")
        and (sha256_file(lock) if lock.is_file() else None) == manifest.get("lock_sha256")
    )
    dependency_item = next((item for item in manifest["files"]
                            if item.get("component") == "python-dependencies"), None)
    if not compatible or dependency_item is None:
        print("[BACKUP] Python dependency snapshot is not compatible; normal setup will repair it.")
        return "incompatible"

    archive_path = backup / _safe_relative(str(dependency_item["path"]))
    if (not archive_path.is_file()
            or archive_path.stat().st_size != int(dependency_item["size"])
            or sha256_file(archive_path) != dependency_item["sha256"]):
        raise ValueError("Python dependency snapshot is missing or damaged")
    venv = root / ".venv"
    site_packages = venv / "Lib" / "site-packages"
    temporary = venv / ".offline-dependencies-restoring"
    shutil.rmtree(temporary, ignore_errors=True)
    temporary.mkdir(parents=True)
    try:
        with zipfile.ZipFile(archive_path) as archive:
            for member in archive.infolist():
                _safe_relative(member.filename)
            archive.extractall(temporary)
        site_packages.mkdir(parents=True, exist_ok=True)
        shutil.copytree(temporary, site_packages, dirs_exist_ok=True)
        marker = venv / ".requirements.sha256"
        source = requirements.read_bytes()
        if lock.is_file():
            source += b"\nLOCK\n" + lock.read_bytes()
        marker.write_text(hashlib.sha256(source).hexdigest() + "\n", encoding="ascii")
        (venv / ".deps.ok").unlink(missing_ok=True)
    finally:
        shutil.rmtree(temporary, ignore_errors=True)
    print("[BACKUP] Restored installed Python dependencies from the local snapshot.")
    return "restored"


def backup_info(backup: Path) -> dict[str, Any]:
    backup = backup.resolve()
    manifest = load_manifest(backup)
    files = manifest["files"]
    return {"path": str(backup), "app_version": manifest.get("app_version"),
            "created": manifest.get("created"), "files": len(files),
            "bytes": sum(int(item.get("size", 0)) for item in files),
            "models": [Path(item["path"]).name for item in files
                       if item.get("component") == "models"
                       and str(item["path"]).lower().endswith(".gguf")],
            "dependencies": any(item.get("component") == "python-dependencies"
                                for item in files),
            "installer": next((Path(item["path"]).name for item in files
                               if item.get("component") == "installer"), None)}


def attach_installer(backup: Path, installer: Path) -> dict[str, Any]:
    backup = backup.resolve()
    installer = installer.resolve()
    manifest = load_manifest(backup)
    if not installer.is_file() or installer.suffix.lower() != ".exe":
        raise FileNotFoundError(f"Setup executable not found: {installer}")
    target = backup / installer.name
    digest = _copy_with_hash(installer, target)
    readme = backup / "README-OFFLINE.txt"
    _write_readme(readme)
    manifest["files"] = [item for item in manifest["files"]
                         if item.get("component") != "installer"
                         and item.get("path") != "README-OFFLINE.txt"]
    manifest["files"].append({"path": installer.name, "size": target.stat().st_size,
                              "sha256": digest, "component": "installer"})
    manifest["files"].append({"path": "README-OFFLINE.txt", "size": readme.stat().st_size,
                              "sha256": sha256_file(readme), "component": "metadata"})
    manifest_path = backup / MANIFEST_NAME
    temporary = manifest_path.with_name(manifest_path.name + ".tmp")
    temporary.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, manifest_path)
    print(f"[DONE] Installer added to offline backup: {target}")
    return manifest


# Application-level files that a version bump replaces. Weights, llama.cpp and
# WebView2 do not follow the application version and are deliberately excluded:
# re-copying them would mean hours of I/O for identical bytes.
APPLICATION_FILES = (
    ("Marvin-Manual-EN.pdf", "output/pdf/Marvin-Manual-EN.pdf"),
    ("Marvin-Manual-CS.pdf", "output/pdf/Marvin-Manual-CS.pdf"),
    ("INSTALL-EN.md", "docs/distribution/INSTALL-EN.md"),
    ("INSTALL-CS.md", "docs/distribution/INSTALL-CS.md"),
    ("requirements.txt", "requirements.txt"),
    ("requirements-windows-py312.lock", "requirements-windows-py312.lock"),
)


RUNTIME_COMPONENTS = {"models", "llama", "strata", "whisper", "openart", "webview2", "settings"}


def refresh_backup(root: Path, backup: Path, *, runtime_root: Path | None = None,
                   exclude: tuple[str, ...] = (), quarantine: Path | None = None) -> dict[str, Any]:
    """Bring an existing offline backup up to the application's current version.

    Replaces only what a version bump actually changes and says which files those
    were, so the answer is measured rather than assumed. The Python dependency
    archive is rebuilt only when requirements or the lock really moved; leaving a
    stale archive beside new requirements would make the backup inconsistent."""
    root, backup = root.resolve(), backup.resolve()
    # The application (version, installer, manuals, requirements) comes from `root`;
    # models, inference programs and the Python environment from `runtime_root`,
    # for example an installed copy that holds the downloaded models.
    runtime_root = (runtime_root or root).resolve()
    manifest = load_manifest(backup)
    version = _version(root)
    records = {item["path"]: item for item in manifest["files"]}
    changed: list[str] = []

    def put(relative: str, source: Path, component: str) -> None:
        digest = sha256_file(source)
        current = records.get(relative)
        if current and current.get("sha256") == digest and (backup / relative).is_file():
            return
        _copy_with_hash(source, backup / relative)
        records[relative] = {"path": relative, "size": source.stat().st_size,
                             "sha256": digest, "component": component}
        changed.append(relative)

    installer = root / "dist" / f"Marvin-Setup-{version}-Full.exe"
    if not installer.is_file():
        installer = root / "dist" / f"Marvin-Setup-{version}-Minimal.exe"
    if not installer.is_file():
        raise FileNotFoundError(f"No Setup executable for {version} in {root / 'dist'}")
    for stale in sorted(backup.glob("Marvin-Setup-*.exe")):
        if stale.name != installer.name:
            stale.unlink()
            records.pop(stale.name, None)
            changed.append("removed " + stale.name)
    put(installer.name, installer, "installer")

    for relative, source in APPLICATION_FILES:
        candidate = root / source
        if candidate.is_file():
            put(relative, candidate, "metadata")

    # Runtime payload a new version may have introduced - 1.12.0 added dictation.
    # Files already recorded at the same size are left alone: re-reading the whole
    # model payload to learn that nothing moved would cost half an hour.
    first_name: dict[tuple[int, int], str] = {}
    current = _runtime_sources(runtime_root, exclude)
    for source, relative, component in current:
        key = relative.as_posix()
        recorded = records.get(key)
        same = _same_file_key(source)
        if same in first_name:
            twin = records[first_name[same]]
            records[key] = {"path": key, "size": source.stat().st_size, "sha256": twin["sha256"],
                            "component": component, "link_to": twin["path"]}
            continue
        if same:
            first_name[same] = key
        target = backup / _safe_relative(str((recorded or {}).get("link_to") or key))
        if recorded and target.is_file() \
                and recorded.get("size") == source.stat().st_size \
                and target.stat().st_size == source.stat().st_size:
            continue
        put(key, source, component)

    if quarantine is not None:
        # Payload the installation no longer has (an entry that was removed): moved aside, not deleted.
        present = {relative.as_posix() for _, relative, _ in current}
        for key, record in list(records.items()):
            if record.get("component") in RUNTIME_COMPONENTS and key not in present:
                records.pop(key)
                target = backup / _safe_relative(key)
                if target.is_file() and not record.get("link_to"):
                    moved = quarantine / _safe_relative(key)
                    moved.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(target), str(moved))
                changed.append("set aside " + key)

    requirements = root / "requirements.txt"
    lock = root / "requirements-windows-py312.lock"
    requirements_digest = sha256_file(requirements)
    lock_digest = sha256_file(lock) if lock.is_file() else None
    if (manifest.get("requirements_sha256") != requirements_digest
            or manifest.get("lock_sha256") != lock_digest):
        site_packages = runtime_root / ".venv" / "Lib" / "site-packages"
        if not site_packages.is_dir():
            raise FileNotFoundError(f"Installed Python dependencies not found: {site_packages}")
        print("[REFRESH] Dependencies moved - rebuilding the archive ...")
        size, digest = _create_dependency_archive(site_packages, backup / DEPENDENCY_ARCHIVE)
        records[DEPENDENCY_ARCHIVE.as_posix()] = {
            "path": DEPENDENCY_ARCHIVE.as_posix(), "size": size, "sha256": digest,
            "component": "python-dependencies"}
        changed.append(DEPENDENCY_ARCHIVE.as_posix())
    else:
        print("[REFRESH] Requirements and lock unchanged - dependency archive kept")

    readme = backup / "README-OFFLINE.txt"
    _write_readme(readme)
    readme_digest = sha256_file(readme)
    if records.get("README-OFFLINE.txt", {}).get("sha256") != readme_digest:
        changed.append("README-OFFLINE.txt")
    records["README-OFFLINE.txt"] = {"path": "README-OFFLINE.txt",
                                     "size": readme.stat().st_size,
                                     "sha256": readme_digest, "component": "metadata"}

    manifest.update(app_version=version, requirements_sha256=requirements_digest,
                    lock_sha256=lock_digest,
                    updated=time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                    files=list(records.values()))
    path = backup / MANIFEST_NAME
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)
    print(f"[DONE] Offline backup refreshed to {version}; changed: "
          + (", ".join(changed) if changed else "nothing"))
    renamed = _rename_for_version(backup, version)
    if renamed != backup:
        manifest["path"] = str(renamed)
        print(f"[DONE] Renamed to {renamed.name}")
    return manifest


def _rename_for_version(backup: Path, version: str) -> Path:
    """Keep the folder name honest about what is inside it.

    The name carries the version, and it was corrected by hand after every
    release - which is exactly how the pointer inside an installation came to
    name a version that no longer existed."""
    import re
    match = re.fullmatch(r"(?i)(Marvin-Offline-Backup-)(\d+(?:\.\d+)*)", backup.name)
    if not match or match.group(2) == version:
        return backup
    target = backup.with_name(match.group(1) + version)
    if target.exists():
        print(f"[WARN] {target.name} already exists; the folder keeps its name")
        return backup
    try:
        backup.rename(target)
    except OSError as error:
        print(f"[WARN] Could not rename the backup folder: {error}")
        return backup
    return target


def _main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("create")
    create.add_argument("--output", required=True)
    create.add_argument("--root", default=str(Path(__file__).resolve().parent.parent))
    verify = sub.add_parser("verify")
    verify.add_argument("--backup", required=True)
    restore = sub.add_parser("restore")
    restore.add_argument("--backup", required=True)
    restore.add_argument("--root", default=str(Path(__file__).resolve().parent.parent))
    restore.add_argument("--components", default=None,
                         help="comma-separated components "
                              "(models,llama,strata,whisper,openart,webview2,settings,python-dependencies)")
    info = sub.add_parser("info")
    info.add_argument("--backup", required=True)
    refresh = sub.add_parser("refresh")
    refresh.add_argument("--backup", required=True)
    refresh.add_argument("--root", default=str(Path(__file__).resolve().parent.parent))
    refresh.add_argument("--runtime-root", help="installation to take models, runtimes and packages from")
    refresh.add_argument("--exclude-models", default="",
                         help="comma-separated paths under runtime/models to leave out")
    refresh.add_argument("--quarantine", help="folder to move payload the installation no longer has into")
    attach = sub.add_parser("attach-installer")
    attach.add_argument("--backup", required=True)
    attach.add_argument("--installer", required=True)
    args = parser.parse_args()
    try:
        if args.command == "create":
            create_backup(Path(args.root), Path(args.output))
        elif args.command == "verify":
            return 0 if verify_backup(Path(args.backup))["ok"] else 1
        elif args.command == "restore":
            selected = ({part.strip() for part in args.components.split(",") if part.strip()}
                        if args.components else None)
            restore_backup(Path(args.root), Path(args.backup), selected)
        elif args.command == "info":
            print(json.dumps(backup_info(Path(args.backup)), ensure_ascii=False, indent=2))
        elif args.command == "refresh":
            refresh_backup(Path(args.root), Path(args.backup),
                           runtime_root=Path(args.runtime_root) if args.runtime_root else None,
                           exclude=tuple(x.strip() for x in args.exclude_models.split(",") if x.strip()),
                           quarantine=Path(args.quarantine) if args.quarantine else None)
        elif args.command == "attach-installer":
            attach_installer(Path(args.backup), Path(args.installer))
        return 0
    except Exception as exc:
        print(f"[ERROR] {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(_main())
