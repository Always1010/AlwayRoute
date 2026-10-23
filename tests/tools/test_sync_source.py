"""Focused regression checks for developer workflow boundaries."""
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
from alwayroute_context import ContextError, load_environment, router_argv

def module(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / filename)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result

sync = module('sync_source', 'sync-source.py')

class WorkflowTests(unittest.TestCase):
    def test_sync_excludes_private_files_even_if_tracked_and_protects_build_trees(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "source").write_text("source input")
            for name in ("source file.py", ".env", "session-log.md", ".env.example", "private/auth.json", "image.apk"):
                path = root / name
                path.parent.mkdir(exist_ok=True)
                path.write_text("sample")
            self.assertTrue(sync.eligible("source file.py", root))
            self.assertTrue(sync.eligible(".env.example", root))
            for name in (".env", "session-log.md", "private/auth.json", "image.apk", "../escape"):
                self.assertFalse(sync.eligible(name, root), name)
        for workspace in ("/", "/srv/task", "/srv/task/openwrt-build/source", "/srv/task/build-cache/project"):
            with self.assertRaises(ContextError):
                sync.validate_workspace({"executor": "ssh", "ssh_alias": "builder", "task_root": "/srv/task",
                                         "openwrt_tree": "/srv/task/openwrt-build/source", "project_workspace": workspace})

    def test_apply_requires_identical_preview_and_does_not_delete(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "source").write_text("source input")
            plan = root / ".local/plan.json"
            env = {"build": {"executor": "ssh", "ssh_alias": "builder", "project_workspace": "/srv/task/workspaces/project"}}
            calls = []
            def run(argv, **kwargs):
                calls.append(argv)
                if "--dry-run" not in argv:
                    (root / "source").write_text("unreviewed edit")
                    staged = Path(argv[-2])
                    if sys.platform == "win32":
                        staged = Path(str(staged)[1] + ":" + str(staged)[2:])
                    self.assertEqual((staged / "source").read_text(), "source input")
                return subprocess.CompletedProcess(argv, 0, b"changed source\n", b"")
            with patch.object(sync, "ROOT", root), patch.object(sync, "load_environment", return_value=env), \
                 patch.object(sync, "runtime", return_value=("rsync", "ssh", {})), \
                 patch.object(sync, "check_remote_workspace"), patch.object(sync, "source_snapshot", return_value={"source": sync.hashlib.sha256(b"source input").hexdigest()}), \
                 patch.object(sync.subprocess, "run", side_effect=run):
                self.assertEqual(sync.main(["--env", "unused", "--plan", str(plan), "--apply"]), 2)
                plan.parent.mkdir(parents=True, exist_ok=True)
                plan.write_text(json.dumps({"schema_version": 1, "target": "builder:/srv/task/workspaces/project/",
                                            "files": {"source": "old hash"}, "preview_sha256": "different"}))
                self.assertEqual(sync.main(["--env", "unused", "--plan", str(plan), "--apply"]), 2)
                self.assertTrue(all("--dry-run" in call for call in calls))
                self.assertGreaterEqual(len(calls), 2)
                self.assertTrue(all("--delete" not in call for call in calls))
                plan.write_text(json.dumps({"schema_version": 1, "target": "builder:/srv/task/workspaces/project/",
                                            "files": {"source": sync.hashlib.sha256(b"source input").hexdigest()},
                                            "preview_sha256": sync.hashlib.sha256(b"changed source\n").hexdigest()}))
                self.assertEqual(sync.main(["--env", "unused", "--plan", str(plan), "--apply"]), 0)
                self.assertFalse(plan.exists())
                self.assertNotIn("--dry-run", calls[-1])

if __name__ == '__main__':
    unittest.main()
