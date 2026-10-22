# 管理层集成与容量独立核查

- 日期：2026-10-23（Asia/Shanghai）。
- 范围：仓库及 Rock 构建副本只读核查；没有连接路由器、安装依赖、运行构建或修改远端环境。
- 基线：`docs/requirements.md`、固定 LuCI `75a306df84a020c57a631ef5b4c02ace56d93387`、现有评估镜像 manifest 和源码。
- 本文记录已核实事实和剩余门槛；不代表 A1–A9 已验收。

## 1. 可复用运行时

Rock 构建根目录：`/srv/alwayroute/openwrt-build/source`。
镜像及 manifest 归档：`/srv/alwayroute/artifacts/alwayroute-eval-20261022/`。

| 项目 | manifest／源码实际结果 | 集成含义 |
| --- | --- | --- |
| ucode | `2026.01.16~85922056-r2`，已有 fs、ubus、uci、uloop、digest | 可复用 JSON、文件操作及 SHA256；不额外引入 Python／Node 到设备 |
| ucode struct／YAML | manifest 未包含 struct；没有通用 YAML 解析器 | 不应假定可直接 import struct 或完整解析 Clash YAML |
| JSON | 已有 json-c、jshn、jsonfilter | 无需新增通用 JSON 运行时 |
| rpcd／LuCI | 已有 rpcd-mod-ucode、rpcd-mod-luci、uhttpd-mod-ubus、LuCI session | 复用认证及 RPC；新增对象仍需最小 ACL |
| HTTPS | 已有 uclient-fetch、libustream-mbedtls、ca-bundle | 订阅抓取不依赖 curl，不关闭证书验证 |
| uclient-fetch 参数 | 固定源码支持 `--header`、`--post-data/file`、`--method`、`--body-data/file`、`--timeout`／`-T`、`-O -`、`--no-proxy` | 可访问 loopback core API；下载仍须单独验证大小上限与超时行为 |

`ucode/lib/fs.c` 实现 `open`、`readfile`、`mkdir`、`rename`、文件句柄 `lock`（flock）；
`popen` 接受 shell 命令字符串，不能把未转义的订阅或用户输入拼进命令。
固定 LuCI 的 `modules/luci-base/root/usr/share/rpcd/ucode/luci` 使用
`{args:{...},call:function(request){...}}`，从 `request.args` 取参，最终 `return {luci:methods}`。
`luci-mod-system/.../view/system/startup.js` 展示 `rpc.declare`、`ui.createHandlerFn`、
`ui.addNotification` 和 `L.hasViewPermission()` 的当前版本用法。

Rock 自带 Python 3.12.3、Node v22.23.0、cc；构建树已有 host cmake、pkg-config、json-c 缓存。
首次核查未发现已编译的 host ucode，已有的 ucode ELF 均在 target MIPS 目录。
`package/utils/ucode/Makefile` 已声明 HostBuild，可由构建负责人复用现有构建环境增量执行
`make package/utils/ucode/host/compile V=s`。其默认 host fs／struct 开启，digest／ubus／uci／uloop 关闭；
host 测试不能把这些目标模块当作默认可用。随后构建负责人在已有构建环境编出 host ucode 与 digest，
路径为 `staging_dir/hostpkg/bin/ucode`；本核查线没有执行编译或安装。

## 2. 开源最小复用判断

沿用此前已核实的候选筛选，不重新泛查大型套件。当前实际可复用组合是 LuCI session／rpcd ACL、
ucode 文件及摘要模块、uclient-fetch，以及现有 sing-box Clash API。
Clash API 提供运行中的代理选择、连接与流量信息；它不能替代订阅来源、本地覆盖、稳定标识、
revision 冲突检查、持久模型及失败回退。管理层只补这些需求缺口，不能用运行控制面板替代完整配置管理。

## 3. 容量基线与验收边界

归档 `image-inspection.json` 记录的真实评估镜像：

| 项目 | 字节数 |
| --- | ---: |
| sysupgrade 文件 | 13,435,470 |
| SquashFS bytes_used | 10,169,904 |
| SquashFS 块大小 | 524,288 |
| overlay 起点（相对 firmware 分区） | 13,434,880 |
| 原始 overlay 容量，未扣文件系统开销 | 1,769,472 |
| 1.5 MiB 规划目标 | 1,572,864 |
| 两者算术差额 | 196,608 |

这 196,608 字节还需容纳新增压缩文件引起的镜像增长及文件系统开销。
主 Agent 随后报告首刷及重启成功，设备 `df` 初始可用 1500 KiB、写入验证 marker 后为 1496 KiB；
均低于 1.5 MiB（1536 KiB）规划目标，不能把原始 overlay 容量作为达标证据。
本核查线没有连接设备；设备操作与结果见[首刷审查](2026-10-23-first-flash-review.md)。
已有 `staging_dir/host/bin/mksquashfs4`；最终应以加入实际 manager／UI 文件后的完整镜像重新检查，
不能把源文件大小、整文件 XZ 或压缩包大小直接当作 overlay 变化。容量不满足时保留明确失败条件，不能自行降低标准。

## 4. 已运行的独立检查与发现

- `tests/integration/runtime-api.uc` 已在固定 host ucode 通过：真实 SHA256、非阻塞排他锁及互斥、
  锁释放、0600 文件、write／flush／close／rename、限长 readfile 和受控错误编码。
  测试仅使用自行创建并清理的 `/tmp/alwayroute-runtime-audit-*`，没有调用 manager／服务／设备。
- `python tests/integration/check-contract.py` 已通过：15 个 UI／rpcd 方法匹配，菜单绑定正确，
  凭证读取／导出及修改仅授予 write 权限，没有文件、UCI、无关 ubus 或通配授权。
- 查到并反馈的固定 API 问题：`file.lock('exnb')` 无效（应为 `xn`）；`die(object)` 不保留自定义
  code；ucode 不支持 `throw`／`finally`。实现者已修正锁、错误编码与重抛；最终语法及功能测试另由构建负责人确认。
- 查到并反馈 UI 默认空 SNI／WS Host 被模型拒绝的问题；UI 实现者已改为空值省略。
- 固定 LuCI RPC 默认 20 秒；rpcd 配置为 30 秒。同步订阅 20 秒以及应用／失败恢复可能超过该窗口，
  且同步 ucode 会阻塞 rpcd。最新实现已改后台 job 与 `job_status`，UI 检查 job ID，完成后才刷新配置，
  失败保留本地编辑；不能只加大浏览器 timeout。
- 后台 worker 的锁描述符需 `ae` 开启 CLOEXEC；最新实现已改并显式解锁，避免后台进程继承锁而自锁。
  apply 的异常分支已先恢复核心，再尽力恢复持久记录，避免磁盘满导致尚未恢复核心便再次抛错。
- 独立运行 `node --test tests/ui/ui.test.cjs`：13 项通过，覆盖订阅覆盖层、删除引用保护、状态、
  revision 冲突、轮询暂停及竞态、默认空参数、只读控件、后台任务成功与失败和生产 LuCI 模块类契约。
- 目标安装路径核查发现 uclient-fetch 实际在 `/bin/uclient-fetch`，此前 `/usr/bin` 调用会失败，
  最新实现已修正。固定目标 BusyBox 的 `CONFIG_TIMEOUT` 未启用，最新实现改用项目自有
  `alwayroute-timeout` 包装直接子进程，没有假定该 applet 存在。
- 自有 timeout 的首版在外部 TERM 时取消 watchdog，却没有对忽略 TERM 的子进程升级 KILL，
  host 隔离实测存在活子进程。实现者修正后，同样的 host `/bin/sh` 测试通过：正常 exit 7
  约 0.01 秒返回；3 秒期限内忽略 TERM 的子进程约 4.05 秒退出 137；向包装器外部 TERM
  后约 1.06 秒退出 143，两种终止均无活直接子进程。测试进程全部清理，目标 ash 的实际验证另计。

## 5. 转发 helper 独立审查

没有连接路由器或执行实际 nft／ip 变更。固定 nftables 1.1.6 上游 `tests/py/inet/tproxy.t`
包含显式 `tproxy ip to 地址:端口` 的通过样例；构建配置已启用 nf-tproxy、nft-tproxy、nft-fib。
这仅是源码旁证，最终完整规则仍须在实际目标内核上执行 `nft --check` 并测试真实流量。

- DNS 拦截在私网 bypass 前，生成器包含 `hijack-dns`；IPv6 范围明确为阻断 LAN 转发及 LAN 到路由器的 IPv6 DNS，
  没有阻断 IPv6 邻居发现。路由器自身发起的流量不进入 LAN prerouting 接管。
- flow offloading 存在时拒绝启用转发；需要实际目标验证 fw4／offload 共存边界。
- 初版只检查 priority 是否存在，可能把被其他组件替换的规则误认成自有，status 也会误报。
  已改为唯一、完整 fwmark／lookup 和 local route 检查。
- 初版 stop 受 `set -e` 影响，nft 删除失败会跳过路由清理。已改为尽力清理、保留其他组件规则，
  并在失败时保留 OWNER 供重试。
- 授权新增 `tests/integration/forwarding-test.py` 两项故障测试：foreign rule replacement 和 nft delete failure。
  用户进一步明确故障阻断后，新增 guard 往返及失败重试保留保护两项，连同原有测试共 10 项，
  已在 Rock 临时目录以命令替身通过；没有修改真实网络。
- guard 原子替换为阻断规则后退去自有 policy rule／route，保留 LAN 私网管理、ICMP／DHCP，
  阻断公网 TCP／UDP、LAN DNS 与 IPv6 转发；status 区分 `guarded:true` 和 `running:true`。
  独立核查修复过一次 heredoc 位置错误；guard → activate 原子替换失败时保留旧 guard，
  不再调用通用 stop 删除保护。已通过 shell 语法及上述隔离故障测试，真实 nft／流量验证另计。
- 固定 `rc.common` 会在 `start_service` 后调用 `service_started`，不能把该 hook 本身当作核心加载成功。
  已反馈 boot/start 路径须先确认核心可用再接管，manager apply 路径另有核心 API 观测与回退。

## 6. 实现审查待关闭项

代码完成后独立检查：订阅失败保留、覆盖及排除持久化、被引用节点消失的处理、凭证脱敏、
命令参数边界、revision 与锁、apply／rollback 失败恢复、sing-box 1.13 schema、UI 保存／应用／连通性状态及 ACL。
首刷基础系统的可写空间已低于 1.5 MiB；加入管理层后的最终镜像容量及透明转发仍需后续实测，
不能把基础首刷成功视为整体需求验收。

冻结 snapshot 的两项集成边界已反馈主 Agent：manager 尚未依赖 forwarding 包，且缺 helper 时
prepare／activate 返回成功；应补依赖或在非 Direct 模式明确失败。manager 的 stop／recover
也必须处理 helper 清理失败，不能停掉核心后仍向 UI 报成功。固定 `rc.common` 忽略
`stop_service` 的普通返回码并继续 `procd_kill`，init 路径也需显式阻止这一失败后的继续执行。

## 7. 主任务追加的实机联调结果

以下为主任务在已首刷的 4A 上实际执行的结果，与上文独立审查的只读范围分开记录。

- 三个自有 APK 使用构建密钥签名，目标已有公钥严格验证通过后安装；未绕过签名、修改信任库或增加系统依赖。重启 rpcd 后等待注册，`capabilities/get/status` 均正常。
- 用户明确允许沿用现有 HTTP 订阅；仅该来源保存 `allowHttp:true`。路由器自行下载完整 Clash YAML，后台刷新成功导入 38 个 VMess 节点，未将订阅的监听、控制器、secret、策略组及规则透传给核心。
- 保存选择后应用成功，实际核心 API、策略组选择和 LAN TProxy 状态一致。单节点 HTTPS 检查通过，首轮延迟 1026 ms；这不等同于所有节点或终端链路均已通过。
- Rock 使用现有直连 LAN 网口向 4A 发送 DNS 请求，代理 DNS 返回测试站点 A 记录；没有修改 Rock 的全局 DNS。
- 经用户明确许可，仅临时增加测试地址 `/32` 路由，经 4A 进行三个 HTTPS 请求，均正常验证服务器证书并返回 HTTP 204，耗时 839/881/642 ms。测试后在 finally 中移除该路由。
- 实际切换 guard 后，同地址公网请求被拒绝，新 SSH 管理连接仍成功；恢复 activate 后再次得到 HTTP 204，临时路由已清理。
- 通过真实保存及应用接口添加仅针对测试地址的 CIDR 阻断规则，连接实际被重置；再通过 rollback 接口恢复原配置，HTTPS 再次返回 204。最终没有保留测试规则。
- 使用真实 root 认证验证 HTTP ubus 可读取 38 节点；LuCI 页面返回 200，标题为 `OpenWrt | AlwayRoute`，执行入口为 `ui.instantiateView('alwayroute/app')`，生产 JS 资源返回 200。这项 HTTP 验证不冒充完整的实机浏览器交互验收。
- 目标 `sysupgrade -l` 已包含 current、lastgood、service 和订阅状态文件；开机启动链接及每小时调度入口存在。应用配置后的独立重启仍待下一具体批次验证。

APK 安装后 overlay 可用约 1380 KiB，保存订阅和应用数据后约 1368 KiB；代理运行时 `MemAvailable` 一次采样约 19 MiB。APK 写入可写层的场景不能代替最终 SquashFS 集成镜像的空间测量。该空间仍低于 1.5 MiB 规划目标，不能标记容量目标通过。

审查补充修正：保存版本与应用版本不一致时，后端禁止节点检查，防止旧核心参数的结果冒充草稿验证；UI 只展示与当前已应用版本相符的检查，并将全局标签明确为“终端出口验证”。对应模型 31、事务 22、下载许可 8、UI 18 项检查通过。

当前边界：节点不可用但核心仍运行时，明确 direct 规则继续由核心执行，代理不自动回退直连；核心整体退出或 guard 保护时，公网 direct 规则也会保守阻断，LAN 管理和私网豁免保留，尚不满足“核心故障时所有明确直连仍可用”。IPv6 采用阻断转发范围；真实 UDP 代理、200 Mbps 吞吐、持续负载及最终镜像重启尚未验收。Rock 到 4A 物理链路目前为 100 Mbps，因此该链路无法证明 200 Mbps 性能。
