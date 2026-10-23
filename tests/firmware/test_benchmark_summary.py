#!/usr/bin/env python3
"""Offline summary tests focus on privacy and incomparable measurements."""

import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[2] / "firmware" / "tools" / "summarize-benchmarks.py"
SPEC = importlib.util.spec_from_file_location("benchmark_summary", SCRIPT)
SUMMARY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SUMMARY)


class BenchmarkSummaryTest(unittest.TestCase):
    def test_whitelist_omits_private_strings_and_keeps_identity_roles(self):
        private = "private-node-" + "do-not-emit"
        rows = [{"core": "baseline-ram", "case": "tcp-4", "parallel": 4, "seconds": 12.3,
                 "mbps": 91.2, "bytes": 1000, "gomaxprocs": 4, "clash_api": True,
                 "cpu_busy_percent": {"cpu": 80, "cpu0": 45, private: 99}, "server": private},
                {"core": private, "case": private, "parallel": 1, "seconds": 4.1,
                 "mbps": 12.2, "bytes": 500, "url": "https://" + private + "/?token=private", "selectors": {private: private}}]
        report = SUMMARY.summarize([{"results": rows, "scope": private, "link_mbps": 1000}], "mixed-proxy-lan")
        self.assertNotIn(private, json.dumps(report))
        self.assertNotIn("https://", json.dumps(report))
        self.assertEqual([row["role"] for row in report["rows"]], ["baseline", "candidate"])
        self.assertNotEqual(report["rows"][0]["candidate"], report["rows"][1]["candidate"])
        self.assertEqual(report["rows"][0]["metrics"]["cpu_busy_percent"], {"cpu": 80, "cpu0": 45})

    def test_preserves_duration_paths_concurrency_and_units_without_uplift(self):
        row = {"label": "candidate", "transport": "tcp", "parallel": 4, "seconds": 12.001, "mbps": 76.54, "bytes": 123456,
               "process_ticks_per_decimal_MB": 12.5, "rss_kib_min": 5000, "rss_kib_max": 7000}
        other = dict(row, parallel=1, seconds=60.005, mbps=88.3)
        report = SUMMARY.summarize([{"transparent_ram": [row], "transparent_flash": [other]}])
        self.assertEqual(report["row_count"], 2)
        self.assertEqual([x["conditions"]["test_path"] for x in report["rows"]], ["transparent-ram", "transparent-flash"])
        self.assertEqual([x["conditions"]["parallel"] for x in report["rows"]], [4, 1])
        self.assertEqual([x["metrics"]["seconds"] for x in report["rows"]], [12.001, 60.005])
        self.assertEqual(report["rows"][0]["metrics"]["mbps"], 76.54)
        self.assertEqual(report["units"]["mbps"], "Mbit/s (decimal)")
        self.assertEqual(report["units"]["process_ticks_per_decimal_MB"], "process clock tick / decimal MB")
        self.assertNotIn("uplift", json.dumps(report))
        with self.assertRaises(SUMMARY.SummaryError):
            SUMMARY.summarize([{"transparent_ram": [row]}], "transparent-flash")

    def test_cli_rejects_private_invalid_value_and_refuses_overwrite(self):
        with tempfile.TemporaryDirectory(prefix="benchmark-summary-") as directory:
            source = Path(directory) / "input.json"
            private = "private-invalid-" + "do-not-emit"
            source.write_text(json.dumps([{"seconds": private, "mbps": 1}]), encoding="utf-8")
            run = subprocess.run([sys.executable, "-B", str(SCRIPT), str(source)], capture_output=True, text=True)
            self.assertEqual(run.returncode, 2)
            self.assertNotIn(private, run.stdout + run.stderr)
            source.write_text(json.dumps([{"seconds": 1, "mbps": 1}]), encoding="utf-8")
            original = source.read_bytes()
            run = subprocess.run([sys.executable, "-B", str(SCRIPT), str(source), "--output", str(source)], capture_output=True, text=True)
            self.assertEqual(run.returncode, 2)
            self.assertEqual(source.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
