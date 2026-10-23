"""Guard source integrity and scope without networking, installing or building a core."""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
import zlib

SPEC = importlib.util.spec_from_file_location('routing_build', Path(__file__).resolve().parents[2] / 'scripts/build-routing.py')
routing = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(routing)


class RoutingInputs(unittest.TestCase):
    def source(self, **changes):
        return json.dumps({'version': 2, 'rules': [{'domain': ['api.synthetic.invalid'],
            'domain_suffix': ['synthetic.invalid'], 'domain_regex': [], **changes}]}).encode()

    def test_source_rejects_non_domain_fields_and_global_suffix(self):
        self.assertEqual(routing.validate_source('domestic-domain', self.source())['domain_suffix'], 1)
        for data in (self.source(ip_cidr=['192.0.2.0/24']), self.source(domain_suffix=['com'])):
            with self.assertRaises(ValueError):
                routing.validate_source('domestic-domain', data)

    def test_filesystem_container_preserves_exact_rule_payload(self):
        payload = b'synthetic rule payload' * 100
        original = b'SRS\x02' + zlib.compress(payload)
        packed = routing.filesystem_srs(original)
        self.assertEqual(packed[:4], original[:4])
        self.assertEqual(zlib.decompress(packed[4:]), payload)
        with self.assertRaises(ValueError):
            routing.filesystem_srs(b'invalid')

    def test_corrupt_cache_is_rejected_without_replacement(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory)
            expected = hashlib.sha256(b'locked input').hexdigest()
            (cache / expected).write_bytes(b'corrupt')
            with self.assertRaisesRegex(ValueError, 'SHA-256 mismatch'):
                routing.cached_input({'sha256': expected}, cache, False)
            self.assertEqual((cache / expected).read_bytes(), b'corrupt')

    def test_ip_source_rejects_private_or_overbroad_ranges(self):
        for network in ['0.0.0.0/0', '10.0.0.0/8', '192.0.2.0/24', '::/0', 'fc00::/7']:
            data = json.dumps({'version': 2, 'rules': [{'ip_cidr': [network]}]}).encode()
            with self.assertRaises(ValueError):
                routing.validate_source('domestic-ip', data)

    def test_ipv4_payload_filter_retains_the_original_source(self):
        data = json.dumps({'version': 2, 'rules': [{'ip_cidr': ['192.0.2.0/24', '2001:db8::/32']}]}).encode()
        selected = json.loads(routing.compile_source('domestic-ip', data, 'ipv4'))
        self.assertEqual(selected['rules'][0]['ip_cidr'], ['192.0.2.0/24'])
        self.assertEqual(json.loads(routing.compile_source('domestic-ip', data, 'dual')), json.loads(data))
        self.assertEqual(len(json.loads(data)['rules'][0]['ip_cidr']), 2)

    def test_missing_cache_does_not_download_implicitly(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, 'not cached'):
                routing.cached_input({'sha256': '0' * 64}, Path(directory), False)

    def test_existing_output_is_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            (output / 'sentinel').write_bytes(b'working data')
            with self.assertRaisesRegex(ValueError, 'never replaced'):
                routing.build({}, output / 'cache', output, output / 'absent-core')
            self.assertEqual((output / 'sentinel').read_bytes(), b'working data')


if __name__ == '__main__':
    unittest.main()
