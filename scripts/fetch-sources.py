"""List or fetch pinned upstream source snapshots without installing software."""

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import tarfile
import urllib.request


ROOT = Path(__file__).resolve().parent.parent
LOCK = ROOT / 'firmware/sources.lock.json'
MARKER = '.alwayroute-source.json'


def object_id(kind, data):
    return hashlib.sha1(f'{kind} {len(data)}\0'.encode() + data).digest()


def source_tree(entries):
    root = {}
    for name, (mode, data) in entries.items():
        parts = name.split('/')
        node = root
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = (mode, object_id('blob', data))

    def tree_id(node):
        content = bytearray()
        for name in sorted(node, key=lambda n: n.encode() + (b'/' if isinstance(node[n], dict) else b'')):
            value = node[name]
            mode, oid = ('40000', tree_id(value)) if isinstance(value, dict) else value
            content.extend(mode.encode() + b' ' + name.encode() + b'\0' + oid)
        return object_id('tree', content)

    return tree_id(root).hex()


def read_archive(path, source):
    entries = {}
    with tarfile.open(path) as archive:
        members = [m for m in archive.getmembers() if not m.isdir()]
        paths = [PurePosixPath(m.name) for m in members]
        if any(p.is_absolute() or '..' in p.parts or '\\' in str(p) or ':' in str(p) for p in paths):
            raise ValueError('Unsafe source archive paths')
        strip = int(bool(paths) and all(len(p.parts) > 1 and p.parts[0] == paths[0].parts[0] for p in paths))
        for member, path in zip(members, paths):
            name = '/'.join(path.parts[strip:])
            if not name or name in entries or name == MARKER:
                raise ValueError(f'Duplicate or reserved source path: {name}')
            if member.issym():
                mode, data = '120000', member.linkname.encode()
            elif member.isfile():
                mode = '100755' if member.mode & 0o111 else '100644'
                data = archive.extractfile(member).read()
            else:
                raise ValueError(f'Unsupported source entry: {name}')
            entries[name] = (mode, data)
    actual = source_tree(entries)
    if actual != source['tree'] or len(entries) != source['file_count']:
        raise ValueError(f'{source["name"]}: archive differs from locked upstream tree ({actual})')
    return entries


def verify_directory(target, entries):
    found = set()
    for directory, directories, files in os.walk(target, followlinks=False):
        for name in list(directories):
            if (Path(directory) / name).is_symlink():
                directories.remove(name)
                files.append(name)
        for name in files:
            path = Path(directory) / name
            relative = path.relative_to(target).as_posix()
            if relative == MARKER:
                continue
            found.add(relative)
            if relative not in entries:
                raise ValueError(f'Extra local file; preserved without overwrite: {path}')
            mode, expected = entries[relative]
            if path.is_symlink():
                if mode != '120000':
                    raise ValueError(f'Unexpected local symlink: {path}')
                actual = os.readlink(path).encode()
            else:
                actual = path.read_bytes()
            if actual != expected:
                raise ValueError(f'Local changes found; preserved without overwrite: {path}')
            if os.name != 'nt' and mode != '120000':
                if bool(path.stat().st_mode & 0o111) != (mode == '100755'):
                    raise ValueError(f'Executable permission differs: {path}')
    if found != entries.keys():
        raise ValueError(f'Incomplete source directory; preserved without overwrite: {target}')


def fetch(source, destination, cache, verify_only):
    target = destination / source['name']
    marker = target / MARKER
    if marker.exists() and not verify_only:
        previous = json.loads(marker.read_text(encoding='utf-8'))
        if previous.get('tree') != source['tree']:
            raise ValueError(f'{target}: another version exists; choose a new --dest')
        print(f'{source["name"]}: already available at {target}; local edits preserved', flush=True)
        return
    if verify_only and not target.is_dir():
        raise ValueError(f'Source directory does not exist: {target}')
    archive = cache / (source['name'] + '-' + source['tree'] + '.tar.gz')
    if not archive.exists():
        if verify_only:
            raise ValueError(f'Cached archive missing: {archive}; fetch to a new --dest first')
        cache.mkdir(parents=True, exist_ok=True)
        temporary = archive.with_suffix('.part')
        print(f'{source["name"]}: downloading {source["archive"]}', flush=True)
        request = urllib.request.Request(source['archive'], headers={'User-Agent': 'AlwayRoute-source-fetch/1'})
        with urllib.request.urlopen(request, timeout=120) as response, temporary.open('wb') as stream:
            while block := response.read(1024 * 1024):
                stream.write(block)
        # Validate bytes and modes before trusting the download or writing sources.
        entries = read_archive(temporary, source)
        temporary.replace(archive)
    else:
        entries = read_archive(archive, source)
    if target.exists():
        verify_directory(target, entries)
    elif not verify_only:
        target.mkdir(parents=True)
        for name, (mode, data) in entries.items():
            path = target / name
            path.parent.mkdir(parents=True, exist_ok=True)
            if mode == '120000' and os.name != 'nt':
                path.symlink_to(data.decode())
            else:
                path.write_bytes(data)
                if os.name != 'nt':
                    path.chmod(0o755 if mode == '100755' else 0o644)
    if not verify_only:
        metadata = {k: source[k] for k in ('name', 'tree', 'file_count')}
        metadata['symlinks'] = {n: d.decode() for n, (m, d) in entries.items() if m == '120000'}
        metadata['executables'] = [n for n, (m, _) in entries.items() if m == '100755']
        marker.write_text(json.dumps(metadata, indent=2) + '\n', encoding='utf-8', newline='\n')
    print(f'{source["name"]}: verified {len(entries)} entries at {target}', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', nargs='?', default='list', choices=('list', 'fetch', 'verify'))
    parser.add_argument('components', nargs='*', help='openwrt, luci, packages, sing-box; default: all')
    parser.add_argument('--dest', type=Path, default=ROOT / '.local/sources')
    parser.add_argument('--cache', type=Path, default=ROOT / '.local/source-cache')
    args = parser.parse_args()
    sources = json.loads(LOCK.read_text(encoding='utf-8'))['sources']
    unknown = set(args.components) - {s['name'] for s in sources}
    if unknown:
        parser.error('Unknown components: ' + ', '.join(sorted(unknown)))
    for source in sources:
        if args.components and source['name'] not in args.components:
            continue
        if args.command == 'list':
            print(f'{source["name"]}: {source.get("commit", source.get("version"))}\n  {source["upstream"]}\n  local: {args.dest.resolve() / source["name"]}')
        else:
            fetch(source, args.dest.resolve(), args.cache.resolve(), args.command == 'verify')


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, tarfile.TarError) as exc:
        raise SystemExit(str(exc)) from exc
