"""Ignored image failures must not authorize stale output.

Uses a fake make process and explicit temporary environment JSON. No builds or
router IO. Windows replaces only POSIX process/lock guards; run on the POSIX
build host as well to exercise the real workspace lock and /proc scanner.
"""
from contextlib import ExitStack, nullcontext
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from unittest.mock import patch

project = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[2]
sys.path.insert(0, str(project / 'firmware/tools'))
spec = importlib.util.spec_from_file_location('native_build', project / 'firmware/tools/run-native-build.py')
supervisor = importlib.util.module_from_spec(spec)
spec.loader.exec_module(supervisor)

for case in ['fresh', 'stale', 'missing', 'oversize', 'make-failed', 'budget']:
    with tempfile.TemporaryDirectory(prefix='alwayroute-supervisor-test-') as directory:
        work = Path(directory)
        source = work / 'source'
        image = source / supervisor.IMAGE_RELATIVE
        image.parent.mkdir(parents=True)
        if case == 'stale':
            image.write_bytes(b'old image')
        environment = work / 'environment.json'
        environment.write_text(json.dumps({
            'schema_version': 1,
            'build': {'task_root': str(work), 'openwrt_tree': str(source),
                      'jobs': 3, 'timeout_seconds': 120, 'disk_limit_bytes': 1048576},
        }))

        class FakeMake:
            pid = 99999999

            def __init__(self, command, **kwargs):
                assert command == ['make', '-j3', 'V=s'], command
                assert kwargs['cwd'] == source.resolve()
                assert kwargs['env']['CMAKE_BUILD_PARALLEL_LEVEL'] == '3'
                assert kwargs['env']['TMPDIR'] == str(work.resolve() / 'tmp')
                self.stopped = case != 'budget'
                if case in ('fresh', 'oversize', 'make-failed', 'budget'):
                    with image.open('wb') as stream:
                        stream.truncate(supervisor.IMAGE_LIMIT_BYTES + 1 if case == 'oversize' else 8)

            def poll(self):
                return (2 if case == 'make-failed' else 0) if self.stopped else None

            def wait(self, **kwargs):
                self.stopped = True
                return self.poll()

        with ExitStack() as stack:
            stack.enter_context(patch.object(supervisor.subprocess, 'Popen', FakeMake))
            if os.name != 'posix':
                stack.enter_context(patch.object(supervisor, 'require_posix_host'))
                stack.enter_context(patch.object(supervisor, 'refuse_active_make'))
                stack.enter_context(patch.object(supervisor, 'build_lock', lambda work: nullcontext()))
            if case == 'budget':
                stack.enter_context(patch.object(supervisor.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, '1048577 workspace')))
                # A Windows Python does not provide killpg. This fake child never
                # starts; create=True keeps that test equally isolated there.
                stop = stack.enter_context(patch.object(supervisor.os, 'killpg', create=True))
            exit_code = supervisor.main(['--env', str(environment)])
            if case == 'budget':
                stop.assert_called_once_with(FakeMake.pid, supervisor.signal.SIGTERM)
        state = json.loads((work / 'native-build-state.json').read_text())
        assert state['status'] == ('succeeded' if case == 'fresh' else 'failed'), case
        assert (exit_code == 0) == (case == 'fresh'), (case, exit_code)
        assert state['image_inspection_required'] is True, case
        assert state['timeout_seconds'] == 120 and state['disk_limit_bytes'] == 1048576
        if case == 'budget':
            assert state['stop_reason'] == 'budget guard'
        print('PASS supervisor', case, flush=True)
