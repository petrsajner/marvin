# Marvin 1.16.0 - one interface, and Results holds the results

19 September 2026.

## Gradio is gone

Marvin carried two interfaces. The React workspace was the one anybody saw; the
Gradio one sat behind it as a compatibility fallback. It was not even reachable
in normal use - `webapp.py` delegated to the workspace on line 26 and exited, and
the `import gradio` below that never ran. It was 4,362 lines of weight on disk
and a dependency in every installation.

Removed: `webapp.py`, `qwen_app.py`, the `gradio` requirement, and the
`MARVIN_LEGACY_UI` switch. `marvin_web.py` replaces them as the entry point - 33
lines, whose only real job is the one thing that was load-bearing in the old
file: the launcher starts it with `pythonw`, which has no console, so `stdout`
and `stderr` are `None` and anything that prints kills the process silently.

**75.9 MB out of every installation**: gradio (74.1), typer, tomlkit,
gradio_client, pydub, safehttpx, hf-gradio.

Two things were checked rather than assumed, and both mattered:

- **pandas stays.** It looked like another 40 MB, but `openai` and `fsspec` need
  it too. The saving is 75.9 MB, not the 116 it appeared to be.
- **`python-multipart` stays.** It was in the tree because Gradio pulled it in,
  and the workspace needs it: `UploadFile` on the server and three `FormData`
  posts in the interface. It was already a direct requirement, so nothing broke -
  but removing it would have broken every file attachment.

### The coverage moved rather than going with it

Slash commands were tested only through the Gradio handler, which was a second
implementation of them. `app_operations.execute_command` - the one the workspace
actually dispatches - had **no tests at all**. Deleting the Gradio tests would
have left the commands untested, so `tests/test_commands.py` now covers them
directly: the catalogue, prompt-shaped commands keeping the user's words, an
unknown command passing through rather than being answered on the model's
behalf, and every advertised command being dispatchable.

The checks that read Gradio markup for element ids are gone, replaced by checks
on the data the workspace builds its markup from: the fields a skill must carry
for the panel, and an attached image coming back as a file with a URL that
resolves. The core suite is 361 checks rather than 372 - eleven fewer, and they
were eleven checks on an interface that no longer exists.

## Results holds the results

Two things kept the real ones out, and neither was the panel - it already opens a
file on click and has a button for its folder.

**It only ever showed the last task.** The change journal starts a fresh manifest
per task and Results asked only the current one, so a finished program dropped
out the moment the next task touched a test script. It now walks every task the
conversation has run.

**A file written by something other than the file tools was never recorded.** A
generated picture whose path was sitting in the conversation was invisible in
Results, because the service writes it and no before/after pair brackets it.
`record_created` covers that, and the image tool uses it.

Ordering had to be fixed on the way: a task id is a second-resolution timestamp
plus random hex, so two tasks in one second sorted by the random half. Tasks are
ordered by the timestamp inside the manifest instead.

## Toasts only when they are the only place

"Clarification received" appeared on every message sent while a task was running,
which is the ordinary way to send one - and the same words are already a label on
that message in the queue list. It was telling the user something they were
looking at.

What remains is the case a toast is for: an error, a task that failed, and
dictation hearing nothing, that last one because the box simply stays empty
otherwise. They also clear themselves after eight seconds now. None of them ever
did, which is most of what made them feel like noise.

## Upgrading

Application code only. Conversations, projects, models and settings are
untouched. Upgrading does not remove Gradio from an existing environment - the
packages stay on disk until the environment is rebuilt - but nothing loads them.

## Verification

361 checks in the core suite, 328 unit tests and 13 localization checks, green
locally before the build, plus a frontend build and a manual rebuild. The
workspace was started from the new entry point and answered on `/config` with
`Marvin v1.16.0` before the build was made.
