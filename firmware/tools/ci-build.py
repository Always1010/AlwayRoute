"""Build the public 4A recipe on an ephemeral GitHub-hosted Linux x64 runner.

Without --apply print the plan only. Does not connect to development hosts or
routers. Installs no system packages; workflow provisions the disposable runner.
"""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import urllib.request

from release_inputs import FIRMWARE, input_identity, load_release, sha256
from target_profile import load_device, seed_text
from release_bundle import package_release

ROOT = FIRMWARE.parent
PACKAGES = ('alwayroute-core', 'alwayroute-manager', 'alwayroute-forwarding', 'luci-app-alwayroute')


def release_version(value):
    if not re.fullmatch(r'v[0-9]+\.[0-9]+\.[0-9]+(?:-[0-9A-Za-z]+(?:[.-][0-9A-Za-z]+)*)?', value):
        raise ValueError('Use vMAJOR.MINOR.PATCH or a prerelease such as v0.1.0-rc.1')
    return value


def run(command, cwd, logs, name, *, env=None, timeout=10800):
    print('Running: ' + name, flush=True)
    with (logs / (name + '.log')).open('wb') as log:
        result = subprocess.run([str(x) for x in command], cwd=cwd, env=env,
                                stdout=log, stderr=subprocess.STDOUT, timeout=timeout)
    if result.returncode:
        print((logs / (name + '.log')).read_text(errors='replace')[-12000:], file=sys.stderr)
        raise RuntimeError(name + ' failed; see the uploaded build log')


def json_file(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def download(url, path, digest):
    if not path.exists():
        request = urllib.request.Request(url, headers={'User-Agent': 'AlwayRoute-release-build/1'})
        with urllib.request.urlopen(request, timeout=120) as response, path.open('xb') as out:
            shutil.copyfileobj(response, out)
    if sha256(path) != digest:
        raise ValueError('Downloaded archive checksum mismatch: ' + path.name)


def prepare(task, spec, device, version):
    if platform.system() != 'Linux' or platform.machine() not in ('x86_64', 'AMD64'):
        raise ValueError('This release workflow requires Linux x64')
    if os.environ.get('GITHUB_ACTIONS') != 'true' or not os.environ.get('RUNNER_TEMP'):
        raise ValueError('--apply is restricted to disposable GitHub runners')
    runner_temp = Path(os.environ['RUNNER_TEMP']).resolve()
    if task == runner_temp or not task.is_relative_to(runner_temp):
        raise ValueError('Build task must be below RUNNER_TEMP')
    task.mkdir(parents=True, exist_ok=True)
    if (task / 'environment.json').exists():
        raise ValueError('Choose a fresh task directory; old build trees are never overwritten')
    free = shutil.disk_usage(task).free
    print('Initial free disk bytes:', free, flush=True)
    if free < 12 * 1024**3:
        raise ValueError('Less than 12 GiB free; inspect runner disk before building')
    logs = task / 'logs'
    logs.mkdir()
    for name in ('caches/downloads', 'caches/go/gocache', 'caches/go/gomodcache',
                 'caches/go/gopath', 'caches/go/tmp', 'caches/openwrt-dl',
                 'sources', 'artifacts', 'openwrt-build/tmp', 'toolchains/go1.27.3'):
        (task / name).mkdir(parents=True, exist_ok=True)
    environment = task / 'environment.json'
    context = {'schema_version': 1, 'name': 'GitHub release runner', 'build': {
        'executor': 'local', 'task_root': str(task), 'project_workspace': str(ROOT),
        'openwrt_tree': str(task / 'openwrt-build/source'),
        'toolchain_root': str(task / 'toolchains'), 'cache_root': str(task / 'caches/go'),
        'output_root': str(task / 'artifacts'), 'jobs': min(os.cpu_count() or 2, 4),
        'timeout_seconds': 14400, 'disk_limit_bytes': 40 * 1024**3}}
    json_file(environment, context)
    go_archive = task / 'caches/downloads/go1.27.3.linux-amd64.tar.gz'
    download(spec['go']['url'], go_archive, spec['go']['sha256'])
    with tarfile.open(go_archive) as archive:
        if any(not (m.name.startswith('go/') or (m.name == 'go' and m.isdir()))
               for m in archive.getmembers()):
            raise ValueError('Unexpected Go archive root')
        archive.extractall(task / 'toolchains/go1.27.3', filter='data')
    # The source fetcher verifies locked Git tree hashes before extraction.
    run([sys.executable, ROOT / 'scripts/fetch-sources.py', 'fetch',
         '--dest', task / 'snapshots', '--cache', task / 'caches/downloads'], ROOT, logs, 'fetch-sources')
    shutil.copytree(task / 'snapshots/sing-box', task / 'sources/sing-box-1.13.21', symlinks=True)
    locks = json.loads((FIRMWARE / 'sources.lock.json').read_text())['sources']
    core_lock = next(s for s in locks if s['name'] == 'sing-box')
    shutil.copyfile(task / ('caches/downloads/sing-box-' + core_lock['tree'] + '.tar.gz'),
                    task / 'artifacts/sing-box-v1.13.21-source.tar.gz')
    tree = task / 'openwrt-build/source'
    shutil.copytree(task / 'snapshots/openwrt', tree, symlinks=True)
    (tree / 'dl').symlink_to(task / 'caches/openwrt-dl', target_is_directory=True)
    (tree / 'feeds.conf').write_text(''.join(
        'src-link ' + name + ' ' + str(task / 'snapshots' / name) + '\n'
        for name in ('packages', 'luci')))
    for patch in device['patches']:
        run(['git', 'apply', '--check', FIRMWARE / patch], tree, logs, 'check-' + Path(patch).stem)
        run(['git', 'apply', FIRMWARE / patch], tree, logs, 'apply-' + Path(patch).stem)
    for name in PACKAGES:
        shutil.copytree(FIRMWARE / 'openwrt' / name, tree / 'package' / name)
    run(['./scripts/feeds', 'update', '-a'], tree, logs, 'feeds-update')
    run(['./scripts/feeds', 'install', '-a'], tree, logs, 'feeds-install')
    # No personal overlay, keys or lab management policy enter the public image.
    if (tree / 'files').exists():
        raise ValueError('Unexpected OpenWrt overlay directory')
    (tree / '.config').write_text(seed_text(device), encoding='utf-8')
    run(['make', 'defconfig'], tree, logs, 'defconfig')
    from target_profile import require_build_target
    require_build_target(tree, device)
    return environment, tree, logs, context


def build(task, version):
    spec = load_release()
    device = load_device(spec['device'])
    environment, tree, logs, settings = prepare(task, spec, device, version)
    from build_context import build_context
    from target_profile import architecture
    module_spec = importlib.util.spec_from_file_location('ci_core', Path(__file__).with_name('build-core.py'))
    core_builder = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(core_builder)
    context = build_context(environment)
    goenv = core_builder.core_environment(context, architecture('amd64'))
    # Explicit network preparation; the actual pinned core builder stays offline.
    goenv.update(GOPROXY='https://proxy.golang.org,direct', GOSUMDB='sum.golang.org')
    run([context['go'], 'mod', 'download'], context['sing_box_source'], logs, 'go-modules', env=goenv)
    host = task / 'artifacts/sing-box-host'
    run([sys.executable, FIRMWARE / 'tools/build-core.py', '--env', environment,
         '--architecture', 'amd64', '--output', host], ROOT, logs, 'host-core')
    core = task / 'artifacts/sing-box-mipsle'
    run([sys.executable, FIRMWARE / 'tools/build-core.py', '--env', environment,
         '--device', device['id'], '--crypto-inline', '--pgo', FIRMWARE / spec['pgo']['path'],
         '--experimental-crypto', spec['crypto_backend'], '--output', core], ROOT, logs, 'router-core')
    inputs = tree / 'alwayroute-input'
    inputs.mkdir()
    shutil.copyfile(core, inputs / 'sing-box')
    shutil.copyfile(core.with_suffix('.build-info.json'), inputs / 'build-info.json')
    shutil.copyfile(context['sing_box_source'] / 'LICENSE', inputs / 'LICENSE')
    routing = task / 'artifacts/routing'
    run([sys.executable, ROOT / 'scripts/build-routing.py', '--sing-box', host,
         '--cache', task / 'caches/routing', '--output', routing, '--fetch'], ROOT, logs, 'routing')
    (inputs / 'routing').mkdir()
    for name in ('domestic-domain.srs', 'domestic-ip.srs', 'manifest.json', 'LICENSE'):
        shutil.copyfile(routing / name, inputs / 'routing' / name)
    commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    manifest = {'schema_version': 1, 'version': version, 'source_commit': commit,
                'device': device['id'], 'core_sha256': sha256(core), 'inputs': input_identity(device),
                'runtime_validation': 'pending; CI build is not device acceptance'}
    json_file(task / 'release-inputs.json', manifest)
    epoch = subprocess.check_output(['git', 'show', '-s', '--format=%ct', 'HEAD'], cwd=ROOT, text=True).strip()
    buildenv = {**os.environ, 'SOURCE_DATE_EPOCH': epoch}
    run(['make', '-j' + str(settings['build']['jobs']), 'download'], tree, logs, 'openwrt-download', env=buildenv)
    run([sys.executable, FIRMWARE / 'tools/run-native-build.py', '--env', environment,
         '--device', device['id']], ROOT, logs, 'firmware-build', env=buildenv, timeout=15000)
    inspection = task / 'image-inspection.json'
    image = tree / device['image']['path']
    run([sys.executable, FIRMWARE / 'tools/inspect-image.py', '--env', environment,
         '--device', device['id'], '--profile', 'release', '--release-manifest', task / 'release-inputs.json',
         '--experimental-crypto', spec['crypto_backend'], '--output', inspection, image], ROOT, logs, 'image-inspection')
    report = json.loads(inspection.read_text())
    if not report['checks'] or not all(report['checks'].values()):
        raise ValueError('Image inspection did not pass')
    manifest['source_date_epoch'] = int(epoch)
    package_release(task, ROOT / 'artifacts/release', version, device, image, inspection, manifest)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--version', type=release_version, required=True)
    parser.add_argument('--task-root', type=Path, required=True)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args(argv)
    spec = load_release()
    if not args.apply:
        print(json.dumps({'version': args.version, 'device': spec['device'], 'apply': False,
                          'task_root': str(args.task_root), 'inputs': input_identity(load_device(spec['device'])),
                          'steps': ['verify sources', 'build host and MIPSLE core', 'compile rules',
                                    'build OpenWrt', 'inspect image', 'package release']}, indent=2))
        return
    build(args.task_root.resolve(), args.version)


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        raise SystemExit(str(error)) from error
