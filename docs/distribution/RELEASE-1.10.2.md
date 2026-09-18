# Marvin 1.10.2 - safe project removal

Released and published on 18 September 2026. GitHub tag `v1.10.2` resolves to
application commit `88d4d969f8aa953850d9f02503ac013f35bccc64`. The [release
manifest](release-1.10.2.json) records all seven public assets, their sizes,
SHA-256 values and stable download URLs. Public link:
https://github.com/petrsajner/marvin/releases/latest

`Marvin-Offline-Backup-1.10.1` was renamed in place to
`Marvin-Offline-Backup-1.10.2` with the Full installer and both manuals
replaced (84 manifest entries, all SHA-256 verified; weights and runtime not
re-copied). Manifest SHA-256: `1a642eaea6ddda7611170e3b55cfbe2250c216f42b36a2abc924aa782842736b`.
All seven server-side asset digests matched the local values before
publication; after publication the unauthenticated `latest` link resolves to
1.10.2, small downloads passed full SHA-256 checks and the installer/ZIP range
requests verified signatures and total sizes.

## The fix

Deleting a project that was **attached from your own folder** now only removes
the project registry entry and the project's conversations — **the folder and
its contents always stay on disk**. Only projects created inside Marvin (under
its projects directory) still delete their folder. If such a folder cannot be
deleted, nothing is removed and a readable error is returned instead of a raw
internal error.

Motivation: an attached folder is owned by the user and can be anything,
including a source-code repository. The previous behavior deleted the whole
folder from disk; on Windows it typically failed midway on read-only or locked
files (for example Git object files), leaving an unclear "Internal Server
Error" — and on folders without such files it would have completed the
deletion. The dialog now shows a proper title, and the button and confirmation
text distinguish the two cases ("Remove project" for attached folders).

## Validation

- 368 core checks (two new: attached-folder deletion keeps files; a locked
  managed folder reports a readable error and stays registered) and all
  workspace, runtime, history, prompt, WebView2, memory-profile and
  localization service tests passed in the source checkout. The React build
  and both revised PDF manuals were rebuilt.
- Actual Full upgrade of the owner's workstation installation: exit 0 in 51.4 s,
  sessions and runtime preserved; the installed copy reports 1.10.2 and passed
  all 112 service tests (three source-only tests skipped). The owner's
  repository-folder project was then removed through the fixed endpoint: the
  registry entry and its one empty conversation were deleted, the repository
  itself stayed byte-identical (verified with `git status`).

| Artifact | Bytes | Actual upgrade |
|---|---:|---|
| Minimal | 53,461,970 | built; not installed this time |
| Full | 940,743,419 | Exit 0, 51.4 s |
