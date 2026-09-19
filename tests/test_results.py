"""Results has to hold the results.

Two things kept the real ones out of it. The change journal starts a fresh
manifest per task and Results asked only the current one, so a finished program
dropped out the moment the next task touched a test script. And anything written
by something other than the file tools - a picture from an image service, an
artefact a program built - was never recorded at all, however plainly its path
appeared in the conversation.
"""
import tempfile
import unittest
from pathlib import Path

from harness.changes import ChangeJournal


class Session:
    """The journal needs somewhere to write and nothing else."""
    def __init__(self, directory: Path):
        self.dir = directory


class ResultsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.workspace = self.root / "project"
        self.workspace.mkdir()
        self.journal = ChangeJournal(Session(self.root / "session"), self.workspace)

    def _write(self, name: str, text: str) -> Path:
        path = self.workspace / name
        self.journal.record_before(path)
        path.write_text(text, encoding="utf-8")
        self.journal.record_after(path)
        return path

    def test_earlier_tasks_are_not_forgotten(self):
        self.journal.begin_task("write the game")
        self._write("game.py", "the finished program")
        self.journal.begin_task("try a test script")
        self._write("scratch_test.py", "a throwaway")

        current = [item["path"] for item in self.journal.summary()["files"]]
        self.assertEqual(current, ["scratch_test.py"],
                         "one task's manifest is still one task's work")

        every = []
        for task_id in self.journal.task_ids():
            every.extend(item["path"] for item in self.journal.summary(task_id)["files"]
                         if item["changed"])
        self.assertIn("game.py", every, "the finished program has to survive the next task")
        self.assertIn("scratch_test.py", every)

    def test_task_ids_are_oldest_first_and_complete(self):
        self.journal.begin_task("one")
        self._write("a.txt", "a")
        self.journal.begin_task("two")
        self._write("b.txt", "b")
        ids = self.journal.task_ids()
        self.assertEqual(len(ids), 2)
        labels = [self.journal.summary(task_id)["label"] for task_id in ids]
        # Not sorted by folder name: a task id is a second-resolution stamp plus
        # random hex, so two tasks in one second would sort by the random half.
        self.assertEqual(labels, ["one", "two"])

    def test_nothing_recorded_yet_reads_as_nothing(self):
        self.assertEqual(ChangeJournal(Session(self.root / "empty"), self.workspace).task_ids(), [])

    def test_a_file_written_by_something_else_still_counts(self):
        """A picture from an image service is written by that service, so no
        before/after pair ever brackets it."""
        self.journal.begin_task("make a picture")
        picture = self.workspace / "generated-images" / "fox.png"
        picture.parent.mkdir(parents=True)
        picture.write_bytes(b"\x89PNG\r\n\x1a\n")
        self.journal.record_created(picture)
        files = self.journal.summary()["files"]
        self.assertEqual(len(files), 1)
        self.assertEqual(files[0]["change"], "created")
        self.assertTrue(files[0]["changed"], "it has to read as changed to reach Results")
        self.assertTrue(files[0]["path"].endswith("fox.png"))

    def test_recording_a_file_twice_records_it_once(self):
        self.journal.begin_task("make a picture")
        picture = self.workspace / "fox.png"
        picture.write_bytes(b"\x89PNG\r\n\x1a\n")
        self.journal.record_created(picture)
        self.journal.record_created(picture)
        self.assertEqual(len(self.journal.summary()["files"]), 1)

    def test_a_file_that_is_not_there_is_not_recorded(self):
        self.journal.begin_task("make a picture")
        self.journal.record_created(self.workspace / "never-arrived.png")
        self.assertEqual(self.journal.summary()["files"], [])

    def test_an_edited_file_is_not_downgraded_to_created(self):
        """record_created must not overwrite a real before/after pair."""
        self.journal.begin_task("edit")
        path = self._write("game.py", "first")
        self.journal.record_created(path)
        files = self.journal.summary()["files"]
        self.assertEqual(len(files), 1)
        self.assertEqual(files[0]["change"], "created",
                        "it did not exist before this task, so created is right")
        self.journal.begin_task("edit again")
        self._write("game.py", "second")
        again = self.journal.summary()["files"]
        self.assertEqual(again[0]["change"], "modified")


class DiscoveryTests(unittest.TestCase):
    """What actually reaches the Results panel, across the whole conversation."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.workspace = self.root / "project"
        self.workspace.mkdir()
        self.session = Session(self.root / "session")
        self.session.dir.mkdir()
        self.session.id = "s1"
        self.session.meta = {"workspace": str(self.workspace)}
        self.journal = ChangeJournal(self.session, self.workspace)

    def _discover(self):
        from harness.application import ApplicationService
        registered = []

        class Store:
            def register_file(self, path, session_id, kind="result", name=None):
                registered.append((Path(path).name, kind))
                return {"id": Path(path).name}

        class Context:
            pass

        context = Context()
        context.changes = self.journal
        context.workspace = self.workspace
        agent = Context()
        agent.ctx = context
        service = ApplicationService.__new__(ApplicationService)
        service.store = Store()
        ApplicationService.discover_results(service, self.session, agent)
        return registered

    def test_the_finished_program_survives_later_tasks(self):
        self.journal.begin_task("write the game")
        game = self.workspace / "game.py"
        self.journal.record_before(game)
        game.write_text("the finished program", encoding="utf-8")
        self.journal.record_after(game)

        self.journal.begin_task("poke at a test")
        scratch = self.workspace / "scratch_test.py"
        self.journal.record_before(scratch)
        scratch.write_text("throwaway", encoding="utf-8")
        self.journal.record_after(scratch)

        names = [name for name, _ in self._discover()]
        self.assertIn("game.py", names, "the thing that was built has to be in Results")
        self.assertIn("scratch_test.py", names)

    def test_a_generated_picture_reaches_results(self):
        self.journal.begin_task("make a picture")
        picture = self.workspace / "generated-images" / "fox.png"
        picture.parent.mkdir(parents=True)
        picture.write_bytes(b"\x89PNG\r\n\x1a\n")
        self.journal.record_created(picture)
        self.assertIn("fox.png", [name for name, _ in self._discover()])

    def test_a_conversation_that_produced_nothing_produces_nothing(self):
        self.assertEqual(self._discover(), [])

    def test_results_survive_a_restart_with_no_agent_loaded(self):
        """Agents live in memory only for conversations used since the program
        started. Asking only those emptied Results after every restart."""
        self.journal.begin_task("write the game")
        game = self.workspace / "game.py"
        self.journal.record_before(game)
        game.write_text("the finished program", encoding="utf-8")
        self.journal.record_after(game)

        from harness.application import ApplicationService
        registered = []

        class Store:
            def register_file(self, path, session_id, kind="result", name=None):
                registered.append(Path(path).name)
                return {"id": Path(path).name}

        service = ApplicationService.__new__(ApplicationService)
        service.store = Store()
        ApplicationService.discover_results(service, self.session, None)
        self.assertIn("game.py", registered)

    def test_an_output_folder_is_read_whatever_wrote_it(self):
        """A picture made before the journal learned to record one still has to
        appear, and so does anything a program drops in an output folder."""
        from harness.application import ApplicationService
        registered = []

        class Store:
            def register_file(self, path, session_id, kind="result", name=None):
                registered.append(Path(path).name)
                return {"id": Path(path).name}

        pictures = self.session.dir / "generated-images"
        pictures.mkdir(parents=True)
        (pictures / "fox.png").write_bytes(b"\x89PNG\r\n\x1a\n")
        exported = self.session.dir / "exports"
        exported.mkdir()
        (exported / "report.pdf").write_bytes(b"%PDF-1.4")

        service = ApplicationService.__new__(ApplicationService)
        service.store = Store()
        ApplicationService.discover_results(service, self.session, None)
        self.assertIn("fox.png", registered)
        self.assertIn("report.pdf", registered)


if __name__ == "__main__":
    unittest.main()
