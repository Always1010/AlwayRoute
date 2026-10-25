# 可选 OpenWrt 外接适配部署

AlwayRoute 是 Coproxy 可选的路由器适配实现。Coproxy 可独立部署；满足交付、来源保留、回程与故障策略能力的原厂或其他路由器，不因没有 AlwayRoute、AR RPC 或本文的 DNS 预检而被排除。本文只说明选择 AlwayRoute 后的 OpenWrt 包与操作条件，不要求所有 Coproxy 用户安装 AlwayRoute 或刷 OpenWrt。

**当前支持显式接管整个接入 LAN，并保留旧单终端配置兼容。** 整个 LAN 使用 `clientMode:lan`、精确接口网络 `clientCIDR` 和空 `clients`；普通设备加入该 LAN / Wi-Fi 后自动纳入来源范围。旧配置缺省仍是单终端，必须先关闭旧接管再切换，空终端列表不会自动扩大范围。受管 IPv4 TCP/UDP 和 DNS 需要验收，公网 IPv6 阻断；路由器本机、外部网关与范围外接口保留基础网络。网关完成代理核心与策略，路由器仅管理来源交付、专用 DNS、阻断和独立关闭。

## 包选择与能力

新纯外接部署选择一组互斥包：

| 包 | 职责 | 主要运行依赖 |
| --- | --- | --- |
| `alwayroute-external-forwarding` | 复用现有外接 nft/策略路由适配器，核对资源归属 | firewall4/nft、ip-full、ucode/fs |
| `alwayroute-external-manager` | 外接模型与事务、后台 job、DNS 预检、专用 DNS 服务和 init | 外接 forwarding、rpcd/ucode、ucode/fs、ubus、dnsmasq、BusyBox nslookup |
| `luci-app-alwayroute-external` | 复用外接页面、样式、菜单与登录认证 | luci-base、外接 manager |

外接包不依赖或安装 sing-box、国内规则 `.srs`、策略目录、订阅下载器、patched uclient/libuclient、digest、本机核心 wrapper 或订阅 cron。基础固件可能因自己的其他功能包含其中某些包，这不构成外接包依赖。原 `alwayroute-core` / `alwayroute-forwarding` / `alwayroute-manager` / `luci-app-alwayroute` 仍作为本机模式包保留；不能与冲突的纯外接包混装。

脚本资源为 `all`，仍须匹配目标 OpenWrt 的包管理器、用户空间 ABI、内核模块、LuCI/rpcd/procd 与签名策略。支持标准 OpenWrt 包系统的既有源码树或 SDK，可构建本文三包；不据此宣称所有版本或架构已实测。现有完整固件 CI 仍走原本机核心配方，没有被改为纯外接整机矩阵。

内核须支持 nft/FIB、inet DNAT、IPv4 策略路由与相应模块；LAN L3 接口必须直接到达网关及受管终端，整个 LAN CIDR 必须与接口实际前缀和网关接管来源完全一致。活动 `flow add` offload 被拒绝，未知厂商加速、多 LAN/VLAN 需另验。基础 LAN/WAN、DNS 和独立管理通道应先正常。nslookup 必须实际支持 `-port=`；包选择会要求相应 BusyBox 功能，不能只检查命令名存在。没有本机 TProxy 核心依赖。

原厂系统只有在用户选择本 AlwayRoute/OpenWrt 实现且缺少其运行环境时，才需要另行评估匹配硬件的 OpenWrt 安装和恢复方式；这里没有跨型号刷机命令。已有设备镜像只能用于对应精确硬件，不可拿来替代其他设备的能力验证。

## 通用组件构建

在已有兼容 Linux OpenWrt 树或 SDK 中操作，不安装本机工具、不清缓存。先从本仓库独立工作副本同步包源码，复用[源码同步工具](../firmware/tools/sync-packages.py)的预览和哈希确认：

```sh
AR_ENV=/absolute/private/build-environment.json
python3 firmware/tools/sync-packages.py --env "$AR_ENV" \
  --package alwayroute-external-manager alwayroute-external-forwarding luci-app-alwayroute-external \
  --plan "$PWD/.local/runs/external-package-sync.json"
# 审阅成功预览后，用相同参数和 --apply 同步
```

工具会明确列出额外共享源码目录：原 manager、forwarding 和 LuCI 目录只作为构建源提供文件，不代表选择或安装旧运行包。没有核心输入、Go 工具链、规则编译或 downloader 补丁要求。每个外接包 `payload.json` 是安装文件白名单；生成脚本只复制列明文件，拒绝链接、目录逃逸和 `.local/`。

保留已有目标/SDK 配置，审阅合并 `firmware/openwrt/external.config` 的包选择，运行该树的 `make defconfig` 并核对结果。片段不选设备、不改变分区或无线配置。新构建入口仅预览，显式 `--apply` 后才增量编译三包；不写 `.config`、不全树构建、不刷机：

```sh
OPENWRT_TREE=/absolute/path/to/existing-compatible-tree
python3 firmware/tools/build-external.py --tree "$OPENWRT_TREE"
python3 firmware/tools/build-external.py --tree "$OPENWRT_TREE" --jobs 2 --apply \
  --output "$PWD/.local/reports/external-package-build.json"
# 已构建时仅复查
python3 firmware/tools/build-external.py --tree "$OPENWRT_TREE" --inspect
```

入口核对源码哈希、三包选择、旧包未选、nslookup 特性，并只运行 `package/<外接包>/compile`。之后验证生成 payload 的精确白名单、内容与模式、依赖元数据及 APK/IPK 产物摘要。报告不会创建通用包仓库，也不等于包签名、内核或终端验收。不得将 APK 当成旧 opkg/IPK 或跨 ABI 混装依赖。现有完整镜像监督器/发布 ZIP 工具仍是其设备和本机核心范围，不能拿来声称已生成通用纯外接固件。

## 初装、迁移与维护

交付批次需附源码提交、OpenWrt/feeds 身份、目标 ABI、准确三包文件与 SHA-256、可信签名来源、空间和加载检查，以及针对目标包管理器核对过的安装/升级/删除命令。使用现有暂存工具逐件选择和核验产物，不整体同步源码或 `.local/`；暂存不代表安装。包数据库管理的文件不通过手工覆盖冒充版本升级。

全新纯外接包只初始化 root:0700 私有目录，无旧模型也能读取外接配置/状态、保存和关闭。init 始终注册外接恢复 worker，不依靠 external-mode 文件选择后端。需要开机自动恢复时，显式启用并启动该服务：

```sh
/etc/init.d/alwayroute enable
/etc/init.d/alwayroute start
/etc/init.d/alwayroute enabled
```

服务自启与外接交付的持久意图分别管理。`enable` 只设置开机启动，`start` 只启动恢复 worker；缺少开启意图时保持关闭，不会因安装、启动服务或保存开启草稿而接管流量。首次开启仍须核验并应用已保存配置，成功应用后保存开启意图及 lastgood 确认配置。正常系统 shutdown 保留该意图和确认配置，并保留来源阻断直到基础网络停止。

启动、restart、reload、网络/接口及 firewall 事件由单个 procd worker 合并处理，与页面/RPC 共用 manager 锁。已有开启意图时先确保来源阻断，再重新核验 lastgood 或 journal 中应恢复的确认配置；网关 UDP DNS、逻辑 LAN 范围、地址及邻居 MAC 检查通过后自动恢复。新保存的草稿不会被自动应用，也不复用旧观察；依赖未就绪或锁忙时持续退避重试，间隔最多 30 秒。`phase:waiting` 表示已确认来源防护后等待恢复，无法确认防护时报 fault；查看 `recovery` 中的错误、尝试次数及下次时间，不能把等待或 DNS 成功当作端到端通过。

开机早期保护依赖随包安装的 fw4 `ruleset-pre` include、默认启用的 `auto_includes=1`，以及由 fw4 在基础网络转发前加载规则。首次部署应确认该 include 出现在实际 `fw4 print` 中，并在目标系统完成实际 nft 规则检查。持久 guard 不等待 LAN 地址出现；fw4 首次加载和 reload 会在同一规则事务中重建它，恢复确认后再清空早期专有表规则。关闭自动 include、绕过 fw4 或提前启用基础转发时，不能保证早期保护；启动服务本身不能替代这些前提。软重启恢复成功也不能代替断电冷启动及实际流量窗口测量。

从本机模式迁移时，先用**旧包仍在时**的停止入口清理旧核心、nft、路由与 owner，再替换互斥包。新纯外接入口不会调用缺失的旧工具或删除旧服务，遇到旧模式的 table、优先级、路由或 owner 残留会拒绝开启/拒绝把关闭报告为成功，需用旧模式工具处理。保留旧节点凭据和外接配置，不复制到交付批次；未知权限或链接不自动修复。

安装或升级后按目标说明加载 rpcd/LuCI 并核对认证 RPC 与实际载荷。纯外接 ACL 只读开放 capabilities/job_status/external_status，配置及所有写操作仍要求现有管理写权限。网页不会展示本机切换操作或读取旧节点；本机包仍保留其原入口。

## 配置与验收

链路、来源、MAC、端口与本地域按角色核验，字段示例见 [external v1](../contracts/external-v1.md)。Coproxy 为网关时，路由器 `gatewayPort` 应与其受限网关 DNS 入口一致，路由器与网关分别核对自己的 L3 接口、地址与 MAC；两台主机的路由表编号/mark 不要求相同。三方同链路可达、保留真实来源和经过路由器回程是当前适配器条件，不增加端间 SNAT 掩盖问题。

登录 LuCI，新建空配置默认选择“全部接入设备（整个 LAN）”；旧配置会明确显示仅一台指定终端，切换前须使用页面顶部独立关闭。核验 LAN 网络与网关来源一致，填写并保存开启草稿，再应用已保存版本。日常应用以新的 3 秒有界 UDP DNS 查询预检，不填写人工 generation/六项确认；它只证明 UDP DNS 可达，不证明核心、接管、来源、出站/回程或端到端出口。保存只更新版本，待同一 job id 终态后重新核对本地状态。RPC 和页面细节见[外接后端](external-proxy.md)。

独立关闭无需网关在线、peer、缓存或配置可读。`external_disable` 或 `/etc/init.d/alwayroute stop` 会持久关闭交付、取消在途恢复并清理自有资源；后续事件或重启不会重新开启。关闭遇到 BUSY 或部分清理失败时检查后台 job、错误与残留，重试到清理确认成功，不能仅因命令已发出就视为完成。需要重新开启时仍须显式应用已保存配置。

维护时先关闭交付，确认后台 job 与自有资源清理并实测普通直连，再升级/卸载包；需要停用服务自启时，也在完成业务关闭后执行 init 的 `disable`。`/etc/init.d/alwayroute disable` 只取消开机启动，不会代替外接关闭或移除持久 guard；只取消自启而保留开启意图，可能导致下次开机保持阻断但没有 worker 自动恢复。不要使用全局 autoremove/purge 或递归删除清理未知资料；具体 conffiles 保留行为由目标包管理器和批次说明明确。两端分别管理自己的服务和资料，一端卸载不会自动操作另一端。

```sh
/usr/libexec/alwayroute-external status
/usr/libexec/alwayroute-external disable
```

同一逻辑 LAN 桥内换物理端口时，只要桥接口、网段、路由器地址及网关地址/MAC 保持一致，恢复仍按该逻辑接口和确认范围处理，不绑定某个物理口。网关应采用稳定 MAC 和 DHCP 保留或等效地址配置。换到其他桥、VLAN、WAN，或改变网关身份、LAN 前缀及 DNS 监听参数时，须先关闭原交付，重新核验并保存、应用新配置；不能把其他口或网段当作同一 LAN 自动接管。

固定包集、核心及明确来源范围；整个 LAN 至少以两台并发终端和后续 DHCP 新终端/地址变化验收，分别检查 IPv4 TCP/UDP、UDP/TCP DNS、LAN 名称/管理 HTTPS、来源保留、WAN 出口、回程、防循环、IPv6 边界和未受管终端。验证核心/DNS 故障阻断、网关仍停止时路由器独立关闭、重复开关与新连接。分别验证开启意图下的软重启与 firewall reload 自动恢复、关闭后重启保持关闭，以及实际断线/同 LAN 换口恢复；断电冷启动、长时间负载和新增 ABI 仍须另验。`active`、DNS 可达、包构建和一次网页成功各有自己的证据边界；端到端仍为 `unverified`。
