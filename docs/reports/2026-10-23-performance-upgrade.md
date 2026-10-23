# 性能精简与保留配置升级记录

> 历史执行快照：日期和结论限于本轮；当前部署见[状态](../status.md)，先后关系见[报告索引](README.md)。私有路径以角色占位，示例命令不是当前操作入口。

2026-10-23（Asia/Shanghai），按用户要求检查代码、降低代理与管理开销、减少 Flash 占用，并打包刷入现有小米 4A 千兆版。已完成构建、保留配置 sysupgrade、重连与功能检查。没有安装本机软件、改全局环境或推送 Git。

## 实施内容

- 状态 RPC 不再返回每个节点、selector 的全部成员及历史，只返回界面和事务确认使用的 selector `now`。核心 `/proxies` 读取上限从 64 KiB 改为有溢出检测的 256 KiB，修复最大模型可能被截断而误报加载失败的问题。同一次请求复用模型，避免为 revision 再读、解析和校验整份配置。
- selector 仅列出直连、当前选择和必要的 Proxy 引用。所有有效节点 outbound 仍保留，任意节点检查及 LuCI 选节点仍可用。LuCI 从管理模型生成选项，选择后 configure 重建核心配置；loopback Clash API 直接 PUT 到未列入该 selector 的其他节点不属于该精简配置的支持入口。
- DNS 端口 53 优先 hijack，避免先走协议嗅探。仅规则模式保留 TLS、HTTP、QUIC 域名嗅探；全局和直连模式跳过嗅探。自定义规则顺序、服务优先级与 Other 兜底语义保留。
- 概览完整状态检查由每 5 秒改为每 15 秒，流量与日志仍每 5 秒更新。首次打开、返回概览、手动刷新及配置/启停确认仍立即读取真实状态；失败尝试也节流，避免错误时增加重复子进程。
- 核心恢复 Go 默认内联，CLI 只编入 run/check/version。通过固定源码的 registry overlay 精简未要求的入口，保留 VMess、SS、Trojan、VLESS Reality/Vision、Hysteria2，以及原有 QUIC、uTLS、Clash API 标签。移除 Tor、SSH、TUN、URLTest 等未被本产品使用的入口，具体差异见 `002-sing-box-router-profile.patch`。
- 用 ip-tiny 替代 ip-full，移除因此不再需要的 libbpf1。没有移除无线、IPv6 基础组件、防火墙或 LuCI 通用管理。

管理层当前仍只支持 VMess 节点建模/订阅导入；本次保留核心中的其他协议能力，没有宣称已增加这些协议的界面或真实上游兼容验收。

## 可复现核心与镜像

新增 `firmware/tools/build-core.py`：使用 Rock 既有 Go 1.27.3 与模块/编译缓存，核对固定源码归档及 1017 个源文件，拒绝源码漂移；通过 Go overlay 应用补丁，不修改第三方源码树。构建设置 `GOPROXY=off`，不安装或下载依赖。完整标签仍为：

```text
with_quic,with_utls,with_clash_api,badlinkname,tfogo_checklinkname0
```

候选核心命令：

```sh
python3 firmware/tools/build-core.py --output <新的产物绝对路径>
```

OpenWrt 继续复用已有构建树、工具链、下载和缓存；先审查项目 rsync dry-run，再同步独立工作副本，逐包 dry-run 后仅更新四个自有包目录。配置差异只有 ip-full → ip-tiny、移除 libbpf；内核及其余保留包版本不变。未运行 clean/dirclean/distclean。增量镜像构建退出 0，耗时 104.321 秒。

| 项目 | 升级前 | 新候选 |
| --- | ---: | ---: |
| 核心 ELF 字节 | 27,918,491 | 23,330,971 |
| sysupgrade 镜像字节 | 13,435,470 | 13,042,254 |
| SquashFS bytes_used | 10,198,384 | 9,791,968 |
| 原始 overlay 容量，未扣文件系统开销 | 1,769,472 | 2,162,688 |
| 设备实际 overlay 可用空间 | 本轮开始 1468 KiB | 升级及最终检查 1876 KiB |

最终镜像减少 393,216 字节，即 384 KiB。可用空间实际变化还包含 JFFS2 文件系统与当前已用数据，不能只用镜像大小直接推算。

- 镜像 SHA-256：`87d09ed5a40c9279e5cd2f3a401566256f7ede5f9fbf5f915f057ed053ee4938`。
- 核心 SHA-256：`978ca409acad3f02c2227381b0057ead88f34333356291bdca1103eb7f27c521`。
- registry 补丁 SHA-256：`425c4214fe65d10081f44bc69da86c07b0bfc6340cc6efdc487ca13c218906d5`。
- 固定上游归档 SHA-256：`c994018d7c2a8fc9fcf6080e4b9cc4f2f915e755342238b77e46fc0806fe96db`。

检查器显式接受已经过设备版本/现有配置检查的核心 SHA，并校验镜像中 ELF 与 build-info 一致。ip-tiny 模式只允许增加管理三包及 ip-tiny，移除 ip-full 及限定依赖，其他包版本必须不变。首次检查因实际 ABI 包名 `libbpf1` 与预期 `libbpf` 不符而拒绝，修正检查器后全部 **245 项检查通过**；没有放宽到任意包增删，也没有因此重建未变化镜像。

## 大模型与控制面结果

同一 ucode 序列化格式，128 节点、16 组、128 规则：

| 项目 | 原实现 | 优化后 |
| --- | ---: | ---: |
| selector 成员引用总数 | 2079 | 39 |
| 生成配置字节 | 52,458 | 37,924 |
| Rock 上生成 50 次耗时 | 5.79 秒 | 5.69 秒 |

生成耗时差距很小，不能据此声称生成器明显提速；可靠变化是配置规模和成员引用数量。大模型契约还覆盖了 128 个最长标识节点、16 组的旧式完整核心响应：171,611 字节裁剪为 1,395 字节的 core 状态，减少 99.19%，不再经过 rpcd/浏览器传输节点成员及历史。真实设备 38 节点、8 组的完整 status JSON 在新增节点检查结果前为 615 字节。

在最终 MIPS 设备上，128 节点、16 组、128 规则的 rule/global/direct 生成配置均通过新核心 check；规则和非规则模式语义分别由现有契约测试保护。

## 代理相对测试

基线和候选分别从刷机前后的 Flash 执行。使用同一 4A、同一 Rock 上的受控 VMess 服务、同一 AES-128-GCM 配置，Rock 经 SSH 转发访问路由器 loopback mixed 端口；每条连接下载 4 MiB，分别 1/4 并发。标准 TLS 使用临时测试 CA 验证，未关闭证书验证。链路为 100 Mbps。

| 传输 | 并发 | 基线 Mbps | 新核心 Mbps | 基线/新核心 CPU ticks | 基线/新核心 RSS KiB |
| --- | ---: | ---: | ---: | ---: | ---: |
| VMess TCP | 1 | 8.69 | 9.37 | 552 / 507 | 23,952 / 19,964 |
| VMess TCP | 4 | 16.94 | 19.18 | 2415 / 2103 | 25,252 / 21,160 |
| VMess WS + TLS | 1 | 5.66 | 7.75 | 831 / 610 | 25,004 / 21,148 |
| VMess WS + TLS | 4 | 11.61 | 15.89 | 3714 / 2626 | 27,288 / 22,912 |

在这组固定条件的短测中，吞吐提高约 8%–37%，相同字节的核心 CPU 时间减少约 8%–29%，进程 RSS 减少约 4 MiB。这是整组核心变化的相对结果，不能单独归因于内联，也不是实际互联网线路带宽上限；SSH 加解密与测试端也有开销。

补测默认 `security=auto`，临时 mixed 仅绑定 LAN 且加临时认证，移除数据路径中的 SSH 转发；仍用同一受控服务和 4 并发，每连接 4 MiB：

| 传输 | Mbps | 核心 CPU ticks | 核心 RSS KiB | MemAvailable KiB |
| --- | ---: | ---: | ---: | ---: |
| VMess TCP / auto | 63.76 | 675 | 21,120 | 27,764 |
| VMess WS + TLS / auto | 61.30 | 705 | 22,548 | 27,324 |

这组 LAN 测试没有同条件的旧核心 auto 基线，不能据此计算升级加速倍数。它与固定 AES 对比也不是同一加密条件。没有 200 Mbps、长时间满载或数百连接验收证据，高并发仍可能使 MT7621 CPU 满载。

早期把候选 ELF 放到 `/tmp` 的实验额外占用约 23 MiB RAM，并出现超时和连接重置，不计入上述基线/候选比较；随后清理 RAM 副本和遗留测试进程、恢复生产转发，再采用上述从 Flash 执行的比较。没有将这些失败抹去或当作核心成功运行。

## 刷写与最终设备检查

实际目标再次核对为 `xiaomi,mi-router-4a-gigabit`。最终镜像在 Rock、PC 和路由器 `/tmp` 的 SHA 一致；设备 `sysupgrade -T` 通过。外置最终配置备份 9965 字节、37 个文件，SHA-256 为 `6bed18c294807b39083bcb51b89442c39d269a58bf4942c9beb5d91d7715ad5b`；保存在 Rock 私有备份目录，不进入 Git。

执行一次保留配置的 `sysupgrade /tmp/alwayroute-perf/upgrade.bin`，未使用 `-n`。SSH 退出 246 且日志包含会话关闭时的 ubus connection failed；后续以新启动 ID 和 `/rom` 核心 SHA 确认升级成功，而非按 SSH 退出码猜测。

- 新 boot ID：（具体运行标识省略），与升级前不同；SSH 主机密钥一致。
- 网络、无线、SSH/Web、shadow、公钥、管理 marker、current/lastgood/service 及主机密钥共 12 项关键文件在升级后、主动应用前逐一 SHA 一致。
- 首启从 lastgood revision 6 自动恢复；随后应用已有的 saved revision 13，当前 saved/applied 均为 13、lastError 为 null。保留 38 节点、1 订阅及用户选择，旧固定服务组按已批准 UI 方案迁移为 8 个策略组。
- 双频无线均 up，两个接口；WAN up 且有 IPv4 地址。已验证认证后的 LuCI 页面 200、HTTP 实际提供的 UI JS 与镜像哈希一致、认证状态 RPC 成功。
- LAN UDP/TCP DNS 均 rcode 0、有回答；记录的 3/4 ms 为热缓存结果。经临时单 IP 路由的透明 HTTPS 在证书验证下返回 204，约 287 ms。临时路由已删除。
- 当前选定代理节点检查 available=true、healthy=passed、checkedRevision=13、delay=1125 ms；这只是该节点的检查结果，不将整个系统 healthy 改为 passed。
- 新核心在设备上接受 VMess、Hysteria2、VLESS Reality/Vision、Trojan、SS 的合成配置，并按预期拒绝 Tor/URLTest；除 VMess TCP/WS+TLS 之外，没有把配置检查写成真实协议流量通过。
- ip-tiny 在升级前用隔离表/优先级 20239/10239 验证 route replace/show/del 和 fwmark rule add/show/del，清理成功；升级后实际 `/sbin/ip` 指向 ip-tiny，透明转发正常。
- 最终 overlay 可用 1876 KiB；一次结束采样 MemAvailable 25,788 KiB。临时 LAN 代理端口关闭，Rock 临时 HTTP/VMess/SSH 测试进程为 0，生产核心与转发已恢复。

本次升级重启、配置保存与实际网络功能已验证；没有额外执行掉电/第二次重启，也没有宣布全部长期性能与 A1–A9 验收完成。前向 IPv6 仍按原声明阻断，本机来源流量仍直连。

## 验证与产物位置

- 52 项管理契约、58 项内存事务、8 项下载权限检查通过。
- 30 项 UI 测试、16 项 UI/RPC/ACL 契约检查、10 项 forwarding 隔离命令测试通过。
- 245 项最终镜像检查通过；全部自有载荷逐文件核对，内核 payload 不变，文本可执行入口 LF/shebang 正常。
- 新增核心及镜像工具语法、参数约束、固定源核查和实际候选构建均已执行。

Rock 公开产物及测量：`<task-root>/artifacts/alwayroute-perf-20261023/`。私有配置备份独立位于 `<private-backup>`。电脑镜像、SHA、检查和脱敏测量位于被 Git 忽略的 `artifacts/performance-20261023/`。测试临时程序没有随固件安装。
