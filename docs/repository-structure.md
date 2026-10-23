# 仓库文件结构与维护约定

整理日期：2026-10-23（Asia/Shanghai）。本说明记录当前受 Git 管理的文件分区和新增文件的放置规则；项目现状见[仓库首页](../README.md)，文档清单见[文档导航](README.md)。

## 目录总览

```text
AlwayRoute/
├── AGENTS.md                          # 仓库协作、提交、同步及增量构建约定
├── README.md                          # 项目概览、当前进度和常用入口
├── .gitattributes                     # 文本文件 LF 换行规则
├── .gitignore                         # 凭证、产物、缓存和本地记录排除规则
├── contracts/
│   ├── v1.md                          # 配置模型与 RPC 契约
│   └── fixtures/                      # 合成配置、订阅输入样本
├── config/
│   └── routing/                       # 分流数据来源锁与历史部署组合
├── firmware/
│   ├── README.md                      # 固定构建输入、集成步骤和限制
│   ├── sources.lock.json              # 上游来源、版本、下载入口与源码树哈希
│   ├── openwrt/
│   │   ├── evaluation.config          # OpenWrt 配置 seed
│   │   ├── 99-alwayroute-management   # 基础管理入口首启脚本
│   │   ├── patches/                   # 针对固定上游版本的补丁
│   │   ├── alwayroute-core/           # 外部 sing-box 核心的打包配方
│   │   ├── alwayroute-manager/        # ucode 管理后端、RPC、ACL 与服务脚本
│   │   ├── alwayroute-forwarding/     # LAN 透明转发适配器及打包配方
│   │   └── luci-app-alwayroute/        # LuCI 页面、公共模块、样式与菜单
│   ├── tools/                         # 在 Rock 使用的核心构建、实验适配、监督和镜像检查工具
│   └── tests/                         # 固件密码实验的 Go 差分检查及实验说明
├── scripts/
│   ├── sync-rock.sh                   # 通用源码同步入口，默认 dry-run
│   └── fetch-sources.py               # 按锁定版本获取上游源码到 .local/sources/
├── tests/
│   ├── README.md                      # 测试入口、环境和覆盖范围
│   ├── manager/                       # 模型、订阅、事务、下载及超时检查
│   ├── firmware/                      # 构建监督及密码输入来源的主机检查
│   ├── integration/                   # 接口边界、转发、首启与运行时检查
│   └── ui/                            # Node 测试与离线页面预览
└── docs/
    ├── README.md                      # 完整文档导航及阅读顺序
    ├── repository-structure.md         # 本文件：目录职责与维护约定
    ├── requirements.md                # 持续维护的需求与验收标准
    ├── implementation-plan.md         # 当前实施方案
    ├── development-workflow.md        # 电脑源码与 Rock 构建工作流
    ├── upstream-sources.md            # 上游下载入口、阅读位置与本地源码维护
    ├── devices/                       # 持续维护的设备与网络记录
    ├── proposals/                     # 可行性分析、候选方案与历史提案
    └── reports/                       # 按日期归档的执行、构建和验证报告
```

此树展示主要目录和入口，没有展开全部包内文件。`.git/` 是 Git 元数据，不属于项目源码。

## 源码与工具职责

| 位置 | 保存内容 | 维护时同时关注 |
| --- | --- | --- |
| `contracts/v1.md`、`contracts/fixtures/` | 管理模型、接口约定及合成样本 | 前后端实现、权限和对应测试 |
| `config/routing/` | `sources.lock.json` 锁定公共参考来源，`deployments/` 记录历史组合并引用正式服务数据和 Git 提交 | 历史数量、顺序、来源与部署报告；不保存第二套业务规则 |
| `firmware/openwrt/alwayroute-manager/files/usr/share/alwayroute/policies/` | 唯一正式服务规则：`catalog.json` 文件名索引，各服务独立 JSON 保存后缀与精确域名 | 后端目录加载、规则优先级、来源说明及包安装；随包升级替换 |
| `firmware/openwrt/alwayroute-core/Makefile` | 外部核心 ELF、来源信息与许可证的安装配方 | 外部输入哈希及增量构建依赖 |
| `firmware/openwrt/alwayroute-manager/files/usr/share/ucode/alwayroute/` | `model.uc`、`subscription.uc`、`store.uc`：模型生成、订阅解析与配置事务 | `contracts/`、`tests/manager/` |
| `firmware/openwrt/alwayroute-manager/files/usr/share/rpcd/` | RPC 实现和 `acl.d/` 权限 | 前端 `api.js` 与接口边界检查 |
| `firmware/openwrt/alwayroute-manager/files/usr/libexec/`、`files/etc/` | 后台作业、下载、启动恢复、定时更新及 init 集成 | 事务、下载许可、超时和重启恢复验证 |
| `firmware/openwrt/alwayroute-forwarding/files/` | nftables／策略路由适配脚本 | 隔离转发测试和实机网络验证 |
| `firmware/openwrt/luci-app-alwayroute/htdocs/luci-static/resources/` | `view/alwayroute/app.js` 页面及 `alwayroute/` 下 API、模型和样式 | 契约、Node 检查及浏览器预览 |
| `firmware/openwrt/luci-app-alwayroute/root/` | LuCI 菜单等安装文件 | rpcd ACL 与页面入口绑定 |
| `firmware/tools/` | 核心构建、实验 overlay、`run-native-build.py` 构建监督、`inspect-image.py` 镜像检查 | 固定 Rock 路径、版本、哈希及检查配置 |
| `firmware/tests/` | 随密码实验适配器使用的 Go 差分测试及实验说明 | 固定补丁、overlay 输入路径和实验状态；不安装进固件 |
| `tests/firmware/` | 对构建监督和密码来源校验的主机检查 | `firmware/tools/`，与上述实验中编译到上游包的 Go 测试职责不同 |
| `scripts/` | 跨组件开发工作流：`sync-rock.sh` 同步、`fetch-sources.py` 上游获取 | 同步排除项、目标路径和固定版本来源 |

包内的 `files/`、`root/` 和 `htdocs/` 沿用对应安装布局；最终设备路径和权限以各包 `Makefile` 为准。后端细节见[管理包说明](../firmware/openwrt/alwayroute-manager/README.md)，构建集成见[固件说明](../firmware/README.md)。

## 本地环境资料

实际环境资料保存在被 Git 忽略的 `.local/lab/`，不属于项目默认配置。

## 新文件放置与变更规则

1. 新功能代码放入对应 OpenWrt 包；新增独立包时在 `firmware/openwrt/` 下按包名建目录，并同步维护构建说明及配置 seed。
2. 接口或配置语义写入 `contracts/`；可共享样本放入 `contracts/fixtures/`，使用合成域名和身份值，不保存真实订阅或节点凭证。
3. 测试按 `manager/`、`integration/`、`ui/` 归属存放；测试桩与预览模拟器保留在 `tests/`，不混入生产包。
4. 与固件构建、镜像检查直接相关的工具放入 `firmware/tools/`；跨组件工作流脚本放入 `scripts/`；一次性本机诊断文件放入 `.local/`，复用前再审查归档。
   正式服务分流数据放入管理包 `files/usr/share/alwayroute/policies/`，按完整服务独立管理，由 `catalog.json` 索引并随包安装；不可使用补丁式业务文件或在 `config/` 保存另一份规则。来源锁与历史组合保留在 `config/routing/`，组合记录引用正式服务文件和 Git 提交，不复制规则。其他公开配置放入 `config/` 对应目录；真实设备配置仍属于私有数据，不因目录存在而纳入 Git。
5. 文档按[文档导航中的维护规则](README.md#维护规则)归档；根目录保留项目入口和仓库级规则。
6. 改名或移动前检查全部引用，特别是测试中的仓库相对路径、包安装路径和文档链接。源码同步不使用 `--delete`，Rock 残留旧文件必须单独审查处理。
7. 完成修改后运行与改动相称的检查，按 `AGENTS.md` 创建中文 Conventional Commit；不同目的分开提交，远程推送需用户在当前请求中明确要求。

## 2026-10-23 命名与归属复核

检查了整理前全部 92 个受 Git 管理文件的路径与目录职责，并搜索了分流数据、脚本、测试和实验补丁的引用。确认的问题是 `scripts/routing-profiles/cn-tiktok.json` 名称只突出国内和 TikTok，却还包含 YouTube 补充，且静态配置数据混入脚本目录；该文件曾迁到 `config/routing/profiles/`。正式项目整理进一步将完整服务规则统一到管理包 `policies/`：保留原有 13 个服务域名，加入 TikTok 与 Domestic，将 YouTube 已知补充合入完整 YouTube 服务；`config/routing/` 只保留来源锁与实际历史部署记录。revision 20 的 120 条自定义规则及部署事实按历史 Git 提交还原，当前正式文件不充当历史快照。

其他目录没有发现需要批量移动的同类混放。OpenWrt 包的 `files/`、`root/`、`htdocs/` 是安装布局；`firmware/tests/` 的 Go 文件是实验 overlay 的构建输入，而 `tests/firmware/` 检查主机工具，保留两者并补全索引。`docs/reports/evidence/` 保存报告使用的脱敏证据，保持关联；按日期命名的历史报告保留当时观察和原补丁名称，不因候选撤回而改写历史或给现存补丁重新编号。

源码同步不自动删除旧路径；本次仅整理本机仓库，未来同步到 Rock 前仍须查看 dry-run，单独审查工作副本旧路径的清理，不涉及正在构建的 OpenWrt 树。
