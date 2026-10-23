"""Exercise crypto provenance against explicitly selected artifacts, without execution.

Run with Python on the build host; reads ELF metadata and temporary source copies.
No image build, router access, cache edits, or target binary execution.
"""
import argparse
import importlib.util
import hashlib
import json
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile


tools = Path(__file__).resolve().parents[2] / 'firmware/tools'
sys.path.insert(0, str(tools))
from build_context import build_context

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--env', type=Path, help='Environment JSON on the build host; default: existing Rock layout')
parser.add_argument('--candidate', type=Path, required=True, help='mipsle-asm-r2 ELF, with adjacent .build-info.json and original overlay stage')
parser.add_argument('--standard', type=Path, required=True, help='Standard ELF, with adjacent .build-info.json')
args = parser.parse_args()
context = build_context(args.env)
spec = importlib.util.spec_from_file_location('image_inspector', tools / 'inspect-image.py')
inspector = importlib.util.module_from_spec(spec)
spec.loader.exec_module(inspector)
validate = inspector.validate_crypto_provenance
pinned = context['sing_box_source']
checks = 0


def verify(info, embedded, elf, backend):
    def check(name, ok):
        if not ok:
            raise ValueError(name)
    validate(info, embedded, elf, backend, pinned, check,
             module_root=context['cache_root'] / 'gomodcache/golang.org/x/crypto@v0.48.0',
             go_root=context['go_root'])


def rejected(action, expected):
    global checks
    try:
        action()
    except ValueError as error:
        assert str(error) == expected, (str(error), expected)
    else:
        raise AssertionError('Accepted tampered provenance: ' + expected)
    checks += 1


def load(path):
    info = json.loads(path.with_suffix('.build-info.json').read_text())
    elf = path.read_bytes()
    assert hashlib.sha256(elf).hexdigest() == info['input_elf_sha256']
    embedded = subprocess.check_output([str(context['go']), 'version', '-m', str(path)], text=True)
    return info, embedded, elf


standard, standard_embedded, standard_elf = load(args.standard)
verify(standard, standard_embedded, standard_elf, None)
checks += 1
info, embedded, elf = load(args.candidate)
backend = 'mipsle-asm-r2'
verify(info, embedded, elf, backend)
checks += 1
rejected(lambda: verify(info, embedded, elf, None), 'core_no_explicit_overlay')
original_stage = Path(next(flag.split('=', 1)[1] for flag in info['command'] if flag.startswith('-overlay='))).parent
wrong_replacement = embedded.replace('\t=>\t' + str(original_stage / 'module'), '\t=>\t' + str(original_stage / 'other-module'))
assert wrong_replacement != embedded
rejected(lambda: verify(info, wrong_replacement, elf, backend), 'core_crypto_embedded_replace')
wrong_assembler = embedded.replace('vendor/golang.org/x/crypto/chacha20=-D GOMIPS_r2', 'vendor/golang.org/x/crypto/chacha20=-D GOMIPS_r5')
assert wrong_assembler != embedded
rejected(lambda: verify(info, wrong_assembler, elf, backend), 'core_crypto_embedded_assembler')

with tempfile.TemporaryDirectory(prefix='crypto-provenance-test-') as temporary:
    stage = Path(temporary) / 'stage'
    shutil.copytree(original_stage, stage, copy_function=shutil.copyfile)
    # Module-cache snapshots preserve read-only directory modes. Only this
    # disposable fixture is made writable for the tamper rejection cases.
    for directory in [stage, *(p for p in stage.rglob('*') if p.is_dir())]:
        directory.chmod(0o700)
    fixture = json.loads(json.dumps(info).replace(str(original_stage), str(stage)))
    for name, key in [('overlay.json', 'overlay_sha256'), ('core.mod', 'modfile_sha256')]:
        path = stage / name
        path.write_text(path.read_text().replace(str(original_stage), str(stage)))
        fixture['crypto_candidate'][key] = hashlib.sha256(path.read_bytes()).hexdigest()
    fixture_embedded = embedded.replace(str(original_stage), str(stage))
    verify(fixture, fixture_embedded, elf, backend)
    checks += 1
    extra = stage / 'module/chacha20poly1305/unreviewed.go'
    extra.write_text('package chacha20poly1305\n')
    rejected(lambda: verify(fixture, fixture_embedded, elf, backend), 'core_crypto_module_snapshot_unchanged')
    extra.unlink()
    unchanged = stage / 'module/chacha20poly1305/chacha20poly1305_generic.go'
    original = unchanged.read_bytes()
    unchanged.write_bytes(original + b'\n')
    rejected(lambda: verify(fixture, fixture_embedded, elf, backend), 'core_crypto_module_snapshot_unchanged')
    unchanged.write_bytes(original)
    extra.symlink_to(unchanged)
    rejected(lambda: verify(fixture, fixture_embedded, elf, backend), 'core_crypto_snapshot_regular_files')
    extra.unlink()

# Keep all metadata unchanged, but replace one real ROTR with a NOP in memory.
section_offset = struct.unpack_from('<I', elf, 32)[0]
section_size, section_count, names_index = struct.unpack_from('<HHH', elf, 46)
sections = [struct.unpack_from('<10I', elf, section_offset + i * section_size) for i in range(section_count)]
names = sections[names_index]
strings = elf[names[4]:names[4] + names[5]]
text = next(s for s in sections if strings[s[0]:].split(b'\0', 1)[0] == b'.text')
tampered = bytearray(elf)
for offset in range(text[4], text[4] + text[5], 4):
    if struct.unpack_from('<I', elf, offset)[0] & 0xffe0003f == 0x00200002:
        tampered[offset:offset + 4] = b'\0' * 4
        break
else:
    raise AssertionError('Candidate did not contain ROTR')
rejected(lambda: verify(info, embedded, tampered, backend), 'core_crypto_actual_rotate_instructions')
print('PASS', checks, 'crypto provenance checks; no target execution')
