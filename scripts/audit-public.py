#!/usr/bin/env python3
"""Offline, read-only privacy candidate audit. Match values never leave memory."""

import argparse
import collections
import json
from pathlib import Path
import re
import subprocess
import sys
import urllib.parse


PRIVATE_KEY = re.compile(r"-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY-----")
SERVICE_TOKEN = re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{30,}|sk-[A-Za-z0-9_-]{24,})\b")
URL = re.compile(r"https?://[^\s<>\"'`\)\]]+", re.I)
PROXY_URI = re.compile(r"\b(?:vmess|vless|trojan|ss|ssr|hysteria2?|tuic)://[^\s\"'`]+", re.I)
ASSIGNMENT = re.compile(
    r"(?:^|[\s,{;])['\"]?(password|passwd|secret|token|api[_-]?key|private[_-]?key|"
    r"client[_-]?secret|access[_-]?token|refresh[_-]?token|uuid)['\"]?\s*[:=]\s*"
    r"(?:\"([^\"\r\n]*)\"|'([^'\r\n]*)'|([^\s,;}\]]+))", re.I
)
EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
USER_PATH = re.compile(r"(?:[A-Za-z]:[\\/]Users[\\/][^\s/\\]+|/home/[^\s/\\]+)")
BOOT_ID = re.compile(r"(?:boot[_ -]?id|overlay).{0,80}\b[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\b", re.I)
SECRET_QUERY_KEYS = {"token", "key", "api_key", "apikey", "auth", "password", "secret", "access_token", "sub"}
PLACEHOLDERS = {"", "null", "none", "false", "true", "password", "changeme", "change-me", "redacted", "example", "test", "dummy", "***", "..."}


def placeholder(value):
    value = value.strip().lower()
    if value in PLACEHOLDERS or value.startswith(("your-", "your_", "example-", "example_", "placeholder", "${", "<")):
        return True
    # Existing fixture UUIDs reserve the all-zero prefix; do not exempt fixtures by path.
    if re.fullmatch(r"00000000-0000-(?:0000|4000)-(?:0000|8000)-[0-9a-f]{12}", value):
        return True
    return False


def git(root, *args):
    process = subprocess.run(["git", "-C", str(root), *args], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if process.returncode:
        raise RuntimeError("Git read operation failed; details suppressed to protect private values")
    return process.stdout


def scan_text(text, location):
    findings = []
    seen = set()

    def add(line, category, severity):
        key = (line, category, severity)
        if key not in seen:
            seen.add(key)
            findings.append(dict(location, line=line, category=category, severity=severity))

    for number, line in enumerate(text.splitlines(), 1):
        if PRIVATE_KEY.search(line):
            add(number, "private_key_material", "candidate")
        if SERVICE_TOKEN.search(line):
            add(number, "service_token_pattern", "candidate")
        for match in URL.finditer(line):
            try:
                url = urllib.parse.urlsplit(match.group(0))
                if url.password and not placeholder(urllib.parse.unquote(url.password)):
                    add(number, "url_embedded_password", "candidate")
                for key, value in urllib.parse.parse_qsl(url.query, keep_blank_values=True):
                    if key.lower() in SECRET_QUERY_KEYS and not placeholder(value):
                        add(number, "url_credential_parameter", "candidate" if len(value) >= 8 else "warning")
                if re.search(r"/(?:sub|subscribe|subscription|link)/[A-Za-z0-9_-]{12,}(?:/|$)", url.path, re.I):
                    add(number, "subscription_url_path", "candidate")
            except ValueError:
                add(number, "unparsed_url", "warning")
        for match in PROXY_URI.finditer(line):
            # A complete URI may encode credentials; ordinary parser references are too short.
            if len(match.group(0).split("://", 1)[1]) >= 12:
                add(number, "proxy_uri_requires_review", "warning")
        for match in ASSIGNMENT.finditer(line):
            field, double, single, bare = match.groups()
            value = double if double is not None else single if single is not None else bare
            if placeholder(value):
                continue
            quoted = double is not None or single is not None
            # Bare expressions and field accesses are code, not proof of a literal secret.
            if not quoted and (not re.fullmatch(r"[A-Za-z0-9_+/.=@:-]+", value) or len(value) < 12):
                continue
            if quoted or (re.search(r"[A-Za-z]", value) and re.search(r"[0-9]", value)):
                severity = "warning" if field.lower() == "uuid" and not re.fullmatch(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}", value) else "candidate"
                add(number, "credential_literal_requires_review", severity)
        if USER_PATH.search(line):
            add(number, "machine_user_path", "warning")
        if BOOT_ID.search(line):
            add(number, "device_runtime_identifier", "warning")
        if EMAIL.search(line):
            add(number, "email_in_content_review_attribution", "warning")
    return findings


class ObjectReader:
    def __init__(self, root):
        self.process = subprocess.Popen(["git", "-C", str(root), "cat-file", "--batch"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)

    def read(self, oid, max_bytes):
        self.process.stdin.write(oid.encode("ascii") + b"\n")
        self.process.stdin.flush()
        header = self.process.stdout.readline().split()
        if len(header) != 3:
            raise RuntimeError("Git object could not be read; details suppressed")
        kind, size = header[1].decode("ascii"), int(header[2])
        # Drain large objects in chunks; do not retain binaries or large blobs in memory.
        chunks, left = [], size
        while left:
            part = self.process.stdout.read(min(left, 65536))
            if not part:
                raise RuntimeError("Incomplete Git object read")
            if size <= max_bytes:
                chunks.append(part)
            left -= len(part)
        self.process.stdout.read(1)
        return kind, size, b"".join(chunks)

    def close(self):
        self.process.stdin.close()
        self.process.stdout.close()
        self.process.wait()


def audit(root, history=False, include_unreachable=False, max_bytes=2_000_000):
    report = {"format_version": 1, "mode": {"history": history or include_unreachable, "include_unreachable": include_unreachable},
              "counts": collections.Counter(), "identity": {"author_groups": 0, "committer_groups": 0, "author_groups_with_email": 0, "committer_groups_with_email": 0},
              "findings": [], "limits": ["heuristic_candidates_are_not_confirmed_leaks", "ignored_and_untracked_files_not_scanned", "large_and_binary_content_skipped", "no_network_or_credential_validation", "external_clones_backups_and_device_files_not_scanned"]}
    tracked = git(root, "ls-files", "-z").decode("utf-8", errors="replace").split("\0")
    for relative in filter(None, tracked):
        report["counts"]["tracked_paths"] += 1
        path = root / relative
        if path.is_symlink():
            report["counts"]["current_symlinks_skipped"] += 1
            continue
        try:
            if path.stat().st_size > max_bytes:
                report["counts"]["current_large_skipped"] += 1
                continue
            data = path.read_bytes()
        except OSError:
            report["counts"]["current_unreadable_or_missing"] += 1
            continue
        if b"\0" in data:
            report["counts"]["current_binary_skipped"] += 1
            continue
        report["counts"]["current_text_files_scanned"] += 1
        report["findings"].extend(scan_text(data.decode("utf-8", errors="replace"), {"scope": "current", "path": relative}))

    if history or include_unreachable:
        objects = {}
        for row in git(root, "rev-list", "--objects", "--all").decode("utf-8", errors="replace").splitlines():
            oid, _, path = row.partition(" ")
            objects[oid] = path
        report["counts"]["reachable_objects"] = len(objects)
        report["counts"]["refs"] = len(git(root, "for-each-ref", "--format=%(objectname)").splitlines())
        reachable = set(objects)
        if include_unreachable:
            for row in git(root, "cat-file", "--batch-all-objects", "--batch-check=%(objectname)").decode("ascii").splitlines():
                objects.setdefault(row, "")
            report["counts"]["additional_objects"] = len(objects) - len(reachable)
        authors, committers = set(), set()
        checked = subprocess.run(["git", "-C", str(root), "cat-file", "--batch-check"],
                                 input=("\n".join(objects) + "\n").encode("ascii"),
                                 stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        if checked.returncode:
            raise RuntimeError("Git object metadata could not be read")
        reader = ObjectReader(root)
        try:
            for row in checked.stdout.splitlines():
                fields = row.split()
                if len(fields) != 3:
                    raise RuntimeError("Incomplete Git object metadata")
                oid, kind, size = fields[0].decode("ascii"), fields[1].decode("ascii"), int(fields[2])
                if kind not in ("blob", "commit"):
                    continue
                path = objects[oid]
                scope = "history" if oid in reachable else "additional_object"
                location = {"scope": scope, "object": oid[:12]}
                if path:
                    location["path"] = path
                if size > max_bytes:
                    report["counts"]["history_large_skipped"] += 1
                    continue
                _, _, data = reader.read(oid, max_bytes)
                if kind == "blob":
                    if b"\0" in data:
                        report["counts"]["history_binary_skipped"] += 1
                        continue
                    report["counts"]["history_text_blobs_scanned"] += 1
                    report["findings"].extend(scan_text(data.decode("utf-8", errors="replace"), location))
                else:
                    header, _, message = data.partition(b"\n\n")
                    for line in header.splitlines():
                        for prefix, target in ((b"author ", authors), (b"committer ", committers)):
                            if line.startswith(prefix):
                                identity = line[len(prefix):].rsplit(b" ", 2)[0]
                                target.add(identity)
                    report["counts"]["commit_messages_scanned"] += 1
                    report["findings"].extend(scan_text(message.decode("utf-8", errors="replace"), dict(location, scope=scope + "_commit_message")))
        finally:
            reader.close()
        report["identity"] = {"author_groups": len(authors), "committer_groups": len(committers),
                              "author_groups_with_email": sum(bool(EMAIL.search(x.decode("utf-8", errors="replace"))) for x in authors),
                              "committer_groups_with_email": sum(bool(EMAIL.search(x.decode("utf-8", errors="replace"))) for x in committers)}
    report["counts"]["candidate_findings"] = sum(x["severity"] == "candidate" for x in report["findings"])
    report["counts"]["warning_findings"] = sum(x["severity"] == "warning" for x in report["findings"])
    report["counts"] = dict(report["counts"])
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--history", action="store_true", help="scan all refs' reachable blobs, commit messages and identity counts")
    parser.add_argument("--include-unreachable", action="store_true", help="also inspect objects available to this repository, including unreachable objects; implies --history")
    parser.add_argument("--output", type=Path, help="write a redacted JSON report (an existing file is never overwritten)")
    parser.add_argument("--max-bytes", type=int, default=2_000_000, help="maximum text file/object size, default 2000000")
    args = parser.parse_args()
    if args.max_bytes < 1:
        parser.error("--max-bytes must be positive")
    try:
        root = Path(git(Path.cwd(), "rev-parse", "--show-toplevel").decode("utf-8").strip())
        if args.output and (args.output.exists() or args.output.is_symlink()):
            raise RuntimeError("Output already exists; refusing to overwrite")
        report = audit(root, args.history, args.include_unreachable, args.max_bytes)
        if args.output:
            with args.output.open("x", encoding="utf-8") as output:
                json.dump(report, output, ensure_ascii=True, indent=2)
                output.write("\n")
        print(json.dumps({"counts": report["counts"], "identity": report["identity"]}, ensure_ascii=True))
        for item in sorted(report["findings"], key=lambda item: item["severity"] != "candidate")[:12]:
            print(json.dumps(item, ensure_ascii=True))
        if len(report["findings"]) > 12:
            print("More finding locations omitted; use --output for the full redacted report.")
        print("Candidates require review. This heuristic audit does not prove the absence of secrets.")
        return 1 if report["counts"]["candidate_findings"] else 0
    except (OSError, RuntimeError, ValueError):
        print("Audit failed; raw error details suppressed to protect private values.", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
