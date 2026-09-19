"""One search over everything, instead of four places to guess between.

Chats had the box above the conversation list, project files had a model tool,
memory was read by eye in settings, decisions had their own panel. Remembering a
sentence but not where it was written meant guessing which one to open.
"""
import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from harness import finder
from harness.application import ApplicationService
from harness.config import Config, load_config
from harness.decisions import DecisionStore
from harness.memory import MemoryStore
from harness.projects import Projects
from harness.web_api import create_app

WORD = "lighthouse"


class FinderTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        data = copy.deepcopy(load_config().data)
        data["hardware"]["vram_gb"] = 32
        self.cfg = Config(data, self.root)
        self.service = ApplicationService(self.cfg, llm_factory=lambda c: None,
                                          manage_model=False)
        self.addCleanup(self.service.models.wait, 3)
        self.addCleanup(self.service.close)
        self.client = TestClient(create_app(self.cfg, service=self.service))
        self.project = Projects(self.cfg).create_new("Scenar")
        self.workspace = Path(self.project["path"])

    def fill(self):
        (self.workspace / "treatment.md").write_text(
            f"The {WORD} keeper refuses to leave the island.", encoding="utf-8")
        DecisionStore(self.workspace).save(f"The {WORD} stays in the final cut",
                                           "s1", "accepted")
        MemoryStore(self.cfg, self.workspace, "writing").append(
            f"Keep the {WORD} imagery", "project")
        session = self.service.new_session(str(self.workspace), "writing")
        session.add("user", f"What happens to the {WORD} in act two?")
        return session

    def groups(self, query=WORD, session_id=None):
        answer = finder.find(self.cfg, query, workspace=self.workspace,
                             work_mode="writing")
        return {group["kind"]: group["items"] for group in answer["groups"]}, answer

    def test_one_word_reaches_all_four_places(self):
        self.fill()
        groups, answer = self.groups()
        self.assertEqual(sorted(groups), ["chat", "decision", "file", "memory"])
        self.assertEqual(answer["total"], sum(len(items) for items in groups.values()))

    def test_every_result_says_where_it_leads(self):
        self.fill()
        groups, _ = self.groups()
        self.assertEqual(groups["chat"][0]["open"]["what"], "chat")
        self.assertTrue(groups["chat"][0]["open"]["session_id"],
                        "a chat result without its id cannot be opened")
        self.assertEqual(Path(groups["file"][0]["open"]["path"]).name, "treatment.md")
        self.assertEqual(groups["memory"][0]["open"], {"what": "memory", "scope": "project"})
        self.assertEqual(groups["decision"][0]["open"], {"what": "decisions"})

    def test_the_project_bookkeeping_is_not_listed_twice(self):
        """Memory and decisions live in files, and have their own groups."""
        self.fill()
        groups, _ = self.groups()
        listed = [item["title"] for item in groups["file"]]
        self.assertEqual(listed, ["treatment.md"])
        self.assertFalse([name for name in listed if "QWEN_MEMORY" in name or ".qwen" in name])

    def test_no_source_can_drown_the_others(self):
        for index in range(finder.PER_SOURCE + 6):
            (self.workspace / f"scene-{index:02d}.md").write_text(
                f"The {WORD} again, scene {index}", encoding="utf-8")
        groups, _ = self.groups()
        self.assertEqual(len(groups["file"]), finder.PER_SOURCE)

    def test_nothing_is_searched_without_searchable_words(self):
        self.fill()
        for query in ("", "   ", "!!!", "  ??  "):
            answer = finder.find(self.cfg, query, workspace=self.workspace)
            self.assertEqual(answer["groups"], [], query)
            self.assertEqual(answer["total"], 0, query)

    def test_without_a_project_the_project_places_are_simply_absent(self):
        self.fill()
        answer = finder.find(self.cfg, WORD, workspace=None, work_mode="writing")
        kinds = {group["kind"] for group in answer["groups"]}
        self.assertNotIn("file", kinds)
        self.assertNotIn("decision", kinds)
        self.assertIn("chat", kinds)

    def test_a_failing_source_does_not_fail_the_search(self):
        """A search that raises is worse than a search that finds less."""
        self.fill()
        with patch("harness.file_index.search_index", side_effect=OSError("disk gone")):
            answer = finder.find(self.cfg, WORD, workspace=self.workspace,
                                 work_mode="writing")
        kinds = {group["kind"] for group in answer["groups"]}
        self.assertNotIn("file", kinds)
        self.assertIn("chat", kinds)

    def test_the_endpoint_uses_the_project_of_the_named_chat(self):
        session = self.fill()
        answer = self.client.get("/api/find", params={"query": WORD,
                                                      "session_id": session.id}).json()
        kinds = {group["kind"] for group in answer["groups"]}
        self.assertIn("file", kinds, "the chat's project should have been searched")
        # Without a chat there is no project, so only what is not project-bound.
        loose = self.client.get("/api/find", params={"query": WORD}).json()
        self.assertNotIn("file", {group["kind"] for group in loose["groups"]})

    def test_a_file_hit_can_actually_be_opened(self):
        """The preview resolves an id from the file store, never a path, so a hit
        that carried only a path answered 404 when clicked."""
        session = self.fill()
        answer = self.client.get("/api/find", params={"query": WORD,
                                                      "session_id": session.id}).json()
        files = next(g for g in answer["groups"] if g["kind"] == "file")
        record = files["items"][0]["open"]["file"]
        self.assertTrue(record["id"])
        self.assertEqual(record["name"], "treatment.md")
        preview = self.client.get(f"/api/files/{record['id']}/preview").json()
        self.assertIn(WORD, preview["content"])

    def test_a_project_file_can_be_made_previewable_by_path(self):
        session = self.fill()
        record = self.client.post(f"/api/sessions/{session.id}/register-file",
                                  json={"path": "treatment.md"}).json()
        self.assertEqual(record["name"], "treatment.md")
        self.assertIn(WORD, self.client.get(
            f"/api/files/{record['id']}/preview").json()["content"])

    def test_a_file_outside_the_project_is_refused(self):
        session = self.fill()
        outside = self.root / "not-in-the-project.md"
        outside.write_text("secret", encoding="utf-8")
        answer = self.client.post(f"/api/sessions/{session.id}/register-file",
                                  json={"path": str(outside)})
        self.assertEqual(answer.status_code, 400)
        missing = self.client.post(f"/api/sessions/{session.id}/register-file",
                                   json={"path": "no-such-file.md"})
        self.assertEqual(missing.status_code, 404)

    def test_a_snippet_shows_the_matching_part_of_a_long_decision(self):
        long_text = "a " * 400 + f"the {WORD} decision" + " b" * 400
        DecisionStore(self.workspace).save(long_text, "s1", "accepted")
        groups, _ = self.groups()
        title = groups["decision"][0]["title"]
        self.assertIn(WORD, title)
        self.assertLessEqual(len(title), finder.SNIPPET_CHARS + 2)


if __name__ == "__main__":
    unittest.main()
