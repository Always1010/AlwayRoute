# 第三方来源与许可

本仓库保存自有适配、配方和补丁；完整上游树与生成产物留在被忽略的目录。以下说明帮助定位原有声明，不将第三方内容重新许可为 MIT。

| 来源 | 仓库中的关联内容 | 保留方式 |
| --- | --- | --- |
| OpenWrt、LuCI、packages | 固件 seed、包配方、目标适配，来源锁定在 `firmware/sources.lock.json` | 各上游树和包使用各自声明；OpenWrt 工程的许可不能代替每个包的许可 |
| sing-box | 外部核心的构建／打包与来源信息 | 保留上游 GPL-3.0-or-later 及版权；核心包安装上游 LICENSE，不能替换成项目 MIT |
| Go、golang.org/x/crypto | 加密补丁、overlay 和差分测试 | 保留补丁原文中的 Go BSD 及其他来源声明；Linux／WireGuard 派生片段中的 GPL-2.0 OR MIT 声明不删改 |
| V2Fly domain-list-community | 正式服务规则的参考资料，提交和逐文件哈希见 `config/routing/sources.lock.json` | 上游采用 MIT，归属 Copyright (c) 2018-2019 V2Ray；原文保存在 [许可文本](LICENSES/domain-list-community-MIT.txt) |
| MetaCubeX meta-rules-dat | 通用国内域名和目的 IP 集合的固定源 JSON，经构建主机编译后随管理包安装 | 保留该分发仓库的 GPL-3.0 文本；源数据、许可证的提交及 SHA-256 见同一来源锁，完整许可证安装到规则目录，原始源与构建输入另行保留 |

业务服务保留选择性规则；国内组使用外部通用集合，不维护特定国内应用清单。来源、匹配语义及构建流程见[规则说明](config/routing/README.md)。不把采样得到的私人访问记录作为公共数据发布。

补丁中的上游作者、邮箱与版权行属于归属信息；项目隐私清理不删除这些署名。发布前仍需按实际镜像包清单检查新增依赖，本文不替代完整固件中各包附带的声明。
