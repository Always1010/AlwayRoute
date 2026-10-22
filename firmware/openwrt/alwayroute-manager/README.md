# AlwayRoute 配置管理后端

OpenWrt rpcd ucode 插件，使用镜像已有的 ucode/fs/digest、uclient-fetch 与 procd。
没有额外 Go、Python 或 Node 常驻进程。所有配置写入按需短期 worker 执行，
LuCI 长操作轮询 job_status，不占用 rpcd 执行订阅抓取或核心重启。
接口及模型详见 [v1契约](../../../contracts/v1.md)。

包安装 root-only 配置库 `/etc/alwayroute/`、rpcd ACL、init 脚本及每小时第17分的
订阅更新 cron。cron 只更新保存配置，管理员须显式应用，避免定时改变现有转发。
下载仅 HTTPS、默认验证证书、20秒总时限、128KiB上限；不使用公共转换服务。
固定镜像未编BusyBox timeout，本包使用一次性POSIX shell watchdog约束下载进程，
完成后清理计时子进程，无需安装timeout或改变BusyBox配置。
URL会出现在短期root下载进程参数中，不写日志、coreAPI或普通状态；完整配置仅有管理写权限可读。

持久文件职责：

- `current.json`：用户保存草稿及revision。
- `lastgood.json`：最近通过核心加载与转发适配器确认的模型；出口健康仍为unverified。
- `previous.json`：上一份应用模型，供保存草稿相同于lastgood时回退。
- `applying.json`：小型提交标志，未清除则下次启动从previous重建，避免半提交配置。
- `service.json`：用户启停选择；停止后重启不会自动恢复代理。
- `subscription-status.json`：最多16个当前来源的更新时间、成功状态及脱敏错误码。

每份模型最多128KiB，三份持久副本最多384KiB；原子写候选峰值增加128KiB。
`/tmp/alwayroute/`放置生成运行配置、订阅正文、作业进度、实时检查和最多20条脱敏事件，
不将流量历史写闪存。凭证目录0700，文件0600。flock非阻塞锁配CLOEXEC，防后台子进程继承锁。

应用流程：expectedRevision校验 → 生成 → `sing-box check` → 转发prepare →
procd restart → loopback API检查所有selector实际选择 → 转发activate → 提交lastgood。
失败先尝试恢复之前运行状态，再尽力恢复持久元数据；闪存写失败也不能跳过核心恢复。
核心重启前先建立故障阻断，init停止阶段按重启标志维持阻断，待核心确认后激活代理。
恢复失败保持阻断，不自动撤销转发变成直连；仅显式停止或Direct模式恢复基础联网。
显式停止若无法撤销自有转发规则，返回FORWARDING_STOP_FAILED并保留核心和启动设置。
重启从lastgood或未完成事务的previous重建；短期post-start确认器核实进程和selector后才启动转发。
coreAPI只监听127.0.0.1:9090，混合代理只监听127.0.0.1:7890。

转发包为必需依赖，提供 `/usr/libexec/alwayroute-forwarding prepare|activate|guard|stop|status`，
前三个以退出码报告结果，status输出JSON。读取固定`/tmp/alwayroute/runtime.json`；
应以运行配置中的clash_api.default_mode识别模式，而非读取尚未应用的current模型。
适配器缺失或失败时不报告应用成功；capabilities明确保持forwarding=unverified。

生成器固定针对 sing-box 1.13.21，支持 VMess TCP/WS、TLS、Rule/Global/Direct、
按序IPv4/IP-CIDR/域名/后缀规则、reject、Proxy及业务selector单层跟随。
DoH走Proxy，bootstrap用路由器系统DNS；直连域名使用bootstrap。缓存512，DNS IPv4-only。
IPv6 LAN绕行阻断及IPv4 TCP/UDP TProxy由转发包实施，管理访问豁免亦由其保证。

订阅解析范围故意有限：VMess URI、整体base64 URI列表、仅含proxies数组的Clash JSON、
精简Clash YAML块列表。YAML用逐字符token及缩进解析，未使用正则抽取字段；
锚点、标签、flow map/数组、多行字符串、未知字段、其他协议、跳过证书验证和udp:false均拒绝。
不宣称支持任意Clash YAML。示例仅使用example.invalid及全合成UUID。
节点连接身份(type/server/port/uuid)SHA256生成稳定ID；改名不变ID；
覆盖与排除独立保存，更新消失选中或被引用节点时拒绝整个更新，原数据保留。

验证命令（使用已有ucode，不安装依赖）：

```sh
python tests/manager/run-tests.py /path/to/ucode -
ucode -L firmware/openwrt/alwayroute-manager/files/usr/share/ucode tests/manager/run.uc
```

第一项将模块机械组合到stdin，运行18项模型/导入检查和20项内存适配事务检查；
第二项检查真实模块导入。事务适配器覆盖revision冲突、后台排队、配置校验失败、
提交写失败恢复、回退、凭证导出脱敏、停机持久、启动中断恢复、转发停止失败、
适配器缺失及核心恢复失败保持阻断，未访问设备。
已在现有Rock host ucode执行；三种模式的生成JSON亦通过现有ARM64 sing-box1.13.21真实check。

仍需目标环境验证：rpcd会话ACL、procd异步时序、uclient TLS与实际订阅、重启及断电恢复、
LAN终端DNS/UDP/IPv6防绕行、实际出口/吞吐/资源。进程存活、API加载确认和单节点延迟
分别展示；任何一项都不替代LAN终端验收。生产代码没有fixture或mock状态回退。
