# 外部代理最小协作语义 v1

本契约描述 AlwayRoute 外接后端与外部网关的共同边界。Coproxy 的对应说明见其 `docs/router-cooperation.md`；双方独立发布，不要求共享源码或真实环境配置。本版只实现路由器后端，不代表对端接管、设备部署或联合验收已经通过。

## 范围与责任

- 首轮是一台明确来源的终端、IPv4 TCP/UDP、真实地址 DNS。终端默认网关和 DNS 入口保持为路由器；公网 IPv6 对受管终端阻断，本地管理保留，其他终端不受影响。
- 路由器选择来源并保留原 IPv4 地址交付网关；网关完成接管、分流和新建出站连接。网关出站经过路由器 WAN，回程经过路由器；同 LAN 的来源 MAC、连接跟踪与回程必须实测，不增加端间 SNAT 掩盖问题。
- 路由器管理自己的 nft、策略路由和专用 DNS 进程；网关管理自己的核心、接管、出口和解析。任一端不得修改对方配置。
- 已确认故障策略为 `block`：开启后对端、核心或 DNS 故障，不自动改为直连。保留开启意图、报告异常；用户显式关闭后撤销自有接管和防护，恢复普通直连。初次开启在预检失败时保持原状态。

## 路由器配置

独立配置不复用旧节点模型；旧 Rule/Global/Direct 不迁移为外部启用。缺少外部配置时默认为关闭。

```json
{
  "schema": 1,
  "revision": 0,
  "enabled": true,
  "family": "ipv4",
  "faultPolicy": "block",
  "link": {
    "interface": "br-lan",
    "routerAddress": "192.0.2.1",
    "gatewayAddress": "192.0.2.2",
    "gatewayMac": "02:00:00:00:00:02"
  },
  "clients": [{"address": "192.0.2.3", "mac": "02:00:00:00:00:03"}],
  "dns": {"gatewayPort": 1053, "listenPort": 1053, "localDomains": ["lan"]},
  "bypass4": []
}
```

示例为合成地址，不是部署参数。`link.interface` 是实际 L3 接口；三个地址和两个 MAC 必须互异。网关稳定地址和 MAC 由管理员核验，不能从历史 DHCP 记录推断。`bypass4` 是明确的额外目的 CIDR 例外，标准私网、保留与广播/组播范围另由适配器保护。例外意味着不进入外部接管，应按最小范围设置。

`dns.listenPort` 是路由器的独立监听，不能占用基础 DNS 53；`gatewayPort` 是网关受限 UDP/TCP DNS 入口。仅选中终端的 UDP/TCP 53 转到专用解析器；本地域后缀和无点名称交给路由器基础 DNS，公网查询交给网关。不改所有终端共用的 dnsmasq 上游。网关 bootstrap 使用独立基础解析，不能返回本条公网转发链。DoH/DoT 按业务流量处理，不由 53 重定向冒充控制。

## 管理与状态

新增认证 RPC：`external_get`、`external_status`、`external_save(expectedRevision, config)`、`external_apply(expectedRevision, peer?)`、`external_disable`。保存只递增 revision，不触网；应用以保存版本做 CAS。耗时应用/关闭沿用后台 job 和 manager 锁，外部操作不生成、不校验、不启动本机代理核心。

日常应用只提交 `expectedRevision`，缺省或空对象 `peer` 使用网关 UDP DNS 预检：从已校验配置读取 gateway IPv4 和 `dns.gatewayPort`，用现有 nslookup 向该入口查询固定的 `example.com`，由既有超时工具限制为 3 秒。每次应用强制新查询，不复用状态缓存；无新依赖、网关控制 API 或后台监控服务。查询失败发生在转发预备与网络修改之前，保留原状态；原已开启状态继续保留既有转发与故障阻断语义，绝不自动切直连。缺少兼容的 nslookup 或超时工具同样视为预检失败。

UDP 查询成功仅证明当时该入口能回答这次 UDP DNS 查询，不证明 TCP DNS、网关核心、流量接管、真实来源、出站或回程。不得据此填入人工观察六项 true、生成 generation 或宣称端到端通过。网关策略和路径仍需按联合验收门槛实测。

兼容保留非空 `peer` 的人工观察路径：必须匹配 gateway、所请求 revision 和对端 generation，携带 `observedAt`，应用前后最多 30 秒。`coreReady`、`captureReady`、`dnsReady`、`egressViaRouter`、`returnViaRouter`、`sourcePreserved` 均需基于实测为 true。此路径标记为 `operator`，不会描述为机器独立证实或终端已验收；网页的正常保存/应用流程不要求填写此表。

状态区分 `savedRevision`、`desiredEnabled`、`appliedRevision`、`phase`、`applicationMethod`、`localForwarding`、`dns`、`gatewayDns`、`peer` 和 `lastError`。`applicationMethod:gateway-dns` 与 `operator` 分别记录应用依据；本地应用、专用 DNS 进程/监听、网关 UDP DNS 观察和端到端出口分开报告。`gatewayDns` 带 `method:udp-query`、`status`（`reachable` / `unreachable` / `unknown`）、`observedAt`、`ageSeconds` 和 `cacheSeconds:60`。`external_status` 仅对正常活动的 DNS 应用模式观察已应用配置，独立 `/tmp` 私有缓存每 60 秒至多发起一次新观察并刷新缓存，轮询不改事务状态；缓存过期而锁忙或缓存不可用时报告 unknown，不能沿用旧值声称当前健康。缓存损坏或不安全不阻止显式应用/关闭，不修复未知权限或链接。`external_get` 只返回已有快照，不发出查询。

`phase:active` 只表示本地应用及该模式的有界观察符合条件，绝不代表完整路径通过。DNS 模式不受人工观察的 30 秒期限影响；DNS 失败/未知或本地检查失败报告 degraded，保留开启意图与转发。兼容人工观察过期仍报告 unknown/degraded。`endToEnd` 与 `baseConnectivity` 始终为 `unverified`，由实际终端验收证明，不能由 RPC 写成通过。重启与事件恢复仍先阻断、再显式重新应用，不复用旧观察自动激活。

## 事务、关闭与恢复

外部配置、应用记录与 journal 独立于本机节点文件。应用持同一 manager 锁：校验与预检 → 持久化恢复记录 → 建立来源范围防护 → 专用 DNS 与路由/nft 应用 → 本地确认 → 持久提交。发生错误恢复上一个确认状态；旧状态开启而恢复失败时保留阻断和 journal。存在未完成事务时禁止新的普通应用，先恢复或显式关闭。

独立关闭不读取旧节点模型、不依赖外部设备在线，不因配置损坏失去入口；先停止重建意图，再核对并撤销自有资源，失败保留残留并允许重试。仅清理与本地基础条件确认成功后报告 `disabled`；WAN、DNS 与真实终端直连仍需联合验收。不会清空全局防火墙、路由表或 conntrack。

启动、网络及 firewall 事件使用同一个锁和持久意图。开启意图下先建立阻断，重新预检后显式应用；关闭不复活代理。与本机核心共存或资源归属不明时拒绝开启，先使用已有本机停止入口退出本机模式，不隐式切换旧配置。

## 联合验收门槛

固定双方源码/安装版本、核心版本、来源范围、超时与观察方式；单终端验证 TCP/UDP、DNS、本地域、来源、实际 WAN 出口、回程、防循环、IPv6 边界和未受管终端。对端离线仍可关闭；核心/DNS 故障、重复开关、损坏配置、应用中断、部分清理失败与重启分别验收。规则生成和模拟适配器测试不等于内核与终端验收。
