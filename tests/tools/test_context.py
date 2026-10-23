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


class WorkflowTests(unittest.TestCase):
    def test_context_rejects_options_credentials_unknown_fields_and_relative_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "env.json"
            for bad in ({"router": {"target": "-oProxyCommand=bad"}},
                        {"build": {"task_root": "../cache"}}, {"password": "your-placeholder"},
                        {"build": {"jobs": True}}, {"build": {"executor": "ssh"}}):
                path.write_text(json.dumps({"schema_version": 1, **bad}))
                with self.assertRaises(ContextError):
                    load_environment(path)
            path.write_text(json.dumps({"schema_version": 1, "router": {"target": "lab-router"}}))
            self.assertEqual(load_environment(path)["router"]["target"], "lab-router")

    def test_router_executor_is_independent_from_builder_and_quotes_arguments(self):
        env = {"build": {"ssh_alias": "different-builder"},
               "router": {"executor": "ssh", "executor_ssh_alias": "operator",
                          "target": "router", "identity_file": "/private/key with spaces", "ssh_port": 122}}
        argv = router_argv(env, ["printf", "literal;no-command"])
        self.assertIn("operator", argv)
        self.assertNotIn("different-builder", " ".join(argv))
        self.assertIn("'literal;no-command'", argv[-1].replace("'\"'\"'", "'"))

if __name__ == '__main__':
    unittest.main()
