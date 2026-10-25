'use strict';
'require view';
'require poll';
'require alwayroute.api as api';

/* External v1 is a separate model. Never read or populate legacy node data. */
function clone(value) { return JSON.parse(JSON.stringify(value)); }
function errorText(error) { return (error && error.message || '操作失败') + (error && error.code ? ' [' + error.code + ']' : ''); }
function show(value) { return value == null ? '未知' : typeof value === 'object' ? JSON.stringify(value) : String(value); }
function flag(value, yes, no) { return value === true ? yes : value === false ? no : '未知'; }
function replace(node, children) { while (node.firstChild) node.removeChild(node.firstChild); children.forEach(function(child) { node.appendChild(child); }); }

return view.extend({
	handleSave: null, handleSaveApply: null, handleReset: null,
	request: function(method, args) {
		var timer;
		return Promise.race([api.call(method, args), new Promise(function(_resolve, reject) {
			timer = window.setTimeout(function() { reject(new Error('请求超时，结果尚未确认；请重新读取状态')); }, 15000);
		})]).finally(function() { window.clearTimeout(timer); });
	},
	load: function() {
		var writable = L.hasViewPermission();
		return Promise.all([
			writable ? this.request('external_get').catch(function(error) { return { readError: errorText(error) }; }) : Promise.resolve({}),
			this.request('external_status').catch(function(error) { return { statusError: errorText(error) }; }),
			this.request('job_status').catch(function(error) { return { jobError: errorText(error) }; }),
			this.request('capabilities').catch(function() { return {}; })
		]).then(function(data) {
			return { config: data[0].config, readError: data[0].readError, state: data[1].state,
				statusError: data[1].statusError, jobError: data[2].jobError, job: data[2].busy ? data[2].job : null, externalOnly: data[3].externalOnly === true };
		});
	},
	render: function(data) {
		this.readonly = !L.hasViewPermission(); this.busy = false; this.dirty = false;
		this.externalOnly = data.externalOnly === true;
		this.config = data.config ? clone(data.config) : null;
		this.state = data.state || {}; this.statusError = data.statusError;
		this.readError = data.readError; this.jobError = data.jobError; this.job = data.job;
		this.uncertain = !!data.jobError || !!data.job;
		this.root = E('div', { 'class': 'cbi-map ar-app' });
		this.paint();
		var self = this;
		this.beforeUnload = function(event) { if (self.dirty) { event.preventDefault(); event.returnValue = ''; } };
		window.addEventListener('beforeunload', this.beforeUnload);
		this.pollFn = function() {
			if (self.root.isConnected) self.wasConnected = true;
			else if (self.wasConnected) { poll.remove(self.pollFn); window.removeEventListener('beforeunload', self.beforeUnload); return Promise.resolve(); }
			if (document.hidden || self.busy) return Promise.resolve();
			return self.refreshStatus();
		};
		poll.add(this.pollFn, 5);
		return E('div', {}, [E('link', { rel: 'stylesheet', href: L.resource('alwayroute/style.css') + '?v=' + encodeURIComponent(L.env.resource_version) }), this.root]);
	},
	button: function(label, action, options) {
		options = options || {}; var self = this;
		return E('button', { type: 'button', title: label, 'aria-label': label,
			'class': 'btn cbi-button ar-button' + (options.icon ? ' ar-icon' : '') + (options.primary ? ' cbi-button-action' : ''),
			disabled: this.busy || (this.readonly && !options.readonly) || (this.uncertain && !options.recovery) || options.disabled || undefined,
			click: function(event) { event.preventDefault(); try { Promise.resolve(action()).catch(function(error) { self.notify(errorText(error)); }); } catch (error) { self.notify(errorText(error)); } }
		}, options.icon ? [E('span', { 'aria-hidden': 'true', 'class': 'ar-glyph' }, [options.icon])] : [label]);
	},
	notify: function(message) { this.message = message; this.paintStatus(); },
	field: function(label, input, hint) {
		var id = 'ar-external-' + (++this.fieldId);
		input.setAttribute('id', id);
		return E('div', { 'class': 'cbi-value ar-field' }, [E('label', { 'class': 'cbi-value-title', 'for': id }, [label]),
			E('div', { 'class': 'cbi-value-field' }, [input].concat(hint ? [E('small', { 'class': 'ar-block ar-muted' }, [hint])] : []))]);
	},
	paintStatus: function() {
		if (!this.statusNode) return;
		var s = this.state || {}, phase = { active: '本地已应用', disabled: '自有资源已关闭', guarded: '来源阻断，等待重新核验', degraded: '异常或观察不可用', recovering: '事务待恢复', fault: '故障', unknown: '未知' };
		var forwarding = s.localForwarding || {}, dns = s.dns || {}, peer = s.peer || {}, gateway = s.gatewayDns || {};
		var fields = [
			['已保存版本', s.savedRevision], ['已保存开关', this.config ? (this.config.enabled ? '开启草稿' : '关闭草稿') : '无法读取 / 只读'],
			['持久期望', s.desiredEnabled === true ? '开启' : s.desiredEnabled === false ? '关闭' : '未知'], ['期望版本', s.desiredRevision],
			['实际来源范围', s.clientScope ? (s.clientScope.mode === 'lan' ? '整个 LAN：' : '指定终端：') + s.clientScope.ipv4 : '未确认'],
			['实际应用版本', s.appliedRevision], ['实际阶段', (phase[s.phase] || '未知') + ' (' + (s.phase || 'unknown') + ')'],
			['本地转发检查', '转发：' + flag(forwarding.running, '运行', '未运行') + '；来源防护：' + flag(forwarding.guarded, '阻断', '未阻断') + '；残留：' + flag(forwarding.residual, '存在', '未发现')],
			['专用 DNS 检查', flag(dns.running, '本地进程及 UDP/TCP 监听已确认', '未运行')],
			['网关 UDP DNS 可达性', (this.statusError ? '未知' : { reachable: '可达', unreachable: '查询失败', unknown: '未知' }[gateway.status] || '未知') + '；观察时间：' + show(gateway.observedAt) + '；观察年龄：' + show(gateway.ageSeconds) + ' 秒；最多缓存 ' + show(gateway.cacheSeconds) + ' 秒；仅证明 UDP 查询'],
			['应用依据', { 'gateway-dns': '网关 UDP DNS 预检', operator: '人工观察（兼容接口）', unknown: '未知' }[s.applicationMethod] || '未知'],
			['对端人工观察', (peer.status === 'reported' && !this.statusError ? '短期人工报告（operator），尚非独立探测' : '未知或观察已过期') + '；代次：' + show(peer.generation) + '；观察时间：' + show(peer.observedAt)],
			['最近故障', s.lastError || '无已报告故障'], ['路由器检查时间（Unix 秒）', s.observedAt]
		];
		var content = [E('h3', {}, ['外部代理状态']), E('dl', {}, fields.reduce(function(nodes, row) {
			return nodes.concat([E('dt', {}, [row[0]]), E('dd', { 'class': 'ar-block' }, [show(row[1])])]);
		}, [])), E('p', { 'class': 'ar-alert ar-warning' }, ['端到端出口：未验证。基础直连：未验证。本地就绪、DNS 可达与人工观察不能证明网关核心、流量接管、来源及回程；请进行真实终端验收。关闭成功后仍需检查普通直连。'])];
		if (this.busy || this.job) content.push(E('p', { role: 'status' }, ['后台操作处理中：' + (this.job ? show(this.job.method) + ' / ' + show(this.job.status) : '等待 RPC') + '。排队不表示完成；可重新读取接回等待。']));
		if (this.statusError) content.push(E('p', { 'class': 'ar-alert ar-error', role: 'alert' }, ['实际状态读取失败，旧快照不可视为当前结果：' + this.statusError]));
		if (this.jobError) content.push(E('p', { 'class': 'ar-alert ar-error', role: 'alert' }, ['后台任务未确认：' + this.jobError]));
		if (this.readError) content.push(E('p', { 'class': 'ar-alert ar-error', role: 'alert' }, ['配置不可读：' + this.readError + '。独立关闭仍可使用。']));
		if (this.message) content.push(E('p', { 'class': 'ar-alert ar-warning', role: 'status' }, [this.message]));
		if (this.dirty) content.push(E('p', {}, ['有未保存修改；先保存再应用已保存版本。']));
		replace(this.statusNode, content);
	},
	paint: function() {
		var self = this; this.fieldId = 0;
		this.statusNode = E('section', { 'class': 'ar-section', 'aria-live': 'polite' });
		var content = [E('div', { 'class': 'ar-heading' }, [E('h2', {}, ['AlwayRoute · 外部代理']),
			this.button('重新读取配置与状态', function() { return self.reload(); }, { icon: '↻', readonly: true, recovery: true })]),
			E('p', {}, ['可接管整个接入 LAN 的 IPv4 终端，新设备无需逐台登记。故障保留开启意图并阻断，不自动直连；手动关闭后撤销自有接管与防护。']),
			E('div', { 'class': 'ar-actions' }, [this.button('关闭外部代理，恢复普通直连', function() { return self.disable(); }, { recovery: true })]), this.statusNode];
		if (this.config && !this.readonly) content.push(this.configForm());
		else if (this.readonly) content.push(E('p', {}, ['当前账户仅可查看状态，未读取管理配置。']));
		if (!this.readonly && !this.externalOnly) content.push(E('details', { 'class': 'ar-details' }, [E('summary', {}, ['首次从本机代理切换']),
			E('p', {}, ['外部开启要求本机核心已停止。此操作只显式停止当前服务，不会启动外部代理；若当前已处于外部模式，也会关闭外部接管。']),
			this.button('停止当前代理服务', function() { return self.operate('service', ['stop']); }, { recovery: true })]));
		replace(this.root, content); this.paintStatus();
	},
	configForm: function() {
		var self = this, c = this.config, l = c.link || {}, client = c.clients[0] || {}, inputs = {};
		var mode = c.clientMode || (!c.link && !c.clients.length ? 'lan' : 'selected'), scopeRows = { lan: [], selected: [] };
		function scopeField(kind, label, node, hint) { var row = self.field(label, node, hint); scopeRows[kind].push(row); row.hidden = kind !== mode; return row; }
		function input(name, value, type) {
			var node = E('input', { type: type || 'text', value: value == null ? '' : value, checked: type === 'checkbox' && value || undefined,
				disabled: self.busy || self.uncertain || undefined, input: function() { self.dirty = true; self.paintStatus(); } });
			inputs[name] = node; return node;
		}
		function list(name, values) {
			var node = E('textarea', { rows: 3, disabled: self.busy || self.uncertain || undefined, input: function() { self.dirty = true; self.paintStatus(); } }, [(values || []).join('\n')]);
			inputs[name] = node; return node;
		}
		this.inputs = inputs;
		return E('section', { 'class': 'ar-section' }, [E('h3', {}, ['链路、来源与 DNS 草稿']),
			E('p', {}, ['保存只更新版本，不改变网络。链路、来源或监听端口变化时须先关闭旧范围。网关地址与 MAC 必须现场核验。']),
			mode === 'selected' && c.clients.length ? E('p', { 'class': 'ar-alert ar-warning' }, ['当前配置只接管一台指定终端。要让所有新接入设备自动代理，请先关闭外部代理，再切换为全部接入设备，填写并核验 LAN 网络范围后保存、应用。']) : E('p', {}, ['全部接入设备模式按 LAN 网络范围接管，普通设备接入该 LAN / Wi-Fi 即可，无需逐台登记 IP 或 MAC。']),
			this.field('保存为开启', input('enabled', c.enabled, 'checkbox'), '勾选并保存后，还须应用已保存版本；取消勾选并保存不等于已经关闭。'),
			this.field('来源范围', inputs.clientMode = E('select', { disabled: self.busy || self.uncertain || undefined, change: function() { var selectedMode = inputs.clientMode.value; Object.keys(scopeRows).forEach(function(kind) { scopeRows[kind].forEach(function(row) { row.hidden = kind !== selectedMode; }); }); self.dirty = true; self.paintStatus(); } }, [
				E('option', { value: 'lan', selected: mode === 'lan' || undefined }, ['全部接入设备（整个 LAN）']),
				E('option', { value: 'selected', selected: mode !== 'lan' || undefined }, ['指定终端（兼容）'])]), '整个 LAN 自动涵盖该接口内新增或变更 DHCP 地址的设备；不包含外部网关和路由器。'),
			scopeField('lan', 'LAN IPv4 网络 CIDR', input('clientCIDR', c.clientCIDR), '整个 LAN 模式必填，如 192.0.2.0/24；须与接口实际前缀及网关来源范围一致。'),
			this.field('LAN L3 接口', input('interface', l.interface)),
			this.field('路由器 IPv4', input('routerAddress', l.routerAddress)), this.field('外部网关 IPv4', input('gatewayAddress', l.gatewayAddress)),
			this.field('外部网关 MAC', input('gatewayMac', l.gatewayMac)), scopeField('selected', '指定终端 IPv4', input('clientAddress', client.address)),
			scopeField('selected', '指定终端 MAC', input('clientMac', client.mac), '仅指定终端模式使用；整个 LAN 模式无需逐台填写。'),
			this.field('网关 DNS 端口', input('gatewayPort', c.dns.gatewayPort, 'number'), '网关受限 UDP/TCP DNS 入口。'),
			this.field('路由器专用 DNS 端口', input('listenPort', c.dns.listenPort, 'number'), '不能使用基础 DNS 的 53 端口。'),
			this.field('本地域后缀', list('localDomains', c.dns.localDomains), '每行一个后缀；本地域和无点名称交给基础 DNS。'),
			this.field('额外 IPv4 目的例外', list('bypass4', c.bypass4), '每行一个网络 CIDR，最多 32 条；例外不进入外部接管，请保持最小范围。'),
			E('p', { 'class': 'ar-muted' }, ['固定策略：IPv4 / 故障阻断。受管终端公网 IPv6 阻断，本地管理保留；受管来源的 UDP/TCP 53 统一转交，不宣称控制 DoH/DoT。']),
			E('div', { 'class': 'ar-actions' }, [this.button('保存草稿', function() { return self.save(); }, { primary: true }),
				this.button('应用已保存版本', function() { return self.apply(); })])]);
	},
	readDraft: function() {
		var c = clone(this.config), i = this.inputs;
		function value(key) { return i[key].value.trim(); }
		function lines(key) { return value(key).split(/\s+/).filter(Boolean); }
		function port(key) { var v = value(key); if (!/^[0-9]+$/.test(v) || +v < 1 || +v > 65535) throw new Error('DNS 端口须为 1–65535 的整数'); return +v; }
		c.enabled = i.enabled.checked;
		var linkFields = ['interface', 'routerAddress', 'gatewayAddress', 'gatewayMac'];
		c.link = linkFields.some(function(k) { return value(k); }) ? Object.fromEntries(linkFields.map(function(k) { return [k, value(k)]; })) : null;
		c.clientMode = value('clientMode');
		if (c.clientMode === 'lan') { c.clientCIDR = value('clientCIDR'); c.clients = []; }
		else { delete c.clientCIDR; c.clients = value('clientAddress') || value('clientMac') ? [{ address: value('clientAddress'), mac: value('clientMac') }] : []; }
		c.dns = { gatewayPort: port('gatewayPort'), listenPort: port('listenPort'), localDomains: lines('localDomains') }; c.bypass4 = lines('bypass4');
		return c;
	},
	save: function() { return this.operate('external_save', [this.config.revision, this.readDraft()]); },
	disable: function() { return this.operate('external_disable', []); },
	apply: function() {
		if (this.dirty) throw new Error('请先保存草稿；应用只对应已保存版本');
		if (!this.config) throw new Error('请先读取已保存配置');
		return this.operate('external_apply', [this.config.revision]);
	},
	waitJob: async function(job) {
		var started = Date.now(); this.job = job; this.paintStatus();
		for (;;) {
			if (Date.now() - started >= 120000) throw new Error('等待后台任务超时，结果尚未确认；请重新读取');
			await new Promise(function(resolve) { window.setTimeout(resolve, 1000); });
			var result = await this.request('job_status'), current = result.job;
			if (!current || current.id !== job.id) throw new Error('后台任务记录已变化，结果尚未确认；请重新读取');
			this.job = current; this.paintStatus();
			if (current.status === 'running') continue;
			if (current.status !== 'succeeded') throw new Error(errorText(current.error || { message: '后台任务失败' }));
			this.job = null; return current.result || { state: current.state };
		}
	},
	operate: async function(method, args) {
		if (this.readonly || this.busy || this.uncertain && !['external_disable', 'service'].includes(method)) return;
		this.busy = true; this.message = null; this.paintStatus(); this.setDisabled(true); var saved = false;
		try {
			var result = await this.request(method, args);
			if (result.job && result.job.status === 'running') result = await this.waitJob(result.job);
			if (result.state) this.state = result.state;
			if (method === 'external_save') {
				this.config = result.config; this.dirty = false;
				saved = true;
				this.message = '草稿已保存，网络未改变。';
			} else this.message = '后台操作已完成；请核对实际状态并进行终端验收。';
			this.job = null; this.jobError = null; this.uncertain = false;
			await this.refreshStatus(true);
		} catch (error) {
			this.message = errorText(error); this.uncertain = !(method === 'external_save' && error.code === 'INVALID_EXTERNAL');
			if (this.job) this.jobError = '操作结果未确认，请重新读取；独立关闭可重试';
		} finally {
			this.busy = false;
			// Preserve the user's form after any failed or non-save operation.
			if (saved) this.paint();
			else { this.setDisabled(false); this.paintStatus(); }
		}
	},
	setDisabled: function(disabled) {
		// Repaint only operation controls. Input values and focus survive status polling.
		var self = this;
		if (this.inputs) Object.keys(this.inputs).forEach(function(key) { self.inputs[key].disabled = disabled || self.uncertain; });
		if (this.root.querySelectorAll) this.root.querySelectorAll('button').forEach(function(button) {
			var name = button.getAttribute('aria-label'), recovery = ['重新读取配置与状态', '关闭外部代理，恢复普通直连', '停止当前代理服务'].includes(name);
			button.disabled = disabled || (self.readonly && name !== '重新读取配置与状态') || (self.uncertain && !recovery);
		});
	},
	refreshStatus: async function(force) {
		if (this.statusPending) { await this.statusPending; if (!force) return; }
		var self = this;
		this.statusPending = this.request('external_status').then(function(result) { self.state = result.state; self.statusError = null; })
			.catch(function(error) { self.statusError = errorText(error); }).finally(function() { self.statusPending = null; self.paintStatus(); });
		return this.statusPending;
	},
	reload: async function() {
		if (this.busy) return;
		if (this.dirty && !window.confirm('重新读取会丢弃未保存的表单修改，继续？')) return;
		this.busy = true; this.setDisabled(true);
		try {
			var progress = await this.request('job_status');
			if (progress.busy && progress.job) await this.waitJob(progress.job);
			if (!this.readonly) {
				try { var saved = await this.request('external_get'); this.config = saved.config; this.readError = null; this.dirty = false; }
				catch (error) { this.config = null; this.readError = errorText(error); }
			}
			this.uncertain = false; this.jobError = null; this.job = null;
			await this.refreshStatus(true);
		} catch (error) { this.jobError = errorText(error); this.uncertain = true; }
		finally { this.busy = false; this.paint(); }
	}
});
