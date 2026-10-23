# 环境配置

复制示例到被 Git 忽略的 `.local/environments/` 后填写真实环境，使用 `--env PATH` 显式选择。示例中的 SSH 别名和文档测试地址不能直接连接真实设备。不在此目录保存真实环境；不要修改系统 SSH 配置来迁就示例。

`remote-linux.example.json` 表达构建、路由器操作和测试发流均由 Linux 主机执行；`direct-router.example.json` 表达电脑管理路由器、构建仍在远端。SSH 别名可使用现有 OpenSSH 配置中的 ProxyJump；跳板与构建主机没有隐式绑定关系。

格式版本为 `schema_version: 1`，支持的字段和校验集中在 `scripts/alwayroute_context.py`。`build`、`router`、`traffic` 可按工具需要提供；未知字段、相对路径、无效预算或包含选项的主机参数会被拒绝。工具链根目录指容器目录，固定 Go 位于其 `go1.27.3/go/`；OpenWrt 路径指源码树本身。

环境文件只提供路径、资源预算、连接引用与测试位置，不提供任意 shell 命令。架构、设备和镜像容量由仓库设备配方选择，上游版本与哈希继续锁定，不随连接方式改变。构建入口必须提供 --env 和 build.task_root，不隐式使用个人目录。密钥内容、密码、订阅和节点不放在 JSON 中；`identity_file` / `known_hosts_file` 只是操作执行机上的私有文件路径。

源码同步要求 `build.executor=ssh`，目标为独立 `project_workspace`，不得指向 OpenWrt 树、缓存或任务根目录。构建工具在构建机执行，`--env` 描述其路径，不会自动在本机或远端安装运行时。`traffic` 描述测试位置；具体网络实验仍须核验执行机与接线，Windows 不会因此获得 Linux 实验能力。

完整操作和边界见 [环境说明](../../docs/operations/environments.md)及[开发流程](../../docs/development-workflow.md)。
