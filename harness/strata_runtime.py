"""Prepare the Strata engine and a Flash-Next model's derived files inside Marvin.

Design: docs/design/2026-10-05-strata-backend.md, section 2.7. Everything runs in
the usual download, verify and prepare phases of a model switch, so the user sees
only the model's progress:

- the engine (`ensure_runtime`): Strata's pinned source (its server and tools),
  the release engine, llama.cpp's gguf-py for the packer and a private Python
  environment from a hashed lock, staged under runtime/strata-candidates,
  checked, and swapped in like the llama.cpp runtime (harness/runtime_update.py);
- a model's derived files (`prepare_model`), once its weights are verified: the
  pack Strata reads the GGUF through, and the MTP draft layer built from the
  pinned upstream checkpoint. Each step can be repeated after an interruption.

A folder that already holds a working Strata (one Strata's own setup prepared,
named in paths.strata_dir) is used as it is.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import zipfile

from harness import strata_backend
from harness.config import ROOT, Config
from harness.runtime_update import activate_runtime, extract_archive, sha256

VERSION = "0.1.39"
# The v0.1.39 tag moved from 6f32ec0 to this commit with the same files; GitHub's
# generated archives are checked by their content, the release asset by its bytes.
SOURCE = {"url": "https://github.com/Niko1221/Strata/archive/a1641e9f77aacad4d201b53c8a7ae8fa21059ebb.zip",
          "name": "strata-source.zip",
          "content": "b55a5b23165d770bcc52ec2d64c1c0765a57478c9b0ecf261872b942bdbfb3fb"}
ENGINE = {"url": f"https://github.com/Niko1221/Strata/releases/download/v{VERSION}/strata-windows-x64.zip",
          "name": "strata-windows-x64.zip",
          "sha256": "a862bcfa2330cd1c23f9b5d6e49f4027da8f8313842bd62e858ec6cd4533813a"}
# The packer reads the GGUF with llama.cpp's gguf-py at the commit Strata's setup pins.
GGUF_PY = {"url": "https://github.com/ggml-org/llama.cpp/archive/3cf03257f219afbe7334045ff7c6a06ac68c627d.zip",
           "name": "llama.cpp-gguf-py.zip", "subtree": "gguf-py/",
           "content": "96c1f2d0a346feba623eeb26b3d4e5a290d28aa4850dad121208517b0861c42f"}
LOCK = ROOT / "requirements-strata-py312.lock"
MARKER = ".marvin-strata.json"
DRAFT_VOCAB = "draft_vocab.bin"      # Strata setup's default subset for the draft head
NO_WINDOW = 0x08000000 if os.name == "nt" else 0


def _content_digest(archive: zipfile.ZipFile, subtree: str = "") -> str:
    """SHA-256 over the files' own hashes, independent of how the archive was compressed."""
    items = []
    for info in archive.infolist():
        if info.is_dir():
            continue
        relative = info.filename.split("/", 1)[1] if "/" in info.filename else info.filename
        if relative.startswith(subtree):
            items.append(f"{relative}\0{hashlib.sha256(archive.read(info)).hexdigest()}\n")
    return hashlib.sha256("".join(sorted(items)).encode()).hexdigest()


def _check(path: Path, spec: dict) -> bool:
    try:
        if "sha256" in spec:
            return sha256(path) == spec["sha256"]
        with zipfile.ZipFile(path) as archive:
            return _content_digest(archive, spec.get("subtree", "")) == spec["content"]
    except (OSError, zipfile.BadZipFile):
        return False


def _fetch(spec: dict, cache: Path, *, cancelled=None, progress=print) -> Path:
    import requests
    path = cache / spec["name"]
    if path.is_file() and _check(path, spec):
        return path
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


def _extract_stripped(archive_path: Path, target: Path, subtree: str = "") -> None:
    """Extract the archive's single top folder (or only `subtree` of it) into `target`."""
    with zipfile.ZipFile(archive_path) as archive:
        tops = {info.filename.split("/", 1)[0] for info in archive.infolist() if "/" in info.filename}
        single = len(tops) == 1 and all("/" in info.filename for info in archive.infolist())
        for info in archive.infolist():
            name = info.filename.split("/", 1)[1] if single else info.filename
            if not name or (subtree and not name.startswith(subtree)):
                continue
            destination = (target / name).resolve()
            if not destination.is_relative_to(target.resolve()):
                raise ValueError(f"Unexpected path in {archive_path.name}: {info.filename}")
            if info.is_dir():
                destination.mkdir(parents=True, exist_ok=True)
                continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info) as source, destination.open("wb") as output:
                shutil.copyfileobj(source, output)


def _base_python() -> Path:
    """The interpreter Marvin's own environment was made from (runtime/python in Full)."""
    bundled = ROOT / "runtime" / "python" / "python.exe"
    if bundled.is_file():
        return bundled
    return Path(getattr(sys, "_base_executable", None) or sys.executable)


def _run(argv: list, *, cwd: Path, env: dict | None = None, cancelled=None, progress=print, what: str) -> None:
    """Run one preparation step, passing its output on; a failure says what failed and how it ended."""
    tail: list[str] = []
    proc = subprocess.Popen([str(a) for a in argv], cwd=str(cwd), env=env, stdin=subprocess.DEVNULL,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                            errors="replace", creationflags=NO_WINDOW)
    try:
        for line in proc.stdout:
            line = line.rstrip()
            if line:
                tail = (tail + [line])[-12:]
                progress(f"    {line}")
            if cancelled and cancelled():
                proc.terminate()
                raise InterruptedError("Model preparation cancelled")
        code = proc.wait()
    finally:
        if proc.poll() is None:
            proc.kill()
    if code:
        raise RuntimeError(f"{what} failed (exit code {code}): " + " | ".join(tail[-4:]))


def tool_env(cfg: Config) -> dict:
    env = strata_backend.server_env()
    env["STRATA_GGUF_PY"] = str(strata_backend.program_dir(cfg) / "third_party" / "llama.cpp" / "gguf-py")
    return env


def _lock_digest() -> str:
    return sha256(LOCK)


def installed_record(cfg: Config) -> dict:
    try:
        return json.loads((strata_backend.program_dir(cfg) / MARKER).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def runtime_current(cfg: Config, key: str) -> bool:
    """Whether the program folder can start the model: every file present, and, where Marvin
    installed it, the pinned version. A folder Strata's setup prepared has no record and is kept."""
    if strata_backend.runtime_problems(cfg, key):
        return False
    record = installed_record(cfg)
    return not record or (record.get("version") == VERSION and record.get("lock") == _lock_digest())


def install(cfg: Config, *, cancelled=None, progress=print, on_phase=None) -> Path:
    """Stage the pinned engine, server, tools and Python environment, check them and swap them in."""
    target = strata_backend.program_dir(cfg)
    runtime = cfg.path("paths.runtime_dir")
    cache = runtime / "runtime-archives" / f"strata-{VERSION}"
    cache.mkdir(parents=True, exist_ok=True)
    if on_phase:
        on_phase("downloading")
    archives = {name: _fetch(spec, cache, cancelled=cancelled, progress=progress)
                for name, spec in (("source", SOURCE), ("engine", ENGINE), ("gguf_py", GGUF_PY))}
    if on_phase:
        on_phase("preparing")
    stage = runtime / "strata-candidates" / f"{VERSION}-{time.time_ns()}"
    stage.mkdir(parents=True)
    try:
        progress(f"Preparing the model engine {VERSION}")
        _extract_stripped(archives["source"], stage)
        _extract_stripped(archives["gguf_py"], stage / "third_party" / "llama.cpp", GGUF_PY["subtree"])
        (stage / "engine").mkdir(exist_ok=True)
        extract_archive(archives["engine"], stage / "engine")
        venv_python = stage / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        _run([_base_python(), "-m", "venv", stage / ".venv"], cwd=stage, cancelled=cancelled, progress=progress,
             what="Creating the engine's Python environment")
        _run([venv_python, "-m", "pip", "install", "--require-hashes", "--no-deps", "--disable-pip-version-check",
              "--no-input", "-r", LOCK], cwd=stage, cancelled=cancelled, progress=progress,
             what="Installing the engine's Python packages")
        build = json.loads((stage / "engine" / "BUILD.json").read_text(encoding="utf-8"))
        if build.get("version") != VERSION:
            raise RuntimeError(f"The downloaded engine reports version {build.get('version')}, not {VERSION}.")
        if not any((stage / ".venv").rglob("cublas64_13.dll")):
            raise RuntimeError("The engine's CUDA libraries (cublas64_13.dll) were not installed.")
        driver = _driver_version()
        if driver and driver < 580:
            progress(f"[WARNING] The NVIDIA driver is {driver}; the engine needs 580 or newer (CUDA 13).")
        (stage / MARKER).write_text(json.dumps({
            "version": VERSION, "source": SOURCE["url"], "engine": ENGINE["sha256"], "gguf_py": GGUF_PY["url"],
            "lock": _lock_digest(), "python": str(_base_python()), "installed": time.strftime("%Y-%m-%d %H:%M:%S"),
        }, indent=2), encoding="utf-8")
        if cancelled and cancelled():
            raise InterruptedError("Model preparation cancelled")
        target.parent.mkdir(parents=True, exist_ok=True)
        backup = activate_runtime(stage, target)
        if backup:
            progress(f"Previous model engine preserved at {backup}")
    except BaseException:
        shutil.rmtree(stage, ignore_errors=True)
        raise
    return target


def _driver_version() -> int | None:
    try:
        output = subprocess.run(["nvidia-smi", "--query-gpu=driver_version", "--format=csv,noheader"],
                                capture_output=True, text=True, timeout=10, creationflags=NO_WINDOW).stdout
        return int(output.strip().splitlines()[0].split(".")[0])
    except (OSError, ValueError, IndexError, subprocess.SubprocessError):
        return None


def ensure_runtime(cfg: Config, key: str, *, cancelled=None, progress=print, on_phase=None) -> None:
    if not runtime_current(cfg, key):
        install(cfg, cancelled=cancelled, progress=progress, on_phase=on_phase)


def _mtp_complete(rt: Path) -> bool:
    return all((rt / name).is_file() for name in ("experts.bin", "dense.bin", "dense.txt"))


def prepare_model(cfg: Config, key: str, *, cancelled=None, progress=print, on_phase=None) -> None:
    """The pack and the MTP draft layer for a model whose weights are verified."""
    settings, data = strata_backend.settings(cfg, key), strata_backend.data_dir(cfg)
    program, python, env = strata_backend.program_dir(cfg), strata_backend.python_exe(cfg), tool_env(cfg)
    pack = data / settings["pack"]
    if not (pack / "native_experts.txt").is_file() or not (pack / "tokenizer" / "vocab.json").is_file():
        if on_phase:
            on_phase("preparing")
        progress(f"Preparing the model files in {pack}")
        _run([python, program / "tools" / "iq_pack.py", "--gguf", cfg.model_file(key), "--out", pack],
             cwd=program, env=env, cancelled=cancelled, progress=progress, what="Preparing the model files")
    rt = data / settings["mtp"]
    mtp = rt.parent
    if not _mtp_complete(rt):
        if on_phase:
            on_phase("downloading")
        progress("Downloading the draft layer for faster answers")
        _run([python, program / "tools" / "mtp_fetch.py", "fetch", "--out", mtp], cwd=program, env=env,
             cancelled=cancelled, progress=progress, what="Downloading the draft layer")
        if on_phase:
            on_phase("preparing")
        gguf = mtp / "mtp-q2_0.gguf"
        _run([python, program / "tools" / "mtp_pack.py", "--src", mtp, "--experts", "q2_0", "--out", gguf],
             cwd=program, env=env, cancelled=cancelled, progress=progress, what="Preparing the draft layer")
        # mtp_rt writes in place; a finished folder only takes the place of the old one.
        partial = mtp / (rt.name + ".partial")
        shutil.rmtree(partial, ignore_errors=True)
        _run([python, program / "tools" / "mtp_rt.py", "--gguf", gguf, "--out", partial], cwd=program, env=env,
             cancelled=cancelled, progress=progress, what="Preparing the draft layer")
        if rt.exists():
            rt.rename(mtp / f"{rt.name}-incomplete-{time.time_ns()}")
        partial.rename(rt)
    vocab = rt / DRAFT_VOCAB
    if not vocab.exists() and (program / "data" / DRAFT_VOCAB).is_file():
        shutil.copyfile(program / "data" / DRAFT_VOCAB, vocab)
