"""Compact owned install files with existing host tools; preserve source files."""
import argparse
import json
from pathlib import Path
import shlex
import subprocess

SHELL_FILES = {'etc/init.d/alwayroute', 'usr/libexec/alwayroute-timeout',
               'etc/uci-defaults/95-alwayroute-schedule'}


def compact_payload(name, data, jsmin):
    if name.endswith('.json'):
        return (json.dumps(json.loads(data), ensure_ascii=False, separators=(',', ':')) + '\n').encode()
    if (name.startswith('usr/share/ucode/alwayroute/') and name.endswith('.uc')
            or name == 'usr/share/rpcd/ucode/alwayroute' or data.startswith(b'#!/usr/bin/ucode\n')):
        prefix = b''
        if data.startswith(b'#!'):
            prefix, data = data.split(b'\n', 1)
            prefix += b'\n'
        result = subprocess.run([str(jsmin)], input=data, capture_output=True, check=True, timeout=30)
        return prefix + result.stdout
    if name in SHELL_FILES:
        # These three owned scripts have no heredocs. Refuse future additions
        # until their literal bodies have a reviewed compaction policy.
        if b'<<' in data:
            raise ValueError('Shell heredoc requires a reviewed install policy: ' + name)
        result = b''.join(line for index, line in enumerate(data.splitlines(keepends=True))
                          if index == 0 or not line.lstrip().startswith(b'#'))
        if shlex.split(data.decode(), comments=True) != shlex.split(result.decode(), comments=True):
            raise ValueError('Shell compaction changed quoted content: ' + name)
        return result
    return data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--jsmin', type=Path, required=True)
    args = parser.parse_args()
    source, output = args.source.resolve(), args.output.absolute()
    if output.resolve() != output or output == source or source in output.parents:
        raise ValueError('Choose a real generated directory outside the source files')
    files = {}
    for path in source.rglob('*'):
        if path.is_symlink() or not (path.is_file() or path.is_dir()):
            raise ValueError('Owned source contains a link or special file')
        if path.is_file():
            files[path.relative_to(source).as_posix()] = path
    if output.exists():
        for path in output.rglob('*'):
            if (path.is_symlink() or not (path.is_file() or path.is_dir())
                    or path.is_file() and path.relative_to(output).as_posix() not in files):
                raise ValueError('Unexpected generated install file; review separately')
    output.mkdir(parents=True, exist_ok=True)
    for name, path in files.items():
        target = output / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(compact_payload(name, path.read_bytes(), args.jsmin))


if __name__ == '__main__':
    main()
