# 设备支持与验证范围

AlwayRoute 的通用功能面向具备所需能力的 OpenWrt 环境。设备支持必须结合具体硬件修订、上游支持、构建检查与实机证据判断；CPU 相同、内存足够或镜像编译成功都不能替代设备验收。

| 设备 | 当前范围 | 记录 |
| --- | --- | --- |
| 小米路由器 4A 千兆版，第一版 | 首个已构建、刷写及部分功能实测的目标；完整验收仍有剩余项 | [设备事实](xiaomi-4a.md)、[刷机指南](xiaomi-4a-flashing.md)、[当前状态](../status.md) |
| 其他型号／修订，包括 4A V2 | 尚未完成项目适配与实机验证，不发布兼容承诺 | [移植与验证流程](../device-porting.md) |

16 MB Flash／128 MB RAM 是当前设备的事实，不是所有目标的推荐规格或项目最低配置。实际约束包括固件分区、可写空间、运行内存峰值、CPU 性能及使用负载。

构建主机、跳板和测试终端属于开发环境，不属于目标设备支持条件。当前实验环境采用 Rock 5B，不要求其他开发者使用该型号；真实连接和路径保存在私有环境文件中。

当前4A的[设备配方](../../firmware/devices/xiaomi-4a-gigabit.json)、[设备seed](../../firmware/devices/xiaomi-4a-gigabit.config)和[原始完整seed快照](../../firmware/openwrt/evaluation.config)均纳入版本管理；后续设备另建配置。当前个人首启参数另存为[部署策略](../../config/deployment/README.md)，不混入硬件配方。
