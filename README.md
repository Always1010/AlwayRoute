# AlwayRoute

让连接小米路由器 4A 的设备通过路由器统一使用代理服务，并通过 LuCI 网页管理节点、订阅、分流规则、运行状态和实时流量。

项目主线是自编 OpenWrt、sing-box 和轻量管理扩展。4A 独立提供管理和转发；电脑仓库保存自有源码、配方和补丁，Rock 5B 负责构建及设备联调。现有 PC → Rock → 4A 操作链路继续使用，PC 直连 4A 作为另一种环境配置支持，实际连通性仍需验证。

截至 2026-10-23，完整管理包和正式服务规则已集成 ROM，真实 VMess、透明 TCP／DNS、配置回退、保留配置升级和自动恢复已有实机证据。有限时长代理测试约 156–167 Mbps；物理断开 Rock、其他协议完整流量、UDP／IPv6 范围及长期耐久仍待验收。精确版本、测试条件和剩余门槛统一见[当前状态](docs/status.md)。

## 从这里开始

- [文档导航](docs/README.md)：使用、开发、构建、设备维护及历史证据。
- [需求与验收](docs/requirements.md)、[剩余实施计划](docs/implementation-plan.md)：产品范围和未完成工作。
- [开发流程](docs/development-workflow.md)、[环境配置](docs/operations/environments.md)：PC 源码主本、Rock 增量构建、经 Rock 或直接访问设备。
- [固件构建](firmware/README.md)、[上游源码获取](docs/upstream-sources.md)：固定输入、自有包、核心及镜像检查。
- [接口契约](contracts/v1.md)、[测试入口](tests/README.md)：前后端边界与针对性检查。
- [开发工具](docs/developer-tools.md)、[隐私与首次公开](docs/privacy-and-publication.md)：正式入口、本地历史文件及审查范围。
- [设备适配与拓扑](docs/devices/xiaomi-4a.md)、[执行报告索引](docs/reports/README.md)：公共设备边界、验证条件和失败记录。

## 仓库内容

| 目录 | 职责 |
| --- | --- |
| `firmware/` | 自有 OpenWrt 包、构建 seed、上游补丁及固件工具 |
| `contracts/` | 配置模型、RPC 契约及合成样本 |
| `config/` | 可公开的规则来源锁和环境示例；真实环境保存在被忽略的 `.local/` |
| `scripts/` | 上游源码获取、环境驱动的同步与设备只读／暂存入口 |
| `tests/` | 主机、后端、界面、集成检查及离线预览 |
| `docs/` | 当前状态、需求、工作流程、设备适配与历史证据 |

完整放置规则见[仓库结构](docs/repository-structure.md)。第三方源码按版本与哈希下载到 `.local/sources/`，不重复纳入 Git；工具链、缓存、固件、备份、真实节点／订阅及密钥不进入仓库。新依赖和本机环境变更须单独获准；仓库整理不代表已经完成设备部署或获得刷机授权。

自有工具和文档采用 MIT，其他组件保留既有许可；范围与第三方来源见[许可证说明](LICENSE.md)及[第三方声明](THIRD_PARTY_NOTICES.md)。
