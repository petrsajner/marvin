"""Physical JSONL boundaries and loss-preserving recovery of local chat history."""
from __future__ import annotations

import hashlib
from contextlib import closing
import json
import re
import sqlite3
import time
from pathlib import Path

from filelock import FileLock
from harness.changes import atomic_write_text


def physical_lines(text: str) -> list[str]:
    # U+0085/U+2028/U+2029 are valid JSON string contents, not JSONL delimiters.
    return text.removeprefix("\ufeff").split("\n")


def dump_record(value) -> str:
    text = json.dumps(value, ensure_ascii=False)
    for char in ("\u0085", "\u2028", "\u2029"):
        text = text.replace(char, f"\\u{ord(char):04x}")
    return text.encode("utf-8", errors="backslashreplace").decode("utf-8")


def history_lock(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    return FileLock(str(path.with_name(".messages.lock")), timeout=30)


def _parse(raw: bytes):
    records, damaged = [], []
    for number, line in enumerate(raw.split(b"\n"), 1):
        if not line.strip():
            continue
        try:
            message = json.loads(line)
            if not isinstance(message, dict) or not isinstance(message.get("role"), str):
                raise ValueError("Invalid history message")
            records.append(message)
        except (ValueError, UnicodeError) as exc:
            damaged.append((len(records), number, line, str(exc)))
            records.append(None)
    return records, damaged


def _saved_messages(database: Path | None, session_id: str) -> dict:
    messages = {}
    if database is None or not database.is_file():
        return messages
    try:
        with closing(sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)) as db:
            for (payload,) in db.execute(
                    "SELECT payload FROM events WHERE session_id=? AND kind='message' ORDER BY seq",
                    (session_id,)):
                try:
                    value = json.loads(payload)
                    if isinstance(value, dict) and isinstance(value.get("id"), str) and isinstance(value.get("role"), str):
                        value.pop("files", None)  # derived UI links, not stored message content
                        messages[value["id"]] = value
                except (ValueError, TypeError):
                    continue
    except sqlite3.Error:
        pass
    return messages


def read_history(path: Path, database: Path | None = None) -> list[dict]:
    raw = path.read_bytes()
    records, damaged = _parse(raw)
    if not damaged:
        return records
    # A reader may have caught an append in progress. Recheck after the writer
    # finishes before deciding that any persistent bytes require recovery.
    with history_lock(path):
        raw = path.read_bytes()
        records, damaged = _parse(raw)
        if not damaged:
            return records
        digest = hashlib.sha256(raw).hexdigest()
        recovery = path.parent / "recovery"
        recovery.mkdir(exist_ok=True)
        backup = recovery / f"messages-{digest}.jsonl"
        if not backup.exists():
            with backup.open("xb") as handle:
                handle.write(raw)
        if backup.read_bytes() != raw:
            raise OSError("History recovery backup verification failed")
        saved = _saved_messages(database, path.parent.name)
        existing_ids = {m.get("id") for m in records if isinstance(m, dict) and isinstance(m.get("id"), str)}
        report = []
        for index, number, line, error in damaged:
            ids = re.findall(r'(?<!\\)"id"\s*:\s*"([^"\\]+)"', line.decode("utf-8", errors="replace"))
            candidates = {key for key in ids if key in saved and key not in existing_ids}
            if len(candidates) == 1:
                key = candidates.pop()
                records[index] = saved[key]
                existing_ids.add(key)
                method = "durable_message_event"
            else:
                # Keep record positions (compression/undo boundaries) and the
                # original bytes. This note is internal, not a user-facing error.
                records[index] = {
                    "id": f"recovered:{digest[:16]}:{number}", "role": "user",
                    "created": time.time(),
                    "content": ("[HISTORY RECOVERY - internal]\n"
                                "A damaged saved record could not be recovered from a complete message event. "
                                "Other messages remain intact. Original bytes are preserved at " + str(backup) + ". "
                                "Do not assume an interrupted action succeeded; inspect actual state before continuing. "
                                "Continue the user's task. Keep technical recovery details internal unless asked "
                                "or missing information is necessary for an accurate answer."),
                }
                method = "preserved_original"
            report.append({"line": number, "error": error, "method": method})
        atomic_write_text(recovery / "latest.json", json.dumps(
            {"original_sha256": digest, "backup": str(backup), "records": report}, ensure_ascii=False, indent=2))
        atomic_write_text(path, "\n".join(dump_record(m) for m in records) + "\n")
        return records
