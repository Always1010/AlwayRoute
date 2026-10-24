# 外接分支后端

适用 `feat/external-proxy`。本轮交付源码与隔离测试，尚未构建安装到路由器，也没有经过真实内核或终端联合验收。最小配置与双方责任见 [external v1 契约](../contracts/external-v1.md)。LuCI 开关和最终镜像精简属于后续工作。

## 配置、应用与状态

通过现有登录认证与 rpcd ACL 调用：

| 方法 | 参数与行为 |
| --- | --- |
| `external_get` | 返回独立外部配置和缓存状态，不读取旧节点模型 |
| `external_save` | `{expectedRevision, config}`；校验并递增保存版本，不修改网络 |
| `external_apply` | `{expectedRevision, peer}`；进入后台 job；保存配置的 `enabled:false` 转为独立关闭 |
| `external_status` | 有界检查自有转发、专用 DNS 进程与 UDP/TCP 监听；外部观察过期显示 unknown/degraded |
| `external_disable` | 无参数；后台关闭，不要求当前配置可读、对端在线或旧节点有效 |

应用与关闭沿用 `job_status`，按 job id 等待终态，再重新读取外部状态。`external_get/save/apply/disable` 需要管理写权限；只有 `external_status` 开放给现有只读管理权限。新增方法尚未接入 LuCI 页面。

`peer` 由操作者在现场检查后填写，包含目标 gateway、路由器 revision、网关 generation、当前路由器时钟下的 observedAt，以及核心、接管、DNS、来源保留和经路由器出站/回程的明确确认。观察最多 30 秒，应用前后都复核；标记为 operator，不能当作已经实现跨设备自动探测。不要从合成测试复制 true 值去绕过现场检查。

`phase:active` 表示本地应用已确认，不代表节点、所有 DNS 业务或终端出口已经通过。`endToEnd` 与 `baseConnectivity` 保持 `unverified`。关闭的 disabled 仅确认自有接管、专用 DNS 与本机核心已清理；真实普通直连仍需单终端验收。

## 持久化与生命周期

`/etc/alwayroute/` 中的 `external-config.json` 保存草稿，`external-intent.json` 保存应用意图，`external-lastgood.json` 保存确认配置，`external-journal.json` 是应用/提交恢复记录，`external-mode.json` 阻止旧核心路径重新启动。状态、运行配置、DNS 配置和资源归属仅存于 `/tmp/alwayroute/`。目录 root 0700，文件 root 0600；危险权限和符号链接拒绝使用，不自动修复。

旧 Rule/Global/Direct 不自动迁移为外部启用。首次外部应用要求本机代理已显式停止。外部模式的旧节点应用、检测和核心启动会被拒绝，capabilities 如实关闭这些能力；包安装依赖暂时保留，最终镜像再精简。

应用顺序为：预检 → 持久 journal → guard → 专用 DNS → 外部路由/nft → 本地确认 → committed journal → 元数据提交与清理。committed 是提交点，后续元数据错误不会把已提交目标当作未提交回滚。旧状态开启而应用失败时恢复原来源阻断，重新观察后显式应用。链路、来源、LAN 前缀或 DNS 监听端口变化必须先关闭旧范围。

独立维护入口：

```sh
/usr/libexec/alwayroute-external status
/usr/libexec/alwayroute-external disable
/usr/libexec/alwayroute-external reconcile
```

这些入口通过同一个 manager 锁；已有事务持锁时返回 BUSY，不能并发改网络。`/etc/init.d/alwayroute stop` 在外部模式调用独立关闭；不递归获取相同 procd 服务锁。外部 restart、reload、接口和 firewall 事件按持久意图恢复 guard，不复用旧对端观察自动激活。关闭后重启不拉起本机代理。中断与事件恢复仍须在最终镜像上验收，包括开机阶段的实际规则建立时序。

专用 DNS 由 `alwayroute-external-dns` 单独监管，只绑定配置的路由器地址和专用端口。选中终端的 UDP/TCP 53 才被转交；本地域和无点名称交给原基础 DNS，公网交给外部 DNS，不写全局 DHCP/DNS UCI。停止会清理自有解析进程，现有 conntrack 不做全局清空。

## 资源与验证边界

网络适配器仅拥有 `inet alwayroute_external`、路由表 20232、优先级 10232 与高字节 mark 0x42；创建前检查冲突、内部转发与 offload，退出只按完整表快照和精确路由归属清理。静态 MAC 仍需现场核验；本实现处理经路由器 L3 的流量，不建立桥 ACL，不改变 ARP 或 sysctl。

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
