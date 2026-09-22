"""The published version number agrees across the places that ship it.

installer/version.txt is the single source at build time; the frontend and the
installer fallback carried their own stale numbers (1.9.0 and 1.14.1 against
1.16.1), which is how a user ends up with two version figures on one screen."""
import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class VersionSyncTests(unittest.TestCase):
    def test_published_version_references_agree(self):
        canonical = (ROOT / "installer" / "version.txt").read_text(
            encoding="utf-8-sig").strip()
        self.assertRegex(canonical, r"^\d+\.\d+\.\d+$")
        package = json.loads(
            (ROOT / "frontend" / "package.json").read_text(encoding="utf-8"))
        self.assertEqual(package["version"], canonical)
        iss = (ROOT / "installer" / "marvin.iss").read_text(encoding="utf-8-sig")
        fallback = re.search(r'#define MyAppVersion "([^"]+)"', iss)
        self.assertIsNotNone(fallback, "installer fallback version is missing")
        self.assertEqual(fallback.group(1), canonical)


if __name__ == "__main__":
    unittest.main()
