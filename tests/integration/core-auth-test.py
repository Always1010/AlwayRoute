"""Check real core API authentication using production ucode and native uclient.

Only synthetic direct-mode configuration and an ephemeral loopback API are used.
No production ports, device state, privileged inbounds, or external requests.
"""
import argparse
import http.client
import json
import os
from pathlib import Path
import socket
import stat
import subprocess
import tempfile
import time
import uuid

ROOT = Path(__file__).resolve().parents[2]
SHARE = ROOT / 'firmware/openwrt/alwayroute-manager/files/usr/share'
MODULES = SHARE / 'ucode'
POLICIES = SHARE / 'alwayroute/policies'
MAX_REPLY = 262144
PROGRAM = """import * as fs from 'fs';
import {empty,validate,generateRuntimeValidated} from 'alwayroute.model';
let request=json(fs.readfile('/dev/stdin')),model=empty();
model.mode='direct';validate(model);
let config=generateRuntimeValidated(model,request.secret);
config.inbounds=[];
config.experimental.clash_api.external_controller=request.controller;
printf('%J',config);
"""


def private_file(path, data):
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, 'wb') as handle:
        handle.write(data)
    info = path.lstat()
    assert stat.S_ISREG(info.st_mode) and stat.S_IMODE(info.st_mode) == 0o600, 'Test file must be private'


def stop(process):
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=3)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=2)


def http_status(port, secret=None):
    connection = http.client.HTTPConnection('127.0.0.1', port, timeout=1)
    try:
        headers = {'Authorization': 'Bearer ' + secret} if secret is not None else {}
        connection.request('GET', '/proxies', headers=headers)
        response = connection.getresponse()
        response.read(MAX_REPLY + 1)
        return response.status
    finally:
        connection.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ucode', type=Path, required=True)
    parser.add_argument('--uclient', type=Path, required=True, help='Native CLI with --header-file and --no-redirect')
    parser.add_argument('--core', type=Path, required=True, help='Existing native host sing-box with clash_api')
    args = parser.parse_args(argv)
    ucode, uclient, core = (str(path.resolve(strict=True)) for path in (args.ucode, args.uclient, args.core))
    # Keep inherited proxies from sending even a loopback test to another host.
    env = {key: value for key, value in os.environ.items()
           if key.lower() not in ('http_proxy', 'https_proxy', 'all_proxy', 'no_proxy')}
    env.update({'NO_PROXY': '127.0.0.1,localhost', 'no_proxy': '127.0.0.1,localhost',
                'ALWAYROUTE_POLICY_DIR': str(POLICIES)})
    process = None
    reservation = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        reservation.bind(('127.0.0.1', 0))
        port = reservation.getsockname()[1]
        assert port not in (7890, 7893, 9090), 'Refusing a production listener port'
        with tempfile.TemporaryDirectory(prefix='alwayroute-core-auth-') as directory:
            work = Path(directory)
            os.chmod(work, 0o700)
            secrets = [str(uuid.uuid4()), str(uuid.uuid4())]
            headers = [work / 'first.headers', work / 'second.headers']
            wrong_secret = str(uuid.uuid4())
            wrong_header = work / 'wrong.headers'
            private_file(wrong_header, ('Authorization: Bearer ' + wrong_secret).encode())
            for path, secret in zip(headers, secrets):
                private_file(path, ('Authorization: Bearer ' + secret).encode())
            body = work / 'selection.json'
            private_file(body, b'{"name":"Proxy"}')

            def fetch(header=None, *, put=False):
                command = [uclient, '--no-redirect', '-q', '-T', '2']
                if header is not None:
                    command += ['--header-file', str(header)]
                if put:
                    command += ['--method', 'PUT', '--header', 'Content-Type: application/json',
                                '--body-file', str(body)]
                command += ['-O', '-', f'http://127.0.0.1:{port}/proxies' + ('/Other' if put else '')]
                result = subprocess.run(command, env=env, capture_output=True, timeout=5)
                assert len(result.stdout) <= MAX_REPLY, 'Core API response exceeds test budget'
                return result

            def selectors(header):
                response = fetch(header)
                assert response.returncode == 0, 'Authenticated native client GET failed'
                value = json.loads(response.stdout)
                assert isinstance(value.get('proxies'), dict), 'Missing core selector registry'
                return value['proxies']

            for phase, secret in enumerate(secrets):
                request = json.dumps({'secret': secret, 'controller': f'127.0.0.1:{port}'}).encode()
                generated = subprocess.run([ucode, '-L', str(MODULES), '-e', PROGRAM],
                                           input=request, env=env, capture_output=True, timeout=10)
                assert generated.returncode == 0, 'Production runtime module generation failed'
                config = json.loads(generated.stdout)
                assert not config['inbounds'] and config['route']['final'] == 'direct'
                assert config['experimental']['clash_api']['secret'] == secret
                path = work / f'config-{phase}.json'
                private_file(path, generated.stdout)
                checked = subprocess.run([core, 'check', '-c', str(path)], env=env,
                                         capture_output=True, timeout=10)
                assert checked.returncode == 0, 'Host core rejected generated synthetic runtime'
                if phase == 0:
                    reservation.close()
                process = subprocess.Popen([core, 'run', '-c', str(path)], env=env, cwd=work,
                                           stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                           stderr=subprocess.DEVNULL)
                try:
                    deadline = time.monotonic() + 10
                    while True:
                        assert process.poll() is None, 'Isolated core exited before accepting authenticated requests'
                        try:
                            if http_status(port, secret) == 200:
                                break
                        except (OSError, http.client.HTTPException):
                            pass
                        assert time.monotonic() < deadline, 'Isolated core API startup timed out'
                        time.sleep(0.05)
                    command_line = Path(f'/proc/{process.pid}/cmdline').read_bytes()
                    assert all(value.encode() not in command_line for value in secrets), 'Core argv contains an API secret'
                    assert http_status(port) == 401, 'Core accepted a request without a bearer token'
                    assert http_status(port, wrong_secret) == 401, 'Core accepted an incorrect bearer token'
                    assert fetch().returncode != 0 and fetch(wrong_header).returncode != 0, 'Native client accepted unauthenticated GET'
                    current = selectors(headers[phase])
                    assert current['Other']['now'] == 'direct', 'Fresh runtime did not restore generated selector defaults'
                    assert fetch(wrong_header, put=True).returncode != 0, 'Core accepted unauthenticated selector PUT'
                    assert selectors(headers[phase])['Other']['now'] == 'direct', 'Rejected PUT changed a selector'
                    assert fetch(headers[phase], put=True).returncode == 0, 'Authenticated native client PUT failed'
                    assert selectors(headers[phase])['Other']['now'] == 'Proxy', 'Authenticated selector PUT did not take effect'
                    if phase:
                        assert http_status(port, secrets[0]) == 401, 'Restarted core accepted the old bearer token'
                        assert fetch(headers[0]).returncode != 0, 'Native client accepted the previous process credential'
                        assert 'Other' in selectors(headers[1]), 'New credential cannot read restarted core'
                finally:
                    stop(process)
                    process = None
            print('PASS real core authentication: production module generation, missing/wrong/private bearer, '
                  'selector PUT/readback, credential rotation and secret-free core argv; loopback only')
    finally:
        stop(process)
        reservation.close()


if __name__ == '__main__':
    main()
