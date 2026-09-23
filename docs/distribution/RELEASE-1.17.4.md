# Release record: Marvin 1.17.4

23 September 2026. Public release of everything since 1.16.1 — the 1.17.0
through 1.17.4 wave — as one release.

## What shipped

The consumer-parity wave from
[consumer-parity-review-2026-09-22.md](../design/consumer-parity-review-2026-09-22.md),
implemented and hardened over five local versions:

| Version | Content |
|---|---|
| 1.17.0 | Quick wins, plain-language change card with per-file restore, live Preview tab, first-run welcome with ready tasks, Simple/Advanced settings, document paste, code copy buttons, confirmations on destructive actions; reliability: shared internal-message prefixes, process cleanup and a timeout watchdog, `load_config` root fix, version sync |
| 1.17.1 | `run_command` pipe-hang fix (file-backed output), handoff fixes (degenerate summaries, chat ordering) |
| 1.17.2 | Handoff summarizer: protocol notes kept out of the transcript, explicit closing cue, mandatory sections, degenerate-answer rejection with retry; context label confusion fixed (the summarizer's own request no longer reads as the chat's context) |
| 1.17.3 | Auto-compression anchors for agentic stretches (completed-turn cuts) plus honest no-op reporting; installer model picker selects Flash-Next |
| 1.17.4 | Context figures reconcile immediately after compression; compression keeps 20% of the limit as live recent work (owner choice) |

## Process

- Screenshot set regenerated from the real workspace UI (model autostart off,
  `--data-dir` pointing at the owner's installation): `docs/images/
  Marvin-Workspace.jpg` (stable release asset) plus ChangeCard, Preview,
  Welcome, Settings, SettingsAdvanced.
- Full payload built with `scripts/build_full_payload.py` (app_version 1.17.4,
  Python 3.12.9, 9101 package files) and compiled with `ISCC /DFullBuild`.
- Offline backup refreshed in place with the packaged `scripts/offline_backup.py
  refresh` — the folder renamed itself to `Marvin-Offline-Backup-1.17.4`,
  `verify` reports 105 files and zero errors, and
  `payload/runtime/openart/openart.exe` is present, satisfying the check the
  previous release record left behind (NEXT-RELEASE.md, deleted with this
  release).
- Suites green before packaging: 359 unittest tests, `tests/test_core.py`
  361 checks / 0 failures, frontend build clean. The version pin in
  `test_core.py` moves with `installer/version.txt` deliberately — a version
  bump that skips it fails the suite.

## Known quirks carried forward

- Backup folder naming still mixes eras in places (`QwenHarness-Offline-Backup`
  prefix in scripts vs `Marvin-Offline-Backup` in the installer's discovery);
  the refresh flow renames the folder by version, which is the direction of
  travel.
- The "tests pass in the installed copy" half of the release rule is checked by
  the owner installing this build on his machine.
