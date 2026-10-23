"""Preview/apply selected AlwayRoute packages on the build host; never build or delete.

--env describes paths on this host, not an automatic SSH executor. Sources are
the current repository. Apply requires an unchanged saved preview and copies
only a private, hashed source snapshot. Existing extra destination files must
be reviewed and removed separately before this tool can proceed.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile

from build_context import build_context


ROOT = Path(__file__).resolve().parents[2]
PACKAGES = ('alwayroute-core', 'alwayroute-manager', 'alwayroute-forwarding', 'luci-app-alwayroute')


class PackageSyncError(ValueError):
    pass


def manifest(directory):
    if not directory.exists():
        return {}
    if not directory.is_dir() or directory.is_symlink():
        raise PackageSyncError('Package directory must be a real directory')
    result = {}
    for path in sorted(directory.rglob('*')):
        if path.is_symlink() or not (path.is_file() or path.is_dir()):
            raise PackageSyncError('Package contains an unsupported link or special file: ' + path.relative_to(directory).as_posix())
        if path.is_file():
            mode = path.stat()
            result[path.relative_to(directory).as_posix()] = {
                'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                'mode': stat.S_IMODE(mode.st_mode), 'mtime_ns': mode.st_mtime_ns,
            }
    return result


def hashes(entries):
    return {name: info['sha256'] for name, info in entries.items()}


def destination(context, name):
    tree = context['openwrt_tree'].absolute()
    package_root = tree / 'package'
    target = package_root / name
    # Resolving the entire path rejects parent links as well as package links.
    if not tree.is_dir() or tree.resolve() != tree or not package_root.is_dir() or package_root.resolve() != package_root:
        raise PackageSyncError('Select an existing OpenWrt tree with a real package directory; symlink paths are refused')
    if target.resolve() != target or target.parent != package_root:
        raise PackageSyncError('Package destination must remain directly inside the selected OpenWrt package directory')
    for key in ('cache_root', 'go_root', 'output_root'):
        protected = context[key].resolve()
        if target == protected or protected in target.parents or target in protected.parents:
            raise PackageSyncError('Package destination overlaps cache, toolchain or artifact data')
    return target


def reject_extra(name, expected, actual):
    extra = sorted(set(actual) - set(expected))
    if extra:
        raise PackageSyncError('Extra destination files; review separately (nothing deleted): ' +
                               ', '.join(name + '/' + path for path in extra))


def run_rsync(executable, source, target, *, dry_run):
    command = [executable, '-a', '--checksum', '--itemize-changes', '--out-format=%i %n%L']
    if dry_run:
        command.append('--dry-run')
    result = subprocess.run(command + [str(source) + '/', str(target) + '/'],
                            capture_output=True, check=True, timeout=300)
    return result.stdout


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--env', type=Path, required=True, help='Validated environment JSON for this build host')
    parser.add_argument('--package', choices=PACKAGES, nargs='+', action='append', required=True,
                        help='Explicit package selection; repeat this option or list multiple names')
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--apply', action='store_true', help='Apply an unchanged successful preview')
    mode.add_argument('--dry-run', action='store_true', help='Preview only (default)')
    parser.add_argument('--plan', type=Path, help='Ignored plan inside this repository .local directory')
    parser.add_argument('--rsync', default='rsync', help='Existing build-host rsync executable')
    args = parser.parse_args(argv)
    try:
        context = build_context(args.env)  # Uses load_environment's shared schema validation.
        names = sorted({name for group in args.package for name in group})
        plan = (args.plan or ROOT / '.local/runs/package-sync-plan.json').resolve()
        if not plan.is_relative_to((ROOT / '.local').resolve()):
            raise PackageSyncError('Package sync plan must stay inside this repository .local directory')
        targets = {name: destination(context, name) for name in names}
        source_root = ROOT / 'firmware/openwrt'
        sources = {}
        before = {}
        for name in names:
            source = source_root / name
            if source.resolve() != source or not source.is_dir():
                raise PackageSyncError('Selected package source must be a real directory in this repository: ' + name)
            sources[name] = manifest(source)
            if not sources[name]:
                raise PackageSyncError('Selected package source is empty: ' + name)
            before[name] = manifest(targets[name])
            reject_extra(name, sources[name], before[name])
        plan.parent.mkdir(parents=True, exist_ok=True)
        os.chmod(plan.parent, 0o700)
        with tempfile.TemporaryDirectory(prefix='package-sync-', dir=plan.parent) as temporary:
            snapshot = Path(temporary)
            previews = {}
            for name in names:
                staged = snapshot / name
                shutil.copytree(source_root / name, staged, symlinks=True)
                if manifest(staged) != sources[name] or manifest(source_root / name) != sources[name]:
                    raise PackageSyncError('Package sources changed while snapshotting; preview again: ' + name)
                previews[name] = run_rsync(args.rsync, staged, targets[name], dry_run=True)
            current = {'schema_version': 1, 'source_root': str(source_root), 'packages': {
                name: {'source': sources[name], 'destination': str(targets[name]), 'target_hashes': hashes(before[name]),
                       'preview_sha256': hashlib.sha256(previews[name]).hexdigest()} for name in names}}
            # A preview must not race local edits or destination changes. The
            # copied snapshot remains the only rsync input even after this check.
            for name in names:
                if manifest(source_root / name) != sources[name] or manifest(targets[name]) != before[name]:
                    raise PackageSyncError('Package inputs or destination changed during preview; preview again: ' + name)
                destination(context, name)
            if not args.apply:
                plan.write_text(json.dumps(current, indent=2) + '\n', encoding='utf-8')
                os.chmod(plan, 0o600)
                for name in names:
                    print(name + ':', flush=True)
                    sys.stdout.buffer.write(previews[name])
                print('Preview saved; review changes before --apply. No files deleted and no build started.')
                return 0
            try:
                previous = json.loads(plan.read_text(encoding='utf-8'))
            except (OSError, ValueError):
                raise PackageSyncError('Run and review a successful package preview before --apply') from None
            if previous != current:
                raise PackageSyncError('Package selection, sources, destinations or preview changed; preview again')
            for name in names:
                if manifest(snapshot / name) != sources[name]:
                    raise PackageSyncError('Source snapshot changed; nothing more will be copied')
                destination(context, name)
                if manifest(targets[name]) != before[name]:
                    raise PackageSyncError('Package destination changed before copy; preview again: ' + name)
                run_rsync(args.rsync, snapshot / name, targets[name], dry_run=False)
                actual = manifest(targets[name])
                reject_extra(name, sources[name], actual)
                if hashes(actual) != hashes(sources[name]):
                    raise PackageSyncError('Package source/target hash sets differ after copy: ' + name)
            for name in names:
                if manifest(source_root / name) != sources[name]:
                    raise PackageSyncError('Copied reviewed snapshot, but repository sources changed; preview again: ' + name)
                destination(context, name)
                actual = manifest(targets[name])
                reject_extra(name, sources[name], actual)
                if hashes(actual) != hashes(sources[name]):
                    raise PackageSyncError('Package destination changed after copy: ' + name)
            plan.unlink()
            print('Verified ' + ', '.join(names) + '; no files deleted and no build started.')
            return 0
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        message = str(error) if isinstance(error, ValueError) else 'Package sync failed; check paths and the existing rsync executable'
        print(message, file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
