"""Flash safety checks use synthetic images and SSH substitutes only."""
import argparse
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import struct
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import zlib

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('flash', ROOT / 'scripts/flash.py')
flash = importlib.util.module_from_spec(spec)
spec.loader.exec_module(flash)


def image():
    payload = b'test-kernel'
    header = bytearray(struct.pack('>7I4B32s', 0x27051956, 0, 0, len(payload), 0, 0,
                                  zlib.crc32(payload), 5, 5, 2, 3, b'test'))
    struct.pack_into('>I', header, 4, zlib.crc32(header))
    squash = bytearray(128)
    squash[:4] = b'hsqs'
    struct.pack_into('<I', squash, 12, 524288)
    struct.pack_into('<H', squash, 20, 4)
    struct.pack_into('<HH', squash, 28, 4, 0)
    struct.pack_into('<Q', squash, 40, len(squash))
    return bytes(header) + payload + bytes(squash)


def probe(mode='openwrt', board=flash.BOARD, boot='00000000-0000-4000-8000-000000000001'):
    fields = {'uid': '0', 'boot': boot, 'cpu': 'system type: MediaTek MT7621 ver:1',
              'mtd': 'mtd0: 01000000 00010000 "ALL"\n'
                     'mtd1: 00030000 00010000 "Bootloader"\n'
                     'mtd2: 00010000 00010000 "Factory"\n'
                     'mtd4: 00d00000 00010000 "OS1"',
              'memory': 'MemAvailable: 60000 kB', 'space': 'Filesystem 1024-blocks Used Available Capacity Mounted\n'
              'tmpfs 62080 2080 60000 4% /tmp', 'board': board,
              'openwrt': 'DISTRIB_ID=OpenWrt' if mode == 'openwrt' else '',
              'stock': "HARDWARE='R4A'\nROM='2.28.62'" if mode == 'stock' else '',
              'bootwait': 'on', 'uart': '1', 'tools': '/usr/bin/md5sum\n/sbin/' + ('sysupgrade' if mode == 'openwrt' else 'mtd')}
    return ''.join('\n---'+k+'---\n'+v+'\n' for k,v in fields.items()).encode()


class FlashTests(unittest.TestCase):
    def bundle(self, directory, data=None):
        directory.mkdir()
        data = image() if data is None else data
        img = directory / 'alwayroute-v0.1.0-xiaomi-4a-gigabit-sysupgrade.bin'
        img.write_bytes(data)
        info = {'schema_version': 1, 'device': flash.DEVICE, 'source_commit': 'a'*40,
                'version': 'v0.1.0', 'image_bytes': len(data), 'image_sha256': flash.digest(data)}
        manifest = directory / 'build-manifest.json'
        manifest.write_text(json.dumps(info))
        (directory / 'SHA256SUMS').write_text(''.join(
            flash.digest(p.read_bytes())+'  '+p.name+'\n' for p in (img,manifest)))
        return img

    def args(self, img, root, mode='openwrt', apply=False):
        return argparse.Namespace(image=img, checksums=None, manifest=None, host='192.0.2.1',
                                  port=22, identity=None, known_hosts=None, mode=mode,
                                  apply=apply, backup_dir=root / 'private')

    def test_constants_follow_device_recipe(self):
        recipe = json.loads((ROOT / 'firmware/devices/xiaomi-4a-gigabit.json').read_text(encoding='utf-8'))
        self.assertEqual(flash.BOARD, recipe['board'])
        self.assertEqual(flash.MAX_IMAGE, recipe['image']['max_bytes'])
        self.assertEqual(flash.STOCK_OS1, recipe['image']['stock_install_max_bytes'])

    def test_bundle_rejects_corruption_before_ssh(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            img = self.bundle(root/'release')
            flash.load_bundle(img)
            img.write_bytes(img.read_bytes()+b'corrupt')
            with patch.object(flash, 'remote') as remote:
                with self.assertRaisesRegex(ValueError, 'checksum mismatch'):
                    flash.execute(self.args(img, root))
                remote.assert_not_called()

    def test_matching_checksum_does_not_bypass_image_crc(self):
        with tempfile.TemporaryDirectory() as temp:
            bad = bytearray(image()); bad[65] ^= 1
            img = self.bundle(Path(temp)/'release', bytes(bad))
            with self.assertRaisesRegex(ValueError, 'layout or CRC'):
                flash.load_bundle(img)

    def test_wrong_board_and_wrong_mode_are_refused(self):
        for value,mode in [(probe(board=flash.BOARD+'-v2'),'openwrt'), (probe(),'stock'), (probe('stock'),'openwrt')]:
            with self.assertRaises(ValueError):
                flash.parse_probe(value,mode,len(image()))

    def test_stock_version_partition_and_boot_flags_are_refused(self):
        original=probe('stock')
        flash.parse_probe(original,'stock',len(image()))
        for old,new in [(b'2.28.62',b'2.28.91'), (b'00d00000',b'00c00000'), (b'\non\n',b'\noff\n')]:
            with self.assertRaises(ValueError):
                flash.parse_probe(original.replace(old,new),'stock',len(image()))

    def test_default_only_probes_without_backup_upload_or_write(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); img=self.bundle(root/'release')
            with patch.object(flash,'remote',return_value=probe()) as remote, patch.object(flash,'backup') as backup:
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(flash.execute(self.args(img,root)),0)
                self.assertEqual(remote.call_count,1)
                backup.assert_not_called()
                self.assertFalse((root/'private').exists())

    def test_windows_acl_command_uses_current_sid_then_verifies(self):
        sid = 'S-1-5-21-100-200-300-400'
        for directory, suffix in ((False, ':F'), (True, ':(OI)(CI)F')):
            with self.subTest(directory=directory), \
                 patch.object(flash.subprocess, 'run', side_effect=[
                     subprocess.CompletedProcess([], 0, ('"host\\user","%s"' % sid).encode()),
                     subprocess.CompletedProcess([], 0, b'')]) as run, \
                 patch.object(flash, '_verify_windows_acl') as verify:
                path = Path('private-item')
                flash._apply_windows_acl(path, directory)
                self.assertEqual(run.call_args_list[1].args[0], [
                    'icacls', str(path), '/inheritance:r', '/grant:r', '*' + sid + suffix])
                verify.assert_called_once_with(path, sid, directory)

    def test_private_file_permission_failure_writes_no_secret_bytes(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'secret.bin'
            with patch.object(flash, 'private_permissions',
                              side_effect=ValueError('permission verification failed')):
                with self.assertRaisesRegex(ValueError, 'permission verification failed'):
                    flash.private_file(path, b'secret-device-backup')
            self.assertEqual(path.read_bytes(), b'')

    def test_backup_permission_failure_precedes_remote_read(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / 'private'
            with patch.object(flash, 'private_permissions',
                              side_effect=ValueError('permission verification failed')), \
                 patch.object(flash, 'remote') as remote:
                with self.assertRaisesRegex(ValueError, 'permission verification failed'):
                    flash.backup([], {'mode': 'openwrt'}, target)
                remote.assert_not_called()

    def test_private_directory_rejects_reparse_parent(self):
        with tempfile.TemporaryDirectory() as temp:
            unsafe = Path(temp) / 'junction'
            unsafe.mkdir()
            target = unsafe / 'private'
            with patch.object(flash, '_is_reparse_point',
                              side_effect=lambda path: path == unsafe):
                with self.assertRaisesRegex(ValueError, 'links or reparse points'):
                    flash.private_directory(target)
            self.assertFalse(target.exists())

    def test_python311_file_attributes_detect_reparse_points(self):
        class ReparsePath:
            def lstat(self):
                return type('Metadata', (), {'st_file_attributes': 0x400})()

            def is_symlink(self):
                return False

        self.assertTrue(flash._is_reparse_point(ReparsePath()))

    @unittest.skipUnless(os.name == 'nt', 'Windows DACL integration check')
    def test_windows_private_acl_round_trip(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = flash.private_directory(Path(temp) / 'private')
            path = directory / 'secret.bin'
            flash.private_file(path, b'secret')
            self.assertEqual(path.read_bytes(), b'secret')

    def apply_case(self, mode='openwrt', fail_test=False, changed=False):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); img=self.bundle(root/'release')
            commands=[]; probes=0
            def remote(ssh, command, data=None, timeout=60):
                nonlocal probes
                commands.append(command)
                if command=='sh -s':
                    probes+=1
                    return probe(mode,boot='00000000-0000-4000-8000-000000000002' if changed and probes>1 else '00000000-0000-4000-8000-000000000001')
                if command.startswith('md5sum '):return (flash.digest(img.read_bytes(),'md5')+'  staged.bin').encode()
                if command.startswith('sysupgrade -T ') and fail_test:raise RuntimeError('image test failed')
                return b''
            def backup(ssh,state,directory):directory.mkdir()
            with patch.object(flash,'remote',side_effect=remote), patch.object(flash,'backup',side_effect=backup), \
                 patch.object(flash, '_apply_windows_acl'), \
                 patch.object(flash.subprocess,'run',return_value=subprocess.CompletedProcess([],255,b'Rebooting')) as write:
                with contextlib.redirect_stdout(io.StringIO()):
                    if fail_test or changed:
                        with self.assertRaises((RuntimeError,ValueError)):
                            flash.execute(self.args(img,root,mode,True))
                        write.assert_not_called()
                        self.assertRegex(commands[-1], r'^rm -f /tmp/alwayroute-flash-[a-f0-9]+\.bin$')
                    else:
                        self.assertEqual(flash.execute(self.args(img,root,mode,True)),3)
                        self.assertEqual(write.call_count,1)
                        command=write.call_args.args[0][-1]
                        if mode=='stock':
                            self.assertRegex(command,r'^mtd -e OS1 -r write /tmp/alwayroute-flash-[a-f0-9]+\.bin OS1$')
                            self.assertNotIn('ALL',command)
                        else:
                            self.assertTrue(command.startswith('sysupgrade /tmp/'))
                            self.assertTrue(any(c.startswith('sysupgrade -T ') for c in commands))

    def test_upgrade_disconnect_never_retries(self):self.apply_case()
    def test_stock_only_writes_os1_once(self):self.apply_case('stock')
    def test_failed_sysupgrade_test_prevents_write(self):self.apply_case(fail_test=True)
    def test_changed_device_prevents_write(self):self.apply_case(changed=True)


if __name__ == '__main__':
    unittest.main()
