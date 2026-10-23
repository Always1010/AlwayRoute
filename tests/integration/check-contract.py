"""Check the independent LuCI, rpcd and ACL integration boundaries without tools."""
import json
import re
from pathlib import Path

root = Path(__file__).resolve().parents[2]
packages = root / "firmware/openwrt"
manager = packages / "alwayroute-manager/files/usr/share/rpcd"
ui = packages / "luci-app-alwayroute"

api = (ui / "htdocs/luci-static/resources/alwayroute/api.js").read_text(encoding="utf-8")
definitions = api.split("var definitions = {", 1)[1].split("};", 1)[0]
ui_methods = set(re.findall(r"\b([A-Za-z_]+)\s*:\s*\[", definitions))

rpc = (manager / "ucode/alwayroute").read_text(encoding="utf-8")
mapping = rpc.split("for(let method,args in {", 1)[1].split("}) {", 1)[0]
rpc_methods, depth = set(), 0
for token in re.finditer(r"([A-Za-z_]+)\s*:|[{}]", mapping):
    value = token.group()
    if token.group(1) and depth == 0:
        rpc_methods.add(token.group(1))
    elif value == "{":
        depth += 1
    elif value == "}":
        depth -= 1

acl = json.loads((manager / "acl.d/alwayroute.json").read_text(encoding="utf-8"))
menu = json.loads((ui / "root/usr/share/luci/menu.d/luci-app-alwayroute.json").read_text(encoding="utf-8"))
groups = menu["admin/services/alwayroute"]["depends"]["acl"]
assert len(groups) == 1 and groups[0] in acl, "menu references a missing ACL group"
grant = acl[groups[0]]
read = set(grant["read"]["ubus"]["alwayroute"])
write = set(grant["write"]["ubus"]["alwayroute"])
assert ui_methods == rpc_methods, f"UI/RPC methods differ: {ui_methods ^ rpc_methods}"
assert read | write == rpc_methods, "RPC methods are missing from or over-granted by ACL"
assert not read & {"get", "export", "save", "refresh", "apply", "select", "rollback", "service", "check", "cancel_check"}, "read ACL exposes credentials or actions"
assert read.isdisjoint(write), "method appears in both permission sets"
for permission in ("read", "write"):
    assert set(grant[permission]) == {"ubus"}, "ACL grants direct file or UCI access"
    assert set(grant[permission]["ubus"]) == {"alwayroute"}, "ACL grants unrelated ubus objects"
    assert "*" not in grant[permission]["ubus"]["alwayroute"], "wildcard RPC permission"
assert menu["admin/services/alwayroute"]["action"]["path"] == "alwayroute/app"
assert (ui / "htdocs/luci-static/resources/view/alwayroute/app.js").is_file()
print(f"PASS {len(rpc_methods)} UI/RPC methods, private credential actions, minimal ACL and menu binding")
