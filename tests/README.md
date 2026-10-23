# 测试目录与执行入口

测试按组件和验证边界分组。下面命令均从仓库根目录执行，使用已有运行时；构建及需要 POSIX 环境的检查优先在 Rock 独立工作副本执行。缺少依赖时先报告，不自动安装。

| 目录／入口 | 检查内容 | 执行环境 |
| --- | --- | --- |
| `ui/ui.test.cjs` | LuCI 模块契约、前端模型、API 和页面逻辑 | 已有 Node，可在电脑运行 |
| `firmware/test-supervisor.py`、`firmware/test_crypto_provenance.py` | 构建监督、实验密码输入来源及镜像元数据保护 | 已有 Python；按测试所需 POSIX 环境选择 Rock |
| `ui/build-preview.cjs`、`ui/preview-runtime.js` | 用生产页面生成带合成 RPC 的离线预览 | Node 生成；浏览器人工检查 |
| `manager/run-tests.py` | 组合并执行模型、订阅、内存事务及下载脚本测试 | Python 与已有 ucode（含 fs／digest 模块） |
| `manager/run.uc` | 通过真实模块导入检查模型与订阅 | 匹配的 ucode 与模块搜索路径 |
| `manager/test-timeout.py` | shell watchdog 退出码、截止超时和中断清理 | POSIX shell 与 Python，适合 Rock |
| `integration/check-contract.py` | UI／RPC 方法、ACL 和菜单绑定的静态一致性 | 已有 Python，可在电脑运行 |
| `integration/forwarding-test.py` | 用替身命令检查转发所有权、失败清理等行为 | POSIX shell 与 Python，适合 Rock |
| `integration/management-defaults-test.py` | 临时目录中检查首启 marker、失败重试与权限 | POSIX shell 与 Python，适合 Rock |
| `integration/runtime-api.uc` | 真实 fs／digest、文件锁、私有权限及错误编码兼容性 | 固定 OpenWrt host ucode，适合 Rock |

## 电脑可运行的检查

```powershell
node --test tests/ui/ui.test.cjs
python tests/integration/check-contract.py
```

需要查看页面时再生成预览：

```powershell
node tests/ui/build-preview.cjs
```

默认输出 `.local/ui-preview/alwayroute.html`，不会自动启动服务器或浏览器；预览步骤和适配边界见 [UI 检查说明](ui/README.md)。

## Rock 上的针对性检查

在已同步的独立源码工作副本根目录运行。下列 `/path/to/ucode` 是占位符，须替换为现有、与固件匹配且可加载 fs／digest 的 host ucode；不要调用面向 MIPS 设备的不可执行二进制。

```sh
# 模型、订阅、事务和下载脚本
python3 tests/manager/run-tests.py /path/to/ucode -

# 真实模块导入
/path/to/ucode -L firmware/openwrt/alwayroute-manager/files/usr/share/ucode tests/manager/run.uc

# 运行时兼容性
/path/to/ucode tests/integration/runtime-api.uc

# 下载 watchdog
python3 tests/manager/test-timeout.py firmware/openwrt/alwayroute-manager/files/usr/libexec/alwayroute-timeout

# 转发与首启脚本的隔离检查
python3 tests/integration/forwarding-test.py
python3 tests/integration/management-defaults-test.py
```

按改动选择相关检查，不默认运行全部测试。转发测试使用隔离命令替身，首启测试重定向状态路径并使用 UCI 替身；运行时检查只使用自己的临时目录。它们不能替代真实 nftables 语法、rpcd 会话权限、procd 时序、LAN 转发、重启恢复或吞吐验收。实机证据归入 [docs/reports](../docs/README.md)，使用合成数据的离线测试不能记作实机通过。

共享合成样本位于 [contracts/fixtures](../contracts/fixtures/)。新增测试跟随所属组件放置，不把模拟器装进固件，也不在样本或测试输出中记录真实凭证。

固件实验中编译进上游 Go 包的差分测试单独位于 [firmware/tests/crypto-assembly](../firmware/tests/crypto-assembly/README.md) 和 [firmware/tests/poly1305-32bit](../firmware/tests/poly1305-32bit/README.md)，由对应 overlay 工具读取，不属于 `tests/firmware/` 的主机工具检查；实验默认关闭，执行边界以各实验说明为准。
