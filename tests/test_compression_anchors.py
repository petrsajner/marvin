"""Automatic shortening survives agentic stretches without user anchors.

Regression tests for 2026-09-23: auto-compression fired past 85% of the
context but found no cut - one user request followed by a hundred tool steps
leaves no user-message boundary in reach, so compression_cut returned None and
trim_to_budget gave up while reporting "trimmed: X to X"."""
import tempfile
import unittest
from pathlib import Path

from harness.session import Session


class _Cfg:
    def __init__(self, root: Path):
        self._root = root
        self.data = {"work_mode": "development"}

    def path(self, dotted: str):
        return {"paths.runtime_dir": self._root / "runtime",
                "paths.sessions_dir": self._root / "sessions"}[dotted]


def desert_session(root: Path, pairs: int = 100) -> Session:
    """One user request, then many tool turns and no further user messages."""
    session = Session(_Cfg(root), work_mode="development")
    session.add("system", "You are the worker.")
    session.add("user", "Build the game with sprite graphics.")
    add_pairs(session, pairs)
    return session


def add_pairs(session: Session, count: int, offset: int = 0) -> None:
    for i in range(offset, offset + count):
        session.add("assistant", "step " + str(i) + " " + "x" * 300,
                    tool_calls=[{"id": f"t{i}", "type": "function",
                                 "function": {"name": "run_command",
                                              "arguments": "{\"command\":\"ls\"}"}}])
        session.add("tool", "result " + "y" * 300, tool_call_id=f"t{i}",
                    name="run_command")


class CompressionAnchorTests(unittest.TestCase):
    def setUp(self):
        self._scratch = tempfile.TemporaryDirectory()
        self.root = Path(self._scratch.name)

    def tearDown(self):
        self._scratch.cleanup()

    def test_finds_a_completed_turn_when_no_user_boundary_is_in_reach(self):
        session = desert_session(self.root)
        cut = session.compression_cut(keep_tokens=int(32768 * 0.35))
        self.assertIsNotNone(cut, "no cut found in a boundary desert")
        # A completed turn: an assistant reply that follows tool results. Never
        # a tool message, which would orphan its tool_call.
        self.assertEqual(session.messages[cut]["role"], "assistant")
        self.assertEqual(session.messages[cut - 1]["role"], "tool")

    def test_user_boundaries_stay_preferred(self):
        session = desert_session(self.root)
        session.add("user", "Now adjust the spider timing.")
        index = len(session.messages) - 1
        add_pairs(session, 8, offset=100)
        cut = session.compression_cut(keep_tokens=int(32768 * 0.35))
        self.assertEqual(cut, index)

    def test_internal_protocols_do_not_anchor_the_cut(self):
        session = desert_session(self.root, pairs=60)
        session.add("user", "[TASK PROTOCOL - follow for this task] x")
        add_pairs(session, 8, offset=60)
        cut = session.compression_cut(keep_tokens=int(32768 * 0.35))
        self.assertIsNotNone(cut)
        self.assertEqual(session.messages[cut]["role"], "assistant")

    def test_trim_advances_through_a_boundary_desert(self):
        session = desert_session(self.root)
        self.assertTrue(session.trim_to_budget(5000))
        self.assertIsNotNone(session.compression)
        cut = session.compression["cut"]
        self.assertNotEqual(session.messages[cut]["role"], "tool")
        self.assertLessEqual(session.estimate_context_tokens(), 5000)


if __name__ == "__main__":
    unittest.main()
