"""Stage an explicit package payload from shared source files, without links."""
import argparse
import json
from pathlib import Path, PurePosixPath
import shutil


def relative(value):
    if not isinstance(value, str) or not value or value == '.':
        raise ValueError('Invalid package payload path')
    path = PurePosixPath(value)
    if (not isinstance(value, str) or path.is_absolute() or path.as_posix() != value
            or any(part in ('.', '..', '.local', '.git') for part in path.parts) or '\\' in value):
        raise ValueError('Invalid package payload path')
    return value


def payload(manifest):
    value = json.loads(Path(manifest).read_text(encoding='utf-8'))
    if value.get('schema') != 1 or not value.get('files'):
        raise ValueError('Invalid payload manifest')
    seen = set()
    for entry in value['files']:
        relative(entry['source']); relative(entry['path'])
        if entry['mode'] not in ('0644', '0755') or entry['path'] in seen:
            raise ValueError('Invalid payload mode or duplicate path')
        seen.add(entry['path'])
    return value


def stage(manifest, source_root, output):
    value = payload(manifest)
    source_root, output = Path(source_root).absolute(), Path(output).absolute()
    if source_root.resolve() != source_root or output.resolve() != output or output == source_root or source_root in output.parents:
        raise ValueError('Use real source and separate generated payload directories')
    expected = {entry['path'] for entry in value['files']}
    if output.exists():
        for path in output.rglob('*'):
            if path.is_symlink() or (path.is_file() and path.relative_to(output).as_posix() not in expected):
                raise ValueError('Unexpected generated payload; inspect before rebuilding')
    # Validate every source before writing any generated package file.
    for entry in value['files']:
        source = source_root / entry['source']
        if source.resolve() != source or not source.is_file() or source.is_symlink():
            raise ValueError('Package source is missing or linked: ' + entry['source'])
    output.mkdir(parents=True, exist_ok=True)
    for entry in value['files']:
        target = output / entry['path']
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source_root / entry['source'], target)
        target.chmod(int(entry['mode'], 8))
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--list-sources', action='store_true')
    parser.add_argument('--source-root', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if args.list_sources:
        print(' '.join(entry['source'] for entry in payload(args.manifest)['files']))
    else:
        if not args.source_root or not args.output:
            parser.error('--source-root and --output required when staging')
        stage(args.manifest, args.source_root, args.output)


if __name__ == '__main__':
    main()
