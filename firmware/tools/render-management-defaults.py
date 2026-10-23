"""Render an explicitly selected first-boot policy to a fresh reviewable file.

Does not access devices or modify an OpenWrt tree. Actual policies stay in the
ignored .local directory; no LAN address or SSH port is assumed by this renderer.
"""
import argparse
import ipaddress
import json
from pathlib import Path
import re

TEMPLATE = Path(__file__).resolve().parents[1] / 'openwrt/management-defaults.sh.in'


def render(policy):
    if (not isinstance(policy, dict) or set(policy) != {'schema_version', 'lan', 'ssh'}
            or type(policy['schema_version']) is not int or policy['schema_version'] != 1):
        raise ValueError('Deployment policy requires schema_version 1, lan and ssh')
    network = ''
    if policy['lan'] is not None:
        lan = policy['lan']
        if not isinstance(lan, dict) or set(lan) != {'address', 'netmask'}:
            raise ValueError('LAN policy requires address and netmask, or null to preserve them')
        if not all(isinstance(lan[k], str) for k in lan):
            raise ValueError('LAN address and netmask must be strings')
        interface = ipaddress.IPv4Interface(lan['address'] + '/' + lan['netmask'])
        if (str(interface.ip) != lan['address'] or str(interface.netmask) != lan['netmask']
                or interface.ip.is_unspecified or interface.ip.is_multicast or interface.ip.is_loopback
                or interface.ip in (interface.network.network_address, interface.network.broadcast_address)):
            raise ValueError('LAN address must be a usable host address with a canonical netmask')
        network = f"set network.lan.ipaddr='{interface.ip}'\nset network.lan.netmask='{interface.netmask}'\n"
    ssh = policy['ssh']
    if not isinstance(ssh, dict) or set(ssh) != {'port', 'interface'}:
        raise ValueError('SSH policy requires port and interface')
    port = ssh['port']
    if port is not None and (type(port) is not int or not 1 <= port <= 65535):
        raise ValueError('SSH port must be 1..65535, or null to preserve it')
    if not isinstance(ssh['interface'], str) or not re.fullmatch(r'[A-Za-z0-9_]{1,32}', ssh['interface']):
        raise ValueError('SSH interface must be a logical UCI network name')
    return (TEMPLATE.read_text(encoding='utf-8')
            .replace('@NETWORK_UCI@', network)
            .replace('@SSH_PORT_UCI@', f"set dropbear.@dropbear[0].Port='{port}'\n" if port is not None else '')
            .replace('@SSH_INTERFACE@', ssh['interface'])
            .replace('@NETWORK_COMMIT@', 'commit network\n' if network else ''))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--policy', type=Path, required=True, help='Explicit deployment JSON; use private .local for actual settings')
    parser.add_argument('--output', type=Path, required=True, help='Fresh output path, outside the build tree until reviewed')
    args = parser.parse_args(argv)
    output = render(json.loads(args.policy.read_text(encoding='utf-8-sig')))
    with args.output.open('x', encoding='utf-8', newline='\n') as stream:
        stream.write(output)


if __name__ == '__main__':
    main()
