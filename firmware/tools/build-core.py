"""Build the pinned core for a selected CPU architecture on the build host using existing source and Go caches.

No downloads, toolchain installation, source-tree edits or global configuration.
All upstream CLI commands and registrations remain available under the pinned tags.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import shutil
import tarfile
import time

from build_context import build_context
from target_profile import (ARCHITECTURES, DEFAULT_DEVICE, GO_ARCH_OPTIONS, architecture,
                            load_device, validate_crypto_target)


ARCHIVE_SHA = 'c994018d7c2a8fc9fcf6080e4b9cc4f2f915e755342238b77e46fc0806fe96db'
TAGS = 'with_quic,with_utls,with_clash_api,badlinkname,tfogo_checklinkname0'
ENTRY = './cmd/sing-box'
COLD_PACKAGES = [
    'github.com/sagernet/sing-box/cmd/sing-box',
    'github.com/spf13/cobra', 'github.com/spf13/pflag',
    'github.com/sagernet/sing-box/option',
    'github.com/sagernet/sing-box/common/convertor/...',
    'github.com/sagernet/sing-box/common/geosite',
    'github.com/sagernet/sing-box/common/srs',
]
HOT_PACKAGES = [
    'math/bits', 'encoding/binary', 'crypto/tls',
    'vendor/golang.org/x/crypto/chacha20',
    'vendor/golang.org/x/crypto/chacha20poly1305',
    'vendor/golang.org/x/crypto/internal/poly1305',
    'golang.org/x/crypto/chacha20', 'golang.org/x/crypto/chacha20poly1305',
    'golang.org/x/crypto/internal/poly1305',
]


def core_environment(context, arch):
    return {**{k: v for k, v in os.environ.items() if k not in GO_ARCH_OPTIONS},
           **arch['go_env'], 'GOMAXPROCS': str(context['jobs']), 'GOTOOLCHAIN': 'local', 'GOPROXY': 'off',
           'GOFLAGS': '', 'GOENV': 'off', 'GOWORK': 'off', 'GOEXPERIMENT': '',
           'GOROOT': str(context['go_root']),
           'GOCACHE': str(context['cache_root'] / 'gocache'),
           'GOMODCACHE': str(context['cache_root'] / 'gomodcache'),
           'GOPATH': str(context['cache_root'] / 'gopath'), 'TMPDIR': str(context['cache_root'] / 'tmp')}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--env', type=Path, required=True, help='Validated build-host environment JSON')
    parser.add_argument('--device', default=DEFAULT_DEVICE, help='Device recipe providing the default architecture and crypto allowlist')
    parser.add_argument('--architecture', choices=tuple(ARCHITECTURES), help='Override for a standalone core; does not declare device compatibility')
    parser.add_argument('--output', type=Path, required=True, help='Fresh ELF destination on this build host')
    parser.add_argument('--pgo', type=Path, help='Device CPU profile; keeps all features and the pinned compiler')
    parser.add_argument('--tls-session-cache', action='store_true',
                        help='Candidate: enable a bounded per-outbound standard TLS session cache')
    parser.add_argument('--experimental-crypto', choices=('poly1305-32', 'mipsle-asm', 'mipsle-asm-r2'),
                        help='Explicit candidate only; retains full core and never modifies upstream trees')
    compiler = parser.add_mutually_exclusive_group()
    compiler.add_argument('--no-inline', action='store_true', help='Comparison only: retain the old all=-l compiler setting')
    compiler.add_argument('--cold-no-inline', action='store_true', help='Disable inlining only in CLI and configuration/file conversion packages')
    compiler.add_argument('--crypto-inline', action='store_true', help='Size candidate: preserve crypto inlining while disabling it in other packages')
    args = parser.parse_args(argv)
    context = build_context(args.env, default_jobs=2, default_timeout=1800)
    device = load_device(args.device)
    arch_name = args.architecture or device['architecture']
    arch = architecture(arch_name)
    validate_crypto_target(arch_name, args.experimental_crypto,
                           device if arch_name == device['architecture'] else None)
    source = context['sing_box_source']
    archive = context['sing_box_archive']
    output = args.output.resolve()
    if output.exists():
        raise SystemExit('Refusing to replace an existing core; choose a fresh output path')
    if hashlib.sha256(archive.read_bytes()).hexdigest() != ARCHIVE_SHA:
        raise SystemExit('Pinned upstream archive hash mismatch')
    verified = set()
    with tarfile.open(archive) as tar:
        for member in tar:
            if not member.isfile():
                continue
            relative = Path(*Path(member.name).parts[1:])
            if relative.is_absolute() or '..' in relative.parts:
                raise SystemExit('Unexpected archive path')
            data = tar.extractfile(member).read()
            if not (source / relative).is_file() or (source / relative).read_bytes() != data:
                raise SystemExit('Upstream source differs from the pinned archive: ' + str(relative))
            verified.add(relative.as_posix())
    if any(p.relative_to(source).as_posix() not in verified for p in source.rglob('*.go')):
        raise SystemExit('Unexpected Go source in the upstream tree')
    go = context['go']
    version = subprocess.check_output([str(go), 'version'], text=True).strip()
    if 'go1.27.3 ' not in version:
        raise SystemExit('Unexpected Go toolchain: ' + version)
    output.parent.mkdir(parents=True, exist_ok=True)
    env = core_environment(context, arch)
    started = time.monotonic()
    gcflags = ['all=-l'] if args.no_inline else [p+'=-l' for p in COLD_PACKAGES] if args.cold_no_inline else []
    if args.crypto_inline:
        gcflags = ['all=-l'] + [p+'=' for p in HOT_PACKAGES]
    command = [str(go), 'build', '-p', str(context['jobs']), '-trimpath', '-buildvcs=false', '-tags', TAGS,
               '-pgo', str(args.pgo.resolve()) if args.pgo else 'off']
    crypto = None
    overlay_path = None
    if args.experimental_crypto:
        legacy = args.experimental_crypto == 'poly1305-32'
        helper_path = Path(__file__).with_name('poly1305-32bit-overlay.py' if legacy else 'crypto-assembly-overlay.py')
        spec = importlib.util.spec_from_file_location('crypto_candidate', helper_path)
        helper = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(helper)
        stage = output.parent / (output.name + '.crypto-stage')
        helper.prepare_overlay(context['cache_root'] / 'gomodcache/golang.org/x/crypto@v0.48.0', go.parent.parent, stage)
        modfile = stage / 'core.mod'
        modfile.write_text((source / 'go.mod').read_text() + '\nreplace golang.org/x/crypto => ' + str(stage / 'module') + '\n')
        shutil.copyfile(source / 'go.sum', stage / 'core.sum')
        command += ['-overlay=' + str(stage / 'overlay.json'), '-modfile=' + str(modfile)]
        overlay_path = stage / 'overlay.json'
        asmflags = []
        if args.experimental_crypto == 'mipsle-asm-r2':
            # MT7621 1004Kc implements MIPS32r2. Limit this macro to ChaCha's two
            # copies; GOMIPS stays softfloat and the installed compiler is unchanged.
            asmflags = [p + '=-D GOMIPS_r2' for p in (
                'golang.org/x/crypto/chacha20', 'vendor/golang.org/x/crypto/chacha20')]
            command += ['-asmflags=' + flag for flag in asmflags]
        manifest_name = 'poly1305-32bit-experiment.json' if legacy else 'assembly-experiment.json'
        crypto = {'backend': args.experimental_crypto, 'experimental': True,
                  'upstream_approved': False, 'asmflags': asmflags,
                  'manifest': json.loads((stage / manifest_name).read_text()),
                  'overlay_sha256': hashlib.sha256((stage / 'overlay.json').read_bytes()).hexdigest(),
                  'modfile_sha256': hashlib.sha256(modfile.read_bytes()).hexdigest()}
    tls_sessions = None
    if args.tls_session_cache:
        helper_path = Path(__file__).with_name('tls-session-overlay.py')
        spec = importlib.util.spec_from_file_location('tls_session_candidate', helper_path)
        helper = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(helper)
        if overlay_path is None:
            stage = output.parent / (output.name + '.tls-stage')
            if stage.exists():
                raise SystemExit('TLS overlay stage already exists')
            overlay_path = stage / 'overlay.json'
            overlay = {'Replace': {}}
            command += ['-overlay=' + str(overlay_path)]
        else:
            overlay = json.loads(overlay_path.read_text())
        tls_sessions = helper.add_overlay(source, overlay_path.parent, overlay)
        overlay_path.write_text(json.dumps(overlay, indent=2) + '\n')
    # Apply required correctness fixes to every backend, sharing the one Go
    # overlay with the optional TLS and crypto replacements.
    helper_path = Path(__file__).with_name('resource-fixes-overlay.py')
    spec = importlib.util.spec_from_file_location('resource_fixes', helper_path)
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    if overlay_path is None:
        stage = output.parent / (output.name + '.resource-stage')
        if stage.exists():
            raise SystemExit('Resource overlay stage already exists')
        overlay_path = stage / 'overlay.json'
        overlay = {'Replace': {}}
        command += ['-overlay=' + str(overlay_path)]
    else:
        overlay = json.loads(overlay_path.read_text())
    resource_fixes = helper.add_overlay(source, overlay_path.parent, overlay)
    overlay_path.write_text(json.dumps(overlay, indent=2) + '\n')
    if crypto is not None:
        crypto['overlay_sha256'] = hashlib.sha256(overlay_path.read_bytes()).hexdigest()
    command += ['-gcflags='+flag for flag in gcflags]
    command += ['-ldflags', '-s -w -buildid= -X internal/godebug.defaultGODEBUG=multipathtcp=0 '
                '-checklinkname=0 -X github.com/sagernet/sing-box/constant.Version=1.13.21-alwayroute-router',
                '-o', str(output), ENTRY]
    with output.with_suffix('.log').open('wb') as log:
        subprocess.run(command, cwd=source, env=env, stdout=log, stderr=subprocess.STDOUT, check=True, timeout=context['timeout_seconds'])
    data = output.read_bytes()
    metadata = {'version': '1.13.21-alwayroute-router', 'source_sha256': ARCHIVE_SHA,
                'input_elf_sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data),
                'go': '1.27.3', 'architecture': arch['description'], 'CGO_ENABLED': 0,
                'architecture_id': arch_name, 'target_go_env': arch['go_env'],
                'tags': TAGS, 'gcflags': gcflags, 'profile_version': 1,
                'entry_package': ENTRY, 'cli_profile': 'full', 'registry_profile': 'upstream',
                'registry_sha256': hashlib.sha256((source/'include/registry.go').read_bytes()).hexdigest(),
                'registry_patch_sha256': None, 'command': command,
                'crypto_candidate': crypto,
                'tls_session_cache': tls_sessions,
                'resource_fixes': resource_fixes,
                'build_environment': {k: env[k] for k in ['GOFLAGS','GOENV','GOWORK','GOEXPERIMENT','GOROOT','GOTOOLCHAIN','GOPROXY']},
                'pgo_sha256': hashlib.sha256(args.pgo.read_bytes()).hexdigest() if args.pgo else None,
                'embedded_build_info': subprocess.check_output([str(go), 'version', '-m', str(output)], env=env, text=True),
                'verified_source_files': len(verified), 'elapsed_seconds': round(time.monotonic() - started, 3),
                'runtime_validation': 'pending device checks; build success is not runtime acceptance'}
    output.with_suffix('.build-info.json').write_text(json.dumps(metadata, indent=2) + '\n')
    print(json.dumps(metadata), flush=True)


if __name__ == '__main__':
    main()
