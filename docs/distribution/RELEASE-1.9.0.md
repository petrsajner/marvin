# Marvin 1.9.0 - measured profiles and distribution verification

Released on 15 September 2026 from application commit
`b1c8e80eac06cc65939dfe48eae4f25c0a9d6e9d`. GitHub tag `v1.9.0` resolves to that
commit. The [release manifest](release-1.9.0.json) records all seven public assets,
their sizes, SHA-256 values and stable download URLs.

The release implements the owner's [approved measured table](../design/profile-remeasurement-2026-09-15.md).
Q8 is the default; Qwen F16 is confined to 32 GB-class cards. The model picker
shows the relevant two contexts for each precision group. Context-only recovery
keeps model identity, cache precision and existing weight placement. Flash-Next
uses measured planning and permits Windows to reclaim RAM during startup.

## Validation

- 366 core checks passed. All 106 service, runtime, history, memory, WebView2 and
  localization tests passed in the source checkout.
- The React production build passed. Both revised PDF manuals were rendered and
  visually checked at the profile table and Flash-Next sections.
- Actual application transitions passed: Q5/Q8/96k under the 24 GB budget,
  IQ3/Q8/64k under 16 GB, and Q5/Q8/192k after returning to automatic detection.
  The change and short answer took approximately 20.3, 17.8 and 19.5 seconds.
- An injected allocation failure continued the task on Q5/Q8/128k, preserving
  the user message and completed history. Equivalent manual/automatic capacity
  reused the running server. No deliberate physical RAM exhaustion was used.
- The managed Flash-Next startup selected 256k, CPU32, eight P-core threads and
  microbatch 256. Load took 43 seconds; chat, tool roundtrip, vision and STOP all
  passed. This short integration check reuses the earlier 55-case qualification;
  it does not repeat or replace its long-input evidence.
- Full's private Python 3.12.9 and 95 locked packages passed relocation into a
  fresh directory, conflicting Python environment variables, fresh API startup,
  dependency consistency and llama.cpp DLL loading. Runtime b10935 and the
  dependency lock are unchanged.

## Real installers and installed application

| Artifact | Bytes | Actual upgrade |
|---|---:|---|
| Minimal | 54,032,026 | Exit 0, 9.3 seconds |
| Full | 941,479,448 | Exit 0, 60.9 seconds |
| Combined Windows ZIP | 994,731,610 | Seven entries; CRC and SHA-256 checks passed |

Both actual upgrades preserved all 706 tracked user-data files. The installed
100 Python source files, launcher, compiled UI, both manuals and the source/frozen
Czech catalogs matched the release. Each installed variant passed 103 executed
service tests; three source-only tests were correctly skipped.

The installed launcher lifecycle check exited 0 after 45.2 seconds. It opened
the existing workspace and selected conversation, autostarted the previously
selected Ornith at Q8/256k, and stopped both the web service and model cleanly.
The real API reported version 1.9.0 and the approved 32 GB menu. Existing chat
contents remained unchanged. The only subsequent change among the 706 recorded
files was the intended offline-backup path update.

These checks ran on the existing Windows workstation and in fresh isolated
environments on that host, not in a clean Windows VM or on physical 16/24 GB GPUs.
The detailed measurement report distinguishes allocation tests from full-window
and physical-hardware qualification.

## Offline update and public downloads

`Marvin-Offline-Backup-1.8.2` was updated and renamed in place to
`Marvin-Offline-Backup-1.9.0`. Six distribution files changed: Full Setup, the two
manuals, the two installation guides and README. The manifest still has 82
entries. The other 76 retain their sizes, modification times and stored hashes;
weights, inference runtime, WebView2 payloads and the Python dependency ZIP were
not recopied or repacked. The installed backup selector points to the new folder.

Changed files passed full SHA-256 verification. Manifest SHA-256:
`27140516f038f2989de5020f98b0e0344406cc1e623f3d2f9361857369551901`.
Restoring the unchanged dependency ZIP into a clean venv passed package, API,
compiled UI and absence-of-personal-data checks.

All seven GitHub asset sizes and server-side SHA-256 digests matched locally
before publication. After publication, unauthenticated latest-release requests
resolved to 1.9.0. Small public downloads passed full SHA-256 checks; installer/ZIP
range requests verified file signatures and total sizes against the matching
GitHub asset digests. The release body explains automatic WebView2 setup.

Public share link: https://github.com/petrsajner/marvin/releases/latest

## Retained evidence and workspace cleanup

The portable measurement JSON/CSV remains in Git. Complete measurement evidence
is retained in `runtime/archive/profile-remeasurement-2026-09-15.zip`.
The verified release archive contains 78 files with a per-file hash manifest:
`runtime/archive/verification-1.9.0.zip`, SHA-256
`3ca1101c05a8932438cd645e20ad4930c2cc5291cc25078a3275dd9f4286dc67`.
Private pre-upgrade user data is retained separately in a local archive and is
excluded from GitHub assets and the public distribution.

Only the three current release artifacts remain in `dist/`. Old artifacts were
archived; reproducible build staging and archived test copies were moved under
`runtime/KE-SMAZANI/after-1.9.0`. All 13 planned moves succeeded. Active development
environments, the installed environment and model weights were retained.
