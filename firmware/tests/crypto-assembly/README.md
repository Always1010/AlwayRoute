# MIPSLE 加密汇编实验

此候选默认不启用，不接入固件默认构建。来源为 stffabi 提交的
[Go CL585755](https://go-review.googlesource.com/c/crypto/+/585755)，固定 revision
`45132dae57e76146e71cc1cda14e3a75dffe2457`，对应
[golang/crypto PR294](https://github.com/golang/crypto/pull/294)。导入时仍为 NEW／未合并，
没有上游密码审查通过结论。作者的 MT7688 性能数据不能作为 MT7621 的验收数据。

两份 `.s` 和 ChaCha Go glue 保持原始字节。唯一 Poly1305 glue 适配将汇编入口声明
的参数名 `msg` 改为 `D`，匹配原汇编 `D_base/D_len`，使 asmdecl 检查通过；参数类型、
偏移、调用、算法均未改变。另将两个 noasm build constraint 适配到 x/crypto v0.48.0。
原作者的 Go BSD、Linux／WireGuard GPL-2.0 OR MIT 来源与许可声明均保留在补丁中。
本候选使用原作者 MIPS32r1 路径，不开启未合入 Go 的 `GOMIPS_r2/r5` 宏。

`crypto-assembly-overlay.py` 核对模块 go.mod、两份库的四个 glue／状态布局文件和补丁
SHA-256，拒绝既有 stage；不下载或修改缓存／GOROOT。Go 禁止 overlay 替换 GOMODCACHE
内文件，因此 helper 将模块复制到 stage/module，overlay 替换该副本及 GOROOT vendor
中的六个文件。标准库 vendor 与模块的输入哈希相同，仍分别构建、执行测试。

在 Rock 使用已有 Python／Go 与缓存，从本仓库的独立工作副本运行。`STAGE` 必须是尚不存在
的目录；输出和 stage 不放在模块缓存或 GOROOT 内。

```sh
ROOT=/srv/alwayroute
STAGE="$ROOT/artifacts/crypto-assembly-review-stage"
GO="$ROOT/toolchains/go1.27.3/go/bin/go"
python3 firmware/tools/crypto-assembly-overlay.py \
  --module-root "$ROOT/build-cache/gomodcache/golang.org/x/crypto@v0.48.0" \
  --goroot "$ROOT/toolchains/go1.27.3/go" --stage "$STAGE" --include-tests

export GOOS=linux GOARCH=mipsle GOMIPS=softfloat CGO_ENABLED=0
export GOTOOLCHAIN=local GOPROXY=off GOMAXPROCS=2
export GOCACHE="$ROOT/build-cache/gocache" GOMODCACHE="$ROOT/build-cache/gomodcache"
export GOPATH="$ROOT/build-cache/gopath" TMPDIR="$ROOT/build-cache/tmp"
cd "$STAGE/module"
for package in chacha20 internal/poly1305 chacha20poly1305; do
  name=$(printf '%s' "$package" | tr / _)
  "$GO" test -c -p 1 -overlay="$STAGE/overlay.json" \
    -o "$STAGE/module_$name.test" "./$package" || exit 1
  "$GO" test -c -p 1 -overlay="$STAGE/overlay.json" \
    -o "$STAGE/vendor_$name.test" "vendor/golang.org/x/crypto/$package" || exit 1
done
```

编译不等于运行验收。设备执行由主 Agent 统一安排，每个二进制使用
`-test.v -test.timeout=5m` 运行所有常规测试。不要设置 `-test.run` 缩小范围，不要关闭 vet，
不要开启默认跳过的慢速 `-stress`。这些测试覆盖：

- 原有 ChaCha RFC 向量、独立缓冲／in-place、未对齐、流式分块、SetCounter、最后一个块及溢出拒绝。
- 原有 Poly1305 向量、非规范初始累加器、未对齐、分块 Write、Verify 失败。
- 原有 AEAD TestVectors 和 TestRandom，包含修改 AAD／nonce／ciphertext 后必须认证失败。
- 新增确定性随机差分，将 asm 与原 generic 输出逐字节比较；覆盖 0、16／64 字节附近、
  1KiB／4KiB／16KiB 附近，ChaCha 独立 src/dst 偏移组合、整块 in-place、不同调用分块。

汇编入口由原有 Go wrapper 保证长度非零且按 64／16 字节对齐；不得直接绕过 wrapper。
测试不代替独立密码审查或长时间稳定性验证。任何测试失败均停止候选推广，不修改密码计算
来迎合测试。加密协议、20 轮 ChaCha、Poly1305 认证和安全校验均须保留。

需要实验核心时，另建临时 `-modfile`，复制主模块的 go.mod／go.sum，在临时 go.mod 追加
`replace golang.org/x/crypto => <stage/module 的绝对路径>`，并同时传入 overlay；不得编辑原始
go.mod、module cache 或 GOROOT。默认构建不创建或引用这些实验文件。

完整核心的显式候选构建已接入 `firmware/tools/build-core.py`，例如：

```sh
python3 firmware/tools/build-core.py --crypto-inline \
  --pgo "$ROOT/artifacts/alwayroute-bottleneck-20261023/mixed-cpu.pprof" \
  --experimental-crypto mipsle-asm-r2 \
  --output "$ROOT/artifacts/crypto-candidate/sing-box-mipsle"
```

`mipsle-asm` 使用原始 shift/or；`mipsle-asm-r2` 仅对模块版和标准 TLS vendor 版
ChaCha 包追加 `-D GOMIPS_r2` 汇编参数，使用原补丁已有的 ROTR 路径。Go 编译器、
`GOMIPS=softfloat`、20 轮算法、Poly1305 校验及全部核心功能均保持。
MT7621 的 1004Kc 支持 MIPS32r2；该候选没有 CPU 运行时分派，不能作为通用 mipsle
二进制分发。构建记录保留明确的实验状态，不能将本地验证描述为上游批准。

镜像检查默认拒绝密码 overlay。检查明确选定的候选时，必须另外传入同名
`--experimental-crypto`，并以实际设备测试过的 ELF SHA-256 调用检查器。通过构建和
镜像检查都不等于完成运行验收；吞吐比较须保留单连接与多连接、TCP 与 TLS，并在
相同存储／内存条件下比较。新增保护页测试用于检测越界读取／写入，不能替代完整
AEAD 向量、认证失败和状态边界测试。
