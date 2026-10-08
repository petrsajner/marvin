"""Marvin prepares the Strata engine and a Flash-Next model's derived files itself (Phase 3)."""
from __future__ import annotations

import io
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile

from harness import strata_backend, strata_runtime
from tests.test_strata_backend import KEY, StrataInstallation, strata_config


def zip_bytes(files: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    return buffer.getvalue()


SOURCE = {"Strata-0.1.39/serve/server.py": b"server", "Strata-0.1.39/tools/iq_pack.py": b"pack",
          "Strata-0.1.39/tools/mtp_fetch.py": b"fetch", "Strata-0.1.39/data/expert-profile.bin": b"profile",
          "Strata-0.1.39/data/draft_vocab.bin": b"vocab", "Strata-0.1.39/LICENSE": b"MIT"}
GGUF_PY = {"llama.cpp-abc/gguf-py/gguf/__init__.py": b"gguf", "llama.cpp-abc/ggml/CMakeLists.txt": b"not needed"}


class Runtime:
    """A Marvin root whose archive cache already holds the pinned downloads, and fake tools."""

    def __init__(self, *, version=strata_runtime.VERSION):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.cfg = strata_config(self.root)
        self.cache = self.cfg.path("paths.runtime_dir") / "runtime-archives" / f"strata-{strata_runtime.VERSION}"
        self.cache.mkdir(parents=True)
        engine = zip_bytes({"strata.exe": b"engine", "strata-vision.exe": b"vision",
                            "BUILD.json": json.dumps({"version": version}).encode()})
        self.specs = {}
        for name, files, spec in (("source", SOURCE, strata_runtime.SOURCE), ("gguf_py", GGUF_PY, strata_runtime.GGUF_PY)):
            data = zip_bytes(files)
            (self.cache / spec["name"]).write_bytes(data)
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                self.specs[name] = {**spec, "content": strata_runtime._content_digest(archive, spec.get("subtree", ""))}
        (self.cache / strata_runtime.ENGINE["name"]).write_bytes(engine)
        self.specs["engine"] = {**strata_runtime.ENGINE, "sha256": __import__("hashlib").sha256(engine).hexdigest()}
        self.commands = []
        self.pip_fails = False

    def run(self, argv, *, cwd, env=None, cancelled=None, progress=print, what):
        argv = [str(a) for a in argv]
        self.commands.append(argv)
        if argv[1:3] == ["-m", "venv"]:
            python = Path(argv[3]) / "Scripts" / "python.exe"
            python.parent.mkdir(parents=True)
            python.write_bytes(b"python")
        elif "pip" in argv:
            if self.pip_fails:
                raise RuntimeError(f"{what} failed (exit code 1): no matching hash")
            dll = Path(argv[0]).parent.parent / "Lib/site-packages/nvidia/cu13/bin/x86_64/cublas64_13.dll"
            dll.parent.mkdir(parents=True)
            dll.write_bytes(b"cublas")

    def patches(self):
        return [patch.object(strata_runtime, "SOURCE", self.specs["source"]),
                patch.object(strata_runtime, "GGUF_PY", self.specs["gguf_py"]),
                patch.object(strata_runtime, "ENGINE", self.specs["engine"]),
                patch.object(strata_runtime, "_run", side_effect=self.run),
                patch.object(strata_runtime, "_driver_version", return_value=591),
                patch.object(strata_runtime, "_base_python", return_value=Path("C:/Python312/python.exe"))]

    def close(self):
        patch.stopall()
        self.temp.cleanup()


class InstallTests(unittest.TestCase):
    def setUp(self):
        self.runtime = Runtime()
        self.cfg = self.runtime.cfg
        for p in self.runtime.patches():
            p.start()
        self.addCleanup(self.runtime.close)

    def install(self, **kwargs):
        return strata_runtime.install(self.cfg, progress=lambda *_: None, **kwargs)

    def test_the_engine_is_staged_checked_and_swapped_in(self):
        phases = []
        target = self.install(on_phase=phases.append)
        self.assertEqual(target, strata_backend.program_dir(self.cfg))
        self.assertEqual((target / "serve" / "server.py").read_bytes(), b"server")
        self.assertEqual((target / "third_party/llama.cpp/gguf-py/gguf/__init__.py").read_bytes(), b"gguf")
        self.assertFalse((target / "third_party/llama.cpp/ggml").exists(), "only gguf-py is taken from llama.cpp")
        self.assertTrue(strata_backend.engine_exe(self.cfg).is_file())
        self.assertTrue(strata_backend.vision_exe(self.cfg).is_file())
        record = strata_runtime.installed_record(self.cfg)
        self.assertEqual(record["version"], strata_runtime.VERSION)
        self.assertEqual(phases, ["downloading", "preparing"])
        pip = next(c for c in self.runtime.commands if "pip" in c)
        self.assertIn("--require-hashes", pip)
        self.assertEqual(pip[-1], str(strata_runtime.LOCK))
        self.assertEqual(self.runtime.commands[0][:3], ["C:\\Python312\\python.exe" if os.name == "nt"
                                                        else "C:/Python312/python.exe", "-m", "venv"])
        self.assertFalse(list((self.cfg.path("paths.runtime_dir") / "strata-candidates").iterdir()))
        self.assertTrue(strata_runtime.runtime_current(self.cfg, KEY))

    def test_the_full_installers_copy_needs_no_internet(self):
        bundled = self.cfg.root / "runtime" / "strata-offline"
        (bundled / "wheels").mkdir(parents=True)
        for spec in (strata_runtime.SOURCE, strata_runtime.ENGINE, strata_runtime.GGUF_PY):
            (self.runtime.cache / spec["name"]).rename(bundled / spec["name"])
        (bundled / "wheels" / "numpy-2.5.3-cp312-cp312-win_amd64.whl").write_bytes(b"wheel")
        with patch.object(strata_runtime, "BUNDLED", bundled), \
             patch("requests.get", side_effect=AssertionError("no download")):
            self.install()
        pip = next(c for c in self.runtime.commands if "pip" in c)
        self.assertEqual(pip[pip.index("--find-links") + 1], str(bundled / "wheels"))
        self.assertIn("--no-index", pip)
        self.assertTrue(strata_runtime.runtime_current(self.cfg, KEY))

    def test_a_failed_step_keeps_the_previous_engine(self):
        self.install()
        (strata_backend.program_dir(self.cfg) / "keep.txt").write_text("previous")
        self.runtime.pip_fails = True
        with self.assertRaisesRegex(RuntimeError, "Installing the engine's Python packages failed"):
            self.install()
        self.assertEqual((strata_backend.program_dir(self.cfg) / "keep.txt").read_text(), "previous")
        self.assertFalse(list((self.cfg.path("paths.runtime_dir") / "strata-candidates").iterdir()))

    def test_a_newer_install_preserves_the_previous_one(self):
        self.install()
        self.install()
        previous = list(strata_backend.program_dir(self.cfg).parent.glob("strata-previous-*"))
        self.assertEqual(len(previous), 1)

    def test_an_engine_of_another_version_is_refused_with_its_version(self):
        other = Runtime(version="0.1.38")
        self.addCleanup(other.close)
        patch.stopall()
        for p in other.patches():
            p.start()
        with self.assertRaisesRegex(RuntimeError, "reports version 0.1.38"):
            strata_runtime.install(other.cfg, progress=lambda *_: None)
        self.assertFalse(strata_backend.program_dir(other.cfg).exists())

    def test_a_download_that_does_not_match_is_not_kept(self):
        spec = {"url": "https://example.invalid/engine.zip", "name": "fresh.zip", "sha256": "0" * 64}
        response = SimpleNamespace(raise_for_status=lambda: None, iter_content=lambda size: [b"other bytes"])

        class Response:
            def __enter__(self):
                return response

            def __exit__(self, *exc):
                return False

        with patch("requests.get", return_value=Response()), \
             self.assertRaisesRegex(RuntimeError, "does not match its pinned checksum"):
            strata_runtime._fetch(spec, self.runtime.cache, progress=lambda *_: None)
        self.assertFalse((self.runtime.cache / "fresh.zip").exists())
        self.assertFalse((self.runtime.cache / "fresh.zip.part").exists())


class CurrencyTests(unittest.TestCase):
    def setUp(self):
        self.installation = StrataInstallation()
        self.cfg = self.installation.cfg
        self.addCleanup(self.installation.close)

    def test_a_folder_strata_setup_prepared_is_used_as_it_is(self):
        self.assertEqual(strata_runtime.installed_record(self.cfg), {})
        self.assertTrue(strata_runtime.runtime_current(self.cfg, KEY))
        with patch.object(strata_runtime, "install", side_effect=AssertionError("must not reinstall")):
            strata_runtime.ensure_runtime(self.cfg, KEY)

    def test_an_older_marvin_install_is_replaced(self):
        (strata_backend.program_dir(self.cfg) / strata_runtime.MARKER).write_text(
            json.dumps({"version": "0.1.38", "lock": strata_runtime._lock_digest()}))
        self.assertFalse(strata_runtime.runtime_current(self.cfg, KEY))
        with patch.object(strata_runtime, "install") as install:
            strata_runtime.ensure_runtime(self.cfg, KEY)
        install.assert_called_once()

    def test_a_missing_part_is_prepared(self):
        strata_backend.engine_exe(self.cfg).unlink()
        self.assertFalse(strata_runtime.runtime_current(self.cfg, KEY))


class PrepareModelTests(unittest.TestCase):
    def setUp(self):
        self.installation = StrataInstallation()
        self.cfg = self.installation.cfg
        self.addCleanup(self.installation.close)
        self.data = strata_backend.data_dir(self.cfg)
        self.spec = strata_backend.settings(self.cfg, KEY)
        program = strata_backend.program_dir(self.cfg)
        (program / "data" / "draft_vocab.bin").write_bytes(b"vocab")
        self.commands = []

    def run_tool(self, argv, *, cwd, env=None, cancelled=None, progress=print, what):
        argv = [str(a) for a in argv]
        self.commands.append((Path(argv[1]).name, argv, env))
        out = Path(argv[argv.index("--out") + 1])
        if argv[1].endswith("iq_pack.py"):
            (out / "tokenizer").mkdir(parents=True, exist_ok=True)
            (out / "tokenizer" / "vocab.json").write_text("{}")
            (out / "native_experts.txt").write_text("ok")
        elif argv[1].endswith("mtp_rt.py"):
            out.mkdir(parents=True)
            for name in ("experts.bin", "dense.bin", "dense.txt"):
                (out / name).write_bytes(b"rt")

    def prepare(self):
        with patch.object(strata_runtime, "_run", side_effect=self.run_tool):
            strata_runtime.prepare_model(self.cfg, KEY, progress=lambda *_: None)

    def test_a_complete_folder_is_left_alone(self):
        self.prepare()
        self.assertEqual([c[0] for c in self.commands], [])

    def test_the_pack_is_written_with_the_pinned_gguf_reader(self):
        (self.data / self.spec["pack"] / "native_experts.txt").unlink()
        self.prepare()
        name, argv, env = self.commands[0]
        self.assertEqual(name, "iq_pack.py")
        self.assertEqual(argv[argv.index("--gguf") + 1], str(self.cfg.model_file(KEY)))
        self.assertEqual(env["STRATA_GGUF_PY"],
                         str(strata_backend.program_dir(self.cfg) / "third_party" / "llama.cpp" / "gguf-py"))
        self.assertTrue((self.data / self.spec["pack"] / "native_experts.txt").is_file())

    def test_the_draft_layer_is_built_aside_and_then_put_in_place(self):
        rt = self.data / self.spec["mtp"]
        (rt / "dense.bin").unlink()          # an interrupted earlier run
        self.prepare()
        self.assertEqual([c[0] for c in self.commands], ["mtp_fetch.py", "mtp_pack.py", "mtp_rt.py"])
        self.assertTrue(self.commands[2][1][-1].endswith("rt.partial"))
        self.assertTrue(all((rt / name).read_bytes() == b"rt" for name in ("experts.bin", "dense.bin", "dense.txt")))
        self.assertEqual(len(list(rt.parent.glob("rt-incomplete-*"))), 1, "the interrupted folder is kept aside")
        self.assertEqual((rt / "draft_vocab.bin").read_bytes(), b"vocab")
        self.commands.clear()
        self.prepare()
        self.assertEqual(self.commands, [], "a second preparation has nothing to do")


if __name__ == "__main__":
    unittest.main()
