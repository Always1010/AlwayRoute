"""Isolated external adapter ownership, fail-closed and source-scope checks.

Uses the real shell and ucode/fs metadata validator, with nft/ip command doubles.
The isolated build user's UID substitutes for root in the test copy only.
Does not validate nft syntax against a kernel or claim terminal acceptance.
Run on a host with existing POSIX sh, Python 3 and ucode/fs; installs nothing.
"""
import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
ADAPTER = ROOT / "firmware/openwrt/alwayroute-forwarding/files/alwayroute-external-forwarding"
CONFIG = {
    "schema": 1, "revision": 3, "enabled": True, "family": "ipv4", "faultPolicy": "block",
    "link": {"interface": "br-lan", "routerAddress": "192.0.2.1",
             "gatewayAddress": "192.0.2.2", "gatewayMac": "02:00:00:00:00:02"},
    "clients": [{"address": "192.0.2.3", "mac": "02:00:00:00:00:03"}],
    "dns": {"gatewayPort": 1053, "listenPort": 1053, "localDomains": ["lan"]},
    "bypass4": [],
}

DOUBLE = r'''#!/usr/bin/env python3
import json, os, pathlib, re, stat, sys
p = pathlib.Path(os.environ['AR_EXTERNAL_STATE'])
s = json.loads(p.read_text())
name, a = pathlib.Path(sys.argv[0]).name, sys.argv[1:]
with pathlib.Path(str(p)+'.log').open('a') as f:
    f.write(name+' '+repr(a)+'\n')
rc = 0
if name == 'nft':
    if a[:1] == ['-s']: a = a[1:]
    if a == ['list', 'tables']:
        rc = 1 if s.get('query_failed') else 0
        if s.get('internal'): print('table inet alwayroute')
    elif a[:3] == ['list', 'table', 'inet']:
        present = s.get('internal') if a[-1] == 'alwayroute' else s.get('table')
        if present: print(s.get('nft_text', 'foreign table'))
        else: rc = 1
    elif a == ['list', 'ruleset']:
        print('flow add @ft' if s.get('offload') else '')
    elif '--check' in a or '--file' in a:
        text = pathlib.Path(a[a.index('--file')+1]).read_text()
        pathlib.Path(str(p)+'.candidate').write_text(text)
        active = 'chain selected_dns' in text
        if '--check' in a:
            if s.get('fail_check'): rc = 1
        elif s.get('fail_nft') or (active and s.get('fail_active')):
            rc = 1
        else:
            s['table'] = True
            s['nft_text'] = text.removeprefix('delete table inet alwayroute_external\n')
    elif a == ['delete', 'table', 'inet', 'alwayroute_external']:
        if s.get('fail_delete'): rc = 1
        else: s['table'] = False
    else: raise AssertionError(a)
elif name == 'ip':
    if a[:1] == ['-N']: a = a[1:]
    if a[:3] == ['link', 'show', 'dev']:
        rc = 1 if s.get('missing_lan') else 0
    elif a[:5] == ['-4', '-o', 'addr', 'show', 'dev']:
        print('2: br-lan    inet '+s.get('router_address', '192.0.2.1')+'/'+str(s.get('router_prefix', 24))+' scope global br-lan')
    elif a[:3] == ['-4', 'route', 'get']:
        if s.get('offlink'): print(a[3]+' via 198.51.100.1 dev wan src 198.51.100.2')
        else: print(a[3]+' dev br-lan src 192.0.2.1 uid 0')
    elif a[:4] == ['-4', 'neigh', 'show', 'to']:
        if not s.get('missing_neighbour'): print(a[4]+' lladdr '+s.get('gateway_mac', '02:00:00:00:00:02')+' REACHABLE')
    elif a == ['-4', 'rule', 'show']:
        if s.get('legacy_rule'): print('10231: from all fwmark 0x41000000/0xff000000 lookup 20231')
        if s.get('foreign_rule'): print('10232: from all fwmark 0x43000000/0xff000000 lookup 20233')
        elif s.get('rule'): print('10232:\tfrom all fwmark 0x42000000/0xff000000 lookup 20232')
    elif a[:4] == ['-4', 'route', 'show', 'table']:
        if a[-1] == 'all' and s.get('legacy_route'): print('local default dev lo table 20231 scope host')
        if s.get('foreign_route'): print('default via 198.51.100.1 dev wan onlink'+s.get('route_suffix', ''))
        elif s.get('route'):
            print('default via 192.0.2.2 dev br-lan onlink'+s.get('route_suffix', ''))
            if s.get('extra_route'): print('198.51.100.0/24 dev wan  ')
    elif a[:3] == ['-4', 'route', 'add']:
        if s.get('fail_route_add'): rc = 1
        else: s['route'] = True
    elif a[:3] == ['-4', 'rule', 'add']:
        if s.get('fail_rule_add'): rc = 1
        else: s['rule'] = True
    elif a[:3] == ['-4', 'route', 'del']:
        if s.get('fail_route_del'): rc = 1
        else: s['route'] = False
    elif a[:3] == ['-4', 'rule', 'del']:
        if s.get('fail_rule_del'): rc = 1
        else: s['rule'] = False
    else: raise AssertionError(a)
p.write_text(json.dumps(s))
sys.exit(rc)
'''


UCODE = os.environ.get("ALWAYROUTE_TEST_UCODE") or shutil.which("ucode")


@unittest.skipUnless(shutil.which("sh") and UCODE, "existing sh and ucode/fs required")
class ExternalForwardingTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="alwayroute-external-")
        self.root = Path(self.temp.name)
        self.private = self.root / "runtime"
        self.private.mkdir(mode=0o700)
        self.runtime = self.private / "external-runtime.json"
        self.write_config(CONFIG)
        self.state = self.root / "state.json"
        self.state.write_text("{}")
        self.bin = self.root / "bin"
        self.bin.mkdir()
        for name in ("nft", "ip"):
            command = self.bin / name
            command.write_text(DOUBLE, encoding="utf-8")
            command.chmod(0o755)
        self.script = self.root / "adapter.sh"
        # A stat executable is intentionally unusable, as on the target image.
        (self.bin / "stat").write_text("#!/bin/sh\nexit 91\n")
        (self.bin / "stat").chmod(0o755)
        source = ADAPTER.read_text(encoding="utf-8")
        self.assertIn("st.uid!=0", source)
        self.script.write_text(source.replace("/tmp/alwayroute", self.private.as_posix())
                               .replace("st.uid!=0", "st.uid!="+str(os.getuid())), encoding="utf-8")
        if not os.access(UCODE, os.X_OK):
            raise RuntimeError("Configured existing host ucode is not executable")
        self.env = {**os.environ, "PATH": str(self.bin)+os.pathsep+str(Path(UCODE).parent)+os.pathsep+os.environ["PATH"],
                    "AR_EXTERNAL_STATE": str(self.state)}

    def tearDown(self):
        self.temp.cleanup()

    def write_config(self, value):
        self.runtime.write_text(json.dumps(value), encoding="utf-8")
        self.runtime.chmod(0o600)

    def update(self, **values):
        state = self.read_state()
        state.update(values)
        self.state.write_text(json.dumps(state))

    def read_state(self):
        return json.loads(self.state.read_text())

    def run_adapter(self, action, succeeds=True):
        result = subprocess.run(["sh", str(self.script), action], env=self.env,
                                capture_output=True, text=True, timeout=20)
        if succeeds:
            self.assertEqual(result.returncode, 0, result.stderr)
        else:
            self.assertNotEqual(result.returncode, 0, result.stdout)
        return result

    def test_pure_migration_check_is_read_only_and_rejects_each_legacy_resource(self):
        self.runtime.write_text('corrupt unused external config')
        self.run_adapter('legacy-clear')
        for fault in ('internal', 'legacy_rule', 'legacy_route', 'query_failed'):
            self.state.write_text(json.dumps({fault: True}))
            before = self.read_state()
            self.run_adapter('legacy-clear', False)
            self.assertEqual(self.read_state(), before)
        self.state.write_text('{}')
        (self.private / 'forwarding.owner').write_text('legacy')
        self.run_adapter('legacy-clear', False)
        self.assertEqual((self.private / 'forwarding.owner').read_text(), 'legacy')

    def test_prepare_validates_without_activating_and_checks_topology(self):
        self.run_adapter("prepare")
        self.assertFalse(self.read_state().get("table"))
        self.assertFalse((self.private / "external-forwarding.owner").exists())
        for failure in ({"offlink": True}, {"missing_lan": True},
                        {"router_address": "192.0.2.9"}, {"offload": True}, {"internal": True}):
            with self.subTest(failure=failure):
                self.state.write_text(json.dumps(failure))
                self.run_adapter("prepare", False)
                self.assertFalse(self.read_state().get("table"))

    def test_private_metadata_needs_no_stat_and_rejects_public_files_and_links(self):
        self.run_adapter("prepare")
        self.runtime.chmod(0o644)
        self.run_adapter("prepare", False)
        self.runtime.chmod(0o600)
        saved = self.private / "original.json"
        self.runtime.rename(saved)
        self.runtime.symlink_to(saved)
        self.run_adapter("prepare", False)
        self.runtime.unlink()
        saved.rename(self.runtime)
        self.private.chmod(0o755)
        self.run_adapter("status", False)

    def test_active_scope_dns_loop_and_wan_leak_prevention(self):
        self.run_adapter("activate")
        status = json.loads(self.run_adapter("status").stdout)
        self.assertTrue(status["running"])
        self.assertTrue(status["residual"])
        nft = self.read_state()["nft_text"]
        self.assertIn('iifname "br-lan" ether saddr 02:00:00:00:00:03 ip saddr 192.0.2.3 meta l4proto { tcp, udp } th dport 53 dnat ip to 192.0.2.1:1053', nft)
        self.assertLess(nft.index('ether saddr 02:00:00:00:00:02 ip saddr 192.0.2.3 drop'), nft.index('ether saddr != 02:00:00:00:00:03 return'))
        self.assertIn('meta mark & 0xff000000 == 0x42000000 oifname "br-lan" return', nft)
        self.assertIn('ip daddr 192.0.2.3 icmp type redirect drop', nft)
        self.assertEqual(nft.count('ip daddr 192.0.2.0/24 fib daddr oifname "br-lan" return'), 2)
        self.assertNotIn('fib daddr . mark', nft)
        self.assertNotIn('fib daddr . saddr', nft)
        self.assertIn('meta nfproto ipv6 reject with icmpv6 type admin-prohibited', nft)
        self.assertIn('meta l4proto { tcp, udp } th dport 53 reject', nft)
        self.assertNotIn('masquerade', nft)
        self.assertNotIn('snat', nft)
        self.assertNotIn('flush', nft)
        self.assertNotIn('hook output priority -151', nft)
        # The source MAC return precedes IPv6 restrictions; other terminals and
        # gateway-originated connections retain the base path.
        forward = nft.split('chain selected_forward {', 1)[1]
        self.assertLess(forward.index('ether saddr != 02:00:00:00:00:03 return'), forward.index('meta nfproto ipv6'))

    def test_entire_lan_uses_dynamic_source_prefix_and_preserves_gateway_paths(self):
        lan = copy.deepcopy(CONFIG)
        lan.update(clientMode="lan", clientCIDR="192.0.2.0/24", clients=[])
        self.write_config(lan)
        self.run_adapter("activate")
        self.assertTrue(json.loads(self.run_adapter("status").stdout)["running"])
        nft = self.read_state()["nft_text"]
        # Prefix membership covers both existing clients and later DHCP leases;
        # no per-device address or MAC is emitted into the LAN source selector.
        self.assertIn('ip saddr 192.0.2.0/24 meta l4proto { tcp, udp } th dport 53 dnat ip to 192.0.2.1:1053', nft)
        self.assertNotIn(CONFIG["clients"][0]["mac"], nft)
        self.assertIn('ip saddr { 192.0.2.0, 192.0.2.255 } drop', nft)
        forward = nft.split('chain selected_forward {', 1)[1]
        self.assertLess(forward.index('iifname != "br-lan" return'), forward.index('ip saddr 192.0.2.0/24'))
        self.assertLess(forward.index('ether saddr 02:00:00:00:00:02 return'), forward.index('meta nfproto ipv6 reject'))
        self.assertIn('ether saddr 02:00:00:00:00:02 ip saddr 192.0.2.0/24 ip saddr != 192.0.2.2 drop', nft)
        self.assertIn('ip saddr { 192.0.2.1, 192.0.2.2 } return', nft)
        self.assertIn('meta nfproto ipv4 ip saddr != 192.0.2.0/24 return', nft)
        self.assertIn('meta nfproto ipv6 meta l4proto { tcp, udp } th dport { 53, 1053 } reject', nft)
        self.assertNotIn('masquerade', nft)
        self.assertNotIn('snat', nft)
        self.run_adapter("guard")
        guarded = self.read_state()["nft_text"]
        self.assertNotIn('chain selected_dns', guarded)
        self.assertIn('meta l4proto { tcp, udp } th dport 53 drop', guarded)
        self.assertTrue(json.loads(self.run_adapter("status").stdout)["guarded"])
        self.runtime.write_text('corrupt unused configuration')
        self.run_adapter("stop")
        self.assertFalse(self.read_state()["table"])
        self.assertFalse(self.read_state().get("rule") or self.read_state().get("route"))

    def test_lan_scope_must_match_real_interface_and_requires_explicit_migration(self):
        lan = copy.deepcopy(CONFIG)
        lan.update(clientMode="lan", clientCIDR="192.0.2.0/24", clients=[])
        self.write_config(lan)
        self.update(router_prefix=25)
        self.run_adapter("prepare", False)
        self.assertFalse(self.read_state().get("table"))
        self.update(router_prefix=24)
        self.run_adapter("activate")
        before = self.read_state()["nft_text"]
        self.write_config(CONFIG)
        self.run_adapter("prepare", False)
        self.run_adapter("guard", False)
        self.assertEqual(self.read_state()["nft_text"], before)
        self.run_adapter("stop")

    def test_guard_survives_address_loss_and_stop_ignores_runtime(self):
        self.run_adapter("activate")
        self.update(router_prefix=25)
        self.run_adapter("status", False)
        self.update(router_address="192.0.2.9", offlink=True)
        self.run_adapter("status", False)
        self.run_adapter("guard")
        state = self.read_state()
        self.assertFalse(state.get("rule") or state.get("route"))
        self.assertTrue(json.loads(self.run_adapter("status").stdout)["guarded"])
        nft = state["nft_text"]
        self.assertNotIn('chain selected_dns', nft)
        self.assertIn('ip daddr 192.0.2.0/24 fib daddr oifname "br-lan" return', nft)
        prerouting = nft.split('chain selected_prerouting {', 1)[1].split('chain selected_input {', 1)[0]
        self.assertIn('meta l4proto { tcp, udp } th dport 53 drop', prerouting)
        self.assertTrue(prerouting.rstrip().endswith('drop\n    }'))
        self.assertIn('ether saddr 02:00:00:00:00:03 meta l4proto { tcp, udp } th dport { 53, 1053 } reject', nft)
        self.runtime.write_text("corrupt JSON")
        self.run_adapter("stop")
        self.run_adapter("stop")
        self.assertFalse(self.read_state().get("table"))
        self.assertFalse((self.private / "external-forwarding.owner").exists())
        self.assertFalse(json.loads(self.run_adapter("status").stdout)["residual"])

    def test_route_trailing_whitespace_preserves_status_and_exact_cleanup(self):
        for suffix in (" ", "   \t "):
            with self.subTest(suffix=suffix):
                self.update(route_suffix=suffix)
                self.run_adapter("activate")
                self.assertTrue(json.loads(self.run_adapter("status").stdout)["running"])
                self.run_adapter("stop")
                self.assertFalse(self.read_state().get("route"))
                self.assertFalse(json.loads(self.run_adapter("status").stdout)["residual"])

    def test_trailing_whitespace_does_not_allow_foreign_or_extra_route_semantics(self):
        for change in ({"foreign_route": True, "route_suffix": "  "},
                       {"extra_route": True}, {"route_suffix": " metric 20 "}):
            with self.subTest(change=change):
                self.state.write_text("{}")
                self.run_adapter("activate")
                self.update(**change)
                self.run_adapter("status", False)
                self.run_adapter("stop", False)
                self.assertTrue(self.read_state()["table"])
                self.assertTrue(self.read_state()["route"])
                self.assertTrue((self.private / "external-forwarding.owner").exists())
                self.update(foreign_route=False, extra_route=False, route_suffix="")
                self.run_adapter("stop")

    def test_activation_failure_retains_guard_and_cleanup_is_retryable(self):
        for fault in ("fail_route_add", "fail_rule_add", "fail_active"):
            with self.subTest(fault=fault):
                self.update(**{fault: True})
                self.run_adapter("activate", False)
                self.assertTrue(self.read_state()["table"])
                self.assertNotIn('chain selected_dns', self.read_state()["nft_text"])
                self.assertTrue(json.loads(self.run_adapter("status").stdout)["guarded"])
                self.update(**{fault: False})
                self.run_adapter("stop")
        self.run_adapter("activate")
        self.update(fail_delete=True)
        self.run_adapter("stop", False)
        self.assertTrue((self.private / "external-forwarding.owner").exists())
        self.assertTrue(self.read_state()["table"])
        self.assertFalse(self.read_state().get("rule") or self.read_state().get("route"))
        self.update(fail_delete=False)
        self.run_adapter("stop")

    def test_foreign_resources_and_changed_snapshot_are_never_removed(self):
        for fault in ("foreign_rule", "foreign_route", "table"):
            with self.subTest(unowned=fault):
                self.state.write_text(json.dumps({fault: True}))
                self.run_adapter("prepare", False)
                self.run_adapter("stop", False)
                self.assertTrue(self.read_state()[fault])
        self.state.write_text("{}")
        self.run_adapter("activate")
        original = self.read_state()["nft_text"]
        self.update(nft_text=original+"# externally changed\n")
        self.run_adapter("stop", False)
        self.assertTrue(self.read_state()["table"])
        self.update(nft_text=original, foreign_rule=True)
        self.run_adapter("stop", False)
        self.assertTrue(self.read_state()["table"])
        self.update(foreign_rule=False)
        self.run_adapter("stop")

    def test_scope_change_requires_explicit_disable(self):
        self.run_adapter("guard")
        before = self.read_state()["nft_text"]
        candidate = copy.deepcopy(CONFIG)
        candidate["clients"][0]["address"] = "192.0.2.4"
        self.write_config(candidate)
        self.run_adapter("prepare", False)
        self.run_adapter("activate", False)
        self.assertEqual(self.read_state()["nft_text"], before)
        candidate = copy.deepcopy(CONFIG)
        candidate["dns"]["listenPort"] = 1054
        self.write_config(candidate)
        self.run_adapter("prepare", False)
        self.assertEqual(self.read_state()["nft_text"], before)
        self.run_adapter("stop")

    def test_failed_kernel_query_cannot_report_successful_stop(self):
        self.run_adapter("activate")
        self.update(query_failed=True)
        self.run_adapter("status", False)
        self.run_adapter("stop", False)
        self.assertTrue(self.read_state()["table"])
        self.assertTrue((self.private / "external-forwarding.owner").exists())
        self.update(query_failed=False)
        self.run_adapter("stop")

    def test_strict_input_and_private_paths_rejected_before_network_mutation(self):
        invalid = []
        for field, value in (("schema", 2), ("revision", True), ("enabled", False),
                             ("family", "ipv6"), ("faultPolicy", "direct"), ("extra", "unknown")):
            c = copy.deepcopy(CONFIG)
            c[field] = value
            invalid.append(c)
        for field, value in (("interface", 'br-lan"; flush ruleset'),
                             ("routerAddress", "192.0.2.001"), ("gatewayAddress", "127.0.0.1"),
                             ("gatewayMac", "ff:ff:ff:ff:ff:ff")):
            c = copy.deepcopy(CONFIG)
            c["link"][field] = value
            invalid.append(c)
        for clients in ([], CONFIG["clients"]*2):
            c = copy.deepcopy(CONFIG)
            c["clients"] = clients
            invalid.append(c)
        for field, value in (("listenPort", 53), ("listenPort", "1053"),
                             ("gatewayPort", 65536), ("localDomains", ['lan\nflush ruleset']),
                             ("localDomains", []), ("localDomains", ["lan", "lan"]),
                             ("localDomains", ["a"*64+".lan"])):
            c = copy.deepcopy(CONFIG)
            c["dns"][field] = value
            invalid.append(c)
        for bypass in (["0.0.0.0/0; flush ruleset"], ["0.0.0.0/0"],
                       ["192.0.2.1/24"], ["192.0.2.0/24", "192.0.2.0/24"]):
            c = copy.deepcopy(CONFIG)
            c["bypass4"] = bypass
            invalid.append(c)
        for candidate in invalid:
            with self.subTest(config=candidate):
                self.write_config(candidate)
                self.run_adapter("prepare", False)
                self.assertFalse(self.read_state().get("table"))
        self.write_config(CONFIG)
        self.runtime.chmod(0o644)
        self.run_adapter("prepare", False)
        self.runtime.chmod(0o600)
        outside = self.root / "elsewhere"
        self.runtime.rename(outside)
        self.runtime.symlink_to(outside)
        self.run_adapter("prepare", False)


if __name__ == "__main__":
    unittest.main()
