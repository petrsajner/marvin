# Marvin 1.17.4 — change cards, live app preview, Test and fix, plan-first

**Marvin has the best engine of any tool in its class:** measured GPU profiles
with an honest recovery ladder, MTP speculative decoding, crash-safe durable
jobs, live steering that protects the prompt cache, a per-file change journal
with one-click restore, document intelligence (in-place Word, PDF, Excel), a
research ledger with citations, memory and decisions that follow you across
chats, dictation, and an offline installer with a verified backup. No cloud
tool has any of this — Dyad and bolt.diy only get close.

**And now it also has the three loops it used to lack** — exactly the ones that
separate a top-tier vibe-coding tool from the rest:

- **The trust loop.** Every finished task ends with a **"What I changed"** card:
  one plain sentence per file ("I added the Start button to `index.html`"), a
  **Restore** button per file, and the technical diff one click away — never in
  your face. Every destructive action asks for confirmation, and the restore
  scope is stated honestly: it restores the project's files — never your chat
  history, never anything outside the project.
- **The result loop.** A generated web app runs in a **live preview** in the
  right panel, refreshing itself while the agent works. A running server
  announces itself as an **"The app is running at …"** card with Open and Stop.
  And **Test and fix** verifies the work: it opens the app, clicks through the
  main controls like a user, reads the console and the network, fixes what it
  finds and verifies the fixes — the result is a **"Test report"** card in plain
  language, each check with ✓ or ✗ and a sentence.
- **The first ten minutes.** An empty chat is now a **welcome screen with ready
  tasks** — one click writes the request for you. The capability catalogue is on
  the surface, dictation speaks your request, and a **Plan first** switch shows
  you the plan and waits for your approval before a single file is touched.
  Settings opens in a **Simple** view, with every technical knob one toggle away
  under Advanced.

![Marvin workspace](https://raw.githubusercontent.com/petrsajner/marvin/main/docs/images/Marvin-Workspace.jpg)

---

## Everything since 1.16.1: the 1.17.0–1.17.4 wave

### Trust — a plain-language change card

Every finished task now ends with **"What I changed"**: one plain sentence per
file, a **Restore** button per file and the technical diff one click away.
Destructive actions (Revert task changes, Unpin all) ask for confirmation in the
same styled dialog the rest of the app uses.

![Change card](https://raw.githubusercontent.com/petrsajner/marvin/main/docs/images/Marvin-ChangeCard.jpg)

### Result — the app is running where you can see it

A new **Preview** panel shows the newest web page or application live,
refreshing itself while the agent works. A background command that prints its
own address becomes an **"The app is running at …"** card with Open and Stop.
And **Test and fix** runs the verification loop: launch, click through the main
controls like a user, read console and network, fix what it finds, verify the
fixes (max three rounds), and report as a **"Test report"** card — checks with
✓/✗ and a sentence each.

![Preview panel](https://raw.githubusercontent.com/petrsajner/marvin/main/docs/images/Marvin-Preview.jpg)

### The first ten minutes — you never face an empty box

The empty chat is now a **welcome screen with ready tasks** from the capability
catalogue — one click writes the request for you. The catalogue itself is on the
surface. Dictation speaks your request. **Plan first** is a switch beside the
work-mode selector: on, Marvin proposes a plan and waits for your approval
before touching a file; off, nothing is ever gated. Settings opens in a
**Simple** view (Advanced keeps every technical knob one toggle away).

![Welcome screen](https://raw.githubusercontent.com/petrsajner/marvin/main/docs/images/Marvin-Welcome.jpg)
![Settings](https://raw.githubusercontent.com/petrsajner/marvin/main/docs/images/Marvin-Settings.jpg)

### Reliability — the fixes behind the loops

- `run_command` can no longer hang: output goes to files instead of pipes, so a
  detached program (`start … &`) cannot hold it past every timeout — and long
  running programs are steered to `start_command`.
- Handoff summaries are real summaries again (Goal/Done/Decisions/Pending/Key
  facts), degenerate answers are rejected and retried, and the new chat lands
  first in the list.
- Automatic compression now finds its cut in agentic stretches (one request,
  a hundred tool steps), keeps **20%** of the limit as live recent work — a full
  chat compresses to about a quarter instead of a half — and the context figures
  reconcile the moment compression ends.
- The installer's model picker selects Flash-Next like every other fitting model.

### Offline backup carries the image-generation program

`scripts/offline_backup.py` now collects `runtime/openart/openart.exe` into the
package, so a machine restored from a backup is finished when the restore is —
not owing a download the first time it sees a connection. Verified for this
release by refreshing a 221 GB backup with the packaged script and checking
`payload/runtime/openart/openart.exe` is inside (105 files, every SHA-256
verified).

## Installing

- **Full** — recommended for a new PC: its own Python, packages and runtime.
- **Minimal** — needs 64-bit Python 3.12 with the Python Launcher (`py`).
- Upgrading over an existing Marvin replaces only the application: environment,
  models, projects, conversations and memory all stay.
