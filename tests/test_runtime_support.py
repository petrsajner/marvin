"""Model integrity and hardware planning contracts, without downloads or GPU allocation."""
import copy
import hashlib
import copy
import struct
import threading
import zipfile
from types import SimpleNamespace
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from harness.hardware import Hardware
from harness.model_files import download_pinned_model, model_ready, local_model_dir
from harness.runtime_plan import choose_plan, GIB
from harness.config import Config, load_config
from harness.model_switch import ModelSwitchController
from harness.runtime_update import activate_runtime, extract_archive, install_runtime


class ModelFileTests(unittest.TestCase):
    def test_setup_downloads_text_only_models_without_requesting_projectors(self):
        from scripts import download_models
        with tempfile.TemporaryDirectory() as temporary:
            cfg = Config(copy.deepcopy(load_config().data), Path(temporary))
            calls = []
            def download(repo, filename, directory):
                calls.append(filename)
                return directory / filename
            with patch.object(download_models, "load_config", return_value=cfg), \
                 patch.object(download_models, "hf_download", side_effect=download), \
                 patch("sys.argv", ["download_models.py", "--models", "nemotron_q4,nemotron_q5"]):
                self.assertEqual(download_models.main(), 0)
            self.assertEqual(len(calls), 2)
            self.assertTrue(all("mmproj" not in name for name in calls))

    def test_launcher_accepts_complete_flash_only_installation(self):
        from launcher import launcher_app
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            models = root / "runtime/models"
            directory = models / "flash"
            directory.mkdir(parents=True)
            assets = []
            for name, data in (("part.gguf", b"weights"), ("mmproj.gguf", b"vision")):
                (directory / name).write_bytes(data)
                assets.append({"path": name, "size": len(data), "sha256": hashlib.sha256(data).hexdigest()})
            spec = {"repo": "test/model", "revision": "pinned", "download_dir": "flash", "assets": assets}
            download_pinned_model(models, spec, progress=lambda _: None)
            config = SimpleNamespace(data={"paths": {"models_dir": "runtime/models"}, "models": {"flash": spec}})
            with patch.object(launcher_app, "ROOT", root), patch("harness.config.load_config", return_value=config):
                self.assertTrue(launcher_app._check_model_files()[0])
                (directory / "mmproj.gguf").unlink()
                self.assertFalse(launcher_app._check_model_files()[0])

    def test_ranged_transfer_resumes_after_connection_break_and_existing_partial(self):
        import requests
        data = b"abcdefghij"
        spec = {"repo": "test/model", "revision": "pinned", "download_dir": "flash",
                "download_transport": "range", "assets": [{"path": "part.gguf", "size": len(data),
                "sha256": hashlib.sha256(data).hexdigest()}]}
        requested = []
        progress_events = []

        class Response:
            status_code = 206
            def __init__(self, offset):
                self.offset = offset
                self.headers = {"Content-Range": f"bytes {offset}-9/10"}
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
            def raise_for_status(self):
                pass
            def iter_content(self, size):
                if self.offset == 3:
                    yield data[3:5]
                    raise requests.ConnectionError("connection interrupted")
                yield data[self.offset:]

        class Session:
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass
            def get(self, url, *, headers, **kwargs):
                requested.append(headers["Range"])
                return Response(int(headers["Range"].split("=")[1].split("-")[0]))

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            directory = root / "flash"
            directory.mkdir()
            (directory / "part.gguf.marvin.part").write_bytes(data[:3])
            # Free space covers only the remaining seven bytes plus the safety reserve.
            with patch("requests.Session", Session), patch("harness.model_files.time.sleep"), \
                 patch("harness.model_files.shutil.disk_usage", return_value=SimpleNamespace(free=2 * GIB + 7)):
                download_pinned_model(root, spec, progress=lambda _: None,
                                      on_progress=lambda done, total: progress_events.append((done, total)))
            self.assertEqual(requested, ["bytes=3-9", "bytes=5-9"])
            self.assertIn((3, 10), progress_events)
            self.assertEqual(progress_events[-1], (10, 10))
            self.assertEqual((directory / "part.gguf").read_bytes(), data)
            self.assertTrue(model_ready(root, spec))
            self.assertFalse((directory / "part.gguf.marvin.part").exists())

    def test_cancel_during_verification_does_not_publish_receipt(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            data = b"weights"
            (root / "part.gguf").write_bytes(data)
            spec = {"repo": "test/model", "revision": "pinned", "assets": [
                {"path": "part.gguf", "size": len(data), "sha256": hashlib.sha256(data).hexdigest()}]}
            cancel = threading.Event()
            def progress(message):
                if message.startswith("[CHECKSUM]"):
                    cancel.set()
            with self.assertRaises(InterruptedError):
                download_pinned_model(root, spec, progress=progress, should_stop=cancel.is_set)
            self.assertFalse(model_ready(root, spec))
            self.assertEqual((root / "part.gguf").read_bytes(), data)

    def test_small_first_shard_is_valid_only_with_all_verified_assets(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            contents = {"part-1.gguf": b"small metadata", "part-2.gguf": b"weights", "mmproj.gguf": b"vision"}
            spec = {"repo": "test/model", "revision": "pinned", "download_dir": "flash",
                    "assets": [{"path": name, "size": len(data), "sha256": hashlib.sha256(data).hexdigest()}
                               for name, data in contents.items()]}
            calls = []

            def download(**kwargs):
                self.assertEqual(kwargs["revision"], "pinned")
                self.assertFalse(model_ready(root, spec))
                calls.append(kwargs["filename"])
                target = Path(kwargs["local_dir"]) / kwargs["filename"]
                target.write_bytes(contents[kwargs["filename"]])
                return str(target)

            with patch("huggingface_hub.hf_hub_download", side_effect=download):
                download_pinned_model(root, spec, progress=lambda _: None)
                self.assertTrue(model_ready(root, spec))
                download_pinned_model(root, spec, progress=lambda _: None)
            self.assertEqual(calls, list(contents))
            (root / "flash/part-2.gguf").write_bytes(b"WEIGHTS")
            self.assertFalse(model_ready(root, spec))

    def test_bad_checksum_never_marks_model_ready(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            spec = {"repo": "test/model", "revision": "pinned", "download_dir": "flash",
                    "assets": [{"path": "part.gguf", "size": 3, "sha256": hashlib.sha256(b"yes").hexdigest()}]}

            def download(**kwargs):
                target = Path(kwargs["local_dir"]) / kwargs["filename"]
                target.write_bytes(b"bad")
                return str(target)

            with patch("huggingface_hub.hf_hub_download", side_effect=download):
                with self.assertRaisesRegex(RuntimeError, "Checksum mismatch"):
                    download_pinned_model(root, spec, progress=lambda _: None)
            self.assertFalse(model_ready(root, spec))

    def test_model_directory_cannot_escape_root(self):
        with self.assertRaises(ValueError):
            local_model_dir(Path.cwd(), {"download_dir": "../outside"})

    def test_backup_excludes_in_progress_ranges_but_keeps_nested_model_files(self):
        from scripts.offline_backup import _runtime_sources
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            directory = root / "runtime/models/flash"
            directory.mkdir(parents=True)
            (directory / "part-1.gguf").write_bytes(b"metadata")
            (directory / "part-2.gguf.marvin.part").write_bytes(b"unfinished")
            (directory / ".marvin-verified.json").write_text("{}")
            names = {source.name for source, _, _ in _runtime_sources(root)}
            self.assertEqual(names, {"part-1.gguf", ".marvin-verified.json"})


class RuntimePlanTests(unittest.TestCase):
    def test_insufficient_hardware_is_rejected_before_the_large_download(self):
        from harness import servermgmt
        from harness.model_catalog import FLASH_NEXT_Q3
        with tempfile.TemporaryDirectory() as temporary:
            data = copy.deepcopy(load_config().data)
            data["models"]["flash_next_q3"] = copy.deepcopy(FLASH_NEXT_Q3)
            data["default_model"] = "flash_next_q3"
            cfg = Config(data, Path(temporary))
            with patch("harness.servermgmt.health", return_value=False), \
                 patch("harness.runtime_plan.detect_hardware", return_value=self.hardware(ram=12)), \
                 patch("harness.model_files.download_pinned_model") as download:
                with self.assertRaisesRegex(RuntimeError, "system memory"):
                    servermgmt.start(cfg)
                download.assert_not_called()

    def test_layout_hint_is_bound_to_the_exact_download_manifest(self):
        from harness.runtime_plan import inspect_layout
        from harness.model_catalog import FLASH_NEXT_Q3
        with tempfile.TemporaryDirectory() as temporary:
            spec = copy.deepcopy(FLASH_NEXT_Q3)
            self.assertEqual(len(inspect_layout(Path(temporary), spec)["expert_layer_bytes"]), 48)
            spec["revision"] = "different-model-revision"
            with self.assertRaisesRegex(RuntimeError, "complete model"):
                inspect_layout(Path(temporary), spec)

    def hardware(self, total=32, free=30, ram=56):
        return Hardware("hybrid", 20, 20, tuple(range(8)), tuple(range(20)),
                        64 * GIB, ram * GIB, "GPU", "id", "driver", total * GIB, free * GIB)

    def layout(self):
        return {"common_bytes": 3 * GIB, "projector_bytes": GIB,
                "lazy_bytes": 27 * GIB, "expert_layer_bytes": [GIB] * 48}

    def test_cpu_pools_respect_hybrid_topology_without_halving_threads(self):
        plan = choose_plan(self.hardware(), self.layout(), 131072)
        self.assertEqual((plan.threads, plan.batch_threads), (8, 8))
        self.assertEqual(plan.args.count("0xff"), 2)

    def test_smaller_gpu_moves_more_expert_layers_to_cpu(self):
        large = choose_plan(self.hardware(), self.layout(), 131072)
        small = choose_plan(self.hardware(16, 14, 60), self.layout(), 131072)
        self.assertGreater(small.cpu_expert_layers, large.cpu_expert_layers)
        self.assertEqual(small.context, 131072)

    def test_larger_context_is_reserved_before_placing_experts(self):
        small = choose_plan(self.hardware(), self.layout(), 131072)
        large = choose_plan(self.hardware(), self.layout(), 262144)
        self.assertGreaterEqual(large.cpu_expert_layers, small.cpu_expert_layers)

    def test_insufficient_ram_and_sub_128k_are_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "system memory"):
            choose_plan(self.hardware(ram=12), self.layout(), 131072)
        with self.assertRaises(ValueError):
            choose_plan(self.hardware(), self.layout(), 32768)

    def test_manual_vram_cannot_invent_a_larger_card(self):
        hw = self.hardware(16, 14, 60)
        normal = choose_plan(hw, self.layout(), 131072)
        overridden = choose_plan(hw, self.layout(), 131072, vram_limit=96)
        self.assertEqual(normal.cpu_expert_layers, overridden.cpu_expert_layers)

    def test_available_memory_is_not_part_of_stable_hardware_identity(self):
        self.assertEqual(self.hardware(free=30).fingerprint(), self.hardware(free=20).fingerprint())


class RuntimeUpdateTests(unittest.TestCase):
    def test_failed_activation_restores_previous_directory(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target, stage = root / "llama", root / "stage"
            target.mkdir()
            stage.mkdir()
            (target / "old.exe").write_bytes(b"old runtime")
            rename = Path.rename
            def failing_rename(path, destination):
                if path == stage:
                    raise PermissionError("simulated activation failure")
                return rename(path, destination)
            with patch.object(Path, "rename", failing_rename), self.assertRaises(PermissionError):
                activate_runtime(stage, target)
            self.assertEqual((target / "old.exe").read_bytes(), b"old runtime")
            self.assertTrue(stage.is_dir())
            self.assertEqual(list(root.glob("llama-previous-*")), [])

    def test_invalid_runtime_never_replaces_installed_copy(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "llama"
            target.mkdir()
            (target / "llama-server.exe").write_bytes(b"installed runtime")
            cache = root / "runtime-archives/b10935"
            cache.mkdir(parents=True)
            archive = cache / "fake.zip"
            with zipfile.ZipFile(archive, "w") as package:
                package.writestr("llama-server.exe", b"new but invalid")
            asset = ("fake.zip", "fake.zip", hashlib.sha256(archive.read_bytes()).hexdigest())
            with patch("harness.runtime_update.ASSETS", (asset,)), \
                 patch("harness.runtime_update.validate_runtime", side_effect=RuntimeError("bad runtime")), \
                 self.assertRaisesRegex(RuntimeError, "bad runtime"):
                install_runtime(target, root)
            self.assertEqual((target / "llama-server.exe").read_bytes(), b"installed runtime")
            self.assertEqual(list(root.glob("llama-stage-*")), [])

    def test_archive_path_escape_is_rejected_before_extraction(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / "bad.zip"
            with zipfile.ZipFile(archive, "w") as package:
                package.writestr("valid.dll", b"ok")
                package.writestr("../outside.dll", b"bad")
            with self.assertRaises(ValueError):
                extract_archive(archive, root / "stage")
            self.assertFalse((root / "outside.dll").exists())
            self.assertFalse((root / "stage/valid.dll").exists())


class SwitchingPreparationTests(unittest.TestCase):
    def test_cancelled_download_does_not_load_obsolete_target(self):
        entered = threading.Event()
        loaded = []
        callbacks = []
        def ensure(cfg, key, *, cancelled):
            if key == "q5":
                entered.set()
                for _ in range(200):
                    if cancelled():
                        raise InterruptedError("cancelled transfer")
                    threading.Event().wait(.005)
                self.fail("Transfer did not receive cancellation")
            loaded.append(key)
            return True
        controller = ModelSwitchController(load_config(), ensure_fn=ensure,
            stop_fn=lambda *args, **kwargs: True, running_fn=lambda *args: False)
        controller.request("q5", on_success=callbacks.append)
        self.assertTrue(entered.wait(1))
        controller.request("q4", on_success=callbacks.append)
        self.assertTrue(controller.wait(3))
        self.assertEqual(loaded, ["q4"])
        self.assertEqual(callbacks, ["q4"])
        self.assertEqual(controller.snapshot().status, "ready")

    def test_failed_new_model_restores_previous_profile(self):
        calls, restored = [], []
        def ensure(cfg, key):
            calls.append((key, cfg.kv_cache_mode(key)))
            return key == "q4"
        cfg = load_config()
        controller = ModelSwitchController(cfg, ensure_fn=ensure,
            stop_fn=lambda *args, **kwargs: True, running_fn=lambda *args: False)
        controller.request("q4", kv_profile="q8_0")
        self.assertTrue(controller.wait(2))
        controller.request("q5", on_failure=restored.append)
        self.assertTrue(controller.wait(2))
        self.assertEqual(controller.snapshot().status, "failed")
        self.assertEqual(restored, ["q4"])
        self.assertEqual(calls[-1], ("q4", "q8_0"))
        self.assertEqual(controller.cfg.model_key(), "q4")
        self.assertEqual(cfg.model_key(), "q4")

    def test_optional_model_is_not_downloaded_by_automatic_setup(self):
        from harness.gpu import download_keys
        from harness.model_catalog import FLASH_NEXT_Q3
        cfg = load_config()
        cfg.data["models"]["flash_next_q3"] = copy.deepcopy(FLASH_NEXT_Q3)
        self.assertNotIn("flash_next_q3", download_keys(cfg, None))
        self.assertNotIn("flash_next_q3", download_keys(cfg, 32))
        cfg.data["default_model"] = "flash_next_q3"
        self.assertIn("flash_next_q3", download_keys(cfg, 32))

    def test_stop_without_owned_pid_does_not_kill_other_servers(self):
        from harness import servermgmt
        with tempfile.TemporaryDirectory() as temporary:
            cfg = load_config()
            cfg.data["paths"]["runtime_dir"] = temporary
            with patch("psutil.process_iter", side_effect=AssertionError("Must not scan other processes")):
                self.assertTrue(servermgmt.stop(cfg, quiet=True))


class GGUFHeaderTests(unittest.TestCase):
    def test_reads_tensor_sizes_without_loading_payload(self):
        from harness.gguf_metadata import read_header
        def string(value):
            encoded = value.encode()
            return struct.pack("<Q", len(encoded)) + encoded
        header = b"GGUF" + struct.pack("<IQQ", 3, 2, 0)
        for name, offset in (("first.weight", 0), ("second.weight", 64)):
            header += string(name) + struct.pack("<I Q I Q", 1, 16, 0, offset)
        header += b"\0" * ((-len(header)) % 32)
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "sample.gguf"
            path.write_bytes(header + b"\0" * 128)
            parsed = read_header(path)
            self.assertEqual([item["bytes"] for item in parsed["tensors"]], [64, 64])
            path.write_bytes(header + b"\0" * 63)
            with self.assertRaises(ValueError):
                read_header(path)


if __name__ == "__main__":
    unittest.main()
