# 测试目录与执行入口

测试按组件和验证边界分组。下面命令均从仓库根目录执行，使用已有运行时；构建及需要 POSIX 环境的检查优先在 构建主机 独立工作副本执行。缺少依赖时先报告，不自动安装。

| 目录／入口 | 检查内容 | 执行环境 |
| --- | --- | --- |
| `ui/ui.test.cjs` | LuCI 模块契约、前端模型、API 和页面逻辑 | 已有 Node，可在电脑运行 |
| `firmware/test-supervisor.py` | 使用临时环境配置验证构建监督，不再靠源码替换固定路径 | 已有Python与所需POSIX环境，适合构建主机 |
| `firmware/test_package_sync.py` | 用替身验证包快照同步、目标边界及多余文件拒绝 | 已有Python，不构建或访问设备 |
| `firmware/test_crypto_provenance.py` | 显式候选／标准核心的密码输入来源和镜像元数据保护 | 已有Python，按输入及构建环境选择构建主机 |
| `tools/test_context.py`、`tools/test_sync_source.py`、`tools/test_device_tools.py`、`tools/test_public_audit.py` | 环境／同步／暂存入口与公开材料审计的隔离检查 | 已有Python；具体平台边界见测试 |
| `tools/test_device_maintenance.py`、`tools/test_network_diagnostics.py` | 设备只读状态、私有备份边界与多网卡路由诊断 | 已有Python，设备／网络命令均使用替身 |
| `firmware/test_device_test_runner.py`、`firmware/test_benchmark_summary.py` | 现有测试二进制执行保护、历史性能结果白名单与条件保留 | 已有Python，不编译、不执行设备测试、不连接设备 |
| `ui/build-preview.cjs`、`ui/preview-runtime.js` | 用生产页面生成带合成 RPC 的离线预览 | Node 生成；浏览器人工检查 |
| `manager/run-tests.py` | 组合并执行模型、订阅、内存事务及下载脚本测试 | Python 与已有 ucode（含 fs／digest 模块） |
| `manager/run.uc` | 通过真实模块导入检查模型与订阅 | 匹配的 ucode 与模块搜索路径 |
| `manager/test-timeout.py` | shell watchdog 退出码、截止超时和中断清理 | POSIX shell 与 Python，适合 构建主机 |
| `integration/check-contract.py` | UI／RPC 方法、ACL 和菜单绑定的静态一致性 | 已有 Python，可在电脑运行 |
| `integration/forwarding-test.py` | 用替身命令检查转发所有权、失败清理等行为 | POSIX shell 与 Python，适合 构建主机 |
| `integration/management-defaults-test.py` | 临时目录中检查首启 marker、失败重试与权限 | POSIX shell 与 Python，适合 构建主机 |
| `integration/runtime-api.uc` | 真实 fs／digest、文件锁、私有权限及错误编码兼容性 | 固定 OpenWrt host ucode，适合 构建主机 |

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

## 构建主机 上的针对性检查

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

## 工作流和密码来源检查

维护本次新增工具时，分别选择对应检查；四项均使用合成数据／替身，不能记作实际路由或密码测试通过：

```sh
python3 tests/tools/test_device_maintenance.py
python3 tests/tools/test_network_diagnostics.py
python3 tests/firmware/test_device_test_runner.py
python3 tests/firmware/test_benchmark_summary.py
```

实际设备测试入口为`firmware/tools/run-device-tests.py --env PATH --binary FILE...`。默认仅离线验证；`--preflight`只读检查设备，`--apply`才上传并运行完整普通Go测试。内存不足即拒绝，不自动停止生产核心。编译来源与实验范围仍按对应`firmware/tests/`说明核对。

```sh
# 构建监督使用自己的临时环境，不连接设备
python3 tests/firmware/test-supervisor.py
# 必须明确提供候选及标准核心；路径从所选build环境理解
python3 tests/firmware/test_crypto_provenance.py --env /path/to/environment.json --candidate /path/to/candidate-core --standard /path/to/standard-core
# 使用临时目录／替身检查工作流，不代表真实PC直连或构建主机构建已经通过
python3 -m unittest discover -s tests/tools -p 'test_*.py'
python3 tests/tools/test_public_audit.py
```

`test_crypto_provenance.py`的`--candidate`和`--standard`是必填输入，不使用文档中的占位符执行。环境字段与作用见[环境说明](../docs/operations/environments.md)，密码实验差分测试仍在`firmware/tests/`，不与主机工具检查合并。

设备入口`python scripts/device.py --env PATH status`只读查询；`stage FILE`默认只预览，显式`--apply`才暂存并核验哈希，均不刷机、不安装包、不应用配置。`python scripts/measure-https.py --env PATH --url https://example.com/`默认预览，`--apply`发起有限HTTPS请求，不修改路由。真实测试地址选择和授权按具体场景核对，不能使用含凭证URL。

HTTPS测量可以绑定traffic角色的源接口／地址，但绑定成功不能证明经过某个网关、WAN或代理出口；必须结合路由与设备证据解释路径。隔离测试、工具成功和一次SSH登录都不能记作PC直连、物理断开构建主机或长期负载验收。
