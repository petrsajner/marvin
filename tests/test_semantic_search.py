"""Semantic search: chunking, vector stores, tool behavior and settings wiring.

Embeddings are mocked with deterministic bag-of-words vectors so no model,
sidecar or GPU is needed."""
import copy
import json
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient

from harness import semantic_index
from harness.application import ApplicationService
from harness.config import Config, load_config
from harness.semantic_index import SemanticFileIndex, SemanticHistoryIndex, chunk_text
from harness.tools.semantic import SemanticSearchTool
from harness.web_api import create_app

DIM = 1024


def mock_vectors(cfg_or_texts, texts=None):
    """Deterministic normalized bag-of-words vectors; accepts (texts) or (cfg, texts)."""
    import numpy as np
    items = texts if texts is not None else cfg_or_texts
    out = []
    for text in items:
        vec = np.zeros(DIM, dtype="float32")
        for word in text.lower().split():
            vec[hash(word) % DIM] += 1.0
        norm = float(np.linalg.norm(vec))
        out.append(vec / norm if norm else vec)
    return np.stack(out) if out else np.zeros((0, DIM), dtype="float32")


class SemanticIndexTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        data = copy.deepcopy(load_config().data)
        data["agent"].update(workspace=None, autonomy="auto")
        self.cfg = Config(data, self.root)
        self.workspace = self.root / "project"
        (self.workspace / "sub").mkdir(parents=True)
        (self.workspace / "notes.md").write_text(
            "The cat sat on the mat.\n\nA second paragraph about animals.", encoding="utf-8")
        (self.workspace / "sub" / "server.py").write_text(
            "def retry_requests():\n    '''Retry failed HTTP requests with backoff.'''\n    pass",
            encoding="utf-8")
        patcher = patch("harness.embedding_server.embed_texts", side_effect=mock_vectors)
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self):
        self.temp.cleanup()

    def test_chunking_packs_paragraphs_and_splits_oversized_blocks(self):
        chunks = chunk_text("alpha\n\nbeta\n\n" + "x" * 2000, max_chars=500, overlap=50)
        self.assertEqual(chunks[0], "alpha\n\nbeta")
        self.assertTrue(all(len(c) <= 500 for c in chunks))
        self.assertGreater(len([c for c in chunks if c.startswith("x")]), 1)
        self.assertEqual(chunk_text("   \n\n  "), [])

    def test_file_index_incremental_update_and_search(self):
        from contextlib import closing

        from harness.file_index import invalidate_project_files
        index = SemanticFileIndex(self.cfg, self.workspace)
        self.assertEqual(index.update(), 2)
        self.assertEqual(index.progress()["pending"], 0)
        query = mock_vectors(["cat mat animal"])[0]
        hits = index.search(query, limit=5)
        self.assertTrue(hits and hits[0]["path"].endswith("notes.md"))
        # A touched file becomes pending again; unchanged files do not.
        time.sleep(0.01)
        (self.workspace / "sub" / "server.py").write_text(
            "def retry_requests():\n    '''Retry with backoff v2.'''\n", encoding="utf-8")
        invalidate_project_files(self.workspace)
        pending = index.pending_files()
        self.assertEqual([p.name for p in pending], ["server.py"])
        self.assertEqual(index.update(), 1)
        # Deleted files are pruned from the store.
        (self.workspace / "notes.md").unlink()
        invalidate_project_files(self.workspace)
        self.assertEqual(index.update(), 0)
        with closing(index._connect()) as db:
            paths = {row[0] for row in db.execute("SELECT path FROM files")}
        self.assertNotIn("notes.md", paths)

    def test_history_index_skips_internal_messages_and_dedupes(self):
        sessions = self.cfg.path("paths.sessions_dir")
        sid = "20260918-100000-test01"
        (sessions / sid).mkdir(parents=True)
        rows = [
            {"role": "system", "content": "SYS"},
            {"role": "user", "content": "We decided to store tokens in RAM"},
            {"role": "assistant", "content": "The draft model stays in system RAM."},
            {"role": "user", "content": "[TASK PROTOCOL] internal"},
        ]
        (sessions / sid / "messages.jsonl").write_text(
            "\n".join(json.dumps(r) for r in rows), encoding="utf-8")
        index = SemanticHistoryIndex(self.cfg)
        self.assertEqual(index.update(), 1)
        self.assertEqual(index.pending_sessions(), 0)
        query = mock_vectors(["draft model RAM tokens decided"])[0]
        hits = index.search(query, limit=5)
        self.assertTrue(hits)
        self.assertEqual(hits[0]["session_id"], sid)
        from contextlib import closing
        with closing(index._connect()) as db:
            stored = {row[0] for row in db.execute("SELECT role FROM chunks")}
        self.assertEqual(stored, {"user", "assistant"})

    def test_tool_reports_disabled_and_searches_when_enabled(self):
        ctx = SimpleNamespace(cfg=self.cfg, workspace=self.workspace)
        self.assertIn("disabled", SemanticSearchTool().run(ctx, "retry logic"))
        self.cfg.data["_semantic_search"] = True
        result = SemanticSearchTool().run(ctx, "cat sat animals")
        self.assertIn("[semantic", result)
        self.assertIn("notes.md", result)
        history = SemanticSearchTool().run(ctx, "draft model in RAM", scope="history")
        self.assertIn("draft model", history.lower())


class SemanticSettingsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        data = copy.deepcopy(load_config().data)
        data["hardware"]["vram_gb"] = 32
        data["agent"].update(workspace=None, autonomy="auto")
        self.cfg = Config(data, self.root)
        self.app = ApplicationService(self.cfg, llm_factory=lambda cfg: None, manage_model=False)
        self.client = TestClient(create_app(self.cfg, service=self.app))

    def tearDown(self):
        self.app.close()
        self.app.models.wait(3)
        self.temp.cleanup()

    def test_semantic_toggle_validates_and_flows_to_runtime_and_state(self):
        # The background model download is out of scope here; keep the test offline.
        with patch("harness.web_api._prepare_semantic_search") as prepare:
            self.assertFalse(self.cfg.data["_semantic_search"])
            state = self.client.get("/api/state").json()
            self.assertFalse(state["semantic_search"]["enabled"])
            response = self.client.patch("/api/settings", json={"semantic_search": True})
            response.raise_for_status()
            prepare.assert_called_once()
            self.assertTrue(self.app.preferences["semantic_search"])
            self.assertTrue(self.cfg.data["_semantic_search"])
            state = self.client.get("/api/state").json()
            self.assertTrue(state["semantic_search"]["enabled"])
            self.assertEqual(
                self.client.patch("/api/settings", json={"semantic_search": "yes"}).status_code, 400)


if __name__ == "__main__":
    unittest.main()
