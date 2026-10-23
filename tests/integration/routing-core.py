"""Exercise generated routing with the real core and synthetic loopback services.

Requires existing build-host ucode and sing-box. No external DNS, production
ports, router, credentials or persistent configuration are used.
"""
import argparse
import json
import os
from pathlib import Path
import socket
import socketserver
import struct
import subprocess
import tempfile
import threading
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
MODULES = ROOT / 'firmware/openwrt/alwayroute-manager/files/usr/share/ucode'
POLICIES = ROOT / 'firmware/openwrt/alwayroute-manager/files/usr/share/alwayroute/policies'
QUERIES = []
ANSWERS = {'other.synthetic.invalid': '127.0.0.2', 'blocked.synthetic.invalid': '127.0.0.3'}


class DNS(socketserver.BaseRequestHandler):
    def handle(self):
        data, transport = self.request
        offset, labels = 12, []
        while data[offset]:
            size = data[offset]
            labels.append(data[offset + 1:offset + 1 + size].decode())
            offset += 1 + size
        name = '.'.join(labels)
        QUERIES.append((self.server.role, name))
        question = data[12:offset + 5]
        address = socket.inet_aton(ANSWERS.get(name, '127.0.0.1'))
        response = data[:2] + struct.pack('!HHHHH', 0x8180, 1, 1, 0, 0) + question
        response += b'\xc0\x0c' + struct.pack('!HHIH', 1, 1, 30, 4) + address
        transport.sendto(response, self.client_address)


class Echo(socketserver.BaseRequestHandler):
    def handle(self):
        self.request.settimeout(8)
        try:
            while data := self.request.recv(1024):
                self.request.sendall(data)
        except (TimeoutError, ConnectionError):
            pass


class EchoServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def port():
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        return listener.getsockname()[1]


def receive(stream, size):
    data = b''
    while len(data) < size:
        part = stream.recv(size - len(data))
        if not part:
            raise AssertionError('Synthetic connection closed unexpectedly')
        data += part
    return data


def query(port_number, name):
    labels = b''.join(bytes([len(x)]) + x.encode() for x in name.split('.')) + b'\0'
    packet = struct.pack('!HHHHHH', 321, 0x100, 1, 0, 0, 0) + labels + struct.pack('!HH', 1, 1)
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as stream:
        stream.settimeout(4)
        stream.sendto(packet, ('127.0.0.1', port_number))
        response = stream.recv(4096)
    assert response[:2] == packet[:2] and response[3] & 15 == 0


def connect(proxy_port, target, target_port, reject=False):
    stream = socket.create_connection(('127.0.0.1', proxy_port), 5)
    stream.sendall(b'\x05\x01\x00')
    assert receive(stream, 2) == b'\x05\x00'
    try:
        address = b'\x01' + socket.inet_aton(target)
    except OSError:
        encoded = target.encode()
        address = b'\x03' + bytes([len(encoded)]) + encoded
    stream.sendall(b'\x05\x01\x00' + address + struct.pack('!H', target_port))
    # Provide sniffable bytes before waiting for the upstream connection.
    stream.sendall(b'synthetic-probe')
    response = receive(stream, 4)
    if response[1] != 0:
        stream.close()
        return None
    size = 4 if response[3] == 1 else 16
    receive(stream, size + 2)
    try:
        assert receive(stream, len(b'synthetic-probe')) == b'synthetic-probe'
    except (AssertionError, ConnectionError):
        stream.close()
        if reject:
            return None
        raise
    return stream


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ucode', type=Path, required=True)
    parser.add_argument('--sing-box', type=Path, required=True)
    args = parser.parse_args()
    servers = []
    process = None
    with tempfile.TemporaryDirectory(prefix='alwayroute-routing-') as directory:
        work = Path(directory)
        try:
            for role in ['bootstrap', 'proxy-dns']:
                server = socketserver.ThreadingUDPServer(('127.0.0.1', 0), DNS)
                server.role = role
                servers.append(server)
            echo = EchoServer(('127.0.0.1', 0), Echo)
            servers.extend([echo, EchoServer(('127.0.0.2', echo.server_address[1]), Echo),
                            EchoServer(('127.0.0.3', echo.server_address[1]), Echo)])
            for server in servers:
                threading.Thread(target=server.serve_forever, daemon=True).start()
            program = """import {empty,generate} from 'alwayroute.model';let m=empty();
m.nodes=[{id:'synthetic-node',name:'Synthetic',type:'vmess',enabled:true,server:'upstream.synthetic.invalid',port:443,uuid:'00000000-0000-4000-8000-000000000001'}];
for(let g in m.groups){if(g.id=='Other')g.selected='Proxy';if(g.id=='Proxy')g.selected='synthetic-node';}
m.rules=[{id:'forced',enabled:true,type:'domain',value:'forced.synthetic.invalid',outbound:'Proxy'},
 {id:'blocked_address',enabled:true,type:'cidr',value:'127.0.0.3/32',outbound:'block'}];
printf('%J',generate(m));"""
            result = subprocess.run([str(args.ucode), '-L', str(MODULES), '-'], input=program.encode(),
                capture_output=True, check=True, timeout=15,
                env={**os.environ, 'ALWAYROUTE_POLICY_DIR': str(POLICIES)})
            config = json.loads(result.stdout)
            # Exercise production selector/DNS generation without an external VMess server.
            config['outbounds'] = [{'type': 'direct', 'tag': o['tag']} if o['tag'] == 'synthetic-node' else o
                                   for o in config['outbounds']]
            domains = {'version': 2, 'rules': [{'domain': ['known.synthetic.invalid', 'forced.synthetic.invalid']}]}
            addresses = {'version': 2, 'rules': [{'ip_cidr': ['127.0.0.1/32', '127.0.0.3/32']}]}
            for entry, source in zip(config['route']['rule_set'], [domains, addresses], strict=True):
                path = work / (entry['tag'] + '.json')
                path.write_text(json.dumps(source))
                target = path.with_suffix('.srs')
                subprocess.run([str(args.sing_box), 'rule-set', 'compile', str(path), '-o', str(target)],
                    capture_output=True, check=True, timeout=15)
                entry['path'] = str(target)
            config['dns']['servers'] = [{'type': 'udp', 'tag': s.role, 'server': '127.0.0.1',
                                        'server_port': s.server_address[1]} for s in servers[:2]]
            mixed_port, api_port, dns_port = port(), port(), port()
            config['inbounds'] = [{'type': 'mixed', 'tag': 'synthetic', 'listen': '127.0.0.1', 'listen_port': mixed_port},
                                  {'type': 'direct', 'tag': 'synthetic-dns', 'listen': '127.0.0.1', 'listen_port': dns_port}]
            config['route']['rules'].insert(0, {'inbound': ['synthetic-dns'], 'action': 'hijack-dns'})
            config['experimental']['clash_api']['external_controller'] = f'127.0.0.1:{api_port}'
            path = work / 'config.json'
            path.write_text(json.dumps(config))
            with (work / 'core.log').open('wb') as log:
                process = subprocess.Popen([str(args.sing_box), 'run', '-c', str(path)], stdout=log, stderr=log)
                api = f'http://127.0.0.1:{api_port}/connections'
                opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
                deadline = time.monotonic() + 8
                while True:
                    try:
                        opener.open(api, timeout=1).close()
                        break
                    except OSError:
                        assert process.poll() is None and time.monotonic() < deadline, 'Isolated core failed to start'
                        time.sleep(.1)
                cases = [('known.synthetic.invalid', 'Domestic', 'bootstrap'),
                         ('forced.synthetic.invalid', 'Proxy', 'proxy-dns'),
                         ('unknown.synthetic.invalid', 'Domestic', 'proxy-dns'),
                         ('other.synthetic.invalid', 'Other', 'proxy-dns'),
                         ('127.0.0.1', 'Domestic', None)]
                for target, group, resolver in cases:
                    before = len(QUERIES)
                    if resolver:
                        query(dns_port, target)
                        assert (resolver, target) in QUERIES[before:], ('Unexpected DNS server', target, resolver, QUERIES[before:])
                    stream = connect(mixed_port, target, echo.server_address[1])
                    assert stream is not None, 'Synthetic route failed'
                    try:
                        with opener.open(api, timeout=2) as response:
                            connections = json.load(response)['connections']
                        rows = [c for c in connections if int(c['metadata']['sourcePort']) == stream.getsockname()[1]]
                        assert len(rows) == 1 and group in rows[0]['chains'], 'Unexpected route group'
                        if resolver is None:
                            assert len(QUERIES) == before, 'IP destination unexpectedly resolved'
                    finally:
                        stream.close()
                for target in ['blocked.synthetic.invalid', '127.0.0.3']:
                    assert connect(mixed_port, target, echo.server_address[1], reject=True) is None, 'User IP block bypassed'
            print('PASS 7 isolated core routing cases: domain/DNS override, resolved IP, pure IP, Other and IP blocks')
        finally:
            if process is not None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
            for server in servers:
                server.shutdown()
                server.server_close()


if __name__ == '__main__':
    main()
