"""Prepare a pinned, default-off VMess framing I/O candidate in a fresh stage.

No downloads, cache edits or compiler settings. The caller supplies the existing
sing-vmess module and uses module_replace with its isolated -modfile.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import stat


INPUT_SHA256 = 'de6d2412041e7e75af8a995532dc71fcb0222ae87c080fb121a613411211432a'
MODULE_SHA256 = '9c678f70449c52c57b1bf6dc40ac5bf55c0a61e3336a8dd0d082aa352e510471'
SOURCE_NAME = 'chunk_length_stream.go'
WS_MODULE_SHA256 = 'ecb9a4a688051d981c0e4cfd13579dcf8806aa727303583944b2451e1fbfc9fc'
WS_INPUT_SHA256 = {
    'read.go': '7cb309a436a35103c32f0fcdef5c9b4e01b12e541307df4cd1ef5b3b3bfead01',
    'wsutil/reader.go': '12edbc87228c58eb45f77302ef5ddaebc15e8f9e16fda2536bb3fffd6fecc051',
}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def checked_read(path, expected):
    data = path.read_bytes()
    if digest(data) != expected:
        raise ValueError('Pinned input SHA-256 mismatch: ' + str(path))
    return data


def apply_patch(original, patch, source_name=SOURCE_NAME):
    """Apply only the single expected file with exact contexts, never fuzz."""
    lines = patch.decode('utf-8').splitlines(keepends=True)
    if lines[:2] != ['--- a/' + source_name + '\n', '+++ b/' + source_name + '\n']:
        raise ValueError('Unexpected patch paths')
    old = original.decode('utf-8').splitlines(keepends=True)
    result, cursor, index = [], 0, 2
    while index < len(lines):
        match = re.fullmatch(r'@@ -(\d+),(\d+) \+(\d+),(\d+) @@\n', lines[index])
        if not match:
            raise ValueError('Invalid hunk header')
        start, count, new_start, new_count = map(int, match.groups())
        position = start - 1
        if position < cursor:
            raise ValueError('Overlapping patch hunks')
        result.extend(old[cursor:position])
        if len(result) != new_start - 1:
            raise ValueError('Unexpected new hunk position')
        cursor, removed, added = position, 0, 0
        index += 1
        while index < len(lines) and not lines[index].startswith('@@ '):
            kind, content = lines[index][0], lines[index][1:]
            if kind not in ' +-':
                raise ValueError('Invalid patch line')
            if kind != '+':
                if cursor >= len(old) or old[cursor] != content:
                    raise ValueError('Exact patch context mismatch')
                cursor += 1
                removed += 1
            if kind != '-':
                result.append(content)
                added += 1
            index += 1
        if (removed, added) != (count, new_count):
            raise ValueError('Patch hunk length mismatch')
    result.extend(old[cursor:])
    return ''.join(result).encode('utf-8')


def prepare_overlay(module_root, stage, include_tests=False):
    module_root, stage = Path(module_root).resolve(), Path(stage).resolve()
    if stage.exists() or stage.is_relative_to(module_root):
        raise ValueError('Choose a fresh stage outside the source module')
    checked_read(module_root / 'go.mod', MODULE_SHA256)
    original = checked_read(module_root / SOURCE_NAME, INPUT_SHA256)
    if any(p.is_symlink() for p in module_root.rglob('*')):
        raise ValueError('Unexpected source symlink')
    firmware = Path(__file__).resolve().parents[1]
    patch = (firmware / 'openwrt/patches/005-vmess-framing-io-experimental.patch').read_bytes()
    modified = apply_patch(original, patch)
    stage.mkdir(parents=True)
    shutil.copytree(module_root, stage / 'module', copy_function=shutil.copyfile)
    # copytree preserves Go's read-only module-cache directory modes.
    # Make only our new copy writable so tests/new generated files can be added.
    for directory in [stage / 'module', *(p for p in (stage / 'module').rglob('*') if p.is_dir())]:
        directory.chmod(directory.stat().st_mode | stat.S_IWUSR)
    (stage / 'module' / SOURCE_NAME).write_bytes(modified)
    if include_tests:
        for source in (firmware / 'tests/io-path').glob('*_test.go'):
            shutil.copyfile(source, stage / 'module' / source.name)
    metadata = {
        'experimental': True, 'production_accepted': False,
        'candidate': 'VMess stream chunk reader: reuse 2-byte scratch and skip zero padding copy',
        'input_sha256': INPUT_SHA256, 'module_go_mod_sha256': MODULE_SHA256,
        'patch_sha256': digest(patch), 'output_sha256': digest(modified),
        'module_replace': {'github.com/sagernet/sing-vmess': str(stage / 'module')},
    }
    (stage / 'io-path-experiment.json').write_text(json.dumps(metadata, indent=2) + '\n', encoding='utf-8')
    return metadata


def prepare_ws_overlay(module_root, stage, include_tests=False):
    """Prepare a separate ws replacement, composable with the VMess candidate."""
    module_root, stage = Path(module_root).resolve(), Path(stage).resolve()
    if stage.exists() or stage.is_relative_to(module_root):
        raise ValueError('Choose a fresh stage outside the source module')
    checked_read(module_root / 'go.mod', WS_MODULE_SHA256)
    inputs = {name: checked_read(module_root / name, sha) for name, sha in WS_INPUT_SHA256.items()}
    if any(p.is_symlink() for p in module_root.rglob('*')):
        raise ValueError('Unexpected source symlink')
    firmware = Path(__file__).resolve().parents[1]
    patch = (firmware / 'openwrt/patches/007-ws-header-scratch-experimental.patch').read_bytes()
    chunks = re.split(rb'(?=^--- a/)', patch, flags=re.MULTILINE)
    outputs = {}
    for chunk in chunks:
        if not chunk:
            continue
        name = chunk.splitlines()[0][6:].decode('utf-8')
        if name not in inputs or name in outputs:
            raise ValueError('Unexpected/duplicate patch path')
        outputs[name] = apply_patch(inputs[name], chunk, name)
    if outputs.keys() != inputs.keys():
        raise ValueError('Incomplete patch file set')
    stage.mkdir(parents=True)
    shutil.copytree(module_root, stage / 'module', copy_function=shutil.copyfile)
    for directory in [stage / 'module', *(p for p in (stage / 'module').rglob('*') if p.is_dir())]:
        directory.chmod(directory.stat().st_mode | stat.S_IWUSR)
    for name, data in outputs.items():
        (stage / 'module' / name).write_bytes(data)
    if include_tests:
        test_root = firmware / 'tests/io-path/ws'
        for source in test_root.rglob('*_test.go'):
            shutil.copyfile(source, stage / 'module' / source.relative_to(test_root))
    metadata = {
        'experimental': True, 'production_accepted': False,
        'candidate': 'WebSocket frame header: reuse caller-owned 12-byte scratch',
        'input_sha256': WS_INPUT_SHA256, 'module_go_mod_sha256': WS_MODULE_SHA256,
        'patch_sha256': digest(patch),
        'output_sha256': {name: digest(data) for name, data in outputs.items()},
        'module_replace': {'github.com/sagernet/ws': str(stage / 'module')},
    }
    (stage / 'io-path-experiment.json').write_text(json.dumps(metadata, indent=2) + '\n', encoding='utf-8')
    return metadata


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--module-root', required=True)
    parser.add_argument('--stage', required=True)
    parser.add_argument('--include-tests', action='store_true')
    parser.add_argument('--candidate', choices=('vmess-framing', 'ws-header'), default='vmess-framing')
    args = parser.parse_args()
    prepare = prepare_ws_overlay if args.candidate == 'ws-header' else prepare_overlay
    print(json.dumps(prepare(args.module_root, args.stage, args.include_tests), indent=2))
