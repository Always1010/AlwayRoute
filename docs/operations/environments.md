# 环境配置与角色

`scripts/alwayroute_context.py`提供共享环境上下文；命令通过`--env PATH`选择JSON环境。公开示例在`config/environments/*.example.json`，实际环境默认保存在被Git忽略的`.local/environments/current.json`。复制示例后只填真实值，不把实际环境回写为示例；文件不保存密钥、口令、订阅或节点正文。

环境把构建位置、设备命令执行位置与测试流量路径分开：改变设备访问方式不意味着迁移构建树。

| 角色 | 字段 | 含义 |
| --- | --- | --- |
| build | `executor`（`local`／`ssh`）、`ssh_alias` | 构建命令在哪台主机执行 |
| build | `project_workspace`、`task_root`、`openwrt_tree` | 独立源码副本、任务根、现有OpenWrt树；同步不得直接指向构建树 |
| build | `toolchain_root`、`cache_root`、`output_root` | 复用的工具链、缓存与输出位置 |
| build | `jobs`、`timeout_seconds`、`disk_limit_bytes` | 并行度、单次时限及磁盘保护 |
| router | `executor`（`local`／`ssh`）、`executor_ssh_alias` | 从PC执行设备SSH，或先到操作主机再执行 |
| router | `target`、`connect_timeout_seconds` | 执行主机视角的路由器SSH目标与连接超时 |
| router | `ssh_port`、`identity_file`、`known_hosts_file` | 端口、执行主机上的既有私钥和可信主机文件引用；不含文件正文 |
| traffic | `executor`、`ssh_alias`、`source_interface`、`source_address`、`gateway` | 流量生成主机与绑定路径；避免把管理链路误当测速路径 |

SSH别名、身份文件和严格主机校验由已经准备好的SSH配置管理。脚本不写系统PATH，不安装依赖、不自动生成SSH配置或关闭主机检查。缺少工具或信任记录时明确失败。

## 两种设备访问方式

当前环境的build与router执行器均在Rock：PC同步自有源码到Rock独立副本，Rock使用已有构建树，再从Rock访问4A。`router.executor=ssh`，`executor_ssh_alias`指向Rock，`target`使用当前实际设备登录目标，并通过`ssh_port`、`identity_file`和`known_hosts_file`引用Rock上已准备的端口与文件；不要求设备已有SSH别名。

未来PC直连时保持build角色指向Rock，仅把router角色改为`executor=local`，`target`使用PC已有的设备SSH别名。PC的SSH别名也可以在用户自行配置后使用ProxyJump。这里的local指PC发起SSH，不表示在PC运行路由器MIPS程序；PC直连配置尚未实机验收。

traffic角色单独描述真实发流位置。只有核对源接口、地址、网关和目标后，才能把结果标为LAN回环、经核心直连、实际WAN或代理测试；不能用默认路由猜测测试路径。

## 命令入口

```powershell
# 默认只预览源码同步；选择实际私有环境
python scripts/sync-source.py --env .local/environments/current.json
# 审查预览后再复制到独立源码工作副本
python scripts/sync-source.py --env .local/environments/current.json --apply
# 设备只读状态
python scripts/device.py --env .local/environments/current.json status
# 默认只预览暂存计划；增加--apply才复制并校验，不刷机
python scripts/device.py --env .local/environments/current.json stage artifacts/example.bin
```

同步apply要求已有成功preview，且输入和远端差异与预览一致；默认计划文件是`.local/runs/source-sync-plan.json`，可用`--plan`选择另一私有路径。stage默认只预览计划，显式`--apply`才复制并核验，固定使用`/tmp/alwayroute-stage-<hash>`暂存。

旧`.local/lab/scripts/sync-rock.sh`作为兼容入口保留。工具用法和已实现的参数以各入口`--help`为准。真实环境文件与`.local/lab/`中的原始环境记录要一起受控保管；整理前资料仅作人工核对，不能当作自动执行脚本。

## 有限HTTPS测量

先用`python scripts/network-diagnostics.py --env PATH --url https://example.com/`检查发流主机的解析及实际IPv4路由，比较环境中声明的源地址、接口和网关。该入口要求发流主机已有Python、getent及iproute；只读查询，输出布尔值和数量，实际地址仅可显式保存到私有`.local/`输出。路由不符时先查明接线与配置，工具不自动增加路由。

`python scripts/measure-https.py --env PATH --url https://example.com/`默认只预览；显式`--apply`后从traffic执行主机发起有限请求，不改路由、DNS或代理配置。默认3次、每次15秒、最多1MiB；可在工具限定范围内选择`--count`和`--timeout`。实际执行要求发流主机已有 curl 8.4.0 或更新版本，缺少时失败而不安装。工具禁用默认 curl 配置及代理环境继承。Windows 本地绑定须提供 `source_address`，不支持仅填接口名。URL须是无凭证、无查询参数和fragment的公开HTTPS地址。

输出连接、TLS、总耗时和字节数，不保存响应正文／cookie。源绑定只说明curl采用指定接口或地址，不证明请求一定经4A、WAN或特定策略；`gateway`描述预期路径，不自动配置网关。对照实际路由和设备状态后才能解释测量结果。
