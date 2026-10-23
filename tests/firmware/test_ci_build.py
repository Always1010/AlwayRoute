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

    def test_release_has_only_zip_and_bin_and_bundle_is_accepted_by_flasher(self):
        with tempfile.TemporaryDirectory() as temp:
            task = Path(temp)
            device = load_device()
            source = task / Path(device['image']['path']).name
            source.write_bytes(image())
            source.with_name(source.name.removesuffix(device['image']['manifest_suffix']) + '.manifest').write_text('alwayroute-core - 1.13.21\n')
            inspection = task / 'inspection.json'
            inspection.write_text(json.dumps({'checks': {'synthetic': True}, 'device': device['id'], 'sha256': ci.sha256(source)}))
            manifest = {'schema_version': 1, 'device': device['id'], 'version': 'v0.1.0', 'source_commit': 'a'*40}
            publish = task / 'release'
            with contextlib.redirect_stdout(io.StringIO()):
                ci.package_release(task, publish, 'v0.1.0', device, source, inspection, manifest)
            public = publish / 'public'
            candidate = next(public.glob('*-sysupgrade.bin'))
            bundle = next(public.glob('*.zip'))
            self.assertEqual({p.name for p in public.iterdir()}, {candidate.name, bundle.name})
            with zipfile.ZipFile(bundle) as archive:
                self.assertEqual(set(archive.namelist()), {candidate.name, 'flash.py', 'SHA256SUMS',
                                                        'build-manifest.json', 'README.md', 'NOTICE.txt'})
                self.assertEqual(archive.read('flash.py'), (ROOT/'scripts/flash.py').read_bytes())
                readme = archive.read('README.md').decode()
                self.assertIn('本版本与下载选择', readme)
                self.assertIn('原厂系统首次刷入', readme)
                self.assertIn('NOTICE.txt', readme)
                self.assertNotIn('FLASHING.md', readme)
                notice = archive.read('NOTICE.txt').decode()
                for license in (ROOT/'LICENSES').glob('*.txt'):
                    self.assertTrue(license.read_text(encoding='utf-8') in notice, 'Missing license: ' + license.name)
                archive.extractall(task/'extracted')
            flash.load_bundle(task/'extracted'/candidate.name)
            self.assertTrue((task/'release-diagnostics/image-inspection.json').is_file())
            self.assertTrue(list((task/'release-diagnostics').glob('*.manifest')))
            for line in (publish/'metadata/SHA256SUMS').read_text().splitlines():
                expected,name=line.split('  ',1)
                self.assertEqual(expected,ci.sha256(public/name))
            notes=(publish/'metadata/release-notes.md').read_text(encoding='utf-8')
            self.assertIn(ci.sha256(bundle),notes)
            self.assertIn(ci.sha256(candidate),notes)

    def test_repack_uses_original_source_snapshot_and_refuses_changed_image(self):
        with tempfile.TemporaryDirectory() as temp:
            task=Path(temp); device=load_device()
            source=task/Path(device['image']['path']).name
            source.write_bytes(image())
            source.with_name(source.name.removesuffix(device['image']['manifest_suffix'])+'.manifest').write_text('test - 1\n')
            inspection=task/'inspection.json'
            inspection.write_text(json.dumps({'checks':{'synthetic':True},'device':device['id'],'sha256':ci.sha256(source)}))
            manifest={'schema_version':1,'device':device['id'],'version':'v0.1.0-rc.1','source_commit':'a'*40}
            snapshot=task/'original-source'
            files={'scripts/flash.py':"print('original release tool')\n",
                   'docs/devices/xiaomi-4a-flashing.md':'# 刷机\n\n## 准备\n使用 alwayroute-v0.1.0-xiaomi-4a-gigabit-sysupgrade.bin\n',
                   'LICENSE.md':'Original scope\n','THIRD_PARTY_NOTICES.md':'Original sources\n',
                   'LICENSES/original.txt':'Original license text\n'}
            for name,content in files.items():
                path=snapshot/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(content,encoding='utf-8',newline='\n')
            with contextlib.redirect_stdout(io.StringIO()):
                ci.package_release(task,task/'release','v0.1.0-rc.1',device,source,inspection,manifest,source_root=snapshot)
            with zipfile.ZipFile(next((task/'release/public').glob('*.zip'))) as archive:
                self.assertEqual(archive.read('flash.py'),files['scripts/flash.py'].encode())
                self.assertIn('Original sources',archive.read('NOTICE.txt').decode())
                self.assertIn('v0.1.0-rc.1-xiaomi',archive.read('README.md').decode())
            source.write_bytes(source.read_bytes()+b'changed')
            with self.assertRaisesRegex(ValueError,'uninspected image'):
                ci.package_release(task,task/'refused','v0.1.0-rc.1',device,source,inspection,manifest,source_root=snapshot)
            self.assertFalse((task/'refused').exists())


if __name__ == '__main__':
    unittest.main()
