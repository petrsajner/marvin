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
