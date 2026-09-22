"""Configuration paths resolve against the right root.

The historical pitfall: load_config(path) read the YAML from `path` but rooted
every paths.* entry at the code directory, so an installed or --data-dir copy
scattered its sessions and runtime into the installation."""
import tempfile
import unittest
from pathlib import Path

from harness.config import ROOT, load_config


class ConfigRootTests(unittest.TestCase):
    def test_default_load_keeps_the_code_root(self):
        self.assertEqual(load_config().root, ROOT)

    def test_data_directory_config_roots_paths_to_its_own_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "config.yaml").write_text("web:\n  port: 7999\n", encoding="utf-8")
            cfg = load_config(root / "config.yaml")
            self.assertEqual(cfg.root, root)
            self.assertTrue(str(cfg.path("paths.runtime_dir")).startswith(str(root)))

    def test_explicit_root_wins(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "config.yaml").write_text("", encoding="utf-8")
            self.assertEqual(load_config(root / "config.yaml", root=ROOT).root, ROOT)


if __name__ == "__main__":
    unittest.main()
