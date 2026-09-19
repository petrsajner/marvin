"""Memory transitions, rollback and pressure recovery without GPU allocation."""
import copy
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from harness import gpu, servermgmt
from harness.agent import Agent, Status, StepResult
from harness.application import ApplicationService
from harness.config import Config, load_config
from harness.model_switch import ModelSwitchController
from harness.runtime_plan import choose_plan, GIB
from harness.web_api import create_app
from tests import test_workspace as helpers


class MemoryProfileTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        data = copy.deepcopy(load_config().data)
        data["hardware"]["vram_gb"] = 32
        data["agent"].update(workspace=None, autonomy="auto")
        data["work_mode"] = "discussion"
        self.cfg = Config(data, self.root)
        self.app = ApplicationService(self.cfg, llm_factory=helpers.Model, manage_model=False)

    def tearDown(self):
        self.app.close()
        self.app.models.wait(3)
        self.temp.cleanup()

    def test_budget_cannot_invent_vram_and_rejects_invalid_values(self):
        self.cfg.data["hardware"]["vram_gb"] = 96
        with patch.object(gpu, "vram_total_gb", return_value=16):
            self.assertEqual(gpu.effective_vram_gb(self.cfg), 16)
        for value in (True, False, 0, -1, float("nan"), float("inf"), "unknown", None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                gpu.normalize_vram_setting(value)

    def test_manual_cap_has_same_plan_as_a_physically_smaller_gpu(self):
        from harness.hardware import Hardware
        layout = {"common_bytes": 3 * GIB, "projector_bytes": GIB,
                  "lazy_bytes": 27 * GIB, "expert_layer_bytes": [GIB] * 48}
        big = Hardware("CPU", 8, 8, tuple(range(8)), tuple(range(8)),
                       96 * GIB, 80 * GIB, "GPU", "id", "driver", 32 * GIB, 30 * GIB)
        from dataclasses import replace
        for cap in (16, 24):
            physical = choose_plan(replace(big, vram_total=cap * GIB, vram_available=(cap - 2) * GIB), layout, 131072)
            limited = choose_plan(big, layout, 131072, vram_limit=cap)
            self.assertEqual(physical.cpu_expert_layers, limited.cpu_expert_layers)
            self.assertEqual(physical.estimated_gpu_bytes, limited.estimated_gpu_bytes)
            self.assertEqual(limited.vram_budget_bytes, cap * GIB)
            self.assertEqual(limited.required_available_ram_bytes, 0)

    def test_old_installed_config_gets_corrected_profiles_without_file_rewrite(self):
        path = self.root / "config.yaml"
        source = "models:\n  q5:\n    kv_cache_profiles:\n      f16: {ctx_size: 98304, min_vram_gb: 24}\n  q3:\n    kv_cache_profiles:\n      q8_0: {ctx_size: 49152, min_vram_gb: 15}\n"
        path.write_text(source)
        cfg = load_config(path)
        self.assertEqual(cfg.kv_cache_profiles("q5")["f16"]["min_vram_gb"], 25.441)
        self.assertEqual(cfg.kv_cache_profiles("q3")["q8_0"]["min_vram_gb"], 13.008)
        self.assertIn("q8_0_compact", cfg.kv_cache_profiles("q5"))
        self.assertEqual(path.read_text(), source)

    def test_budget_switch_back_restores_the_saved_model_and_context(self):
        self.app.preferences.update(model="q3", vram_gb=16, memory_presets={
            "auto": {"model": "nemotron_q5", "profile": "q8_0_256k", "requested_profile": "q8_0_256k"}})
        self.app.manage_model = True
        try:
            with patch.object(gpu, "vram_total_gb", return_value=32), patch.object(self.app.models, "request", return_value=True) as request:
                client = TestClient(create_app(self.cfg, service=self.app))
                response = client.patch("/api/settings", json={"vram_gb": "auto"})
                response.raise_for_status()
                self.assertEqual(response.json()["model"], "nemotron_q5")
                self.assertEqual(request.call_args.kwargs["kv_profile"], "q8_0_256k")
                self.assertFalse(request.call_args.kwargs["restart"])
        finally:
            self.app.manage_model = False

    def test_vram_change_selects_compatible_base_model_and_profile(self):
        self.app.manage_model = True
        try:
            with patch.object(gpu, "vram_total_gb", return_value=32), \
                 patch.object(self.app.models, "request", return_value=True) as request:
                client = TestClient(create_app(self.cfg, service=self.app))
                response = client.patch("/api/settings", json={"model": "q5", "vram_gb": 16})
                response.raise_for_status()
                self.assertEqual(response.json()["model"], "q3")
                self.assertEqual(request.call_args.args[0], "q3")
                self.assertEqual(request.call_args.kwargs["config"].data["hardware"]["vram_gb"], 16)
                state = client.get("/api/state").json()
                self.assertNotIn("q5", [m["id"] for m in state["models"]])
                self.assertEqual(client.patch("/api/settings", json={"vram_gb": "invalid"}).status_code, 400)
                self.assertEqual(self.app.preferences["vram_gb"], 16)
        finally:
            self.app.manage_model = False

    def test_changed_hardware_never_takes_already_running_shortcut(self):
        calls = []
        controller = ModelSwitchController(self.cfg, running_fn=lambda *_: True,
            stop_fn=lambda *a, **k: calls.append("stop") or True,
            ensure_fn=lambda cfg, key: calls.append(cfg.data["hardware"]["vram_gb"]) or True)
        changed = Config(copy.deepcopy(self.cfg.data), self.root)
        changed.data["hardware"]["vram_gb"] = 24
        controller.request(changed.model_key(), config=changed)
        self.assertTrue(controller.wait(2))
        self.assertEqual(calls, ["stop", 24])

    def test_unreleased_previous_process_prevents_new_allocation(self):
        with patch("harness.model_switch.servermgmt.health", return_value=False):
            controller = ModelSwitchController(self.cfg, stop_fn=lambda *a, **k: False,
                running_fn=lambda *_: False, ensure_fn=lambda *_: self.fail("New model started before release"))
            controller.request("q4")
            self.assertTrue(controller.wait(2))
            self.assertEqual(controller.snapshot().status, "failed")

    def test_restart_seeds_rollback_with_last_successful_budget(self):
        self.app.close()
        self.app.preferences.update(model="flash_next_q3", vram_gb=16,
            last_running_model="q4", last_running_kv="q8_0_compact", last_running_vram_gb=24)
        self.app.save_preferences()
        with patch.object(Config, "model_ready", return_value=True):
            self.app = ApplicationService(self.cfg, llm_factory=helpers.Model, manage_model=False)
        calls = []
        self.app.models._stop = lambda *a, **k: True
        self.app.models._running = lambda *_: False
        def ensure(cfg, key, **kwargs):
            calls.append((key, cfg.kv_cache_mode(key), cfg.data["hardware"]["vram_gb"]))
            return key == "q4"
        self.app.models._ensure = ensure
        self.app.start_model()
        self.assertTrue(self.app.models.wait(3))
        self.assertEqual(calls[-1], ("q4", "q8_0_compact", 24))
        self.assertEqual(self.app.preferences["model"], "q4")
        self.assertEqual(self.app.preferences["vram_gb"], 24)
        self.assertEqual(self.app.models.snapshot().restored_model, "q4")

    def test_pressure_recovery_reduces_context_and_does_not_repeat_tools(self):
        self.app.preferences.update(model="flash_next_q3")
        session = self.app.new_session(work_mode="discussion")
        session.add("assistant", "", tool_calls=[{"id": "done", "type": "function",
                    "function": {"name": "write_file", "arguments": "{}"}}])
        session.add("tool", "File already saved", tool_call_id="done", name="write_file")
        calls = []
        def ensure(cfg, key, **kwargs):
            calls.append(cfg.context_size())
            return True
        self.app.models = ModelSwitchController(self.cfg, ensure_fn=ensure,
            stop_fn=lambda *a, **k: True, running_fn=lambda *_: False)
        self.app.manage_model = True
        steps = []
        def step(agent, **kwargs):
            steps.append(agent.cfg.context_size())
            if len(steps) <= 2:
                path = self.cfg.path("paths.runtime_dir") / "model-failure.json"
                path.write_text(json.dumps({"code": "ram_pressure", "model": "flash_next_q3", "time": time.time()}))
                return StepResult(Status.ERROR, text="Connection reset")
            return StepResult(Status.FINAL, text="Recovered")
        try:
            with patch.object(Agent, "step", autospec=True, side_effect=step), \
                 patch.object(servermgmt, "health", return_value=True), \
                 patch.object(servermgmt, "running_model", return_value="flash_next_q3"):
                self.app.submit(session.id, "Continue the work", request_id="pressure")
                helpers.wait_for(lambda: self.app.store.job("pressure")["status"] == "complete" and self.app.active is None)
            self.assertEqual(steps, [262144, 196608, 131072])
            self.assertEqual(calls, [196608, 131072])
            self.assertEqual(len([m for m in session.messages if m.get("tool_call_id") == "done"]), 1)
            self.assertEqual(self.app.preferences["last_running_kv"], "q8_0_128k")
        finally:
            self.app.manage_model = False

    def test_startup_pressure_retries_only_a_smaller_supported_context(self):
        self.cfg.data["default_model"] = "flash_next_q3"
        contexts = []
        def start(cfg, key, **kwargs):
            contexts.append(cfg.context_size())
            if len(contexts) == 1:
                (cfg.path("paths.runtime_dir") / "model-failure.json").write_text(json.dumps({
                    "code": "ram_pressure", "model": key, "error": "Pressure"}))
                raise RuntimeError("Pressure")
            return 0
        with patch.object(servermgmt, "health", return_value=False), patch.object(servermgmt, "start", side_effect=start):
            self.assertTrue(servermgmt.ensure(self.cfg, "flash_next_q3"))
        self.assertEqual(contexts, [262144, 196608])

    def test_approved_menu_is_exact_for_each_card_class(self):
        expected = {
            # Approved on 2026-09-19 after measuring a 16 GB budget: a two-bit
            # quant buys either the vision projector back on the card or twice
            # the context, and quantising only the value half costs a gigabyte.
            16: {"q2": {"q8_0": ["128k", "96k", "64k"], "q4_0": ["192k"]},
                 "q3": {"q8_0": ["64k", "48k"], "q8_0/q4_0": ["96k"], "q4_0": ["128k"]}},
            24: {"q3": {"q8_0": ["128k", "96k"]},
                 "q4": {"q8_0": ["96k", "96k·MTP", "64k", "64k·MTP"]},
                 "q5": {"q8_0": ["96k", "64k"]},
                 "nemotron_q4": {"q8_0": ["512k", "256k"]},
                 "nemotron_q5": {"q8_0": ["512k", "256k"]}},
            32: {"q2": {"q8_0": ["256k"]},
                 "q4": {"q8_0": ["256k", "256k·MTP", "192k", "192k·MTP"], "f16": ["128k", "96k"]},
                 "q5": {"q8_0": ["192k", "192k·MTP", "128k", "128k·MTP"], "f16": ["128k", "96k"]},
                 "ornith_q5": {"q8_0": ["256k", "192k"]},
                 "nemotron_q4": {"q8_0": ["512k", "256k"]},
                 "nemotron_q5": {"q8_0": ["512k", "256k"]}},
        }
        for capacity, table in expected.items():
            actual = {}
            for key in self.cfg.data["models"]:
                if self.cfg.model(key).get("adaptive_runtime"):
                    continue
                for profile in gpu.offered_profiles(self.cfg, key, capacity - .16).values():
                    context = f"{profile['ctx_size'] // 1024}k" + ("·MTP" if profile.get("speculative") else "")
                    # Keys and values can differ, and a menu that merged them
                    # would hide the difference this table exists to record.
                    cache = profile["cache_type"]
                    if profile.get("value_cache_type"):
                        cache += "/" + profile["value_cache_type"]
                    actual.setdefault(key, {}).setdefault(cache, []).append(context)
            for groups in actual.values():
                for contexts in groups.values():
                    contexts.sort(key=lambda c: (-int(c.split("k")[0]), "MTP" in c))
            self.assertEqual(actual, table)
        self.assertFalse(gpu.offered_profiles(self.cfg, "q3", 96))

    def test_mtp_recovery_ladder_drops_the_draft_before_the_context(self):
        self.cfg.data["default_model"] = "q5"
        self.cfg.set_kv_cache_mode("q5", "q8_0_mtp")
        self.assertEqual(gpu.lower_memory_profiles(self.cfg, "q5"),
                         ["q8_0", "q8_0_128k_mtp", "q8_0_128k"])
        # After the first step the session still interleaves MTP variants.
        self.cfg.data["_recovery_origin_mtp"] = {"q5": True}
        self.cfg.set_kv_cache_mode("q5", "q8_0")
        self.assertEqual(gpu.lower_memory_profiles(self.cfg, "q5"),
                         ["q8_0_128k_mtp", "q8_0_128k"])
        # Plain selections never gain MTP during recovery.
        self.cfg.data["_recovery_origin_mtp"] = {}
        self.assertEqual(gpu.lower_memory_profiles(self.cfg, "q5"), ["q8_0_128k"])

    def test_startup_recovery_walks_the_mtp_ladder(self):
        self.cfg.data["default_model"] = "q5"
        self.cfg.set_kv_cache_mode("q5", "q8_0_mtp")
        selected = []

        def start(cfg, key, **kwargs):
            selected.append(cfg.kv_cache_mode(key))
            if len(selected) < 3:
                (cfg.path("paths.runtime_dir") / "model-failure.json").write_text(json.dumps({
                    "code": "vram_pressure", "model": key, "error": "Pressure"}))
                raise RuntimeError("Pressure")
            return 0

        with patch.object(servermgmt, "health", return_value=False), patch.object(servermgmt, "start", side_effect=start):
            self.assertTrue(servermgmt.ensure(self.cfg, "q5"))
        self.assertEqual(selected, ["q8_0_mtp", "q8_0", "q8_0_128k_mtp"])
        self.assertEqual(self.cfg.data["_recovery_origin_mtp"], {"q5": True})

    def test_best_fit_prefers_plain_profiles_over_mtp_twins(self):
        self.cfg.data["default_model"] = "q5"
        self.assertEqual(gpu.best_fit(self.cfg, 31.8), ("q5", "q8_0"))
        self.cfg.data["default_model"] = "q4"
        self.assertEqual(gpu.best_fit(self.cfg, 31.8), ("q4", "q8_0"))

    def test_speculative_profiles_pair_with_measured_plain_twins(self):
        for key in ("q4", "q5"):
            profiles = self.cfg.kv_cache_profiles(key)
            for name, values in profiles.items():
                if values.get("speculative") != "mtp":
                    continue
                twins = [v for v in profiles.values() if not v.get("speculative")
                         and v["ctx_size"] == values["ctx_size"]
                         and v["cache_type"] == values["cache_type"]]
                self.assertEqual(len(twins), 1, name)
                self.assertEqual(values["gpu_class"], twins[0]["gpu_class"], name)
                self.assertEqual(values["server_args"], twins[0]["server_args"], name)
                self.assertGreater(values["min_vram_gb"], twins[0]["min_vram_gb"], name)
                self.assertTrue(values["label"].endswith(" · MTP"), name)
                self.assertNotIn("--spec-type", values["server_args"], name)
        # Qwen IQ3 keeps no speculative variants.
        self.assertFalse([n for n in self.cfg.kv_cache_profiles("q3") if "mtp" in n])
        # The 24 GiB class offers MTP only where the measured allocation fits.
        self.assertEqual([n for n, v in self.cfg.kv_cache_profiles("q5").items()
                          if v.get("speculative") and v["gpu_class"] == 24], [])

    def test_mtp_draft_args_download_and_verification(self):
        draft = self.cfg.mtp_draft_file()
        draft.parent.mkdir(parents=True, exist_ok=True)
        draft.write_bytes(b"gguf")
        with patch("harness.model_files.download_pinned_model") as download, \
             patch.object(Config, "mtp_draft_ready", return_value=False):
            download.side_effect = lambda models_dir, spec, **kwargs: models_dir
            args = servermgmt._mtp_draft_args(self.cfg)
        self.assertEqual(download.call_count, 1)
        self.assertEqual(args[:2], ["--spec-type", "draft-mtp"])
        self.assertEqual(args[3], str(draft))
        # An already verified draft is not downloaded again.
        with patch("harness.model_files.download_pinned_model") as download, \
             patch.object(Config, "mtp_draft_ready", return_value=True):
            self.assertEqual(servermgmt._mtp_draft_args(self.cfg), args)
        self.assertFalse(download.called)
        # A draft that cannot be produced is a hard error.
        draft.unlink()
        with patch.object(Config, "mtp_draft_ready", return_value=True):
            with self.assertRaisesRegex(RuntimeError, "MTP draft"):
                servermgmt._mtp_draft_args(self.cfg)

    def test_runtime_reports_running_profile_with_speculative_flag(self):
        self.app.models.cfg.set_kv_cache_mode("q5", "q8_0_mtp")
        try:
            with patch.object(servermgmt, "server_state", return_value="running"), \
                 patch.object(servermgmt, "running_model", return_value="q5"), \
                 patch.object(servermgmt, "vram_value", return_value="28.5 GB"):
                client = TestClient(create_app(self.cfg, service=self.app))
                profile = client.get("/api/runtime").json()["profile"]
        finally:
            self.app.models.cfg.set_kv_cache_mode("q5", "q8_0")
        self.assertEqual(profile["id"], "q8_0_mtp")
        self.assertEqual(profile["label"], "Q8 · 192k · MTP")
        self.assertTrue(profile["speculative"])

    def test_fallback_keeps_precision_class_and_placement(self):
        from harness.measured_profiles import freeze_placement
        for key, model in self.cfg.data["models"].items():
            for name, values in self.cfg.kv_cache_profiles(key).items():
                self.cfg.data.pop("_recovery_placement", None)
                self.cfg.data["default_model"] = key
                self.cfg.set_kv_cache_mode(key, name)
                for index, lower in enumerate(gpu.lower_memory_profiles(self.cfg)):
                    target = self.cfg.kv_cache_profiles(key)[lower]
                    self.assertEqual(target.get("cache_type"), values.get("cache_type"))
                    self.assertEqual(target.get("gpu_class"), values.get("gpu_class"))
                    if values.get("speculative") and index == 0:
                        # The first MTP recovery step drops the draft at the same context.
                        self.assertEqual(target["ctx_size"], values["ctx_size"])
                        self.assertFalse(target.get("speculative"))
                    else:
                        self.assertLess(target["ctx_size"], values["ctx_size"])
                freeze_placement(self.cfg)
                self.assertEqual(self.cfg.data["_recovery_placement"]["server_args"], values.get("server_args", []))
        self.cfg.data.pop("_recovery_placement", None)
        self.cfg.data["default_model"] = "nemotron_q5"
        self.cfg.set_kv_cache_mode("nemotron_q5", "q8_0_512k_spill")
        freeze_placement(self.cfg)
        self.cfg.set_kv_cache_mode("nemotron_q5", "q8_0_256k_spill")
        self.assertIn("21", self.cfg.data["_recovery_placement"]["server_args"])

    def test_flash_reclaims_ram_and_freezes_experts_during_recovery(self):
        from dataclasses import replace
        from harness.hardware import Hardware
        from harness.model_catalog import FLASH_NEXT_Q3
        layout = FLASH_NEXT_Q3["layout_hint"]["layout"]
        hw = Hardware("hybrid", 20, 20, tuple(range(8)), tuple(range(20)),
                      64 * GIB, 2 * GIB, "GPU", "id", "driver", int(31.84 * GIB), int(29.4 * GIB))
        large = choose_plan(hw, layout, 262144)
        small = choose_plan(hw, layout, 196608, cpu_expert_layers=large.cpu_expert_layers)
        self.assertEqual(large.cpu_expert_layers, 32)
        self.assertEqual(small.cpu_expert_layers, 32)
        self.assertAlmostEqual(large.estimated_gpu_bytes / GIB, 29.250, places=3)
        self.assertAlmostEqual(large.estimated_host_bytes / GIB, 41.394, places=3)
        self.assertLess(small.estimated_gpu_bytes, large.estimated_gpu_bytes)
        self.assertIn("256", large.args)
        with self.assertRaises(RuntimeError):
            choose_plan(replace(hw, ram_total=16 * GIB), layout, 131072)
        with self.assertRaisesRegex(RuntimeError, "qualification"):
            choose_plan(replace(hw, vram_total=16 * GIB, vram_available=14 * GIB), layout, 262144)

    def test_allocator_detection_ignores_old_launch_logs(self):
        directory = self.cfg.path("paths.runtime_dir")
        log = directory / "llama-server.log"
        old = b"CUDA out of memory\n"
        log.write_bytes(old + b"New launch succeeded\n")
        (directory / "model-run.json").write_text(json.dumps({
            "model": self.cfg.model_key(), "context": 196608, "log_offset": len(old)}))
        servermgmt.record_allocation_failure(self.cfg, "Connection reset")
        self.assertFalse(servermgmt.last_failure(self.cfg))
        servermgmt.record_allocation_failure(self.cfg, "CUDA error: out of memory")
        self.assertEqual(servermgmt.last_failure(self.cfg)["code"], "vram_pressure")


if __name__ == "__main__":
    unittest.main()
