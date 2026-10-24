"""Exercise the real patched downloader against synthetic loopback HTTP servers.

Requires an existing host uclient-fetch. No public URLs, device access or installs.
"""
import argparse
import contextlib
import os
import socket
import ssl
import subprocess
import threading
import time
import tempfile
from pathlib import Path


@contextlib.contextmanager
def server(respond, tls_context=None):
    listener = socket.socket()
    listener.bind(('127.0.0.1', 0))
    listener.listen(16)
    listener.settimeout(.1)
    stopped = threading.Event()
    errors = []
    seen = []

    def serve():
        while not stopped.is_set():
            try:
                conn, _ = listener.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            with conn:
                conn.settimeout(2)
                try:
                    if tls_context:
                        conn = tls_context.wrap_socket(conn, server_side=True)
                    request = b''
                    while b'\r\n\r\n' not in request and len(request) < 16384:
                        block = conn.recv(4096)
                        if not block:
                            break
                        request += block
                    seen.append(request)
                    for chunk in respond(request, listener.getsockname()[1]):
                        conn.sendall(chunk)
                    if tls_context:
                        conn.unwrap().close()  # Send TLS close_notify instead of an abrupt TCP EOF.
                except (BrokenPipeError, ConnectionResetError, socket.timeout, ssl.SSLError):
                    pass  # Rejection may close before the synthetic response completes.
                except BaseException as error:
                    errors.append(error)
                finally:
                    conn.close()
    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    try:
        yield listener.getsockname()[1], seen
    finally:
        stopped.set()
        listener.close()
        thread.join(timeout=3)
        assert not thread.is_alive(), 'synthetic server did not stop'
        if errors:
            raise errors[0]


def run(binary, response, *, accepted, flags=('--header-limits',), expected=b'ok'):
    def respond(request, port):
        return response(request, port) if callable(response) else [response]
    with server(respond) as (port, seen):
        result = subprocess.run([str(binary), '--no-proxy', '-q', '-T', '2', '-O', '-',
                                 *flags, f'http://127.0.0.1:{port}/'],
                                capture_output=True, timeout=6)
        assert (result.returncode == 0) == accepted, (result.returncode, result.stderr)
        if accepted:
            assert result.stdout == expected, (len(result.stdout), expected[:30])
        else:
            assert not result.stdout, 'rejected headers must not yield a subscription body'
        return len(seen)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--uclient', type=Path, required=True)
    args = parser.parse_args()
    binary = args.uclient.resolve(strict=True)
    prefix = b'HTTP/1.1 200 OK\r\n'
    suffix = b'Content-Length: 2\r\nConnection: close\r\n\r\nok'
    run(binary, prefix + suffix, accepted=True)
    # A large body already in the receive buffer is not part of the header budget.
    body = b'x' * 65536
    run(binary, prefix + b'Content-Length: 65536\r\nConnection: close\r\n\r\n' + body,
        accepted=True, expected=body)
    for headers in [b'X-Large: ' + b'x' * 6000 + b'\r\n',
                    (b'X-Count: x\r\n' * 70),
                    (b'X-Total: ' + b'x' * 3000 + b'\r\n') * 6,
                    b'X-Folded: x\r\n ' + b'x' * 6000 + b'\r\n']:
        run(binary, prefix + headers + suffix, accepted=False)
    # Many individually small headers remain compatible for non-opt-in consumers.
    run(binary, prefix + (b'X-Count: x\r\n' * 70) + suffix,
        accepted=True, flags=())

    def incomplete(_request, _port):
        yield prefix
        for _ in range(20):
            yield b'X' * 512
            time.sleep(.001)
    run(binary, incomplete, accepted=False)

    def redirect(request, port):
        path = request.split(b' ')[1]
        step = 0 if path == b'/' else int(path[1:])
        if step < 3:
            # Each response fits; accumulated chain headers exceed the per-response limit.
            return [b'HTTP/1.1 302 Found\r\nLocation: http://127.0.0.1:' + str(port).encode()
                    + b'/' + str(step + 1).encode() + b'\r\n'
                    + (b'X-Redirect: ' + b'x' * 2500 + b'\r\n') * 3
                    + b'Content-Length: 0\r\nConnection: close\r\n\r\n']
        return [prefix + suffix]
    assert run(binary, redirect, accepted=True) == 4
    print('PASS real downloader: bounded lines/count/total/folding/incomplete headers, body and redirect compatibility')
    with tempfile.TemporaryDirectory(prefix='alwayroute-downloader-tls-') as directory:
        cert, key = Path(directory)/'cert.pem', Path(directory)/'key.pem'
        subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes',
                        '-keyout', str(key), '-out', str(cert), '-days', '1', '-subj', '/CN=127.0.0.1',
                        '-addext', 'subjectAltName=DNS:127.0.0.1,IP:127.0.0.1'],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20)
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(cert, key)
        options = [str(binary), '--header-limits', '--no-proxy', '--https-only', '-q', '-T', '2', '-O', '-']
        def fetch(url, trusted=True):
            return subprocess.run(options + (['--ca-certificate', str(cert)] if trusted else []) + [url],
                                  capture_output=True, timeout=6)
        with server(lambda *_: [prefix + suffix]) as (port, seen):
            result = fetch(f'http://127.0.0.1:{port}/')
            assert result.returncode != 0 and not result.stdout and not seen, 'initial plaintext request was sent'
        with server(lambda *_: [prefix + suffix], ctx) as (port, seen):
            result = fetch(f'https://127.0.0.1:{port}/')
            assert result.returncode == 0 and result.stdout == b'ok', (result.returncode, result.stderr, len(seen))
            result = fetch(f'https://127.0.0.1:{port}/', trusted=False)
            assert result.returncode != 0 and not result.stdout, 'untrusted certificate was accepted'
        with server(lambda *_: [prefix + suffix]) as (plain, received):
            with server(lambda *_: [b'HTTP/1.1 302 Found\r\nLocation: http://127.0.0.1:'
                                     + str(plain).encode() + b'/secret\r\nContent-Length: 0\r\n\r\n'], ctx) as (port, seen):
                result = fetch(f'https://127.0.0.1:{port}/')
                assert result.returncode != 0 and not result.stdout and not received, 'redirect downgrade reached plaintext server'
        def secure_redirect(request, port):
            if request.split(b' ')[1] == b'/':
                return [b'HTTP/1.1 302 Found\r\nLocation: https://127.0.0.1:' + str(port).encode()
                        + b'/done\r\nContent-Length: 0\r\nConnection: close\r\n\r\n']
            return [prefix + suffix]
        with server(secure_redirect, ctx) as (port, seen):
            result = fetch(f'https://127.0.0.1:{port}/')
            assert result.returncode == 0 and result.stdout == b'ok' and len(seen) == 2, result.stderr
        print('PASS real TLS: trusted chain, invalid certificate, initial HTTP and downgrade rejection before transmission')
    with tempfile.TemporaryDirectory(prefix='alwayroute-private-header-') as directory:
        root = Path(directory)
        path = root/'auth'
        token = 'synthetic-loopback-token-never-in-argv'
        path.write_text('Authorization: Bearer '+token+'\n')
        path.chmod(0o600)
        ready, release = threading.Event(), threading.Event()
        def authenticate(request, _port):
            assert ('Authorization: Bearer '+token).encode() in request
            ready.set()
            assert release.wait(3), 'test did not release the authenticated request'
            yield prefix + suffix
        options = [str(binary), '--no-proxy', '--header-limits', '--no-redirect', '--header-file', str(path),
                   '-q', '-T', '2', '-O', '-']
        with server(authenticate) as (port, _seen):
            process = subprocess.Popen(options+[f'http://127.0.0.1:{port}/'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            try:
                assert ready.wait(3), 'authenticated request did not reach the local controller'
                assert token.encode() not in Path(f'/proc/{process.pid}/cmdline').read_bytes(), 'token exposed in argv'
            finally:
                release.set()
                try:
                    output, error = process.communicate(timeout=6)
                except BaseException:
                    process.kill(); process.communicate()
                    raise
            assert process.returncode == 0 and output == b'ok' and token.encode() not in error
        cases = [('public', 'Authorization: Bearer '+token, 0o644),
                 ('injection', 'Authorization: Bearer '+token+'\nX-Injected: yes', 0o600),
                 ('empty', '', 0o600), ('large', 'X: '+('x'*1024), 0o600)]
        link = root/'symlink'; link.symlink_to(path)
        hard = root/'hardlink'; os.link(path, hard)
        fifo = root/'fifo'; os.mkfifo(fifo, 0o600)
        invalid = [link, hard, fifo]
        for name, content, mode in cases:
            item = root/name; item.write_text(content); item.chmod(mode); invalid.append(item)
        for item in invalid:
            with server(lambda *_: [prefix + suffix]) as (port, seen):
                command = [*options]; command[command.index('--header-file')+1] = str(item)
                result = subprocess.run(command+[f'http://127.0.0.1:{port}/'], capture_output=True, timeout=4)
                assert result.returncode != 0 and not seen and token.encode() not in result.stderr, item.name
        hard.unlink()  # The original file must have one link for the next valid request.
        with server(lambda *_: [prefix + suffix]) as (target, received):
            with server(lambda *_: [b'HTTP/1.1 302 Found\r\nLocation: http://127.0.0.1:'
                                     + str(target).encode() + b'/\r\nContent-Length: 0\r\n\r\n']) as (port, _seen):
                result = subprocess.run(options+[f'http://127.0.0.1:{port}/'], capture_output=True, timeout=4)
                assert result.returncode != 0 and not received, 'private controller request followed a redirect'
        print('PASS private controller headers: authenticated request, argv privacy, file safety and redirect rejection')


if __name__ == '__main__':
    main()
