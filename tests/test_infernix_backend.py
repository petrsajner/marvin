"""Tests for the Blackwell-accelerated Infernix backend, runtime, and non-Blackwell greyed-out UI."""
from __future__ import annotations

import copy
import hashlib
import io
import json
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile

from fastapi.testclient import TestClient

from harness import gpu, hardware, infernix_backend, infernix_runtime, servermgmt
from harness.application import ApplicationService
from harness.config import Config, load_config
from harness.hardware import Hardware
from harness.web_api import create_app
from tests import test_workspace as helpers

GIB = 1024**3
M27 = "qwen27b_infernix"
MFN = "flash_next_infernix"

BLACKWELL_32 = Hardware(
    "Intel64", 20, 20, tuple(range(8)), tuple(range(20)),
    64 * GIB, 48 * GIB, "NVIDIA GeForce RTX 5090", "GPU-5090", "591.44",
    int(31.84 * GIB), int(29.0 * GIB), "12.0",
)
BLACKWELL_OLD_DRV = Hardware(
    "Intel64", 20, 20, tuple(range(8)), tuple(range(20)),
    64 * GIB, 48 * GIB, "NVIDIA GeForce RTX 5090", "GPU-5090", "576.12",
    int(31.84 * GIB), int(29.0 * GIB), "12.0",
)
ADA_24 = Hardware(
    "Intel64", 16, 16, tuple(range(16)), tuple(range(16)),
    64 * GIB, 48 * GIB, "NVIDIA GeForce RTX 4090", "GPU-4090", "591.44",
    int(23.98 * GIB), int(21.0 * GIB), "8.9",
)
AMPERE_12 = Hardware(
    "Intel64", 8, 8, tuple(range(8)), tuple(range(8)),
    32 * GIB, 24 * GIB, "NVIDIA GeForce RTX 3060", "GPU-3060", "591.44",
    int(11.98 * GIB), int(10.5 * GIB), "8.6",
)


def zip_bytes(files: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    return buffer.getvalue()


class InfernixInstallation:
    """A temporary Marvin root populated with Infernix binaries and placeholder artifacts."""

    def __init__(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.cfg = Config(copy.deepcopy(load_config().data), self.root)
        files = [
            infernix_backend.server_exe(self.cfg),
            infernix_backend.chat_template_path(self.cfg, M27),
            self.cfg.model_file(M27),
            self.cfg.model_file(MFN),
            infernix_backend.ngram_volume_path(self.cfg, MFN),
            infernix_backend.draft_model_path(self.cfg, MFN),
        ]
        for path in files:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"x")
        self.cfg.path("paths.runtime_dir").mkdir(parents=True, exist_ok=True)

    def close(self):
        self.temp.cleanup()


class BlackwellHardwareTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.cfg = Config(copy.deepcopy(load_config().data), Path(self.temp.name))

    def tearDown(self):
        self.temp.cleanup()

    def test_compute_capability_and_blackwell_detection(self):
        self.assertEqual(hardware.compute_capability_major("12.0"), 12)
        self.assertEqual(hardware.compute_capability_major("12.1"), 12)
        self.assertEqual(hardware.compute_capability_major("8.9"), 8)
        self.assertIsNone(hardware.compute_capability_major(""))
        self.assertTrue(hardware.is_blackwell(BLACKWELL_32))
        self.assertFalse(hardware.is_blackwell(ADA_24))
        self.assertFalse(hardware.is_blackwell(AMPERE_12))

    def test_model_availability_gates_infernix_by_blackwell_and_driver(self):
        self.assertEqual(gpu.model_availability(self.cfg, "q5", hardware=ADA_24), (True, None))
        self.assertEqual(gpu.model_availability(self.cfg, "flash_next_strata", hardware=AMPERE_12), (True, None))
        self.assertEqual(
            gpu.model_availability(self.cfg, M27, hardware=ADA_24),
            (False, "Requires NVIDIA RTX 50-series (Blackwell)"),
        )
        self.assertEqual(
            gpu.model_availability(self.cfg, MFN, hardware=AMPERE_12),
            (False, "Requires NVIDIA RTX 50-series (Blackwell)"),
        )
        self.assertEqual(
            gpu.model_availability(self.cfg, M27, hardware=BLACKWELL_OLD_DRV),
            (False, "Requires NVIDIA driver 580 or newer"),
        )
        self.assertEqual(gpu.model_availability(self.cfg, M27, hardware=BLACKWELL_32), (True, None))
        self.assertEqual(gpu.model_availability(self.cfg, MFN, hardware=BLACKWELL_32), (True, None))

    def test_best_fit_and_download_keys_never_select_unavailable_or_optional_infernix(self):
        with patch.object(hardware, "detect_hardware", return_value=ADA_24):
            self.assertFalse(gpu.fits(self.cfg, M27, "int8_64k_g24", 24.0))
            self.assertEqual(gpu.best_fit(self.cfg, 24.0), ("q5", "q8_0_96k"))
            self.assertNotIn(M27, gpu.download_keys(self.cfg, 24.0))
            self.assertNotIn(MFN, gpu.download_keys(self.cfg, 24.0))
        with patch.object(hardware, "detect_hardware", return_value=BLACKWELL_32):
            self.assertTrue(gpu.fits(self.cfg, M27, "int8_256k", 32.0))
            self.assertEqual(gpu.best_fit(self.cfg, 32.0), ("q5", "q8_0"))
            self.assertNotIn(M27, gpu.download_keys(self.cfg, 32.0))
            self.assertNotIn(MFN, gpu.download_keys(self.cfg, 32.0))

    def test_recovery_ladder_keeps_precision_and_shrinks_context(self):
        self.cfg.set_kv_cache_mode(M27, "int8_256k")
        self.assertEqual(gpu.lower_memory_profiles(self.cfg, M27), ["int8_192k", "int8_128k"])
        self.cfg.set_kv_cache_mode(M27, "nvfp4_128k_g24")
        self.assertEqual(gpu.lower_memory_profiles(self.cfg, M27), ["nvfp4_64k_g24"])
        self.cfg.set_kv_cache_mode(MFN, "int8_256k_g32")
        self.assertEqual(gpu.lower_memory_profiles(self.cfg, MFN), ["int8_128k_g32"])


class WebUiGreyedOutTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        data = copy.deepcopy(load_config().data)
        data["agent"].update(workspace=None, autonomy="auto")
        self.cfg = Config(data, self.root)
        self.app = ApplicationService(self.cfg, llm_factory=helpers.Model, manage_model=False)

    def tearDown(self):
        self.app.close()
        self.app.models.wait(3)
        self.temp.cleanup()

    def test_non_blackwell_gpu_lists_infernix_models_as_disabled_and_rejects_selection(self):
        with patch.object(hardware, "detect_hardware", return_value=ADA_24), \
             patch.object(gpu, "vram_total_gb", return_value=24.0):
            client = TestClient(create_app(self.cfg, service=self.app))
            models = {m["id"]: m for m in client.get("/api/state").json()["models"]}
            self.assertIn(M27, models, "Infernix 27B stays visible as a disabled option on non-Blackwell GPUs")
            self.assertIn(MFN, models, "Infernix Flash-Next stays visible as a disabled option on non-Blackwell GPUs")
            for key in (M27, MFN):
                self.assertFalse(models[key]["available"])
                self.assertEqual(models[key]["unavailable_reason"], "Requires NVIDIA RTX 50-series (Blackwell)")
                self.assertEqual(models[key]["profiles"], [])
            self.assertTrue(models["q5"]["available"])
            self.assertIsNone(models["q5"]["unavailable_reason"])

            resp = client.patch("/api/settings", json={"model": M27})
            self.assertEqual(resp.status_code, 400)
            self.assertIn("Blackwell", resp.json()["detail"])
            self.assertNotEqual(self.app.preferences["model"], M27)

    def test_blackwell_gpu_enables_infernix_models_with_profiles(self):
        with patch.object(hardware, "detect_hardware", return_value=BLACKWELL_32), \
             patch.object(gpu, "vram_total_gb", return_value=32.0):
            client = TestClient(create_app(self.cfg, service=self.app))
            models = {m["id"]: m for m in client.get("/api/state").json()["models"]}
            for key in (M27, MFN):
                self.assertTrue(models[key]["available"])
                self.assertIsNone(models[key]["unavailable_reason"])
                self.assertGreaterEqual(len(models[key]["profiles"]), 2)
            self.assertEqual(models[M27]["speculative_builtin"], "DFlash2 + n-gram")
            self.assertEqual(models[MFN]["speculative_builtin"], "DFlash2")
            self.assertEqual(models["flash_next_strata"]["speculative_builtin"], "DFlash2")
            self.assertIsNone(models["q5"]["speculative_builtin"])

    def test_runtime_reports_speculative_label_for_infernix_and_strata(self):
        with patch.object(servermgmt, "server_state", return_value="running"), \
             patch.object(servermgmt, "vram_value", return_value="28.0 / 32.0 GB"):
            client = TestClient(create_app(self.cfg, service=self.app))
            with patch.object(servermgmt, "running_model", return_value=M27):
                prof = client.get("/api/runtime").json()["profile"]
                self.assertTrue(prof["speculative"])
                self.assertEqual(prof["speculative_label"], "DFlash2 + n-gram")
            client = TestClient(create_app(self.cfg, service=self.app))
            with patch.object(servermgmt, "running_model", return_value=MFN):
                prof = client.get("/api/runtime").json()["profile"]
                self.assertTrue(prof["speculative"])
                self.assertEqual(prof["speculative_label"], "DFlash2")


class InfernixBackendTests(unittest.TestCase):
    def setUp(self):
        self.inst = InfernixInstallation()
        self.cfg = self.inst.cfg

    def tearDown(self):
        servermgmt.BIND_SERVER_TO_PROCESS = True
        self.inst.close()

    def test_27b_server_argv_contains_required_flags_and_ram_cap(self):
        argv = infernix_backend.server_argv(self.cfg, M27, 262144)
        self.assertEqual(argv[0], str(infernix_backend.server_exe(self.cfg)))
        self.assertEqual(argv[1], str(self.cfg.model_file(M27)))
        self.assertEqual(argv[argv.index("--model-id") + 1], "local-model")
        self.assertIn("--any-model-name", argv)
        self.assertEqual(argv[argv.index("--max-context") + 1], "262144")
        self.assertEqual(argv[argv.index("--default-max-tokens") + 1], "262144")
        self.assertEqual(argv[argv.index("--kv-dtype") + 1], "int8")
        self.assertEqual(argv[argv.index("--kv-capacity") + 1], "262144")
        self.assertEqual(argv[argv.index("--spec") + 1], "dflash2")
        self.assertEqual(argv[argv.index("--draft-tokens") + 1], "auto")
        self.assertIn("--lm-head-draft", argv)
        self.assertEqual(argv[argv.index("--ngram-draft-tokens") + 1], "auto")
        self.assertIn("--embedding-host", argv)
        self.assertEqual(argv[argv.index("--host-context-mib") + 1], "4096")
        self.assertIn("--chat-template", argv)
        self.assertIn("--preserve-thinking", argv)
        self.assertIn("--tolerant-tool-calls", argv)
        self.assertIn("--vision", argv)
        self.assertNotIn("--ngram-volume", argv)

    def test_flash_next_server_argv_includes_ngram_drafter_and_exclusive_layout(self):
        argv = infernix_backend.server_argv(self.cfg, MFN, 262144)
        self.assertEqual(argv[argv.index("--ngram-volume") + 1], str(infernix_backend.ngram_volume_path(self.cfg, MFN)))
        self.assertEqual(argv[argv.index("--draft-model") + 1], str(infernix_backend.draft_model_path(self.cfg, MFN)))
        self.assertEqual(argv[argv.index("--expert-ram-layout") + 1], "exclusive")
        self.assertEqual(argv[argv.index("--host-context-mib") + 1], "2048")
        self.assertNotIn("--kv-capacity", argv)
        self.assertNotIn("--embedding-host", argv)

    def test_missing_files_are_named_by_prepare(self):
        infernix_backend.server_exe(self.cfg).unlink()
        infernix_backend.draft_model_path(self.cfg, MFN).unlink()
        with self.assertRaises(RuntimeError) as raised:
            infernix_backend.prepare(self.cfg, MFN, 262144)
        message = str(raised.exception)
        self.assertIn("the Infernix server", message)
        self.assertIn("the DFlash2 drafter", message)

    def test_monitor_probe_distinguishes_active_and_background_requests(self):
        def fake_get(payload, status=200):
            return SimpleNamespace(status_code=status, json=lambda: payload)

        with patch("requests.get", return_value=fake_get({"requests": [{"phase": "decode", "background": False}]})):
            self.assertTrue(infernix_backend.slots_processing(self.cfg))
        with patch("requests.get", return_value=fake_get({"requests": [{"phase": "prefill", "background": True}]})):
            self.assertFalse(infernix_backend.slots_processing(self.cfg))
        with patch("requests.get", return_value=fake_get({"requests": []})):
            self.assertFalse(infernix_backend.slots_processing(self.cfg))
        with patch("requests.get", return_value=fake_get({}, status=503)):
            self.assertIsNone(infernix_backend.slots_processing(self.cfg))

    def test_owns_process_checks_name_executable_and_port(self):
        exe = infernix_backend.server_exe(self.cfg)
        good = SimpleNamespace(
            name=lambda: exe.name,
            exe=lambda: str(exe),
            cmdline=lambda: [str(exe), "model.infernix", "--port", "8080"],
        )
        wrong_port = SimpleNamespace(
            name=lambda: exe.name,
            exe=lambda: str(exe),
            cmdline=lambda: [str(exe), "model.infernix", "--port", "9999"],
        )
        wrong_name = SimpleNamespace(
            name=lambda: "llama-server.exe",
            exe=lambda: str(exe),
            cmdline=lambda: [str(exe), "--port", "8080"],
        )
        self.assertTrue(infernix_backend.owns_process(self.cfg, M27, good))
        self.assertFalse(infernix_backend.owns_process(self.cfg, M27, wrong_port))
        self.assertFalse(infernix_backend.owns_process(self.cfg, M27, wrong_name))

    def test_servermgmt_refuses_infernix_on_non_blackwell_before_downloads(self):
        with patch.object(hardware, "detect_hardware", return_value=ADA_24), \
             patch.object(infernix_runtime, "ensure_runtime", side_effect=AssertionError("must not download")), \
             self.assertRaisesRegex(RuntimeError, "Requires NVIDIA RTX 50-series"):
            servermgmt.start(self.cfg, M27)

    def test_servermgmt_launches_infernix_on_blackwell_and_records_backend(self):
        class FakeProc:
            def __init__(self, argv, **kwargs):
                self.argv, self.kwargs = list(argv), kwargs
                self.pid = 43210
                self.returncode = None

            def poll(self):
                return self.returncode

            def kill(self):
                self.returncode = -9

            def wait(self, timeout=None):
                return 0

        launched = []
        contained = []

        def fake_popen(argv, **kwargs):
            proc = FakeProc(argv, **kwargs)
            launched.append(proc)
            return proc

        with patch.object(hardware, "detect_hardware", return_value=BLACKWELL_32), \
             patch.object(gpu, "vram_total_gb", return_value=32.0), \
             patch.object(servermgmt, "health", return_value=False), \
             patch.object(servermgmt, "wait_health", return_value=True), \
             patch.object(servermgmt, "vram_str", return_value="GPU VRAM: 28.0 / 32.0 GB"), \
             patch.object(Config, "model_ready", return_value=True), \
             patch.object(infernix_runtime, "ensure_runtime") as ensure_rt, \
             patch.object(infernix_runtime, "prepare_model") as prep_model, \
             patch("harness.winjob.contain", side_effect=contained.append), \
             patch("subprocess.Popen", side_effect=fake_popen):
            rc = servermgmt.start(self.cfg, M27)
        for proc in launched:
            proc.returncode = 0
        self.assertEqual(rc, 0)
        ensure_rt.assert_called_once()
        prep_model.assert_called_once()
        self.assertEqual(len(launched), 1)
        self.assertEqual(launched[0].kwargs["stdin"], subprocess.DEVNULL)
        self.assertEqual(len(contained), 1)
        run = json.loads((self.cfg.path("paths.runtime_dir") / "model-run.json").read_text(encoding="utf-8"))
        self.assertEqual(run["backend"], "infernix")
        self.assertEqual(run["model"], M27)

    def test_record_allocation_failure_reads_infernix_log(self):
        self.cfg.data["default_model"] = M27
        log = infernix_backend.server_log(self.cfg)
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text("FATAL: CUDA out of device memory; model does not fit\n", encoding="utf-8")
        (self.cfg.path("paths.runtime_dir") / "model-run.json").write_text(
            json.dumps({"model": M27, "backend": "infernix", "context": 262144, "log_offset": 0}),
            encoding="utf-8",
        )
        servermgmt.record_allocation_failure(self.cfg)
        failure = servermgmt.last_failure(self.cfg)
        self.assertEqual(failure.get("code"), "vram_pressure")
        self.assertEqual(failure.get("model"), M27)


class InfernixRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.cfg = Config(copy.deepcopy(load_config().data), self.root)
        exe_name = "infernix-serve.exe" if infernix_backend.WINDOWS else "infernix-serve"
        self.archive_bytes = zip_bytes({
            f"infernix-2026.11.20-windows-x64/{exe_name}": b"binary",
            "infernix-2026.11.20-windows-x64/chat_templates/qwen3_8.jinja": b"template",
        })
        self.spec = {
            **infernix_runtime.ENGINE,
            "sha256": hashlib.sha256(self.archive_bytes).hexdigest(),
        }
        self.cache = self.cfg.path("paths.runtime_dir") / "runtime-archives" / f"infernix-{infernix_runtime.VERSION}"
        self.cache.mkdir(parents=True)
        (self.cache / self.spec["name"]).write_bytes(self.archive_bytes)

    def tearDown(self):
        self.temp.cleanup()

    def test_install_stages_validates_and_swaps_in(self):
        phases = []
        with patch.object(infernix_runtime, "ENGINE", self.spec), \
             patch.object(infernix_runtime, "validate_runtime") as validate:
            target = infernix_runtime.install(self.cfg, progress=lambda *_: None, on_phase=phases.append)
        validate.assert_called_once()
        self.assertEqual(target, infernix_backend.program_dir(self.cfg))
        self.assertTrue(infernix_backend.server_exe(self.cfg).is_file())
        self.assertTrue(infernix_backend.chat_template_path(self.cfg, M27).is_file())
        self.assertEqual(phases, ["downloading", "preparing"])
        self.assertTrue(infernix_runtime.runtime_current(self.cfg, M27))
        self.assertEqual(infernix_runtime.installed_record(self.cfg)["version"], infernix_runtime.VERSION)

    def test_bundled_offline_archive_needs_no_internet(self):
        bundled = self.root / "runtime" / "infernix-offline"
        bundled.mkdir(parents=True)
        (self.cache / self.spec["name"]).rename(bundled / self.spec["name"])
        with patch.object(infernix_runtime, "ENGINE", self.spec), \
             patch.object(infernix_runtime, "BUNDLED", bundled), \
             patch.object(infernix_runtime, "validate_runtime"), \
             patch("requests.get", side_effect=AssertionError("no download")):
            infernix_runtime.install(self.cfg, progress=lambda *_: None)
        self.assertTrue(infernix_runtime.runtime_current(self.cfg, M27))

    def test_path_traversal_in_zip_is_rejected_before_writing(self):
        bad = self.root / "bad.zip"
        bad.write_bytes(zip_bytes({
            "top/ok.dll": b"ok",
            "top/../../escaped.dll": b"bad",
        }))
        stage = self.root / "stage"
        stage.mkdir()
        with self.assertRaises(ValueError):
            infernix_runtime._extract_stripped(bad, stage)
        self.assertFalse((self.root / "escaped.dll").exists())
        self.assertFalse((stage / "ok.dll").exists())

    def test_prepare_model_fetches_flash_next_dflash2_companion(self):
        calls = []
        with patch("harness.model_files.model_ready", return_value=False), \
             patch("harness.model_files.download_pinned_model", side_effect=lambda root, spec, **kw: calls.append((root, spec))):
            infernix_runtime.prepare_model(self.cfg, MFN, progress=lambda *_: None)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0], self.cfg.model_root(MFN))
        self.assertEqual(calls[0][1]["download_dir"], "flash-next-dflash2")

    def test_offline_backup_collects_infernix_runtime_and_models(self):
        from scripts import offline_backup
        inst = InfernixInstallation()
        self.addCleanup(inst.close)
        sources = offline_backup._runtime_sources(inst.root)
        rels = {rel.as_posix() for _, rel, _ in sources}
        self.assertTrue(any(r.startswith("payload/runtime/infernix/") for r in rels))
        self.assertTrue(any(r.startswith("payload/runtime/models/infernix/") for r in rels))


if __name__ == "__main__":
    unittest.main()
