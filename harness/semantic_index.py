"""Vector indexes for hybrid semantic search (project files + chat history).

Storage follows the existing on-demand SQLite index conventions: per-workspace
databases beside the FTS5 index (runtime/indexes/<key>.vectors.sqlite3) and one
shared store for history (sessions/semantic-index.sqlite3). Vectors are stored
normalized as float16 BLOBs; similarity is a plain dot product. The embedding
model itself runs in the CPU sidecar (harness/embedding_server.py) and is only
touched when semantic search is enabled in the settings.

Indexing happens in a background worker thread so a tool call never blocks on
embedding thousands of chunks; the tool reports progress from the state table."""
from __future__ import annotations

import json
import re
import sqlite3
import threading
import time
from contextlib import closing
from pathlib import Path

from harness.config import Config

CHUNK_CHARS = 1500
CHUNK_OVERLAP = 150
MAX_FILE_BYTES = 2 * 1024 * 1024
UPDATE_BATCH_FILES = 8          # files per embedding round inside the worker
HISTORY_MESSAGE_CAP = 4000
from harness.internal_messages import INTERNAL_USER_PREFIXES as _INTERNAL_PREFIXES

_path_locks: dict[str, threading.Lock] = {}
_path_locks_guard = threading.Lock()


def _lock_for(path: Path) -> threading.Lock:
    key = str(path).lower()
    with _path_locks_guard:
        return _path_locks.setdefault(key, threading.Lock())


def workspace_vector_db(cfg: Config, root: Path) -> Path:
    import hashlib
    key = hashlib.sha256(str(Path(root).resolve()).encode()).hexdigest()[:24]
    directory = cfg.path("paths.runtime_dir") / "indexes"
    directory.mkdir(parents=True, exist_ok=True)
    return directory / f"{key}.vectors.sqlite3"


def chunk_text(text: str, max_chars: int = CHUNK_CHARS, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """Split text on blank lines into chunks of roughly max_chars characters."""
    blocks = [block.strip() for block in re.split(r"\n\s*\n", text) if block.strip()]
    chunks: list[str] = []
    current = ""
    for block in blocks:
        if len(block) > max_chars:
            if current:
                chunks.append(current)
                current = ""
            for start in range(0, len(block), max_chars - overlap):
                chunks.append(block[start:start + max_chars])
                if start + max_chars >= len(block):
                    break
            continue
        if current and len(current) + len(block) + 2 > max_chars:
            chunks.append(current)
            current = block
        else:
            current = f"{current}\n\n{block}" if current else block
    if current:
        chunks.append(current)
    return chunks or ([text.strip()] if text.strip() else [])


def _set_meta(db: sqlite3.Connection, key: str, value) -> None:
    db.execute("INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)",
               (key, json.dumps(value)))


def _get_meta(db: sqlite3.Connection, key: str):
    row = db.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return json.loads(row[0]) if row else None


class SemanticFileIndex:
    """Incremental vector index over a workspace's text files."""

    def __init__(self, cfg: Config, root: Path):
        self.cfg = cfg
        self.root = Path(root).resolve()
        self.db_path = workspace_vector_db(cfg, self.root)

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.db_path, timeout=10)
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value)")
        db.execute("CREATE TABLE IF NOT EXISTS files(path TEXT PRIMARY KEY, mtime INTEGER, size INTEGER)")
        db.execute("CREATE TABLE IF NOT EXISTS chunks(path TEXT, idx INTEGER, text TEXT, vec BLOB,"
                   " PRIMARY KEY(path, idx))")
        return db

    def pending_files(self, extensions: set[str] | None = None) -> list[Path]:
        """Changed or new files since the last indexed state (mtime/size based)."""
        from harness.file_index import project_files
        from harness.tools.search import TEXT_EXTENSIONS
        extensions = extensions or TEXT_EXTENSIONS
        with _lock_for(self.db_path), closing(self._connect()) as db:
            known = {row[0]: (row[1], row[2]) for row in db.execute("SELECT path, mtime, size FROM files")}
        pending = []
        for path in project_files(self.root):
            if path.suffix.lower() not in extensions:
                continue
            try:
                stat = path.stat()
            except OSError:
                continue  # Vanished between the cached walk and now.
            if stat.st_size > MAX_FILE_BYTES:
                continue
            rel = str(path.relative_to(self.root))
            if known.get(rel) != (stat.st_mtime_ns, stat.st_size):
                pending.append(path)
        return pending

    def update(self, max_files: int = UPDATE_BATCH_FILES) -> int:
        """Embed and store up to max_files pending files; returns files indexed."""
        from harness.embedding_server import embed_texts
        from harness.file_index import project_files
        pending = self.pending_files()
        with _lock_for(self.db_path), closing(self._connect()) as db, db:
            if not pending:
                # Deletions must be pruned even when nothing else changed.
                seen = {str(p.relative_to(self.root)) for p in project_files(self.root)}
                for gone in {row[0] for row in db.execute("SELECT path FROM files")} - seen:
                    db.execute("DELETE FROM files WHERE path = ?", (gone,))
                    db.execute("DELETE FROM chunks WHERE path = ?", (gone,))
                _set_meta(db, "updated", time.time())
                return 0
        batch = pending[:max_files]
        chunk_rows: list[tuple[str, int, str]] = []
        for path in batch:
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                text = ""
            if "\x00" in text:
                text = ""
            rel = str(path.relative_to(self.root))
            for idx, chunk in enumerate(chunk_text(text)):
                chunk_rows.append((rel, idx, chunk))
        vectors = embed_texts(self.cfg, [row[2] or " " for row in chunk_rows])
        with _lock_for(self.db_path), closing(self._connect()) as db, db:
            for path in batch:
                rel = str(path.relative_to(self.root))
                stat = path.stat()
                db.execute("DELETE FROM chunks WHERE path = ?", (rel,))
                db.execute("INSERT OR REPLACE INTO files(path, mtime, size) VALUES (?, ?, ?)",
                           (rel, stat.st_mtime_ns, stat.st_size))
            for (rel, idx, text), vec in zip(chunk_rows, vectors):
                db.execute("INSERT OR REPLACE INTO chunks(path, idx, text, vec) VALUES (?, ?, ?, ?)",
                           (rel, idx, text, vec.astype("float16").tobytes()))
            seen = {str(p.relative_to(self.root)) for p in project_files(self.root)}
            for gone in {row[0] for row in db.execute("SELECT path FROM files")} - seen:
                db.execute("DELETE FROM files WHERE path = ?", (gone,))
                db.execute("DELETE FROM chunks WHERE path = ?", (gone,))
            _set_meta(db, "updated", time.time())
        return len(batch)

    def progress(self) -> dict:
        pending = self.pending_files()
        with _lock_for(self.db_path), closing(self._connect()) as db:
            done = db.execute("SELECT COUNT(*) FROM files").fetchone()[0]
        return {"done": done, "pending": len(pending), "total": done + len(pending)}

    def search(self, query_vec, limit: int) -> list[dict]:
        import numpy as np
        with _lock_for(self.db_path), closing(self._connect()) as db:
            rows = db.execute("SELECT path, idx, text, vec FROM chunks").fetchall()
        if not rows:
            return []
        matrix = np.frombuffer(b"".join(row[3] for row in rows), dtype="float16").astype("float32")
        matrix = matrix.reshape(len(rows), -1)
        scores = matrix @ query_vec.astype("float32")
        order = np.argsort(-scores)[:limit]
        return [{"path": rows[i][0], "chunk": rows[i][1], "text": rows[i][2],
                 "score": float(scores[i])} for i in order if scores[i] > 0.05]


class SemanticHistoryIndex:
    """Vector index over user/assistant messages of all saved sessions."""

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.db_path = cfg.path("paths.sessions_dir") / "semantic-index.sqlite3"

    def _connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.db_path, timeout=10)
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value)")
        db.execute("CREATE TABLE IF NOT EXISTS sessions(session_id TEXT PRIMARY KEY,"
                   " indexed_mtime REAL, indexed_count INTEGER)")
        db.execute("CREATE TABLE IF NOT EXISTS chunks(session_id TEXT, idx INTEGER, role TEXT,"
                   " text TEXT, vec BLOB, PRIMARY KEY(session_id, idx))")
        return db

    def _session_rows(self, sid: str) -> list[tuple[str, str]]:
        messages_file = self.cfg.path("paths.sessions_dir") / sid / "messages.jsonl"
        rows: list[tuple[str, str]] = []
        try:
            with messages_file.open(encoding="utf-8") as stream:
                for line in stream:
                    try:
                        message = json.loads(line)
                    except ValueError:
                        continue
                    role, content = message.get("role"), message.get("content") or ""
                    if role not in ("user", "assistant") or not content:
                        continue
                    if content.startswith(_INTERNAL_PREFIXES):
                        continue
                    rows.append((role, content))
        except OSError:
            pass
        return rows

    def update(self, max_sessions: int = 4) -> int:
        """Embed changed sessions; returns the number of sessions refreshed."""
        from harness.embedding_server import embed_texts
        sessions_dir = self.cfg.path("paths.sessions_dir")
        with _lock_for(self.db_path), closing(self._connect()) as db:
            known = {row[0]: (row[1], row[2]) for row in
                     db.execute("SELECT session_id, indexed_mtime, indexed_count FROM sessions")}
        changed = []
        for messages_file in sorted(sessions_dir.glob("*/messages.jsonl")):
            sid = messages_file.parent.name
            mtime = messages_file.stat().st_mtime
            if known.get(sid) and known[sid][0] >= mtime:
                continue
            changed.append((sid, mtime))
            if len(changed) >= max_sessions:
                break
        if not changed:
            return 0
        chunk_rows: list[tuple[str, int, str, str]] = []
        for sid, _ in changed:
            for idx, (role, content) in enumerate(self._session_rows(sid)):
                for piece_idx, piece in enumerate(chunk_text(content, HISTORY_MESSAGE_CAP, 200)):
                    chunk_rows.append((sid, idx * 100 + piece_idx, role, piece))
        vectors = embed_texts(self.cfg, [row[3] or " " for row in chunk_rows])
        with _lock_for(self.db_path), closing(self._connect()) as db, db:
            for sid, _ in changed:
                db.execute("DELETE FROM chunks WHERE session_id = ?", (sid,))
            for (sid, idx, role, text), vec in zip(chunk_rows, vectors):
                db.execute("INSERT OR REPLACE INTO chunks(session_id, idx, role, text, vec)"
                           " VALUES (?, ?, ?, ?, ?)", (sid, idx, role, text, vec.astype("float16").tobytes()))
            for sid, mtime in changed:
                count = db.execute("SELECT COUNT(*) FROM chunks WHERE session_id = ?", (sid,)).fetchone()[0]
                db.execute("INSERT OR REPLACE INTO sessions(session_id, indexed_mtime, indexed_count)"
                           " VALUES (?, ?, ?)", (sid, mtime, count))
            live = {p.parent.name for p in sessions_dir.glob("*/messages.jsonl")}
            for gone in {row[0] for row in db.execute("SELECT session_id FROM sessions")} - live:
                db.execute("DELETE FROM sessions WHERE session_id = ?", (gone,))
                db.execute("DELETE FROM chunks WHERE session_id = ?", (gone,))
            _set_meta(db, "updated", time.time())
        return len(changed)

    def pending_sessions(self) -> int:
        sessions_dir = self.cfg.path("paths.sessions_dir")
        with _lock_for(self.db_path), closing(self._connect()) as db:
            known = {row[0]: row[1] for row in db.execute("SELECT session_id, indexed_mtime FROM sessions")}
        count = 0
        for messages_file in sessions_dir.glob("*/messages.jsonl"):
            if not known.get(messages_file.parent.name, 0) >= messages_file.stat().st_mtime:
                count += 1
        return count

    def search(self, query_vec, limit: int) -> list[dict]:
        import numpy as np
        with _lock_for(self.db_path), closing(self._connect()) as db:
            rows = db.execute("SELECT session_id, role, text, vec FROM chunks").fetchall()
        if not rows:
            return []
        matrix = np.frombuffer(b"".join(row[3] for row in rows), dtype="float16").astype("float32")
        matrix = matrix.reshape(len(rows), -1)
        scores = matrix @ query_vec.astype("float32")
        order = np.argsort(-scores)[: limit * 3]
        hits, seen = [], set()
        for i in order:
            sid = rows[i][0]
            if sid in seen or scores[i] <= 0.05:
                continue
            seen.add(sid)
            hits.append({"session_id": sid, "role": rows[i][1], "text": rows[i][2],
                         "score": float(scores[i])})
            if len(hits) >= limit:
                break
        return hits


# ---- background worker ------------------------------------------------------

_tasks: list[tuple] = []          # ("files", cfg, root) or ("history", cfg)
_tasks_lock = threading.Lock()
_worker: threading.Thread | None = None


def request_files_indexing(cfg: Config, root: Path) -> None:
    with _tasks_lock:
        if any(t[0] == "files" and t[1] is cfg and str(t[2]) == str(root) for t in _tasks):
            return
        _tasks.append(("files", cfg, Path(root)))
    _ensure_worker()


def request_history_indexing(cfg: Config) -> None:
    with _tasks_lock:
        if not any(t[0] == "history" and t[1] is cfg for t in _tasks):
            _tasks.append(("history", cfg))
    _ensure_worker()


def _ensure_worker() -> None:
    global _worker
    with _tasks_lock:
        if _worker is not None and _worker.is_alive():
            return
        _worker = threading.Thread(target=_worker_loop, name="semantic-indexer", daemon=True)
        _worker.start()


def _worker_loop() -> None:
    from harness.embedding_server import embed_texts  # noqa: F401  (fail fast if missing)
    while True:
        with _tasks_lock:
            task = _tasks.pop(0) if _tasks else None
        if task is None:
            return
        kind, cfg = task[0], task[1]
        try:
            if kind == "files":
                index = SemanticFileIndex(cfg, task[2])
                while index.update():
                    pass
            else:
                index = SemanticHistoryIndex(cfg)
                while index.update():
                    pass
        except Exception:
            # The sidecar or the model is unavailable; the tool reports the state.
            with _tasks_lock:
                _tasks.clear()
            return
