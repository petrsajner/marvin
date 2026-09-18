"""Capability catalogue: coverage of the registry, availability and translations.

The catalogue is curated prose, so nothing stops it drifting away from the code
except these tests. The coverage test is the important one: a new tool that nobody
decided to advertise fails the suite instead of quietly never being mentioned."""
import copy
import json
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from harness import capabilities
from harness.application import ApplicationService
from harness.capabilities import CAPABILITIES, CATEGORIES, INTERNAL_TOOLS
from harness.config import Config, load_config
from harness.web_api import create_app
from harness.work_modes import WORK_MODES

LOCALE = Path(__file__).resolve().parent.parent / "harness" / "locales" / "cs.json"


class CatalogueTests(unittest.TestCase):
    def test_every_registered_tool_is_mapped_or_explicitly_internal(self):
        """A new tool must be a decision, not an omission."""
        registered = set()
        for mode in WORK_MODES:
            registered |= capabilities.registry_tools(mode)
        mapped = {tool for item in CAPABILITIES for tool in item.tools}
        unclassified = sorted(registered - mapped - set(INTERNAL_TOOLS))
        self.assertEqual(
            unclassified, [],
            "Map these tools to a capability or list them in INTERNAL_TOOLS "
            f"with a reason: {unclassified}")

    def test_no_capability_names_a_tool_that_does_not_exist(self):
        registered = set()
        for mode in WORK_MODES:
            registered |= capabilities.registry_tools(mode)
        for item in CAPABILITIES:
            missing = sorted(set(item.tools) - registered)
            self.assertEqual(missing, [], f"{item.id} names unknown tools: {missing}")

    def test_declared_modes_actually_register_the_tools(self):
        for item in CAPABILITIES:
            for mode in item.modes:
                present = capabilities.registry_tools(mode)
                missing = sorted(set(item.tools) - present)
                self.assertEqual(
                    missing, [],
                    f"{item.id} claims {mode} but it does not register: {missing}")

    def test_internal_tools_are_real_and_carry_a_reason(self):
        registered = set()
        for mode in WORK_MODES:
            registered |= capabilities.registry_tools(mode)
        for name, reason in INTERNAL_TOOLS.items():
            self.assertIn(name, registered, f"INTERNAL_TOOLS lists unknown tool {name}")
            self.assertTrue(reason.strip(), f"{name} needs a reason")

    def test_entries_are_well_formed(self):
        seen = set()
        for item in CAPABILITIES:
            self.assertNotIn(item.id, seen, f"duplicate capability id {item.id}")
            seen.add(item.id)
            self.assertIn(item.category, CATEGORIES, f"{item.id} has an unknown category")
            self.assertTrue(item.modes, f"{item.id} has no modes")
            self.assertTrue(item.tools, f"{item.id} has no tools")
            for mode in item.modes:
                self.assertIn(mode, WORK_MODES, f"{item.id} names unknown mode {mode}")
            # Entries describe an outcome; the model-facing vocabulary must not leak.
            # Only identifier-shaped names are checked: tools called "click" or
            # "scroll" share their name with ordinary English words.
            identifiers = [tool for tool in item.tools if "_" in tool]
            for field in (item.title, item.summary, item.example):
                self.assertTrue(field.strip(), f"{item.id} has an empty field")
                for tool in identifiers:
                    self.assertNotIn(tool, field,
                                     f"{item.id} exposes the tool name {tool} to the user")

    def test_availability_follows_the_mode(self):
        research_only = next(item for item in CAPABILITIES if item.id == "research_run")
        self.assertEqual(research_only.modes, ("research",))
        by_mode = {mode: {row["id"]: row["available"] for row in capabilities.for_mode(mode)}
                   for mode in WORK_MODES}
        self.assertTrue(by_mode["research"]["research_run"])
        self.assertFalse(by_mode["discussion"]["research_run"])
        self.assertTrue(by_mode["computer"]["control_computer"])
        self.assertFalse(by_mode["writing"]["control_computer"])
        # Available everywhere means available in every mode.
        self.assertTrue(all(by_mode[mode]["read_documents"] for mode in WORK_MODES))

    def test_missing_tool_makes_an_entry_unavailable(self):
        original = capabilities.registry_tools

        def without_export(mode):
            return original(mode) - {"export_document"}

        capabilities.registry_tools = without_export
        try:
            rows = {row["id"]: row["available"] for row in capabilities.for_mode("writing")}
        finally:
            capabilities.registry_tools = original
        self.assertFalse(rows["export_document"])
        self.assertTrue(rows["read_documents"])

    def test_unknown_mode_is_rejected(self):
        with self.assertRaises(ValueError):
            capabilities.for_mode("nonsense")

    def test_every_user_visible_string_has_a_czech_translation(self):
        messages = json.loads(LOCALE.read_text(encoding="utf-8"))["messages"]
        missing = []
        for item in CAPABILITIES:
            for field in (item.title, item.summary, item.example):
                if field not in messages or not messages[field].strip():
                    missing.append(f"{item.id}: {field}")
        self.assertEqual(missing, [], "Missing Czech translations: " + "; ".join(missing))


class CatalogueEndpointTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        data = copy.deepcopy(load_config().data)
        data["hardware"]["vram_gb"] = 32
        data["agent"].update(workspace=None, autonomy="auto")
        self.cfg = Config(data, self.root)
        self.service = ApplicationService(self.cfg, llm_factory=lambda c: None,
                                          manage_model=False)
        self.client = TestClient(create_app(self.cfg, service=self.service))

    def tearDown(self):
        self.service.close()
        self.service.models.wait(3)
        self.temp.cleanup()

    def test_endpoint_reports_availability_per_mode(self):
        for mode in WORK_MODES:
            payload = self.client.get("/api/capabilities", params={"mode": mode}).json()
            self.assertEqual(payload["mode"], mode)
            self.assertEqual(len(payload["capabilities"]), len(CAPABILITIES))
            rows = {row["id"]: row for row in payload["capabilities"]}
            self.assertEqual(rows["research_run"]["available"], mode == "research")
            self.assertEqual(rows["control_computer"]["available"], mode == "computer")
            self.assertTrue(rows["read_documents"]["available"])

    def test_endpoint_rejects_an_unknown_mode(self):
        self.assertEqual(
            self.client.get("/api/capabilities", params={"mode": "nope"}).status_code, 400)


if __name__ == "__main__":
    unittest.main()
