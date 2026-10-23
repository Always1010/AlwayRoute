"""Build pinned local sing-box rule sets on the build host, without installing tools.

Downloaded sources and compiled output must stay in ignored/private directories.
Use --fetch to permit downloads; otherwise all inputs must already be cached.
The output directory must be new, so a failed build cannot replace working data.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / 'config/routing/sources.lock.json'


def digest(data):
    return hashlib.sha256(data).hexdigest()


def cached_input(spec, cache, fetch):
    expected = spec['sha256']
    if not re.fullmatch(r'[0-9a-f]{64}', expected):
        raise ValueError('Invalid locked SHA-256')
    path = cache / expected
    if path.exists():
        data = path.read_bytes()
    elif fetch:
        if not re.fullmatch(r'https://raw\.githubusercontent\.com/[^/]+/[^/]+/[0-9a-f]{40}/.+', spec['url']):
            raise ValueError('Input URL must use an immutable HTTPS GitHub commit')
        with urllib.request.urlopen(spec['url'], timeout=45) as response:
            data = response.read(2 * 1024 * 1024 + 1)
        if len(data) > 2 * 1024 * 1024 or digest(data) != expected:
            raise ValueError('Downloaded input size or SHA-256 mismatch')
        path.write_bytes(data)
    else:
        raise ValueError('Locked input is not cached; use --fetch on the build host')
    if digest(data) != expected:
        raise ValueError('Cached input SHA-256 mismatch; cache was not replaced')
    return data


def validate_source(name, data):
    source = json.loads(data)
    if set(source) != {'version', 'rules'} or source['version'] != 2 or len(source['rules']) != 1:
        raise ValueError('Unexpected rule-set source format')
    rule = source['rules'][0]
    if name != 'domestic-domain' or set(rule) != {'domain', 'domain_suffix', 'domain_regex'}:
        raise ValueError('Unexpected domain rule-set fields')
    for field, values in rule.items():
        if not isinstance(values, list) or any(not isinstance(x, str) or not x for x in values):
            raise ValueError('Invalid rule-set values')
        if len(values) != len(set(values)):
            raise ValueError('Duplicate rule-set values')
    if set(rule['domain_suffix']) & {'com', 'net', 'org'}:
        raise ValueError('Unexpected global top-level suffix; review before importing')
    return {field: len(values) for field, values in rule.items()}


def build(lock, cache, output, core, fetch=False):
    if output.exists():
        raise ValueError('Choose a new output directory; existing output is never replaced')
    version = subprocess.run([str(core), 'version'], capture_output=True, text=True, check=True, timeout=15).stdout
    if not re.search(r'^sing-box version 1\.13\.21(?:-alwayroute-router)?\s*$', version, re.M):
        raise ValueError('Use the pinned sing-box 1.13.21 build-host CLI')
    cache.mkdir(parents=True, exist_ok=True)
    inputs = []
    for spec in lock['ruleSets']:
        data = cached_input(spec, cache, fetch)
        inputs.append((spec, data, validate_source(spec['name'], data)))
    license_data = cached_input(lock['ruleSetLicense'], cache, fetch)
    output.mkdir(parents=True)
    manifest = {'schema': 1, 'compilerVersion': '1.13.21', 'compilerSha256': digest(core.read_bytes()),
                'sourceLockSha256': digest(LOCK.read_bytes()), 'ruleSets': [], 'license': lock['ruleSetLicense']}
    # Keep source JSON beside the output for audit/reproduction, outside the install payload.
    sources = output / 'sources'
    sources.mkdir()
    for spec, data, counts in inputs:
        source = sources / (spec['name'] + '.json')
        source.write_bytes(data)
        target = output / (spec['name'] + '.srs')
        subprocess.run([str(core), 'rule-set', 'compile', str(source), '--output', str(target)], check=True, timeout=60)
        manifest['ruleSets'].append({**spec, 'counts': counts, 'file': target.name,
                                    'binarySha256': digest(target.read_bytes()), 'binaryBytes': target.stat().st_size})
    (output / 'LICENSE').write_bytes(license_data)
    (output / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sing-box', required=True, type=Path, help='Existing build-host 1.13.21 executable')
    parser.add_argument('--cache', type=Path, default=ROOT / '.local/routing-cache')
    parser.add_argument('--output', type=Path, required=True, help='Fresh private/ignored output directory')
    parser.add_argument('--fetch', action='store_true')
    args = parser.parse_args()
    for path in (args.cache.resolve(), args.output.resolve()):
        if path.is_relative_to(ROOT) and not path.is_relative_to(ROOT / '.local'):
            parser.error('Generated data must stay under .local or outside the repository')
    try:
        manifest = build(json.loads(LOCK.read_text(encoding='utf-8')), args.cache.resolve(),
                         args.output.resolve(), args.sing_box.resolve(), args.fetch)
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        parser.exit(1, str(error) + '\n')
    print(json.dumps({'ruleSets': [{k: x[k] for k in ('name', 'counts', 'binaryBytes', 'binarySha256')}
                                   for x in manifest['ruleSets']]}, indent=2))


if __name__ == '__main__':
    main()
