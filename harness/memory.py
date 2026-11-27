"""Persistent model memory: global, work-mode and project layers.

Files:
  global: {app}/memory/GLOBAL.md
  development: {app}/memory/MEMORY.md (the original coding memory)
  other modes: {app}/memory/modes/<work_mode>.md
  project: {workspace}/QWEN_MEMORY.md

All three active layers are injected into the system prompt at task start and after compression. The model can read and update them through memory tools."""
from __future__ import annotations

from .i18n import locale_data

from pathlib import Path

from harness.config import Config
from harness.work_modes import WORK_MODES, normalize_work_mode


GLOBAL_TEMPLATE = """# Global memory

<!-- Facts and preferences that apply across all work modes and projects.
     To write here use save_memory with scope="global". Keep it brief, one fact per line. -->
"""


def _mode_template(work_mode: str) -> str:
    label = WORK_MODES[work_mode].label
    return f"""# Work mode memory: {label}

<!-- Facts, rules and preferences that apply to the {label} mode across projects.
     To write here use save_memory with scope="mode". Keep it brief, one fact per line. -->
"""


class MemoryStore:
    def __init__(self, cfg: Config, workspace: Path | None = None,
                 work_mode: str | None = None):
        self.cfg = cfg
        self.workspace = Path(workspace) if workspace else None
        self.work_mode = normalize_work_mode(
            work_mode or cfg.data.get("work_mode"), cfg.agent.get("mode", "agent"))
        settings = cfg.data.get("memory", {})
        directory = settings.get("directory", settings.get("global_dir", "memory"))
        self.base_dir = cfg.root / directory
        self.global_path = self.base_dir / settings.get("global_filename", "GLOBAL.md")
        self.modes_dir = self.base_dir / settings.get("modes_directory", "modes")
        self.development_filename = settings.get("development_filename", "MEMORY.md")
        self.project_filename = settings.get("project_filename", "QWEN_MEMORY.md")
        self._ensure_global()
        self._ensure_mode()

    def _ensure_global(self) -> None:
        self.global_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.global_path.exists():
            self.global_path.write_text(GLOBAL_TEMPLATE, encoding="utf-8")

    def mode_path(self) -> Path:
        if self.work_mode == "development":
            return self.base_dir / self.development_filename
        return self.modes_dir / f"{self.work_mode}.md"

    def _ensure_mode(self) -> None:
        path = self.mode_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_text(_mode_template(self.work_mode), encoding="utf-8")
            return
        if self.work_mode != "development":
            return
        try:
            text = path.read_text(encoding="utf-8")
            legacy = locale_data("legacy_memory_heading", "")
            if legacy and text.startswith(legacy):
                text = text.replace(legacy, "# Work mode memory: Development", 1)
                text = text.replace('scope="global"', 'scope="mode"', 1)
                path.write_text(text, encoding="utf-8")
        except OSError:
            pass

    def project_path(self) -> Path | None:
        if self.workspace is None:
            return None
        return self.workspace / self.project_filename

    def ensure_project(self) -> None:
        path = self.project_path()
        if path is None:
            return
        try:
            if not path.exists():
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(
                    f"# Project memory ({self.project_filename})\n\n"
                    "<!-- Facts that apply to this project only. "
                    "To write here use save_memory with scope=\"project\". -->\n",
                    encoding="utf-8")
        except OSError:
            pass

    def _path_for(self, scope: str) -> Path | None:
        if scope == "global":
            return self.global_path
        if scope == "mode":
            return self.mode_path()
        if scope == "project":
            return self.project_path()
        return None

    def read(self, scope: str) -> str:
        if scope not in ("global", "mode", "project"):
            return f"ERROR: Unknown memory scope: {scope}"
        path = self._path_for(scope)
        if path is None:
            return "ERROR: No project is selected; project memory is inactive."
        if not path.exists():
            return "(empty)"
        try:
            return path.read_text(encoding="utf-8")
        except OSError as exc:
            return f"ERROR: cannot read {path}: {exc}"

    def append(self, fact: str, scope: str) -> str:
        fact = (fact or "").strip()
        if not fact:
            return "ERROR: The fact is empty; there is nothing to save."
        if scope not in ("global", "mode", "project"):
            return f"ERROR: Unknown memory scope: {scope}"
        path = self._path_for(scope)
        if path is None:
            return "ERROR: No project is selected; project memory is unavailable."
        if scope == "project":
            self.ensure_project()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            # Deduplicate identical existing memory bullets (case- and whitespace-normalized).
            norm_new = " ".join(fact.lower().split())
            if path.exists():
                existing = path.read_text(encoding="utf-8", errors="replace").splitlines()
                for line in existing:
                    stripped = line.strip()
                    if stripped.startswith("- "):
                        if " ".join(stripped[2:].lower().split()) == norm_new:
                            labels = {"global": "global", "mode": "work-mode", "project": "project"}
                            return f"Already in {labels[scope]} memory: {fact[:80]}"
            with open(path, "a", encoding="utf-8") as handle:
                handle.write(f"- {fact}\n")
            labels = {"global": "global", "mode": "work-mode", "project": "project"}
            return f"OK: saved to {labels[scope]} memory: {fact[:80]}"
        except OSError as exc:
            return f"ERROR: cannot write {path}: {exc}"

    def _matching_fact_indices(self, lines: list[str], needle: str) -> list[int]:
        query = (needle or "").strip().lower()
        if not query:
            return []
        exact: list[int] = []
        partial: list[int] = []
        for idx, line in enumerate(lines):
            stripped = line.strip()
            if not stripped.startswith("- "):
                continue
            body = stripped[2:].strip().lower()
            if body == query:
                exact.append(idx)
            elif query in body:
                partial.append(idx)
        return exact or partial

    def replace(self, old_text: str, new_fact: str, scope: str) -> str:
        """Replace one outdated fact line in the specified memory layer."""
        old_text = (old_text or "").strip()
        new_fact = (new_fact or "").strip()
        if not old_text or not new_fact:
            return "ERROR: Both old_text and new_text must be non-empty."
        if scope not in ("global", "mode", "project"):
            return f"ERROR: Unknown memory scope: {scope}"
        path = self._path_for(scope)
        if path is None or not path.exists():
            return f"ERROR: Memory layer '{scope}' is unavailable."
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
            hits = self._matching_fact_indices(lines, old_text)
            if not hits:
                return f"ERROR: No memory line matching {old_text!r} found in {scope} memory."
            if len(hits) > 1:
                preview = "; ".join(lines[i].strip()[:80] for i in hits[:4])
                return f"ERROR: {len(hits)} lines matched {old_text!r} ({preview}); pass a more specific phrase."
            lines[hits[0]] = f"- {new_fact}"
            from harness.changes import atomic_write_text
            atomic_write_text(path, "\n".join(lines) + "\n")
            return f"OK: updated {scope} memory: {new_fact[:80]}"
        except OSError as exc:
            return f"ERROR: cannot update {path}: {exc}"

    def remove(self, match_text: str, scope: str) -> str:
        """Remove one outdated fact line from the specified memory layer."""
        match_text = (match_text or "").strip()
        if not match_text:
            return "ERROR: Provide text identifying the memory line to remove."
        if scope not in ("global", "mode", "project"):
            return f"ERROR: Unknown memory scope: {scope}"
        path = self._path_for(scope)
        if path is None or not path.exists():
            return f"ERROR: Memory layer '{scope}' is unavailable."
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
            hits = self._matching_fact_indices(lines, match_text)
            if not hits:
                return f"ERROR: No memory line matching {match_text!r} found in {scope} memory."
            if len(hits) > 1:
                preview = "; ".join(lines[i].strip()[:80] for i in hits[:4])
                return f"ERROR: {len(hits)} lines matched {match_text!r} ({preview}); pass a more specific phrase."
            removed = lines.pop(hits[0]).strip()
            from harness.changes import atomic_write_text
            atomic_write_text(path, "\n".join(lines) + "\n")
            return f"OK: removed from {scope} memory: {removed[:80]}"
        except OSError as exc:
            return f"ERROR: cannot update {path}: {exc}"

    def context_block(self) -> str:
        """All three active memory scopes, without artificial truncation."""
        label = WORK_MODES[self.work_mode].label
        parts = [
            "## PERSISTENT MEMORY",
            "The following durable memory layers all apply to this chat. Use all of them. "
            "Store universal user facts in scope 'global', facts shared by this work mode "
            "in scope 'mode', and project-specific facts in scope 'project'.",
            f"### GLOBAL MEMORY (all work modes and projects)\n{self.read('global').strip()}",
            f"### WORK MODE MEMORY ({label})\n{self.read('mode').strip()}",
        ]
        if self.project_path() is not None:
            parts.append(
                f"### PROJECT MEMORY (workspace: {self.workspace.name})\n"
                f"{self.read('project').strip()}")
        else:
            parts.append("### PROJECT MEMORY: no project selected (project layer inactive)")
        return "\n\n".join(parts)
