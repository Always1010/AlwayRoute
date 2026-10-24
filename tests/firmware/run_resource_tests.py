"""Run the pinned TProxy socket regression and prove it fails without the fix.

Uses the existing build-host Go and offline caches; no downloads or devices.
"""
import argparse
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'firmware/tools'))
from build_context import build_context


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--env', type=Path, required=True)
    args = parser.parse_args()
    context = build_context(args.env, default_jobs=2)
    spec = importlib.util.spec_from_file_location('core_builder', ROOT / 'firmware/tools/build-core.py')
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    spec = importlib.util.spec_from_file_location('resource_fixes', ROOT / 'firmware/tools/resource-fixes-overlay.py')
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    # Select the installed Go host explicitly; production's MIPS target cannot run here.
    host = json.loads(subprocess.check_output([str(context['go']), 'env', '-json', 'GOHOSTOS', 'GOHOSTARCH'], text=True))
    env = builder.core_environment(context, {'go_env': {
        'GOOS': host['GOHOSTOS'], 'GOARCH': host['GOHOSTARCH'], 'CGO_ENABLED': '0'}})
    with tempfile.TemporaryDirectory(prefix='alwayroute-resource-test-') as temporary:
        stage = Path(temporary)
        overlay = {'Replace': {}}
        helper.add_overlay(context['sing_box_source'], stage, overlay, include_tests=True)
        overlay_path = stage / 'overlay.json'
        overlay_path.write_text(json.dumps(overlay))
        command = [str(context['go']), 'test', '-p', str(context['jobs']), '-count=1', '-timeout=2m',
                   '-tags', builder.TAGS, '-overlay=' + str(overlay_path), '-run', '^TestTProxyReusedSocket',
                   './protocol/redirect']
        subprocess.run(command, cwd=context['sing_box_source'], env=env, check=True, timeout=180)
        patched = stage / 'resource-tproxy.go'
        patched.write_bytes((context['sing_box_source'] / helper.SOURCE).read_bytes())
        command[command.index('^TestTProxyReusedSocket')] = '^TestTProxyReusedSocketWriteErrorCloses$'
        result = subprocess.run(command, cwd=context['sing_box_source'], env=env, text=True,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=180)
        if result.returncode == 0 or 'failed socket was discarded without being closed' not in result.stdout:
            raise AssertionError('Unpatched negative control did not expose the socket leak:\n' + result.stdout)
        print('PASS: both socket tests; unpatched negative control reproduced the leak')


if __name__ == '__main__':
    main()
