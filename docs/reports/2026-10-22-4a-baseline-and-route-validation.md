# 4A 管理入口、备份与两条路线验证

- 日期：2026-10-22（Asia/Shanghai）。
- 本轮直接验证：通过 Rock 5B 登录 4A、完成在线备份、收紧 SSH、修改默认 root 密码，并重启验证。
- 前次降级及权限获取过程来自[前次报告](2026-10-22-4a-root-ssh-verification.md)，本轮没有重复降级或漏洞利用。
- 当前固件：MiWiFi `2.28.62`；尚未刷入 OpenWrt。

## 1. 已验证结果

| 项目 | 本轮结果 |
| --- | --- |
| root | 新建 SSH 连接返回 `uid=0(root)` |
| SSH | `root@192.168.31.1:122`，已有 Ed25519 密钥认证 |
| 监听范围 | 由所有 IPv4／IPv6 地址改为仅 `192.168.31.1:122` |
| SSH 密码登录 | 已禁用；客户端握手只收到 `publickey` 认证方式 |
| 系统 root 密码 | 已替换为随机恢复口令；重启后通过私下比对密码哈希验证保留；口令未写入仓库或聊天 |
| 开机自启 | 已执行一次真实重启；boot ID 变化，新建 SSH 登录成功，启动记录显示 `S99alwayroute-ssh` 执行返回 0 |
| 恢复耗时 | 从发送重启请求到首次确认新 boot ID 约 62 秒，受检查间隔影响，不是精确启动耗时 |
| 原厂 Web | 公开接口仍返回 `R4A / 2.28.62 / CN` |
| 4A 上网 | 通过本机 curl 请求百度 HTTPS，HTTP 200、证书校验结果 0 |
| Rock 管理网络 | 默认路由仍为 Wi-Fi → `192.168.1.1`，有线仅连接 `192.168.31.0/24` |

启动脚本由原来的 `killall dropbear` 改为独立 PID 文件及进程路径核对，避免停止其他 Dropbear 实例。新增 `K98` 停止链接，保留 `S99` 启动链接。临时验证端口 1122 已停止。

Rock 上的访问文件：

- SSH 私钥沿用 `/srv/alwayroute/keys/4a_ed25519`。
- 本轮新增专用主机指纹文件 `/srv/alwayroute/keys/4a_known_hosts`；首次通过直连管理网段建立信任，后续严格核验；没有独立带外核验主机指纹。
- 恢复口令保存于 `/srv/alwayroute/keys/4a-root-recovery-password.txt`，权限 0600。SSH 不接受该口令登录。

## 2. 分区及配置备份

Rock 目录：`/srv/alwayroute/backups/4a-baseline-20261022T133657Z/`。

- `mtd00-ALL.bin` 为 16,777,216 字节整片 Flash 读取。
- 分别保存 mtd1–mtd10 的 Bootloader、Config、Bdata、Factory、crash、cfg_bak、overlay、OS1、rootfs、disk。
- 保存变更前 `/etc` 与 SSH 程序／密钥目录的逻辑归档；另存加固后的归档。
- 初始 11 个原始 MTD 文件及一个逻辑归档合计 45,569,808 字节；后续加固归档和记录另计。
- 每份原始备份长度均与 `/proc/mtd` 一致，生成 SHA-256／MD5 清单；Bootloader、Bdata、Factory、OS1、rootfs 另与设备第二次读取的 MD5 比对。
- 所有单分区备份均与整片备份中已核对偏移处内容一致。
- 归档目录和文件分别采用 0700／0600；包含设备秘密，仅保留在 Rock，未复制进 Git。

这是正常运行中的在线读取，不是停机后的原子快照。可写 JFFS2 恢复能力尚未通过写回验证；MTD 条目存在重叠，不能拼接分区或盲目回写整片 Flash。

## 3. 设备与恢复条件

- Linux `3.10.14`，MT7621，Linux 可见内存 124,160 KiB。
- 本轮重启后的一个采样点：MemFree 46,584 KiB、Buffers 8,468 KiB、Cached 25,732 KiB、Shmem 712 KiB；不能将其相加当作精确 MemAvailable。
- `/etc` 与 `/data` 是同一 1 MiB JFFS2 分区；加固后剩余约 360 KiB；`/userdisk` 剩余约 376 KiB。
- PCI 无线设备 ID 为 `14c3:7662` 与 `14c3:7603`；与 OpenWrt 第一版千兆 4A 的 mt76x2／mt7603 组合对应，作为该构建目标的硬件证据。尚未查看机身或 PCB 修订标识。
- Bootloader 为 U-Boot 1.1.3，二进制包含 TFTP 功能及编译默认地址 `192.168.31.1`／`192.168.31.2`。这些字符串不等于已验证实际恢复时的网络行为。
- 原厂 `2.28.62` 镜像仍保存在 Rock，已在私有备份清单记录 SHA-256。
- 恢复条件与失联处理顺序写入私有目录 `RECOVERY-NOTES.txt`。没有安装 TFTP 服务、进入恢复模式或执行恢复刷写；刷机前仍需确认物理恢复和地址隔离条件。

硬件参考：[OpenWrt 25.12.6 设备定义](https://github.com/openwrt/openwrt/blob/v25.12.6/target/linux/ramips/image/mt7621.mk)。

## 4. 两条路线的后续门槛

1. 原厂路线：固定候选核心，先验证 ELF／内核兼容、显式代理与内存，再测试单台终端透明接管；持久空间、独立启动和完整 Web 管理另行验证。
2. 新固件路线：先获得匹配目标的实际定制核心和完整镜像预算，再准备具体刷机清单。不能把 16 MiB 减下载文件大小视为可写空间。
3. Hysteria2 出站与局域网 UDP 接管分别验证；缺少 TUN／TPROXY 不直接证明 Hysteria2 出站不可用。不存在 `/dev/net/tun` 也不能单独证明内核没有 TUN 能力。
4. Rock 保持辅助角色；正常使用不得依赖 Rock 提供转发、网页或每次启动供给核心。

## 5. 环境与变更边界

- 本轮按单 Agent 顺序操作设备，没有并发 Agent 写入。
- 电脑没有安装软件、修改全局设置或网络；项目记录更新另计。
- Rock 没有修改系统网络、服务、系统 PATH 或 apt 软件包。
- 用户已单独批准在任务目录安装官方 Go 1.27.3 ARM64 工具链及构建依赖缓存；安装和后续构建结果待本报告后续补充。
- 路由器只进行本报告所述 SSH／密码变更和一次重启；未刷 OpenWrt、未修改代理防火墙规则。
