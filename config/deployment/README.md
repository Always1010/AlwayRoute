# 首启部署策略

这里保存可选示例，真实部署策略放被忽略的 `.local/`。LAN 地址和 SSH 端口属于部署环境，不属于路由器型号，也不由设备配方自动选择。

| 示例 | 行为 |
| --- | --- |
| `isolated-lan.example.json` | 保存现有个人4A实验策略：LAN 192.168.31.1/24、LAN内SSH 122 |
| `preserve-network.example.json` | 保留已有LAN地址和SSH端口，仅使用显式指定的SSH逻辑接口 |

两个示例均沿用现有的公钥认证、Web仅回环监听及首启marker机制。它们不是可直接开放网页的成品配置；集成前提供已审阅的SSH公钥，随后按设备访问与认证流程配置Web。已有marker时保留配置升级跳过初始化。若不需要自定义首启策略，可不安装本脚本，沿用对应OpenWrt的管理初始化流程。

```sh
# 只生成供审阅的全新文件，不连接或修改设备、不写OpenWrt树
python3 firmware/tools/render-management-defaults.py --policy /path/to/private-policy.json --output /path/to/run/99-alwayroute-management
```

审阅输出后才将其集成到构建树的 `files/etc/uci-defaults/99-alwayroute-management`。镜像检查通过 `--management-defaults /path/to/run/99-alwayroute-management`显式选择审阅基准，并同时比较基准、构建树和镜像中的脚本。

原 `tests/fixtures/management-defaults.sh`保持不变，作为当前4A实验环境的兼容快照；它不是其他设备默认值。当前实验策略渲染结果必须与该快照逐字节一致，修改模板时执行相关回归检查。历史镜像可继续用该快照作为显式检查基准。
