"""Image generation: the switch, the absent credential, and what the model is told.

Generating a picture is the one thing in this harness that calls a paid service
on the owner's account, so most of what matters here is refusal: off by default,
off when the switch says so whatever the model asks, and invisible to the model
entirely when it cannot be used.
"""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from harness import openart
from harness.agent import build_registry
from harness.config import Config, DEFAULTS, load_config
from harness.tools.base import AgentContext
from harness.tools.imagegen import GenerateImageTool


class OpenArtTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.cfg = Config(copy.deepcopy(load_config().data), self.root)
        self.cfg.data["paths"]["runtime_dir"] = str(self.root / "runtime")
        self.workspace = self.root / "project"
        self.workspace.mkdir()

    def _install_fake_cli(self):
        path = openart.openart_cli(self.cfg)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"not really a program")
        return path

    def _context(self):
        return AgentContext(cfg=self.cfg, session=SimpleNamespace(),
                            workspace=self.workspace, project_workspace=self.workspace)

    # -- the switch ----------------------------------------------------------
    def test_it_is_off_until_the_owner_turns_it_on(self):
        self.assertIn("openart", DEFAULTS)
        self.assertIs(DEFAULTS["openart"]["enabled"], False)
        self.assertFalse(openart.enabled(self.cfg))

    def test_the_model_is_not_told_about_a_tool_it_cannot_use(self):
        self.assertNotIn("generate_image", build_registry("agent", "development", self.cfg).names())
        self.cfg.data["openart"]["enabled"] = True
        self.assertIn("generate_image", build_registry("agent", "development", self.cfg).names())

    def test_without_a_configuration_the_tool_is_left_out(self):
        """The safe direction: a tool in the schema is a promise to the model."""
        self.assertNotIn("generate_image", build_registry("agent", "development").names())

    def test_signed_in_but_switched_off_still_refuses(self):
        self._install_fake_cli()
        with patch.object(openart, "account", return_value={"plan": "pro", "credits": 500}):
            result = openart.generate(self.cfg, "a fox", directory=self.workspace / "out")
        self.assertFalse(result["ok"])
        self.assertFalse((self.workspace / "out").exists(),
                         "a refused generation must not even make the folder")

    def test_the_tool_refuses_in_words_the_model_can_act_on(self):
        self.cfg.data["openart"]["enabled"] = False
        answer = GenerateImageTool().run(self._context(), prompt="a fox")
        self.assertTrue(answer.startswith("ERROR"))

    def test_enabled_but_not_installed_says_so_rather_than_failing(self):
        self.cfg.data["openart"]["enabled"] = True
        answer = GenerateImageTool().run(self._context(), prompt="a fox")
        self.assertTrue(answer.startswith("ERROR"))
        self.assertNotIn("Traceback", answer)

    # -- no credential anywhere ----------------------------------------------
    def test_the_configuration_holds_no_credential(self):
        """The CLI keeps its own in the user profile, so nothing reaches config.yaml,
        an export or a backup. There is nothing here to leak."""
        self.assertEqual(set(DEFAULTS["openart"]), {"enabled"})

    def test_signing_in_is_handed_back_rather_than_performed(self):
        self._install_fake_cli()
        argv = openart.login_argv(self.cfg)
        self.assertEqual(argv[-1], "login")
        self.assertTrue(argv[0].endswith("openart.exe"))

    def test_reported_account_carries_only_identity_and_balance(self):
        from harness.application import ApplicationService
        service = ApplicationService.__new__(ApplicationService)
        service.cfg = self.cfg
        service._openart_install = {"running": False, "error": "", "done": 0, "total": 0}
        service._openart_account = {"at": 0.0, "value": None}
        self._install_fake_cli()
        secret = {"email": "a@b.c", "plan": "pro", "credits": 500, "token": "SECRET-VALUE"}
        with patch.object(openart, "account", return_value=secret):
            state = ApplicationService.openart_state(service, refresh=True)
        self.assertEqual(set(state["account"]), {"name", "plan", "credits"})
        self.assertNotIn("SECRET-VALUE", json.dumps(state))

    # -- the pinned download --------------------------------------------------
    def test_the_program_is_pinned_and_verifiable(self):
        name, size, digest = openart.ARCHIVE
        self.assertTrue(name.endswith(".zip"))
        self.assertGreater(size, 0)
        self.assertEqual(len(digest), 64)
        self.assertTrue(all(c in "0123456789abcdef" for c in digest))
        self.assertEqual(openart.install_bytes(), size)

    # -- talking to the program ----------------------------------------------
    def test_a_missing_program_is_an_answer_not_an_exception(self):
        code, _, err = openart._run(self.cfg, ["account"])
        self.assertNotEqual(code, 0)
        self.assertTrue(err)

    def test_an_unreadable_answer_does_not_become_a_crash(self):
        self._install_fake_cli()
        with patch.object(openart, "_run", return_value=(0, "not json at all", "")):
            data, message = openart._json(self.cfg, ["account"])
        self.assertIsNone(data)
        self.assertIn("not json", message)

    def test_price_is_read_from_either_shape_the_cli_uses(self):
        self._install_fake_cli()
        with patch.object(openart, "_run", return_value=(0, json.dumps({"totalCredits": 12}), "")):
            self.assertEqual(openart.cost(self.cfg, "nano-banana-2"), 12)
        rows = {"items": [{"model": "nano-banana-2", "totalCredits": 9}]}
        with patch.object(openart, "_run", return_value=(0, json.dumps(rows), "")):
            self.assertEqual(openart.cost(self.cfg, "nano-banana-2"), 9)
        with patch.object(openart, "_run", return_value=(1, "", "no such model")):
            self.assertIsNone(openart.cost(self.cfg, "nonsense"))

    def test_a_picture_that_arrived_counts_even_if_the_wording_changes(self):
        """The directory is the authority on what was produced, so a reworded
        result must not make a generated picture look like a failure."""
        directory = self.workspace / "out"
        directory.mkdir()
        before = set()
        arrived = directory / "fox.png"
        arrived.write_bytes(b"\x89PNG\r\n\x1a\n")
        self.assertEqual(openart._saved_files({"wording": "changed"}, directory, before), [arrived])

    def test_the_payload_is_the_fallback_when_nothing_is_new(self):
        directory = self.workspace / "out"
        directory.mkdir()
        elsewhere = self.workspace / "elsewhere.png"
        elsewhere.write_bytes(b"\x89PNG\r\n\x1a\n")
        found = openart._saved_files({"file": str(elsewhere)}, directory, set())
        self.assertEqual(found, [elsewhere])

    def test_a_generated_picture_lands_in_the_project_and_is_shown(self):
        self.cfg.data["openart"]["enabled"] = True
        self._install_fake_cli()
        produced = self.workspace / openart.SAVE_DIRECTORY / "a.png"

        def fake_generate(cfg, prompt, *, model, directory, reference=None, timeout=0):
            directory.mkdir(parents=True, exist_ok=True)
            produced.write_bytes(b"\x89PNG\r\n\x1a\n")
            return {"ok": True, "files": [produced], "model": model}

        ctx = self._context()
        with patch.object(openart, "missing", return_value=[]), \
             patch.object(openart, "cost", return_value=7), \
             patch.object(openart, "generate", side_effect=fake_generate):
            answer = GenerateImageTool().run(ctx, prompt="a fox in snow", name="fox")
        saved = self.workspace / openart.SAVE_DIRECTORY / "fox.png"
        self.assertTrue(saved.is_file(), "the name the model asked for is used")
        self.assertIn("7", answer, "the price belongs in the answer")
        self.assertIn(saved, ctx.pending_images, "the model should see what it made")

    # -- what the model is told ----------------------------------------------
    def test_the_catalogue_names_the_models_the_owner_asked_for(self):
        ids = [row[0] for row in openart.MODELS]
        self.assertIn("nano-banana-2", ids)
        self.assertTrue(any(name.startswith("gpt-image-2-5") for name in ids))
        self.assertEqual(openart.DEFAULT_MODEL, "nano-banana-2")

    def test_the_description_is_fixed_text_so_the_prompt_stays_stable(self):
        """A catalogue fetched per session would change the tool description, and
        that travels in every request - the same way a changing system prompt
        cost a full reprocess."""
        first = GenerateImageTool().schema()
        second = GenerateImageTool().schema()
        self.assertEqual(first, second)
        for row in openart.MODELS:
            self.assertIn(row[0], first["function"]["description"])


if __name__ == "__main__":
    unittest.main()
