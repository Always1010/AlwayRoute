"""Run pure ucode manager checks without installing anything or writing device state.

Usage: python tests/manager/run-tests.py /path/to/ucode -
The command receives a self-contained test program on stdin. The transaction
suite injects an in-memory filesystem and core adapter; it never runs a service.
"""
from pathlib import Path
import base64
import json
import os
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
MODULES = ROOT / 'firmware/openwrt/alwayroute-manager/files/usr/share/ucode/alwayroute'
POLICIES = ROOT / 'firmware/openwrt/alwayroute-manager/files/usr/share/alwayroute/policies'


def bundle(names):
    return '\n'.join(
        '\n'.join(line for line in (MODULES / name).read_text(encoding='utf-8').splitlines()
                  if not line.startswith('import ')).replace('export function ', 'function ')
        for name in names
    )


command = sys.argv[1:] or ['ucode', '-']
catalog = [json.loads((POLICIES / name).read_text(encoding='utf-8'))
           for name in json.loads((POLICIES / 'catalog.json').read_text(encoding='utf-8'))]
catalog_data = base64.b64encode(json.dumps(catalog, ensure_ascii=False).encode()).decode()
catalog_stub = "function loadPolicies() { return json(b64dec('" + catalog_data + "')); }\n"
model_tests = (ROOT / 'tests/manager/run.uc').read_text(encoding='utf-8')
model_tests = '\n'.join(line for line in model_tests.splitlines() if not line.startswith('import '))
suites = [
    "import * as fs from 'fs';\nimport { sha256 } from 'digest';\n" + bundle(['policies.uc', 'model.uc', 'subscription.uc']) + '\n' + model_tests,
    (ROOT / 'tests/manager/transactions.uc').read_text(encoding='utf-8').replace(
        '// MANAGER_SOURCE', catalog_stub + bundle(['model.uc', 'subscription.uc', 'selection.uc', 'traffic.uc', 'status.uc', 'external-model.uc', 'external-controller.uc', 'external.uc', 'job-worker.uc', 'store.uc'])),
    (ROOT / 'tests/manager/fetch.uc').read_text(encoding='utf-8').replace(
        '// FETCH_SOURCE', '\n'.join(line for line in
            (ROOT / 'firmware/openwrt/alwayroute-manager/files/usr/libexec/alwayroute-fetch')
            .read_text(encoding='utf-8').splitlines()
            if not line.startswith('import ') and not line.startswith('#!'))),
    "import { sha256 } from 'digest';\n" + catalog_stub + bundle(['model.uc', 'selection.uc']) + '\n' + '\n'.join(
        line for line in (ROOT / 'tests/manager/selection.uc').read_text(encoding='utf-8').splitlines()
        if not line.startswith('import ')),
    (ROOT / 'tests/manager/traffic.uc').read_text(encoding='utf-8').replace('// TRAFFIC_SOURCE', bundle(['traffic.uc'])),
    (ROOT / 'tests/manager/status.uc').read_text(encoding='utf-8').replace('// STATUS_SOURCE', bundle(['status.uc'])),
    bundle(['external-model.uc']) + '\n' + '\n'.join(line for line in (ROOT / 'tests/manager/external-model.uc').read_text(encoding='utf-8').splitlines() if not line.startswith('import ')),
    (ROOT / 'tests/manager/external-controller.uc').read_text(encoding='utf-8').replace('// EXTERNAL_SOURCE', bundle(['external-model.uc', 'external-controller.uc'])),
    (ROOT / 'tests/manager/external-runtime.uc').read_text(encoding='utf-8').replace('// EXTERNAL_RUNTIME_SOURCE', bundle(['external-model.uc', 'external-controller.uc', 'external.uc'])),
]
for suite in suites:
    result = subprocess.run(command, input=suite.encode('utf-8'), check=False,
                            env={**os.environ, 'ALWAYROUTE_POLICY_DIR': str(POLICIES)})
    if result.returncode:
        raise SystemExit(result.returncode)
