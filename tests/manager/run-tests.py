"""Run pure ucode manager checks without installing anything or writing device state.

Usage: python tests/manager/run-tests.py /path/to/ucode -
The command receives a self-contained test program on stdin. The transaction
suite injects an in-memory filesystem and core adapter; it never runs a service.
"""
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
MODULES = ROOT / 'firmware/openwrt/alwayroute-manager/files/usr/share/ucode/alwayroute'


def bundle(names):
    return '\n'.join(
        '\n'.join(line for line in (MODULES / name).read_text(encoding='utf-8').splitlines()
                  if not line.startswith('import ')).replace('export function ', 'function ')
        for name in names
    )


command = sys.argv[1:] or ['ucode', '-']
model_tests = (ROOT / 'tests/manager/run.uc').read_text(encoding='utf-8')
model_tests = '\n'.join(line for line in model_tests.splitlines() if not line.startswith('import '))
suites = [
    "import { sha256 } from 'digest';\n" + bundle(['model.uc', 'subscription.uc']) + '\n' + model_tests,
    (ROOT / 'tests/manager/transactions.uc').read_text(encoding='utf-8').replace(
        '// MANAGER_SOURCE', bundle(['model.uc', 'subscription.uc', 'store.uc'])),
    (ROOT / 'tests/manager/fetch.uc').read_text(encoding='utf-8').replace(
        '// FETCH_SOURCE', '\n'.join(line for line in
            (ROOT / 'firmware/openwrt/alwayroute-manager/files/usr/libexec/alwayroute-fetch')
            .read_text(encoding='utf-8').splitlines()
            if not line.startswith('import ') and not line.startswith('#!'))),
]
for suite in suites:
    result = subprocess.run(command, input=suite.encode('utf-8'), check=False)
    if result.returncode:
        raise SystemExit(result.returncode)
