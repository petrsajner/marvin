"""Tests for workspace relocation, automatic discovery, and Git/GitHub recovery."""
from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from harness.application import ApplicationService
from harness.config import Config, load_config
from harness.history_index import HistoryIndex
from harness.projects import (
    Projects,
    find_relocated_folder,
    normalize_git_remote,
    read_git_identity,
    restore_git_workspace,
    sanitize_git_remote,
)
from harness.session import Session
from harness.web_api import create_app


def _rmtree_force(path: Path) -> None:
    def _on_error(func, target, _exc):
        try:
            os.chmod(target, stat.S_IWRITE)
            func(target)
        except OSError:
            pass
    shutil.rmtree(path, onexc=_on_error)


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    proc = subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
        creationflags=0x08000000 if os.name == "nt" else 0,
    )
    if proc.returncode != 0:
        raise AssertionError(f"git {' '.join(args)} failed ({proc.returncode}): {proc.stderr or proc.stdout}")
    return proc


def _init_git_repo(path: Path, *, filename: str = "README.md", content: str = "hello\n",
                   remote: str | None = None, branch: str = "main") -> None:
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init", "-b", branch)
    _git(path, "config", "user.email", "marvin@example.com")
    _git(path, "config", "user.name", "Marvin Test")
    (path / filename).write_text(content, encoding="utf-8")
    _git(path, "add", filename)
    _git(path, "commit", "-m", "Initial commit")
    if remote:
        _git(path, "remote", "add", "origin", remote)


def _make_cfg(root: Path) -> Config:
    data = load_config().data
    data["projects"] = {"root_dir": "projects"}
    data["paths"] = {
        "runtime_dir": "runtime",
        "sessions_dir": "sessions",
        "models_dir": "models",
    }
    return Config(data, root=root)


class ProjectRelocationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="marvin-reloc-"))
        self.app_root = self.tmp / "app"
        self.app_root.mkdir()
        self.cfg = _make_cfg(self.app_root)
        self.service = ApplicationService(self.cfg, manage_model=False)
        self.client = TestClient(create_app(self.cfg, service=self.service))

    def tearDown(self):
        self.service.close()
        _rmtree_force(self.tmp)

    # ---------------------------------------------------------------- helpers
    def test_sanitize_and_normalize_git_remote(self):
        self.assertEqual(
            sanitize_git_remote("https://ghp_secretToken@github.com/Owner/Repo.git"),
            "https://github.com/Owner/Repo.git",
        )
        self.assertEqual(
            sanitize_git_remote("https://user:pass@github.com:8443/Owner/Repo.git"),
            "https://github.com:8443/Owner/Repo.git",
        )
        self.assertEqual(sanitize_git_remote("--upload-pack=evil"), "")
        self.assertEqual(sanitize_git_remote("  -c core.sshCommand=bad "), "")
        self.assertEqual(
            normalize_git_remote("git@github.com:Owner/Repo.git"),
            normalize_git_remote("https://github.com/owner/repo"),
        )

    def test_attach_folder_records_git_identity_without_credentials(self):
        repo = self.tmp / "work" / "alpha"
        _init_git_repo(repo, remote="https://token123@github.com/acme/alpha.git", branch="main")
        project = Projects(self.cfg).attach_folder(str(repo))
        self.assertEqual(project.get("git_remote"), "https://github.com/acme/alpha.git")
        self.assertEqual(project.get("git_branch"), "main")
        self.assertTrue(project.get("git_root_commit"))

    # ---------------------------------------------------------------- Step 1
    def test_step1_auto_locate_moved_and_renamed_git_repo_rejects_decoy(self):
        orig = self.tmp / "drive_d" / "work" / "MyRepo"
        _init_git_repo(orig, remote="https://github.com/acme/myrepo.git", branch="main")
        projects = Projects(self.cfg)
        project = projects.attach_folder(str(orig))

        # Create a session & pinned file & history index entry tied to the original path.
        pinned = orig / "README.md"
        session = self.service.select_project(project["id"])
        session.add("user", "Remember this unique relocation phrase")
        session.pin_context_file(pinned)
        HistoryIndex(self.cfg.path("paths.sessions_dir")).sync_existing()

        # Move AND rename the real repo to a simulated second drive; place a decoy repo at same name!
        sim_drive_e = self.tmp / "drive_e"
        moved = sim_drive_e / "archived" / "MyRepo-Renamed"
        moved.parent.mkdir(parents=True)
        shutil.move(str(orig), str(moved))

        decoy = sim_drive_e / "work" / "MyRepo"
        _init_git_repo(decoy, filename="decoy.txt", content="other repo\n",
                       remote="https://github.com/other/decoy.git")

        located = self.service.locate_project(project["id"], drives=[sim_drive_e], extra_roots=[sim_drive_e])
        self.assertTrue(located["found"])
        self.assertTrue(located["relocated"])
        self.assertEqual(Path(located["new_path"]).resolve(), moved.resolve())
        self.assertEqual(located["sessions_updated"], 1)

        # Registry, session meta, pinned file, and SQLite history index all point to the new path.
        updated_project = Projects(self.cfg).by_id(project["id"])
        self.assertEqual(Path(updated_project["path"]).resolve(), moved.resolve())
        self.assertFalse(updated_project.get("missing"))

        meta = json.loads((session.dir / "meta.json").read_text(encoding="utf-8"))
        self.assertEqual(Path(meta["workspace"]).resolve(), moved.resolve())
        self.assertEqual(Path(meta["pinned_files"][0]).resolve(), (moved / "README.md").resolve())

        hits = HistoryIndex(self.cfg.path("paths.sessions_dir")).search("unique relocation phrase")
        self.assertEqual(len(hits), 1)
        self.assertEqual(Path(hits[0]["workspace"]).resolve(), moved.resolve())

    def test_step1_non_git_prefers_marvin_marker_and_refuses_ambiguous_tie(self):
        orig = self.tmp / "src_root" / "NotesApp"
        orig.mkdir(parents=True)
        (orig / "QWEN_MEMORY.md").write_text("# Memory\n", encoding="utf-8")
        project = Projects(self.cfg).attach_folder(str(orig))

        # Move to new location while also creating an unrelated same-name folder without marker.
        search_root = self.tmp / "other_drive"
        real_new = search_root / "Moved" / "NotesApp"
        real_new.parent.mkdir(parents=True)
        shutil.move(str(orig), str(real_new))

        plain_same_name = search_root / "Other" / "NotesApp"
        plain_same_name.mkdir(parents=True)

        found = find_relocated_folder(
            Projects(self.cfg).by_id(project["id"]),
            self.cfg,
            drives=[search_root],
            extra_roots=[search_root],
        )
        self.assertEqual(found.resolve(), real_new.resolve())

        # Now add a second Marvin-marked folder with the exact same name -> ambiguous tie -> returns None.
        (plain_same_name / "QWEN_MEMORY.md").write_text("# Other memory\n", encoding="utf-8")
        ambiguous = find_relocated_folder(
            Projects(self.cfg).by_id(project["id"]),
            self.cfg,
            drives=[search_root],
            extra_roots=[search_root],
        )
        self.assertIsNone(ambiguous)

    def test_step1_select_project_auto_redirects_or_raises_unavailable(self):
        orig = self.tmp / "plain_old" / "Vanished"
        orig.mkdir(parents=True)
        project = Projects(self.cfg).attach_folder(str(orig))
        shutil.rmtree(orig)

        with patch("harness.projects._local_drives", return_value=[]):
            with self.assertRaisesRegex(FileNotFoundError, "Project folder is unavailable"):
                self.service.select_project(project["id"])

            resp = self.client.post(f"/api/projects/{project['id']}/locate")
            self.assertEqual(resp.status_code, 200)
            self.assertFalse(resp.json()["found"])

    # ---------------------------------------------------------------- Step 2 + 3
    def test_step3_new_empty_folder_clones_from_remote_via_api(self):
        # Create a local bare repo acting as a GitHub remote.
        bare = self.tmp / "remotes" / "demo.git"
        bare.mkdir(parents=True)
        _git(bare, "init", "--bare", "-b", "main")

        orig = self.tmp / "old_disk" / "DemoApp"
        _init_git_repo(orig, filename="app.py", content="print('v1')\n", remote=str(bare), branch="main")
        _git(orig, "push", "-u", "origin", "main")

        project = Projects(self.cfg).attach_folder(str(orig))
        session = self.service.select_project(project["id"])
        session.add("user", "Initial project chat")

        # Simulate deleting/losing the original folder completely.
        _rmtree_force(orig)

        # User creates a brand-new empty folder via Explorer and triggers Step 2 + 3 API.
        fresh_dir = self.tmp / "new_disk" / "DemoApp-Fresh"
        fresh_dir.mkdir(parents=True)

        resp = self.client.post(
            f"/api/projects/{project['id']}/relocate",
            json={"path": str(fresh_dir), "mode": "new", "init_git": True},
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()
        self.assertEqual(Path(body["new_path"]).resolve(), fresh_dir.resolve())
        self.assertEqual(body["git"]["action"], "cloned")
        self.assertTrue(body["git"]["ok"])
        self.assertEqual((fresh_dir / "app.py").read_text(encoding="utf-8"), "print('v1')\n")

        ident = read_git_identity(fresh_dir)
        self.assertEqual(normalize_git_remote(ident.get("git_remote")), normalize_git_remote(str(bare)))
        self.assertEqual(ident.get("git_branch"), "main")
        self.assertEqual(body["sessions_updated"], 1)

    def test_step3_non_empty_new_folder_initializes_git_links_origin_and_preserves_files(self):
        bare = self.tmp / "remotes" / "preserve.git"
        bare.mkdir(parents=True)
        _git(bare, "init", "--bare", "-b", "main")

        seed = self.tmp / "seed"
        _init_git_repo(seed, filename="upstream.txt", content="from remote\n", remote=str(bare), branch="main")
        _git(seed, "push", "-u", "origin", "main")

        target = self.tmp / "nonempty"
        target.mkdir(parents=True)
        local_file = target / "local_notes.txt"
        local_file.write_text("do not overwrite me\n", encoding="utf-8")

        result = restore_git_workspace(target, remote_url=str(bare), branch="main", init_local=True)
        self.assertTrue(result["ok"])
        self.assertEqual(result["action"], "initialized_and_fetched")
        self.assertEqual(local_file.read_text(encoding="utf-8"), "do not overwrite me\n")
        self.assertTrue((target / ".git").is_dir())
        refs = _git(target, "branch", "-r").stdout
        self.assertIn("origin/main", refs)

    def test_step3_new_folder_without_remote_initializes_local_git(self):
        target = self.tmp / "local_only"
        target.mkdir(parents=True)
        result = restore_git_workspace(target, remote_url=None, branch="main", init_local=True)
        self.assertTrue(result["ok"])
        self.assertEqual(result["action"], "initialized")
        self.assertTrue((target / ".git").is_dir())

    def test_step3_existing_repo_missing_origin_adds_remote_only(self):
        target = self.tmp / "existing_no_remote"
        _init_git_repo(target, filename="keep.txt", content="kept\n", remote=None, branch="main")
        result = restore_git_workspace(
            target,
            remote_url="https://github.com/acme/restored.git",
            branch="main",
            init_local=True,
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["action"], "remote_added")
        self.assertEqual(read_git_identity(target).get("git_remote"), "https://github.com/acme/restored.git")
        self.assertEqual((target / "keep.txt").read_text(encoding="utf-8"), "kept\n")

    def test_step3_rejects_flag_injection_in_remote_url(self):
        target = self.tmp / "bad_remote"
        target.mkdir(parents=True)
        with self.assertRaisesRegex(ValueError, "Invalid Git remote URL"):
            restore_git_workspace(target, remote_url="--upload-pack=calc.exe", init_local=True)


if __name__ == "__main__":
    unittest.main()
