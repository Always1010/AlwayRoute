"""Package an inspected image as two public assets and private CI metadata.

May also repack an existing release using its original source snapshot. Never
builds firmware, modifies tags or contacts a router or GitHub.
"""
import hashlib
import json
from pathlib import Path
import re
import shutil
import zipfile

ROOT = Path(__file__).resolve().parents[2]


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8', newline='\n')


def source_links(text, source_url):
    return re.sub(r'\]\(([^):#]+)\)', lambda match: '](' + source_url + match[1] + ')', text)


def package_release(task, publish, version, device, image, inspection, manifest, *, source_root=None):
    """Keep the firmware identity; choose original sources when repacking a tag."""
    source_root = Path(source_root) if source_root is not None else ROOT
    report = json.loads(inspection.read_text(encoding='utf-8'))
    image_sha = sha256(image)
    if (not report.get('checks') or not all(report['checks'].values())
            or report.get('device') != device['id'] or report.get('sha256') != image_sha
            or manifest.get('device') != device['id'] or manifest.get('version') != version
            or not re.fullmatch(r'[0-9a-f]{40}', manifest.get('source_commit', ''))):
        raise ValueError('Cannot package an uninspected image or mismatched release identity')
    guide = source_root / 'docs/devices/xiaomi-4a-flashing.md'
    flash = source_root / 'scripts/flash.py'
    if not guide.is_file() or not flash.is_file():
        raise ValueError('Flashing guide and tool must come from the selected source snapshot')
    package_manifest = image.with_name(image.name.removesuffix(device['image']['manifest_suffix']) + '.manifest')
    if not package_manifest.is_file():
        raise ValueError('Inspected OpenWrt package manifest is missing')

    publish.mkdir(parents=True, exist_ok=False)
    public = publish / 'public'
    metadata = publish / 'metadata'
    diagnostics = task / 'release-diagnostics'
    contents = task / 'release-bundle'
    for directory in (public, metadata, diagnostics, contents):
        directory.mkdir(exist_ok=False)
    name = 'alwayroute-' + version + '-' + device['id']
    binary = public / (name + '-sysupgrade.bin')
    shutil.copyfile(image, binary)
    shutil.copyfile(binary, contents / binary.name)
    shutil.copyfile(flash, contents / 'flash.py')
    identity = {**manifest, 'image_sha256': image_sha, 'image_bytes': image.stat().st_size,
                'inspection_checks': len(report['checks']), 'bundle_layout_version': 2}
    write_json(contents / 'build-manifest.json', identity)
    write_json(metadata / 'build-manifest.json', identity)

    source_url = 'https://github.com/Always1010/AlwayRoute/blob/' + identity['source_commit'] + '/'
    guide_text = guide.read_text(encoding='utf-8').split('\n', 1)[1].lstrip()
    guide_text = guide_text.replace(
        '版本号以实际发布为准，下面的 `v0.1.0` 仅为示例。',
        '下面命令已使用本版本文件名；管理地址和端口请按实际情况调整。')
    guide_text = guide_text.replace('v0.1.0', version).replace('FLASHING.md', 'README.md')
    guide_text = guide_text.replace('https://github.com/Always1010/AlwayRoute/blob/main/', source_url)
    (contents / 'README.md').write_text(
        '# AlwayRoute ' + version + '\n\n'
        '## 本版本与下载选择\n\n'
        '- 适用设备：小米路由器4A千兆版第一版。\n'
        '- ZIP：首次安装或使用脚本刷机；解压后从本文件开始。\n'
        '- 单独的BIN：已有OpenWrt时，可在LuCI的系统升级页面上传；先备份并检查兼容性。\n'
        '- 本版本已通过构建及镜像检查，尚未实机刷写验收；WAN为DHCP，不含PPPoE。\n'
        '- 固件源码：`' + identity['source_commit'] + '`。\n\n'
        + guide_text + '\n## 许可与来源\n\n'
        '许可、版权、源码来源和完整许可文本统一见 `NOTICE.txt`。详细镜像报告与包清单保存在对应的Actions构建记录中。\n',
        encoding='utf-8', newline='\n')

    notices = ['AlwayRoute ' + version + ' — 许可、版权与源码来源\n',
               '固件源码：' + source_url.replace('/blob/', '/tree/') + '\n',
               '上游版本与下载：' + source_url + 'firmware/sources.lock.json\n',
               '规则数据与许可来源：' + source_url + 'config/routing/sources.lock.json\n',
               '构建方法：' + source_url + 'docs/github-build.md\n',
               '详细包清单与镜像检查报告见对应的GitHub Actions构建记录。\n']
    for filename in ('LICENSE.md', 'THIRD_PARTY_NOTICES.md'):
        notices.append('\n' + '=' * 72 + '\n' + filename + '\n' + '=' * 72 + '\n\n')
        notices.append(source_links((source_root / filename).read_text(encoding='utf-8'), source_url))
    licenses = sorted((source_root / 'LICENSES').glob('*.txt'))
    if not licenses:
        raise ValueError('Original license texts are missing')
    for path in licenses:
        notices.append('\n' + '=' * 72 + '\nLICENSES/' + path.name + '\n' + '=' * 72 + '\n\n')
        notices.append(path.read_text(encoding='utf-8'))
    (contents / 'NOTICE.txt').write_text(''.join(notices), encoding='utf-8', newline='\n')
    (contents / 'SHA256SUMS').write_text(''.join(
        sha256(path) + '  ' + path.name + '\n' for path in sorted(contents.iterdir())), encoding='utf-8', newline='\n')
    bundle = public / (name + '.zip')
    with zipfile.ZipFile(bundle, 'x', compression=zipfile.ZIP_STORED) as archive:
        for path in sorted(contents.iterdir()):
            archive.write(path, path.name)

    # Metadata travels between Actions jobs but is never attached to the Release.
    sums = ''.join(sha256(path) + '  ' + path.name + '\n' for path in sorted(public.iterdir()))
    (metadata / 'SHA256SUMS').write_text(sums, encoding='utf-8', newline='\n')
    (metadata / 'release-notes.md').write_text(
        '仅适用于**小米路由器4A千兆版第一版**，不适用于百兆版或V2。\n\n'
        '- **ZIP**：首次安装或脚本刷机，解压后阅读 `README.md`。\n'
        '- **BIN**：已有OpenWrt时，可用于网页升级。\n\n'
        '构建及镜像检查已通过，本次固件尚未实机刷写验收。WAN为DHCP，不含PPPoE。\n\n'
        '<details>\n<summary>SHA-256 校验值</summary>\n\n```text\n' + sums + '```\n\n</details>\n',
        encoding='utf-8', newline='\n')
    shutil.copyfile(inspection, diagnostics / 'image-inspection.json')
    shutil.copyfile(package_manifest, diagnostics / package_manifest.name)
    print('Release assets ready (ZIP + BIN): ' + str(public), flush=True)
