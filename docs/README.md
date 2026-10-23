# 文档导航

项目概览见[仓库首页](../README.md)，当前部署身份与验收边界只在[当前状态](status.md)汇总。以下按要完成的工作选择入口。

| 目的 | 入口 |
| --- | --- |
| 了解范围及剩余工作 | [需求与A1–A9验收](requirements.md)、[实施计划](implementation-plan.md) |
| 修改自有代码 | [仓库结构](repository-structure.md)、[接口契约](../contracts/v1.md)、[测试入口](../tests/README.md) |
| 配置开发和联调环境 | [环境说明](operations/environments.md)、[访问与只读检查](operations/access.md) |
| 同步与构建 | [开发流程](development-workflow.md)、[上游源码获取](upstream-sources.md)、[固件构建](../firmware/README.md) |
| 选择正式工具与清理临时文件 | [开发工具清单](developer-tools.md) |
| 准备公开仓库 | [隐私与首次公开](privacy-and-publication.md)、[许可范围](../LICENSE.md)、[第三方声明](../THIRD_PARTY_NOTICES.md) |
| 维护分流数据 | [规则维护与来源](../config/routing/README.md)、[管理后端](../firmware/openwrt/alwayroute-manager/README.md) |
| 升级与恢复 | [部署检查边界](operations/deployment.md)、[恢复条件](operations/recovery.md) |
| 核对硬件与接线 | [4A适配及基本拓扑](devices/xiaomi-4a.md) |
| 查历史依据与失败 | [执行报告索引](reports/README.md)、[独立运行路线决策](reports/2026-10-22-route-decision.md) |

## 文档维护

- 需求定义产品范围，状态文件记录完成度，操作文档说明前提和步骤，报告保留当时事实；不要在多个入口复制版本表或部署流水账。
- 报告使用 `YYYY-MM-DD-主题.md`，文首注明日期、范围、状态和后续关系。相同日期的先后以报告索引和关联链接为准。
- 报告保留测试条件、失败、候选撤回及覆盖边界。修改错误时明确说明，不能将未执行写成已通过。
- 真实环境、主机身份、备份索引和私有测量保存在被忽略的 `.local/` 或受控远端；公开材料只含通用角色、必要硬件事实、版本、哈希和脱敏统计。
- 使用相对链接；路径改动后核对全部引用、脚本和测试。同步默认不删除远端旧文件，迁移后需按开发流程单独审查。
- 新增长期文档或报告更新本索引或报告索引；仅改变常用入口或产品能力时修改根 README。
