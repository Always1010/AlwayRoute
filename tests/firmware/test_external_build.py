"""Reject wrong selections and stale/shared input; no make or SDK installation."""
import importlib.util
from pathlib import Path
import shutil
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('external_build', ROOT / 'firmware/tools/build-external.py')
build = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build)


class ExternalBuild(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.tree = Path(self.temporary.name).resolve()
        (self.tree / 'include').mkdir()
        (self.tree / 'include/package.mk').write_text('# existing SDK fixture\n')
        self.config = ROOT / 'firmware/openwrt/external.config'
        (self.tree / '.config').write_bytes(self.config.read_bytes())
        stage = build.staging()
        for name in build.PACKAGES:
            directory = self.tree / 'package' / name
            directory.mkdir(parents=True, exist_ok=True)
            for filename in ('Makefile', 'payload.json'):
                shutil.copyfile(ROOT / 'firmware/openwrt' / name / filename, directory / filename)
            for entry in stage.payload(directory / 'payload.json')['files']:
                target = self.tree / 'package' / entry['source']
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(ROOT / 'firmware/openwrt' / entry['source'], target)
        helper = Path('alwayroute-external-manager/tools/stage-files.py')
        (self.tree / 'package' / helper).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / 'firmware/openwrt' / helper, self.tree / 'package' / helper)

    def test_pure_inputs_are_identified_without_core_or_rules(self):
        tree, identities = build.inputs(self.tree)
        self.assertEqual(tree, self.tree)
        self.assertEqual(set(identities), set(build.PACKAGES))
        self.assertFalse((tree / 'alwayroute-input').exists())
        self.assertFalse((tree / 'package/alwayroute-core').exists())

    def test_local_package_selection_or_stale_shared_source_is_refused(self):
        (self.tree / '.config').write_bytes(self.config.read_bytes() + b'\nCONFIG_PACKAGE_alwayroute-core=y\n')
        with self.assertRaisesRegex(ValueError, 'local-mode'):
            build.inputs(self.tree)
        (self.tree / '.config').write_bytes(self.config.read_bytes())
        source = self.tree / 'package/alwayroute-manager/files/usr/share/ucode/alwayroute/external.uc'
        source.write_text('stale copied source')
        with self.assertRaisesRegex(ValueError, 'Shared package source differs'):
            build.inputs(self.tree)


if __name__ == '__main__':
    unittest.main()
