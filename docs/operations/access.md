# 访问与只读检查

先阅读[环境角色](environments.md)，按私有环境选择电脑直连或经操作主机执行 SSH。

## 首次使用某个环境

1. 核对设备型号、管理接线与网段；排除上游和PC虚拟网卡的地址重叠。
2. 核对执行主机上的SSH目标／别名、端口、既有密钥和可信主机记录；不要关闭严格检查，也不要把已有生产密钥复制进仓库。
3. 运行`python scripts/device.py --env .local/environments/current.json status`，确认目标身份和状态。status是只读入口，失败不会自动修网络或认证。
4. 检查build独立工作副本、构建树、缓存及输出根不是同一目录，再做源码同步dry-run。
5. PC直连路径首次成功后，仍需验证LAN浏览器认证、断开Rock、新连接和重启；单次SSH成功不等于A8通过。

当前没有因仓库整理而新建本机网卡、路由、SSH配置或服务。真实主机值由私有环境文件提供；历史文档中的占位符不应直接粘贴执行。

日常联调可用`python scripts/device-maintenance.py --env .local/environments/current.json preflight`核对身份、核心与转发状态、空闲作业、待应用状态和revision；`resources`读取有限的进程／系统计数。全局`--expect-board`、`--expect-core-sha256`和`--manifest`可加入已知身份约束，放在子命令前。工具不会为使检查通过而启动服务或修复配置。

调试前用`snapshot --save LABEL`留存私有基线，结束后用`compare SNAPSHOT_JSON`核对配置、选择和核心身份；输出只公开哈希与一致性。快照是多次读取的观察结果，不能当作事务锁。备份流程及恢复边界见[恢复说明](recovery.md)，已退役的批次脚本见本地环境资料。
