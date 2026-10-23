# AlwayRoute

AlwayRoute 面向 OpenWrt 路由器，提供基于 sing-box 的代理管理与透明转发能力，通过 LuCI 网页管理节点、订阅、分流规则、运行状态和实时流量。

项目主线是自编 OpenWrt、sing-box 和轻量管理扩展，目标是由路由器独立完成管理和转发。通用功能、CPU 架构、设备适配与开发环境分别维护；构建主机和测试终端由开发者按实际环境选择。

当前首个实机验证目标为小米路由器 4A 千兆版（第一版）。其他型号与硬件修订需要独立适配、构建和验证，当前固件不能直接用于其他设备。支持边界见[设备列表与适配原则](docs/devices/README.md)。

截至 2026-10-23，在该设备上，完整管理包和正式服务规则已集成固件，真实 VMess、透明 TCP／DNS、配置回退、保留配置升级和自动恢复已有实机证据；其他协议完整流量、UDP／IPv6 范围、完整独立运行及长期耐久仍有待验收项。精确版本、设备性能和测试条件统一见[当前状态](docs/status.md)。

## 从这里开始

- [文档导航](docs/README.md)：使用、开发、构建、设备维护及历史证据。
- [需求与验收](docs/requirements.md)、[剩余实施计划](docs/implementation-plan.md)：产品范围和未完成工作。
- [开发流程](docs/development-workflow.md)、[环境配置](docs/operations/environments.md)：源码主本、独立构建副本、增量缓存及设备访问角色。
- [固件构建](firmware/README.md)、[上游源码获取](docs/upstream-sources.md)：固定输入、自有包、核心及镜像检查。
- [接口契约](contracts/v1.md)、[测试入口](tests/README.md)：前后端边界与针对性检查。
- [开发工具](docs/developer-tools.md)、[隐私与首次公开](docs/privacy-and-publication.md)：正式入口、本地历史文件及审查范围。
- [设备适配](docs/devices/README.md)、[移植方案](docs/device-porting.md)、[执行报告索引](docs/reports/README.md)：支持范围、适配层次、验证条件和失败记录。

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
