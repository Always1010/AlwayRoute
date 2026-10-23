"""Reject stale or tampered compiled routing payloads during image inspection."""
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

TOOLS = Path(__file__).resolve().parents[2] / 'firmware/tools'
sys.path.insert(0, str(TOOLS))
SPEC = importlib.util.spec_from_file_location('image_inspector', TOOLS / 'inspect-image.py')
inspector = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(inspector)


class RoutingPayload(unittest.TestCase):
    def inspect(self, tamper=None):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            license_data = b'Synthetic license'
            lock = {'ruleSets': [{'name': name, 'sha256': '0' * 64} for name in ['domestic-domain', 'domestic-ip']],
                    'ruleSetLicense': {'sha256': hashlib.sha256(license_data).hexdigest()}}
            lock_path = root / 'sources.lock.json'
            lock_path.write_text(json.dumps(lock))
            manifest = {'compilerVersion': '1.13.21', 'ipFamily': 'ipv4', 'storageCompression': 'zlib-stored',
                        'sourceLockSha256': hashlib.sha256(lock_path.read_bytes()).hexdigest(),
                        'license': lock['ruleSetLicense'], 'ruleSets': []}
            payload = {'LICENSE': license_data}
            for spec in lock['ruleSets']:
                data = ('Synthetic ' + spec['name']).encode()
                payload[spec['name'] + '.srs'] = data
                manifest['ruleSets'].append({**spec, 'file': spec['name'] + '.srs', 'binaryBytes': len(data),
                                            'binarySha256': hashlib.sha256(data).hexdigest()})
            payload['manifest.json'] = json.dumps(manifest).encode()
            for name, data in payload.items():
                (root / name).write_bytes(data)
            if tamper == 'binary':
                payload['domestic-ip.srs'] = b'Stale binary'
            if tamper == 'lock':
                lock_path.write_text(json.dumps({**lock, 'changed': True}))

            def check(name, condition):
                if not condition:
                    raise ValueError(name)

            return inspector.inspect_routing(lambda p: payload[Path(p).name], root, lock_path, check)

    def test_matches_reviewed_inputs(self):
        self.assertEqual(len(self.inspect()), 2)

    def test_stale_binary_rejected(self):
        with self.assertRaisesRegex(ValueError, 'routing_payload_domestic-ip'):
            self.inspect('binary')

    def test_changed_source_lock_rejected(self):
        with self.assertRaisesRegex(ValueError, 'routing_source_lock'):
            self.inspect('lock')


if __name__ == '__main__':
    unittest.main()
