"""Explicit, experimental CL585755 overlay; never writes caches or GOROOT.

This unmerged upstream contribution has not received upstream crypto approval.
The MIPS32r1 assembly remains byte-identical to patch set 2. Poly1305's Go
declaration parameter is renamed msg -> D solely to match assembly operands
for asmdecl vet. The noasm constraints are rebased onto pinned current inputs.
No network access, compilation, toolchain installation, or default enablement.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil


REVISION = '45132dae57e76146e71cc1cda14e3a75dffe2457'
PATCH_SHA256 = 'c1eea9c8a0d98779a2465d2535a6204a5aeb5ce50cf7abe812e2dc5d7f25ab34'
INPUT_SHA256 = {
    'chacha20/chacha_noasm.go': 'bbdb67ceb30ef13efc54e17935f47e00744b96754e03364e606d4f1f8f9085c1',
    'chacha20/chacha_generic.go': '34403e82b1387b4402b00ce30c1364508c333f4bdbe671321690c6ebaa8d3180',
    'internal/poly1305/mac_noasm.go': 'f5308cd6f14bab1b00963eeae8137d63fc5452db7f7d49276a56f457bfd89d2d',
    'internal/poly1305/sum_generic.go': 'b0094a2895d5bda42dcaaf57c0b31fc914c3b6c6aa6237aab0100a6d78346933',
}
ADDED_SHA256 = {
    'chacha20/chacha_mipsle.go': '53d3279927b04eac98830a9be69b09684cbccf2ba410f8e8beed9a43e5acb1b2',
    'chacha20/chacha_mipsle.s': 'a4b6577214cec22bb3d5f235a36e41a274bf443d202433b5110d7d1fdc04b6c5',
    'internal/poly1305/sum_mipsle.go': '5a9ca210573fb1a45d50ae6fe59500b87bfce3d9a93201d00d27a48e12471562',
    'internal/poly1305/sum_mipsle.s': '3018e13391278103cc921f8866a5030154d0f27cfba8e53109a492329da70044',
}
MODULE_SHA256 = 'c591925f226a3dd387d4b6023287760fbafdbd9175bed7c5c28ca498f7c2fce7'


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def checked_read(path, expected):
    data = path.read_bytes()
    if sha256(data) != expected:
        raise ValueError('Pinned input SHA-256 mismatch: ' + str(path))
    return data


def apply_exact_patch(patch, inputs):
    """Apply only this hash-pinned six-file unified diff, without fuzz/tools."""
    lines = patch.decode('utf-8').splitlines(keepends=True)
    outputs = {}
    index = next(i for i, line in enumerate(lines) if line.startswith('--- '))
    while index < len(lines):
        old_name = lines[index][4:].strip()
        if not lines[index + 1].startswith('+++ b/'):
            raise ValueError('Invalid patch destination')
        name = lines[index + 1][6:].strip()
        if name in outputs or name not in set(ADDED_SHA256) | {
            'chacha20/chacha_noasm.go', 'internal/poly1305/mac_noasm.go'
        }:
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
    for name, expected in ADDED_SHA256.items():
        if sha256(outputs[name]) != expected:
            raise ValueError('Original upstream contribution changed: ' + name)
    original_glue = outputs['internal/poly1305/sum_mipsle.go'].replace(
        b'func update(state *macState, D []byte, padbit uint32)',
        b'func update(state *macState, msg []byte, padbit uint32)')
    if sha256(original_glue) != '992af1756b7fdc1927a26b50f82cc7e6fa7c6cd5603f5021f41eff57572ceedd':
        raise ValueError('Unexpected change beyond the declaration parameter rename')
    return outputs


def prepare_overlay(module_root, goroot, stage, include_tests=False):
    """Return Go's {Replace: ...}; source trees are verified and read only.

    module_root must be x/crypto v0.48.0, goroot must be Go1.27.3, and stage
    must be a new, caller-selected directory outside both input trees.
    The two input copies must have identical pinned glue/layout files. Go
    forbids overlays inside GOMODCACHE, so a module source snapshot is made
    at stage/module. Main builds must use a temporary -modfile with:
        replace golang.org/x/crypto => <absolute stage/module>
    """
    module_root, goroot, stage = (Path(p).resolve() for p in (module_root, goroot, stage))
    vendor_root = goroot / 'src/vendor/golang.org/x/crypto'
    if stage.exists() or any(stage.is_relative_to(p) for p in (module_root, goroot)):
        raise ValueError('Choose a fresh stage outside module cache and GOROOT')
    checked_read(module_root / 'go.mod', MODULE_SHA256)
    if (goroot / 'VERSION').read_text(encoding='utf-8').splitlines()[0] != 'go1.27.3':
        raise ValueError('Expected the pinned Go1.27.3 GOROOT')
    patch_path = Path(__file__).resolve().parents[1] / 'openwrt/patches/003-xcrypto-mipsle-assembly-experimental.patch'
    patch = checked_read(patch_path, PATCH_SHA256)
    replacements, generated = {}, {}
    if any(p.is_symlink() for p in module_root.rglob('*')):
        raise ValueError('Unexpected symlink in the module source snapshot')
    for label, root in (('module', module_root), ('stdlib-vendor', vendor_root)):
        inputs = {name: checked_read(root / name, digest) for name, digest in INPUT_SHA256.items()}
        for name in ADDED_SHA256:
            if (root / name).exists():
                raise ValueError('Unexpected existing assembly: ' + str(root / name))
        for name, data in apply_exact_patch(patch, inputs).items():
            target = stage / 'overrides' / label / name
            virtual_root = stage / 'module' if label == 'module' else root
            replacements[str(virtual_root / name)] = str(target)
            generated[target] = data
    if include_tests:
        test_root = Path(__file__).resolve().parents[1] / 'tests/crypto-assembly'
        # The Go distribution omits these upstream tests. Inject identical test
        # sources into its vendor packages so stdlib TLS's copy is tested too.
        for package in ('chacha20', 'internal/poly1305', 'chacha20poly1305'):
            for original in (module_root / package).glob('*_test.go'):
                target = stage / 'vendor-tests' / package / original.name
                logical = vendor_root / package / original.name
                if logical.exists():
                    raise ValueError('Unexpected existing vendor test: ' + str(logical))
                generated[target] = original.read_bytes()
                replacements[str(logical)] = str(target)
        for package, test in (('chacha20', 'chacha20_differential_test.go'),
                              ('internal/poly1305', 'poly1305_differential_test.go')):
            target = stage / 'tests' / test
            generated[target] = (test_root / test).read_bytes()
            replacements[str(stage / 'module' / package / 'alwayroute_assembly_differential_test.go')] = str(target)
            replacements[str(vendor_root / package / 'alwayroute_assembly_differential_test.go')] = str(target)
    stage.mkdir(parents=True)
    shutil.copytree(module_root, stage / 'module', copy_function=shutil.copyfile)
    for target, data in generated.items():
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    overlay = {'Replace': replacements}
    (stage / 'overlay.json').write_text(json.dumps(overlay, indent=2) + '\n', encoding='utf-8')
    metadata = {'experimental': True, 'production_accepted': False,
                'upstream_review_status': 'NEW / unmerged; no crypto reviewer approval',
                'revision': REVISION, 'patch_sha256': PATCH_SHA256,
                'module_replace': {'golang.org/x/crypto': str(stage / 'module')},
                'input_sha256': INPUT_SHA256, 'module_go_mod_sha256': MODULE_SHA256,
                'isa_path': 'MIPS32r1; no GOMIPS_r2/r5 assembler macro',
                'output_sha256': {str(p.relative_to(stage)): sha256(data) for p, data in generated.items()}}
    (stage / 'assembly-experiment.json').write_text(json.dumps(metadata, indent=2) + '\n', encoding='utf-8')
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
