# PC源码主本与构建主机构建流程

本文描述已有构建主机的增量开发流程。GitHub托管Runner从干净环境构建发布固件的独立入口见[tag构建说明](github-build.md)，不需要同步到个人构建主机。

电脑仓库保存AlwayRoute自有业务代码、构建配方、补丁与文档；构建主机保留独立源码副本、OpenWrt构建树、工具链及缓存。第三方源码通过[固定入口](upstream-sources.md)获取，本机阅读副本在`.local/sources/`，不进入Git，也不直接覆盖构建主机现有树。

## 环境与现有工具

三角色及字段见[环境说明](operations/environments.md)。公开示例只含占位值；实际配置在`.local/environments/current.json`。依赖已有Python、SSH及可用rsync／Git Bash；实际工具选择由入口帮助说明。缺少工具时报告，不安装软件，不写全局PATH、SSH配置、注册表或服务。过去获批的私有工具清单留在`.local/`供本机核对，不作为新环境已安装的证明。

文本工作文件使用UTF-8／LF；Git索引规范化不会自动改写现有工作文件，而rsync传的是实际字节。尤其核对脚本shebang不得带CR；最终权限以包Makefile为准，不把Windows权限直接当作设备权限。

## 同步自有源码

```powershell
# 默认dry-run，先审查范围和目标
python scripts/sync-source.py --env .local/environments/current.json
# 审阅后复制到build.project_workspace
python scripts/sync-source.py --env .local/environments/current.json --apply
```

兼容入口`.local/lab/scripts/sync-rock.sh`保留；先以`--help`核对实际支持参数。同步只指向独立源码工作副本，禁止将整仓库目标设为`build.openwrt_tree`。Git元数据、本地私有数据、凭证、备份、第三方下载树、工具链、缓存和产物都不随源码同步。

每次先看dry-run，再apply；apply须有成功预览并核对输入与远端差异未变。计划默认保存在`.local/runs/source-sync-plan.json`，可用`--plan`选择。同步不使用全树`--delete`。本地改名删除后，远端可能留旧文件，需先核对明确路径，再单独处理；不能顺手清理构建树或缓存。包集成到OpenWrt的`package/`是另一受控步骤，不能由整仓库同步代替。

## 远端修改回传

优先在PC修改再同步。若排障直接修改构建主机自有文件，先列出实际文件，从build.project_workspace或对应自有包路径回传到`.local/incoming/`，只选择属于本项目的源码／补丁。先dry-run，后复制；不要直接覆盖PC未提交修改。

用`git diff --no-index -- <本机文件> <回传文件>`审查（发现差异返回1正常），合并有价值内容、运行相称检查、创建本地提交，再同步确认。第三方变化整理为本仓库补丁，不能把整个上游工作树回传并加入Git；设备配置、备份和订阅也不属于回传源码。

## 增量构建与缓存

| 环境位置 | 复用边界 |
| --- | --- |
| `build.openwrt_tree/dl` | 固定来源与哈希的下载归档 |
| `build.openwrt_tree/build_dir` | 依赖仍有效的解包文件、对象与构建状态 |
| `build.openwrt_tree/staging_dir` | 已生成主机工具与交叉工具链 |
| `build.cache_root` | Go模块、编译及临时缓存 |
| `build.toolchain_root`、`build.output_root` | 已准备工具链及分批输出；输出不能覆盖有效基线 |

按变更范围构建组件，必要时增量重打镜像；不默认重编内核，不例行`clean`／`dirclean`／`distclean`或`git clean -xdf`。变版本、工具链或确需定向清理时，先说明原因和范围，保留仍有效缓存。自有包追踪外部核心、build-info、LICENSE与正式规则的变化，避免误用旧输入。

最后记录的OpenWrt配置未启用`CONFIG_CCACHE`；系统存在ccache不能证明当前构建使用它，切换也不能使旧编译自动成为命中。固件配方与检查见[固件说明](../firmware/README.md)，设备应用见[部署边界](operations/deployment.md)。
