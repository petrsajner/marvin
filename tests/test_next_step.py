"""The composer's next-step suggestion: tags in replies, streaming and the agent's record."""
from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from harness.config import load_config
from harness.next_step import (NextStepStreamFilter, clean_suggestion, derive_next_step,
                               split_next_step, summary_next_step)


class SplitNextStepTests(unittest.TestCase):
    def test_a_reply_without_a_tag_is_returned_unchanged(self):
        text = "Done.\n\n- a <b> c\n"
        self.assertEqual(split_next_step(text), (text, ""))

    def test_the_tag_is_removed_and_its_text_returned(self):
        clean, hint = split_next_step("Fixed.\n\n<next_step>Run the tests again</next_step>\n")
        self.assertEqual(clean, "Fixed.")
        self.assertEqual(hint, "Run the tests again")

    def test_the_last_usable_tag_wins_and_every_tag_is_removed(self):
        clean, hint = split_next_step(
            "Step 1 <next_step>Check the log</next_step> done.\n<NEXT_STEP>  Commit the\n changes </next_step>")
        self.assertEqual(clean, "Step 1 done.")
        self.assertEqual(hint, "Commit the changes")

    def test_none_and_empty_values_offer_nothing(self):
        self.assertEqual(split_next_step("Ok.\n<next_step>NONE</next_step>"), ("Ok.", ""))
        self.assertEqual(split_next_step("Ok.\n<next_step> </next_step>"), ("Ok.", ""))

    def test_an_unclosed_tag_at_the_end_is_still_hidden(self):
        self.assertEqual(split_next_step("Ok.\n<next_step>Add a test"), ("Ok.", "Add a test"))

    def test_quotes_markup_and_length_are_cleaned(self):
        self.assertEqual(clean_suggestion('"**Run** the app"'), "Run the app")
        self.assertEqual(clean_suggestion("Add `tests/__init__.py` for test_calc"),
                         "Add tests/__init__.py for test_calc")
        self.assertEqual(clean_suggestion('Commit with the message "fix division"'),
                         'Commit with the message "fix division"')
        self.assertEqual(clean_suggestion("„Přidej test“"), "Přidej test")
        long = clean_suggestion("word " * 200)
        self.assertLessEqual(len(long), 301)
        self.assertTrue(long.endswith("…"))


class StreamFilterTests(unittest.TestCase):
    def stream(self, chunks):
        visible = NextStepStreamFilter()
        shown = "".join(visible.feed(chunk) for chunk in chunks)
        return shown + visible.flush()

    def test_a_tag_split_across_chunks_never_shows(self):
        chunks = ["Done.\n", "<next", "_st", "ep>Start ", "the app</next", "_step>"]
        self.assertEqual(self.stream(chunks), "Done.\n")

    def test_text_that_only_looks_like_a_tag_start_is_released(self):
        self.assertEqual(self.stream(["a <n", "ote> b ", "<"]), "a <note> b <")

    def test_text_after_a_tag_is_shown(self):
        self.assertEqual(self.stream(["x<next_step>y</next_step>z"]), "xz")

    def test_an_unclosed_tag_stays_hidden_when_the_stream_ends(self):
        self.assertEqual(self.stream(["Ok.", "<next_step>Add"]), "Ok.")


class DeriveNextStepTests(unittest.TestCase):
    def test_the_summary_next_steps_section_under_any_heading(self):
        content = "✅ Done: file x\n📋 Follow-up:\n- Start the app and check the login\n- Commit"
        self.assertEqual(summary_next_step(content), "Start the app and check the login")
        self.assertEqual(summary_next_step("📋 Next steps: run the migration"), "run the migration")
        self.assertEqual(summary_next_step("No summary here"), "")

    def test_a_failing_check_comes_before_the_plan_and_the_summary(self):
        plan = {"steps": [{"text": "Add the API", "status": "pending"}]}
        checks = [{"what": "unit tests", "ok": False, "note": "2 failed"}]
        self.assertEqual(derive_next_step(plan, checks, "📋 Next steps: deploy"),
                         "Fix the failing check: unit tests")

    def test_an_unfinished_plan_step_comes_before_the_summary(self):
        plan = {"steps": [{"text": "Write the parser", "status": "completed"},
                          {"text": "Add the API", "status": "pending"}],
                "validations": [{"label": "pytest", "status": "passed"}]}
        self.assertEqual(derive_next_step(plan, [], "📋 Next steps: deploy"), "Continue with: Add the API")

    def test_a_failed_last_validation_counts_as_a_failing_check(self):
        plan = {"validations": [{"label": "npm test", "status": "failed"}]}
        self.assertEqual(derive_next_step(plan, [], ""), "Fix the failing check: npm test")

    def test_nothing_open_falls_back_to_the_summary(self):
        self.assertEqual(derive_next_step({}, [], "📋 Next steps:\n1. Release it"), "Release it")
        self.assertEqual(derive_next_step({}, [], "Done."), "")


class PromptTests(unittest.TestCase):
    def test_every_work_mode_asks_for_a_running_next_step(self):
        from harness.prompts import NEXT_STEP_DEVELOPMENT, build_system_prompt
        cfg = load_config(Path(tempfile.gettempdir()) / "marvin-missing.yaml")
        for mode, work_mode in (("chat", "discussion"), ("chat", "research"), ("agent", "writing"),
                                ("agent", "development"), ("computer", "computer")):
            prompt = build_system_prompt(mode, cfg, None, work_mode)
            self.assertIn("<next_step>", prompt, work_mode)
            self.assertEqual(NEXT_STEP_DEVELOPMENT in prompt, work_mode == "development", work_mode)

    def test_turning_suggestions_off_removes_the_request_from_every_prompt(self):
        from harness.prompts import build_system_prompt
        cfg = load_config(Path(tempfile.gettempdir()) / "marvin-missing.yaml")
        cfg.data["next_step_suggestions"] = False
        for mode, work_mode in (("chat", "discussion"), ("agent", "development")):
            self.assertNotIn("<next_step>", build_system_prompt(mode, cfg, None, work_mode), work_mode)


class AgentNextStepTests(unittest.TestCase):
    def setUp(self):
        from harness.agent import Agent, build_registry
        from harness.prompts import system_prompt
        from harness.safety import SafetyPolicy
        from harness.session import Session
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        cfg = load_config(root / "missing.yaml", root=root)
        cfg.data["paths"]["sessions_dir"] = str(root / "sessions")
        cfg.data["agent"]["workspace"] = str(root)
        (root / "notes.txt").write_text("notes", encoding="utf-8")
        self.replies = []
        self.events = []
        test = self

        class Model:
            def stream(self, messages, on_text=None, on_reasoning=None, **kwargs):
                result, chunks = test.replies.pop(0)
                for chunk in test.thoughts.pop(0) if test.thoughts else []:
                    if on_reasoning:
                        on_reasoning(chunk)
                for chunk in chunks:
                    if on_text:
                        on_text(chunk)
                return result

        self.thoughts = []

        self.session = Session(cfg, system_prompt=system_prompt("agent"), workspace=str(root))
        self.agent = Agent(cfg, Model(), self.session, build_registry("agent"), SafetyPolicy("auto"),
                           mode="agent", work_mode="computer",
                           on_event=lambda kind, payload: self.events.append((kind, payload)))

    def tearDown(self):
        self.temp.cleanup()

    def reply(self, text, chunks=None, tool_calls=None):
        from harness.llm import AssistantResult
        self.replies.append((AssistantResult(content=text, tool_calls=tool_calls or []),
                             chunks if chunks is not None else [text]))

    def shown_text(self):
        return "".join(payload for kind, payload in self.events if kind == "text")

    def test_the_final_reply_keeps_no_tag_and_leaves_its_suggestion(self):
        from harness.agent import Status
        self.agent.new_task("Check the notes")
        self.reply("The notes are fine.\n<next_step>Add tests to the notes</next_step>",
                   ["The notes are fine.\n<next", "_step>Add tests to the notes</next_step>"])
        result = self.agent.step()
        self.assertIs(result.status, Status.FINAL)
        final = [m for m in self.session.messages if m.get("role") == "assistant"][-1]
        self.assertEqual(final["content"], "The notes are fine.")
        self.assertNotIn("next_step", self.shown_text())
        self.assertEqual(self.session.meta["next_step"]["text"], "Add tests to the notes")
        self.assertEqual(self.session.meta["next_step"]["source"], "model")
        self.assertIn(("next_step", self.session.meta["next_step"]),
                      [(kind, payload) for kind, payload in self.events if kind == "next_step"])

    def test_a_guess_formed_during_the_work_is_kept_when_the_final_reply_has_none(self):
        self.agent.new_task("Read the notes")
        self.reply("Reading the file.\n<next_step>Summarize the notes</next_step>",
                   tool_calls=[{"id": "c1", "type": "function",
                                "function": {"name": "read_file", "arguments": '{"path": "notes.txt"}'}}])
        self.agent.step()
        self.assertEqual(self.session.meta["next_step"]["text"], "Summarize the notes")
        assistant = [m for m in self.session.messages if m.get("role") == "assistant"][-1]
        self.assertEqual(assistant["content"], "Reading the file.")
        self.reply("The file holds one word.")
        self.agent.step()
        self.assertEqual(self.session.meta["next_step"]["text"], "Summarize the notes")

    def test_the_task_state_fills_in_for_a_final_reply_without_a_guess(self):
        self.agent.new_task("Do two steps")
        self.agent.ctx.task_plan.set_plan("Two steps", ["Write the parser", "Add the API"])
        self.agent.ctx.task_plan.update_step(1, "completed")
        self.reply("The first step is done.")
        self.agent.step()
        self.assertEqual(self.session.meta["next_step"],
                         {**self.session.meta["next_step"], "text": "Continue with: Add the API", "source": "task"})

    def test_a_new_task_clears_the_previous_suggestion(self):
        self.agent.new_task("First")
        self.reply("Done.\n<next_step>Second task</next_step>")
        self.agent.step()
        self.assertTrue(self.session.meta.get("next_step"))
        self.agent.new_task("Second task")
        self.assertIsNone(self.session.meta.get("next_step"))
        self.assertEqual([payload for kind, payload in self.events if kind == "next_step"][-1], None)

    def test_with_suggestions_off_the_tag_is_still_hidden_but_nothing_is_offered(self):
        self.agent.cfg.data["next_step_suggestions"] = False
        self.agent.new_task("Do two steps")
        self.agent.ctx.task_plan.set_plan("Two steps", ["Write the parser", "Add the API"])
        self.reply("Started.\n<next_step>Add the API</next_step>")
        self.agent.step()
        final = [m for m in self.session.messages if m.get("role") == "assistant"][-1]
        self.assertEqual(final["content"], "Started.")
        self.assertIsNone(self.session.meta.get("next_step"))
        self.assertFalse([kind for kind, _ in self.events if kind == "next_step"])

    def test_a_tag_drafted_in_the_reasoning_is_hidden_and_is_not_the_suggestion(self):
        from harness.llm import AssistantResult
        self.agent.new_task("Check the notes")
        thinking = "Plan the reply.\n<next_step>User may ask for more</next_step>\nDone thinking."
        self.thoughts.append(["Plan the reply.\n<next", "_step>User may ask for more</next_step>\nDone thinking."])
        self.replies.append((AssistantResult(content="The notes are fine.", reasoning=thinking),
                             ["The notes are fine."]))
        self.agent.step()
        shown = "".join(payload for kind, payload in self.events if kind == "reasoning")
        self.assertNotIn("next_step", shown)
        self.assertNotIn("User may ask", shown)
        self.assertTrue(shown.startswith("Plan the reply.") and shown.endswith("Done thinking."), shown)
        final = [m for m in self.session.messages if m.get("role") == "assistant"][-1]
        self.assertNotIn("next_step", final.get("reasoning", ""))
        self.assertNotEqual((self.session.meta.get("next_step") or {}).get("text"), "User may ask for more")

    def test_the_task_protocol_asks_for_the_next_step_line_after_its_own_ending(self):
        from harness.prompts import NEXT_STEP_CLOSING

        def protocol_notes():
            return [str(m["content"]) for m in self.session.messages
                    if str(m.get("content", "")).startswith("[TASK PROTOCOL")]

        self.agent.new_task("Change the notes")
        self.assertTrue(protocol_notes()[-1].endswith(NEXT_STEP_CLOSING))
        self.agent.cfg.data["next_step_suggestions"] = False
        self.agent.new_task("Change them again")
        self.assertNotIn(NEXT_STEP_CLOSING, protocol_notes()[-1])

    def test_turning_suggestions_off_clears_the_one_already_shown(self):
        self.agent.new_task("First")
        self.reply("Done.\n<next_step>Second task</next_step>")
        self.agent.step()
        self.agent.cfg.data["next_step_suggestions"] = False
        self.agent._publish_next_step("Another", "model")
        self.assertIsNone(self.session.meta.get("next_step"))


class SettingTests(unittest.TestCase):
    def test_the_setting_is_stored_validated_and_reaches_the_task_configuration(self):
        import copy
        from fastapi.testclient import TestClient
        from harness.application import ApplicationService
        from harness.config import Config
        from harness.web_api import create_app
        with tempfile.TemporaryDirectory() as directory:
            data = copy.deepcopy(load_config().data)
            data["agent"]["workspace"] = None
            cfg = Config(data, Path(directory))
            service = ApplicationService(cfg, llm_factory=lambda cfg: None, manage_model=False)
            with TestClient(create_app(cfg, service=service)) as client:
                session = service.session(client.post("/api/sessions", json={}).json()["session_id"])
                self.assertTrue(service.config_for(session).data["next_step_suggestions"])
                client.patch("/api/settings", json={"next_step_suggestions": False}).raise_for_status()
                self.assertIs(service.preferences["next_step_suggestions"], False)
                self.assertFalse(service.config_for(session).data["next_step_suggestions"])
                self.assertGreaterEqual(
                    client.patch("/api/settings", json={"next_step_suggestions": "no"}).status_code, 400)
                self.assertIs(service.preferences["next_step_suggestions"], False)


if __name__ == "__main__":
    unittest.main()
