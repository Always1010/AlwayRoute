"""First-boot policy rendering and explicit image selection; no host UCI calls."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'firmware/tools'))


def module(name, file):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'firmware/tools' / file)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


renderer = module('management_renderer', 'render-management-defaults.py')
inspector = module('image_inspector', 'inspect-image.py')


def check(name, condition):
    if not condition:
        raise ValueError(name)


class DeploymentTests(unittest.TestCase):
    def policy(self, name):
        return json.loads((ROOT / 'config/deployment' / (name + '.example.json')).read_text())

    def test_synthetic_policy_matches_reviewed_first_boot_fixture(self):
        old = (ROOT / 'tests/fixtures/management-defaults.sh').read_bytes()
        output = renderer.render(self.policy('isolated-lan')).encode()
        self.assertEqual(output, old)
        self.assertNotIn(b'\r', output)

    def test_preserve_policy_does_not_override_lan_or_ssh_port(self):
        output = renderer.render(self.policy('preserve-network'))
        self.assertNotIn('set network.', output)
        self.assertNotIn('commit network', output)
        self.assertNotIn(".Port=", output)
        self.assertIn('[ -e "$MARKER" ] && exit 0', output)
        self.assertIn("PasswordAuth='off'", output)
        self.assertIn("127.0.0.1:80", output)

    def test_invalid_or_injectable_policy_is_rejected(self):
        for mutation in (lambda p: p.update(command='touch bad'),
                         lambda p: p['ssh'].update(port=True),
                         lambda p: p['ssh'].update(port=65536),
                         lambda p: p['ssh'].update(interface="lan'; reboot"),
                         lambda p: p['lan'].update(address="192.0.2.1'; reboot"),
                         lambda p: p['lan'].update(address='192.0.2.0'),
                         lambda p: p['lan'].update(netmask='255.0.255.0')):
            policy = self.policy('isolated-lan')
            mutation(policy)
            with self.assertRaises(ValueError):
                renderer.render(policy)

    def test_renderer_refuses_to_overwrite_reviewed_output(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'defaults'
            argv = ['--policy', str(ROOT / 'config/deployment/isolated-lan.example.json'),
                    '--output', str(output)]
            renderer.main(argv)
            before = output.read_bytes()
            with self.assertRaises(FileExistsError):
                renderer.main(argv)
            self.assertEqual(output.read_bytes(), before)

    def test_image_policy_requires_explicit_selection_and_three_way_match(self):
        target = 'etc/uci-defaults/99-alwayroute-management'
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)
            path = source / 'files' / target
            path.parent.mkdir(parents=True)
            path.write_bytes(b'reviewed policy')
            key = source / 'files/etc/dropbear/authorized_keys'
            key.parent.mkdir(parents=True)
            key.write_bytes(b'ssh-ed25519 synthetic-key test\n')
            readfile = lambda name: (source / 'files' / name).read_bytes()
            self.assertIsNone(inspector.inspect_management(readfile, set(), source, None, check))
            with self.assertRaisesRegex(ValueError, 'no_unselected_management_defaults'):
                inspector.inspect_management(readfile, {target}, source, None, check)
            reviewed = source / 'reviewed'
            reviewed.write_bytes(path.read_bytes())
            self.assertIsNotNone(inspector.inspect_management(readfile, {target}, source, reviewed, check))
            path.write_bytes(b'unreviewed tree edit')
            with self.assertRaisesRegex(ValueError, 'management_defaults_match_reviewed_input'):
                inspector.inspect_management(readfile, {target}, source, reviewed, check)


if __name__ == '__main__':
    unittest.main()
