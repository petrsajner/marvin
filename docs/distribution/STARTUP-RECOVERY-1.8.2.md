# Marvin 1.8.2: automatic history loading and recovery

13 September 2026; follows `2fbce10` (1.8.1).

## Root cause

After a Minimal installation, the model and web server ran, but `/api/state` returned HTTP 400: `Unterminated string starting at: line 1 column 29 (char 28)`. All 44 physical JSONL records in the affected chat were valid. A fetched source contained U+2028, a Unicode line separator.

The reader used `str.splitlines()`, which also splits U+0085, U+2028 and U+2029 inside JSON strings. It cut a valid message in half. Import and search-index rebuilding shared the defect. The data was intact. Earlier startup diagnostics checked server/model availability but did not open the selected conversation.

## Application behavior

- Readers use physical LF/CRLF JSONL boundaries. Unicode separators inside message contents remain part of the message; import and search follow the same rule.
- New writes escape these characters losslessly. Valid old conversations do not need rewriting or deletion.
- On a truly invalid record, loading first waits for any concurrent write and rereads the file, avoiding interference with an in-progress message.
- Recovery preserves a verified copy of original bytes under the chat's `recovery` directory. A complete message can be restored from its uniquely identified durable event. Existing messages are not duplicated and deliberately removed steps are not arbitrarily resurrected.
- If no complete record exists, original bytes remain preserved and available messages open. Missing positions are tracked internally to retain compression boundaries and prevent assumed success of interrupted actions. Missing content is never invented.
- Main and fallback UIs recover in the background without confirmation dialogs or technical repair prompts. Normal startup has no new diagnostic gate.

The extended `/api/state`, selected-chat and detail checks belong to release `--smoke` verification. The runtime fix is correct reading and automatic recovery, not stricter startup rejection.

## Verification

The original defect was reproduced before repair. Then 366 core checks and 65 service/runtime tests passed, including nine Unicode-history, project import/export, search, UI-startup, event-recovery, original-file preservation and concurrent-write checks.

The actual affected chat loaded all 44 messages with an identical before/after SHA-256: no original byte changed. A real Minimal 1.8.2 upgrade exited 0; all 65 service tests passed in the installed environment. Normal `Marvin.exe` opened the workspace, returned HTTP 200 for state/chat/detail, displayed the original history and reported Flash-Next Ready. The application was left available to the user at the end of that run.

Q3 weights, Q8 KV, xhigh, model files and inference dependencies were unchanged. Local evidence includes private conversation/database snapshots, so it is excluded from Git and distribution.

## Historical package hashes

These identify the initial history-recovery build. At the owner's request, 1.8.2 installers were subsequently replaced with automatic-WebView2 builds under the same version. See the [release manifest](release-1.8.2.json) for current files.

| File in `dist/` | Bytes | SHA-256 |
|---|---:|---|
| `Marvin-Setup-1.8.2-Minimal.exe` | 52,349,925 | `c70be547575dcbbfaf49f164044f406b4c0df17980c747c3d2ac4b8554fae79f` |
| `Marvin-Setup-1.8.2-Full.exe` | 727,137,000 | `81af7e0c0980b0d7cc4dbc724cd7538e217f91d0da04dac5dd3de7a6aa8c8fa6` |
| `Marvin-1.8.2-Windows-x64.zip` | 778,636,639 | `054b3436bad504591a50cce9d60730171d2f82700d6a9bf63240a217c48458c7` |

The ZIP's seven entries were verified. Only six distribution files plus the manifest changed in `Marvin-Offline-Backup-1.8.2/`; 73 other entries retained sizes, modification times and hashes. Offline manifest SHA-256: `0c9c2f02afbbb962a44d4b3ac13b667905d4b34f5fd799763bd6cab875549c54`. Installed Python sources and both PDFs matched that distribution.
