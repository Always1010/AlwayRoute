"""Exercise the procd start registration without touching host service state."""

from pathlib import Path
import os
import shutil
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parents[2]
INIT = ROOT / "firmware/openwrt/alwayroute-manager/files/etc/init.d/alwayroute"
RUNNER = ROOT / "firmware/openwrt/alwayroute-manager/files/usr/libexec/alwayroute-core-run"

source = INIT.read_text(encoding="utf-8")
runner = RUNNER.read_text(encoding="utf-8")
assert "alwayroute-core-prepare" not in source, (
    "rc.common start/reload must not rotate a credential unless procd spawns the core"
)
assert runner.count("/usr/libexec/alwayroute-core-prepare") == 1
assert runner.index("alwayroute-core-prepare") < runner.index("sing-box check") < runner.index("exec /usr/bin/sing-box run")

shell = shutil.which("sh")
if shell is None:
    print("SKIP init start behavior: POSIX sh is unavailable")
    raise SystemExit(0)

with tempfile.TemporaryDirectory(prefix="alwayroute-init-") as directory:
    root = Path(directory)
    runtime_dir = root / "runtime"
    runtime_dir.mkdir(mode=0o700)
    runtime = runtime_dir / "runtime.json"
    original = b'{"experimental":{"clash_api":{"secret":"stable"}}}\n'
    runtime.write_bytes(original)
    runtime.chmod(0o600)
    log = root / "procd.log"

    # Run the actual function body with only its absolute runtime path redirected
    # into the temporary directory. procd is represented by side-effect-free stubs.
    body = "\n".join(source.splitlines()[1:]).replace(
        "/tmp/alwayroute", runtime_dir.as_posix()
    )
    script = root / "run.sh"
    script.write_text(
        "set -eu\n"
        + body
        + "\nprocd_open_instance() { :; }\n"
        + "procd_set_param() { printf '%s\\n' \"$*\" >> \"$PROCD_LOG\"; }\n"
        + "procd_close_instance() { :; }\n"
        + "start_service\nstart_service\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        [shell, script.as_posix()],
        env={**os.environ, "PROCD_LOG": log.as_posix()},
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert result.returncode == 0, result.stderr.decode(errors="replace")
    assert runtime.read_bytes() == original, "repeated start registration changed runtime credentials"
    commands = [line for line in log.read_text(encoding="utf-8").splitlines() if line.startswith("command ")]
    assert commands == [
        "command /usr/libexec/alwayroute-core-run",
        "command /usr/libexec/alwayroute-core-run",
    ], "each start must only register the spawn wrapper"

    # The external mode must precede even a stale legacy runtime.json. All
    # absolute service/config paths are redirected to isolated command doubles.
    config_dir = root / 'config'
    config_dir.mkdir()
    (config_dir / 'external-mode.json').write_text('{"backend":"external"}')
    events = root / 'events.log'
    helper = root / 'external-helper'
    helper.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$EVENTS_LOG"\n')
    helper.chmod(0o755)
    forwarding = root / 'forwarding-helper'
    forwarding.write_text('#!/bin/sh\nprintf "forwarding %s\\n" "$*" >> "$EVENTS_LOG"\n')
    forwarding.chmod(0o755)
    external_body = body.replace('/etc/alwayroute', config_dir.as_posix()).replace(
        '/usr/libexec/alwayroute-external', helper.as_posix()).replace(
        '/usr/libexec/alwayroute-forwarding', forwarding.as_posix())
    log.write_text('')
    script.write_text(
        'set -eu\n' + external_body + '\n'
        + 'procd_open_instance() { :; }\n'
        + 'procd_set_param() { printf "%s\\n" "$*" >> "$PROCD_LOG"; }\n'
        + 'procd_close_instance() { :; }\n'
        + 'start_service\nstop_service\nrestart\nreload_service\n', encoding='utf-8')
    result = subprocess.run([shell, script.as_posix()],
                            env={**os.environ, 'PROCD_LOG': log.as_posix(), 'EVENTS_LOG': events.as_posix()},
                            capture_output=True, check=False)
    assert result.returncode == 0, result.stderr.decode(errors='replace')
    assert not log.read_text(), 'external mode must never register the old core'
    assert events.read_text().splitlines() == ['reconcile', 'disable', 'reconcile', 'reconcile'], (
        'external stop must close independently and restart/reload preserve intent')

    pure = (ROOT / 'firmware/openwrt/alwayroute-external-manager/files/etc/init.d/alwayroute').read_text(encoding='utf-8')
    assert 'alwayroute-boot' not in pure and 'sing-box' not in pure
    assert 'external-mode.json' not in pure, 'pure external lifecycle cannot depend on a mode marker'
    events.write_text('')
    script.write_text('set -eu\n' + '\n'.join(pure.splitlines()[1:]).replace(
        '/usr/libexec/alwayroute-external-supervisor', helper.as_posix()).replace(
        '/usr/libexec/alwayroute-external', helper.as_posix()) +
        '\nprocd_open_instance() { :; }\nprocd_set_param() { :; }\nprocd_close_instance() { :; }\n'
        'start() { start_service; }\nstop() { stop_service; }\n'
        'start_service\nstop_service\nrestart\nreload_service\nshutdown\n', encoding='utf-8')
    result = subprocess.run([shell, script.as_posix()], env={**os.environ, 'EVENTS_LOG': events.as_posix()}, capture_output=True)
    assert result.returncode == 0, result.stderr.decode(errors='replace')
    assert events.read_text().splitlines() == ['start', 'disable', 'start', 'event', 'pause', 'shutdown'], (
        'pure lifecycle registers one worker, coalesces events and preserves shutdown intent')


print("PASS init: legacy credential registration and independent external lifecycle")
