"""Localization boundaries, compatibility, safe startup and package coverage."""
import json
import copy
from pathlib import Path
import re
import runpy
from string import Formatter
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from harness import i18n
from harness.agent import DOCUMENT_OPERATION_RE
from harness.config import Config, DEFAULTS

ROOT = Path(__file__).resolve().parent.parent
LOCALIZED_DOCS = {"docs/manual/manual_cs.md", "docs/distribution/INSTALL-CS.md"}
CZECH_CHARACTERS = re.compile("[\u00e1\u010d\u010f\u00e9\u011b\u00ed\u0148\u00f3\u0159\u0161\u0165\u00fa\u016f\u00fd\u017e]", re.I)
TEXT_SUFFIXES = {"", ".py", ".ts", ".tsx", ".js", ".mjs", ".css", ".html", ".md", ".txt",
                 ".yaml", ".yml", ".json", ".toml", ".ps1", ".bat", ".iss", ".spec"}


class LocalizationTests(unittest.TestCase):
    def test_english_fallback_and_explicit_czech(self):
        with patch.object(i18n, "_current", "en"):
            self.assertEqual(i18n.t("Settings"), "Settings")
            self.assertNotEqual(i18n.translate("Settings", "cs"), "Settings")
            self.assertEqual(i18n.translate("New untranslated message", "cs"), "New untranslated message")
            i18n.set_language("cs")
            self.assertEqual(i18n.t("Settings"), i18n.translate("Settings", "cs"))
            i18n.set_language("unsupported")
            self.assertEqual(i18n.t("Settings"), "Settings")

    def test_missing_malformed_or_wrongly_typed_catalog_never_blocks_import(self):
        for value in ("{", "[]", '{"messages": [], "aliases": 42, "native_name": 9}'):
            with self.subTest(value=value), patch.object(Path, "read_text", return_value=value):
                module = runpy.run_path(str(ROOT / "harness/i18n.py"))
                self.assertEqual(module["translate"]("Settings", "cs"), "Settings")
                self.assertEqual(module["normalize"]("cs"), "cs")
        with patch.object(Path, "read_text", side_effect=OSError("missing")):
            module = runpy.run_path(str(ROOT / "harness/i18n.py"))
            self.assertEqual(module["LANGUAGES"]["cs"], "Czech")

    def test_malformed_optional_pattern_and_placeholder_fall_back(self):
        with patch.object(i18n, "_CATALOG", {"document_operation_pattern": "["}):
            self.assertEqual(i18n.input_pattern("document_operation_pattern"), "")
        with patch.object(i18n, "_CS", {"Hello {name}": "Hello {wrong}"}):
            self.assertEqual(i18n.translate("Hello {name}", "cs", name="Alex"), "Hello Alex")

    def test_saved_workspace_language_precedes_legacy_and_installer(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runtime = root / "runtime"
            runtime.mkdir()
            self.assertIsNone(i18n.detect_language(root))
            (runtime / "ui-language.txt").write_text("cs", encoding="utf-8")
            self.assertEqual(i18n.detect_language(root), "cs")
            (runtime / "webui-state.json").write_text('{"language":"en"}', encoding="utf-8")
            self.assertEqual(i18n.detect_language(root), "en")
            current = runtime / "workspace-settings.json"
            current.write_text('{"language":"cs"}', encoding="utf-8")
            self.assertEqual(i18n.detect_language(root), "cs")
            current.write_text('{"language":"en"}', encoding="utf-8")
            self.assertEqual(i18n.detect_language(root), "en")
            current.write_text('{', encoding="utf-8")
            self.assertEqual(i18n.detect_language(root), "en")

    def test_legacy_input_remains_supported_in_english_ui(self):
        with patch.object(i18n, "_current", "en"):
            for value in ("Save the answer as PDF", *i18n.locale_data("document_operation_examples", [])):
                self.assertRegex(value, DOCUMENT_OPERATION_RE)
        # The existing core suite checks migration from these original labels/headings.
        self.assertTrue(i18n.locale_data("legacy_profile_labels", {}))
        self.assertTrue(i18n.locale_data("legacy_memory_heading", ""))

    def test_every_builtin_profile_has_an_english_label_and_external_translation(self):
        cfg = Config(copy.deepcopy(DEFAULTS))
        for model in cfg.data["models"]:
            for profile in cfg.kv_cache_profiles(model).values():
                label = profile["label"]
                with self.subTest(model=model, label=label):
                    self.assertNotRegex(label, CZECH_CHARACTERS)
                    self.assertIn(label, i18n._CS)
                    self.assertEqual(profile["label_cs"], i18n.translate(label, "cs"))

    def test_catalog_placeholders_match_english_messages(self):
        def fields(text):
            return {name for _, name, _, _ in Formatter().parse(text) if name is not None}
        for original, translated in i18n._CS.items():
            with self.subTest(message=original):
                self.assertEqual(fields(original), fields(translated))

    @unittest.skipUnless((ROOT / "frontend/src").is_dir(), "Frontend source is not shipped in installed copies")
    def test_frontend_literal_translation_keys_are_in_the_catalog(self):
        pattern = re.compile(r'\b(?:tr|translate)\(\s*("(?:[^"\\]|\\.)*")')
        for path in (ROOT / "frontend/src").rglob("*"):
            if path.suffix not in (".ts", ".tsx"):
                continue
            for literal in pattern.findall(path.read_text(encoding="utf-8")):
                self.assertIn(json.loads(literal), i18n._CS, str(path.relative_to(ROOT)))

    @unittest.skipUnless((ROOT / "installer/marvin.iss").is_file(), "Build manifests are not shipped in installed copies")
    def test_packaging_includes_catalog_and_installer_resources(self):
        setup = (ROOT / "installer/marvin.iss").read_text(encoding="utf-8")
        self.assertIn(r'harness\locales\*.json', setup)
        self.assertIn('harness/locales', (ROOT / "Marvin.spec").read_text(encoding="utf-8"))
        self.assertIn(r'harness\locales;harness\locales', (ROOT / "installer/build_exe.bat").read_text(encoding="utf-8"))
        for relative in re.findall(r'#include "([^"]+)"', setup):
            self.assertTrue((ROOT / "installer" / relative).is_file(), relative)

    @unittest.skipUnless((ROOT / ".git").exists(), "Source-tree check; installed copies have no Git metadata")
    def test_czech_text_is_confined_to_localization_and_user_guides(self):
        files = subprocess.check_output(["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"], cwd=ROOT).decode().split("\0")
        errors = []
        for name in files:
            path = ROOT / name
            if name in LOCALIZED_DOCS or name.startswith(("harness/locales/", "installer/locales/")):
                continue
            if path.is_file() and path.suffix in TEXT_SUFFIXES:
                for number, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
                    if CZECH_CHARACTERS.search(line):
                        errors.append(f"{name}:{number}")
        self.assertEqual(errors, [], "Move translations into a locale resource: " + ", ".join(errors))


class HarnessMessageTests(unittest.TestCase):
    """Messages the harness itself produces reached the Czech interface in English:
    set_language was only ever called by the legacy Gradio surface."""

    # Every message the harness emits to the user as a notice.
    HARNESS_MESSAGES = (
        "Adjusting the memory profile and continuing the task.",
        "Auto-commit failed: {error}",
        "Auto-committed as {hash} ({count} files)",
        "📦 Context ~{est} tokens (over 85% of {limit}) - summarizing the earlier conversation ...",
        "📦 Context trimmed: ~{est} to ~{new} tokens",
        "📦 Context compressed: ~{est} to ~{new} tokens; the full history is kept",
        "📦 Summarization failed ({error}) - applied a hard trim",
        "Preparing the research plan before searching...",
        "Context overflow: compressing and retrying...",
        "Preparing the final synthesis from all loaded sources...",
    )

    def tearDown(self):
        from harness.i18n import set_language
        set_language("en")

    def test_every_harness_message_has_a_czech_translation(self):
        import json
        locale = json.loads(
            (Path(__file__).resolve().parent.parent / "harness" / "locales"
             / "cs.json").read_text(encoding="utf-8"))["messages"]
        missing = [text for text in self.HARNESS_MESSAGES
                   if not locale.get(text, "").strip()]
        self.assertEqual(missing, [], "Missing Czech: %s" % missing)

    def test_the_translation_keeps_every_placeholder(self):
        import json
        import re
        locale = json.loads(
            (Path(__file__).resolve().parent.parent / "harness" / "locales"
             / "cs.json").read_text(encoding="utf-8"))["messages"]
        for text in self.HARNESS_MESSAGES:
            expected = set(re.findall(r"{(\w+)}", text))
            actual = set(re.findall(r"{(\w+)}", locale[text]))
            self.assertEqual(actual, expected,
                             "Placeholders differ for %r" % text)

    def test_the_workspace_sets_the_catalogue_language(self):
        """Constructing the service must move the catalogue, not just the UI."""
        import copy
        import tempfile
        from harness.application import ApplicationService
        from harness.config import Config, load_config
        from harness.i18n import get_language, t
        with tempfile.TemporaryDirectory() as directory:
            data = copy.deepcopy(load_config().data)
            data["agent"].update(workspace=None, autonomy="auto")
            cfg = Config(data, Path(directory))
            service = ApplicationService(cfg, llm_factory=lambda c: None,
                                         manage_model=False)
            try:
                service.preferences["language"] = "cs"
                from harness.i18n import set_language
                set_language("cs")
                self.assertEqual(get_language(), "cs")
                # Compared against the catalogue, so no Czech lives in the source.
                import json
                catalogue = json.loads(
                    (Path(__file__).resolve().parent.parent / "harness" / "locales"
                     / "cs.json").read_text(encoding="utf-8"))["messages"]
                key = "Adjusting the memory profile and continuing the task."
                self.assertEqual(t(key), catalogue[key])
                self.assertNotEqual(t(key), key)
            finally:
                service.close()
                service.models.wait(3)


if __name__ == "__main__":
    unittest.main()
