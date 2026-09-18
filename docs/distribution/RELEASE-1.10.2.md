# Marvin 1.10.2 - safe project removal

Released on 18 September 2026. GitHub tag `v1.10.2`.

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
