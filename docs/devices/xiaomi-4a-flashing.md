# 小米路由器 4A 千兆版第一版刷机

仅适用于 **4A 千兆版第一版（R4A，MT7621）**，不适用于百兆版、千兆 V2 或其他型号。先核对机身标签和硬件修订；项目支持边界见 [设备说明](https://github.com/Always1010/AlwayRoute/blob/main/docs/devices/xiaomi-4a.md)。

## 准备

1. 从 [Releases](https://github.com/Always1010/AlwayRoute/releases) 下载对应版本的固件与工具包 `.zip` 并解压，先打开唯一的使用说明 `README.md`；目录内还有 `*-sysupgrade.bin`、`flash.py`、`SHA256SUMS`、`build-manifest.json` 和合并后的许可来源说明 `NOTICE.txt`。已有OpenWrt、准备通过网页升级时，可单独下载 `.bin`。版本号以实际发布为准，下面的 `v0.1.0` 仅为示例。
2. 电脑已有 Python 3.10+ 和 OpenSSH 客户端即可；脚本只用标准库。电脑连接路由器 LAN，**首次刷机建议网线连接**。已有 Wi-Fi 可用于 SSH／上传，但新系统默认关闭无线，首启需要有线连接；保留配置升级后可重新连接已保留的 Wi-Fi。
3. 确认 root SSH 已可登录，先用普通 `ssh` 登录并核对主机指纹。脚本保留严格主机检查，可使用已有密钥、SSH agent 或交互式口令；自定义端口使用 `--port`，密钥使用 `--identity`。不需要构建主机、跳板或个人实验拓扑。

## 原厂系统首次刷入

已验证的原厂路径是 `2.28.91 → 2.28.62 → root／SSH → OpenWrt`。原厂 Web 不会直接接受这个项目镜像；先按 [XMiR-Patcher 上游说明](https://github.com/openwrt-xiaomi/xmir-patcher)准备匹配版本的 root／SSH 入口和恢复启动标志（`boot_wait=on`、`uart_en=1`）。这一步的工具、降级与解锁需要自行按硬件和版本核对，本脚本不自动解锁或修改启动变量。脚本仅接受已记录的 `R4A / 2.28.62` 原厂入口。

在解压目录运行预检，将地址、端口和文件名改成自己的实际值：

```powershell
python flash.py --mode stock --host root@192.168.31.1 --port 22 --image alwayroute-v0.1.0-xiaomi-4a-gigabit-sysupgrade.bin
```

预检通过后，在同一条命令末尾加 `--apply --backup-dir ../private-backups/4a-first-flash`。备份目录必须不存在且位于发布文件目录之外。脚本先把完整 Flash 和分区备份保存到电脑并校验，再上传固件到内存目录、校验传输，最后只向 `OS1` 提交一次写入并重启。不会写 Bootloader、Factory 或 ALL；首刷不会继承原厂网络、密码和 Wi-Fi 配置。

脚本会在读取设备备份前建立私有目录，并在写入每个敏感文件前限制和核验权限。Windows 会移除继承的 DACL、只授予当前用户 SID 完全控制并回读确认；文件系统不支持该权限、权限核验失败，或目标路径含符号链接、目录联接等重解析点时，脚本会在写入敏感字节前终止。请把备份放在支持 Windows ACL 的本地文件系统中。

## 已装 OpenWrt 后升级

使用当前管理地址、SSH 端口和对应新固件运行预检：

```powershell
python flash.py --mode openwrt --host root@192.168.1.1 --image alwayroute-v0.1.0-xiaomi-4a-gigabit-sysupgrade.bin
```

预检通过后，在同一条命令末尾加 `--apply --backup-dir ../private-backups/4a-upgrade-v0.1.0`。脚本先导出私有配置备份、上传并核验固件，再通过 `sysupgrade -T` 检查后执行保留配置升级。现有 LAN、认证和无线等配置按 OpenWrt 备份规则保留；个人旧镜像的管理设置也会保留。升级前确认重要的自定义文件已进入备份列表；完整配置和节点备份不要上传 GitHub。

## 重启后

- 保持供电，等待几分钟。SSH 断开或脚本退出码 `3` 表示写入命令已提交但完成状态待确认，**不要据此重复刷写**；先查看启动现象和备份目录中的 `flash-output.txt`。
- 原厂首刷后的公开镜像采用 OpenWrt 标准初始化：有线访问 `192.168.1.1`，SSH 端口 `22`，网页 `http://192.168.1.1/`。先设置 root 密码和无线，再进入 LuCI 的 AlwayRoute 页面添加节点。WAN 默认 DHCP，当前配方不含 PPPoE。
- 保留配置升级继续使用原来的管理地址和认证。系统重装会生成新的 SSH 主机密钥；核对新指纹后单独处理信任记录，不关闭主机检查。
- 核对新系统版本、LAN／无线、AlwayRoute 页面和实际联网。CI 构建与镜像检查通过不代表每版已经实机验收；既有证据与限制见 [当前状态](https://github.com/Always1010/AlwayRoute/blob/main/docs/status.md)。

原厂 OS1 首刷与 OpenWrt 升级不能互换命令。项目已有备份和重启恢复证据，物理恢复写回尚未实测；操作前准备外置备份和可接触设备的恢复条件，异常处理见 [恢复说明](https://github.com/Always1010/AlwayRoute/blob/main/docs/operations/recovery.md)。
