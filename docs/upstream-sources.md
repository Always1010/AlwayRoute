# 上游源码获取入口

本仓库保存 AlwayRoute 自有代码、构建配方及补丁，上游源码通过固定版本获取到电脑的 `.local/sources/`。这个目录被 Git 忽略，源码可在同一项目下查看和修改，但不会重复进入本项目提交。首次构建允许下载依赖。

来源、当前固件使用的提交、完整源码树哈希及下载地址集中在 [firmware/sources.lock.json](../firmware/sources.lock.json)。获取入口是 [scripts/fetch-sources.py](../scripts/fetch-sources.py)，只使用已有 Python 标准库，不安装软件、依赖，不修改系统 PATH，也不连接或修改 Rock。

## 使用方法

从仓库根目录运行：

```powershell
# 查看来源、锁定版本和本机位置；不下载
python scripts/fetch-sources.py

# 只获取 LuCI，或指定若干组件
python scripts/fetch-sources.py fetch luci
python scripts/fetch-sources.py fetch openwrt luci

# 获取当前固件所用的四个上游项目
python scripts/fetch-sources.py fetch

# 与锁定版本比较内容、文件数和归档中的权限
python scripts/fetch-sources.py verify
```

默认源码位置为 `.local/sources/<组件>/`，原始归档缓存在 `.local/source-cache/`。脚本在解包前计算完整 Git tree 哈希，比较每个文件的字节、原始执行位和符号链接，确认与当前固件使用的源码版本一致；校验失败不会创建源码目录。已经存在且带有匹配来源标记的目录会直接复用，保留本地修改；需要检查是否仍与原始版本一致时运行 `verify`。

不会自动删除、重置或覆盖已有不同版本／修改过的源码。需要另一份工作副本时使用 `--dest .local/sources-other`；缓存位置也可通过 `--cache` 指定。更换锁定版本时应选新目录，审查本地修改后再决定如何迁移。来源标记为各组件目录中的 `.alwayroute-source.json`，不属于上游源码。

Windows 下，符号链接以目标路径文本占位，原始链接目标与可执行文件清单保存在来源标记中；这些目录用于阅读和编辑，不能直接通过普通文件复制当作 Linux 构建树。Rock 已有对应版本的完整构建树；新准备 Linux 副本时，应传输并解包校验过的源码归档，保留原始链接和权限，遵守[源码同步流程](development-workflow.md)的 dry-run 与独立目录约定。不要直接覆盖正在使用的构建树或缓存。

## 源码位置

| 项目 | 上游入口 | 下载后的本机目录 |
| --- | --- | --- |
| OpenWrt | [官方源码仓库](https://git.openwrt.org/openwrt/openwrt.git) | `.local/sources/openwrt/` |
| LuCI | [官方源码仓库](https://git.openwrt.org/project/luci.git) | `.local/sources/luci/` |
| packages feed | [官方源码仓库](https://git.openwrt.org/feed/packages.git) | `.local/sources/packages/` |
| sing-box | [上游源码仓库](https://github.com/SagerNet/sing-box) | `.local/sources/sing-box/` |

下载使用官方项目的 GitHub 源码归档镜像，锁定提交与 Rock 当前构建一致。具体阅读入口：

- LuCI 框架：`luci/modules/luci-base/`。
- 网络接口和无线页面：`luci/modules/luci-mod-network/htdocs/luci-static/resources/view/network/`。
- 系统和状态页面：`luci/modules/luci-mod-system/`、`luci/modules/luci-mod-status/`。
- 主题和防火墙页面：`luci/themes/luci-theme-bootstrap/`、`luci/applications/luci-app-firewall/`。
- OpenWrt 设备定义和内核适配：`openwrt/target/linux/`；基础包定义：`openwrt/package/`。
- sing-box 协议实现和命令：`sing-box/protocol/`、`sing-box/cmd/sing-box/`。
- AlwayRoute 自有页面和后端仍在本仓库的 `firmware/openwrt/`。

这些是完整上游项目快照，不包含上游 Git 历史，也不是离线构建依赖全集。Linux 内核原始源码、各包下载源码、工具链源码和 Go 模块仍由配方按版本／哈希获取。当前未使用的 routing／telephony／video feed，以及 sing-box 的独立 Apple／Android 客户端仓库，不属于本固件源码入口范围。各项目保留各自的许可证和版权声明。
