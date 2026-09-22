"""run_command survives detached children and keeps its output contract.

Regression test for the 2026-09-22 hang: launching a program in the background
(start ... &) left an orphan holding the inherited stdout/stderr pipes, and the
unbounded communicate() drain after the timeout blocked the run controller
indefinitely - past the tool timeout and past the STOP button."""
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace

from harness.config import load_config
from harness.tools.shell import RunCommandTool


class _Ctx:
    def __init__(self, workspace: Path):
        self.cfg = load_config()
        self.workspace = workspace
        self.abort_flag = threading.Event()
        self.session = SimpleNamespace(dir=workspace)

    def resolve(self, path):
        return Path(path)


def run_guarded(ctx, command, **kwargs):
    """Run the tool on a thread so a hang becomes a test failure, not a stall."""
    guard = kwargs.pop("guard", 15)
    result: dict = {}

    def target():
        try:
            result["value"] = RunCommandTool().run(ctx, command, **kwargs)
        except Exception as exc:  # surfaced below instead of a silent dead thread
            result["error"] = exc

    thread = threading.Thread(target=target, daemon=True)
    thread.start()
    thread.join(guard)
    return result, thread.is_alive()


class RunCommandTests(unittest.TestCase):
    def setUp(self):
        self._scratch = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.ctx = _Ctx(Path(self._scratch.name))

    def tearDown(self):
        self._scratch.cleanup()

    def test_output_and_exit_code(self):
        result, hung = run_guarded(self.ctx, "echo hello")
        self.assertFalse(hung)
        self.assertNotIn("error", result)
        self.assertIn("hello", result["value"])
        self.assertIn("[exit code: 0]", result["value"])

    def test_stderr_is_kept_separate(self):
        result, hung = run_guarded(self.ctx, "echo oops >&2")
        self.assertFalse(hung)
        self.assertNotIn("error", result)
        self.assertIn("STDERR:", result["value"])
        self.assertIn("oops", result["value"])

    def test_detached_child_cannot_hang_the_command(self):
        # The shell exits immediately and leaves a backgrounded sleep holding
        # whatever carries the output. Before the file-backed fix the read
        # blocked until the sleep itself exited - far past any timeout. The
        # neutral cwd keeps the orphan from pinning the test's scratch folder.
        result, hung = run_guarded(
            self.ctx, "(sleep 25 &) ; echo started",
            cwd=tempfile.gettempdir(), guard=15)
        self.assertFalse(hung, "run_command hung on a detached child")
        self.assertNotIn("error", result)
        self.assertIn("started", result["value"])
        self.assertIn("[state: finished]", result["value"])

    def test_timeout_with_detached_child_still_returns(self):
        # The shell itself runs past the deadline this time; the kill must not
        # end up waiting on the detached child either.
        result, hung = run_guarded(
            self.ctx, "(sleep 25 &) ; sleep 30",
            cwd=tempfile.gettempdir(), timeout=2, guard=15)
        self.assertFalse(hung, "run_command hung after its timeout")
        self.assertNotIn("error", result)
        self.assertIn("timed out after 2s", result["value"])


if __name__ == "__main__":
    unittest.main()
