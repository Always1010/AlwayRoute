"""Flash a checked AlwayRoute release on Xiaomi 4A Gigabit v1 using existing SSH.

Default: verify local release files and read device identity only. --apply also
backs up privately, stages the image, preflights and submits ONE write command.
No package installation, SSH configuration changes, unlocking or network edits.
"""
import argparse
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import re
import secrets
import struct
import subprocess
import sys
import tarfile
import zlib

DEVICE = 'xiaomi-4a-gigabit'
BOARD = 'xiaomi,mi-router-4a-gigabit'
MAX_IMAGE = 13565952
STOCK_OS1 = 13631488
FLASH_BYTES = 16777216
PROBE = r'''set -eu
printf '\n---uid---\n'; id -u
printf '\n---boot---\n'; cat /proc/sys/kernel/random/boot_id
printf '\n---cpu---\n'; cat /proc/cpuinfo
printf '\n---mtd---\n'; cat /proc/mtd
printf '\n---memory---\n'; cat /proc/meminfo
printf '\n---space---\n'; df -Pk /tmp
printf '\n---openwrt---\n'
if [ -f /etc/openwrt_release ]; then cat /etc/openwrt_release; fi
printf '\n---board---\n'
if [ -f /tmp/sysinfo/board_name ]; then cat /tmp/sysinfo/board_name; fi
printf '\n---stock---\n'
if [ -f /etc/xiaoqiang_version ]; then cat /etc/xiaoqiang_version; fi
printf '\n---bootwait---\n'
if command -v nvram >/dev/null 2>&1; then nvram get boot_wait; fi
printf '\n---uart---\n'
if command -v nvram >/dev/null 2>&1; then nvram get uart_en; fi
printf '\n---tools---\n'
command -v md5sum
if [ -f /etc/openwrt_release ]; then command -v sysupgrade; else command -v mtd; fi
'''


def digest(data, algorithm='sha256'):
    return hashlib.new(algorithm, data).hexdigest()


def load_bundle(image, checksums=None, manifest=None):
    image = Path(image)
    if not 160 <= image.stat().st_size <= MAX_IMAGE:
        raise ValueError('Image is outside the reviewed 4A size limit')
    checksums = Path(checksums) if checksums else image.parent / 'SHA256SUMS'
    manifest = Path(manifest) if manifest else image.parent / 'build-manifest.json'
    sums = {}
    for line in checksums.read_text(encoding='utf-8').splitlines():
        match = re.fullmatch(r'([0-9a-f]{64}) [ *]([^/\\\r\n]+)', line)
        if not match or match[2] in sums:
            raise ValueError('Invalid or duplicate SHA256SUMS entry')
        sums[match[2]] = match[1]
    data, manifest_data = image.read_bytes(), manifest.read_bytes()
    if digest(data) != sums.get(image.name) or digest(manifest_data) != sums.get(manifest.name):
        raise ValueError('Image or build manifest checksum mismatch')
    info = json.loads(manifest_data)
    if (info.get('schema_version') != 1 or info.get('device') != DEVICE
            or info.get('image_sha256') != digest(data) or info.get('image_bytes') != len(data)):
        raise ValueError('Release manifest does not identify this 4A image')
    if not re.fullmatch(r'[0-9a-f]{40}', info.get('source_commit', '')):
        raise ValueError('Release manifest has no source commit')
    # Reject non-uImage, corrupt images and wrong layouts before any SSH access.
    if not 160 <= len(data) <= MAX_IMAGE:
        raise ValueError('Image is outside the reviewed 4A size limit')
    header = struct.unpack('>7I4B32s', data[:64])
    crc_header = bytearray(data[:64]); crc_header[4:8] = bytes(4)
    end = 64 + header[3]
    if (header[0] != 0x27051956 or header[7:10] != (5, 5, 2)
            or zlib.crc32(crc_header) & 0xffffffff != header[1]
            or not 64 < end <= len(data) - 96
            or zlib.crc32(data[64:end]) & 0xffffffff != header[6]
            or data[end:end+4] != b'hsqs'
            or struct.unpack_from('<HH', data, end+28) != (4, 0)
            or struct.unpack_from('<H', data, end+20)[0] != 4
            or struct.unpack_from('<I', data, end+12)[0] != 524288
            or end + struct.unpack_from('<Q', data, end+40)[0] > len(data)):
        raise ValueError('Invalid 4A uImage/SquashFS layout or CRC')
    return data, info


def parse_probe(data, mode, image_bytes):
    text = data.decode('utf-8', errors='strict')
    parts = re.split(r'\n---([a-z]+)---\n', text)
    fields = dict(zip(parts[1::2], (p.strip() for p in parts[2::2])))
    if fields.get('uid') != '0' or not re.fullmatch(r'[0-9a-f-]{36}', fields.get('boot', '')):
        raise ValueError('Root SSH and a readable boot ID are required')
    if 'MT7621' not in fields.get('cpu', ''):
        raise ValueError('CPU is not the reviewed MT7621 target')
    partitions = {}
    for index, size, erase, name in re.findall(r'^mtd(\d+): ([0-9a-f]+) ([0-9a-f]+) "([A-Za-z0-9_-]+)"$', fields.get('mtd', ''), re.M):
        if name in partitions:
            raise ValueError('Duplicate MTD partition identity')
        partitions[name] = {'index': int(index), 'bytes': int(size, 16), 'erase': int(erase, 16)}
    if mode == 'stock':
        stock = fields.get('stock', '')
        if fields.get('openwrt') or not re.search(r"^HARDWARE=['\"]?R4A['\"]?\s*$", stock, re.M):
            raise ValueError('Stock mode requires confirmed R4A vendor identity')
        if not re.search(r"^ROM=['\"]?2\.28\.62['\"]?\s*$", stock, re.M):
            raise ValueError('Only the recorded stock 2.28.62 entry is supported; do not guess another version')
        if (partitions.get('OS1', {}).get('bytes') != STOCK_OS1
                or partitions.get('ALL', {}).get('bytes') != FLASH_BYTES
                or partitions.get('OS1', {}).get('erase') != 65536
                or not {'Bootloader', 'Factory'} <= partitions.keys()
                or any(not 0 < p['bytes'] <= FLASH_BYTES for p in partitions.values())):
            raise ValueError('Stock flash/OS1 layout does not match the verified device')
        if fields.get('bootwait') != 'on' or fields.get('uart') != '1':
            raise ValueError('Recorded recovery boot flags are missing; prepare them before first flash')
    elif not fields.get('openwrt') or fields.get('board') != BOARD:
        raise ValueError('OpenWrt mode requires the exact Gigabit v1 board; V2/other devices are refused')
    if 'md5sum' not in fields.get('tools', '') or (('sysupgrade' if mode == 'openwrt' else 'mtd') not in fields.get('tools', '')):
        raise ValueError('Required device tools are missing')
    memory = {k: int(v)*1024 for k,v in re.findall(r'^(\w+):\s+(\d+) kB$', fields.get('memory', ''), re.M)}
    available = memory.get('MemAvailable', sum(memory.get(k, 0) for k in ('MemFree', 'Buffers', 'Cached')))
    rows = fields.get('space', '').splitlines()
    try:
        free = int(rows[-1].split()[-3]) * 1024
    except (IndexError, ValueError):
        raise ValueError('Cannot determine /tmp free space') from None
    if min(available, free) < image_bytes + 8*1024**2:
        raise ValueError('Insufficient RAM or /tmp space; stop active proxy jobs and check again')
    return {'mode': mode, 'board': BOARD if mode == 'openwrt' else 'R4A/2.28.62',
            'boot_id': fields['boot'], 'partitions': partitions, 'available_bytes': available,
            'tmp_free_bytes': free}


def ssh_command(args):
    if not re.fullmatch(r'(?:root@)?[A-Za-z0-9_][A-Za-z0-9_.-]*', args.host):
        raise ValueError('Use a root SSH alias, IPv4 address or root@host without options')
    host = args.host if args.host.startswith('root@') else 'root@' + args.host
    command = ['ssh', '-o', 'StrictHostKeyChecking=yes', '-o', 'ConnectTimeout=10', '-p', str(args.port)]
    if args.identity:
        command += ['-i', str(args.identity)]
    if args.known_hosts:
        command += ['-o', 'UserKnownHostsFile=' + str(args.known_hosts)]
    return command + [host]


def remote(ssh, command, data=None, timeout=60):
    result = subprocess.run(ssh + [command], input=data, stdout=subprocess.PIPE, timeout=timeout)
    if result.returncode:
        raise RuntimeError('SSH operation failed before flashing (exit %s)' % result.returncode)
    return result.stdout


def private_file(path, data):
    with path.open('xb') as out:
        os.chmod(path, 0o600)
        out.write(data)


def backup(ssh, state, directory):
    directory.mkdir(mode=0o700, parents=True, exist_ok=False)
    records = {}
    if state['mode'] == 'stock':
        # Reads only. ALL is an external backup, never a flash destination.
        for name, partition in state['partitions'].items():
            source = '/dev/mtd' + str(partition['index'])
            data = remote(ssh, 'cat ' + source, timeout=120)
            actual = remote(ssh, 'md5sum ' + source, timeout=120).decode().split()[0]
            if len(data) != partition['bytes'] or digest(data, 'md5') != actual:
                raise ValueError('Stock partition backup size/hash changed: ' + name)
            filename = name + '.bin'
            private_file(directory / filename, data)
            records[filename] = {'bytes': len(data), 'sha256': digest(data)}
    else:
        data = remote(ssh, 'sysupgrade -b -', timeout=120)
        # Validate the archive without extracting keys/configuration to stdout.
        if not data.startswith(b'\x1f\x8b') or len(data) > 16*1024**2:
            raise ValueError('Invalid or oversized sysupgrade configuration backup')
        with gzip.GzipFile(fileobj=io.BytesIO(data)) as stream:
            unpacked = stream.read(32*1024**2 + 1)
        if len(unpacked) > 32*1024**2:
            raise ValueError('Expanded configuration backup exceeds limit')
        with tarfile.open(fileobj=io.BytesIO(unpacked), mode='r:') as archive:
            members = archive.getmembers()
            if (not members or not any(m.name.lstrip('./') == 'etc/config/network' for m in members)
                    or any(m.name.startswith('/') or '..' in Path(m.name).parts for m in members)):
                raise ValueError('Configuration backup is incomplete or has unsafe paths')
        private_file(directory / 'sysupgrade-config.tar.gz', data)
        records['sysupgrade-config.tar.gz'] = {'bytes': len(data), 'sha256': digest(data)}
    private_file(directory / 'backup-manifest.json', (json.dumps(
        {'device': DEVICE, 'before': state, 'files': records}, indent=2)+'\n').encode())


def execute(args):
    data, manifest = load_bundle(args.image, args.checksums, args.manifest)
    ssh = ssh_command(args)
    state = parse_probe(remote(ssh, 'sh -s', PROBE.encode()), args.mode, len(data))
    print(json.dumps({'apply': args.apply, 'device': DEVICE, 'mode': args.mode,
                      'image_sha256': digest(data), 'image_bytes': len(data),
                      'version': manifest.get('version'), 'identity': state['board'],
                      'write_target': 'OS1' if args.mode == 'stock' else 'sysupgrade (keep config)'}, indent=2))
    if not args.apply:
        print('Preflight passed. No files uploaded, backups created or flash writes performed.')
        return 0
    if args.backup_dir is None:
        raise ValueError('--apply requires a fresh --backup-dir outside the downloaded release folder')
    directory = args.backup_dir.resolve()
    if directory.is_relative_to(args.image.resolve().parent):
        raise ValueError('Keep private backups outside the release folder')
    backup(ssh, state, directory)
    target = '/tmp/alwayroute-flash-' + secrets.token_hex(8) + '.bin'
    remote(ssh, 'umask 077; set -C; cat > ' + target, data, timeout=120)
    transferred = remote(ssh, 'md5sum ' + target).decode().split()[0]
    if transferred != digest(data, 'md5'):
        raise ValueError('Staged image transfer checksum mismatch')
    current = parse_probe(remote(ssh, 'sh -s', PROBE.encode()), args.mode, 0)
    if current['boot_id'] != state['boot_id'] or current['partitions'] != state['partitions']:
        raise ValueError('Device changed after backup; no flash command submitted')
    if args.mode == 'openwrt':
        remote(ssh, 'sysupgrade -T ' + target)
    # This is the only write submission. Disconnect/timeout NEVER triggers a retry.
    command = 'mtd -e OS1 -r write ' + target + ' OS1' if args.mode == 'stock' else 'sysupgrade ' + target
    print('Backup verified. Submitting one flash command; keep power connected.', flush=True)
    try:
        result = subprocess.run(ssh + [command], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=300)
        private_file(directory / 'flash-output.txt', result.stdout)
    except subprocess.TimeoutExpired as error:
        private_file(directory / 'flash-output.txt', error.stdout or b'')
        print('Flash command was submitted; completion is unknown after timeout. Do not repeat it. Check the reboot and new system manually.')
        return 3
    if result.returncode:
        print('Flash command was submitted; SSH exit %s. Do not repeat it. Inspect private flash-output.txt and confirm the reboot/new system.' % result.returncode)
        return 3
    print('Flash command finished. Confirm the new system after reboot; runtime acceptance is still pending.')
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image', type=Path, required=True)
    parser.add_argument('--host', required=True, help='Router address or existing SSH alias; root user only')
    parser.add_argument('--port', type=int, default=22)
    parser.add_argument('--identity', type=Path)
    parser.add_argument('--known-hosts', type=Path)
    parser.add_argument('--mode', choices=('stock', 'openwrt'), required=True)
    parser.add_argument('--checksums', type=Path)
    parser.add_argument('--manifest', type=Path)
    parser.add_argument('--backup-dir', type=Path)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args(argv)
    if not 1 <= args.port <= 65535:
        parser.error('SSH port must be between 1 and 65535')
    return execute(args)


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError, tarfile.TarError) as error:
        raise SystemExit(str(error)) from error
