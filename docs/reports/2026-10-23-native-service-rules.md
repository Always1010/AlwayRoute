# 正式服务目录、多值规则与整机部署

> 本报告是最后记录的ROM部署依据；后续仓库整理未重刷设备。当前验收边界见[状态](../status.md)。私有路径以角色占位。

2026-10-23（Asia/Shanghai）。接续国内／TikTok 分流配置，按用户要求将服务数据纳入正式初始项目：完整 YouTube 规则归入 youtube.json，移除补充文件与按日期组织的当前配置，原生服务不占手工规则额度；实现多值与正则规则，并完成保留配置整机升级。

## 当前结果

| 项目 | 最终状态 |
| --- | --- |
| 保存／应用 revision | 23，policyVersion 2 |
| 用户模型 | 原有38个节点、1个订阅、10个策略组；原通用120条迁出，手工规则0条 |
| 手工容量 | 512条，每条最多128个值；整体模型仍限128KiB |
| 正式服务目录 | 15个服务，共196个后缀与16个精确域名 |
| 生成路由／DNS块 | 路由11块（含DNS接管和嗅探），DNS 9块；迁移前129／127块 |
| Other | Proxy；刷前最新revision 22时曾被切为direct，本轮按用户前述明确要求设回代理 |
| 国内组 | direct，对应域名DNS使用本机bootstrap |
| TikTok | 保留刷前单独选择的节点，未改回跟随Proxy |
| 运行状态 | 代理与透明转发运行，Wi-Fi双频和WAN up；healthy保留unverified |

## 项目数据结构

唯一生产数据源为 [policies](../../firmware/openwrt/alwayroute-manager/files/usr/share/alwayroute/policies/)；catalog.json 是文件名索引，每个服务只保留一份 JSON，由管理包安装到 `/usr/share/alwayroute/policies/`。model.uc不再硬编码第二套域名数据。

- [youtube.json](../../firmware/openwrt/alwayroute-manager/files/usr/share/alwayroute/policies/youtube.json) 合并完整7个后缀及2个精确域名。
- [tiktok.json](../../firmware/openwrt/alwayroute-manager/files/usr/share/alwayroute/policies/tiktok.json) 含30个后缀及8个精确域名。
- [domestic.json](../../firmware/openwrt/alwayroute-manager/files/usr/share/alwayroute/policies/domestic.json) 含72个后缀及6个精确域名。
- 其余服务的数据、名称和用途保留；全新模型默认10组，国内与Other初始direct，其他业务跟随Proxy。本设备Other为用户要求的Proxy。

`config/routing/`只保留上游来源锁与审查说明，不再存第二套业务 profiles 或部署日期配置。历史部署事实在报告中维护，旧值与顺序由Git还原。Rock独立工作副本中遗留的旧混合文件已按明确路径归档，不清理第三方源码、工具链、缓存或备份。

## 规则模型与兼容迁移

手工规则支持 `values` 数组，旧 `value` 单值继续兼容，两者必须恰有一个。域名、后缀、IPv4、CIDR和regex均可按同类型多值生成一个匹配块；每条上限128值。网页按行编辑、去空行和有序去重，保留正则中的逗号；列表显示有限摘要，完整内容放在title；容量由capabilities读取，达到上限仍可编辑已有规则。

普通服务使用精确域名／后缀列表，无需为明确的域名清单制造复杂正则。手工regex映射为核心domain_regex，由sing-box check在应用前验证。DNS保持对应域名与正则的顺序及组出口解析。自定义规则优先，专属业务优先于Proxy境外预设，明确境外预设优先于宽泛国内后缀；Domestic不并入Proxy聚合。

policyVersion 1升级到2时，仅移除仍启用、单值、类型／域名／出口与正式目录相符，且ID符合原自动生成算法的规则。编辑过、停用或自行创建的规则保留；保留已有组、节点、订阅和覆盖设置。缺少TikTok／Domestic时在容量允许的条件下添加；当前版本不会补回用户后来删除的组。无版本旧配置使用同样的国内默认出口逻辑。删除YouTube等专属组后，已知境外域名仍由Proxy兜底。

## 检查与设备问题修复

最终通过73项模型检查、63项事务检查、8项下载权限检查、35项UI检查和17项UI/RPC/ACL契约检查。新增覆盖多值、正则、容量、旧格式编辑、原自动规则迁移、用户覆盖保留，以及缺组和旧版本默认出口边界。真实配置迁移预演对410个域名样例比较结果一致，候选通过设备核心检查。

首轮r3整机升级后，保存迁移的后台作业没有及时启动，记录JOB_INTERRUPTED，原revision 22及转发继续运行；没有将失败提交记作已生效。定位到新目录加载器的域名校验：`{1,253}`范围正则在设备上对各域名重复编译，实测目录加载33.025秒、后台入口33.085秒，超过既有无PID作业启动窗口。

修复为显式检查非空和最大长度，再使用简单字符集正则，接受范围保持相同。设备对照为目录0.462秒、后台入口0.564秒，均含SSH开销。之后configure成功保存revision 23，并把此修复构建进manager r4再保留配置升级。最终ROM实测目录加载0.490秒，不依赖额外overlay补丁。两个实际sysupgrade均各自检查、备份并只发送一次；另一次刷前因核心状态快照短暂不可用而中止，未发出sysupgrade。

## 最终固件与刷后证据

| 项目 | 最终结果 |
| --- | --- |
| 设备 | xiaomi,mi-router-4a-gigabit |
| 管理包 | alwayroute-manager 1.0.0-r4，luci-app-alwayroute 1.0.0-r3 |
| 镜像字节 | 13,501,006 |
| 镜像SHA-256 | 7069fd419b9292e68461a65f938792f245d45886689228e576b20acc30b6cc05 |
| 核心SHA-256 | 0c8f208383bf790a89e03be83f9b953ebe490cad64c403d4e58087f6c36722b2，保持不变 |
| 镜像检查 | 294项通过，143个包；仅管理后端和网页包版本变化 |
| ROM／运行常驻文件 | 36／35项与最终镜像逐项一致 |
| 最终boot ID | 已变化并核对ROM，具体运行标识省略 |
| 最终升级保持项 | 13项关键配置哈希、10组选择、revision 23均保持 |
| overlay | 总1664KiB，已用236KiB，可用1428KiB |

复用Rock原构建树与下载／工具链缓存，定向同步两个管理包并增量打包，未重编或更换代理核心，未做全树清理。全部四个自有包的输入哈希与电脑源码核对，最终镜像与本机副本哈希一致。没有安装本机依赖、修改本机环境或远程push。

最终LAN UDP DNS：百度、豆包和i.ytimg.com均rcode 0、有回答；LAN TCP DNS百度也正常。21个实际运行路由／DNS匹配样例通过。证书验证开启的回环mixed代理HTTPS：百度200、豆包302、TikTok robots.txt 200；后者不等同移动端视频播放验收。网页JS通过HTTP读取并与最终镜像哈希一致。

YouTube样例缩略图初次请求发生TLS连接重置；随后两次有界复核均200、各15,921字节，约0.97秒及4.83秒，连接记录明确命中完整YouTube规则并经Proxy。保留初次失败，不据此宣称原移动端封面故障根因已查明，也不将网络重置误判为漏规则。验证用临时SSH隧道已退出，格式校验候选文件已清理；没有关闭TLS验证。

## 产物与恢复

本机被Git忽略的 `artifacts/native-services-r4-20261023/` 保存最终镜像、检查结果、四包源码绑定、版本变化、刷后快照及SHA256SUMS。Rock对应目录为 `<task-root>/artifacts/native-services-r4-20261023/`。

原revision 22／policyVersion 1及37文件配置备份位于Rock `<private-backup>`；最终r4刷前revision 23／policyVersion 2备份在同级 `native-services-r4-20261023/`。备份目录0700、文件0600，不复制到公开产物或Git。需要回退到不支持policyVersion 2的旧管理器时，必须配套使用升级前version 1配置备份，不能把新版模型直接交给旧后端。网络与缩略图复核证据保留在Rock私有 `private-probes/native-services-verification-20261023/`。
