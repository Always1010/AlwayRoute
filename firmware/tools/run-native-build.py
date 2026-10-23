"""Incremental device image build supervisor, run on the POSIX build host.

--env selects existing build paths and resource limits, not a remote executor.
A separate --device recipe selects the image path and capacity limits.
Requires existing prerequisites; installs no software and never cleans caches.
Preserve existing native-build.log/state files before a deliberate next run.
"""
import argparse
from contextlib import contextmanager
import datetime
import json
import os
from pathlib import Path
import signal
import subprocess
import time
import traceback

from build_context import build_context
from target_profile import DEFAULT_DEVICE, load_device, require_build_target


def refuse_active_make(source):
    for proc in Path('/proc').iterdir():
        if not proc.name.isdecimal():
            continue
        try:
            if (proc / 'comm').read_text().strip() == 'make' and (proc / 'cwd').resolve(strict=True) == source:
                raise SystemExit('Refusing to start: make PID ' + proc.name + ' is already active in this source directory')
        except (FileNotFoundError, ProcessLookupError, PermissionError):
            continue


@contextmanager
def build_lock(work):
    try:
        import fcntl
    except ImportError as error:
        raise SystemExit('This supervisor requires the existing POSIX build host (fcntl and /proc); --env does not move execution') from error
    with (work / '.native-build.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit('Refusing to start: another build supervisor holds the task lock')
        yield


def image_stamp(image):
    if not image.is_file():
        return None
    stat = image.stat()
    return stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns


def require_posix_host():
    if os.name != 'posix' or not Path('/proc').is_dir():
        raise SystemExit('This supervisor requires the existing POSIX build host with /proc; no build was started')


def run_build(context):
    require_posix_host()
    source = context['openwrt_tree'].resolve(strict=True)
    work = context['build_root'].resolve(strict=True)
    if not source.is_dir() or source.parent != work:
        raise SystemExit('OpenWrt source must be an existing directory inside its build workspace')
    require_build_target(source, context['device'])
    # Read-only check protects older, unguarded supervisors too. Repeat under the
    # lock to close the race between two guarded starts.
    refuse_active_make(source)
    with build_lock(work):
        refuse_active_make(source)
        require_build_target(source, context['device'])
        return supervise(context, source, work)


def supervise(context, source, work):
    statefile = work / 'native-build-state.json'
    begin = time.monotonic()
    process = None
    device = context['device']
    image = source / device['image']['path']
    previous_image = image_stamp(image)
    command = ['make', '-j' + str(context['jobs']), 'V=s']
    with (work / 'native-build.log').open('wb') as log:
        try:
            process = subprocess.Popen(
                command, cwd=source, stdin=subprocess.DEVNULL, stdout=log,
                stderr=subprocess.STDOUT, start_new_session=True,
                env={**os.environ, 'TMPDIR': str(work / 'tmp'),
                     'CMAKE_BUILD_PARALLEL_LEVEL': str(context['jobs'])})
            state = {
                'pid': process.pid, 'monitor_pid': os.getpid(),
                'started_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
                'command': command, 'disk_limit_bytes': context['disk_limit_bytes'],
                'timeout_seconds': context['timeout_seconds'],
                'status': 'running', 'incremental': True, 'device': device['id'],
                'image_limit_bytes': device['image']['max_bytes'],
            }
            while process.poll() is None:
                usage = subprocess.run(['du', '-sb', str(work)], capture_output=True, text=True, timeout=60)
                if usage.returncode not in (0, 1) or not usage.stdout.strip():
                    raise RuntimeError('No valid workspace size measurement')
                size = int(usage.stdout.split()[0])
                state.update(elapsed_seconds=round(time.monotonic() - begin), workspace_bytes=size,
                             last_check_utc=datetime.datetime.now(datetime.timezone.utc).isoformat())
                temporary = statefile.with_suffix('.json.tmp')
                temporary.write_text(json.dumps(state, indent=2) + '\n')
                temporary.replace(statefile)
                if size > state['disk_limit_bytes'] or time.monotonic() - begin > context['timeout_seconds']:
                    state['stop_reason'] = 'budget guard'
                    os.killpg(process.pid, signal.SIGTERM)
                    process.wait(timeout=20)
                    break
                try:
                    process.wait(timeout=20)
                except subprocess.TimeoutExpired:
                    pass
            returncode = process.wait()
            log.flush()
            # OpenWrt can ignore image recipe failures and leave an older .bin.
            # A successful make alone must never authorize that stale image.
            current_image = image_stamp(image)
            fresh_image = current_image is not None and current_image != previous_image
            bounded_image = fresh_image and image.stat().st_size <= device['image']['max_bytes']
            accepted = returncode == 0 and bounded_image and 'stop_reason' not in state
            state.update(
                status='succeeded' if accepted else 'failed', returncode=returncode,
                elapsed_seconds=round(time.monotonic() - begin, 3), image_inspection_required=True,
                image_fresh=fresh_image, image_within_size_limit=bool(bounded_image))
            if returncode == 0 and not accepted and 'stop_reason' not in state:
                state['stop_reason'] = 'make returned zero without a fresh image within the device size limit'
            statefile.write_text(json.dumps(state, indent=2) + '\n')
            print(json.dumps(state), flush=True)
            return 0 if accepted else returncode or 1
        except BaseException:
            if process and process.poll() is None:
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                    process.wait(timeout=15)
                except Exception:
                    os.killpg(process.pid, signal.SIGKILL)
            statefile.write_text(json.dumps({
                'status': 'supervisor_failed_build_stopped', 'error': traceback.format_exc(),
            }, indent=2) + '\n')
            raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--env', type=Path, required=True, help='Validated build-host environment JSON')
    parser.add_argument('--device', default=DEFAULT_DEVICE, help='Repository device recipe name')
    args = parser.parse_args(argv)
    context = build_context(args.env)
    context['device'] = load_device(args.device)
    return run_build(context)


if __name__ == '__main__':
    raise SystemExit(main())
