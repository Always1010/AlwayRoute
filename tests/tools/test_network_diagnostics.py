"""Read-only topology diagnosis must preserve route state and hide private values."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from alwayroute_context import ContextError
spec = importlib.util.spec_from_file_location("network_diagnostics", ROOT / "scripts/network-diagnostics.py")
network = importlib.util.module_from_spec(spec)
spec.loader.exec_module(network)


class NetworkDiagnosticsTests(unittest.TestCase):
    def test_source_binding_does_not_hide_wrong_interface_or_gateway(self):
        env = {"traffic": {"source_address": "192.0.2.2", "source_interface": "lan-test", "gateway": "192.0.2.1"}}
        raw = {"supported": True, "resolved_addresses_count": 1, "routes_unchanged": True,
               "routes": [{"query_succeeded": True, "destination": "198.51.100.1", "prefsrc": "192.0.2.2",
                           "dev": "uplink", "gateway": "198.51.100.254"}]}
        public = network.public_summary(raw, env)
        self.assertTrue(public["route_checks"][0]["source_matches"])
        self.assertFalse(public["route_checks"][0]["expected_path_matches"])
        self.assertNotIn("192.0.2", json.dumps(public))
        self.assertNotIn("198.51.100", json.dumps(public))

    def test_remote_probe_does_not_interpolate_environment_or_write_routes(self):
        env = {"traffic": {"executor": "ssh", "ssh_alias": "runner", "source_address": "192.0.2.2"}}
        reply = subprocess.CompletedProcess([], 0, b'{"supported":true,"routes":[]}')
        with patch.object(network.subprocess, "run", return_value=reply) as run:
            network.diagnose(env, "https://example.com/")
        command = run.call_args.args[0]
        self.assertIn("runner", command)
        self.assertNotIn("192.0.2.2", command[-1])
        for forbidden in ("sudo", "'add'", "'del'", "'replace'", "'flush'"):
            self.assertNotIn(forbidden, network.PROBE)
        with self.assertRaises(ContextError):
            network.request_for(env, "https://example.com/?token=private")


if __name__ == "__main__":
    unittest.main()
