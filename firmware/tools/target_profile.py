"""Device recipes and CPU settings, independent of private host environments.

Only repository device recipes are accepted by name. Adding a recipe does not
constitute runtime acceptance; unsupported image layouts are rejected explicitly.
"""
import argparse
import copy
import json
from pathlib import Path, PurePosixPath
import re

FIRMWARE = Path(__file__).resolve().parents[1]
DEFAULT_DEVICE = 'xiaomi-4a-gigabit'
ARCHITECTURES = {
    'mipsle-softfloat': {
        'go_env': {'GOOS': 'linux', 'GOARCH': 'mipsle', 'GOMIPS': 'softfloat', 'CGO_ENABLED': '0'},
        'description': 'linux/mipsle softfloat', 'elf_class': 1, 'elf_data': 1, 'elf_machine': 8,
    },
    'arm64': {
        'go_env': {'GOOS': 'linux', 'GOARCH': 'arm64', 'GOARM64': 'v8.0', 'CGO_ENABLED': '0'},
        'description': 'linux/arm64 v8.0', 'elf_class': 2, 'elf_data': 1, 'elf_machine': 183,
    },
    'amd64': {
        'go_env': {'GOOS': 'linux', 'GOARCH': 'amd64', 'GOAMD64': 'v1', 'CGO_ENABLED': '0'},
        'description': 'linux/amd64 v1', 'elf_class': 2, 'elf_data': 1, 'elf_machine': 62,
    },
}
GO_ARCH_OPTIONS = ('GOARCH', 'GOOS', 'GOARM', 'GOARM64', 'GOAMD64', 'GOMIPS', 'GOMIPS64',
                   'GOPPC64', 'GORISCV64', 'GOWASM')
CRYPTO_BACKENDS = {'poly1305-32', 'mipsle-asm', 'mipsle-asm-r2'}


def architecture(name):
    if name not in ARCHITECTURES:
        raise ValueError('Unknown CPU architecture recipe: ' + str(name))
    return copy.deepcopy(ARCHITECTURES[name])


def relative_path(value):
    if (not isinstance(value, str) or not value or '\\' in value or ':' in value
            or any(c in value for c in '\x00\r\n')):
        raise ValueError('Recipe paths must be relative POSIX paths')
    path = PurePosixPath(value)
    if path.is_absolute() or '..' in path.parts or path.as_posix() != value or value == '.':
        raise ValueError('Recipe path escapes its root or is not normalized')
    return value


def load_device(name=DEFAULT_DEVICE):
    if not isinstance(name, str) or not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', name):
        raise ValueError('Use a repository device recipe name, not a path')
    data = json.loads((FIRMWARE / 'devices' / (name + '.json')).read_text(encoding='utf-8'))
    fields = {'schema_version', 'id', 'name', 'architecture', 'target', 'board', 'excluded_boards',
              'seed_files', 'patches', 'image', 'required_packages', 'forbidden_packages', 'allowed_crypto_backends'}
    if not isinstance(data, dict) or set(data) != fields or type(data['schema_version']) is not int or data['schema_version'] != 1 or data['id'] != name:
        raise ValueError('Invalid device recipe fields, identity or schema version')
    architecture(data['architecture'])
    if not re.fullmatch(r'[a-z0-9_-]+/[a-z0-9_-]+', data['target']):
        raise ValueError('Invalid OpenWrt target/subtarget')
    for key in ('name', 'board'):
        if not isinstance(data[key], str) or not data[key] or any(c in data[key] for c in '\x00\r\n'):
            raise ValueError('Invalid device ' + key)
    for key in ('excluded_boards', 'seed_files', 'patches', 'required_packages', 'forbidden_packages', 'allowed_crypto_backends'):
        values = data[key]
        if not isinstance(values, list) or not all(isinstance(v, str) and v and not any(c in v for c in '\x00\r\n') for v in values) or len(values) != len(set(values)):
            raise ValueError('Invalid device list: ' + key)
    if not data['seed_files'] or data['board'] in data['excluded_boards']:
        raise ValueError('Missing seed or contradictory board identity')
    for value in data['seed_files'] + data['patches']:
        path = FIRMWARE / relative_path(value)
        if not path.is_file() or not path.resolve().is_relative_to(FIRMWARE.resolve()):
            raise ValueError('Missing or escaped recipe input: ' + value)
    image = data['image']
    if not isinstance(image, dict) or set(image) != {'path', 'manifest_suffix', 'format', 'max_bytes', 'stock_install_max_bytes', 'firmware_partition_bytes', 'erase_block_bytes', 'squashfs_block_bytes'}:
        raise ValueError('Invalid image recipe fields')
    relative_path(image['path'])
    if not image['path'].startswith('bin/targets/' + data['target'] + '/'):
        raise ValueError('Image path must belong to the recipe target')
    if not isinstance(image['format'], str) or not re.fullmatch('[a-z0-9-]+', image['format']):
        raise ValueError('Invalid image format name')
    if (not isinstance(image['manifest_suffix'], str) or not image['manifest_suffix'].startswith('-')
            or '/' in image['manifest_suffix'] or not image['path'].endswith(image['manifest_suffix'])):
        raise ValueError('Invalid manifest suffix')
    for key in ('max_bytes', 'stock_install_max_bytes', 'firmware_partition_bytes', 'erase_block_bytes', 'squashfs_block_bytes'):
        if type(image[key]) is not int or image[key] <= 0:
            raise ValueError('Invalid image byte limit: ' + key)
    if not image['max_bytes'] <= image['stock_install_max_bytes'] <= image['firmware_partition_bytes']:
        raise ValueError('Image size limits contradict partition boundaries')
    if set(data['required_packages']) & set(data['forbidden_packages']):
        raise ValueError('Contradictory package policy')
    if not set(data['allowed_crypto_backends']) <= CRYPTO_BACKENDS:
        raise ValueError('Unknown crypto backend in device recipe')
    if data['architecture'] != 'mipsle-softfloat' and data['allowed_crypto_backends']:
        raise ValueError('MIPS crypto backends cannot be enabled for another architecture')
    return data


def validate_crypto_target(arch, backend, device=None):
    architecture(arch)
    if backend and (arch != 'mipsle-softfloat' or backend not in CRYPTO_BACKENDS
                    or device is None or backend not in device['allowed_crypto_backends']):
        raise ValueError('Crypto backend requires an explicitly compatible device recipe')


def require_image_validator(device):
    if device['image']['format'] != 'uimage-mips-squashfs' or device['architecture'] != 'mipsle-softfloat':
        raise ValueError('No verified image validator for this device format/architecture')


def seed_text(device):
    return '\n'.join((FIRMWARE / name).read_text(encoding='utf-8').rstrip() for name in device['seed_files']) + '\n'


def require_build_target(source, device):
    """Refuse a reused build tree still configured for a different board."""
    expected = {line for line in seed_text(device).splitlines()
                if line.startswith('CONFIG_TARGET_') and line.endswith('=y')}
    resolved = set((source / '.config').read_text(encoding='utf-8').splitlines())
    selected = {line for line in resolved if line.startswith('CONFIG_TARGET_')
                and '_DEVICE_' in line and line.endswith('=y')}
    wanted = {line for line in expected if '_DEVICE_' in line}
    if not wanted or not expected <= resolved or selected != wanted:
        raise ValueError('Resolved OpenWrt target differs from the selected device recipe; review defconfig first')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--device', default=DEFAULT_DEVICE)
    parser.add_argument('--seed-output', type=Path, help='Write combined seed to a fresh path; does not configure or build OpenWrt')
    args = parser.parse_args(argv)
    device = load_device(args.device)
    if args.seed_output:
        with args.seed_output.open('x', encoding='utf-8', newline='\n') as output:
            output.write(seed_text(device))
    print(json.dumps(device, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
