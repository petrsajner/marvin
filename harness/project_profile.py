"""Project-specific validation commands with conservative auto-detection."""
from __future__ import annotations

import functools
import json
import subprocess
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


@functools.lru_cache(maxsize=16)
def _module_available(python: str, module: str) -> bool:
    """Whether the resolved interpreter can import a tool module.

    A detected command that cannot even start is worse than no command at all,
    so detection only offers runners that are actually installed. Cached per
    interpreter because detection runs on every status poll."""
    try:
        proc = subprocess.run([python, "-c", f"import {module}"], capture_output=True,
                              timeout=30, creationflags=NO_WINDOW)
    except (OSError, subprocess.SubprocessError):
        return False
    return proc.returncode == 0


@dataclass(frozen=True)
class ProjectCheck:
    id: str
    label: str
    command: str
    shell: str = "powershell"
    timeout: int = 900
    kind: str = "test"
    primary: bool = False

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class ProjectProfile:
    def __init__(self, workspace: Path, python: Path | str):
        self.workspace = Path(workspace).resolve()
        self.python = str(python)

    def checks(self) -> list[ProjectCheck]:
        configured = self._configured_checks()
        return configured if configured else self._detected_checks()

    def select(self, check_id: str = "primary") -> ProjectCheck | None:
        checks = self.checks()
        if not checks:
            return None
        if check_id and check_id != "primary":
            selected = next((item for item in checks
                             if item.id == check_id or item.kind == check_id), None)
            if selected:
                return selected
        return next((item for item in checks if item.primary), checks[0])

    def describe(self) -> str:
        checks = self.checks()
        if not checks:
            return "No validation commands detected. Add .qwen/project.yaml to define them."
        lines = ["Available project validation commands:"]
        for item in checks:
            primary = " (primary)" if item.primary else ""
            lines.append(
                f"- {item.id}: {item.label}{primary}\n"
                f"  [{item.kind}, {item.shell}, timeout {item.timeout}s] {item.command}")
        lines.append(
            "A project can override detection in .qwen/project.yaml under a checks list.")
        return "\n".join(lines)

    def _configured_checks(self) -> list[ProjectCheck]:
        path = self.workspace / ".qwen" / "project.yaml"
        if not path.is_file():
            return []
        try:
            import yaml
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            raw_checks = data.get("checks") or []
        except (OSError, ValueError, TypeError, ImportError):
            return []
        checks: list[ProjectCheck] = []
        for index, raw in enumerate(raw_checks, 1):
            if not isinstance(raw, dict) or not str(raw.get("command") or "").strip():
                continue
            checks.append(ProjectCheck(
                id=str(raw.get("id") or f"check-{index}"),
                label=str(raw.get("label") or raw.get("id") or f"Check {index}"),
                command=str(raw["command"]),
                shell=str(raw.get("shell") or "powershell"),
                timeout=max(1, int(raw.get("timeout") or 900)),
                kind=str(raw.get("kind") or "test"),
                primary=bool(raw.get("primary", index == 1)),
            ))
        return checks

    def _reads(self, name: str) -> str:
        path = self.workspace / name
        try:
            return path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""

    def _pytest_configured(self) -> bool:
        """Whether the project itself asks for pytest rather than the stdlib runner."""
        if ((self.workspace / "pytest.ini").is_file()
                or (self.workspace / "conftest.py").is_file()
                or (self.workspace / "tests" / "conftest.py").is_file()):
            return True
        return ("[tool.pytest" in self._reads("pyproject.toml")
                or "[tool:pytest]" in self._reads("setup.cfg"))

    def _python_test_check(self) -> ProjectCheck | None:
        """Detect a Python test command that can actually run here.

        Marvin's own entry script wins. Otherwise the discovery form is chosen by
        what imports in practice: `-s tests` for a tests directory (works with and
        without __init__.py) and `-s . -p 'test_*.py'` for test modules kept in the
        project root. pytest is used only when the project configures it and the
        interpreter can import it; the stdlib runner keeps the check usable
        everywhere else."""
        if (self.workspace / "tests" / "test_core.py").is_file():
            return ProjectCheck("tests", "Core tests",
                                f"& '{self.python}' 'tests/test_core.py'", primary=True)
        tests_dir = self.workspace / "tests"
        has_tests_dir = tests_dir.is_dir() and any(tests_dir.rglob("test_*.py"))
        root_tests = any(self.workspace.glob("test_*.py"))
        if self._pytest_configured() and _module_available(self.python, "pytest"):
            target = " tests" if has_tests_dir else ""
            return ProjectCheck("tests", "Pytest suite",
                                f"& '{self.python}' -m pytest -q{target}", primary=True)
        if has_tests_dir:
            return ProjectCheck("tests", "Unittest suite",
                                f"& '{self.python}' -m unittest discover -s tests",
                                primary=True)
        if root_tests:
            return ProjectCheck(
                "tests", "Unittest suite",
                f"& '{self.python}' -m unittest discover -s . -p 'test_*.py'",
                primary=True)
        return None

    def _detected_checks(self) -> list[ProjectCheck]:
        checks: list[ProjectCheck] = []
        python_tests = self._python_test_check()
        if python_tests:
            checks.append(python_tests)

        pyproject = self.workspace / "pyproject.toml"
        if pyproject.is_file():
            text = pyproject.read_text(encoding="utf-8", errors="replace").lower()
            if "ruff" in text and _module_available(self.python, "ruff"):
                checks.append(ProjectCheck(
                    "lint", "Ruff lint", f"& '{self.python}' -m ruff check .",
                    kind="lint"))
            if "mypy" in text and _module_available(self.python, "mypy"):
                checks.append(ProjectCheck(
                    "typecheck", "Mypy", f"& '{self.python}' -m mypy .",
                    kind="typecheck"))

        package_path = self.workspace / "package.json"
        if package_path.is_file():
            try:
                scripts = (json.loads(package_path.read_text(encoding="utf-8"))
                           .get("scripts") or {})
            except (OSError, ValueError):
                scripts = {}
            for script, kind in (("test", "test"), ("check", "test"),
                                 ("lint", "lint"), ("typecheck", "typecheck"),
                                 ("build", "build")):
                if script not in scripts:
                    continue
                checks.append(ProjectCheck(
                    f"npm-{script}", f"npm {script}", f"npm run {script}",
                    kind=kind, primary=not any(item.primary for item in checks)))

        if (self.workspace / "Cargo.toml").is_file():
            checks.append(ProjectCheck(
                "cargo-test", "Cargo tests", "cargo test", kind="test",
                primary=not any(item.primary for item in checks)))
        if (self.workspace / "go.mod").is_file():
            checks.append(ProjectCheck(
                "go-test", "Go tests", "go test ./...", kind="test",
                primary=not any(item.primary for item in checks)))
        if list(self.workspace.glob("*.sln")) or list(self.workspace.glob("*.csproj")):
            checks.append(ProjectCheck(
                "dotnet-test", ".NET tests", "dotnet test", kind="test",
                primary=not any(item.primary for item in checks)))
        return checks
