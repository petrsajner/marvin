# Finding your way - one search, one keystroke, and a document you can watch

19 September 2026. Items C, D and E of the
[harness parity roadmap](harness-parity-roadmap.md), which ship together because
they are one complaint from three directions: everything is in the interface
somewhere, and you have to know where.

The capability catalogue answered this for tools the model has. These answer it
for work the owner has already done, and for the document being written now.

## D. One search instead of four

Everything was searchable, each from a different place:

| What | Where it was searched |
|---|---|
| Conversations | the box above the conversation list |
| Project files | a model tool, so you had to ask the model |
| Memory | read by eye in Settings |
| Project decisions | its own panel |

Someone who remembers a sentence but not where they wrote it had to guess which
of the four to open. `harness/finder.py` searches all of them and says, for each
hit, what it is and where it leads, so the interface opens the right thing rather
than describing it.

Decisions taken while building it:

- **Per-source cap of eight.** Project files match far more readily than the
  other three, and without a cap a file search buries the one memory line that
  was the actual answer.
- **The project's own bookkeeping is not listed twice.** `QWEN_MEMORY.md` and
  `.qwen/decisions.json` are files, and they are also the memory and decision
  groups. Measured during development: a one-word search returned the same
  decision three times before those paths were excluded from the file group.
- **A source that fails is left out, not fatal.** A search is the wrong thing to
  have break; a missing group is better than an error where the answer should be.
- **File hits carry a registered file record.** The preview resolves an id from
  the file store, never a path, so a hit carrying only a path answered 404 when
  clicked - found by clicking it.
- **The chat's project decides which project is searched.** No chat, no project
  groups, rather than searching whichever project happened to be selected last.

## E. A palette, for people who would rather type

Ctrl+K opens it. Actions are built where the callbacks already live, so the
palette is a second way into the interface and not a second implementation of it:
new chat, the capability catalogue, each work mode, decisions, the context,
progress and changes panels, compression, dictation when it is ready, and each
settings section - the last from the same list the settings dialog itself uses,
so the two cannot drift apart.

Typing also searches, through the same `/api/find`, and the results are labelled
in words - "Conversation", "Project file", "Memory", "Project decision" - rather
than by field name. Enter runs the first matching action.

## C. A document you can watch being written

Writing is the mode this harness is really for, and it was the one place with no
feedback while work happened. The document existed on disk and the chat described
it; seeing it meant opening a preview that then froze at the moment it opened.

Two changes, both small:

- **An open preview follows the file**, re-reading it every 1.5 s and re-rendering
  only when the content actually changed, so the view does not flicker while the
  model writes.
- **A changed document is one click from being watched.** The Files changed list
  gains a button for anything a preview can render - Markdown, text, DOCX, PDF,
  HTML, CSV, spreadsheets - which registers the file and opens the live preview.
  Code and binaries do not get the button, because there is nothing to render.

`POST /api/sessions/{sid}/register-file` exists for that click, and refuses a path
outside the project rather than registering whatever it is handed.

## What this deliberately is not

- **Not a new index.** All four sources already had one; this is one question
  asked of all of them.
- **Not a semantic search in the interface.** `semantic_search` remains a model
  tool and stays opt-in; the box is keyword search, which is what "I know I wrote
  this word" needs.
- **Not a file browser.** Search finds a file and opens its preview; managing
  files is still the project panel's job.

## Verification

`tests/test_finder.py`: all four sources reached by one word, every hit says where
it leads, the bookkeeping is not listed twice, no source can drown the others, a
failing source does not fail the search, a file hit really opens, and a path
outside the project is refused. The palette and the live preview are interface
wiring over those same endpoints; the settings-section list being shared is what
keeps the palette honest about what exists.
