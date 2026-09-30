# Release record: Marvin 1.18.2

30 September 2026. Contains the startup and MTP corrections first installed as
1.18.1, plus the desktop focus correction identified during the owner's review.
The detailed baseline comparison and evidence are in
[Review of the 1.18.0 update](REVIEW-1.18.0.md).

## Behavior

- The workspace renders its loading screen while application state is missing,
  then opens the conversation instead of crashing to a black window.
- Memory recovery continues to serve the active task's captured profile request.
  A selection changed during that task is applied to the next task.
- A new explicit model request replaces an obsolete served-profile marker,
  including when an already-running matching profile can be reused.
- Startup focuses the created WebView window by its native handle. It does not
  expose the hidden GDI+ helper or raise other windows with Marvin in their titles.

## Validation

- 371 unittest tests and 361 core checks passed; localization/version checks passed.
- TypeScript/Vite production build passed. Browser regression checks cover initial
  rendering, delayed state, visible API failures, reload and the MTP settings paths.
- Native-window probe passed with real WinForms main/helper windows. The final
  installed-window/taskbar check was interrupted by Escape; see the review record.
- Full runtime passed the isolated private-Python, conflicting-environment,
  locked-dependency, DLL-load and fresh-API checks. Its verified dependency payload
  was reused from 1.18.1 with the new application-version metadata.
- Actual Minimal upgrade exited 0. Installed code/assets matched the build;
  all 15 pre-existing history files retained their original SHA-256 values.
  The installed API reported 1.18.2 and returned the original chat list.
- English/Czech manual versions match 1.18.2 and their covers were rendered and inspected.

The assets are staged in `dist/release-1.18.2/` with the established public
filenames. The exact hashes and download URLs are recorded in
`release-1.18.2.json`. The application build commit is `592dcde`; the release
description and refreshed screenshots are documentation changes.

| File | Bytes | SHA-256 |
|---|---:|---|
| Marvin-Setup-Minimal.exe | 54,589,621 | `536f78b412b2e0eac55ab99727f38ac698941ee671109ecef1f5db0b172330d9` |
| Marvin-Setup-Full.exe | 915,201,770 | `d73befd686b94f3c542f3028f714ec8532b0f176c55612b0138d2c0b7b042a6d` |
| Marvin-Manual-EN.pdf | 197,260 | `fe176291333afc62150cdd2d78bbafc5a354eb300ff2e11e7c5fb5369cd2c1be` |
| Marvin-Manual-CS.pdf | 191,555 | `0f76ea2a863ce62646e8f466cb7d85c38a016e8df8634a57cc5969200fe27580` |
| Marvin-Workspace.jpg | 136,523 | `41bdec06fd93e28ab17c53167777f566c9fda995860d93a0781c58ac3055652b` |

## Offline package refresh

The existing offline package was refreshed and renamed to
`Marvin-Offline-Backup-1.18.2/`. It contains 105 recorded files and
236,351,758,023 bytes. The refresh replaced the Full installer and both manuals,
removed `Marvin-Setup-1.18.0-Full.exe`, and retained the dependency archive because
the requirements and lock are unchanged. The 97 retained payload files match
their previous manifest records, sizes and modification times. Updated-file
SHA-256 values match the manifest and staged release assets.

The source and installed application's `runtime/offline-backup-path.txt` markers
now point to the renamed folder. The installed marker previously pointed to the
old pre-move 1.16.1 location.

`tests/check_distribution.py` passed against the refreshed package: dependency
restoration into a fresh venv, all locked versions, application API, compiled UI
delivery and an empty personal-data store. This is a fresh-environment check,
not a clean Windows VM or an additional Full installer execution.

The public description in `RELEASE-NOTES-1.18.2.md` carries forward the workstation
overview from 1.17.4 and adds all changes through 1.18.2. Seven screenshots were
captured from the production frontend with disposable English demonstration
data, including the visible MTP switch. Screenshot rendering produced no
JavaScript errors. Image links are pinned to the 1.18.2 Git tag.

The broken GitHub release 1.18.0 was removed on 30 September 2026, with its
historical source tag retained. This release is its corrected replacement.

## GitHub publication verification

Published on 30 September 2026 as the latest release:
[Marvin 1.18.2](https://github.com/petrsajner/marvin/releases/tag/v1.18.2).
The release tag points at `6336629014984468ad39a7b5baa50218418a0383`; the
application build remains `592dcde`.

All six uploaded asset sizes and GitHub SHA-256 digests matched the release
manifest before publication. After publication, all six complete downloads,
including Full and Minimal, were streamed without authentication and matched
their expected sizes and hashes. The public latest-release API returns
`v1.18.2`; the 1.18.0 release endpoint returns HTTP 404.

All seven gallery URLs returned HTTP 200 and matched the local image bytes.
An anonymous browser opened the public release, rendered all seven images
including the expanded settings gallery, and showed the Latest badge. The
workspace preview checksum in the manifest reflects the refreshed 1.18.2
screenshot; installer and manual hashes are unchanged.
