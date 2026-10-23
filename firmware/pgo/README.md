# 4A 发布构建的 PGO 输入

`xiaomi-4a-mixed-cpu.pprof` 是项目在小米 4A 第一版千兆设备上采集的混合负载 CPU profile，作为编译输入跟踪，不是设备配置或固件产物。对应[完整功能加密优化记录](../../docs/reports/2026-10-23-crypto-optimization.md)。

- SHA-256：`c0ca6b0e9e2e79d1840e6493e8eb7470a67e2086bfc22ecc5b1865d839c03012`，与历史记录一致，原字节保留。
- 2026-10-23 从构建主机只读取回；审查 gzip/protobuf profile 的字符串表、样本标签和注释。388 项字符串为运行时／源码符号、源码文件、采样单位和映射标识，唯一绝对路径为 `/usr/bin/sing-box`；样本标签和注释均为零，没有 URL、节点认证或个人主机路径。
- 采样数据只用于编译器热点决策，不包含抓包、请求内容、节点配置或订阅文件。此项目自有采样输入采用仓库 MIT 许可。
- 固定选择、文件哈希和 Go 工具链见 [release.json](../release.json)。更新 profile 必须重新审查内容、容量和实际行为；不能从 profile 复用推导新固件已通过实机验收。
