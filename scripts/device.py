"""Read sanitized router status or stage a file with a SHA-256 check; never flash."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shlex
import sys
from pathlib import Path

from alwayroute_context import ContextError, load_environment, run_router

BOARD = "xiaomi,mi-router-4a-gigabit"


def object_reply(raw: bytes) -> dict:
    try:
        reply = json.loads(raw)
    except (ValueError, UnicodeError):
        raise ContextError("Router returned invalid JSON; raw response withheld") from None
    if not isinstance(reply, dict):
        raise ContextError("Router returned an unexpected response shape")
    return reply


def status(environment: dict) -> dict:
    board = object_reply(run_router(environment, ["ubus", "call", "system", "board"]))
    reply = object_reply(run_router(environment, ["ubus", "call", "alwayroute", "status", "{}"]))
    if reply.get("ok") is False:
        raise ContextError("AlwayRoute status RPC failed; raw response withheld")
    def flag(section: str, key: str):
        value = reply.get(section, {})
        return value.get(key) if isinstance(value, dict) and type(value.get(key)) is bool else None
    state = reply.get("state", {})
    revision = state.get("appliedRevision") if isinstance(state, dict) else None
    return {"expected_4a_board": board.get("board_name") == BOARD,
            "service_running": flag("service", "running"), "core_available": flag("core", "available"),
            "forwarding_running": flag("forwarding", "running"),
            "applied_revision": revision if type(revision) is int and revision >= 0 else None}


def stage(environment: dict, path: Path, apply: bool) -> dict:
    if not path.is_file() or path.is_symlink():
        raise ContextError("Stage input must be a regular local file")
    if not 0 < path.stat().st_size <= 32 * 1024 * 1024:
        raise ContextError("Stage input must be nonempty and at most 32 MiB")
    data = path.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    target = "/tmp/alwayroute-stage-" + digest
    result = {"apply": apply, "bytes": len(data), "sha256": digest, "temporary_target": target,
              "firmware_validation": "not_performed", "flash_dispatched": False}
    if not apply:
        return result
    # Exclusive creation avoids clobbering a file/symlink. Never infer flashing from staging.
    code = "umask 077; set -C; cat > " + shlex.quote(target)
    run_router(environment, ["sh", "-c", code], data=data, timeout=90)
    actual = run_router(environment, ["sha256sum", target], timeout=60).split(maxsplit=1)[0]
    if not re.fullmatch(rb"[0-9a-f]{64}", actual) or actual.decode() != digest:
        raise ContextError("Staged file hash mismatch; inspect the temporary file before retrying")
    result["hash_verified"] = True
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env", type=Path, required=True)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("status", help="Read board and sanitized service state")
    upload = commands.add_parser("stage", help="Plan temporary upload; add --apply to upload, never flash")
    upload.add_argument("file", type=Path)
    upload.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    try:
        environment = load_environment(args.env)
        result = status(environment) if args.command == "status" else stage(environment, args.file, args.apply)
        print(json.dumps(result, indent=2))
        return 0
    except (ContextError, OSError) as error:
        print(str(error) if isinstance(error, ContextError) else "Local input could not be read", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
