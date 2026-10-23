# GitHub 标签构建与发布

当前唯一发布设备为小米路由器 4A 千兆版第一版 `xiaomi-4a-gigabit`。工作流为 [build-firmware.yml](../.github/workflows/build-firmware.yml)，编排入口为 [ci-build.py](../firmware/tools/ci-build.py)。不需要个人构建机、设备 SSH 密钥或代理节点凭证。

## 触发和下载

工作流随代码上传后，向 GitHub 推送 `vMAJOR.MINOR.PATCH` 标签触发固件编译，如 `v0.1.0`；预发布示例为 `v0.1.0-rc.1`。只在本地创建标签不会触发，普通分支提交不编译固件。实际打标签时必须选择包含工作流、构建输入和刷机工具的提交。

```sh
# 以下是维护者发布示例，不由文档或构建脚本自动执行
git tag -a v0.1.0 -m "发布 v0.1.0"
git push origin v0.1.0
```

在 Actions 中手动运行 `Build 4A firmware` 可调试冷构建，也可在默认分支预热缓存。手动运行只上传 Actions 产物，不创建 Release。tag 构建通过所有检查后自动创建对应 Release；含预发布后缀的版本标为 prerelease。发布任务仅在下载到已检查产物后取得 `contents: write`，编译任务只有仓库读取权限，使用临时 `GITHUB_TOKEN`，无需个人 PAT。重复创建同名 Release 会失败，不覆盖已发布文件。

成功产物包括：

- `alwayroute-<版本>-xiaomi-4a-gigabit-bundle.zip`：解压获得下面的固件、工具和说明。
- `*-sysupgrade.bin`、OpenWrt 包清单、`flash.py`、`FLASHING.md`。
- `SHA256SUMS`、`build-manifest.json`、`image-inspection.json`、许可声明和发布说明。

ZIP 内的校验列表覆盖解压内容，Release 单独的列表还覆盖 ZIP 本身。刷机见[4A指南](devices/xiaomi-4a-flashing.md)。构建失败只留排障日志，不发布固件；Actions成功产物和日志分别保留30天、14天，Release 附件长期保留。

## 构建输入和流程

1. 检出触发提交，校验 [sources.lock.json](../firmware/sources.lock.json) 中的上游源码树和固定 feeds；只使用该配方需要的 packages／LuCI 两个 feed。
2. 根据 [release.json](../firmware/release.json) 下载校验固定 Go 1.27.3，准备受 `go.sum` 校验的模块。主机 CLI 与 MIPSLE 路由器核心分别构建，完整上游 CLI／注册表／功能标签保留。
3. 4A核心显式使用 `crypto-inline`、[公开PGO](../firmware/pgo/README.md)和 `mipsle-asm-r2`；实际核心编译关闭网络，缺少输入直接失败，不自动退回其他优化配置。
4. 用主机 CLI 编译锁定来源的国内规则，集成四个自有包、组合4A seed及容量补丁，构建 OpenWrt。发布镜像不安装个人 `files/` overlay、公钥或实验首启策略，沿用标准 OpenWrt 初始化。
5. 发布检查核对设备、容量、CRC、核心来源／优化参数、正式规则、自有文件和权限；检查本次输入清单，不依赖私人历史基线镜像。通过后才生成下载包和校验列表。

构建清单记录源码提交、配方／补丁／规则来源锁／PGO哈希、核心与固件哈希、构建时间基准和检查数量。固定输入便于追踪，不承诺新的构建与历史部署镜像逐字节相同；历史镜像包含不同的管理初始化。每次新产物仍需独立实机验收，现有[状态](status.md)不自动更新为新版本已部署。

## Runner、缓存和排障

使用 `ubuntu-24.04` x64 GitHub 托管 Runner。工作流仅在这台一次性虚拟机中安装构建依赖，并删除预装但不参与构建的 .NET、Android 和 GHC 目录腾出空间；不修改开发电脑或已有构建主机。开始构建前至少要求12GiB可用空间；监督器另限制构建树体积和运行时长。首次实际冷构建仍须验证峰值磁盘和耗时，不能从静态检查推导一定装得下。

缓存仅覆盖校验过的下载归档、OpenWrt `dl`、规则来源和 Go 模块／编译缓存；不缓存整个 OpenWrt 构建树或生成固件。上游、工具链和规则来源参与 key。任何缓存缺失都走完整准备，缓存命中不跳过来源校验。不启用或声称已使用 ccache。

不同 tag 名称的 Actions 缓存互相隔离；默认分支上手动运行建立的缓存可被后续 tag 恢复。因此首版不承诺标签间自动增量复用，必要时先在默认分支手动预热。参见 [GitHub tag 过滤规则](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax#onpushbranchestagsbranches-ignoretags-ignore)、[缓存作用域](https://docs.github.com/en/actions/reference/workflows-and-actions/dependency-caching#restrictions-for-accessing-a-cache)和[Runner规格](https://docs.github.com/en/actions/reference/runners/github-hosted-runners)。

失败后下载 `firmware-build-logs`，按步骤查看来源、Go、规则、make或镜像检查日志。磁盘不足先核对峰值和依赖范围，再决定拆分构建阶段或调整 Runner；不自动改用付费 Runner、不升级上游、不放宽镜像检查，也不清理个人现有缓存。完整host ucode运行时与设备测试另按[测试入口](../tests/README.md)执行；CI静态检查和编译不替代这些结果。

## 离线预览

已有 Python 可在电脑上查看计划，不创建目录、不下载、不编译：

```powershell
python firmware/tools/ci-build.py --version v0.1.0-rc.1 --task-root .local/ci-preview
```

`--apply` 限制在 GitHub Linux x64 Runner 的 `RUNNER_TEMP` 子目录，拒绝覆盖已有构建任务。仓库修改后仍按协作规则创建本地提交；上传分支和标签需遵守当前对话的明确 push 授权。
