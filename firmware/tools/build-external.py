"""Build/check optional pure AlwayRoute packages in an existing OpenWrt tree/SDK.

Does not install tools, change .config, select a board, clean,
flash or connect to devices. Synchronize and review package sources first.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
PACKAGES = ('alwayroute-external-forwarding', 'alwayroute-external-manager', 'luci-app-alwayroute-external')
FORBIDDEN = ('alwayroute-core', 'alwayroute-manager', 'alwayroute-forwarding', 'luci-app-alwayroute')


def staging():
    spec = importlib.util.spec_from_file_location('external_stage', ROOT /
        'firmware/openwrt/alwayroute-external-manager/tools/stage-files.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def inputs(tree):
    tree = Path(tree).absolute()
    if tree.resolve() != tree or not (tree / 'include/package.mk').is_file() or not (tree / '.config').is_file():
        raise ValueError('Choose an existing real OpenWrt source/SDK with a reviewed .config')
    lines = set((tree / '.config').read_text().splitlines())
    for name in PACKAGES:
        if not any('CONFIG_PACKAGE_' + name + '=' + selection in lines for selection in ('y', 'm')):
            raise ValueError('Select external package and run make defconfig first: ' + name)
    for name in FORBIDDEN:
        if any('CONFIG_PACKAGE_' + name + '=' + selection in lines for selection in ('y', 'm')):
            raise ValueError('Pure recipe refuses selected local-mode package: ' + name)
    for feature in ('NSLOOKUP', 'FEATURE_NSLOOKUP_BIG', 'FEATURE_NSLOOKUP_LONG_OPTIONS', 'LONG_OPTS'):
        if 'CONFIG_BUSYBOX_CONFIG_' + feature + '=y' not in lines:
            raise ValueError('Reviewed nslookup feature missing: ' + feature)
    stage = staging()
    identities = {}
    for name in PACKAGES:
        local = ROOT / 'firmware/openwrt' / name
        copied = tree / 'package' / name
        for relative in ('Makefile', 'payload.json'):
            if not (copied / relative).is_file() or sha(copied / relative) != sha(local / relative):
                raise ValueError('Synchronize reviewed external package source first: ' + name)
        manifest = stage.payload(local / 'payload.json')
        for entry in manifest['files']:
            source = tree / 'package' / entry['source']
            if source.resolve() != source or not source.is_file() or sha(source) != sha(ROOT / 'firmware/openwrt' / entry['source']):
                raise ValueError('Shared package source differs: ' + entry['source'])
        identities[name] = {'manifestSha256': sha(local / 'payload.json'), 'makefileSha256': sha(local / 'Makefile'),
                            'sourceFiles': {entry['source']: sha(tree / 'package' / entry['source']) for entry in manifest['files']}}
    helper = 'alwayroute-external-manager/tools/stage-files.py'
    if sha(tree / 'package' / helper) != sha(ROOT / 'firmware/openwrt' / helper):
        raise ValueError('Shared staging tool differs; synchronize source again')
    return tree, identities


def inspect(tree):
    stage = staging()
    result = {}
    for name in PACKAGES:
        manifest = stage.payload(ROOT / 'firmware/openwrt' / name / 'payload.json')
        roots = list((tree / 'build_dir').glob('*/' + name + '-*/.pkgdir/' + name))
        if len(roots) != 1:
            raise ValueError('Expected one built payload directory for ' + name)
        root = roots[0]
        if root.resolve() != root:
            raise ValueError('Built payload path contains a link')
        expected = {entry['path'] for entry in manifest['files']}
        actual = set()
        for path in root.rglob('*'):
            if path.is_symlink() or not (path.is_file() or path.is_dir()):
                raise ValueError('Unexpected payload link or special file')
            if path.is_file():
                actual.add(path.relative_to(root).as_posix())
        if actual != expected:
            raise ValueError('Built package file allowlist mismatch: ' + name)
        for entry in manifest['files']:
            path = root / entry['path']
            if sha(path) != sha(tree / 'package' / entry['source']) or (path.stat().st_mode & 0o7777) != int(entry['mode'], 8):
                raise ValueError('Built package content/mode differs: ' + entry['path'])
        # The package builder's generated metadata records resolved runtime deps.
        controls = list(root.parent.parent.glob('ipkg-*/' + name + '/CONTROL/control'))
        if not controls:
            # APK output keeps its dependency declaration in the staging metadata.
            metadata = tree / 'tmp/.packageinfo'
            text = metadata.read_text() if metadata.is_file() else ''
            blocks = [b for b in text.split('\n\n') if '\nPackage: ' + name + '\n' in '\n' + b + '\n']
            if len(blocks) != 1:
                raise ValueError('Missing generated dependency metadata: ' + name)
            control = blocks[0]
        else:
            control = controls[0].read_text()
        dependencies = next((line.split(':', 1)[1] for line in control.splitlines() if line.startswith('Depends:')), '')
        if not dependencies:
            raise ValueError('Missing dependency declaration: ' + name)
        if any(('+' + dependency in dependencies or dependency in dependencies.replace(',', ' ').split()) for dependency in FORBIDDEN):
            raise ValueError('Local-mode dependency leaked into external package: ' + name)
        if any(token in dependencies for token in ('uclient-fetch', 'libuclient', 'ucode-mod-digest', 'alwayroute-input')):
            raise ValueError('Legacy downloader/rule dependency leaked: ' + name)
        artifacts = sorted(str(p.relative_to(tree)) for extension in ('apk', 'ipk')
                           for p in (tree / 'bin/packages').glob('**/' + name + '*.' + extension))
        if not artifacts:
            raise ValueError('No packaged artifact found: ' + name)
        result[name] = {'files': len(actual), 'dependencies': dependencies.strip(),
                        'artifacts': [{'path': p, 'sha256': sha(tree / p)} for p in artifacts]}
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tree', type=Path, required=True)
    parser.add_argument('--jobs', type=int, default=1)
    parser.add_argument('--apply', action='store_true', help='Compile only the three external packages')
    parser.add_argument('--inspect', action='store_true', help='Check existing built package payloads without compiling')
    parser.add_argument('--output', type=Path, help='New report path; defaults to stdout')
    args = parser.parse_args(argv)
    try:
        if not 1 <= args.jobs <= 16 or args.apply and args.inspect:
            raise ValueError('Use jobs 1..16 and choose either --apply or --inspect')
        if args.output and (args.output.exists() or args.output.is_symlink() or not args.output.parent.is_dir()):
            raise ValueError('Choose a new report in an existing directory before building')
        tree, identities = inputs(args.tree)
        commands = [['make', '-j' + str(args.jobs), 'package/' + name + '/compile', 'V=s'] for name in PACKAGES]
        result = {'scope': 'optional-alwayroute-openwrt-external-packages', 'apply': args.apply,
                  'sourceManifests': identities, 'commands': commands}
        if args.apply:
            for command in commands:
                subprocess.run(command, cwd=tree, check=True, timeout=1800)
        if args.apply or args.inspect:
            result['packages'] = inspect(tree)
        data = json.dumps(result, indent=2) + '\n'
        if args.output:
            with args.output.open('x', encoding='utf-8') as stream:
                stream.write(data)
            args.output.chmod(0o600)
        else:
            print(data, end='')
        return 0
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        print(str(error), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
