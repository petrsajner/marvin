"""Application project registry, folder relocation, and Git workspace recovery.

projects.json stores id, name, path, creation time, work mode, and optional Git
identity (sanitized origin URL, branch, and root commit hash). When a project
directory moves to another folder or drive, Marvin can locate it automatically,
let the owner pick or create a folder via the native Explorer dialog, and
restore the GitHub connection and local Git repository in a new directory."""
from __future__ import annotations

import configparser
import ctypes
import json
import os
import re
import shutil
import subprocess
import time
import urllib.parse
import uuid
from collections import deque
from pathlib import Path

from harness.config import Config
from harness.work_modes import normalize_work_mode

_NO_WINDOW = 0x08000000 if os.name == "nt" else 0

_MARVIN_MARKERS: tuple[str, ...] = (
    "QWEN_MEMORY.md",
    ".qwen/decisions.json",
    ".qwen/project.yaml",
)

_SKIP_DIRS: frozenset[str] = frozenset({
    "$recycle.bin",
    "system volume information",
    "windows",
    "windows.old",
    "program files",
    "program files (x86)",
    "programdata",
    "recovery",
    "perflogs",
    "msocache",
    "appdata",
    "boot",
    "drivers",
    "intel",
    "amd",
    "nvidia",
    "winsxs",
    "node_modules",
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    "dist",
    "build",
    "target",
    ".next",
    ".nuxt",
    ".cache",
    ".gradle",
    ".m2",
    "site-packages",
    "temp",
    "tmp",
})

_HOME_DEV_SUBDIRS: tuple[str, ...] = (
    "Projects",
    "Repos",
    "Source",
    "source/repos",
    "Dev",
    "Code",
    "Work",
    "Documents",
    "Desktop",
    "OneDrive",
)


def _path_key(value: str | Path | None) -> str:
    if not value:
        return ""
    text = os.path.normpath(str(value))
    return os.path.normcase(text) if os.name == "nt" else text


def validate_root(value: str, cfg: Config) -> Path:
    """Check a chosen location for new projects, or raise ValueError.

    Existing projects keep the absolute path they were created with, so changing
    this moves nothing on disk; it only decides where the next one goes."""
    if not str(value).strip():
        raise ValueError("Choose a folder for new projects")
    path = Path(str(value).strip().strip('"')).expanduser()
    if not path.is_absolute():
        raise ValueError("The project folder must be an absolute path")
    path = path.resolve()
    if not path.is_dir():
        raise ValueError(f"Folder does not exist: {path}")
    for reserved in ("paths.runtime_dir", "paths.sessions_dir"):
        guarded = cfg.path(reserved).resolve()
        if path == guarded or guarded in path.parents or path in guarded.parents:
            raise ValueError(
                "Projects cannot live inside the model runtime or the "
                f"conversation history: {guarded}")
    probe = path / f".marvin-write-probe-{id(path):x}"
    try:
        probe.write_text("", encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"Folder is not writable: {path}") from exc
    finally:
        probe.unlink(missing_ok=True)
    return path


def _safe_name(name: str) -> str:
    name = re.sub(r'[<>:"/\\|?*]', "-", name).strip(". ")
    return name or "project"


def sanitize_git_remote(url: str | None) -> str:
    """Return a credential-free Git remote URL, or '' if empty/unsafe.

    Rejects option-like strings (starting with '-') and strips embedded HTTP(S)
    userinfo so access tokens are never persisted in projects.json."""
    text = str(url or "").strip()
    if not text or text.startswith("-"):
        return ""
    if any(ch in text for ch in ("\r", "\n", "\x00")):
        return ""
    lower = text.lower()
    if lower.startswith(("http://", "https://")):
        parts = urllib.parse.urlsplit(text)
        host = parts.hostname or ""
        if not host:
            return ""
        if ":" in host and not host.startswith("["):
            host = f"[{host}]"
        netloc = f"{host}:{parts.port}" if parts.port else host
        return urllib.parse.urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))
    return text


def normalize_git_remote(url: str | None) -> str:
    """Normalize HTTPS/SSH/SCP Git remote URLs to a canonical comparison key."""
    clean = sanitize_git_remote(url)
    if not clean:
        return ""
    # SCP-style SSH URL: git@github.com:owner/repo.git
    scp = re.match(r"^(?:[^@/\s]+@)?([^:/\s]+):(.+)$", clean)
    if scp and not re.match(r"^[a-zA-Z]:[\\/]", clean) and "://" not in clean:
        host, rest = scp.group(1).lower(), scp.group(2).strip("/")
        if rest.lower().endswith(".git"):
            rest = rest[:-4]
        return f"{host}/{rest.lower()}"
    if "://" in clean:
        parts = urllib.parse.urlsplit(clean)
        scheme = (parts.scheme or "").lower()
        if scheme == "file":
            raw_path = urllib.parse.unquote(parts.path or "")
            if os.name == "nt" and raw_path.startswith("/") and len(raw_path) > 2 and raw_path[2] == ":":
                raw_path = raw_path[1:]
            return _normalize_local_remote(raw_path)
        host = (parts.hostname or "").lower()
        rest = (parts.path or "").strip("/")
        if rest.lower().endswith(".git"):
            rest = rest[:-4]
        return f"{host}/{rest.lower()}" if host else rest.lower()
    return _normalize_local_remote(clean)


def _normalize_local_remote(raw: str) -> str:
    text = raw.replace("\\", "/").rstrip("/")
    if text.lower().endswith(".git"):
        text = text[:-4]
    return text.lower() if os.name == "nt" else text


def _safe_branch_name(branch: str | None) -> str:
    text = str(branch or "").strip()
    if not text or text.startswith("-"):
        return ""
    if any(bad in text for bad in (" ", "\t", "\r", "\n", "..", "~", "^", ":", "\\", "@{", "\x00")):
        return ""
    return text


def _run_git(cwd: Path, args: list[str], timeout: int = 10) -> subprocess.CompletedProcess | None:
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    try:
        return subprocess.run(
            ["git", *args],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdin=subprocess.DEVNULL,
            timeout=timeout,
            creationflags=_NO_WINDOW,
            env=env,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None


def _fast_origin_from_git_config(path: Path) -> str:
    """Read origin URL straight from .git/config without spawning git.exe."""
    git_entry = path / ".git"
    config_file = git_entry / "config" if git_entry.is_dir() else None
    if config_file is None or not config_file.is_file():
        return ""
    parser = configparser.RawConfigParser()
    try:
        parser.read_string(config_file.read_text(encoding="utf-8", errors="replace"))
    except (OSError, configparser.Error):
        return ""
    for section in parser.sections():
        if section.strip().lower() == 'remote "origin"':
            return sanitize_git_remote(parser.get(section, "url", fallback=""))
    return ""


def read_git_identity(path: Path) -> dict[str, str]:
    """Read sanitized origin remote, current branch, and root commit of a Git folder."""
    if not path.is_dir() or not (path / ".git").exists():
        return {}
    info: dict[str, str] = {}
    remote_proc = _run_git(path, ["remote", "get-url", "origin"], timeout=5)
    if remote_proc and remote_proc.returncode == 0:
        remote = sanitize_git_remote(remote_proc.stdout)
        if remote:
            info["git_remote"] = remote
    branch_proc = _run_git(path, ["branch", "--show-current"], timeout=5)
    if branch_proc and branch_proc.returncode == 0:
        branch = _safe_branch_name(branch_proc.stdout)
        if branch:
            info["git_branch"] = branch
    root_proc = _run_git(path, ["rev-list", "--max-parents=0", "HEAD"], timeout=5)
    if root_proc and root_proc.returncode == 0:
        first = next((line.strip() for line in (root_proc.stdout or "").splitlines() if line.strip()), "")
        if first:
            info["git_root_commit"] = first
    return info


def _has_marvin_marker(path: Path) -> bool:
    for rel in _MARVIN_MARKERS:
        try:
            if (path / rel).exists():
                return True
        except OSError:
            continue
    return False


def _local_drives() -> list[Path]:
    """Return mounted local fixed/removable drive roots on Windows (never network drives)."""
    if os.name != "nt":
        return []
    DRIVE_REMOVABLE = 2
    DRIVE_FIXED = 3
    drives: list[Path] = []
    try:
        kernel32 = ctypes.windll.kernel32
        mask = int(kernel32.GetLogicalDrives())
        for bit in range(26):
            if not (mask & (1 << bit)):
                continue
            root = f"{chr(ord('A') + bit)}:\\"
            dtype = int(kernel32.GetDriveTypeW(root))
            if dtype in (DRIVE_FIXED, DRIVE_REMOVABLE):
                p = Path(root)
                try:
                    if p.is_dir():
                        drives.append(p)
                except OSError:
                    continue
    except Exception:
        return []
    return drives


def find_relocated_folder(
    project: dict,
    cfg: Config,
    *,
    other_paths: set[str] | None = None,
    drives: list[Path] | None = None,
    extra_roots: list[Path] | None = None,
    max_dirs: int = 2500,
    timeout_s: float = 4.0,
) -> Path | None:
    """Attempt to locate a moved project directory across folders and local drives.

    Priority:
    1. Exact relative path on another local drive (e.g. D:\\Work\\App -> E:\\Work\\App).
    2. Nearby folders (same parent, grandparent, configured project root, siblings of
       other registered projects, common user dev folders).
    3. Shallow scan (depth 2) of local fixed/removable drives, skipping OS/cache trees.

    When Git identity (root commit or origin remote) is known, only a Git-verified
    match is accepted so decoy folders with the same name never cause a wrong redirect.
    When no Git identity exists, an unambiguous single best match by folder name
    (preferring folders with Marvin markers) is returned; ties return None so the
    user chooses manually."""
    old_raw = project.get("path") or ""
    if not old_raw:
        return None
    old_path = Path(old_raw)
    old_name = (old_path.name or project.get("name") or "").strip()
    if not old_name:
        return None
    old_name_lower = old_name.lower()

    target_root_commit = (project.get("git_root_commit") or "").strip().lower()
    target_remote = normalize_git_remote(project.get("git_remote"))
    has_git_id = bool(target_root_commit or target_remote)

    excluded = {_path_key(p) for p in (other_paths or ()) if p}
    excluded.add(_path_key(old_path))

    local_drives = list(drives) if drives is not None else _local_drives()
    deadline = time.monotonic() + max(0.2, float(timeout_s))

    checked_keys: set[str] = set()
    candidates: list[tuple[int, int, int, Path]] = []  # (score, same_name, -depth_len, path)
    git_probes = 0
    max_git_probes = 60

    def _evaluate(cand: Path, *, allow_git_probe: bool) -> int:
        nonlocal git_probes
        key = _path_key(cand)
        if not key or key in excluded or key in checked_keys:
            return 0
        checked_keys.add(key)
        try:
            if not cand.is_dir():
                return 0
        except OSError:
            return 0

        same_name = int(cand.name.lower() == old_name_lower)

        if has_git_id:
            if not (cand / ".git").exists():
                return 0
            # Fast pure-Python remote check first (zero subprocess overhead).
            fast_remote = normalize_git_remote(_fast_origin_from_git_config(cand))
            if target_remote and fast_remote and fast_remote != target_remote and not target_root_commit:
                return 0
            should_probe = (
                (target_remote and fast_remote == target_remote)
                or same_name == 1
                or (allow_git_probe and git_probes < max_git_probes)
            )
            if not should_probe:
                return 0
            if git_probes >= max_git_probes:
                # If fast remote already matched identically, accept even if probe budget ran out.
                if target_remote and fast_remote == target_remote:
                    score = 90
                    candidates.append((score, same_name, -len(cand.parts), cand.resolve()))
                    return score
                return 0
            git_probes += 1
            ident = read_git_identity(cand)
            cand_root = (ident.get("git_root_commit") or "").strip().lower()
            cand_remote = normalize_git_remote(ident.get("git_remote")) or fast_remote

            root_match = bool(target_root_commit and cand_root and cand_root == target_root_commit)
            remote_match = bool(target_remote and cand_remote and cand_remote == target_remote)
            root_conflict = bool(target_root_commit and cand_root and cand_root != target_root_commit)
            remote_conflict = bool(target_remote and cand_remote and cand_remote != target_remote)

            if root_match and remote_match:
                score = 100
            elif root_match:
                score = 95
            elif remote_match and not root_conflict:
                score = 90
            else:
                if root_conflict or remote_conflict:
                    return 0
                return 0
            candidates.append((score, same_name, -len(cand.parts), cand.resolve()))
            return score

        # Non-Git project: require exact folder name match (case-insensitive).
        if not same_name:
            return 0
        score = 70 if _has_marvin_marker(cand) else 50
        candidates.append((score, same_name, -len(cand.parts), cand.resolve()))
        return score

    # --- Tier 1: Same relative path on other local drives & direct top-level drive match ---
    rel_tail: Path | None = None
    if old_path.drive and len(old_path.parts) > 1:
        rel_tail = Path(*old_path.parts[1:])
    for drv in local_drives:
        if time.monotonic() > deadline:
            break
        if rel_tail is not None:
            if _evaluate(drv / rel_tail, allow_git_probe=True) >= 90:
                break
        if _evaluate(drv / old_name, allow_git_probe=True) >= 90:
            break

    if any(score >= 90 for score, *_ in candidates):
        candidates.sort(key=lambda item: (item[0], item[1], item[2]), reverse=True)
        return candidates[0][3]

    # --- Tier 2: Nearby & known project roots ---
    tier2_roots: list[tuple[Path, int, bool]] = []  # (root, max_depth, allow_git_probe)
    seen_roots: set[str] = set()

    def _add_root(root: Path | None, depth: int, probe: bool) -> None:
        if root is None:
            return
        try:
            if not root.is_dir():
                return
            resolved = root.resolve()
        except OSError:
            return
        rk = _path_key(resolved)
        if rk in seen_roots:
            return
        seen_roots.add(rk)
        tier2_roots.append((resolved, depth, probe))

    _add_root(Projects(cfg).root_dir, 2, True)
    _add_root(old_path.parent, 2, True)
    if old_path.parent != old_path.parent.parent:
        _add_root(old_path.parent.parent, 2, True)
    for raw_other in other_paths or ():
        _add_root(Path(raw_other).parent, 2, True)
    for root in extra_roots or ():
        _add_root(root, 3, True)
    if drives is None:
        home = Path.home()
        for sub in _HOME_DEV_SUBDIRS:
            _add_root(home / sub, 2, True)

    # --- Tier 3: Shallow scan of local drives (depth 2) ---
    tier3_roots: list[tuple[Path, int, bool]] = []
    for drv in local_drives:
        try:
            if drv.is_dir():
                rk = _path_key(drv.resolve())
                if rk not in seen_roots:
                    seen_roots.add(rk)
                    tier3_roots.append((drv.resolve(), 2, False))
        except OSError:
            continue

    visited_dirs = 0

    def _scan(root: Path, max_depth: int, allow_git_probe: bool) -> bool:
        nonlocal visited_dirs
        queue: deque[tuple[Path, int]] = deque([(root, 0)])
        while queue:
            if visited_dirs >= max_dirs or time.monotonic() > deadline:
                return False
            current, depth = queue.popleft()
            if depth >= max_depth:
                continue
            try:
                entries = list(os.scandir(current))
            except OSError:
                continue
            for entry in entries:
                if visited_dirs >= max_dirs or time.monotonic() > deadline:
                    return False
                try:
                    if not entry.is_dir(follow_symlinks=False):
                        continue
                except OSError:
                    continue
                lname = entry.name.lower()
                if lname in _SKIP_DIRS:
                    continue
                visited_dirs += 1
                cand = Path(entry.path)
                is_git_dir = False
                try:
                    is_git_dir = (cand / ".git").exists()
                except OSError:
                    is_git_dir = False
                if lname == old_name_lower or (has_git_id and is_git_dir):
                    score = _evaluate(cand, allow_git_probe=allow_git_probe)
                    if score >= 90:
                        return True
                # Avoid descending into other Git repositories or hidden tool folders.
                if not is_git_dir and not entry.name.startswith(".") and depth + 1 < max_depth:
                    queue.append((cand, depth + 1))
        return False

    for root, depth, probe in tier2_roots:
        if _scan(root, depth, probe):
            break

    if not any(score >= 90 for score, *_ in candidates):
        for root, depth, probe in tier3_roots:
            if _scan(root, depth, probe):
                break

    if not candidates:
        return None
    candidates.sort(key=lambda item: (item[0], item[1], item[2]), reverse=True)
    best_score = candidates[0][0]
    if best_score >= 90:
        return candidates[0][3]
    # For non-Git matches, require a single unambiguous best candidate.
    top = [item for item in candidates if item[0] == best_score]
    if len(top) == 1:
        return top[0][3]
    return None


def restore_git_workspace(
    target: Path,
    *,
    remote_url: str | None = None,
    branch: str | None = None,
    init_local: bool = True,
) -> dict:
    """Restore GitHub remote connection and local Git repository in a target folder.

    Non-destructive: never overwrites or resets existing user files.
    - Existing Git repo: keeps commits intact; attaches 'origin' if missing and URL provided.
    - Empty folder + remote URL: runs `git clone` to restore history, files, and origin;
      falls back to `git init` + `git remote add origin` if offline or auth is required.
    - Non-empty folder + remote URL: runs `git init` + `git remote add origin` + non-destructive
      `git fetch origin` while keeping all existing files untouched.
    - No remote URL + init_local=True: runs `git init` for a fresh local repository."""
    target = Path(target).resolve()
    if not target.is_dir():
        raise ValueError(f"Directory does not exist: {target}")

    raw_remote = str(remote_url or "").strip()
    remote = sanitize_git_remote(raw_remote)
    if raw_remote and not remote:
        raise ValueError("Invalid Git remote URL")
    safe_branch = _safe_branch_name(branch)

    if shutil.which("git") is None:
        return {
            "ok": False,
            "action": "git_unavailable",
            "remote": remote,
            "branch": safe_branch,
            "warnings": ["Git is not installed or not available on PATH."],
        }

    warnings: list[str] = []

    # 1. Target is already a Git repository
    if (target / ".git").exists():
        ident = read_git_identity(target)
        existing_remote = ident.get("git_remote", "")
        current_branch = ident.get("git_branch", "")
        if remote and not existing_remote:
            add = _run_git(target, ["remote", "add", "origin", remote], timeout=10)
            if add and add.returncode == 0:
                return {
                    "ok": True,
                    "action": "remote_added",
                    "remote": remote,
                    "branch": current_branch,
                    "warnings": [],
                }
            err = ((add.stderr if add else "") or "Could not add origin remote").strip()
            warnings.append(err[:400])
            return {
                "ok": False,
                "action": "existing_repo",
                "remote": existing_remote,
                "branch": current_branch,
                "warnings": warnings,
            }
        return {
            "ok": True,
            "action": "existing_repo",
            "remote": existing_remote,
            "branch": current_branch,
            "warnings": [],
        }

    def _init_repo() -> tuple[bool, str]:
        args = ["init"]
        if safe_branch:
            args.extend(["-b", safe_branch])
        proc = _run_git(target, args, timeout=15)
        if proc and proc.returncode == 0:
            return True, ""
        # Older Git versions without `init -b`: retry plain `git init`
        if safe_branch:
            proc2 = _run_git(target, ["init"], timeout=15)
            if proc2 and proc2.returncode == 0:
                _run_git(target, ["symbolic-ref", "HEAD", f"refs/heads/{safe_branch}"], timeout=10)
                return True, ""
            err = ((proc2.stderr if proc2 else "") or (proc.stderr if proc else "") or "git init failed").strip()
            return False, err[:400]
        err = ((proc.stderr if proc else "") or "git init failed").strip()
        return False, err[:400]

    is_empty = not any(target.iterdir())

    # 2. Empty folder + remote URL -> try full clone from GitHub/remote first
    if remote and is_empty:
        clone = _run_git(target, ["clone", "--", remote, "."], timeout=120)
        if clone and clone.returncode == 0:
            ident = read_git_identity(target)
            actual_branch = ident.get("git_branch", "")
            if safe_branch and actual_branch != safe_branch:
                verify = _run_git(target, ["rev-parse", "--verify", f"origin/{safe_branch}"], timeout=10)
                if verify and verify.returncode == 0:
                    checkout = _run_git(target, ["checkout", safe_branch], timeout=30)
                    if checkout and checkout.returncode == 0:
                        actual_branch = safe_branch
            return {
                "ok": True,
                "action": "cloned",
                "remote": ident.get("git_remote") or remote,
                "branch": actual_branch,
                "warnings": [],
            }
        err = ((clone.stderr if clone else "") or "git clone failed or timed out").strip()
        warnings.append(err[:400])
        # Fall back to local init + origin remote link so the GitHub connection is still restored.
        ok, init_err = _init_repo()
        if not ok:
            warnings.append(init_err)
            return {"ok": False, "action": "error", "remote": remote, "branch": safe_branch, "warnings": warnings}
        _run_git(target, ["remote", "add", "origin", remote], timeout=10)
        ident = read_git_identity(target)
        return {
            "ok": True,
            "action": "initialized_with_remote",
            "remote": ident.get("git_remote") or remote,
            "branch": ident.get("git_branch") or safe_branch,
            "warnings": warnings,
        }

    # 3. Non-empty folder + remote URL -> init + attach origin + safe non-destructive fetch
    if remote and not is_empty:
        ok, init_err = _init_repo()
        if not ok:
            return {"ok": False, "action": "error", "remote": remote, "branch": safe_branch, "warnings": [init_err]}
        add = _run_git(target, ["remote", "add", "origin", remote], timeout=10)
        if not add or add.returncode != 0:
            err = ((add.stderr if add else "") or "Could not add origin remote").strip()
            warnings.append(err[:400])
        fetch = _run_git(target, ["fetch", "origin"], timeout=60)
        ident = read_git_identity(target)
        if fetch and fetch.returncode == 0:
            return {
                "ok": True,
                "action": "initialized_and_fetched",
                "remote": ident.get("git_remote") or remote,
                "branch": ident.get("git_branch") or safe_branch,
                "warnings": warnings,
            }
        fetch_err = ((fetch.stderr if fetch else "") or "git fetch failed or timed out").strip()
        warnings.append(fetch_err[:400])
        return {
            "ok": True,
            "action": "initialized_with_remote",
            "remote": ident.get("git_remote") or remote,
            "branch": ident.get("git_branch") or safe_branch,
            "warnings": warnings,
        }

    # 4. No remote URL -> initialize local Git repository when requested
    if init_local:
        ok, init_err = _init_repo()
        if not ok:
            return {"ok": False, "action": "error", "remote": "", "branch": safe_branch, "warnings": [init_err]}
        ident = read_git_identity(target)
        return {
            "ok": True,
            "action": "initialized",
            "remote": "",
            "branch": ident.get("git_branch") or safe_branch,
            "warnings": [],
        }

    return {"ok": True, "action": "none", "remote": "", "branch": "", "warnings": []}


class Projects:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.file = cfg.root / "projects.json"
        p = cfg.data.get("projects", {})
        self.root_dir = cfg.root / p.get("root_dir", "projects")

    # ------------------------------------------------------------------
    def _load(self) -> list[dict]:
        try:
            return json.loads(self.file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []

    def _save(self, items: list[dict]) -> None:
        from harness.changes import atomic_write_text
        atomic_write_text(self.file, json.dumps(items, ensure_ascii=False, indent=1))

    def _apply_git_identity(self, item: dict, folder: Path) -> bool:
        """Record Git identity on a project dict if present; return True when changed."""
        if not folder.is_dir() or not (folder / ".git").exists():
            return False
        ident = read_git_identity(folder)
        changed = False
        for key in ("git_remote", "git_branch", "git_root_commit"):
            value = ident.get(key)
            if value and item.get(key) != value:
                item[key] = value
                changed = True
        return changed

    # ------------------------------------------------------------------
    def list_all(self) -> list[dict]:
        items = self._load()
        changed = False
        for it in items:
            folder = Path(it["path"])
            if not folder.is_dir():
                it["missing"] = True
            else:
                # Backfill Git identity once for existing repositories so a future
                # move across folders or drives can be detected automatically.
                if (folder / ".git").exists() and not it.get("git_root_commit") and not it.get("_git_empty"):
                    if self._apply_git_identity(it, folder):
                        changed = True
                    elif not it.get("git_remote"):
                        it["_git_empty"] = True
                        changed = True
        if changed:
            # Never persist the transient missing flag.
            to_save = [{k: v for k, v in it.items() if k != "missing"} for it in items]
            self._save(to_save)
        return items

    def by_id(self, project_id: str) -> dict | None:
        for it in self.list_all():
            if it.get("id") == project_id:
                return it
        return None

    def by_path(self, path: str) -> dict | None:
        key = _path_key(path)
        return next((p for p in self._load() if _path_key(p.get("path")) == key), None)

    def refresh_git_metadata(self, project_id: str) -> dict | None:
        """Refresh stored Git remote/branch/root commit for an existing project."""
        items = self._load()
        for item in items:
            if item.get("id") == project_id:
                folder = Path(item["path"])
                if folder.is_dir() and (folder / ".git").exists():
                    item.pop("_git_empty", None)
                    if self._apply_git_identity(item, folder):
                        self._save(items)
                return item
        return None

    def create_new(self, name: str) -> dict:
        """Create a project directory under the configured root and register it."""
        name = _safe_name(name)
        folder = self.root_dir / name
        i = 2
        while folder.exists():  # Choose a unique name.
            folder = self.root_dir / f"{name}-{i}"
            i += 1
        folder.mkdir(parents=True, exist_ok=True)
        proj = {"id": uuid.uuid4().hex[:8], "name": folder.name,
                "path": str(folder), "created": time.time(),
                "managed": True,
                "work_mode": normalize_work_mode(self.cfg.data.get("work_mode"),
                                                   self.cfg.agent.get("mode"))}
        items = self._load()
        items.append(proj)
        self._save(items)
        return proj

    def attach_folder(self, path: str) -> dict:
        """Register an existing directory as a project, using its directory name."""
        p = Path(path).resolve()
        if not p.is_dir():
            raise ValueError(f"Directory does not exist: {p}")
        existing = self.by_path(str(p))
        if existing:
            self.refresh_git_metadata(existing["id"])
            return self.by_path(str(p)) or existing
        proj = {"id": uuid.uuid4().hex[:8], "name": p.name,
                "path": str(p), "created": time.time(),
                "managed": False,
                "work_mode": normalize_work_mode(self.cfg.data.get("work_mode"),
                                                   self.cfg.agent.get("mode"))}
        self._apply_git_identity(proj, p)
        items = self._load()
        items.append(proj)
        self._save(items)
        return proj

    def relocate(self, project_id: str, new_path: str) -> tuple[dict, str]:
        """Point an existing project record to a new existing directory.

        Returns (updated_project, old_path). Never deletes any files on disk."""
        target = Path(str(new_path).strip().strip('"')).expanduser()
        if not target.is_absolute():
            raise ValueError("The project folder must be an absolute path")
        target = target.resolve()
        if not target.is_dir():
            raise ValueError(f"Directory does not exist: {target}")
        items = self._load()
        project = next((it for it in items if it.get("id") == project_id), None)
        if project is None:
            raise ValueError("Unknown project")
        target_key = _path_key(target)
        for other in items:
            if other is not project and _path_key(other.get("path")) == target_key:
                raise ValueError(f"This folder is already registered as project '{other.get('name', '')}'")
        old_path = project["path"]
        project["path"] = str(target)
        project.pop("missing", None)
        project.pop("_git_empty", None)
        # Only keep managed=True if the relocated folder still lives under projects.root_dir.
        if project.get("managed"):
            try:
                root_resolved = self.root_dir.resolve()
                if not target.is_relative_to(root_resolved):
                    project["managed"] = False
            except OSError:
                project["managed"] = False
        self._apply_git_identity(project, target)
        self._save(items)
        return dict(project), old_path

    def ensure_registered(self, path: str) -> dict | None:
        """Register an untracked workspace when migrating an older installation."""
        if not path:
            return None
        try:
            return self.attach_folder(path)
        except ValueError:
            return None

    def set_work_mode(self, path: str, work_mode: str) -> None:
        items = self._load()
        key = _path_key(path)
        for item in items:
            if _path_key(item.get("path")) == key:
                item["work_mode"] = normalize_work_mode(work_mode)
                self._save(items)
                return

    def set_autocommit(self, path: str, enabled: bool) -> None:
        """Per-project auto-commit switch, persisted in the project registry."""
        items = self._load()
        key = _path_key(path)
        for item in items:
            if _path_key(item.get("path")) == key:
                item["autocommit"] = bool(enabled)
                self._save(items)
                return

    def delete_by_path(self, path: str) -> dict:
        """Unregister a project. Only Marvin-created project folders are deleted from disk.

        Attached folders belong to the user; removing such a project never touches
        their contents, whatever they contain (a repository, personal documents)."""
        items = self._load()
        key = _path_key(path)
        project = next((item for item in items if _path_key(item.get("path")) == key), None)
        if project is None:
            raise ValueError("The project is not registered")
        if project.get("managed"):
            target = Path(project["path"]).resolve()
            protected = [self.cfg.root.resolve(), self.root_dir.resolve(), Path.home().resolve()]
            anchor = Path(target.anchor).resolve()
            if target == anchor or any(target == item or item.is_relative_to(target)
                                       for item in protected):
                raise ValueError(f"Refusing to delete a protected directory: {target}")
            if target.exists():
                try:
                    if target.is_symlink() or (hasattr(target, "is_junction") and target.is_junction()):
                        target.unlink() if target.is_symlink() else target.rmdir()
                    elif target.is_dir():
                        shutil.rmtree(target)
                    else:
                        raise ValueError(f"Project path is not a directory: {target}")
                except OSError as exc:
                    raise ValueError(
                        "The project folder could not be deleted because a file is locked "
                        "or read-only; the project was not removed.") from exc
        self._save([item for item in items if item is not project])
        return project
