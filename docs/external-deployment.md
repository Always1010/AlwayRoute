# OpenWrt 外接模式部署

本流程按角色、系统能力及匹配的固件或包集部署。接入路由器负责终端选择、交付、专用 DNS、故障阻断和独立关闭；外接 Linux 网关负责 Mihomo 接管、分流、节点订阅和 MetaCubeXD 管理。Linux 侧按 Coproxy 仓库的 `docs/deployment.md` 与 `docs/management-https.md` 安装，两端分别管理自己的资源，不需要固定路由器或外接主机型号。

**当前受管范围强制限定为一台明确 IPv4 地址和 MAC 的终端。** 开启时配置必须恰好有一个 `clients` 项，模型拒绝第二项；这不是“先试一台、随后可直接扩大”的建议。IPv4 TCP/UDP 与 DNS 需要逐项验收，受管公网 IPv6 阻断。多终端、整个 LAN 或 CIDR 来源接管需要同时扩展并验证两端，不能只修改配置放宽范围。

## 1. 选择交付路线与系统边界

| 路线 | 当前可用入口 | 进入下一步的条件 |
| --- | --- | --- |
| 已发布的完整固件 | [发布说明](github-build.md)与对应设备的安装说明 | 当前公开固件发布配方仅覆盖设备列表中的既有目标。核对产物包含外接功能的源码提交，旧 Release 不因分支新增功能就自动包含新页面或后端。镜像型号、硬件修订和格式必须完全匹配 |
| 匹配 OpenWrt 的组件包集 | 本仓库四个包的源码、固定构建输入与定向构建流程 | 尚未提供经通用初装/升级验收的跨设备包仓库或一组通用已发布 APK。须由交付者提供与目标固件匹配、经过校验的具体批次及安装说明 |
| 自行构建完整固件 | [固件构建](../firmware/README.md)、[设备移植](device-porting.md) | 使用已登记且匹配目标的设备配方。新目标需补齐适配与镜像验证；不能套用已有设备的镜像、分区限制或刷写命令 |

从原厂系统开始时，先按精确硬件的 OpenWrt 安装及恢复方法得到可独立管理的基础系统，再进入本流程。封闭固件缺少下列能力时，不属于当前安装支持范围。这里没有跨型号通用刷机命令；[现有刷机入口](devices/xiaomi-4a-flashing.md)继续只适用于其明确设备范围。

目标路由器应已具备稳定 LAN/WAN、基础 DNS、SSH 或 LuCI 管理、可写空间和独立于代理的管理通道。安装批次应核对以下能力，而不是只检查 CPU 名称：

| 层次 | 要求与限制 |
| --- | --- |
| OpenWrt 用户空间 | 匹配的 LuCI、rpcd/ucode、ubus、procd、ucode fs/digest、jsonfilter、ip-full、firewall4/nftables、dnsmasq 和 CA 证书包 |
| 内核及网络 | 所选接口可直接到达网关和终端；网关路由不能再经中间网关。nft/FIB/NAT、IPv4 策略路由及依赖内核模块须可用，活动 `flow add` offload 会被拒绝；未知厂商加速与多 LAN/VLAN 须另验 |
| DNS 预检 | 已有 nslookup 必须支持 `-port=<端口>`，并有包内 `alwayroute-timeout`。只有工具名存在不够，交付者须在目标基础镜像确认参数能力；当前预检不安装替代工具 |
| 包管理器/ABI | 固定源码基线为 OpenWrt 25.12.6，现有包与验证记录采用 APK。按实际目标的包格式、库 ABI、内核 ABI 和签名信任配套；不把 APK 当作旧版 opkg/IPK，也不跨版本混装库或 kmod |
| 架构 | manager、forwarding 和 LuCI 的脚本/资源为 `all`，但现依赖仍包含架构相关核心与 kmod。独立核心构建参数提供 `mipsle-softfloat`、`arm64`、`amd64`；不代表对应路由器镜像或所有 OpenWrt 架构已验收 |

现有依赖保持不变：`luci-app-alwayroute` 依赖 manager；manager 依赖 core、forwarding、rpcd-mod-ucode、ucode/fs/digest、uclient-fetch、ca-bundle、dnsmasq；forwarding 依赖 core、firewall4、jsonfilter、ip-full、ubus、ucode/fs；core 还依赖 ca-bundle、kmod-nft-tproxy、ip-full。外接模式不会启动本机核心，但当前包集仍需满足这些依赖。纯外接精简依赖属于后续工作。

manager 还要求 `uclient-fetch` 与 ABI 对应的 `libuclient` 至少为 `2026.06.07~daad21fa-r4`，来自依次应用的 `020-uclient-header-limits.patch`、`021-uclient-https-only.patch`、`022-uclient-private-header.patch`。这些补丁位于 `firmware/openwrt/patches/`，针对固定上游配方；其他 OpenWrt 版本须另行适配和核验，不能只把版本号改成满足依赖。完整配方中的设备容量补丁不因此成为所有型号的要求；CI 的 host digest 补丁用于构建检查，也不能当作目标端通用补丁照搬。

## 2. 生成并交付可审阅批次

已有匹配且包含外接功能的发布批次可直接进入下一节。自行构建在已有 Linux 构建环境执行，前置软件、工具链、固定源码/归档与缓存按[上游来源](upstream-sources.md)、[环境字段](operations/environments.md)和[固件说明](../firmware/README.md)准备；这些步骤不因阅读文档而获得安装本机软件的授权。

下面变量均为角色占位符，在 AlwayRoute 源码根目录设置，不使用个人构建目录作为默认值：

```sh
AR_ENV=/absolute/private/build-environment.json
DEVICE='<已登记且与目标匹配的设备配方ID>'
RUN=/absolute/private/new-build-run
```

`AR_ENV` 选择已核验的 `build.task_root/openwrt_tree/toolchain_root/cache_root/output_root` 及预算。构建脚本在构建主机本地执行，不因为 `--env` 有 SSH 字段就自动跳转执行。源码同步到独立工作副本，不能把整仓库覆盖到 OpenWrt 树；具体命令见[开发流程](development-workflow.md)。

现有参数入口如下。前两条分别只列来源和配方；写 seed、同步包及构建是后续明确操作。包同步预览会在忽略的 `.local/` 中保存哈希计划/临时快照，不构建或连接设备。

```sh
python3 scripts/fetch-sources.py list
python3 firmware/tools/target_profile.py --device "$DEVICE"
python3 firmware/tools/target_profile.py --device "$DEVICE" --seed-output "$RUN/seed.config"

python3 firmware/tools/sync-packages.py --env "$AR_ENV" \
  --package alwayroute-core alwayroute-forwarding alwayroute-manager luci-app-alwayroute \
  --plan "$PWD/.local/runs/external-package-sync.json"
# 核验成功预览且输入/目标未变后，复制选中的包源码到构建树
python3 firmware/tools/sync-packages.py --env "$AR_ENV" \
  --package alwayroute-core alwayroute-forwarding alwayroute-manager luci-app-alwayroute \
  --plan "$PWD/.local/runs/external-package-sync.json" --apply
```

没有目标对应配方时，按[移植流程](device-porting.md)确定新配方；不能填当前已有型号来绕过目标检查。独立 `build-core.py --architecture arm64|amd64` 是核心候选入口，不会生成新设备配方或 APK 安装兼容性证明。

按所选树的固定 feeds、设备 seed 与补丁完成集成并审阅 `make defconfig`；在 `alwayroute-input/` 放匹配架构的核心、`build-info.json`、LICENSE，管理包所需的 `.srs`/manifest/LICENSE 按[规则构建说明](../config/routing/README.md)准备。当前外接包仍需这些构建输入，不可因运行时不用本机规则而省略。已有核心构建和整机监督入口是：

```sh
python3 firmware/tools/build-core.py --env "$AR_ENV" --device "$DEVICE" --output "$RUN/sing-box"
python3 firmware/tools/run-native-build.py --env "$AR_ENV" --device "$DEVICE"
```

第一条会实际编译默认标准核心；复现某个已有优化批次须显式使用其相同选项与 PGO，不能用默认产物冒认。第二条实际监督整树 make 并要求对应新镜像，不是“只构建外接 APK”的开关。组件联调应在匹配构建树按改动定向构建包；已有说明中的 `package/alwayroute-core/compile` 是核心目标，其余包及 downloader 的确切 make 目标由交付者按该树展开的配置核对并记录。本文没有执行构建，也不假定另一棵 SDK/源码树的目标名称或依赖已被验证。

交付者应在批次中明确：源码提交、外接功能范围、OpenWrt/feeds/补丁身份、目标架构及 ABI、四包及所需 downloader/依赖的准确文件名与版本、每件 SHA-256、可信签名来源、容量检查、安装/升级/卸载命令和已执行的检查。当前仓库的发布 ZIP 工具生成既有设备固件，不会自动形成通用 APK 仓库。OpenWrt 单包构建完成也不等于 APK 本体已签名；不得通过关闭签名检查安装候选。

## 3. 传送、安装与加载

先核对目标基础系统身份和网络，再选择这台设备对应的完整固件或组件包集。在目标 root shell 可使用现有基础命令读取系统身份；这是记录目标，不是自动判定任何型号都兼容：

```sh
ubus call system board
```

组件文件可用现有暂存工具逐件选择；它只复制并核验 SHA，不安装包、不刷机、不启停服务：

```sh
ROUTER_ENV=/absolute/private/router-environment.json
PACKAGE_FILE=/absolute/private/reviewed-package.apk
python3 scripts/device.py --env "$ROUTER_ENV" stage "$PACKAGE_FILE"
# 核验计划中的文件、目标与摘要后，才执行暂存
python3 scripts/device.py --env "$ROUTER_ENV" stage "$PACKAGE_FILE" --apply
```

安装前按批次在目标的实际包管理器中核验签名、已安装版本、依赖解析和空间。当前仓库没有通用 APK 安装/卸载包装器，也没有可套用到任意 OpenWrt 的已验命令；**具体包集必须附带针对其包管理器版本核对过的验签、安装、升级及删除参数**，取得前停在批次交付阶段。不可将上述 `stage --apply` 当成安装完成，不把历史包名或旧 opkg 命令照搬到 APK 系统，不逐文件覆盖受包管理器管理的源码来冒充版本安装。

批次须覆盖首次配置目录初始化、包内 uci-defaults 和服务加载。现有 `alwayroute-storage-init` 仅创建缺失的 root:0700 目录，或收紧已知 root:0755 旧目录；未知权限、身份或链接会拒绝。manager 仍安装原有调度入口，不能把整个包描述成只含外接页面。rpcd/LuCI 刷新及会话影响按目标系统的批次说明执行，不能只复制一份 JS 就认定后端已更新。最后核对包数据库、实际载荷和认证 RPC/UI 与该批次对应；失败保留诊断，先处理加载或归属问题，再进入配置。

## 4. 填写两端角色参数并首次启用

先在 Linux 端完成 Coproxy 安装、管理 HTTPS、私有管理员凭据、策略/订阅及实际核心应用；确认网关 DNS 能由路由器访问。网页可达与核心可用分别验证。使用同一份经现场核验的角色记录填写下表，不依据旧 DHCP、历史 MAC 或当前电脑默认路由猜值。

| 含义 | AlwayRoute 字段 | Coproxy 输入或实际身份 |
| --- | --- | --- |
| 路由器局域网地址 | `link.routerAddress` | `runtime.automaticGateway.routerIPv4` |
| Linux 网关地址 | `link.gatewayAddress` | `runtime.automaticGateway.gatewayIPv4` |
| 唯一受管终端 IPv4 | `clients[0].address` | `runtime.automaticGateway.clientIPv4` |
| 终端 MAC | `clients[0].mac` | 该终端在路由器入口的实际单播 MAC；不是 Linux 或路由器 MAC |
| 网关 MAC 方向 | `link.gatewayMac` | Linux 网关入接口的实际 MAC；不填路由器 MAC |
| 路由器 MAC 方向 | 由路由器实际 L3 接口核验 | `runtime.automaticGateway.routerMAC`，Linux guard 所期待的交付方 MAC；不填终端或 Linux MAC |
| 入口接口 | `link.interface`：路由器的实际 L3 接口 | `runtime.automaticGateway.ingressInterface`：Linux 入接口。分别属于两台主机，不要求名称相同 |
| 网关 DNS 端口 | `dns.gatewayPort` | 必须等于 `runtime.automaticGateway.dnsPort` 和 `management.deployment.dnsPort` |
| 路由器专用 DNS 监听 | `dns.listenPort` | 路由器本地空闲非 53 端口，独立于 Linux 端口；不占用基础 DNS |
| 本地域与网页解析 | `dns.localDomains` | 包含实际 LAN 域后缀，使管理域名继续由路由器基础 DNS 解析；HTTPS URL、证书 SAN、反代与 `management.origin` 一致 |

例如可将网关 DNS 统一为合成端口 `15353`、路由器专用监听为 `1053`；两个仓库样本的默认 `gatewayPort/dnsPort` 不应未经核对直接混用。若管理入口为合成的 `gateway.lan`，两端实际 LAN 解析和 `localDomains` 应覆盖 `lan`，证书也须匹配。完整合成配置见[external v1](../contracts/external-v1.md)，全部地址与 MAC 需替换为部署输入。

路由器、网关、终端按当前适配器要求同链路可达；端间不增加 SNAT 掩盖来源或回程问题。Linux bootstrap 独立于受管公网 DNS 转交链，避免循环。路由器的 table/mark 与 Linux 的 table/mark 是各自主机的资源，不是必须填相同的协作参数。额外 `bypass4` 目的例外按最小范围审阅。

登录 LuCI，进入“服务 → AlwayRoute”。先使用“首次从本机代理切换”的停止入口退出本机模式；它不会顺带开启外接。填写参数，保存为开启，再选择“应用已保存版本”，等待同一 job id 终态并重新读取状态。保存只递增草稿，不改变网络。日常应用仅提交保存版本，由后端做新的网关 UDP DNS 查询，不要求用户构造 generation 或人工观察表。详细界面、RPC 与事务行为见[外接后端](external-proxy.md)。

“本地已应用”“网关 UDP DNS 可达”和真实终端联网分别判断。首次 DNS 预检失败保持原状态；已经开启后的故障保留阻断和开启意图，不自动直连。命令行维护在已安装目标可读取状态：

```sh
/usr/libexec/alwayroute-external status
```

## 5. 关闭、升级与卸载

用户关闭使用网页独立关闭按钮；管理员也可在目标执行：

```sh
/usr/libexec/alwayroute-external disable
/usr/libexec/alwayroute-external status
```

关闭不依赖 Linux 在线、旧节点模型或当前外部配置可读。它只撤销可证明归属的自有转发、专用 DNS 与意图，不清空全局防火墙、路由表或 conntrack；出现 BUSY、残留或归属不明时先核对事务与资源，不能仅因命令已发出就认为成功。`disabled` 还需终端实际普通直连验收。Linux 核心停止保留其 guard，不能代替这一步路由器关闭。

升级先等待后台任务达到终态，在路由器完成独立关闭并验证直连，再于维护窗口核对新包集/固件、签名、依赖、空间和持久配置兼容性；按该批次明确命令升级，再核对版本和载荷、重新登录并显式应用。`/etc/alwayroute/` 为包声明的持久 conffiles，包含旧模型凭据及外接配置/意图/journal；保留政策须由具体升级方式确认，不删除后假装初装，不把真实内容复制进包集。完整固件升级还需适用设备的镜像检查与恢复条件，包升级不能替代刷机验证。

卸载前同样先独立关闭、确认后台任务与自有规则/进程已清理并验证直连，再按匹配包管理器及批次说明移除包。当前没有保留数据卸载器，不能承诺任意包管理器默认保留 conffiles；操作者应明确保留资料政策及包管理器的删除选项。不要使用全局 autoremove/purge 或递归删除来清理未知依赖、认证资料、基础 DNS、防火墙和其他项目资源。完整固件中的只读基础包不等于可以原地回到原厂，回退按对应设备流程处理。

Linux 端升级或卸载是另一侧流程：路由器先关闭交付，然后按 Coproxy 当前计划停止核心、核对完整网络回执并显式安全 remove，再运行其部署入口。两端独立服务、反代、证书与持久资料均按各自归属处理，不因一侧卸载而自动清除另一侧。

## 6. 验收与交付结论

固定双方源码/安装版本、核心版本、包集摘要和唯一受管来源，分别验证 IPv4 TCP/UDP、UDP/TCP DNS、LAN 名称与 HTTPS 管理、原始来源、出口/回程、防循环、未受管终端不受影响及受管 IPv6 边界。再验证核心或 DNS 故障时受管公网阻断、核心仍停止时路由器独立关闭可恢复直连，以及重复开关和升级后的实际新连接。重启/断电、长时间负载和新固件组合必须独立记录，不能继承旧批次通过状态。

状态、编译、包签名、nft 检查、DNS 响应和一次网页成功各有自己的证明范围；端到端状态仍按实际终端验收解释。角色方案可跨设备复用，当前验收只覆盖明确记录的组合；新增型号、未支持架构、纯外接精简包和多终端继续分别适配，不承诺任意 OpenWrt/封闭固件均可用。真实参数、访问身份、包操作原始输出及恢复记录保存在被忽略的本地资料中，正式内容只记录必要的脱敏范围。
