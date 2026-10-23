# TikTok、国内直连与策略组 DNS 分流部署记录

> 历史执行快照：日期和结论限于本轮；当前部署见[状态](../status.md)，先后关系见[报告索引](README.md)。私有路径以角色占位，示例命令不是当前操作入口。

2026-10-23（Asia/Shanghai）。本轮在最新整机刷写和性能复测之后，按用户要求通过后端接口新增 TikTok、国内直连两个组，Other 保持代理，并修复策略组直连时的 DNS 选择。未重新编译或替换 sing-box、未刷机、未重启设备、未安装本机软件或修改本机环境，也未推送 Git。源码修改仅覆盖管理后端 `model.uc`，以文件覆盖形式部署到设备 overlay。

## 配置结果

保存和应用 revision 从 19 更新为 20，策略组从 8 个变为 10 个：

| 组 | 设备保存选择与核心实际选择 |
| --- | --- |
| TikTok | Proxy |
| 国内直连（ID 为 Domestic） | direct |
| Other | Proxy，保持原选择 |

原有节点、订阅、覆盖设置和其余组选择保持。Other 仍位于组列表末尾。后台 configure job 成功，服务与透明转发均运行；`healthy` 保持原有的 `unverified`，不把有限测试改写为全面交付验收。

当次使用的公开数据现已归入管理包的完整 [YouTube](../../firmware/openwrt/alwayroute-manager/files/usr/share/alwayroute/policies/youtube.json)、[TikTok](../../firmware/openwrt/alwayroute-manager/files/usr/share/alwayroute/policies/tiktok.json) 和[国内服务](../../firmware/openwrt/alwayroute-manager/files/usr/share/alwayroute/policies/domestic.json) 规则集；当次组合顺序与规则数量由本文记录，旧清单可从 Git 提交 `1e27197a89b31ee9e73a6c7c98ad619218b0086b` 还原，当前维护方式见[分流数据说明](../../config/routing/README.md)。当前 YouTube 文件为完整服务，不能视作当时 4 条补充规则的快照，历史值与顺序需从上述 Git 提交还原。上游参考固定为 V2Fly domain-list-community 提交 `5b6a77d14fb904a1255f02e2e1b2bcc36ed31f83`，[来源锁文件](../../config/routing/sources.lock.json)记录 33 个参考文件的 URL 和 SHA-256；不是设备自动下载的全量规则库。后续正式项目整理没有改写本文记录的设备 revision 20 部署事实。

| 自定义规则 | 数量 | 内容 |
| --- | --- | --- |
| YouTube 补充 | 4 | ggpht.com、ggpht.cn、yt3.googleusercontent.com、youtubei.googleapis.com |
| TikTok | 38 | 主站、API、区域 CDN、直播、共享 CDN 精确主机及设备采样关联资源 |
| 国内直连 | 78 | 常用软件业务／资源域名、精选主机及最后的 cn 后缀补充 |
| 合计 | 120 | 当前后端上限 128，剩余 8 条 |

国内覆盖腾讯／微信／QQ、淘宝／支付宝、京东／拼多多、抖音／豆包、哔哩哔哩、小红书／快手、爱奇艺／优酷／芒果、百度／网盘、网易、美团／点评／饿了么、高德／滴滴／携程、WPS 国内资源／钉钉／飞书、知乎／微博、小米及部分银行。`.cn` 补充还覆盖许多其他国内域名；不能据此保证服务器地理位置或某个 App 的每一条连接。

YouTube、TikTok 明确规则在国内规则之前。共享云/CDN未整段归入直连：例如仅为淘宝的四个明确 alicdn 主机添加规则，未添加整个 alicdn.com；ibyteimg.com 上的 TikTok 关联资源也使用精确域名。WPS 国际主站 wps.com 未整段直连。

## DNS 修复

旧生成器只为规则直接写成 `outbound: direct` 的域名生成 bootstrap DNS 规则。规则指向选择 direct 的策略组时仍落入默认 proxy-dns。

新生成器为所有启用的自定义域名规则及内置业务域名按原有顺序生成 DNS 规则，解析组当前选择及允许的单层 Proxy 引用：实际选择 direct 时使用 bootstrap，其他情况使用 proxy-dns。保留显式代理例外，避免被后续宽泛直连 DNS 规则覆盖；停用规则、IP/CIDR 不生成域名 DNS 规则。全局／直连模式不应用这些业务 DNS 规则。修改组选择须通过 configure 应用才能同步重建 DNS。

运行配置包含 127 条 DNS 规则，即 120 条自定义域名规则与 7 条内置业务规则。国内规则使用 bootstrap，TikTok、YouTube 及 Other 默认使用 proxy-dns。设备 bootstrap 为本机解析，当前系统解析指向回环 dnsmasq，其 WAN DNS 为已有运营商 DNS；本轮没有修改 resolv、DHCP 或 WAN 配置。

## 部署与检查

源码先通过 rsync dry-run 审核，再同步到 Rock 独立工作副本，未向 OpenWrt 构建树同步。使用 Rock 已有 host ucode 检查，不安装依赖。通过 62 项模型检查、63 项事务检查、8 项下载权限检查；新增用例覆盖直连组、跟随 Proxy、选择切回代理、内置直连组、规则优先级及模式隔离。公开规则清单另通过唯一性、数量和共享 CDN 范围检查。

部署前把原管理模型、current、lastgood、服务设置、运行配置、后端源文件及状态保存到 Rock 的私有目录，目录 0700，文件 0600。先在 host 生成候选，并在设备执行 sing-box check，随后原子替换 model.uc，调用 alwayroute.configure。后台任务通过新进程加载新生成器，无需重启 rpcd。检查实际运行配置与校验过的候选逐字段相同。

首次 configure 使用 SSH 命令参数传输较长 JSON 时，SSH 断开；确认原模型和运行 revision 19 均未改变后恢复原 model.uc。随后改为通过标准输入运行 ucode，使用现有 ubus 模块调用相同 alwayroute RPC，成功提交 revision 20。没有通过重试覆盖未知的提交结果。

实机检查包括 21 个运行路由／DNS 匹配样例，涵盖国内域名、TikTok、YouTube、OpenAI、未知域名及共享 CDN 非目标主机。实际结果：

| 检查 | 结果 |
| --- | --- |
| LAN UDP DNS：百度 | rcode 0，3 条回答，25 ms |
| LAN UDP DNS：豆包 | rcode 0，18 条回答，31 ms |
| LAN UDP DNS：i.ytimg.com | rcode 0，11 条回答，228 ms |
| LAN TCP DNS：百度 | rcode 0，3 条回答，8 ms；此前查询可能已预热缓存 |
| HTTPS：百度 | 200 |
| HTTPS：豆包主页 | 302，未跟随跳转，不宣称完成 App 全功能检查 |
| HTTPS：YouTube 样例缩略图 | 200，15,921 字节，约 1.16 秒 |
| HTTPS：TikTok robots.txt | 200，不能等同视频播放验收 |

DNS 查询从 Rock 的 LAN 地址发往 4A。HTTPS 测试通过临时 SSH 转发连接路由器回环 mixed 入站，证书验证开启，未禁用 TLS 验证；测试后隧道退出。该部分不冒充 LAN 透明 HTTPS 验证。实际 LAN 终端连接另有如下记录：

- frontier100-audio-ime-quic-lq.doubao.com：由原 Other → Proxy 变为 Domestic → direct，有接收数据。
- frontier5-audio-ime-ws-lq.doubao.com：Domestic → direct，有接收数据。
- dig.bdurl.net：精确域名规则 → Domestic → direct，有接收数据。
- 测试缩略图 i.ytimg.com：YouTube → Proxy。
- 测试 www.tiktok.com：TikTok → Proxy。

DNS 服务器选择由实际运行配置核对，并完成真实 LAN DNS 查询；本轮未抓取 WAN DNS 数据包，不把查询时延当作上游链路的独立证明。

## YouTube 排查边界

用户报告 Other 直连时，YouTube 移动端视频可播放但列表封面失败；Other 代理后恢复。排查期间未捕获原移动端失败的图片连接，不能确认具体故障域名、连接识别或缓存原因。

已确认原预设遗漏 ggpht.com，并补充 ggpht.cn 以及两个 YouTube 专用子域的组归属；这些是规则完整性改进，不作为已复现故障根因。样例缩略图请求已成功并命中 YouTube，但不能据此声称原移动端问题彻底修复。按用户决定，最终 Other 保持代理、国内服务明确直连。

## 保持项、空间与回退

- sing-box SHA-256 保持 `0c8f208383bf790a89e03be83f9b953ebe490cad64c403d4e58087f6c36722b2`。
- 设备 boot ID 保持 （具体运行标识省略）。
- network、dhcp、wireless、dropbear、uhttpd 配置哈希均与本轮操作前相同。
- 部署的 model.uc SHA-256 为 `5325103dd53cc1dd8bee1ccf0016cd980d24b8573479ef8a2e6f0304dff0925f`，与本机仓库源文件相同。
- overlay 可用空间从本轮操作前 1412 KiB 变为 1372 KiB。当前 ROM 内仍是上次刷写版本，此次 DNS 修复由 overlay 覆盖；包版本元数据未因直接文件部署而更新。
- 私有备份与验证证据位于 Rock 的 `<private-verification>`。其中含真实配置，不回传仓库。首次失败尝试的备份单独保留在同级 `routing-20261023/`。

回退时先核对当前 revision 与后台任务状态，恢复备份中的 before-model.uc，再把 before-model.json 的模型 revision 更新为当前 revision，通过 configure 提交完整旧模型并等待成功；不得直接把旧 revision 文件覆盖到 current。配置事务失败仍使用已有 lastgood 恢复机制。设备临时候选文件清理，私有备份保留。
