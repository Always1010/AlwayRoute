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
		this.root = E('div', { 'class': 'cbi-map ar-app' });
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
			'class': 'btn cbi-button ar-button ' + (options.primary ? 'cbi-button-action ' : '') + (options.style || '') + (options.text ? '' : ' ar-icon'),
			disabled: options.disabled || this.busy || (this.readonly && !options.readonly) || undefined,
			click: function(event) {
				event.preventDefault();
				try { Promise.resolve(action()).catch(function(error) { self.error(error); }); }
				catch (error) { self.error(error); }
			}
		}, options.text ? [label] : [E('span', { 'aria-hidden': 'true', 'class': 'ar-glyph' }, [icon])]);
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
		this.operationMethod = method;
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

	refreshRuntime: function(afterMutation) {
		var self = this;
		if (this.busy || document.hidden || !this.root.isConnected) return Promise.resolve();
		if (this.tab !== 'overview' && this.tab !== 'logs') return Promise.resolve();
		this.pendingPolls = this.pendingPolls || {};
		if (this.pendingPolls[this.tab]) return afterMutation ? this.pendingPolls[this.tab].then(function() { return self.refreshRuntime(); }) : Promise.resolve();
		this.polling = true;
		var generation = this.operationGeneration || 0, tab = this.tab;
		var requests = tab === 'logs' ? [api.call('logs', [20])] : [api.call('status'), api.call('traffic')];
		var operation = Promise.allSettled(requests).then(function(results) {
			if (!self.root.isConnected || self.busy || self.tab !== tab || generation !== (self.operationGeneration || 0)) return;
			if (tab === 'logs') {
				self.logs = results[0].status === 'fulfilled' ? (results[0].value.entries || []).slice(-20) : [];
				self.logsError = results[0].status === 'rejected' ? results[0].reason.message : null;
				self.updateLive(); return;
			}
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
			self.updateLive();
		}).finally(function() {
			delete self.pendingPolls[tab]; self.polling = Object.keys(self.pendingPolls).length > 0;
		});
		this.pendingPolls[tab] = operation;
		return operation;
	},

	configurationLabel: function() {
		if (this.busy || this.activeJob) return ({ save: '正在保存配置…', apply: '正在应用配置…', refresh: '正在更新订阅…', check: '正在检查节点…', service: '正在切换服务…', rollback: '正在恢复配置…', import: '正在导入节点…' })[this.activeJob ? this.activeJob.method : this.operationMethod] || '正在执行，请稍候…';
		return this.dirty ? '有未保存的修改' : this.state.appliedRevision == null ? '配置尚未应用' :
			this.state.savedRevision !== this.state.appliedRevision ? '配置已保存，尚未应用' : '配置已应用';
	},
	serviceRunning: function() {
		var service = this.runtime && this.runtime.service;
		return typeof service === 'boolean' ? service : service && service.running;
	},
	actualChoice: function(id) {
		var core = this.runtime && this.runtime.core, groups = core && core.available !== false && core.groups;
		if (groups && groups.proxies) groups = groups.proxies;
		var actual = groups && groups[id];
		return typeof actual === 'string' ? actual : actual && actual.now;
	},
	groupStatus: function(group) {
		if (this.serviceRunning() === false) return '服务已停止';
		var actual = this.actualChoice(group.id);
		if (!actual) return '实际出口未获取';
		if (actual !== group.selected) return '核心当前选择：' + model.label(this.draft, actual);
		if (actual === 'Proxy') {
			var primary = this.actualChoice('Proxy');
			return primary ? '核心跟随：' + model.label(this.draft, primary) : '核心跟随主策略';
		}
		return '核心选择一致';
	},
	updateLive: function() {
		// Polling only replaces status text. Keep focused selects, forms and scroll intact.
		var self = this, live = this.live || {}, running = this.serviceRunning(), traffic = this.traffic || {};
		if (live.service) live.service.textContent = running === true ? '运行中' : running === false ? '已停止' : '未知';
		if (live.traffic) live.traffic.textContent = traffic.available ? '↑ ' + model.formatRate(traffic.upload) + '    ↓ ' + model.formatRate(traffic.download) : '不可用';
		if (live.health) live.health.textContent = model.stateLabel(this.state.healthy);
		if (live.config) live.config.textContent = this.configurationLabel();
		if (live.conflict) live.conflict.hidden = !this.conflict;
		if (live.runtimeError) { live.runtimeError.hidden = !this.runtimeError; live.runtimeError.textContent = this.runtimeError || ''; }
		if (live.lastError) { live.lastError.hidden = !this.state.lastError; live.lastError.textContent = this.lastErrorLabel(); }
		if (live.start) live.start.disabled = !!(this.busy || this.readonly || this.dirty || this.conflict || running === true);
		if (live.stop) live.stop.disabled = !!(this.busy || this.readonly || running === false);
		if (live.apply) live.apply.disabled = !!(this.busy || this.readonly || this.conflict);
		if (live.save) live.save.disabled = !!(this.busy || this.readonly || !this.dirty || this.conflict);
		(this.draft.groups || []).forEach(function(group) { if (live.groups && live.groups[group.id]) live.groups[group.id].textContent = self.groupStatus(group); });
		if (live.logs) {
			var fingerprint = JSON.stringify([this.logsError || null, this.logs]);
			if (fingerprint !== this.logsFingerprint) {
				var top = live.logs.scrollTop, left = live.logs.scrollLeft;
				domReplace(live.logs, this.logEntries()); this.logsFingerprint = fingerprint;
				live.logs.scrollTop = top; live.logs.scrollLeft = left;
			}
		}
	},

	paint: function() {
		if (!this.root) return;
		var self = this, s = this.state;
		this.live = { groups: {} };
		var tabs = [['overview', '代理策略'], ['nodes', '节点'], ['subscriptions', '订阅'], ['logs', '日志'], ['settings', '备份与恢复']];
		var content = [E('div', { 'class': 'ar-heading' }, [
			E('h2', {}, ['AlwayRoute']),
			E('div', { 'class': 'ar-actions' }, [
				this.button('重新读取', '↻', function() { return self.reload(); }, { readonly: true })
			])
		])];
		this.live.conflict = E('div', { 'class': 'alert-message warning', role: 'alert', hidden: !this.conflict || undefined }, ['配置已被其他会话修改，当前编辑内容已保留。请先记录修改，再重新读取。']);
		content.push(this.live.conflict);
		if (this.readonly) content.push(E('p', { 'class': 'ar-alert ar-warning' }, ['当前 LuCI 账户仅有读取权限；修改操作已禁用。']));
		if (this.message) content.push(E('div', { 'class': 'ar-alert ar-' + this.message.type, role: 'status' }, [this.message.text]));
		this.live.lastError = E('div', { 'class': 'alert-message error', role: 'alert', hidden: !s.lastError || undefined }, [this.lastErrorLabel()]);
		content.push(this.live.lastError);
		content.push(E('ul', { 'class': 'cbi-tabmenu', 'aria-label': 'AlwayRoute 页面' }, tabs.map(function(tab) {
			return E('li', { 'class': tab[0] === self.tab ? 'cbi-tab' : 'cbi-tab-disabled' }, [E('a', { href: '#', 'aria-current': tab[0] === self.tab ? 'page' : undefined,
				click: function(event) { event.preventDefault(); self.tab = tab[0]; self.paint(); self.refreshRuntime(); }
			}, [tab[1]])]);
		})));
		content.push(this['render_' + this.tab]());
		this.live.config = E('span', { 'class': 'ar-config-state', role: 'status' }, [this.configurationLabel()]);
		this.live.apply = this.button('保存并应用', '', function() { return self.saveApply(); }, { text: true, primary: true, style: 'cbi-button-apply', disabled: this.conflict });
		this.live.save = this.button('保存', '', function() { return self.save(); }, { text: true, style: 'cbi-button-save', disabled: !this.dirty || this.conflict });
		content.push(E('div', { 'class': 'cbi-page-actions ar-page-actions' }, [this.live.config,
			E('div', { 'class': 'ar-actions' }, [this.live.apply, this.live.save,
				this.button('重置', '', function() { return self.reload(); }, { text: true, style: 'cbi-button-reset', disabled: !this.dirty })])
		]));
		domReplace(this.root, content);
	},

	reload: function() {
		var self = this;
		if (this.dirty && !window.confirm('重新读取将丢弃尚未保存的编辑。继续？')) return;
		this.checks = {};
		return this.mutate('get', [], '已重新读取持久配置。').then(function() { return self.refreshRuntime(); });
	},
	save: function() { return this.mutate('save', [this.revision, this.draft], '配置已保存，尚未应用。'); },
	saveApply: function() {
		var self = this;
		if (this.conflict) throw new Error('请先处理版本冲突');
		return (this.dirty ? this.save() : Promise.resolve()).then(function() { return self.apply(); });
	},
	apply: function() {
		if (this.dirty || this.conflict) throw new Error('请先保存当前编辑并处理版本冲突');
		var self = this;
		return this.mutate('apply', [this.revision], '配置已应用。').then(function(result) { return self.refreshRuntime(true).then(function() { return result; }); });
	},

	lastErrorLabel: function() {
		var error = this.state.lastError;
		return error ? '管理服务：' + (typeof error === 'string' ? error : error.message || '执行失败') : '';
	},
	card: function(title, children) { return E('section', { 'class': 'cbi-section ar-section' }, [E('h3', {}, [title])].concat(children)); },
	empty: function(text) { return E('p', { 'class': 'ar-empty' }, [text]); },
	table: function(headers, rows) {
		return E('div', { 'class': 'ar-table-scroll' }, [E('table', { 'class': 'table cbi-section-table ar-table' }, [
			E('thead', {}, [E('tr', { 'class': 'tr cbi-section-table-titles' }, headers.map(function(h) { return E('th', { 'class': 'th cbi-section-table-cell', scope: 'col' }, [h]); }))]),
			E('tbody', {}, rows.map(function(row) { return E('tr', { 'class': 'tr cbi-section-table-row' }, row.map(function(cell, i) { return E('td', { 'class': 'td cbi-section-table-cell' + (headers[i] === '操作' ? ' cbi-section-actions' : ' left') }, [cell]); })); }))
		])]);
	},

	render_overview: function() {
		var self = this, running = this.serviceRunning(), traffic = this.traffic || {};
		var mode = this.select(this.draft.mode, [['rule', '规则分流'], ['global', '全局代理'], ['direct', '全部直连']]);
		var fallback = this.select(this.draft.defaultOutbound, this.outbounds({ groups: true, block: true }));
		mode.disabled = this.busy || this.readonly;
		fallback.disabled = this.busy || this.readonly || this.draft.mode !== 'rule';
		mode.addEventListener('change', function() { self.draft.mode = mode.value; self.changed(); });
		fallback.addEventListener('change', function() { self.draft.defaultOutbound = fallback.value; self.changed(); });
		this.live.service = E('strong', {}, [running === true ? '运行中' : running === false ? '已停止' : '未知']);
		this.live.start = this.button('启动', '', function() { return self.mutate('service', ['start'], '启动请求已完成。').then(function() { return self.refreshRuntime(); }); }, { text: true, disabled: this.dirty || this.conflict || running === true });
		this.live.stop = this.button('停止', '', function() { return self.mutate('service', ['stop'], '服务已停止。').then(function() { return self.refreshRuntime(); }); }, { text: true, disabled: running === false });
		this.live.traffic = E('span', {}, [traffic.available ? '↑ ' + model.formatRate(traffic.upload) + '    ↓ ' + model.formatRate(traffic.download) : '不可用']);
		this.live.health = E('span', {}, [model.stateLabel(this.state.healthy)]);
		this.live.runtimeError = E('p', { 'class': 'alert-message warning', hidden: !this.runtimeError || undefined }, [this.runtimeError || '']);
		var section = this.strategySection || 'groups';
		return E('div', {}, [this.card('运行与策略', [
			this.field('代理服务', E('div', { 'class': 'ar-actions' }, [this.live.service, this.live.start, this.live.stop,
				this.button('刷新运行状态', '↻', function() { return self.refreshRuntime(); }, { readonly: true })])),
			this.field('实时流量', this.live.traffic),
			this.field('终端出口验证', this.live.health),
			this.live.runtimeError,
			this.field('运行模式', mode),
			this.draft.mode === 'rule' ? this.field('默认出口', fallback, '未匹配分流规则时使用。') : E('p', { 'class': 'cbi-section-descr' }, [this.draft.mode === 'global' ? '全局代理使用主策略组，分流规则暂不参与。' : '应用后停止代理接管，保留已有策略配置。'])
		]),
			E('ul', { 'class': 'cbi-tabmenu', 'aria-label': '代理策略设置' }, [['groups', '策略组'], ['rules', '分流规则']].map(function(tab) {
				return E('li', { 'class': section === tab[0] ? 'cbi-tab' : 'cbi-tab-disabled' }, [E('a', { href: '#', 'aria-current': section === tab[0] ? 'page' : undefined,
					click: function(event) { event.preventDefault(); self.strategySection = tab[0]; self.paint(); }
				}, [tab[1]])]);
			})), section === 'rules' ? this.render_rules() : this.render_groups()
		]);
	},

	render_nodes: function() {
		var self = this, searchable = [];
		var rows = this.draft.nodes.map(function(raw) {
			var n = model.effectiveNode(self.draft, raw), override = self.draft.overrides[raw.id];
			searchable.push({ name: n.name.toLowerCase(), source: raw.source || '@manual' });
			var source = raw.source && self.draft.subscriptions.filter(function(s) { return s.id === raw.source; })[0];
			var result = self.checks[n.id];
			var check = result && self.state.appliedRevision != null && result.checkedRevision === self.state.appliedRevision ? self.checkLabel(result) : null;
			return [E('strong', {}, [n.name]),
				n.type.toUpperCase(), source ? source.name + (override ? ' · 本地覆盖' : '') : '手动',
				n.excluded ? '已排除' : n.enabled ? '启用' : '停用',
				check ? check : '未检查',
				E('div', { 'class': 'ar-actions' }, [
					self.button('编辑节点', '✎', function() { self.editNode(raw); }),
					self.button('检查此节点', '◉', function() { return self.checkNode(n.id); }, { disabled: self.dirty || self.conflict || self.state.appliedRevision == null || self.state.savedRevision !== self.state.appliedRevision || n.excluded || !n.enabled })
				])];
		});
		var list = this.table(['名称', '协议', '来源', '状态', '节点检查', '操作'], rows);
		var search = this.input(this.nodeQuery || '', 'search', { placeholder: '搜索节点名称', 'aria-label': '搜索节点名称' });
		var sources = [['', '全部来源'], ['@manual', '手动节点']].concat(this.draft.subscriptions.map(function(s) { return [s.id, s.name]; }));
		var sourceFilter = this.select(this.nodeSource || '', sources); sourceFilter.setAttribute('aria-label', '节点来源');
		var count = E('p', { 'class': 'cbi-section-descr' }, []);
		function filter() {
			self.nodeQuery = search.value; self.nodeSource = sourceFilter.value;
			var query = search.value.trim().toLowerCase(), visible = 0, elements = list.children[0].children[1].children;
			searchable.forEach(function(node, i) {
				var matches = node.name.indexOf(query) !== -1 && (!sourceFilter.value || node.source === sourceFilter.value);
				elements[i].hidden = !matches; if (matches) visible++;
			});
			count.textContent = visible + ' / ' + rows.length + ' 个节点';
		}
		// A removed subscription must not leave a stale filter selecting no source.
		if (!sources.some(function(s) { return s[0] === self.nodeSource; })) { sourceFilter.value = ''; this.nodeSource = ''; }
		search.addEventListener('input', filter); sourceFilter.addEventListener('change', filter); filter();
		return this.card('节点', [E('div', { 'class': 'ar-toolbar' }, [E('div', { 'class': 'ar-actions ar-filters' }, [search, sourceFilter]),
			E('div', { 'class': 'ar-actions' }, [this.button('导入节点', '⇧', function() {
				self.showImport('导入为手动节点', function(content) { return self.mutate('import', [self.revision, content], '节点已导入并保存。请选择策略组出口，再应用配置。'); });
			}, { text: true, disabled: this.dirty || this.conflict }), this.button('添加节点', '+', function() { self.editNode(); }, { text: true, primary: true })])]),
			rows.length ? list : this.empty('暂无节点，请添加节点或订阅。'), count,
			E('p', { 'class': 'ar-muted' }, ['在代理策略页选择出口。节点检查需先保存并应用当前配置。'])]);
	},

	input: function(value, type, attrs) { return E('input', Object.assign({ type: type || 'text', value: value == null ? '' : String(value), 'class': 'cbi-input-text' }, attrs || {})); },
	select: function(value, choices) {
		return E('select', { 'class': 'cbi-input-select' }, choices.map(function(choice) {
			return E('option', { value: choice[0], selected: choice[0] === value ? '' : undefined }, [choice[1]]);
		}));
	},
	field: function(label, control, help) {
		var id = model.id('field'); control.id = id;
		return E('div', { 'class': 'cbi-value ar-field' }, [E('label', { 'class': 'cbi-value-title', 'for': id }, [label]),
			E('div', { 'class': 'cbi-value-field' }, [control, help ? E('div', { 'class': 'cbi-value-description' }, [help]) : ''])]);
	},
	modal: function(title, fields, commit, actions) {
		var self = this, errorBox = E('p', { 'class': 'ar-alert ar-error', hidden: '' });
		var extra = (actions || []).map(function(action) { return self.button(action.label, '', function() {
			try { if (action.run() !== false) ui.hideModal(); }
			catch (error) { errorBox.hidden = false; errorBox.textContent = error.message; }
		}, { text: true, style: action.style, disabled: action.disabled }); });
		ui.showModal(title, [E('div', { 'class': 'ar-form' }, fields), errorBox, E('div', { 'class': 'ar-modal-actions' }, [
			E('div', { 'class': 'ar-actions' }, extra), E('div', { 'class': 'ar-actions' }, [
			this.button('取消', '×', function() { ui.hideModal(); }, { text: true }),
			this.button('确定', '✓', function() {
				try { commit(); ui.hideModal(); self.changed(); }
				catch (error) { errorBox.hidden = false; errorBox.textContent = error.message; }
			}, { text: true, primary: true })
		])])]);
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
		var excluded = this.input('', 'checkbox', { checked: n.excluded || undefined });
		var sniField = this.field('TLS Server Name', sni), pathField = this.field('WebSocket Path', path), hostField = this.field('WebSocket Host', host);
		function transportFields() { sniField.hidden = !tls.checked; pathField.hidden = hostField.hidden = transport.value !== 'ws'; }
		tls.addEventListener('change', transportFields); transport.addEventListener('change', transportFields); transportFields();
		var fields = [this.field('名称', name), raw && raw.source ? this.field('本地排除', excluded) : this.field('启用节点', enabled),
			this.field('协议', E('span', {}, ['VMess'])), this.field('服务器', server), this.field('端口', port), this.field('UUID（敏感）', uuid),
			this.field('传输', transport), pathField, hostField, this.field('启用 TLS', tls), sniField,
			E('details', { 'class': 'ar-details' }, [E('summary', {}, ['高级参数']), this.field('VMess 加密', security), this.field('VMess alterId', alterId)]),
			raw && raw.source ? E('p', { 'class': 'cbi-section-descr' }, ['修改作为本地覆盖保留，订阅更新不会覆盖。']) : ''];
		var actions = raw ? raw.source ? self.draft.overrides[raw.id] ? [{ label: '恢复订阅原始值', run: function() {
			if (!window.confirm('清除此节点的本地覆盖？')) return false;
			delete self.draft.overrides[raw.id]; self.changed();
		} }] : [] : [{ label: '删除节点', style: 'cbi-button-remove', run: function() {
			if (!window.confirm('删除节点“' + n.name + '”？')) return false;
			model.removeNode(self.draft, raw.id); self.changed();
		} }] : [];
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
				if (excluded.checked && !n.excluded && model.references(self.draft, raw.id).length) throw new Error('请先移除该节点的策略组、规则和默认出口引用');
				self.draft.overrides[raw.id] = Object.assign({}, previous, { name: name.value.trim(), patch: values, excluded: excluded.checked });
			}
			else {
				var next = Object.assign({}, raw || { id: model.id('n'), type: 'vmess', source: null }, values, { name: name.value.trim(), enabled: enabled.checked });
				if (!next.transport) delete next.transport;
				if (raw) self.draft.nodes[self.draft.nodes.indexOf(raw)] = next;
				else self.draft.nodes.push(next);
			}
		}, actions);
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
		return this.mutate('select', [this.revision, group, id], '选择已保存，请应用后生效。');
	},

	render_subscriptions: function() {
		var self = this;
		var rows = this.draft.subscriptions.map(function(s) {
			var count = self.draft.nodes.filter(function(n) { return n.source === s.id; }).length;
			return [s.name, s.enabled ? '启用' : '停用', String(count), s.intervalHours ? '每 ' + s.intervalHours + ' 小时' : '手动更新',
				E('div', {}, [E('span', {}, [typeof s.lastUpdate === 'number' ? new Date(s.lastUpdate * 1000).toLocaleString() : s.lastUpdate || '从未更新']), s.lastError ? E('small', { 'class': 'ar-error ar-block' }, [s.lastError]) : '']),
				E('div', { 'class': 'ar-actions' }, [self.button('编辑订阅', '✎', function() { self.editSubscription(s); }),
					self.button('手动更新订阅', '↻', function() { return self.updateSubscription(s); }, { disabled: self.dirty || self.conflict || !s.enabled }),
					self.button('从本地内容更新', '⇧', function() { self.importSubscription(s); }, { disabled: self.dirty || self.conflict || !s.enabled })])];
		});
		return this.card('订阅来源', [E('div', { 'class': 'ar-toolbar' }, [E('p', { 'class': 'ar-muted' }, ['订阅地址仅用于本机管理服务抓取，不发送公共转换服务。失败时保留旧节点。']),
			this.button('添加订阅', '+', function() { self.editSubscription(); }, { text: true, primary: true })]),
			rows.length ? this.table(['名称', '状态', '节点数', '更新计划', '最近结果', '操作'], rows) : this.empty('暂无订阅，请添加订阅后保存并更新。'),
			E('p', { 'class': 'ar-muted' }, ['订阅只更新节点，不导入策略组和规则；节点被引用时不会静默删除。'])]);
	},
	editSubscription: function(original) {
		var self = this, s = original || { name: '', url: '', enabled: true, intervalHours: 0, allowHttp: false };
		var name = this.input(s.name), url = this.input(s.url, 'password', { autocomplete: 'new-password' });
		var enabled = this.input('', 'checkbox', { checked: s.enabled || undefined }), interval = this.input(s.intervalHours, 'number', { min: 0, max: 168 });
		var allowHttp = this.input('', 'checkbox', { checked: s.allowHttp === true || undefined });
		var actions = original ? [{ label: '删除订阅', style: 'cbi-button-remove', run: function() {
			if (!window.confirm('删除订阅“' + s.name + '”及所属节点和本地覆盖？')) return false;
			model.removeSubscription(self.draft, s.id); self.changed();
		} }] : [];
		this.modal(original ? '编辑订阅' : '添加订阅', [this.field('名称', name), this.field('订阅地址（敏感）', url), this.field('启用订阅', enabled),
			this.field('更新间隔（小时）', interval, '0 表示仅手动更新；范围为 1–168 小时。'),
			E('details', { 'class': 'ar-details' }, [E('summary', {}, ['更多选项']), this.field('允许此订阅使用未加密HTTP', allowHttp, '仅对此来源生效，HTTP 不加密传输。')])], function() {
			var address = url.value.trim(), https = /^https:\/\/[^\s]+$/i.test(address), http = /^http:\/\/[^\s]+$/i.test(address);
			if (!name.value.trim() || !(https || (http && allowHttp.checked))) throw new Error('名称必填；默认要求 HTTPS，现有 HTTP 来源须显式勾选此订阅的未加密 HTTP 许可');
			if (!/^\d+$/.test(interval.value) || Number(interval.value) > 168) throw new Error('更新间隔须为 0–168 的整数');
			var next = Object.assign({}, s, { id: s.id || model.id('s'), name: name.value.trim(), url: address, enabled: enabled.checked, intervalHours: Number(interval.value), allowHttp: allowHttp.checked });
			if (original) self.draft.subscriptions[self.draft.subscriptions.indexOf(original)] = next;
			else self.draft.subscriptions.push(next);
		}, actions);
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
		var errorBox = E('p', { 'class': 'ar-alert ar-error', hidden: '' });
		var submit = this.button('导入并保存', '', function() {
			if (!area.value.trim()) { errorBox.hidden = false; errorBox.textContent = '请先粘贴导入内容'; return; }
			submit.disabled = true;
			return Promise.resolve().then(function() { return commit(area.value); }).then(function() { ui.hideModal(); }).catch(function(error) {
				errorBox.hidden = false; errorBox.textContent = error.message;
			}).finally(function() { submit.disabled = false; });
		}, { text: true, primary: true });
		ui.showModal(title, [E('p', {}, ['支持 VMess 链接、Base64 列表及受限 Clash 内容。仅导入节点，失败保留原有数据。']), this.field('订阅或节点内容', area), errorBox,
			E('div', { 'class': 'right ar-actions' }, [this.button('取消', '×', function() { ui.hideModal(); }, { text: true }),
				submit])]);
	},

	outbounds: function(options) {
		options = options || {};
		var list = [['direct', '直连']];
		if (options.block) list.push(['block', '阻断']);
		if (options.groups) this.draft.groups.forEach(function(g) { list.push([g.id, g.name + '（策略组）']); });
		if (options.follow) list.push(['Proxy', '跟随主策略（' + model.label(this.draft, 'Proxy') + '）']);
		var self = this;
		this.draft.nodes.forEach(function(raw) { var n = model.effectiveNode(self.draft, raw); if (n.enabled && !n.excluded) list.push([n.id, n.name]); });
		return list;
	},
	render_groups: function() {
		var self = this;
		var rows = this.draft.groups.map(function(g) {
			var select = self.select(g.selected, self.outbounds({ follow: g.id !== 'Proxy' }));
			select.setAttribute('aria-label', g.name + '的出口');
			select.disabled = self.busy || self.readonly;
			select.addEventListener('change', function() { g.selected = select.value; self.changed(); });
			var actual = E('small', { 'class': 'ar-muted ar-block', 'data-group-status': g.id }, [self.groupStatus(g)]);
			self.live.groups[g.id] = actual;
			var count = self.draft.rules.filter(function(r) { return r.outbound === g.id && r.enabled; }).length, uses = [];
			if (g.id === 'Proxy') uses.push('主策略');
			if (self.draft.defaultOutbound === g.id) uses.push('默认出口');
			if (count) uses.push(count + ' 条规则');
			return [E('strong', {}, [g.name]), E('div', {}, [select, actual]), uses.join(' · ') || '未使用',
				self.button('编辑策略组', '✎', function() { self.editGroup(g); })];
		});
		return this.card('策略组', [this.table(['名称', '出口', '用途', '操作'], rows),
			E('div', { 'class': 'ar-toolbar ar-toolbar-end' }, [this.button('添加策略组', '+', function() { self.editGroup(); }, { text: true, primary: true, disabled: this.draft.groups.length >= 16 })]),
			E('p', { 'class': 'cbi-section-descr' }, ['组名不会自动匹配网站，请通过分流规则指定用途。'])]);
	},
	editGroup: function(original) {
		var self = this, name = this.input(original ? original.name : ''), selected = this.select(original ? original.selected : 'Proxy', this.outbounds({ follow: !original || original.id !== 'Proxy' }));
		var fields = [this.field('名称', name), this.field('出口', selected)];
		var actions = original && original.id !== 'Proxy' ? [{ label: '删除策略组', run: function() { return self.removeGroup(original); }, style: 'cbi-button-remove' }] : [];
		this.modal(original ? '编辑策略组' : '添加策略组', fields, function() {
			var value = name.value.trim();
			if (!value || value.length > 128) throw new Error('名称须为 1–128 个字符');
			if (original) { original.name = value; original.selected = selected.value; }
			else {
				if (self.draft.groups.length >= 16) throw new Error('最多支持 16 个策略组');
				self.draft.groups.push({ id: model.id('g'), name: value, selected: selected.value });
			}
		}, actions);
	},
	removeGroup: function(group) {
		if (group.id === 'Proxy') throw new Error('必须保留主策略组');
		var refs = model.references(this.draft, group.id);
		if (refs.length) throw new Error('请先处理引用：' + refs.join('、'));
		if (!window.confirm('删除策略组“' + group.name + '”？')) return false;
		this.draft.groups = this.draft.groups.filter(function(g) { return g.id !== group.id; });
		this.changed(); return true;
	},

	render_rules: function() {
		var self = this;
		var rows = this.draft.rules.map(function(r, i) {
			return [String(i + 1), r.enabled ? '启用' : '停用', ({ domain: '域名', suffix: '域名后缀', ip: 'IPv4', cidr: 'IPv4 网段' })[r.type] || r.type,
				r.value, model.label(self.draft, r.outbound), E('div', { 'class': 'ar-actions' }, [
					self.button('编辑规则', '✎', function() { self.editRule(r); }),
					self.button('提高优先级', '↑', function() { self.moveRule(i, -1); }, { disabled: i === 0 }),
					self.button('降低优先级', '↓', function() { self.moveRule(i, 1); }, { disabled: i === self.draft.rules.length - 1 }),
					self.button('删除规则', '×', function() { if (window.confirm('删除规则“' + r.value + '”？')) { self.draft.rules.splice(i, 1); self.changed(); } })])];
		});
		return this.card('分流规则', [this.draft.mode !== 'rule' ? E('p', { 'class': 'alert-message notice' }, ['当前模式不使用分流规则，切换到规则分流并应用后生效。']) : '',
			E('div', { 'class': 'ar-toolbar' }, [E('p', { 'class': 'ar-muted' }, ['按从上到下的顺序匹配，未匹配时使用默认出口。']),
				this.button('添加规则', '+', function() { self.editRule(); }, { text: true, primary: true })]),
			rows.length ? this.table(['优先级', '状态', '匹配类型', '匹配值', '出口', '操作'], rows) : this.empty('暂无自定义规则；规则模式使用默认出口。'),
			E('p', { 'class': 'ar-muted' }, ['支持域名、域名后缀和 IPv4 地址/网段。'])]);
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

	logEntries: function() {
		if (this.logsError) return [E('p', { 'class': 'ar-error' }, [this.logsError])];
		if (!this.logs.length) return [this.empty('暂无管理事件。')];
		return [this.table(['时间', '级别', '事件'], this.logs.map(function(entry) {
			if (typeof entry === 'string') return ['—', '—', entry];
			return [typeof entry.time === 'number' ? new Date(entry.time * 1000).toLocaleString() : entry.time || '—', entry.level || '—', entry.message || ''];
		}))];
	},
	render_logs: function() {
		var self = this;
		this.logsFingerprint = JSON.stringify([this.logsError || null, this.logs]);
		this.live.logs = E('div', { 'class': 'ar-log-content' }, this.logEntries());
		return this.card('管理日志', [E('div', { 'class': 'ar-toolbar' }, [E('p', { 'class': 'cbi-section-descr' }, ['最近 20 条管理事件，每 5 秒更新。']),
			this.button('刷新日志', '↻', function() { return self.refreshRuntime(); }, { readonly: true })]), this.live.logs]);
	},
	render_settings: function() {
		var self = this;
		return E('div', {}, [this.card('配置备份', [E('p', { 'class': 'cbi-section-descr' }, ['导出路由器上已保存的配置。完整配置包含节点与订阅凭证。']),
			E('div', { 'class': 'ar-actions' }, [this.button('导出脱敏配置', '↓', function() { return self.exportConfig(false); }, { text: true }),
				this.button('导出完整配置', '↓', function() { return self.exportConfig(true); }, { text: true })])]),
			this.card('配置恢复', [E('p', { 'class': 'cbi-section-descr' }, ['替换当前已保存配置并应用。']),
				this.button('恢复上一份可用配置', '↶', function() {
					if (self.dirty || self.conflict) throw new Error('请先处理未保存修改和版本冲突');
					if (window.confirm('恢复上一份可用配置？当前已保存配置将被替换。')) return self.mutate('rollback', [self.revision], '恢复请求已完成，请核对实际运行状态。');
				}, { text: true, disabled: this.dirty || this.conflict })])]);
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
