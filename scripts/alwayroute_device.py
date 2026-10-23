"""Read-only device maintenance primitives and private local recovery archives.

No import-time I/O. No service, configuration, package or flash writes are exposed.
"""
from __future__ import annotations

import hashlib
import gzip
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import secrets
import stat
import subprocess
import tarfile
import threading
from datetime import datetime, timezone

from alwayroute_context import ContextError, router_argv, run_router

SHA256 = re.compile(r"[0-9a-f]{64}\Z")
REQUIRED_CONFIG = (
    "etc/config/network", "etc/config/dhcp", "etc/config/wireless",
    "etc/config/dropbear", "etc/config/uhttpd", "etc/shadow",
    "etc/dropbear/authorized_keys", "etc/alwayroute/management-initialized",
    "etc/alwayroute/current.json", "etc/alwayroute/lastgood.json",
    "etc/alwayroute/service.json",
)
MAX_ARCHIVE = 16 * 1024 * 1024
MAX_EXPANDED = 32 * 1024 * 1024
MAX_MEMBERS = 4096
REPO_ROOT = Path(__file__).resolve().parents[1]


def object_json(raw: bytes) -> dict:
    if len(raw) > MAX_ARCHIVE:
        raise ContextError("Device JSON exceeds the supported limit; content withheld")
    try:
        value = json.loads(raw)
    except (ValueError, UnicodeError):
        raise ContextError("Invalid device JSON; content withheld") from None
    if not isinstance(value, dict):
        raise ContextError("Unexpected device response; content withheld")
    return value


def digest_json(value: object) -> str:
    raw = json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


def safe_member(name: str) -> str:
    if not isinstance(name, str) or not name or len(name) > 512 or "\\" in name:
        raise ContextError("Unsafe archive or manifest path; name withheld")
    if any(ord(c) < 32 or ord(c) == 127 for c in name):
        raise ContextError("Unsafe archive or manifest path; name withheld")
    while name.startswith("./"):
        name = name[2:]
    path = PurePosixPath(name)
    parts = name.rstrip("/").split("/")
    if not name or path.is_absolute() or any(p in ("", ".", "..") for p in parts) or ":" in name:
        raise ContextError("Unsafe archive or manifest path; name withheld")
    return path.as_posix()


def rpc(environment: dict, method: str) -> dict:
    if method not in {"get", "status", "job_status"}:
        raise ContextError("Only read-only maintenance RPCs are supported")
    if method == "job_status":
        # The product RPC repairs interrupted jobs. Observe the file instead;
        # stale running jobs must remain blocked until an explicit recovery.
        code = ("import * as fs from 'fs';let s=fs.readfile('/tmp/alwayroute/job.json');"
                "let j=s==null?null:json(s);if(s!=null && type(j)!='object')exit(3);"
                "if(j!=null && index(['idle','running','succeeded','failed','cancelled'],j.status)<0)exit(3);"
                "printf('%J',{ok:true,busy:j?.status=='running'});")
        value = object_json(run_router(environment, ["ucode", "-"], data=code.encode(), timeout=45))
    else:
        value = object_json(run_router(environment, ["ubus", "call", "alwayroute", method, "{}"], timeout=45))
    if value.get("ok") is False:
        raise ContextError("Maintenance RPC failed; raw response withheld")
    return value


def valid_hashes(value: object) -> dict:
    if not isinstance(value, dict) or not value or len(value) > MAX_MEMBERS:
        raise ContextError("Invalid file hash response; content withheld")
    result = {}
    for name, digest in value.items():
        normal = safe_member(name)
        if normal != name or not isinstance(digest, str) or not SHA256.fullmatch(digest):
            raise ContextError("Invalid file hash response; content withheld")
        result[normal] = digest
    return result


def read_hashes(environment: dict, paths: list[str], prefix: str = "/") -> dict:
    if prefix not in {"/", "/rom/"} or not paths or len(paths) > MAX_MEMBERS:
        raise ContextError("Invalid hash request")
    paths = [safe_member(path) for path in paths]
    code = ("import * as fs from 'fs';import {sha256} from 'digest';let h={};"
            "for(let p in " + json.dumps(paths) + "){let s=fs.readfile("
            + json.dumps(prefix) + "+p);if(s==null)exit(3);h[p]=sha256(s);}printf('%J',h);")
    result = valid_hashes(object_json(run_router(environment, ["ucode", "-"], data=code.encode(), timeout=90)))
    if set(result) != set(paths):
        raise ContextError("Device hash result did not cover the requested files")
    return result


def critical_hashes(environment: dict) -> tuple[dict, bool]:
    code = ("import * as fs from 'fs';import {sha256} from 'digest';let paths="
            + json.dumps(list(REQUIRED_CONFIG))
            + ";for(let p in (fs.glob('/etc/dropbear/dropbear_*_host_key')??[]))push(paths,substr(p,1));"
            "let h={};for(let p in paths){let s=fs.readfile('/'+p);if(s==null)exit(3);h[p]=sha256(s);}"
            "printf('%J',{hashes:h,pending:fs.stat('/etc/alwayroute/applying.json')!=null});")
    result = object_json(run_router(environment, ["ucode", "-"], data=code.encode(), timeout=90))
    hashes = valid_hashes(result.get("hashes"))
    if not set(REQUIRED_CONFIG) <= set(hashes) or type(result.get("pending")) is not bool:
        raise ContextError("Critical configuration or transaction state is incomplete")
    if not any(is_host_key(name) for name in hashes):
        raise ContextError("No persistent SSH host key was captured")
    return hashes, result["pending"]


def is_host_key(name: str) -> bool:
    return bool(re.fullmatch(r"etc/dropbear/dropbear_[A-Za-z0-9_-]+_host_key", name))


def core_hash(environment: dict, path: str) -> str:
    raw = run_router(environment, ["sha256sum", path], timeout=90).split(maxsplit=1)
    if not raw or not re.fullmatch(rb"[0-9a-f]{64}", raw[0]):
        raise ContextError("Invalid core digest; raw response withheld")
    return raw[0].decode("ascii")


def revision(value: object) -> int | None:
    return value if type(value) is int and value >= 0 else None


def collect_snapshot(environment: dict, *, keep_private: bool = False) -> tuple[dict, dict]:
    board = object_json(run_router(environment, ["ubus", "call", "system", "board"]))
    status = rpc(environment, "status")
    job = rpc(environment, "job_status")
    model = rpc(environment, "get").get("model")
    if not isinstance(board.get("board_name"), str) or not isinstance(model, dict):
        raise ContextError("Device identity or saved model is unavailable")
    if any(not isinstance(status.get(section), dict) for section in ("state", "core", "service", "forwarding")):
        raise ContextError("Runtime status has an unexpected structure")
    state = status["state"]
    groups = status["core"].get("groups")
    if not isinstance(state, dict) or not isinstance(groups, dict) or type(job.get("busy")) is not bool:
        raise ContextError("Core, revision or job state is unavailable")
    selected = {}
    for name, item in groups.items():
        if not isinstance(name, str) or not isinstance(item, dict) or not isinstance(item.get("now"), str):
            raise ContextError("Core selector state is incomplete")
        selected[name] = item["now"]
    hashes, pending = critical_hashes(environment)
    flags = {}
    for section, key in (("service", "running"), ("core", "available"), ("forwarding", "running")):
        value = status.get(section, {}).get(key)
        if type(value) is not bool:
            raise ContextError("Runtime availability state is incomplete")
        flags[section + "_" + key] = value
    # The two status reads detect a concurrent management transition. This is observation, not a lock.
    final = rpc(environment, "status")
    final_job = rpc(environment, "job_status")
    if any(not isinstance(final.get(section), dict) for section in ("state", "core", "service", "forwarding")):
        raise ContextError("Final runtime status has an unexpected structure")
    if final["state"] != state or final["core"].get("groups") != groups or final_job.get("busy") != job["busy"] or any(
            final[section].get(key) != status[section].get(key)
            for section, key in (("service", "running"), ("core", "available"), ("forwarding", "running"))):
        raise ContextError("Device changed during snapshot; retry after management is idle")
    live_core = core_hash(environment, "/usr/bin/sing-box")
    rom_core = core_hash(environment, "/rom/usr/bin/sing-box")
    boot = run_router(environment, ["cat", "/proc/sys/kernel/random/boot_id"]).strip()
    result = {"schema_version": 1, "board_sha256": digest_json(board["board_name"]),
              "critical_hashes": hashes, "selectors_sha256": digest_json(selected),
              "selector_count": len(selected), "model_revision": revision(model.get("revision")),
              "saved_revision": revision(state.get("savedRevision")),
              "applied_revision": revision(state.get("appliedRevision")),
              "job_busy": job["busy"], "pending_transaction": pending,
              "core_sha256": live_core, "rom_core_sha256": rom_core,
              "boot_id_sha256": hashlib.sha256(boot).hexdigest(), **flags}
    if any(result[key] is None for key in ("model_revision", "saved_revision")) or "appliedRevision" not in state:
        raise ContextError("Configuration revisions are unavailable")
    if state["appliedRevision"] is not None and result["applied_revision"] is None:
        raise ContextError("Applied revision is invalid")
    private = {"status": status, "model": model, "selectors": selected} if keep_private else {}
    return result, private


def load_manifest(path: Path) -> dict:
    try:
        inspection = object_json(path.read_bytes())
        rows = inspection["owned_payload_hashes"]
        if not isinstance(rows, dict) or not rows or len(rows) > MAX_MEMBERS:
            raise ValueError
        result = {}
        for name, row in rows.items():
            normal = safe_member(name)
            digest = row["installed_sha256"]
            if normal != name or not normal.startswith(("etc/", "usr/", "www/")) or not SHA256.fullmatch(digest):
                raise ValueError
            result[normal] = digest
        return result
    except (OSError, KeyError, TypeError, ValueError):
        raise ContextError("Invalid image inspection manifest; content withheld") from None


def verify_manifest(environment: dict, manifest: dict) -> dict:
    actual = read_hashes(environment, list(manifest), "/rom/")
    return {"rom_manifest_match": actual == manifest, "rom_files_checked": len(manifest)}


def preflight(snapshot: dict, *, expected_board: str | None = None,
              expected_core: str | None = None) -> dict:
    checks = {"service_running": snapshot["service_running"], "core_available": snapshot["core_available"],
              "forwarding_running": snapshot["forwarding_running"], "job_idle": not snapshot["job_busy"],
              "no_pending_transaction": not snapshot["pending_transaction"],
              "revisions_aligned": snapshot["model_revision"] == snapshot["saved_revision"] == snapshot["applied_revision"],
              "core_matches_rom": snapshot["core_sha256"] == snapshot["rom_core_sha256"]}
    if expected_board is not None:
        checks["expected_board"] = snapshot["board_sha256"] == digest_json(expected_board)
    if expected_core is not None:
        if not SHA256.fullmatch(expected_core):
            raise ContextError("Expected core SHA-256 must be 64 lowercase hexadecimal characters")
        checks["expected_core"] = snapshot["core_sha256"] == expected_core
    return {"ok": all(checks.values()), "checks": checks, "snapshot_schema": 1}


def validate_snapshot(value: object) -> dict:
    if not isinstance(value, dict) or type(value.get("schema_version")) is not int or value["schema_version"] != 1:
        raise ContextError("Unsupported private snapshot")
    hashes = valid_hashes(value.get("critical_hashes"))
    if not set(REQUIRED_CONFIG) <= set(hashes) or not any(is_host_key(name) for name in hashes):
        raise ContextError("Private snapshot lacks required critical files")
    for name in ("board_sha256", "selectors_sha256", "core_sha256", "rom_core_sha256", "boot_id_sha256"):
        if not isinstance(value.get(name), str) or not SHA256.fullmatch(value[name]):
            raise ContextError("Invalid private snapshot digest")
    if "applied_revision" not in value or (value["applied_revision"] is not None and revision(value["applied_revision"]) is None):
        raise ContextError("Invalid private snapshot applied revision")
    for name in ("model_revision", "saved_revision", "selector_count"):
        if revision(value.get(name)) is None:
            raise ContextError("Invalid private snapshot counter")
    for name in ("job_busy", "pending_transaction", "service_running", "core_available", "forwarding_running"):
        if type(value.get(name)) is not bool:
            raise ContextError("Invalid private snapshot state")
    return value


def compare_snapshots(before: dict, after: dict) -> dict:
    before = validate_snapshot(before)
    after = validate_snapshot(after)
    # The boot token is deliberately informational: post-upgrade recovery must reboot.
    keys = ("board_sha256", "critical_hashes", "selectors_sha256", "selector_count", "model_revision",
            "saved_revision", "applied_revision", "job_busy", "pending_transaction", "core_sha256",
            "rom_core_sha256", "service_running", "core_available", "forwarding_running")
    checks = {name + "_unchanged": before[name] == after[name] for name in keys}
    return {"match": all(checks.values()), "checks": checks,
            "boot_changed": before["boot_id_sha256"] != after["boot_id_sha256"]}


def validate_backup(blob: bytes) -> dict:
    if not blob or len(blob) > MAX_ARCHIVE:
        raise ContextError("Backup archive is empty or too large")
    files = {}
    seen = set()
    total = 0
    try:
        # Bound all decompressed bytes before tarfile consumes PAX/long-name metadata.
        with gzip.GzipFile(fileobj=io.BytesIO(blob), mode="rb") as compressed:
            expanded = compressed.read(MAX_EXPANDED + 1)
        if len(expanded) > MAX_EXPANDED:
            raise ContextError("Backup tar stream exceeds the supported expanded limit")
        with tarfile.open(fileobj=io.BytesIO(expanded), mode="r:") as archive:
            for member in archive:
                name = safe_member(member.name)
                if name in seen or len(seen) >= MAX_MEMBERS or not name.startswith(("etc/", "root/")) and name not in {"etc", "root"}:
                    raise ContextError("Backup has duplicate, excessive or unexpected members")
                seen.add(name)
                if member.isdir():
                    continue
                if not member.isfile() or member.size < 0 or member.size > MAX_ARCHIVE:
                    raise ContextError("Backup contains unsupported member types or sizes")
                total += member.size
                if total > MAX_EXPANDED:
                    raise ContextError("Backup expanded size exceeds the supported limit")
                reader = archive.extractfile(member)
                if reader is None:
                    raise ContextError("Backup member cannot be read")
                digest = hashlib.sha256()
                actual = 0
                while block := reader.read(65536):
                    actual += len(block)
                    if actual > member.size:
                        raise ContextError("Backup member length is invalid")
                    digest.update(block)
                if actual != member.size:
                    raise ContextError("Backup member is truncated")
                files[name] = digest.hexdigest()
    except (tarfile.TarError, OSError, EOFError, ValueError):
        raise ContextError("Backup archive validation failed; content withheld") from None
    if not set(REQUIRED_CONFIG) <= set(files) or not any(is_host_key(name) for name in files):
        raise ContextError("Backup is missing required configuration or a persistent SSH host key")
    return {"member_count": len(seen), "file_hashes": files, "expanded_bytes": total,
            "archive_sha256": hashlib.sha256(blob).hexdigest()}


def private_permissions(path: Path, *, directory: bool) -> None:
    os.chmod(path, 0o700 if directory else 0o600)
    if os.name == "nt":
        # POSIX mode bits do not enforce Windows confidentiality; restrict the new local ACL too.
        try:
            identity = subprocess.run(["whoami", "/user", "/fo", "csv", "/nh"], capture_output=True,
                                      timeout=10, check=True).stdout.decode(errors="replace")
            sid = re.search(r"S-1-\d+(?:-\d+)+", identity)
            if not sid:
                raise ValueError
            grant = "*" + sid.group() + (":(OI)(CI)F" if directory else ":F")
            subprocess.run(["icacls", str(path), "/inheritance:r", "/grant:r", grant],
                           capture_output=True, timeout=15, check=True)
        except (OSError, subprocess.SubprocessError, ValueError):
            raise ContextError("Cannot enforce private local backup permissions") from None


def private_directory(label: str = "device", *, repo_root: Path | None = None) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,40}", label):
        raise ContextError("Use a short alphanumeric private snapshot label")
    root = (repo_root or REPO_ROOT).resolve()
    local = root / ".local"
    backups = local / "backups"
    for path in (local, backups):
        is_junction = getattr(path, "is_junction", lambda: False)()
        try:
            reparse = bool(getattr(path.lstat(), "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))
        except FileNotFoundError:
            reparse = False
        if path.is_symlink() or is_junction or reparse or (path.exists() and not path.is_dir()):
            raise ContextError("Private backup parent must be a real local directory")
        if not path.resolve().is_relative_to(root):
            raise ContextError("Private backup parent leaves the repository")
        path.mkdir(exist_ok=True, mode=0o700)
    if not backups.resolve().is_relative_to(root):
        raise ContextError("Private backup root leaves the repository")
    # Existing backup-parent permissions are left unchanged; the new child disables inheritance.
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    destination = backups / (label + "-" + stamp + "-" + secrets.token_hex(4))
    destination.mkdir(mode=0o700, exist_ok=False)
    private_permissions(destination, directory=True)
    return destination


def write_private(path: Path, data: bytes) -> None:
    with path.open("xb") as stream:
        private_permissions(path, directory=False)
        stream.write(data)


def save_snapshot(snapshot: dict, label: str = "snapshot", *, repo_root: Path | None = None) -> Path:
    validate_snapshot(snapshot)
    destination = private_directory(label, repo_root=repo_root)
    write_private(destination / "snapshot.json", (json.dumps(snapshot, sort_keys=True, indent=2) + "\n").encode())
    return destination


def read_snapshot(path: Path) -> dict:
    try:
        return validate_snapshot(object_json(path.read_bytes()))
    except OSError:
        raise ContextError("Cannot read the selected private snapshot") from None


def read_backup_archive(environment: dict) -> bytes:
    """Bound received SSH output, not just its size after capture_output returns."""
    process = subprocess.Popen(router_argv(environment, ["sysupgrade", "-b", "-"]),
                               stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    expired = threading.Event()
    def stop():
        expired.set()
        try:
            process.kill()
        except OSError:
            pass
    timer = threading.Timer(90, stop)
    timer.daemon = True
    timer.start()
    try:
        data = process.stdout.read(MAX_ARCHIVE + 1)
        if expired.is_set() or len(data) > MAX_ARCHIVE:
            raise ContextError("Backup output exceeded its time or size limit")
        timer.cancel()
        if process.wait(timeout=10) != 0:
            raise ContextError("Backup read failed; raw SSH output withheld")
        return data
    except subprocess.SubprocessError:
        raise ContextError("Backup read could not complete; raw SSH output withheld") from None
    finally:
        timer.cancel()
        process.stdout.close()
        if process.poll() is None:
            process.kill()
        process.wait(timeout=10)


def create_backup(environment: dict, *, apply: bool = False, expected_board: str | None = None,
                  expected_core: str | None = None, manifest: dict | None = None,
                  repo_root: Path | None = None) -> dict:
    if not apply:
        return {"apply": False, "router_read": "sysupgrade -b -", "local_destination": ".local/backups/<exclusive-directory>",
                "archive_validation": "required", "device_flash": False, "changes_persistent_configuration": False}
    before, private = collect_snapshot(environment, keep_private=True)
    ready = preflight(before, expected_board=expected_board, expected_core=expected_core)
    if not ready["ok"]:
        raise ContextError("Backup preflight failed; no archive saved")
    if manifest is not None and not verify_manifest(environment, manifest)["rom_manifest_match"]:
        raise ContextError("ROM manifest mismatch; no archive saved")
    blob = read_backup_archive(environment)
    checked = validate_backup(blob)
    if any(checked["file_hashes"].get(name) != digest for name, digest in before["critical_hashes"].items()):
        raise ContextError("Backup content differs from the captured critical configuration")
    after, _ = collect_snapshot(environment)
    comparison = compare_snapshots(before, after)
    if not comparison["match"] or comparison["boot_changed"]:
        raise ContextError("Device changed while backing up; no archive saved")
    destination = private_directory("device-backup", repo_root=repo_root)
    write_private(destination / "config.tar.gz", blob)
    write_private(destination / "snapshot.json", (json.dumps(before, sort_keys=True, indent=2) + "\n").encode())
    write_private(destination / "private-state.json", (json.dumps(private, sort_keys=True, indent=2) + "\n").encode())
    summary = {"apply": True, "archive_validated": True, "archive_bytes": len(blob),
               "archive_sha256": checked["archive_sha256"], "members": checked["member_count"],
               "critical_files": len(before["critical_hashes"]), "device_unchanged": True,
               "private_directory": destination.relative_to((repo_root or REPO_ROOT).resolve()).as_posix(),
               "device_flash": False, "changes_persistent_configuration": False}
    write_private(destination / "summary.json", (json.dumps(summary, sort_keys=True, indent=2) + "\n").encode())
    return summary


def _proc_counter(value: str) -> int:
    if not re.fullmatch(r"[0-9]+", value):
        raise ContextError("Malformed resource counter; raw content withheld")
    return int(value)


def resource_sample(environment: dict) -> dict:
    """Collect instantaneous, read-only counters; ticks are not seconds or throughput."""
    raw_pids = run_router(environment, ["sh", "-c", "pidof sing-box || true"]).split()
    if len(raw_pids) > 64 or any(not re.fullmatch(rb"[1-9][0-9]{0,9}", value) for value in raw_pids):
        raise ContextError("Unexpected core PID response; raw content withheld")
    pids = sorted(set(value.decode("ascii") for value in raw_pids))
    code = ("import * as fs from 'fs';let processes=[];for(let pid in " + json.dumps(pids)
            + ")push(processes,{stat:fs.readfile('/proc/'+pid+'/stat'),status:fs.readfile('/proc/'+pid+'/status')});"
            "printf('%J',{cpu:fs.readfile('/proc/stat'),memory:fs.readfile('/proc/meminfo'),"
            "softnet:fs.readfile('/proc/net/softnet_stat'),tcp:fs.readfile('/proc/net/snmp'),processes});")
    raw = object_json(run_router(environment, ["ucode", "-"], data=code.encode(), timeout=30))
    try:
        first = raw["cpu"].splitlines()[0].split()
        if first[0] != "cpu" or not 5 <= len(first) <= 11:
            raise ValueError
        names = ("user", "nice", "system", "idle", "iowait", "irq", "softirq", "steal", "guest", "guest_nice")
        cpu = {name: _proc_counter(value) for name, value in zip(names, first[1:])}
        mem = re.search(r"(?m)^MemAvailable:\s+([0-9]+) kB$", raw["memory"])
        if not mem:
            raise ValueError
        dropped = 0
        for line in raw["softnet"].splitlines():
            parts = line.split()
            if len(parts) < 2 or not re.fullmatch(r"[0-9a-fA-F]+", parts[1]):
                raise ValueError
            dropped += int(parts[1], 16)
        tcp = [line.split()[1:] for line in raw["tcp"].splitlines() if line.startswith("Tcp:")]
        if len(tcp) != 2 or len(tcp[0]) != len(tcp[1]) or "RetransSegs" not in tcp[0]:
            raise ValueError
        retrans = _proc_counter(tcp[1][tcp[0].index("RetransSegs")])
        rows = raw["processes"]
        if not isinstance(rows, list) or len(rows) != len(pids):
            raise ValueError
        processes = []
        for row in rows:
            stat, status = row["stat"], row["status"]
            if stat is None or status is None:
                continue  # A process may exit during an observational sample.
            fields = stat[stat.rindex(")") + 1:].split()
            if len(fields) < 22:
                raise ValueError
            vmrss = re.search(r"(?m)^VmRSS:\s+([0-9]+) kB$", status)
            vmhwm = re.search(r"(?m)^VmHWM:\s+([0-9]+) kB$", status)
            if not vmrss or not vmhwm:
                raise ValueError
            processes.append({"utime_ticks": _proc_counter(fields[11]), "stime_ticks": _proc_counter(fields[12]),
                              "rss_pages": _proc_counter(fields[21]), "vmrss_kib": int(vmrss.group(1)),
                              "vmhwm_kib": int(vmhwm.group(1))})
        return {"core_pid_count": len(pids), "captured_processes": len(processes), "processes": processes,
                "aggregate_cpu_ticks": cpu, "mem_available_kib": int(mem.group(1)),
                "softnet_dropped_packets": dropped, "tcp_retransmitted_segments": retrans,
                "sampling": "instantaneous_cumulative_counters", "ticks_are_seconds": False,
                "throughput_measured": False, "path_verified": False}
    except (KeyError, TypeError, ValueError, AttributeError):
        raise ContextError("Resource counters are incomplete; raw content withheld") from None
