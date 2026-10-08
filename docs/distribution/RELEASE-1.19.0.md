# Release record: Marvin 1.19.0

8 October 2026. Qwen3.8-Flash-Next moves to the Strata engine: measured
profiles for 16, 24 and 32 GB cards with 32, 48 and 64 GB of RAM, Marvin
prepares the engine and Flash-Next's files itself, and switching to Flash-Next
keeps the chat. The engine work and its evidence are in the
[Strata handover](../design/2026-10-06-strata-handover.md) and the
[qualification record](../design/strata-qualification-2026-10-07.md).

## Behavior

- Two Flash-Next entries, IQ3_S (default) and IQ2_XS (optional), each with a
  profile per GPU class and RAM class; 48 and 96 GB cards use the 32 GB rows
  (derived, not measured). The llama.cpp Flash-Next entry is gone and its
  preference moves to IQ3_S.
- On first use Marvin installs the pinned engine (0.1.39) into
  `runtime/strata`, verifies the weights, builds the expert pack and the MTP
  draft layer. The Full installer carries the engine archives and the 16 wheels
  of `requirements-strata-py312.lock`, so only weights and the draft layer are
  downloaded.
- The emergency RAM guard counts Strata's mapped expert pages as reclaimable
  and waits 60 s for a Strata server while commit room remains. Profiles where
  the engine fills the card keep a 1100 MiB VRAM reserve.
- A research task keeps the model's structured report as its single answer; the
  change summary appears only when the task changed files.
- The loop warning also detects a repeated cycle of steps; outside Git the
  task's change journal counts as the diff review.

## Validation

- 485 unittest tests passed on the release commit; localization checks passed.
- `installer/release.bat` built both installers with all tests and the Full
  runtime check passing.
- A real install into an empty folder and `tests/e2e_flash_next.py clean`
  passed: Marvin prepared the engine and Flash-Next's files from nothing and
  switched Q5 → Flash-Next → Q5 in one chat.
- The owner tested the installed build in daily use on 8 October; the first
  field test's KV downgrade under Windows paging was fixed and re-verified
  (lowest free RAM 0.99 GiB, no restart).

The assets are staged in `dist/release-1.19.0/` with the established public
filenames. The exact hashes and download URLs are recorded in
`release-1.19.0.json`. The application build commit is `eaf9b32`; later
commits change only documentation.

| File | Bytes | SHA-256 |
|---|---:|---|
| Marvin-Setup-Minimal.exe | 54,135,437 | `12a5e3a42f51a27685c8fd7075883230f0293b8b54818fd09257c129db6e329b` |
| Marvin-Setup-Full.exe | 1,515,021,413 | `2aff41dd509f6fce78e7add62e03134624e13349ccd41649acf9f6f5b9c5cdd3` |
| Marvin-Manual-EN.pdf | 226,770 | `a71556c5a3e9e9d722000c8145a15d22c3405bbdf7f4eb79ed30ea12626e2c29` |
| Marvin-Manual-CS.pdf | 221,776 | `ec33410458f74b43cf603dc1d17e9566d1f26c915d08383d90c7b64fbd9c8eaa` |
| Marvin-Workspace.jpg | 136,523 | `41bdec06fd93e28ab17c53167777f566c9fda995860d93a0781c58ac3055652b` |

## Offline package refresh

`Marvin-Offline-Backup-1.18.2` was refreshed from the installation and renamed
to `Marvin-Offline-Backup-1.19.0`: 2,948 recorded files, 217.8 GB of payload,
`offline_backup.py verify` passed for every file. It carries the 1.19.0 Full
installer, the Python environment, llama.cpp, the prepared engine with its
venv, Flash-Next IQ3_S with its pack and draft layer, and the other models.
IQ2_XS and the draft layer's download intermediates stay out. The old
llama.cpp Flash-Next files were moved aside for the owner to delete.

The public description is `RELEASE-NOTES-1.19.0.md`. Its intelligence table
quotes the Artificial Analysis Intelligence Index as of October 2026.
