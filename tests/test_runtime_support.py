"""Model integrity and hardware planning contracts, without downloads or GPU allocation."""
import copy
import hashlib
import copy
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
from harness.config import Config, load_config
from harness.model_switch import ModelSwitchController
from harness.runtime_update import activate_runtime, extract_archive, install_runtime

GIB = 1024**3


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

    def test_the_backup_folder_is_renamed_to_the_version_it_holds(self):
        """It was renamed by hand after every release, which is how the pointer
        inside an installation came to name a version that no longer existed."""
        from scripts.offline_backup import _rename_for_version
        with tempfile.TemporaryDirectory() as temporary:
            backup = Path(temporary) / "Marvin-Offline-Backup-1.11.2"
            backup.mkdir()
            renamed = _rename_for_version(backup, "1.12.1")
            self.assertEqual(renamed.name, "Marvin-Offline-Backup-1.12.1")
            self.assertTrue(renamed.is_dir())
            # Already current: left alone rather than touched for nothing.
            self.assertEqual(_rename_for_version(renamed, "1.12.1"), renamed)
            # A folder that is not named after a version keeps its name.
            plain = Path(temporary) / "my backup"
            plain.mkdir()
            self.assertEqual(_rename_for_version(plain, "1.12.1"), plain)

    def test_an_existing_folder_is_never_overwritten_by_the_rename(self):
        from scripts.offline_backup import _rename_for_version
        with tempfile.TemporaryDirectory() as temporary:
            backup = Path(temporary) / "Marvin-Offline-Backup-1.11.2"
            backup.mkdir()
            (backup / "manifest.json").write_text("{}", encoding="utf-8")
            occupied = Path(temporary) / "Marvin-Offline-Backup-1.12.1"
            occupied.mkdir()
            (occupied / "keep-me.txt").write_text("other backup", encoding="utf-8")
            self.assertEqual(_rename_for_version(backup, "1.12.1"), backup)
            self.assertEqual((occupied / "keep-me.txt").read_text(encoding="utf-8"),
                             "other backup")

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

    def test_every_downloaded_program_travels_in_the_backup(self):
        """A machine set up from the backup has to be complete, not complete
        except for the downloads it still has to make. Image generation cannot
        reach its service offline, but the program it needs still belongs here."""
        from scripts.offline_backup import _runtime_sources
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for folder, name in (("models", "weights.gguf"), ("llama", "llama-server.exe"),
                                 ("whisper", "whisper-cli.exe"), ("openart", "openart.exe")):
                directory = root / "runtime" / folder
                directory.mkdir(parents=True)
                (directory / name).write_bytes(b"program")
            collected = {source.name: rel for source, rel, _ in _runtime_sources(root)}
            self.assertIn("openart.exe", collected)
            self.assertEqual(collected["openart.exe"],
                             Path("payload/runtime/openart/openart.exe"),
                             "it has to restore where the harness looks for it")
            for expected in ("weights.gguf", "llama-server.exe", "whisper-cli.exe"):
                self.assertIn(expected, collected)

    def test_flash_next_engine_and_its_shared_shard_travel_once(self):
        """The engine Marvin prepared goes along; the second shard IQ3_S and IQ2_XS share
        is stored once and linked again on restore, and the engine's environment is
        pointed at the restoring installation's Python."""
        import os
        from scripts.offline_backup import create_backup, restore_backup, verify_backup
        with tempfile.TemporaryDirectory() as temporary:
            outer = Path(temporary)
            source = outer / "source"
            models = source / "runtime/models/strata/models"
            (models / "IQ3_S").mkdir(parents=True)
            (models / "IQ2_XS").mkdir()
            (models / "IQ3_S/shard-2.gguf").write_bytes(b"SHARED" * 1000)
            os.link(models / "IQ3_S/shard-2.gguf", models / "IQ2_XS/shard-2.gguf")
            (models / "IQ3_S/shard-1.gguf").write_bytes(b"IQ3" * 100)
            engine = source / "runtime/strata"
            (engine / "engine").mkdir(parents=True)
            (engine / "engine/strata.exe").write_bytes(b"ENGINE")
            (engine / ".venv").mkdir()
            (engine / ".venv/pyvenv.cfg").write_text("home = C:\\Elsewhere\\Python312\nversion = 3.12.9\n")
            (source / "runtime/llama").mkdir(parents=True)
            (source / "runtime/llama/llama-server.exe").write_bytes(b"LLAMA")
            (source / ".venv/Lib/site-packages/example").mkdir(parents=True)
            (source / ".venv/Lib/site-packages/example/__init__.py").write_text("VALUE = 1\n")
            (source / "requirements.txt").write_text("example==1.0\n")
            (source / "version.txt").write_text("test-version\n")
            backup = outer / "backup"
            manifest = create_backup(source, backup)
            linked = [item for item in manifest["files"] if item.get("link_to")]
            self.assertEqual([Path(item["path"]).parent.name for item in linked], ["IQ3_S"])
            self.assertEqual(len(list(backup.rglob("shard-2.gguf"))), 1, "the shared shard is stored once")
            self.assertIn("payload/runtime/strata/engine/strata.exe", {item["path"] for item in manifest["files"]})
            self.assertTrue(verify_backup(backup)["ok"])
            restored = outer / "restored"
            (restored / ".venv/Scripts").mkdir(parents=True)
            (restored / ".venv/Scripts/python.exe").touch()
            (restored / "runtime/python").mkdir(parents=True)
            (restored / "runtime/python/python.exe").touch()
            (restored / "requirements.txt").write_text("example==1.0\n")
            result = restore_backup(restored, backup)
            first = restored / "runtime/models/strata/models/IQ2_XS/shard-2.gguf"
            second = restored / "runtime/models/strata/models/IQ3_S/shard-2.gguf"
            self.assertEqual(second.read_bytes(), b"SHARED" * 1000)
            self.assertTrue(first.samefile(second), "linked again, not copied twice")
            self.assertIn(f"home = {restored / 'runtime/python'}",
                          (restored / "runtime/strata/.venv/pyvenv.cfg").read_text())
            self.assertTrue(result["strata_environment"].startswith("home = "))


class BackupRefreshTests(unittest.TestCase):
    def test_refresh_takes_the_installation_and_sets_stale_payload_aside(self):
        """1.19.0 (owner, 8 October): models and runtimes from the installed copy, the application from the
        repository; the removed llama.cpp Flash-Next moves aside; draft-layer intermediates and excluded
        weights stay out."""
        from scripts.offline_backup import create_backup, refresh_backup, verify_backup
        with tempfile.TemporaryDirectory() as temporary:
            outer = Path(temporary)
            repo, installed = outer / "repo", outer / "installed"
            for root in (repo, installed):
                (root / ".venv/Lib/site-packages/example").mkdir(parents=True)
                (root / ".venv/Lib/site-packages/example/__init__.py").write_text("VALUE = 1\n")
                (root / "requirements.txt").write_text("example==1.0\n")
                (root / "runtime/llama").mkdir(parents=True)
                (root / "runtime/llama/llama-server.exe").write_bytes(b"LLAMA")
                (root / "runtime/models").mkdir(parents=True)
                (root / "runtime/models/q5.gguf").write_bytes(b"Q5")
            (repo / "runtime/models/Qwen3.8-Flash-Next").mkdir()
            (repo / "runtime/models/Qwen3.8-Flash-Next/old.gguf").write_bytes(b"OLD FLASH")
            (repo / "version.txt").write_text("1.18.2\n")
            backup = outer / "backup"
            create_backup(repo, backup)
            (repo / "version.txt").write_text("1.19.0\n")
            (repo / "dist").mkdir()
            (repo / "dist/Marvin-Setup-1.19.0-Full.exe").write_bytes(b"SETUP")
            data = installed / "runtime/models/strata"
            for relative, content in (("models/IQ3_S/shard-1.gguf", b"IQ3"), ("models/IQ2_XS/shard-1.gguf", b"IQ2"),
                                      ("packs/iq3_s/native_experts.txt", b"P"), ("mtp/rt/experts.bin", b"RT"),
                                      ("mtp/tensors/mtp.fc.bin", b"BF16"), ("mtp/mtp-q2_0.gguf", b"PACKED")):
                (data / relative).parent.mkdir(parents=True, exist_ok=True)
                (data / relative).write_bytes(content)
            (installed / "runtime/strata/engine").mkdir(parents=True)
            (installed / "runtime/strata/engine/strata.exe").write_bytes(b"ENGINE")
            quarantine = outer / "set-aside"
            manifest = refresh_backup(repo, backup, runtime_root=installed,
                                      exclude=("strata/models/IQ2_XS",), quarantine=quarantine)
            paths = {item["path"] for item in manifest["files"]}
            self.assertIn("payload/runtime/models/strata/models/IQ3_S/shard-1.gguf", paths)
            self.assertIn("payload/runtime/models/strata/mtp/rt/experts.bin", paths)
            self.assertIn("payload/runtime/strata/engine/strata.exe", paths)
            self.assertFalse(any("IQ2_XS" in p or "/tensors/" in p or p.endswith("mtp-q2_0.gguf") for p in paths))
            self.assertNotIn("payload/runtime/models/Qwen3.8-Flash-Next/old.gguf", paths)
            self.assertEqual((quarantine / "payload/runtime/models/Qwen3.8-Flash-Next/old.gguf").read_bytes(),
                             b"OLD FLASH", "set aside, not deleted")
            self.assertEqual(manifest["app_version"], "1.19.0")
            self.assertTrue(verify_backup(Path(manifest.get("path", backup)))["ok"])


class HardwareIdentityTests(unittest.TestCase):
    def hardware(self, total=32, free=30, ram=56, total_ram=64):
        return Hardware("hybrid", 20, 20, tuple(range(8)), tuple(range(20)),
                        total_ram * GIB, ram * GIB, "GPU", "id", "driver", total * GIB, free * GIB)

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
        from harness.measured_profiles import PROFILES
        from harness.model_catalog import FLASH_NEXT_STRATA
        cfg = load_config()
        cfg.data["models"]["flash_next_strata"] = {**copy.deepcopy(FLASH_NEXT_STRATA),
                                                   "kv_cache_profiles": copy.deepcopy(PROFILES["flash_next_strata"])}
        with patch("harness.gpu.installed_ram_gib", return_value=63.7):
            self.assertNotIn("flash_next_strata", download_keys(cfg, None))
            self.assertNotIn("flash_next_strata", download_keys(cfg, 32))
            cfg.data["default_model"] = "flash_next_strata"
            self.assertIn("flash_next_strata", download_keys(cfg, 32))

    def test_stop_without_owned_pid_does_not_kill_other_servers(self):
        from harness import servermgmt
        with tempfile.TemporaryDirectory() as temporary:
            cfg = load_config()
            cfg.data["paths"]["runtime_dir"] = temporary
            with patch("psutil.process_iter", side_effect=AssertionError("Must not scan other processes")):
                self.assertTrue(servermgmt.stop(cfg, quiet=True))


if __name__ == "__main__":
    unittest.main()
