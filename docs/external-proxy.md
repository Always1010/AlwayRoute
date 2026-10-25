# 外接分支后端

新部署先阅读[OpenWrt 外接模式部署](external-deployment.md)，核对匹配固件/包集、依赖、两端参数及整个 LAN / 兼容单终端的来源边界，再进入本文的已安装后操作。

适用 `feat/external-proxy`。包含后端、LuCI 管理源码与隔离测试；各部署仍须实测来源、回程与真实终端出口。最小配置与双方责任见 [external v1 契约](../contracts/external-v1.md)。纯外接组件包与构建入口见部署说明；完整纯外接固件镜像仍需匹配设备配方另验。

## 配置、应用与状态

通过现有登录认证与 rpcd ACL 调用：

| 方法 | 参数与行为 |
| --- | --- |
| `external_get` | 返回独立外部配置和缓存状态，不读取旧节点模型 |
| `external_save` | `{expectedRevision, config}`；校验并递增保存版本，不修改网络 |
| `external_apply` | `{expectedRevision, peer?}`；日常只需版本，进入后台 job；保存配置的 `enabled:false` 转为独立关闭 |
| `external_status` | 有界检查自有转发、专用 DNS 进程与 UDP/TCP 监听；DNS 应用模式按 60 秒间隔缓存网关 UDP DNS 观察 |
| `external_disable` | 无参数；后台关闭，不要求当前配置可读、对端在线或旧节点有效 |

应用与关闭沿用 `job_status`，按 job id 等待终态，再重新读取外部状态。`external_get/save/apply/disable` 需要管理写权限；只有 `external_status` 开放给现有只读管理权限。

普通 `external_apply` 不提交 `peer`（rpcd 默认空对象也视为未提交）。后端先用现有 `/usr/libexec/alwayroute-timeout 3` 运行 `nslookup -port=<gatewayPort> example.com <gatewayAddress>`；地址和端口只来自已严格校验的配置，固定查询名，不插入任意命令片段。每次应用强制新查，失败时不进入转发预备或修改网络；原已开启则继续保留既有故障阻断路径。不安装依赖、不控制网关。目标须已有支持指定端口的 nslookup，缺少命令同样会拒绝开启。

成功只说明网关当时回答了一次 UDP DNS 查询。`applicationMethod:gateway-dns`、`gatewayDns.status:reachable`、本地 `phase:active` 分开报告，不能据此确认 TCP DNS、核心、接管、原始来源、实际 WAN 出口或回程；`peer` 保持 unknown，不伪造 generation 或六项 true。`endToEnd` 与 `baseConnectivity` 保持 `unverified`。关闭的 disabled 仅确认自有接管、专用 DNS 与本机核心已清理，真实普通直连仍需受管终端验收。

`external_status` 对 DNS 应用模式的已应用配置进行有界观察，`gatewayDns` 展示 UDP 范围、`observedAt`、观察年龄 `ageSeconds` 与 `cacheSeconds:60`。观察结果只在 `/tmp` 的独立私有缓存保存，每 60 秒至多发起一次新观察并刷新缓存，5 秒页面轮询不重复发查询或写事务状态；`external_get` 不查询。缓存到期时重新查询；失败为 unreachable，锁忙或不能取新观察则为 unknown，均显示 degraded，保留开启意图和既有转发。DNS 应用模式不因不存在人工观察而在 30 秒后无条件降级。缓存损坏不成为应用或关闭前提，未知文件权限/链接不会自动修复。

兼容 API 可显式提供非空 `peer`，由操作者提交实测的目标 gateway、revision、generation、路由器时钟 observedAt 与六项确认，应用前后不超过 30 秒，标记为 operator。该兼容路径仍会在观察过期时显示 unknown/degraded。网页正常应用不再提供或要求人工表；合成测试值不能代替现场证据。

## LuCI 操作

登录后进入“服务 → AlwayRoute”（`/cgi-bin/luci/admin/services/alwayroute`）。本分支的原有入口加载独立外接页面，保留旧本机节点页面源码，但不在此入口展示节点、订阅和 Rule/Global/Direct 控件。

1. 从旧本机包切换时，在替换包之前用“首次从本机代理切换”显式停止当前代理服务并确认旧资源清理。纯外接包的全新安装不需要旧核心或旧配置，也不显示此区。
2. 新配置选择“全部接入设备（整个 LAN）”，填写链路、精确 LAN CIDR 与 DNS；已有指定终端配置须先关闭后切换，选择“保存为开启”，保存草稿。页面分别展示已保存开关/版本、持久期望和实际应用；保存成功只表示草稿递增版本，不改变网络。可保存关闭草稿，但立即关闭应使用独立关闭按钮。
3. 选择“应用已保存版本”。页面只提交版本，不要求填写 generation 或勾选人工确认。后端以网关 UDP DNS 新查询预检，再应用本地来源防护、专用 DNS 与转发；保存了关闭草稿时，此应用走独立关闭。
4. 应用/关闭等待匹配 job id 的后台终态，然后重新读取实际状态。失败或结果未确认时暂停常规写操作，保留输入，使用重新读取核对状态。刷新页面发现运行中任务时可重新读取接回等待。DNS 失败/未知、人工观察过期和读取失败分别展示；轮询只更新状态区，不覆盖编辑中的表单。
5. 确认“本地已应用”和“网关 UDP DNS 可达”后，仍需实测终端出口、来源保留、出站与回程。页面始终标注端到端未验证，不把 DNS 成功提升为核心或整条路径通过。
6. “关闭外部代理，恢复普通直连”是独立恢复入口，即使外部配置不可读仍可调用，也不要求对端在线、人工观察或缓存有效。关闭失败可重试；`disabled` 只确认本地自有资源清理，真实终端普通直连仍须验收。只读账户只查询状态与后台任务，不读取管理配置或提供可写操作。

前端关键逻辑可使用已有 Node 执行 `node --test tests/ui/ui.test.cjs`；RPC/ACL/入口契约执行 `python3 tests/integration/check-contract.py`。合成 DOM 和 RPC 测试不等于固定 LuCI 实机渲染、认证、内核或端到端验收。

## 持久化与生命周期

`/etc/alwayroute/` 中的 `external-config.json` 保存草稿，`external-intent.json` 保存应用意图，`external-lastgood.json` 保存确认配置，`external-journal.json` 是应用/提交恢复记录，`external-mode.json` 阻止旧核心路径重新启动。`external-stop-request.json` 是独立持久取消标记，显式应用仅确认其获取锁前捕获的请求代次；更新的关闭请求始终优先。`external-enable-token.json` 记录已确认代次，不删除关闭标记，避免比较与删除之间覆盖新的关闭请求。`external-boot/guard.nft` 是已进入事务的来源范围对应的持久早期阻断规则；其他状态、运行配置、DNS 配置和资源归属仅存于 `/tmp/alwayroute/`。目录 root 0700，文件 root 0600；危险权限和符号链接拒绝使用，不自动修复。

安装/升级的既有 uci-defaults 流程先调用 `alwayroute-storage-init`：缺失的配置目录创建为 root 0700；仅将 root 所有的真实 `/etc/alwayroute/` 目录从已知旧版精确 0755 收紧为 0700，已有 0700 保持不变。链接、非 root 所有、可被组或其他用户写入及其他未知权限均拒绝，不修复未知资源。该迁移仅使用 ucode/fs，不读取或复制节点凭据，不启动代理核心；运行期继续严格要求私有目录。

旧 Rule/Global/Direct 不自动迁移为外部启用。从本机模式迁移前要求旧代理与旧转发已显式清理。外部模式的旧节点应用、检测和核心启动会被拒绝，capabilities 如实关闭这些能力；原本机包保留其依赖，纯外接包不安装本机核心、规则和下载器。纯外接 dispatcher 从首次调用即确定后端，不依赖模式文件，不加载旧模型；RPC/ACL 仅保留外接管理与后台状态。

应用顺序为：预检 → 持久 journal → guard → 专用 DNS → 外部路由/nft → 本地确认 → committed journal → 元数据提交与清理。committed 是提交点，后续元数据错误不会把已提交目标当作未提交回滚。旧状态开启而应用失败时恢复原来源阻断，重新预检后显式应用。链路、来源、LAN 前缀或 DNS 监听端口变化必须先关闭旧范围。

独立维护入口：

```sh
/usr/libexec/alwayroute-external status
/usr/libexec/alwayroute-external disable
/usr/libexec/alwayroute-external reconcile
```

这些入口通过同一个 manager 锁；已有事务持锁时返回 BUSY，不能并发改网络。`/etc/init.d/alwayroute stop` 在外部模式调用独立关闭；不递归获取相同 procd 服务锁。纯外接包由 procd 监管单个恢复 worker；restart、reload、接口和 firewall 事件合并为待检查标记。worker 在相同 manager 锁下仅恢复 journal/lastgood 的确认配置，重新核验网关 UDP DNS、逻辑 LAN 范围及网关 MAC 后自动恢复；健康事件只检查，不重复重装。网关或链路未就绪持续按 1、2、4、8、16、30 秒退避，后续间隔最多 30 秒，无固定重试次数。BUSY 也保留事件并重试。新保存的草稿不会被自动应用。显式关闭在等待锁前先保存独立关闭请求，在途恢复激活前后复查，避免稍后的事件重新开启。正常 shutdown 暂停 worker、保留持久开启意图和来源阻断；显式 stop 才关闭意图。关闭后重启不拉起本机代理。中断与事件恢复仍须在最终镜像上验收，包括开机阶段的实际规则建立时序。

纯外接包随包安装 `/usr/share/nftables.d/ruleset-pre/30-alwayroute-external.nft`，通过 fw4 默认自动 include 机制，在首次规则事务及每次 reload 中原子重建持久早期 guard；不等待 LAN 地址出现。正常活动恢复并确认本地资源后，仅清空早期专有表的规则；规则文件仍保留，下一次 fw4 reload 会重新阻断并触发恢复。关闭先移除持久文件，再清专有表，不改其他防火墙 include、基础 DNS 或全局路由。需要保持 fw4 的 `auto_includes=1`，首次部署应确认该 include 进入 `fw4 print`、通过实际 `nft -c`；若系统关闭自动 include 或手动绕过 fw4/提前开启转发，无法保证早期保护。整机冷启动的无直通窗口仍须在最终镜像与物理终端上测量，静态顺序不能替代该验收。

恢复状态 `waiting` 表示来源阻断并等待自动恢复；`recovery` 提供尝试次数、最近/下次时间、退避间隔和错误码，BUSY 等 worker 错误也显示。`active` 仍只说明本地应用与有界 UDP DNS 观察，并非核心、出口、回程或真实终端端到端验证。

专用 DNS 由 `alwayroute-external-dns` 单独监管，只绑定配置的路由器地址和专用端口。受管 LAN 或指定终端的 UDP/TCP 53 才被转交；本地域和无点名称交给原基础 DNS，公网交给外部 DNS，不写全局 DHCP/DNS UCI。停止会清理自有解析进程，现有 conntrack 不做全局清空。

## 资源与验证边界

网络适配器拥有 `inet alwayroute_external_boot`（专有注释校验）和 `inet alwayroute_external`、路由表 20232、优先级 10232 与高字节 mark 0x42；创建前检查冲突、内部转发与 offload，退出只按完整表快照和精确路由归属清理。激活要求邻居表确认网关 MAC 与配置一致，网关采用稳定 MAC 和 DHCP 保留；同一逻辑 LAN 桥内换物理端口不改变规则接口，换到其他 VLAN/桥或改变网关身份须先关闭并重新确认。本实现处理经路由器 L3 的流量，不建立桥 ACL，不改变 ARP 或 sysctl。

如果进程在 nft 提交成功、安装快照写入之前中断，或外部程序修改了自有表，无法证明归属时会保守拒删，保留 owner/journal 并报残留，需要操作者审阅修复后重试。此类情况不能报告自动恢复或关闭成功。

配置与事务的独立检查：

```sh
python3 tests/manager/run-external-tests.py /path/to/ucode -
python3 tests/manager/check-imports.py /path/to/ucode
python3 tests/manager/run-tests.py /path/to/ucode -
python3 tests/integration/external-forwarding-test.py
python3 tests/manager/init-service-test.py
python3 tests/integration/check-contract.py
```

测试用合成输入、内存适配器和隔离命令替身，不能代替 nft 内核验证、同 LAN 回程、真实来源、DNS、IPv6、故障与最终镜像验收。FIB 查询与 inet DNAT 形式对照 [nftables 路由匹配](https://wiki.nftables.org/wiki-nftables/index.php/Matching_routing_information)和 [NAT 说明](https://wiki.nftables.org/wiki-nftables/index.php/Performing_Network_Address_Translation_(NAT))，具体可用性仍以目标内核检查为准。
