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

print("PASS init start: repeated registration leaves runtime credential unchanged")
