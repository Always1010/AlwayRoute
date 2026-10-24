# CI host digest 独立冷构建验证

2026-10-24 在 Rock 现有 Linux ARM64 环境完成独立冷构建：从原构建树的已下载归档重建 libmd、json-c、ucode，使用本次新生成的 host ucode 验证真实 fs／digest／SHA256，并通过当时远端同步副本中的四项 CI 运行时门禁。

本次只写新的私有 artifact 目录，不修改现有 OpenWrt 源码树、hostpkg、工具链、系统依赖或配置，不连接设备，不下载或安装系统软件。使用已有 GCC 13.3.0、CMake 3.28.3、make、pkg-config、tar、zstd、git、patch、readelf 及系统 zlib；并行度为 2。

## 方法和配方复审

可复用入口为 [verify_ci_host_digest.py](../../tests/firmware/verify_ci_host_digest.py)：

```sh
python3 tests/firmware/verify_ci_host_digest.py \
  --source-tree <existing-openwrt-tree> \
  --task-root <new-private-artifact-directory> --jobs 2
```

入口拒绝已存在的任务目录和与原源码树重叠的输出。先验证三份归档 SHA256，再复制对应包配方，在副本检查并应用 `012-ucode-host-digest-for-ci.patch`；重放锁定 OpenWrt 的 json-c／ucode 包补丁，使用独立源码目录与私有安装前缀完成编译和产物暂存。ucode 模块开关从应用补丁后的配方读取。

`012` 的依赖关系为 `ucode/host → libjson-c/host + libmd/host`。libmd 新增标准 `HostBuild`，没有返回 ucode 的依赖；ucode 原有目标端 `PKG_BUILD_DEPENDS:=libmd` 和目标端模块配置保持不变。OpenWrt host 查找根包含 host、hostpkg；上游 libjson-c 的 host 前缀在 host，新增 libmd 默认在 hostpkg，可被 ucode host 的 pkg-config 和 CMake 查找。

libmd host 通过 `--disable-shared --with-pic` 生成静态 PIC 库。运行时可加载的 digest 模块仍是 `digest.so`，其中链接静态 `libmd.a`，不要求运行主机额外提供共享 `libmd.so`。实际生成的 libtool 为 `pic_mode=yes`、`pic_flag=" -fPIC -DPIC"`；新 `digest.so` 成功链接并执行 SHA256，CMake 明确选择本次私有 `libmd.a`。`readelf -d digest.so` 的 NEEDED 只有 `libc.so.6` 和 `ld-linux-aarch64.so.1`，没有 `libmd.so`。json-c 也来自本次私有 `libjson-c.a`。

## 实际证据

私有证据目录为 Rock 的 `artifacts/ci-host-digest-cold-20261024-01/`，保留 `evidence.json`、`runtime-gate-evidence.json`、各步骤日志、独立源码和新生成产物，总计约 20MiB。冷构建及首次导入检查耗时约 45.3 秒。三份原包 Makefile 的校验和在执行前后相同。

| 输入／新产物 | SHA256 |
| --- | --- |
| `012-ucode-host-digest-for-ci.patch` | `2a35f0b3f7b54a953ffc1e4fce49381343e8459f57407a464700b6fccd0d6588` |
| `libmd-1.1.0.tar.xz` | `1bd6aa42275313af3141c7cf2e5b964e8b1fd488025caf2f971f43b00776b332` |
| `json-c-0.18-nodoc.tar.gz` | `602cdefc1d2aab8318fc0814b7ce7d59e72514d4276ca3eff92f35f86cf1c160` |
| `ucode-2026.01.16~85922056.tar.zst` | `8c6f586f90e704827dc8736bf3726d15989a978c6a726a52d51e33f8019403b6` |
| 新 `libmd.a` | `0991af07ca87e961281ba100f17b18bfb633b6b8ba47b47335da1d3cfa69e4a8` |
| 新 `digest.so` | `f61fe49665dbf04e8bced9a45078d6ab2b660ac078edb85e51e9f110ab6b400d` |
| 新 host `ucode` | `816d118b4826d87083ea3c1d3f20f0dd020420b3113fadcbf212adb2c8a05fff` |

新 host ucode 实际导入 fs／digest，以 fs 读取仓库发布配方，并核对 `sha256('abc')` 等于标准摘要 `ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad`。真实 manager 模块导入通过。

随后只在新任务目录创建 `staging_dir/hostpkg → hostpkg` 链接，使当时远端副本的实际 `runtime_release_gate()` 使用这个新生成的解释器，四项门禁全部通过，耗时 21.248 秒：

- `manager-imports`：真实 manager 模块导入通过。
- `manager-tests`：82 项模型契约、105 项事务、11 项下载权限、9 项 selection、9 项异步 traffic 检查通过。
- `manager-watchdog`：退出码、截止超时和外部 TERM 下的抗 TERM 子进程清理通过。
- `forwarding-tests`：10 项命令替身隔离检查通过。

这里的四项门禁和检查数量对应当时远端同步点，不包括后续 `93f32049` 增加的第五项 `downloader-security`、`dcbad7ea` 的 status 检查及后续 API secret 变更。不能将上述结果当作更新后完整门禁已经通过；更新后的独立副本可继续复用本次生成的新 host ucode，再运行当前门禁。其私有路径为 `<artifact-root>/ci-host-digest-cold-20261024-01/hostpkg/bin/ucode`。

## 验证边界

本次证明新配方所需库能够从锁定归档冷编，生成可用的新 host ucode／digest，且本次新解释器可以执行实际 CI 运行时门禁。没有复用旧 host ucode 或旧 digest 来替代这些结果。

本次直接执行包的 configure／CMake／编译／私有暂存步骤，使用已有系统 zlib、Unix Makefiles 生成器和 ARM64 编译器；未执行完整 OpenWrt 顶层 make 的 HostBuild 依赖调度、其 Ninja 生成器或 GitHub Linux x64 冷 Runner。完整发布构建的磁盘／耗时、标准密码后端镜像容量和最终发布检查仍需由真实 GitHub Runner 验证。host 隔离测试也不能替代设备的 nftables、rpcd／procd、转发和吞吐验收。
