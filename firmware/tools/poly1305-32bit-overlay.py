"""Default-off historical Poly1305 experiment; no assembly or cache edits.

Use only with pinned x/crypto v0.48.0 / Go1.27.3. This adaptation has not
received upstream review. The old arithmetic is preserved verbatim apart
from identifiers. No network, installation, configuration or build side effects.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil


HISTORICAL_REVISION = 'bd318be0434a57050ed475e0f45c3dbb16c09c2e'
HISTORICAL_SHA256 = '017c015b4df791195634145bded2dcd805d451054e1cbb7a68f61d4e943f063f'
PATCH_SHA256 = '4a646f0a1a17a322f04e77733f307eb684aadd9276be0ae5a2d6eca3467b4f71'
INPUT_SHA256 = {
    'internal/poly1305/poly1305.go': 'c4b20ab7330e47ee155a775f69ae3b0e432c75d74ad005cf764228a69ddf6da6',
    'internal/poly1305/mac_noasm.go': 'f5308cd6f14bab1b00963eeae8137d63fc5452db7f7d49276a56f457bfd89d2d',
    'internal/poly1305/sum_generic.go': 'b0094a2895d5bda42dcaaf57c0b31fc914c3b6c6aa6237aab0100a6d78346933',
    'chacha20/chacha_generic.go': '34403e82b1387b4402b00ce30c1364508c333f4bdbe671321690c6ebaa8d3180',
    'chacha20/chacha_noasm.go': 'bbdb67ceb30ef13efc54e17935f47e00744b96754e03364e606d4f1f8f9085c1',
}
ADDED_SHA256 = {
    'internal/poly1305/sum_generic32_mipsle.go': '4d26a222f4b18a94132efdbf4e332c9536cda3fb973369a906eaf3a9206040f0',
    'internal/poly1305/mac_generic32_mipsle.go': 'a36f417fd8dc810cc8ca432dd9f973435ab722b512dd88c3ee0aaba6c4a298e9',
    'internal/poly1305/mac_constructor_default.go': '3e1a47468e2aceb0e649dfb9f6b3f77da38b959638ce2cfef8b28fea62c80b8d',
}
MODULE_SHA256 = 'c591925f226a3dd387d4b6023287760fbafdbd9175bed7c5c28ca498f7c2fce7'
UPSTREAM_TEST_SHA256 = '92898c3ec8e8047db2afd6ff46ec060445ecf84b9e062dc71e76f0af95d2da42'


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def checked_read(path, expected):
    data = path.read_bytes()
    if sha256(data) != expected:
        raise ValueError('Pinned input SHA-256 mismatch: ' + str(path))
    return data


def apply_exact_patch(patch, inputs):
    """Apply the pinned five-file unified diff with exact contexts and no fuzz."""
    lines = patch.decode('utf-8').splitlines(keepends=True)
    outputs = {}
    index = next(i for i, line in enumerate(lines) if line.startswith('--- '))
    allowed = set(ADDED_SHA256) | {'internal/poly1305/poly1305.go', 'internal/poly1305/mac_noasm.go'}
    while index < len(lines):
        old_name = lines[index][4:].strip()
        if not lines[index + 1].startswith('+++ b/'):
            raise ValueError('Invalid patch destination')
        name = lines[index + 1][6:].strip()
        if name in outputs or name not in allowed:
            raise ValueError('Unexpected/duplicate patch path: ' + name)
        old = [] if old_name == '/dev/null' else inputs[name].decode('utf-8').splitlines(keepends=True)
        if old_name not in ('/dev/null', 'a/' + name):
            raise ValueError('Unexpected patch source')
        index += 2
        result, cursor = [], 0
        while index < len(lines) and lines[index].startswith('@@ '):
            match = re.fullmatch(r'@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@\n', lines[index])
            if not match:
                raise ValueError('Invalid hunk header')
            start, count, _, new_count = (int(v) if v is not None else 1 for v in match.groups())
            position = start - 1 if start else 0
            if position < cursor:
                raise ValueError('Overlapping patch hunks')
            result.extend(old[cursor:position])
            cursor = position
            index += 1
            removed = inserted = 0
            while index < len(lines) and lines[index][0] in ' +-':
                if lines[index].startswith('--- '):
                    break
                kind, content = lines[index][0], lines[index][1:]
                if kind != '+':
                    if cursor >= len(old) or old[cursor] != content:
                        raise ValueError('Exact patch context mismatch: ' + name)
                    cursor += 1
                    removed += 1
                if kind != '-':
                    result.append(content)
                    inserted += 1
                index += 1
            if (removed, inserted) != (count, new_count):
                raise ValueError('Patch hunk length mismatch: ' + name)
        result.extend(old[cursor:])
        outputs[name] = ''.join(result).encode('utf-8')
    if set(outputs) != allowed:
        raise ValueError('Unexpected patch file set')
    for name, expected in ADDED_SHA256.items():
        if sha256(outputs[name]) != expected:
            raise ValueError('Pinned added file changed: ' + name)
    # Reverse only the documented names/build tag and recover the old file hash.
    original = outputs['internal/poly1305/sum_generic32_mipsle.go'].decode('utf-8')
    original = original.replace('//go:build mipsle && gc && !purego\n\n', '', 1)
    names = {name + '32': name for name in (
        'sumGeneric', 'newMACGeneric', 'macGeneric', 'updateGeneric', 'finalizeGeneric')}
    original = re.sub(r'\b(?:' + '|'.join(names) + r')\b', lambda m: names[m[0]], original)
    if sha256(original.encode('utf-8')) != HISTORICAL_SHA256:
        raise ValueError('Historical arithmetic changed beyond identifier renames')
    expected_api = inputs['internal/poly1305/poly1305.go'].replace(
        b'initialize(key, &m.macState)', b'm.mac = newMAC(key)', 1)
    if outputs['internal/poly1305/poly1305.go'] != expected_api:
        raise ValueError('Unexpected public API change beyond constructor hook')
    return outputs


def prepare_overlay(module_root, goroot, stage, include_tests=False):
    """Copy a pinned module to new stage; return {Replace: ...} for Go.

    Main-module builds need a temporary -modfile replacing golang.org/x/crypto
    with stage/module. The original module cache/GOROOT are never modified.
    --include-tests adds MIPS-only fixture wiring and module/vendor coverage.
    Do not merge this overlay with the separate 003 assembly experiment.
    """
    module_root, goroot, stage = (Path(p).resolve() for p in (module_root, goroot, stage))
    vendor_root = goroot / 'src/vendor/golang.org/x/crypto'
    if stage.exists() or any(stage.is_relative_to(p) for p in (module_root, goroot)):
        raise ValueError('Choose a fresh stage outside module cache and GOROOT')
    checked_read(module_root / 'go.mod', MODULE_SHA256)
    if (goroot / 'VERSION').read_text(encoding='utf-8').splitlines()[0] != 'go1.27.3':
        raise ValueError('Expected pinned Go1.27.3 GOROOT')
    if any(p.is_symlink() for p in module_root.rglob('*')):
        raise ValueError('Unexpected module source symlink')
    firmware = Path(__file__).resolve().parents[1]
    patch = checked_read(firmware / 'openwrt/patches/004-poly1305-mipsle-32bit-experimental.patch', PATCH_SHA256)
    replacements, generated = {}, {}
    for label, root in (('module', module_root), ('stdlib-vendor', vendor_root)):
        inputs = {name: checked_read(root / name, digest) for name, digest in INPUT_SHA256.items()}
        for name in ADDED_SHA256:
            if (root / name).exists():
                raise ValueError('Unexpected candidate file: ' + str(root / name))
        for name, data in apply_exact_patch(patch, inputs).items():
            target = stage / 'overrides' / label / name
            virtual = stage / 'module' if label == 'module' else root
            replacements[str(virtual / name)] = str(target)
            generated[target] = data
    if include_tests:
        upstream = checked_read(module_root / 'internal/poly1305/poly1305_test.go', UPSTREAM_TEST_SHA256)
        old = b'\t\th := New(&key)\n\t\tif s := v.InitialState(); s != [3]uint64{0, 0, 0} {\n\t\t\th.macState.h = s\n\t\t}'
        new = b'\t\th := New(&key)\n\t\tif s := v.InitialState(); s != [3]uint64{0, 0, 0} {\n\t\t\talwayRouteSetLegacyInitialState(h, s)\n\t\t}'
        if upstream.count(old) != 1:
            raise ValueError('Unexpected upstream initial-state test wiring')
        fixture = (firmware / 'tests/poly1305-32bit/legacy_fixture_test.go').read_bytes()
        differential = (firmware / 'tests/crypto-assembly/poly1305_differential_test.go').read_bytes().replace(
            b'TestAlwayRouteAssemblyDifferential', b'TestAlwayRouteLegacyDifferential')
        for label, root in (('module', stage / 'module'), ('stdlib-vendor', vendor_root)):
            for package in ('internal/poly1305', 'chacha20poly1305'):
                for original in (module_root / package).glob('*_test.go'):
                    if label == 'module' and original.name != 'poly1305_test.go':
                        continue
                    data = upstream.replace(old, new) if original.name == 'poly1305_test.go' else original.read_bytes()
                    target = stage / 'tests' / label / package / original.name
                    generated[target] = data
                    replacements[str(root / package / original.name)] = str(target)
            for name, data in (('alwayroute_legacy_fixture_test.go', fixture),
                               ('alwayroute_legacy_differential_test.go', differential)):
                target = stage / 'tests' / label / 'internal/poly1305' / name
                generated[target] = data
                replacements[str(root / 'internal/poly1305' / name)] = str(target)
    stage.mkdir(parents=True)
    shutil.copytree(module_root, stage / 'module', copy_function=shutil.copyfile)
    for target, data in generated.items():
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    overlay = {'Replace': replacements}
    (stage / 'overlay.json').write_text(json.dumps(overlay, indent=2) + '\n', encoding='utf-8')
    metadata = {'experimental': True, 'production_accepted': False,
                'historical_revision': HISTORICAL_REVISION, 'historical_sha256': HISTORICAL_SHA256,
                'adaptation_review': 'not reviewed upstream; historical source approval is not adaptation approval',
                'patch_sha256': PATCH_SHA256, 'input_sha256': INPUT_SHA256,
                'module_go_mod_sha256': MODULE_SHA256,
                'module_replace': {'golang.org/x/crypto': str(stage / 'module')},
                'candidate': 'MIPSLE gc non-purego, historical 26-bit Poly1305; current ChaCha; no added assembly',
                'output_sha256': {str(p.relative_to(stage)): sha256(data) for p, data in generated.items()}}
    (stage / 'poly1305-32bit-experiment.json').write_text(json.dumps(metadata, indent=2) + '\n', encoding='utf-8')
    return overlay


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--module-root', type=Path, required=True)
    parser.add_argument('--goroot', type=Path, required=True)
    parser.add_argument('--stage', type=Path, required=True)
    parser.add_argument('--include-tests', action='store_true')
    args = parser.parse_args()
    prepare_overlay(args.module_root, args.goroot, args.stage, args.include_tests)
    print(args.stage.resolve() / 'overlay.json')
