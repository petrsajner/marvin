"""Per-task file-change journal with persistent rollback."""
from __future__ import annotations

import difflib
import hashlib
import json
import os
import shutil
import threading
import time
import uuid
from pathlib import Path

# Diffs above this size are truncated rather than rendered whole.
DIFF_MAX_BYTES = 1536 * 1024
DIFF_CONTEXT = 3
# Harness-managed project state. A workspace snapshot must not attribute these to
# whichever task happened to run when they changed - they would show up as task
# changes and reach the optional auto-commit. An explicit agent edit still
# records normally through record_before/record_after.
HARNESS_STATE_DIRS = {".qwen"}


def file_sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


# How many times a replace is retried before the failure is treated as real.
REPLACE_ATTEMPTS = 5


def atomic_write_text(path: Path, content: str) -> None:
    """Write a file atomically, tolerating a reader that holds it open.

    On Windows os.replace fails while another handle has the target open, and
    several of these files are read by the interface exactly while they are
    being written - run-live.json about three times a second for a whole run.
    The collision is transient, but it used to propagate out of the run
    controller and mark the task as failed. A persistent failure still raises:
    a full disk or a permission problem must not pass silently."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex[:8]}.tmp")
    try:
        temporary.write_text(content, encoding="utf-8", newline="\n")
        for attempt in range(REPLACE_ATTEMPTS):
            try:
                os.replace(temporary, path)
                return
            except OSError:
                if attempt == REPLACE_ATTEMPTS - 1:
                    raise
                time.sleep(0.05 * (attempt + 1))
    finally:
        temporary.unlink(missing_ok=True)


class ChangeJournal:
    def __init__(self, session, workspace: Path):
        self.session = session
        self.workspace = Path(workspace).resolve()
        self.base = session.dir / "changes"
        self.task_id: str | None = None
        self._records: dict[str, dict] = {}
        self._lock = threading.RLock()
        self._snapshot = False
        latest = self._load_manifest(None)
        if latest and not latest.get("undone_at"):
            self.task_id = latest["task_id"]
            self._records = {item["path"]: item for item in latest.get("files", [])}
            self._snapshot = bool(latest.get("snapshot"))

    def set_workspace(self, workspace: Path) -> None:
        self.workspace = Path(workspace).resolve()

    def begin_task(self, label: str = "") -> str:
        with self._lock:
            stamp = time.strftime("%Y%m%d-%H%M%S")
            self.task_id = f"{stamp}-{uuid.uuid4().hex[:6]}"
            self._records = {}
            self._snapshot = False
            self._write_manifest(label=label[:200])
            return self.task_id

    @property
    def task_dir(self) -> Path:
        if self.task_id is None:
            self.begin_task()
        return self.base / str(self.task_id)

    def record_before(self, path: Path) -> None:
        path = path.resolve()
        key = str(path)
        with self._lock:
            if key in self._records:
                return
            existed = path.is_file()
            backup_name = hashlib.sha256(key.encode("utf-8")).hexdigest() + ".bak"
            record = {
                "path": key,
                "display_path": self._display_path(path),
                "existed": existed,
                "backup": backup_name if existed else None,
                "before_sha256": file_sha256(path),
                "after_sha256": None,
            }
            if existed:
                self.task_dir.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, self.task_dir / backup_name)
            self._records[key] = record
            self._write_manifest()

    def record_after(self, path: Path) -> None:
        path = path.resolve()
        with self._lock:
            record = self._records.get(str(path))
            if record is None:
                return
            record["after_sha256"] = file_sha256(path)
            self._write_manifest()

    def record_directory_before(self, path: Path) -> None:
        path = path.resolve()
        key = str(path)
        with self._lock:
            if key in self._records:
                return
            existed = path.is_dir()
            self._records[key] = {
                "path": key,
                "display_path": self._display_path(path),
                "kind": "directory",
                "existed": existed,
                "backup": None,
                "before_sha256": "directory" if existed else None,
                "after_sha256": None,
            }
            self._write_manifest()

    def record_directory_after(self, path: Path) -> None:
        path = path.resolve()
        with self._lock:
            record = self._records.get(str(path))
            if record is None:
                return
            record["after_sha256"] = "directory" if path.is_dir() else None
            self._write_manifest()

    def summary(self, task_id: str | None = None) -> dict:
        manifest = self._load_manifest(task_id)
        records = manifest.get("files", []) if manifest else []
        undone = bool(manifest and manifest.get("undone_at"))
        return {
            "task_id": manifest.get("task_id") if manifest else None,
            "label": manifest.get("label", "") if manifest else "",
            "file_count": len(records),
            "files": [
                {
                    "path": record["display_path"],
                    "change": ("directory" if record.get("kind") == "directory"
                               else "deleted" if record["existed"] and record.get("after_sha256") is None
                               else "modified" if record["existed"] else "created"),
                    "changed": not undone and record.get("before_sha256") != record.get("after_sha256"),
                }
                for record in records
            ],
        }

    def task_ids(self) -> list[str]:
        """Every task this conversation has recorded, oldest first.

        A fresh manifest is started per task, so anything that asks only the
        current one sees a single task's work - which is why a finished program
        dropped out of Results the moment the next task began.

        Ordered by the timestamp inside each manifest, not by the folder name: a
        task id is a second-resolution stamp plus random hex, so two tasks in the
        same second sort by the random half."""
        if not self.base.exists():
            return []
        found = []
        for path in self.base.glob("*/manifest.json"):
            manifest = self._read_json(path) or {}
            found.append((float(manifest.get("created") or 0.0), path.parent.name))
        return [name for _, name in sorted(found)]

    def record_created(self, path: Path) -> None:
        """Record a file produced by something other than the file tools.

        A picture written by an image service, or an artefact a program built, is
        as much a result as a file the model edited - and Results is assembled
        from this journal, so whatever does not pass through here is invisible
        there however plainly it is named in the conversation."""
        path = Path(path).resolve()
        key = str(path)
        with self._lock:
            if key in self._records or not path.is_file():
                return
            self._records[key] = {
                "path": key,
                "display_path": self._display_path(path),
                "existed": False,
                "backup": None,
                "before_sha256": None,
                "after_sha256": file_sha256(path),
            }
            self._write_manifest()

    def _diff_lines(self, before: list[str], after: list[str]) -> list[dict]:
        """Line records with old/new numbers; long equal runs collapse into gaps."""
        records: list[dict] = []
        a = b = 0
        pending: list[dict] = []
        for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(
                None, before, after, autojunk=False).get_opcodes():
            if tag == "equal":
                for offset, text in enumerate(before[i1:i2]):
                    pending.append({"tag": " ", "a": i1 + offset + 1, "b": j1 + offset + 1, "text": text})
            else:
                records.extend(pending)
                pending = []
                for offset, text in enumerate(before[i1:i2]):
                    records.append({"tag": "-", "a": i1 + offset + 1, "b": None, "text": text})
                for offset, text in enumerate(after[j1:j2]):
                    records.append({"tag": "+", "a": None, "b": j1 + offset + 1, "text": text})
        # Collapse long unchanged runs into gap markers with a small context fringe.
        collapsed: list[dict] = []
        run: list[dict] = []

        def flush_run() -> None:
            if not run:
                return
            if len(run) > 2 * DIFF_CONTEXT + 2:
                collapsed.extend(run[:DIFF_CONTEXT])
                collapsed.append({"tag": "gap", "count": len(run) - 2 * DIFF_CONTEXT})
                collapsed.extend(run[-DIFF_CONTEXT:])
            else:
                collapsed.extend(run)
            run.clear()

        for record in records + pending:
            if record["tag"] == " ":
                run.append(record)
                continue
            flush_run()
            collapsed.append(record)
        flush_run()
        return collapsed

    def file_diff(self, path: str, task_id: str | None = None) -> dict:
        """Structured line diff of one recorded file against its live content."""
        manifest = self._load_manifest(task_id)
        record = next((r for r in (manifest or {}).get("files", [])
                       if r.get("display_path") == path or r.get("path") == path), None)
        restorable = record is not None
        if record is None and (manifest or {}).get("snapshot"):
            live = self.workspace / path
            inside = True
            try:
                live.resolve().relative_to(self.workspace)
            except (OSError, ValueError):
                inside = False
            if inside and live.is_file() and not self._harness_state(live):
                record = {"path": str(live.resolve()), "display_path": self._display_path(live),
                          "existed": False, "backup": None, "before_sha256": None,
                          "after_sha256": file_sha256(live)}
        if record is None or record.get("kind") == "directory":
            raise FileNotFoundError(f"No recorded change for {path}")
        task_dir = self.base / manifest["task_id"]
        live = Path(record["path"])
        change = ("deleted" if record["existed"] and record.get("after_sha256") is None
                  else "modified" if record["existed"] else "created")
        changed_after = False
        binary = truncated = False

        def read_lines(source: Path) -> list[str]:
            nonlocal binary, truncated
            try:
                raw = source.read_bytes()
            except OSError:
                return []
            if b"\x00" in raw[:65536]:
                binary = True
                return []
            truncated = truncated or len(raw) > DIFF_MAX_BYTES
            return raw[:DIFF_MAX_BYTES].decode("utf-8", errors="replace").splitlines()

        before = read_lines(task_dir / record["backup"]) if record["existed"] else []
        after = [] if change == "deleted" else read_lines(live)
        if record["existed"] and change != "deleted":
            try:
                changed_after = file_sha256(live) != record.get("after_sha256")
            except OSError:
                changed_after = True
        return {
            "task_id": manifest["task_id"], "path": record["display_path"], "change": change,
            "undone": bool(manifest.get("undone_at")), "restorable": restorable,
            "changed_after": changed_after, "binary": binary, "truncated": truncated,
            "lines": [] if binary else self._diff_lines(before, after),
        }

    def undo(self, task_id: str | None = None, force: bool = False, paths: list[str] | None = None) -> dict:
        with self._lock:
            manifest = self._load_manifest(task_id)
            if not manifest:
                return {"restored": [], "errors": ["No task checkpoint available"]}
            task_dir = self.base / manifest["task_id"]
            wanted = set(paths) if paths is not None else None
            restored: list[str] = []
            errors: list[str] = []
            for record in reversed(manifest.get("files", [])):
                if wanted is not None and record["display_path"] not in wanted:
                    continue
                path = Path(record["path"])
                try:
                    if record.get("kind") != "directory" and not force:
                        current = file_sha256(path)
                        if current == record.get("before_sha256"):
                            restored.append(record["display_path"])
                            continue
                        if current != record.get("after_sha256"):
                            errors.append(f"{record['display_path']}: changed after this task; left unchanged")
                            continue
                    if record.get("kind") == "directory":
                        if not record["existed"] and path.is_dir():
                            path.rmdir()
                    elif record["existed"]:
                        backup = task_dir / record["backup"]
                        path.parent.mkdir(parents=True, exist_ok=True)
                        temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex[:8]}.restore")
                        shutil.copy2(backup, temporary)
                        os.replace(temporary, path)
                    else:
                        path.unlink(missing_ok=True)
                    restored.append(record["display_path"])
                except OSError as exc:
                    errors.append(f"{record['display_path']}: {exc}")
            # A partial restore leaves the task itself active for the remaining files.
            if not errors and wanted is None:
                manifest["undone_at"] = time.time()
            manifest["restore_errors"] = errors
            self._atomic_json(task_dir / "manifest.json", manifest)
            return {"task_id": manifest["task_id"], "restored": restored, "errors": errors}

    def revert_last_task(self) -> dict:
        """Rollback all file changes from the most recent task."""
        with self._lock:
            res = self.undo(self.task_id)
            if res.get("restored"):
                return res
            if not self.base.exists():
                return {"restored": [], "errors": []}
            manifests = sorted(self.base.glob("*/manifest.json"), reverse=True)
            for m in manifests:
                data = self._read_json(m)
                if data and data.get("files") and not data.get("undone_at"):
                    return self.undo(data.get("task_id"))
            return {"restored": [], "errors": []}

    def create_checkpoint(self, label: str = "manual") -> str:
        """Create an explicit snapshot checkpoint."""
        self.begin_task(label)
        self.capture_workspace()
        return self.task_id

    def capture_workspace(self) -> None:
        from harness.file_index import project_files
        self._snapshot = True
        for path in project_files(self.workspace, refresh=True):
            if (path.is_file() and not path.is_relative_to(self.base)
                    and not self._harness_state(path)):
                self.record_before(path)
                self.record_after(path)
        self._write_manifest()

    def reconcile_workspace(self) -> None:
        if not self._snapshot:
            return
        from harness.file_index import project_files
        for path in project_files(self.workspace, refresh=True):
            if path.is_relative_to(self.base) or self._harness_state(path):
                continue
            key = str(path.resolve())
            if key not in self._records:
                self._records[key] = {"path": key, "display_path": self._display_path(path),
                    "existed": False, "backup": None, "before_sha256": None, "after_sha256": None}
        for record in self._records.values():
            if record.get("kind") != "directory":
                record["after_sha256"] = file_sha256(Path(record["path"]))
        self._write_manifest()

    def _harness_state(self, path: Path) -> bool:
        try:
            parts = path.resolve().relative_to(self.workspace).parts
        except (OSError, ValueError):
            return False
        return bool(parts) and parts[0] in HARNESS_STATE_DIRS

    def changed_since(self, task_id: str | None = None) -> dict:
        """Files whose current content differs from a checkpoint's saved state.

        summary() reports what a task recorded, but a restore point taken before
        any edit records before == after for every file. Comparing the live file
        against the saved pre-task hash is what makes a checkpoint inspectable."""
        manifest = self._load_manifest(task_id)
        if not manifest:
            return {"task_id": None, "label": "", "files": []}
        files: list[dict] = []
        for record in manifest.get("files", []):
            if record.get("kind") == "directory":
                continue
            live = file_sha256(Path(record["path"]))
            if live == record.get("before_sha256"):
                continue
            files.append({
                "path": record["display_path"],
                "change": ("created" if not record["existed"]
                           else "deleted" if live is None else "modified"),
                "changed": True, "restorable": True,
            })
        if manifest.get("snapshot"):
            # A file created after the snapshot has no manifest entry, but it is
            # still drift the user wants to see. It cannot be restored from a
            # backup that never existed.
            from harness.file_index import project_files
            known = {record["path"] for record in manifest.get("files", [])}
            for path in project_files(self.workspace, refresh=True):
                if (str(path.resolve()) in known or path.is_relative_to(self.base)
                        or self._harness_state(path) or not path.is_file()):
                    continue
                files.append({"path": self._display_path(path), "change": "created",
                              "changed": True, "restorable": False})
        return {"task_id": manifest["task_id"], "label": manifest.get("label", ""),
                "files": sorted(files, key=lambda item: item["path"])}

    def _display_path(self, path: Path) -> str:
        try:
            return str(path.relative_to(self.workspace))
        except ValueError:
            return str(path)

    def _write_manifest(self, label: str | None = None) -> None:
        if self.task_id is None:
            return
        path = self.task_dir / "manifest.json"
        previous = self._read_json(path) or {}
        manifest = {
            "task_id": self.task_id,
            "created": previous.get("created", time.time()),
            "label": previous.get("label", "") if label is None else label,
            "workspace": str(self.workspace),
            "files": list(self._records.values()),
            "snapshot": self._snapshot,
        }
        self._atomic_json(path, manifest)

    def _load_manifest(self, task_id: str | None) -> dict | None:
        selected = task_id or self.task_id
        if selected:
            return self._read_json(self.base / selected / "manifest.json")
        if not self.base.exists():
            return None
        manifests = sorted(self.base.glob("*/manifest.json"), reverse=True)
        return self._read_json(manifests[0]) if manifests else None

    @staticmethod
    def _read_json(path: Path) -> dict | None:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    @staticmethod
    def _atomic_json(path: Path, data: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, path)
