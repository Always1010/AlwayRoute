# 标准 TLS 会话恢复候选

`session_test.go` 通过 Go overlay 加入固定 sing-box 1.13.21 的
`common/tls/alwayroute_session_test.go`，不复制进上游源码树或固件。
使用 `firmware/tools/tls-session-overlay.py` 的 `add_overlay()` 生成生产补丁，
再在同一 `Replace` 中加入上述测试文件的绝对路径。

在既有构建主机运行该包的 `go test`，沿用 `build-core.py` 的固定 Go、tags、
离线模块缓存和隔离环境，加入 `-ldflags=-checklinkname=0`。
选择 `-run '^TestOutboundSessionResumption$' -count=1` 验证 TLS 1.2／1.3
实际恢复、两个独立 outbound 的票据隔离，以及错误主机名证书拒绝。
需要相对微基准时增加
`-bench '^BenchmarkOutboundSessionHandshake$' -benchtime=30x`。

候选核心用 `build-core.py --tls-session-cache` 显式启用；可与既有
`--crypto-inline --pgo ... --experimental-crypto mipsle-asm-r2` 组合。
默认关闭，不改变公开发布配方。每个标准 TLS outbound 独立缓存最多四项，
不启用 TLS 0-RTT，不改变 Reality／uTLS 实现或证书校验配置。
镜像检查会重建并核对补丁、源文件、生成文件和 overlay 的精确范围。

ARM 主机微基准包含同机 TLS 服务端与客户端，只用于验证方向；不能据此
推导 MIPS 路由器或公网请求的时延收益。设备测试先检查内存，不向低内存
生产设备复制完整候选 ELF 或强行启动第二个核心。
