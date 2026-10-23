# AlwayRoute 固件构建与设备适配

本目录保存自有包、seed、补丁、构建和只读镜像检查工具，不保存固件、节点／订阅、主机私钥或设备备份。当前部署身份统一见[状态](../docs/status.md)，本文件说明构建输入和流程，不能当作设备刷写授权。

发布构建固定输入见 [release.json](release.json) 与 [PGO 输入说明](pgo/README.md)。`inspect-image.py --profile release --release-manifest PATH --experimental-crypto mipsle-asm-r2` 核对本次构建输入、完整核心、优化参数、正式规则及自有载荷，沿用 OpenWrt 管理初始化，不依赖私人历史基线镜像。原 `baseline`／`manager` 检查及历史基线对比继续保留。

## 固定输入与生产差异

GitHub托管Runner按版本tag构建4A发布包的准备、触发和下载流程见[标签构建](../docs/github-build.md)。公开发布使用标准OpenWrt管理初始化；下述首启脚本和历史基线对比属于可选开发／回归流程，不是CI发布前提。

上游来源、提交、归档和树哈希在[sources.lock.json](sources.lock.json)：OpenWrt25.12.6、固定LuCI／packages与sing-box1.13.21；使用已有Go1.27.3、CGO关闭构建；CPU架构由设备配方选择，当前4A为MIPSLE softfloat。电脑阅读入口见[上游获取](../docs/upstream-sources.md)。当前唯一实机验证目标为第一版千兆4A，其参数和专用补丁必须保留；其他设备另建适配，不覆盖4A配置。支持范围见[设备列表](../docs/devices/README.md)，分层和移植流程见[多设备适配](../docs/device-porting.md)。

`tools/build-core.py`保留完整上游CLI／注册表及固定tags。默认构建不启用密码overlay；最后部署核心则明确选择`--crypto-inline`、匹配PGO和`--experimental-crypto mipsle-asm-r2`。选项、PGO哈希、补丁、模块及来源校验见[完整功能加密优化](../docs/reports/2026-10-23-crypto-optimization.md)。缺失当时PGO输入时不能承诺逐字节复现，不应以默认构建产物冒充已部署核心。

`003`汇编补丁、对应overlay和差分测试参与该显式后端来源核验；`004`旧32位Poly1305候选是独立、默认关闭实验，不能叠加。详见[汇编测试](tests/crypto-assembly/README.md)和[独立实验](tests/poly1305-32bit/README.md)。后续I/O等稳定性失败候选已撤回，详见[实验清理](../docs/reports/2026-10-23-200m-feasibility.md)。不要重新编号旧补丁，也不能为清理实验目录误删生产所需输入。

## 集成步骤

1. 按[环境配置](../docs/operations/environments.md)选择现有build角色，源码先dry-run同步到独立project_workspace，保持PC主本；OpenWrt构建树不接收整仓库覆盖。
2. 将`openwrt/alwayroute-core`、`alwayroute-manager`、`alwayroute-forwarding`、`luci-app-alwayroute`逐包集成到现有构建树的`package/`。在构建机使用 `python3 firmware/tools/sync-packages.py --env PATH --package alwayroute-manager luci-app-alwayroute` 先预览，再同参加 `--apply`。工具核对已审阅快照与完整目标哈希集合；多余旧文件须单独审查，不自动删除，不启动构建。管理包负责事务，LuCI负责网页，转发包负责LAN nft TProxy，核心包安装外部已验证ELF。
3. `alwayroute-input/`放外部核心、不含凭证的`build-info.json`及上游LICENSE；核对架构、静态链接、来源和SHA。核心包的`PKG_FILE_DEPENDS`跟踪三项外部输入，禁止对该ELF二次strip改变已验身份。
   管理包另需 `alwayroute-input/routing/` 中的两份国内 `.srs`、`manifest.json` 和第三方 `LICENSE`。按 [规则构建说明](../config/routing/README.md) 在构建主机从固定提交生成，审查后复制这四项，不复制源 JSON。管理包追踪这些外部输入；镜像检查同时核对来源锁、清单与二进制哈希，缺失或过期输入不能作为新镜像交付。
4. 用所选设备组合seed（下节说明），准备对应feed后`make defconfig`，审查完整配置差异。`openwrt/evaluation.config`完整保留原4A配方作为兼容快照；测试保证组合seed与它的有效选项一致。保留固定feeds提交、完整／差异配置、内核配置和包清单。
5. 按[部署策略](../config/deployment/README.md)显式选择并渲染首启脚本，审阅后放入构建树，同时提供已有SSH公钥；不放主机私钥、订阅或节点。原`openwrt/99-alwayroute-management`仅是当前实验策略兼容快照，不是硬件默认值。首启marker使保留配置升级跳过默认LAN／SSH／Web初始化，旧基础镜像迁移先核对并备份marker。
6. 在固定上游版本先`git apply --check`核对`001-4a-evaluation-image-limit.patch`，它将本设备IMAGE_SIZE限制为13248KiB，不修改物理分区；原厂OS1为13MiB，与OpenWrt固件区分开核算。
7. 使用已有工具链和缓存定向构建／重打包，运行镜像检查，绑定源码提交、输入哈希、最终镜像及日志。设备暂存／应用另见[部署](../docs/operations/deployment.md)。

镜像不含有效节点时不自动提供代理。当前用途保留双频无线、IPv6、LuCI、防火墙、TProxy与ip-full，WAN采用DHCP，未包含PPP／PPPoE。512KiB XZ块来自容量取舍，不能从镜像可刷直接推导RAM或长期负载达标。

## 工具、缓存与检查

`tools/run-native-build.py`监督同一构建树的并发、单次时限和磁盘；`tools/inspect-image.py`借助同树fwtool与unsquashfs检查元数据、载荷、权限、输入和来源。命令从build执行主机运行，通过`--env PATH`选择环境；具体选项见各入口`--help`。不会安装依赖、连接路由器或自动刷机。

生产集成应选择manager检查profile及对应显式加密后端，提供匹配基线／输入；当前实验镜像还须用`--management-defaults`显式提供原首启脚本或已审阅的新策略输出。不传该参数时，检查要求镜像不含自定义管理首启脚本。默认检查仍拒绝未声明overlay。构建核心与检查镜像必须采用同一环境、同一来源，不能只修改允许的SHA来绕过来源检查。

保留OpenWrt的dl／build_dir／staging_dir与Go缓存，按变更范围增量构建。例：只换核心输入可先构建`package/alwayroute-core/compile`再重打镜像；只改管理包先构建对应包。不要例行clean／dirclean／distclean，不因系统有ccache就声称已启用。每批日志、state和产物分开保存，避免覆盖可用基线。详细约定见[开发流程](../docs/development-workflow.md)。

## 选择设备、架构与环境

设备配置在 `devices/<设备名>.json`。当前默认 `--device xiaomi-4a-gigabit`，完整保存第一版4A的 target、board、镜像路径、13248 KiB限制、13 MiB原厂首刷边界、OpenWrt固件区、压缩块、无线包和专用补丁。通用包选择在 `openwrt/common.config`，4A的其余选项在 `devices/xiaomi-4a-gigabit.config`；原 `evaluation.config`保留为兼容快照。改4A选项时须更新对应输入和快照，不能让两者漂移。

```sh
# 离线查看设备配方；生成全新seed，不修改OpenWrt树
python3 firmware/tools/target_profile.py --device xiaomi-4a-gigabit --seed-output /path/to/run/seed.config
# 审阅并集成seed、feeds和所列补丁后，在既有构建主机执行
python3 firmware/tools/build-core.py --env /path/to/environment.json --device xiaomi-4a-gigabit --output /path/to/run/sing-box
python3 firmware/tools/run-native-build.py --env /path/to/environment.json --device xiaomi-4a-gigabit
```

上述核心命令默认关闭overlay和PGO；复现已部署优化核心仍须显式提供原有优化选项与匹配PGO。设备配方中的密码后端列表只是允许范围，不会自动启用实验。镜像检查同样接受 `--device`，原有 `--profile baseline|manager`仍表示内容检查类型，不表示硬件型号；其他必需输入继续按前述检查流程提供。

核心可用 `--architecture arm64`或`--architecture amd64`构建独立候选，基线分别固定为ARMv8.0和AMD64 v1，并隔离宿主CPU选项。它们只是架构构建入口，尚无新设备镜像或实机验证，不能与4A镜像混用；MIPS实验后端会在不兼容架构上被拒绝。

构建路径必须通过 `--env`及`build.task_root`明确指定，不再默认个人实验主机目录；现有环境中已配置的树、工具链与缓存继续复用。构建监督在启动make前核对已解析目标，拒绝用另一设备的构建树冒充所选配方。镜像检查按配方核对容量、设备、ELF与包选择；当前仅实现uImage MIPS + SquashFS布局，不支持的格式明确失败，新增设备须补齐对应验证器。
