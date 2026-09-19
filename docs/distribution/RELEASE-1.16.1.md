# Marvin 1.16.1 - Results after a restart, and whatever wrote the file

19 September 2026.

A generated picture did not appear in Results. Chasing it found two things, only
one of which was about pictures.

## Results was empty after every restart

`discover_results` read the change journal from the loaded agent, and agents live
in memory only for conversations that have run a task since the program started.
Open Marvin, open a conversation, and Results showed nothing the journal knew -
no changed files, no finished program - until that conversation was used again.

It now builds a journal from the conversation when no agent is loaded, which is
the pattern the same function's neighbours already use.

## Output folders are read, whatever wrote them

`exports` was scanned; `generated-images` was not, so a picture depended entirely
on having been recorded in the journal. The picture that started this was written
by 1.15.0, seven minutes before 1.16.0 installed the code that records one, so
nothing had recorded it and nothing ever would.

Both folders are now scanned, in the conversation and in the project. A file put
there by a program, a service or an earlier version is in Results because it is
there, not because something remembered to mention it.

## When Results loads

Every time the detail panel is asked for: opening a conversation, and after each
tool step, run status change and settings change. It is not a thing that happens
at the end of a task.

## Verification

361 checks in the core suite and 330 unit tests, green locally before the build.
Checked against the actual conversation that reported this: the picture is found
with no agent loaded.
