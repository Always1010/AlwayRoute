#!/usr/bin/env python3
"""Protect redaction and historical coverage with isolated disposable repositories."""

import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "audit-public.py"
SPEC = importlib.util.spec_from_file_location("public_audit", SCRIPT)
AUDIT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(AUDIT)


def credential(value, field=None):
    return json.dumps({field or ("pass" + "word"): value})


class PublicAuditTest(unittest.TestCase):
    def test_candidate_values_and_identity_are_never_reported(self):
        fixture_value = "synthetic" + "9SecretForAuditOnly"
        email = "fixture-person" + "@example.invalid"
        content = credential(fixture_value) + '\nhttps://host.invalid/?token=' + fixture_value + '\n' + email
        report = AUDIT.scan_text(content, {"scope": "current", "path": "input.txt"})
        serialized = json.dumps(report)
        self.assertNotIn(fixture_value, serialized)
        self.assertNotIn(email, serialized)
        self.assertNotIn("https://", serialized)
        self.assertTrue(any(item["severity"] == "candidate" for item in report))
        self.assertTrue(any(item["category"] == "email_in_content_review_attribution" for item in report))

    def test_explicit_placeholder_does_not_exempt_fixture_paths(self):
        placeholder = credential("00000000-0000-0000-0000-000000000001", "u" + "uid") + credential("<password>")
        self.assertEqual(AUDIT.scan_text(placeholder, {"path": "fixtures/sample"}), [])
        real_candidate = credential("synthetic" + "9SecretForAuditOnly")
        self.assertEqual(AUDIT.scan_text(real_candidate, {"path": "fixtures/sample"})[0]["severity"], "candidate")

    def test_deleted_history_auxiliary_ref_and_unreachable_objects(self):
        with tempfile.TemporaryDirectory(prefix="public-audit-") as directory:
            root = Path(directory)

            def git(*args):
                return subprocess.check_output(["git", "-C", str(root), *args], stderr=subprocess.DEVNULL)

            git("init", "-q")
            git("config", "user.name", "Audit Fixture")
            git("config", "user.email", "fixture-person@example.invalid")
            fixture_value = "synthetic" + "9SecretForAuditOnly"
            (root / "old.txt").write_text(credential(fixture_value), encoding="utf-8")
            git("add", "old.txt")
            git("commit", "-qm", "initial")
            old_commit = git("rev-parse", "HEAD").strip().decode()
            (root / "old.txt").write_text("safe public text\n", encoding="utf-8")
            git("commit", "-qam", "remove private candidate")
            tree = git("rev-parse", "HEAD^{tree}").strip().decode()
            auxiliary = subprocess.run(["git", "-C", str(root), "commit-tree", tree, "-p", old_commit], input=credential(fixture_value, "to" + "ken").encode(), stdout=subprocess.PIPE, check=True).stdout.strip().decode()
            git("update-ref", "refs/codex/audit-fixture", auxiliary)
            process = subprocess.run(["git", "-C", str(root), "hash-object", "-w", "--stdin"], input=credential(fixture_value, "to" + "ken").encode(), stdout=subprocess.PIPE, check=True)
            unreachable = process.stdout.strip().decode()[:12]
            report = AUDIT.audit(root, history=True)
            self.assertEqual(report["identity"]["author_groups"], 1)
            self.assertEqual(report["identity"]["author_groups_with_email"], 1)
            self.assertTrue(any(item["scope"] == "history" and item.get("path") == "old.txt" for item in report["findings"]))
            self.assertTrue(any(item["scope"] == "history_commit_message" and item.get("object") == auxiliary[:12] for item in report["findings"]))
            self.assertFalse(any(item.get("object") == unreachable for item in report["findings"]))
            expanded = AUDIT.audit(root, include_unreachable=True)
            self.assertTrue(any(item.get("object") == unreachable and item["scope"] == "additional_object" for item in expanded["findings"]))
            self.assertNotIn(fixture_value, json.dumps(expanded))
            self.assertNotIn("fixture-person@", json.dumps(expanded))
            run = subprocess.run([sys.executable, str(SCRIPT), "--history"], cwd=root, capture_output=True, text=True)
            self.assertEqual(run.returncode, 1)
            self.assertNotIn(fixture_value, run.stdout + run.stderr)
            self.assertNotIn("fixture-person@", run.stdout + run.stderr)


if __name__ == "__main__":
    unittest.main()
