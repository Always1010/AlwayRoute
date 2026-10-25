# 外部代理最小协作语义 v1

本契约描述 AlwayRoute 外接后端与外部网关的共同边界。Coproxy 的对应说明见其 `docs/router-cooperation.md`；双方独立发布，不要求共享源码或真实环境配置。本版只实现路由器后端，不代表对端接管、设备部署或联合验收已经通过。

## 范围与责任

- 支持显式整个接入 LAN 或兼容单台指定终端，覆盖 IPv4 TCP/UDP、真实地址 DNS。终端默认网关和 DNS 入口保持为路由器；公网 IPv6 对受管终端阻断，本地管理保留，范围外接口和终端不受影响。
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
  "clientMode": "lan",
  "clientCIDR": "192.0.2.0/24",
  "clients": [],
  "dns": {"gatewayPort": 1053, "listenPort": 1053, "localDomains": ["lan"]},
  "bypass4": []
}
```

示例为合成地址，不是部署参数。`link.interface` 是实际 L3 接口；路由器与网关须为不同的可用主机地址。网关稳定地址和 MAC 由管理员核验，不能从历史 DHCP 记录推断。`bypass4` 是明确的额外目的 CIDR 例外，标准私网、保留与广播/组播范围另由适配器保护。例外意味着不进入外部接管，应按最小范围设置。

`clientMode:lan` 必须显式提供 `clientCIDR`（规范网络 CIDR，前缀 1–30）和空 `clients`。路由器与网关都须位于该网络内且不能是网络地址或广播地址；应用时还须读取实际 `link.interface` 上路由器地址的掩码，要求 CIDR 完全相同。网关配置的来源范围也须与其相同。仅配置接口接收的该 IPv4 来源被接管，不接管 WAN 或其他 LAN/VLAN。DHCP 新设备或地址变化自动由该范围覆盖，无须逐一填地址、MAC、手动代理或终端证书。路由器本机与外部网关的地址/MAC 不参与接管；网关以其他 LAN 客户端源地址回送的包会被拒绝，公网源地址的正常回包可经路由器返回。

缺省 `clientMode` 或显式 `selected` 保留旧单终端语义：`clients` 必须恰有一个 `{address,mac}`，且不能带 `clientCIDR`。旧 `enabled:true, clients:[]` 始终无效，绝不被解释为整个 LAN。范围、模式或监听变化必须先独立关闭，再保存、应用；保存草稿不改变现有接管。

`dns.listenPort` 是路由器的独立监听，不能占用基础 DNS 53；`gatewayPort` 是网关受限 UDP/TCP DNS 入口。受管来源的 UDP/TCP 53 统一转到专用解析器；本地域后缀和无点名称交给路由器基础 DNS，公网查询交给网关。不改所有终端共用的 dnsmasq 上游。网关 bootstrap 使用独立基础解析，不能返回本条公网转发链。DoH/DoT 按业务流量处理，不由 53 重定向冒充控制。

## 管理与状态

新增认证 RPC：`external_get`、`external_status`、`external_save(expectedRevision, config)`、`external_apply(expectedRevision, peer?)`、`external_disable`。保存只递增 revision，不触网；应用以保存版本做 CAS。耗时应用/关闭沿用后台 job 和 manager 锁，外部操作不生成、不校验、不启动本机代理核心。

日常应用只提交 `expectedRevision`，缺省或空对象 `peer` 使用网关 UDP DNS 预检：从已校验配置读取 gateway IPv4 和 `dns.gatewayPort`，用现有 nslookup 向该入口查询固定的 `example.com`，由既有超时工具限制为 3 秒。每次应用强制新查询，不复用状态缓存；无新依赖、网关控制 API 或后台监控服务。查询失败发生在转发预备与网络修改之前，保留原状态；原已开启状态继续保留既有转发与故障阻断语义，绝不自动切直连。缺少兼容的 nslookup 或超时工具同样视为预检失败。

UDP 查询成功仅证明当时该入口能回答这次 UDP DNS 查询，不证明 TCP DNS、网关核心、流量接管、真实来源、出站或回程。不得据此填入人工观察六项 true、生成 generation 或宣称端到端通过。网关策略和路径仍需按联合验收门槛实测。

兼容保留非空 `peer` 的人工观察路径：必须匹配 gateway、所请求 revision 和对端 generation，携带 `observedAt`，应用前后最多 30 秒。`coreReady`、`captureReady`、`dnsReady`、`egressViaRouter`、`returnViaRouter`、`sourcePreserved` 均需基于实测为 true。此路径标记为 `operator`，不会描述为机器独立证实或终端已验收；网页的正常保存/应用流程不要求填写此表。

状态的 `clientScope` 标记实际已应用/阻断的模式与 IPv4 范围，不能用新保存的草稿冒充已应用。状态区分 `savedRevision`、`desiredEnabled`、`appliedRevision`、`phase`、`applicationMethod`、`localForwarding`、`dns`、`gatewayDns`、`peer` 和 `lastError`。`applicationMethod:gateway-dns` 与 `operator` 分别记录应用依据；本地应用、专用 DNS 进程/监听、网关 UDP DNS 观察和端到端出口分开报告。`gatewayDns` 带 `method:udp-query`、`status`（`reachable` / `unreachable` / `unknown`）、`observedAt`、`ageSeconds` 和 `cacheSeconds:60`。`external_status` 仅对正常活动的 DNS 应用模式观察已应用配置，独立 `/tmp` 私有缓存每 60 秒至多发起一次新观察并刷新缓存，轮询不改事务状态；缓存过期而锁忙或缓存不可用时报告 unknown，不能沿用旧值声称当前健康。缓存损坏或不安全不阻止显式应用/关闭，不修复未知权限或链接。`external_get` 只返回已有快照，不发出查询。

`phase:active` 只表示本地应用及该模式的有界观察符合条件，绝不代表完整路径通过。DNS 模式不受人工观察的 30 秒期限影响；DNS 失败/未知或本地检查失败报告 degraded，保留开启意图与转发。兼容人工观察过期仍报告 unknown/degraded。`endToEnd` 与 `baseConnectivity` 始终为 `unverified`，由实际终端验收证明，不能由 RPC 写成通过。纯外接包重启与事件恢复先阻断，再对持久 intent 与 journal/lastgood 重新预检并自动恢复；不读取草稿代替确认配置，不复用旧观察。单个 procd worker 与 RPC 共用 manager 锁，事件合并；BUSY 与依赖未就绪持续退避，间隔最多 30 秒。显式关闭的独立持久取消标记优先于在途恢复与后续事件。`recovery` 报告等待原因、次数、最近/下次尝试时间和间隔，`waiting` 表示等待自动恢复。

纯外接 init 的正常系统 `shutdown` 保留持久开启意图和 lastgood，先将确认范围切回阻断、停止专用 DNS，并保留阻断直到基础网络关闭。显式 `stop` / `external_disable` 仍先持久保存关闭意图，再独立清理自有资源；两者不能共用持久关闭语义。

## 事务、关闭与恢复

外部配置、应用记录与 journal 独立于本机节点文件。应用持同一 manager 锁：校验与预检 → 持久化恢复记录 → 建立来源范围防护 → 专用 DNS 与路由/nft 应用 → 本地确认 → 持久提交。发生错误恢复上一个确认状态；旧状态开启而恢复失败时保留阻断和 journal。存在未完成事务时禁止新的普通应用，先恢复或显式关闭。

独立关闭不读取旧节点模型、不依赖外部设备在线，不因配置损坏失去入口；先停止重建意图，再核对并撤销自有资源，失败保留残留并允许重试。仅清理与本地基础条件确认成功后报告 `disabled`；WAN、DNS 与真实终端直连仍需联合验收。不会清空全局防火墙、路由表或 conntrack。

启动、网络及 firewall 事件使用同一个锁和持久意图。开启意图下先建立阻断，重新预检后显式应用；关闭不复活代理。与本机核心共存或资源归属不明时拒绝开启，先使用已有本机停止入口退出本机模式，不隐式切换旧配置。

## 联合验收门槛

固定双方源码/安装版本、核心版本、来源范围、超时与观察方式；整个 LAN 验收至少两台普通终端同时使用，并覆盖后续 DHCP 新终端、租约变化、TCP/UDP、UDP/TCP DNS、本地域、管理连接、原始来源、实际 WAN 出口、经路由器回程、防循环、IPv6 边界和范围外接口；兼容单源另行回归。对端离线仍可关闭；核心/DNS 故障、重复开关、损坏配置、应用中断、部分清理失败与重启分别验收。规则生成和模拟适配器测试不等于内核与终端验收。

纯外接的 fw4 `ruleset-pre` include 引用 root 私有的持久 `external-boot/guard.nft`，在 fw4 首次规则事务与重载时重建 `inet alwayroute_external_boot`。生成与持久同步先于开启意图；恢复先确保早期 guard，再做地址、范围、邻居 MAC 与 DNS 检查，成功后只清空早期表规则。独立关闭先移除持久 guard，再按专有注释清表。该保障依赖 fw4 默认 `auto_includes=1` 和由 fw4 启用基础转发；不得将未经最终固件冷启动测量的顺序宣称为无直通窗口验收。

关闭标记每次含新的 nonce。应用在获取 manager 锁前捕获 marker token，后台任务保留同一 token；预检后仅确认该 token，不删除 marker。新的关闭请求无论在持锁期间还是确认写入期间到达，都因代次不同保持取消；无 `/tmp` 状态的冷启动也检查实际资源与持久 guard，完成未收尾的独立关闭。
