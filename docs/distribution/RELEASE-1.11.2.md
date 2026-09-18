# Marvin 1.11.2 - capability catalogue, advice on failure, and a prefill that survives a clarification

Released and published on 19 September 2026. GitHub tag `v1.11.2` resolves to
application commit `dec825c4b0de9733ff1889e65ddafd59c5736105`. The [release
manifest](release-1.11.2.json) records all six public assets, their sizes, SHA-256
values and stable download URLs. Public link:
https://github.com/petrsajner/marvin/releases/latest

## What's new

**Capability catalogue** (`harness/capabilities.py`, "What can I ask for?" beside
Attach). The registry holds 33 tools in Discussion and Research, 37 in Writing, 68
in Development and 75 in Computer, and the interface surfaced none of them; the
only user-facing list was a section of the PDF manual. Tool descriptions could not
be reused because they are written for the model, down to parameter names. Twenty-two
curated entries are keyed on what a person can ask for and carry a ready example,
which is the part that matters for someone who does not program: the obstacle is
not the names, it is the phrasing. Availability resolves against the real registry
at request time. An entry belonging to another work mode offers the mode switch
instead of a prompt that mode cannot deliver - proper research is a Research-mode
capability, not a way of phrasing a question - and where a capability already has a
place in the interface the entry links there instead of duplicating it.

**Advice when something fails** (`harness/failures.py`). A failed task reached the
user as a toast that faded. Both paths that can fail a run now leave a durable
notice in the conversation, and the offer extends to a failed tool result and to a
project check that failed, timed out or could not start. Recognised causes get a
plain-language next step; an unrecognised one gets none, because inventing advice
is worse than admitting there is none. Everything else offers to hand the error to
the model, with the prepared question placed in the composer rather than sent, so
it can be read and edited and no run starts by surprise.

**A clarification no longer costs the read context.** Measured on the owner's own
run: steps 1 to 53 reused the cached prefix, roughly two thousand new tokens per
step. A one-line clarification set the same interruption a stop uses, the in-flight
request was cut, llama-server discarded the slot, and step 54 restarted at cache 0
for all 109,557 tokens - about a quarter of an hour before any work resumed.
Interrupting during generation is cheap because the prompt is already read;
interrupting during the read is not, and a clarification does not need to. The
interruption now carries a reason and only an explicit stop cuts the read short.
Clarify now still redirects the answer at a sentence boundary, and a message that
has to wait says so, because silence looks like it was lost.

## Fixed

- The Stop buttons in Progress > Processes end one background command, but were
  labelled only *Stop* and their notification said *Stopping task*. Pressing one
  looked exactly like stopping the run while it kept going.
- Check detection covers the layouts that exist in practice - `test_*.py` in the
  project root, a plain `tests/` directory - defaults to the stdlib `unittest`
  runner and uses pytest only when the project configures it and the interpreter
  can import it. Checks run with the project's own `.venv` or `venv`.
- A restore point is inspectable: it lists what changed in the workspace since it
  was taken and each file opens in the diff viewer, which previously could only be
  reached through a file the agent had changed in the newest task.
- `atomic_write_text` retries a replace blocked by a reader. It is shared by about
  twenty writers, among them the live status written three times a second while
  the interface reads it, and a transient collision used to fail the task.
- Workspace snapshots no longer attribute `.qwen` harness state to the running
  task, so it cannot reach the optional auto-commit.
- The core suite wrote conversations into the live sessions directory when run
  from an installed copy, two per run. A check now compares that directory before
  and after the run.
- `build_full_payload` leaked 1.2 GB per build, and a further 1.2 GB per released
  version once the payload name carried the version.

## Release packaging

The release ZIP is gone. It contained the same two installers and the same manuals
that are published beside it, compressed by 0.1% because installers are compressed
already, so every release uploaded 993 MB of what it had just uploaded. Six assets
remain. `scripts/package_distribution.ps1` now stages exactly those under their
published names, hard-linked rather than copied, and writes one SHA256SUMS over
them; `tests/check_distribution.py` validates that staged set instead of an
archive. The 1.11.2 ZIP was removed from the release after publication and its
checksum file replaced.

## Validation

- 369 core checks and a 179-test gate, which now also covers the auto-commit, diff
  viewer, project check, semantic search and capability suites.
- 22 capabilities with every one of the 75 registered tools accounted for: 69
  mapped, 6 explicitly internal, verified by a test so a new tool nobody decided to
  advertise fails the suite.
- Check detection and a full check run verified against the owner's real projects
  through the installed application.
- `tests/check_distribution.py --backup Marvin-Offline-Backup-1.11.2`: staged
  assets hash to their checksum file, backup dependencies restored, fresh venv with
  locked packages, working API, compiled UI, no personal data. Scope is a fresh
  venv and staged app API, not a clean Windows VM or an actual installer run.
- Actual Full upgrade of the owner's installation (`/VERYSILENT`, exit 0). All
  eleven conversations, the projects and the eleven downloaded models were
  retained; the installed copy passes 369 core checks and 98 service tests with its
  own interpreter.
- The offline backup was renamed in place to `Marvin-Offline-Backup-1.11.2` and
  refreshed with the `refresh` command added in 1.11.1: four files changed - the
  1.11.1 installer removed, the 1.11.2 installer added, both manuals replaced.
  Requirements and the lock are byte-identical, so the dependency archive was kept;
  86 manifest entries, nothing missing and no orphans.

| Artifact | Bytes | SHA-256 |
|---|---:|---|
| Minimal | 53,515,438 | `731a6f25ffc477e5de17c526fc25f1ae926099b0a953734144b315d2d07672bc` |
| Full | 940,812,645 | `7c5b8028ec7760fb43a2420b5e2734d5107ea95b594dcb90e8cd5437755ee014` |
