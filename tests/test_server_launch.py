"""Golden launch contract for the llama-server path, without a process, GPU or download.

The Strata backend branches servermgmt at the few places that touch the process
(docs/design/2026-10-05-strata-backend.md, section 2.10). These tests pin what
the llama path does today, so that branch can prove it changed nothing:

- the exact argv of every built-in llama model and profile, Flash-Next's
  adaptive plan, MTP drafts, a manual GPU budget and a frozen recovery placement
  (tests/fixtures/llama_launch_golden.json);
- the launch side effects: PID file, run record, log header, guard thread;
- process identity, stop, readiness and the recovery ladder.

An intentional argv change regenerates the fixture with
MARVIN_REGENERATE_GOLDEN=1 and is reviewed as a diff.
"""
from __future__ import annotations

import contextlib
import copy
from dataclasses import replace
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import psutil

from harness import servermgmt
from harness.config import Config, load_config
from harness.hardware import Hardware

GIB = 1024**3

GOLDEN = Path(__file__).with_name("fixtures") / "llama_launch_golden.json"
REGENERATE = os.environ.get("MARVIN_REGENERATE_GOLDEN") == "1"
NO_WINDOW = 0x08000000
PID = 43210

# The owner's machine class: RTX 5090 and a hybrid CPU with 8 performance and
# 12 efficiency cores, 64 GB of RAM. Fixed, so the Flash plan is reproducible.
HARDWARE = Hardware("Intel64 Family 6 Model 198", 20, 20, tuple(range(8)), tuple(range(20)),
                    64 * GIB, 48 * GIB, "NVIDIA GeForce RTX 5090", "GPU-test", "580.00",
                    int(31.84 * GIB), int(29.4 * GIB))
# Detected capacity per GPU class, as the picker sees a real card of that size.
DETECTED = {32: 31.84, 24: 23.84, 16: 15.84}


def builtin_config(root: Path) -> Config:
    """Built-in defaults only: the developer's own config.yaml must not shape a golden argv."""
    return load_config(root / "config.yaml", root=root)


def llama_models(cfg: Config) -> list[str]:
    return [key for key, model in cfg.data["models"].items() if model.get("backend", "llama") == "llama"]


class FakeProcess:
    """What subprocess.Popen returns, recording how it was asked to start."""

    def __init__(self, argv, **kwargs):
        self.argv = list(argv)
        self.kwargs = kwargs
        self.pid = PID
        # Already finished as far as the memory guard can tell, so its thread ends at once.
        self.returncode = 0
        self.killed = False

    def poll(self):
        return self.returncode

    def kill(self):
        self.killed = True
        self.returncode = -9

    def terminate(self):
        self.returncode = 1

    def wait(self, timeout=None):
        return self.returncode


class RecordingThread(threading.Thread):
    started_threads: list = []

    def start(self):
        RecordingThread.started_threads.append(self)
        super().start()


class Installation:
    """A temporary Marvin root with a runtime and every built-in model file present."""

    def __init__(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.cfg = builtin_config(self.root)
        self.exe = self.cfg.path("paths.llama_dir") / "bin" / "llama-server.exe"
        self.exe.parent.mkdir(parents=True)
        self.exe.write_bytes(b"runtime")
        for key in self.cfg.data["models"]:
            for path in (self.cfg.model_file(key), self.cfg.mmproj_file(key)):
                if path is not None:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(b"weights")
        draft = self.cfg.mtp_draft_file()
        draft.parent.mkdir(parents=True, exist_ok=True)
        draft.write_bytes(b"draft")
        self.cfg.path("paths.runtime_dir").mkdir(parents=True, exist_ok=True)

    def close(self):
        self.temp.cleanup()

    def normalize(self, value: str) -> str:
        return value.replace(str(self.root), "<root>").replace("\\", "/")

    def launch(self, key: str, *, detected: float = DETECTED[32], hardware: Hardware = HARDWARE,
               ready: bool = True, runtime=..., cancelled=None, healthy: bool = False,
               running: str | None = None, stop_result: bool = True) -> dict:
        """Start `key` with every outside effect replaced; return what reached the process."""
        processes: list[FakeProcess] = []
        readiness: list[dict] = []
        stops: list[dict] = []
        RecordingThread.started_threads = []

        def popen(argv, **kwargs):
            processes.append(FakeProcess(argv, **kwargs))
            return processes[-1]

        def wait_health(cfg, timeout=servermgmt.HEALTH_TIMEOUT, proc=None, cancelled=None):
            readiness.append({"proc": proc, "cancelled": cancelled})
            if not ready and proc is not None:
                proc.returncode = None   # still running: the failure path must kill it
            return ready

        def no_download(*args, **kwargs):
            raise AssertionError("A verified model must not be downloaded again")

        threads = SimpleNamespace(Thread=RecordingThread, Event=threading.Event, Lock=threading.Lock)
        exe = self.exe if runtime is ... else runtime
        output = io.StringIO()
        with contextlib.ExitStack() as stack:
            for target in (
                    patch.object(servermgmt, "health", return_value=healthy),
                    patch.object(servermgmt, "running_model", return_value=running),
                    patch.object(servermgmt, "stop",
                                 side_effect=lambda cfg, quiet=False: stops.append({"quiet": quiet}) or stop_result),
                    patch.object(servermgmt, "wait_health", side_effect=wait_health),
                    patch.object(servermgmt, "vram_str", return_value="GPU VRAM: test"),
                    patch.object(servermgmt, "threading", threads),
                    patch.object(servermgmt.subprocess, "Popen", side_effect=popen),
                    patch.object(servermgmt.subprocess, "CREATE_NO_WINDOW", NO_WINDOW, create=True),
                    patch("harness.gpu.vram_total_gb", return_value=detected),
                    patch.object(Config, "model_ready", return_value=True),
                    patch.object(Config, "mtp_draft_ready", return_value=True),
                    patch("harness.model_files.download_pinned_model", side_effect=no_download),
                    patch("harness.runtime_update.ensure_runtime", return_value=exe),
                    patch("harness.hardware.detect_hardware", return_value=hardware),
                    contextlib.redirect_stdout(output)):
                stack.enter_context(target)
            code = servermgmt.start(self.cfg, key, cancelled=cancelled)
            for thread in RecordingThread.started_threads:
                thread.join(timeout=5)
        result = {"code": code, "processes": processes, "readiness": readiness, "stops": stops,
                  "output": output.getvalue(),
                  "guard_threads": [t.name for t in RecordingThread.started_threads]}
        if processes:
            run = json.loads((self.cfg.path("paths.runtime_dir") / "model-run.json").read_text(encoding="utf-8"))
            result.update(
                argv=[self.normalize(str(arg)) for arg in processes[0].argv],
                record={"profile": self.cfg.kv_cache_mode(key), "context": run["context"],
                        "placement": run["placement"]},
                run=run)
        return result

    def golden_record(self, key: str, **launch) -> dict:
        result = self.launch(key, **launch)
        if result["code"] != 0:
            raise AssertionError(f"{key} did not launch: {result['output']}")
        return {"argv": result["argv"], **result["record"]}


def golden_cases() -> dict:
    """Every built-in llama model and profile, plus the launch variants the Strata branch must not touch."""
    cases = {}
    installation = Installation()
    try:
        cfg = installation.cfg
        for key in llama_models(cfg):
            for profile, values in cfg.kv_cache_profiles(key).items():
                case = Installation()
                try:
                    case.cfg.set_kv_cache_mode(key, profile)
                    detected = DETECTED[values.get("gpu_class", 32)]
                    cases[f"{key}/{profile}"] = case.golden_record(key, detected=detected)
                finally:
                    case.close()
    finally:
        installation.close()

    def variant(name, key, profile, prepare=None, **launch):
        case = Installation()
        try:
            case.cfg.set_kv_cache_mode(key, profile)
            if prepare:
                prepare(case.cfg)
            cases[name] = case.golden_record(key, **launch)
        finally:
            case.close()

    def budget(value):
        return lambda cfg: cfg.data["hardware"].update(vram_gb=value)

    def frozen(model, server_args, **extra):
        return lambda cfg: cfg.data.update(_recovery_placement={"model": model, "server_args": server_args, **extra})

    def extra_args(cfg):
        cfg.data["server"]["extra_args"] = ["--metrics", "--slot-save-path", "slots"]

    # A manual GPU budget turns llama's own fitting off for measured profiles.
    variant("manual-budget/q5/q8_0", "q5", "q8_0", budget(32))
    variant("manual-budget/q4/q8_0_compact_mtp", "q4", "q8_0_compact_mtp", budget(24))
    # A recovery keeps the failed run's placement while the context shrinks.
    variant("recovery/nemotron_q5/q8_0_256k_spill", "nemotron_q5", "q8_0_256k_spill",
            frozen("nemotron_q5", ["--fit", "off", "--n-cpu-moe", "21"]), detected=DETECTED[24])
    # A frozen placement of another model is ignored.
    variant("recovery-other-model/q5/q8_0_128k", "q5", "q8_0_128k",
            frozen("nemotron_q5", ["--fit", "off", "--n-cpu-moe", "21"]))
    # The profile no longer fits a smaller card: the best fitting one is chosen.
    variant("budget-reselect/q5/q8_0", "q5", "q8_0", detected=DETECTED[24])
    # The owner's extra server arguments always come last.
    variant("extra-args/q5/q8_0_mtp", "q5", "q8_0_mtp", extra_args)
    return cases


class GoldenArgvTests(unittest.TestCase):
    maxDiff = None

    def test_every_builtin_llama_launch_matches_the_golden_argv(self):
        actual = golden_cases()
        if REGENERATE:
            GOLDEN.parent.mkdir(parents=True, exist_ok=True)
            GOLDEN.write_text(json.dumps(actual, indent=1) + "\n", encoding="utf-8")
            self.skipTest(f"regenerated {GOLDEN.name}")
        expected = json.loads(GOLDEN.read_text(encoding="utf-8"))
        self.assertEqual(sorted(actual), sorted(expected), "launch cases were added or removed")
        for name in expected:
            with self.subTest(name):
                self.assertEqual(actual[name], expected[name])

    def test_every_profile_is_covered(self):
        with tempfile.TemporaryDirectory() as temporary:
            cfg = builtin_config(Path(temporary))
        expected = json.loads(GOLDEN.read_text(encoding="utf-8"))
        for key in llama_models(cfg):
            for profile in cfg.kv_cache_profiles(key):
                self.assertIn(f"{key}/{profile}", expected)


class LaunchSideEffectTests(unittest.TestCase):
    def setUp(self):
        self.installation = Installation()
        self.cfg = self.installation.cfg
        self.runtime = self.cfg.path("paths.runtime_dir")

    def tearDown(self):
        self.installation.close()

    def test_launch_records_identity_log_and_placement(self):
        log = self.runtime / "llama-server.log"
        log.write_bytes(b"earlier launch\n")
        (self.runtime / "model-failure.json").write_text('{"code": "ram_pressure"}', encoding="utf-8")
        self.cfg.set_kv_cache_mode("q5", "q8_0_128k")
        cancelled = lambda: False  # noqa: E731
        result = self.installation.launch("q5", cancelled=cancelled)
        self.assertEqual(result["code"], 0)
        process = result["processes"][0]
        self.assertEqual(process.kwargs["stderr"], subprocess.STDOUT)
        self.assertEqual(process.kwargs["creationflags"], NO_WINDOW)
        self.assertEqual(process.kwargs["cwd"], str(self.installation.exe.parent))
        self.assertTrue(process.kwargs["stdout"].closed, "the log handle belongs to the child alone")
        self.assertEqual(Path(process.kwargs["stdout"].name), log)
        self.assertEqual(servermgmt.pid_file(self.cfg).read_text(encoding="utf-8"), f"q5:{PID}")
        run = result["run"]
        self.assertEqual((run["model"], run["pid"], run["context"], run["log_offset"]),
                         ("q5", PID, 131072, len(b"earlier launch\n")))
        self.assertEqual(run["placement"], {"model": "q5", "server_args": ["--fit", "off"]})
        self.assertIsInstance(run["started"], float)
        self.assertEqual(self.cfg.data["_active_placement"], run["placement"])
        self.assertIn(b"===== START q5 ", log.read_bytes())
        self.assertFalse((self.runtime / "model-failure.json").exists(), "a launch clears the previous failure")
        self.assertEqual(result["readiness"], [{"proc": process, "cancelled": cancelled}])
        self.assertEqual(result["guard_threads"], ["model-memory-guard"])

    def test_missing_projector_launches_text_only_with_a_warning(self):
        self.cfg.mmproj_file("q4").unlink()
        self.cfg.set_kv_cache_mode("q4", "q8_0")
        result = self.installation.launch("q4")
        self.assertEqual(result["code"], 0)
        self.assertNotIn("--mmproj", result["argv"])
        self.assertIn("[WARNING] mmproj not found", result["output"])

    def test_unknown_model_is_reported_without_a_launch(self):
        result = self.installation.launch("no-such-model")
        self.assertEqual((result["code"], result["processes"]), (1, []))
        self.assertIn("Unknown model 'no-such-model'", result["output"])

    def test_already_running_model_is_kept(self):
        result = self.installation.launch("q5", healthy=True, running="q5")
        self.assertEqual((result["code"], result["processes"]), (0, []))

    def test_switch_refuses_to_start_while_the_previous_model_holds_memory(self):
        with self.assertRaisesRegex(RuntimeError, "has not released its memory"):
            self.installation.launch("q5", healthy=True, running="q4", stop_result=False)

    def test_switch_stops_the_previous_model_first(self):
        result = self.installation.launch("q5", healthy=True, running="q4")
        self.assertEqual(result["code"], 0)
        self.assertEqual(result["stops"], [{"quiet": True}])
        self.assertEqual(len(result["processes"]), 1)

    def test_missing_runtime_is_reported(self):
        result = self.installation.launch("q5", runtime=None)
        self.assertEqual((result["code"], result["processes"]), (1, []))
        self.assertIn("llama-server.exe not found", result["output"])

    def test_missing_model_file_is_reported(self):
        self.cfg.model_file("q5").unlink()
        result = self.installation.launch("q5")
        self.assertEqual((result["code"], result["processes"]), (1, []))
        self.assertIn("Model not found", result["output"])

    def test_cancel_before_launch_starts_nothing(self):
        answers = iter([False, True])
        result = self.installation.launch("q5", cancelled=lambda: next(answers))
        self.assertEqual((result["code"], result["processes"]), (1, []))

    def test_cancel_before_anything_starts_nothing(self):
        result = self.installation.launch("q5", cancelled=lambda: True)
        self.assertEqual((result["code"], result["processes"]), (1, []))

    def test_failed_readiness_kills_the_process_and_forgets_it(self):
        with patch.object(servermgmt, "record_allocation_failure") as record:
            result = self.installation.launch("q5", ready=False)
        self.assertEqual(result["code"], 1)
        self.assertTrue(result["processes"][0].killed)
        self.assertFalse(servermgmt.pid_file(self.cfg).exists())
        record.assert_called_with(self.cfg)
        self.assertIn("Server startup failed", result["output"])

    def test_no_profile_for_the_budget_is_an_error(self):
        with self.assertRaisesRegex(RuntimeError, "no supported profile"):
            self.installation.launch("nemotron_q5", detected=DETECTED[16])


class FakePsProcess:
    def __init__(self, *, name="llama-server.exe", exe=None, cmdline=(), running=True,
                 status=psutil.STATUS_RUNNING):
        self._name, self._exe, self._cmdline = name, exe, list(cmdline)
        self._running, self._status = running, status

    def is_running(self):
        return self._running

    def status(self):
        return self._status

    def name(self):
        return self._name

    def exe(self):
        return self._exe

    def cmdline(self):
        return self._cmdline


class ProcessIdentityTests(unittest.TestCase):
    def setUp(self):
        self.installation = Installation()
        self.cfg = self.installation.cfg
        self.exe = str(self.installation.exe)
        self.pid_file = servermgmt.pid_file(self.cfg)

    def tearDown(self):
        self.installation.close()

    def resolve(self, process, record=f"q5:{PID}"):
        if record is None:
            self.pid_file.unlink(missing_ok=True)
        else:
            self.pid_file.write_text(record, encoding="utf-8")

        def lookup(pid):
            self.assertEqual(pid, PID)
            if isinstance(process, Exception):
                raise process
            return process

        with patch("psutil.Process", side_effect=lookup):
            return servermgmt._managed_process(self.cfg)

    def owned(self, **changes):
        values = {"exe": self.exe, "cmdline": [self.exe, "-m", "model.gguf", "--port", "8080", "--jinja"]}
        values.update(changes)
        return FakePsProcess(**values)

    def test_owned_server_is_recognized_and_its_record_kept(self):
        process = self.owned()
        self.assertIs(self.resolve(process), process)
        self.assertTrue(self.pid_file.exists())
        with patch("psutil.Process", return_value=process):
            self.assertEqual(servermgmt.running_model(self.cfg), "q5")

    def test_name_is_compared_without_case(self):
        process = self.owned(name="LLAMA-SERVER.EXE")
        self.assertIs(self.resolve(process), process)

    def test_anything_else_is_forgotten(self):
        cases = {
            "no record": (self.owned(), None),
            "malformed record": (self.owned(), "q5"),
            "non-numeric pid": (self.owned(), "q5:abc"),
            "gone": (psutil.NoSuchProcess(PID), f"q5:{PID}"),
            "access denied": (psutil.AccessDenied(PID), f"q5:{PID}"),
            "not running": (self.owned(running=False), f"q5:{PID}"),
            "zombie": (self.owned(status=psutil.STATUS_ZOMBIE), f"q5:{PID}"),
            "other program": (self.owned(name="python.exe"), f"q5:{PID}"),
            "other runtime": (self.owned(exe=str(self.installation.root / "other" / "llama-server.exe")),
                              f"q5:{PID}"),
            "no port": (self.owned(cmdline=[self.exe, "-m", "model.gguf"]), f"q5:{PID}"),
            "port without value": (self.owned(cmdline=[self.exe, "--port"]), f"q5:{PID}"),
            "other port": (self.owned(cmdline=[self.exe, "--port", "8091"]), f"q5:{PID}"),
        }
        for name, (process, record) in cases.items():
            with self.subTest(name):
                self.assertIsNone(self.resolve(process, record))
                self.assertFalse(self.pid_file.exists())

    def test_missing_runtime_cannot_own_a_process(self):
        process = self.owned()
        self.installation.exe.unlink()
        self.assertIsNone(self.resolve(process))
        self.assertFalse(self.pid_file.exists())

    def test_server_state_distinguishes_loading_from_down(self):
        with patch.object(servermgmt, "health", return_value=True):
            self.assertEqual(servermgmt.server_state(self.cfg), "running")
        with patch.object(servermgmt, "health", return_value=False), \
             patch.object(servermgmt, "_managed_process", return_value=object()):
            self.assertEqual(servermgmt.server_state(self.cfg), "starting")
        with patch.object(servermgmt, "health", return_value=False), \
             patch.object(servermgmt, "_managed_process", return_value=None):
            self.assertEqual(servermgmt.server_state(self.cfg), "down")


class FakeTree:
    def __init__(self, children=()):
        self._children = list(children)
        self.killed = False

    def children(self, recursive=False):
        assert recursive
        return list(self._children)

    def kill(self):
        self.killed = True


class StopTests(unittest.TestCase):
    def setUp(self):
        self.installation = Installation()
        self.cfg = self.installation.cfg
        self.pid_file = servermgmt.pid_file(self.cfg)
        self.pid_file.write_text(f"q5:{PID}", encoding="utf-8")
        self.sleeps = []
        clock = SimpleNamespace(sleep=self.sleeps.append, time=time.time, strftime=time.strftime)
        self.clock = patch.object(servermgmt, "time", clock)
        self.clock.start()

    def tearDown(self):
        self.clock.stop()
        self.installation.close()

    def stop(self, process, *, alive=(), health=(False,), error=None):
        waited = []

        def wait_procs(procs, timeout):
            waited.append((list(procs), timeout))
            if error:
                raise error
            return [], list(alive)

        answers = iter(health)
        output = io.StringIO()
        with patch.object(servermgmt, "_managed_process", return_value=process), \
             patch("psutil.wait_procs", side_effect=wait_procs), \
             patch.object(servermgmt, "health", side_effect=lambda cfg, timeout=3.0: next(answers, False)), \
             contextlib.redirect_stdout(output):
            result = servermgmt.stop(self.cfg)
        return result, waited, output.getvalue()

    def test_stop_kills_the_whole_tree_and_waits_for_the_port(self):
        child = FakeTree()
        process = FakeTree([child])
        result, waited, output = self.stop(process, health=(True, True, False))
        self.assertTrue(result)
        self.assertTrue(child.killed and process.killed)
        self.assertEqual(waited, [([child, process], 5)])
        self.assertFalse(self.pid_file.exists())
        self.assertEqual(self.sleeps, [1, 1])
        self.assertIn("llama-server stopped", output)

    def test_port_that_never_closes_is_given_fifteen_seconds(self):
        result, _, _ = self.stop(FakeTree(), health=[True] * 20)
        self.assertTrue(result)
        self.assertEqual(len(self.sleeps), 15)

    def test_survivor_keeps_its_record_and_fails_the_stop(self):
        process = FakeTree()
        result, _, _ = self.stop(process, alive=[process])
        self.assertFalse(result)
        self.assertTrue(self.pid_file.exists())

    def test_process_that_already_ended_counts_as_stopped(self):
        result, _, output = self.stop(FakeTree(), error=psutil.NoSuchProcess(PID))
        self.assertTrue(result)
        self.assertFalse(self.pid_file.exists())
        self.assertIn("was not running", output)

    def test_nothing_owned_only_clears_the_record(self):
        result, waited, output = self.stop(None)
        self.assertTrue(result)
        self.assertEqual(waited, [])
        self.assertFalse(self.pid_file.exists())
        self.assertIn("was not running", output)


class ReadinessTests(unittest.TestCase):
    def setUp(self):
        with tempfile.TemporaryDirectory() as temporary:
            self.cfg = builtin_config(Path(temporary))
        self.clock = [0.0]
        self.sleeps = []

        def sleep(seconds):
            self.sleeps.append(seconds)
            self.clock[0] += seconds

        self.patch = patch.object(servermgmt, "time", SimpleNamespace(time=lambda: self.clock[0], sleep=sleep))
        self.patch.start()

    def tearDown(self):
        self.patch.stop()

    def wait(self, health, **kwargs):
        answers = iter(health)
        with patch.object(servermgmt, "health", side_effect=lambda cfg: next(answers, False)):
            return servermgmt.wait_health(self.cfg, **kwargs)

    def test_ready_when_health_answers(self):
        self.assertTrue(self.wait([False, False, True]))
        self.assertEqual(self.sleeps, [2, 2])

    def test_process_exit_ends_the_wait(self):
        process = SimpleNamespace(poll=lambda: 3)
        self.assertFalse(self.wait([False], proc=process))
        self.assertEqual(self.sleeps, [])

    def test_cancel_ends_the_wait(self):
        self.assertFalse(self.wait([True], cancelled=lambda: True))

    def test_timeout_ends_the_wait(self):
        self.assertFalse(self.wait([False] * 100, timeout=10))
        self.assertEqual(sum(self.sleeps), 10)

    def test_health_requires_status_200(self):
        import requests
        with patch("requests.get", return_value=SimpleNamespace(status_code=503)):
            self.assertFalse(servermgmt.health(self.cfg))
        with patch("requests.get", return_value=SimpleNamespace(status_code=200)) as get:
            self.assertTrue(servermgmt.health(self.cfg))
        self.assertEqual(get.call_args.args[0], "http://127.0.0.1:8080/health")
        with patch("requests.get", side_effect=requests.ConnectionError("refused")):
            self.assertFalse(servermgmt.health(self.cfg))


class RecoveryLadderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.cfg = builtin_config(self.root)
        self.cfg.path("paths.runtime_dir").mkdir(parents=True)
        self.failure = self.cfg.path("paths.runtime_dir") / "model-failure.json"

    def tearDown(self):
        self.temp.cleanup()

    def fail(self, key, code="vram_pressure", error="Pressure"):
        self.failure.write_text(json.dumps({"code": code, "model": key, "error": error}), encoding="utf-8")

    def ensure(self, key, outcomes, *, healthy=False, running=None, phases=None, cancelled=None):
        """outcomes: per start, 0/1 or an exception; a failure record can be written first."""
        started = []

        def start(cfg, model, **kwargs):
            started.append((model, cfg.kv_cache_mode(model)))
            outcome = outcomes[len(started) - 1]
            if callable(outcome):
                outcome = outcome(cfg, model)
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

        with patch.object(servermgmt, "health", return_value=healthy), \
             patch.object(servermgmt, "running_model", return_value=running), \
             patch.object(servermgmt, "start", side_effect=start):
            result = servermgmt.ensure(self.cfg, key, on_phase=phases.append if phases is not None else None,
                                       cancelled=cancelled)
        return result, started

    def test_running_model_is_reused(self):
        result, started = self.ensure("q5", [], healthy=True, running="q5")
        self.assertTrue(result)
        self.assertEqual(started, [])

    def test_successful_start(self):
        self.assertEqual(self.ensure("q5", [0]), (True, [("q5", "q8_0")]))

    def test_plain_failure_is_not_retried(self):
        self.assertEqual(self.ensure("q5", [1]), (False, [("q5", "q8_0")]))

    def test_error_without_memory_pressure_propagates(self):
        with self.assertRaisesRegex(RuntimeError, "broken"):
            self.ensure("q5", [RuntimeError("broken")])

    def test_pressure_lowers_only_the_context_and_freezes_the_placement(self):
        self.cfg.data["default_model"] = "nemotron_q5"
        self.cfg.set_kv_cache_mode("nemotron_q5", "q8_0_512k_spill")
        phases = []

        def pressure(cfg, key):
            self.fail(key)
            return RuntimeError("Pressure")

        result, started = self.ensure("nemotron_q5", [pressure, 0], phases=phases)
        self.assertTrue(result)
        self.assertEqual(started, [("nemotron_q5", "q8_0_512k_spill"), ("nemotron_q5", "q8_0_256k_spill")])
        self.assertEqual(self.cfg.data["_recovery_placement"],
                         {"model": "nemotron_q5", "server_args": ["--fit", "off", "--n-cpu-moe", "21"]})
        self.assertEqual(self.cfg.data["_recovered_contexts"], {"nemotron_q5": 262144})
        self.assertTrue(self.cfg.data["_memory_profile_recovered"])
        self.assertEqual(phases, ["preparing"])
        self.assertNotIn("_recovery_origin_mtp", self.cfg.data)

    def test_pressure_reported_as_a_plain_failure_also_recovers(self):
        def pressure(cfg, key):
            self.fail(key, "ram_pressure")
            return 1

        result, started = self.ensure("q5", [pressure, 0])
        self.assertTrue(result)
        self.assertEqual([profile for _, profile in started], ["q8_0", "q8_0_128k"])

    def test_mtp_session_remembers_its_origin(self):
        self.cfg.set_kv_cache_mode("q5", "q8_0_mtp")

        def pressure(cfg, key):
            self.fail(key)
            return 1

        result, started = self.ensure("q5", [pressure, 0])
        self.assertTrue(result)
        self.assertEqual([profile for _, profile in started], ["q8_0_mtp", "q8_0"])
        self.assertEqual(self.cfg.data["_recovery_origin_mtp"], {"q5": True})

    def test_lowest_profile_reports_the_failure(self):
        self.cfg.set_kv_cache_mode("q5", "q8_0_128k")

        def pressure(cfg, key):
            self.fail(key, "ram_pressure", "Not enough RAM for 128k")
            return 1

        with self.assertRaisesRegex(RuntimeError, "Not enough RAM for 128k"):
            self.ensure("q5", [pressure])

    def test_pressure_of_another_model_is_not_this_ones(self):
        def pressure(cfg, key):
            self.fail("q4")
            return 1

        self.assertEqual(self.ensure("q5", [pressure]), (False, [("q5", "q8_0")]))

    def test_cancel_stops_the_ladder(self):
        def pressure(cfg, key):
            self.fail(key)
            return 1

        result, started = self.ensure("q5", [pressure], cancelled=lambda: True)
        self.assertFalse(result)
        self.assertEqual(len(started), 1)


if __name__ == "__main__":
    unittest.main()
