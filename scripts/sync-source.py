"""Preview or apply reviewed source synchronization to an independent SSH workspace."""
from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path, PurePosixPath

from alwayroute_context import ContextError, load_environment, ssh_target

ROOT = Path(__file__).resolve().parents[1]
BLOCKED_DIRS = {".git", ".local", ".ssh", ".gnupg", "keys", "secrets", "private", "credentials",
                "backups", "backup", "downloads", "artifacts", "toolchains", "build-cache", "openwrt-build",
                "private-probes", "node_modules", ".cache", ".venv", "venv", "__pycache__", "build_dir",
                "staging_dir", "dl", "build", "dist", "coverage"}
BLOCKED_FILES = (".env", ".env.*", ".netrc", ".npmrc", ".pypirc", ".git-credentials", "*.pem", "*.key",
                 "*.p12", "*.pfx", "*.ppk", "id_rsa*", "id_ed25519*", "id_ecdsa*", "id_dsa*",
                 "authorized_keys", "known_hosts", "credentials*", "secrets.*", "*.bin", "*.img", "*.iso",
                 "*.ipk", "*.apk", "*.trx", "*.itb", "*.ubi", "*.exe", "*.dll", "*.o", "*.a", "*.so",
                 "*.so.*", "*.pyc", "*.zip", "*.tar", "*.gz", "*.xz", "*.7z", "session-log.md")


def eligible(name: str, root: Path = ROOT) -> bool:
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts or any(p.lower() in BLOCKED_DIRS for p in path.parts[:-1]):
        return False
    actual = root.joinpath(*path.parts)
    if not actual.is_file() or actual.is_symlink():
        return False
    relative_parent = Path()
    for part in path.parts[:-1]:
        relative_parent /= part
        if (root / relative_parent).is_symlink():
            return False
    base = path.name.lower()
    if base == ".env.example" or fnmatch.fnmatchcase(base, ".env.*.example"):
        return True
    return not any(fnmatch.fnmatchcase(base, pattern) for pattern in BLOCKED_FILES)


def validate_workspace(build: dict) -> tuple[str, str]:
    host = ssh_target(build.get("ssh_alias"), "build.ssh_alias")
    if build.get("executor") != "ssh":
        raise ContextError("Source sync requires build.executor=ssh")
    workspace = PurePosixPath(build.get("project_workspace", ""))
    if not workspace.is_absolute() or len(workspace.parts) < 4 or ".." in workspace.parts:
        raise ContextError("Select a dedicated absolute project workspace")
    if any(p.lower() in BLOCKED_DIRS for p in workspace.parts):
        raise ContextError("Project workspace cannot be a private, build, cache or artifact directory")
    for key in ("task_root", "openwrt_tree", "cache_root", "toolchain_root", "output_root"):
        if key not in build:
            continue
        protected = PurePosixPath(build[key])
        if workspace == protected or workspace in protected.parents or (key != "task_root" and protected in workspace.parents):
            raise ContextError("Project workspace overlaps a protected build location")
    return host, str(workspace)


def msys_path(path: str | Path) -> str:
    value = str(path).replace("\\", "/")
    return "/" + value[0].lower() + value[2:] if re.match(r"^[A-Za-z]:/", value) else value


def runtime(rsync_option: str | None, ssh_option: str | None) -> tuple[str, str, dict]:
    env = os.environ.copy()
    search = [str(ROOT / ".local/tools/rsync/bin")]
    git = shutil.which("git")
    if os.name == "nt" and git:
        git_root = Path(git).resolve().parent.parent
        search += [str(git_root / "usr/bin"), str(git_root / "mingw64/bin")]
    env["PATH"] = os.pathsep.join(search + [env.get("PATH", "")])
    rsync = rsync_option or shutil.which("rsync", path=env["PATH"])
    ssh = ssh_option or shutil.which("ssh", path=env["PATH"])
    if not rsync or not ssh:
        raise ContextError("rsync/ssh unavailable; select existing executables, do not install automatically")
    return rsync, ssh, env


def source_snapshot(root: Path = ROOT) -> dict[str, str]:
    result = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
                            cwd=root, capture_output=True, check=True)
    names = sorted({os.fsdecode(name) for name in result.stdout.split(b"\0") if name})
    return {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in names if eligible(name, root)}


def check_remote_workspace(ssh: str, host: str, build: dict, process_env: dict) -> None:
    # Inspect actual destinations too: lexical checks cannot detect a workspace symlink into a build tree.
    guard = """import json,pathlib,sys
d=json.loads(sys.argv[1]);w=pathlib.Path(d['project_workspace']);r=w.resolve()
if r!=w: raise SystemExit('symlink workspace')
if (r/'include/toplevel.mk').exists() or (r/'staging_dir').exists(): raise SystemExit('OpenWrt tree')
for k in ('task_root','openwrt_tree','cache_root','toolchain_root','output_root'):
 if k not in d: continue
 p=pathlib.Path(d[k]).resolve()
 if r==p or r in p.parents or (k!='task_root' and p in r.parents): raise SystemExit('protected tree')
"""
    payload = {key: value for key, value in build.items() if key in {
        "project_workspace", "task_root", "openwrt_tree", "cache_root", "toolchain_root", "output_root"}}
    command = shlex.join(["python3", "-c", guard, json.dumps(payload)])
    result = subprocess.run([ssh, "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes",
                             "-o", "ConnectTimeout=10", host, command],
                            capture_output=True, env=process_env, timeout=30, check=False)
    if result.returncode:
        raise ContextError("Remote workspace validation failed; no source copy attempted")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env", required=True, type=Path, help="Private environment JSON")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true", help="Apply only an unchanged successful preview")
    mode.add_argument("--dry-run", action="store_true", help="Preview (default)")
    parser.add_argument("--rsync", help="Existing rsync executable")
    parser.add_argument("--ssh", help="Existing SSH executable")
    parser.add_argument("--plan", type=Path, default=ROOT / ".local/runs/source-sync-plan.json")
    args = parser.parse_args(argv)
    try:
        build = load_environment(args.env).get("build", {})
        host, workspace = validate_workspace(build)
        rsync, ssh, process_env = runtime(args.rsync, args.ssh)
        check_remote_workspace(ssh, host, build, process_env)
        snapshot = source_snapshot()
        if not snapshot:
            raise ContextError("No eligible source files")
        plan = args.plan.resolve()
        if not plan.is_relative_to((ROOT / ".local").resolve()):
            raise ContextError("Sync plan must stay inside this repository's ignored .local directory")
        plan.parent.mkdir(parents=True, exist_ok=True)
        os.chmod(plan.parent, 0o700)
        staged = Path(tempfile.mkdtemp(prefix="source-snapshot-", dir=plan.parent))
        # Send immutable reviewed bytes, rather than files another editor can change during rsync.
        try:
            for name, expected in snapshot.items():
                target = staged / name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(ROOT / name, target)
                if hashlib.sha256(target.read_bytes()).hexdigest() != expected:
                    raise ContextError("Source changed while preparing the snapshot; preview again")
        except BaseException:
            if staged.resolve().is_relative_to(plan.parent.resolve()):
                shutil.rmtree(staged)
            raise
        with tempfile.NamedTemporaryFile(dir=plan.parent, delete=False) as handle:
            manifest = Path(handle.name)
            handle.write(b"".join(os.fsencode(name) + b"\0" for name in snapshot))
        try:
            ssh_command = shlex.join([msys_path(ssh) if os.name == "nt" else ssh,
                                      "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes"])
            base = [rsync, "--archive", "--checksum", "--no-perms", "--no-owner", "--no-group", "--omit-dir-times",
                    "--relative", "--chmod=D755,F644", "--from0", "--files-from=" + msys_path(manifest),
                    "--mkpath", "--protect-args", "--itemize-changes", "--human-readable", "-e", ssh_command]
            tail = [msys_path(staged) + "/", host + ":" + workspace.rstrip("/") + "/"]
            preview = subprocess.run(base + ["--dry-run"] + tail, cwd=ROOT, env=process_env,
                                     capture_output=True, check=True, timeout=300)
            current = {"schema_version": 1, "target": tail[-1], "files": snapshot,
                       "preview_sha256": hashlib.sha256(preview.stdout).hexdigest()}
            if source_snapshot() != snapshot:
                raise ContextError("Sources changed during preview; preview again")
            if args.apply:
                try:
                    previous = json.loads(plan.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    raise ContextError("Run and review a successful preview before --apply") from None
                if previous != current:
                    raise ContextError("Sources, destination or remote changes differ from reviewed preview; preview again")
                subprocess.run(base + tail, cwd=ROOT, env=process_env, check=True, timeout=600,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                plan.unlink()
                print(f"Applied {len(snapshot)} source files; no remote deletion requested.")
            else:
                plan.write_text(json.dumps(current, indent=2) + "\n", encoding="utf-8")
                os.chmod(plan, 0o600)
                sys.stdout.buffer.write(preview.stdout)
                print(f"Previewed {len(snapshot)} source files. Review changes before --apply; no remote deletion requested.")
        finally:
            manifest.unlink(missing_ok=True)
            if staged.resolve().is_relative_to(plan.parent.resolve()):
                shutil.rmtree(staged)
        return 0
    except (ContextError, OSError, subprocess.SubprocessError) as error:
        message = str(error) if isinstance(error, ContextError) else "Sync failed; check selected environment and existing tools"
        print(message, file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
