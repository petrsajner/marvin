# Marvin 1.10.1 - MTP visibility and the RAM-draft verdict

Released on 18 September 2026 from the local application commit recorded in Git.
Local release, same scope as 1.10.0: the owner's workstation installation only,
no GitHub assets.

## Changes

- The header now shows an amber **MTP** badge next to the model name while a
  speculative profile is running (`/api/runtime` reports the running profile
  with its id, label and speculative flag).
- The generation status line shows the live token rate (`~N tok/s`, a rolling
  client estimate from streamed text) next to the existing token estimate.
- Keeping the MTP draft in system RAM was measured and **rejected**: the draft
  on CPU is 33–40 % slower than plain generation because one draft forward
  pass over DDR5 (~25 ms) exceeds the whole GPU target step (~16 ms). The q5
  24 GiB class therefore ships without MTP variants. Evidence in
  [mtp-profiles](../design/mtp-profiles.md); no product code path was added.
- A speed investigation of the owner's session found MTP active with
  task-dependent gains (115–135 tok/s on short tasks, ~62–67 tok/s on
  long-context natural text at ~50 % acceptance); the live tok/s display makes
  this visible while working.

## Validation

- Release pipeline passed: 366 core checks and 111 service tests in the source
  checkout; React build and both revised PDF manuals rebuilt.
- Actual Full upgrade: exit 0 in 67.9 s, sessions and runtime preserved. The
  installed copy reports 1.10.1 and passed 112 service tests (three source-only
  tests skipped), including the new running-profile assertion. `/api/runtime`
  in the installed copy returns `q8_0_mtp / "Q8 · 192k · MTP" / speculative`.

| Artifact | Bytes | Actual upgrade |
|---|---:|---|
| Minimal | 53,468,892 | built; not installed this time |
| Full | 940,743,277 | Exit 0, 67.9 s |

## Offline backup

`Marvin-Offline-Backup-1.9.0` was renamed in place to
`Marvin-Offline-Backup-1.10.1`. Four distribution files changed (Full Setup,
both manuals — the install guides, README-OFFLINE and requirement files are
unchanged) and the MTP draft model with its verification receipt was added
under `payload/runtime/models/Qwen3.8-27B/`. The manifest now has 84 entries;
weights, llama.cpp, WebView2 payloads and the Python dependency ZIP were not
re-copied or repacked. The installed backup selector points to the new folder.
Every file passed the full SHA-256 `offline_backup.py verify` check.
Manifest SHA-256: `03f690bca711ba6297d8bce8c9328b25114d82486df5a31240367a1ed8a6e0f3`.
