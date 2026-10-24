# 核心资源释放回归

`011-sing-box-tproxy-close-failed-socket.patch` 在复用 UDP 回写连接写失败时，
先显式关闭旧连接再清空引用。修复由 `build-core.py` 对所有架构和密码后端强制应用，
与可选 TLS／密码 overlay 合并为一个 Go overlay，不改上游源码、GOROOT 或模块缓存。
构建清单记录原始源码、补丁及输出的 SHA-256；镜像检查重建源码并核对精确替换范围。
历史 baseline 检查仍可读取旧核心；新的 manager／release 检查要求资源修复清单。

在已有构建主机及离线模块缓存中运行：

```sh
python3 tests/firmware/run_resource_tests.py --env /path/to/build-environment.json
```

该入口只执行宿主 Linux 的 redirect 包两项定向测试，不运行设备程序或服务。
测试使用普通 loopback UDP socket，过期写 deadline 产生真实错误；断言错误返回、
缓存引用清空及原 socket 已关闭，并验证正常写入仍保留连接和正确传输载荷。
入口还在临时 overlay 中移除关闭语句再运行同一错误测试，确认未修复版本确实失败。
测试源码只注入临时测试 overlay，不进入正式核心或上游目录。
