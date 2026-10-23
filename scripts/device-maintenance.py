"""Read-only preflight, sanitized snapshots, comparison and private sysupgrade backup.

Backup defaults to a plan. No command flashes, starts a service, changes selectors or applies configuration.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from alwayroute_context import ContextError, load_environment
from alwayroute_device import (collect_snapshot, compare_snapshots, create_backup, load_manifest,
                               preflight, read_snapshot, resource_sample, save_snapshot, verify_manifest)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env", type=Path, required=True)
    parser.add_argument("--expect-board")
    parser.add_argument("--expect-core-sha256")
    parser.add_argument("--manifest", type=Path, help="Image inspection JSON; compare owned ROM payload hashes only")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("preflight", help="Observe idle, aligned revision and core state; no device writes")
    commands.add_parser("resources", help="Read whitelisted CPU ticks, memory, drop and retransmit counters; no throughput claim")
    snapshot = commands.add_parser("snapshot", help="Print hash-only state or save in an exclusive private directory")
    snapshot.add_argument("--save", metavar="LABEL")
    compare = commands.add_parser("compare", help="Compare live state with a selected private snapshot")
    compare.add_argument("snapshot", type=Path)
    backup = commands.add_parser("backup", help="Plan sysupgrade backup; --apply reads archive and saves privately on PC")
    backup.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    try:
        environment = load_environment(args.env)
        manifest = load_manifest(args.manifest) if args.manifest else None
        if args.command == "resources":
            if args.manifest or args.expect_board or args.expect_core_sha256:
                raise ContextError("Use preflight for identity and ROM expectations")
            result = resource_sample(environment)
            ok = True
        elif args.command == "backup":
            result = create_backup(environment, apply=args.apply, expected_board=args.expect_board,
                                   expected_core=args.expect_core_sha256, manifest=manifest)
            ok = True
        else:
            baseline = read_snapshot(args.snapshot) if args.command == "compare" else None
            snapshot, _ = collect_snapshot(environment)
            observed = preflight(snapshot, expected_board=args.expect_board, expected_core=args.expect_core_sha256)
            manifest_result = verify_manifest(environment, manifest) if manifest is not None else {}
            if args.command == "preflight":
                result = {**observed, **manifest_result}
            elif args.command == "compare":
                result = {**compare_snapshots(baseline, snapshot), "preflight": observed, **manifest_result}
            else:
                result = {"snapshot": snapshot, "preflight": observed, **manifest_result}
                if args.save:
                    destination = save_snapshot(snapshot, args.save)
                    result["private_directory"] = destination.relative_to(Path(__file__).resolve().parents[1]).as_posix()
            ok = observed["ok"] and manifest_result.get("rom_manifest_match", True) and result.get("match", True)
        print(json.dumps(result, sort_keys=True, indent=2))
        return 0 if ok else 1
    except (ContextError, OSError, TypeError, KeyError, ValueError):
        # Even parser/type errors in remote content must not echo a server, path or model value.
        print("Device maintenance could not complete; check environment, prerequisites and private inputs. Raw content withheld.", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
