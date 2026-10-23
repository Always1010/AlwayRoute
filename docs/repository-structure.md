# 仓库结构与维护约定

本仓库是AlwayRoute自有源码、构建配方与补丁的主本；第三方完整源码、真实环境和构建产物不纳入Git。

```text
AlwayRoute/
├── AGENTS.md                  # 协作、提交、同步与缓存约定
├── README.md                  # 项目概览和常用入口
├── contracts/                 # 模型、RPC契约、合成样本
├── config/
│   ├── environments/          # 可公开的*.example.json
│   └── routing/               # 来源锁、规则维护说明
├── firmware/
│   ├── README.md              # 当前构建配方与检查入口
│   ├── sources.lock.json      # 上游版本、提交、来源与树哈希
│   ├── openwrt/               # 自有四包、seed、首启脚本、补丁
│   ├── tools/                 # 核心构建、overlay、监督、镜像检查
│   └── tests/                 # overlay编译输入及Go差分测试
├── scripts/                   # 环境上下文、同步、设备入口、上游获取
├── tests/                     # manager、ui、integration、firmware主机检查
└── docs/
    ├── README.md              # 按任务组织的导航
    ├── status.md              # 唯一当前部署与验收摘要
    ├── requirements.md        # 产品需求及验收标准
    ├── implementation-plan.md # 剩余工作与依赖
    ├── development-workflow.md
    ├── upstream-sources.md
    ├── operations/            # 环境、访问、部署与恢复
    ├── devices/               # 公共硬件适配及基本拓扑
    └── reports/               # 索引、执行事实、失败与脱敏证据
```

## 源码和测试归属

- `firmware/openwrt/alwayroute-manager/`：ucode模型、订阅、存储事务、RPC、ACL、短期作业与启动恢复。
- `firmware/openwrt/luci-app-alwayroute/`：LuCI页面、API／模型模块、样式和菜单。
- `firmware/openwrt/alwayroute-forwarding/`：nftables及策略路由适配；`alwayroute-core/`安装外部已校验核心与来源。
- 包内`files/`、`root/`、`htdocs/`沿用OpenWrt安装布局，不为缩短路径复制到另一个src目录；权限和安装位置以Makefile为准。
- 正式服务规则的唯一主本在manager包`files/usr/share/alwayroute/policies/`；`catalog.json`索引各服务，来源和匹配语义见[规则维护](../config/routing/README.md)。`config/routing/`不保存第二套规则或当前设备配置。
- `firmware/tests/`是overlay编译到上游Go包的测试输入；`tests/firmware/`验证主机工具。两者不能仅因名称相近就合并。
- 构建和镜像专用工具放`firmware/tools/`；跨组件流程放`scripts/`；合成fixture放`contracts/fixtures/`；界面预览与替身命令留`tests/`，不安装到设备。

## 私有数据与工作区

| 位置 | 用途 |
| --- | --- |
| `.local/environments/current.json` | 实际build／router／traffic环境；不保存密钥正文 |
| `.local/lab/` | 私人接线、主机指纹／备份索引及整理前文档资料；不公开 |
| `.local/sources/`、`.local/source-cache/` | 锁定上游源码及归档；有用修改整理为正式补丁 |
| `.local/incoming/`、`.local/ui-preview/` | 远端回传待审查、离线界面预览 |
| `artifacts/` | 固件、包和原始检查产物；只提交脱敏结论、版本与哈希 |
| `session-log.md` | 本地会话笔记；可复用结论整理到正式文档 |

这些路径由Git忽略；忽略规则不能识别任意业务源码中的秘密，也不能移除旧提交中的内容。Rock上的独立源码副本与OpenWrt构建树、缓存、工具链、输出是不同目录，具体值由[环境配置](operations/environments.md)描述。

## 变更规则

新增文件放到现有职责分区；接口语义变化同时关注契约、生产实现和相关测试。文档按[导航规则](README.md#文档维护)维护。改名或移动前检查所有引用，尤其overlay测试输入、包安装路径和构建工具相对路径。

同步必须先dry-run，禁止整仓库直接指向OpenWrt构建树；不使用自动全树删除。远端旧路径逐项审查后处理，不能连带删除下载、工具链、对象、备份或当前构建成果。每个完成的独立修改按[AGENTS.md](../AGENTS.md)验证并本地提交。
