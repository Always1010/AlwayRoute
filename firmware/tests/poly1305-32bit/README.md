# 历史 32 位 Poly1305 独立实验

004 是默认关闭的源码候选，与 003 汇编实验、生产构建脚本和镜像检查器独立。不叠加两个
overlay，不改变 ChaCha，不增加汇编，不回退 Go 或整个 x/crypto 依赖版本。

固定来源为 Go x/crypto 重写前提交
[`bd318be0434a57050ed475e0f45c3dbb16c09c2e`](https://go.googlesource.com/crypto/+/bd318be0434a57050ed475e0f45c3dbb16c09c2e/poly1305/sum_generic.go)
的 `poly1305/sum_generic.go`，SHA-256 为
`017c015b4df791195634145bded2dcd805d451054e1cbb7a68f61d4e943f063f`。
该实现也随 [Go1.13.15](https://github.com/golang/go/blob/go1.13.15/src/vendor/golang.org/x/crypto/poly1305/sum_generic.go)
发布。2017 年 32 位计算实现的
[合并记录](https://go.googlesource.com/crypto/+/537c9dfe43c8ca78e68e340fc140bca4d8bfaaa0)
包含 Michael Munday、Adam Langley 审阅；2019 年流式封装的
[合并记录](https://go.googlesource.com/crypto/+/c2843e01d9a2bc60bb26ad24e09734fdc2d9ec58)
由 Filippo Valsorda 审阅。后续
[64 位重写](https://go.googlesource.com/crypto/+/2dbfe9001fa8e8b979ff80a1c88b888d48e1b575)
说明可读性和 Xeon／Mac 性能收益，没有声明旧实现存在安全修复问题；这并不构成对旧代码
全部历史风险的排除，也不意味着当前适配已获上游审查。

旧文件只增加 MIPSLE／gc／非 purego build constraint，并重命名五个内部标识符，避免与
保留的当前 64 位 generic 冲突。helper 反向撤销这些名字／build tag 后核对原文件 SHA-256，
确保初始化、clamp、乘法、进位、归约和最终输出没有自行改写。原 Go BSD 声明保留。
旧类独立持有 `h,r [5]uint32`、`s [4]uint32`、buffer 和 offset，没有生产状态转换。

唯一公共源码适配是在 `New` 内部将初始化语句改为内部构造函数调用。MIPSLE gc 非 purego
构造旧类；其他架构和 purego 继续执行原初始化。MAC 的 Verify、finalized 和 Sum／Verify 后
禁止 Write 的逻辑逐字保留；当前 AEAD、重叠检查、counter 边界和 20 轮 ChaCha 不变。

在 Rock 用已有工具生成全新 stage；helper 不下载、不安装、不改缓存或 GOROOT。Go 不允许
overlay 覆盖 GOMODCACHE，因此模块复制到 stage/module 后再覆盖，标准库 vendor 也覆盖同一
份候选。`--include-tests` 专供 MIPSLE gc 非 purego 测试；其他架构的后备检查使用不带该选项的
独立 stage。

```sh
ROOT=/srv/alwayroute
STAGE="$ROOT/artifacts/poly1305-32bit-review-stage"
GO="$ROOT/toolchains/go1.27.3/go/bin/go"
python3 firmware/tools/poly1305-32bit-overlay.py \
  --module-root "$ROOT/build-cache/gomodcache/golang.org/x/crypto@v0.48.0" \
  --goroot "$ROOT/toolchains/go1.27.3/go" --stage "$STAGE" --include-tests
export GOOS=linux GOARCH=mipsle GOMIPS=softfloat CGO_ENABLED=0
export GOTOOLCHAIN=local GOPROXY=off GOMAXPROCS=2
export GOCACHE="$ROOT/build-cache/gocache" GOMODCACHE="$ROOT/build-cache/gomodcache"
export GOPATH="$ROOT/build-cache/gopath" TMPDIR="$ROOT/build-cache/tmp"
cd "$STAGE/module"
for package in internal/poly1305 chacha20poly1305; do
  name=$(printf '%s' "$package" | tr / _)
  "$GO" test -c -p 1 -pgo=off -overlay="$STAGE/overlay.json" \
    -o "$STAGE/legacy32_module_$name.test" "./$package" || exit 1
  "$GO" test -c -p 1 -pgo=off -overlay="$STAGE/overlay.json" \
    -o "$STAGE/legacy32_vendor_$name.test" "vendor/golang.org/x/crypto/$package" || exit 1
done
```

执行入口统一为 `firmware/tools/run-device-tests.py --env /path/to/operation-environment.json --binary FILE...`。
默认仅离线校验和计划，`--preflight` 只读验证设备与资源，显式 `--apply` 才执行。
必须选择本轮全部四个模块／vendor测试产物，不能把单个示例当作完整验收。
低内存、繁忙作业或未完成配置事务会被拒绝，不为运行测试自动停生产或改系统参数；微基准保持显式、独立执行。

四个二进制都须在设备完整执行 `-test.v -test.timeout=5m`。原 TestBurnin 默认 skip，不开启
慢速 `-stress`，不缩小其他测试范围，不关闭 vet。上游所有预期 tag、Verify 篡改拒绝和
AEAD 负例保持；New 的四条非规范初始累加器向量仅在测试中用三个等值常量 fixture 连接旧
布局，未知新 fixture 会报错，没有删除、跳过或修改预期结果。当前 64 位 generic 的测试
保持原样，003 的随机／分块差分测试复用为 New 对照当前 64 位 generic，另验证精确填满
16 字节缓冲区、重复 Sum、Verify 正反例及 Sum／Verify 后 Write 必须 panic。

全测试通过后，两个 AEAD 二进制与既有 generic 基线采用相同参数串行微基准：

```sh
./对应二进制.test -test.run='^$' \
  -test.bench='^BenchmarkChacha20Poly1305$/(Open|Seal)-8192$' \
  -test.benchtime=2s -test.count=3 -test.cpu=4 -test.benchmem
```

该结果是单 goroutine 的加解密速度，不能替代完整代理吞吐与运行验收。获准比较完整核心
时，从已核验 full CLI／上游 registry 基线 metadata 复用原 command、gcflags、PGO 文件及
SHA-256，仅另加 004 overlay 和临时 `-modfile` 的模块 replace，记录全部差异；不能修改生产
脚本、源 go.mod、module cache、GOROOT 或默认启用候选。任何边界测试失败立即停止候选，
不改密码计算来迎合测试。历史代码已合并的来源证据也不能替代本次适配的独立密码审查。
