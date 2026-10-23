"""Protect the existing 4A recipe and reject incompatible image/core targets.

Synthetic image headers and fake compiler calls only; no build or device IO.
"""
import copy
import contextlib
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zlib

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'firmware/tools'))
import target_profile as recipes
from build_context import build_context


def module(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'firmware/tools' / filename)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


inspector = module('image_inspector', 'inspect-image.py')
builder = module('core_builder', 'build-core.py')


def check(name, condition):
    if not condition:
        raise ValueError(name)


def settings(text):
    return dict(line.split('=', 1) if line.startswith('CONFIG_') else
                (line.split()[1], 'n') for line in text.splitlines()
                if line.startswith('CONFIG_') or line.startswith('# CONFIG_'))


def image():
    payload = b'kernel'
    squash = bytearray(96)
    squash[:4] = b'hsqs'
    struct.pack_into('<I', squash, 12, 524288)
    struct.pack_into('<H', squash, 20, 4)
    struct.pack_into('<HH', squash, 28, 4, 0)
    struct.pack_into('<Q', squash, 40, len(squash))
    header = bytearray(struct.pack('>7I4B32s', 0x27051956, 0, 0, len(payload), 0, 0,
                                  zlib.crc32(payload), 5, 5, 2, 0, b'test'))
    struct.pack_into('>I', header, 4, zlib.crc32(header))
    return header + payload + squash


class TargetTests(unittest.TestCase):
    def setUp(self):
        self.device = recipes.load_device()

    def test_existing_4a_configuration_and_limits_are_preserved(self):
        old = (ROOT / 'firmware/openwrt/evaluation.config').read_text()
        self.assertEqual(settings(recipes.seed_text(self.device)), settings(old))
        self.assertEqual(self.device['image']['max_bytes'], 13248 * 1024)
        self.assertEqual(self.device['image']['stock_install_max_bytes'], 0xD00000)
        self.assertEqual(self.device['image']['firmware_partition_bytes'], 0xE80000)
        self.assertEqual(recipes.architecture(self.device['architecture'])['go_env'],
                         {'GOOS': 'linux', 'GOARCH': 'mipsle', 'GOMIPS': 'softfloat', 'CGO_ENABLED': '0'})
        self.assertEqual(self.device['patches'], ['openwrt/patches/001-4a-evaluation-image-limit.patch'])

    def test_recipe_paths_and_unknown_formats_do_not_bypass_checks(self):
        for name in ('../xiaomi-4a-gigabit', 'C:/profile', '--device'):
            with self.assertRaises(ValueError):
                recipes.load_device(name)
        for value in ('../image', '/image', 'C:/image', 'bin/../image', 'bin\\image'):
            with self.assertRaises(ValueError):
                recipes.relative_path(value)
        device = copy.deepcopy(self.device)
        device['image']['format'] = 'fit'
        with self.assertRaisesRegex(ValueError, 'No verified image validator'):
            inspector.inspect_layout(image(), device, check)

    def test_layout_keeps_crc_size_and_truncation_guards(self):
        self.assertEqual(inspector.inspect_layout(image(), self.device, check)[0], 70)
        for data, expected in ((b'x', 'image_header_available'),
                               (image()[:-1], 'squashfs_header_available'),
                               (image() + bytes(13248 * 1024), 'bounded_by_evaluation_limit')):
            with self.assertRaisesRegex(ValueError, expected):
                inspector.inspect_layout(data, self.device, check)
        broken = image()
        broken[64] ^= 1
        with self.assertRaisesRegex(ValueError, 'kernel_data_crc'):
            inspector.inspect_layout(broken, self.device, check)

    def test_board_revision_and_core_architecture_must_match(self):
        metadata = {'supported_devices': [self.device['board']], 'version': {'target': 'ramips/mt7621'}}
        core = bytearray(20)
        core[:6] = b'\x7fELF\x01\x01'
        struct.pack_into('<H', core, 18, 8)
        inspector.inspect_identity(metadata, core, self.device, check)
        metadata['supported_devices'].append('xiaomi,mi-router-4a-gigabit-v2')
        with self.assertRaisesRegex(ValueError, 'metadata_excludes_v2'):
            inspector.inspect_identity(metadata, core, self.device, check)
        metadata['supported_devices'].pop()
        struct.pack_into('<H', core, 18, 183)
        with self.assertRaisesRegex(ValueError, 'core_elf_target'):
            inspector.inspect_identity(metadata, core, self.device, check)
        metadata['version']['target'] = 'mediatek/filogic'
        with self.assertRaisesRegex(ValueError, 'metadata_target'):
            inspector.inspect_identity(metadata, core, self.device, check)

    def test_mips_crypto_rejected_for_other_cpu_before_any_build(self):
        for arch in ('arm64', 'amd64'):
            with self.assertRaisesRegex(ValueError, 'compatible device'):
                recipes.validate_crypto_target(arch, 'mipsle-asm-r2', self.device)
        for backend in self.device['allowed_crypto_backends']:
            recipes.validate_crypto_target('mipsle-softfloat', backend, self.device)
        with self.assertRaises(ValueError):
            recipes.validate_crypto_target('mipsle-softfloat', 'mipsle-asm-r2')

    def test_host_paths_are_explicit_and_independent_of_device(self):
        with self.assertRaisesRegex(ValueError, 'Select --env'):
            build_context()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'env.json'
            path.write_text(json.dumps({'schema_version': 1, 'build': {'task_root': directory}}))
            self.assertEqual(build_context(path)['task_root'], Path(directory))
            path.write_text(json.dumps({'schema_version': 1, 'build': {}}))
            with self.assertRaisesRegex(ValueError, 'build.task_root'):
                build_context(path)

    def test_wrong_build_tree_and_cli_crypto_override_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)
            config = source / '.config'
            config.write_text(recipes.seed_text(self.device))
            recipes.require_build_target(source, self.device)
            config.write_text(config.read_text().replace('DEVICE_xiaomi_mi-router-4a-gigabit=y',
                                                         'DEVICE_other-router=y'))
            with self.assertRaisesRegex(ValueError, 'Resolved OpenWrt target'):
                recipes.require_build_target(source, self.device)
        with patch.object(builder, 'build_context', return_value={}), patch.object(builder.subprocess, 'run') as run:
            with self.assertRaisesRegex(ValueError, 'compatible device'):
                builder.main(['--env', 'unused.json', '--architecture', 'arm64',
                              '--experimental-crypto', 'mipsle-asm-r2', '--output', 'unused-core'])
            run.assert_not_called()

    def test_core_environment_does_not_inherit_host_cpu_options(self):
        context = {'jobs': 2, 'go_root': Path('/toolchains/go'), 'cache_root': Path('/cache')}
        with patch.dict(os.environ, {'GOARCH': 'amd64', 'GOMIPS': 'hardfloat',
                                     'GOARM64': 'v9.5', 'GOAMD64': 'v4', 'GOFLAGS': '-race'}):
            for name in recipes.ARCHITECTURES:
                arch = recipes.architecture(name)
                env = builder.core_environment(context, arch)
                self.assertEqual({k: env[k] for k in recipes.GO_ARCH_OPTIONS if k in env},
                                 {k: v for k, v in arch['go_env'].items() if k != 'CGO_ENABLED'})
                self.assertEqual(env['CGO_ENABLED'], '0')
                self.assertEqual(env['GOFLAGS'], '')
                self.assertEqual(env['GOPROXY'], 'off')

    def test_baseline_inspection_cli_uses_selected_recipe_without_private_defaults(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'source'
            source.mkdir()
            environment = root / 'env.json'
            environment.write_text(json.dumps({'schema_version': 1, 'build': {
                'task_root': directory, 'openwrt_tree': str(source)}}))
            candidate = root / Path(self.device['image']['path']).name
            candidate.write_bytes(image())
            core = bytearray(20)
            core[:6] = b'\x7fELF\x01\x01'
            struct.pack_into('<H', core, 18, 8)
            digest = hashlib.sha256(core).hexdigest()
            packages = ['alwayroute-core', 'kmod-nft-tproxy', 'ip-full', 'luci-base',
                        'luci-mod-admin-full', 'uhttpd', 'dropbear', 'firewall4', 'odhcp6c',
                        'odhcpd-ipv6only'] + self.device['required_packages']
            candidate.with_name(candidate.name.removesuffix(self.device['image']['manifest_suffix']) + '.manifest').write_text(
                ''.join(name + ' - 1\n' for name in packages))
            metadata = {'supported_devices': [self.device['board']],
                        'version': {'target': self.device['target'], 'version': '25.12.6'}}
            files = {'usr/bin/sing-box': bytes(core), 'usr/share/alwayroute/build-info.json':
                     json.dumps({'input_elf_sha256': digest}).encode()}

            def tools(argv, **kwargs):
                if '-cat' in argv:
                    output = files[argv[-1]]
                elif '-ll' in argv:
                    output = b''
                elif '-m' in argv:
                    output = b'\tdep\tgolang.org/x/crypto\tv0.48.0\th1:/VRzVqiRSggnhY7gNRxPauEQ5Drw9haKdM0jqfcCFts=\n'
                else:
                    output = json.dumps(metadata).encode()
                return subprocess.CompletedProcess(argv, 0, output)

            report = root / 'inspection.json'
            with patch.object(inspector.subprocess, 'run', side_effect=tools), contextlib.redirect_stdout(io.StringIO()):
                inspector.main(['--env', str(environment), '--device', self.device['id'],
                                '--core-sha256', digest, '--output', str(report), str(candidate)])
            result = json.loads(report.read_text())
            self.assertTrue(all(result['checks'].values()))
            self.assertEqual(result['device'], self.device['id'])
            self.assertIsNone(result['management_defaults_sha256'])
            self.assertFalse(result['boot_verified'])


if __name__ == '__main__':
    unittest.main()
