"""Rock-only regression: ignored image failures must not authorize stale output.

Uses Python's standard library and a fake make process. No builds or router IO.
"""
import json
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

project = Path(sys.argv[1])
original = (project/'firmware/tools/run-native-build.py').read_text()
for case in ['fresh', 'stale', 'missing', 'oversize', 'make-failed']:
    with tempfile.TemporaryDirectory(prefix='alwayroute-supervisor-test-') as directory:
        work = Path(directory)
        image = work/'source/bin/targets/ramips/mt7621/openwrt-ramips-mt7621-xiaomi_mi-router-4a-gigabit-squashfs-sysupgrade.bin'
        image.parent.mkdir(parents=True)
        if case == 'stale':
            image.write_bytes(b'old image')
        source = original.replace("w=pathlib.Path('/srv/alwayroute/openwrt-build')", 'w=pathlib.Path('+repr(directory)+')')

        class FakeMake:
            pid = 99999999

            def __init__(self, *args, **kwargs):
                if case in ('fresh', 'oversize', 'make-failed'):
                    with image.open('wb') as stream:
                        stream.truncate(13248*1024+1 if case == 'oversize' else 8)

            def poll(self):
                return 2 if case == 'make-failed' else 0

            def wait(self, **kwargs):
                return self.poll()

        namespace = {}
        exit_code = 0
        try:
            with patch('subprocess.Popen', FakeMake):
                exec(compile(source, 'run-native-build.py', 'exec'), namespace)
        except SystemExit as error:
            exit_code = error.code
        finally:
            if 'lock' in namespace:
                namespace['lock'].close()
        state = json.loads((work/'native-build-state.json').read_text())
        assert state['status'] == ('succeeded' if case == 'fresh' else 'failed'), case
        assert (exit_code == 0) == (case == 'fresh'), (case, exit_code)
        assert state['image_inspection_required'] is True, case
        print('PASS supervisor', case, flush=True)
