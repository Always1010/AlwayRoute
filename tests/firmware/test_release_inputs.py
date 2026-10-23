"""Protect release input identity without compiling or connecting devices."""
import copy
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

TOOLS = Path(__file__).resolve().parents[2] / 'firmware/tools'
sys.path.insert(0, str(TOOLS))
from release_inputs import FIRMWARE, input_identity, load_release, sha256, validate_release_core
from target_profile import load_device

spec = importlib.util.spec_from_file_location('builder', TOOLS / 'build-core.py')
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


class ReleaseInputsTest(unittest.TestCase):
    def test_public_profile_and_tampering(self):
        device = load_device()
        recipe = load_release()
        with tempfile.TemporaryDirectory() as temporary:
            inputs = Path(temporary)
            (inputs / 'sing-box').write_bytes(b'test-core')
            flags = ['all=-l'] + [p + '=' for p in builder.HOT_PACKAGES]
            info = {'input_elf_sha256': sha256(inputs / 'sing-box'), 'go': '1.27.3',
                    'pgo_sha256': recipe['pgo']['sha256'], 'gcflags': flags,
                    'command': ['go', 'build', '-pgo', str((FIRMWARE / recipe['pgo']['path']).resolve()),
                                *['-gcflags=' + f for f in flags]],
                    'crypto_candidate': {'backend': 'mipsle-asm-r2'}}
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
                ('crypto_candidate', {'backend': 'poly1305-32'}, 'release_crypto_backend'),
            ]:
                wrong = copy.deepcopy(info)
                wrong[key] = value
                (inputs / 'build-info.json').write_text(json.dumps(wrong))
                with self.assertRaisesRegex(ValueError, failure):
                    verify(i=wrong)


if __name__ == '__main__':
    unittest.main()
