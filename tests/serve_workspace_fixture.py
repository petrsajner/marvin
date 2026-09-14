"""Run the production UI/API against disposable data and a deterministic model."""
import copy
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from test_workspace import Model
from harness.application import ApplicationService
from harness.config import Config, load_config
from harness.projects import Projects
from harness.web_api import create_app
import uvicorn


if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="ui-fixture-", dir=ROOT / "runtime") as directory:
        data = copy.deepcopy(load_config().data)
        data["agent"].update(workspace=None, autonomy="auto")
        data["work_mode"] = "development"
        data["skills"]["directory"] = str(ROOT / "skills")
        cfg = Config(data, Path(directory))
        service = ApplicationService(cfg, llm_factory=Model, manage_model=False)
        service.preferences["language"] = "en"
        project = Projects(cfg).create_new("Notes Studio")
        session = service.new_session(project["path"], "development")
        session.meta["title"] = "Search and saving"
        session.add("user", "Add search while preserving automatic note saving.")
        session.add("assistant", "I checked note persistence. Next I will add search and verify restoration of unfinished work.")
        for i in range(25):
            older = service.new_session(project["path"], "development")
            older.add("user", f"What number is written in the attached image? Answer with the number only. Title wrapping check {i + 1}")
        service.select_session(session.id)
        uvicorn.run(create_app(cfg, service=service), host="127.0.0.1", port=7878, log_level="warning")
