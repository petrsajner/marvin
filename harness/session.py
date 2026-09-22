"""Conversation persistence: JSONL messages and session-local images.

Stored messages reference image files. API messages are rendered in OpenAI-compatible format with base64 data URLs."""
from __future__ import annotations

import base64
import copy
import json
import mimetypes
import shutil
import sqlite3
import time
import uuid
from functools import lru_cache
from pathlib import Path
from typing import Any

from harness.config import Config
from harness.i18n import t
from harness.internal_messages import INTERNAL_USER_PREFIXES as _INTERNAL_USER_PREFIXES
from harness.jsonl import dump_record, history_lock, physical_lines, read_history

IMG_MIMES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif", ".webp": "image/webp", ".bmp": "image/bmp"}


class Session:
    def __init__(self, cfg: Config, session_id: str | None = None, system_prompt: str | None = None,
                 workspace: str | None = None, transient: bool = False,
                 work_mode: str | None = None):
        self.cfg = cfg
        self.id = session_id or time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
        self.dir = cfg.path("paths.sessions_dir") / self.id
        self.img_dir = self.dir / "images"
        self.messages: list[dict[str, Any]] = []
        # Compression changes the model view to system prompt, summary and recent messages.
        # The UI and JSONL retain the complete message history.
        self.compression: dict[str, Any] | None = None  # {"cut": int, "summary": str}
        self.compression_rev = 0  # Increment after each compression change for the UI marker.
        self.meta: dict[str, Any] = {"workspace": workspace, "title": None,
                                     "created": time.time(), "updated": time.time(),
                                     "pinned_files": [], "work_mode": work_mode}
        # A transient chat exists only in memory until its first real user message.
        # persist() writes it then, avoiding empty conversation directories.
        self.transient = transient
        if system_prompt:
            self.add("system", system_prompt)

    # Message insertion.
    def add(self, role: str, content: Any, *, images: list[Path] | None = None,
            tool_calls: list[dict] | None = None, tool_call_id: str | None = None,
            name: str | None = None, reasoning: str | None = None,
            changes: list[dict] | None = None,
            checks: list[dict] | None = None) -> dict:
        msg: dict[str, Any] = {"role": role, "content": content,
                                "id": uuid.uuid4().hex, "created": time.time()}
        for key in ("run_id", "step_id", "request_id"):
            if getattr(self, key, None) is not None:
                msg[key] = getattr(self, key)
        if role == "tool":
            msg["tool_status"] = getattr(content, "status", "completed")
            if msg["tool_status"] == "error":
                from harness.failures import advise
                hint = advise(str(content))
                if hint:
                    msg["hint"] = hint
        if reasoning:
            msg["reasoning"] = str(reasoning)
        if tool_calls:
            msg["tool_calls"] = tool_calls
        if tool_call_id:
            msg["tool_call_id"] = tool_call_id
        if name:
            msg["name"] = name
        if changes:
            # Per-file plain-language summary of a finished task's file edits.
            msg["changes"] = list(changes)
        if checks:
            # Rows of a test-and-fix report: what was checked and how it went.
            msg["checks"] = list(checks)
        if self.transient and role == "user":
            self.persist()  # Persist the conversation when its first real message arrives.
        if images:
            msg["images"] = [str(self._store_image(p)) for p in images]
        self.messages.append(msg)
        self._append_jsonl(msg)
        # Update the title from the first user message and refresh the timestamp.
        if role == "user" and not self.meta.get("title") and isinstance(content, str) \
                and content.strip() and not content.startswith("["):
            self.meta["title"] = content.strip().replace("\n", " ")[:70]
        self.meta["updated"] = time.time()
        self.meta["message_count"] = len(self.messages)
        self._save_meta()
        observer = getattr(self, "on_message", None)
        if observer:
            observer(msg)
        return msg

    def _store_image(self, path: Path) -> Path:
        """Copy an image into the session directory and return its new path."""
        if self.transient:
            self.persist()
        self.img_dir.mkdir(parents=True, exist_ok=True)
        if self.dir.resolve() in path.resolve().parents:
            return path  # The image is already in the session, for example a screenshot.
        dest = self.img_dir / f"{uuid.uuid4().hex[:8]}-{path.name}"
        shutil.copy2(path, dest)
        return dest

    # -- render for the API ----------------------------------------------------
    SUMMARY_PREFIX = ("[SESSION HISTORY SUMMARY - older conversation was auto-compressed. "
                      "Use it as context, do not re-ask the user about these facts:]\n\n")
    # Kept as a class attribute for existing callers; the list itself lives in
    # harness.internal_messages so every filter shares one definition.
    INTERNAL_USER_PREFIXES = _INTERNAL_USER_PREFIXES

    def _view_messages(self) -> list[dict]:
        """Return the model-visible message view after applying compression."""
        if not self.compression:
            return self.messages
        cut = min(self.compression["cut"], len(self.messages))
        head = self.messages[:1] if self.messages and self.messages[0]["role"] == "system" else []
        summary_msg = {"role": "user", "content": self.SUMMARY_PREFIX + self.compression["summary"]}
        return head + [summary_msg] + self.messages[cut:]

    # A message whose images were given up under context pressure. The flag is
    # persisted because the set of images the model sees must not depend on how
    # many arrived afterwards: silently dropping an image from a message the
    # server has already processed changes the prompt prefix and costs a full
    # reprocess of the conversation. See prune_images.
    HIDDEN_IMAGES_KEY = "images_hidden"

    def _sent_images(self, message: dict) -> list[str]:
        if message.get(self.HIDDEN_IMAGES_KEY):
            return []
        return list(message.get("images") or [])

    def to_api_messages(self, include_pins: bool = True) -> list[dict]:
        """Render API messages, keeping every image that has not been pruned."""
        view = self._view_messages()
        out: list[dict] = []
        for m in view:
            m2 = {k: v for k, v in m.items() if k not in
                  ("images", self.HIDDEN_IMAGES_KEY, "id", "created", "attachments",
                   "request_id", "run_id", "step_id", "tool_status")}
            if "reasoning" in m2:
                reasoning_val = m2.pop("reasoning", None)
                if reasoning_val and "reasoning_content" not in m2:
                    m2["reasoning_content"] = reasoning_val
            imgs = self._sent_images(m)
            if not imgs:
                if not m2.get("content") and not m2.get("tool_calls"):
                    continue
                out.append(m2)
                continue
            parts: list[dict] = []
            if m2.get("content"):
                parts.append({"type": "text", "text": str(m2["content"])})
            else:
                parts.append({"type": "text", "text": "[image]"})
            for p in imgs:
                parts.append({"type": "image_url", "image_url": {"url": self._data_url(p)}})
            m2["content"] = parts
            out.append(m2)
        pinned = self.pinned_context_block() if include_pins else ""
        if pinned:
            out.append({"role": "user", "content": pinned})
        return out

    @staticmethod
    def _data_url(path: str | Path) -> str:
        path = Path(path)
        stat = path.stat()
        return Session._cached_data_url(str(path), stat.st_mtime_ns, stat.st_size)

    @staticmethod
    @lru_cache(maxsize=16)
    def _cached_data_url(path_str: str, _mtime_ns: int, _size: int) -> str:
        path = Path(path_str)
        mime = IMG_MIMES.get(path.suffix.lower(), "image/png")
        b64 = base64.b64encode(path.read_bytes()).decode()
        return f"data:{mime};base64,{b64}"

    # -- context estimate / compression -----------------------------------------
    #
    # These two constants were measured against what the server actually
    # tokenised, not assumed. An image-free conversation of 287,114 characters
    # was 89,670 prompt tokens - 3.20 characters per token, not the 3.6 assumed
    # before, because Czech prose and JSON tool output both tokenise worse than
    # English. Given that ratio, a conversation carrying seven screenshots left
    # 18,087 tokens unaccounted for: 2,583 per picture, not 1,400.
    #
    # Both errors ran the same way, so the harness believed the context was
    # emptier than it was - by 17% in one measured session and 11% in another.
    # That is why the figure beside the composer disagreed with the one the
    # server reported while reading the prompt: one was measured, one was not.
    IMAGE_TOKENS = 2600      # Measured cost of one downscaled screenshot.
    CHARS_PER_TOKEN = 3.2    # Measured on Czech prose, Python and JSON mixed.
    SCALE_KEY = "token_scale"

    @classmethod
    def tokens_for(cls, chars: int, images: int = 0, scale: float = 1.0) -> int:
        """The one place characters and pictures become a token count."""
        return int((chars / cls.CHARS_PER_TOKEN + images * cls.IMAGE_TOKENS) * scale)

    def token_scale(self) -> float:
        """The correction this conversation has learned from the server."""
        try:
            value = float(self.meta.get(self.SCALE_KEY) or 1.0)
        except (TypeError, ValueError):
            return 1.0
        return value if 0.5 <= value <= 2.0 else 1.0

    def calibrate_tokens(self, prompt_tokens: int, raw_estimate: int) -> float:
        """Learn the real ratio from a request the server has counted for us.

        Constants cannot know whether a conversation is Czech prose, Python or
        screenshots, and the mix changes as the work does. The server reports the
        exact prompt length with every response, so the estimate does not have to
        keep guessing: it is corrected towards what was actually measured, gently
        enough that one odd request cannot swing it."""
        if prompt_tokens <= 0 or raw_estimate <= 0:
            return self.token_scale()
        observed = prompt_tokens / raw_estimate
        if not 0.5 <= observed <= 2.0:
            return self.token_scale()      # A truncated or retried request teaches nothing.
        scale = round(self.token_scale() + (observed - self.token_scale()) * 0.3, 4)
        self.meta[self.SCALE_KEY] = scale
        self._save_meta()
        return scale

    def estimate_context_tokens(self, include_pins: bool = True) -> int:
        """Estimate the actual API input, counting only images still being sent."""
        import json as _json
        view = self._view_messages()
        total = 0
        images = 0
        for m in view:
            c = m.get("content") or ""
            if isinstance(c, str):
                total += len(c)
            elif isinstance(c, list):
                for part in c:
                    if isinstance(part, dict):
                        if part.get("type") == "text":
                            total += len(str(part.get("text", "")))
                        elif part.get("type") == "image_url":
                            images += 1
            images += len(self._sent_images(m))
            if m.get("tool_calls"):
                total += len(_json.dumps(m["tool_calls"], ensure_ascii=False))
            total += len(str(m.get("reasoning") or m.get("reasoning_content") or ""))
        if include_pins:
            total += len(self.pinned_context_block())
        return self.tokens_for(total, images, self.token_scale())

    def pin_context_file(self, path: Path) -> bool:
        resolved = str(path.resolve())
        pins = list(self.meta.get("pinned_files") or [])
        if resolved in pins:
            return False
        pins.append(resolved)
        self.meta["pinned_files"] = pins[-10:]
        self._save_meta()
        return True

    def unpin_context_file(self, path: Path | str) -> bool:
        resolved = str(Path(path).resolve())
        target_name = Path(path).name
        pins = list(self.meta.get("pinned_files") or [])
        match = None
        for p in pins:
            if p == resolved or p == str(path) or Path(p).name == target_name:
                match = p
                break
        if not match:
            return False
        pins.remove(match)
        self.meta["pinned_files"] = pins
        self._save_meta()
        return True

    def pinned_context_block(self, max_chars: int = 40_000) -> str:
        parts: list[str] = []
        used = 0
        for raw in self.meta.get("pinned_files") or []:
            path = Path(raw)
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            room = max_chars - used
            if room <= 0:
                break
            text = text[:room]
            parts.append(f"### {path}\n{text}")
            used += len(text)
        if not parts:
            return ""
        return "[PINNED PROJECT FILES - user-selected persistent context]\n\n" + "\n\n".join(parts)

    def context_breakdown(self) -> dict:
        import collections as _collections
        view = self._view_messages()
        counts = _collections.Counter(m.get("role", "other") for m in view)
        images = sum(len(m.get("images", [])) for m in view)
        images_sent = sum(len(self._sent_images(m)) for m in view)
        pins = [raw for raw in self.meta.get("pinned_files") or [] if Path(raw).is_file()]
        return {
            "estimated_tokens": self.estimate_context_tokens(),
            "visible_messages": len(view),
            "total_messages": len(self.messages),
            "roles": dict(counts),
            "images": images,
            "images_sent": images_sent,
            "pinned_files": pins,
            "compressed": bool(self.compression),
        }

    def _msg_tokens(self, m: dict) -> int:
        """Estimate one message's token cost, including images and tool calls."""
        import json as _json
        c = m.get("content") or ""
        if not isinstance(c, str):
            c = " ".join(str(p.get("text", "")) for p in c if isinstance(p, dict))
        chars = len(str(c)) + len(str(m.get("reasoning") or m.get("reasoning_content") or ""))
        if m.get("tool_calls"):
            chars += len(_json.dumps(m["tool_calls"], ensure_ascii=False))
        return self.tokens_for(chars, len(self._sent_images(m)), self.token_scale())

    @classmethod
    def _is_user_boundary(cls, message: dict) -> bool:
        content = message.get("content")
        return (message.get("role") == "user" and isinstance(content, str)
                and not content.startswith(cls.INTERNAL_USER_PREFIXES))

    def compression_cut(self, min_keep: int = 6,
                        keep_tokens: int | None = None) -> int | None:
        """Find a user-message boundary for the retained recent conversation segment."""
        msgs = self.messages
        head_len = 1 if msgs and msgs[0]["role"] == "system" else 0
        if len(msgs) - head_len <= min_keep:
            return None
        cut = None
        if keep_tokens is not None:
            acc = 0
            for i in range(len(msgs) - 1, head_len - 1, -1):
                acc += self._msg_tokens(msgs[i])
                if acc > keep_tokens:
                    break
                if self._is_user_boundary(msgs[i]) and (len(msgs) - i) >= min_keep:
                    cut = i
        else:
            rest = msgs[head_len:]
            for i in range(len(rest) - min_keep, 0, -1):
                if self._is_user_boundary(rest[i]):
                    cut = head_len + i
                    break
        if cut is None or cut <= head_len:
            return None
        if self.compression and cut <= self.compression["cut"]:
            return None
        return cut

    def compress_to_summary(self, summary: str, min_keep: int = 6,
                            keep_tokens: int | None = None,
                            cut: int | None = None) -> bool:
        """Record a compression boundary without deleting history.

        All messages remain in memory and JSONL. The model sees the system prompt, a summary and messages after the cut. Cuts use user-message boundaries to preserve assistant tool-call/result pairs.

        keep_tokens limits the retained segment; otherwise only min_keep applies."""
        cut = cut if cut is not None else self.compression_cut(min_keep, keep_tokens)
        if cut is None:
            return False  # The new cut must advance beyond the previous one.
        self.compression = {"cut": cut, "summary": summary}
        self.compression_rev += 1
        self._save_compression()
        return True

    def prunable_images(self, keep: int = 4) -> tuple[int, int]:
        """How many images pruning would drop, and roughly what that frees.

        Asked before pruning, because the rewrite costs the server every token
        after the first dropped image: giving up one picture to save a couple of
        thousand tokens is a minute of reprocessing for nothing."""
        carrying = [m for m in self._view_messages() if self._sent_images(m)]
        kept = 0
        dropped = 0
        for message in reversed(carrying):
            count = len(self._sent_images(message))
            if kept < keep:
                kept += count
                continue
            dropped += count
        return dropped, self.tokens_for(0, dropped, self.token_scale())

    def prune_images(self, keep: int = 4) -> int:
        """Give up all but the newest `keep` images and return how many were dropped.

        This is the one place allowed to change history the model has already
        seen, because images are by far the largest items in a computer-use
        conversation and the cheapest to lose. It runs only under context
        pressure - never as a side effect of taking another screenshot - so the
        conversation costs one reprocess instead of one per step."""
        carrying = [m for m in self._view_messages() if self._sent_images(m)]
        kept = 0
        dropped = 0
        for message in reversed(carrying):
            if kept < keep:
                kept += len(self._sent_images(message))
                continue
            dropped += len(self._sent_images(message))
            message[self.HIDDEN_IMAGES_KEY] = True
        if dropped:
            self._rewrite_jsonl()
        return dropped

    def trim_to_budget(self, budget_tokens: int, min_keep: int = 6) -> bool:
        """Fallback: advance the model-view cut while retaining full history for the UI."""
        changed = False
        while self.estimate_context_tokens() > budget_tokens and len(self.messages) > min_keep + 1:
            cur = self.compression["cut"] if self.compression else 1
            # Find the next user-message boundary after the current cut.
            nxt = next((i for i in range(cur + 1, len(self.messages) - min_keep + 1)
                        if self._is_user_boundary(self.messages[i])), None)
            if nxt is None:
                break
            self.compression = {
                "cut": nxt,
                "summary": (self.compression["summary"] if self.compression
                            else "(older context hard-trimmed without summary)"),
            }
            changed = True
        if changed:
            self.compression_rev += 1
            self._save_compression()
        return self.estimate_context_tokens() <= budget_tokens

    # -- persistence ---------------------------------------------------------
    @property
    def _jsonl(self) -> Path:
        return self.dir / "messages.jsonl"

    def persist(self) -> None:
        """Write the complete transient conversation and leave transient mode."""
        if not self.transient:
            return
        self.transient = False
        self.dir.mkdir(parents=True, exist_ok=True)
        self._save_meta()
        with history_lock(self._jsonl), open(self._jsonl, "w", encoding="utf-8") as f:
            for m in self.messages:
                f.write(dump_record(m) + "\n")

    def _append_jsonl(self, msg: dict) -> None:
        if self.transient:
            return
        self.dir.mkdir(parents=True, exist_ok=True)
        with history_lock(self._jsonl), open(self._jsonl, "a", encoding="utf-8") as f:
            f.write(dump_record(msg) + "\n")

    def _rewrite_jsonl(self) -> None:
        """Rewrite the complete JSONL file after history repair."""
        self.dir.mkdir(parents=True, exist_ok=True)
        tmp = self._jsonl.with_suffix(".tmp")
        with history_lock(self._jsonl):
            with open(tmp, "w", encoding="utf-8") as f:
                for m in self.messages:
                    f.write(dump_record(m) + "\n")
            tmp.replace(self._jsonl)
        self._update_history_index()

    def last_user_index(self) -> int | None:
        for index in range(len(self.messages) - 1, -1, -1):
            message = self.messages[index]
            content = message.get("content")
            if message.get("role") == "user" and isinstance(content, str) \
                    and not content.startswith(self.INTERNAL_USER_PREFIXES):
                return index
        return None

    def rewind_last_turn(self, keep_user: bool) -> str | None:
        index = self.last_user_index()
        if index is None:
            return None
        content = str(self.messages[index].get("content") or "")
        self.messages = self.messages[:index + 1 if keep_user else index]
        self._clear_compression()
        self.meta["message_count"] = len(self.messages)
        self.meta["updated"] = time.time()
        self._rewrite_jsonl()
        self._save_meta()
        return content

    def fork_at_last_user(self, system_prompt: str) -> "Session" | None:
        index = self.last_user_index()
        if index is None:
            return None
        fork = Session(self.cfg, system_prompt=system_prompt,
                       workspace=self.meta.get("workspace"), transient=False,
                       work_mode=self.meta.get("work_mode"))
        copied: list[dict] = [fork.messages[0]] if fork.messages else []
        first = 1 if self.messages and self.messages[0].get("role") == "system" else 0
        for original in self.messages[first:index + 1]:
            message = copy.deepcopy(original)
            if message.get("images"):
                new_images: list[str] = []
                for raw in message["images"]:
                    try:
                        new_images.append(str(fork._store_image(Path(raw))))
                    except OSError:
                        continue
                message["images"] = new_images
            copied.append(message)
        fork.messages = copied
        title = self.meta.get("title") or t("New branch")
        fork.meta.update({
            "title": f"{title} {t('(fork)')}"[:100],
            "message_count": len(copied),
            "pinned_files": list(self.meta.get("pinned_files") or []),
            "updated": time.time(),
        })
        fork._rewrite_jsonl()
        fork._save_meta()
        return fork

    def export_markdown(self) -> Path:
        export_dir = self.dir / "exports"
        export_dir.mkdir(parents=True, exist_ok=True)
        target = export_dir / f"{self.id}.md"
        lines = [f"# {self.meta.get('title') or 'Marvin chat'}", ""]
        role_names = {"user": "User", "assistant": "Assistant", "tool": "Tool"}
        for message in self.messages:
            role = message.get("role")
            content = message.get("content")
            if role == "system" or (role == "user" and isinstance(content, str)
                                    and content.startswith(self.INTERNAL_USER_PREFIXES)):
                continue
            if not content and message.get("tool_calls"):
                names = ", ".join(call.get("function", {}).get("name", "tool")
                                  for call in message["tool_calls"])
                content = f"Tool calls: {names}"
            lines.extend([f"## {role_names.get(role, str(role))}", "", str(content or ""), ""])
            for image in message.get("images", []):
                lines.append(f"Attachment: `{Path(image).name}`\n")
        atomic = "\n".join(lines)
        target.write_text(atomic, encoding="utf-8", newline="\n")
        return target

    def export_jsonl(self) -> Path:
        export_dir = self.dir / "exports"
        export_dir.mkdir(parents=True, exist_ok=True)
        target = export_dir / f"{self.id}.jsonl"
        with open(target, "w", encoding="utf-8") as handle:
            for message in self.messages:
                handle.write(dump_record(message) + "\n")
        return target

    def _clear_compression(self) -> None:
        if self.compression is not None:
            self.compression = None
            self.compression_rev += 1
        self._compression_file.unlink(missing_ok=True)

    @property
    def _task_state_file(self) -> Path:
        return self.dir / "task-state.json"

    def save_task_state(self, state: dict) -> None:
        if self.transient:
            return
        state = {**state, "updated": time.time()}
        temporary = self._task_state_file.with_suffix(".tmp")
        temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(self._task_state_file)

    def load_task_state(self) -> dict:
        try:
            state = json.loads(self._task_state_file.read_text(encoding="utf-8"))
            return state if isinstance(state, dict) else {}
        except (OSError, ValueError):
            return {}

    @property
    def _compression_file(self) -> Path:
        return self.dir / "compression.json"

    @property
    def _meta_file(self) -> Path:
        return self.dir / "meta.json"

    def _save_meta(self) -> None:
        if self.transient:
            return
        try:
            self.dir.mkdir(parents=True, exist_ok=True)
            from harness.changes import atomic_write_text
            atomic_write_text(self._meta_file, json.dumps(self.meta, ensure_ascii=False))
        except OSError:
            pass
        self._update_history_index(incremental=True)

    def _update_history_index(self, incremental: bool = False) -> None:
        if self.transient or not self._jsonl.exists():
            return
        try:
            from harness.history_index import HistoryIndex
            HistoryIndex(self.cfg.path("paths.sessions_dir")).reindex(
                self.id, self.meta, self.messages, source_mtime=self._jsonl.stat().st_mtime,
                incremental=incremental)
        except (OSError, ValueError, sqlite3.Error):
            pass

    def _load_meta(self) -> None:
        try:
            self.meta = json.loads(self._meta_file.read_text(encoding="utf-8"))
            self.meta.setdefault("workspace", None)
            self.meta.setdefault("title", None)
            self.meta.setdefault("pinned_files", [])
            self.meta.setdefault("work_mode", None)
        except (OSError, ValueError):
            pass

    def _save_compression(self) -> None:
        if self.compression:
            self.dir.mkdir(parents=True, exist_ok=True)
            from harness.changes import atomic_write_text
            atomic_write_text(self._compression_file, json.dumps(self.compression, ensure_ascii=False))

    def _load_compression(self) -> None:
        try:
            data = json.loads(self._compression_file.read_text(encoding="utf-8"))
            if isinstance(data, dict) and "cut" in data and "summary" in data:
                self.compression = data
                self.compression_rev += 1
        except (OSError, ValueError):
            pass

    @classmethod
    def load(cls, cfg: Config, session_id: str, system_prompt: str | None = None) -> "Session":
        base = cfg.path("paths.sessions_dir").resolve()
        if (base / session_id).resolve().parent != base:
            raise ValueError("Invalid conversation identifier")
        s = cls(cfg, session_id=session_id)
        f = s._jsonl
        if not f.exists():
            raise FileNotFoundError(f"Session {session_id} not found ({f})")
        s.messages = []
        records = read_history(f, cfg.path("paths.runtime_dir") / "application.sqlite3")
        for index, message in enumerate(records):
            message.setdefault("id", f"{s.id}:{index}")
            s.messages.append(message)
        s._load_meta()
        # Derive a title for older sessions without metadata.
        if not s.meta.get("title"):
            for m in s.messages:
                if m["role"] == "user" and isinstance(m.get("content"), str) \
                        and m["content"].strip() and not m["content"].startswith("["):
                    s.meta["title"] = m["content"].strip().replace("\n", " ")[:70]
                    break
        s._load_compression()
        if system_prompt:
            if s.messages and s.messages[0]["role"] == "system":
                s.messages[0]["content"] = system_prompt
            else:
                s.messages.insert(0, {"role": "system", "content": system_prompt})
        return s

    @classmethod
    def import_jsonl(cls, cfg: Config, source: Path, system_prompt: str,
                     workspace: str | None = None,
                     work_mode: str | None = None) -> "Session":
        messages: list[dict] = []
        for number, line in enumerate(physical_lines(source.read_text(encoding="utf-8")), 1):
            if not line.strip():
                continue
            try:
                message = json.loads(line)
            except ValueError as exc:
                raise ValueError(f"Invalid JSONL on line {number}: {exc}") from exc
            if not isinstance(message, dict) or message.get("role") not in {
                    "system", "user", "assistant", "tool"}:
                raise ValueError(f"Invalid message on line {number}")
            if message.get("images"):
                message["images"] = [raw for raw in message["images"] if Path(raw).is_file()]
            messages.append(message)
        if not messages:
            raise ValueError("The imported conversation contains no messages")
        if messages[0].get("role") == "system":
            messages[0]["content"] = system_prompt
        else:
            messages.insert(0, {"role": "system", "content": system_prompt})
        session = cls(cfg, system_prompt=system_prompt, workspace=workspace,
                      work_mode=work_mode)
        session.messages = messages
        session.meta["message_count"] = len(messages)
        session.meta["workspace"] = workspace
        session.meta["work_mode"] = work_mode
        session.meta["title"] = next(
            (str(message.get("content", ""))[:70] for message in messages
             if message.get("role") == "user"
             and not str(message.get("content", "")).startswith(cls.INTERNAL_USER_PREFIXES)),
            "Imported conversation",
        )
        session.meta["updated"] = time.time()
        session._rewrite_jsonl()
        session._save_meta()
        return session

    @classmethod
    def delete(cls, cfg: Config, session_id: str) -> bool:
        """Remove a session directory and its images; return True on success."""
        import shutil
        d = cfg.path("paths.sessions_dir") / session_id
        if d.exists() and d.is_dir():
            shutil.rmtree(d, ignore_errors=True)
            try:
                from harness.history_index import HistoryIndex
                HistoryIndex(cfg.path("paths.sessions_dir")).remove(session_id)
            except Exception:
                pass
            return True
        return False

    def adopt_workspace(self, workspace: str | None) -> None:
        """Assign a project workspace to a session that has none.

        Older sessions without metadata can inherit the currently selected project and appear in its history."""
        if workspace and not self.meta.get("workspace"):
            self.meta["workspace"] = workspace
            self._save_meta()

    @staticmethod
    def list_sessions(cfg: Config, limit: int = 60) -> list[dict]:
        """List sessions with workspace, title and timestamps, newest first."""
        base = cfg.path("paths.sessions_dir")
        if not base.exists():
            return []
        out: list[dict] = []
        for d in base.iterdir():
            if not (d.is_dir() and (d / "messages.jsonl").exists()):
                continue
            meta: dict = {}
            try:
                meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
            except (OSError, ValueError):
                pass
            try:
                n = int(meta["message_count"])
            except (KeyError, TypeError, ValueError):
                n = sum(1 for _ in open(d / "messages.jsonl", encoding="utf-8"))
            title = meta.get("title")
            if not title:
                try:
                    for line in open(d / "messages.jsonl", encoding="utf-8"):
                        m = json.loads(line)
                        if m.get("role") == "user" and isinstance(m.get("content"), str) \
                                and m["content"].strip() and not m["content"].startswith("["):
                            title = m["content"].strip().replace("\n", " ")[:70]
                            break
                except (OSError, ValueError):
                    title = None
            out.append({
                "id": d.name,
                "messages": n,
                "workspace": meta.get("workspace"),
                "title": title or t("(untitled)"),
                "updated": float(meta.get("updated") or 0) or 0,
            })
        out.sort(key=lambda s: s["updated"], reverse=True)
        return out[:limit]

    @staticmethod
    def search_sessions(cfg: Config, query: str, limit: int = 30) -> list[dict]:
        query = (query or "").strip().lower()
        if not query:
            return []
        from harness.history_index import HistoryIndex
        return HistoryIndex(cfg.path("paths.sessions_dir")).search(query, limit)
