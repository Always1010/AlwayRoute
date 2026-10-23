# VMess 分帧 I/O 最小候选

此候选默认不启用，固定 sing-vmess
`v0.2.8-0.20250909125414-3aed155119a1`。仅修改 StreamChunkReader：

- 在 Reader 内复用 2 字节 scratch，以 `io.ReadFull` 和 `BigEndian.Uint16`
  代替 `binary.Read` 的临时分配。结构体实际增量受平台对齐影响。
- padding 长度为零时跳过 `io.CopyN`；非零 padding 保留原读取路径。

没有改变读取长度、帧边界、SHAKE 输入与顺序、加密算法、计数、取消、关闭或
deadline，没有增加预读、聚合等待或连接级大缓冲。裸 VMess TCP 默认 chacha
会经过此路径；sing-box 的 TLS + security=auto 会选择 zero，TCP 不走此 Reader，
因此不能将该候选描述为 WS/TLS 提速方案。

`io-path-overlay.py` 核对原模块 go.mod 和源文件 SHA-256，并精确应用补丁，
将模块复制到新 stage。它不会改动模块缓存、GOROOT 或默认构建配置。
完整核心构建应在临时 `-modfile` 中替换 sing-vmess；与现有密码 overlay 组合
由主构建流程负责，不能编辑原 go.mod。

在 Rock 的仓库独立工作副本运行，使用已有 Go 和依赖缓存：

```sh
ROOT=/srv/alwayroute
STAGE="$ROOT/artifacts/io-path-review"
GO="$ROOT/toolchains/go1.27.3/go/bin/go"
python3 firmware/tools/io-path-overlay.py \
  --module-root "$ROOT/build-cache/gomodcache/github.com/sagernet/sing-vmess@v0.2.8-0.20250909125414-3aed155119a1" \
  --stage "$STAGE" --include-tests
export GOTOOLCHAIN=local GOPROXY=off GOMAXPROCS=2 CGO_ENABLED=0
export GOCACHE="$ROOT/build-cache/gocache" GOMODCACHE="$ROOT/build-cache/gomodcache"
export GOPATH="$ROOT/build-cache/gopath" TMPDIR="$ROOT/build-cache/tmp"
cp "$ROOT/sources/sing-box-1.13.21/go.mod" "$STAGE/test.mod"
cp "$ROOT/sources/sing-box-1.13.21/go.sum" "$STAGE/test.sum"
"$GO" mod edit -modfile="$STAGE/test.mod" -module=github.com/sagernet/sing-vmess \
  -droprequire=github.com/sagernet/sing-vmess
cd "$STAGE/module"
"$GO" test -modfile="$STAGE/test.mod" -p 1 -run '^TestAlwayRouteFraming' -count=1 .
"$GO" test -modfile="$STAGE/test.mod" -p 1 -run '^$' -bench '^BenchmarkAlwayRouteFraming$' -benchmem -benchtime=1s .
GOOS=linux GOARCH=mipsle GOMIPS=softfloat "$GO" test -modfile="$STAGE/test.mod" -p 1 -c -o "$STAGE/framing-mipsle.test" .
```

差分 oracle 保留原 Read 实现；测试比较输出、返回长度、错误及底层消费字节数，
覆盖 masking/padding 组合、短帧、零长终止、超长帧、碎片、EOF、截断、注入错误及
Read/ReadBuffer 交替。编译与主机微基准不代表 4A 吞吐提升；4A 上测试和真实 TPROXY
流量对照统一由主 Agent 调度，确认无延迟/稳定性回退后才决定是否采用。

## 独立 WebSocket 帧头候选

`007-ws-header-scratch-experimental.patch` 固定
`github.com/sagernet/ws v0.0.0-20231204124109-acfe8907c854`，新增接受调用方
12 字节 scratch 的 `ReadHeaderBuffer`；原 `ReadHeader` API 保留原行为。
只有已有串行读取语义的 `wsutil.Reader.NextFrame` 使用 Reader 内 scratch。
两次头部读取的长度和次数、错误、mask、长度高位及原有帧检查保持不变。
不增加预读或聚合，也不改变 TLS 校验、WebSocket mask 或控制帧处理。

helper 使用 `--candidate ws-header` 和对应 ws 模块的 `--module-root`；必须另选
fresh stage。输出的 `module_replace` 键是 `github.com/sagernet/ws`，可以与 VMess
和密码候选的替换合并。测试文件位于 `ws/`，helper 将其放入 ws 模块根目录。
与上面的 VMess 测试一样复制 sing-box 的 go.mod/go.sum 到该 stage 的 test.mod/test.sum，
以保留实际固件依赖版本，但 `go mod edit` 的 `-module` 和 `-droprequire` 均改为
`github.com/sagernet/ws`；以下命令在此 ws stage/module 内执行。

```sh
"$GO" test -modfile="$STAGE/test.mod" -p 1 -count=1 . ./wsutil
"$GO" test -modfile="$STAGE/test.mod" -p 1 -run '^$' -bench '^BenchmarkAlwayRouteHeader$' -benchmem -benchtime=1s .
GOOS=linux GOARCH=mipsle GOMIPS=softfloat "$GO" test -modfile="$STAGE/test.mod" -p 1 -c -o "$STAGE/header-mipsle.test" .
GOOS=linux GOARCH=mipsle GOMIPS=softfloat "$GO" test -modfile="$STAGE/test.mod" -p 1 -c -o "$STAGE/wsutil-mipsle.test" ./wsutil
```

新差分测试对照原 `ReadHeader`，比较头部、错误、消费字节数和实际 Read 调用次数，
覆盖掩码、长度编码边界、高位非法值、控制帧标志、截断和连续复用。固定的 ws 模块
未附带上游测试，因此另加最小 wsutil 集成测试，检查分片、中间 ping、连续不同长度
帧、解掩码、错误掩码拒绝、帧长限制和截断错误。微基准只衡量帧头解析，不能外推整机吞吐。
