"""Offline release-plan and package-to-flasher compatibility checks."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'firmware/tools'))
sys.path.insert(0, str(ROOT / 'tests/tools'))
from test_flash import image, flash
from target_profile import load_device
from release_inputs import load_release

spec = importlib.util.spec_from_file_location('ci_build', ROOT / 'firmware/tools/ci-build.py')
ci = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ci)


class CiBuildTests(unittest.TestCase):
    def test_default_plan_performs_no_writes_or_downloads(self):
        with tempfile.TemporaryDirectory() as temp:
            task = Path(temp) / 'not-created'
            with patch.object(ci, 'build') as build, contextlib.redirect_stdout(io.StringIO()) as output:
                ci.main(['--version', 'v0.1.0-rc.1', '--task-root', str(task)])
            build.assert_not_called()
            self.assertFalse(task.exists())
            self.assertFalse(json.loads(output.getvalue())['apply'])
        for version in ['release', 'v1', 'v1.0.0;touch bad', '-v1.0.0']:
            with self.assertRaises(ValueError):ci.release_version(version)

    def test_apply_refuses_local_host_and_task_escape(self):
        with tempfile.TemporaryDirectory() as temp:
            task = Path(temp) / 'not-created'
            with patch.dict(os.environ, {'GITHUB_ACTIONS': 'false'}), patch.object(ci.platform, 'system', return_value='Linux'), patch.object(ci.platform, 'machine', return_value='x86_64'):
                with self.assertRaisesRegex(ValueError, 'disposable GitHub runners'):
                    ci.prepare(task, load_release(), load_device(), 'v0.1.0')
            with patch.dict(os.environ, {'GITHUB_ACTIONS': 'true', 'RUNNER_TEMP': str(Path(temp)/'runner')}), patch.object(ci.platform, 'system', return_value='Linux'), patch.object(ci.platform, 'machine', return_value='x86_64'):
                with self.assertRaisesRegex(ValueError, 'below RUNNER_TEMP'):
                    ci.prepare(task, load_release(), load_device(), 'v0.1.0')
            self.assertFalse(task.exists())

    def test_zip_and_loose_release_files_are_accepted_by_the_flasher(self):
        with tempfile.TemporaryDirectory() as temp:
            task = Path(temp)
            device = load_device()
            source = task / Path(device['image']['path']).name
            source.write_bytes(image())
            source.with_name(source.name.removesuffix(device['image']['manifest_suffix']) + '.manifest').write_text('alwayroute-core - 1.13.21\n')
            inspection = task / 'inspection.json'
            inspection.write_text(json.dumps({'checks': {'synthetic': True}}))
            manifest = {'schema_version': 1, 'device': device['id'], 'version': 'v0.1.0', 'source_commit': 'a'*40}
            publish = task / 'release'
            with contextlib.redirect_stdout(io.StringIO()):
                ci.package_release(task, publish, 'v0.1.0', device, source, inspection, manifest)
            candidate = next(publish.glob('*-sysupgrade.bin'))
            flash.load_bundle(candidate)
            bundle = next(publish.glob('*-bundle.zip'))
            with zipfile.ZipFile(bundle) as archive:
                self.assertNotIn(bundle.name, archive.namelist())
                self.assertEqual(archive.read('flash.py'), (ROOT/'scripts/flash.py').read_bytes())
                archive.extractall(task/'extracted')
            flash.load_bundle(task/'extracted'/candidate.name)
            for line in (publish/'SHA256SUMS').read_text().splitlines():
                expected,name=line.split('  ',1)
                self.assertEqual(expected,ci.sha256(publish/name))


if __name__ == '__main__':
    unittest.main()
