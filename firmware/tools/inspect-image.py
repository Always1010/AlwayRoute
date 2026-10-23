"""Read-only inspection of the single approved 4A evaluation image.

Run on Rock after make has produced its target image and native host tools.
This script never connects to or writes a router.
"""
import argparse
import hashlib
import json
import pathlib
import re
import struct
import subprocess
import tempfile
import zlib

work = pathlib.Path('/srv/alwayroute/openwrt-build')
source = work / 'source'
default_core_sha256 = 'f2abdeffaaec58568d7471e44e0fe0d9557eee6a3011ffc2c6f36fcaac396d76'


def sha256_arg(value):
    if not re.fullmatch(r'[0-9a-fA-F]{64}', value):
        raise argparse.ArgumentTypeError('SHA-256 must contain exactly 64 hexadecimal characters')
    return value.lower()


parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('image', type=pathlib.Path)
parser.add_argument('--profile', choices=('baseline', 'manager'), default='baseline')
parser.add_argument('--baseline-image', type=pathlib.Path, help='Required for manager: previously inspected baseline image')
parser.add_argument('--core-sha256', type=sha256_arg, default=default_core_sha256)
parser.add_argument('--output', type=pathlib.Path, default=work / 'image-inspection.json')
args = parser.parse_args()
if args.profile == 'manager' and args.baseline_image is None:
    parser.error('--profile manager requires --baseline-image')
image = args.image.resolve()
data = image.read_bytes()
expected_core_sha = args.core_sha256
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
if args.profile == 'manager':
    pinned = pathlib.Path('/srv/alwayroute/sources/sing-box-1.13.21')
    tags = 'with_quic,with_utls,with_clash_api,badlinkname,tfogo_checklinkname0'
    check('core_full_cli', build_info.get('cli_profile') == 'full' and build_info.get('entry_package') == './cmd/sing-box')
    check('core_full_registry', build_info.get('registry_profile') == 'upstream' and build_info.get('registry_patch_sha256') is None)
    check('core_pinned_source', build_info.get('source_sha256') == 'c994018d7c2a8fc9fcf6080e4b9cc4f2f915e755342238b77e46fc0806fe96db')
    check('core_registry_matches_pinned_source', build_info.get('registry_sha256') == hashlib.sha256((pinned/'include/registry.go').read_bytes()).hexdigest())
    check('core_original_feature_tags', build_info.get('tags') == tags)
    check('core_isolated_build_environment', build_info.get('build_environment') == {
        'GOFLAGS':'', 'GOENV':'off', 'GOWORK':'off', 'GOEXPERIMENT':'',
        'GOROOT':'/srv/alwayroute/toolchains/go1.27.3/go',
        'GOTOOLCHAIN':'local', 'GOPROXY':'off'})
    with tempfile.TemporaryDirectory(prefix='inspect-core-') as directory:
        elf = pathlib.Path(directory)/'sing-box'
        elf.write_bytes(core)
        embedded = tool('/srv/alwayroute/toolchains/go1.27.3/go/bin/go', 'version', '-m', str(elf)).decode()
    settings = {}
    for line in embedded.splitlines():
        fields = line.strip().split(None, 1)
        if len(fields) == 2 and fields[0] == 'build' and '=' in fields[1]:
            key, value = fields[1].split('=', 1)
            settings[key] = value.strip('"')
    check('core_embedded_target', all(settings.get(k) == v for k, v in {'GOOS':'linux','GOARCH':'mipsle','GOMIPS':'softfloat','CGO_ENABLED':'0'}.items()))
    check('core_embedded_tags', settings.get('-tags') == tags)
    check('core_embedded_full_entry', '\n\tpath\tgithub.com/sagernet/sing-box/cmd/sing-box\n' in embedded)
    # Go's embedded settings are not exhaustive: -overlay is not recorded there.
    check('core_no_explicit_overlay', not any(str(flag).startswith(('-overlay','-modfile')) for flag in build_info.get('command', [])))
startup = readfile('etc/uci-defaults/99-alwayroute-management')
check('management_defaults_match_reviewed_input', startup == (source / 'files/etc/uci-defaults/99-alwayroute-management').read_bytes())
key = readfile('etc/dropbear/authorized_keys')
check('public_key_matches', key == (source / 'files/etc/dropbear/authorized_keys').read_bytes())
check('only_ed25519_public_key_embedded', key.startswith(b'ssh-ed25519 ') and b'PRIVATE KEY' not in key and len(key.splitlines()) == 1)
listing = tool(str(unsquashfs), '-o', str(offset), '-ll', str(image)).decode(errors='replace')
listed_paths = {
    match.group(1).split(' -> ', 1)[0]
    for line in listing.splitlines()
    if (match := re.search(r'squashfs-root/(.*)$', line))
}
input_hashes = {}
executable_texts = []
executable_source_fragments = []
if args.profile == 'baseline':
    check('no_proxy_autostart', 'squashfs-root/etc/init.d/alwayroute' not in listing and 'squashfs-root/etc/init.d/sing-box' not in listing)
else:
    # Compare all owned payloads with reviewed package inputs. LuCI deliberately
    # minifies web assets, so replay its existing host tools before comparing.
    config = (source / '.config').read_text().splitlines()
    for package, directory, prefix in [
        ('alwayroute-forwarding', 'files', 'usr/libexec'),
        ('alwayroute-manager', 'files', ''),
        ('luci-app-alwayroute', 'root', ''),
        ('luci-app-alwayroute', 'htdocs', 'www'),
    ]:
        root = source / 'package' / package / directory
        for path in sorted(root.rglob('*')):
            if not path.is_file():
                continue
            target = '/'.join(part for part in (prefix, path.relative_to(root).as_posix()) if part)
            expected = path.read_bytes()
            input_sha = hashlib.sha256(expected).hexdigest()
            if directory == 'htdocs' and path.suffix == '.js' and 'CONFIG_LUCI_JSMIN=y' in config:
                result = subprocess.run([str(source / 'staging_dir/hostpkg/bin/jsmin')], input=expected, capture_output=True, timeout=120, check=True)
                expected = result.stdout
            elif directory == 'htdocs' and path.suffix == '.css' and 'CONFIG_LUCI_CSSTIDY=y' in config:
                with tempfile.TemporaryDirectory(prefix='alwayroute-inspect-', dir=work / 'tmp') as temporary:
                    output = pathlib.Path(temporary) / 'style.css'
                    tool(str(source / 'staging_dir/hostpkg/bin/csstidy'), str(path), '--template=highest', '--remove_last_semicolon=true', str(output))
                    expected = output.read_bytes()
            actual = readfile(target)
            check('manager_input_' + target, actual == expected)
            input_hashes[target] = {'input_sha256': input_sha, 'installed_sha256': hashlib.sha256(actual).hexdigest()}
    check('manager_no_embedded_user_state', not any(
        path == 'etc/config/alwayroute' or path == 'etc/init.d/sing-box'
        or path == 'etc/alwayroute' or path.startswith('etc/alwayroute/')
        or path == 'tmp/alwayroute' or path.startswith('tmp/alwayroute/')
        for path in listed_paths
    ))
    # The service is allowed to autostart only after a user enabled it and a
    # successful revision exists. A fresh image contains neither state file.
    store = readfile('usr/share/ucode/alwayroute/store.uc')
    check('manager_boot_requires_enabled_lastgood', b"read(DATA+'/service.json',{enabled:false})" in store and b"read(DATA+'/lastgood.json',null)" in store and b'if(!config.enabled || !good)return false;' in store)
    init = readfile('etc/init.d/alwayroute')
    check('manager_init_requires_runtime', b'[ -s /tmp/alwayroute/runtime.json ] || /usr/libexec/alwayroute-boot || return 0' in init)
    check('manager_boot_service_enabled', any(
        line.startswith('l') and line.endswith('squashfs-root/etc/rc.d/S95alwayroute -> ../init.d/alwayroute')
        for line in listing.splitlines()
    ))
    for line in listing.splitlines():
        match = re.search(r'squashfs-root/(.*)$', line)
        if not match or not line.startswith('-') or 'x' not in line.split()[0]:
            continue
        path = match.group(1)
        content = readfile(path)
        if b'\0' in content:
            continue
        try:
            content.decode('utf-8')
        except UnicodeDecodeError:
            continue
        executable_texts.append(path)
        first_line = content.split(b'\n', 1)[0]
        check('executable_text_lf_' + path, b'\r\n' not in content)
        if not first_line.startswith(b'#!') and path not in input_hashes:
            # Upstream shell fragments (for example /etc/profile.d/*.sh) can
            # carry execute bits although they are only sourced by a shell.
            executable_source_fragments.append(path)
            continue
        interpreter = first_line[2:].split()[0] if first_line.startswith(b'#!') and first_line[2:].strip() else b''
        check('executable_text_shebang_' + path, interpreter.startswith(b'/') and interpreter.decode().lstrip('/') in listed_paths)
check('no_embedded_ssh_host_keys', not any('squashfs-root/etc/dropbear/dropbear_' in line and '_host_key' in line for line in listing.splitlines()))
manifest = image.with_name(image.name.replace('-squashfs-sysupgrade.bin', '.manifest'))
packages = {}
for line in manifest.read_text().splitlines():
    name, version = line.split(' - ', 1)
    packages[name] = version
for name in ['alwayroute-core', 'kmod-mt7603', 'kmod-mt76x2', 'kmod-nft-tproxy', 'ip-full', 'luci-base', 'luci-mod-admin-full', 'uhttpd', 'dropbear', 'firewall4', 'odhcp6c', 'odhcpd-ipv6only']:
    check('package_' + name, name in packages)
expected_package_delta = None
if args.profile == 'manager':
    for name in ['alwayroute-forwarding', 'alwayroute-manager', 'luci-app-alwayroute']:
        check('package_' + name, name in packages)
    baseline_data = args.baseline_image.read_bytes()
    baseline_kernel_end = 64 + struct.unpack_from('>I', baseline_data, 12)[0]
    check('manager_kernel_payload_unchanged', data[64:kernel_end] == baseline_data[64:baseline_kernel_end])
    baseline_manifest = args.baseline_image.with_name(args.baseline_image.name.replace('-squashfs-sysupgrade.bin', '.manifest'))
    baseline_packages = dict(line.split(' - ', 1) for line in baseline_manifest.read_text().splitlines())
    manager_packages = {'alwayroute-forwarding', 'alwayroute-manager', 'luci-app-alwayroute'}
    added_packages = set(packages) - set(baseline_packages)
    expected_package_delta = {'added': sorted(manager_packages), 'removed': []}
    check('manager_only_three_added_packages', added_packages == manager_packages)
    check('manager_baseline_packages_unchanged', all(packages.get(name) == version for name, version in baseline_packages.items()))
check('no_ppp', 'ppp' not in packages and 'ppp-mod-pppoe' not in packages)
overlay_start = ((offset + used + 65535) // 65536) * 65536
report = {
    'image': str(image), 'profile': args.profile, 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest(),
    'expected': {
        'core_sha256': expected_core_sha,
        'ip_package': 'ip-full',
        'manager_package_delta': expected_package_delta,
    },
    'uimage_payload_end': kernel_end, 'squashfs_bytes_used': used,
    'squashfs_block_size': squashfs_block_size,
    'overlay_start_relative_firmware': overlay_start,
    'physical_firmware_bytes': 0xE80000,
    'raw_overlay_capacity_bytes_before_filesystem_overhead': 0xE80000 - overlay_start,
    'stock_OS1_remaining_after_image': 0xD00000 - len(data),
    'core_bytes': len(core), 'core_sha256': core_sha,
    'metadata': metadata, 'package_count': len(packages), 'checks': checks,
    'boot_verified': False, 'flashing_performed': False,
    'owned_payload_hashes': input_hashes,
    'executable_texts_checked': executable_texts,
    'upstream_executable_texts_without_shebang': executable_source_fragments,
}
out = args.output
out.write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps(report, indent=2))
