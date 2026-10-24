"""Check the real pinned resource patch and standard/TLS overlay provenance.

Python only. Reads an explicitly selected pinned source tree; all mutations use
temporary output files. Crypto variants also use test_crypto_provenance.py.
"""
import argparse
import copy
import importlib.util
import json
from pathlib import Path
import sys
import tempfile

TOOLS = Path(__file__).resolve().parents[2] / 'firmware/tools'
sys.path.insert(0, str(TOOLS))


def module(name, filename):
    spec = importlib.util.spec_from_file_location(name, TOOLS / filename)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    args = parser.parse_args()
    source = args.source.resolve()
    helper = module('resource_fixes', 'resource-fixes-overlay.py')
    tls = module('tls_sessions', 'tls-session-overlay.py')
    inspector = module('inspector', 'inspect-image.py')
    embedded = '\tdep\tgolang.org/x/crypto\tv0.48.0\th1:/VRzVqiRSggnhY7gNRxPauEQ5Drw9haKdM0jqfcCFts=\n'
    checks = 0

    def verify(info):
        def check(name, ok):
            if not ok:
                raise ValueError(name)
        inspector.validate_crypto_provenance(info, embedded, b'', None, source, check)

    def rejected(info, expected):
        nonlocal checks
        try:
            verify(info)
        except ValueError as error:
            assert str(error) == expected, (str(error), expected)
        else:
            raise AssertionError('Accepted tampered provenance: ' + expected)
        checks += 1

    with tempfile.TemporaryDirectory(prefix='resource-provenance-') as temporary:
        for with_tls in (False, True):
            stage = Path(temporary) / ('tls' if with_tls else 'standard')
            overlay = {'Replace': {}}
            info = {'resource_fixes': helper.add_overlay(source, stage, overlay)}
            if with_tls:
                info['tls_session_cache'] = tls.add_overlay(source, stage, overlay)
            overlay_path = stage / 'overlay.json'
            overlay_path.write_text(json.dumps(overlay))
            info['command'] = ['go', 'build', '-overlay=' + str(overlay_path)]
            verify(info)
            checks += 1
            wrong = copy.deepcopy(info)
            wrong['resource_fixes']['patch_sha256'] = '0' * 64
            rejected(wrong, 'core_resource_fixes_manifest')
            wrong = copy.deepcopy(info)
            del wrong['resource_fixes']
            rejected(wrong, 'core_no_explicit_overlay')
            replacement = stage / 'resource-tproxy.go'
            original = replacement.read_bytes()
            replacement.write_bytes(original.replace(b'\t\t\t\tconn.Close()\n', b''))
            rejected(info, 'core_resource_fixes_replacement')
            replacement.write_bytes(original)
            extra = copy.deepcopy(overlay)
            extra['Replace'][str(source / 'unreviewed.go')] = str(replacement)
            overlay_path.write_text(json.dumps(extra))
            rejected(info, 'core_no_explicit_overlay')
            overlay_path.write_text(json.dumps(overlay))
            duplicate = copy.deepcopy(info)
            duplicate['command'].append('-overlay=' + str(overlay_path))
            rejected(duplicate, 'core_resource_fixes_overlay_argument')
    print('PASS', checks, 'resource provenance checks (standard and TLS); no source-tree edits')


if __name__ == '__main__':
    main()
