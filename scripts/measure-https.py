"""Bounded HTTPS measurements from the configured traffic runner, without changing routes."""
from __future__ import annotations

import argparse
import json
import re
import shlex
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit

from alwayroute_context import ContextError, load_environment, ssh_argv


def command(environment: dict, url: str, timeout: int) -> list[str]:
    parsed = urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ContextError("Use a public HTTPS test URL without credentials, query or fragment")
    traffic = environment.get("traffic")
    if not traffic:
        raise ContextError("traffic context is required; router connection does not determine the traffic path")
    local_windows = sys.platform == "win32" and traffic.get("executor", "local") == "local"
    if local_windows and traffic.get("source_interface") and not traffic.get("source_address"):
        raise ContextError("Windows curl requires source_address; interface-name binding is unsupported")
    # Explicit curl metrics only. No response body, cookies or raw request/response headers are retained.
    argv = ["curl", "--disable", "--silent", "--fail", "--noproxy", "*", "--proto", "=https", "--max-time", str(timeout),
            "--connect-timeout", "5", "--max-filesize", "1048576", "--output", "NUL" if local_windows else "/dev/null",
            "--write-out", "%{http_code} %{time_connect} %{time_appconnect} %{time_total} %{size_download}"]
    if traffic.get("source_interface") or traffic.get("source_address"):
        argv += ["--interface", traffic.get("source_address") or traffic["source_interface"]]
    argv += ["--url", url]
    if traffic.get("executor") == "ssh":
        # The SSH account may use zsh: bare =https otherwise triggers its =command expansion.
        return ssh_argv(traffic["ssh_alias"]) + [shlex.join(["sh", "-c", shlex.join(argv)])]
    return argv


def require_bounded_curl(environment: dict) -> None:
    traffic = environment["traffic"]
    argv = ["curl", "--disable", "--version"]
    if traffic.get("executor") == "ssh":
        argv = ssh_argv(traffic["ssh_alias"]) + [shlex.join(["sh", "-c", shlex.join(argv)])]
    result = subprocess.run(argv, capture_output=True, timeout=20, check=False)
    match = re.match(rb"curl (\d+)\.(\d+)\.(\d+)", result.stdout)
    if result.returncode or not match or tuple(map(int, match.groups())) < (8, 4, 0):
        raise ContextError("Bounded measurement requires existing curl >= 8.4.0 on the traffic runner; no software changed")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env", type=Path, required=True)
    parser.add_argument("--url", default="https://example.com/")
    parser.add_argument("--count", type=int, choices=range(1, 6), default=3)
    parser.add_argument("--timeout", type=int, choices=range(1, 31), default=15)
    parser.add_argument("--apply", action="store_true", help="Run bounded requests (default: plan only)")
    args = parser.parse_args(argv)
    try:
        environment = load_environment(args.env)
        call = command(environment, args.url, args.timeout)
        if not args.apply:
            print(json.dumps({"apply": False, "requests": args.count, "max_seconds_each": args.timeout,
                              "max_bytes_each": 1048576, "changes_routes": False,
                              "source_bound": bool(environment["traffic"].get("source_interface") or environment["traffic"].get("source_address"))}))
            return 0
        measurements = []
        require_bounded_curl(environment)
        for _ in range(args.count):
            result = subprocess.run(call, capture_output=True, timeout=args.timeout + 20, check=False)
            metrics = result.stdout.decode("ascii", errors="replace").strip()
            if result.returncode or not re.fullmatch(r"[0-9]{3}(?: [0-9]+(?:\.[0-9]+)?){4}", metrics):
                raise ContextError(f"HTTPS measurement failed (exit {result.returncode}); no raw output displayed")
            code, connect, tls, total, size = metrics.split()
            measurements.append({"http_status": int(code), "connect_seconds": float(connect),
                                 "tls_seconds": float(tls), "total_seconds": float(total), "bytes": float(size)})
        print(json.dumps({"measurements": measurements, "changes_routes": False,
                          "path_verified": False, "note": "Source binding alone does not prove the router or policy path"}, indent=2))
        return 0
    except (ContextError, OSError, ValueError, subprocess.SubprocessError) as error:
        print(str(error) if isinstance(error, ContextError) else "Measurement could not complete", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
