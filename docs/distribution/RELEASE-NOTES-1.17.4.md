# Marvin 1.17.4 — change cards, live app preview, Test and fix, plan-first

**Marvin má ze srovnávané sady nejlepší „motor":** měřené GPU profily s poctivým
recovery žebříčkem, MTP spekulativní dekódování, crash-safe trvalé úlohy, živé
nasměrování s ochranou prompt cache, journal změn s vrácením souborů po jednom,
dokumentovou inteligenci (Word in-place, PDF, Excel), research ledger s citacemi,
paměť a rozhodnutí napříč chaty, diktát a offline instalátor s ověřenou zálohou.
Žádný cloudový nástroj tohle nemá — Dyad a bolt.diy se o to jen přibližují.

**A teď k tomu přibyly i tři smyčky, které dřív chyběly** — přesně ty, které dělají
z vibe-coding nástroje špičku:

- **Smyčka důvěry.** Po každém úkolu se objeví karta „Co jsem změnil" s lidskou
  větou u každého souboru, vrácením jedním kliknutím a technickým diffem až na
  vyžádání. Každá destruktivní akce se ptá na potvrzení a rozsah vrácení je
  vyslovený poctivě: vrací soubory projektu — historii chatu a věci mimo projekt
  ne.
- **Smyčka výsledku.** Generovaná webová aplikace běží v živém náhledu
  v pravém panelu s automatickým obnovováním; spuštěný server se hlásí kartou
  „Aplikace běží na …" s otevřením a zastavením. A **„Otestuj a oprav"** aplikaci
  sama otevře, prokliká hlavní ovládání, přečte konzoli i síť, opraví nalezené
  a opravy ověří — výsledek je karta „Zpráva z testu" v lidské řeči.
- **Prvních deset minut.** Uvítací obrazovka s hotovými úlohami místo prázdného
  chatu, katalog schopností na očích místo za žárovkou, diktát, přepínač
  „Plán napřed" pro chvíle, kdy chcete nejdřív vidět plán a schválit ho — a
  Nastavení s režimem Jednoduché/Pokročilé, aby běžný uživatel neviděl ani jedno
  „KV cache profil".

![Marvin workspace](https://raw.githubusercontent.com/petrsajner/marvin/main/docs/images/Marvin-Workspace.jpg)

*In English:* Marvin ships the best engine in its class — measured GPU profiles
with an honest recovery ladder, MTP speculative decoding, crash-safe durable
jobs, live steering that protects the prompt cache, a per-file change journal
with one-click restore, document intelligence (in-place Word, PDF, Excel), a
research ledger with citations, cross-chat memory and decisions, dictation, and
an offline installer with a verified backup. No cloud tool has this. And now it
also has the three loops the category leaders had and Marvin lacked: the **trust
loop** (a plain-language "What I changed" card with one-click restore and honest
restore scope), the **result loop** (a live app preview, an "app is running"
card, and *Test and fix* which opens the app, clicks through it, reads console
and network, fixes and verifies), and **the first ten minutes** (a welcome
screen with ready tasks, the capability catalogue on the surface, dictation, an
opt-in *Plan first* switch, and Simple/Advanced settings).

---

## Everything since 1.16.1: the 1.17.0–1.17.4 wave

### Důvěra — a plain-language change card

Every finished task now ends with **"What I changed"**: one plain sentence per
file ("I added the Start button to `index.html`"), a **Restore** button per file
and the technical diff one click away — never in your face. Destructive actions
(Revert task changes, Unpin all) ask for confirmation in the same styled dialog
the rest of the app uses.

![Change card](https://raw.githubusercontent.com/petrsajner/marvin/main/docs/images/Marvin-ChangeCard.jpg)

### Výsledek — the app is running where you can see it

A new **Preview** panel shows the newest web page or application live, refreshing
itself while the agent works. A background command that prints its own address
becomes an **"The app is running at …"** card with Open and Stop. And
**Test and fix** runs the verification loop: launch, click through the main
controls like a user, read console and network, fix what it finds, verify the
fixes (max three rounds), and report as a **"Test report"** card — checks with
✓/✗ and a sentence each.

![Preview panel](https://raw.githubusercontent.com/petrsajner/marvin/main/docs/images/Marvin-Preview.jpg)

### Prvních deset minut — you never face an empty box

The empty chat is now a **welcome screen with ready tasks** from the capability
catalogue — one click writes the request for you. The catalogue itself is on the
surface. Dictation speaks your request in Czech or English. **Plan first** is a
switch beside the work-mode selector: on, Marvin proposes a plan and waits for
your approval before touching a file; off, nothing is ever gated. Settings opens
in a **Simple** view (Advanced keeps every technical knob one toggle away).

![Welcome screen](https://raw.githubusercontent.com/petrsajner/marvin/main/docs/images/Marvin-Welcome.jpg)
![Settings](https://raw.githubusercontent.com/petrsajner/marvin/main/docs/images/Marvin-Settings.jpg)

### Spolehlivost — the fixes behind the loops

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
release by refreshing the owner's 221 GB backup with the packaged script and
checking `payload/runtime/openart/openart.exe` is inside (105 files, every
SHA-256 verified).

## Instalace

- **Full** — doporučeno pro nový počítač: vlastní Python, balíčky i runtime.
- **Minimal** — potřebuje 64bitový Python 3.12 s Python Launcherem (`py`).
- Přeinstalace přes existující Marvina vymění jen aplikaci: prostředí, modely,
  projekty, konverzace i paměť zůstávají.

*Upgrading over an existing Marvin replaces only the application: environment,
models, projects, conversations and memory all stay.*
