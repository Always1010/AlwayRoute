"""Build the pinned router core on Rock using existing source and Go caches.

No downloads, toolchain installation, source-tree edits or global configuration.
The overlay only narrows registration; the required mixed protocols stay enabled.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import time

ROOT = Path('/srv/alwayroute')
ARCHIVE_SHA = 'c994018d7c2a8fc9fcf6080e4b9cc4f2f915e755342238b77e46fc0806fe96db'
TAGS = 'with_quic,with_utls,with_clash_api,badlinkname,tfogo_checklinkname0'
ENTRY = ['cmd.go', 'cmd_check.go', 'cmd_run.go', 'cmd_version.go', 'main.go']
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--output', type=Path, required=True)
parser.add_argument('--no-inline', action='store_true', help='Comparison only: retain the old all=-l compiler setting')
args = parser.parse_args()
source = ROOT / 'sources/sing-box-1.13.21'
archive = ROOT / 'artifacts/sing-box-v1.13.21-source.tar.gz'
patch = Path(__file__).resolve().parents[1] / 'openwrt/patches/002-sing-box-router-profile.patch'
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
       'GOCACHE': str(ROOT / 'build-cache/gocache'),
       'GOMODCACHE': str(ROOT / 'build-cache/gomodcache'),
       'GOPATH': str(ROOT / 'build-cache/gopath'), 'TMPDIR': str(ROOT / 'build-cache/tmp')}
started = time.monotonic()
with tempfile.TemporaryDirectory(prefix='core-overlay-', dir=output.parent) as temp:
    stage = Path(temp)
    (stage / 'include').mkdir()
    shutil.copyfile(source / 'include/registry.go', stage / 'include/registry.go')
    subprocess.run(['git', 'apply', '--check', str(patch)], cwd=stage, check=True)
    subprocess.run(['git', 'apply', str(patch)], cwd=stage, check=True)
    overlay = stage / 'overlay.json'
    overlay.write_text(json.dumps({'Replace': {str(source / 'include/registry.go'): str(stage / 'include/registry.go')}}))
    command = [str(go), 'build', '-p', '2', '-trimpath', '-buildvcs=false', '-overlay', str(overlay), '-tags', TAGS]
    if args.no_inline:
        command += ['-gcflags=all=-l']
    command += ['-ldflags', '-s -w -buildid= -X internal/godebug.defaultGODEBUG=multipathtcp=0 '
                '-checklinkname=0 -X github.com/sagernet/sing-box/constant.Version=1.13.21-alwayroute-router',
                '-o', str(output)]
    command += ['cmd/sing-box/' + name for name in ENTRY]
    with output.with_suffix('.log').open('wb') as log:
        subprocess.run(command, cwd=source, env=env, stdout=log, stderr=subprocess.STDOUT, check=True, timeout=1800)
data = output.read_bytes()
metadata = {'version': '1.13.21-alwayroute-router', 'source_sha256': ARCHIVE_SHA,
            'input_elf_sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data),
            'go': '1.27.3', 'architecture': 'linux/mipsle softfloat', 'CGO_ENABLED': 0,
            'tags': TAGS, 'gcflags': 'all=-l' if args.no_inline else None,
            'entry_files': ENTRY, 'registry_patch_sha256': hashlib.sha256(patch.read_bytes()).hexdigest(),
            'verified_source_files': len(verified), 'elapsed_seconds': round(time.monotonic() - started, 3),
            'runtime_validation': 'pending device checks; build success is not runtime acceptance'}
output.with_suffix('.build-info.json').write_text(json.dumps(metadata, indent=2) + '\n')
print(json.dumps(metadata), flush=True)
