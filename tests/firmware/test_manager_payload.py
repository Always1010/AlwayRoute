"""Protect literals and executable headers during owned install compaction."""
import importlib.util
import json
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('manager_compactor', ROOT /
    'firmware/openwrt/alwayroute-manager/tools/compact-payload.py')
compact = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(compact)


class PayloadTest(unittest.TestCase):
    def test_shell_literals_and_interpreter_are_preserved(self):
        source = b'#!/bin/sh\n# removable\nprintf "%s" "first\n# literal\nlast"\n'
        with self.assertRaisesRegex(ValueError, 'quoted content'):
            compact.compact_payload('etc/init.d/alwayroute', source, 'unused')
        source = b'#!/bin/sh\n# removable\nprintf "%s" "# literal"\n'
        self.assertEqual(compact.compact_payload('etc/init.d/alwayroute', source, 'unused'),
                         b'#!/bin/sh\nprintf "%s" "# literal"\n')
        with self.assertRaisesRegex(ValueError, 'heredoc'):
            compact.compact_payload('etc/init.d/alwayroute', b'#!/bin/sh\ncat <<EOF\n', 'unused')

    def test_json_values_and_ucode_headers_survive(self):
        value = {'name': '合成 # //', 'url': 'https://example.invalid/a?x=A%2Fb', 'items': [1, False]}
        raw = json.dumps(value, ensure_ascii=False, indent=2).encode()
        self.assertEqual(json.loads(compact.compact_payload('policy.json', raw, 'unused')), value)
        with patch.object(compact.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, b'print(1);')) as run:
            result = compact.compact_payload('usr/libexec/alwayroute-boot', b'#!/usr/bin/ucode\nprint(1);\n', 'jsmin')
        self.assertEqual(result, b'#!/usr/bin/ucode\nprint(1);')
        self.assertEqual(run.call_args.kwargs['input'], b'print(1);\n')


if __name__ == '__main__':
    unittest.main()
