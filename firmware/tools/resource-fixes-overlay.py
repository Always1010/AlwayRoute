"""Reproducible mandatory resource fixes for the pinned sing-box source."""
import argparse
import difflib
import hashlib
import json
from pathlib import Path

SOURCE = 'protocol/redirect/tproxy.go'
INPUT_SHA256 = '17602419da3f23ae84992065f52155034564b36be6679e9d4eb607302bf95e50'
PATCH = Path(__file__).parents[1] / 'openwrt/patches/011-sing-box-tproxy-close-failed-socket.patch'


def patched_source(source):
    original = (Path(source) / SOURCE).read_bytes()
    if hashlib.sha256(original).hexdigest() != INPUT_SHA256:
        raise ValueError('TProxy source differs from pinned sing-box 1.13.21')
    text = original.decode('utf-8')
    anchor = '\t\t\tif err != nil {\n\t\t\t\tw.conn = nil\n'
    if text.count(anchor) != 1:
        raise ValueError('Ambiguous TProxy resource fix context')
    updated = text.replace(anchor, '\t\t\tif err != nil {\n\t\t\t\tconn.Close()\n\t\t\t\tw.conn = nil\n')
    diff = ''.join(difflib.unified_diff(text.splitlines(True), updated.splitlines(True),
                                      fromfile='a/' + SOURCE, tofile='b/' + SOURCE))
    if PATCH.read_text(encoding='utf-8') != diff:
        raise ValueError('TProxy resource patch differs from the reviewed transformation')
    return updated.encode('utf-8'), hashlib.sha256(PATCH.read_bytes()).hexdigest()


def add_overlay(source, stage, overlay, *, include_tests=False):
    data, digest = patched_source(source)
    target = str((Path(source) / SOURCE).resolve())
    if target in overlay.get('Replace', {}):
        raise ValueError('TProxy source already replaced by another overlay')
    stage = Path(stage).resolve()
    stage.mkdir(parents=True, exist_ok=True)
    destination = stage / 'resource-tproxy.go'
    with destination.open('xb') as handle:
        handle.write(data)
    overlay.setdefault('Replace', {})[target] = str(destination)
    if include_tests:
        test = Path(__file__).parents[1] / 'tests/resource-fixes/tproxy_test.go'
        test_target = (Path(source) / SOURCE).with_name('alwayroute_resource_test.go').resolve()
        if test_target.exists() or str(test_target) in overlay['Replace']:
            raise ValueError('Resource test source already exists')
        overlay['Replace'][str(test_target)] = str(test.resolve())
    return {'source_sha256': INPUT_SHA256, 'patch_sha256': digest,
            'output_sha256': hashlib.sha256(data).hexdigest()}


def validate_overlay(source, overlay, metadata, check):
    data, digest = patched_source(source)
    expected = {'source_sha256': INPUT_SHA256, 'patch_sha256': digest,
                'output_sha256': hashlib.sha256(data).hexdigest()}
    check('core_resource_fixes_manifest', metadata == expected)
    target = str((Path(source) / SOURCE).resolve())
    replacement = overlay.get('Replace', {}).get(target)
    check('core_resource_fixes_replacement', isinstance(replacement, str)
          and Path(replacement).is_absolute() and Path(replacement).is_file()
          and not Path(replacement).is_symlink() and Path(replacement).read_bytes() == data)
    return target


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--stage', type=Path, required=True, help='Fresh stage outside the upstream tree')
    parser.add_argument('--include-tests', action='store_true')
    args = parser.parse_args()
    if args.stage.exists():
        parser.error('Resource overlay stage already exists')
    overlay = {'Replace': {}}
    manifest = add_overlay(args.source, args.stage, overlay, include_tests=args.include_tests)
    (args.stage / 'overlay.json').write_text(json.dumps(overlay, indent=2) + '\n')
    print(json.dumps(manifest))
