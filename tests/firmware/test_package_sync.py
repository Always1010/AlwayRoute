"""Exercise reviewed package copies with fake rsync; no builds or router IO."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch


TOOLS = Path(__file__).resolve().parents[2] / 'firmware/tools'
sys.path.insert(0, str(TOOLS))
spec = importlib.util.spec_from_file_location('package_sync', TOOLS / 'sync-packages.py')
sync = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sync)


class Output(io.StringIO):
    @property
    def buffer(self):
        return self

    def write(self, value):
        return super().write(value.decode() if isinstance(value, bytes) else value)


class PackageSyncTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='alwayroute-package-test-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.name = 'alwayroute-manager'
        self.source = self.root / 'firmware/openwrt' / self.name
        self.source.mkdir(parents=True)
        (self.source / 'Makefile').write_bytes(b'reviewed input')
        self.tree = self.root / 'build/source'
        (self.tree / 'package').mkdir(parents=True)
        self.target = self.tree / 'package' / self.name
        self.environment = self.root / 'env.json'
        self.environment.write_text(json.dumps({'schema_version': 1, 'build': {
            'task_root': str(self.root / 'task'), 'openwrt_tree': str(self.tree),
        }}))
        self.calls = []
        self.copy_hook = None
        self.preview_hook = None
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(sync, 'ROOT', self.root))
        self.stack.enter_context(patch.object(sync, 'run_rsync', side_effect=self.rsync))
        self.stack.enter_context(contextlib.redirect_stdout(Output()))
        self.errors = self.stack.enter_context(contextlib.redirect_stderr(io.StringIO()))

    def rsync(self, executable, source, target, *, dry_run):
        self.calls.append((source, target, dry_run))
        if dry_run:
            if self.preview_hook:
                self.preview_hook()
            return b'>fc........ Makefile\n'
        if self.copy_hook:
            self.copy_hook()
        shutil.copytree(source, target, dirs_exist_ok=True, copy_function=shutil.copy2)
        return b''

    def invoke(self, *extra):
        return sync.main(['--env', str(self.environment), '--package', self.name, *extra])

    def test_rejects_destination_resolving_outside_build_tree(self):
        original = Path.resolve
        outside = self.root / 'outside'
        with patch.object(Path, 'resolve', lambda path, *args, **kwargs:
                          outside if path == self.target else original(path, *args, **kwargs)):
            self.assertEqual(self.invoke(), 2)
        self.assertFalse(self.calls)
        self.assertIn('inside', self.errors.getvalue())

    def test_rejects_source_change_after_review_or_during_preview(self):
        self.assertEqual(self.invoke(), 0)
        (self.source / 'Makefile').write_bytes(b'changed since review')
        self.assertEqual(self.invoke('--apply'), 2)
        self.assertTrue(all(call[2] for call in self.calls))
        self.assertFalse(self.target.exists())
        self.preview_hook = lambda: (self.source / 'Makefile').write_bytes(b'changed during preview')
        self.assertEqual(self.invoke('--apply'), 2)
        self.assertTrue(all(call[2] for call in self.calls))

    def test_reports_extra_files_without_deleting_them(self):
        self.target.mkdir()
        old = self.target / 'retired.uc'
        old.write_bytes(b'preserved')
        self.assertEqual(self.invoke(), 2)
        self.assertFalse(self.calls)
        self.assertEqual(old.read_bytes(), b'preserved')
        self.assertIn(self.name + '/retired.uc', self.errors.getvalue())

    def test_apply_copies_reviewed_snapshot_even_if_repository_changes_during_copy(self):
        self.assertEqual(self.invoke(), 0)
        self.copy_hook = lambda: (self.source / 'Makefile').write_bytes(b'unreviewed input')
        self.assertEqual(self.invoke('--apply'), 2)
        self.assertEqual((self.target / 'Makefile').read_bytes(), b'reviewed input')
        copied_from = [call[0] for call in self.calls if not call[2]][0]
        self.assertNotEqual(copied_from, self.source)

    def test_success_verifies_complete_hash_sets_and_clears_plan(self):
        self.assertEqual(self.invoke(), 0)
        self.assertEqual(self.invoke('--apply'), 0)
        self.assertEqual(sync.hashes(sync.manifest(self.target)), sync.hashes(sync.manifest(self.source)))
        self.assertFalse((self.root / '.local/runs/package-sync-plan.json').exists())


if __name__ == '__main__':
    unittest.main()
