"""Local evaluation scenarios with deterministic, model-free scoring.

Each scenario is a prepared agent task plus a checker that runs after the task
finishes and inspects the workspace/session with local tools only. Results are
appended to runtime/eval-results.json so they survive restarts; the Settings
section shows the latest per script and the Results panel shows the history."""
from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

NO_WINDOW = 0x08000000
CHECK_TIMEOUT = 120


def _run_tests(workspace: Path) -> tuple[bool, str]:
    """Run the workspace's unit tests with the standard-library runner."""
    proc = subprocess.run(
        ["python", "-m", "unittest", "discover", "-s", "tests", "-v"],
        cwd=workspace, capture_output=True, text=True, encoding="utf-8",
        errors="replace", timeout=CHECK_TIMEOUT, creationflags=NO_WINDOW)
    ok = proc.returncode == 0
    tail = "\n".join((proc.stderr or proc.stdout or "").strip().splitlines()[-4:])
    return ok, tail or "(no output)"


def _make_workspace(cfg, script_id: str) -> Path:
    root = cfg.path("paths.runtime_dir") / "eval-workspaces" / f"{script_id}-{int(time.time())}"
    root.mkdir(parents=True, exist_ok=True)
    return root


EVALS: dict[str, dict] = {}


def eval_spec(script_id, label, description, work_mode, prompt, fixture=None):
    def wrap(builder):
        EVALS[script_id] = {
            "id": script_id, "label": label, "description": description,
            "work_mode": work_mode, "prompt": prompt,
            "build_fixture": builder, "fixture": fixture,
        }
        return builder
    return wrap


# --- 1) code: add a function with tests ------------------------------------

@eval_spec(
    "code_add_function", "Code: function with tests",
    "Asks the agent to create a utility module with a specified function and unit tests, then run them.",
    "development",
    "Create a file `textutils.py` with a function `word_frequency(text)` that returns a dict "
    "mapping each lowercase word to its count (words split on whitespace, punctuation stripped "
    "from edges). Add `tests/test_textutils.py` with standard-library `unittest` tests covering "
    "normal text, empty input and punctuation (name test classes TestWordFrequency). "
    "Run the tests with `python -m unittest discover -s tests` and report the real result.",
)
def _build_code_add(root: Path) -> None:
    (root / "tests").mkdir()


# --- 2) code: fix a prepared bug -------------------------------------------

_BUGGY_CALC = """def add_clamped(a, b, low=-100, high=100):
    \"\"\"Return a+b clamped into [low, high].\"\"\"
    result = a + b
    if result < low or result > high:
        return 0
    return result
"""

_CALC_TESTS = """import unittest
from calc import add_clamped


class TestAddClamped(unittest.TestCase):
    def test_inside(self):
        self.assertEqual(add_clamped(2, 3), 5)

    def test_clamps_high(self):
        self.assertEqual(add_clamped(60, 60), 100)

    def test_clamps_low(self):
        self.assertEqual(add_clamped(-60, -60), -100)

    def test_boundary(self):
        self.assertEqual(add_clamped(100, 0), 100)
        self.assertEqual(add_clamped(-100, 0), -100)
"""


@eval_spec(
    "code_fix_bug", "Code: fix a bug",
    "Provides a small module with a failing test suite; the agent must find and fix the bug.",
    "development",
    "The module `calc.py` in this workspace has a bug: `tests/test_calc.py` fails. "
    "Find the bug, fix `calc.py` so the whole suite passes, and run the checks to verify.",
)
def _build_fix_bug(root: Path) -> None:
    (root / "tests").mkdir(parents=True)
    (root / "calc.py").write_text(_BUGGY_CALC, encoding="utf-8")
    (root / "tests" / "__init__.py").write_text("", encoding="utf-8")
    (root / "tests" / "test_calc.py").write_text(_CALC_TESTS, encoding="utf-8")


# --- 3) research: ledger coverage -------------------------------------------

@eval_spec(
    "research_coverage", "Research: sources and synthesis",
    "Runs a short research task; the checker verifies fetched sources, a synthesis and full citation coverage.",
    "research",
    "Research the question: 'What are the main practical differences between SQLite WAL "
    "and DELETE journal modes?' Work as usual: plan sub-questions, search, fetch at least two "
    "sources and finish with a complete synthesis citing every source.",
)
def _build_research(root: Path) -> None:
    pass


# --- 4) writing: structured document ----------------------------------------

_REQUIRED_HEADINGS = ["Introduction", "Methods", "Results", "Conclusion"]

_DOC_PROMPT = (
    "Create a Word document `report.docx` in this workspace about renewable energy trends. "
    "It must contain exactly these level-1 headings in order: Introduction, Methods, Results, "
    "Conclusion. Under each heading write 2-3 sentences. Finish by confirming the file exists."
)


@eval_spec(
    "document_edit", "Writing: structured document",
    "Asks for a DOCX with four required sections; the checker reads the document and verifies the headings.",
    "writing",
    _DOC_PROMPT,
)
def _build_document(root: Path) -> None:
    pass


# --- 5) discussion: project memory ------------------------------------------

_MEMORY_FACT = "preferred-unit=metric"

_MEMORY_PROMPT = (
    f"Remember this project fact by saving it to the project memory with scope 'project': "
    f"'All measurements in this project use metric units ({_MEMORY_FACT}).' "
    "Then reply with a one-sentence confirmation."
)


@eval_spec(
    "chat_memory", "Discussion: project memory",
    "Asks the agent to store a fact in the project memory; the checker verifies the memory file content.",
    "discussion",
    _MEMORY_PROMPT,
)
def _build_memory(root: Path) -> None:
    pass


# --- checkers ---------------------------------------------------------------

def _check_code_add(session, agent) -> tuple[bool, str]:
    workspace = Path(session.meta.get("workspace") or "")
    module = workspace / "textutils.py"
    tests = workspace / "tests" / "test_textutils.py"
    if not module.is_file() or not tests.is_file():
        return False, f"missing files: module={module.is_file()} tests={tests.is_file()}"
    ok, tail = _run_tests(workspace)
    return ok, tail


def _check_fix_bug(session, agent) -> tuple[bool, str]:
    workspace = Path(session.meta.get("workspace") or "")
    ok, tail = _run_tests(workspace)
    return ok, tail


def _check_research(session, agent) -> tuple[bool, str]:
    from harness.research import ResearchLedger
    run = ResearchLedger(session).current()
    if not run:
        return False, "no research run recorded"
    sources = run.get("sources") or []
    if len(sources) < 2:
        return False, f"only {len(sources)} source(s) fetched"
    synthesis = run.get("synthesis") or ""
    if len(synthesis.strip()) < 200:
        return False, "synthesis missing or too short"
    coverage = run.get("citation_coverage") or {}
    if not coverage or not all(coverage.values()):
        missing = [sid for sid, ok in coverage.items() if not ok] or list(
            {s.get("id") for s in sources} - set(coverage))
        return False, f"citation coverage incomplete: {missing}"
    return True, f"{len(sources)} sources, synthesis {len(synthesis)} chars, coverage complete"


def _check_document(session, agent) -> tuple[bool, str]:
    from docx import Document
    workspace = Path(session.meta.get("workspace") or "")
    path = workspace / "report.docx"
    if not path.is_file():
        return False, "report.docx not created"
    doc = Document(str(path))
    headings = [p.text.strip() for p in doc.paragraphs if p.style.name == "Heading 1"]
    if headings != _REQUIRED_HEADINGS:
        return False, f"headings {headings}"
    body = "\n".join(p.text for p in doc.paragraphs)
    if len(body) < 200:
        return False, "document body too short"
    return True, f"headings ok, {len(headings)} sections"


def _check_memory(session, agent) -> tuple[bool, str]:
    workspace = Path(session.meta.get("workspace") or "")
    memory_file = workspace / "QWEN_MEMORY.md"
    if not memory_file.is_file():
        return False, "QWEN_MEMORY.md not created"
    content = memory_file.read_text(encoding="utf-8", errors="replace")
    if "metric" not in content.lower():
        return False, f"fact not stored; content: {content[:120]!r}"
    return True, f"memory file contains the fact ({len(content)} chars)"


_CHECKERS = {
    "code_add_function": _check_code_add,
    "code_fix_bug": _check_fix_bug,
    "research_coverage": _check_research,
    "document_edit": _check_document,
    "chat_memory": _check_memory,
}


# --- scoring + persistence ---------------------------------------------------

def results_file(cfg) -> Path:
    return cfg.path("paths.runtime_dir") / "eval-results.json"


def read_history(cfg, script_id: str | None = None) -> list[dict]:
    try:
        rows = json.loads(results_file(cfg).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [row for row in rows if script_id is None or row.get("script") == script_id]


def _append_result(cfg, record: dict) -> None:
    from harness.changes import atomic_write_text
    rows = read_history(cfg)
    rows.append(record)
    atomic_write_text(results_file(cfg), json.dumps(rows, ensure_ascii=False, indent=1))


def score(cfg, session, agent) -> dict | None:
    """Run the checker for a session marked with meta['eval']; persist + return the record."""
    script_id = (session.meta or {}).get("eval")
    if not script_id or script_id not in EVALS:
        return None
    started = time.time()
    state, detail = "error", ""
    try:
        state, detail = _CHECKERS[script_id](session, agent)
        state = "pass" if state else "fail"
    except Exception as exc:  # A broken checker must never fail the run itself.
        detail = f"{type(exc).__name__}: {exc}"
    record = {"script": script_id, "session_id": session.id, "state": state,
              "detail": str(detail)[:800], "time": started,
              "duration": round(time.time() - started, 1)}
    try:
        _append_result(cfg, record)
    except OSError:
        pass
    return record


def catalog(cfg) -> dict:
    """Script list with the latest result per script, plus the full history."""
    history = list(reversed(read_history(cfg)))
    latest: dict[str, dict] = {}
    for row in reversed(history):
        latest.setdefault(row.get("script"), row)
    scripts = [{"id": spec["id"], "label": spec["label"], "description": spec["description"],
                "work_mode": spec["work_mode"], "last": latest.get(spec["id"])}
               for spec in EVALS.values()]
    return {"scripts": scripts, "history": history[:60]}
