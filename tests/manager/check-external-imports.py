"""Import the actual pure installed module set, with no legacy files present."""
import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / 'firmware/openwrt/alwayroute-external-manager'
spec = importlib.util.spec_from_file_location('external_stage', PACKAGE / 'tools/stage-files.py')
stage = importlib.util.module_from_spec(spec)
spec.loader.exec_module(stage)
with tempfile.TemporaryDirectory(prefix='alwayroute-pure-import-') as directory:
    output = Path(directory).resolve()
    stage.stage(PACKAGE / 'payload.json', ROOT / 'firmware/openwrt', output)
    subprocess.run([sys.argv[1] if len(sys.argv) > 1 else 'ucode', '-L', str(output / 'usr/share/ucode'), '-e',
        "import {call,work} from 'alwayroute.store'; print('PASS pure external imports without legacy models, digest, policies or downloader\\n');"], check=True)
