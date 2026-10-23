# 分流数据来源与历史记录

正式服务规则的唯一数据源是管理包的 [policies 目录](../../firmware/openwrt/alwayroute-manager/files/usr/share/alwayroute/policies/)，随 `alwayroute-manager` 安装到设备 `/usr/share/alwayroute/policies/`。本目录只保留 [sources.lock.json](sources.lock.json) 和来源说明，不保存另一套业务规则或按日期命名的部署配置。

## 正式服务目录

[catalog.json](../../firmware/openwrt/alwayroute-manager/files/usr/share/alwayroute/policies/catalog.json) 是按界面显示顺序排列的简单文件名数组；后端据此读取同目录服务文件。顺序为 Proxy、OpenAI、Claude、Google、YouTube、TikTok、X、Telegram、Domestic、Other、Microsoft、Apple、Meta、Discord、Steam。显示顺序与编译路由时的匹配优先级分别由后端处理；尤其 `.cn` 不能遮蔽 YouTube、TikTok 等明确业务。

每个服务使用独立小写文件名，例如 `youtube.json`、`tiktok.json`、`domestic.json`，统一字段为 `id`、`name`、`default`、`description`、`domains` 和 `exactDomains`。`domains` 是域名后缀，`exactDomains` 是精确域名；两个列表独立保存，避免把共享云或 CDN 的精确主机扩大成整个后缀。`default` 表示初始启用服务组，出口选择由模型负责。Other 的列表为空，作为最终出口。文件不含节点、订阅或设备凭据。

| 服务文件 | 后缀 | 精确域名 | 说明 |
| --- | --- | --- | --- |
| [youtube.json](../../firmware/openwrt/alwayroute-manager/files/usr/share/alwayroute/policies/youtube.json) | 7 | 2 | 主站、短链、视频、静态内容、头像及移动 API 的完整服务数据 |
| [tiktok.json](../../firmware/openwrt/alwayroute-manager/files/usr/share/alwayroute/policies/tiktok.json) | 30 | 8 | TikTok 主站、API、区域 CDN、直播及已确认关联主机 |
| [domestic.json](../../firmware/openwrt/alwayroute-manager/files/usr/share/alwayroute/policies/domestic.json) | 72 | 6 | 常用国内业务、明确资源主机和 `.cn` 后缀 |

其余 12 个原有服务的数据保持原有后缀列表，并显式提供空 `exactDomains`。正式 JSON 随包升级替换，不属于 `/etc/alwayroute/` 的 conffiles；修改包内数据会触发 OpenWrt `package.mk` 对包目录的递归增量依赖检查，无需单独下载或拷贝业务清单。

## 来源与审查范围

上游参考统一锁定在 [sources.lock.json](sources.lock.json)，固定 V2Fly domain-list-community 提交 `5b6a77d14fb904a1255f02e2e1b2bcc36ed31f83` 的 33 个文件 URL 和 SHA-256。这些是审查参考，正式服务数据是项目选择性维护的集合，设备不自动下载上游全量规则。来源锁仅供仓库维护，不随包安装；服务 JSON 无指向仓库的设备无效相对路径。

- YouTube 参考 `youtube`；`ggpht.com`、`ggpht.cn`、`yt3.googleusercontent.com`、`youtubei.googleapis.com` 已合并进完整 YouTube 服务文件。原封面故障未复现，不能据此宣称已经确定故障根因。
- TikTok 参考 `tiktok`；`p19-oec-va.ibyteimg.com` 和 `roovza.cdn-settings.appsflyersdk.com` 来自 2026-10-23 设备连接采样，只保留精确主机，不扩展共享域名后缀。
- 国内服务参考 `tencent`、`alibaba`、`jd`、`pinduoduo`、`douyin`、`doubao`、`bytedance`、`bilibili`、`bilibili-cdn`、`xiaohongshu`、`kuaishou`、`iqiyi`、`youku`、`hunantv`、`baidu`、`netease`、`meituan`、`eleme`、`amap`、`didi`、`ctrip`、`kingsoft`、`wps`、`dingtalk`、`feishu`、`zhihu`、`sina`、`xiaomi`、`cmb`、`ccb`、`geolocation-cn`。`mon.zijieapi.com`、`dig.bdurl.net` 为与豆包连接同时出现的采样主机。淘宝只保留 `img.alicdn.com`、`imgextra.alicdn.com`、`gw.alicdn.com`、`g.alicdn.com` 四个精确主机。

共享云和 CDN 不整段归入直连，例如不把整个 `ibyteimg.com`、`alicdn.com`、`aliyuncs.com` 设为直连。WPS 的国内 `.cn` 域名与 `wpscdn.com` 属于国内范围，未将国际主站 `wps.com` 整体直连。规则只在规则模式生效，选择性覆盖不保证每个 App 的所有请求或服务器地理位置。DNS 由后端依据规则顺序及策略组实际出口生成；组选择变更通过 `configure` 应用。

## 历史部署与维护

历史部署事实与验证结果统一放入 [docs/reports](../../docs/README.md)，不作为当前配置数据。revision 20 的旧值和顺序可从 Git 提交 `1e27197a89b31ee9e73a6c7c98ad619218b0086b` 的旧 profiles 还原，设备部署事实见[当次报告](../../docs/reports/2026-10-23-domestic-tiktok-routing.md)。

新增和维护业务只修改正式 `policies/` 服务文件，必要时更新 `catalog.json`；更新参考来源时修改本目录唯一的来源锁并核对上述审查说明。新的部署、迁移和测试结果写入报告，不再生成带日期的配置清单，也不复制业务规则。
