# 分流规则来源与维护

正式服务元数据位于管理包的 `files/usr/share/alwayroute/policies/`，随包安装到 `/usr/share/alwayroute/policies/`。`catalog.json` 决定界面顺序；实际路由与 DNS 优先级由后端统一生成。`domains` 表示后缀，`exactDomains` 表示精确主机，两者不能互相扩大范围。

## 国内集合

国内策略组使用通用社区国内域名集合与国家顶级域补充，不在项目中维护针对特定国内应用的清单、测试样例或专属策略组。数据来源及版本固定在本目录唯一的 [sources.lock.json](sources.lock.json)。其中 `files` 保留其他服务的审查参考；`ruleSets` 是必须构建和安装的国内集合输入，不能把二者混为仅供参考的链接。

首版域名基础来自 MetaCubeX 发布的 `geolocation-cn`，并非该项目覆盖范围更大的 `cn`。集合的精确域名、后缀和正则语义均由同版本 sing-box 编译保留。第三方源 JSON、编译产物和缓存不加入 Git，设备只安装本地二进制 `.srs`、来源清单和第三方许可证，不在启动时下载规则。

手工规则先于正式业务；明确业务及境外聚合先于国内集合；未命中流量仍交给 Other。路由和 DNS 引用同一个域名规则集，DNS 依据国内组的实际出口选择。删除国内组或使用全局／直连模式时，不加载也不应用国内规则集。新增集合不占用户手工规则额度，不改变已有节点、组选择、配置版本或 Other 的出口。

## 构建与增量输入

在构建主机的独立源码副本中，使用已有的 sing-box 1.13.21 主机 CLI：

```sh
python3 scripts/build-routing.py --sing-box /path/to/host/sing-box \
  --cache /path/to/private/routing-cache --output /path/to/new/routing-output --fetch
```

`--fetch` 显式允许下载固定提交的输入；不带该选项时只读已缓存内容。脚本校验 SHA-256、输入字段和基础范围，输出必须是新目录；失败不会覆盖既有产物或自动修复损坏缓存。源码 JSON 留在输出的 `sources/` 供审查和复现，不安装到设备。

审查生成的 `manifest.json` 后，把输出中的 `*.srs`、`manifest.json` 和 `LICENSE` 放入所选 OpenWrt 树的 `alwayroute-input/routing/`，不复制 `sources/`。管理包用 `PKG_FILE_DEPENDS` 跟踪这些外部输入，并在 Prepare 阶段保存构建快照；不能只替换源文件却复用旧包。

本机源码、同步预览、构建缓存及部署边界仍遵循 [开发流程](../../docs/development-workflow.md)。规则生成与包构建在构建主机执行，不安装本机依赖，不清理工具链或下载缓存。

## 更新和验证

建议每周检查上游变动，审查差异后更新锁定提交与哈希，重新生成并验证，再随已审阅的包或固件发布。此维护建议不创建定时任务。固定输入哈希只能确认版本完整性，不能证明上游分类绝对准确；扩大共享平台、正则或顶级域范围必须单独审查。

验证使用合成域名保护手工覆盖、业务优先级、组出口、模式隔离和缺失文件拒绝等边界；设备连接及 DNS 采样保存在私有目录，公开报告仅记录脱敏的数量、类别和结果。不能以域名命中、配置校验或一次 HTTP 成功代替完整应用与长期负载验收。

历史部署事实见 [报告索引](../../docs/reports/README.md)，旧版人工选择性覆盖的历史数量不代表当前规则规模。
