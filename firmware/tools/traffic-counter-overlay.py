"""Prepare a default-off exact traffic-counter overlay for sing-box 1.13.21.

Only a fresh stage is written. The upstream tree, Go runtime, module cache and
build tags remain unchanged. No installation, downloads or build side effects.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re


PACKAGE = 'experimental/clashapi/trafficontrol/'
PATCH_SHA256 = 'ae6409cc3df7bd35881212a1b166824593123dcc4be6248c86deaf1906ea557a'
INPUT_SHA256 = {
    PACKAGE + 'manager.go': '58712bde43bdf590ffcc7d016a19496b283d0e43b69eeb6c7355af4457971c37',
    PACKAGE + 'tracker.go': '3549c366ba6887f0191ca8ec091d2293870e5f23745774d20a9e371827e9986d',
}


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def checked_read(path, expected):
    data = path.read_bytes()
    if sha256(data) != expected:
        raise ValueError('Pinned input SHA-256 mismatch: ' + str(path))
    return data


def apply_exact_patch(patch, inputs):
    """Apply only the pinned three-file unified diff, without fuzz."""
    lines = patch.decode('utf-8').splitlines(keepends=True)
    outputs, index = {}, 0
    allowed = set(INPUT_SHA256) | {PACKAGE + 'counter.go'}
    while index < len(lines):
        if not lines[index].startswith('--- ') or not lines[index + 1].startswith('+++ b/'):
            raise ValueError('Invalid patch header')
        old_name, name = lines[index][4:].strip(), lines[index + 1][6:].strip()
        if name in outputs or name not in allowed:
            raise ValueError('Unexpected/duplicate patch path: ' + name)
        expected_old = 'a/' + name if name in inputs else '/dev/null'
        if old_name != expected_old:
            raise ValueError('Unexpected patch source: ' + old_name)
        old = inputs[name].decode('utf-8').splitlines(keepends=True) if name in inputs else []
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
    return outputs


def prepare_overlay(source, stage, include_tests=False):
    source, stage = (Path(p).resolve() for p in (source, stage))
    if stage.exists() or stage.is_relative_to(source) or source.is_relative_to(stage):
        raise ValueError('Choose a fresh stage outside the upstream source tree')
    if (source / PACKAGE / 'counter.go').exists():
        raise ValueError('Unexpected preexisting counter.go in upstream source')
    inputs = {name: checked_read(source / name, digest) for name, digest in INPUT_SHA256.items()}
    firmware = Path(__file__).resolve().parents[1]
    patch = checked_read(firmware / 'openwrt/patches/006-traffic-counter-mutex-experimental.patch', PATCH_SHA256)
    generated = apply_exact_patch(patch, inputs)
    if include_tests:
        generated[PACKAGE + 'alwayroute_counter_test.go'] = (firmware / 'tests/traffic-counters/counter_test.go').read_bytes()
    # Validate all input before creating stage. -overlay never mutates source.
    stage.mkdir(parents=True)
    replacements = {}
    for name, data in generated.items():
        target = stage / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        replacements[str(source / name)] = str(target)
    overlay = {'Replace': replacements}
    (stage / 'overlay.json').write_text(json.dumps(overlay, indent=2) + '\n', encoding='utf-8')
    metadata = {
        'experimental': True, 'production_accepted': False,
        'candidate': 'immediate int64 counters with independent sync.Mutex locks',
        'patch_sha256': PATCH_SHA256, 'input_sha256': INPUT_SHA256,
        'output_sha256': {name: sha256(data) for name, data in generated.items()},
        'validation': 'requires MIPS runtime and same-condition throughput/latency comparison',
    }
    (stage / 'traffic-counter-experiment.json').write_text(json.dumps(metadata, indent=2) + '\n', encoding='utf-8')
    return overlay


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--stage', type=Path, required=True)
    parser.add_argument('--include-tests', action='store_true')
    args = parser.parse_args()
    prepare_overlay(args.source, args.stage, args.include_tests)
    print(args.stage.resolve() / 'overlay.json')
