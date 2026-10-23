"""Small, dependency-free environment and SSH context for developer tools.

Environment files contain locations and connection references, never credentials.
Importing this module performs no I/O or connection.
"""
from __future__ import annotations

import json
import re
import shlex
import subprocess
from pathlib import Path, PurePosixPath, PureWindowsPath


class ContextError(ValueError):
    """An invalid environment or an unsuccessful external operation."""


FIELDS = {
    "build": {"executor", "ssh_alias", "project_workspace", "task_root", "openwrt_tree",
              "toolchain_root", "cache_root", "output_root", "jobs", "timeout_seconds", "disk_limit_bytes"},
    "router": {"executor", "executor_ssh_alias", "target", "connect_timeout_seconds",
               "ssh_port", "identity_file", "known_hosts_file"},
    "traffic": {"executor", "ssh_alias", "source_interface", "source_address", "gateway"},
}
PATH_FIELDS = {"project_workspace", "task_root", "openwrt_tree", "toolchain_root", "cache_root",
               "output_root", "identity_file", "known_hosts_file"}
NUMBER_LIMITS = {"jobs": (1, 256), "timeout_seconds": (1, 604800),
                 "disk_limit_bytes": (1048576, 2**60), "connect_timeout_seconds": (1, 300),
                 "ssh_port": (1, 65535)}
TARGET = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.:@-]*\Z")


def absolute_path(value: str, field: str) -> str:
    if not isinstance(value, str) or not value or any(c in value for c in "\x00\r\n"):
        raise ContextError(f"{field}: expected a nonempty path")
    path = PureWindowsPath(value) if re.match(r"^[A-Za-z]:[/\\]", value) else PurePosixPath(value)
    if not path.is_absolute() or ".." in path.parts or str(path) == path.anchor:
        raise ContextError(f"{field}: expected an absolute path below a filesystem root")
    return value


def ssh_target(value: str, field: str = "SSH target") -> str:
    if not isinstance(value, str) or not TARGET.fullmatch(value) or value.count("@") > 1:
        raise ContextError(f"{field}: expected an SSH alias or user@host without options or credentials")
    return value


def load_environment(path: str | Path) -> dict:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        raise ContextError("Cannot read environment JSON; check the selected file") from None
    if not isinstance(data, dict) or type(data.get("schema_version")) is not int or data["schema_version"] != 1:
        raise ContextError("Environment requires schema_version 1")
    if set(data) - {"schema_version", "name", *FIELDS}:
        raise ContextError("Unknown top-level environment fields")
    if "name" in data and (not isinstance(data["name"], str) or any(c in data["name"] for c in "\x00\r\n")):
        raise ContextError("name: expected a single-line label")
    for section, fields in FIELDS.items():
        if section not in data:
            continue
        values = data[section]
        if not isinstance(values, dict) or set(values) - fields:
            raise ContextError(f"{section}: unknown fields or invalid object")
        for key, value in values.items():
            field = f"{section}.{key}"
            if key in NUMBER_LIMITS:
                low, high = NUMBER_LIMITS[key]
                if type(value) is not int or not low <= value <= high:
                    raise ContextError(f"{field}: integer outside supported range")
            elif key == "executor":
                if value not in ("local", "ssh"):
                    raise ContextError(f"{field}: use local or ssh")
            elif key in PATH_FIELDS:
                absolute_path(value, field)
            elif key in {"ssh_alias", "executor_ssh_alias", "target"}:
                ssh_target(value, field)
            elif not isinstance(value, str) or not value or any(c in value for c in "\x00\r\n"):
                raise ContextError(f"{field}: expected a nonempty single-line string")
        if values.get("executor") == "ssh":
            alias = "executor_ssh_alias" if section == "router" else "ssh_alias"
            if not values.get(alias):
                raise ContextError(f"{section}.{alias}: required for SSH execution")
    return data


def ssh_argv(target: str, timeout: int = 10, *, port: int | None = None,
             identity: str | None = None, known_hosts: str | None = None) -> list[str]:
    argv = ["ssh", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes",
            "-o", f"ConnectTimeout={timeout}"]
    if port is not None:
        argv += ["-p", str(port)]
    if identity:
        argv += ["-i", identity]
    if known_hosts:
        argv += ["-o", "UserKnownHostsFile=" + known_hosts]
    return argv + [ssh_target(target)]


def router_argv(environment: dict, command: list[str]) -> list[str]:
    router = environment.get("router", {})
    if "target" not in router:
        raise ContextError("router.target is required")
    timeout = router.get("connect_timeout_seconds", 10)
    inner = ssh_argv(router["target"], timeout, port=router.get("ssh_port"),
                     identity=router.get("identity_file"), known_hosts=router.get("known_hosts_file"))
    inner.append(shlex.join(command))
    if router.get("executor", "local") == "ssh":
        return ssh_argv(router["executor_ssh_alias"], timeout) + [shlex.join(inner)]
    return inner


def run_router(environment: dict, command: list[str], *, data: bytes | None = None,
               timeout: int = 30) -> bytes:
    try:
        result = subprocess.run(router_argv(environment, command), input=data,
                                capture_output=True, timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired):
        raise ContextError("Router operation could not complete; check connection and timeout") from None
    if result.returncode:
        # stderr may include private paths, credentials echoed by a remote tool, or configuration.
        raise ContextError(f"Router operation failed (exit {result.returncode}); no raw output displayed")
    return result.stdout
