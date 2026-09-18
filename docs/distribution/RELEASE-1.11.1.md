# Marvin 1.11.1 - project checks and the diff viewer on real projects

Built locally on 18 September 2026 from application commit `423c025`. **Not
published to GitHub**: the artifacts below exist only in the local `dist`
directory, so there is no `release-1.11.1.json` asset manifest yet. That file is
written when the release is actually uploaded and its server-side digests can be
compared.

This is a correctness release for the three features 1.11.0 shipped that had only
ever been exercised against this repository's own layout.

## Fixed

**Project checks now detect the layouts that exist in practice.** Detection knew
only `tests/test_core.py`, a `tests/` directory with `pyproject.toml`/`pytest.ini`,
and the Node/Rust/Go/.NET markers. A project with `test_*.py` in its root reported
"No project checks detected", and a plain `tests/` directory produced a `pytest`
command that fails immediately where pytest is not installed. Detection now covers
root-level modules and a bare `tests/` directory, defaults to the stdlib `unittest`
runner, and uses pytest only when the project configures it *and* the interpreter
can import it. Lint and type checks are offered only when their tool is installed.
The discovery form was chosen from measured behaviour per layout, not assumed:
`-s tests` works with and without `__init__.py`, `-s . -p test_*.py` is required
for root-level modules.

**Checks run with the project's interpreter.** Interpreter selection existed in
four copies that all looked only for `.venv/Scripts/python.exe`. One
`project_python()` now owns it and also accepts a plain `venv` directory.

**A status write no longer aborts the run.** On Windows `os.replace` fails while
another handle holds the target open, and the UI polls the status file for the
whole run. The write now retries; losing one never ends the run.

**Detected checks are visible before the first run.** The status merges the
current definitions with each check's stored outcome, so a check that never ran
reports `never` instead of the panel staying empty, and an outcome whose check
disappeared is dropped.

**A failed detection no longer wedges a project.** Detection ran after the running
slot was claimed, so an exception left the project marked as running for the rest
of the session and rejected every later run.

**Repair opens a Development chat.** `Fix failures with agent` reused the most
recent chat in the project whatever its mode, and `start_project_check` does not
exist outside Development and Computer. Both check endpoints now refuse a project
with no detectable checks instead of starting a task that cannot succeed.

**The diff viewer is reachable.** Both entry points required a file the agent had
changed in the newest task, so with no agent activity there was no way in at all.
A restore point now lists what changed in the workspace since it was taken and
each row opens the diff against the saved version - the backend already accepted a
`task_id`, but no caller ever passed one.

**Harness state stays out of the task.** A workspace snapshot attributed `.qwen`
to whichever task was running, so `check-status.json` and `decisions.json`
appeared as task changes and would have been picked up by the optional
auto-commit.

**The check panel no longer hammers the backend.** Check polling was added to the
runtime effect together with the status object, which is a fresh object on every
poll; since that effect polls immediately on entry, a running check turned it into
a tight loop over the runtime, check and session-detail endpoints.

## Build and release plumbing

- `build_full_payload.py` renamed the previous payload aside and never removed it,
  leaking 1.2 GB of build output per full build. Six such directories (7.2 GB) had
  accumulated. It now swaps the new payload in and drops the old one; this build
  left exactly one payload directory behind.
- The release gate stopped at `test_localization` and never covered the
  auto-commit, diff viewer, project check or semantic search suites. It now runs
  all four.
- `test_semantic_search` bucketed mock embeddings with the builtin `hash()`, which
  is salted per process, so word collisions and the ranking it asserts changed
  with every interpreter start. Measured at 1 failure in 12 hash seeds - a gate
  that blocks roughly one build in twelve at random. `crc32` makes it
  reproducible: 0 failures in 14 seeds.

## Validation

- 368 core checks and the full 155-test integration gate, three consecutive clean
  runs before the build and again inside it.
- 21 project-check tests covering the real layouts: root-level and `tests/`
  discovery actually running green and red with the app's own interpreter, pytest
  only when importable, the pre-run listing, the stale-outcome prune, the wedge,
  and the repair chat mode. 10 diff-viewer tests including the checkpoint and
  `task_id` paths.
- Verified against the owner's actual projects through the installed application:
  a root-level `test_arkanoid.py` and a `tests/` directory are both detected, the
  latter correctly resolving that project's own `.venv`; three projects without
  test files honestly report none. A full run on the root-level project returned
  the project's real result, `ModuleNotFoundError: No module named 'pygame'`,
  because that project has no virtual environment of its own.
- `tests/check_distribution.py --backup Marvin-Offline-Backup-1.11.0`: ZIP CRC and
  SHA256SUMS verified, backup dependencies restored, fresh venv with locked
  packages, working API, compiled UI, no personal data. Scope is a fresh venv and
  staged app API, not a clean Windows VM or an actual installer run.

| Artifact | Bytes | SHA-256 |
|---|---:|---|
| Minimal | 53,493,841 | `5421840434ebcb58a4477a969867e5367ca7124ba2054c5851a2ed2bc8a0d023` |
| Full | 940,780,529 | `92344cba6d94c736249e103a3d61647111ea6164a1a79ce26a9f6ec99a61daf6` |
| ZIP | 993,440,032 | `004a6d48b18ae660060f8a0f2a4d1768f1fde1627ee18b1239260f27b1e53fc0` |

## Applied

- The owner's installation was upgraded with `Marvin-Setup-1.11.1-Full.exe`
  (`/VERYSILENT`, exit 0). Conversations, projects, configuration and the
  downloaded models were retained; the installed code matches the source tree and
  the installation passes 368 core checks plus 101 service tests with its own
  interpreter.
- `Marvin-Offline-Backup-1.11.0` was renamed in place to
  `Marvin-Offline-Backup-1.11.1` and refreshed. A version bump was previously an
  ad hoc copy, which left it unclear what actually needed replacing, so
  `offline_backup.py` gained a `refresh` command that does exactly the
  application-level files and reports which ones it touched. For 1.11.1 that was
  four: the 1.11.0 Full installer removed, the 1.11.1 Full installer added, and
  both manuals replaced. `requirements.txt` and the lock are byte-identical, so
  the Python dependency archive was deliberately kept; weights, llama.cpp and
  WebView2 were never candidates. 86 manifest entries with nothing missing and no
  orphan files; every replaced file plus an untouched anchor re-hashed correctly.
  A full 210 GiB verification pass was not run - it is available as
  `offline_backup.py verify --backup <path>`.
