# Marvin 1.10.0 - MTP speculative profiles

Released on 18 September 2026 from the local application commit recorded in Git.
This is a **local release**: the installers upgraded the owner's workstation
installation only. No GitHub tag, public asset or offline-backup update was
made; those steps remain for a later public release.

The release adds opt-in MTP speculative decoding to Qwen Q4/Q5 (see
[design](../design/mtp-profiles.md) and [memory profiles](../design/memory-profiles.md)):

- New measured profiles labeled "· MTP" next to their plain Q8 counterparts:
  q5 192k/128k (32 GiB class), q4 256k/192k (32 GiB) and q4 96k/64k (24 GiB).
  Decode measured 2.2–2.9× faster on structured output and 1.6–1.8× on natural
  text; the draft costs 1.9–2.8 GiB measured VRAM per case. Plain profiles,
  defaults and the 2026-09-15 measurements are unchanged.
- The pinned draft model `QWEN27B_MTP_DRAFT` (1.37 GB, SHA-256 verified,
  resumable) downloads automatically on the first MTP start and is covered by
  offline backups through the existing models directory scan.
- Recovery order for MTP sessions: same context without MTP, then lower
  context with MTP, then without. Plain selections never gain MTP.

## Validation

- Release pipeline passed: 366 core checks and all 111 service, runtime,
  history, prompt, WebView2, memory-profile and localization tests in the
  source checkout; the React production build and both revised PDF manuals
  were rebuilt by `installer/release.bat`.
- Profile qualification on the RTX 5090 host: six plain/MTP pairs measured
  back-to-back (raw records: `runtime/spec-test/results.jsonl`); the full
  agent smoke suite passed 4/4 under MTP on q5 192k and q4 256k (chat, exact
  tool-call content, vision OCR). Live budget transitions including an
  injected MTP memory failure recovered q8_0_mtp → q8_0 at the same context
  (`tests/check_memory_transitions.py`).
- One test defect was caught by the installed-copy run and fixed before the
  final build: `test_best_fit_prefers_plain_profiles_over_mtp_twins` depended
  on the checkout's `default_model`; it now pins the model explicitly.

## Real installers and installed application

| Artifact | Bytes | Actual upgrade |
|---|---:|---|
| Minimal | 53,457,798 | built; not installed this time |
| Full | 940,742,803 | Exit 0, 59.4 s |

The actual Full upgrade preserved the 14 recorded session directories and the
existing runtime (weights, llama.cpp, venv) untouched. The installed copy
reported version 1.10.0, contained the MTP profiles and Czech labels, and
passed all 111 executed service tests with the three source-only tests
correctly skipped.

The installed application then started q5 with the `q8_0_mtp` profile through
its own machinery: the 1.37 GB draft was downloaded, SHA-256-verified and
receipted on first use, the model loaded, and an exact-string reply confirmed
generation. Details in the local validation log.

## Not done in this local release

- No GitHub release, tag or public download; the 1.9.0 assets remain latest.
- `Marvin-Offline-Backup-1.9.0` was not updated or renamed.
- The combined Windows ZIP was not rebuilt; `dist/` holds the two 1.10.0
  installers alongside the 1.9.0 release artifacts.
