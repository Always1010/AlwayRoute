# 4A 完整功能加密优化与刷机记录

2026-10-23，Asia/Shanghai。用户批准在不删功能的前提下继续优化、构建并刷入小米 4A 千兆版。本轮已完成候选比较、设备加密测试、完整镜像检查、保留配置刷写及刷后网络检查。

最终 Flash 核心在受控局域网透明代理测试中，4 并发连续 60 秒平均达到 **VMess TCP 173.08 Mbps、VMess WS/TLS 160.88 Mbps**。尚未达到 200 Mbps；这些是设备受控转发能力，不是互联网宽带或实际订阅节点测速。

## 当前版本与历史记录

本记录对应完整上游 CLI、完整注册表、全部既有编译标签、ip-full 和 143 个软件包。策略组保留完整成员，保留当前运行配置的规则、协议嗅探、DNS 与统计功能。

此前《性能精简与保留配置升级记录》记录过精简 CLI、注册表、selector 与 ip-tiny 的历史版本；这些精简已在后续完整功能恢复阶段撤回，不描述本轮已部署状态。本轮开始时的完整功能基线为核心 `a21f9cb1…`、镜像 `64424850…`。

管理界面现有协议建模范围不因底层保留更多协议而自动扩大。本轮没有声称增加新的节点类型导入或完成所有协议的真实上游兼容性验收。

## 实施与取舍

1. 完整核心继续使用 sing-box 1.13.21、Go 1.27.3、linux/mipsle softfloat。复用已有混合负载 PGO，仅在密码计算热点保留内联，完整 CLI/注册表不裁剪。
2. 对模块版和标准 TLS vendor 版的 ChaCha20、Poly1305 使用固定来源的 MIPS 汇编。最终候选额外启用原补丁已有的 MIPS32r2 ROTR 路径，适配 MT7621 的 1004Kc；20 轮 ChaCha、认证、安全检查及协议内容保持。
3. `build-core.py` 加入显式 `--experimental-crypto` 候选，默认仍为标准 Go 实现。复制固定模块快照、使用独立 modfile/overlay/stage，不修改上游源码、GOROOT 或 Go 模块缓存。
4. 镜像检查核验完整模块目录哈希、实际 ELF 依赖替换与汇编参数、补丁范围及实际 ROTR/MADDU 指令。标准构建默认拒绝实验 overlay，不能仅靠自述元数据冒充标准核心。
5. 增加保护页、越界、只读输入与差分测试，并独立试验历史 32 位 Poly1305。后者完整代理提升很小，没有部署。
6. 额外网络 I/O 内联候选在一次短测中仅 TCP 高约 3%、WS/TLS 基本相同，ELF 增加 64 KiB。该差距不足以证明稳定收益，未采用，也未更改默认编译参数。

底层汇编来源为 [Go CL585755](https://go-review.googlesource.com/c/crypto/+/585755)，固定 revision `45132dae57e76146e71cc1cda14e3a75dffe2457`，对应 [golang/crypto PR294](https://github.com/golang/crypto/pull/294)。核查时仍未合并，没有上游密码审查通过结论。本地差分、向量、边界测试和实际传输通过，不等于正式密码安全或恒定时间审计。

此 MIPS32r2 核心没有运行时 CPU 分派，不应作为通用 mipsle 核心分发。镜像仅针对已经核对的 `xiaomi,mi-router-4a-gigabit`。

## 同条件比较

Rock 与路由器通过 1000 Mbps 全双工有线 LAN 连接；受控 VMess 服务和下载源位于 Rock。批量数据不经过 SSH，也不使用 WAN；SSH 仅用于配置和采样。VMess 使用 `security=auto`，WS/TLS 验证测试证书，未关闭证书验证。

下表均为 4 并发、约 12 秒、核心同样放在 RAM 的公平比较。透明测试加载实际运行配置的脱敏模板，保留 8 个 selector、319 个成员引用、9 条运行规则及其中 1 条 sniff，保留每组当前选择；仅将节点叶子替换为受控 LAN VMess。通过实际连接元数据核对 TPROXY 和代理链。

| 透明代理路径 | 完整功能基线 | 最终 r2 候选 | 变化 |
| --- | ---: | ---: | ---: |
| VMess TCP | 80.13 Mbps | 165.41 Mbps | +106.4% |
| VMess WS/TLS | 91.67 Mbps | 163.18 Mbps | +78.0% |

该透明负载只使用 `www.google.com` 这一合成 HTTP 主机名和对应策略分支；完整配置存在不等于所有规则分支同时受压。当前独立 OpenAI 选择也被保留，没有把所有组改成跟随 Proxy。

不同测试入口不能混为一张提速表：

| 入口与条件 | 基线 TCP / WS-TLS | 最终 r2 TCP / WS-TLS |
| --- | ---: | ---: |
| 普通 HTTP 显式代理，4 并发、12 秒、RAM | 89.02 / 87.13 Mbps | 141.39 / 143.97 Mbps |
| HTTP CONNECT，4 并发、12 秒、RAM | 99.21 / 92.87 Mbps | 175.56 / 169.08 Mbps |
| 完整规则 TPROXY，4 并发、12 秒、RAM | 80.13 / 91.67 Mbps | 165.41 / 163.18 Mbps |

普通 HTTP 代理入口还包含响应处理、复制等开销；此前 83–89 Mbps 不能当作所有代理入口相同的固定上限。CONNECT 单连接 TCP 从 50.37 提升到 86.73 Mbps；普通 HTTP 单连接 r2 TCP/WS-TLS 为 68.49/76.76 Mbps。不能把多连接总吞吐宣称为单连接速度。

历史 32 位 Poly1305 候选在普通 HTTP 代理 4 并发仅达到 TCP 90.06、WS/TLS 90.39 Mbps，未兑现明显提速预期，因此舍弃。普通 MIPS32r1 汇编为 127.15/130.31 Mbps，MIPS32r2 路径进一步提高到上述 141.39/143.97 Mbps。

## 刷入 Flash 后的持续负载

使用已安装的 `/usr/bin/sing-box`，没有在 `/tmp` 放一份 27 MB 核心。沿用完整规则透明测试，TCP 和 WS/TLS 各持续 60 秒、4 并发：

| 指标 | TCP | WS/TLS |
| --- | ---: | ---: |
| 平均吞吐 | 173.08 Mbps | 160.88 Mbps |
| 下载字节 | 1,298,101,304 | 1,206,612,618 |
| CPU 平均 busy | 92.23% | 92.09% |
| system CPU | 32.27% | 30.65% |
| softirq CPU | 10.27% | 11.66% |
| 采样进程 RSS 范围 | 26,188–28,516 KiB | 27,816–28,552 KiB |
| 采样 MemAvailable 最低 | 22,308 KiB | 22,272 KiB |
| softnet 丢包计数增量 | 0 | 0 |
| 已核对 TPROXY 下载连接 | 4 | 4 |

吞吐使用各 curl 实际传输时长，CPU 使用前后 `/proc/stat` 差分；每约 8 秒采样内存。Flash 持续测试与 RAM 短测存储条件、时长不同，不用两者直接计算优化倍数。两轮总计传输约 2.50 GB，结束后内核没有 OOM、panic、BUG 或 segfault 记录；这只是本轮有限时长验证，不是数小时耐久或数百连接测试。

优化降低了每字节处理成本，但跑到新上限时 CPU 仍接近饱和，不能承诺满流量下低负载。r2 CPU profile 中 ChaCha/Poly1305 仍有明显开销，同时系统调用、复制与内核网络处理占比较高；继续提高到 200 Mbps 仍需解决 CPU/数据路径瓶颈，不能靠再次缩小界面或删除策略组证明。

## 构建、Flash 与可复现输入

先审查 rsync dry-run，再同步 Rock 独立工作副本；仅更新构建需要的核心输入和元数据。复用 OpenWrt、下载、工具链和 Go 缓存，不运行 clean/dirclean/distclean，不安装本机依赖。镜像增量构建退出 0，耗时 89.135 秒。

| 指标 | 本轮完整功能基线 | 已部署 r2 |
| --- | ---: | ---: |
| 核心 ELF 字节 | 27,918,491 | 27,918,491 |
| sysupgrade 镜像字节 | 13,501,006 | 13,435,470 |
| SquashFS bytes_used | 10,233,592 | 10,228,588 |
| 原始 overlay 容量，未扣文件系统开销 | 1,703,936 | 1,769,472 |
| 软件包数量 | 143 | 143 |

压缩载荷减少 5,004 字节，跨越对齐边界后镜像减少 65,536 字节、原始 overlay 增加 64 KiB。不是核心 ELF 缩小 64 KiB。刷后实际 overlay 总量 1,728 KiB、已用 236 KiB、可用 1,492 KiB，仍需节制持久化日志与大型规则文件。

最终构建命令：

```sh
python3 firmware/tools/build-core.py --crypto-inline \
  --pgo /srv/alwayroute/artifacts/alwayroute-bottleneck-20261023/mixed-cpu.pprof \
  --experimental-crypto mipsle-asm-r2 \
  --output /srv/alwayroute/artifacts/alwayroute-crypto-20261023/sing-box-r2-repro-mipsle
```

- 核心 SHA-256：`0c8f208383bf790a89e03be83f9b953ebe490cad64c403d4e58087f6c36722b2`。
- 镜像 SHA-256：`bee3240b2d0196df315d2a4af61f7d4b32d29b631ed6493ecf6eca9e946b2246`。
- PGO SHA-256：`c0ca6b0e9e2e79d1840e6493e8eb7470a67e2086bfc22ecc5b1865d839c03012`。
- 固定上游归档 SHA-256：`c994018d7c2a8fc9fcf6080e4b9cc4f2f915e755342238b77e46fc0806fe96db`。
- 原始汇编补丁 SHA-256：`c1eea9c8a0d98779a2465d2535a6204a5aeb5ce50cf7abe812e2dc5d7f25ab34`。

## 验证与部署结果

- 新保护页测试：模块版/vendor 版 ChaCha 各 9 个顶层测试通过，Poly1305 各 10 个通过、1 个原有慢速 stress 默认跳过。包含两端保护页、未对齐、canary、只读输入、in-place 与最后计数器边界。
- r2 路径：模块版/vendor 版 ChaCha 各 9 个、AEAD 各 5 个顶层测试通过。实际设备执行向量、随机差分、认证失败测试，vet 未关闭；未改变的 Poly 汇编沿用上述保护页验收。
- 历史 32 位候选：模块版/vendor 版 Poly1305 各 11 个通过、1 个默认 stress 跳过，AEAD 各 5 个通过；候选没有部署。
- 10 项针对依赖与篡改的来源验证通过；正式镜像 277 项检查全部通过，143 个软件包的既有版本、完整核心入口、自有载荷与内核约束保留。
- 设备 `sysupgrade -T` 通过；保留配置升级前，将 37 文件备份保存到 Rock 私有目录。12 项关键配置哈希刷后和所有测试结束后均一致。
- 首轮自动等待未在时限内确认启动；随后以新 boot ID `<runtime-id>` 和 `/rom/usr/bin/sing-box` 的最终 SHA 确认升级成功。没有因 SSH/ubus 会话断开重复刷机。
- 38 个节点、1 个订阅、8 个策略组、319 个 selector 成员引用保留；saved/applied revision 均为 13，lastError 为 null。首启核心与转发自动恢复。
- 设备接受 VMess、Hysteria2、VLESS Reality/Vision/uTLS、Trojan、Shadowsocks、SOCKS、HTTP、URLTest 合成配置；完整 CLI 和 ip-full 入口检查通过。这是配置/入口检查，不能代替这些协议全部实际流量验收。
- 刷后真实透明 HTTPS 在证书验证下返回 204，约 309 ms；UDP/TCP DNS 正常，LuCI 登录后页面 200、实际提供的 UI 文件与镜像哈希一致、状态 RPC 正常。
- WAN 与 LAN2 均为 1000 Mbps；双频无线 up。测试进程、专用 nft 表、策略路由和 Rock 临时主机路由已清理，只有一个已安装生产核心运行。
- 测试结束 MemAvailable 25,504 KiB。整体状态仍为 `healthy=unverified`，不把单条成功请求改写成所有上游节点健康通过。

## 提交与产物

本轮相关本地提交：`542e00ff`（保护页测试）、`c3518652`（历史 32 位隔离候选）、`550e39a8`（可复现完整候选构建）、`1e76d73d`（真实依赖与完整源码核验）。未执行远程 push，保留用户原有未提交修改。

电脑公开产物位于 Git 忽略目录 `artifacts/crypto-20261023/`：最终镜像、manifest、构建元数据、镜像检查、脱敏性能/密码测试汇总、刷后网络/状态检查及 SHA256SUMS。下载后 10 个产物哈希逐一通过。

Rock 原始测量和构建输入位于 `/srv/alwayroute/artifacts/alwayroute-crypto-20261023/`。该远端工作目录包含测试认证材料和策略标识，不作为整个公开目录分发。设备备份单独保存在 `/srv/alwayroute/backups/crypto-upgrade-20261023/`，没有进入 Git 或电脑公开产物目录。
