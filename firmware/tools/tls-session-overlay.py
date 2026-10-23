"""Pinned, opt-in TLS session resumption; never edits upstream sources or caches."""
import difflib
import hashlib
from pathlib import Path

SOURCE = 'common/tls/std_client.go'
INPUT_SHA256 = 'eaf0e0dafd10b8ed15733625ce448248680a5afe9dc4358f7df0725685d5d3ac'
CAPACITY = 4


def patched_source(source):
    original = (Path(source) / SOURCE).read_bytes()
    if hashlib.sha256(original).hexdigest() != INPUT_SHA256:
        raise ValueError('TLS client differs from pinned sing-box 1.13.21')
    anchor = '\ttlsConfig.RootCAs = adapter.RootPoolFromContext(ctx)\n'
    extra = ('\t// Keep tickets within this outbound\'s TLS configuration and bound memory.\n'
             '\t// This enables ordinary session resumption, not TLS early data.\n'
             '\ttlsConfig.ClientSessionCache = tls.NewLRUClientSessionCache(4)\n')
    text = original.decode('utf-8')
    if text.count(anchor) != 1:
        raise ValueError('Ambiguous TLS session cache patch context')
    updated = text.replace(anchor, anchor + extra)
    patch = Path(__file__).parents[1] / 'openwrt/patches/010-sing-box-tls-session-cache.patch'
    diff = ''.join(difflib.unified_diff(text.splitlines(True), updated.splitlines(True),
                                      fromfile='a/' + SOURCE, tofile='b/' + SOURCE))
    if patch.read_text(encoding='utf-8') != diff:
        raise ValueError('TLS session cache patch differs from the reviewed transformation')
    return updated.encode('utf-8'), hashlib.sha256(patch.read_bytes()).hexdigest()


def add_overlay(source, stage, overlay):
    """Add one verified replacement to a fresh or existing crypto overlay stage."""
    data, patch_digest = patched_source(source)
    target = str((Path(source) / SOURCE).resolve())
    if target in overlay.get('Replace', {}):
        raise ValueError('TLS source already replaced by another overlay')
    destination = Path(stage).resolve() / 'tls-session-std_client.go'
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open('xb') as handle:
        handle.write(data)
    overlay.setdefault('Replace', {})[target] = str(destination)
    return {'capacity': CAPACITY, 'source_sha256': INPUT_SHA256,
            'patch_sha256': patch_digest, 'output_sha256': hashlib.sha256(data).hexdigest()}


def validate_overlay(source, overlay, metadata, check):
    data, digest = patched_source(source)
    expected = {'capacity': CAPACITY, 'source_sha256': INPUT_SHA256,
                'patch_sha256': digest, 'output_sha256': hashlib.sha256(data).hexdigest()}
    check('core_tls_session_cache_manifest', metadata == expected)
    target = str((Path(source) / SOURCE).resolve())
    replacement = overlay.get('Replace', {}).get(target)
    check('core_tls_session_cache_replacement', isinstance(replacement, str)
          and Path(replacement).is_absolute() and Path(replacement).is_file()
          and not Path(replacement).is_symlink() and Path(replacement).read_bytes() == data)
    return target
