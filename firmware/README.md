# 4A固件构建配方

本目录保存自有包、seed、补丁、构建和只读镜像检查工具，不保存固件、节点／订阅、主机私钥或设备备份。当前部署身份统一见[状态](../docs/status.md)，本文件说明构建输入和流程，不能当作设备刷写授权。

## 固定输入与生产差异

上游来源、提交、归档和树哈希在[sources.lock.json](sources.lock.json)：OpenWrt25.12.6、固定LuCI／packages与sing-box1.13.21；现有Go1.27.3用于MIPSLE softfloat、CGO关闭构建。电脑阅读入口见[上游获取](../docs/upstream-sources.md)。目标为第一版千兆4A，硬件边界见[设备适配](../docs/devices/xiaomi-4a.md)。

`tools/build-core.py`保留完整上游CLI／注册表及固定tags。默认构建不启用密码overlay；最后部署核心则明确选择`--crypto-inline`、匹配PGO和`--experimental-crypto mipsle-asm-r2`。选项、PGO哈希、补丁、模块及来源校验见[完整功能加密优化](../docs/reports/2026-10-23-crypto-optimization.md)。缺失当时PGO输入时不能承诺逐字节复现，不应以默认构建产物冒充已部署核心。

`003`汇编补丁、对应overlay和差分测试参与该显式后端来源核验；`004`旧32位Poly1305候选是独立、默认关闭实验，不能叠加。详见[汇编测试](tests/crypto-assembly/README.md)和[独立实验](tests/poly1305-32bit/README.md)。后续I/O等稳定性失败候选已撤回，详见[实验清理](../docs/reports/2026-10-23-200m-feasibility.md)。不要重新编号旧补丁，也不能为清理实验目录误删生产所需输入。

## 集成步骤

1. 按[环境配置](../docs/operations/environments.md)选择现有build角色，源码先dry-run同步到独立project_workspace，保持PC主本；OpenWrt构建树不接收整仓库覆盖。
2. 将`openwrt/alwayroute-core`、`alwayroute-manager`、`alwayroute-forwarding`、`luci-app-alwayroute`逐包集成到现有构建树的`package/`。在构建机使用 `python3 firmware/tools/sync-packages.py --env PATH --package alwayroute-manager luci-app-alwayroute` 先预览，再同参加 `--apply`。工具核对已审阅快照与完整目标哈希集合；多余旧文件须单独审查，不自动删除，不启动构建。管理包负责事务，LuCI负责网页，转发包负责LAN nft TProxy，核心包安装外部已验证ELF。
3. `alwayroute-input/`放外部核心、不含凭证的`build-info.json`及上游LICENSE；核对架构、静态链接、来源和SHA。核心包的`PKG_FILE_DEPENDS`跟踪三项外部输入，禁止对该ELF二次strip改变已验身份。
4. 用`openwrt/evaluation.config`作seed，准备对应feed后`make defconfig`，审查完整配置差异。保留固定feeds提交、完整／差异配置、内核配置和包清单。
5. 按包安装规则放置首启脚本及已有SSH公钥；不放主机私钥、订阅或节点。首启marker使保留配置升级跳过默认LAN／SSH／Web初始化，旧基础镜像迁移先核对并备份marker。
6. 在固定上游版本先`git apply --check`核对`001-4a-evaluation-image-limit.patch`，它将本设备IMAGE_SIZE限制为13248KiB，不修改物理分区；原厂OS1为13MiB，与OpenWrt固件区分开核算。
7. 使用已有工具链和缓存定向构建／重打包，运行镜像检查，绑定源码提交、输入哈希、最终镜像及日志。设备暂存／应用另见[部署](../docs/operations/deployment.md)。

镜像不含有效节点时不自动提供代理。当前用途保留双频无线、IPv6、LuCI、防火墙、TProxy与ip-full，WAN采用DHCP，未包含PPP／PPPoE。512KiB XZ块来自容量取舍，不能从镜像可刷直接推导RAM或长期负载达标。

## 工具、缓存与检查

`tools/run-native-build.py`监督同一构建树的并发、单次时限和磁盘；`tools/inspect-image.py`借助同树fwtool与unsquashfs检查元数据、载荷、权限、输入和来源。命令从build执行主机运行，通过`--env PATH`选择环境；具体选项见各入口`--help`。不会安装依赖、连接路由器或自动刷机。

生产集成应选择manager检查profile及对应显式加密后端，提供匹配基线／输入；默认检查拒绝未声明overlay。构建核心与检查镜像必须采用同一环境、同一来源，不能只修改允许的SHA来绕过来源检查。

保留OpenWrt的dl／build_dir／staging_dir与Go缓存，按变更范围增量构建。例：只换核心输入可先构建`package/alwayroute-core/compile`再重打镜像；只改管理包先构建对应包。不要例行clean／dirclean／distclean，不因系统有ccache就声称已启用。每批日志、state和产物分开保存，避免覆盖可用基线。详细约定见[开发流程](../docs/development-workflow.md)。
