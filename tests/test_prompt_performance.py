"""Request-prefix reuse, native prefill progress and bounded source reads."""
import copy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import httpx
from openai import OpenAI

from harness.agent import Agent
from harness.config import Config, load_config
from harness.llm import LLMClient
from harness.research import ResearchLedger
from harness.safety import SafetyPolicy
from harness.session import Session
from harness.tools.base import AgentContext, ToolRegistry
from harness.tools.web import WebFetchTool


class PromptPerformanceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.cfg = Config(copy.deepcopy(load_config().data), self.root)
        self.cfg.data['paths']['sessions_dir'] = str(self.root / 'sessions')
        self.cfg.agent['workspace'] = None
        self.session = Session(self.cfg, system_prompt='Stable system instructions')
        self.session.add('user', 'Inspect the project')
        self.agent = Agent(self.cfg, None, self.session, ToolRegistry(), SafetyPolicy('auto'))

    def test_followup_keeps_exact_prefix_including_context_and_generated_reasoning(self):
        with patch.object(self.agent, '_dynamic_context_sections', return_value={'plan': 'Plan: inspect'}):
            count = len(self.session.messages)
            preview = self.agent._api_messages()
            self.assertEqual(len(self.session.messages), count, 'UI previews must be read-only')
            first = self.agent._request_messages()
            self.assertEqual(first, preview)
        self.session.add('assistant', 'Read the evidence.', reasoning='Reasoning ' * 500,
                         tool_calls=[{'id': 'call1', 'type': 'function', 'function': {
                             'name': 'read_file', 'arguments': '{"path":"evidence.txt"}'}}])
        self.session.add('tool', 'Evidence found.', tool_call_id='call1', name='read_file')
        with patch.object(self.agent, '_dynamic_context_sections', return_value={'plan': 'Plan: verify'}):
            second = self.agent._request_messages()
        self.assertEqual(second[:len(first)], first)
        self.assertEqual(second[len(first)]['reasoning_content'], 'Reasoning ' * 500)
        self.assertEqual(second[-2]['tool_call_id'], 'call1')
        self.assertIn('Plan: verify', second[-1]['content'])
        loaded = Session.load(self.cfg, self.session.id)
        self.assertEqual(loaded.to_api_messages(include_pins=False), second)
        self.assertEqual(sum(Session._is_user_boundary(m) for m in loaded.messages), 1)

    def test_unchanged_context_is_not_repeated_and_removed_context_is_cleared(self):
        with patch.object(self.agent, '_dynamic_context_sections', return_value={'pins': 'Pinned requirement'}):
            self.agent._request_messages()
            self.session.add('assistant', 'Ready.')
            self.agent._request_messages()
            snapshots = [m for m in self.session.messages if str(m.get('content')).startswith('[DYNAMIC TASK CONTEXT')]
            self.assertEqual(len(snapshots), 1)
        with patch.object(self.agent, '_dynamic_context_sections', return_value={}):
            messages = self.agent._request_messages()
        self.assertEqual(json.loads(messages[-1]['content'].split('\n\n', 1)[1]), {'pins': ''})

    def test_changing_plan_does_not_resend_unchanged_large_pinned_files(self):
        pinned = 'COMPLETE_PINNED_SPECIFICATION ' * 1000
        with patch.object(self.agent, '_dynamic_context_sections', return_value={'pins': pinned, 'plan': 'Inspect'}):
            first = self.agent._request_messages()
        self.session.add('assistant', 'Inspected.')
        with patch.object(self.agent, '_dynamic_context_sections', return_value={'pins': pinned, 'plan': 'Verify'}):
            second = self.agent._request_messages()
        self.assertEqual(second[:len(first)], first)
        self.assertNotIn('COMPLETE_PINNED_SPECIFICATION', second[-1]['content'])
        self.assertEqual(json.loads(second[-1]['content'].split('\n\n', 1)[1]), {'plan': 'Verify'})

    def test_saving_a_memory_fact_does_not_rewrite_the_system_prompt(self):
        """Memory in the system prompt cost a full reprocess of the conversation.

        Measured before this: a single saved line invalidated 140k processed
        tokens and the next request spent 98 s re-reading the whole session."""
        from harness.memory import MemoryStore
        self.agent.refresh_system_prompt()   # As a task start does, before the first request.
        first = self.agent._request_messages()
        system = first[0]["content"]
        self.assertNotIn("PERSISTENT MEMORY", system)
        MemoryStore(self.cfg, None, self.agent.work_mode).append("Prefer short answers", "global")
        self.agent.refresh_system_prompt()
        self.session.add("assistant", "Saved.")
        second = self.agent._request_messages()
        self.assertEqual(second[0]["content"], system, "the system prompt must stay byte-identical")
        self.assertEqual(second[: len(first)], first, "the processed prefix must survive")
        self.assertIn("Prefer short answers", second[-1]["content"])

    def test_memory_and_skills_are_delivered_as_dynamic_sections(self):
        from harness.memory import MemoryStore
        MemoryStore(self.cfg, None, self.agent.work_mode).append("Remembered fact", "global")
        sections = self.agent._dynamic_context_sections()
        self.assertIn("Remembered fact", sections["memory"])
        self.assertIn("PERSISTENT MEMORY", sections["memory"])

    def test_a_new_screenshot_never_rewrites_already_sent_history(self):
        """The API view sent the newest 8 images and recomputed that set every
        request, so the ninth screenshot removed the first one from a message the
        server had already processed - 11 breaks in one measured session."""
        sent = None
        for step in range(12):
            shot = self.root / ("shot-%02d.png" % step)
            shot.write_bytes(b"\x89PNG\r\n\x1a\n" + bytes([step]) * 64)
            self.session.add("user", "[The following image(s) were captured by tools:]",
                             images=[shot])
            with patch.object(self.agent, "_dynamic_context_sections", return_value={}):
                current = self.agent._request_messages()
            if sent is not None:
                self.assertEqual(current[: len(sent)], sent,
                                 "screenshot %d rewrote the prefix" % step)
            sent = current
            self.session.add("assistant", "Observed step %d." % step)
        images = sum(1 for m in sent for part in (m["content"] if isinstance(m["content"], list) else [])
                     if part.get("type") == "image_url")
        self.assertEqual(images, 12, "every screenshot stays in the prompt until pruned")

    def test_pruning_is_the_only_thing_that_drops_images_and_it_persists(self):
        shots = []
        for step in range(6):
            shot = self.root / ("frame-%02d.png" % step)
            shot.write_bytes(b"\x89PNG\r\n\x1a\n" + bytes([step]) * 64)
            shots.append(shot)
            self.session.add("user", "Frame %d" % step, images=[shot])
        before = self.session.estimate_context_tokens(include_pins=False)
        self.assertEqual(self.session.prune_images(keep=2), 4)
        after = self.session.estimate_context_tokens(include_pins=False)
        self.assertLess(after, before)
        self.assertEqual(self.session.prune_images(keep=2), 0, "pruning twice must be a no-op")
        rendered = self.session.to_api_messages(include_pins=False)
        self.assertFalse([m for m in rendered if Session.HIDDEN_IMAGES_KEY in m],
                         "the pruning flag is internal and must not reach the model")
        kept = [m for m in rendered if isinstance(m.get("content"), list)]
        self.assertEqual(len(kept), 2)
        self.assertIn("Frame 5", kept[-1]["content"][0]["text"])
        reloaded = Session.load(self.cfg, self.session.id)
        self.assertEqual(reloaded.to_api_messages(include_pins=False), rendered,
                         "the decision has to survive a reload, or the prefix changes again")
        self.assertEqual(reloaded.context_breakdown()["images"], 6)
        self.assertEqual(reloaded.context_breakdown()["images_sent"], 2)

    def test_context_pressure_gives_up_screenshots_before_summarizing(self):
        for step in range(8):
            shot = self.root / ("big-%02d.png" % step)
            shot.write_bytes(b"\x89PNG\r\n\x1a\n" + bytes([step]) * 64)
            self.session.add("user", "Step %d" % step, images=[shot])
        notes = []
        self.agent.emit = lambda kind, text, **rest: notes.append(str(text))
        with patch.object(self.agent, "_ctx_limit", return_value=12000), \
                patch("harness.context.summarize_messages") as summarize:
            self.agent._maybe_compress()
        summarize.assert_not_called()
        # The notice carries the picture marker in every language.
        self.assertTrue(any(note.startswith("🖼") for note in notes), notes)
        self.assertEqual(sum(1 for m in self.session.to_api_messages(include_pins=False)
                             if isinstance(m.get("content"), list)), 4)

    def test_one_stray_screenshot_does_not_buy_a_rewrite(self):
        """Measured on the owner's session: after a first prune of 21 pictures,
        every later screenshot made exactly one prunable again, and each of those
        rewrote the prompt from that picture onwards - about 45k tokens and fifty
        seconds - to free 1400. Those three rewrites bought nothing."""
        for step in range(5):
            shot = self.root / ("late-%02d.png" % step)
            shot.write_bytes(b"\x89PNG\r\n\x1a\n" + bytes([step]) * 64)
            self.session.add("user", "Step %d" % step, images=[shot])
        prunable, saving = self.session.prunable_images(keep=4)
        self.assertEqual(prunable, 1, "only the oldest picture is droppable here")
        notes = []
        self.agent.emit = lambda kind, text, **rest: notes.append(str(text))
        with patch.object(self.agent, "_ctx_limit", return_value=200000), \
                patch.object(self.agent, "estimate_context_tokens", return_value=180000), \
                patch("harness.context.summarize_messages", return_value="summary"):
            self.agent._maybe_compress()
        self.assertFalse([note for note in notes if note.startswith("🖼")],
                         "a single picture is not worth rewriting the prompt for")
        self.assertEqual(sum(1 for m in self.session.to_api_messages(include_pins=False)
                             if isinstance(m.get("content"), list)), 5,
                         "nothing should have been given up")

    def test_a_worthwhile_prune_still_happens(self):
        for step in range(25):
            shot = self.root / ("many-%02d.png" % step)
            shot.write_bytes(b"\x89PNG\r\n\x1a\n" + bytes([step]) * 64)
            self.session.add("user", "Step %d" % step, images=[shot])
        prunable, saving = self.session.prunable_images(keep=4)
        self.assertEqual(prunable, 21)
        notes = []
        self.agent.emit = lambda kind, text, **rest: notes.append(str(text))
        # A real estimate over the threshold rather than a patched one: twenty
        # five pictures are worth about 35k tokens against this limit.
        with patch.object(self.agent, "_ctx_limit", return_value=30000), \
                patch("harness.context.summarize_messages", return_value="summary"):
            self.agent._maybe_compress()
        self.assertTrue([note for note in notes if note.startswith("🖼")], notes)
        self.assertEqual(sum(1 for m in self.session.to_api_messages(include_pins=False)
                             if isinstance(m.get("content"), list)), 4)

    def test_asking_the_cost_does_not_pay_it(self):
        for step in range(9):
            shot = self.root / ("ask-%02d.png" % step)
            shot.write_bytes(b"\x89PNG\r\n\x1a\n" + bytes([step]) * 64)
            self.session.add("user", "Step %d" % step, images=[shot])
        before = self.session.to_api_messages(include_pins=False)
        self.session.prunable_images(keep=4)
        self.assertEqual(self.session.to_api_messages(include_pins=False), before)

    # -- the context figure has to be the same number everywhere ----------------
    #
    # Two displays disagreed - 56k beside the composer against the server's own
    # 70k while it read the prompt - because one was a character estimate and the
    # other was measured. These pin the estimate to what was measured and keep
    # the two paths that compute it from drifting apart again.

    def test_the_estimate_matches_what_the_server_actually_counted(self):
        """Measured: an image-free conversation of 287,114 characters was 89,670
        prompt tokens, and seven screenshots accounted for a further 18,087."""
        self.assertAlmostEqual(Session.tokens_for(287114), 89670, delta=89670 * 0.02)
        self.assertAlmostEqual(Session.tokens_for(0, 7), 18087, delta=18087 * 0.02)

    def test_both_ways_of_counting_the_context_agree(self):
        """The estimate walks the session; the request walks rendered messages.
        When those two drifted apart, the UI showed two different numbers."""
        shot = self.root / "agree.png"
        shot.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x01" * 64)
        self.session.add("user", "Look at this", images=[shot])
        self.session.add("assistant", "Noted.", reasoning="thinking at some length")
        with patch.object(self.agent, "_dynamic_context_sections", return_value={}):
            messages = self.agent._api_messages()
        chars, images = self.agent._sent_size(messages)
        self.assertEqual(images, 1, "the rendered request must still carry the picture")
        from_request = Session.tokens_for(chars - self.agent._schema_chars(), images,
                                          self.session.token_scale())
        self.assertAlmostEqual(self.session.estimate_context_tokens(include_pins=False),
                               from_request, delta=2)

    def test_calibration_covers_what_the_server_also_counts(self):
        """Tool definitions travel with every request, so leaving them out would
        teach the estimate that the prompt is bigger than it is."""
        registry = ToolRegistry()
        with patch.object(registry, "schemas", return_value=[{"name": "x", "parameters": {}}]):
            agent = Agent(self.cfg, None, self.session, registry, SafetyPolicy("auto"))
            with patch.object(agent, "_dynamic_context_sections", return_value={}):
                messages = agent._api_messages()
            self.assertGreater(agent._schema_chars(), 0)
            chars, _ = agent._sent_size(messages)
        self.assertGreaterEqual(chars, agent._schema_chars())

    def test_the_server_count_corrects_the_estimate(self):
        with patch.object(self.agent, "_dynamic_context_sections", return_value={}):
            self.agent._request_messages()
        raw = self.agent._last_sent
        self.assertGreater(raw, 0)
        self.session.calibrate_tokens(int(raw * 1.5), raw)
        self.assertGreater(self.session.token_scale(), 1.0,
                           "a longer prompt than estimated must raise the estimate")
        self.assertLess(self.session.token_scale(), 1.5,
                        "one request must not swing it the whole way")
        self.assertEqual(self.session.meta[Session.SCALE_KEY], self.session.token_scale())

    def test_calibration_repeated_converges_on_the_measurement(self):
        raw = 10000
        for _ in range(20):
            self.session.calibrate_tokens(12000, raw)
        self.assertAlmostEqual(self.session.token_scale(), 1.2, delta=0.02)
        self.assertAlmostEqual(Session.tokens_for(32000, 0, self.session.token_scale()),
                               12000, delta=120)

    def test_an_implausible_measurement_teaches_nothing(self):
        """A truncated, retried or failed request must not corrupt the estimate."""
        for prompt_tokens in (0, -5, 100, 10 ** 7):
            self.session.calibrate_tokens(prompt_tokens, 10000)
            self.assertEqual(self.session.token_scale(), 1.0)
        self.session.meta[Session.SCALE_KEY] = 9.0
        self.assertEqual(self.session.token_scale(), 1.0, "a stored absurdity is ignored")

    def test_a_learned_correction_reaches_every_reported_figure(self):
        self.session.calibrate_tokens(15000, 10000)
        scale = self.session.token_scale()
        self.assertGreater(scale, 1.0)
        breakdown = self.agent.context_usage_breakdown()
        plain = {"messages": self.session.estimate_context_tokens(include_pins=False)}
        self.assertEqual(breakdown["messages"], plain["messages"])
        self.assertGreater(sum(breakdown.values()), 0)
        shot = self.root / "learned.png"
        shot.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x02" * 64)
        for step in range(9):
            self.session.add("user", "Step %d" % step, images=[shot])
        _, saving = self.session.prunable_images(keep=4)
        self.assertEqual(saving, Session.tokens_for(0, 5, scale),
                         "what pruning frees must be counted the same way")

    def test_every_request_is_recorded_so_a_lost_cache_can_be_explained(self):
        """The conversation on disk shows the final state, so a message rewritten
        in place looks as though it always was that way. The trace does not."""
        from harness import request_trace
        with patch.object(self.agent, "_dynamic_context_sections", return_value={}):
            self.agent._request_messages()
            self.session.add("assistant", "Read the evidence.")
            self.agent._request_messages()
        traces = self.session.dir / "requests"
        self.assertEqual(len(list(traces.glob("request-*.json"))), 2)
        report = request_trace.compare(traces)
        self.assertEqual(len(report), 1)
        self.assertTrue(report[0]["appended_only"], "appending must read as appending")

    def test_a_rewritten_message_is_named_rather_than_guessed_at(self):
        from harness import request_trace
        first = [{"role": "system", "content": "rules"},
                 {"role": "user", "content": "a question"},
                 {"role": "assistant", "content": "an answer"}]
        second = [{"role": "system", "content": "rules"},
                  {"role": "user", "content": "a question"},
                  {"role": "assistant", "content": "a different answer"},
                  {"role": "user", "content": "next"}]
        traces = self.root / "traces"
        request_trace.record(traces, first, step=1)
        request_trace.record(traces, second, step=2)
        report = request_trace.compare(traces)
        self.assertEqual(len(report), 1)
        self.assertFalse(report[0]["appended_only"])
        self.assertEqual(report[0]["agreed_for"], 2)
        self.assertEqual(report[0]["first_difference"]["before"]["role"], "assistant")

    def test_two_requests_in_the_same_clock_tick_are_both_kept(self):
        """time_ns() reads a clock that steps about 15 ms on Windows, so two tool
        steps in quick succession really do get the same value. Losing one would
        hide a rewrite exactly where requests come closest together."""
        from harness import request_trace
        traces = self.root / "ticks"
        with patch.object(request_trace.time, "time_ns", return_value=1789800000000000000):
            for index in range(5):
                request_trace.record(traces, [{"role": "user", "content": "step %d" % index}],
                                     step=index)
        written = sorted(traces.glob("request-*.json"))
        self.assertEqual(len(written), 5, "no request may overwrite another")
        steps = [json.loads(path.read_text(encoding="utf-8"))["step"] for path in written]
        self.assertEqual(steps, [0, 1, 2, 3, 4], "and they must stay in the order written")

    def test_the_trace_keeps_only_the_recent_requests(self):
        from harness import request_trace
        traces = self.root / "bounded"
        for index in range(request_trace.KEEP + 12):
            request_trace.record(traces, [{"role": "user", "content": "step %d" % index}])
        self.assertLessEqual(len(list(traces.glob("request-*.json"))), request_trace.KEEP)

    def test_the_trace_records_shape_and_never_the_words(self):
        from harness import request_trace
        secret = "the lighthouse keeper refuses to leave"
        entries = request_trace.fingerprint([{"role": "user", "content": secret}])
        self.assertEqual(entries[0]["chars"], len(secret))
        self.assertNotIn(secret, json.dumps(entries))

    def test_native_progress_survives_openai_sdk_stream_without_visible_output(self):
        progress = {'total': 12000, 'cache': 10000, 'processed': 11000, 'time_ms': 9500}
        payloads = [
            {'choices': [], 'prompt_progress': progress},
            {'choices': [{'index': 0, 'delta': {'content': 'Done'}, 'finish_reason': None}]},
            {'choices': [], 'usage': {'prompt_tokens': 12000, 'completion_tokens': 1, 'total_tokens': 12001},
             'timings': {'prompt_n': 2000, 'prompt_ms': 18000, 'predicted_per_second': 27}},
        ]
        bodies = []
        def handle(request):
            bodies.append(json.loads(request.content))
            events = [dict(id='test', object='chat.completion.chunk', created=1, model='local', **p) for p in payloads]
            content = ''.join('data: ' + json.dumps(e) + '\n\n' for e in events) + 'data: [DONE]\n\n'
            return httpx.Response(200, headers={'content-type': 'text/event-stream'}, text=content)
        llm = LLMClient(self.cfg)
        llm.client.close()
        llm.client = OpenAI(api_key='local', base_url='http://local/v1',
                            http_client=httpx.Client(transport=httpx.MockTransport(handle)))
        self.addCleanup(llm.client.close)
        observed = []
        result = llm.stream([{'role': 'user', 'content': 'Test'}], on_prompt_progress=observed.append)
        self.assertTrue(bodies[0]['return_progress'])
        self.assertEqual(observed, [progress])
        self.assertEqual(result.content, 'Done')
        self.assertEqual(result.usage['timings']['prompt_n'], 2000)
        from harness.research import _ask
        llm.on_prompt_progress = observed.append
        started = []
        llm.on_generation_started = lambda: started.append(True)
        self.assertEqual(_ask(llm, 'Plan a test'), 'Done')
        self.assertEqual(observed, [progress, progress])
        self.assertEqual(started, [True])

    def test_focused_source_read_keeps_full_evidence_and_avoids_redownload(self):
        text = ('unrelated occupation\n' * 1000 + '\nMultimedia Specialist 261211\n'
                + 'other occupation\n' * 1000 + '\nAnimator 232413\n')
        response = SimpleNamespace(url='https://example.test/list', headers={'content-type': 'text/plain'},
                                   text=text, raise_for_status=lambda: None)
        ctx = AgentContext(self.cfg, self.session)
        ctx.research = ResearchLedger(self.session)
        tool = WebFetchTool()
        with patch('requests.get', return_value=response) as download:
            excerpt = tool.run(ctx, response.url, query='multimedia specialist|animator', max_chars=1500)
            self.assertIn('Multimedia Specialist 261211', excerpt)
            self.assertIn('Animator 232413', excerpt)
            self.assertLess(len(excerpt), 2000)
            self.assertGreater(len(ctx.research.current()['sources'][0]['content']), 30000)
            again = tool.run(ctx, response.url, query='Animator')
            self.assertIn('232413', again)
            self.assertEqual(download.call_count, 1)
            missing = tool.run(ctx, response.url, query='[no regex match]')
            self.assertIn('No literal match', missing)
            tool.run(ctx, response.url, refresh=True, max_chars=20)
            self.assertEqual(download.call_count, 2)

    def test_source_pagination_can_retrieve_text_beyond_initial_excerpt(self):
        text = 'START ' + 'middle ' * 3000 + ' END_REQUIREMENT'
        initial = WebFetchTool._excerpt(text, 'https://example.test/a', 100, 0, '')
        later = WebFetchTool._excerpt(text, 'https://example.test/a', 100, len(text) - 80, '')
        self.assertNotIn('END_REQUIREMENT', initial)
        self.assertIn('start=100', initial)
        self.assertIn('END_REQUIREMENT', later)


if __name__ == '__main__':
    unittest.main()
