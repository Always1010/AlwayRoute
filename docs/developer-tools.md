# 开发工具与本地历史文件

正式入口与环境配置共同维护；真实环境、原始输出和退役脚本不进入公开源码。工具只复用已有运行时，不自动安装软件。

| 入口 | 用途与边界 |
| --- | --- |
| `scripts/fetch-sources.py` | 锁定上游源码获取／校验；保持独立于设备连接 |
| `scripts/build-routing.py` | 构建主机校验固定规则源并生成本地 `.srs` 与来源清单；显式允许下载，默认 IPv4，不安装工具或改写既有产物 |
| `scripts/sync-source.py` | PC 到独立源码副本；默认预览、应用要求计划一致、传输已校验快照、不删除远端文件 |
| `.local/lab/scripts/sync-rock.sh` | 使用本地 current 环境的兼容入口，也接受显式 `--env` |
| `firmware/tools/sync-packages.py` | 构建机把明确选择的自有包集成到 package；默认预览、完整哈希验证，目标旧文件拒绝且不删除 |
| `firmware/tools/render-management-defaults.py` | 显式读取部署策略生成待审首启脚本，不写构建树或设备 |
| `firmware/tools/target_profile.py` | 离线查看设备配方、组合seed；不修改构建树或启用补丁 |
| `firmware/tools/build-core.py` | 固定来源核心构建；环境参数与目标配方分开，实验必须显式选择 |
| `firmware/tools/run-native-build.py` | 同树增量构建监督；锁、并发、预算、产物新鲜度和大小保护 |
| `firmware/tools/inspect-image.py` | 按设备配方检查镜像及核心来源，未知格式拒绝，设备写入另行执行 |
| `scripts/device.py` | 白名单状态输出、默认离线暂存计划；显式 apply 才临时上传，不刷机 |
| `scripts/device-maintenance.py` | 只读预检、资源、私有快照与比较；backup 默认离线计划，显式 apply 才读取并验证配置备份 |
| `scripts/network-diagnostics.py` | 按 traffic 角色解析目标并查询实际 IPv4 路由，比较源地址／接口／网关，不修改网络 |
| `scripts/measure-https.py` | 按 traffic 角色执行有限 HTTPS 测量，不改变路由；需要已有 curl >= 8.4，结果不自动证明实际转发路径 |
| `firmware/tools/run-device-tests.py` | 已编译静态 MIPSLE 测试二进制的离线计划、只读预检及显式有界执行；资源不足拒绝，不停生产服务 |
| `firmware/tools/summarize-benchmarks.py` | 离线白名单汇总历史性能结果，保留测试条件、匿名化候选，不跨条件推导提升 |
| `scripts/audit-public.py` | 当前受跟踪文件、可达历史和可选对象库的脱敏候选检查，不替代人工复核 |

## 本地清单与归档

2026-10-23 整理前 `.local/` 根有 40 个 Python 任务脚本。逐项处理情况记录在私有 `.local/tool-inventory.json`，归档放 `.local/archive/2026-10-23/`。清单记录原文件名、分类、替代入口与必要的文件摘要，不复制口令正文。

- 旧加密候选构建和旧镜像检查已有正式替代，移入本地归档。
- 旧分流生成／部署／验证及退休配置已被正式规则和报告替代，移入本地归档，避免再次作为当前配置执行。
- 已完成的 rsync 准备、下载绕行与镜像探测脚本移入本地归档，不作为开发自动前置步骤。
- 日期构建编排的通用部分由包同步、构建监督和镜像检查入口承接；日期、版本、原基线和产物比较属于历史 run 数据。
- 剩余29份设备、密码测试、性能与协议实验脚本已逐项复核，可复用能力迁入上表正式入口，原文件完整移入私有归档，详见本地环境资料。旧刷写、停服、改路由和系统参数的实验不再作为当前调试入口。

两批共归档40份Python和1份退休JSON；`.local/`根剩余Python脚本为0。历史实现、PGO输入、结果和备份仍可复核；本批没有永久销毁唯一历史代码，也没有删除构建缓存。

归档不是公开发布。脚本可能仍有个人主机和密钥路径，不把整个 `.local/`、`artifacts/` 或工作目录打包。将来提取新能力时，先迁移代码、参数、关键失败检查和对应证据，再退役旧入口。
