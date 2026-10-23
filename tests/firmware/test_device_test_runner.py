"""Validate bounded device-test orchestration with a fake router; never execute ELF."""
import contextlib
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('device_test_runner', ROOT / 'firmware/tools/run-device-tests.py')
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


def elf(machine=8, segment=1):
    data = bytearray(84)
    data[:7] = b'\x7fELF\x01\x01\x01'
    struct.pack_into('<HHI', data, 16, 2, machine, 1)
    struct.pack_into('<I', data, 28, 52)
    struct.pack_into('<HHH', data, 40, 52, 32, 1)
    struct.pack_into('<8I', data, 52, segment, 0, 0, 0, len(data), len(data), 5, 4096)
    return data


class FakeRouter:
    def __init__(self):
        self.calls = []
        self.uploads = {}
        self.executed = False
        self.bad_hash = False
        self.exit_code = 0
        self.timeout = False
        self.timed = False
        self.stopped = self.removed = False
        self.log = b'--- PASS: TestVector (0.01s)\nPASS\n'
        self.owner = None
        self.busy = self.pending = False
        self.saved = self.applied = 7
        self.memory_kib = 100000
        self.free_kib = 100000

    def __call__(self, environment, command, *, data=None, timeout=30):
        self.calls.append(command)
        if command == ['sha256sum', '/usr/bin/sing-box']:
            return b'a' * 64 + b'  /usr/bin/sing-box\n'
        if command[:4] == ['ubus', 'call', 'alwayroute', 'status']:
            return json.dumps({'service': {'running': True}, 'core': {'available': True},
                               'forwarding': {'running': True},
                               'state': {'savedRevision': self.saved, 'appliedRevision': self.applied}}).encode()
        if command[:4] == ['ubus', 'call', 'alwayroute', 'job_status']:
            return json.dumps({'ok': True, 'busy': self.busy}).encode()
        if command == ['ubus', 'call', 'system', 'board']:
            return json.dumps({'board_name': runner.BOARD}).encode()
        if command == ['cat', '/etc/openwrt_release']:
            return b"DISTRIB_ARCH='mipsel_24kc'\n"
        if command == ['uname', '-m']:
            return b'mips\n'
        if command == ['cat', '/proc/meminfo']:
            return f'MemAvailable: {self.memory_kib} kB\n'.encode()
        if command == ['df', '-k', '/tmp']:
            return f'Filesystem 1K-blocks Used Available Use% Mounted\ntmpfs 100000 0 {self.free_kib} 0% /tmp\n'.encode()
        if command[:2] == ['sh', '-c']:
            code = command[2]
            if code == runner.CAPABILITIES:
                return b'private-watchdog-v1\n'
            if code == runner.PENDING_CHECK:
                return b'pending\n' if self.pending else b'clear\n'
            if code == runner.JOB_CHECK:
                return json.dumps({'status': 'running' if self.busy else 'succeeded'}).encode()
            directory, token = command[4:6]
            assert directory == '/tmp/alwayroute-device-tests-' + token
            if code == runner.SETUP:
                self.owner = (directory, token)
            else:
                assert self.owner == (directory, token), 'cleanup/upload must own the exact current run'
                if code == runner.UPLOAD:
                    self.uploads[directory + '/' + command[6]] = data
                elif code == runner.STOP:
                    self.stopped = True
                elif code == runner.REMOVE:
                    assert self.stopped, 'never remove before stopping owned children'
                    self.removed = True
                else:
                    raise AssertionError('Unapproved shell action')
            return b''
        if command[0] == 'sha256sum':
            digest = hashlib.sha256(self.uploads[command[1]]).hexdigest()
            return ((('0' * 64) if self.bad_hash else digest) + '  input\n').encode()
        if command[0] == 'chmod':
            return b''
        if command[0] == 'sh' and command[1].endswith('/runner.sh'):
            self.executed = True
            assert command[4:] == ['315', '300', '4']
            if self.timeout:
                raise runner.ContextError('Synthetic transport timeout')
            return b''
        if command[0] == 'cat' and command[1].endswith('/status'):
            return f'{self.exit_code} {int(self.timed)}\n'.encode()
        if command[0] == 'cat' and command[1].endswith('/test.log'):
            if not self.executed:
                raise runner.ContextError('No log before test execution')
            return self.log
        raise AssertionError('Unapproved remote operation: ' + repr(command))


class DeviceTestRunnerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='alwayroute-device-runner-test-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.binary = self.root / 'fixture.test'
        self.binary.write_bytes(elf())
        self.environment = self.root / 'environment.json'
        self.environment.write_text(json.dumps({'schema_version': 1, 'router': {'target': 'fixture-router'}}))
        self.fake = FakeRouter()
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(runner, 'ROOT', self.root))
        self.stack.enter_context(patch.object(runner, 'run_router', side_effect=self.fake))
        self.permissions = self.stack.enter_context(patch.object(runner, 'private_permissions'))
        self.stdout = self.stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
        self.stderr = self.stack.enter_context(contextlib.redirect_stderr(io.StringIO()))

    def invoke(self, *extra):
        return runner.main(['--env', str(self.environment), '--binary', str(self.binary), *extra])

    def test_wrong_arch_or_dynamic_binary_never_contacts_device(self):
        for data in (elf(machine=62), elf(segment=3)):
            self.binary.write_bytes(data)
            self.assertEqual(self.invoke('--apply'), 2)
        self.assertFalse(self.fake.calls)

    def test_plan_is_offline_and_does_not_create_output(self):
        self.assertEqual(self.invoke(), 0)
        self.assertFalse(self.fake.calls)
        self.assertFalse((self.root / '.local').exists())
        self.assertFalse(json.loads(self.stdout.getvalue())['benchmarks'])

    def test_bad_upload_hash_prevents_execution_and_cleans_only_owned_run(self):
        self.fake.bad_hash = True
        self.assertEqual(self.invoke('--apply'), 2)
        self.assertFalse(self.fake.executed)
        self.assertTrue(self.fake.stopped and self.fake.removed)
        self.assertEqual(len(self.fake.uploads), 1)

    def test_preflight_reads_readiness_without_uploads_and_reports_low_memory(self):
        self.fake.memory_kib = 19000
        self.assertEqual(self.invoke('--preflight'), 2)
        summary = json.loads(self.stdout.getvalue())
        self.assertTrue(summary['preflight'] and summary['board_verified'])
        self.assertFalse(summary['ready_to_execute'] or summary['memory_ready'])
        self.assertEqual(summary['memory_available_bytes'], 19000 * 1024)
        self.assertFalse(self.fake.uploads or self.fake.executed or self.fake.stopped)
        self.assertNotIn(['ubus', 'call', 'alwayroute', 'job_status', '{}'], self.fake.calls)
        self.assertFalse((self.root / '.local').exists())
        self.permissions.assert_not_called()

    def test_busy_pending_or_misaligned_revisions_refuse_before_upload(self):
        for changed in ({'busy': True}, {'pending': True}, {'applied': 6}):
            with self.subTest(changed=changed):
                fake = FakeRouter()
                for name, value in changed.items():
                    setattr(fake, name, value)
                with patch.object(runner, 'run_router', side_effect=fake):
                    self.assertEqual(self.invoke('--apply'), 2)
                self.assertFalse(fake.uploads or fake.executed or fake.stopped)

    def test_failure_and_timeout_archive_private_output_and_cleanup_without_production_mutation(self):
        for timeout in (False, True):
            with self.subTest(timeout=timeout):
                self.fake = FakeRouter()
                self.fake.exit_code = 1
                self.fake.timeout = timeout
                self.fake.log = b'PRIVATE_RAW_OUTPUT\npanic: test timed out after 5m\nFAIL\n'
                with patch.object(runner, 'run_router', side_effect=self.fake):
                    self.assertEqual(self.invoke('--apply'), 2)
                self.assertTrue(self.fake.executed and self.fake.stopped and self.fake.removed)
                for command in self.fake.calls:
                    if '/usr/bin/sing-box' in command:
                        self.assertEqual(command, ['sha256sum', '/usr/bin/sing-box'])
                    self.assertNotIn('killall', command)
                    self.assertNotIn('sysupgrade', command)
                self.assertNotIn('PRIVATE_RAW_OUTPUT', self.stdout.getvalue())
        logs = list((self.root / '.local/runs').glob('*/0.test.log'))
        self.assertEqual(len(logs), 2)
        self.assertTrue(all(b'PRIVATE_RAW_OUTPUT' in path.read_bytes() for path in logs))

    def test_success_runs_full_suite_and_records_verified_result(self):
        self.assertEqual(self.invoke('--apply'), 0)
        summary = json.loads(self.stdout.getvalue())
        self.assertTrue(summary['production_unchanged'])
        result = summary['results'][0]
        self.assertEqual(result['exit_code'], 0)
        self.assertTrue(result['passed'] and result['cleanup_complete'])
        self.assertEqual(result['log_sha256'], hashlib.sha256(self.fake.log).hexdigest())
        self.assertIn(b'-test.v "-test.timeout=${go_limit}s"', self.fake.uploads[self.fake.owner[0] + '/runner.sh'])
        self.assertNotIn(b'-test.run', runner.RUNNER.encode())
        directory_calls = [call for call in self.permissions.call_args_list if call.kwargs['directory']]
        self.assertEqual(len(directory_calls), 1)
        for call in self.permissions.call_args_list:
            self.assertTrue(call.args[0].is_relative_to(directory_calls[0].args[0]))


if __name__ == '__main__':
    unittest.main()
