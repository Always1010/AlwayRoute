"""Read-only inspection using a selected device recipe and supported image layout.

Run on the build host after make produced its target image and native host tools.
This script never connects to or writes a router.
"""
import argparse
import base64
import hashlib
import importlib.util
import json
import pathlib
import re
import struct
import subprocess
import tempfile
import zlib

from build_context import build_context
from target_profile import (DEFAULT_DEVICE, architecture, load_device, require_image_validator,
                            validate_crypto_target)


default_core_sha256 = 'f2abdeffaaec58568d7471e44e0fe0d9557eee6a3011ffc2c6f36fcaac396d76'


def sha256_arg(value):
    if not re.fullmatch(r'[0-9a-fA-F]{64}', value):
        raise argparse.ArgumentTypeError('SHA-256 must contain exactly 64 hexadecimal characters')
    return value.lower()


def validate_crypto_provenance(build_info, embedded, core, backend, pinned, check, *,
                               module_root=None, go_root=None):
    """Bind candidate inputs to embedded dependency data and actual instructions."""
    command = build_info.get('command', [])
    overlay_flags = [str(flag) for flag in command if str(flag).startswith(('-overlay', '-modfile'))]
    candidate = build_info.get('crypto_candidate')
    dependencies, current = [], None
    settings = {}
    for line in embedded.splitlines():
        fields = line.strip().split('\t')
        if fields[0] == 'dep':
            current = {'path': fields[1], 'version': fields[2],
                       'checksum': fields[3] if len(fields) > 3 else '', 'replacement': None}
            dependencies.append(current)
        elif fields[0] == '=>' and current is not None:
            current['replacement'] = fields[1:]
        elif fields[0] == 'build' and len(fields) == 2 and '=' in fields[1]:
            key, value = fields[1].split('=', 1)
            settings[key] = json.loads(value) if value.startswith('"') else value
    crypto_deps = [dep for dep in dependencies if dep['path'] == 'golang.org/x/crypto']
    check('core_crypto_embedded_dependency', len(crypto_deps) == 1 and crypto_deps[0]['version'] == 'v0.48.0')
    dependency = crypto_deps[0]
    checksum = 'h1:/VRzVqiRSggnhY7gNRxPauEQ5Drw9haKdM0jqfcCFts='
    if not backend:
        check('core_no_explicit_overlay', not overlay_flags and not candidate)
        check('core_crypto_standard_dependency', dependency['replacement'] is None and dependency['checksum'] == checksum)
        check('core_crypto_standard_assembler', '-asmflags' not in settings
              and not any(str(flag).startswith('-asmflags') for flag in command))
        return

    check('core_explicit_crypto_candidate', isinstance(candidate, dict) and candidate.get('backend') == backend
          and candidate.get('experimental') is True and candidate.get('upstream_approved') is False)
    legacy = backend == 'poly1305-32'
    helper_path = pathlib.Path(__file__).with_name('poly1305-32bit-overlay.py' if legacy else 'crypto-assembly-overlay.py')
    spec = importlib.util.spec_from_file_location('crypto_candidate', helper_path)
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    manifest = candidate['manifest']
    check('core_crypto_pinned_patch', manifest.get('patch_sha256') == helper.PATCH_SHA256)
    check('core_crypto_pinned_inputs', manifest.get('input_sha256') == helper.INPUT_SHA256
          and manifest.get('module_go_mod_sha256') == helper.MODULE_SHA256)
    expected_asmflags = [p + '=-D GOMIPS_r2' for p in ('golang.org/x/crypto/chacha20',
                         'vendor/golang.org/x/crypto/chacha20')] if backend == 'mipsle-asm-r2' else []
    check('core_crypto_asm_scope', candidate.get('asmflags') == expected_asmflags
          and [s for s in command if str(s).startswith('-asmflags')] == ['-asmflags=' + s for s in expected_asmflags])
    # Go 1.27 records only the last repeated per-package flag in BuildInfo.
    check('core_crypto_embedded_assembler', settings.get('-asmflags') == (expected_asmflags[-1] if expected_asmflags else None))
    check('core_crypto_overlay_arguments', len(overlay_flags) == 2 and overlay_flags[0].startswith('-overlay=')
          and overlay_flags[1].startswith('-modfile='))
    overlay_path = pathlib.Path(overlay_flags[0].split('=', 1)[1])
    modfile = pathlib.Path(overlay_flags[1].split('=', 1)[1])
    check('core_crypto_build_inputs_available', overlay_path.is_absolute() and modfile.is_absolute()
          and overlay_path.is_file() and modfile.is_file())
    check('core_crypto_overlay_digest', hashlib.sha256(overlay_path.read_bytes()).hexdigest() == candidate.get('overlay_sha256'))
    check('core_crypto_modfile_digest', hashlib.sha256(modfile.read_bytes()).hexdigest() == candidate.get('modfile_sha256'))
    original_stage = overlay_path.parent
    check('core_crypto_embedded_replace', dependency['replacement'] == [str(original_stage / 'module'), '(devel)'])

    # Hash the entire unmodified snapshot using Go dirhash.Hash1, not just the
    # handful of patched files. Added, missing or changed AEAD files must fail.
    module = original_stage / 'module'
    paths = list(module.rglob('*')) if module.is_dir() else []
    check('core_crypto_snapshot_regular_files', module.is_dir() and not module.is_symlink()
          and all(not p.is_symlink() and (p.is_file() or p.is_dir()) for p in paths))
    names = sorted(p.relative_to(module).as_posix() for p in paths if p.is_file())
    check('core_crypto_snapshot_valid_names', all('\n' not in name for name in names))
    digest_lines = ''.join(hashlib.sha256((module / name).read_bytes()).hexdigest()
                           + '  golang.org/x/crypto@v0.48.0/' + name + '\n' for name in names)
    snapshot_sum = 'h1:' + base64.b64encode(hashlib.sha256(digest_lines.encode()).digest()).decode()
    check('core_crypto_module_snapshot_unchanged', snapshot_sum == checksum)

    # Regenerate only the pinned overrides; compare their actual bytes and scope.
    with tempfile.TemporaryDirectory(prefix='inspect-crypto-') as directory:
        stage = pathlib.Path(directory) / 'stage'
        if module_root is None or go_root is None:
            raise ValueError('Explicit crypto module and Go paths are required')
        helper.prepare_overlay(module_root, go_root, stage)
        name = 'poly1305-32bit-experiment.json' if legacy else 'assembly-experiment.json'
        expected_manifest = json.loads((stage / name).read_text())
        check('core_crypto_exact_generated_sources', manifest.get('output_sha256') == expected_manifest['output_sha256'])
        expected_overlay = json.loads((stage / 'overlay.json').read_text().replace(str(stage), str(original_stage)))
        check('core_crypto_exact_overlay_scope', json.loads(overlay_path.read_text()) == expected_overlay)
        check('core_crypto_generated_files_unchanged', all(
            hashlib.sha256((original_stage / name).read_bytes()).hexdigest() == digest
            for name, digest in expected_manifest['output_sha256'].items()))
        check('core_crypto_modfile_only_expected_replace', modfile.read_text() == (pinned / 'go.mod').read_text()
              + '\nreplace golang.org/x/crypto => ' + str(original_stage / 'module') + '\n')

    # Verify both ChaCha copies actually contain r2 rotations. Self-reported flags
    # do not prove that the module scope matched. Other candidates must stay r1.
    check('core_crypto_elf32_sections', len(core) >= 52 and core[:6] == b'\x7fELF\x01\x01')
    section_offset = struct.unpack_from('<I', core, 32)[0]
    section_size, section_count, names_index = struct.unpack_from('<HHH', core, 46)
    check('core_crypto_section_table_bounds', section_size >= 40 and section_count > 0 and names_index < section_count
          and section_offset + section_size * section_count <= len(core))
    sections = [struct.unpack_from('<10I', core, section_offset + i * section_size) for i in range(section_count)]
    string_section = sections[names_index]
    check('core_crypto_section_names_bounds', string_section[4] + string_section[5] <= len(core))
    strings = core[string_section[4]:string_section[4] + string_section[5]]
    text = [s for s in sections if s[0] < len(strings) and strings[s[0]:].split(b'\0', 1)[0] == b'.text']
    check('core_crypto_text_section_bounds', len(text) == 1 and text[0][4] + text[0][5] <= len(core) and text[0][5] % 4 == 0)
    rotations, multiply_accumulates = [], 0
    for (word,) in struct.iter_unpack('<I', core[text[0][4]:text[0][4] + text[0][5]]):
        if word & 0xffe0003f == 0x00200002:
            rotations.append(word)
        if word & 0xfc00003f == 0x70000001:
            multiply_accumulates += 1
    check('core_crypto_actual_rotate_instructions', len(rotations) == (64 if backend == 'mipsle-asm-r2' else 0)
          and all(((word >> 6) & 31) in (16, 20, 24, 25) for word in rotations))
    check('core_crypto_actual_poly1305_assembly', multiply_accumulates == (0 if legacy else 38))


def inspect_layout(data, device, check):
    require_image_validator(device)
    check('bounded_by_evaluation_limit', len(data) <= device['image']['max_bytes'])
    check('fits_stock_OS1', len(data) <= device['image']['stock_install_max_bytes'])
    check('image_header_available', len(data) >= 64)
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
    check('squashfs_header_available', offset + 96 <= len(data))
    check('squashfs_at_kernel_end', data[offset:offset+4] == b'hsqs')
    check('squashfs_v4', struct.unpack_from('<HH', data, offset + 28) == (4, 0))
    used = struct.unpack_from('<Q', data, offset + 40)[0]
    check('squashfs_bounds', offset + used <= len(data))
    check('squashfs_xz', struct.unpack_from('<H', data, offset + 20)[0] == 4)
    squashfs_block_size = struct.unpack_from('<I', data, offset + 12)[0]
    check('squashfs_512k_blocks', squashfs_block_size == device['image']['squashfs_block_bytes'])
    return kernel_end, offset, used, squashfs_block_size


def inspect_identity(metadata, core, device, check):
    devices = metadata.get('new_supported_devices', metadata.get('supported_devices', []))
    check('metadata_device', device['board'] in devices)
    check('metadata_excludes_v2', not set(device['excluded_boards']) & set(devices))
    check('metadata_target', metadata['version']['target'] == device['target'])
    arch = architecture(device['architecture'])
    check('core_elf_target', len(core) >= 20 and core[:6] == bytes([127, 69, 76, 70, arch['elf_class'], arch['elf_data']])
          and struct.unpack_from('<H' if arch['elf_data'] == 1 else '>H', core, 18)[0] == arch['elf_machine'])


def inspect_management(readfile, listed_paths, source, reviewed, check):
    target = 'etc/uci-defaults/99-alwayroute-management'
    if reviewed is None:
        check('no_unselected_management_defaults', target not in listed_paths)
        return None
    expected = reviewed.read_bytes()
    check('management_defaults_match_reviewed_input',
          expected == (source / 'files' / target).read_bytes() == readfile(target))
    key = readfile('etc/dropbear/authorized_keys')
    check('public_key_matches', key == (source / 'files/etc/dropbear/authorized_keys').read_bytes())
    check('only_ed25519_public_key_embedded', key.startswith(b'ssh-ed25519 ') and b'PRIVATE KEY' not in key and len(key.splitlines()) == 1)
    return hashlib.sha256(expected).hexdigest()


def inspect_routing(readfile, inputs, lock_path, check):
    """Bind installed compiled rules to the reviewed lock and external build inputs."""
    lock = json.loads(lock_path.read_bytes())
    expected_manifest = (inputs / 'manifest.json').read_bytes()
    actual_manifest = readfile('usr/share/alwayroute/rules/manifest.json')
    check('routing_manifest_input', actual_manifest == expected_manifest)
    manifest = json.loads(actual_manifest)
    check('routing_source_lock', manifest.get('sourceLockSha256') == hashlib.sha256(lock_path.read_bytes()).hexdigest())
    check('routing_compiler_version', manifest.get('compilerVersion') == '1.13.21')
    check('routing_ip_family', manifest.get('ipFamily') in ('ipv4', 'dual'))
    check('routing_storage_compression', manifest.get('storageCompression') == 'zlib-stored')
    check('routing_required_sets', [s.get('name') for s in manifest.get('ruleSets', [])] == ['domestic-domain', 'domestic-ip'])
    check('routing_license_source', manifest.get('license') == lock['ruleSetLicense'])
    license_data = readfile('usr/share/alwayroute/rules/LICENSE')
    check('routing_license_payload', license_data == (inputs / 'LICENSE').read_bytes()
          and hashlib.sha256(license_data).hexdigest() == lock['ruleSetLicense']['sha256'])
    hashes = {}
    for source, compiled in zip(lock['ruleSets'], manifest['ruleSets'], strict=True):
        name = source['name']
        check('routing_source_' + name, all(compiled.get(k) == value for k, value in source.items()))
        check('routing_filename_' + name, compiled.get('file') == name + '.srs')
        target = 'usr/share/alwayroute/rules/' + name + '.srs'
        expected = (inputs / (name + '.srs')).read_bytes()
        actual = readfile(target)
        sha = hashlib.sha256(actual).hexdigest()
        check('routing_payload_' + name, actual == expected and sha == compiled['binarySha256']
              and len(actual) == compiled['binaryBytes'])
        hashes[target] = {'input_sha256': hashlib.sha256(expected).hexdigest(), 'installed_sha256': sha}
    return hashes


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--env', type=pathlib.Path, required=True, help='Validated build-host environment JSON')
    parser.add_argument('--device', default=DEFAULT_DEVICE, help='Repository device recipe name')
    parser.add_argument('image', type=pathlib.Path)
    parser.add_argument('--management-defaults', type=pathlib.Path, help='Explicit reviewed first-boot script; omission requires no custom management script')
    parser.add_argument('--profile', choices=('baseline', 'manager', 'release'), default='baseline')
    parser.add_argument('--release-manifest', type=pathlib.Path, help='Required for release: current run input manifest')
    parser.add_argument('--baseline-image', type=pathlib.Path, help='Required for manager: previously inspected baseline image')
    parser.add_argument('--core-sha256', type=sha256_arg, default=default_core_sha256)
    parser.add_argument('--experimental-crypto', choices=('poly1305-32', 'mipsle-asm', 'mipsle-asm-r2'),
                        help='Explicitly inspect one pinned experimental backend; default rejects overlays')
    parser.add_argument('--output', type=pathlib.Path, help='Report path (default: <OpenWrt tree parent>/image-inspection.json)')
    args = parser.parse_args(argv)
    context = build_context(args.env)
    device = load_device(args.device)
    require_image_validator(device)
    validate_crypto_target(device['architecture'], args.experimental_crypto, device)
    source = context['openwrt_tree']
    work = context['build_root']
    if args.profile == 'manager' and args.baseline_image is None:
        parser.error('--profile manager requires --baseline-image')
    if args.profile == 'release' and (args.release_manifest is None or args.management_defaults is not None
                                     or args.experimental_crypto != 'mipsle-asm-r2'):
        parser.error('release requires --release-manifest, mipsle-asm-r2 and standard OpenWrt management defaults')
    if args.experimental_crypto and args.profile not in ('manager', 'release'):
        parser.error('--experimental-crypto requires --profile manager or release')
    image = args.image.resolve()
    if not image.name.endswith(device['image']['manifest_suffix']):
        parser.error('Image filename does not match the selected device manifest suffix')
    data = image.read_bytes()
    release_manifest = json.loads(args.release_manifest.read_bytes()) if args.profile == 'release' else None
    expected_core_sha = sha256_arg(release_manifest['core_sha256']) if release_manifest else args.core_sha256
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


    kernel_end, offset, used, squashfs_block_size = inspect_layout(data, device, check)
    fwtool = source / 'staging_dir/host/bin/fwtool'
    metadata = json.loads(tool(str(fwtool), '-i', '/dev/stdout', str(image)))
    check('metadata_version', metadata['version']['version'] == '25.12.6')
    unsquashfs = source / 'staging_dir/host/bin/unsquashfs4'


    def readfile(path):
        return tool(str(unsquashfs), '-o', str(offset), '-cat', str(image), path)


    core = readfile('usr/bin/sing-box')
    core_sha = hashlib.sha256(core).hexdigest()
    inspect_identity(metadata, core, device, check)
    # Packaging may strip the ELF again; distinguish a changed payload explicitly.
    check('core_matches_tested_payload', core_sha == expected_core_sha)
    build_info = json.loads(readfile('usr/share/alwayroute/build-info.json'))
    check('core_provenance', build_info['input_elf_sha256'] == expected_core_sha)
    pinned = context['sing_box_source']
    with tempfile.TemporaryDirectory(prefix='inspect-core-') as directory:
        elf = pathlib.Path(directory)/'sing-box'
        elf.write_bytes(core)
        embedded = tool(str(context['go']), 'version', '-m', str(elf)).decode()
    validate_crypto_provenance(build_info, embedded, core, args.experimental_crypto, pinned, check,
                               module_root=context['cache_root'] / 'gomodcache/golang.org/x/crypto@v0.48.0',
                               go_root=context['go_root'])
    if args.profile in ('manager', 'release'):
        tags = 'with_quic,with_utls,with_clash_api,badlinkname,tfogo_checklinkname0'
        check('core_full_cli', build_info.get('cli_profile') == 'full' and build_info.get('entry_package') == './cmd/sing-box')
        check('core_full_registry', build_info.get('registry_profile') == 'upstream' and build_info.get('registry_patch_sha256') is None)
        check('core_pinned_source', build_info.get('source_sha256') == 'c994018d7c2a8fc9fcf6080e4b9cc4f2f915e755342238b77e46fc0806fe96db')
        check('core_registry_matches_pinned_source', build_info.get('registry_sha256') == hashlib.sha256((pinned/'include/registry.go').read_bytes()).hexdigest())
        check('core_original_feature_tags', build_info.get('tags') == tags)
        check('core_isolated_build_environment', build_info.get('build_environment') == {
            'GOFLAGS':'', 'GOENV':'off', 'GOWORK':'off', 'GOEXPERIMENT':'',
            'GOROOT':str(context['go_root']),
            'GOTOOLCHAIN':'local', 'GOPROXY':'off'})
        settings = {}
        for line in embedded.splitlines():
            fields = line.strip().split(None, 1)
            if len(fields) == 2 and fields[0] == 'build' and '=' in fields[1]:
                key, value = fields[1].split('=', 1)
                settings[key] = value.strip('"')
        check('core_embedded_target', all(settings.get(k) == v for k, v in architecture(device['architecture'])['go_env'].items()))
        check('core_embedded_tags', settings.get('-tags') == tags)
        check('core_embedded_full_entry', '\n\tpath\tgithub.com/sagernet/sing-box/cmd/sing-box\n' in embedded)
    listing = tool(str(unsquashfs), '-o', str(offset), '-ll', str(image)).decode(errors='replace')
    listed_paths = {
        match.group(1).split(' -> ', 1)[0]
        for line in listing.splitlines()
        if (match := re.search(r'squashfs-root/(.*)$', line))
    }
    management_sha = inspect_management(readfile, listed_paths, source, args.management_defaults, check)
    if args.profile == 'release':
        from release_inputs import validate_release_core
        validate_release_core(build_info, source / 'alwayroute-input', release_manifest, context, device, check)
        check('release_no_embedded_authorized_keys', 'etc/dropbear/authorized_keys' not in listed_paths)
        check('release_no_custom_overlay', not (source / 'files').exists())
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
        input_hashes.update(inspect_routing(readfile, source / 'alwayroute-input/routing',
                            pathlib.Path(__file__).resolve().parents[2] / 'config/routing/sources.lock.json', check))
        check('routing_no_source_json', not any(
            path.startswith('usr/share/alwayroute/rules/') and path.endswith('.json')
            and path != 'usr/share/alwayroute/rules/manifest.json' for path in listed_paths))
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
    manifest = image.with_name(image.name.removesuffix(device['image']['manifest_suffix']) + '.manifest')
    packages = {}
    for line in manifest.read_text().splitlines():
        name, version = line.split(' - ', 1)
        packages[name] = version
    for name in ['alwayroute-core', 'kmod-nft-tproxy', 'ip-full', 'luci-base', 'luci-mod-admin-full', 'uhttpd', 'dropbear', 'firewall4', 'odhcp6c', 'odhcpd-ipv6only'] + device['required_packages']:
        check('package_' + name, name in packages)
    expected_package_delta = None
    if args.profile in ('manager', 'release'):
        for name in ['alwayroute-forwarding', 'alwayroute-manager', 'luci-app-alwayroute']:
            check('package_' + name, name in packages)
    if args.profile == 'manager':
        baseline_data = args.baseline_image.read_bytes()
        baseline_kernel_end = 64 + struct.unpack_from('>I', baseline_data, 12)[0]
        check('manager_kernel_payload_unchanged', data[64:kernel_end] == baseline_data[64:baseline_kernel_end])
        baseline_manifest = args.baseline_image.with_name(args.baseline_image.name.removesuffix(device['image']['manifest_suffix']) + '.manifest')
        baseline_packages = dict(line.split(' - ', 1) for line in baseline_manifest.read_text().splitlines())
        manager_packages = {'alwayroute-forwarding', 'alwayroute-manager', 'luci-app-alwayroute'}
        added_packages = set(packages) - set(baseline_packages)
        expected_package_delta = {'added': sorted(manager_packages), 'removed': []}
        check('manager_only_three_added_packages', added_packages == manager_packages)
        check('manager_baseline_packages_unchanged', all(packages.get(name) == version for name, version in baseline_packages.items()))
    check('device_forbidden_packages_absent', not set(device['forbidden_packages']) & set(packages))
    erase = device['image']['erase_block_bytes']
    overlay_start = ((offset + used + erase - 1) // erase) * erase
    check('overlay_within_firmware_partition', overlay_start <= device['image']['firmware_partition_bytes'])
    report = {
        'image': str(image), 'profile': args.profile, 'device': device['id'], 'architecture': device['architecture'], 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest(),
        'expected': {
            'core_sha256': expected_core_sha,
            'ip_package': 'ip-full',
            'manager_package_delta': expected_package_delta,
        },
        'uimage_payload_end': kernel_end, 'squashfs_bytes_used': used,
        'squashfs_block_size': squashfs_block_size,
        'overlay_start_relative_firmware': overlay_start,
        'physical_firmware_bytes': device['image']['firmware_partition_bytes'],
        'raw_overlay_capacity_bytes_before_filesystem_overhead': device['image']['firmware_partition_bytes'] - overlay_start,
        'stock_OS1_remaining_after_image': device['image']['stock_install_max_bytes'] - len(data),
        'core_bytes': len(core), 'core_sha256': core_sha,
        'management_defaults_sha256': management_sha,
        'metadata': metadata, 'package_count': len(packages), 'checks': checks,
        'boot_verified': False, 'flashing_performed': False,
        'owned_payload_hashes': input_hashes,
        'executable_texts_checked': executable_texts,
        'upstream_executable_texts_without_shebang': executable_source_fragments,
    }
    out = args.output or work / 'image-inspection.json'
    out.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
