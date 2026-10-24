"""Cold-check CI host digest from existing archives in a fresh private task.

Does not download or modify an existing OpenWrt tree, toolchain, or system prefix.
Checks patch 012 and reproduces its host configure/build/staging steps directly;
this is not a complete OpenWrt make or GitHub runner acceptance test.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
HOST_PATCH = ROOT / 'firmware/openwrt/patches/012-ucode-host-digest-for-ci.patch'
PACKAGES = {
    'libmd': ('package/libs/libmd', 'libmd-1.1.0.tar.xz',
              '1bd6aa42275313af3141c7cf2e5b964e8b1fd488025caf2f971f43b00776b332', 'libmd-1.1.0'),
    'json-c': ('package/libs/libjson-c', 'json-c-0.18-nodoc.tar.gz',
               '602cdefc1d2aab8318fc0814b7ce7d59e72514d4276ca3eff92f35f86cf1c160', 'json-c-0.18'),
    'ucode': ('package/utils/ucode', 'ucode-2026.01.16~85922056.tar.zst',
              '8c6f586f90e704827dc8736bf3726d15989a978c6a726a52d51e33f8019403b6', 'ucode-2026.01.16~85922056'),
}


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-tree', type=Path, required=True, help='Existing OpenWrt tree, read only')
    parser.add_argument('--task-root', type=Path, required=True, help='Fresh private artifact directory')
    parser.add_argument('--jobs', type=int, default=2, choices=range(1, 5))
    args = parser.parse_args()
    if sys.platform != 'linux':
        parser.error('This cold build check requires an existing Linux host')
    required = ('cc', 'cmake', 'make', 'pkg-config', 'git', 'patch', 'tar', 'zstd', 'readelf')
    missing = [name for name in required if not shutil.which(name)]
    if missing:
        parser.error('Missing existing tools (nothing installed): ' + ', '.join(missing))
    source = args.source_tree.resolve(strict=True)
    task = args.task_root.resolve()
    if task.is_relative_to(source) or source.is_relative_to(task):
        parser.error('Task must be separate from the existing OpenWrt tree')
    # Verify all immutable inputs before creating any build output.
    original_recipes = {}
    for name, (relative, archive, digest, _) in PACKAGES.items():
        recipe = source / relative / 'Makefile'
        original_recipes[name] = sha256(recipe)
        text = recipe.read_text()
        if digest not in text or sha256(source / 'dl' / archive) != digest:
            raise ValueError('Archive or package lock differs: ' + name)
    task.mkdir(parents=True, exist_ok=False)
    logs = task / 'logs'
    logs.mkdir()
    env = {key: value for key, value in os.environ.items() if key not in
           ('CFLAGS', 'CPPFLAGS', 'LDFLAGS', 'LD_LIBRARY_PATH', 'CMAKE_PREFIX_PATH',
            'PKG_CONFIG_PATH', 'PKG_CONFIG_LIBDIR', 'PKG_CONFIG_SYSROOT_DIR', 'CONFIG_SITE')}
    prefix = task / 'hostpkg'
    env.update(PKG_CONFIG_PATH=str(prefix / 'lib/pkgconfig'), PKG_CONFIG_LIBDIR=str(prefix / 'lib/pkgconfig'))
    evidence = {'status': 'building', 'scope': 'isolated host configure/build/staging; not full OpenWrt make',
                'task_root': str(task), 'source_tree_read_only': str(source),
                'original_recipes': original_recipes, 'host_patch_sha256': sha256(HOST_PATCH),
                'archives': {name: values[2] for name, values in PACKAGES.items()},
                'commands': [], 'started_unix': time.time()}

    def run(command, name, cwd=task, timeout=300):
        command = [str(item) for item in command]
        evidence['commands'].append({'name': name, 'command': command, 'cwd': str(cwd)})
        print('Running: ' + name, flush=True)
        with (logs / (name + '.log')).open('wb') as log:
            result = subprocess.run(command, cwd=cwd, env=env, stdout=log, stderr=subprocess.STDOUT, timeout=timeout)
        if result.returncode:
            print((logs / (name + '.log')).read_text(errors='replace')[-8000:], file=sys.stderr)
            raise RuntimeError(name + ' failed: ' + str(result.returncode))

    try:
        recipes = task / 'recipes'
        for relative, _, _, _ in PACKAGES.values():
            shutil.copytree(source / relative, recipes / relative)
        run(['git', 'apply', '--check', HOST_PATCH], 'host-patch-check', recipes)
        run(['git', 'apply', HOST_PATCH], 'host-patch-apply', recipes)
        libmd_recipe = (recipes / PACKAGES['libmd'][0] / 'Makefile').read_text()
        ucode_recipe = (recipes / PACKAGES['ucode'][0] / 'Makefile').read_text()
        if ('HOST_CONFIGURE_ARGS += --disable-shared --with-pic' not in libmd_recipe
                or '$(eval $(call HostBuild))' not in libmd_recipe
                or 'HOST_BUILD_DEPENDS:=libjson-c/host libmd/host' not in ucode_recipe
                or '-DDIGEST_SUPPORT=ON' not in ucode_recipe):
            raise ValueError('Patched host recipes no longer match this verification')
        evidence['patched_recipes'] = {name: sha256(recipes / values[0] / 'Makefile')
                                       for name, values in PACKAGES.items()}
        sources = task / 'sources'
        sources.mkdir()
        for name, (relative, archive, _, top) in PACKAGES.items():
            run(['tar', '-xf', source / 'dl' / archive, '-C', sources], name + '-extract')
            for number, patch in enumerate(sorted((recipes / relative / 'patches').glob('*.patch'))):
                run(['patch', '-p1', '--fuzz=0', '-i', patch], name + '-patch-' + str(number), sources / top)
        md = sources / PACKAGES['libmd'][3]
        run([md / 'configure', '--prefix=' + str(prefix), '--disable-shared', '--with-pic'], 'libmd-configure', md)
        run(['make', '-j' + str(args.jobs)], 'libmd-build', md)
        run(['make', 'install'], 'libmd-private-stage', md)
        if not (prefix / 'lib/libmd.a').is_file() or list(prefix.glob('lib/libmd.so*')):
            raise ValueError('libmd must be newly built as a static PIC archive only')
        json_build = task / 'json-c-build'
        run(['cmake', '-S', sources / PACKAGES['json-c'][3], '-B', json_build,
             '-DCMAKE_BUILD_TYPE=Release', '-DCMAKE_INSTALL_PREFIX=' + str(prefix),
             '-DCMAKE_INSTALL_LIBDIR=lib', '-DDISABLE_EXTRA_LIBS=TRUE', '-DBUILD_SHARED_LIBS=FALSE'], 'json-c-configure')
        run(['cmake', '--build', json_build, '-j', args.jobs], 'json-c-build')
        run(['cmake', '--install', json_build], 'json-c-private-stage')
        ucode_build = task / 'ucode-build'
        # Read module switches from the patched recipe rather than keeping a
        # second list. System zlib/compiler are existing read-only prerequisites.
        modules = re.findall(r'-(D[A-Z0-9_]+_SUPPORT=(?:ON|OFF))', ucode_recipe)
        run(['cmake', '-S', sources / PACKAGES['ucode'][3], '-B', ucode_build,
             '-DCMAKE_BUILD_TYPE=Release', '-DCMAKE_INSTALL_PREFIX=' + str(prefix),
             '-DCMAKE_INSTALL_LIBDIR=lib', '-DCMAKE_PREFIX_PATH=' + str(prefix),
             '-DCMAKE_BUILD_RPATH=' + str(prefix / 'lib'), '-DCMAKE_INSTALL_RPATH=' + str(prefix / 'lib'),
             '-DSOVERSION=20230711', '-DBUILD_SHARED_LIBS=OFF', *['-' + value for value in modules]], 'ucode-configure')
        cache = (ucode_build / 'CMakeCache.txt').read_text()
        if 'libmd:FILEPATH=' + str(prefix / 'lib/libmd.a') not in cache:
            raise ValueError('ucode did not select the newly built private libmd.a')
        run(['cmake', '--build', ucode_build, '-j', args.jobs], 'ucode-build')
        run(['cmake', '--install', ucode_build], 'ucode-private-stage')
        digest = prefix / 'lib/ucode/digest.so'
        run(['readelf', '-d', digest], 'digest-dynamic-dependencies')
        dependencies = (logs / 'digest-dynamic-dependencies.log').read_text()
        if 'libmd.so' in dependencies:
            raise ValueError('digest unexpectedly depends on a system shared libmd')
        binary = prefix / 'bin/ucode'
        run([binary, '-e', "import { readfile } from 'fs'; import { sha256 } from 'digest'; "
             "if (sha256('abc') != 'ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad') die('bad SHA256'); "
             "if (!readfile('firmware/release.json')) die('fs unavailable'); print('PASS fresh host fs/digest/SHA256\\n');"],
            'fresh-host-fs-digest', ROOT)
        run([sys.executable, ROOT / 'tests/manager/check-imports.py', binary], 'fresh-manager-imports', ROOT)
        evidence.update(status='succeeded', libmd_static_sha256=sha256(prefix / 'lib/libmd.a'),
                        digest_module_sha256=sha256(digest), host_ucode_sha256=sha256(binary),
                        host_ucode=str(binary), libmd_selected=str(prefix / 'lib/libmd.a'))
    except BaseException as error:
        evidence.update(status='failed', error=str(error))
        raise
    finally:
        evidence['finished_unix'] = time.time()
        evidence['original_recipes_unchanged'] = all(
            sha256(source / PACKAGES[name][0] / 'Makefile') == digest for name, digest in original_recipes.items())
        (task / 'evidence.json').write_text(json.dumps(evidence, indent=2) + '\n')
    print(json.dumps(evidence, indent=2), flush=True)


if __name__ == '__main__':
    main()
