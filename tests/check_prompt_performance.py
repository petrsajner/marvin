"""Measure request-prefix reuse on one isolated, owned local model server."""
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import psutil
import requests

from harness.config import Config, load_config
from harness.llm import LLMClient
from harness import servermgmt
from harness.tools.web import WebFetchTool


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', default='flash_next_q3')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--source-file', type=Path)
    parser.add_argument('--source-only', action='store_true')
    args = parser.parse_args()
    if any((p.info['name'] or '').lower() == 'llama-server.exe'
           for p in psutil.process_iter(['name'])):
        raise RuntimeError('Another model server is running; finish or stop it before this isolated audit.')
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    if (output / 'results.json').exists():
        raise RuntimeError('Use a new audit output directory.')
    data = copy.deepcopy(load_config().data)
    data['default_model'] = args.model
    data['server']['port'] = 8081
    data['paths'].update(runtime_dir=str(output / 'server'), llama_dir=str(ROOT / 'runtime/llama'),
                         models_dir=str(ROOT / 'runtime/models'), sessions_dir=str(output / 'sessions'))
    data['reasoning_effort'] = 'low'
    cfg = Config(data, ROOT)
    report = {'model': args.model, 'cases': [], 'scope': 'Synthetic two-turn A/B with identical sampling; not a whole-task speed claim.'}

    def save():
        (output / 'results.json').write_text(json.dumps(report, indent=2), encoding='utf-8')

    llm = None
    try:
        if servermgmt.start(cfg, args.model) != 0:
            raise RuntimeError('Audit model did not start')
        llm = LLMClient(cfg)
        report['context'] = cfg.context_size()
        plan = output / 'server/execution-plans' / f'{args.model}.json'
        if plan.exists():
            report['runtime_plan'] = json.loads(plan.read_text(encoding='utf-8'))

        def invoke(messages, max_tokens, thinking=None):
            started = time.perf_counter()
            first = []
            progress = []
            def visible(_):
                if not first:
                    first.append(time.perf_counter() - started)
            result = llm.stream(messages, sampling={'temperature': 0, 'top_k': 1, 'max_tokens': max_tokens},
                                on_text=visible, on_reasoning=visible, on_prompt_progress=progress.append,
                                thinking=thinking)
            assert not result.stopped and (result.content or result.reasoning)
            return result, {'first_output_s': round(first[0], 3) if first else None,
                            'elapsed_s': round(time.perf_counter() - started, 3), 'usage': result.usage,
                            'progress_events': len(progress), 'last_progress': progress[-1] if progress else None}

        # ABBA order reduces warm-up and order effects. Each new case changes the
        # leading system string so its first request cannot reuse the prior case.
        for index, fixed in enumerate(() if args.source_only else (False, True, True, False)):
            base = [{'role': 'system', 'content': f'Audit case {index}. Follow the requested format.'},
                    {'role': 'user', 'content': 'Print integers from 1 through 400 separated by commas. Do not skip integers. Think briefly.'}]
            dynamic = {'role': 'user', 'content': '[DYNAMIC TASK CONTEXT - current snapshot]\nTask plan: produce the numbered list.'}
            first, initial = invoke(base + [dynamic], 512)
            assistant = {'role': 'assistant', 'content': first.content, 'reasoning_content': first.reasoning}
            follow = {'role': 'user', 'content': 'The list is sufficient. Reply with the single word DONE.'}
            next_dynamic = {'role': 'user', 'content': '[DYNAMIC TASK CONTEXT - current snapshot]\nTask plan: acknowledge completion.'}
            history = base + ([dynamic] if fixed else []) + [assistant, follow, next_dynamic]
            _, followup = invoke(history, 32)
            case = {'fixed_prefix': fixed, 'initial': initial, 'followup': followup}
            report['cases'].append(case)
            print(json.dumps(case), flush=True)
            save()

        if args.source_file:
            text = args.source_file.read_text(encoding='utf-8')
            query = 'Multimedia Specialist|Animator|Film and Video Editor|Graphic Designer'
            focused = WebFetchTool._excerpt(text, 'https://example.test/saved-source', 2200, 0, query)
            token_counts = {}
            source_cases = {}
            report['source_read'] = {'tokens': token_counts, 'cases': source_cases,
                                     'query': query, 'full_text_remains_available': True}
            for label, content in [('full', text), ('focused', focused)]:
                response = requests.post(cfg.base_url + '/tokenize', json={'content': content}, timeout=10)
                response.raise_for_status()
                token_counts[label] = len(response.json()['tokens'])
                answer, measurement = invoke([
                    {'role': 'system', 'content': 'Source audit ' + label + '. Read the reference accurately.'},
                    {'role': 'user', 'content': content + '\n\nWhat is the numeric ANZSCO code for Multimedia Specialist? Answer just the code.'}], 64, thinking=False)
                measurement['answer'] = answer.content
                source_cases[label] = measurement
                save()
            assert all('261211' in c['answer'] for c in source_cases.values()), source_cases
        report['complete'] = True
        save()
    finally:
        if llm is not None:
            llm.client.close()
        servermgmt.stop(cfg, quiet=True)


if __name__ == '__main__':
    main()
