"""Resolve build-host paths without connecting hosts or changing configuration.

Without --env the existing Rock task layout is retained. Environment files are
validated by the repository workflow module; these tools still run on the build
host even when its environment describes an SSH executor.
"""
from pathlib import Path
import sys


DEFAULT_TASK_ROOT = Path('/srv/alwayroute')
IMAGE_RELATIVE = Path('bin/targets/ramips/mt7621/openwrt-ramips-mt7621-xiaomi_mi-router-4a-gigabit-squashfs-sysupgrade.bin')
IMAGE_LIMIT_BYTES = 13248 * 1024


def build_context(environment=None, *, default_jobs=8, default_timeout=7200):
    build = {}
    if environment is not None:
        scripts = Path(__file__).resolve().parents[2] / 'scripts'
        if str(scripts) not in sys.path:
            sys.path.insert(0, str(scripts))
        from alwayroute_context import load_environment
        build = load_environment(environment).get('build', {})
    task = Path(build.get('task_root', DEFAULT_TASK_ROOT))
    tree = Path(build.get('openwrt_tree', task / 'openwrt-build/source'))
    toolchains = Path(build.get('toolchain_root', task / 'toolchains'))
    go_root = toolchains / 'go1.27.3/go'
    return {
        'task_root': task,
        'openwrt_tree': tree,
        'build_root': tree.parent,
        'go_root': go_root,
        'go': go_root / 'bin/go',
        'cache_root': Path(build.get('cache_root', task / 'build-cache')),
        'output_root': Path(build.get('output_root', task / 'artifacts')),
        'sing_box_source': task / 'sources/sing-box-1.13.21',
        'sing_box_archive': task / 'artifacts/sing-box-v1.13.21-source.tar.gz',
        'jobs': build.get('jobs', default_jobs),
        'timeout_seconds': build.get('timeout_seconds', default_timeout),
        'disk_limit_bytes': build.get('disk_limit_bytes', 30 * 1024 ** 3),
    }
