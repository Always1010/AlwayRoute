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
		if (!L.hasViewPermission()) return Promise.all([this.request('status').then(function(runtime) {
			return { model: { revision: runtime.state.savedRevision, nodes: [], groups: [], subscriptions: [], overrides: {}, rules: [] }, state: runtime.state, runtime: runtime };
		}), this.request('capabilities')]);
		return this.request('job_status').then(function(progress) {
			var checking = progress.busy && progress.job && progress.job.method === 'check';
			var saved = checking ? self.request('get').then(function(result) { result.checkJob = progress.job; return result; }) :
				progress.busy && progress.job && progress.job.status === 'running' ? self.waitJob(progress.job) : self.request('get');
			return Promise.all([saved, self.request('capabilities')]);
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
		this.runtime = data[0].runtime || null;
		this.lastStatusAttempt = null;
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
			if (data[0].checkJob) { self.observeCheck(data[0].checkJob); return; }
			if (self.root.isConnected) { self.wasConnected = true; self.refreshRuntime(true); }
		}, 0);
		return E('div', {}, [E('link', { rel: 'stylesheet', href: L.resource('alwayroute/style.css') + '?v=' + encodeURIComponent(L.env.resource_version) }), this.root]);
	},

	button: function(label, icon, action, options) {
		options = options || {};
		var self = this;
		return E('button', {
			type: 'button', title: label, 'aria-label': label,
			'class': 'btn cbi-button ar-button ' + (options.primary ? 'cbi-button-action ' : '') + (options.style || '') + (options.text ? '' : ' ar-icon'),
			disabled: options.disabled || (this.busy && !options.duringCheck) || (this.uncertain && !options.recovery) || (this.readonly && !options.readonly) || undefined,
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

	request: function(method, args) {
		var timer;
		return Promise.race([api.call(method, args), new Promise(function(_resolve, reject) {
			timer = window.setTimeout(function() { var error = new Error('请求超时，操作结果尚未确认'); error.code = 'OPERATION_TIMEOUT'; reject(error); }, 15000);
		})]).finally(function() { window.clearTimeout(timer); });
	},
	mutate: function(method, args, success, verify) {
		var self = this;
		if (this.readonly) return Promise.reject(new Error('当前账户仅有读取权限'));
		if (this.busy) return Promise.reject(new Error('另一项操作正在执行'));
		if (this.uncertain) return Promise.reject(new Error('上次操作结果尚未确认，请先重新检查状态'));
		this.busy = true;
		this.operationMethod = method;
		this.operationGeneration = (this.operationGeneration || 0) + 1;
		this.message = null;
		this.paint();
		return this.request(method, args).then(function(result) {
			if (result.job && result.job.status === 'running') return self.waitJob(result.job);
			return result;
		}).then(async function(result) {
			if (verify) await verify(result);
			self.accept(result);
			self.message = { type: 'success', text: typeof success === 'function' ? success(result) : success };
			return result;
		}).catch(async function(error) {
			if (error.code === 'OPERATION_TIMEOUT' || error.code === 'STATE_UNCONFIRMED') self.uncertain = true;
			else if (method === 'configure' || method === 'service') {
				try { self.runtime = await self.request('status'); self.updateState(self.runtime.state || self.state); }
				catch (_error) { self.runtime = null; self.uncertain = true; }
			}
			self.error(error);
			throw error;
		}).finally(function() { self.busy = false; self.pendingModel = null; self.pendingGroup = null; self.paint(); });
	},

	waitJob: function(job) {
		var self = this, started = Date.now(), interval = job.method === 'check' ? 1000 : 200;
		this.activeJob = job;
		this.pendingJob = job;
		this.paint();
		async function next() {
			for (;;) {
				await new Promise(function(resolve) { window.setTimeout(resolve, interval); });
				interval = 1000;
				if (Date.now() - started >= (job.method === 'check' ? 600000 : 120000)) { var timeout = new Error('等待超时，操作结果尚未确认，请重新检查'); timeout.code = 'OPERATION_TIMEOUT'; throw timeout; }
				var result = await self.request('job_status');
				var current = result.job;
				if (!current || current.id !== job.id) { var changed = new Error('后台任务记录已变化，请重新检查实际状态'); changed.code = 'STATE_UNCONFIRMED'; throw changed; }
				self.activeJob = current;
				if (job.method === 'check') { self.pendingJob = current; self.acceptChecks(current.result || { checks: current.checks }); }
				if (current.status === 'running') {
					continue;
				}
				if (current.status !== 'succeeded' && !(job.method === 'check' && current.status === 'cancelled')) {
					self.pendingJob = null;
					var detail = current.error || {}, error = new Error(detail.message || '后台任务失败');
					error.code = detail.code || 'JOB_FAILED'; throw error;
				}
				self.pendingJob = null;
				return self.request('get').then(function(saved) { return Object.assign({}, current.result || {}, saved); });
			}
		}
		return next().finally(function() { self.activeJob = null; });
	},
	runtimeSnapshotPending: function(runtime, requireCore) {
		if (!runtime) return true;
		if (runtime.snapshot && runtime.snapshot.status !== 'current') return true;
		var service = runtime.service, running = typeof service === 'boolean' ? service : service && service.running;
		if (typeof running !== 'boolean' || service && service.status === 'unknown') return true;
		return !!(requireCore && running && runtime.core && runtime.core.status === 'unknown');
	},
	readRuntimeStatus: async function(requireCore) {
		var runtime;
		for (var attempt = 0; attempt < 10; attempt++) {
			runtime = await this.request('status');
			if (!this.runtimeSnapshotPending(runtime, requireCore)) return runtime;
			if (attempt < 9) await new Promise(function(resolve) { window.setTimeout(resolve, 1000); });
		}
		return runtime;
	},
	confirmRuntime: async function(result, expectedRunning) {
		var runtime;
		try { runtime = await this.readRuntimeStatus(!!result.model); }
		catch (_error) { var unavailable = new Error('操作已返回，但无法确认实际状态，请重新检查'); unavailable.code = 'STATE_UNCONFIRMED'; throw unavailable; }
		this.runtime = runtime;
		var running = this.serviceRunning(), candidate = result.model;
		var valid = typeof running === 'boolean' && (expectedRunning == null || running === expectedRunning);
		if (candidate && running) {
			valid = valid && runtime.state && runtime.state.appliedRevision === candidate.revision;
			candidate.groups.forEach(function(group) {
				if (group.id === 'Other' && group.selected === 'block') return;
				if (this.actualChoice(group.id) !== group.selected) valid = false;
			}, this);
		}
		if (!valid) { var error = new Error('实际状态尚未确认，请重新检查后再操作'); error.code = 'STATE_UNCONFIRMED'; throw error; }
		result.state = runtime.state || result.state;
		return runtime;
	},
	configureModel: function(candidate, success) {
		var self = this, wasRunning = this.serviceRunning();
		if (this.busy || this.uncertain) return Promise.reject(new Error('请先等待当前操作或重新检查状态'));
		if (this.conflict) return Promise.reject(new Error('配置已由其他会话更新，请先重新读取'));
		this.pendingModel = candidate;
		return this.mutate('configure', [this.revision, candidate], function() {
			return self.serviceRunning() === false ? '已更新，下次启动使用。' : success || '已切换。';
		}, function(result) { return self.confirmRuntime(result, typeof wasRunning === 'boolean' ? wasRunning : null); });
	},
	changeConfig: function(edit, success) {
		var candidate = model.clone(this.draft);
		edit(candidate);
		return this.configureModel(candidate, success);
	},
	activateMutation: function(method, args, success) {
		var self = this, wasRunning = this.serviceRunning();
		return this.mutate(method, args, function() { return self.serviceRunning() === false ? '已更新，下次启动使用。' : success; }, function(result) {
			return self.confirmRuntime(result, typeof wasRunning === 'boolean' ? wasRunning : null);
		});
	},
	changeMode: function(value) {
		if (this.busy || this.uncertain || this.conflict) return Promise.reject(new Error('请先等待当前操作或重新检查状态'));
		if (value === this.draft.mode) return Promise.resolve();
		if (value !== 'direct' && !this.proxyReady()) {
			var choices = this.outbounds({ nodesOnly: true });
			this.paint();
			if (!choices.length) return Promise.reject(new Error('请先在节点或订阅页面添加可用节点，再切换代理模式'));
			var selection = this.select('', [['', '请选择节点']].concat(choices));
			this.modal('选择代理节点', [this.field('代理节点', selection)], function(next) {
				if (!choices.some(function(choice) { return choice[0] === selection.value; })) throw new Error('请选择代理节点');
				next.mode = value; next.groups.find(function(group) { return group.id === 'Proxy'; }).selected = selection.value;
			});
			return Promise.resolve();
		}
		return this.changeConfig(function(next) { next.mode = value; }, '运行模式已切换。');
	},
	proxyReady: function() {
		var primary = this.draft.groups.find(function(group) { return group.id === 'Proxy'; });
		return !!primary && this.outbounds({ nodesOnly: true }).some(function(choice) { return choice[0] === primary.selected; });
	},
	toggleService: function() {
		var self = this, running = this.serviceRunning();
		if (this.uncertain || typeof running !== 'boolean') return this.reconcile();
		this.serviceTarget = !running;
		return this.mutate('service', [running ? 'stop' : 'start'], running ? '服务已停止。' : '服务已启动。', function(result) {
			return self.confirmRuntime(result, !running);
		});
	},
	reconcile: async function() {
		if (this.busy) return;
		this.operationGeneration = (this.operationGeneration || 0) + 1;
		this.busy = true; this.operationMethod = 'verify'; this.paint();
		try {
			var progress = await this.request('job_status');
			if (progress.busy || progress.job && progress.job.status === 'running') {
				this.uncertain = true; this.message = { type: 'error', text: '后台操作仍在执行，请稍后重新检查。' }; return;
			}
			var saved = await this.request('get'), runtime = await this.readRuntimeStatus(true);
			if (!runtime.service || typeof runtime.service.running !== 'boolean') throw new Error('仍无法确认服务状态');
			if (!runtime.state || runtime.state.savedRevision !== saved.model.revision) throw new Error('读取期间配置再次变化，请重新检查');
			this.accept(saved); this.runtime = runtime; this.updateState(runtime.state || saved.state);
			if (runtime.service.running && (runtime.state.appliedRevision !== saved.model.revision || saved.model.groups.some(function(group) {
				return this.actualChoice(group.id) !== (group.id === 'Other' && group.selected === 'block' ? 'direct' : group.selected);
			}, this))) {
				this.uncertain = true; this.message = { type: 'error', text: '服务运行，但配置加载仍未确认，请稍后重新检查。' }; return;
			}
			this.uncertain = false; this.pendingJob = null;
			this.message = progress.job && progress.job.status === 'failed' ? { type: 'error', text: '上次操作失败：' + (progress.job.error && progress.job.error.message || '请检查运行状态') } : { type: 'success', text: '已重新读取实际状态。' };
		} catch (error) { this.uncertain = true; this.error(error); }
		finally { this.busy = false; this.paint(); }
	},

	changed: function() { this.dirty = true; this.message = null; this.paint(); },

	refreshRuntime: function(forceStatus) {
		var self = this;
		if (this.busy || document.hidden || !this.root.isConnected) return Promise.resolve();
		if (this.tab !== 'overview' && this.tab !== 'logs') return Promise.resolve();
		this.pendingPolls = this.pendingPolls || {};
		if (this.pendingPolls[this.tab]) return forceStatus ? this.pendingPolls[this.tab].then(function() { return self.refreshRuntime(true); }) : Promise.resolve();
		this.polling = true;
		var generation = this.operationGeneration || 0, tab = this.tab;
		var requestStatus = tab === 'overview' && (forceStatus || this.lastStatusAttempt == null || Date.now() - this.lastStatusAttempt >= 15000);
		if (requestStatus) this.lastStatusAttempt = Date.now(); // Throttle attempts after both successful and failed status requests.
		function valid() { return self.root.isConnected && !self.busy && self.tab === tab && generation === (self.operationGeneration || 0); }
		function settle(method, args) {
			return self.request(method, args).then(function(value) {
				if (!valid()) return;
				if (method === 'logs') { self.logs = (value.entries || []).slice(-20); self.logsError = null; }
				else if (method === 'traffic') self.traffic = value;
				else {
					self.runtime = value;
					var remote = self.runtime.state || {};
					if (self.readonly) self.revision = remote.savedRevision;
					else if (remote.savedRevision !== self.revision) self.conflict = true;
					self.updateState(remote);
					self.keepChecks(self.runtime.checks);
					self.runtimeError = null;
				}
				self.updateLive();
			}, function(error) {
				if (!valid()) return;
				if (method === 'logs') { self.logs = []; self.logsError = error.message; }
				else if (method === 'status') { self.runtime = null; self.runtimeError = error.message; }
				else self.traffic = { available: false, reason: error.message };
				self.updateLive();
			});
		}
		var requests = tab === 'logs' ? [settle('logs', [20])] : requestStatus ? [settle('status'), settle('traffic')] : [settle('traffic')];
		var operation = Promise.allSettled(requests).finally(function() {
			delete self.pendingPolls[tab]; self.polling = Object.keys(self.pendingPolls).length > 0;
		});
		this.pendingPolls[tab] = operation;
		return operation;
	},

	configurationLabel: function() {
		if (this.busy || this.activeJob) return ({ configure: '正在更新配置…', verify: '正在确认状态…', save: '正在保存配置…', apply: '正在应用配置…', refresh: '正在更新订阅…', check: '正在检查节点…', service: '正在切换服务…', rollback: '正在恢复配置…', import: '正在导入节点…' })[this.activeJob ? this.activeJob.method : this.operationMethod] || '正在执行，请稍候…';
		if (this.uncertain) return '操作结果未确认，请重新检查';
		if (this.serviceRunning() === false) return '服务已停止，修改将在下次启动使用';
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
			if (this.pendingGroup === group.id && this.busy) return '正在切换…';
		if (this.serviceRunning() === false) return '';
		if (group.id === 'Other' && group.selected === 'block') return '未匹配流量将阻断';
		var actual = this.actualChoice(group.id);
		if (!actual) return '实际出口未获取';
		if (actual !== group.selected) return '核心当前选择：' + model.label(this.draft, actual);
		return '';
	},
	updateLive: function() {
		// Polling only replaces status text. Keep focused selects, forms and scroll intact.
		var self = this, live = this.live || {}, running = this.serviceRunning(), traffic = this.traffic || {};
		if (live.service) live.service.textContent = running === true ? '运行中' : running === false ? '已停止' : '未知';
		if (live.traffic) {
			live.traffic.textContent = traffic.available ? '↑ ' + model.formatRate(traffic.upload) + '    ↓ ' + model.formatRate(traffic.download) : '不可用';
			live.traffic.setAttribute('title', traffic.available && traffic.sampledAt ? '采样于 ' + new Date(traffic.sampledAt * 1000).toLocaleTimeString() : traffic.reason || '等待流量采样');
		}
		if (live.health) live.health.textContent = model.stateLabel(this.state.healthy);
		if (live.config) live.config.textContent = this.configurationLabel();
		if (live.conflict) live.conflict.hidden = !this.conflict;
		if (live.runtimeError) { live.runtimeError.hidden = !this.runtimeError; live.runtimeError.textContent = this.runtimeError || ''; }
		if (live.lastError) { live.lastError.hidden = !this.state.lastError; live.lastError.textContent = this.lastErrorLabel(); }
		if (live.toggle) {
			var checking = this.uncertain || typeof running !== 'boolean';
			var label = this.busy && this.operationMethod === 'service' ? (this.serviceTarget ? '启动中…' : '停止中…') : checking ? '重新检查' : running ? '停止' : '启动';
			var needsNode = !checking && !running && this.draft.mode !== 'direct' && !this.proxyReady();
			live.toggle.textContent = label; live.toggle.setAttribute('aria-label', label); live.toggle.setAttribute('title', needsNode ? '请先添加并选择代理节点' : label);
			live.toggle.disabled = !!(this.busy || needsNode || (!checking && this.readonly));
		}
		(live.controls || []).forEach(function(control) { control.disabled = !!(self.busy || self.readonly || self.uncertain || self.conflict || typeof running !== 'boolean'); });
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
		if (this.readonly) tabs = [['overview', '运行状态'], ['logs', '日志']];
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
				click: function(event) { event.preventDefault(); self.tab = tab[0]; self.paint(); self.refreshRuntime(tab[0] === 'overview'); }
			}, [tab[1]])]);
		})));
		var checkJob = this.activeJob || this.pendingJob;
		if (checkJob && checkJob.method === 'check') {
			var progress = checkJob.progress || {}, currentNode = this.draft.nodes.find(function(n) { return n.id === progress.currentNodeId; });
			content.push(E('div', { 'class': 'ar-operation-status', role: 'status', 'aria-live': 'polite' }, [
				E('span', {}, [(this.cancelling ? '正在取消检测' : '正在串行检测') + ' · ' + (progress.completed || 0) + ' / ' + (progress.total || '…') +
					' · ' + (({ node: '单节点', subscription: '此订阅', selected: '所选节点', all: '全部来源（含手动）' })[progress.scope] || '正在确认范围') + (progress.retryFailed ? ' · 仅失败节点' : '') +
					' · 通过 ' + (progress.passed || 0) + ' · 失败 ' + (progress.failed || 0) + (currentNode ? ' · ' + currentNode.name : '')]),
				this.button('取消检测', '■', function() { return self.cancelCheck(); }, { duringCheck: true, recovery: true, disabled: this.cancelling })
			]));
		}
		content.push(this['render_' + this.tab]());
		this.live.config = E('span', { 'class': 'ar-config-state', role: 'status' }, [this.configurationLabel()]);
		content.push(E('div', { 'class': 'ar-operation-status' }, [this.live.config,
			this.uncertain ? this.button('重新检查', '↻', function() { return self.reconcile(); }, { text: true, readonly: true, recovery: true }) : ''
		]));

		domReplace(this.root, content);
	},

	reload: function() {
		var self = this;
		if (this.readonly) return this.refreshRuntime(true);
		if (this.dirty && !window.confirm('重新读取将丢弃尚未保存的编辑。继续？')) return;
		this.checks = {};
		return this.mutate('get', [], '已重新读取持久配置。').then(function() { return self.refreshRuntime(true); });
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
		if (this.readonly) {
			this.live.service = E('strong', {}, [running === true ? '运行中' : running === false ? '已停止' : '未知']);
			this.live.traffic = E('span', {}, [traffic.available ? '↑ ' + model.formatRate(traffic.upload) + '    ↓ ' + model.formatRate(traffic.download) : '不可用']);
			this.live.runtimeError = E('p', { 'class': 'alert-message warning', hidden: !this.runtimeError || undefined }, [this.runtimeError || '']);
			return this.card('运行状态', [this.field('代理服务', this.live.service), this.field('实时流量', this.live.traffic), this.live.runtimeError]);
		}
		var mode = this.select(this.pendingModel ? this.pendingModel.mode : this.draft.mode, [['rule', '规则分流'], ['global', '全局代理'], ['direct', '全部直连']]);
		this.live.controls = [mode];
		mode.disabled = this.busy || this.readonly || this.uncertain || this.conflict || typeof running !== 'boolean';
		mode.addEventListener('change', function() { self.changeMode(mode.value).catch(function(error) { self.error(error); }); });
		this.live.service = E('strong', {}, [running === true ? '运行中' : running === false ? '已停止' : '未知']);
		var checking = this.uncertain || typeof running !== 'boolean';
		var label = this.busy && this.operationMethod === 'service' ? (this.serviceTarget ? '启动中…' : '停止中…') : checking ? '重新检查' : running ? '停止' : '启动';
		var needsNode = !checking && !running && this.draft.mode !== 'direct' && !this.proxyReady();
		this.live.toggle = this.button(label, '', function() { return self.toggleService(); }, { text: true, readonly: checking, recovery: checking, disabled: needsNode });
		if (needsNode) this.live.toggle.setAttribute('title', '请先添加并选择代理节点');
		this.live.traffic = E('span', {}, [traffic.available ? '↑ ' + model.formatRate(traffic.upload) + '    ↓ ' + model.formatRate(traffic.download) : '不可用']);
		this.live.health = E('span', {}, [model.stateLabel(this.state.healthy)]);
		this.live.runtimeError = E('p', { 'class': 'alert-message warning', hidden: !this.runtimeError || undefined }, [this.runtimeError || '']);
		var basic = [this.field('代理服务', E('div', { 'class': 'ar-actions' }, [this.live.service, this.live.toggle])),
			this.field('实时流量', this.live.traffic), this.field('运行模式', mode), this.live.runtimeError];
		if (this.draft.mode === 'global') {
			var primary = this.draft.groups.find(function(g) { return g.id === 'Proxy'; });
			basic.push(this.field('代理节点', this.groupSelect(primary)));
		}
		var content = [this.card('运行与策略', basic)];
		if (this.draft.mode !== 'rule') return E('div', {}, content);
		var section = this.strategySection || 'groups';
		content.push(E('ul', { 'class': 'cbi-tabmenu', 'aria-label': '代理策略设置' }, [['groups', '策略组'], ['rules', '分流规则']].map(function(tab) {
			return E('li', { 'class': section === tab[0] ? 'cbi-tab' : 'cbi-tab-disabled' }, [E('a', { href: '#', 'aria-current': section === tab[0] ? 'page' : undefined,
				click: function(event) { event.preventDefault(); self.strategySection = tab[0]; self.paint(); }
			}, [tab[1]])]);
		})));
		content.push(section === 'rules' ? this.render_rules() : this.render_groups());
		return E('div', {}, content);
	},

	render_nodes: function() {
		var self = this, searchable = [], selected = this.selectedNodes || Object.create(null), eligible = Object.create(null);
		var locked = !!(this.busy || this.uncertain || this.readonly), blocked = this.dirty || this.conflict || this.state.appliedRevision == null || this.state.savedRevision !== this.state.appliedRevision;
		this.draft.nodes.forEach(function(raw) { var n = model.effectiveNode(self.draft, raw); if (n.enabled && !n.excluded) eligible[n.id] = true; });
		Object.keys(selected).forEach(function(id) { if (!eligible[id]) delete selected[id]; });
		this.selectedNodes = selected;
		var selectAll = this.input('', 'checkbox', { 'aria-label': '全选当前筛选结果中的可检测节点', disabled: locked || undefined });
		var selection = E('span', { 'class': 'ar-muted', role: 'status' }, []), boxes = [], visibleIds = [];
		var checkSelected = this.button('检查所选', '', function() { return self.checkSelected(); }, { text: true, disabled: blocked || !Object.keys(selected).length });
		function updateSelection() {
			var count = Object.keys(selected).length, visibleSelected = visibleIds.filter(function(id) { return selected[id]; }).length;
			selection.textContent = '已选 ' + count + ' 个节点（跨筛选保留）';
			selectAll.checked = visibleIds.length > 0 && visibleSelected === visibleIds.length;
			selectAll.indeterminate = visibleSelected > 0 && visibleSelected < visibleIds.length;
			selectAll.disabled = locked || !visibleIds.length;
			checkSelected.disabled = locked || !!blocked || !count;
			boxes.forEach(function(item) { item.box.checked = !!selected[item.id]; });
		}
		selectAll.addEventListener('change', function() {
			visibleIds.forEach(function(id) { if (selectAll.checked) selected[id] = true; else delete selected[id]; }); updateSelection();
		});
		var rows = this.draft.nodes.map(function(raw) {
			var n = model.effectiveNode(self.draft, raw), override = self.draft.overrides[raw.id];
			searchable.push({ id: n.id, name: n.name.toLowerCase(), source: raw.source || '@manual' });
			var source = raw.source && self.draft.subscriptions.filter(function(s) { return s.id === raw.source; })[0];
			var result = self.checks[n.id];
			var check = result && self.state.appliedRevision != null && result.checkedRevision === self.state.appliedRevision ? self.checkLabel(result) : null;
			var checkbox = self.input('', 'checkbox', { 'aria-label': '选择节点 ' + n.name, 'data-node-id': n.id, checked: selected[n.id] || undefined, disabled: locked || !eligible[n.id] || undefined });
			checkbox.addEventListener('change', function() { if (checkbox.checked) selected[n.id] = true; else delete selected[n.id]; updateSelection(); });
			boxes.push({ id: n.id, box: checkbox });
			var current = (self.activeJob || self.pendingJob || {}).progress;
			return [checkbox, E('strong', {}, [n.name]),
				n.type.toUpperCase(), source ? source.name + (override ? ' · 本地覆盖' : '') : '手动',
				n.excluded ? '已排除' : n.enabled ? '启用' : '停用',
				E('div', {}, [current && current.currentNodeId === n.id ? E('span', {}, ['正在检测… ']) : '', check || '未检查',
					check && result.time ? E('small', { 'class': 'ar-muted' }, [' · ' + new Date(result.time * 1000).toLocaleString()]) : '']),
				E('div', { 'class': 'ar-actions' }, [
					self.button('编辑节点', '✎', function() { self.editNode(raw); }),
					self.button('检查此节点', '◉', function() { return self.checkNode(n.id); }, { disabled: self.dirty || self.conflict || self.state.appliedRevision == null || self.state.savedRevision !== self.state.appliedRevision || n.excluded || !n.enabled })
				])];
		});
		var list = this.table([selectAll, '名称', '协议', '来源', '状态', '节点检查', '操作'], rows);
		var search = this.input(this.nodeQuery || '', 'search', { placeholder: '搜索节点名称', 'aria-label': '搜索节点名称' });
		var sources = [['', '全部来源'], ['@manual', '手动节点']].concat(this.draft.subscriptions.map(function(s) { return [s.id, s.name]; }));
		var sourceFilter = this.select(this.nodeSource || '', sources); sourceFilter.setAttribute('aria-label', '节点来源');
		var count = E('p', { 'class': 'cbi-section-descr' }, []);
		function filter() {
			self.nodeQuery = search.value; self.nodeSource = sourceFilter.value;
			var query = search.value.trim().toLowerCase(), visible = 0, elements = list.children[0].children[1].children;
			visibleIds = [];
			searchable.forEach(function(node, i) {
				var matches = node.name.indexOf(query) !== -1 && (!sourceFilter.value || node.source === sourceFilter.value);
				elements[i].hidden = !matches; if (matches) visible++;
				if (matches && eligible[node.id]) visibleIds.push(node.id);
			});
			count.textContent = visible + ' / ' + rows.length + ' 个节点';
			updateSelection();
		}
		// A removed subscription must not leave a stale filter selecting no source.
		if (!sources.some(function(s) { return s[0] === self.nodeSource; })) { sourceFilter.value = ''; this.nodeSource = ''; }
		search.addEventListener('input', filter); sourceFilter.addEventListener('change', filter); filter();
		return this.card('节点', [E('div', { 'class': 'ar-toolbar' }, [E('div', { 'class': 'ar-actions ar-filters' }, [search, sourceFilter]),
			E('div', { 'class': 'ar-actions' }, [this.button('导入节点', '⇧', function() {
				self.showImport('导入为手动节点', function(content) { return self.activateMutation('import', [self.revision, content, true], '节点已导入并生效。'); });
			}, { text: true, disabled: this.dirty || this.conflict }), this.button('添加节点', '+', function() { self.editNode(); }, { text: true, primary: true })])]),
			E('div', { 'class': 'ar-toolbar' }, [E('div', { 'class': 'ar-actions' }, [checkSelected,
				this.button('扫描全部', '', function() { return self.checkAll(false); }, { text: true, disabled: blocked || !Object.keys(eligible).length }),
				this.button('仅重试失败', '', function() { return self.checkAll(true); }, { text: true, disabled: blocked || !Object.keys(eligible).some(function(id) { var r = self.checks[id]; return r && r.checkedRevision === self.state.appliedRevision && r.healthy === 'failed'; }) })]), selection]),
			rows.length ? list : this.empty('暂无节点，请添加节点或订阅。'), count,
			E('p', { 'class': 'ar-muted' }, ['表头只选择当前筛选结果；检查所选包含筛选外已选节点。扫描全部及仅重试失败覆盖所有来源（含手动），均跳过停用、排除节点；重试只检查当前配置的失败结果。检测保持当前出口。'])]);
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
		var fieldset;
		async function submit(edit) {
			fieldset.disabled = true; errorBox.hidden = true;
			try {
				var candidate = model.clone(self.draft);
				if (edit(candidate) === false) return;
				await self.configureModel(candidate, '配置已更新。'); ui.hideModal();
			} catch (error) { errorBox.hidden = false; errorBox.textContent = error.message; }
			finally { fieldset.disabled = false; }
		}
		var extra = (actions || []).map(function(action) { return self.button(action.label, '', function() { return submit(action.run); }, { text: true, style: action.style, disabled: action.disabled }); });
		fieldset = E('fieldset', { 'class': 'ar-modal-fields' }, [E('div', { 'class': 'ar-form' }, fields), errorBox,
			E('div', { 'class': 'ar-modal-actions' }, [E('div', { 'class': 'ar-actions' }, extra), E('div', { 'class': 'ar-actions' }, [
				this.button('取消', '', function() { ui.hideModal(); }, { text: true }),
				this.button('确定', '', function() { return submit(commit); }, { text: true, primary: true })
			])])]);
		ui.showModal(title, [fieldset]);
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
		var actions = raw ? raw.source ? self.draft.overrides[raw.id] ? [{ label: '恢复订阅原始值', run: function(next) {
			if (!window.confirm('清除此节点的本地覆盖？')) return false;
			delete next.overrides[raw.id];
		} }] : [] : [{ label: '删除节点', style: 'cbi-button-remove', run: function(next) {
			if (!window.confirm('删除节点“' + n.name + '”？')) return false;
			model.removeNode(next, raw.id);
		} }] : [];
		this.modal(raw ? '编辑节点' : '添加 VMess 节点', fields, function(next) {
			if (!name.value.trim() || !server.value.trim() || !uuid.value.trim()) throw new Error('名称、服务器和 UUID 必填');
			if (!model.validPort(port.value)) throw new Error('端口须为 1–65535 的整数');
			if (!/^\d+$/.test(alterId.value) || Number(alterId.value) > 65535) throw new Error('alterId 须为 0–65535 的整数');
			var tlsConfig = { enabled: tls.checked }, wsConfig = { type: 'ws', path: path.value || '/' };
			if (sni.value.trim()) tlsConfig.serverName = sni.value.trim();
			if (host.value.trim()) wsConfig.host = host.value.trim();
			var values = { server: server.value.trim(), port: Number(port.value), uuid: uuid.value.trim(), security: security.value, alterId: Number(alterId.value),
				tls: tlsConfig, transport: transport.value ? wsConfig : null };
			if (raw && raw.source) {
				var previous = next.overrides[raw.id] || {};
				if (excluded.checked && !n.excluded && model.references(next, raw.id).length) throw new Error('请先移除该节点的策略组、规则和默认出口引用');
				next.overrides[raw.id] = Object.assign({}, previous, { name: name.value.trim(), patch: values, excluded: excluded.checked });
			}
			else {
				var item = Object.assign({}, raw || { id: model.id('n'), type: 'vmess', source: null }, values, { name: name.value.trim(), enabled: enabled.checked });
				if (!item.transport) delete item.transport;
				if (raw) next.nodes[next.nodes.findIndex(function(n) { return n.id === raw.id; })] = item;
				else next.nodes.push(item);
			}
		}, actions);
	},

	checkNode: function(id) {
		return this.startCheck(id, '');
	},
	checkSubscription: function(id) {
		return this.startCheck('', id);
	},
	checkSelected: function() {
		var ids = Object.keys(this.selectedNodes || {});
		if (!ids.length) throw new Error('请先选择要检查的节点');
		return this.startCheck('', '', ids, 'selected', false);
	},
	checkAll: function(retryFailed) {
		return this.startCheck('', '', [], 'all', retryFailed === true);
	},
	checkSummary: function(result) {
		var scope = ({ node: '单节点', subscription: '此订阅', selected: '所选节点', all: '全部来源（含手动）' })[result.scope] || '';
		return (result.cancelled ? '检测已取消' : '检测完成') + (scope ? ' · ' + scope : '') + (result.retryFailed ? ' · 仅失败节点' : '') + ' · ' + (result.completed || 0) + ' / ' + (result.total || 1) +
			' · 通过 ' + (result.passed || 0) + ' · 失败 ' + (result.failed || 0) + ' · 跳过停用/排除 ' + (result.skipped || 0) + '；当前出口保持不变。';
	},
	acceptChecks: function(result) {
		var checks = Object.assign({}, this.checks, result.checks || {});
		if (result.nodeId) checks[result.nodeId] = result;
		this.keepChecks(checks); this.paint();
	},
	startCheck: function(nodeId, subscriptionId, nodeIds, scope, retryFailed) {
		var self = this;
		if (this.dirty || this.conflict || this.state.savedRevision !== this.state.appliedRevision || this.state.appliedRevision == null) throw new Error('请先启动服务并确认当前配置已生效，再执行节点检查');
		this.cancelling = false;
		var args = scope ? [nodeId, subscriptionId, nodeIds, scope, retryFailed] : [nodeId, subscriptionId];
		return this.mutate('check', args, function(result) { return self.checkSummary(result); }).then(function(result) { self.acceptChecks(result); return result; });
	},
	observeCheck: function(job) {
		var self = this;
		this.busy = true; this.operationMethod = 'check'; this.cancelling = false;
		this.acceptChecks({ checks: job.checks || (job.result || {}).checks });
		return this.waitJob(job).then(function(result) { self.accept(result); self.acceptChecks(result); self.message = { type: 'success', text: self.checkSummary(result) }; })
			.catch(function(error) { self.uncertain = true; self.error(error); })
			.finally(function() { self.busy = false; self.paint(); });
	},
	cancelCheck: function() {
		var self = this, job = this.activeJob || this.pendingJob;
		if (this.readonly || this.cancelling || !job || job.method !== 'check') return Promise.resolve();
		this.cancelling = true; this.paint();
		return this.request('cancel_check', [job.id]).catch(function(error) { self.cancelling = false; self.paint(); throw error; });
	},
	chooseNode: function(group, id) {
		var current = this.draft.groups.find(function(g) { return g.id === group; });
		if (!current) return Promise.reject(new Error('策略组不存在'));
		if (current.selected === id) return Promise.resolve();
		this.pendingGroup = group;
		return this.changeConfig(function(next) { next.groups.find(function(g) { return g.id === group; }).selected = id; }, '出口已切换。');
	},
	groupSelect: function(group) {
		var self = this, pending = this.pendingModel && this.pendingModel.groups.find(function(g) { return g.id === group.id; });
		var primary = group.id === 'Proxy', choices = this.outbounds({ nodesOnly: primary, follow: !primary, block: group.id === 'Other' });
		var value = pending ? pending.selected : group.selected;
		if (primary && !choices.some(function(choice) { return choice[0] === value; })) { choices.unshift(['', '请选择节点']); value = ''; }
		var select = this.select(value, choices);
		select.setAttribute('aria-label', group.name + '的出口');
		select.disabled = this.busy || this.readonly || this.uncertain || this.conflict || typeof this.serviceRunning() !== 'boolean';
		select.addEventListener('change', function() { self.chooseNode(group.id, select.value).catch(function(error) { self.error(error); }); });
		this.live.controls = this.live.controls || []; this.live.controls.push(select);
		return select;
	},

	render_subscriptions: function() {
		var self = this;
		var rows = this.draft.subscriptions.map(function(s) {
			var count = self.draft.nodes.filter(function(n) { return n.source === s.id; }).length;
			return [s.name, s.enabled ? '启用' : '停用', String(count), s.intervalHours ? '每 ' + s.intervalHours + ' 小时' : '手动更新',
				E('div', {}, [E('span', {}, [typeof s.lastUpdate === 'number' ? new Date(s.lastUpdate * 1000).toLocaleString() : s.lastUpdate || '从未更新']), s.lastError ? E('small', { 'class': 'ar-error ar-block' }, [s.lastError]) : '']),
				E('div', { 'class': 'ar-actions' }, [self.button('编辑订阅', '✎', function() { self.editSubscription(s); }),
					self.button('手动更新订阅', '↻', function() { return self.updateSubscription(s); }, { disabled: self.dirty || self.conflict || !s.enabled }),
					self.button('检测订阅节点', '◉', function() { return self.checkSubscription(s.id); }, { disabled: self.dirty || self.conflict || self.state.appliedRevision == null || self.state.savedRevision !== self.state.appliedRevision || !count }),
					self.button('从本地内容更新', '⇧', function() { self.importSubscription(s); }, { disabled: self.dirty || self.conflict || !s.enabled })])];
		});
		return this.card('订阅来源', [E('div', { 'class': 'ar-toolbar' }, [E('p', { 'class': 'ar-muted' }, ['订阅地址仅用于本机管理服务抓取，不发送公共转换服务。失败时保留旧节点。']),
			this.button('添加订阅', '+', function() { self.editSubscription(); }, { text: true, primary: true })]),
			rows.length ? this.table(['名称', '状态', '节点数', '更新计划', '最近结果', '操作'], rows) : this.empty('暂无订阅，请先添加订阅，再更新节点。'),
			E('p', { 'class': 'ar-muted' }, ['检测已加载、已启用且未排除的节点，逐个发送小型 HTTPS 请求；显示代理请求延迟，不自动切换出口。订阅只更新节点，不导入策略组和规则。'])]);
	},
	editSubscription: function(original) {
		var self = this, s = original || { name: '', url: '', enabled: true, intervalHours: 0, allowHttp: false };
		var name = this.input(s.name), url = this.input(s.url, 'password', { autocomplete: 'new-password' });
		var enabled = this.input('', 'checkbox', { checked: s.enabled || undefined }), interval = this.input(s.intervalHours, 'number', { min: 0, max: 168 });
		var allowHttp = this.input('', 'checkbox', { checked: s.allowHttp === true || undefined });
		var actions = original ? [{ label: '删除订阅', style: 'cbi-button-remove', run: function(next) {
			if (!window.confirm('删除订阅“' + s.name + '”及所属节点和本地覆盖？')) return false;
			model.removeSubscription(next, s.id);
		} }] : [];
		this.modal(original ? '编辑订阅' : '添加订阅', [this.field('名称', name), this.field('订阅地址（敏感）', url), this.field('启用订阅', enabled),
			this.field('更新间隔（小时）', interval, '0 表示仅手动更新；范围为 1–168 小时。'),
			E('details', { 'class': 'ar-details' }, [E('summary', {}, ['更多选项']), this.field('允许此订阅使用未加密HTTP', allowHttp, '仅对此来源生效，HTTP 不加密传输。')])], function(next) {
			var address = url.value.trim(), https = /^https:\/\/[^\s]+$/i.test(address), http = /^http:\/\/[^\s]+$/i.test(address);
			if (!name.value.trim() || !(https || (http && allowHttp.checked))) throw new Error('名称必填；默认要求 HTTPS，现有 HTTP 来源须显式勾选此订阅的未加密 HTTP 许可');
			if (!/^\d+$/.test(interval.value) || Number(interval.value) > 168) throw new Error('更新间隔须为 0–168 的整数');
			var item = Object.assign({}, s, { id: s.id || model.id('s'), name: name.value.trim(), url: address, enabled: enabled.checked, intervalHours: Number(interval.value), allowHttp: allowHttp.checked });
			if (original) next.subscriptions[next.subscriptions.findIndex(function(item) { return item.id === original.id; })] = item;
			else next.subscriptions.push(item);
		}, actions);
	},
	updateSubscription: function(s, content) {
		return this.activateMutation('refresh', [this.revision, s.id, content || '', true], '订阅已更新并生效。');
	},
	importSubscription: function(s) {
		var self = this;
		this.showImport('从本地订阅内容更新', function(content) { return self.updateSubscription(s, content); });
	},
	showImport: function(title, commit) {
		var self = this, area = E('textarea', { rows: 10, 'class': 'cbi-input-textarea', autocomplete: 'off', spellcheck: 'false', maxlength: 131072 });
		var errorBox = E('p', { 'class': 'ar-alert ar-error', hidden: '' });
		var cancel = this.button('取消', '', function() { ui.hideModal(); }, { text: true });
		var submit = this.button('导入', '', function() {
			if (!area.value.trim()) { errorBox.hidden = false; errorBox.textContent = '请先粘贴导入内容'; return; }
			submit.disabled = area.disabled = cancel.disabled = true;
			return Promise.resolve().then(function() { return commit(area.value); }).then(function() { ui.hideModal(); }).catch(function(error) {
				errorBox.hidden = false; errorBox.textContent = error.message;
			}).finally(function() { submit.disabled = !!self.uncertain; area.disabled = cancel.disabled = false; });
		}, { text: true, primary: true });
		ui.showModal(title, [E('p', {}, ['支持 VMess 链接、Base64 列表及受限 Clash 内容。仅导入节点，失败保留原有数据。']), this.field('订阅或节点内容', area), errorBox,
			E('div', { 'class': 'right ar-actions' }, [cancel, submit])]);
	},

	outbounds: function(options) {
		options = options || {};
		var list = options.nodesOnly ? [] : [['direct', '直连']];
		if (options.block) list.push(['block', '阻断']);
		if (options.groups) this.draft.groups.forEach(function(g) { list.push([g.id, g.name + '（策略组）']); });
		if (options.follow) list.push(['Proxy', '跟随代理']);
		var self = this;
		this.draft.nodes.forEach(function(raw) { var n = model.effectiveNode(self.draft, raw); if (n.enabled && !n.excluded) list.push([n.id, n.name]); });
		return list;
	},
	render_groups: function() {
		var self = this, presets = this.capabilities.policyPresets || [];
		var groups = this.draft.groups.filter(function(g) { return g.id !== 'Other' && g.id !== 'Proxy'; });
		groups.unshift(this.draft.groups.find(function(g) { return g.id === 'Proxy'; }));
		groups.push(this.draft.groups.find(function(g) { return g.id === 'Other'; }));
		var rows = groups.filter(Boolean).map(function(g) {
			var actual = E('small', { 'class': 'ar-muted ar-block', 'data-group-status': g.id }, [self.groupStatus(g)]);
			self.live.groups[g.id] = actual;
			var preset = presets.find(function(p) { return p.id === g.id; });
			var count = self.draft.rules.filter(function(r) { return r.outbound === g.id && r.enabled; }).length;
			var description = preset ? preset.description : count ? count + ' 条自定义规则' : '尚无匹配规则';
			return [E('strong', { title: description }, [g.name]),
				E('div', {}, [self.groupSelect(g), actual]), self.button('编辑策略组', '✎', function() { self.editGroup(g); })];
		});
		var table = this.table(['策略组', '出口', '操作'], rows); table.setAttribute('class', 'ar-table-scroll ar-group-table');
		return this.card('策略组', [table,
			E('div', { 'class': 'ar-toolbar ar-toolbar-end' }, [
				this.button('添加服务策略', '+', function() { self.addService(); }, { text: true, disabled: this.draft.groups.length >= 16 || !presets.some(function(p) { return p.id !== 'Other' && p.id !== 'Proxy' && !self.draft.groups.some(function(g) { return g.id === p.id; }); }) }),
				this.button('添加自定义策略', '+', function() { self.editGroup(); }, { text: true, disabled: this.draft.groups.length >= 16 })])]);
	},
	addService: function() {
		var self = this, available = (this.capabilities.policyPresets || []).filter(function(p) { return p.id !== 'Proxy' && p.id !== 'Other' && !self.draft.groups.some(function(g) { return g.id === p.id; }); });
		if (!available.length) return;
		var selection = this.select(available[0].id, available.map(function(p) { return [p.id, p.name]; }));
		this.modal('添加服务策略', [this.field('服务', selection), E('p', { 'class': 'cbi-section-descr' }, ['同时启用对应的内置域名规则。'])], function(next) {
			var preset = available.find(function(p) { return p.id === selection.value; });
			if (next.groups.length >= 16 || next.groups.some(function(g) { return g.id === preset.id; })) throw new Error('策略组已存在或数量已满');
			next.groups.splice(next.groups.findIndex(function(g) { return g.id === 'Other'; }), 0, { id: preset.id, name: preset.name, selected: preset.id === 'Domestic' ? 'direct' : 'Proxy' });
		});
	},

	editGroup: function(original) {
		var self = this, primary = original && original.id === 'Proxy', name = this.input(original ? original.name : ''), choices = this.outbounds({ nodesOnly: primary, follow: !primary, block: original && original.id === 'Other' });
		if (primary) choices.unshift(['', '请选择节点']);
		var selected = this.select(original ? original.selected : 'Proxy', choices);
		var fields = [this.field('名称', name), this.field('出口', selected)];
		var preset = original && (this.capabilities.policyPresets || []).find(function(p) { return p.id === original.id; });
		if (preset) fields.push(E('p', { 'class': 'cbi-section-descr' }, [preset.description]));
		var actions = original && original.id !== 'Proxy' && original.id !== 'Other' ? [{ label: '删除策略组', run: function(next) { return self.removeGroup(original, next); }, style: 'cbi-button-remove' }] : [];
		this.modal(original ? '编辑策略组' : '添加策略组', fields, function(next) {
			if (primary && !selected.value) throw new Error('请选择代理节点');
			var value = name.value.trim();
			if (!value || value.length > 128) throw new Error('名称须为 1–128 个字符');
			if (original) { var group = next.groups.find(function(g) { return g.id === original.id; }); group.name = value; group.selected = selected.value; }
			else {
				if (next.groups.length >= 16) throw new Error('最多支持 16 个策略组');
				next.groups.splice(next.groups.findIndex(function(g) { return g.id === 'Other'; }), 0, { id: model.id('g'), name: value, selected: selected.value });
			}
		}, actions);
	},
	removeGroup: function(group, next) {
		next = next || this.draft;
		if (group.id === 'Proxy' || group.id === 'Other') throw new Error('必须保留代理和 Other 策略组');
		var refs = model.references(next, group.id);
		if (refs.length) throw new Error('请先处理引用：' + refs.join('、'));
		if (!window.confirm('删除策略组“' + group.name + '”？')) return false;
		next.groups = next.groups.filter(function(g) { return g.id !== group.id; });
		return true;
	},
	ruleLimit: function(name, fallback) {
		var value = this.capabilities && this.capabilities.limits && Number(this.capabilities.limits[name]);
		return Number.isInteger(value) && value > 0 ? value : fallback;
	},
	ruleValues: function(rule) {
		if (Array.isArray(rule.values)) return rule.values.map(function(value) { return String(value); });
		return rule.value == null ? [] : [String(rule.value)];
	},
	ruleValueSummary: function(rule) {
		var values = this.ruleValues(rule), visible = values.slice(0, 3).map(function(value) {
			return value.length > 64 ? value.slice(0, 61) + '…' : value;
		});
		return E('span', { title: values.join('\n') }, [visible.join('、') + (values.length > visible.length ? '（共 ' + values.length + ' 项）' : '')]);
	},

	render_rules: function() {
		var self = this, ruleLimit = this.ruleLimit('rules', 128);
		var rows = this.draft.rules.map(function(r, i) {
			var values = self.ruleValues(r);
			return [String(i + 1), r.enabled ? '启用' : '停用', ({ domain: '域名', suffix: '域名后缀', ip: 'IPv4', cidr: 'IPv4 网段', regex: '正则表达式' })[r.type] || r.type,
				self.ruleValueSummary(r), model.label(self.draft, r.outbound), E('div', { 'class': 'ar-actions' }, [
					self.button('编辑规则', '✎', function() { self.editRule(r); }),
					self.button('提高优先级', '↑', function() { return self.moveRule(i, -1); }, { disabled: i === 0 }),
					self.button('降低优先级', '↓', function() { return self.moveRule(i, 1); }, { disabled: i === self.draft.rules.length - 1 }),
					self.button('删除规则', '×', function() { if (window.confirm('删除规则“' + (values[0] || '') + (values.length > 1 ? '”等 ' + values.length + ' 项？' : '”？'))) { return self.changeConfig(function(next) { next.rules.splice(i, 1); }, '规则已删除。'); } })])];
		});
		return this.card('分流规则', [this.draft.mode !== 'rule' ? E('p', { 'class': 'alert-message notice' }, ['当前模式不使用分流规则，切换到规则分流后生效。']) : '',
			E('div', { 'class': 'ar-toolbar' }, [E('p', { 'class': 'ar-muted' }, ['自定义规则优先，其后匹配服务规则、代理，最后进入 Other。已用 ' + this.draft.rules.length + ' / ' + ruleLimit + ' 条。']),
				this.button('添加规则', '+', function() { self.editRule(); }, { text: true, primary: true, disabled: this.draft.rules.length >= ruleLimit })]),
			rows.length ? this.table(['优先级', '状态', '匹配类型', '匹配值', '出口', '操作'], rows) : this.empty('暂无自定义规则，当前使用内置服务规则和 Other 兜底。'),
			E('p', { 'class': 'ar-muted' }, ['支持域名、域名后缀、正则表达式和 IPv4 地址/网段；每行一个匹配值。'])]);
	},
	moveRule: function(index, delta) {
		var other = index + delta;
		if (other < 0 || other >= this.draft.rules.length) return Promise.resolve();
		return this.changeConfig(function(next) { var moved = next.rules.splice(index, 1)[0]; next.rules.splice(other, 0, moved); }, '规则顺序已更新。');
	},

	editRule: function(original) {
		var self = this, r = original || { type: 'suffix', values: [], outbound: 'Proxy', enabled: true };
		var type = this.select(r.type, [['domain', '精确域名'], ['suffix', '域名后缀'], ['regex', '正则表达式'], ['ip', 'IPv4 地址'], ['cidr', 'IPv4 CIDR 网段']]);
		var valueLimit = this.ruleLimit('ruleValues', 128), ruleLimit = this.ruleLimit('rules', 128);
		var values = E('textarea', { rows: 8, 'class': 'cbi-input-textarea', autocomplete: 'off', spellcheck: 'false', maxlength: 131072 }, [this.ruleValues(r).join('\n')]);
		values.value = this.ruleValues(r).join('\n');
		var outbound = this.select(r.outbound, this.outbounds({ groups: true, block: true })), enabled = this.input('', 'checkbox', { checked: r.enabled || undefined });
		this.modal(original ? '编辑规则' : '添加规则', [this.field('匹配类型', type), this.field('匹配值', values, '每行一个值；空行会忽略，重复值只保留第一次。'), this.field('出口', outbound), this.field('启用规则', enabled)], function(next) {
			var normalized = [];
			values.value.split(/\r\n|\n|\r/).forEach(function(value) {
				value = value.trim();
				if (value && normalized.indexOf(value) < 0) normalized.push(value);
			});
			if (!normalized.length) throw new Error('匹配值不能为空');
			if (normalized.length > valueLimit) throw new Error('每条规则最多支持 ' + valueLimit + ' 个匹配值');
			if (!original && next.rules.length >= ruleLimit) throw new Error('最多支持 ' + ruleLimit + ' 条自定义规则');
			var item = { id: r.id || model.id('r'), type: type.value, values: normalized, outbound: outbound.value, enabled: enabled.checked };
			if (original) next.rules[next.rules.findIndex(function(item) { return item.id === original.id; })] = item;
			else next.rules.push(item);
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
