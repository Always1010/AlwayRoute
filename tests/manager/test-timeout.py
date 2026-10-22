"""POSIX watchdog regression checks; requires only an existing Python and /bin/sh.

Usage: python3 tests/manager/test-timeout.py <path/to/alwayroute-timeout>
Uses temporary test children and removes them even when an assertion fails.
"""
from pathlib import Path
import os
import signal
import subprocess
import sys
import tempfile
import time

wrapper = Path(sys.argv[1]).resolve()
normal = subprocess.run(['sh', str(wrapper), '3', sys.executable, '-c', 'raise SystemExit(7)'],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=4)
assert normal.returncode == 7, normal.returncode


def resistant_child_test(interrupt):
    with tempfile.TemporaryDirectory(prefix='alwayroute-timeout-') as directory:
        pid_file = Path(directory) / 'pid'
        child = ('import os,signal,time,pathlib;'
                 'signal.signal(signal.SIGTERM,signal.SIG_IGN);'
                 f'pathlib.Path({str(pid_file)!r}).write_text(str(os.getpid()));'
                 'time.sleep(30)')
        process = subprocess.Popen(['sh', str(wrapper), '20' if interrupt else '3',
                                    sys.executable, '-c', child],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        child_pid = None
        try:
            end = time.monotonic() + 3
            while not pid_file.exists() and time.monotonic() < end:
                time.sleep(.02)
            assert pid_file.exists(), 'test child did not start'
            child_pid = int(pid_file.read_text())
            if interrupt:
                process.send_signal(signal.SIGTERM)
            code = process.wait(timeout=6)
            assert code == (143 if interrupt else 137), code
            try:
                os.kill(child_pid, 0)
            except ProcessLookupError:
                pass
            else:
                raise AssertionError('TERM-resistant direct child survived wrapper exit')
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
            if child_pid is not None:
                try:
                    os.kill(child_pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass


resistant_child_test(False)
resistant_child_test(True)
print('PASS watchdog preserves exit code and reaps resistant children on deadline/external TERM')
