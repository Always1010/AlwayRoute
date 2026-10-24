# 首启部署策略

这里保存可选示例，真实部署策略放被忽略的 `.local/`。LAN 地址和 SSH 端口属于部署环境，不属于路由器型号，也不由设备配方自动选择。

| 示例 | 行为 |
| --- | --- |
| `isolated-lan.example.json` | 使用文档测试地址 192.0.2.1/24 和 SSH 2222 演示显式隔离管理策略；使用前替换为实际值 |
| `preserve-network.example.json` | 保留已有LAN地址和SSH端口，仅使用显式指定的SSH逻辑接口 |

两个示例均使用公钥认证、Web仅回环监听及首启marker机制。它们不是可直接开放网页的成品配置；集成前提供已审阅的SSH公钥，随后按设备访问与认证流程配置Web。已有marker时保留配置升级跳过初始化。若不需要自定义首启策略，可不安装本脚本，沿用对应OpenWrt的管理初始化流程。

```sh
# 只生成供审阅的全新文件，不连接或修改设备、不写OpenWrt树
python3 firmware/tools/render-management-defaults.py --policy /path/to/private-policy.json --output /path/to/run/99-alwayroute-management
```

审阅输出后才将其集成到构建树的 `files/etc/uci-defaults/99-alwayroute-management`。镜像检查通过 `--management-defaults /path/to/run/99-alwayroute-management`显式选择审阅基准，并同时比较基准、构建树和镜像中的脚本。

实际部署策略和历史首启脚本只保存在 `.local/lab/`，不作为公开默认值或测试输入。`tests/fixtures/management-defaults.sh` 是由合成示例渲染的测试夹具，用于验证首启行为；不直接集成到固件。模板修改后运行部署策略和首启隔离检查。
