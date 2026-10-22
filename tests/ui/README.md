# UI 检查与离线浏览器预览

直接使用现有 Node，不安装依赖：

```powershell
node --test tests/ui/ui.test.cjs
node tests/ui/build-preview.cjs
```

第二条仅生成 `.local/ui-preview/alwayroute.html`，不启动服务器、浏览器或设备连接。也可传入输出文件绝对路径。文件包含当前生产 `app.js`、`api.js`、`model.js`、CSS，浏览器真实 DOM、明确标注的脱敏 RPC 模拟器及最小 LuCI 适配层。`.local` 已由仓库忽略；预览模拟器只位于 `tests/ui`，不会安装进固件。

由主 Agent 协调浏览器打开生成的 HTML。若浏览器工具禁止 `file:`，主 Agent 可使用已有本地静态服务器承载 `.local/ui-preview`。默认桌面自适应；点击“手机 · 390px”时内层 iframe 的真实布局视口变成 390px，生产 CSS 的媒体查询会真实触发。也可直接把浏览器视口设置为 390×844。外层只负责预览控制，内层显示生产页面。

浏览器检查建议：

1. 总览检查 saved/applied/healthy 各自独立，核心观测与保存选择分别显示；切换“核心/流量不可用”时数值应为不可用。
2. 节点页添加/编辑，打开实际 DOM 模态框并键盘导航；关闭后本地 dirty 可见，保存后才更新版本。
3. 订阅页编辑 URL/更新周期，节点页修改订阅节点名称后查看本地覆盖标识。
4. 策略页改变 Proxy/跟随设置，保存后总览“核心实际选择”应保持旧值，应用后台任务结束后才变化。
5. 规则页移动优先级、编辑类型/出口；手机宽度下页签和表格可水平滚动，不挤压控件。
6. 选择“写入时版本冲突”或“后台任务失败”，确认错误可见、编辑未被静默清空、排队未被显示为完成。

预览模拟器不验证真实订阅解析、核心运行、认证授权、透明转发和设备持久化，不可作为实机验收证据。最终仍须固定 LuCI 和真实 RPC 联调。

## 固定 LuCI 加载契约核对

核对版本：`75a306df84a020c57a631ef5b4c02ace56d93387`。

- [`luci.js`](https://github.com/openwrt/luci/blob/75a306df84a020c57a631ef5b4c02ace56d93387/modules/luci-base/htdocs/luci-static/resources/luci.js#L2394) 的模块编译器要求 factory 返回 Class 子类，然后实例化。生产两个公共模块已改用 `baseclass.extend()`；原先只验证普通对象的 Node 测试已改为强制此构造契约。
- [`luci.js` 中的 view](https://github.com/openwrt/luci/blob/75a306df84a020c57a631ef5b4c02ace56d93387/modules/luci-base/htdocs/luci-static/resources/luci.js#L1846) 先执行 load，再 render 并挂载 Node。view、dom、poll 都是内建模块；不存在独立 `view.js`/`dom.js` 源文件。页面的 Footer handlers 为 null，避免额外 LuCI 保存操作。
- [`dom.attr/create`](https://github.com/openwrt/luci/blob/75a306df84a020c57a631ef5b4c02ace56d93387/modules/luci-base/htdocs/luci-static/resources/luci.js#L1419) 将函数属性绑定为事件，并略过 null/undefined。生产动态文本均作为 children 数组内容，避免落入非数组 children 的 HTML 解析路径。
- [`rpc.declare`](https://github.com/openwrt/luci/blob/75a306df84a020c57a631ef5b4c02ace56d93387/modules/luci-base/htdocs/luci-static/resources/rpc.js#L282) 按 params 顺序生成命名参数。不提供 expect 时返回原始 ubus 数据；生产 api 层进一步强制检查 `ok === true`。

生产页面不使用 `String.format`、`L.view` 或 `L.dom` 等隐式旧接口。测试适配层覆盖这次实际使用的接口，不把最小 shim 等同完整 LuCI 运行时。
