"""Startup must open existing conversations and recover damaged history safely."""
import copy
import io
import json
from pathlib import Path
import tempfile
import unittest
import threading
from unittest.mock import patch

from fastapi.testclient import TestClient

from harness.application import ApplicationService
from harness.app_storage import EventStore, export_project, import_project
from harness.config import Config, load_config
from harness.history_index import HistoryIndex
from harness.projects import Projects
from harness.session import Session
from harness.web_api import create_app


class HistoryRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.cfg = Config(copy.deepcopy(load_config().data), self.root)
        self.cfg.agent['workspace'] = None

    def legacy(self, sid='unicode-chat', workspace=None):
        session = Session(self.cfg, session_id=sid, system_prompt='System', workspace=workspace)
        session.add('user', 'Read the source')
        session.add('assistant', 'Before\u0085middle\u2028paragraph\u2029AFTER_SEPARATOR_NEEDLE')
        session.add('assistant', 'The following message must also survive.')
        raw = ('\r\n'.join(json.dumps(m, ensure_ascii=False) for m in session.messages)).encode('utf-8')
        session._jsonl.write_bytes(raw)
        return session, raw

    def test_legacy_unicode_separators_open_unchanged(self):
        original, raw = self.legacy()
        loaded = Session.load(self.cfg, original.id)
        self.assertEqual(loaded.messages, original.messages)
        self.assertEqual(original._jsonl.read_bytes(), raw)
        self.assertFalse((original.dir / 'recovery').exists())

    def test_history_search_rebuild_and_chat_import_keep_unicode(self):
        original, _ = self.legacy()
        index = HistoryIndex(self.cfg.path('paths.sessions_dir'))
        index.remove(original.id)
        self.assertTrue(index.search('AFTER_SEPARATOR_NEEDLE'))
        imported = Session.import_jsonl(self.cfg, original._jsonl, 'System')
        self.assertEqual(imported.messages[2]['content'], original.messages[2]['content'])

    def test_project_archive_import_preserves_unicode_records(self):
        project = Projects(self.cfg).create_new('Unicode project')
        original, _ = self.legacy(workspace=project['path'])
        archive = export_project(self.cfg, project, self.root / 'project.zip')
        restored = import_project(self.cfg, archive)
        entry = next(s for s in Session.list_sessions(self.cfg)
                     if s.get('workspace') == restored['path'])
        loaded = Session.load(self.cfg, entry['id'])
        self.assertEqual(loaded.messages[2]['content'], original.messages[2]['content'])

    def test_startup_opens_selected_unicode_chat(self):
        session, raw = self.legacy()
        service = ApplicationService(self.cfg, manage_model=False)
        self.addCleanup(service.close)
        service.preferences['session_id'] = session.id
        with TestClient(create_app(self.cfg, service=service)) as client:
            response = client.get('/api/state')
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()['session_id'], session.id)
            chat = client.get('/api/sessions/' + session.id)
            self.assertEqual(chat.status_code, 200, chat.text)
            self.assertEqual(chat.json()['messages'][2]['content'], session.messages[2]['content'])
        self.assertEqual(session._jsonl.read_bytes(), raw)

    def test_damaged_record_restores_exact_message_from_durable_event(self):
        session, _ = self.legacy()
        original = copy.deepcopy(session.messages[2])
        store = EventStore(self.cfg.path('paths.runtime_dir') / 'application.sqlite3')
        store.emit(session.id, 'message', {**original, 'files': []})
        records = [json.dumps(m, ensure_ascii=False) for m in session.messages]
        records[2] = '{broken json, "id": ' + json.dumps(original['id']) + '}'
        damaged = '\n'.join(records).encode('utf-8')
        session._jsonl.write_bytes(damaged)
        loaded = Session.load(self.cfg, session.id)
        self.assertEqual(loaded.messages[2], original)
        self.assertEqual(len(loaded.messages), 4)
        backups = list((session.dir / 'recovery').glob('messages-*.jsonl'))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_bytes(), damaged)
        self.assertEqual(Session.load(self.cfg, session.id).messages, loaded.messages)
        self.assertEqual(len(list((session.dir / 'recovery').glob('messages-*.jsonl'))), 1)

    def test_unrecoverable_record_does_not_block_ui_or_remove_later_messages(self):
        session, _ = self.legacy()
        records = [json.dumps(m, ensure_ascii=False) for m in session.messages]
        records[2] = '{"role":"assistant","content":"unfinished'
        damaged = '\n'.join(records).encode('utf-8')
        session._jsonl.write_bytes(damaged)
        service = ApplicationService(self.cfg, manage_model=False)
        self.addCleanup(service.close)
        service.preferences['session_id'] = session.id
        with TestClient(create_app(self.cfg, service=service)) as client:
            response = client.get('/api/state')
            self.assertEqual(response.status_code, 200, response.text)
            chat = client.get('/api/sessions/' + session.id).json()
        self.assertEqual(len(chat['messages']), 4)
        self.assertTrue(chat['messages'][2]['content'].startswith('[HISTORY RECOVERY'))
        self.assertFalse(Session._is_user_boundary(chat['messages'][2]))
        self.assertEqual(chat['messages'][3]['content'], session.messages[3]['content'])
        backup = next((session.dir / 'recovery').glob('messages-*.jsonl'))
        self.assertEqual(backup.read_bytes(), damaged)

    def test_new_jsonl_records_escape_separators_without_changing_content(self):
        session = Session(self.cfg)
        content = 'one\u0085two\u2028three\u2029four'
        session.add('user', content)
        raw = session._jsonl.read_text(encoding='utf-8')
        self.assertNotIn('\u2028', raw)
        self.assertNotIn('\u0085', raw)
        self.assertNotIn('\u2029', raw)
        self.assertEqual(json.loads(raw)['content'], content)

    def test_reader_waits_for_active_append_instead_of_repairing_partial_write(self):
        from harness.jsonl import history_lock
        session, complete = self.legacy()
        done = threading.Event()
        result = []
        def reader():
            try:
                result.append(Session.load(self.cfg, session.id))
            finally:
                done.set()
        with history_lock(session._jsonl):
            session._jsonl.write_bytes(complete[:-10])
            thread = threading.Thread(target=reader)
            thread.start()
            self.assertFalse(done.wait(.1))
            session._jsonl.write_bytes(complete)
        thread.join(3)
        self.assertTrue(done.is_set())
        self.assertEqual(result[0].messages, session.messages)
        self.assertFalse((session.dir / 'recovery').exists())
        self.assertEqual(session._jsonl.read_bytes(), complete)

    def test_smoke_checks_real_workspace_and_selected_chat(self):
        from launcher.launcher_app import _check_workspace_api
        opened = []
        def open_url(url, **kwargs):
            opened.append(url)
            data = {'session_id': 'selected'} if url.endswith('/api/state') else (
                {'id': 'selected', 'messages': []} if url.endswith('/selected') else {})
            return io.BytesIO(json.dumps(data).encode())
        with patch('urllib.request.urlopen', side_effect=open_url):
            _check_workspace_api('http://localhost:7860')
        self.assertTrue(any(url.endswith('/api/sessions/selected') for url in opened))
        with patch('urllib.request.urlopen', side_effect=ValueError('broken response')):
            with self.assertRaises(ValueError):
                _check_workspace_api('http://localhost:7860')


if __name__ == '__main__':
    unittest.main()
