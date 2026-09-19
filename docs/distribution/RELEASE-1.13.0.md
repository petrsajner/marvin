# Marvin 1.13.0 - find anything, drive a window without losing the screen, watch a document being written

19 September 2026. The last three gaps from the comparison against other
harnesses, plus the second half of computer control.

## One search instead of four

The box at the top of the sidebar now searches everything: conversations, the text
files in the open project, all three layers of memory, and the project's
decisions. Each result says what it is, and clicking it opens that place rather
than describing it. Which project is searched follows the open conversation.

Three faults surfaced while building it, all now covered by tests. A one-word
search returned the same decision three times, because memory and decisions live
in files and were also reported as files. Project files match so much more
readily than the other sources that eight file hits buried the single line of
memory that was the answer - hence a cap per source. And a file result carried
only a path, so clicking it answered 404: the preview resolves an id from the file
store. That one was found by clicking it.

A source that fails is left out rather than failing the search. A missing group is
better than an error where the answer should be.

## Go to, with Ctrl+K

A box that offers what the interface can do - new chat, switch work mode, the
capability catalogue, the context, progress and changes panels, each settings
page, dictation when it is ready - and below that, whatever the words found in
your own work, through the same search. Enter runs the first action.

The actions are built where their callbacks already live, so this is a second way
into the interface rather than a second implementation of it, and the list of
settings pages is shared with the settings dialog so the two cannot drift apart.

## A document you can watch being written

Writing is the mode this harness is really for, and it was the one place with no
feedback while work happened: the document was on disk, the chat described it, and
a preview froze at the moment it opened.

An open preview now follows the file, re-reading it and redrawing only when the
content really changed. In **Files changed**, a document the task touched has a
second button that opens it rendered and keeps it current. The button appears for
what can be rendered - Markdown, text, DOCX, PDF, HTML, CSV, spreadsheets - and
not for code or binaries, which have nothing to show.

## Keys into a window, without taking the screen

`press_key` accepts a window title and posts the keys straight into that program,
which no longer has to be in front. Measured against two real pygame windows with
the target covered: enter, letters, arrows and `ctrl+s` all arrived, with press,
release and the modifier registered, and the window in front received nothing at
all.

Bringing a window forward is therefore the fallback rather than the opening move,
for the programs that read the keyboard directly and can only be reached in front.
The Computer prompt states that order, and a test keeps it stated.

There is also a new skill, `testing-a-running-program`, covering both that path
and the headless one: an SDL or pygame program runs with the dummy video driver,
renders into memory and saves a frame the model can look at, which answers
questions about behaviour without a window and without touching the screen.
Verified here: no window appeared, posted events were delivered, the saved frame
was a real picture.

## Dictation shows its progress

Enabling dictation downloads 556 MB, and the panel used to show one sentence that
never changed - indistinguishable from a download that had stalled, which is
exactly how it read. It now reports bytes and a percentage, counting the whole
installation rather than each file, and the panel follows it once a second.

The speech model and program have been part of the offline backup since 1.12.0.
Verified again for this release: restoring into a clean folder brings all
seventeen files, including the verification receipts, after which dictation
reports itself ready with no network at all.

## Two chores that were being done by hand

Refreshing the offline backup now renames its folder to the version it holds, and
the application follows a backup that was renamed instead of reporting the
recorded name as missing - which is how the pointer came to name 1.11.1 while the
folder said 1.11.2. And a rebuilt private environment no longer keeps every
predecessor for ever: one is a safety net, a collection is just disk.

## Verification

370 checks in the core suite and 266 unit tests, green locally before the build.
The measurements behind the window work and the search are recorded in
[finding-your-way.md](../design/finding-your-way.md) and
[voice-input.md](../design/voice-input.md).
