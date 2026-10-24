"""Build isolated host copies of existing uclient/ustream sources and test limits.

Uses only the selected OpenWrt tree's sources/host libubox, system CMake/compiler
and existing OpenSSL development files. Never installs or changes the build tree.
"""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]


def unique(paths, label):
    paths = list(paths)
    if len(paths) != 1:
        raise ValueError(f'Need one existing {label} source; found {len(paths)}')
    return paths[0]


def copy_sources(source, target):
    target.mkdir()
    for path in source.iterdir():
        if path.is_file() and (path.suffix in ('.c', '.h') or path.name == 'CMakeLists.txt'):
            shutil.copyfile(path, target/path.name)


def inner_patch(name, added_path):
    lines = (ROOT/'firmware/openwrt/patches'/name).read_text().splitlines(True)
    start = lines.index('+++ b/' + added_path + '\n') + 1
    result = []
    for line in lines[start:]:
        if line.startswith('@@'):
            continue
        if not line.startswith('+'):
            break
        result.append(line[1:])
    if not result:
        raise ValueError('Missing packaged uclient patch')
    return ''.join(result).encode()


def run(command, cwd=None, env=None, data=None):
    result = subprocess.run([str(x) for x in command], cwd=cwd, env=env, input=data,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=120)
    if result.returncode:
        sys.stdout.buffer.write(result.stdout[-12000:])
        raise RuntimeError('Isolated build/test failed: ' + str(command[0]))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--openwrt-tree', type=Path, required=True)
    args = parser.parse_args()
    tree = args.openwrt_tree.resolve(strict=True)
    client = unique((tree/'build_dir').glob('target-*/uclient-2026.06.07~daad21fa'), 'pinned uclient')
    ssl = unique((tree/'build_dir').glob('target-*/ustream-ssl-*/ustream-ssl-*/CMakeLists.txt'), 'ustream').parent
    host = tree/'staging_dir/host'
    if not (host/'lib/libubox.so').is_file():
        raise ValueError('Existing host libubox is required; no dependency installation attempted')
    with tempfile.TemporaryDirectory(prefix='alwayroute-uclient-security-') as directory:
        work = Path(directory)
        include = work/'include/libubox'
        shutil.copytree(host/'include/libubox', include)
        shutil.copyfile(ssl/'ustream-ssl.h', include/'ustream-ssl.h')
        copy_sources(client, work/'uclient')
        copy_sources(ssl, work/'ustream')
        source = work/'uclient'
        if 'uclient_http_set_header_limits' not in (source/'uclient-http.c').read_text():
            patch = inner_patch('020-uclient-header-limits.patch', 'package/libs/uclient/patches/900-header-limits.patch')
            run(['patch', '--batch', '--fuzz=0', '--dry-run', '-p1'], source, data=patch)
            run(['patch', '--batch', '--fuzz=0', '-p1'], source, data=patch)
        common = ['-Dubox_include_dir='+str(work/'include'), '-Dubox_library='+str(host/'lib/libubox.so')]
        run(['cmake', '-S', work/'ustream', '-B', work/'ssl-build', *common])
        run(['cmake', '--build', work/'ssl-build', '--target', 'ustream-ssl', '-j2'])
        run(['cmake', '-S', source, '-B', work/'client-build', '-DBUILD_UCODE=OFF', *common])
        run(['cmake', '--build', work/'client-build', '--target', 'uclient-fetch', '-j2'])
        env = {**os.environ, 'LD_LIBRARY_PATH': ':'.join([str(work/'client-build'), str(work/'ssl-build'), str(host/'lib')])}
        result = run([sys.executable, ROOT/'tests/integration/uclient-security-test.py',
                      '--uclient', work/'client-build/uclient-fetch'], env=env)
        sys.stdout.buffer.write(result.stdout)


if __name__ == '__main__':
    main()
