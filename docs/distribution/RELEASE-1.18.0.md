# Release record: Marvin 1.18.0

30 September 2026. Public release of the speculative-decoding selection fix and
the visible Speculative decoding toggle — the fix for the 2026-09-26 incident
where a graphics-memory event turned MTP off and it stayed off.

## What shipped

- **A recovery never rewrites the user's selection.** `kv_cache_modes` is the
  choice, `last_running_kv` is what runs, and the memory preset remembers the
  request separately from the profile that actually ran. Speculative decoding
  returns at the next model start once the card has room.
- **The demotion is announced.** "Speculative decoding was turned off after a
  graphics-memory event" appears in the chat's activity history with a one-click
  "Turn MTP back on".
- **Speculative decoding (MTP) is on the surface.** A visible toggle
  ("2–3× faster answers") in both Simple and Advanced settings adds or removes
  the draft model on the selected profile; the KV cache profile dropdown lists
  base profiles only.
- **Tasks keep running on the working profile** after a demotion — only a changed
  selection restarts the model between tasks. The budget switch-back recall
  restores the requested profile and never overrides an explicit profile choice
  from the same request.

## Process

- The GitHub release embeds `docs/images/Marvin-Workspace.jpg`, the workspace
  image prepared for 1.17.4 — the owner's standing requirement is no release
  without an image. The Settings screenshots in `docs/images/` predate the
  Speculative-decoding toggle and were deliberately left as they are.
- Full payload built with `scripts/build_full_payload.py` (app_version 1.18.0)
  and compiled with `ISCC /DFullBuild`; the Minimal installer is the plain
  `ISCC /DMyAppVersion=1.18.0` pass.
- Manuals rebuilt with `scripts/build_manuals.py` — `test_core` requires the
  manual PDFs to carry the current version, so a bump that skips this fails the
  suite.
- Suites green before packaging: 364 unittest tests (5 new for the selection
  preservation, the demotion notice, the no-retry rule and the preset recall),
  `tests/test_core.py` 361 checks / 0 failures, frontend build clean.
- The release scripts and two tests tolerate filesystems without hard links
  since the project moved to an exFAT drive: the Full runtime check and the
  asset staging copy instead of link there, and the frontend/version scans skip
  in installed copies where those files are not shipped.
- Changed files copied into the installed copy at `%LOCALAPPDATA%\QwenHarness`
  and both suites run there. The owner installing this build remains the final
  check.
- Offline backup refreshed in place with the packaged
  `scripts/offline_backup.py refresh` — the folder renames itself to
  `Marvin-Offline-Backup-1.18.0`.
- The stale `NEXT-RELEASE.md` entry (openart.exe collected into the offline
  backup) is deleted with this record: it shipped and was verified in 1.17.4 and
  the 1.17.4 notes already say so.

## Known quirks carried forward

- Backup folder naming still mixes eras in places (`QwenHarness-Offline-Backup`
  prefix in scripts vs `Marvin-Offline-Backup` in the installer's discovery);
  the refresh flow renames the folder by version, which is the direction of
  travel.
- The offline backup path marker in an installed copy still points at the
  pre-move project folder; `offline_backup.py` is always given `--backup`
  explicitly, so only the in-app backup button would care.
