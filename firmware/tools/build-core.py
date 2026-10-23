"""Build the pinned router core on Rock using existing source and Go caches.

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

ROOT = Path('/srv/alwayroute')
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
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--output', type=Path, required=True)
parser.add_argument('--pgo', type=Path, help='Device CPU profile; keeps all features and the pinned compiler')
parser.add_argument('--experimental-crypto', choices=('poly1305-32', 'mipsle-asm', 'mipsle-asm-r2'),
                    help='Explicit candidate only; retains full core and never modifies upstream trees')
compiler = parser.add_mutually_exclusive_group()
compiler.add_argument('--no-inline', action='store_true', help='Comparison only: retain the old all=-l compiler setting')
compiler.add_argument('--cold-no-inline', action='store_true', help='Disable inlining only in CLI and configuration/file conversion packages')
compiler.add_argument('--crypto-inline', action='store_true', help='Size candidate: preserve crypto inlining while disabling it in other packages')
args = parser.parse_args()
source = ROOT / 'sources/sing-box-1.13.21'
archive = ROOT / 'artifacts/sing-box-v1.13.21-source.tar.gz'
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
go = ROOT / 'toolchains/go1.27.3/go/bin/go'
version = subprocess.check_output([str(go), 'version'], text=True).strip()
if 'go1.27.3 ' not in version:
    raise SystemExit('Unexpected Go toolchain: ' + version)
output.parent.mkdir(parents=True, exist_ok=True)
env = {**os.environ, 'GOOS': 'linux', 'GOARCH': 'mipsle', 'GOMIPS': 'softfloat',
       'CGO_ENABLED': '0', 'GOMAXPROCS': '2', 'GOTOOLCHAIN': 'local', 'GOPROXY': 'off',
       'GOFLAGS': '', 'GOENV': 'off', 'GOWORK': 'off', 'GOEXPERIMENT': '',
       'GOROOT': str(go.parent.parent),
       'GOCACHE': str(ROOT / 'build-cache/gocache'),
       'GOMODCACHE': str(ROOT / 'build-cache/gomodcache'),
       'GOPATH': str(ROOT / 'build-cache/gopath'), 'TMPDIR': str(ROOT / 'build-cache/tmp')}
started = time.monotonic()
gcflags = ['all=-l'] if args.no_inline else [p+'=-l' for p in COLD_PACKAGES] if args.cold_no_inline else []
if args.crypto_inline:
    gcflags = ['all=-l'] + [p+'=' for p in HOT_PACKAGES]
command = [str(go), 'build', '-p', '2', '-trimpath', '-buildvcs=false', '-tags', TAGS,
           '-pgo', str(args.pgo.resolve()) if args.pgo else 'off']
crypto = None
if args.experimental_crypto:
    legacy = args.experimental_crypto == 'poly1305-32'
    helper_path = Path(__file__).with_name('poly1305-32bit-overlay.py' if legacy else 'crypto-assembly-overlay.py')
    spec = importlib.util.spec_from_file_location('crypto_candidate', helper_path)
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    stage = output.parent / (output.name + '.crypto-stage')
    helper.prepare_overlay(ROOT / 'build-cache/gomodcache/golang.org/x/crypto@v0.48.0', go.parent.parent, stage)
    modfile = stage / 'core.mod'
    modfile.write_text((source / 'go.mod').read_text() + '\nreplace golang.org/x/crypto => ' + str(stage / 'module') + '\n')
    shutil.copyfile(source / 'go.sum', stage / 'core.sum')
    command += ['-overlay=' + str(stage / 'overlay.json'), '-modfile=' + str(modfile)]
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
command += ['-gcflags='+flag for flag in gcflags]
command += ['-ldflags', '-s -w -buildid= -X internal/godebug.defaultGODEBUG=multipathtcp=0 '
            '-checklinkname=0 -X github.com/sagernet/sing-box/constant.Version=1.13.21-alwayroute-router',
            '-o', str(output), ENTRY]
with output.with_suffix('.log').open('wb') as log:
    subprocess.run(command, cwd=source, env=env, stdout=log, stderr=subprocess.STDOUT, check=True, timeout=1800)
data = output.read_bytes()
metadata = {'version': '1.13.21-alwayroute-router', 'source_sha256': ARCHIVE_SHA,
            'input_elf_sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data),
            'go': '1.27.3', 'architecture': 'linux/mipsle softfloat', 'CGO_ENABLED': 0,
            'tags': TAGS, 'gcflags': gcflags, 'profile_version': 1,
            'entry_package': ENTRY, 'cli_profile': 'full', 'registry_profile': 'upstream',
            'registry_sha256': hashlib.sha256((source/'include/registry.go').read_bytes()).hexdigest(),
            'registry_patch_sha256': None, 'command': command,
            'crypto_candidate': crypto,
            'build_environment': {k: env[k] for k in ['GOFLAGS','GOENV','GOWORK','GOEXPERIMENT','GOROOT','GOTOOLCHAIN','GOPROXY']},
            'pgo_sha256': hashlib.sha256(args.pgo.read_bytes()).hexdigest() if args.pgo else None,
            'embedded_build_info': subprocess.check_output([str(go), 'version', '-m', str(output)], env=env, text=True),
            'verified_source_files': len(verified), 'elapsed_seconds': round(time.monotonic() - started, 3),
            'runtime_validation': 'pending device checks; build success is not runtime acceptance'}
output.with_suffix('.build-info.json').write_text(json.dumps(metadata, indent=2) + '\n')
print(json.dumps(metadata), flush=True)
