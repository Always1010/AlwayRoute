# 静态路由预设

管理器把少量稳定的域名后缀直接编译进 sing-box 配置，不在设备上下载或定时更新规则集。自定义规则始终排在这些预设之前；业务预设排在 `Proxy` 之前；全部未命中的流量最终交给 `Other`。因此用户可以用一条自定义规则覆盖任何内置判断。

新配置的 `Other` 默认为直连。旧配置首次读取时会把原 `defaultOutbound` 的实际选择迁到 `Other.selected`；旧选择为阻断时仍以最终拒绝规则实现，不会降级成直连。迁移会保留节点和自定义组；若旧配置已占满 16 个组且没有可合并的旧固定组用于腾出 `Other`，管理器会明确拒绝迁移，避免静默删除自定义组。

这些列表只覆盖各服务的主要网页、API、静态内容和媒体域名，**不是完整的网络准入清单**。服务商可能使用地区域名、第三方 CDN、云存储或随时调整主机名；游戏、语音、推送和流媒体尤其可能还有按 IP 或动态发现的端点。遇到漏分流时应添加自定义规则，并在升级固件时审查本文件与 `model.uc` 的差异。

编写本表时只参考服务商自己的文档：

- [OpenAI 的网络建议](https://help.openai.com/en/articles/9247338-network-recommendations-for-chatgpt-errors-on-web-and-apps)列出了 ChatGPT/OpenAI 应放行的主要域名。
- [GitHub 的 Copilot 网络准入参考](https://docs.github.com/en/copilot/reference/copilot-allowlist-reference)和[受限网络说明](https://docs.github.com/en/enterprise-cloud@latest/get-started/using-github/allowing-access-to-githubs-services-from-a-restricted-network)说明了 `github.com`、`githubassets.com`、`githubusercontent.com` 等域名，同时明确官方动态清单也不保证覆盖所有功能。
- [Microsoft 365 URL 与 IP 范围](https://learn.microsoft.com/office365/enterprise/urls-and-ip-address-ranges)说明了 Microsoft 365 的主域名及专用 `.microsoft` 域名；本预设只取适合家庭路由的少量域名后缀，不复制其庞大动态清单。
- [Apple 企业网络主机清单](https://support.apple.com/101555)列出了 Apple、iCloud、商店和静态内容域名，并说明部分 CDN 名称会变化。
- [YouTube 嵌入说明](https://support.google.com/youtube/answer/171780)明确使用 `youtube.com` 与 `youtube-nocookie.com`；YouTube 预设在 Google 之前匹配，避免视频域名先落入通用 Google 组。
- [Discord 官方域名迁移说明](https://support.discord.com/hc/en-us/articles/360042987951-Discordapp-com-is-now-Discord-com)确认 `discord.com`，并指出内容可能来自 `cdn.discordapp.com`。
- [Telegram 客户端配置](https://core.telegram.org/api/config)与[官方域名范围](https://core.telegram.org/bug-bounty)列出 `telegram.org`、`t.me`、`telegram.me`、`telesco.pe` 等官方域名。
- [X API 官方文档](https://developer.x.com/en/support/twitter-api/error-troubleshooting)使用 `api.x.com`；预设同时保留服务迁移前仍在使用的 `twitter.com` 与 `twimg.com` 后缀。

`Netflix`、`Disney+`、`Spotify` 与 `GitHub` 归入 `Proxy`，不再占用独立策略组。`Proxy` 的末尾内置规则使用整个预设目录域名的去重并集：已启用的业务组会在它之前先匹配；未启用的 `Microsoft`、`Apple`、`Meta`、`Discord`、`Steam`，以及被用户删除的默认业务组，则自然落入 `Proxy`，而不是 `Other`。完整目录由 `model.uc` 的 `policyCatalog()` 返回，界面与后端应读取该目录，而不是复制一份列表。
