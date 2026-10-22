# AlwayRoute Manager 增量构建记录（2026-10-23）

最终镜像已构建并归档，构建线未执行刷机。修正输入提交 `49c8643`，完整增量构建退出 0、耗时 86.977 秒；Manager profile 的 **244 项检查全部通过**。镜像 13,435,470 字节，SHA-256 为 `58780cefc18ef4a8624be9128f6b9ecce4c59e5a20efbba87840332676030135`。用户随后批准保留配置升级，主任务已发起一次 sysupgrade，交接时正等待重启；实际升级恢复结果和最终设备 overlay 空间由主任务另行补充验收。

## 构建边界与输入

- PC 仓库为自有源码主本；Rock 工作副本为 `/srv/alwayroute/workspaces/AlwayRoute/`。
- 复用 `/srv/alwayroute/openwrt-build/source`，上游固定提交 `64900e756efa667774214f9c6b17c113222e01f7`（OpenWrt 25.12.6）。不安装软件，不改全局 PATH、网络或服务，不连接路由器、不刷机。
- 保留现有工具链、下载归档、Go 模块/编译缓存；不运行 clean、dirclean、distclean，不启用 ccache，不重编外部 sing-box 核心。
- 仅将 `alwayroute-forwarding`、`alwayroute-manager`、`luci-app-alwayroute` 三个目录通过逐包 rsync 放入 `source/package/`。每次先看 dry-run；不将整仓库覆盖到 OpenWrt 构建树。
- 保留原目标、内核配置、512 KiB SquashFS 块、13248 KiB 镜像上限和核心 ELF SHA-256 `f2abdeffaaec58568d7471e44e0fe0d9557eee6a3011ffc2c6f36fcaac396d76`。
- `make defconfig` 前后逐行比较，唯一配置增加为三个新包；原有目标、内核和其他包选项完全一致。原有 `rpcd-mod-ucode`、`ucode-mod-digest` 已被基线选择，未额外增加依赖组件。
- 启动每轮 make 前检查同树活跃 make，并复用文件锁、进程组与 30 GiB / 2 小时守护。构建使用 `-j8 V=s`；日志和状态文件逐轮分开保存。

## 构建配方与验收脚本修正

LuCI 包原配方末尾为 `# Call BuildPackage from luci.mk.`，首字母大写使 OpenWrt `include/scan.mk` 的区分大小写 `call BuildPackage` 签名扫描漏掉该包，`defconfig` 会静默移除其选择。已改为上游标准签名 `# call BuildPackage - OpenWrt buildroot signature`；修正后配置中存在该包。

镜像检查脚本新增显式 `--profile manager --baseline-image <已归档基线>`。默认 `baseline` 保留原先的 37 项检查，归档基线回归全部通过。Manager profile 保留镜像大小、CRC、目标/版本/设备、公钥、SSH 主机密钥排除、原始核心 ELF 等边界；增加以下检查：

- 三个新增包全部存在，基线 140 个包的版本全部保留，包集合只增加三个包。
- 压缩内核 payload 与归档基线逐字节一致。
- 所有自有 manager、forwarding、LuCI 输入文件与镜像载荷逐文件核对，保存源文件 SHA-256 和安装载荷 SHA-256。LuCI JS/CSS 使用现有 host minifier 重放相同转换后比较，保留原压缩配置。
- fresh 镜像没有 `/etc/alwayroute/` 持久状态、节点配置或 `/tmp/alwayroute/` 运行配置。已审查的 boot 必须同时满足用户启用和存在 lastgood 才能生成 runtime，init 必须先获得 runtime 才启动代理。
- ROM 内必须存在精确启动链接 `/etc/rc.d/S95alwayroute -> ../init.d/alwayroute`，保证保留启用状态和 lastgood 后具备自动恢复入口。
- 镜像全部可执行 UTF-8 文本检查无 CRLF；全部已有 shebang 检查解释器路径存在，自有包可执行文本必须有 shebang。上游可执行位的 shell source 片段（例如 `/etc/profile.d/busybox-history-file.sh`）没有 shebang 是既有上游行为，单独记录，不能误作需执行的入口文件。

OpenWrt `include/package.mk` 的 prepared hash 和 rdep 默认追踪整个包 `${CURDIR}`，因此 `files/` 内容更新会使准备戳变更，不需要清空已有构建缓存。最终以包内字节和镜像载荷 hash 另行确认，不能仅依赖戳记推断更新成功。

## 首轮产物拒绝记录

首轮分别构建 forwarding、manager、LuCI，均退出 0；完整增量镜像构建耗时 95.994 秒，也退出 0。随后发现 PC 工作区的 `alwayroute-fetch` 含 CRLF，其已打包首行为十六进制 `23212f7573722f62696e2f75636f64650d`（`#!/usr/bin/ucode\r`），目标机不能按该 shebang 直接执行。

扩展检查器正确以 `executable_text_lf_usr/libexec/alwayroute-fetch` 拒绝该镜像。该轮 APK、镜像和 manifest 均移到最终归档目录下的 `pre-fix/`，并记录 `rejection.json`，不可安装或刷入。拒绝镜像 13,435,470 字节，SHA-256 `949769a2795eea1694f2b2c41aeb07bcee4ed9a14484b9089d921afaa7e5c8c1`。编译退出 0 不代表镜像验收通过。

## 最终产物

LF 规范和已授权的订阅 HTTP 例外补丁合并为冻结快照后，已一次同步、定向构建三个候选包，供实机 RPC、订阅和代理 apply 联调。该轮退出 0，耗时 106.68 秒。实机联调后只针对“拒绝检查未应用草稿、UI 结果按已应用版本展示”两个修正重新构建 manager 和 UI，退出 0，耗时 71.093 秒，forwarding 保持不变。表中为这轮修正后的签名包。

直接用现有 host `apk extract` 提取 APK，核对全部 19 个自有载荷与输入一致（含 LuCI minifier 重放）；所有 manager 可执行入口没有 CRLF，fetch 首行为 `#!/usr/bin/ucode`。manager 和 LuCI 的 prepared hash 随输入发生变化，未变化的 forwarding 戳保持不变。

| 最终签名包 | 字节数 | SHA-256 |
| --- | ---: | --- |
| `alwayroute-forwarding-1-r1.apk` | 3395 | `470600a337b84f3c8f5b6fdbc9326468aff48986b2e3732711d209164f4c7037` |
| `alwayroute-manager-1.0.0-r1.apk` | 15228 | `09b5195aee7f33da9c5a8b6fddd038e2dbf8aacbaaf7bfe9e907d89d06b76ad8` |
| `luci-app-alwayroute-0.apk` | 14296 | `cf3931a2658935c433726e7e8fb66a856a4051b24e186bd13c641303c5a61268` |

forwarding 依赖 `libc`、`alwayroute-core`、`firewall4`、`jsonfilter`、`ip-full`、`ubus`；manager 依赖 `libc`、`alwayroute-core`、`alwayroute-forwarding`、`rpcd-mod-ucode`、`ucode`、`ucode-mod-fs`、`ucode-mod-digest`、`uclient-fetch`、`ca-bundle`；UI 依赖 `alwayroute-manager`、`libc`、`luci-base`。

表中为补签后的 APK。OpenWrt 本版本单包 `mkpkg` 默认没有给 APK 本体签名，`package/Makefile` 的 merge-index/index 仅签仓库索引，因此最初候选 APK 被目标机和 host 的严格校验拒绝为 `UNTRUSTED signature`。已只在归档副本上使用现有构建签名密钥执行 `apk adbsign`，随后 host 用对应公钥严格 `apk verify` 三包全部返回 OK，签名后的包重新提取，全部 19 个自有载荷 SHA-256 保持不变。原始未签包保存在 `unsigned-build-output/`。

构建公钥、基线固件嵌入公钥与目标机已有 `/etc/apk/keys/public-key.pem` 相同，PEM SHA-256 为 `c3d447f965bf14729cf825ffc3218fdf0200b69c07d833668901d96b4b09a0db`，DER SHA-256 为 `680eba4179c4964cedc02598a0419681d9e4362d0072bfab82d2d9bdcc4156e3`。目标机不需要修改信任库，不需要跳过签名校验。签名输入因原本未签，需要 `adbsign --allow-untrusted` 读取；此参数不用于最终 `verify` 或目标机安装。签名过程不输出、不复制私钥。

联调期间仅按变化部署自有源码或重包，接口实机通过后才构建最终镜像。首轮 CRLF 拒绝产物和迁移修正前的镜像均单独隔离，不作为最终交付。

三包由主任务在路由器上严格验签、安装成功；rpcd 重启后等待注册，`capabilities`、`get`、`status` 已通过。修正版还实测未应用草稿的 check 以 `NOT_APPLIED` 拒绝，随后应用 revision 6 成功并确认核心实际加载。真实订阅解析 38 个节点、节点 HTTPS 检查、LAN DNS、三次透明 HTTPS TLS 校验/204、guard 阻断后恢复及 CIDR 阻断/回滚均由主任务实测通过。APK 覆盖安装联调后设备 `/overlay` 可用约 1368 KiB（基线约 1496 KiB），不代表最终 SquashFS 集成镜像的首次启动可用空间。

## 升级迁移修正

主任务完成真实订阅、节点 HTTPS、LAN DNS、透明 HTTPS、guard 阻断与恢复等实机验证后，曾放行完整增量镜像。该轮构建退出 0（86.647 秒），Manager profile 的 243 项检查全部通过，内核 payload、核心 SHA、原 140 个包版本均不变；但随后升级迁移审查发现旧 `99-alwayroute-management` 会在新 ROM 首次运行时无条件把已配置的 LAN uhttpd 监听重新改为 localhost。结构检查通过不能覆盖这一迁移语义缺口，因此该轮产物移入 `pre-migration/`，不作为最终升级交付。

修正提交 `49c8643` 为管理默认值增加 `/etc/alwayroute/management-initialized` 标记：已存在则跳过；首次 UCI 设置成功后才创建 root-only 标记，失败不写标记。主任务已在当前设备核对现有 LAN/SSH/LuCI 配置后显式建立该标记，并确认 `sysupgrade -l` 保留；完成设备配置外置备份。本镜像不嵌入标记、用户配置、订阅节点或设备私钥。

构建端只把该 `99` 文件从独立镜像副本同步至 `source/files/etc/uci-defaults/99-alwayroute-management`，先 dry-run，权限保持 0755，三包输入 SHA 和已签名 APK 全部保持不变。该实际修正导致必要的一次额外增量镜像构建，不进行无改动的重复构建。

最终修正后构建耗时 86.977 秒，守护最后采样构建工作区 10,760,396,631 字节。镜像内管理默认值与已审核的修正源文件逐字节一致，fresh ROM 内没有预置 marker；S95 启动链接存在。最终 244 项检查全部通过，143 个包仅比基线增加三个自有包，原有 140 个包版本未变；内核配置和压缩内核 payload 均与原基线一致，core ELF 和管理公钥 SHA 保持原值，镜像中没有 SSH 主机私钥或用户节点/启用配置。19 个自有载荷、90 个可执行文本全部通过对应哈希、LF 和 shebang 检查。

主任务已将该最终镜像外置到 PC，PC SHA-256 与 Rock 一致；传至路由器 `/tmp/alwayroute-manager-final.bin` 后，设备再次核对 SHA-256 一致，`sysupgrade -T` 返回 0、无警告。主任务在用户明确批准后再核对 SHA、预检和 marker，已发起一次保留配置升级，交接时等待重启。构建线仅负责镜像和预检证据归档，未执行刷写；启动后恢复结果由主任务补充。镜像输入保持 `49c8643`，其后文档提交不进入镜像。

归档位置：`build-host:/srv/alwayroute/artifacts/alwayroute-manager-20261023/`。最终镜像文件名为 `openwrt-ramips-mt7621-xiaomi_mi-router-4a-gigabit-squashfs-sysupgrade.bin`；同目录包含最终签名三包、`SHA256SUMS`、manifest、`resolved.config`、`kernel.config`、`config.buildinfo`、`feeds.buildinfo`、`version.buildinfo`、逐包输入 SHA、`image-inspection.json`、`inspection.log`、`final-build-verification.json`、构建日志及状态。原始基线归档 `/srv/alwayroute/artifacts/alwayroute-eval-20261022/` 保持不变。

## 容量解释

| 容量项 | 精确字节数 | 含义 |
| --- | ---: | --- |
| 最终镜像 | 13,435,470 | 已包含尾部元数据 |
| 当前配方硬上限 | 13,565,952 | 13248 KiB，尚余 130,482 字节 |
| 原厂 OS1 首刷边界 | 13,631,488 | `0xD00000`，本镜像尚余 196,018 字节；首刷路径仍须独立校验 |
| 当前 OpenWrt firmware 分区 | 15,204,352 | `0xE80000`，保留配置升级不能沿用原厂 OS1 的操作流程 |
| 压缩内核 payload 结束位置 | 3,206,221 | SquashFS 起始位置 |
| SquashFS 实际 used | 10,198,384 | XZ、512 KiB 块 |
| 按擦除块对齐的 overlay 起点 | 13,434,880 | 相对 firmware 起点 |
| raw overlay 容量 | 1,769,472 | 1728 KiB / 1.6875 MiB，尚未扣文件系统开销 |

原厂首刷边界与现有 OpenWrt sysupgrade 分区边界分别核算；构建子任务没有执行刷机，随后由主任务执行，结果见下节。raw overlay 只是扣除文件系统开销前的物理空间，不能当作实际可用空间达标证据。基础首启可用 1500 KiB，写入标记后约 1496 KiB，均低于 1.5 MiB；最终升级后实测也未达到该规划值。

## 主任务追加：最终保留配置升级与启动验证

用户针对上述最终 SHA 单独批准后，主任务再核对目标 SHA、marker 和 `sysupgrade -T`，执行一次不带 `-n` 的 `sysupgrade /tmp/alwayroute-manager-final.bin`。没有写 Bootloader、Factory 或 ALL。外置配置备份为 9562 字节，包含网络、无线、SSH/Web、shadow、authorized_keys、主机密钥、管理模型/service 和 marker，11 项必需内容核对通过。

升级关闭会话时 SSH 包装返回 246，日志包含 procd/ubus connection failed；不能把该会话退出码作为最终刷写结果。约 124 秒后以原主机密钥重新连接，新 boot ID 为 `<runtime-id>`；`/rom` 内 marker 修正脚本、S95 启动入口与 manager 模块载荷已确认，证明实际运行的是最终镜像。

- 原 11 项关键配置文件逐一 SHA 与升级前备份一致，双频 AP 自动启用，SSID 保持不变，root 登录及认证后 LuCI 页面返回 200。
- current/lastgood 为 revision 6，38 个节点、1 个订阅、无测试规则；saved/applied 均为 6，核心、selector 与透明转发自动恢复，没有重新保存或手动启动服务。
- 升级后透明 HTTPS 两次证书校验通过并返回 204，耗时 1172/770 ms；沿用已批准的单 IP 临时测试路由，结束后移除。
- 启动后的首轮节点检查未确认、首轮 LAN DNS 超时；没有修改配置或服务，随后 UDP/TCP DNS 分别约 1214/1215 ms 返回 rcode 0，节点检查再测通过（1106 ms）。原因未确定，保留冷启动瞬时失败记录，不宣称没有发生过。
- overlay 在初次连接为 1484 KiB、稍后为 1492 KiB；核心 RSS 一次采样为 29,724 KiB，MemAvailable 为 22,140 KiB。不是原始物理容量达标证据，也不代表持续并发性能。

最终镜像及检查文件已复制到电脑 `artifacts/manager-20261023/`，固件 SHA 与 Rock/目标一致。真实手机浏览器使用、物理断开 Rock、UDP 代理及 200 Mbps/持续负载仍需按各自范围验收；不把本轮自动恢复成功标成全部 A1–A9 完成。
