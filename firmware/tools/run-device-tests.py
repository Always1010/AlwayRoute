"""Run existing static MIPSLE Go test binaries on the verified 4A, only with --apply.

All ordinary Go tests run (-test.v, no test.run filter); no benchmark, build,
installation, service change or production binary replacement is performed.
The installed download watchdog only accepts 3/20 seconds, so each run uploads
its own bounded child watchdog and removes only its token-owned temporary files.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import struct
import sys
import uuid


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
from alwayroute_context import ContextError, load_environment, run_router
from alwayroute_device import private_permissions


BOARD = 'xiaomi,mi-router-4a-gigabit'
MAX_BINARY_BYTES = 32 * 1024 * 1024
LOG_RESERVE_BYTES = 16 * 1024 * 1024
MIN_AVAILABLE_MEMORY = 32 * 1024 * 1024
PENDING_CHECK = r'''if test -e /etc/alwayroute/applying.json || test -e /tmp/alwayroute/restarting.json; then printf 'pending\n'; else printf 'clear\n'; fi'''
JOB_CHECK = r'''if test -f /tmp/alwayroute/job.json; then cat /tmp/alwayroute/job.json; else printf '%s\n' '{"status":"idle"}'; fi'''
CAPABILITIES = r'''set -eu
for tool in sha256sum readlink sleep env df chmod cat mkdir rm rmdir tr ls; do command -v "$tool" >/dev/null; done
test -r /proc/self/stat
test -n "$(readlink /proc/self/exe)"
(ulimit -f 8192)
printf 'private-watchdog-v1\n'
'''
SETUP = r'''set -eu
d=$1; token=$2
test "$d" = "/tmp/alwayroute-device-tests-$token"
umask 077
mkdir -m700 "$d"
printf '%s\n' "$token" > "$d/owner"
'''
UPLOAD = r'''set -eu
d=$1; token=$2; name=$3
test "$d" = "/tmp/alwayroute-device-tests-$token"
test ! -L "$d"
test "$(cat "$d/owner")" = "$token"
case "$name" in test|runner.sh) ;; *) exit 2 ;; esac
umask 077
set -C
cat > "$d/$name"
'''
RUNNER = r'''#!/bin/sh
set -u
d=$1; token=$2; limit=$3; go_limit=$4; cpus=$5
test "$d" = "/tmp/alwayroute-device-tests-$token" || exit 2
test "$(cat "$d/owner")" = "$token" || exit 2
umask 077
printf '%s\n' "$$" > "$d/runner.pid"
owned_task() {
  test -n "${task:-}" || return 1
  test "$(readlink "/proc/$task/exe" 2>/dev/null)" != "$d/test" || return 0
  # The direct child briefly remains a shell before exec; its inherited argv
  # still contains this unique runner path and owner token.
  cmd=$(tr '\000' ' ' < "/proc/$task/cmdline" 2>/dev/null || :)
  case "$cmd" in *"$d/runner.sh $d $token "*) return 0 ;; esac
  return 1
}
(ulimit -f 8192 || exit 2; exec env GOMAXPROCS="$cpus" TMPDIR="$d" "$d/test" -test.v "-test.timeout=${go_limit}s") > "$d/test.log" 2>&1 &
task=$!
printf '%s\n' "$task" > "$d/pid"
(
  nap=''
  cancel() { trap '' TERM INT HUP; if test -n "$nap"; then kill -TERM "$nap" 2>/dev/null; wait "$nap" 2>/dev/null; fi; exit 0; }
  trap cancel TERM INT HUP
  sleep "$limit" & nap=$!; wait "$nap"
  if owned_task; then
    printf '1\n' > "$d/timed_out"
    kill -TERM "$task" 2>/dev/null
  fi
  sleep 1 & nap=$!; wait "$nap"
  if owned_task; then kill -KILL "$task" 2>/dev/null; fi
) &
watchdog=$!
finish() {
  code=$1
  trap '' TERM INT HUP
  kill -TERM "$watchdog" 2>/dev/null; wait "$watchdog" 2>/dev/null
  if test -n "$task"; then
    if owned_task; then kill -TERM "$task" 2>/dev/null; sleep 1; fi
    if owned_task; then kill -KILL "$task" 2>/dev/null; fi
    wait "$task" 2>/dev/null
  fi
  timed=0; test ! -f "$d/timed_out" || timed=1
  printf '%s %s\n' "$code" "$timed" > "$d/status"
  rm -f "$d/pid" "$d/runner.pid"
  exit 0
}
trap 'finish 143' TERM
trap 'finish 130' INT
trap 'finish 129' HUP
wait "$task"; code=$?; task=''
finish "$code"
'''
STOP = r'''set -eu
d=$1; token=$2
test "$d" = "/tmp/alwayroute-device-tests-$token"
test ! -L "$d"
test -d "$d" || exit 0
test "$(cat "$d/owner")" = "$token"
if test -f "$d/runner.pid"; then
  p=$(cat "$d/runner.pid"); case "$p" in ''|*[!0-9]*) exit 2 ;; esac
  cmd=$(tr '\000' ' ' < "/proc/$p/cmdline" 2>/dev/null || :)
  case "$cmd" in *"$d/runner.sh $d $token "*) kill -TERM "$p" 2>/dev/null || :; sleep 3 ;; esac
  cmd=$(tr '\000' ' ' < "/proc/$p/cmdline" 2>/dev/null || :)
  case "$cmd" in *"$d/runner.sh $d $token "*) exit 1 ;; esac
fi
if test -f "$d/pid"; then
  p=$(cat "$d/pid"); case "$p" in ''|*[!0-9]*) exit 2 ;; esac
  if test "$(readlink "/proc/$p/exe" 2>/dev/null || :)" = "$d/test"; then
    kill -TERM "$p" 2>/dev/null || :; sleep 1
    test "$(readlink "/proc/$p/exe" 2>/dev/null || :)" != "$d/test" || kill -KILL "$p" 2>/dev/null
    sleep 1
    test "$(readlink "/proc/$p/exe" 2>/dev/null || :)" != "$d/test"
  fi
fi
'''
REMOVE = r'''set -eu
d=$1; token=$2
test "$d" = "/tmp/alwayroute-device-tests-$token"
test ! -L "$d"
test -d "$d" || exit 0
test "$(cat "$d/owner")" = "$token"
rm -f "$d/test" "$d/runner.sh" "$d/test.log" "$d/pid" "$d/runner.pid" "$d/status" "$d/timed_out"
test "$(ls -A "$d")" = owner
rm -f "$d/owner"
rmdir "$d"
'''


def script(environment, text, *arguments, data=None, timeout=30):
    return run_router(environment, ['sh', '-c', text, 'alwayroute-device-tests', *arguments], data=data, timeout=timeout)


def binary(path):
    if not path.is_file() or path.is_symlink() or not 0 < path.stat().st_size <= MAX_BINARY_BYTES:
        raise ContextError('Each test binary must be a regular file of at most 32 MiB')
    data = path.read_bytes()
    if len(data) < 52 or len(data) > MAX_BINARY_BYTES or data[:7] != b'\x7fELF\x01\x01\x01':
        raise ContextError('Test binary must be ELF32 little-endian MIPS; no device was contacted')
    kind, machine = struct.unpack_from('<HH', data, 16)
    phoff = struct.unpack_from('<I', data, 28)[0]
    ehsize, phsize, phcount = struct.unpack_from('<HHH', data, 40)
    if kind != 2 or machine != 8 or ehsize != 52 or phsize != 32 or not phcount or phoff < 52 or phoff + phsize * phcount > len(data):
        raise ContextError('Test binary has an incompatible MIPS executable header')
    headers = [struct.unpack_from('<8I', data, phoff + i * phsize) for i in range(phcount)]
    if not any(h[0] == 1 for h in headers) or any(h[0] in (2, 3) or h[1] + h[4] > len(data) for h in headers):
        raise ContextError('Test binary must be static MIPSLE without a dynamic loader')
    return {'data': data, 'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data)}


def digest_reply(raw):
    match = re.match(rb'([0-9a-f]{64})(?:\s|$)', raw)
    if not match:
        raise ContextError('Device returned an invalid SHA-256 response; raw output withheld')
    return match.group(1).decode()


def production(environment):
    sha = digest_reply(run_router(environment, ['sha256sum', '/usr/bin/sing-box']))
    try:
        reply = json.loads(run_router(environment, ['ubus', 'call', 'alwayroute', 'status', '{}']))
        flags = [reply[s][k] for s, k in [('service', 'running'), ('core', 'available'), ('forwarding', 'running')]]
        saved = reply['state']['savedRevision']
        applied = reply['state']['appliedRevision']
    except (ValueError, KeyError, TypeError):
        raise ContextError('Cannot read production service state; raw output withheld') from None
    if not all(type(value) is bool for value in flags):
        raise ContextError('Unexpected production service state')
    if type(saved) is not int or saved < 0 or (applied is not None and (type(applied) is not int or applied < 0)):
        raise ContextError('Unexpected production revision state')
    return {'core_sha256': sha, 'service_running': flags[0], 'core_available': flags[1],
            'forwarding_running': flags[2], 'saved_revision': saved, 'applied_revision': applied}


def activity(environment):
    state = production(environment)
    try:
        # job_status RPC can repair stale metadata. Read the marker directly so
        # preflight never performs that repair; stale running jobs stay blocked.
        job = json.loads(script(environment, JOB_CHECK))
    except ValueError:
        raise ContextError('Cannot verify production job state; raw output withheld') from None
    if not isinstance(job, dict) or job.get('status') not in ('idle', 'running', 'succeeded', 'failed', 'cancelled'):
        raise ContextError('Unexpected production job state')
    pending = script(environment, PENDING_CHECK).strip()
    if pending not in (b'clear', b'pending'):
        raise ContextError('Cannot verify pending production transactions')
    return {**state, 'job_idle': job['status'] != 'running', 'no_pending_transaction': pending == b'clear',
            'revisions_aligned': state['applied_revision'] is not None and state['saved_revision'] == state['applied_revision']}


def idle(state):
    return state['job_idle'] and state['no_pending_transaction'] and state['revisions_aligned']


def preflight(environment, size):
    try:
        board = json.loads(run_router(environment, ['ubus', 'call', 'system', 'board']))
    except (ValueError, TypeError):
        raise ContextError('Cannot verify device board; raw output withheld') from None
    if not isinstance(board, dict) or board.get('board_name') != BOARD:
        raise ContextError('Device is not the supported first-generation gigabit 4A')
    release = run_router(environment, ['cat', '/etc/openwrt_release'])
    machine = run_router(environment, ['uname', '-m']).strip()
    if machine not in (b'mips', b'mipsel') or not re.search(rb"^DISTRIB_ARCH=['\"]mipsel_24kc['\"]\s*$", release, re.M):
        raise ContextError('Device architecture does not match static MIPSLE test binaries')
    if script(environment, CAPABILITIES).strip() != b'private-watchdog-v1':
        raise ContextError('Device does not support the private bounded watchdog interface')
    try:
        free = int(run_router(environment, ['df', '-k', '/tmp']).splitlines()[-1].split()[3]) * 1024
    except (ValueError, IndexError):
        raise ContextError('Cannot verify free space in device /tmp') from None
    required = size + len(RUNNER.encode()) + LOG_RESERVE_BYTES
    memory = run_router(environment, ['cat', '/proc/meminfo'])
    available = re.search(rb'^MemAvailable:\s+([0-9]+)\s+kB\s*$', memory, re.M)
    available = int(available.group(1)) * 1024 if available else None
    return {'board_verified': True, 'architecture_verified': True, 'watchdog_compatible': True,
            'tmp_free_bytes': free, 'tmp_required_bytes': required, 'tmp_space_ready': free >= required,
            'memory_available_bytes': available, 'memory_required_bytes': MIN_AVAILABLE_MEMORY,
            'memory_ready': available is not None and available >= MIN_AVAILABLE_MEMORY}


def readiness(environment, size):
    resources = preflight(environment, size)
    state = activity(environment)
    return {**resources, **state,
            'ready_to_execute': resources['tmp_space_ready'] and resources['memory_ready'] and idle(state)}


def private_write(path, data):
    with path.open('xb') as handle:
        private_permissions(path, directory=False)
        handle.write(data)


def timeout_seconds(value):
    try:
        seconds = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError('Timeout must be an integer from 30 to 900 seconds') from None
    if not 30 <= seconds <= 900:
        raise argparse.ArgumentTypeError('Timeout must be an integer from 30 to 900 seconds')
    return seconds


def execute(environment, item, output, index, seconds, cpus):
    token = uuid.uuid4().hex
    directory = '/tmp/alwayroute-device-tests-' + token
    result = {'sha256': item['sha256'], 'bytes': item['bytes'], 'exit_code': None, 'passed': False,
              'timed_out': False, 'cleanup_complete': False}
    attempted = False
    error = None
    try:
        if not readiness(environment, item['bytes'])['ready_to_execute']:
            raise ContextError('Device resources, job, transaction or revisions are not ready for test execution')
        attempted = True
        script(environment, SETUP, directory, token)
        for name, data in [('test', item['data']), ('runner.sh', RUNNER.encode())]:
            script(environment, UPLOAD, directory, token, name, data=data, timeout=90)
            actual = digest_reply(run_router(environment, ['sha256sum', directory + '/' + name]))
            if actual != hashlib.sha256(data).hexdigest():
                raise ContextError('Uploaded test input hash mismatch; test was not executed')
        run_router(environment, ['chmod', '700', directory + '/test', directory + '/runner.sh'])
        if not idle(activity(environment)):
            raise ContextError('Production activity changed during upload; test was not executed')
        run_router(environment, ['sh', directory + '/runner.sh', directory, token,
                                 str(seconds + 15), str(seconds), str(cpus)], timeout=seconds + 35)
        status = run_router(environment, ['cat', directory + '/status']).strip()
        if not re.fullmatch(rb'[0-9]{1,3} [01]', status):
            raise ContextError('Device test returned an invalid exit record')
        code, timed = map(int, status.split())
        if code > 255:
            raise ContextError('Device test returned an invalid exit code')
        result.update(exit_code=code, timed_out=bool(timed))
    except (ContextError, OSError):
        error = 'Device test operation failed; inspect the private result and log'
    finally:
        if attempted:
            stopped = False
            try:
                script(environment, STOP, directory, token, timeout=15)
                stopped = True
            except ContextError:
                error = 'Owned child cleanup could not be verified; device inspection is required'
            try:
                log = run_router(environment, ['cat', directory + '/test.log'], timeout=30)
                private_write(output / (str(index) + '.test.log'), log)
                result['log_sha256'] = hashlib.sha256(log).hexdigest()
                result['timed_out'] = result['timed_out'] or b'panic: test timed out after ' in log
                result['passed'] = result['exit_code'] == 0 and not result['timed_out'] and log.rstrip().endswith(b'PASS')
            except (ContextError, OSError):
                pass
            if stopped:
                try:
                    script(environment, REMOVE, directory, token)
                    result['cleanup_complete'] = True
                except ContextError:
                    error = 'Owned temporary file cleanup was incomplete; device inspection is required'
    if error:
        result['error'] = error
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--env', type=Path, required=True)
    parser.add_argument('--binary', type=Path, nargs='+', action='append', required=True, help='Existing Go test ELF; repeat or list multiple paths')
    parser.add_argument('--timeout', type=timeout_seconds, default=300, help='Full ordinary Go test timeout, 30-900 seconds (default: 300)')
    parser.add_argument('--cpus', type=int, choices=(1, 2, 4), default=4)
    parser.add_argument('--output', type=Path, help='Fresh private directory under this repository .local/runs')
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--apply', action='store_true', help='Upload and execute (default: offline plan only)')
    mode.add_argument('--preflight', action='store_true', help='Read device readiness only; no uploads or test execution')
    args = parser.parse_args(argv)
    try:
        environment = load_environment(args.env)
        paths = [path for group in args.binary for path in group]
        if len(paths) > 16:
            raise ContextError('Select at most sixteen test binaries per private run')
        items = [binary(path) for path in paths]  # All local validation precedes every device operation.
        if args.preflight:
            check = readiness(environment, max(item['bytes'] for item in items))
            print(json.dumps({'apply': False, 'preflight': True, **check}))
            return 0 if check['ready_to_execute'] else 2
        if not args.apply:
            print(json.dumps({'apply': False, 'binaries': [{k: v for k, v in item.items() if k != 'data'} for item in items],
                              'timeout_seconds': args.timeout, 'all_ordinary_tests': True, 'benchmarks': False}))
            return 0
        runs = (ROOT / '.local/runs').resolve()
        output = (args.output or runs / ('device-tests-' + uuid.uuid4().hex)).resolve()
        if not output.is_relative_to(runs) or output == runs:
            raise ContextError('Test output must be a fresh directory under this repository .local/runs')
        output.parent.mkdir(parents=True, exist_ok=True)
        output.mkdir(mode=0o700, exist_ok=False)
        private_permissions(output, directory=True)
        before = production(environment)
        results = []
        try:
            for index, item in enumerate(items):
                result = execute(environment, item, output, index, args.timeout, args.cpus)
                results.append(result)
                private_write(output / 'results.json' if len(items) == 1 else output / (str(index) + '.result.json'),
                              (json.dumps(result, indent=2) + '\n').encode())
                if not result['passed'] or not result['cleanup_complete']:
                    break
        finally:
            try:
                unchanged = production(environment) == before
            except ContextError:
                unchanged = False
            summary = {'apply': True, 'results': results, 'production_unchanged': unchanged}
            private_write(output / 'summary.json', (json.dumps(summary, indent=2) + '\n').encode())
            print(json.dumps(summary))
        return 0 if unchanged and len(results) == len(items) and all(r['passed'] and r['cleanup_complete'] for r in results) else 2
    except (ContextError, OSError) as error:
        print(str(error) if isinstance(error, ContextError) else 'Private test inputs or output directory could not be read/written', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
