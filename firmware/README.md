# 4A 固件验证输入

本目录保存可审查的构建配方，不保存固件、节点凭证、SSH 私钥或设备备份。
当前配方包含基础网络、核心及初版管理扩展；仍在最终镜像和实机恢复验收阶段，不代表负载与吞吐全部达标。

管理扩展由 `alwayroute-manager`、`luci-app-alwayroute`、`alwayroute-forwarding` 三个包组成，使用 seed 选入镜像；分别负责配置事务、LuCI 页面和 LAN nft TProxy。真实订阅导入、节点选择应用、透明 HTTPS、阻断与回退已在设备验证，见[管理扩展核查](../docs/reports/2026-10-23-manager-integration-audit.md)和[构建记录](../docs/reports/2026-10-23-manager-build.md)。

## 固定输入

OpenWrt、LuCI、packages feed 和 sing-box 的来源、固定版本与源码树哈希另集中记录在 [sources.lock.json](sources.lock.json)。需要在电脑查看完整上游代码时运行 `python scripts/fetch-sources.py fetch`，下载到被 Git 忽略的 `.local/sources/`；详细入口见[上游源码获取](../docs/upstream-sources.md)。

- OpenWrt `v25.12.6`，提交 `64900e756efa667774214f9c6b17c113222e01f7`。
- 第一版千兆 4A 目标 `xiaomi_mi-router-4a-gigabit`；用户确认机身标签“千兆版、R4A”，PCI 的 MT7662／MT7603 与该目标对应；未拆机查看 PCB，实际恢复条件仍须在刷机前核对。
- 使用发布源码中固定到提交的 packages 与 luci feeds；可使用 OpenWrt 官方 GitHub 镜像，提交必须不变。
- sing-box `1.13.21`、Go `1.27.3`、MIPSLE softfloat、`CGO_ENABLED=0`。
- tag 为 `with_quic,with_utls,with_clash_api,badlinkname,tfogo_checklinkname0`。
- 本轮体积候选增加 `-gcflags=all=-l`；常规版本和该候选均已在原厂固件完成版本、配置及单条 VMess 连接测试。原厂启动时需要短时调整内存提交检查，参数已恢复；新固件执行与性能仍需验证。

## 构建约定

1. 将 `openwrt/alwayroute-core`、`alwayroute-manager`、`alwayroute-forwarding`、`luci-app-alwayroute` 分别放入构建源码对应的 `package/` 目录。
2. 在构建源码的 `alwayroute-input/` 放置外部编译的 `sing-box`、不含凭证的 `build-info.json` 及对应上游 `LICENSE`。构建前验证 ELF 架构、静态链接及固定哈希。
3. 用 `openwrt/evaluation.config` 作为 seed，经 `make defconfig` 生成完整配置。先安装该配置需要的 LuCI feed 包及其依赖。
4. 将 `openwrt/99-alwayroute-management` 放入 `files/etc/uci-defaults/`，权限 0755；只放入已有 SSH **公钥**作为 `files/etc/dropbear/authorized_keys`。镜像不包含主机私钥、节点或订阅。脚本首次成功执行后建立 `/etc/alwayroute/management-initialized`，后续保留配置升级时跳过，避免覆盖 LAN、SSH 和 Web 设置；从旧基础镜像迁移前必须先建立并备份该 marker。
5. 在固定的 OpenWrt 源码根目录应用[设备镜像限制补丁](openwrt/patches/001-4a-evaluation-image-limit.patch)：`git apply --check` 通过后再 `git apply`。补丁仅将这一设备的 `IMAGE_SIZE` 改为更严格的 `13248k` 上限（12.9375MiB），DTS 的物理分区不变。原厂 OS1 为 13MiB；最终文件及元数据仍需独立核对。
6. 固定版本、seed、完整 `.config`、差异配置、feeds 提交、包清单、内核配置、构建日志和 SHA-256 一起保留在 Rock 任务目录。

自有包、首启脚本、配置 seed 和设备补丁以本机仓库为准，通过受控同步送往 Rock 构建。上游源码、下载缓存、完整构建目录和私有凭证不放入本仓库。

本轮使用的[构建监督脚本](tools/run-native-build.py)与[镜像只读检查器](tools/inspect-image.py)也保存在仓库，均限定 Rock 的现有任务目录 `/srv/alwayroute/openwrt-build`。监督脚本保留 `make -j8 V=s`、30GiB 和单次 2 小时保护，并在已有同目录 make 或另一个监督实例活跃时拒绝启动；它不会安装依赖。新运行前须外置保留既有 `native-build.log` 与 `native-build-state.json`。检查器使用同一构建生成的 `fwtool` 和 `unsquashfs` 检查指定镜像，不连接或写入路由器；当前预期固定版本、512KiB XZ 块、既定公钥及核心 SHA。

全量源码构建是本轮 ARM64 Rock 环境下采用的路径。官方参考镜像已包含 LuCI；具备匹配运行环境时，也可使用官方 ImageBuilder 将预编译软件包和自有核心重新打包。直接刷官方镜像后安装核心会占用可写 overlay，不能复用将核心压入只读 SquashFS 的容量收益；具体是否容纳仍须测量。

首次构建会编译主机工具、交叉工具链、内核和软件包。保留 Rock 构建树的 `dl/`、`build_dir/`、`staging_dir/` 和现有 Go 缓存，下一轮继续使用同一目录做增量构建；不要例行 `clean`、`dirclean` 或删除缓存。当前未启用 OpenWrt `CONFIG_CCACHE`。自有核心包通过 `PKG_FILE_DEPENDS` 跟踪外部 ELF、`build-info.json` 与 `LICENSE`，更新输入后会重新准备该包；仅改核心时可先执行 `make package/alwayroute-core/compile V=s`，再增量执行整体 `make -j8 V=s` 生成镜像并重新校验。更新上游版本、工具链或目标配置时须重新评估受影响范围，不能承诺完全免编译。

## 核心构建记录

在固定的 sing-box `v1.13.21` 源码目录执行以下命令。`TASK` 表示 Rock 的任务根目录 `/srv/alwayroute`；这些变量仅作用于当前构建进程，不使用 `go env -w` 或修改系统 PATH。模块源码仍经过默认 Go 校验机制验证。

```sh
TASK=/srv/alwayroute
GOOS=linux GOARCH=mipsle GOMIPS=softfloat CGO_ENABLED=0 \
GOMAXPROCS=2 GOTOOLCHAIN=local \
GOCACHE="$TASK/build-cache/gocache" \
GOMODCACHE="$TASK/build-cache/gomodcache" \
GOPATH="$TASK/build-cache/gopath" TMPDIR="$TASK/build-cache/tmp" \
GOPROXY=https://goproxy.cn,direct \
"$TASK/toolchains/go1.27.3/go/bin/go" build \
  -p 2 -trimpath -buildvcs=false -gcflags=all=-l \
  -tags with_quic,with_utls,with_clash_api,badlinkname,tfogo_checklinkname0 \
  -ldflags '-s -w -buildid= -X internal/godebug.defaultGODEBUG=multipathtcp=0 -checklinkname=0 -X github.com/sagernet/sing-box/constant.Version=1.13.21-alwayroute-probe' \
  -o "$TASK/artifacts/sing-box-1.13.21-noinline-mipsle" ./cmd/sing-box
```

- 源码归档 SHA-256：`c994018d7c2a8fc9fcf6080e4b9cc4f2f915e755342238b77e46fc0806fe96db`。
- 实测核心为 27,918,491 字节，SHA-256：`f2abdeffaaec58568d7471e44e0fe0d9557eee6a3011ffc2c6f36fcaac396d76`。
- 核心已由 Go 的 `-s -w` 去除符号；自有包以 `RSTRIP:=:` 禁止 OpenWrt 对这一包二次 strip，确保镜像解出的 ELF 与原厂实测核心逐字节一致。默认 `sstrip -z` 的副本实验会再减少 4,014 字节并改变 SHA，未将该未实测变体放入镜像。
- 禁用内联可能影响性能；短时单节点连接通过不替代吞吐与并发验收。

## 基础候选行为与限制

以下描述最初的基础镜像。管理扩展镜像会从已保存的 enabled／lastgood 配置恢复核心及转发；空白设备仍不会自带订阅、节点或已启用的代理。当前已配置设备通过保留配置升级维持 Wi-Fi、认证和 LAN Web 入口，不应重跑基础默认值覆盖它们。

- 保留双频无线、IPv6、LuCI 基础管理与 nftables，加入 TProxy 模块和 ip-full。
- 当前用途是 B → 4A WAN 的 DHCP 上联；省去 PPP／PPPoE 及相应 LuCI 协议界面。
- 省去内核调试符号和调试信息，不据此承诺最终体积、性能或稳定性。
- 原生完整系统采用 256KiB SquashFS 块时超出本轮镜像上限，seed 因此改为 512KiB，仅增量重打包；未减少协议、IPv6 或无线功能。较大压缩块的解压内存及随机读取性能尚未在新系统实机验证，完整代理管理 UI 也尚未计入镜像预算。
- 首次启动 LAN 为 `192.168.31.1`，SSH 122 仅在 LAN 使用已有公钥，不接受密码登录。
- Web 先只监听本机回环 HTTP。刷入并设置正式认证后，才能按明确配置开放到受控 LAN；当前没有完整代理管理扩展。
- 核心只随镜像提供，不自动启动、不修改 DNS 或接管终端流量。
- 不自动沿用原厂 Wi-Fi 配置；OpenWrt 初始无线状态需按实际镜像检查。
- 本目录没有刷写脚本。实际刷入前必须检查最终镜像、备份、恢复方法、首次访问路径和具体授权。

证据及当前结果见[验证报告](../docs/reports/2026-10-22-4a-baseline-and-route-validation.md)。
