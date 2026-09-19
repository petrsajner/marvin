"""A stale bundled payload must not stop the application from starting.

1.12.0 added a Python package. The Minimal installer replaces requirements.txt,
while the bundled payload and its manifest ship only with Full, so on a machine
installed from Full the two digests stopped matching and the bootstrap refused:
Marvin would not start at all, with a dialog that only named a log file.
"""
import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent


def load_bootstrap():
    spec = importlib.util.spec_from_file_location(
        "marvin_bootstrap_full", ROOT / "scripts" / "bootstrap_full.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def digest_of(requirements: Path, lock: Path) -> str:
    return hashlib.sha256(requirements.read_bytes() + b"\nLOCK\n" + lock.read_bytes()).hexdigest()


class HousekeepingTests(unittest.TestCase):
    """Rebuilt environments were moved aside and kept for ever."""

    def setUp(self):
        self.bootstrap = load_bootstrap()
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def test_only_the_newest_previous_environment_is_kept(self):
        history = self.root / "runtime" / "environment-history"
        for name in ("1000", "2000", "3000"):
            (history / name / "Lib").mkdir(parents=True)
        for name in ("failed-environment-1000", "failed-environment-2000"):
            (self.root / "runtime" / name).mkdir(parents=True)
        self.bootstrap._forget_old_environments(self.root)
        self.assertEqual(sorted(item.name for item in history.iterdir()), ["3000"])
        self.assertEqual(
            sorted(item.name for item in (self.root / "runtime").glob("failed-environment-*")),
            ["failed-environment-2000"])

    def test_it_does_nothing_when_there_is_nothing_to_forget(self):
        (self.root / "runtime").mkdir()
        self.bootstrap._forget_old_environments(self.root)      # Must not raise.
        self.assertFalse((self.root / "runtime" / "environment-history").exists())


class StalePayloadTests(unittest.TestCase):
    def setUp(self):
        self.bootstrap = load_bootstrap()
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        (self.root / "runtime" / "python").mkdir(parents=True)
        (self.root / "runtime" / "python" / "python.exe").write_bytes(b"MZ")
        self.requirements = self.root / "requirements.txt"
        self.lock = self.root / "requirements-windows-py312.lock"
        self.requirements.write_text("numpy\nsounddevice\n", encoding="utf-8")
        self.lock.write_text("numpy==2.5.2\nsounddevice==0.5.6\n", encoding="utf-8")
        self.digest = digest_of(self.requirements, self.lock)
        # A payload from an older release: its manifest predates the new package.
        (self.root / "runtime" / "full-manifest.json").write_text(
            json.dumps({"requirements_digest": "0" * 64}), encoding="utf-8")
        self.venv = self.root / ".venv"
        (self.venv / "Scripts").mkdir(parents=True)
        (self.venv / "Scripts" / "python.exe").write_bytes(b"MZ")

    def prepare(self):
        with patch.object(sys, "base_prefix", str(self.root / "runtime" / "python")):
            self.bootstrap.prepare(self.root)

    def test_an_environment_that_already_satisfies_requirements_starts(self):
        """The case that bricked startup: pip had already installed the package."""
        (self.venv / ".requirements.sha256").write_text(self.digest + "\n", encoding="ascii")
        self.prepare()
        self.assertTrue((self.venv / "Scripts" / "python.exe").is_file(),
                        "the working environment must not be thrown away")
        self.assertFalse((self.root / "runtime" / "environment-history").exists(),
                         "nothing needed rebuilding, so nothing should have been moved aside")

    def test_the_next_start_takes_the_fast_path(self):
        (self.venv / ".requirements.sha256").write_text(self.digest + "\n", encoding="ascii")
        self.prepare()
        stamp = json.loads((self.venv / ".full-runtime.json").read_text(encoding="utf-8"))
        self.assertEqual(stamp["digest"], self.digest)
        self.prepare()          # Must not raise, and must not rebuild.
        self.assertTrue((self.venv / "Scripts" / "python.exe").is_file())

    def test_a_matching_payload_still_takes_the_fast_path(self):
        (self.root / "runtime" / "full-manifest.json").write_text(
            json.dumps({"requirements_digest": self.digest}), encoding="utf-8")
        (self.venv / ".requirements.sha256").write_text(self.digest + "\n", encoding="ascii")
        self.prepare()
        self.assertTrue((self.venv / "Scripts" / "python.exe").is_file())

    def test_an_older_environment_is_updated_in_place_not_demolished(self):
        """Rebuilding from a payload that is itself older would lose the change."""
        (self.venv / ".requirements.sha256").write_text("f" * 64 + "\n", encoding="ascii")
        calls = []

        class Completed:
            returncode = 0

        def record(command, **kwargs):
            calls.append(command)
            return Completed()

        with patch.object(self.bootstrap.subprocess, "run", side_effect=record):
            self.prepare()
        self.assertTrue(any("pip" in part for command in calls for part in command),
                        "the difference should have been installed with pip")
        self.assertIn(str(self.lock), [part for command in calls for part in command])
        self.assertFalse((self.root / "runtime" / "environment-history").exists(),
                         "a working environment must not be moved aside")
        self.assertEqual((self.venv / ".requirements.sha256").read_text(encoding="ascii").strip(),
                         self.digest)

    def test_it_still_refuses_to_run_under_the_wrong_interpreter(self):
        with self.assertRaises(RuntimeError) as caught:
            self.bootstrap.prepare(self.root)
        self.assertIn("runtime/python", str(caught.exception))

    def test_a_stale_environment_is_not_declared_ready(self):
        """An environment installed for older requirements has to be rebuilt."""
        (self.venv / ".requirements.sha256").write_text("f" * 64 + "\n", encoding="ascii")
        with self.assertRaises(BaseException):
            # Rebuilding needs a real payload, which this fake root does not have;
            # the point is that it does not take the ready path.
            self.prepare()
        self.assertFalse((self.venv / ".full-runtime.json").is_file())


if __name__ == "__main__":
    unittest.main()
