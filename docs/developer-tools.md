# 项目开发工具

正式入口与环境配置共同维护；真实环境、原始输出和退役脚本不进入公开源码。工具只复用已有运行时，不自动安装软件。

| 入口 | 用途与边界 |
| --- | --- |
| `firmware/tools/ci-build.py` | 默认只打印4A发布构建计划；apply限定GitHub Linux临时Runner，准备锁定输入、构建及打包，不连接个人主机或设备 |
| `scripts/flash.py` | 独立4A发布刷机入口；默认校验和只读预检，显式 apply 才私有备份、暂存及一次写入；原厂与OpenWrt分支严格区分 |
| `scripts/fetch-sources.py` | 锁定上游源码获取／校验；保持独立于设备连接 |
| `scripts/build-routing.py` | 构建主机校验固定规则源并生成本地 `.srs` 与来源清单；显式允许下载，默认 IPv4，不安装工具或改写既有产物 |
| `scripts/sync-source.py` | PC 到独立源码副本；默认预览、应用要求计划一致、传输已校验快照、不删除远端文件 |
| `firmware/tools/sync-packages.py` | 构建机把明确选择的自有包集成到 package；默认预览、完整哈希验证，目标旧文件拒绝且不删除 |
| `firmware/tools/render-management-defaults.py` | 显式读取部署策略生成待审首启脚本，不写构建树或设备 |
| `firmware/tools/target_profile.py` | 离线查看设备配方、组合seed；不修改构建树或启用补丁 |
| `firmware/tools/build-core.py` | 固定来源核心构建；环境参数与目标配方分开，实验必须显式选择 |
| `firmware/tools/run-native-build.py` | 同树增量构建监督；锁、并发、预算、进程组有界清理、产物新鲜度和大小保护 |
| `firmware/tools/inspect-image.py` | 按设备配方检查镜像及核心来源，未知格式拒绝，设备写入另行执行 |
| `scripts/device.py` | 白名单状态输出、默认离线暂存计划；显式 apply 才临时上传，不刷机 |
| `scripts/device-maintenance.py` | 只读预检、资源、私有快照与比较；backup 默认离线计划，显式 apply 才读取并验证配置备份 |
| `scripts/network-diagnostics.py` | 按 traffic 角色解析目标并查询实际 IPv4 路由，比较源地址／接口／网关，不修改网络 |
| `scripts/measure-https.py` | 按 traffic 角色执行有限 HTTPS 测量，不改变路由；需要已有 curl >= 8.4，结果不自动证明实际转发路径 |
| `firmware/tools/run-device-tests.py` | 已编译静态 MIPSLE 测试二进制的离线计划、只读预检及显式有界执行；资源不足拒绝，不停生产服务 |
| `firmware/tools/summarize-benchmarks.py` | 离线白名单汇总历史性能结果，保留测试条件、匿名化候选，不跨条件推导提升 |
| `scripts/audit-public.py` | 当前受跟踪文件、可达历史和可选对象库的脱敏候选检查，不替代人工复核 |

构建监督器要求已有 Linux `/proc` 与 Python `waitid(WNOWAIT)`。超预算或监督异常时，对整个构建进程组发送 TERM，最多等待 20 秒；仍存活的后代升级 KILL，再等待最多 5 秒确认退出，并有界回收直接子进程。期间保留未回收的组长 PID，避免 PID／进程组编号复用导致误伤。清理未完成时状态为 `supervisor_failed_cleanup_incomplete`，不能按已停止处理。`tests/firmware/test-supervisor.py` 在 Windows 只验证隔离逻辑；真实信号、后代退出和回收用例须在已有 Linux 主机执行，测试的失败清理还要求已有 pidfd 支持。

## 本地环境工具

环境专用脚本与说明保存在 `.local/lab/scripts/` 和 `.local/lab/docs/`，导航为 `.local/lab/README.md`；临时实验在 `.local/experiments/`。它们不属于源码同步和公开发布输入。
