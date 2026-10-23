# 许可证范围

AlwayRoute 按组件保留许可，不能把整套固件的所有内容统一视为 MIT。

| 范围 | 许可 |
| --- | --- |
| 本仓库自行编写的 `scripts/`、`firmware/tools/`、测试与构建支持代码 | [MIT](LICENSES/MIT.txt)，另有原始声明的文件除外 |
| 自有文档、接口契约、环境示例和配置说明 | [MIT](LICENSES/MIT.txt)；引用内容及第三方数据保留原有声明 |
| `firmware/openwrt/alwayroute-manager/`、`alwayroute-forwarding/` 的自有代码 | [MIT](LICENSES/MIT.txt)；管理包另安装的第三方规则数据保留来源锁及随包 GPL-3.0 文本，不重新许可为 MIT |
| `firmware/openwrt/luci-app-alwayroute/`、`alwayroute-core/` | 保持现有配方的 GPL-3.0-or-later；见 [GPL 文本](LICENSES/GPL-3.0-or-later.txt) |
| OpenWrt／Go／x/crypto 补丁及衍生测试片段 | 保留文件内上游版权与原始许可，见 [第三方说明](THIRD_PARTY_NOTICES.md) |
| 分流参考来源及据此选择性维护的数据 | 保留来源许可与归属，见 [第三方说明](THIRD_PARTY_NOTICES.md) |

本说明不改变第三方软件、补丁原文或上游源码的许可。锁文件和补丁用于确定来源；下载目录中的上游许可证随各项目保存。分发固件或二进制时，应按实际包含的组件提供对应版权、许可文本及源码材料，不能仅附本仓库的 MIT 文本。

未发布的私有环境、订阅、认证资料和设备备份不因位于工作目录或被工具读取而成为公开分发内容。
