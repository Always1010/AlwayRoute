"""Protect release input identity without compiling or connecting devices."""
import copy
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

TOOLS = Path(__file__).resolve().parents[2] / 'firmware/tools'
sys.path.insert(0, str(TOOLS))
from release_inputs import FIRMWARE, input_identity, load_release, sha256, validate_release_core
from target_profile import load_device

spec = importlib.util.spec_from_file_location('builder', TOOLS / 'build-core.py')
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


class ReleaseInputsTest(unittest.TestCase):
    def test_release_inspector_accepts_standard_and_requires_explicit_experiments_outside_release(self):
        spec = importlib.util.spec_from_file_location('release_inspector', TOOLS / 'inspect-image.py')
        inspector = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(inspector)
        device = load_device()
        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary)
            image = work / ('missing' + device['image']['manifest_suffix'])
            base = ['--env', str(work / 'environment.json'), str(image)]
            release = ['--profile', 'release', '--release-manifest', str(work / 'release.json')]
            with patch.object(inspector, 'build_context', return_value={'openwrt_tree': work, 'build_root': work}):
                # Reaching the deliberately absent image proves the release
                # parser accepts the standard backend before any inspection IO.
                with self.assertRaises(FileNotFoundError) as failure:
                    inspector.main(base + release)
                self.assertEqual(Path(failure.exception.filename), image.resolve())
                for backend in device['allowed_crypto_backends']:
                    with self.subTest(backend=backend), contextlib.redirect_stderr(io.StringIO()) as output:
                        with self.assertRaises(SystemExit) as failure:
                            inspector.main(base + release + ['--experimental-crypto', backend])
                        self.assertEqual(failure.exception.code, 2)
                        self.assertIn('standard Go crypto', output.getvalue())
                    with self.assertRaises(FileNotFoundError):
                        inspector.main(base + ['--profile', 'manager', '--baseline-image', str(work / 'baseline.bin'),
                                               '--experimental-crypto', backend])

    def test_public_profile_and_tampering(self):
        device = load_device()
        recipe = load_release()
        self.assertEqual(recipe['crypto_backend'], 'standard-go')
        self.assertIn('openwrt/patches/011-sing-box-tproxy-close-failed-socket.patch', input_identity(device))
        self.assertNotIn('openwrt/patches/003-xcrypto-mipsle-assembly-experimental.patch', input_identity(device))
        with tempfile.TemporaryDirectory() as temporary:
            inputs = Path(temporary)
            (inputs / 'sing-box').write_bytes(b'test-core')
            flags = ['all=-l'] + [p + '=' for p in builder.HOT_PACKAGES]
            info = {'input_elf_sha256': sha256(inputs / 'sing-box'), 'go': '1.27.3',
                    'pgo_sha256': recipe['pgo']['sha256'], 'gcflags': flags,
                    'command': ['go', 'build', '-pgo', str((FIRMWARE / recipe['pgo']['path']).resolve()),
                                *['-gcflags=' + f for f in flags]],
                    'crypto_candidate': None,
                    'resource_fixes': {'patch_sha256': sha256(FIRMWARE / 'openwrt/patches/011-sing-box-tproxy-close-failed-socket.patch')}}
            (inputs / 'build-info.json').write_text(json.dumps(info))
            manifest = {'device': device['id'], 'inputs': input_identity(device),
                        'core_sha256': info['input_elf_sha256']}

            def check(name, ok):
                if not ok:
                    raise ValueError(name)

            def verify(i=info, m=manifest):
                validate_release_core(i, inputs, m, {}, device, check)

            verify()
            wrong = copy.deepcopy(manifest)
            wrong['inputs']['sources.lock.json'] = '0' * 64
            with self.assertRaisesRegex(ValueError, 'release_public_input_identity'):
                verify(m=wrong)
            wrong = copy.deepcopy(manifest)
            wrong['core_sha256'] = '0' * 64
            with self.assertRaisesRegex(ValueError, 'release_core_digest'):
                verify(m=wrong)
            for key, value, failure in [
                ('pgo_sha256', None, 'release_pgo_digest'),
                ('gcflags', [], 'release_compiler_profile'),
                ('resource_fixes', None, 'release_required_resource_fixes'),
                ('crypto_candidate', {'backend': 'mipsle-asm-r2'}, 'release_crypto_backend'),
                ('crypto_candidate', {}, 'release_crypto_backend'),
                ('command', info['command'] + ['-asmflags=golang.org/x/crypto/chacha20=-D GOMIPS_r2'], 'release_crypto_backend'),
                ('command', info['command'] + ['-modfile=/some/experimental.mod'], 'release_crypto_backend'),
            ]:
                wrong = copy.deepcopy(info)
                wrong[key] = value
                (inputs / 'build-info.json').write_text(json.dumps(wrong))
                with self.assertRaisesRegex(ValueError, failure):
                    verify(i=wrong)


if __name__ == '__main__':
    unittest.main()
