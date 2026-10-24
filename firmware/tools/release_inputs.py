"""Pinned public release inputs; no downloads or host configuration changes."""
import hashlib
import json
from pathlib import Path

from target_profile import load_device, relative_path

FIRMWARE = Path(__file__).resolve().parents[1]
RELEASE = FIRMWARE / 'release.json'
CI_HOST_PATCHES = ('openwrt/patches/012-ucode-host-digest-for-ci.patch',)


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_release():
    spec = json.loads(RELEASE.read_text(encoding='utf-8'))
    if (spec.get('schema_version') != 1 or spec.get('device') != 'xiaomi-4a-gigabit'
            or spec.get('crypto_backend') != 'standard-go'
            or spec.get('compiler_profile') != 'crypto-inline'
            or spec.get('go', {}).get('version') != '1.27.3'):
        raise ValueError('Unsupported release recipe')
    pgo = FIRMWARE / relative_path(spec['pgo']['path'])
    if not pgo.resolve().is_relative_to(FIRMWARE.resolve()) or sha256(pgo) != spec['pgo']['sha256']:
        raise ValueError('Release PGO differs from the reviewed input')
    load_device(spec['device'])
    return spec


def input_identity(device):
    """Bind a run to committed recipes, patches, rules and public PGO input."""
    spec = load_release()
    if device['id'] != spec['device']:
        raise ValueError('Release only supports the reviewed 4A recipe')
    paths = ['release.json', 'sources.lock.json', 'devices/' + device['id'] + '.json',
             *device['seed_files'], *device['patches'], *CI_HOST_PATCHES, spec['pgo']['path'],
             'openwrt/patches/011-sing-box-tproxy-close-failed-socket.patch']
    return {**{name: sha256(FIRMWARE / name) for name in paths},
            '../config/routing/sources.lock.json': sha256(FIRMWARE.parent / 'config/routing/sources.lock.json')}


def validate_release_core(info, inputs, manifest, context, device, check):
    spec = load_release()
    check('release_public_input_identity', manifest.get('inputs') == input_identity(device))
    check('release_device', manifest.get('device') == device['id'] == spec['device'])
    expected = json.loads((inputs / 'build-info.json').read_bytes())
    check('release_core_metadata_matches_input', info == expected)
    check('release_core_digest', sha256(inputs / 'sing-box') == info['input_elf_sha256'] == manifest.get('core_sha256'))
    check('release_pgo_digest', info.get('pgo_sha256') == spec['pgo']['sha256'])
    command = info.get('command', [])
    pgo = str((FIRMWARE / spec['pgo']['path']).resolve())
    check('release_pgo_selected', '-pgo' in command and command[command.index('-pgo') + 1] == pgo)
    check('release_compiler', info.get('go') == spec['go']['version'])
    # Import the existing compiler profile instead of maintaining another copy.
    import importlib.util
    module_spec = importlib.util.spec_from_file_location('release_core_builder', Path(__file__).with_name('build-core.py'))
    builder = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(builder)
    flags = ['all=-l'] + [p + '=' for p in builder.HOT_PACKAGES]
    check('release_compiler_profile', info.get('gcflags') == flags
          and [x for x in command if x.startswith('-gcflags=')] == ['-gcflags=' + x for x in flags])
    check('release_required_resource_fixes', isinstance(info.get('resource_fixes'), dict))
    check('release_crypto_backend', info.get('crypto_candidate') is None
          and not any(str(flag).startswith(('-modfile', '-asmflags')) for flag in command))
