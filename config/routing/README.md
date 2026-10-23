# 经审查的分流配置数据

这里保存供管理后端接口合并使用的公开分流数据。文件按业务拆分，组合记录只引用业务清单，不重复保存规则；上游来源统一锁定在一个文件。它们不包含节点、订阅或设备凭据，不会自动安装进固件，也不能原样传给 sing-box 或作为订阅导入。

| 文件 | 职责 | 2026-10-23 规则数 |
| --- | --- | --- |
| [profiles/tiktok.json](profiles/tiktok.json) | 只保存 TikTok 分组和规则，初始跟随 Proxy | 38 |
| [profiles/domestic-direct.json](profiles/domestic-direct.json) | 只保存国内直连分组和规则，初始选择 direct | 78 |
| [profiles/youtube-supplement.json](profiles/youtube-supplement.json) | 只补充已有 YouTube 组的域名，不新建该组 | 4 |
| [sources.lock.json](sources.lock.json) | 33 个上游参考文件的固定提交、URL 和 SHA-256 | 不含分流规则 |
| [deployments/2026-10-23-revision-20.json](deployments/2026-10-23-revision-20.json) | 记录 revision 20 使用的清单及组合顺序、Other 出口和数量 | 合计 120 |

业务清单的 `sources.manifest` 指向公共来源锁文件，`sources.files` 列出本清单参考的来源名称。`groups` 是需要补充的策略组，`routes` 是有序规则块，每个块的 `values` 按顺序展开为单条后端自定义规则，`category` 和 `evidence` 仅作审查说明。组合记录的 `profileFiles` 按顺序加载，路径相对组合记录本身解析；先合并各清单的组，再依次展开各清单规则。

## 合并与应用

目前没有自动导入器。通过现有 `configure` 接口应用时，先读取最新模型，保留原节点、订阅及已有选择；在 `Other` 之前添加清单中缺少的组，确认 YouTube 等被引用的已有组存在，再合并规则。每个 value 占一条自定义规则，规则 ID 应由出口、类型和值稳定生成。`existingGroupSelections` 记录此次组合要求的已有组出口，应明确核对后设置；不能覆盖其他已有选择。

提交使用最新 `expectedRevision`，等待后台 job 成功并读取核心实际选择。`appliedRevision` 仅记录当次部署版本，不能代替提交时读取的最新 revision。已有规则不得覆盖或静默删除，合并前按实际去重结果重新计算当前后端的 128 条限制；120 条只表示这一组合本身的数量。

2026-10-23 组合将 YouTube、TikTok 明确规则放在国内 `.cn` 补充之前，Other 保持代理。共享云和 CDN 只补明确主机或专用子域，不将整个 `ibyteimg.com`、`alicdn.com`、`aliyuncs.com` 等设为直连。WPS 的国内 `.cn` 域名及 `wpscdn.com` 在国内范围内，未将国际主站 `wps.com` 整体直连。

数据是常用服务的选择性覆盖，不代表每个 App 的所有请求或服务器地理位置，只在规则模式下生效。DNS 由后端按规则顺序及策略组当前实际出口生成；选择变更须通过 `configure` 应用，直接修改核心 selector 不会同步重建 DNS。设备采样关联主机在 `evidence` 中说明；YouTube 清单补齐已知遗漏与专用子域归属，不代表复现过原封面故障。

## 维护与迁移

新增业务规则修改对应 `profiles/` 文件；更新来源时修改 `sources.lock.json` 并核对相关清单引用；需要记录不同业务的组合时，在 `deployments/` 添加按日期和部署版本命名的记录，避免把多个业务重新塞进某个单一业务名称的文件。组合记录引用清单的当前版本，历史规则的精确内容通过对应 Git 提交还原。

原 `scripts/routing-profiles/cn-tiktok.json` 将国内、TikTok、YouTube 三类规则混在同一文件。本次仅调整仓库组织，将它拆为上述文件，保留原 120 条规则、顺序、出口、两组初始选择和来源元数据；没有通过接口重新应用，设备 revision 20 未改变。部署结果见[分流部署记录](../../docs/reports/2026-10-23-domestic-tiktok-routing.md)。
