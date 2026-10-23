# UI 检查与离线浏览器预览

直接使用现有 Node，不安装依赖：

```powershell
node --test tests/ui/ui.test.cjs
node tests/ui/build-preview.cjs
```

第二条仅生成 `.local/ui-preview/alwayroute.html`，不启动服务器、浏览器或设备连接。也可传入输出文件绝对路径。文件包含当前生产 `app.js`、`api.js`、`model.js`、CSS，浏览器真实 DOM、明确标注的脱敏 RPC 模拟器及最小 LuCI 适配层。主题样式直接读取 `.local/sources/luci/` 中的固定上游源码；缺失时先按项目源码流程准备，不自动安装依赖。第三个命令行参数可选 `bootstrap`（默认）、`material`、`openwrt-2020`。`.local` 已由仓库忽略；预览模拟器只位于 `tests/ui`，不会安装进固件。

由主 Agent 协调浏览器打开生成的 HTML。若浏览器工具禁止 `file:`，主 Agent 可使用已有本地静态服务器承载 `.local/ui-preview`。默认桌面自适应；点击“手机 · 390px”时内层 iframe 的真实布局视口变成 390px，生产 CSS 的媒体查询会真实触发。也可直接把浏览器视口设置为 390×844。外层只负责预览控制，内层显示生产页面。

浏览器检查建议：

1. 首页合并服务状态、流量与代理策略；不再有独立默认出口和保存按钮。Proxy置顶，Other固定最后；GitHub、Netflix、Disney+、Spotify合并进Proxy。预览服务目录直接来自生产管理模型，不维护另一份列表。
2. 运行模式和出口下拉框变更立即提交configure；候选等待时禁用重复操作，确认实际状态后才接受新模型。失败保留旧选择，超时或核心实际不一致时进入“重新检查”状态，禁止叠加写请求。
3. 非规则模式隐藏策略组、分流规则及添加策略入口；全局模式只保留一个代理节点选择，直连模式不显示节点选择。服务启停只有一个按钮，等待期间显示启动中/停止中，确认响应后才切换。
4. 停止服务后改变策略只更新下次启动配置，不启动服务；再次启动须使用最新配置。添加可选服务和自定义组都插入Other之前。
5. 节点、订阅、规则编辑在弹窗中点击一次确定即可提交，等待时禁用字段，失败保留输入；导入和订阅更新使用activate:true，在同一事务中确认并生效。
6. 首页轮询不替换已聚焦的下拉框；日志独立成页且不变时保留DOM，备份与恢复独立成页。390px下策略选择保持可用，其他宽表只在表格内部滚动。
7. 检查“核心/流量不可用”“写入时版本冲突”“后台任务失败”场景：排队不算完成，核心选择不代表流量连通；错误应可见且不能伪造候选已经生效。
8. Proxy仅提供已启用且未排除的节点，无节点时显示占位并禁用启动。从直连切到代理模式、但Proxy尚未选择节点时，先弹窗选择节点，与模式在一次事务中提交；没有可用节点时提示先添加。
9. 只读账户仅请求status、capabilities、traffic、logs，显示运行状态和日志，不读取包含凭据的get配置。普通请求15秒超时，检测任务最多等待600秒，其余后台任务120秒；超时仅表示结果未确认，须重新检查，不能当成取消或完成。
10. 单节点及整订阅检测显示串行进度；忙时仍可取消，取消后保留已完成结果。刷新页面可接回正在运行的检测，不自动切换出口。预览模拟器不替代实机检测验证。

预览模拟器不验证真实订阅解析、核心运行、认证授权、透明转发和设备持久化，不可作为实机验收证据。最终仍须固定 LuCI 和真实 RPC 联调。

## 固定 LuCI 加载契约核对

核对版本：`75a306df84a020c57a631ef5b4c02ace56d93387`。

- [`luci.js`](https://github.com/openwrt/luci/blob/75a306df84a020c57a631ef5b4c02ace56d93387/modules/luci-base/htdocs/luci-static/resources/luci.js#L2394) 的模块编译器要求 factory 返回 Class 子类，然后实例化。生产两个公共模块已改用 `baseclass.extend()`；原先只验证普通对象的 Node 测试已改为强制此构造契约。
- [`luci.js` 中的 view](https://github.com/openwrt/luci/blob/75a306df84a020c57a631ef5b4c02ace56d93387/modules/luci-base/htdocs/luci-static/resources/luci.js#L1846) 先执行 load，再 render 并挂载 Node。view、dom、poll 都是内建模块；不存在独立 `view.js`/`dom.js` 源文件。页面的 Footer handlers 为 null，避免额外 LuCI 保存操作。
- [`dom.attr/create`](https://github.com/openwrt/luci/blob/75a306df84a020c57a631ef5b4c02ace56d93387/modules/luci-base/htdocs/luci-static/resources/luci.js#L1419) 将函数属性绑定为事件，并略过 null/undefined。生产动态文本均作为 children 数组内容，避免落入非数组 children 的 HTML 解析路径。
- [`rpc.declare`](https://github.com/openwrt/luci/blob/75a306df84a020c57a631ef5b4c02ace56d93387/modules/luci-base/htdocs/luci-static/resources/rpc.js#L282) 按 params 顺序生成命名参数。不提供 expect 时返回原始 ubus 数据；生产 api 层进一步强制检查 `ok === true`。

生产页面不使用 `String.format`、`L.view` 或 `L.dom` 等隐式旧接口。测试适配层覆盖这次实际使用的接口，不把最小 shim 等同完整 LuCI 运行时。
