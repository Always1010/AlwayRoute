"""Run the external model and transaction engine using existing ucode on stdin."""
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
MODULES = ROOT / 'firmware/openwrt/alwayroute-manager/files/usr/share/ucode/alwayroute'


def bundle(names):
    return '\n'.join('\n'.join(line for line in (MODULES / name).read_text(encoding='utf-8').splitlines()
                              if not line.startswith('import ')).replace('export function ', 'function ')
                     for name in names)


command = sys.argv[1:] or ['ucode', '-']
model_test = '\n'.join(line for line in (ROOT / 'tests/manager/external-model.uc').read_text(encoding='utf-8').splitlines()
                       if not line.startswith('import '))
suites = [bundle(['external-model.uc']) + '\n' + model_test,
          (ROOT / 'tests/manager/external-controller.uc').read_text(encoding='utf-8').replace(
              '// EXTERNAL_SOURCE', bundle(['external-model.uc', 'external-controller.uc']))]
for suite in suites:
    result = subprocess.run(command, input=suite.encode('utf-8'), check=False)
    if result.returncode:
        raise SystemExit(result.returncode)
