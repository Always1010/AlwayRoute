# AlwayRoute 配置管理后端

OpenWrt rpcd ucode 插件，使用镜像已有的 ucode/fs/digest、uclient-fetch 与 procd。
没有额外 Go、Python 或 Node 常驻进程。所有配置写入按需短期 worker 执行，
LuCI 长操作轮询 job_status，不占用 rpcd 执行订阅抓取或核心重启。
单节点、整订阅、多选及全部来源连通性／延迟检测复用该 worker 与已加载核心，默认串行，支持逐行进度、失败重试与取消。
取消在当前一次有超时限制的探测结束后生效；已完成结果保留在/tmp，不写闪存，检测不重启或切换代理。
接口及模型详见 [v1契约](../../../contracts/v1.md)。

包安装 root-only 配置库 `/etc/alwayroute/`、rpcd ACL、init 脚本及每小时第17分的
订阅更新 cron。cron 只更新保存配置，管理员须显式应用，避免定时改变现有转发。
正式服务规则随包安装到 `/usr/share/alwayroute/policies/`，由 `catalog.json` 文件名数组索引，
每个服务独立 JSON 保存域名后缀与精确域名。该目录不列入 conffiles，随包升级替换；
规则维护、匹配语义与来源锁统一见仓库 [config/routing/](../../../config/routing/README.md)，不维护第二份预设说明。
包目录由 OpenWrt `package.mk` 递归追踪，修改服务数据参与增量重建。
国内组另引用 `/usr/share/alwayroute/rules/` 中的通用域名和目的 IP 二进制集合，
路由与 DNS 共享域名数据；未匹配域名解析后先重查手工地址覆盖，再进行国内 IP 补漏。
这些构建主机生成的外部输入由 `PKG_FILE_DEPENDS` 跟踪，不进入用户模型和 capabilities 大数组，
也不在设备启动时联网下载。构建命令、版本锁与第三方许可仍以规则维护说明为准。
下载默认仅 HTTPS、默认验证证书、20秒总时限、128KiB上限；不使用公共转换服务。
每个订阅可由管理员显式设置`allowHttp:true`，仅为该来源允许http://输入；
缺字段、false或非布尔true均不构成许可。HTTP没有传输加密，不全局放开，也不允许其他scheme。
固定uclient-fetch源码自动跟随最多10次重定向，没有CLI关闭或限制选项，
因此不能保证重定向链阻止HTTPS降级；只严格约束初始URL，不添加猜测参数。
固定镜像未编BusyBox timeout，本包使用一次性POSIX shell watchdog约束下载进程，
完成后清理计时子进程，无需安装timeout或改变BusyBox配置。
URL会出现在短期root下载进程参数中，不写日志、coreAPI或普通状态；完整配置仅有管理写权限可读。

持久文件职责：

- `current.json`：最新确认配置及revision；旧save/select接口也可保存待应用草稿。
- `lastgood.json`：最近通过核心加载与转发适配器确认的模型；出口健康仍为unverified。
- `previous.json`：上一份应用模型，供保存草稿相同于lastgood时回退。
- `applying.json`：提交标志及原启停设置；configure/rollback还保存原current，未清除时读取与启动恢复旧配置，避免半提交配置。
- `service.json`：用户启停选择；停止后重启不会自动恢复代理。
- `subscription-status.json`：最多16个当前来源的更新时间、成功状态及脱敏错误码。

每份模型最多128KiB，三份持久副本最多384KiB；configure提交标志还暂存一份原current，原子写候选另增加最多128KiB。
`/tmp/alwayroute/`放置生成运行配置、订阅正文、作业进度、实时检查和最多20条脱敏事件，
不将流量历史写闪存。凭证目录0700，文件0600。flock非阻塞锁配CLOEXEC，防后台子进程继承锁。
读取current时按原始文件字节缓存已通过完整校验的模型，并始终返回独立副本；内容改变立刻重新校验，损坏文件不能回退旧缓存，applying.previousCurrent仍按事务恢复规则处理。
事务内最多缓存三份字节相同的已验证模型，避免current/lastgood/恢复副本反复校验；候选在revision递增后完整校验一次。内部generateValidated只接收已验证且未再改动的模型，公开generate仍完整校验，避免重复校验有效节点。

应用流程：expectedRevision校验 → 生成 → `sing-box check` → 转发prepare →
procd restart → loopback API检查所有selector实际选择 → 转发activate → 提交lastgood。
即时configure在单个后台事务完成模型规范化、revision校验与递增；运行时通常复用上述确认流程，
最后提交current及lastgood并清除标志。包括current保存失败在内的错误均恢复旧current及运行态，
未清标志保留旧current作为读取和断电恢复依据。服务停止时只校验并保存current，保持停止；
service.start使用最新current，确认后lastgood/state对应同一revision，不会启动旧选择。
只改变已有策略组选择、并且生成配置除了selector默认选择外完全相同时，使用核心PUT接口热切换，保留当前连接，不重启核心。
该分支先核对saved/applied/lastgood、旧运行配置、实际选择与转发状态，仍使用相同applying标志、三次sync、previous及current/lastgood提交协议，更新/tmp运行配置默认值并读回确认。
任一步失败沿用完整核心恢复与故障阻断；需要改变DNS规则、Other阻断、模式、规则或节点参数时继续完整应用，不能仅PUT伪造成功。
首页import/refresh使用activate:true，将解析后的节点候选交给同一确认流程，失败不提前保存节点；
import此时同样排入后台worker。省略activate继续保留原仅保存语义，cron仍不自动应用。
失败先尝试恢复之前运行状态，再尽力恢复持久元数据；闪存写失败也不能跳过核心恢复。
核心重启前先建立故障阻断，init停止阶段按重启标志维持阻断，待核心确认后激活代理。
恢复失败保持阻断，不自动撤销转发变成直连；仅显式停止或Direct模式恢复基础联网。
显式停止若无法撤销自有转发规则，返回FORWARDING_STOP_FAILED并保留核心和启动设置。
重启从lastgood或未完成事务的previous重建；短期post-start确认器核实进程和selector后才启动转发。
coreAPI只监听127.0.0.1:9090，混合代理只监听127.0.0.1:7890。
流量RPC立即读取/tmp短期样本，独立的一次性采样器读取核心流式接口，不占用rpcd等待采样。
样本携带时间戳、15秒有效期、revision与重启epoch，未采到/过期/服务停止显示不可用；最多每5秒启动一次，独立锁防重叠，无新依赖或常驻服务。

转发包为必需依赖，提供 `/usr/libexec/alwayroute-forwarding prepare|activate|guard|stop|status`，
前三个以退出码报告结果，status输出JSON。读取固定`/tmp/alwayroute/runtime.json`；
应以运行配置中的clash_api.default_mode识别模式，而非读取尚未应用的current模型。
适配器缺失或失败时不报告应用成功；capabilities明确保持forwarding=unverified。

生成器固定针对 sing-box 1.13.21，支持 VMess TCP/WS、TLS、Rule/Global/Direct、
按序IPv4/IP-CIDR/域名/后缀及正则规则、reject、Proxy及业务selector单层跟随；手工规则最多512条，每条128值，模型仍限128KiB。
DoH走Proxy，bootstrap用路由器系统DNS；直连域名使用bootstrap。DNS IPv4-only，
共享DNS缓存显式配置1024项，与固定sing-box 1.13.21的`max(options.CacheCapacity, 1024)`下限一致；
此前写512也会实际分配至少1024项，此次仅纠正配置与预算表述，不能算作缓存扩容或内存节省。
1024是条目容量预算，单条DNS消息长度及缓存管理开销可变，不能据此宣称固定KiB内存上限。
IPv6 LAN绕行阻断及IPv4 TCP/UDP TProxy由转发包实施，管理访问豁免亦由其保证。

订阅解析范围故意有限：VMess URI、整体base64 URI列表、仅含proxies数组的Clash JSON、
Clash YAML中的顶层proxies块。完整Clash其余监听、secret、proxy-groups及rules均忽略，不透传。
节点支持块形式或单行flow map标量，逐字符处理引号、转义、逗号和冒号；
YAML用逐字符token及缩进解析，未使用正则抽取字段。
锚点、标签、嵌套flow map/数组、多行字符串、未知节点字段、其他协议、跳过证书验证和udp:false均拒绝。
不宣称支持任意Clash YAML。示例仅使用example.invalid及全合成UUID。
节点连接身份(type/server/port/uuid)SHA256生成稳定ID；改名不变ID；
覆盖与排除独立保存，更新消失选中或被引用节点时拒绝整个更新，原数据保留。

验证命令（使用已有ucode，不安装依赖）：

```sh
python tests/manager/check-imports.py /path/to/ucode
python tests/manager/run-tests.py /path/to/ucode -
ucode -L firmware/openwrt/alwayroute-manager/files/usr/share/ucode tests/manager/run.uc
```

第一项保持import/export进行真实管理模块导入，不调用管理方法；第二项将模块机械组合到stdin，运行模型/导入、内存适配事务及下载脚本许可检查；
第三项检查模型与订阅的真实模块导入。事务适配器覆盖revision冲突、后台排队、配置校验失败、
提交写失败恢复、回退、凭证导出脱敏、停机持久、启动中断恢复、转发停止失败、
适配器缺失及核心恢复失败保持阻断，未访问设备。
即时配置事务另覆盖运行/停止态配置确认、最新current启动、导入/订阅节点候选失败保持原配置、
current写失败及提交标记清除失败恢复、中断读保护与恢复后继续配置；不会调用真实进程或服务。
已在现有Rock host ucode执行；三种模式的生成JSON亦通过现有ARM64 sing-box1.13.21真实check。
私有Clash订阅已有解析与设备联调证据，仓库仅含合成fixture；URL、节点值、凭证与原始样本不公开。

当前设备证据与剩余验收统一见[状态](../../../docs/status.md)，包括断电恢复、UDP／IPv6范围与长期资源边界。进程存活、API加载确认和单节点延迟分别展示，任何一项都不替代LAN终端验收。生产代码没有fixture或mock状态回退。
