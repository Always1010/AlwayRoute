"""Test first-boot defaults in a temporary directory with an isolated UCI stub.

Run using an existing POSIX shell and Python. No host /etc paths are accessed.
An optional first argument selects the reviewed defaults script.
"""
from pathlib import Path
import os
import shlex
import stat
import subprocess
import sys
import tempfile

source_path = (Path(sys.argv[1]) if len(sys.argv) > 1 else
               Path(__file__).resolve().parents[2] / 'tests/fixtures/management-defaults.sh')
source = source_path.read_bytes()
assert source and b'\r' not in source, 'defaults script must be nonempty and LF-only'
assert source.count(b'STATE_DIR=/etc/alwayroute') == 1, 'test must redirect the state directory exactly once'

with tempfile.TemporaryDirectory(prefix='alwayroute-management-defaults-') as directory:
    test_root = Path(directory)
    state_dir = test_root / 'state'
    marker = state_dir / 'management-initialized'
    log = test_root / 'uci.log'
    stub_dir = test_root / 'bin'
    stub_dir.mkdir()
    stub = stub_dir / 'uci'
    stub.write_text('#!/bin/sh\ncat >> "$UCI_LOG"\nexit "${UCI_FAIL:-0}"\n')
    stub.chmod(0o700)
    script = test_root / 'defaults'
    script.write_text(source.decode('utf-8').replace(
        'STATE_DIR=/etc/alwayroute', 'STATE_DIR=' + shlex.quote(str(state_dir))))
    env = dict(os.environ, PATH=str(stub_dir) + os.pathsep + os.environ['PATH'],
               UCI_LOG=str(log), UCI_FAIL='0')

    def run():
        return subprocess.run(['sh', str(script)], env=env, check=False,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode

    assert run() == 0 and marker.is_file(), 'first successful run must create marker'
    assert stat.S_IMODE(state_dir.stat().st_mode) == 0o700, 'state directory must be 0700'
    assert stat.S_IMODE(marker.stat().st_mode) == 0o600, 'marker must be 0600'
    original = log.read_bytes()
    assert b"127.0.0.1:80" in original, 'first-boot Web listener must stay on loopback'
    if len(sys.argv) == 1:
        assert b"Port='2222'" in original, 'synthetic fixture SSH port changed'
    env['UCI_FAIL'] = '1'
    assert run() == 0 and log.read_bytes() == original, 'second run must skip UCI entirely'
    marker.unlink()
    assert run() != 0 and not marker.exists(), 'failed UCI batch must not create marker'
    env['UCI_FAIL'] = '0'
    assert run() == 0 and marker.is_file(), 'failed first run must remain retryable'

print('PASS management defaults: first run, marker skip, failed batch, retry and 0700/0600 modes')
