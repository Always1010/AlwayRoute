# 小米 4A 降级、root 与 SSH 管理入口记录

> 本文保留前次执行的历史报告，部分判断只基于版本线推断。后续已直接完成 SSH 加固、分区备份及一次重启验证，当前状态以[本轮验证报告](2026-10-22-4a-baseline-and-route-validation.md)为准。尤其是默认 root 密码已更换、SSH 密码认证已禁用，不能继续按本文旧状态处理；Hysteria2 出站与终端 UDP 接管也须分别判断。

- 日期：2026-10-22（Asia/Shanghai）
- 状态：降级与 root／SSH 已完成；持久化配置已安装并手动验证，**未重启验证**
- 关联：[设备记录](../devices/xiaomi-4a.md)、[实施方案](../implementation-plan.md)

## 1. 结果摘要

| 项目 | 结果 |
| --- | --- |
| 原固件 | MiWiFi `2.28.91`（R4A，按版本线判断为 V1） |
| 当前固件 | MiWiFi `2.28.62`，原配置保留 |
| root | 已取得，`uid=0(root)` |
| SSH | `root@192.168.31.1:122`，Ed25519 密钥认证 |
| 持久化 | `/userdisk/dropbear` + `/etc/init.d/alwayroute-ssh` + `S99` 链接；手动启动验证通过，未重启验证 |
| 代理／OpenWrt | 未安装、未刷写 |

## 2. 操作过程

1. **只读核查**：确认 Rock 为 Ubuntu 24.04/aarch64，XMiR 提交与记录一致；确认 4A 为 `R4A / 2.28.91 / CN`，22、23、122 关闭，80 开放，`fac_info` 中 `ssh=false`、`telnet=false`。
2. **2.28.91 尝试公开链**：`c_upload` 对原生备份返回 `code:0`，但任何包含第三个成员的 tar（包括 `speedtest_urls.xml`、符号链接、PAX 覆盖、重复名）都返回 `1629`。判断该版本存在“精确两成员”校验，公开的 `c_upload + netspeed` 链无法落地。
3. **降级**：确认 `2.28.x` 对应 V1；使用小米官方镜像 `miwifi_r4a_firmware_72d65_2.28.62.bin`（MD5 与文件名一致，内部版本/硬件字符串为 `2.28.62`/`R4A`）。通过 `upload_rom` 暂存、`flash_rom?custom=1` 刷写，约 3 分钟后回到 `2.28.62`，配置保留。
4. **取得 root**：在 2.28.62 上使用 `c_upload + netspeed` 执行命令，Rock 回调收到来自 `192.168.31.1` 的 `uid=0 / mips` 证据。
5. **建立 SSH**：投放并组装 dropbear，生成主机密钥，在 122 端口启动；配置 `/userdisk/dropbear` 与 init 脚本，验证密钥登录。
6. **采集信息与清理**：采集分区、空间、内存、内核模块、防火墙和启动项；删除临时密码文件、探针脚本和会崩溃的 UPX 二进制。

## 3. 关键问题与处理

| 问题 | 现象 | 处理 |
| --- | --- | --- |
| 2.28.91 `c_upload` 校验 | 额外 tar 成员一律 `1629` | 放弃该版本，降级到 2.28.62 |
| `netspeed` 随机挑选 URL | 仅 3 项的 XML 中，注入项未被选中 | 使用 14 个 `type="1"` 本地项 + 1 个 `type="2"` 注入项，共 15 项 |
| dropbear 崩溃 | UPX 5.02 版在本机触发 `Trace/breakpoint_trap` | 在 Rock 用 UPX 5.02 解包为 383,048 字节原始 ELF |
| `/etc` 组可写 | dropbear 拒绝把 `/etc` 作为 `authorized_keys` 目录 | 改用 `/userdisk/dropbear_keys` |
| `/etc` 空间不足 | 组装二进制写到 196KB 时 `No space left on device` | 二进制放在 `/userdisk`，临时实例放在 `/tmp` |
| `-A` 参数无效 | dropbear v2025.87 不支持 `-A` | 使用 `-D <目录>` 指定 `authorized_keys` |
| 持久化 | 未重启 | 仅标记“已配置、未重启验证” |

## 4. 最终设备状态

| 项目 | 实测 |
| --- | --- |
| 型号／版本 | `R4A`，V1（2.28.x 版本线），`2.28.62` |
| CPU | MT7621，MIPS 1004Kc V2.15，4 VPE，ISA `mips1 mips2 mips32r1 mips32r2` |
| 内核 | `Linux 3.10.14 #1 MiWiFi-R4A-2.28.62 SMP ... mips` |
| 内存 | 124,160KB 总量，约 39MB 空闲，约 29MB 缓存 |
| Flash | 16MB（`mtd0 ALL`）；`overlay` 1MB，`OS1` 13MB，`rootfs` 11.19MB，`disk` 1.5MB |
| 可写空间 | `/etc`+`/data`（同一 jffs2）约 400KB；`/userdisk` 约 376KB；`/tmp` tmpfs 约 59.6MB |
| 防火墙 | iptables 1.4.12.2；`REDIRECT` 可用；**无 TPROXY、无 nft、无 `/dev/net/tun`** |
| 其他工具 | `ipset`、`dnsmasq`、`tc`；`ip_forward=1` |
| 现有规则 | 存在 `REDIRECT tcp 443 -> 8443`（`tquery_s`），以及 MiWiFi 的 URL 过滤／`hw_nat` 模块 |
| SSH | 22/23 关闭，122 开放；root 密钥登录可用 |

## 5. 两条路线的门槛

### 原厂固件 + ShellCrash

- root 已不是门槛。
- 持久空间不足以存放完整代理核心；只能临时放在 `/tmp`（重启丢失），启动时重新获取会引入外部依赖。
- 无 TUN／TPROXY，只有 `REDIRECT` 和 MiWiFi 自有转发模块；UDP／QUIC／Hysteria2 的透明代理覆盖是主要缺口。
- 124MB RAM 下核心 + Web 管理的常驻内存，以及 16MB Flash 的长期空间，仍需实测。
- 现有 443→8443 的 `REDIRECT` 与 URL 过滤模块需要设计避让。

### 刷入 OpenWrt 等新固件

- V1 已确认（2.28.x 与 MT7621/1004Kc 一致）。
- 基础镜像约 7.3–7.7MB，16MB Flash 剩余约 6.7–7.2MB；定制核心 + 管理页仍需核算。
- 124MB RAM 需实机验证。
- 首次启动地址与路由器 B 的 `192.168.1.0/24` 冲突，需要隔离方案。
- 完整分区备份、恢复演练和刷写授权尚未进行。

## 6. 未验证事项

- **重启后 SSH 是否自动启动**（未重启）。
- ShellCrash／核心在 `/tmp` 的实际常驻内存、UDP 覆盖和稳定性。
- 4A 的完整分区备份与恢复演练。
- 物理标签上的 V1/V2 标识（仅按 2.28.x 版本线推断为 V1）。
- 4A 当前 WAN 的互联网连通性（利用阶段测速结果为 0，未单独核实）。

## 7. 变更与残留

### Rock 5B

- 新增 SSH 私钥：`/srv/alwayroute/keys/4a_ed25519`（0600）。
- 保留恢复资料：`backups/` 下 2.28.91 配置备份、设备信息、代理能力检查、2.28.62 官方镜像。
- 已删除：临时管理密码文件、探针脚本、UPX 工具与临时二进制。
- 未安装软件，未改 Rock 网络。

### 小米 4A

- 固件降级到 `2.28.62`，配置保留。
- root 密码被设为 XMiR 默认弱口令，**建议尽快修改**。
- NVRAM 设置了 `boot_wait=on`、`bootdelay=3`、`uart_en=1`。
- 持久 SSH：`/userdisk/dropbear`、`/userdisk/dropbear_keys/*`、`/etc/init.d/alwayroute-ssh`、`S99` 链接。
- 已删除会崩溃的 `/etc/dropbear/dropbear`（UPX 版）和旧 `/etc/init.d/dropbear`；旧 `S50dropbear` 链接已移除。
- 未安装代理，未刷 OpenWrt，未重启验证持久化。

## 8. 结论

本轮已完成“降级—取得 root—建立 SSH”的闭环，并取得了设备资源与内核能力的实测数据。

但**取得 root 不等于两条路线均已可行**：原厂路线的存储、内存与 TUN/TPROXY 缺口仍然明显；OpenWrt 路线仍需备份、恢复和镜像预算验证。下一步应先在“重启持久化验证”和“ShellCrash 资源/UDP 能力实测”之间做选择，而不是直接进入部署。
