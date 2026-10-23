"""Focused regression checks for developer workflow boundaries."""
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
from alwayroute_context import ContextError, load_environment, router_argv

def module(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / filename)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result

import device
measure = module('measure_https', 'measure-https.py')

class WorkflowTests(unittest.TestCase):
    def test_stage_plan_is_offline_and_upload_does_not_flash(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "input.bin"
            path.write_bytes(b"fixture")
            with patch.object(device, "run_router") as router:
                planned = device.stage({}, path, False)
                router.assert_not_called()
                router.side_effect = [b"", (planned["sha256"] + " temporary").encode()]
                applied = device.stage({}, path, True)
                self.assertTrue(applied["hash_verified"])
                self.assertFalse(applied["flash_dispatched"])
                self.assertIn("set -C", router.call_args_list[0].args[1][-1])
                self.assertNotIn("sysupgrade", str(router.call_args_list))

    def test_status_filters_private_fields_and_https_does_not_modify_routes(self):
        replies = [b'{"board_name":"xiaomi,mi-router-4a-gigabit","private":"must-not-print"}',
                   b'{"service":{"running":true},"nodes":["secret"],"state":{"appliedRevision":23}}']
        with patch.object(device, "run_router", side_effect=replies):
            result = device.status({})
            self.assertNotIn("secret", json.dumps(result))
            self.assertNotIn("must-not-print", json.dumps(result))
        argv = measure.command({"traffic": {"executor": "ssh", "ssh_alias": "runner", "source_address": "192.0.2.2"}}, "https://example.com/", 5)
        self.assertIn("runner", argv)
        self.assertNotIn(" route ", argv[-1])
        self.assertIn("curl --disable", argv[-1])
        self.assertIn("--noproxy", argv[-1])
        with self.assertRaises(ContextError):
            measure.command({"traffic": {"executor": "local"}}, "https://example.com/?token=private", 5)
        with patch.object(measure.sys, "platform", "win32"):
            local = measure.command({"traffic": {"source_address": "192.0.2.2"}}, "https://example.com/", 5)
            self.assertEqual(local[local.index("--output") + 1], "NUL")
            with self.assertRaises(ContextError):
                measure.command({"traffic": {"source_interface": "Ethernet"}}, "https://example.com/", 5)
        with patch.object(measure.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, b"curl 8.3.0")):
            with self.assertRaises(ContextError):
                measure.require_bounded_curl({"traffic": {"executor": "local"}})

if __name__ == '__main__':
    unittest.main()
