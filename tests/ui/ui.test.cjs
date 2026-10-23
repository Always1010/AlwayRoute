'use strict';

// Native Node tests only. Production modules never import this test adapter.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const root = path.resolve(__dirname, '../..');
const resource = path.join(root, 'firmware/openwrt/luci-app-alwayroute/htdocs/luci-static/resources');
const read = file => fs.readFileSync(path.join(resource, file), 'utf8');
class BaseClass {
  static extend(properties) { class Child extends this {} Object.assign(Child.prototype, properties); return Child; }
  static isSubclass(value) { return typeof value === 'function' && value.prototype instanceof this; }
}
function loadModule(source, names = [], values = []) {
  const Type = new Function('baseclass', ...names, source)(BaseClass, ...values);
  assert.ok(BaseClass.isSubclass(Type), 'LuCI factory must yield a Class subclass, not a plain object');
  return new Type();
}
const loadModel = () => loadModule(read('alwayroute/model.js'));
const model = loadModel();
const empty = () => ({ schema: 1, policyVersion: 1, revision: 0, mode: 'rule', defaultOutbound: 'Other', nodes: [], subscriptions: [], overrides: {},
  groups: [{ id: 'Proxy', name: '代理', selected: 'direct' }, { id: 'OpenAI', name: 'OpenAI', selected: 'Proxy' }, { id: 'Other', name: 'Other', selected: 'direct' }], rules: [] });
const node = (id = 'n1', source = null) => ({ id, source, name: '节点', type: 'vmess', enabled: true, server: 'example.test', port: 443,
  uuid: '00000000-0000-4000-8000-000000000000', security: 'auto', alterId: 0 });

function harness(call, writable = true) {
  // Minimal DOM surface exercises rendering without requiring npm/browser installs.
  class Element {
    constructor(tag, attrs = {}, children = []) {
      this.tag = tag; this.attrs = attrs; this.children = []; this.events = {};
      this.value = attrs.value == null ? '' : String(attrs.value);
      this.checked = !!attrs.checked; this.disabled = !!attrs.disabled; this.isConnected = true;
      if (attrs.click) this.events.click = attrs.click;
      children.forEach(c => this.appendChild(c));
      if (tag === 'select') this.value = (children.find(c => c.attrs.selected != null) || children[0] || { attrs: {} }).attrs.value || '';
    }
    appendChild(child) { this.children.push(child); return child; }
    removeChild(child) { this.children.splice(this.children.indexOf(child), 1); }
    addEventListener(event, fn) { this.events[event] = fn; }
    setAttribute(key, value) { this.attrs[key] = value; }
    remove() {}
    get firstChild() { return this.children[0]; }
  }
  const E = (tag, attrs, children) => new Element(tag, attrs || {}, Array.isArray(children) ? children : children ? [children] : []);
  const document = { hidden: false, body: E('body') };
  const window = { confirm: () => true, addEventListener() {}, removeEventListener() {}, setTimeout, clearTimeout };
  const poll = { add() {}, remove() {} };
  const ui = { showModal(title, children) { ui.modal = { title, children }; }, hideModal() { ui.modal = null; } };
  const view = loadModule(read('view/alwayroute/app.js'), ['view', 'ui', 'poll', 'api', 'model', 'E', 'L', 'window', 'document'],
    [BaseClass, ui, poll, { call }, model, E, { env: { resource_version: 'test-refresh' }, resource: x => x, hasViewPermission: () => writable }, window, document]);
  view.draft = empty(); view.state = { savedRevision: 0, appliedRevision: null, healthy: 'unverified' };
  view.revision = 0; view.capabilities = {}; view.checks = {}; view.logs = []; view.tab = 'overview'; view.root = E('div');
  return { view, document, ui, window };
}

function text(element) {
  if (element == null) return '';
  if (typeof element !== 'object') return String(element);
  return (element.children || []).map(text).join(' ');
}
function find(element, predicate) {
  if (!element || typeof element !== 'object') return null;
  if (predicate(element)) return element;
  for (const child of element.children || []) { const hit = find(child, predicate); if (hit) return hit; }
  return null;
}

function fieldInput(fields, label) {
  const field = find({ children: fields }, n => n.attrs && n.attrs.class === 'cbi-value ar-field' && text(n.children[0]) === label);
  return find(field, n => ['input', 'select', 'textarea'].includes(n.tag));
}

test('rendered styles share the current LuCI document resource version', () => {
  const { view, window } = harness(async () => ({ ok: true }));
  window.setTimeout = () => {}; // This check does not start background RPCs.
  const page = view.render([{ model: empty(), state: {} }, {}]);
  const stylesheet = find(page, n => n.tag === 'link' && n.attrs.rel === 'stylesheet');
  assert.equal(stylesheet.attrs.href, 'alwayroute/style.css?v=test-refresh');
});

test('effective subscription overrides remain separate from source nodes', () => {
  const m = empty(); m.nodes.push(node('s1', 'sub'));
  m.overrides.s1 = { name: '本地名称', excluded: true, patch: { port: 8443 } };
  const n = model.effectiveNode(m, m.nodes[0]);
  assert.equal(n.name, '本地名称'); assert.equal(n.port, 8443); assert.equal(n.excluded, true);
  assert.equal(m.nodes[0].name, '节点'); assert.equal(m.nodes[0].port, 443);
});

test('stable node references block destructive node and subscription deletion', () => {
  const m = empty(); m.nodes.push(node('n1', 'sub')); m.subscriptions.push({ id: 'sub' }); m.groups[0].selected = 'n1';
  assert.throws(() => model.removeNode(m, 'n1'), /策略组/);
  assert.throws(() => model.removeSubscription(m, 'sub'), /引用/);
  assert.equal(m.nodes.length, 1); assert.equal(m.subscriptions.length, 1);
  m.groups[0].selected = 'direct'; m.overrides.n1 = { excluded: true }; model.removeSubscription(m, 'sub');
  assert.equal(m.nodes.length, 0); assert.equal(m.overrides.n1, undefined);
});

test('unavailable rates and unknown health never become successful zero values', () => {
  assert.equal(model.formatRate(null), '不可用'); assert.equal(model.formatRate(NaN), '不可用');
  assert.equal(model.formatRate(0), '0 B/s'); assert.equal(model.formatRate(2048), '2.0 KiB/s');
  assert.equal(model.stateLabel('unverified'), '未验证');
  assert.equal(model.validPort('1.2'), false); assert.equal(model.validPort('65536'), false);
  assert.ok(model.id('s').length <= 20);
  assert.match(model.forwardingLabel({ available: false, scope: 'unverified' }), /scope：unverified/);
});

test('API rejects failed or malformed responses and preserves revision errors', async () => {
  let result = { ok: false, error: { code: 'REVISION_CONFLICT', message: '版本冲突' } };
  const api = loadModule(read('alwayroute/api.js'), ['rpc'], [{ declare: () => () => Promise.resolve(result) }]);
  await assert.rejects(api.call('save', [0, {}]), e => e.code === 'REVISION_CONFLICT');
  result = null; await assert.rejects(api.call('get'), /有效结果/);
  result = { ok: true, state: {} }; assert.equal((await api.call('get')).ok, true);
});

test('production dependency directives resolve through the LuCI class factory contract', () => {
  const registry = { baseclass: BaseClass, view: BaseClass, ui: {}, poll: {}, rpc: { declare: () => () => Promise.resolve({ ok: true }) } };
  function requireModule(name) {
    if (registry[name]) return registry[name];
    const source = read(name.replace(/\./g, '/') + '.js');
    const dependencies = [...source.matchAll(/^['"]require\s+(\S+?)(?:\s+as\s+([A-Za-z_]\w*))?['"];\s*$/gm)];
    const names = dependencies.map(m => m[2] || m[1].replace(/[^A-Za-z0-9_]/g, '_'));
    const values = dependencies.map(m => requireModule(m[1]));
    const Type = new Function(...names, source)(...values);
    assert.ok(BaseClass.isSubclass(Type), name + ' must return a LuCI Class subclass');
    return (registry[name] = new Type());
  }
  const page = requireModule('view.alwayroute.app');
  assert.equal(typeof page.render, 'function');
  assert.equal(typeof registry['alwayroute.api'].call, 'function');
  assert.equal(typeof registry['alwayroute.model'].effectiveNode, 'function');
});

test('all tabs render authenticated data; observed selector is independent from saved choice', () => {
  const { view } = harness(async () => ({ ok: true }));
  view.draft.nodes.push(node()); view.draft.groups[0].selected = 'n1';
  view.runtime = { service: { running: true }, core: { available: true, groups: { Proxy: { now: 'direct' } } }, forwarding: { scope: 'unverified' } };
  view.paint();
  assert.match(text(view.root), /核心当前选择：直连/); assert.doesNotMatch(text(view.root), /最近事件|配置导出/);
  assert.doesNotMatch(text(view.root), /\[object Object\]/);
  for (const tab of ['nodes', 'subscriptions', 'logs', 'settings']) { view.tab = tab; view.paint(); assert.ok(view.root.children.length); }
});

test('selector changes submit one transaction and keep confirmed choice until runtime acknowledgement', async () => {
  let finish, candidate;
  const calls = [], base = empty(); base.nodes = [node('n1'), node('n2')]; base.groups[0].selected = 'n1';
  const { view } = harness(async (method, args) => {
    calls.push(method);
    if (method === 'configure') { candidate = model.clone(args[1]); candidate.revision = 1; return new Promise(resolve => { finish = resolve; }); }
    return { state: { savedRevision: 1, appliedRevision: 1 }, service: { running: true }, core: { available: true, groups: Object.fromEntries(candidate.groups.map(g => [g.id, { now: g.selected }])) } };
  });
  view.draft = base; view.runtime = { service: { running: true } };
  const operation = view.chooseNode('Proxy', 'n2');
  assert.equal(view.busy, true); assert.equal(view.draft.groups[0].selected, 'n1');
  assert.equal(view.pendingModel.groups[0].selected, 'n2');
  assert.equal(find(view.root, n => n.attrs['aria-label'] === '保存'), null);
  finish({ model: candidate, state: { savedRevision: 1, appliedRevision: 1 } }); await operation;
  assert.deepEqual(calls, ['configure', 'status']);
  assert.equal(view.draft.groups[0].selected, 'n2'); assert.equal(view.actualChoice('Proxy'), 'n2');
  assert.equal(view.busy, false);
});

test('failed configure preserves previous model and failed runtime confirmation requires reconciliation', async () => {
  const base = empty(); base.nodes = [node('n1'), node('n2')]; base.groups[0].selected = 'n1';
  let fail = true, mismatch = false, saved = model.clone(base);
  const { view } = harness(async (method, args) => {
    if (method === 'configure') {
      if (fail) { const error = new Error('核心校验失败'); error.code = 'CORE_CHECK_FAILED'; throw error; }
      saved = model.clone(args[1]); saved.revision++;
      return { model: saved, state: { savedRevision: 1, appliedRevision: 1 } };
    }
    if (method === 'get') return { model: saved, state: { savedRevision: saved.revision, appliedRevision: saved.revision } };
    if (method === 'job_status') return { busy: false, job: null };
    return { state: { savedRevision: saved.revision, appliedRevision: saved.revision }, service: { running: true }, core: { available: true, groups: Object.fromEntries(saved.groups.map(g => [g.id, { now: mismatch && g.id === 'Proxy' ? 'n1' : g.selected }])) } };
  });
  view.draft = base; view.runtime = { service: { running: true } };
  await assert.rejects(view.chooseNode('Proxy', 'n2'), /核心校验失败/);
  assert.equal(view.draft.groups[0].selected, 'n1'); assert.equal(view.revision, 0);
  fail = false; mismatch = true;
  await assert.rejects(view.chooseNode('Proxy', 'n2'), /尚未确认/);
  assert.equal(view.uncertain, true); assert.equal(view.draft.groups[0].selected, 'n1');
  await assert.rejects(view.changeMode('global'), /重新检查/);
  mismatch = false; await view.reconcile();
  assert.equal(view.uncertain, false); assert.equal(view.draft.groups[0].selected, 'n2');
});

test('service toggle waits for actual response and uses one action button', async () => {
  let finish, running = true;
  const { view } = harness(async method => {
    if (method === 'service') return new Promise(resolve => { finish = resolve; });
    return { state: { savedRevision: 0, appliedRevision: null }, service: { running }, core: { available: running, groups: {} } };
  });
  view.runtime = { service: { running: true } }; view.paint();
  assert.ok(find(view.root, n => n.attrs['aria-label'] === '停止'));
  assert.equal(find(view.root, n => n.attrs['aria-label'] === '启动'), null);
  const operation = view.toggleService();
  assert.equal(view.serviceRunning(), true); assert.equal(view.busy, true);
  assert.equal(find(view.root, n => n.attrs['aria-label'] === '停止中…').disabled, true);
  running = false; finish({ state: { savedRevision: 0, appliedRevision: null } }); await operation;
  assert.equal(view.serviceRunning(), false); assert.ok(find(view.root, n => n.attrs['aria-label'] === '启动'));
  assert.equal(find(view.root, n => n.attrs['aria-label'] === '停止'), null);
});

test('request timeout leaves the previous model and blocks mutations until state is checked', async () => {
  const { view, window } = harness(async method => method === 'configure' ? new Promise(() => {}) : {});
  view.draft.nodes.push(node()); view.draft.groups[0].selected = 'n1';
  window.setTimeout = fn => { queueMicrotask(fn); return 0; };
  await assert.rejects(view.changeMode('global'), /超时/);
  assert.equal(view.busy, false); assert.equal(view.uncertain, true); assert.equal(view.draft.mode, 'rule');
  await assert.rejects(view.changeMode('direct'), /重新检查/);
});

test('custom groups preserve references on rename and block deleting primary or referenced groups', () => {
  const { view } = harness(async () => { throw new Error('Editing must not call RPC'); });
  let fields, commit;
  view.modal = (_title, f, c) => { fields = f; commit = c; };
  view.editGroup(); fieldInput(fields, '名称').value = '工作'; commit(view.draft);
  const group = view.draft.groups.find(g => g.name === '工作'), id = group.id;
  assert.equal(group.selected, 'Proxy');
  view.draft.rules.push({ id: 'r1', type: 'suffix', value: 'example.com', enabled: true, outbound: id });
  view.editGroup(group); fieldInput(fields, '名称').value = '工作网站'; commit(view.draft);
  assert.equal(group.id, id); assert.equal(view.draft.rules[0].outbound, id);
  assert.throws(() => view.removeGroup(group), /引用/);
  assert.throws(() => view.removeGroup(view.draft.groups[0]), /必须保留/);
  view.draft.rules = []; view.draft.defaultOutbound = id;
  assert.throws(() => view.removeGroup(group), /默认出口/);
  view.draft.defaultOutbound = 'Other'; view.removeGroup(group);
  assert.equal(view.draft.groups.some(g => g.id === id), false);
});

test('service presets default Domestic to direct and other services to Proxy', () => {
  const { view } = harness(async () => { throw new Error('Adding a service must not call RPC before confirmation'); });
  view.capabilities = { policyPresets: [
    { id: 'Domestic', name: '国内服务' },
    { id: 'YouTube', name: 'YouTube' }
  ] };
  let fields, commit;
  view.modal = (_title, f, c) => { fields = f; commit = c; };

  view.addService();
  fieldInput(fields, '服务').value = 'Domestic';
  commit(view.draft);
  assert.equal(view.draft.groups.find(g => g.id === 'Domestic').selected, 'direct');

  view.addService();
  fieldInput(fields, '服务').value = 'YouTube';
  commit(view.draft);
  assert.equal(view.draft.groups.find(g => g.id === 'YouTube').selected, 'Proxy');
});

test('runtime refresh preserves strategy controls and never promotes draft choices to actual choices', async () => {
  let actual = 'direct', lastError = null;
  const { view } = harness(async method => method === 'status' ? { state: { savedRevision: 0, appliedRevision: 0, healthy: 'unverified', lastError }, service: { running: true }, core: { available: true, groups: { Proxy: { now: actual } } } } : { available: true, upload: 1, download: 2 });
  view.draft.nodes.push(node()); view.paint();
  const control = find(view.root, n => n.attrs['aria-label'] === '代理的出口');
  await view.refreshRuntime(true);
  assert.equal(find(view.root, n => n.attrs['aria-label'] === '代理的出口'), control);
  view.draft.groups[0].selected = 'n1';
  assert.equal(view.dirty, undefined); assert.equal(view.actualChoice('Proxy'), 'direct');
  assert.equal(view.groupStatus(view.draft.groups[0]), '核心当前选择：直连');
  await view.refreshRuntime(true); assert.equal(view.draft.groups[0].selected, 'n1');
  actual = 'n1'; await view.refreshRuntime(true);
  assert.equal(view.groupStatus(view.draft.groups[0]), '');
  lastError = { message: '转发失败' }; await view.refreshRuntime(true);
  assert.equal(view.live.lastError.hidden, false); assert.match(view.live.lastError.textContent, /转发失败/);
  lastError = null; await view.refreshRuntime(true); assert.equal(view.live.lastError.hidden, true);
  view.runtime.core = { available: false, groups: {} };
  assert.equal(view.groupStatus(view.draft.groups[0]), '实际出口未获取');
  view.runtime.service.running = false;
  assert.equal(view.groupStatus(view.draft.groups[0]), '');
});

test('log polling is independent from pending status requests and page content stays separate', async () => {
  let finishStatus;
  const calls = [];
  const { view } = harness(async method => {
    calls.push(method);
    if (method === 'status') return new Promise(resolve => { finishStatus = resolve; });
    return method === 'logs' ? { entries: [{ time: 1700000000, level: 'info', message: '管理事件' }] } : { available: false };
  });
  view.paint(); const status = view.refreshRuntime();
  view.tab = 'logs'; view.paint(); await view.refreshRuntime();
  assert.deepEqual(calls, ['status', 'traffic', 'logs']);
  assert.equal(view.logs[0].message, '管理事件');
  const table = view.live.logs.firstChild;
  await view.refreshRuntime(); assert.equal(view.live.logs.firstChild, table);
  assert.doesNotMatch(text(view.root), /导出完整配置|实时流量/);
  finishStatus({ state: { savedRevision: 99 } }); await status;
  assert.equal(view.revision, 0); assert.equal(view.conflict, undefined);
  view.tab = 'settings'; view.paint();
  assert.match(text(view.root), /导出完整配置/); assert.doesNotMatch(text(view.root), /最近 20 条/);
});

test('revision conflict preserves confirmed choice and concurrent operations are rejected', async () => {
  let finish;
  const { view } = harness(async method => {
    if (method === 'configure') return new Promise(resolve => { finish = resolve; });
    return { state: { savedRevision: 0, appliedRevision: 0 }, service: { running: false }, core: { available: false, groups: {} } };
  });
  view.runtime = { service: { running: false } };
  view.draft.nodes.push(node()); view.draft.groups[0].selected = 'n1';
  const first = view.changeMode('global'); await assert.rejects(view.mutate('configure', []), /另一项操作/);
  finish({ model: Object.assign(empty(), { mode: 'global', revision: 1 }), state: { savedRevision: 1, appliedRevision: null } }); await first;
  assert.equal(view.draft.mode, 'global');
  const other = harness(async method => {
    if (method === 'status') return { state: { savedRevision: 1 }, service: { running: false } };
    const error = new Error('冲突'); error.code = 'REVISION_CONFLICT'; throw error;
  }).view;
  other.draft.nodes.push(node()); other.draft.groups[0].selected = 'n1';
  await assert.rejects(other.changeMode('global'), /冲突/);
  assert.equal(other.draft.mode, 'rule'); assert.equal(other.conflict, true);
});

test('polling pauses on hidden/non-overview pages and stale responses cannot overwrite a mutation', async () => {
  const calls = []; const pending = [];
  const { view, document } = harness((method) => { calls.push(method); return new Promise(resolve => pending.push([method, resolve])); });
  document.hidden = true; await view.refreshRuntime(); assert.equal(calls.length, 0);
  document.hidden = false; view.tab = 'nodes'; await view.refreshRuntime(); assert.equal(calls.length, 0);
  view.tab = 'overview'; const operation = view.refreshRuntime();
  assert.deepEqual(calls, ['status', 'traffic']);
  const duplicate = view.refreshRuntime(); await duplicate; assert.equal(calls.length, 2);
  view.operationGeneration = 1;
  pending.forEach(([method, resolve]) => resolve(method === 'status' ? { state: { savedRevision: 99 } } : method === 'logs' ? { entries: [] } : { available: false }));
  await operation; assert.equal(view.conflict, undefined); assert.equal(view.revision, 0);
});

test('overview throttles status while traffic continues and forced refresh bypasses the interval', async () => {
  const calls = []; let statusAttempts = 0;
  const { view } = harness(async method => {
    calls.push(method);
    if (method === 'status' && ++statusAttempts === 1) throw new Error('temporary status failure');
    if (method === 'status') return { state: { savedRevision: 0, appliedRevision: 0 }, service: { running: true } };
    return { available: true, upload: calls.length, download: 0 };
  });
  await view.refreshRuntime();
  const cachedRuntime = { service: { running: false } };
  view.runtime = cachedRuntime;
  await view.refreshRuntime();
  assert.equal(view.runtime, cachedRuntime);
  assert.equal(view.traffic.upload, 3);
  await view.refreshRuntime(true);
  assert.deepEqual(calls, ['status', 'traffic', 'traffic', 'status', 'traffic']);
});

test('runtime acknowledgement renders before a slow traffic response', async () => {
  let releaseTraffic;
  const { view } = harness(async method => method === 'traffic' ? new Promise(resolve => { releaseTraffic = resolve; }) :
    { state: { savedRevision: 0, appliedRevision: 0 }, service: { running: true }, core: { available: true, groups: {} } });
  const pending = view.refreshRuntime(true);
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(view.runtime.service.running, true);
  assert.equal(view.polling, true);
  releaseTraffic({ available: true, upload: 3, download: 7 });
  await pending;
  assert.equal(view.traffic.download, 7);
});

test('new node editor omits empty optional TLS and websocket fields', () => {
  const { view } = harness(async () => ({}));
  let fields, commit;
  view.modal = (_title, f, c) => { fields = f; commit = c; };
  view.editNode();
  const input = label => fieldInput(fields, label);
  input('名称').value = '测试'; input('服务器').value = 'example.test'; input('UUID（敏感）').value = node().uuid;
  input('VMess 加密').value = 'auto'; input('VMess alterId').value = '0'; input('传输').value = 'ws';
  commit(view.draft); const n = view.draft.nodes[0];
  assert.equal(n.tls.serverName, undefined); assert.equal(n.transport.host, undefined); assert.equal(n.transport.path, '/');
});

test('HTTP subscription permission defaults off and is scoped to the explicitly approved source', () => {
  const { view } = harness(async () => ({}));
  let fields, commit;
  view.modal = (_title, f, c) => { fields = f; commit = c; };
  const input = label => fieldInput(fields, label);
  view.editSubscription();
  assert.equal(input('允许此订阅使用未加密HTTP').checked, false);
  input('名称').value = '现有 HTTP 来源'; input('订阅地址（敏感）').value = 'http://example.invalid/redacted';
  assert.throws(() => commit(view.draft), /显式勾选/); assert.equal(view.draft.subscriptions.length, 0);
  input('允许此订阅使用未加密HTTP').checked = true; commit(view.draft);
  assert.equal(view.draft.subscriptions[0].allowHttp, true);
  view.editSubscription();
  assert.equal(input('允许此订阅使用未加密HTTP').checked, false);
  input('名称').value = '正常 HTTPS 来源'; input('订阅地址（敏感）').value = 'https://example.invalid/redacted'; commit(view.draft);
  assert.equal(view.draft.subscriptions[1].allowHttp, false);
});

test('editing a subscription preserves explicit HTTP permission and allows revoking it after moving to HTTPS', () => {
  const { view } = harness(async () => ({}));
  const original = { id: 'http_source', name: 'HTTP', url: 'http://example.invalid/redacted', enabled: true, intervalHours: 0, allowHttp: true };
  view.draft.subscriptions.push(original);
  let fields, commit;
  view.modal = (_title, f, c) => { fields = f; commit = c; };
  const input = label => fieldInput(fields, label);
  view.editSubscription(original); assert.equal(input('允许此订阅使用未加密HTTP').checked, true);
  input('允许此订阅使用未加密HTTP').checked = false;
  assert.throws(() => commit(view.draft), /HTTPS/); assert.equal(original.allowHttp, true);
  input('订阅地址（敏感）').value = 'https://example.invalid/redacted'; commit(view.draft);
  assert.equal(view.draft.subscriptions[0].allowHttp, false);
  assert.equal(view.draft.subscriptions[0].id, original.id);
  const legacy = { id: 'legacy', name: '旧 HTTPS', url: 'https://example.invalid/redacted', enabled: true, intervalHours: 0 };
  view.draft.subscriptions.push(legacy); view.editSubscription(legacy);
  assert.equal(input('允许此订阅使用未加密HTTP').checked, false);
});

test('non-rule modes hide group/rule controls and only global mode has a proxy node selector', () => {
  const { view } = harness(async () => ({})); view.runtime = { service: { running: true } };
  view.draft.mode = 'global'; view.paint();
  assert.equal(find(view.root, n => n.attrs['aria-label'] === '重新读取').disabled, false);
  assert.equal(find(view.root, n => n.attrs['aria-label'] === '添加自定义策略'), null);
  assert.equal(find(view.root, n => n.attrs['aria-label'] === '代理策略设置'), null);
  assert.ok(find(view.root, n => n.attrs['aria-label'] === '代理的出口'));
  view.draft.mode = 'direct'; view.paint();
  assert.equal(find(view.root, n => n.attrs['aria-label'] === '代理的出口'), null);
  assert.equal(find(view.root, n => n.attrs['aria-label'] === '停止').disabled, false);
});

test('rule editor converts legacy values into ordered deduplicated multi-value rules', () => {
  const { view } = harness(async () => ({}));
  view.capabilities = { limits: { rules: 512, ruleValues: 4 } };
  const original = { id: 'r1', type: 'suffix', value: 'legacy.example', outbound: 'Proxy', enabled: true };
  view.draft.rules.push(original);
  let fields, commit;
  view.modal = (_title, f, c) => { fields = f; commit = c; };
  view.editRule(original);
  const values = fieldInput(fields, '匹配值');
  assert.equal(values.tag, 'textarea');
  assert.equal(values.value, 'legacy.example');
  values.value = ' ^first,part$ \n\n^second$\n^first,part$\r^third$ ';
  fieldInput(fields, '匹配类型').value = 'regex';
  commit(view.draft);
  assert.deepEqual(view.draft.rules[0], { id: 'r1', type: 'regex', values: ['^first,part$', '^second$', '^third$'], outbound: 'Proxy', enabled: true });
  assert.equal('value' in view.draft.rules[0], false);
});

test('rule editor enforces advertised value and rule limits while keeping edits available at capacity', () => {
  const { view } = harness(async () => ({}));
  view.capabilities = { limits: { rules: 1, ruleValues: 4 } };
  view.draft.rules.push({ id: 'r1', type: 'regex', values: ['^one,part$', '^two$', '^three$', '^four$'], outbound: 'Proxy', enabled: true });
  const card = view.render_rules();
  assert.match(text(card), /已用 1 \/ 1 条/);
  assert.equal(find(card, n => n.attrs && n.attrs['aria-label'] === '添加规则').disabled, true);
  assert.equal(find(card, n => n.attrs && n.attrs['aria-label'] === '编辑规则').disabled, false);
  assert.match(text(card), /正则表达式/);
  assert.match(text(card), /共 4 项/);
  assert.doesNotMatch(text(card), /\^four\$/);
  assert.equal(find(card, n => n.tag === 'span' && n.attrs.title === '^one,part$\n^two$\n^three$\n^four$') != null, true);

  let fields, commit;
  view.capabilities.limits.ruleValues = 2;
  view.modal = (_title, f, c) => { fields = f; commit = c; };
  view.editRule();
  fieldInput(fields, '匹配值').value = 'one\ntwo\nthree';
  assert.throws(() => commit(view.draft), /最多支持 2 个匹配值/);
  fieldInput(fields, '匹配值').value = 'one';
  assert.throws(() => commit(view.draft), /最多支持 1 条自定义规则/);
});

test('asynchronous job stays busy until success and reloads persisted data; check result is preserved', async () => {
  const calls = []; let polls = 0;
  const { view, window } = harness(async method => {
    calls.push(method);
    if (method === 'check') return { ok: true, job: { id: 'j1', method, status: 'running' } };
    if (method === 'job_status') return { ok: true, busy: ++polls === 1,
      job: { id: 'j1', method: 'check', status: polls === 1 ? 'running' : 'succeeded', result: { nodeId: 'n1', available: true, delay: 42, healthy: 'passed', checkedRevision: 0 } } };
    return { ok: true, model: empty(), state: { savedRevision: 0, appliedRevision: 0, healthy: 'unverified' } };
  });
  window.setTimeout = (fn, ms) => ms === 1000 ? queueMicrotask(fn) : setTimeout(fn, ms);
  view.state.appliedRevision = 0;
  const task = view.checkNode('n1'); assert.equal(view.busy, true); assert.match(view.configurationLabel(), /正在检查节点/);
  await task;
  assert.deepEqual(calls, ['check', 'job_status', 'job_status', 'get']);
  assert.equal(view.busy, false); assert.equal(view.checks.n1.delay, 42); assert.equal(view.checks.n1.checkedRevision, 0); assert.equal(view.state.healthy, 'unverified');
});

test('subscription progress can be cancelled while busy and keeps partial results', async () => {
  const calls = []; let polling;
  const { view, window } = harness(async (method, args) => {
    calls.push([method, args]);
    if (method === 'check') return { ok: true, job: { id: 'batch', method, status: 'running', progress: { total: 2, completed: 0 } } };
    if (method === 'cancel_check') { polling(); return { ok: true, cancelling: true }; }
    if (method === 'job_status') return { ok: true, job: { id: 'batch', method: 'check', status: 'cancelled', result: {
      cancelled: true, total: 2, completed: 1, passed: 1, failed: 0, checks: { n1: { nodeId: 'n1', delay: 42, checkedRevision: 0 } }
    } } };
    return { ok: true, model: empty(), state: { savedRevision: 0, appliedRevision: 0, healthy: 'unverified' } };
  });
  window.setTimeout = (fn, ms) => ms === 1000 ? (polling = fn) : setTimeout(fn, ms);
  view.state.appliedRevision = 0;
  const task = view.checkSubscription('demo');
  await new Promise(resolve => setImmediate(resolve));
  assert.deepEqual(calls[0], ['check', ['', 'demo']]);
  assert.match(text(view.root), /正在串行检测.*0 \/ 2/);
  assert.equal(find(view.root, n => n.attrs['aria-label'] === '取消检测').disabled, false);
  assert.equal(find(view.root, n => n.attrs['aria-label'] === '重新读取').disabled, true);
  await view.cancelCheck(); await task;
  assert.equal(view.busy, false); assert.equal(view.uncertain, undefined);
  assert.equal(view.checks.n1.delay, 42); assert.match(view.message.text, /检测已取消.*1 \/ 2/);
  assert.equal(calls.some(([method]) => ['configure', 'select', 'service'].includes(method)), false);
});

test('loading a running check renders immediately with a resumable job', async () => {
  const calls = [], job = { id: 'batch', method: 'check', status: 'running' };
  const { view } = harness(async method => {
    calls.push(method);
    if (method === 'job_status') return { ok: true, busy: true, job };
    return { ok: true, model: empty(), state: { savedRevision: 0, appliedRevision: 0 } };
  });
  const loaded = await view.load();
  assert.equal(loaded[0].checkJob, job);
  assert.deepEqual(calls, ['job_status', 'get', 'capabilities']);
});

test('node selection follows visible eligible rows and preserves hidden choices with explicit batch scopes', async () => {
  const { view } = harness(async () => { throw new Error('selection must not call RPC'); });
  view.state.appliedRevision = 0;
  view.draft.subscriptions = [{ id: 'sub', name: '订阅' }];
  view.draft.nodes = [Object.assign(node('manual'), { name: '手动甲' }), Object.assign(node('sub1', 'sub'), { name: '订阅乙' }),
    Object.assign(node('disabled'), { name: '停用', enabled: false }), Object.assign(node('excluded', 'sub'), { name: '排除' })];
  view.draft.overrides.excluded = { excluded: true };
  const root = view.render_nodes(), byLabel = label => find(root, n => n.attrs['aria-label'] === label);
  const all = byLabel('全选当前筛选结果中的可检测节点'), source = byLabel('节点来源');
  assert.equal(byLabel('检查所选').disabled, true);
  assert.equal(byLabel('选择节点 停用').disabled, true); assert.equal(byLabel('选择节点 排除').disabled, true);
  source.value = '@manual'; source.events.change(); all.checked = true; all.events.change();
  assert.deepEqual(Object.keys(view.selectedNodes), ['manual']);
  source.value = 'sub'; source.events.change(); assert.equal(all.checked, false);
  all.checked = true; all.events.change(); assert.deepEqual(Object.keys(view.selectedNodes), ['manual', 'sub1']);
  source.value = ''; source.events.change(); assert.equal(all.checked, true);
  byLabel('选择节点 订阅乙').checked = false; byLabel('选择节点 订阅乙').events.change();
  assert.equal(all.indeterminate, true);
  const query = byLabel('搜索节点名称'); query.value = '不存在'; query.events.input(); assert.equal(all.disabled, true);
  assert.equal(byLabel('检查所选').disabled, false);
  const calls = []; view.startCheck = (...args) => { calls.push(args); return Promise.resolve(); };
  await view.checkSelected(); await view.checkAll(false); await view.checkAll(true);
  assert.deepEqual(calls, [['', '', ['manual'], 'selected', false], ['', '', [], 'all', false], ['', '', [], 'all', true]]);
  view.selectedNodes = {}; assert.throws(() => view.checkSelected(), /先选择/);
  view.selectedNodes = { manual: true, vanished: true }; view.draft.nodes[0].enabled = false; view.render_nodes();
  assert.deepEqual(Object.keys(view.selectedNodes), []);
});

test('running checks publish row results and times through lightweight job polling and retain partial failures', async () => {
  const saved = empty(); saved.nodes.push(node('n1'), node('n2'));
  const calls = [], outcome = { nodeId: 'n1', checkedRevision: 0, healthy: 'failed', available: false, reason: '超时', time: 1700000000 };
  let polls = 0, resume;
  const { view, window } = harness(async method => {
    calls.push(method);
    if (method === 'job_status') return { ok: true, job: { id: 'resume', method: 'check', status: ++polls === 1 ? 'running' : 'failed',
      progress: { scope: 'all', total: 2, completed: 1, currentNodeId: 'n2', failed: 1 }, checks: { n1: outcome }, error: { code: 'JOB_INTERRUPTED', message: '后台中断' } } };
    throw new Error('only job_status is needed while checking');
  });
  window.setTimeout = (fn, ms) => ms === 1000 ? (resume = fn) : setTimeout(fn, ms);
  view.state.appliedRevision = 0; view.draft = saved; view.tab = 'nodes';
  const task = view.observeCheck({ id: 'resume', method: 'check', status: 'running', checks: { n1: outcome } });
  assert.equal(view.checks.n1.healthy, 'failed');
  resume(); await new Promise(setImmediate);
  assert.match(text(view.root), /不可用：超时/); assert.match(text(view.root), /正在检测/);
  assert.match(text(view.root), new RegExp(new Date(outcome.time * 1000).toLocaleString().replace(/[.*+?^${}()|[\]\\]/g, '\\$&')));
  assert.equal(find(view.root, n => n.attrs['aria-label'] === '仅重试失败').disabled, true);
  assert.equal(find(view.root, n => n.attrs['aria-label'] === '全选当前筛选结果中的可检测节点').disabled, true);
  resume(); await task;
  assert.deepEqual(calls, ['job_status', 'job_status']); assert.equal(view.checks.n1.healthy, 'failed');
  assert.equal(view.uncertain, true); assert.match(view.message.text, /后台中断/);
});

test('batch check actions preserve busy, read-only and revision protections', async () => {
  const { view } = harness(async () => { throw new Error('blocked checks must not call RPC'); });
  view.draft.nodes.push(node()); view.state.appliedRevision = 0;
  view.checks.n1 = { healthy: 'failed', checkedRevision: 0 };
  for (const flag of ['busy', 'readonly', 'dirty', 'conflict', 'uncertain']) {
    view[flag] = true;
    const root = view.render_nodes();
    for (const label of ['检查所选', '扫描全部', '仅重试失败']) assert.equal(find(root, n => n.attrs['aria-label'] === label).disabled, true, `${flag}: ${label}`);
    view[flag] = false;
  }
  view.state.savedRevision = 1;
  assert.throws(() => view.checkAll(false), /先启动服务/);
  view.state.savedRevision = 0; view.readonly = true; await assert.rejects(view.checkAll(false), /读取权限/);
  view.readonly = false; view.busy = true; await assert.rejects(view.checkAll(false), /另一项操作/);
});

test('status restores only node checks belonging to the currently applied revision', async () => {
  let applied = 2;
  const { view } = harness(async method => method === 'status' ? {
    ok: true, state: { savedRevision: 3, appliedRevision: applied, healthy: 'unverified' },
    checks: { n1: { nodeId: 'n1', delay: 42, healthy: 'passed', checkedRevision: 2 }, old: { healthy: 'passed', checkedRevision: 1 }, unknown: { healthy: 'passed' } }
  } : method === 'logs' ? { ok: true, entries: [] } : { ok: true, available: false });
  view.revision = 3; view.draft.nodes.push(node());
  await view.refreshRuntime(true);
  assert.deepEqual(Object.keys(view.checks), ['n1']);
  view.tab = 'nodes'; view.paint();
  assert.match(text(view.root), /42 ms/); assert.equal(view.state.healthy, 'unverified');
  assert.equal(find(view.root, n => n.attrs['aria-label'] === '检查此节点').disabled, true);
  applied = 3; view.tab = 'overview'; await view.refreshRuntime(true);
  assert.deepEqual(view.checks, {});
});

test('unapplied configuration blocks node checks and applying a new revision removes old results', () => {
  const { view } = harness(async () => { throw new Error('RPC should not run'); });
  view.state = { savedRevision: 2, appliedRevision: 1, healthy: 'unverified' };
  view.checks = { n1: { checkedRevision: 1, healthy: 'passed', delay: 42 } };
  assert.throws(() => view.checkNode('n1'), /先启动服务/);
  view.accept({ state: { savedRevision: 2, appliedRevision: 2, healthy: 'unverified' } });
  assert.deepEqual(view.checks, {}); assert.equal(view.state.healthy, 'unverified');
});

test('explicit reload clears cached node checks while preserving separate global health', async () => {
  const { view } = harness(async () => ({ ok: true, model: empty(), state: { savedRevision: 0, appliedRevision: 0, healthy: 'unverified' } }));
  view.tab = 'nodes'; view.checks = { n1: { checkedRevision: 0, healthy: 'passed', delay: 42 } };
  await view.reload();
  assert.deepEqual(view.checks, {}); assert.equal(view.state.healthy, 'unverified');
});

test('failed asynchronous configure never replaces confirmed model or actual selector', async () => {
  const { view, window } = harness(async method => method === 'configure' ? { ok: true, job: { id: 'j2', method, status: 'running' } } : method === 'status' ? { state: { savedRevision: 0, appliedRevision: 0 }, service: { running: true }, core: { available: true, groups: { Proxy: { now: 'direct' } } } } :
    { ok: true, busy: false, job: { id: 'j2', status: 'failed', error: { code: 'CORE_CHECK_FAILED', message: '核心校验失败' } } });
  window.setTimeout = (fn, ms) => ms === 1000 ? queueMicrotask(fn) : setTimeout(fn, ms);
  view.runtime = { service: { running: true } };
  view.draft.nodes.push(node()); view.draft.groups[0].selected = 'n1';
  await assert.rejects(view.changeMode('global'), /核心校验失败/);
  assert.equal(view.busy, false); assert.equal(view.draft.mode, 'rule'); assert.match(view.message.text, /CORE_CHECK_FAILED/);
});

test('readonly load and refresh use status without requesting credential-bearing configuration', async () => {
  const calls = [];
  const { view } = harness(async method => {
    calls.push(method);
    if (method === 'status') return { state: { savedRevision: calls.length, appliedRevision: 0 }, service: { running: false } };
    if (method === 'capabilities') return {};
    if (method === 'traffic') return { available: false };
    throw new Error('read-only role cannot call ' + method);
  }, false);
  view.render(await view.load());
  assert.deepEqual(calls, ['status', 'capabilities']);
  assert.equal(find(view.root, n => n.attrs['aria-label'] === '运行模式'), null);
  assert.equal(find(view.root, n => n.attrs['aria-label'] === '启动'), null);
  assert.doesNotMatch(text(view.root), /备份与恢复|订阅|策略组/);
  await view.reload();
  assert.equal(!!view.conflict, false); assert.equal(calls.includes('get'), false);
  await assert.rejects(view.mutate('configure', []), /读取权限/);
});

test('stopped edits reject unexpected startup for configure and activated imports', async () => {
  for (const importing of [false, true]) {
    const saved = empty(); saved.revision = 1;
    const { view } = harness(async method => method === 'status' ? { state: { savedRevision: 1, appliedRevision: 1 }, service: { running: true }, core: { groups: Object.fromEntries(saved.groups.map(g => [g.id, { now: g.selected }])) } } : { model: saved });
    view.runtime = { service: { running: false } };
    await assert.rejects(importing ? view.activateMutation('import', [0, 'content', true], '成功') : view.configureModel(saved), /尚未确认/);
    assert.equal(view.uncertain, true); assert.equal(view.revision, 0);
  }
});

test('reconciliation invalidates overview polls that started before state verification', async () => {
  let resolveOld, requests = 0;
  const saved = empty(); saved.revision = 2;
  const { view } = harness(async method => {
    if (method === 'status' && ++requests === 1) return new Promise(resolve => { resolveOld = resolve; });
    if (method === 'status') return { state: { savedRevision: 2, appliedRevision: null }, service: { running: false } };
    if (method === 'get') return { model: saved, state: { savedRevision: 2, appliedRevision: null } };
    return { busy: false, available: false };
  });
  const old = view.refreshRuntime(); view.uncertain = true; await view.reconcile();
  resolveOld({ state: { savedRevision: 0 }, service: { running: true } }); await old;
  assert.equal(view.serviceRunning(), false); assert.equal(view.revision, 2); assert.equal(view.conflict, false);
});

test('unconfigured proxy modes request a node in the same transaction and never offer direct as a proxy node', async () => {
  const { view } = harness(async () => { throw new Error('opening the node picker must not write'); });
  view.runtime = { service: { running: false } }; view.draft.mode = 'direct';
  await assert.rejects(view.changeMode('global'), /添加可用节点/);
  view.draft.nodes.push(node()); let fields, commit;
  view.modal = (_title, f, c) => { fields = f; commit = c; };
  for (const mode of ['global', 'rule']) {
    await view.changeMode(mode); assert.equal(view.draft.mode, 'direct');
    assert.throws(() => commit(model.clone(view.draft)), /请选择代理节点/);
    fieldInput(fields, '代理节点').value = 'n1';
    const candidate = model.clone(view.draft); commit(candidate);
    assert.equal(candidate.mode, mode); assert.equal(candidate.groups[0].selected, 'n1');
  }
  view.draft.mode = 'rule'; view.paint();
  assert.equal(find(view.root, n => n.attrs['aria-label'] === '启动').disabled, true);
  const selector = view.groupSelect(view.draft.groups[0]);
  assert.equal(find(selector, n => n.tag === 'option' && n.attrs.value === 'direct'), null);
});

test('empty import stays open and failed import releases fields while preserving input', async () => {
  const { view, ui } = harness(async () => ({})); let calls = 0;
  view.showImport('导入', async () => { calls++; throw new Error('解析失败'); });
  const submit = find({ children: ui.modal.children }, n => n.tag === 'button' && n.attrs['aria-label'] === '导入');
  const area = find({ children: ui.modal.children }, n => n.tag === 'textarea');
  submit.events.click({ preventDefault() {} }); await new Promise(setImmediate);
  assert.equal(calls, 0); assert.ok(ui.modal);
  area.value = 'invalid content'; submit.events.click({ preventDefault() {} }); await new Promise(setImmediate);
  assert.equal(calls, 1); assert.equal(area.value, 'invalid content'); assert.equal(area.disabled, false); assert.equal(submit.disabled, false);
  assert.match(find({ children: ui.modal.children }, n => n.attrs && n.attrs.class === 'ar-alert ar-error').textContent, /解析失败/);
});
