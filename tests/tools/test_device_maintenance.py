"""Isolated device maintenance checks; no router, SSH or build operation is executed."""
from __future__ import annotations

import copy
from contextlib import redirect_stdout, redirect_stderr
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace
import tarfile
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import alwayroute_device as device
from alwayroute_context import ContextError

spec = importlib.util.spec_from_file_location("device_maintenance_cli", ROOT / "scripts/device-maintenance.py")
cli = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cli)
SECRET = "private-synthetic-node-and-password"


def make_archive(*, extra=None, omit=None):
    content = {name: ("synthetic:" + name).encode() for name in device.REQUIRED_CONFIG}
    content["etc/dropbear/dropbear_ed25519_host_key"] = SECRET.encode()
    if omit:
        content.pop(omit)
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w:gz") as archive:
        for name, raw in content.items():
            member = tarfile.TarInfo(name)
            member.size = len(raw)
            archive.addfile(member, io.BytesIO(raw))
        if extra is not None:
            member = extra if isinstance(extra, tarfile.TarInfo) else tarfile.TarInfo(extra)
            archive.addfile(member, io.BytesIO(b""))
    return output.getvalue(), content


def sample_snapshot():
    _, content = make_archive()
    return {"schema_version": 1, "board_sha256": device.digest_json("synthetic-board"),
            "critical_hashes": {name: hashlib.sha256(raw).hexdigest() for name, raw in content.items()},
            "selectors_sha256": device.digest_json({"synthetic-group": SECRET}), "selector_count": 3,
            "model_revision": 37, "saved_revision": 37, "applied_revision": 37,
            "job_busy": False, "pending_transaction": False, "core_sha256": "a" * 64,
            "rom_core_sha256": "a" * 64, "boot_id_sha256": "b" * 64,
            "service_running": True, "core_available": True, "forwarding_running": True}


class MaintenanceTests(unittest.TestCase):
    def test_optional_deployment_files_preserve_presence_without_blocking_public_images(self):
        # Standard OpenWrt may use password authentication and no custom defaults.
        before = sample_snapshot()
        device.validate_snapshot(before)
        blob, _ = make_archive()
        device.validate_backup(blob)
        after = copy.deepcopy(before)
        for name in device.OPTIONAL_CONFIG:
            after["critical_hashes"][name] = hashlib.sha256(name.encode()).hexdigest()
        device.validate_snapshot(after)
        self.assertFalse(device.compare_snapshots(before, after)["match"])
        self.assertFalse(device.compare_snapshots(after, before)["match"])
        for hashes in (before["critical_hashes"], after["critical_hashes"]):
            with mock.patch.object(device, "run_router", return_value=json.dumps(
                    {"hashes": hashes, "pending": False}).encode()):
                self.assertEqual(device.critical_hashes({}), (hashes, False))

    def test_tar_valid_required_files_and_no_extraction(self):
        blob, content = make_archive()
        with mock.patch.object(tarfile.TarFile, "extractall", side_effect=AssertionError("must never extract")):
            result = device.validate_backup(blob)
        self.assertEqual(result["file_hashes"], {name: hashlib.sha256(raw).hexdigest() for name, raw in content.items()})
        self.assertNotIn(SECRET, json.dumps(result))

    def test_tar_rejects_traversal_absolute_duplicate_and_unexpected(self):
        for name in ("../outside", "/etc/shadow", "etc/../../outside", "etc\\shadow", "etc//shadow",
                     "etc/config/network", "tmp/unsafe", "etc/secret\nname", "C:/secret"):
            with self.subTest(kind=name):
                blob, _ = make_archive(extra=name)
                with self.assertRaises(ContextError):
                    device.validate_backup(blob)

    def test_tar_rejects_links_devices_and_fifos(self):
        for kind in (tarfile.SYMTYPE, tarfile.LNKTYPE, tarfile.FIFOTYPE, tarfile.CHRTYPE):
            member = tarfile.TarInfo("etc/unsupported")
            member.type = kind
            member.linkname = "../../outside"
            blob, _ = make_archive(extra=member)
            with self.subTest(kind=kind), self.assertRaises(ContextError):
                device.validate_backup(blob)

    def test_tar_requires_configuration_and_host_key(self):
        blob, _ = make_archive(omit="etc/alwayroute/current.json")
        with self.assertRaises(ContextError):
            device.validate_backup(blob)
        blob, _ = make_archive()
        with mock.patch.object(device, "is_host_key", return_value=False), self.assertRaises(ContextError):
            device.validate_backup(blob)

    def test_tar_size_and_corruption_limits(self):
        blob, _ = make_archive()
        for raw in (b"", b"not gzip", blob[:24]):
            with self.subTest(length=len(raw)), self.assertRaises(ContextError):
                device.validate_backup(raw)
        with mock.patch.object(device, "MAX_EXPANDED", 8), self.assertRaises(ContextError):
            device.validate_backup(blob)
        with mock.patch.object(device, "MAX_MEMBERS", 2), self.assertRaises(ContextError):
            device.validate_backup(blob)

    def test_tar_expansion_limit_also_covers_pax_metadata(self):
        output = io.BytesIO()
        with tarfile.open(fileobj=output, mode="w:gz", format=tarfile.PAX_FORMAT) as archive:
            member = tarfile.TarInfo("etc/comment")
            member.pax_headers = {"comment": "x" * 131072}
            archive.addfile(member, io.BytesIO())
        with mock.patch.object(device, "MAX_EXPANDED", 65536), self.assertRaises(ContextError):
            device.validate_backup(output.getvalue())

    def test_backup_receive_stops_at_the_compressed_limit(self):
        process = mock.Mock()
        process.stdout = io.BytesIO(b"x" * 33)
        process.poll.return_value = None
        with mock.patch.object(device, "router_argv", return_value=["ssh", "fixture"]), \
             mock.patch.object(device.subprocess, "Popen", return_value=process), \
             mock.patch.object(device, "MAX_ARCHIVE", 32), self.assertRaises(ContextError):
            device.read_backup_archive({})
        process.kill.assert_called_once()

    def test_compare_detects_configuration_selector_revision_job_and_core_changes(self):
        before = sample_snapshot()
        changes = {"selectors_sha256": "c" * 64, "model_revision": 38, "saved_revision": 38,
                   "applied_revision": 38, "job_busy": True, "pending_transaction": True,
                   "core_available": False, "service_running": False, "forwarding_running": False,
                   "core_sha256": "d" * 64, "rom_core_sha256": "d" * 64}
        self.assertTrue(device.compare_snapshots(before, before)["match"])
        for field, value in changes.items():
            after = copy.deepcopy(before)
            after[field] = value
            with self.subTest(field=field):
                self.assertFalse(device.compare_snapshots(before, after)["match"])
        after = copy.deepcopy(before)
        after["critical_hashes"]["etc/shadow"] = "e" * 64
        self.assertFalse(device.compare_snapshots(before, after)["match"])
        after = copy.deepcopy(before)
        after["boot_id_sha256"] = "f" * 64
        result = device.compare_snapshots(before, after)
        self.assertTrue(result["match"])
        self.assertTrue(result["boot_changed"])
        self.assertNotIn(SECRET, json.dumps(result))

    def test_snapshot_rejects_missing_critical_files_or_unknown_state(self):
        for field, value in (("critical_hashes", {"etc/shadow": "a" * 64}), ("job_busy", None),
                             ("saved_revision", True), ("schema_version", True)):
            bad = sample_snapshot()
            bad[field] = value
            with self.subTest(field=field), self.assertRaises(ContextError):
                device.validate_snapshot(bad)

    def test_stopped_snapshot_records_no_applied_revision_without_claiming_ready(self):
        snap = sample_snapshot()
        snap["applied_revision"] = None
        snap["service_running"] = False
        snap["core_available"] = False
        device.validate_snapshot(snap)
        self.assertFalse(device.preflight(snap)["ok"])

    def test_preflight_is_dynamic_and_rejects_busy_or_mismatched_identity(self):
        snap = sample_snapshot()
        self.assertTrue(device.preflight(snap, expected_board="synthetic-board", expected_core="a" * 64)["ok"])
        self.assertFalse(device.preflight(snap, expected_board="different-board")["ok"])
        snap["job_busy"] = True
        self.assertFalse(device.preflight(snap)["ok"])

    def test_manifest_reads_only_rom_and_rejects_unsafe_paths(self):
        with tempfile.TemporaryDirectory() as temp:
            manifest = Path(temp) / "manifest.json"
            manifest.write_text(json.dumps({"owned_payload_hashes": {"usr/libexec/alwayroute-job": {"installed_sha256": "a" * 64}}}))
            expected = device.load_manifest(manifest)
            with mock.patch.object(device, "read_hashes", return_value=expected) as reader:
                self.assertTrue(device.verify_manifest({}, expected)["rom_manifest_match"])
                self.assertEqual(reader.call_args.args[2], "/rom/")
            manifest.write_text(json.dumps({"owned_payload_hashes": {"../secret": {"installed_sha256": "a" * 64}}}))
            with self.assertRaises(ContextError):
                device.load_manifest(manifest)

    def test_live_collection_is_read_only_and_hashes_private_selectors(self):
        snap = sample_snapshot()
        status = {"ok": True, "state": {"savedRevision": 37, "appliedRevision": 37},
                  "service": {"running": True}, "core": {"available": True, "groups": {SECRET: {"now": SECRET}}},
                  "forwarding": {"running": True}, "private": SECRET}
        def remote(environment, command, **kwargs):
            if command == ["ubus", "call", "system", "board"]:
                return json.dumps({"board_name": "synthetic-board", "hostname": SECRET}).encode()
            if command[:3] == ["ubus", "call", "alwayroute"]:
                method = command[3]
                data = status if method == "status" else {"busy": False, "job": SECRET} if method == "job_status" else {"model": {"revision": 37, "secret": SECRET}}
                return json.dumps(data).encode()
            if command == ["ucode", "-"]:
                self.assertIn(b"fs.readfile", kwargs["data"])
                self.assertNotIn(b"fs.writefile", kwargs["data"])
                if b"/tmp/alwayroute/job.json" in kwargs["data"]:
                    return b'{"ok":true,"busy":false}'
                return json.dumps({"hashes": snap["critical_hashes"], "pending": False}).encode()
            if command[0] == "sha256sum":
                return ("a" * 64 + "  ignored").encode()
            if command == ["cat", "/proc/sys/kernel/random/boot_id"]:
                return SECRET.encode()
            raise AssertionError("Unexpected operation")
        with mock.patch.object(device, "run_router", side_effect=remote):
            result, private = device.collect_snapshot({})
        self.assertEqual(result["model_revision"], 37)
        self.assertEqual(result["selector_count"], 1)
        self.assertEqual(private, {})
        self.assertNotIn(SECRET, json.dumps(result))
        self.assertTrue(device.preflight(result)["ok"])

    def test_resources_whitelist_cpu_ticks_memory_and_packet_counters(self):
        fields = ["S"] + ["0"] * 22
        fields[11], fields[12], fields[21] = "25", "7", "42"
        proc = "123 (synthetic private core) " + " ".join(fields)
        raw = {"cpu": "cpu 100 2 30 400 5 6 7 8 0 0\n", "memory": "MemAvailable: 2048 kB\n",
               "softnet": "00000001 00000002 00000003\n00000004 00000005 00000006\n",
               "tcp": "Tcp: RtoAlgorithm RetransSegs InSegs\nTcp: 1 9 100\n",
               "processes": [{"stat": proc, "status": "Name: " + SECRET + "\nVmRSS: 168 kB\nVmHWM: 200 kB\n"}]}
        with mock.patch.object(device, "run_router", side_effect=[b"123\n", json.dumps(raw).encode()]) as remote:
            result = device.resource_sample({})
        self.assertEqual(remote.call_args_list[0].args[1], ["sh", "-c", "pidof sing-box || true"])
        self.assertEqual(result["processes"][0], {"utime_ticks": 25, "stime_ticks": 7, "rss_pages": 42, "vmrss_kib": 168, "vmhwm_kib": 200})
        self.assertEqual(result["softnet_dropped_packets"], 7)
        self.assertEqual(result["tcp_retransmitted_segments"], 9)
        self.assertEqual(result["mem_available_kib"], 2048)
        self.assertFalse(result["ticks_are_seconds"])
        self.assertFalse(result["throughput_measured"])
        self.assertNotIn(SECRET, json.dumps(result))
        self.assertNotIn("synthetic private core", json.dumps(result))

    def test_resources_reject_non_numeric_pid_without_second_command(self):
        with mock.patch.object(device, "run_router", return_value=b"123; unsafe") as remote, self.assertRaises(ContextError):
            device.resource_sample({})
        self.assertEqual(remote.call_count, 1)

    def test_existing_backup_parent_permissions_are_not_changed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            parent = root / ".local/backups"
            parent.mkdir(parents=True)
            with mock.patch.object(device, "private_permissions") as permissions:
                destination = device.private_directory(repo_root=root)
            permissions.assert_called_once_with(destination, directory=True)

    def test_local_snapshot_directory_rejects_parent_symlink_and_path_label(self):
        with self.assertRaises(ContextError):
            device.private_directory("../escape")
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / ".local").write_text("not a directory")
            with self.assertRaises(ContextError):
                device.private_directory(repo_root=root)

    def test_backup_parent_reparse_point_is_rejected_on_python311(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            (root / ".local/backups").mkdir(parents=True)
            original = Path.lstat
            def lstat(path):
                if path == root / ".local/backups":
                    return SimpleNamespace(st_file_attributes=0x400, st_mode=original(path).st_mode)
                return original(path)
            with mock.patch.object(Path, "lstat", lstat), self.assertRaises(ContextError):
                device.private_directory(repo_root=root)

    def test_backup_plan_never_contacts_router_or_creates_directory(self):
        with mock.patch.object(device, "run_router", side_effect=AssertionError("no SSH")), mock.patch.object(device, "private_directory", side_effect=AssertionError("no local write")):
            result = device.create_backup({})
        self.assertFalse(result["apply"])
        self.assertFalse(result["device_flash"])

    def test_backup_private_roundtrip_and_race_rejection(self):
        snapshot = sample_snapshot()
        blob, _ = make_archive()
        private = {"model": {"secret": SECRET}, "status": {"private": SECRET}}
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with mock.patch.object(device, "collect_snapshot", side_effect=[(snapshot, private), (snapshot, {})]), mock.patch.object(device, "read_backup_archive", return_value=blob) as remote:
                result = device.create_backup({}, apply=True, repo_root=root)
            remote.assert_called_once_with({})
            self.assertNotIn(SECRET, json.dumps(result))
            destination = root / result["private_directory"]
            self.assertIn(SECRET, (destination / "private-state.json").read_text())
            self.assertEqual((destination / "config.tar.gz").read_bytes(), blob)
            if os.name != "nt":
                self.assertEqual(destination.stat().st_mode & 0o777, 0o700)
                self.assertEqual((destination / "config.tar.gz").stat().st_mode & 0o777, 0o600)
            changed = copy.deepcopy(snapshot)
            changed["boot_id_sha256"] = "c" * 64
            with mock.patch.object(device, "collect_snapshot", side_effect=[(snapshot, private), (changed, {})]), mock.patch.object(device, "read_backup_archive", return_value=blob), self.assertRaises(ContextError):
                device.create_backup({}, apply=True, repo_root=root)
            self.assertEqual(len(list((root / ".local/backups").iterdir())), 1)

    def test_cli_never_prints_private_remote_error_or_state(self):
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(cli, "load_environment", return_value={}), mock.patch.object(cli, "collect_snapshot", side_effect=ContextError(SECRET)), redirect_stdout(out), redirect_stderr(err):
            result = cli.main(["--env", "synthetic.json", "preflight"])
        self.assertEqual(result, 2)
        self.assertNotIn(SECRET, out.getvalue() + err.getvalue())
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(cli, "load_environment", return_value={}), mock.patch.object(cli, "collect_snapshot", return_value=(sample_snapshot(), {"secret": SECRET})), redirect_stdout(out), redirect_stderr(err):
            self.assertEqual(cli.main(["--env", "synthetic.json", "snapshot"]), 0)
        self.assertNotIn(SECRET, out.getvalue() + err.getvalue())


if __name__ == "__main__":
    unittest.main()
