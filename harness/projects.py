"""Application project registry.

projects.json contains id, name, path and creation time. New projects create a directory under projects.root_dir; attached projects register an existing directory. A session's workspace is the selected project's path."""
from __future__ import annotations

import json
import re
import shutil
import time
import uuid
from pathlib import Path

from harness.config import Config
from harness.work_modes import normalize_work_mode


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
    return name or "projekt"


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

    # ------------------------------------------------------------------
    def list_all(self) -> list[dict]:
        items = self._load()
        for it in items:  # Recreate a missing directory, for example after external deletion.
            if not Path(it["path"]).is_dir():
                it["missing"] = True
        return items

    def by_path(self, path: str) -> dict | None:
        return next((p for p in self._load() if p["path"] == path), None)

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
            return existing
        proj = {"id": uuid.uuid4().hex[:8], "name": p.name,
                "path": str(p), "created": time.time(),
                "managed": False,
                "work_mode": normalize_work_mode(self.cfg.data.get("work_mode"),
                                                   self.cfg.agent.get("mode"))}
        items = self._load()
        items.append(proj)
        self._save(items)
        return proj

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
        for item in items:
            if item.get("path") == path:
                item["work_mode"] = normalize_work_mode(work_mode)
                self._save(items)
                return

    def set_autocommit(self, path: str, enabled: bool) -> None:
        """Per-project auto-commit switch, persisted in the project registry."""
        items = self._load()
        for item in items:
            if item.get("path") == path:
                item["autocommit"] = bool(enabled)
                self._save(items)
                return

    def delete_by_path(self, path: str) -> dict:
        """Unregister a project. Only Marvin-created project folders are deleted from disk.

        Attached folders belong to the user; removing such a project never touches
        their contents, whatever they contain (a repository, personal documents)."""
        items = self._load()
        project = next((item for item in items if item.get("path") == path), None)
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
