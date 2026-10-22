"""Exercise adapter ownership and failure cleanup with isolated command doubles.

This does not validate nft syntax or forwarding on the router's kernel.
"""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[2]
ADAPTER = REPO / "firmware/openwrt/alwayroute-forwarding/files/alwayroute-forwarding"
DOUBLE = r'''#!/usr/bin/env python3
import json, os, pathlib, sys
p = pathlib.Path(os.environ['AR_TEST_STATE'])
s = json.loads(p.read_text())
name, args = pathlib.Path(sys.argv[0]).name, sys.argv[1:]
with pathlib.Path(str(p)+'.log').open('a') as f: f.write(name+' '+repr(args)+'\n')
rc = 0
if name == 'jsonfilter': print(s.get('mode','Rule'))
elif name == 'ubus': print('{}')
elif name == 'nft':
 if args[:3] == ['list','table','inet']: rc = 0 if s.get('table') else 1
 elif args == ['list','ruleset']: print('flow add @ft' if s.get('offload') else '')
 elif args[:3] == ['delete','table','inet']:
  if s.get('fail_nft_delete'): rc = 1
  else: s['table'] = False
 elif '--check' in args:
  source = args[args.index('--file')+1]
  text = sys.stdin.read() if source == '-' else pathlib.Path(source).read_text()
  pathlib.Path(str(p)+'.nft').write_text(text)
 elif '--file' in args:
  if s.get('fail_nft'): rc = 1
  else: s['table'] = True
elif name == 'ip':
 if args == ['-4','rule','show']:
  if s.get('foreign_rule'): print('10231: from all fwmark 0x42000000/0xff000000 lookup 20232')
  elif s.get('rule'): print('10231: from all fwmark 0x41000000/0xff000000 lookup 20231')
 elif args[:4] == ['-4','route','show','table']:
  if s.get('route'): print('local default dev lo scope host')
 elif args[:3] == ['-4','route','replace']: s['route'] = True
 elif args[:3] == ['-4','route','del']: s['route'] = False
 elif args[:3] == ['-4','rule','add']:
  if s.get('foreign_rule'): rc = 2
  else: s['rule'] = True
 elif args[:3] == ['-4','rule','del']:
  if s.get('foreign_rule'): rc = 2
  else: s['rule'] = False
p.write_text(json.dumps(s))
sys.exit(rc)
'''


class ForwardingTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="alwayroute-forwarding-")
        self.root = Path(self.temp.name)
        self.state = self.root / "command-state.json"
        self.state.write_text(json.dumps({"mode": "Rule", "lan": "br-lan"}))
        self.private = self.root / "runtime"
        self.private.mkdir()
        (self.private / "runtime.json").write_text("{}")
        self.bin = self.root / "bin"
        self.bin.mkdir()
        for name in ("nft", "ip", "ubus", "jsonfilter"):
            p = self.bin / name
            # The first jsonfilter call reads the mode; the second reads LAN.
            content = DOUBLE.replace(
                "if name == 'jsonfilter': print(s.get('mode','Rule'))",
                "if name == 'jsonfilter': print(s.get('lan','br-lan') if '@.l3_device' in args else s.get('mode','Rule'))",
            )
            p.write_text(content)
            p.chmod(0o755)
        self.script = self.root / "adapter.sh"
        self.script.write_text(ADAPTER.read_text().replace("/tmp/alwayroute", str(self.private)))
        self.env = dict(os.environ, PATH=str(self.bin) + os.pathsep + os.environ["PATH"], AR_TEST_STATE=str(self.state))

    def tearDown(self):
        self.temp.cleanup()

    def run_adapter(self, action):
        return subprocess.run(["sh", str(self.script), action], env=self.env, capture_output=True, text=True, timeout=10)

    def update(self, **values):
        state = json.loads(self.state.read_text())
        state.update(values)
        self.state.write_text(json.dumps(state))

    def test_prepare_does_not_activate_and_dns_precedes_private_bypass(self):
        result = self.run_adapter("prepare")
        self.assertEqual(result.returncode, 0, result.stderr)
        state = json.loads(self.state.read_text())
        self.assertFalse(state.get("table", False))
        self.assertFalse((self.private / "forwarding.owner").exists())
        nft = Path(str(self.state) + ".nft").read_text()
        self.assertLess(nft.index("th dport 53"), nft.index("ip daddr @bypass4"))
        self.assertIn('iifname != "br-lan" return', nft)
        self.assertIn("meta nfproto ipv6 reject", nft)

    def test_activate_and_stop_remove_only_owned_state(self):
        result = self.run_adapter("activate")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(json.loads(self.run_adapter("status").stdout)["running"])
        self.assertEqual(self.run_adapter("stop").returncode, 0)
        state = json.loads(self.state.read_text())
        self.assertFalse(state["table"] or state["rule"] or state["route"])
        self.assertEqual(self.run_adapter("stop").returncode, 0)

    def test_guard_blocks_without_policy_route_and_can_reactivate(self):
        self.assertEqual(self.run_adapter("activate").returncode, 0)
        result = self.run_adapter("guard")
        self.assertEqual(result.returncode, 0, result.stderr)
        status = json.loads(self.run_adapter("status").stdout)
        self.assertTrue(status["guarded"])
        self.assertFalse(status["running"])
        state = json.loads(self.state.read_text())
        self.assertTrue(state["table"])
        self.assertFalse(state.get("rule") or state.get("route"))
        self.assertTrue((self.private / "forwarding.owner").exists())
        self.assertTrue((self.private / "forwarding.guard").exists())
        nft = Path(str(self.state) + ".nft").read_text()
        self.assertIn("chain guard_forward", nft)
        self.assertNotIn("tproxy", nft)
        self.assertLess(nft.index("th dport 53 reject"), nft.index("ip daddr @bypass4 return"))
        self.assertIn("meta nfproto ipv6 reject", nft)
        self.assertIn("meta l4proto { tcp, udp } reject", nft)
        self.assertEqual(self.run_adapter("activate").returncode, 0)
        status = json.loads(self.run_adapter("status").stdout)
        self.assertTrue(status["running"])
        self.assertFalse(status.get("guarded", False))
        self.assertFalse((self.private / "forwarding.guard").exists())
        state = json.loads(self.state.read_text())
        self.assertTrue(state["table"] and state["rule"] and state["route"])
        self.assertEqual(self.run_adapter("stop").returncode, 0)
        state = json.loads(self.state.read_text())
        self.assertFalse(state.get("table") or state.get("rule") or state.get("route"))
        self.assertFalse((self.private / "forwarding.owner").exists())
        self.assertFalse((self.private / "forwarding.guard").exists())

    def test_failed_reactivation_preserves_existing_guard(self):
        self.assertEqual(self.run_adapter("activate").returncode, 0)
        self.assertEqual(self.run_adapter("guard").returncode, 0)
        self.update(fail_nft=True)
        self.assertNotEqual(self.run_adapter("activate").returncode, 0)
        state = json.loads(self.state.read_text())
        self.assertTrue(state["table"], "failed replacement must retain the old guard table")
        self.assertFalse(state.get("rule") or state.get("route"))
        status = json.loads(self.run_adapter("status").stdout)
        self.assertTrue(status["guarded"])
        self.assertFalse(status["running"])
        self.assertTrue((self.private / "forwarding.owner").exists())
        self.assertTrue((self.private / "forwarding.guard").exists())
        commands = Path(str(self.state) + ".log").read_text().splitlines()
        self.assertFalse(any("['delete', 'table', 'inet'" in line for line in commands), "retry failure must never explicitly delete the guard")

    def test_existing_unowned_resources_are_preserved(self):
        self.update(table=True, rule=True, route=True)
        self.assertNotEqual(self.run_adapter("activate").returncode, 0)
        self.assertEqual(self.run_adapter("stop").returncode, 0)
        state = json.loads(self.state.read_text())
        self.assertTrue(state["table"] and state["rule"] and state["route"])

    def test_failure_cleans_partial_route_and_rule(self):
        self.update(fail_nft=True)
        self.assertNotEqual(self.run_adapter("activate").returncode, 0)
        state = json.loads(self.state.read_text())
        self.assertFalse(state.get("rule") or state.get("route"))
        self.assertFalse((self.private / "forwarding.owner").exists())

    def test_foreign_rule_replacement_is_preserved_and_never_reported_running(self):
        self.assertEqual(self.run_adapter("activate").returncode, 0)
        self.update(rule=False, foreign_rule=True)
        self.assertFalse(json.loads(self.run_adapter("status").stdout)["running"])
        self.assertNotEqual(self.run_adapter("activate").returncode, 0)
        self.assertTrue(json.loads(self.state.read_text())["foreign_rule"])
        result = self.run_adapter("stop")
        self.assertNotEqual(result.returncode, 0)
        state = json.loads(self.state.read_text())
        self.assertTrue(state["foreign_rule"], "stop must not delete a replacement rule owned by another component")
        self.assertFalse(state.get("table") or state.get("route"), "foreign-rule conflict must not prevent cleanup of our resources")
        self.assertTrue((self.private / "forwarding.owner").exists(), "failed cleanup must retain its recovery marker")

    def test_nft_delete_failure_still_cleans_routing_and_is_retryable(self):
        self.assertEqual(self.run_adapter("activate").returncode, 0)
        self.update(fail_nft_delete=True)
        result = self.run_adapter("stop")
        self.assertNotEqual(result.returncode, 0)
        state = json.loads(self.state.read_text())
        self.assertTrue(state["table"], "failed nft delete must remain visible")
        self.assertFalse(state.get("rule") or state.get("route"), "nft failure must not skip routing cleanup")
        self.assertTrue((self.private / "forwarding.owner").exists())
        self.update(fail_nft_delete=False)
        self.assertEqual(self.run_adapter("stop").returncode, 0)
        state = json.loads(self.state.read_text())
        self.assertFalse(state.get("table") or state.get("rule") or state.get("route"))
        self.assertFalse((self.private / "forwarding.owner").exists())

    def test_direct_mode_and_offload_boundary(self):
        self.update(offload=True)
        self.assertNotEqual(self.run_adapter("prepare").returncode, 0)
        self.update(mode="Direct")
        self.assertEqual(self.run_adapter("activate").returncode, 0)
        self.assertFalse(json.loads(self.state.read_text()).get("table", False))

    def test_invalid_interface_never_reaches_nft(self):
        self.update(lan='br-lan"; unexpected')
        self.assertNotEqual(self.run_adapter("prepare").returncode, 0)
        self.assertFalse(Path(str(self.state) + ".nft").exists())


if __name__ == "__main__":
    unittest.main()
