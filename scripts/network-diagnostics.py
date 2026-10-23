"""Read-only traffic-runner route diagnosis; never add routes or alter the router."""
from __future__ import annotations

import argparse
import ipaddress
import json
import shlex
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit

from alwayroute_context import ContextError, load_environment, ssh_argv

ROOT = Path(__file__).resolve().parents[1]

# Run the same bounded read-only probe on the chosen executor. Input is JSON on
# stdin; nothing from the environment is interpolated into the Python source.
PROBE = r'''
import hashlib,ipaddress,json,os,subprocess,sys
request=json.load(sys.stdin)
def call(argv):
 try:
  p=subprocess.run(argv,capture_output=True,timeout=5)
  return p.returncode,p.stdout
 except (OSError,subprocess.TimeoutExpired):return 127,b''
def routes():return call(['ip','-j','-4','route','show','table','main'])
if os.name!='posix':
 print(json.dumps({'supported':False,'reason':'POSIX iproute executor required'}));sys.exit(0)
before_code,before=routes()
if before_code:
 print(json.dumps({'supported':False,'reason':'Existing iproute command unavailable'}));sys.exit(0)
try:addresses=[str(ipaddress.IPv4Address(request['host']))]
except ValueError:
 code,out=call(['getent','ahostsv4',request['host']]);addresses=[]
 if not code:
  for line in out.splitlines():
   try:value=str(ipaddress.IPv4Address(line.split()[0].decode()))
   except (ValueError,IndexError,UnicodeError):continue
   if value not in addresses:addresses.append(value)
rows=[]
for address in addresses[:4]:
 argv=['ip','-j','-4','route','get',address]
 if request.get('source_address'):argv+=['from',request['source_address']]
 code,out=call(argv)
 row={'destination':address,'query_succeeded':code==0}
 if not code:
  try:
   found=json.loads(out)[0]
   row.update({key:found[key] for key in ('dev','gateway','prefsrc','src','from','table') if key in found})
  except (ValueError,KeyError,IndexError,TypeError):row['query_succeeded']=False
 rows.append(row)
after_code,after=routes()
print(json.dumps({'supported':True,'resolved_addresses_count':len(addresses),
 'routes_unchanged':after_code==0 and before==after,'routes':rows}))
'''


def request_for(environment: dict, url: str) -> dict:
    parsed = urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ContextError("Use an HTTPS diagnostic URL without credentials, query or fragment")
    traffic = environment.get("traffic")
    if not traffic:
        raise ContextError("traffic context is required")
    request = {"host": parsed.hostname}
    for key in ("source_address", "gateway"):
        if traffic.get(key):
            try:
                ipaddress.IPv4Address(traffic[key])
            except ValueError:
                raise ContextError(f"traffic.{key}: this diagnostic requires an IPv4 address") from None
    if traffic.get("source_address"):
        request["source_address"] = traffic["source_address"]
    return request


def diagnose(environment: dict, url: str) -> dict:
    request = request_for(environment, url)
    traffic = environment["traffic"]
    command = [sys.executable, "-c", PROBE]
    if traffic.get("executor") == "ssh":
        command = ssh_argv(traffic["ssh_alias"]) + [shlex.join(["python3", "-c", PROBE])]
    try:
        reply = subprocess.run(command, input=json.dumps(request).encode(), capture_output=True, timeout=35)
        data = json.loads(reply.stdout) if reply.returncode == 0 else None
    except (OSError, ValueError, subprocess.SubprocessError):
        raise ContextError("Traffic route probe failed; raw executor output withheld") from None
    if not isinstance(data, dict):
        raise ContextError("Traffic route probe returned invalid data")
    return data


def public_summary(raw: dict, environment: dict) -> dict:
    traffic = environment["traffic"]
    if raw.get("supported") is not True:
        return {"supported": False, "changes_routes": False,
                "reason": "Use an existing POSIX traffic executor with iproute and getent"}
    rows = []
    for index, route in enumerate(raw.get("routes", []), 1):
        source = route.get("prefsrc") or route.get("src") or route.get("from")
        matches = {
            "source_matches": source == traffic["source_address"] if traffic.get("source_address") and source else None,
            "interface_matches": route.get("dev") == traffic["source_interface"] if traffic.get("source_interface") else None,
            "gateway_matches": route.get("gateway") == traffic["gateway"] if traffic.get("gateway") else None,
        }
        rows.append({"destination_index": index, "route_found": route.get("query_succeeded") is True,
                     **matches, "expected_path_matches": route.get("query_succeeded") is True and
                     not any(value is False for value in matches.values())})
    count = raw.get("resolved_addresses_count")
    return {"supported": True, "changes_routes": False,
            "routes_unchanged": raw.get("routes_unchanged") is True,
            "resolved_addresses_count": count if type(count) is int else 0,
            "route_checks": rows, "https_or_policy_verified": False}


def save_private(path: Path, raw: dict) -> None:
    target = path.resolve()
    if not target.is_relative_to((ROOT / ".local").resolve()):
        raise ContextError("Private diagnostic output must be inside this repository's .local directory")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.parent.chmod(0o700)
    with target.open("x", encoding="utf-8") as handle:
        target.chmod(0o600)
        json.dump(raw, handle, indent=2)
        handle.write("\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env", required=True, type=Path)
    parser.add_argument("--url", default="https://example.com/")
    parser.add_argument("--private-output", type=Path, help="Optional exclusive raw route report inside .local")
    args = parser.parse_args(argv)
    try:
        environment = load_environment(args.env)
        raw = diagnose(environment, args.url)
        if args.private_output:
            save_private(args.private_output, raw)
        summary = public_summary(raw, environment)
        print(json.dumps(summary, indent=2))
        return 0 if summary.get("supported") else 2
    except (ContextError, OSError) as error:
        print(str(error) if isinstance(error, ContextError) else "Private report could not be created", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
