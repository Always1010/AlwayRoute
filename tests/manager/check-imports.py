"""Compile real manager modules without calling them or touching device state."""
from pathlib import Path
import os
import subprocess
import sys

root = Path(__file__).resolve().parents[2]
package = root / 'firmware/openwrt/alwayroute-manager/files/usr/share'
ucode = sys.argv[1] if len(sys.argv) == 2 else 'ucode'
result = subprocess.run(
    [ucode, '-L', str(package / 'ucode'), '-e',
     "import { call } from 'alwayroute.store'; "
     "import { sampleTraffic } from 'alwayroute.traffic'; "
     "import { sampleStatus } from 'alwayroute.status'; "
     "import { selectionPlan } from 'alwayroute.selection'; "
     "print('PASS real manager module imports\\n');"],
    env={**os.environ, 'ALWAYROUTE_POLICY_DIR': str(package / 'alwayroute/policies')},
    check=False,
)
raise SystemExit(result.returncode)
