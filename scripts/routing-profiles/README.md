# 经审查的路由配置清单

`cn-tiktok.json` 保存 2026-10-23 实机配置使用的非敏感分流数据，不包含节点、订阅、设备配置或凭据，也不会自动安装进固件。上游参考固定到指定 Git commit，并记录所参考文件的 SHA-256。

此清单供现有后端 `configure` 接口合并使用：先读取最新模型，保留原节点、订阅及已有选择；在 `Other` 之前添加 `groups` 中缺少的组，再将 `routes` 按顺序展开为现有 `domain`／`suffix` 规则。每个 value 占一条自定义规则，规则 ID 应由出口、类型和值稳定生成。提交时使用最新 `expectedRevision`，等待后台 job 成功并读取核心实际选择。它不是可以原样传给 sing-box 或导入订阅的配置文件。

- `TikTok` 初始跟随 `Proxy`；`Domestic`（国内直连）初始选择 `direct`；`Other` 保持代理。
- 120 条规则包括 YouTube 补充 4 条、TikTok 38 条和国内直连 78 条，剩余 8 个自定义规则位置。合并已有规则前必须重新计算 128 条上限，不覆盖或静默删除用户规则。
- YouTube 与 TikTok 的明确域名位于国内 `.cn` 补充规则之前。共享云/CDN只补明确主机或专用子域，不将整个 `ibyteimg.com`、`alicdn.com`、`aliyuncs.com` 等设为直连。
- WPS 的国内 `.cn` 域名及 `wpscdn.com` 在国内范围内，未将国际主站 `wps.com` 整体直连。
- 数据是常用服务的选择性覆盖，不代表每个 App 的所有请求或服务器地理位置。只在规则模式下生效。
- DNS 由后端按规则顺序及策略组当前实际出口生成；选择变更须通过 `configure` 应用，直接修改核心 selector 不会同步重建 DNS。
- 设备采样关联主机在 `evidence` 中单独说明；不能将其视为已证实的 YouTube 故障根因。YouTube 条目补齐已知遗漏与专用子域归属，不代表复现过原故障。
