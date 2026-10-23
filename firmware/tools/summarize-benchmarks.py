#!/usr/bin/env python3
"""Summarize existing benchmark JSON offline using an output field whitelist.

Accepts a result-row list, a {"results": [...]} report, or the legacy public
transparent_ram/transparent_flash summary. No networking or devices are used;
sidecar proc/connection logs are not opened. Private text fields are omitted.

Example: python firmware/tools/summarize-benchmarks.py RESULTS.json --test-path mixed-proxy-lan
Candidate and case names become stable anonymous IDs in input order. Input and
row numbers locate originals privately. This tool never calculates an uplift,
combines samples or treats different durations/paths/concurrency as equivalent.
"""

import argparse
import json
import math
from pathlib import Path
import re
import sys


TEST_PATHS = ("unknown", "mixed-proxy-lan", "mixed-proxy-ssh", "explicit-connect-lan", "transparent-ram", "transparent-flash")
TRANSPORTS = {"tcp", "ws-tls", "direct", "udp", "quic"}
SECURITY = {"auto", "aes-128-gcm", "chacha20-poly1305", "none", "zero"}
UNITS = {
    "bytes": "byte", "seconds": "second", "mbps": "Mbit/s (decimal)",
    "cpu_ticks": "process clock tick", "process_cpu_ticks": "process clock tick",
    "rss_kib": "KiB", "rss_kib_min": "KiB", "rss_kib_max": "KiB",
    "available_kib": "KiB", "available_kib_min": "KiB", "available_kib_max": "KiB",
    "memory_available_kib": "KiB", "cpu_system_percent": "%", "cpu_softirq_percent": "%",
    "process_ticks_per_decimal_MB": "process clock tick / decimal MB",
    "softnet_drop_delta": "packet counter delta", "verified_tproxy_flows": "flow",
}
INTEGER_METRICS = {"bytes", "cpu_ticks", "process_cpu_ticks", "rss_kib", "rss_kib_min", "rss_kib_max",
                   "available_kib", "available_kib_min", "available_kib_max", "memory_available_kib",
                   "softnet_drop_delta", "verified_tproxy_flows"}


class SummaryError(ValueError):
    """Messages are fixed categories; never embed source values or paths."""


def numeric(value, integer=False, positive=False, allow_negative=False):
    if type(value) not in (int, float):
        raise SummaryError("invalid_numeric_field")
    if not math.isfinite(value) or (integer and int(value) != value):
        raise SummaryError("invalid_numeric_field")
    if (positive and value <= 0) or (not allow_negative and value < 0):
        raise SummaryError("invalid_numeric_range")
    return value


def sections(document):
    if isinstance(document, list):
        return [("row_list", "unknown", document)], {}
    if not isinstance(document, dict):
        raise SummaryError("unsupported_result_schema")
    if isinstance(document.get("results"), list):
        return [("results_wrapper", "unknown", document["results"])], document
    result = [(key, path, document[key]) for key, path in
              (("transparent_ram", "transparent-ram"), ("transparent_flash", "transparent-flash"))
              if isinstance(document.get(key), list)]
    if result:
        return result, document
    raise SummaryError("unsupported_result_schema")


def summarize(documents, test_path=None):
    if test_path is not None and test_path not in TEST_PATHS:
        raise SummaryError("unsupported_test_path")
    output = {"format_version": 1, "units": {**UNITS, "cpu_busy_percent": "%", "reported_link_mbps": "Mbit/s (decimal)"},
              "policy": {"candidate_and_case_names": "anonymous_ids_in_first_appearance_order",
                         "comparison": "none_rows_are_not_aggregated_or_ranked",
                         "duration_basis": "recorded_seconds_definition_not_verified",
                         "unrecognized_fields": "omitted_without_echoing_values"},
              "rows": [], "input_count": len(documents)}
    candidates, cases = {}, {}
    for input_number, document in enumerate(documents, 1):
        groups, metadata = sections(document)
        for section, section_path, rows in groups:
            if test_path is not None and section_path != "unknown" and test_path != section_path:
                raise SummaryError("test_path_conflicts_with_summary_section")
            for row_number, row in enumerate(rows, 1):
                if not isinstance(row, dict):
                    raise SummaryError("invalid_result_row")
                if not any(key in row for key in ("mbps", "bytes", "seconds")):
                    raise SummaryError("result_row_has_no_transfer_metrics")
                label = row.get("core", row.get("label"))
                label = label if isinstance(label, str) else None
                fingerprint = row.get("core_sha256", row.get("sha256", metadata.get("core_sha256")))
                fingerprint = fingerprint if isinstance(fingerprint, str) else None
                identity = (label, fingerprint) if label or fingerprint else (None, input_number)
                candidates.setdefault(identity, "candidate-" + str(len(candidates) + 1))
                case = row.get("case")
                case = case if isinstance(case, str) else None
                case_identity = case if case is not None else (input_number, section, row_number)
                cases.setdefault(case_identity, "case-" + str(len(cases) + 1))
                transport = row.get("transport")
                if not isinstance(transport, str) or transport not in TRANSPORTS:
                    transport = "ws-tls" if case and case.startswith("ws-tls") else "tcp" if case and case.startswith("tcp") else "direct" if case == "direct" else "unknown"
                security = metadata.get("security")
                conditions = {"test_path": test_path or section_path, "transport": transport,
                              "profiling": "enabled" if case and case.endswith("-profile") else "not_recorded",
                              "security": security if isinstance(security, str) and security in SECURITY else "not_recorded"}
                if case and "preemptoff" in case:
                    conditions["async_preemption"] = "disabled_in_case_name"
                for field in ("parallel", "gomaxprocs"):
                    if field in row:
                        conditions[field] = numeric(row[field], integer=True, positive=True)
                if "clash_api" in row:
                    if type(row["clash_api"]) is not bool:
                        raise SummaryError("invalid_boolean_field")
                    conditions["clash_api"] = row["clash_api"]
                if "link_mbps" in metadata:
                    conditions["reported_link_mbps"] = numeric(metadata["link_mbps"], positive=True)
                metrics = {}
                for field in UNITS:
                    if field in row:
                        metrics[field] = numeric(row[field], integer=field in INTEGER_METRICS,
                                                 positive=field == "seconds", allow_negative=field.endswith("_delta"))
                        if field.endswith("_percent") and metrics[field] > 100:
                            raise SummaryError("invalid_percent_range")
                if "cpu_busy_percent" in row:
                    busy = row["cpu_busy_percent"]
                    if isinstance(busy, dict):
                        metrics["cpu_busy_percent"] = {}
                        for key, value in busy.items():
                            if isinstance(key, str) and re.fullmatch(r"cpu(?:[0-9]{1,3})?", key):
                                measured = numeric(value)
                                if measured > 100:
                                    raise SummaryError("invalid_percent_range")
                                metrics["cpu_busy_percent"][key] = measured
                    else:
                        measured = numeric(busy)
                        if measured > 100:
                            raise SummaryError("invalid_percent_range")
                        metrics["cpu_busy_percent"] = measured
                output["rows"].append({"input": input_number, "section": section, "row": row_number,
                                       "candidate": candidates[identity], "role": "baseline" if label and re.match(r"baseline(?:[-_]|$)", label, re.I) else "candidate" if label else "unspecified",
                                       "case": cases[case_identity], "conditions": conditions, "metrics": metrics})
    output["candidate_count"] = len(candidates)
    output["row_count"] = len(output["rows"])
    output["notes"] = ["Recorded throughput is retained; it is not recomputed from rounded seconds.",
                       "Missing conditions stay unknown; scope text and case labels cannot prove equal test conditions.",
                       "CPU ticks are not seconds; the source clock rate is not assumed.",
                       "Source labels, paths, nodes, URLs, connection evidence and selector choices are omitted."]
    return output


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("inputs", type=Path, nargs="+", help="existing supported benchmark JSON files, in desired order")
    parser.add_argument("--test-path", choices=TEST_PATHS, help="explicit condition for these inputs; use separate runs for different paths")
    parser.add_argument("--output", type=Path, help="write JSON to a new file; never overwrite an input or existing file")
    args = parser.parse_args(argv)
    try:
        documents = []
        for number, path in enumerate(args.inputs, 1):
            try:
                documents.append(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, UnicodeError, ValueError):
                print("input " + str(number) + ": unreadable_or_invalid_json (source details withheld)", file=sys.stderr)
                return 2
        result = summarize(documents, args.test_path)
        rendered = json.dumps(result, ensure_ascii=True, allow_nan=False, indent=2) + "\n"
        if args.output:
            with args.output.open("x", encoding="utf-8") as output:
                output.write(rendered)
            print(json.dumps({"input_count": result["input_count"], "row_count": result["row_count"], "candidate_count": result["candidate_count"], "output_written": True}))
        else:
            sys.stdout.write(rendered)
        return 0
    except SummaryError as error:
        print("summary_failed: " + str(error), file=sys.stderr)
        return 2
    except (OSError, OverflowError, ValueError):
        print("summary_failed: output_or_numeric_error (source details withheld)", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
