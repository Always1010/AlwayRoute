'use strict';

// TEST ONLY: browser-native DOM and explicit simulated rpcd. Never shipped in LuCI.
(function() {
  var clone = function(value) { return JSON.parse(JSON.stringify(value)); };
  var calls = [], intervals = new Map(), scenario = 'normal', app, saved, state, observed, serviceRunning, job, events, checks;
  var errors = document.getElementById('preview-error');
  window.addEventListener('error', function(event) { errors.textContent += event.message + '\n'; });
  window.addEventListener('unhandledrejection', function(event) { errors.textContent += String(event.reason && event.reason.stack || event.reason) + '\n'; });

  // Follows the fixed LuCI dom.attr semantics: null is omitted, functions are events,
  // all other values become attributes. Production calls always pass children arrays.
  function E(tag, attrs, children) {
    var element = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function(key) {
      var value = attrs[key];
      if (value == null) return;
      if (typeof value === 'function') element.addEventListener(key, value);
      else element.setAttribute(key, typeof value === 'object' ? JSON.stringify(value) : String(value));
    });
    (Array.isArray(children) ? children : children == null ? [] : [children]).forEach(function(child) {
      element.appendChild(child instanceof Node ? child : document.createTextNode(String(child)));
    });
    return element;
  }

  class BaseClass {
    constructor() { if (typeof this.__init__ === 'function') this.__init__(); }
    static extend(properties) { class Child extends this {} Object.assign(Child.prototype, properties); return Child; }
    static isSubclass(value) { return typeof value === 'function' && value.prototype instanceof this; }
  }
  var poll = {
    add: function(fn, seconds) { if (!intervals.has(fn)) intervals.set(fn, window.setInterval(function() { Promise.resolve(fn()).catch(report); }, seconds * 1000)); },
    remove: function(fn) { window.clearInterval(intervals.get(fn)); intervals.delete(fn); }
  };
  var modal = null, previousFocus = null;
  var ui = {
    showModal: function(title, children) {
      ui.hideModal(); previousFocus = document.activeElement;
      var panel = E('section', { 'class': 'preview-modal', role: 'dialog', 'aria-modal': 'true', 'aria-label': title }, [E('h2', {}, [title])].concat(children));
      modal = E('div', { 'class': 'preview-overlay' }, [panel]); document.body.appendChild(modal);
      var first = modal.querySelector('input,select,textarea,button'); if (first) first.focus();
    },
    hideModal: function() { if (modal) { modal.remove(); modal = null; if (previousFocus) previousFocus.focus(); } }
  };
  document.addEventListener('keydown', function(event) {
    if (!modal) return;
    if (event.key === 'Escape') { ui.hideModal(); return; }
    if (event.key === 'Tab') {
      var controls = Array.from(modal.querySelectorAll('button,input,select,textarea')).filter(function(e) { return !e.disabled; });
      if (!controls.length) return;
      var first = controls[0], last = controls[controls.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    }
  });
  var L = { resource: function() { return 'data:text/css,'; }, hasViewPermission: function() { return true; } };
  class View extends BaseClass {
    __init__() {
      this.ready = Promise.resolve().then(this.load.bind(this)).then(this.render.bind(this)).then(function(nodes) {
        document.getElementById('view').replaceChildren(nodes);
        document.getElementById('preview-status').textContent = '生产模块已通过 Class 契约加载';
      });
      this.ready.catch(report);
    }
  }
  function report(error) { errors.textContent += String(error && error.stack || error) + '\n'; }
  function fixture() {
    saved = { schema: 1, revision: 4, mode: 'rule', defaultOutbound: 'Proxy', nodes: [
      { id: 'manual_demo', name: '东京 · 手动 VMess', type: 'vmess', enabled: true, source: null, server: 'tokyo.example.invalid', port: 443, uuid: '00000000-0000-4000-8000-000000000000', security: 'auto', alterId: 0, tls: { enabled: true, serverName: 'example.invalid' } },
      { id: 's_demo_sample', name: '订阅 · VMess WebSocket', type: 'vmess', enabled: true, source: 'demo', sourceKey: 'sample', server: 'subscription.example.invalid', port: 443, uuid: '00000000-0000-4000-8000-000000000001', security: 'auto', alterId: 0, tls: { enabled: true }, transport: { type: 'ws', path: '/demo' } }
    ], subscriptions: [{ id: 'demo', name: '脱敏订阅样例', url: 'https://subscription.example.invalid/redacted', enabled: true, intervalHours: 24, lastUpdate: Math.floor(Date.now() / 1000) - 3600 }],
      overrides: { s_demo_sample: { name: '香港 · 订阅本地名称' } },
      groups: [{ id: 'Proxy', name: '代理', selected: 'manual_demo' }, { id: 'OpenAI', name: 'OpenAI', selected: 'Proxy' }, { id: 'Netflix', name: 'Netflix', selected: 'Proxy' }, { id: 'Disney', name: 'Disney+', selected: 'direct' }],
      rules: [{ id: 'demo_rule1', enabled: true, type: 'suffix', value: 'example.com', outbound: 'Proxy' }, { id: 'demo_rule2', enabled: true, type: 'cidr', value: '192.0.2.0/24', outbound: 'direct' }, { id: 'demo_rule3', enabled: false, type: 'domain', value: 'blocked.example.invalid', outbound: 'block' }] };
    state = { savedRevision: 4, appliedRevision: 4, healthy: 'unverified' };
    observed = clone(saved.groups); serviceRunning = true; job = null; calls.length = 0; checks = {};
    events = [{ time: '预览样例', level: 'info', message: '这里只显示脱敏管理事件；不代表任何设备操作成功。' }];
  }
  function result() { return { ok: true, model: clone(saved), state: clone(state) }; }
  function fail(code, message) { return { ok: false, error: { code: code, message: message } }; }
  function persist(next) { saved = clone(next); saved.revision++; state.savedRevision = saved.revision; return result(); }
  function startJob(method, args) {
    job = { id: 'preview_' + Date.now(), status: 'running', method: method, doneAt: Date.now() + 750, args: clone(args) };
    return { ok: true, job: { id: job.id, status: job.status, method: method } };
  }
  function finishJob() {
    if (!job || job.status !== 'running' || Date.now() < job.doneAt) return;
    if (scenario === 'job-failed') { job.status = 'failed'; job.error = { code: 'PREVIEW_JOB_FAILED', message: '测试场景：后台任务失败，未模拟成功。' }; return; }
    if (job.method === 'check') { job.result = { ok: true, nodeId: job.args.nodeId, available: true, delay: 42, healthy: 'passed', checkedRevision: state.appliedRevision }; checks[job.args.nodeId] = clone(job.result); }
    if (job.method === 'apply' || job.method === 'rollback') { state.appliedRevision = saved.revision; observed = clone(saved.groups); state.healthy = 'unverified'; }
    if (job.method === 'refresh') { saved.subscriptions.find(function(s) { return s.id === job.args.subscriptionId; }).lastUpdate = Math.floor(Date.now() / 1000); saved.revision++; state.savedRevision = saved.revision; }
    if (job.method === 'service') serviceRunning = job.args.action === 'start';
    job.status = 'succeeded'; job.state = clone(state);
    events.push({ time: '预览样例', level: 'info', message: '模拟任务完成：' + job.method });
  }
  function dispatch(method, args) {
    calls.push({ method: method, argumentNames: Object.keys(args) }); if (calls.length > 100) calls.shift();
    if (method === 'job_status') { finishJob(); return { ok: true, busy: !!job && job.status === 'running', job: job ? clone(job) : null }; }
    if (method === 'capabilities') return { ok: true, schema: 1, protocols: ['vmess'], subscriptionFormats: ['vmess-uri', 'base64-vmess-list', 'clash-json', 'clash-yaml-block-subset'], forwarding: 'unverified' };
    if (method === 'get') return result();
    if (method === 'status') return { ok: true, state: clone(state), checks: clone(checks), service: { running: serviceRunning }, core: { available: scenario !== 'unavailable', groups: scenario === 'unavailable' ? null : Object.fromEntries(observed.map(function(g) { return [g.id, { now: g.selected }]; })) }, forwarding: { scope: 'preview-only', available: false, dns: 'unverified', udp: 'unverified', ipv6: 'unverified' } };
    if (method === 'traffic') return scenario === 'unavailable' ? { ok: true, available: false, upload: null, download: null, reason: '测试场景：核心流量不可用' } : { ok: true, available: true, upload: 18432, download: 345678, unit: 'bytes/s', reason: '脱敏模拟数据，仅用于本地预览' };
    if (method === 'logs') return { ok: true, entries: clone(events.slice(-20)) };
    if (method === 'export') { var m = clone(saved); if (!args.includeSecrets) { m.nodes.forEach(function(n) { n.uuid = '[redacted]'; }); m.subscriptions.forEach(function(s) { s.url = 'https://redacted.invalid/'; }); } return { ok: true, model: m, redacted: !args.includeSecrets }; }
    if (job && job.status === 'running') return fail('BUSY', '测试场景：后台任务仍在执行');
    if (scenario === 'conflict') return fail('REVISION_CONFLICT', '测试场景：另一会话已修改配置，当前编辑仍保留');
    if (args.expectedRevision != null && args.expectedRevision !== saved.revision) return fail('REVISION_CONFLICT', '测试版本冲突');
    if (method === 'save') return persist(args.model);
    if (method === 'select') { var next = clone(saved); next.groups.find(function(g) { return g.id === args.group; }).selected = args.nodeId; return persist(next); }
    if (method === 'import') { if (!args.content.trim()) return fail('INVALID_INPUT', '测试输入不能为空'); return persist(saved); }
    if (['apply', 'refresh', 'rollback', 'check'].includes(method) || method === 'service' && args.action === 'start') return startJob(method, args);
    if (method === 'service' && args.action === 'stop') { serviceRunning = false; return { ok: true, state: clone(state) }; }
    return fail('UNSUPPORTED', '预览未实现此模拟操作');
  }
  var rpc = { declare: function(spec) { return function() {
    var args = {}, values = arguments; (spec.params || []).forEach(function(key, i) { args[key] = values[i]; });
    return Promise.resolve().then(function() { return dispatch(spec.method, args); });
  }; } };
  var modules = { baseclass: BaseClass, view: View, ui: ui, poll: poll, rpc: rpc };
  function requireModule(name) {
    if (modules[name]) return modules[name];
    var source = window.PREVIEW_MODULES[name]; if (!source) throw new Error('Missing preview module: ' + name);
    var names = [], dependencies = [], expression = /^['"]require\s+(\S+?)(?:\s+as\s+([A-Za-z_]\w*))?['"];\s*$/gm, match;
    while ((match = expression.exec(source))) { names.push(match[2] || match[1].replace(/[^A-Za-z0-9_]/g, '_')); dependencies.push(requireModule(match[1])); }
    var Type = new Function('window', 'document', 'L', 'E', ...names, source)(window, document, L, E, ...dependencies);
    if (!BaseClass.isSubclass(Type)) throw new TypeError('LuCI factory yields invalid constructor: ' + name);
    modules[name] = new Type(); return modules[name];
  }
  function reset() {
    if (app) { poll.remove(app.pollFn); window.removeEventListener('beforeunload', app.beforeUnload); }
    ui.hideModal(); errors.textContent = ''; fixture(); delete modules['view.alwayroute.app'];
    document.getElementById('view').replaceChildren(E('p', {}, ['正在加载…']));
    try { app = requireModule('view.alwayroute.app'); app.ready.then(function() { return app.refreshRuntime(); }).catch(report); }
    catch (error) { report(error); }
    window.preview = { calls: calls, get app() { return app; }, reset: reset, scenario: function(value) { scenario = value; app.refreshRuntime(); } };
  }
  document.getElementById('preview-reset').addEventListener('click', reset);
  document.getElementById('preview-scenario').addEventListener('change', function(event) { scenario = event.target.value; app.refreshRuntime(); });
  reset();
})();
