"""Handoff summaries stay prose and newly created chats stay newest.

Regression tests for the 2026-09-22 handoff bugs: the summarizer answered a
tool-less request with raw tool-call markup (which then got cached and became
the entire content of the continuation chat), and the goodbye note re-dated
the old chat after the new one existed, pushing the new chat to second place
in the list."""
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

from harness.context import looks_like_tool_call, summarize_messages
from harness.session import Session

# Assembled from fragments so this file never contains call markup literally.
TOOL_MARKUP = "".join(("<", "tool_call><", "function=fake><", "/function><",
                       "/tool_call>"))
GOOD_SUMMARY = (
    "## Goal\nCentipede sprites to match the 1981 arcade reference page.\n\n"
    "## Done\nRewrote centipede.py with sprite rendering [Message m1]; extracted "
    "frames from eight reference GIFs into research/sprites/; rebuilt "
    "dist/Centipede.exe with PyInstaller.\n\n"
    "## Decisions & context\nUse the reference sprites verbatim; keep the game "
    "rules unchanged.\n\n"
    "## Pending\nLive verification of the rebuilt exe; spider timing.\n\n"
    "## Key facts\npygame 2.6.1; project path projects/Centipede.")


class _Cfg:
    def __init__(self, root: Path):
        self._root = root
        self.data = {"work_mode": "computer"}

    def context_size(self):
        return 32768

    def path(self, dotted: str):
        return {"paths.runtime_dir": self._root / "runtime",
                "paths.sessions_dir": self._root / "sessions"}[dotted]

    def sampling(self, *_args, **_kwargs):
        return {}


class _LLM:
    """Returns prepared replies in order; counts calls and keeps the requests."""

    def __init__(self, root: Path, replies):
        self.cfg = _Cfg(root)
        self.replies = list(replies)
        self.calls = 0
        self.seen: list = []

    def stream(self, _messages, sampling=None, thinking=False, should_stop=None):
        self.calls += 1
        self.seen.append(_messages)
        return SimpleNamespace(stopped=False, content=self.replies.pop(0))


MESSAGES = [{"role": "user", "content": "make the sprites match the reference",
             "id": "m1"}]


class SummarizeTests(unittest.TestCase):
    def setUp(self):
        self._scratch = tempfile.TemporaryDirectory()
        self.root = Path(self._scratch.name)

    def tearDown(self):
        self._scratch.cleanup()

    def _cache_files(self):
        return list((self.root / "runtime" / "summary-cache").glob("*.md"))

    def test_tool_call_answer_is_retried_and_not_cached(self):
        llm = _LLM(self.root, [TOOL_MARKUP, GOOD_SUMMARY])
        self.assertEqual(summarize_messages(llm, MESSAGES), GOOD_SUMMARY)
        self.assertEqual(llm.calls, 2)
        cached = self._cache_files()
        self.assertEqual(len(cached), 1)
        self.assertEqual(cached[0].read_text(encoding="utf-8"), GOOD_SUMMARY)

    def test_persistent_tool_call_answers_fail_visibly(self):
        llm = _LLM(self.root, [TOOL_MARKUP, TOOL_MARKUP])
        with self.assertRaises(RuntimeError):
            summarize_messages(llm, MESSAGES)
        self.assertEqual(self._cache_files(), [])

    def test_cached_tool_call_answer_is_regenerated(self):
        # First run caches a good summary; then the cache is poisoned the way
        # the pre-validation bug did it, and the next run must not serve it.
        llm = _LLM(self.root, [GOOD_SUMMARY])
        summarize_messages(llm, MESSAGES)
        self._cache_files()[0].write_text(TOOL_MARKUP, encoding="utf-8")
        healed = _LLM(self.root, [GOOD_SUMMARY])
        self.assertEqual(summarize_messages(healed, MESSAGES), GOOD_SUMMARY)
        self.assertEqual(healed.calls, 1)

    def test_markup_detector(self):
        self.assertTrue(looks_like_tool_call(TOOL_MARKUP))
        self.assertFalse(looks_like_tool_call(GOOD_SUMMARY))

    def test_echoed_transcript_line_is_retried(self):
        # The observed degeneration: the model continued the transcript by
        # re-answering with the previous handoff's one-line goodbye.
        echo = "Continuation chat: abc123"
        llm = _LLM(self.root, [echo, GOOD_SUMMARY])
        result = summarize_messages(llm, [
            {"role": "assistant", "content": echo, "id": "a1"},
            {"role": "user", "content": "continue with the sprite work " * 40,
             "id": "m1"},
        ])
        self.assertEqual(result, GOOD_SUMMARY)
        self.assertEqual(llm.calls, 2)

    def test_too_short_summary_is_retried(self):
        llm = _LLM(self.root, ["Done.", GOOD_SUMMARY])
        summarize_messages(llm, [
            {"role": "user", "content": "long task description " * 300,
             "id": "m1"}])
        self.assertEqual(llm.calls, 2)

    def test_protocol_notes_are_excluded_from_the_transcript(self):
        llm = _LLM(self.root, [GOOD_SUMMARY])
        summarize_messages(llm, [
            {"role": "user", "content": "[TASK PROTOCOL - follow for this task] x",
             "id": "p1"},
            {"role": "user", "content": "make the sprites match the reference",
             "id": "m1"},
        ])
        request = llm.seen[0][1]["content"]
        self.assertNotIn("[TASK PROTOCOL", request)
        self.assertIn("make the sprites match the reference", request)
        self.assertIn("END OF TRANSCRIPT", request)


class ChatOrderingTests(unittest.TestCase):
    def test_touch_makes_a_conversation_the_most_recent(self):
        with tempfile.TemporaryDirectory() as tmp:
            session = Session(_Cfg(Path(tmp)), work_mode="discussion")
            session.add("user", "hello")
            before = session.meta["updated"]
            time.sleep(0.01)
            session.touch()
            self.assertGreater(session.meta["updated"], before)


if __name__ == "__main__":
    unittest.main()
