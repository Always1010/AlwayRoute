"""Read-only inspection of the single approved 4A evaluation image.

Run on Rock after make has produced its target image and native host tools.
This script never connects to or writes a router.
"""
import hashlib
import json
import pathlib
import struct
import subprocess
import sys
import zlib

work = pathlib.Path('/srv/alwayroute/openwrt-build')
source = work / 'source'
image = pathlib.Path(sys.argv[1]).resolve()
data = image.read_bytes()
expected_core_sha = 'f2abdeffaaec58568d7471e44e0fe0d9557eee6a3011ffc2c6f36fcaac396d76'
checks = {}


def check(name, condition):
    checks[name] = bool(condition)
    if not condition:
        raise ValueError('Image inspection failed: ' + name)


def tool(*args):
    r = subprocess.run(args, capture_output=True, timeout=120)
    if r.returncode:
        raise RuntimeError('Image tool failed: ' + str(args[0]))
    return r.stdout


check('bounded_by_evaluation_limit', len(data) <= 13248 * 1024)
check('fits_stock_OS1', len(data) <= 0xD00000)
h = struct.unpack('>7I4B32s', data[:64])
check('uimage_magic', h[0] == 0x27051956)
header = bytearray(data[:64])
header[4:8] = bytes(4)
check('uimage_header_crc', zlib.crc32(header) & 0xFFFFFFFF == h[1])
kernel_end = 64 + h[3]
check('kernel_payload_bounds', 64 < kernel_end < len(data))
check('kernel_data_crc', zlib.crc32(data[64:kernel_end]) & 0xFFFFFFFF == h[6])
check('linux_mips_kernel', h[7:10] == (5, 5, 2))
# This target appends SquashFS immediately after its uImage loader payload.
offset = kernel_end
check('squashfs_at_kernel_end', data[offset:offset+4] == b'hsqs')
check('squashfs_v4', struct.unpack_from('<HH', data, offset + 28) == (4, 0))
used = struct.unpack_from('<Q', data, offset + 40)[0]
check('squashfs_bounds', offset + used <= len(data))
check('squashfs_xz', struct.unpack_from('<H', data, offset + 20)[0] == 4)
squashfs_block_size = struct.unpack_from('<I', data, offset + 12)[0]
check('squashfs_512k_blocks', squashfs_block_size == 524288)
fwtool = source / 'staging_dir/host/bin/fwtool'
metadata = json.loads(tool(str(fwtool), '-i', '/dev/stdout', str(image)))
devices = metadata.get('new_supported_devices', metadata.get('supported_devices', []))
check('metadata_device', 'xiaomi,mi-router-4a-gigabit' in devices)
check('metadata_excludes_v2', 'xiaomi,mi-router-4a-gigabit-v2' not in devices)
check('metadata_target', metadata['version']['target'] == 'ramips/mt7621')
check('metadata_version', metadata['version']['version'] == '25.12.6')
unsquashfs = source / 'staging_dir/host/bin/unsquashfs4'


def readfile(path):
    return tool(str(unsquashfs), '-o', str(offset), '-cat', str(image), path)


core = readfile('usr/bin/sing-box')
core_sha = hashlib.sha256(core).hexdigest()
check('core_elf_mipsle', core[:6] == b'\x7fELF\x01\x01' and struct.unpack_from('<H', core, 18)[0] == 8)
# Packaging may strip the ELF again; distinguish a changed payload explicitly.
check('core_matches_tested_payload', core_sha == expected_core_sha)
build_info = json.loads(readfile('usr/share/alwayroute/build-info.json'))
check('core_provenance', build_info['input_elf_sha256'] == expected_core_sha)
startup = readfile('etc/uci-defaults/99-alwayroute-management')
check('management_defaults_match_reviewed_input', startup == (source / 'files/etc/uci-defaults/99-alwayroute-management').read_bytes())
key = readfile('etc/dropbear/authorized_keys')
check('public_key_matches', key == (source / 'files/etc/dropbear/authorized_keys').read_bytes())
check('only_ed25519_public_key_embedded', key.startswith(b'ssh-ed25519 ') and b'PRIVATE KEY' not in key and len(key.splitlines()) == 1)
listing = tool(str(unsquashfs), '-o', str(offset), '-ll', str(image)).decode(errors='replace')
check('no_proxy_autostart', 'squashfs-root/etc/init.d/alwayroute' not in listing and 'squashfs-root/etc/init.d/sing-box' not in listing)
check('no_embedded_ssh_host_keys', not any('squashfs-root/etc/dropbear/dropbear_' in line and '_host_key' in line for line in listing.splitlines()))
manifest = image.with_name(image.name.replace('-squashfs-sysupgrade.bin', '.manifest'))
packages = {}
for line in manifest.read_text().splitlines():
    name, version = line.split(' - ', 1)
    packages[name] = version
for name in ['alwayroute-core', 'kmod-mt7603', 'kmod-mt76x2', 'kmod-nft-tproxy', 'ip-full', 'luci-base', 'luci-mod-admin-full', 'uhttpd', 'dropbear', 'firewall4', 'odhcp6c', 'odhcpd-ipv6only']:
    check('package_' + name, name in packages)
check('no_ppp', 'ppp' not in packages and 'ppp-mod-pppoe' not in packages)
overlay_start = ((offset + used + 65535) // 65536) * 65536
report = {
    'image': str(image), 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest(),
    'uimage_payload_end': kernel_end, 'squashfs_bytes_used': used,
    'squashfs_block_size': squashfs_block_size,
    'overlay_start_relative_firmware': overlay_start,
    'physical_firmware_bytes': 0xE80000,
    'raw_overlay_capacity_bytes_before_filesystem_overhead': 0xE80000 - overlay_start,
    'stock_OS1_remaining_after_image': 0xD00000 - len(data),
    'core_bytes': len(core), 'core_sha256': core_sha,
    'metadata': metadata, 'package_count': len(packages), 'checks': checks,
    'boot_verified': False, 'flashing_performed': False,
}
out = work / 'image-inspection.json'
out.write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps(report, indent=2))
