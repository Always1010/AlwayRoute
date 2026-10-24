"""Image acceptance and bounded cleanup of the build's whole process group.

Uses a fake make process and explicit temporary environment JSON. No builds or
router IO. Windows runs isolated control-flow checks and explicitly skips the
real Linux signal/reaping cases; run on the POSIX build host for those too.
"""
from contextlib import ExitStack, nullcontext
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from unittest.mock import Mock, call, patch

project = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[2]
sys.path.insert(0, str(project / 'firmware/tools'))
spec = importlib.util.spec_from_file_location('native_build', project / 'firmware/tools/run-native-build.py')
supervisor = importlib.util.module_from_spec(spec)
spec.loader.exec_module(supervisor)
from target_profile import load_device, seed_text
device = load_device()

for case in ['fresh', 'stale', 'missing', 'oversize', 'make-failed', 'budget']:
    with tempfile.TemporaryDirectory(prefix='alwayroute-supervisor-test-') as directory:
        work = Path(directory)
        source = work / 'source'
        image = source / device['image']['path']
        image.parent.mkdir(parents=True)
        (source / '.config').write_text(seed_text(device))
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
            returncode = None

            def __init__(self, command, **kwargs):
                assert command == ['make', '-j3', 'V=s'], command
                assert kwargs['cwd'] == source.resolve()
                assert kwargs['env']['CMAKE_BUILD_PARALLEL_LEVEL'] == '3'
                assert kwargs['env']['TMPDIR'] == str(work.resolve() / 'tmp')
                self.stopped = case != 'budget'
                if case in ('fresh', 'oversize', 'make-failed', 'budget'):
                    with image.open('wb') as stream:
                        stream.truncate(device['image']['max_bytes'] + 1 if case == 'oversize' else 8)

            def poll(self):
                return (2 if case == 'make-failed' else 0) if self.stopped else None

            def wait(self, **kwargs):
                self.stopped = True
                self.returncode = self.poll()
                return self.returncode

        with ExitStack() as stack:
            stack.enter_context(patch.object(supervisor.subprocess, 'Popen', FakeMake))
            stack.enter_context(patch.object(supervisor, 'leader_exited', lambda process: process.stopped))
            if os.name != 'posix':
                stack.enter_context(patch.object(supervisor, 'require_posix_host'))
                stack.enter_context(patch.object(supervisor, 'refuse_active_make'))
                stack.enter_context(patch.object(supervisor, 'build_lock', lambda work: nullcontext()))
            if case == 'budget':
                stack.enter_context(patch.object(supervisor.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, '1048577 workspace')))
                # A Windows Python does not provide killpg. This fake child never
                # starts; create=True keeps that test equally isolated there.
                stop = stack.enter_context(patch.object(supervisor.os, 'killpg', create=True))
                stack.enter_context(patch.object(supervisor, 'wait_for_group', return_value=True))
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


# Isolated control-flow checks also run on Windows. They are not evidence of
# POSIX signal delivery; the real descendants below exercise that separately.
child = Mock(pid=99999999, returncode=None)
with patch.object(supervisor.signal, 'SIGKILL', 9, create=True), patch.object(
        supervisor.os, 'killpg', create=True) as stop, patch.object(
        supervisor, 'wait_for_group', side_effect=[False, True]):
    supervisor.stop_build_group(child, grace_seconds=0, kill_seconds=1)
    assert stop.call_args_list == [call(child.pid, supervisor.signal.SIGTERM),
                                   call(child.pid, supervisor.signal.SIGKILL)]
    child.wait.assert_called_once_with(timeout=1)
    child.poll.assert_not_called()
print('PASS isolated cleanup escalates after leader exit and reaps', flush=True)

child.returncode = 0
with patch.object(supervisor.os, 'killpg', create=True) as stop:
    supervisor.stop_build_group(child)
    stop.assert_not_called()
print('PASS isolated cleanup never signals a reaped PID/PGID', flush=True)

child = Mock(pid=99999999, returncode=None)
with patch.object(supervisor.os, 'killpg', create=True, side_effect=ProcessLookupError), patch.object(
        supervisor, 'wait_for_group', return_value=True):
    supervisor.stop_build_group(child, kill_seconds=1)
    child.wait.assert_called_once_with(timeout=1)
print('PASS isolated cleanup reaps when the group has disappeared', flush=True)

child = Mock(pid=99999999, returncode=None)
with patch.object(supervisor.signal, 'SIGKILL', 9, create=True), patch.object(
        supervisor.os, 'killpg', create=True), patch.object(supervisor, 'wait_for_group', return_value=False):
    try:
        supervisor.stop_build_group(child, grace_seconds=0, kill_seconds=1)
    except supervisor.BuildCleanupError:
        pass
    else:
        raise AssertionError('live descendants after SIGKILL were reported as stopped')
    child.wait.assert_called_once_with(timeout=1)
print('PASS isolated cleanup reports incomplete shutdown and still reaps', flush=True)


if (os.name != 'posix' or not hasattr(os, 'WNOWAIT') or not Path('/proc').is_dir()
        or not hasattr(os, 'pidfd_open') or not hasattr(supervisor.signal, 'pidfd_send_signal')):
    print('SKIP real POSIX process-group cleanup: requires Linux /proc, waitid(WNOWAIT), and pidfds', flush=True)
else:
    # Both paths use supervise(), with a real session leader that exits on TERM
    # and a descendant that ignores it. Exception cleanup starts after the
    # leader has already exited but has deliberately not been reaped.
    real_popen = subprocess.Popen
    real_stop = supervisor.stop_build_group
    for case in ('budget-descendant', 'exception-descendant'):
        with tempfile.TemporaryDirectory(prefix='alwayroute-supervisor-group-') as directory:
            work = Path(directory)
            source = work / 'source'
            source.mkdir()
            descendant_pid = work / 'descendant.pid'
            child_code = '''import os, signal, sys, time
signal.signal(signal.SIGTERM, signal.SIG_IGN)
open(sys.argv[1], 'w').write(str(os.getpid()))
while True: time.sleep(1)
'''
            leader_code = '''import subprocess, sys, time
subprocess.Popen([sys.executable, '-c', sys.argv[2], sys.argv[1]])
while True: time.sleep(1)
'''
            processes = []
            descendant_handles = []

            def start_make(command, **kwargs):
                process = real_popen([sys.executable, '-c', leader_code,
                                      str(descendant_pid), child_code], **kwargs)
                processes.append(process)
                deadline = time.monotonic() + 5
                while not descendant_pid.exists() or not descendant_pid.read_text().strip():
                    assert time.monotonic() < deadline, 'descendant failed to become ready'
                    time.sleep(0.01)
                # Keep a stable test-child handle for failure cleanup even if
                # a broken supervisor reaps its leader before the assertion.
                descendant_handles.append(os.pidfd_open(int(descendant_pid.read_text())))
                return process

            def measure(*args, **kwargs):
                if case == 'exception-descendant':
                    os.kill(processes[0].pid, supervisor.signal.SIGTERM)
                    supervisor.wait_for_leader(processes[0], 2)
                    assert supervisor.leader_exited(processes[0]), 'leader did not exit'
                    raise RuntimeError('injected measurement failure after leader exit')
                return subprocess.CompletedProcess([], 0, '1048577 workspace')

            context = {'device': device, 'jobs': 3, 'timeout_seconds': 120, 'disk_limit_bytes': 1048576}
            try:
                begin = time.monotonic()
                with patch.object(supervisor.subprocess, 'Popen', start_make), patch.object(
                        supervisor.subprocess, 'run', measure), patch.object(
                        supervisor, 'stop_build_group', lambda process: real_stop(process, 0.15, 2)):
                    if case == 'exception-descendant':
                        try:
                            supervisor.supervise(context, source, work)
                        except RuntimeError as error:
                            assert str(error) == 'injected measurement failure after leader exit'
                        else:
                            raise AssertionError('measurement failure did not propagate')
                    else:
                        assert supervisor.supervise(context, source, work) != 0
                process = processes[0]
                assert time.monotonic() - begin < 5, 'process-group cleanup exceeded its bound'
                assert process.returncode == -supervisor.signal.SIGTERM, 'leader was not reaped after TERM'
                try:
                    os.waitpid(process.pid, os.WNOHANG)
                except ChildProcessError:
                    pass
                else:
                    raise AssertionError('leader was not reaped by the supervisor')
                assert not supervisor.group_is_running(process.pid), 'descendant survived cleanup'
                stat = Path('/proc') / descendant_pid.read_text() / 'stat'
                assert not stat.exists() or stat.read_text().rsplit(')', 1)[1].split()[0] in ('Z', 'X')
                state = json.loads((work / 'native-build-state.json').read_text())
                assert state['status'] == ('failed' if case == 'budget-descendant' else 'supervisor_failed_build_stopped')
                print('PASS real POSIX supervisor', case, flush=True)
            finally:
                # Leave no live test children even when a regression is found.
                for handle in descendant_handles:
                    try:
                        supervisor.signal.pidfd_send_signal(handle, supervisor.signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    finally:
                        os.close(handle)
                for process in processes:
                    if process.returncode is None:
                        os.killpg(process.pid, supervisor.signal.SIGKILL)
                        process.wait(timeout=2)
