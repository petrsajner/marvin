# Marvin 1.10.1 - MTP visibility and the RAM-draft verdict

Released on 18 September 2026 and published publicly. GitHub tag `v1.10.1`
resolves to application commit `aff018b8263e29d14fc56bf603a2d97b3f765089`
(pushed as `53e24d4..aff018b` on `main`). The [release
manifest](release-1.10.1.json) records all seven public assets, their sizes,
SHA-256 values and stable download URLs. Public link:
https://github.com/petrsajner/marvin/releases/latest

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

## Public downloads

All seven asset sizes and server-side SHA-256 digests matched the local values
before publication (draft verified via the releases API). After publication,
unauthenticated `latest` requests resolve to 1.10.1. Small public downloads
(both manuals, SHA256SUMS.txt, the workspace preview) passed full SHA-256
checks; installer and ZIP range requests verified the PE/ZIP file signatures
and total sizes against the GitHub asset digests. The release body explains the
MTP profiles and the automatic WebView2 setup. The combined ZIP
(`Marvin-1.10.1-Windows-x64.zip`, 993,374,015 bytes) and the dependency
restore from the updated backup into a fresh venv passed
`tests/check_distribution.py` before upload.
