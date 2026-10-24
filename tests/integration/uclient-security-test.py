"""Exercise the real patched downloader against synthetic loopback HTTP servers.

Requires an existing host uclient-fetch. No public URLs, device access or installs.
"""
import argparse
import contextlib
import socket
import subprocess
import threading
import time
from pathlib import Path


@contextlib.contextmanager
def server(respond):
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
                    request = b''
                    while b'\r\n\r\n' not in request and len(request) < 16384:
                        block = conn.recv(4096)
                        if not block:
                            break
                        request += block
                    seen.append(request)
                    for chunk in respond(request, listener.getsockname()[1]):
                        conn.sendall(chunk)
                except (BrokenPipeError, ConnectionResetError, socket.timeout):
                    pass  # Rejection may close before the synthetic response completes.
                except BaseException as error:
                    errors.append(error)
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


if __name__ == '__main__':
    main()
