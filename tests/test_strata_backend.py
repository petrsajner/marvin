"""The Strata backend seam (docs/design/2026-10-05-strata-backend.md, Phase 2), without a process or GPU.

The llama path is pinned separately by tests/test_server_launch.py; these tests
cover what a `backend: strata` model does at the same places.
"""
from __future__ import annotations

import contextlib
import copy
from dataclasses import replace
import io
import json
import mmap
import os
from pathlib import Path
import subprocess
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from harness import servermgmt, strata_backend
from harness.config import Config, load_config
from harness.hardware import Hardware, shared_working_set
GIB = 1024**3

KEY = "flash_next_strata"
IQ2 = "flash_next_strata_iq2"
# The owner's PC: 64 GB of RAM and a 32 GB card.
P256, P128 = "int8_256k_r64g32", "int8_128k_r64g32"
PID = 52345
NO_WINDOW = 0x08000000
HYBRID = Hardware("Intel64 Family 6 Model 198", 20, 20, tuple(range(8)), tuple(range(20)),
                  64 * GIB, 48 * GIB, "NVIDIA GeForce RTX 5090", "GPU-test", "580.00",
                  int(31.84 * GIB), int(29.4 * GIB))
UNIFORM = replace(HYBRID, performance_cpus=tuple(range(16)), physical_cpus=tuple(range(16)))


def strata_config(root: Path, *, extra="") -> Config:
    path = root / "config.yaml"
    path.write_text(extra, encoding="utf-8")
    return load_config(path, root=root)


class StrataInstallation:
    """A temporary root with a Strata program folder and data folder laid out as Strata's setup leaves them."""

    def __init__(self, *, vision=True):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.cfg = strata_config(self.root)
        cfg = self.cfg
        spec = strata_backend.settings(cfg, KEY)
        data = strata_backend.data_dir(cfg)
        files = [strata_backend.python_exe(cfg), strata_backend.server_script(cfg),
                 strata_backend.engine_exe(cfg), strata_backend.vision_exe(cfg),
                 strata_backend.program_dir(cfg) / spec["expert_profile"],
                 cfg.model_file(KEY), data / spec["ple_gguf"],
                 data / spec["pack"] / "native_experts.txt", data / spec["pack"] / "tokenizer" / "vocab.json",
                 data / spec["mtp"] / "experts.bin", data / spec["mtp"] / "dense.bin",
                 data / spec["mtp"] / "dense.txt", self.cuda_library()]
        if vision:
            files.append(cfg.mmproj_file(KEY))
        for path in files:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"x")
        cfg.path("paths.runtime_dir").mkdir(parents=True, exist_ok=True)

    def cuda_library(self) -> Path:
        venv = strata_backend.program_dir(self.cfg) / ".venv"
        if strata_backend.WINDOWS:
            return venv / "Lib/site-packages/nvidia/cu13/bin/x86_64/cublas64_13.dll"
        return venv / "lib/python3.12/site-packages/nvidia/cu13/lib/libcublas.so.13"

    def close(self):
        self.temp.cleanup()

    def normalize(self, value):
        if isinstance(value, list):
            return [self.normalize(v) for v in value]
        if isinstance(value, dict):
            return {k: self.normalize(v) for k, v in value.items()}
        if isinstance(value, str):
            return value.replace(str(self.root), "<root>").replace("\\", "/")
        return value


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_both_weights_are_built_in(self):
        cfg = load_config(self.root / "missing.yaml", root=self.root)
        self.assertIn(KEY, cfg.data["models"])
        self.assertIn(IQ2, cfg.data["models"])
        self.assertEqual(len(cfg.kv_cache_profiles(KEY)), 18, "nine RAM and GPU classes, two contexts each")
        self.assertEqual(cfg.kv_cache_mode(KEY), P256)
        self.assertEqual(cfg.context_size(KEY), 262144)

    def test_backend_is_a_closed_choice(self):
        cfg = strata_config(self.root)
        self.assertEqual(cfg.backend("q5"), "llama")
        self.assertEqual(cfg.backend(KEY), "strata")
        cfg.data["models"]["custom"] = {"alias": "Custom", "file": "custom.gguf", "backend": "vllm"}
        with self.assertRaisesRegex(ValueError, "unknown inference backend 'vllm'.*llama, strata"):
            cfg.backend("custom")

    def test_strata_files_live_in_the_strata_data_folder(self):
        cfg = strata_config(self.root, extra="paths:\n  strata_data_dir: D:/StrataEval/Strata-data\n")
        data = Path("D:/StrataEval/Strata-data")
        self.assertEqual(cfg.model_root(KEY), data)
        self.assertEqual(cfg.model_file(KEY), data / "models/IQ3_S/Qwen3.8-Flash-Next-GSQ-RCO-IQ3_S-00001-of-00002.gguf")
        self.assertEqual(cfg.mmproj_file(KEY), data / "models/mmproj-Qwen3.8-Flash-Next-BF16.gguf")
        self.assertEqual(cfg.model_root("q5"), cfg.path("paths.models_dir"))

    def test_downloads_land_where_strata_setup_puts_them(self):
        """A data folder Strata's setup prepared is then adopted with a checksum instead of a new download."""
        from harness.model_files import asset_path, local_model_dir
        cfg = strata_config(self.root)
        spec = cfg.model(KEY)
        directory = local_model_dir(cfg.model_root(KEY), spec)
        self.assertEqual(asset_path(directory, spec["assets"][0]["path"]), cfg.model_file(KEY).resolve())
        self.assertEqual(asset_path(directory, spec["assets"][1]["path"]),
                         (cfg.model_root(KEY) / spec["strata"]["ple_gguf"]).resolve())
        self.assertEqual(asset_path(directory, spec["assets"][2]["path"]), cfg.mmproj_file(KEY).resolve())

    def offered(self, cfg, key, vram, ram):
        from harness import gpu
        with patch("harness.gpu.installed_ram_gib", return_value=ram):
            return gpu.offered_profiles(cfg, key, vram)

    def test_profiles_carry_their_measurement(self):
        cfg = strata_config(self.root)
        for key in (KEY, IQ2):
            for name, profile in cfg.kv_cache_profiles(key).items():
                self.assertEqual(profile["measurement_id"], "strata-qualification-2026-10-07", name)
                self.assertGreater(profile["min_vram_gb"], 14, name)
                self.assertLessEqual(profile["min_vram_gb"], {32: 31.0, 24: 22.0, 16: 14.4}[profile["gpu_class"]], name)
                self.assertNotIn("server_args", profile)
                self.assertEqual("expert_cache" in profile, profile["gpu_class"] < 32, name)

    def test_the_picker_offers_the_profiles_of_this_ram_and_gpu_class(self):
        cfg = strata_config(self.root)
        # Windows reports a little less than the installed modules.
        self.assertEqual(list(self.offered(cfg, KEY, 31.84, 63.7)), [P256, P128])
        self.assertEqual(list(self.offered(cfg, KEY, 31.84, 127.6)), [P256, P128], "more than 64 GB uses 64 GB")
        self.assertEqual(list(self.offered(cfg, KEY, 23.84, 47.7)), ["int8_256k_r48g24", "int8_128k_r48g24"])
        self.assertEqual(list(self.offered(cfg, IQ2, 15.9, 31.8)), ["int8_256k_r32g16", "int8_128k_r32g16"])
        self.assertEqual(self.offered(cfg, KEY, 31.84, 15.8), {}, "under 32 GB of RAM nothing is offered")
        self.assertEqual(self.offered(cfg, KEY, 11.9, 63.7), {})

    def test_each_class_runs_the_measured_expert_mode(self):
        cfg = strata_config(self.root)
        profiles = cfg.kv_cache_profiles(KEY)
        self.assertEqual(profiles[P256]["engine_args"], [])
        self.assertEqual(profiles["int8_256k_r64g16"]["engine_args"], ["--kv-resident", "32768"])
        self.assertEqual(profiles["int8_256k_r48g24"]["engine_args"], ["--resident-experts"])
        self.assertEqual(profiles["int8_256k_r48g24"]["expert_cache"], 4118)
        # 48/16 at 128k is the 256k placement with a smaller KV, as recovery from 256k runs it.
        self.assertEqual(profiles["int8_128k_r48g16"]["expert_cache"], profiles["int8_256k_r48g16"]["expert_cache"])
        self.assertEqual(cfg.kv_cache_profiles(IQ2)["int8_256k_r48g16"]["engine_args"], [])

    def test_recovery_stays_in_the_ram_and_gpu_class(self):
        from harness import gpu
        cfg = strata_config(self.root)
        cfg.set_kv_cache_mode(KEY, P256)
        self.assertEqual(gpu.lower_memory_profiles(cfg, KEY), [P128])
        cfg.set_kv_cache_mode(KEY, "int8_256k_r32g24")
        self.assertEqual(gpu.lower_memory_profiles(cfg, KEY), ["int8_128k_r32g24"])
        cfg.set_kv_cache_mode(KEY, "int8_128k_r32g24")
        self.assertEqual(gpu.lower_memory_profiles(cfg, KEY), [])

    def test_the_iq2_entry_shares_the_data_folder_with_its_own_receipt(self):
        from harness.model_files import receipt_file
        cfg = strata_config(self.root)
        iq3, iq2 = cfg.model(KEY), cfg.model(IQ2)
        self.assertEqual(cfg.model_root(IQ2), cfg.model_root(KEY))
        self.assertEqual(iq2["download_dir"], iq3["download_dir"])
        self.assertNotEqual(receipt_file(Path("d"), iq2), receipt_file(Path("d"), iq3))
        self.assertEqual(cfg.mmproj_file(IQ2), cfg.mmproj_file(KEY))
        self.assertEqual(iq2["assets"][1]["sha256"], iq3["assets"][1]["sha256"], "the second shard is one file")
        self.assertEqual(iq2["strata"]["pack"], "packs/iq2_xs")
        self.assertIn("IQ2_XS", iq2["strata"]["ple_gguf"])
        self.assertTrue(iq2["optional_download"])

    def test_the_optional_entry_is_never_chosen_or_downloaded_automatically(self):
        from harness import gpu
        cfg = strata_config(self.root)
        self.assertNotIn(KEY, gpu.download_keys(cfg, 32))
        self.assertNotEqual(gpu.best_fit(cfg, 31.84)[0], KEY)

    def test_image_estimate_follows_the_engine(self):
        from harness.session import Session
        cfg = strata_config(self.root)
        cfg.data["paths"]["sessions_dir"] = str(self.root / "sessions")
        session = Session(cfg)
        self.assertEqual(session.image_tokens(), Session.IMAGE_TOKENS)
        cfg.data["default_model"] = KEY
        self.assertEqual(session.image_tokens(), 1024)
        self.assertEqual(session.tokens_for(0, 2, image_tokens=session.image_tokens()), 2048)
        self.assertEqual(Session.tokens_for(0, 1), Session.IMAGE_TOKENS)


class SharedAssetTests(unittest.TestCase):
    """Two weights of one model share a data folder, the second shard and the projector."""

    def spec(self, name, assets):
        import hashlib
        return {"repo": "org/model", "revision": "abc", "download_dir": "models", "download_transport": "range",
                "receipt": f".marvin-verified-{name}.json",
                "assets": [{"path": path, "size": len(data), "sha256": hashlib.sha256(data).hexdigest()}
                           for path, data in assets]}

    def test_a_file_another_entry_verified_is_linked_instead_of_downloaded(self):
        from harness import model_files
        shared, own = b"shared shard " * 100, b"iq2 shard"
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first = self.spec("first", [("IQ3_S/b.gguf", shared)])
            second = self.spec("second", [("IQ2_XS/a.gguf", own), ("IQ2_XS/b.gguf", shared)])
            (root / "models/IQ3_S").mkdir(parents=True)
            (root / "models/IQ3_S/b.gguf").write_bytes(shared)
            fetched = []

            def ranged(directory, spec, asset, **kwargs):
                fetched.append(asset["path"])
                target = model_files.asset_path(directory, asset["path"])
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(own)
                return target

            with patch.object(model_files, "ranged_download", side_effect=ranged), \
                 patch("huggingface_hub.hf_hub_download", side_effect=AssertionError("no download")):
                model_files.download_pinned_model(root, first, progress=lambda *_: None)
                model_files.download_pinned_model(root, second, progress=lambda *_: None)
            self.assertEqual(fetched, ["IQ2_XS/a.gguf"], "the shared shard is not fetched again")
            self.assertEqual((root / "models/IQ2_XS/b.gguf").read_bytes(), shared)
            self.assertTrue(model_files.model_ready(root, first), "the first entry stays verified")
            self.assertTrue(model_files.model_ready(root, second))
            if os.name == "nt":
                self.assertTrue((root / "models/IQ2_XS/b.gguf").samefile(root / "models/IQ3_S/b.gguf"))


class ServerConfigTests(unittest.TestCase):
    def setUp(self):
        self.installation = StrataInstallation()
        self.cfg = self.installation.cfg

    def tearDown(self):
        self.installation.close()

    def test_config_matches_the_format_strata_setup_writes(self):
        where = strata_backend.placement(self.cfg, KEY)
        config = self.installation.normalize(strata_backend.build_config(self.cfg, KEY, 262144, where, HYBRID))
        data = "<root>/runtime/models/strata"
        program = "<root>/runtime/strata"
        exe = ".exe" if strata_backend.WINDOWS else ""
        library = self.installation.normalize(str(self.installation.cuda_library().parent))
        self.assertEqual(config, {
            "exe": f"{program}/engine/strata{exe}",
            "args": ["--pack", f"{data}/packs/iq3_s",
                     "--native", f"{data}/models/IQ3_S/Qwen3.8-Flash-Next-GSQ-RCO-IQ3_S-00001-of-00002.gguf",
                     "--ple-gguf", f"{data}/models/IQ3_S/Qwen3.8-Flash-Next-GSQ-RCO-IQ3_S-00002-of-00002.gguf",
                     "--expert-profile", f"{program}/data/expert-profile.bin",
                     "--expert-cache", "auto", "--prefill", "auto", "--spec", "4", "--spec-min-p", "0.5",
                     "--mtp", f"{data}/mtp/rt", "--max-context", "262144", "--kv", "int8",
                     "--vision", "--vram-reserve-mib", "700", "--pool-workers", "13"],
            "cwd": program,
            "tokenizer": f"{data}/packs/iq3_s/tokenizer",
            "model_name": "qwen3.8-flash-next-iq3_s",
            "log": "<root>/runtime/strata-run/strata-flash_next_strata.log",
            "lib_dirs": [library],
            "port": 8080,
            "open_browser": False,
            "effort_position": "end",
            "vision": {"exe": f"{program}/engine/strata-vision{exe}",
                       "mmproj": f"{data}/models/mmproj-Qwen3.8-Flash-Next-BF16.gguf",
                       "model": f"{data}/models/IQ3_S/Qwen3.8-Flash-Next-GSQ-RCO-IQ3_S-00001-of-00002.gguf",
                       "gpu": True, "max_tokens": 1024},
        })

    def test_context_profile_arguments_and_cpu_follow_the_launch(self):
        self.cfg.set_kv_cache_mode(KEY, "int8_128k_r64g16")
        args = strata_backend.engine_args(self.cfg, KEY, 131072, strata_backend.placement(self.cfg, KEY), UNIFORM)
        self.assertEqual(args[args.index("--max-context") + 1], "131072")
        self.assertEqual(args[args.index("--kv-resident") + 1], "32768")
        self.assertNotIn("--pool-workers", args, "a uniform CPU keeps the engine's own worker count")

    def test_missing_projector_starts_without_images(self):
        self.cfg.mmproj_file(KEY).unlink()
        config = strata_backend.build_config(self.cfg, KEY, 262144, strata_backend.placement(self.cfg, KEY))
        self.assertNotIn("vision", config)
        self.assertNotIn("--vision", config["args"])

    def test_resident_experts_and_a_recovery_placement(self):
        self.cfg.data["models"][KEY]["strata"]["resident_experts"] = True
        self.cfg.data["_recovery_placement"] = {"model": KEY, "expert_cache": "auto", "expert_cache_slots": 9600,
                                                "vram_reserve_mib": 900}
        where = strata_backend.placement(self.cfg, KEY)
        self.assertEqual(where, {"model": KEY, "expert_cache": 9600, "vram_reserve_mib": 900})
        args = strata_backend.engine_args(self.cfg, KEY, 131072, where)
        self.assertIn("--resident-experts", args)
        self.assertEqual(args[args.index("--expert-cache") + 1], "9600")
        self.assertEqual(args[args.index("--vram-reserve-mib") + 1], "900")
        self.cfg.data["_recovery_placement"]["model"] = "q5"
        self.assertEqual(strata_backend.placement(self.cfg, KEY)["expert_cache"], "auto")

    def test_a_smaller_card_profile_fixes_the_expert_cache(self):
        self.cfg.set_kv_cache_mode(KEY, "int8_128k_r64g24")
        where = strata_backend.placement(self.cfg, KEY)
        self.assertEqual(where["expert_cache"], 4882)
        args = strata_backend.engine_args(self.cfg, KEY, 131072, where)
        self.assertEqual(args[args.index("--expert-cache") + 1], "4882")
        # A recovery still keeps what the failed run logged.
        self.cfg.data["_recovery_placement"] = {"model": KEY, "expert_cache_slots": 5100}
        self.assertEqual(strata_backend.placement(self.cfg, KEY)["expert_cache"], 5100)

    def test_build_manifest_libraries_take_precedence(self):
        engine = strata_backend.engine_exe(self.cfg).parent
        (engine / "BUILD.json").write_text(json.dumps({"version": "0.1.39", "lib_dirs": ["rocm/bin", "C:/abs"]}))
        self.assertEqual(strata_backend.lib_dirs(self.cfg), [str(engine / "rocm/bin"), str(Path("C:/abs"))])

    def test_pool_workers_follow_strata_setup(self):
        self.assertEqual(strata_backend.pool_workers(HYBRID), 13)          # 8 P + 12 E
        self.assertIsNone(strata_backend.pool_workers(UNIFORM))
        self.assertIsNone(strata_backend.pool_workers(replace(HYBRID, performance_cpus=tuple(range(8)),
                                                                     physical_cpus=tuple(range(16)))))   # 8 + 8
        self.assertIsNone(strata_backend.pool_workers(None))

    def test_prepare_writes_the_config_and_drops_web_page_defaults(self):
        shared = strata_backend.shared_settings_path(self.cfg, KEY)
        shared.parent.mkdir(parents=True, exist_ok=True)
        shared.write_text('{"max_tokens": 256}', encoding="utf-8")
        self.assertEqual(shared.name, "strata-flash_next_strata.shared-settings.json")
        prepared = strata_backend.prepare(self.cfg, KEY, 262144)
        written = json.loads(strata_backend.config_path(self.cfg, KEY).read_text(encoding="utf-8"))
        self.assertEqual(written, prepared.config)
        self.assertFalse(shared.exists())
        self.assertEqual(self.installation.normalize(prepared.argv), [
            self.installation.normalize(str(strata_backend.python_exe(self.cfg))),
            "<root>/runtime/strata/serve/server.py", "--engine", "strata",
            "--config", "<root>/runtime/strata-run/strata-flash_next_strata.json",
            "--host", "127.0.0.1", "--port", "8080"])
        self.assertEqual(prepared.cwd, strata_backend.program_dir(self.cfg))
        self.assertEqual(prepared.run, {"backend": "strata", "engine_log": str(strata_backend.engine_log(self.cfg, KEY)),
                                        "engine_log_offset": 0})

    def test_server_environment(self):
        with patch.dict(os.environ, {"STRATA_API_KEY": "", "PATH": os.environ.get("PATH", "")}):
            env = strata_backend.server_env()
        self.assertNotIn("STRATA_API_KEY", env)
        self.assertEqual((env["PYTHONUTF8"], env["PYTHONIOENCODING"]), ("1", "utf-8"))

    def test_missing_parts_are_named(self):
        strata_backend.engine_exe(self.cfg).unlink()
        (strata_backend.data_dir(self.cfg) / "mtp/rt/experts.bin").unlink()
        with self.assertRaises(RuntimeError) as raised:
            strata_backend.prepare(self.cfg, KEY, 262144)
        message = str(raised.exception)
        self.assertIn("the engine: ", message)
        self.assertIn("the MTP draft layer", message)
        self.assertNotIn("the prepared weights index", message)
        self.assertTrue(message.startswith("Qwen 3.8 Flash-Next · IQ3_S cannot start: some of its files are missing"))
        self.assertIn("Selecting the model again", message)


class FakeServer:
    """What subprocess.Popen returns for the Strata launcher process."""

    def __init__(self, argv, **kwargs):
        self.argv, self.kwargs = list(argv), kwargs
        self.pid = PID
        self.returncode = 0
        self.killed = False
        self._handle = 1

    def poll(self):
        return self.returncode

    def kill(self):
        self.killed = True
        self.returncode = -9

    def terminate(self):
        self.returncode = 1

    def wait(self, timeout=None):
        return self.returncode


class LaunchTests(unittest.TestCase):
    def setUp(self):
        self.installation = StrataInstallation()
        self.cfg = self.installation.cfg
        # As the model switch leaves it: the model being started is the selected one.
        self.cfg.data["default_model"] = KEY
        self.runtime = self.cfg.path("paths.runtime_dir")

    def tearDown(self):
        servermgmt.BIND_SERVER_TO_PROCESS = True
        self.installation.close()

    def launch(self, *, ready=True, engine_output="", server_output="", downloaded=True, entry="start"):
        """`ready`, `engine_output` and `server_output` may be lists, one item per launch."""
        processes, readiness, contained, trees = [], [], [], []
        # Kept on the test as well, for launches that end in an exception.
        self.processes, self.trees = processes, trees
        log = strata_backend.engine_log(self.cfg, KEY)

        def nth(value):
            return value[len(processes) - 1] if isinstance(value, list) else value

        def popen(argv, **kwargs):
            processes.append(FakeServer(argv, **kwargs))
            processes[-1].config = json.loads(strata_backend.config_path(self.cfg, KEY).read_text(encoding="utf-8"))
            for path, text in ((log, nth(engine_output)), (strata_backend.server_log(self.cfg), nth(server_output))):
                if text:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    with path.open("a", encoding="utf-8") as stream:
                        stream.write(text)
            return processes[-1]

        def wait_health(cfg, timeout=servermgmt.HEALTH_TIMEOUT, proc=None, cancelled=None, probe=None):
            readiness.append(probe)
            answer = nth(ready)
            if not answer:
                proc.returncode = None
            return answer

        threads = SimpleNamespace(Thread=threading.Thread, Event=threading.Event, Lock=threading.Lock)
        output = io.StringIO()
        with patch.object(servermgmt, "health", return_value=False), \
             patch.object(servermgmt, "wait_health", side_effect=wait_health), \
             patch.object(servermgmt, "vram_str", return_value="GPU VRAM: test"), \
             patch.object(servermgmt, "threading", threads), \
             patch.object(servermgmt, "_end_tree", side_effect=trees.append), \
             patch.object(servermgmt.subprocess, "Popen", side_effect=popen), \
             patch.object(servermgmt.subprocess, "CREATE_NO_WINDOW", NO_WINDOW, create=True), \
             patch("harness.gpu.vram_total_gb", return_value=31.84), \
             patch("harness.gpu.installed_ram_gib", return_value=63.7), \
             patch.object(Config, "model_ready", return_value=downloaded), \
             patch("harness.model_files.download_pinned_model") as download, \
             patch("harness.runtime_update.ensure_runtime", side_effect=AssertionError("llama runtime")), \
             patch("harness.hardware.detect_hardware", return_value=HYBRID), \
             patch("harness.winjob.contain", side_effect=lambda proc: contained.append(proc) or True), \
             contextlib.redirect_stdout(output):
            code = servermgmt.start(self.cfg, KEY) if entry == "start" else servermgmt.ensure(self.cfg, KEY)
        return SimpleNamespace(code=code, processes=processes, readiness=readiness, contained=contained,
                               trees=trees, download=download, output=output.getvalue())

    def run_record(self):
        return json.loads((self.runtime / "model-run.json").read_text(encoding="utf-8"))

    def test_launch_starts_the_server_with_its_own_config_and_waits_for_the_model(self):
        result = self.launch(engine_output="strata generate: expert cache auto: 29.10 GiB free, 700 MiB reserved (+218 MiB for the draft head) -> 8641 slots\n"
                                           "strata generate: expert cache 9840 slots, 23.41 GiB of VRAM; policy is\n")
        self.assertEqual(result.code, 0)
        process = result.processes[0]
        self.assertEqual(process.argv, strata_backend.server_argv(self.cfg, KEY))
        self.assertEqual(process.kwargs["cwd"], str(strata_backend.program_dir(self.cfg)))
        self.assertEqual(process.kwargs["stdin"], subprocess.DEVNULL)
        self.assertEqual(process.kwargs["stderr"], subprocess.STDOUT)
        self.assertEqual(process.kwargs["creationflags"], NO_WINDOW)
        self.assertEqual(process.kwargs["env"]["PYTHONUTF8"], "1")
        self.assertEqual(Path(process.kwargs["stdout"].name), strata_backend.server_log(self.cfg))
        self.assertEqual(result.contained, [process], "the server ends with Marvin")
        self.assertEqual(result.readiness, [strata_backend.ready])
        self.assertEqual(servermgmt.pid_file(self.cfg).read_text(encoding="utf-8"), f"{KEY}:{PID}")
        run = self.run_record()
        self.assertEqual((run["backend"], run["model"], run["context"]), ("strata", KEY, 262144))
        self.assertEqual(run["placement"], {"model": KEY, "expert_cache": "auto", "vram_reserve_mib": 700,
                                            "expert_cache_slots": 8641})
        self.assertEqual(self.cfg.data["_active_placement"], run["placement"])
        self.assertIn("ready_engine_log_offset", run)
        self.assertIn("ready_log_offset", run)
        self.assertTrue(strata_backend.config_path(self.cfg, KEY).is_file())

    def test_the_cli_leaves_the_server_running(self):
        servermgmt.BIND_SERVER_TO_PROCESS = False
        result = self.launch()
        self.assertEqual((result.code, result.contained), (0, []))

    def test_a_missing_engine_is_prepared_before_the_weights_download(self):
        from harness import strata_runtime
        strata_backend.engine_exe(self.cfg).unlink()
        order = []

        def install(cfg, **kwargs):
            order.append("engine")
            strata_backend.engine_exe(cfg).write_bytes(b"x")

        with patch.object(strata_runtime, "install", side_effect=install), \
             patch.object(strata_runtime, "prepare_model", side_effect=lambda cfg, key, **kw: order.append("files")):
            result = self.launch(downloaded=False)
        self.assertEqual(result.code, 0)
        self.assertEqual(order, ["engine", "files"])
        self.assertTrue(result.download.called)

    def test_a_failed_engine_preparation_says_why_and_downloads_nothing(self):
        from harness import strata_runtime
        strata_backend.engine_exe(self.cfg).unlink()
        with patch.object(strata_runtime, "install", side_effect=RuntimeError("The download of x does not match")), \
             self.assertRaisesRegex(RuntimeError, "does not match"):
            self.launch(downloaded=False)
        self.assertFalse(self.processes)

    def test_weights_download_into_the_strata_data_folder(self):
        result = self.launch(downloaded=False)
        self.assertEqual(result.code, 0)
        self.assertEqual(result.download.call_args.args[0], strata_backend.data_dir(self.cfg))

    def test_failed_start_ends_the_whole_tree_and_says_why(self):
        with self.assertRaisesRegex(RuntimeError, "The model stopped before it was ready: RuntimeError: "
                                                  "the engine exited before it was ready") as raised:
            self.launch(ready=False,
                        engine_output="strata generate: expert cache auto: 28.40 GiB free, 700 MiB reserved (+218 MiB for the draft head) -> 8400 slots\n"
                                      "strata generate: expert cache: 9600 slots (22.8 GiB) after 2 smaller tries\n"
                                      "strata: CUDA driver version is insufficient\n",
                        server_output="Traceback (most recent call last):\n  File \"serve/server.py\", line 4001\n"
                                      "RuntimeError: the engine exited before it was ready (see strata.log)\n")
        self.assertIn(str(strata_backend.server_log(self.cfg)), str(raised.exception))
        process = self.processes[0]
        self.assertTrue(process.killed)
        self.assertIn(process, self.trees)
        self.assertFalse(servermgmt.pid_file(self.cfg).exists())
        self.assertEqual(self.cfg.data["_active_placement"]["expert_cache_slots"], 8400)
        self.assertNotIn("ready_engine_log_offset", self.run_record())
        self.assertEqual(servermgmt.last_failure(self.cfg), {}, "a driver problem is not memory pressure")

    def test_memory_failure_at_256k_retries_128k_with_the_same_expert_cache(self):
        self.cfg.set_kv_cache_mode(KEY, P256)
        result = self.launch(entry="ensure", ready=[False, True],
                             engine_output=["strata generate: expert cache auto: 29.10 GiB free, 700 MiB reserved (+218 MiB) -> 8641 slots\n"
                                            "strata generate: expert cache 9840 slots, 23.41 GiB of VRAM\n"
                                            "strata generate: the weight arena does not fit\n", ""])
        self.assertTrue(result.code)
        first, second = (p.config["args"] for p in result.processes)
        self.assertEqual(first[first.index("--max-context") + 1], "262144")
        self.assertEqual(first[first.index("--expert-cache") + 1], "auto")
        self.assertEqual(second[second.index("--max-context") + 1], "131072")
        self.assertEqual(second[second.index("--expert-cache") + 1], "8641")
        self.assertEqual(second[second.index("--vram-reserve-mib") + 1], "700")
        self.assertEqual(self.cfg.kv_cache_mode(KEY), P128)
        self.assertEqual(self.cfg.data["_recovered_contexts"], {KEY: 131072})


class FakeProcess:
    def __init__(self, exe, cmdline):
        self._exe, self._cmdline = exe, cmdline

    def is_running(self):
        return True

    def status(self):
        return "running"

    def name(self):
        return "python.exe"

    def exe(self):
        return self._exe

    def cmdline(self):
        return self._cmdline


class IdentityTests(unittest.TestCase):
    def setUp(self):
        self.installation = StrataInstallation()
        self.cfg = self.installation.cfg
        self.argv = strata_backend.server_argv(self.cfg, KEY)

    def tearDown(self):
        self.installation.close()

    def owns(self, exe=None, argv=None):
        return strata_backend.owns_process(self.cfg, KEY, FakeProcess(exe or self.argv[0], argv or self.argv))

    def test_marvins_server_is_recognized(self):
        self.assertTrue(self.owns())

    def test_other_processes_are_not(self):
        argv = self.argv
        cases = {
            "other python": dict(exe=str(self.installation.root / "python.exe")),
            "other script": dict(argv=[argv[0], str(self.installation.root / "server.py"), *argv[2:]]),
            "other config": dict(argv=[*argv[:5], str(self.installation.root / "other.json"), *argv[6:]]),
            "other port": dict(argv=[*argv[:-1], "18080"]),
            "no port": dict(argv=argv[:-2]),
        }
        for name, change in cases.items():
            with self.subTest(name):
                self.assertFalse(self.owns(**change))

    def test_unreadable_process_is_not_owned(self):
        class Gone(FakeProcess):
            def exe(self):
                raise PermissionError("access denied")
        self.assertFalse(strata_backend.owns_process(self.cfg, KEY, Gone("", [])))

    def test_managed_process_uses_the_strata_identity(self):
        servermgmt.pid_file(self.cfg).write_text(f"{KEY}:{PID}", encoding="utf-8")
        process = FakeProcess(self.argv[0], self.argv)
        with patch("psutil.Process", return_value=process):
            self.assertIs(servermgmt._managed_process(self.cfg), process)
            self.assertEqual(servermgmt.running_model(self.cfg), KEY)
        other = FakeProcess(self.argv[0], [*self.argv[:-1], "9999"])
        with patch("psutil.Process", return_value=other):
            self.assertIsNone(servermgmt._managed_process(self.cfg))
        self.assertFalse(servermgmt.pid_file(self.cfg).exists())


class ResponseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.cfg = strata_config(Path(self.temp.name))

    def tearDown(self):
        self.temp.cleanup()

    def test_ready_needs_a_loaded_strata_model(self):
        def answer(status, body):
            return SimpleNamespace(status_code=status, json=lambda: body)
        cases = [(answer(200, {"service": "strata", "loaded": True}), True),
                 (answer(200, {"service": "strata", "loaded": False}), False),
                 (answer(200, {"status": "ok"}), False),
                 (answer(503, {"service": "strata", "loaded": True}), False)]
        for response, expected in cases:
            with self.subTest(response.json()), patch("requests.get", return_value=response):
                self.assertIs(strata_backend.ready(self.cfg), expected)
        import requests
        with patch("requests.get", side_effect=requests.ConnectionError("loading")):
            self.assertFalse(strata_backend.ready(self.cfg))

    def test_unload_posts_json(self):
        import requests
        with patch("requests.post", return_value=SimpleNamespace(status_code=200, json=lambda: {"status": "unloaded"})) as post:
            self.assertEqual(strata_backend.unload(self.cfg), "unloaded")
        self.assertEqual(post.call_args.args[0], "http://127.0.0.1:8080/unload")
        self.assertEqual(post.call_args.kwargs["json"], {})
        with patch("requests.post", side_effect=requests.ReadTimeout("slow")):
            self.assertIn("ReadTimeout", strata_backend.unload(self.cfg))


class StopTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.cfg = strata_config(Path(self.temp.name))
        self.cfg.path("paths.runtime_dir").mkdir(parents=True)
        servermgmt.pid_file(self.cfg).write_text(f"{KEY}:{PID}", encoding="utf-8")

    def tearDown(self):
        self.temp.cleanup()

    def test_stop_unloads_then_ends_the_tree(self):
        events = []

        class Tree:
            def children(self, recursive=False):
                return [SimpleNamespace(kill=lambda: events.append("engine killed"))]

            def kill(self):
                events.append("server killed")

        output = io.StringIO()
        with patch.object(servermgmt, "_managed_process", return_value=Tree()), \
             patch.object(strata_backend, "unload", side_effect=lambda cfg: events.append("unload") or "unloaded"), \
             patch("psutil.wait_procs", return_value=([], [])), \
             patch.object(servermgmt, "health", return_value=False), \
             contextlib.redirect_stdout(output):
            self.assertTrue(servermgmt.stop(self.cfg))
        self.assertEqual(events, ["unload", "engine killed", "server killed"])
        self.assertIn("[INFO] Strata unload: unloaded", output.getvalue())
        self.assertIn("[OK] Strata server stopped.", output.getvalue())
        self.assertFalse(servermgmt.pid_file(self.cfg).exists())

    def test_nothing_running_is_not_unloaded(self):
        with patch.object(servermgmt, "_managed_process", return_value=None), \
             patch.object(strata_backend, "unload", side_effect=AssertionError("nothing to unload")), \
             patch.object(servermgmt, "health", return_value=False), \
             contextlib.redirect_stdout(io.StringIO()):
            self.assertTrue(servermgmt.stop(self.cfg, quiet=True))


class AllocationFailureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.cfg = strata_config(Path(self.temp.name))
        self.cfg.data["default_model"] = KEY
        self.runtime = self.cfg.path("paths.runtime_dir")
        self.runtime.mkdir(parents=True)
        self.engine_log = self.runtime / "strata-run" / f"strata-{KEY}.log"
        self.engine_log.parent.mkdir()

    def tearDown(self):
        self.temp.cleanup()

    def record(self, startup: str, later: str, *, ready=True):
        self.engine_log.write_text(startup, encoding="utf-8")
        strata_backend.server_log(self.cfg).write_text("ready: http://127.0.0.1:8080/v1\n", encoding="utf-8")
        run = {"model": KEY, "context": 262144, "backend": "strata", "log_offset": 0,
               "engine_log": str(self.engine_log), "engine_log_offset": 0}
        if ready:
            run.update(strata_backend.log_offsets(self.cfg, run))
        with self.engine_log.open("a", encoding="utf-8") as stream:
            stream.write(later)
        (self.runtime / "model-run.json").write_text(json.dumps(run), encoding="utf-8")

    def test_startup_warnings_do_not_turn_a_request_error_into_memory_pressure(self):
        self.record("strata generate: WARNING: the resident RAM mode does not fit (budget); keeping 40 GiB\n", "")
        servermgmt.record_allocation_failure(self.cfg, "APIError: malformed tool call: <tool_call>{")
        self.assertEqual(servermgmt.last_failure(self.cfg), {})

    def test_failure_after_ready_is_memory_pressure(self):
        self.record("", "mtp: the K/V state does not fit\n")
        servermgmt.record_allocation_failure(self.cfg, "APIError: the engine stopped unexpectedly (exit code 1)")
        failure = servermgmt.last_failure(self.cfg)
        self.assertEqual((failure["model"], failure["context"]), (KEY, 262144))
        self.assertIn(failure["code"], ("ram_pressure", "vram_pressure"))

    def test_failed_start_reads_the_whole_launch(self):
        self.record("strata: KV streaming: cannot pin 3.50 GiB of RAM\n", "", ready=False)
        servermgmt.record_allocation_failure(self.cfg)
        self.assertEqual(servermgmt.last_failure(self.cfg)["code"], "ram_pressure")


class MemoryGuardTests(unittest.TestCase):
    """The emergency guard ends a server below GUARD_RAM_BYTES of available RAM."""

    def available(self, free, mapped, *, strata):
        tree = SimpleNamespace(children=lambda recursive: [SimpleNamespace(pid=PID + 1)])
        with patch("psutil.virtual_memory", return_value=SimpleNamespace(available=free)), \
             patch("psutil.Process", return_value=tree), \
             patch("harness.hardware.shared_working_set", return_value=mapped) as shared:
            value = servermgmt.guard_available(SimpleNamespace(pid=PID), strata=strata)
        return value, shared

    def test_experts_read_from_the_files_count_as_available(self):
        value, shared = self.available(300 * 2**20, 19 * 2**30, strata=True)
        self.assertGreater(value, servermgmt.GUARD_RAM_BYTES)
        shared.assert_called_once_with([PID, PID + 1])

    def test_a_strata_server_without_mapped_pages_still_trips_the_guard(self):
        value, _ = self.available(300 * 2**20, 0, strata=True)
        self.assertLess(value, servermgmt.GUARD_RAM_BYTES)

    def test_llama_is_counted_as_measured_in_september(self):
        value, shared = self.available(300 * 2**20, 19 * 2**30, strata=False)
        self.assertEqual(value, 300 * 2**20)
        shared.assert_not_called()

    def test_working_sets_are_read_only_when_memory_runs_short(self):
        value, shared = self.available(8 * 2**30, 19 * 2**30, strata=True)
        self.assertEqual(value, 8 * 2**30)
        shared.assert_not_called()

    def test_mapped_file_pages_are_shared_and_private_memory_is_not(self):
        if os.name != "nt":
            self.skipTest("Windows working sets")
        before = shared_working_set([os.getpid()])
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "weights.bin"
            path.write_bytes(os.urandom(32 * 2**20))
            with path.open("rb") as handle, mmap.mmap(handle.fileno(), 0, access=mmap.ACCESS_READ) as view:
                touched = sum(view[i] for i in range(0, len(view), 4096))
                mapped = shared_working_set([os.getpid()])
                private = bytearray(32 * 2**20)
                for i in range(0, len(private), 4096):
                    private[i] = 1
                self.assertGreaterEqual(touched, 0)
                self.assertGreater(mapped - before, 24 * 2**20)
                self.assertLess(shared_working_set([os.getpid()]) - mapped, 8 * 2**20)
        self.assertEqual(shared_working_set([2**31 - 1]), 0, "a process that cannot be read counts as zero")


class ClientTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.cfg = strata_config(Path(self.temp.name))

    def tearDown(self):
        self.temp.cleanup()

    def requests_for(self, key):
        from harness.llm import LLMClient
        self.cfg.data["default_model"] = key
        sent = []

        def create(**params):
            sent.append(params)
            if params.get("stream"):
                return iter(())
            message = SimpleNamespace(content="OK", tool_calls=None, reasoning_content=None)
            return SimpleNamespace(choices=[SimpleNamespace(message=message)])

        client = LLMClient(self.cfg)
        client.client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
        client.stream([{"role": "user", "content": "hi"}])
        client.ask([{"role": "user", "content": "hi"}])
        return sent

    def test_strata_requests_ask_for_the_rest_of_the_context(self):
        self.assertEqual([p.get("max_tokens") for p in self.requests_for(KEY)], [-1, -1])

    def test_llama_requests_are_unchanged(self):
        self.assertEqual([("max_tokens" in p) for p in self.requests_for("q5")], [False, False])

    def test_overflow_wording_of_both_engines(self):
        from harness.agent import OVERFLOW_RE
        self.assertTrue(OVERFLOW_RE.search("prompt (262000 tokens) leaves no room to answer in the context (262144)"))
        self.assertTrue(OVERFLOW_RE.search("prompt (200 tokens) + max tokens (9) exceeds the context (100)"))
        self.assertTrue(OVERFLOW_RE.search("request (300000 tokens) exceeds the available context size "
                                           "(262144 tokens), try increasing it"))


class StreamReplayTests(unittest.TestCase):
    """Strata v0.1.39's own server output, recorded from its scripted mock engine, through Marvin's client.

    The mock has no clock, so these streams carry no `timings`; the real engine
    adds llama-style timings to the final chunk."""

    FIXTURES = Path(__file__).with_name("fixtures")

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.cfg = strata_config(Path(self.temp.name))
        self.cfg.data["default_model"] = KEY

    def tearDown(self):
        self.temp.cleanup()

    def replay(self, name):
        import httpx
        from openai import OpenAI
        from harness.llm import LLMClient
        raw = (self.FIXTURES / name).read_bytes()
        sent = []

        def handler(request):
            sent.append(json.loads(request.content))
            return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=raw)

        llm = LLMClient(self.cfg)
        llm.client = OpenAI(base_url="http://strata.test/v1", api_key="local", max_retries=0,
                            http_client=httpx.Client(transport=httpx.MockTransport(handler)))
        reasoning, text = [], []
        result = llm.stream([{"role": "user", "content": "Read notes.txt and tell me its second line."}],
                            on_reasoning=reasoning.append, on_text=text.append)
        return result, sent, "".join(reasoning), "".join(text)

    def test_reasoning_and_a_streamed_tool_call(self):
        result, sent, reasoning, _ = self.replay("strata_stream_tool_call.sse")
        self.assertEqual(result.reasoning, "The user wants the second line, so I read the file first.")
        self.assertEqual(reasoning, result.reasoning)
        self.assertEqual(result.content.strip(), "")
        self.assertEqual([c["function"]["name"] for c in result.tool_calls], ["read_file"])
        self.assertEqual(json.loads(result.tool_calls[0]["function"]["arguments"]), {"path": "notes.txt"})
        self.assertTrue(result.tool_calls[0]["id"])
        self.assertEqual((result.usage["prompt_tokens"], result.usage["completion_tokens"]), (29369, 165))
        self.assertEqual(sent[0]["max_tokens"], -1)
        self.assertTrue(sent[0]["stream"])

    def test_answer_after_the_tool(self):
        result, _, _, text = self.replay("strata_stream_answer.sse")
        self.assertEqual(result.content.strip(), "The second line is beta.")
        self.assertEqual(text, result.content)
        self.assertEqual(result.reasoning, "The tool returned two lines.")
        self.assertEqual(result.tool_calls, [])

    def test_unreadable_tool_call_arrives_as_an_error(self):
        with self.assertRaisesRegex(Exception, "malformed tool call") as raised:
            self.replay("strata_stream_malformed.sse")
        from harness.agent import MALFORMED_TOOL_CALL_RE
        self.assertTrue(MALFORMED_TOOL_CALL_RE.search(str(raised.exception)))


class MalformedToolCallTests(unittest.TestCase):
    def setUp(self):
        from harness.agent import Agent, build_registry
        from harness.safety import SafetyPolicy
        from harness.session import Session
        from harness.prompts import system_prompt
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.cfg = strata_config(root)
        self.cfg.data["paths"]["sessions_dir"] = str(root / "sessions")
        self.cfg.data["agent"]["workspace"] = str(root)
        self.outcomes = []
        test = self

        class Model:
            def stream(self, messages, **kwargs):
                outcome = test.outcomes.pop(0)
                if isinstance(outcome, Exception):
                    raise outcome
                return outcome

        self.events = []
        self.session = Session(self.cfg, system_prompt=system_prompt("agent"), workspace=str(root))
        self.agent = Agent(self.cfg, Model(), self.session, build_registry("agent"),
                           SafetyPolicy("auto"), mode="agent",
                           on_event=lambda kind, payload: self.events.append((kind, payload)))
        self.agent.new_task("Read notes.txt")

    def tearDown(self):
        self.temp.cleanup()

    def malformed(self):
        return RuntimeError("malformed tool call: <tool_call>{\"name\": \"read_file\"")

    def test_unreadable_tool_calls_are_retried_silently_then_reported(self):
        from harness.agent import MALFORMED_TOOL_CALL_RETRIES, Status
        self.outcomes = [self.malformed() for _ in range(MALFORMED_TOOL_CALL_RETRIES + 1)]
        self.events.clear()
        for _ in range(MALFORMED_TOOL_CALL_RETRIES):
            self.assertEqual(self.agent.step().status, Status.CONTINUE)
        self.assertEqual([e for e in self.events if e[0] == "info"], [], "the user sees the task go on, nothing more")
        notes = [m for m in self.session.messages if str(m.get("content", "")).startswith("[TOOL CALL NOT READ")]
        self.assertEqual(len(notes), MALFORMED_TOOL_CALL_RETRIES)
        self.assertIn("malformed tool call", notes[0]["content"])
        final = self.agent.step()
        self.assertEqual(final.status, Status.ERROR)
        self.assertIn("malformed tool call", final.text)

    def test_a_readable_reply_resets_the_count(self):
        from harness.agent import MALFORMED_TOOL_CALL_RETRIES, Status
        from harness.llm import AssistantResult
        call = {"id": "c1", "type": "function", "function": {"name": "list_dir", "arguments": "{}"}}
        self.outcomes = ([self.malformed() for _ in range(MALFORMED_TOOL_CALL_RETRIES)]
                         + [AssistantResult(tool_calls=[call])]
                         + [self.malformed() for _ in range(MALFORMED_TOOL_CALL_RETRIES)])
        statuses = [self.agent.step().status for _ in range(2 * MALFORMED_TOOL_CALL_RETRIES + 1)]
        self.assertNotIn(Status.ERROR, statuses)

    def test_the_guidance_is_an_internal_message(self):
        from harness.internal_messages import INTERNAL_USER_PREFIXES
        from harness.agent import MALFORMED_TOOL_CALL_NOTE
        self.assertTrue(MALFORMED_TOOL_CALL_NOTE.startswith(INTERNAL_USER_PREFIXES))

    @unittest.skipUnless((Path(__file__).resolve().parent.parent / "frontend/src/api.ts").is_file(),
                         "Frontend source is not shipped in installed copies")
    def test_the_workspace_hides_the_guidance(self):
        """The chat view keeps its own list of internal prefixes."""
        source = (Path(__file__).resolve().parent.parent / "frontend/src/api.ts").read_text(encoding="utf-8")
        self.assertIn("TOOL CALL NOT READ", source)


class SeamlessSwitchTests(unittest.TestCase):
    """Switching to the Strata model must look like switching any other model (owner, 2026-10-06)."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.cfg = strata_config(self.root)

    def tearDown(self):
        self.temp.cleanup()

    def test_a_saved_llama_flash_next_selection_moves_to_the_same_model(self):
        """The llama.cpp entry was removed once this one was qualified (owner, 2026-10-07)."""
        from harness.application import ApplicationService
        from tests import test_workspace as helpers
        with tempfile.TemporaryDirectory() as temporary:
            cfg = strata_config(Path(temporary))
            runtime = cfg.path("paths.runtime_dir")
            runtime.mkdir(parents=True, exist_ok=True)
            (runtime / "workspace-settings.json").write_text(json.dumps({
                "model": "flash_next_q3", "last_running_model": "flash_next_q3",
                "adaptive_kv_requests": {"flash_next_q3": "q8_0_192k"}}), encoding="utf-8")
            service = ApplicationService(cfg, llm_factory=helpers.Model, manage_model=False)
            try:
                self.assertEqual(service.preferences["model"], KEY)
                self.assertEqual(service.preferences["last_running_model"], KEY)
                self.assertNotIn("adaptive_kv_requests", service.preferences)
            finally:
                service.close()
                service.models.wait(3)

    def test_nothing_the_user_sees_names_the_engine(self):
        model = self.cfg.model(KEY)
        iq2 = self.cfg.model(IQ2)
        shown = [model["alias"], model["status_label"], iq2["alias"], iq2["status_label"],
                 *(p["label"] for p in self.cfg.kv_cache_profiles(KEY).values()),
                 *(p["label_cs"] for p in self.cfg.kv_cache_profiles(KEY).values()),
                 # The setup hint after it names config keys; it lasts only while the entry is hidden.
                 strata_backend.explain(self.cfg, KEY, ["the engine: x"]),
                 strata_backend.start_failure(self.cfg, {"engine_log": "", "log_offset": 0}).split(". Logs:")[0]]
        for text in shown:
            self.assertNotRegex(text, "(?i)strata|llama", text)
        self.assertEqual({p["label"] for p in self.cfg.kv_cache_profiles(KEY).values()}, {"Q8 · 256k", "Q8 · 128k"})

    def test_picture_estimate_follows_the_model_of_each_run(self):
        from harness.agent import Agent, build_registry
        from harness.safety import SafetyPolicy
        from harness.session import Session
        self.cfg.data["paths"]["sessions_dir"] = str(self.root / "sessions")
        session = Session(self.cfg)                         # the conversation, made with the service's config
        for key, expected in ((KEY, 1024), ("q5", Session.IMAGE_TOKENS), (KEY, 1024)):
            run = Config(copy.deepcopy(self.cfg.data), self.root)
            run.data["default_model"] = key
            Agent(run, object(), session, build_registry("agent"), SafetyPolicy("auto"), mode="agent")
            self.assertEqual(session.image_tokens(), expected, key)

    def test_prompt_progress_reads_the_monitor_while_the_prompt_is_read(self):
        def answer(live):
            return SimpleNamespace(json=lambda: {"live": live})
        reading = {"state": "reading", "prompt_read": 65536, "prompt_total": 120000, "elapsed_s": 12.5,
                   "prefill_tok_s_mean": 5600.0}
        with patch("requests.get", return_value=answer(reading)) as get:
            self.assertEqual(strata_backend.prompt_progress(self.cfg),
                             {"total": 120000, "processed": 65536, "time_ms": 12500, "rate": 5600.0})
        self.assertEqual(get.call_args.args[0], "http://127.0.0.1:8080/metrics")
        for live in ({"state": "generating", "prompt_total": 120000}, {"state": "reading", "prompt_total": None},
                     {"state": "idle"}):
            with self.subTest(live), patch("requests.get", return_value=answer(live)):
                self.assertIsNone(strata_backend.prompt_progress(self.cfg))
        import requests
        with patch("requests.get", side_effect=requests.ConnectionError("busy")):
            self.assertIsNone(strata_backend.prompt_progress(self.cfg))

    def test_the_client_reports_prompt_progress_until_the_answer_starts(self):
        from harness.llm import LLMClient
        self.cfg.data["default_model"] = KEY
        first_chunk = threading.Event()

        def chunks():
            first_chunk.wait(5)
            delta = SimpleNamespace(content="Hi", reasoning_content=None, tool_calls=None)
            yield SimpleNamespace(choices=[SimpleNamespace(delta=delta)], usage=None)

        polls = []

        def progress(cfg):
            polls.append(1)
            if len(polls) == 2:
                first_chunk.set()
            return {"total": 100, "processed": 40 * len(polls), "time_ms": 1000 * len(polls)}

        client = LLMClient(self.cfg)
        client.client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(
            create=lambda **params: chunks())))
        seen = []
        with patch.object(strata_backend, "prompt_progress", side_effect=progress):
            result = client.stream([{"role": "user", "content": "hi"}], on_prompt_progress=seen.append)
        self.assertEqual(result.content, "Hi")
        self.assertGreaterEqual(len(seen), 1)
        self.assertEqual(seen[0], {"total": 100, "processed": 40, "time_ms": 1000})

    def test_llama_models_are_never_polled(self):
        from harness.llm import LLMClient
        self.cfg.data["default_model"] = "q5"
        client = LLMClient(self.cfg)
        client.client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(
            create=lambda **params: iter(()))))
        with patch.object(strata_backend, "prompt_progress", side_effect=AssertionError("llama streams its own")):
            client.stream([{"role": "user", "content": "hi"}], on_prompt_progress=lambda p: None)


class WebStateTests(unittest.TestCase):
    def test_picker_describes_the_strata_entry_from_its_capabilities(self):
        from fastapi.testclient import TestClient
        from harness.application import ApplicationService
        from harness.web_api import create_app
        from tests import test_workspace as helpers
        with tempfile.TemporaryDirectory() as temporary:
            cfg = strata_config(Path(temporary))
            cfg.data["agent"].update(workspace=None, autonomy="auto")
            service = ApplicationService(cfg, llm_factory=helpers.Model, manage_model=False)
            try:
                with patch("harness.gpu.vram_total_gb", return_value=31.84), \
                     patch("harness.gpu.installed_ram_gib", return_value=63.7):
                    models = TestClient(create_app(cfg, service=service)).get("/api/state").json()["models"]
            finally:
                service.close()
                service.models.wait(3)
        entry = next(m for m in models if m["id"] == KEY)
        self.assertTrue(entry["vision"])
        self.assertTrue(entry["uses_system_ram"])
        self.assertFalse(entry["installed"])
        self.assertEqual([p["id"] for p in entry["profiles"]], [P256, P128])


if __name__ == "__main__":
    unittest.main()
