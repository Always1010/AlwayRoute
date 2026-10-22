'use strict';
'require view';
'require ui';
'require poll';
'require alwayroute.api as api';
'require alwayroute.model as model';

/* All displayed runtime data comes from authenticated rpcd. No sample fallback. */
return view.extend({
	handleSave: null,
	handleSaveApply: null,
	handleReset: null,

	load: function() {
		var self = this;
		return api.call('job_status').then(function(progress) {
			var saved = progress.busy && progress.job && progress.job.status === 'running' ? self.waitJob(progress.job) : api.call('get');
			return Promise.all([saved, api.call('capabilities')]);
		});
	},

	render: function(data) {
		this.draft = model.clone(data[0].model);
		this.state = data[0].state || {};
		this.capabilities = data[1];
		this.revision = this.state.savedRevision;
		this.dirty = false;
		this.readonly = !L.hasViewPermission();
		this.busy = false;
		this.tab = 'overview';
		this.runtime = null;
		this.traffic = null;
		this.logs = [];
		this.checks = {};
		this.root = E('div', { 'class': 'ar-app' });
		this.paint();
		var self = this;
		this.beforeUnload = function(event) {
			if (self.dirty) { event.preventDefault(); event.returnValue = ''; }
		};
		window.addEventListener('beforeunload', this.beforeUnload);
		this.pollFn = function() {
			if (self.root.isConnected) self.wasConnected = true;
			else if (self.wasConnected) {
				poll.remove(self.pollFn);
				window.removeEventListener('beforeunload', self.beforeUnload);
				return Promise.resolve();
			}
			return self.refreshRuntime();
		};
		poll.add(this.pollFn, 5);
		this.root.addEventListener('DOMNodeRemoved', function(event) {
			if (event.target === self.root) {
				poll.remove(self.pollFn);
				window.removeEventListener('beforeunload', self.beforeUnload);
			}
		});
		// LuCI mounts the returned Node after render resolves. Start after mounting,
		// so the first visit has data immediately and detach cleanup can observe it.
		window.setTimeout(function() {
			if (self.root.isConnected) { self.wasConnected = true; self.refreshRuntime(); }
		}, 0);
		return E('div', {}, [E('link', { rel: 'stylesheet', href: L.resource('alwayroute/style.css') }), this.root]);
	},

	button: function(label, icon, action, options) {
		options = options || {};
		var self = this;
		return E('button', {
			type: 'button', title: label, 'aria-label': label,
			'class': 'cbi-button ar-button ' + (options.primary ? 'cbi-button-action ' : '') + (options.text ? '' : 'ar-icon'),
			disabled: options.disabled || this.busy || (this.readonly && !options.readonly) || undefined,
			click: function(event) {
				event.preventDefault();
				try { Promise.resolve(action()).catch(function(error) { self.error(error); }); }
				catch (error) { self.error(error); }
			}
		}, [E('span', { 'aria-hidden': 'true', 'class': 'ar-glyph' }, [icon]), options.text ? ' ' + label : '']);
	},

	error: function(error) {
		if (error && error.code === 'REVISION_CONFLICT') this.conflict = true;
		this.message = { type: 'error', text: (error && error.message || '操作失败') +
			(error && error.code ? ' [' + error.code + ']' : '') };
		this.paint();
	},

	accept: function(result) {
		if (result.model) { this.draft = model.clone(result.model); this.dirty = false; }
		if (result.state) this.updateState(result.state);
		this.revision = this.state.savedRevision;
		this.conflict = false;
	},
	updateState: function(state) {
		this.state = state;
		this.keepChecks(this.checks);
	},
	keepChecks: function(checks) {
		var current = {}, revision = this.state.appliedRevision;
		if (revision != null) Object.keys(checks || {}).forEach(function(id) {
			var check = checks[id];
			if (check && check.checkedRevision === revision) current[id] = check;
		});
		this.checks = current;
	},
	checkLabel: function(check) {
		return check.available === false ? '不可用：' + (check.reason || model.stateLabel(check.healthy)) :
			check.delay != null ? check.delay + ' ms' : model.stateLabel(check.healthy);
	},

	mutate: function(method, args, success) {
		var self = this;
		if (this.busy) return Promise.reject(new Error('另一项操作正在执行'));
		this.busy = true;
		this.operationGeneration = (this.operationGeneration || 0) + 1;
		this.message = null;
		this.paint();
		return api.call(method, args).then(function(result) {
			if (result.job && result.job.status === 'running') return self.waitJob(result.job);
			return result;
		}).then(function(result) {
			self.accept(result);
			self.message = { type: 'success', text: success };
			return result;
		}).catch(function(error) {
			self.error(error);
			throw error;
		}).finally(function() { self.busy = false; self.paint(); });
	},

	waitJob: function(job) {
		var self = this, started = Date.now();
		this.activeJob = job;
		this.paint();
		async function next() {
			for (;;) {
				await new Promise(function(resolve) { window.setTimeout(resolve, 1000); });
				if (document.hidden) { started = Date.now(); continue; }
				var result = await api.call('job_status');
				var current = result.job;
				if (!current || current.id !== job.id) throw new Error('后台任务记录已变化，请重新读取配置和运行状态');
				self.activeJob = current;
				if (current.status === 'running') {
					if (Date.now() - started > 180000) throw new Error('后台任务仍在运行，界面等待已超时。请重新读取状态，勿重复提交');
					continue;
				}
				if (current.status !== 'succeeded') {
					var detail = current.error || {}, error = new Error(detail.message || '后台任务失败');
					error.code = detail.code || 'JOB_FAILED'; throw error;
				}
				return api.call('get').then(function(saved) { return Object.assign({}, current.result || {}, saved); });
			}
		}
		return next().finally(function() { self.activeJob = null; });
	},

	changed: function() { this.dirty = true; this.message = null; this.paint(); },

	refreshRuntime: function() {
		var self = this;
		if (this.busy || this.polling || document.hidden || this.tab !== 'overview' || !this.root.isConnected) return Promise.resolve();
		this.polling = true;
		var generation = this.operationGeneration || 0;
		return Promise.allSettled([api.call('status'), api.call('traffic'), api.call('logs', [20])]).then(function(results) {
			if (!self.root.isConnected || self.busy || generation !== (self.operationGeneration || 0)) return;
			if (results[0].status === 'fulfilled') {
				self.runtime = results[0].value;
				var remote = self.runtime.state || {};
				if (remote.savedRevision !== self.revision) self.conflict = true;
				self.updateState(remote);
				self.keepChecks(self.runtime.checks);
				self.runtimeError = null;
			}
			else { self.runtime = null; self.runtimeError = results[0].reason.message; }
			self.traffic = results[1].status === 'fulfilled' ? results[1].value : { available: false, reason: results[1].reason.message };
			if (results[2].status === 'fulfilled') {
				self.logs = (results[2].value.entries || []).slice(-20);
				self.logsError = null;
			}
			else { self.logs = []; self.logsError = results[2].reason.message; }
			self.paint();
		}).finally(function() { self.polling = false; });
	},

	paint: function() {
		if (!this.root) return;
		var self = this, s = this.state;
		var tabs = [['overview', '总览'], ['nodes', '节点'], ['subscriptions', '订阅'], ['groups', '策略组'], ['rules', '规则'], ['settings', '配置与恢复']];
		var content = [E('div', { 'class': 'ar-heading' }, [
			E('div', {}, [E('h2', {}, ['AlwayRoute']), E('p', { 'class': 'ar-muted' }, ['路由器代理 · 配置保存、应用与连通性独立验证'])]),
			E('div', { 'class': 'ar-actions' }, [
				this.button('重新读取', '↻', function() { return self.reload(); }, { readonly: true }),
				this.button('保存', '✓', function() { return self.save(); }, { text: true, primary: true, disabled: !this.dirty || this.conflict }),
				this.button('应用已保存配置', '▷', function() { return self.apply(); }, { text: true, disabled: this.dirty || this.conflict })
			])
		]), E('div', { 'class': 'ar-statebar', role: 'status', 'aria-live': 'polite' }, [
			E('span', { 'class': this.dirty ? 'ar-badge ar-warning' : 'ar-badge' }, [this.dirty ? '有未保存修改' : '编辑内容已保存']),
			E('span', { 'class': 'ar-badge' }, ['已保存版本 ' + (s.savedRevision == null ? '未知' : s.savedRevision)]),
			E('span', { 'class': 'ar-badge ' + (s.savedRevision !== s.appliedRevision ? 'ar-warning' : '') }, ['已应用版本 ' + (s.appliedRevision == null ? '无' : s.appliedRevision)]),
			E('span', { 'class': 'ar-badge' }, ['终端出口验证：' + model.stateLabel(s.healthy)]),
			this.busy ? E('span', { 'class': 'ar-badge' }, [this.activeJob ? '后台任务 ' + this.activeJob.method + ' 正在执行…' : '正在执行，请稍候…']) : ''
		])];
		if (this.conflict) content.push(E('div', { 'class': 'ar-alert ar-error', role: 'alert' }, ['配置已被其他会话修改。当前编辑内容保留；请复制需要保留的内容后重新读取，再编辑保存。']));
		if (this.readonly) content.push(E('p', { 'class': 'ar-alert ar-warning' }, ['当前 LuCI 账户仅有读取权限；修改操作已禁用。']));
		if (this.message) content.push(E('div', { 'class': 'ar-alert ar-' + this.message.type, role: 'status' }, [this.message.text]));
		if (s.lastError) content.push(E('div', { 'class': 'ar-alert ar-error' }, ['管理服务：' + (typeof s.lastError === 'string' ? s.lastError : s.lastError.message || '执行失败')]));
		content.push(E('nav', { 'class': 'ar-tabs', 'aria-label': 'AlwayRoute 页面' }, tabs.map(function(tab) {
			return E('button', { type: 'button', 'class': tab[0] === self.tab ? 'active' : '', 'aria-current': tab[0] === self.tab ? 'page' : undefined,
				click: function() { self.tab = tab[0]; self.paint(); self.refreshRuntime(); }
			}, [tab[1]]);
		})));
		content.push(this['render_' + this.tab]());
		domReplace(this.root, content);
	},

	reload: function() {
		var self = this;
		if (this.dirty && !window.confirm('重新读取将丢弃尚未保存的编辑。继续？')) return;
		this.checks = {};
		return this.mutate('get', [], '已重新读取持久配置。').then(function() { return self.refreshRuntime(); });
	},
	save: function() { return this.mutate('save', [this.revision, this.draft], '配置已保存。尚未应用；单节点检查也须单独执行。'); },
	apply: function() {
		if (this.dirty || this.conflict) throw new Error('请先保存当前编辑并处理版本冲突');
		return this.mutate('apply', [this.revision], '配置应用请求已完成。请查看实际运行状态；此结果不代表实际出口连通性通过。');
	},

	card: function(title, children) { return E('section', { 'class': 'ar-card' }, [E('h3', {}, [title])].concat(children)); },
	empty: function(text) { return E('p', { 'class': 'ar-empty' }, [text]); },
	table: function(headers, rows) {
		return E('div', { 'class': 'ar-table-scroll' }, [E('table', { 'class': 'table ar-table' }, [
			E('thead', {}, [E('tr', {}, headers.map(function(h) { return E('th', {}, [h]); }))]),
			E('tbody', {}, rows.map(function(row) { return E('tr', {}, row.map(function(cell) { return E('td', {}, [cell]); })); }))
		])]);
	},

	render_overview: function() {
		var self = this, runtime = this.runtime || {}, core = runtime.core || {}, service = runtime.service || {};
		var running = typeof service === 'boolean' ? service : service.running;
		var traffic = this.traffic || {};
		var observed = core.available === false ? null : core.groups;
		if (observed && observed.proxies) observed = observed.proxies;
		var groupRows = (this.draft.groups || []).map(function(group) {
			var actual = observed && observed[group.id];
			var selected = typeof actual === 'string' ? actual : actual && actual.now;
			return [group.name, model.label(self.draft, group.selected), selected ? model.label(self.draft, selected) : '未观测到'];
		});
		return E('div', {}, [
			E('div', { 'class': 'ar-grid' }, [
				this.card('代理服务', [E('strong', { 'class': 'ar-value' }, [running === true ? '运行中' : running === false ? '已停止' : '未知']),
					E('p', { 'class': 'ar-muted' }, [this.runtimeError || '进程运行与节点连通性分别检查。']),
					E('div', { 'class': 'ar-actions' }, [this.button('启动服务', '▷', function() { return self.mutate('service', ['start'], '启动请求已完成，请核对运行状态。'); }, { text: true, disabled: this.dirty }),
						this.button('停止服务', '■', function() { return self.mutate('service', ['stop'], '停止请求已完成，请核对运行状态。'); }, { text: true })])]),
				this.card('运行模式', [E('strong', { 'class': 'ar-value' }, [({ rule: '规则分流', global: '全局代理', direct: '直连' })[this.draft.mode] || '未知']),
					E('p', { 'class': 'ar-muted' }, ['此处为保存的模式；应用版本一致后再核对流量实际出口。'])]),
				this.card('实时流量', [E('div', { 'class': 'ar-rate' }, [E('div', {}, ['↑ 上行 ', E('strong', {}, [traffic.available ? model.formatRate(traffic.upload) : '不可用'])]),
					E('div', {}, ['↓ 下行 ', E('strong', {}, [traffic.available ? model.formatRate(traffic.download) : '不可用'])])]),
					E('p', { 'class': 'ar-muted' }, [traffic.reason || '核心观测值，每 5 秒更新；隐藏页面暂停。'])])
			]),
			this.card('策略选择与核心观测', [this.table(['策略组', '保存的选择', '核心实际选择'], groupRows),
				E('p', { 'class': 'ar-muted' }, ['切换默认影响后续新连接；已有连接可能继续使用原出口。核心观测不等同外网出口验证。'])]),
			this.card('支持范围', [E('p', {}, ['核心版本 1.13.21；目前仅 VMess 样本完成真实连接验证。其他协议或未知参数不会自动视为支持。']),
				E('p', {}, ['订阅格式：' + ((this.capabilities.subscriptionFormats || []).join('、') || '以管理服务校验结果为准')]),
				E('p', { 'class': 'ar-alert ar-warning' }, ['DNS、IPv6、UDP 与透明转发接管的实测范围：' + model.forwardingLabel(runtime.forwarding || this.capabilities.forwarding) + '。管理页面可用不代表终端流量已接管。'])]),
			this.card('最近事件（最多 20 条）', [this.logsError ? this.empty(this.logsError) : this.logs.length ? E('ol', { 'class': 'ar-logs' }, this.logs.map(function(entry) {
				return E('li', {}, [typeof entry === 'string' ? entry : [entry.time || '', entry.level || '', entry.message || ''].filter(Boolean).join(' ')]);
			})) : this.empty('暂无管理事件。日志不包含节点凭证和订阅地址。')])
		]);
	},

	render_nodes: function() {
		var self = this;
		var rows = this.draft.nodes.map(function(raw) {
			var n = model.effectiveNode(self.draft, raw), override = self.draft.overrides[raw.id];
			var source = raw.source && self.draft.subscriptions.filter(function(s) { return s.id === raw.source; })[0];
			var result = self.checks[n.id];
			var check = result && self.state.appliedRevision != null && result.checkedRevision === self.state.appliedRevision ? self.checkLabel(result) : null;
			return [E('div', {}, [E('strong', {}, [n.name]), E('small', { 'class': 'ar-muted ar-block' }, [n.id])]),
				n.type.toUpperCase(), source ? source.name + (override ? ' · 本地覆盖' : '') : '手动',
				n.excluded ? '已排除' : n.enabled ? '启用' : '停用',
				check ? check : '未检查',
				E('div', { 'class': 'ar-actions' }, [
					self.button('编辑节点', '✎', function() { self.editNode(raw); }),
					self.button('检查此节点', '◉', function() { return self.checkNode(n.id); }, { disabled: self.dirty || self.conflict || self.state.savedRevision !== self.state.appliedRevision || n.excluded || !n.enabled }),
					self.button('保存为 Proxy 选择', '▷', function() { return self.chooseNode('Proxy', n.id); }, { disabled: self.dirty || self.conflict || n.excluded || !n.enabled }),
					raw.source && override ? self.button('清除本地覆盖', '↶', function() {
						if (window.confirm('清除此节点的本地名称、参数和排除设置？保存后使用订阅原始值。')) { delete self.draft.overrides[n.id]; self.changed(); }
					}) : '',
					raw.source ? self.button(n.excluded ? '取消本地排除' : '本地排除此节点', n.excluded ? '+' : '−', function() {
						if (!n.excluded && model.references(self.draft, n.id).length) throw new Error('请先移除该节点的策略组、规则和默认出口引用');
						self.draft.overrides[n.id] = Object.assign({}, override || {}, { excluded: !n.excluded }); self.changed();
					}) : self.button('删除节点', '×', function() {
						if (window.confirm('删除节点“' + n.name + '”？保存后持久生效。')) { model.removeNode(self.draft, n.id); self.changed(); }
					})
				])];
		});
		return this.card('节点', [E('div', { 'class': 'ar-toolbar' }, [E('p', { 'class': 'ar-muted' }, ['稳定 ID 用于规则引用；订阅节点的编辑与排除保存为独立覆盖。']),
			E('div', { 'class': 'ar-actions' }, [this.button('导入节点链接 / 配置', '⇧', function() {
				self.showImport('导入为手动节点', function(content) { return self.mutate('import', [self.revision, content], '节点已导入并保存。请选择策略组出口，再应用配置。'); });
			}, { text: true, disabled: this.dirty || this.conflict }), this.button('添加节点', '+', function() { self.editNode(); }, { text: true, primary: true })])]),
			rows.length ? this.table(['名称', '协议', '来源', '状态', '单节点检查', '操作'], rows) : this.empty('还没有节点。添加 VMess 节点，或在订阅页导入受支持的订阅内容。'),
			E('p', { 'class': 'ar-muted' }, ['选择节点仅保存选择，随后须应用；实际选择请到总览查看。请先应用已保存版本，再执行单节点检查。检查结果仅对应当前已应用版本，且不代表终端出口验证。'])]);
	},

	input: function(value, type, attrs) { return E('input', Object.assign({ type: type || 'text', value: value == null ? '' : String(value), 'class': 'cbi-input-text' }, attrs || {})); },
	select: function(value, choices) {
		return E('select', { 'class': 'cbi-input-select' }, choices.map(function(choice) {
			return E('option', { value: choice[0], selected: choice[0] === value ? '' : undefined }, [choice[1]]);
		}));
	},
	field: function(label, control, help) {
		return E('label', { 'class': 'ar-field' }, [E('span', {}, [label]), control, help ? E('small', { 'class': 'ar-muted' }, [help]) : '']);
	},
	modal: function(title, fields, commit) {
		var self = this, errorBox = E('p', { 'class': 'ar-alert ar-error', hidden: '' });
		ui.showModal(title, [E('div', { 'class': 'ar-form' }, fields), errorBox, E('div', { 'class': 'right ar-actions' }, [
			this.button('取消', '×', function() { ui.hideModal(); }, { text: true }),
			this.button('保留编辑', '✓', function() {
				try { commit(); ui.hideModal(); self.changed(); }
				catch (error) { errorBox.hidden = false; errorBox.textContent = error.message; }
			}, { text: true, primary: true })
		])]);
	},

	editNode: function(raw) {
		var self = this;
		var n = raw ? model.effectiveNode(this.draft, raw) : { name: '', type: 'vmess', enabled: true, server: '', port: 443, uuid: '', security: 'auto', alterId: 0 };
		var name = this.input(n.name), server = this.input(n.server), port = this.input(n.port, 'number', { min: 1, max: 65535 });
		var uuid = this.input(n.uuid, 'password', { autocomplete: 'new-password' });
		var security = this.select(n.security, ['auto', 'aes-128-gcm', 'chacha20-poly1305', 'none', 'zero'].map(function(v) { return [v, v]; }));
		var alterId = this.input(n.alterId || 0, 'number', { min: 0, max: 65535 });
		var enabled = this.input('', 'checkbox', { checked: n.enabled || undefined, disabled: raw && raw.source || undefined });
		var tls = this.input('', 'checkbox', { checked: n.tls && n.tls.enabled || undefined }), sni = this.input(n.tls && n.tls.serverName);
		var transport = this.select(n.transport && n.transport.type || '', [['', 'TCP'], ['ws', 'WebSocket']]);
		var path = this.input(n.transport && n.transport.path), host = this.input(n.transport && n.transport.host);
		var fields = [this.field('名称', name), this.field('服务器', server), this.field('端口', port), this.field('UUID（敏感）', uuid), this.field('VMess 加密', security), this.field('VMess alterId', alterId),
			this.field('启用节点', enabled), this.field('启用 TLS', tls), this.field('TLS Server Name', sni), this.field('传输', transport), this.field('WebSocket Path', path), this.field('WebSocket Host', host),
			E('p', { 'class': 'ar-muted' }, ['仅支持管理服务明确校验的 VMess 参数；未知参数不自动忽略。' + (raw && raw.source ? '订阅节点的名称和参数改动保存在本地覆盖中。' : '')])];
		this.modal(raw ? '编辑节点' : '添加 VMess 节点', fields, function() {
			if (!name.value.trim() || !server.value.trim() || !uuid.value.trim()) throw new Error('名称、服务器和 UUID 必填');
			if (!model.validPort(port.value)) throw new Error('端口须为 1–65535 的整数');
			if (!/^\d+$/.test(alterId.value) || Number(alterId.value) > 65535) throw new Error('alterId 须为 0–65535 的整数');
			var tlsConfig = { enabled: tls.checked }, wsConfig = { type: 'ws', path: path.value || '/' };
			if (sni.value.trim()) tlsConfig.serverName = sni.value.trim();
			if (host.value.trim()) wsConfig.host = host.value.trim();
			var values = { server: server.value.trim(), port: Number(port.value), uuid: uuid.value.trim(), security: security.value, alterId: Number(alterId.value),
				tls: tlsConfig, transport: transport.value ? wsConfig : null };
			if (raw && raw.source) {
				var previous = self.draft.overrides[raw.id] || {};
				if (enabled.checked !== raw.enabled) throw new Error('订阅节点请通过“本地排除”控制是否可用；启停订阅可在订阅页设置');
				self.draft.overrides[raw.id] = Object.assign({}, previous, { name: name.value.trim(), patch: values });
			}
			else {
				var next = Object.assign({}, raw || { id: model.id('n'), type: 'vmess', source: null }, values, { name: name.value.trim(), enabled: enabled.checked });
				if (!next.transport) delete next.transport;
				if (raw) self.draft.nodes[self.draft.nodes.indexOf(raw)] = next;
				else self.draft.nodes.push(next);
			}
		});
	},

	checkNode: function(id) {
		var self = this;
		if (this.dirty || this.conflict || this.state.savedRevision !== this.state.appliedRevision || this.state.appliedRevision == null) throw new Error('请先保存并应用当前版本，再执行单节点检查');
		return this.mutate('check', [id], '单节点检查已返回；检查结果仅对应此次请求。').then(function(result) {
			var checks = Object.assign({}, self.checks); checks[id] = result;
			self.keepChecks(checks);
			self.paint();
		});
	},
	chooseNode: function(group, id) {
		if (this.dirty || this.conflict) throw new Error('请先保存编辑并处理版本冲突');
		return this.mutate('select', [this.revision, group, id], '选择已持久保存。请应用，然后在总览核对核心实际选择。');
	},

	render_subscriptions: function() {
		var self = this;
		var rows = this.draft.subscriptions.map(function(s) {
			return [s.name, s.enabled ? '启用' : '停用', s.intervalHours ? '每 ' + s.intervalHours + ' 小时' : '手动更新',
				E('div', {}, [E('span', {}, [typeof s.lastUpdate === 'number' ? new Date(s.lastUpdate * 1000).toLocaleString() : s.lastUpdate || '从未更新']), s.lastError ? E('small', { 'class': 'ar-error ar-block' }, [s.lastError]) : '']),
				E('div', { 'class': 'ar-actions' }, [self.button('编辑订阅', '✎', function() { self.editSubscription(s); }),
					self.button('手动更新订阅', '↻', function() { return self.updateSubscription(s); }, { disabled: self.dirty || self.conflict || !s.enabled }),
					self.button('从本地内容更新', '⇧', function() { self.importSubscription(s); }, { disabled: self.dirty || self.conflict || !s.enabled }),
					self.button('删除订阅及所属节点', '×', function() {
						if (window.confirm('删除订阅“' + s.name + '”及所属节点和本地覆盖？引用须先移除。')) { model.removeSubscription(self.draft, s.id); self.changed(); }
					})])];
		});
		return this.card('订阅来源', [E('div', { 'class': 'ar-toolbar' }, [E('p', { 'class': 'ar-muted' }, ['订阅地址仅用于本机管理服务抓取，不发送公共转换服务。失败时保留旧节点。']),
			this.button('添加订阅', '+', function() { self.editSubscription(); }, { text: true, primary: true })]),
			rows.length ? this.table(['名称', '状态', '更新计划', '最近结果', '操作'], rows) : this.empty('暂无订阅。添加后先保存，再手动更新或粘贴受支持的订阅内容。'),
			E('p', { 'class': 'ar-muted' }, ['更新可能增加或移除节点。若所选节点或规则引用消失，服务端拒绝更新并保留旧数据；请先调整引用。定时更新由路由器管理服务执行。'])]);
	},
	editSubscription: function(original) {
		var self = this, s = original || { name: '', url: '', enabled: true, intervalHours: 0, allowHttp: false };
		var name = this.input(s.name), url = this.input(s.url, 'password', { autocomplete: 'new-password' });
		var enabled = this.input('', 'checkbox', { checked: s.enabled || undefined }), interval = this.input(s.intervalHours, 'number', { min: 0, max: 168 });
		var allowHttp = this.input('', 'checkbox', { checked: s.allowHttp === true || undefined });
		this.modal(original ? '编辑订阅' : '添加订阅', [this.field('名称', name), this.field('订阅地址（敏感）', url), this.field('启用订阅', enabled),
			this.field('允许此订阅使用未加密HTTP', allowHttp, '仅用于现有 HTTP 来源。凭证和节点配置不受传输加密保护；此开关仅对此订阅生效。'),
			this.field('更新间隔（小时）', interval, '0 表示仅手动更新；定时范围为 1–168 小时。')], function() {
			var address = url.value.trim(), https = /^https:\/\/[^\s]+$/i.test(address), http = /^http:\/\/[^\s]+$/i.test(address);
			if (!name.value.trim() || !(https || (http && allowHttp.checked))) throw new Error('名称必填；默认要求 HTTPS，现有 HTTP 来源须显式勾选此订阅的未加密 HTTP 许可');
			if (!/^\d+$/.test(interval.value) || Number(interval.value) > 168) throw new Error('更新间隔须为 0–168 的整数');
			var next = Object.assign({}, s, { id: s.id || model.id('s'), name: name.value.trim(), url: address, enabled: enabled.checked, intervalHours: Number(interval.value), allowHttp: allowHttp.checked });
			if (original) self.draft.subscriptions[self.draft.subscriptions.indexOf(original)] = next;
			else self.draft.subscriptions.push(next);
		});
	},
	updateSubscription: function(s, content) {
		return this.mutate('refresh', [this.revision, s.id, content || ''], '订阅更新已保存。本地覆盖保留；请应用后核对实际运行选择。');
	},
	importSubscription: function(s) {
		var self = this;
		this.showImport('从本地订阅内容更新', function(content) { return self.updateSubscription(s, content); });
	},
	showImport: function(title, commit) {
		var area = E('textarea', { rows: 10, 'class': 'cbi-input-textarea', autocomplete: 'off', spellcheck: 'false', maxlength: 131072 });
		ui.showModal(title, [E('p', {}, ['仅提交到本机管理服务。支持格式由服务端校验，未知协议或字段会被拒绝；失败保留旧数据。']), this.field('VMess URI / Base64 / Clash JSON 或受限 YAML', area),
			E('div', { 'class': 'right ar-actions' }, [this.button('取消', '×', function() { ui.hideModal(); }, { text: true }),
				this.button('导入并保存', '⇧', function() { if (!area.value.trim()) throw new Error('请先粘贴导入内容'); ui.hideModal(); return commit(area.value); }, { text: true, primary: true })])]);
	},

	outbounds: function(options) {
		options = options || {};
		var list = [['direct', '直连']];
		if (options.block) list.push(['block', '阻断']);
		if (options.groups) this.draft.groups.forEach(function(g) { list.push([g.id, g.name + '（策略组）']); });
		if (options.follow) list.push(['Proxy', '跟随 Proxy']);
		var self = this;
		this.draft.nodes.forEach(function(raw) { var n = model.effectiveNode(self.draft, raw); if (n.enabled && !n.excluded) list.push([n.id, n.name]); });
		return list;
	},
	render_groups: function() {
		var self = this;
		return this.card('策略组', [E('p', { 'class': 'ar-muted' }, ['OpenAI、Netflix 与 Disney+ 可以跟随 Proxy，也可选择独立节点或直连。选择会先保存，随后须应用。']),
			E('div', { 'class': 'ar-grid' }, this.draft.groups.map(function(g) {
				var select = self.select(g.selected, self.outbounds({ follow: g.id !== 'Proxy' }));
				select.disabled = self.busy || self.dirty || self.conflict || self.readonly;
				return self.card(g.name, [self.field('保存的出口', select), self.button('保存此组选择', '✓', function() { return self.chooseNode(g.id, select.value); }, { text: true, disabled: self.dirty || self.conflict })]);
			}))]);
	},

	render_rules: function() {
		var self = this;
		var mode = this.select(this.draft.mode, [['rule', '规则分流'], ['global', '全局代理'], ['direct', '直连']]);
		var defaultOutbound = this.select(this.draft.defaultOutbound, this.outbounds({ groups: true, block: true }));
		mode.disabled = defaultOutbound.disabled = this.busy || this.readonly;
		mode.addEventListener('change', function() { self.draft.mode = mode.value; self.changed(); });
		defaultOutbound.addEventListener('change', function() { self.draft.defaultOutbound = defaultOutbound.value; self.changed(); });
		var rows = this.draft.rules.map(function(r, i) {
			return [String(i + 1), r.enabled ? '启用' : '停用', ({ domain: '域名', suffix: '域名后缀', ip: 'IPv4', cidr: 'IPv4 网段' })[r.type] || r.type,
				r.value, model.label(self.draft, r.outbound), E('div', { 'class': 'ar-actions' }, [
					self.button('编辑规则', '✎', function() { self.editRule(r); }),
					self.button('提高优先级', '↑', function() { self.moveRule(i, -1); }, { disabled: i === 0 }),
					self.button('降低优先级', '↓', function() { self.moveRule(i, 1); }, { disabled: i === self.draft.rules.length - 1 }),
					self.button('删除规则', '×', function() { if (window.confirm('删除规则“' + r.value + '”？')) { self.draft.rules.splice(i, 1); self.changed(); } })])];
		});
		return this.card('规则与默认出口', [E('div', { 'class': 'ar-form ar-inline-form' }, [this.field('运行模式', mode), this.field('未匹配时的默认出口', defaultOutbound)]),
			E('div', { 'class': 'ar-toolbar' }, [E('p', { 'class': 'ar-muted' }, ['按从上到下的顺序，首条启用且匹配的规则生效。全局代理使用 Proxy；直连模式不执行分流规则。']),
				this.button('添加规则', '+', function() { self.editRule(); }, { text: true, primary: true })]),
			rows.length ? this.table(['优先级', '状态', '匹配类型', '匹配值', '出口', '操作'], rows) : this.empty('暂无自定义规则；规则模式使用默认出口。'),
			E('p', { 'class': 'ar-muted' }, ['首版仅明确支持域名、域名后缀与 IPv4 地址/网段。IPv6 输入会被拒绝；DNS、UDP 和终端透明转发仍需实际验证。'])]);
	},
	moveRule: function(index, delta) {
		var other = index + delta;
		if (other < 0 || other >= this.draft.rules.length) return;
		var moved = this.draft.rules.splice(index, 1)[0]; this.draft.rules.splice(other, 0, moved); this.changed();
	},
	editRule: function(original) {
		var self = this, r = original || { type: 'suffix', value: '', outbound: 'Proxy', enabled: true };
		var type = this.select(r.type, [['domain', '精确域名'], ['suffix', '域名后缀'], ['ip', 'IPv4 地址'], ['cidr', 'IPv4 CIDR 网段']]);
		var value = this.input(r.value), outbound = this.select(r.outbound, this.outbounds({ groups: true, block: true })), enabled = this.input('', 'checkbox', { checked: r.enabled || undefined });
		this.modal(original ? '编辑规则' : '添加规则', [this.field('匹配类型', type), this.field('匹配值', value), this.field('出口', outbound), this.field('启用规则', enabled)], function() {
			if (!value.value.trim()) throw new Error('匹配值不能为空');
			var next = { id: r.id || model.id('r'), type: type.value, value: value.value.trim(), outbound: outbound.value, enabled: enabled.checked };
			if (original) self.draft.rules[self.draft.rules.indexOf(original)] = next;
			else self.draft.rules.push(next);
		});
	},

	render_settings: function() {
		var self = this;
		return E('div', {}, [this.card('配置导出', [E('p', {}, ['导出来自路由器的已保存配置。默认脱敏导出可用于审查；完整导出包含 UUID 和订阅凭证，请妥善保存。']),
			E('div', { 'class': 'ar-actions' }, [this.button('导出脱敏配置', '↓', function() { return self.exportConfig(false); }, { text: true }),
				this.button('导出含凭证的完整配置', '↓', function() { return self.exportConfig(true); }, { text: true })])]),
			this.card('配置恢复', [E('p', {}, ['恢复管理服务保存的上一份可用配置。恢复请求返回后仍需核对服务、核心选择和新连接出口。']),
				this.button('恢复上一份可用配置', '↶', function() {
					if (self.dirty || self.conflict) throw new Error('请先处理未保存修改和版本冲突');
					if (window.confirm('恢复上一份可用配置？当前已保存配置将被替换。')) return self.mutate('rollback', [self.revision], '恢复请求已完成，请核对实际运行状态。');
				}, { text: true, disabled: this.dirty || this.conflict })]),
			this.card('基础网络与管理通道', [E('p', {}, ['本页复用 LuCI 登录认证。核心控制 API 只由管理服务在本机访问，浏览器不持有核心密钥。']),
				E('p', { 'class': 'ar-alert ar-warning' }, ['恢复上一份代理配置与恢复基础联网是不同操作。DNS、转发与启动配置的撤销能力尚须设备实测；停止代理服务不能视为已经恢复基础网络。'])])]);
	},
	exportConfig: function(includeSecrets) {
		if (includeSecrets && !window.confirm('完整导出包含节点 UUID 与订阅凭证。确认保存到当前设备？')) return;
		return api.call('export', [includeSecrets]).then(function(result) {
			var blob = new Blob([JSON.stringify(result.model, null, 2) + '\n'], { type: 'application/json;charset=utf-8' });
			var url = URL.createObjectURL(blob), a = E('a', { href: url, download: 'alwayroute-' + (result.redacted ? 'redacted' : 'private') + '.json' });
			document.body.appendChild(a); a.click(); a.remove(); window.setTimeout(function() { URL.revokeObjectURL(url); }, 1000);
		});
	}
});

function domReplace(element, children) {
	while (element.firstChild) element.removeChild(element.firstChild);
	children.forEach(function(child) { element.appendChild(child); });
}
