"""Desktop prerequisite recovery; never change the machine's shared runtime."""
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
import winreg

from harness import webview_runtime as runtime


class WebViewRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.directory = self.root / "runtime/webview2"
        self.directory.mkdir(parents=True)
        self.manifest = {}
        for kind in ("standalone", "bootstrapper"):
            content = ("MZ-test-" + kind).encode()
            self.manifest[kind] = {"filename": kind + ".exe", "size": len(content),
                                   "sha256": hashlib.sha256(content).hexdigest(),
                                   "url": "https://example.invalid/pinned.exe"}
        (self.directory / "webview2.json").write_text(json.dumps(self.manifest))

    def payload(self, kind, directory=None):
        path = (directory or self.directory) / self.manifest[kind]["filename"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(("MZ-test-" + kind).encode())
        return path

    def test_registry_checks_user_machine_and_both_views(self):
        handle = Mock()
        handle.__enter__ = Mock(return_value=handle)
        handle.__exit__ = Mock(return_value=False)
        with patch.object(winreg, "OpenKey", return_value=handle) as opened, \
             patch.object(winreg, "QueryValueEx", side_effect=[("0.0.0.0", 1), ("bad", 1),
                                                             ("152.0.4191.66", 1), ("87.0.622.0", 1)]):
            self.assertEqual(runtime.installed_version(), "152.0.4191.66")
        self.assertEqual(opened.call_count, 4)
        self.assertEqual({call.args[0] for call in opened.call_args_list},
                         {winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE})
        self.assertEqual({call.args[3] for call in opened.call_args_list},
                         {winreg.KEY_READ | winreg.KEY_WOW64_32KEY, winreg.KEY_READ | winreg.KEY_WOW64_64KEY})

    def test_missing_registry_returns_none(self):
        with patch.object(winreg, "OpenKey", side_effect=FileNotFoundError):
            self.assertIsNone(runtime.installed_version())

    def test_existing_runtime_does_not_require_payload_or_network(self):
        with patch.object(runtime, "installed_version", return_value="152.0.4191.66"), \
             patch.object(runtime, "_install") as install, patch.object(runtime.urllib.request, "urlopen") as network:
            self.assertEqual(runtime.ensure_webview2(self.root / "absent"), "present")
            install.assert_not_called()
            network.assert_not_called()

    def test_full_uses_standalone_without_network(self):
        standalone = self.payload("standalone")
        self.payload("bootstrapper")
        with patch.object(runtime, "installed_version", return_value=None), \
             patch.object(runtime, "_install", return_value=True) as install, \
             patch.object(runtime.urllib.request, "urlopen") as network:
            self.assertEqual(runtime.ensure_webview2(self.root), "installed")
            self.assertEqual(install.call_args.args[0], standalone)
            network.assert_not_called()

    def test_minimal_uses_bundled_bootstrapper(self):
        bootstrap = self.payload("bootstrapper")
        with patch.object(runtime, "installed_version", return_value=None), \
             patch.object(runtime, "_install", return_value=True) as install:
            runtime.ensure_webview2(self.root)
            self.assertEqual(install.call_args.args[0], bootstrap)

    def test_registered_offline_backup_preferred_to_bootstrapper(self):
        backup = self.root / "backup"
        standalone = self.payload("standalone", backup / "payload/runtime/webview2")
        self.payload("bootstrapper")
        (self.root / "runtime/offline-backup-path.txt").write_text(str(backup))
        with patch.object(runtime, "installed_version", return_value=None), \
             patch.object(runtime, "_install", return_value=True) as install:
            runtime.ensure_webview2(self.root)
            self.assertEqual(install.call_args.args[0], standalone)

    def test_damaged_standalone_falls_back_without_executing_it(self):
        self.payload("standalone").write_bytes(b"tampered")
        bootstrap = self.payload("bootstrapper")
        with patch.object(runtime, "installed_version", return_value=None), \
             patch.object(runtime, "_install", return_value=True) as install:
            runtime.ensure_webview2(self.root)
            self.assertEqual(install.call_args.args[0], bootstrap)

    def test_missing_payload_downloads_and_verifies_pinned_bootstrapper(self):
        with patch.object(runtime, "installed_version", return_value=None), \
             patch.object(runtime, "_install", return_value=True) as install, \
             patch.object(runtime.urllib.request, "urlopen", return_value=io.BytesIO(b"MZ-test-bootstrapper")):
            self.assertEqual(runtime.ensure_webview2(self.root), "installed")
            self.assertTrue(install.call_args.args[0].is_file())

    def test_corrupt_download_never_executes(self):
        with patch.object(runtime, "installed_version", return_value=None), \
             patch.object(runtime, "_install") as install, \
             patch.object(runtime.urllib.request, "urlopen", return_value=io.BytesIO(b"bad")):
            with self.assertRaisesRegex(ValueError, "checksum"):
                runtime.ensure_webview2(self.root)
            install.assert_not_called()
        self.assertFalse(list(self.directory.glob("*.download")))

    def test_silent_command_without_console(self):
        path = self.payload("bootstrapper")
        with patch.object(runtime.subprocess, "Popen") as popen:
            runtime._start_installer(path)
        self.assertEqual(popen.call_args.args[0], [str(path), "/silent", "/install"])
        self.assertEqual(popen.call_args.kwargs["creationflags"], 0x08000000)

    def test_exit_success_without_runtime_is_not_success(self):
        process = Mock(returncode=0)
        process.poll.return_value = 0
        with patch.object(runtime, "_start_installer", return_value=process), \
             patch.object(runtime, "installed_version", return_value=None), patch.object(runtime.time, "sleep"):
            self.assertFalse(runtime._install(Path("test.exe"), lambda _: None))

    def test_delayed_registration_is_accepted_even_after_busy_exit(self):
        process = Mock(returncode=1)
        process.poll.return_value = 1
        with patch.object(runtime, "_start_installer", return_value=process), \
             patch.object(runtime, "installed_version", side_effect=[None, None, "152.0.4191.66"]), \
             patch.object(runtime.time, "sleep"):
            self.assertTrue(runtime._install(Path("test.exe"), lambda _: None))

    def test_timeout_does_not_kill_shared_updater(self):
        process = Mock()
        process.poll.return_value = None
        with patch.object(runtime, "_start_installer", return_value=process):
            with self.assertRaises(TimeoutError):
                runtime._install(Path("test.exe"), lambda _: None, timeout=0)
        process.kill.assert_not_called()
        process.terminate.assert_not_called()

    def test_installer_entry_point_needs_no_venv_or_model(self):
        from launcher import launcher_app
        with patch.object(launcher_app, "ROOT", self.root), \
             patch.object(launcher_app, "ensure_webview2", return_value="installed") as prepare, \
             patch.object(launcher_app, "_show_splash") as splash, \
             patch.object(launcher_app.subprocess, "Popen") as process, \
             patch("sys.argv", ["Marvin.exe", "--prepare-webview2"]):
            self.assertEqual(launcher_app.main(), 0)
            prepare.assert_called_once()
            splash.assert_not_called()
            process.assert_not_called()

    def test_offline_backup_round_trip_includes_desktop_payload(self):
        from scripts.offline_backup import _runtime_sources, restore_backup
        self.payload("standalone")
        self.payload("bootstrapper")
        sources = [entry for entry in _runtime_sources(self.root) if entry[2] == "webview2"]
        self.assertEqual(len(sources), 3)
        backup = self.root / "backup"
        files = []
        for source, relative, component in sources:
            target = backup / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(source.read_bytes())
            files.append({"path": relative.as_posix(), "size": source.stat().st_size,
                          "sha256": hashlib.sha256(source.read_bytes()).hexdigest(), "component": component})
        (backup / "manifest.json").write_text(json.dumps({"format_version": 2, "files": files}))
        destination = self.root / "restored"
        restore_backup(destination, backup, {"webview2"})
        for source, _, _ in sources:
            self.assertEqual((destination / "runtime/webview2" / source.name).read_bytes(), source.read_bytes())


if __name__ == "__main__":
    unittest.main()
