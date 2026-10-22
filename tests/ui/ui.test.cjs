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
const empty = () => ({ schema: 1, revision: 0, mode: 'rule', defaultOutbound: 'Proxy', nodes: [], subscriptions: [], overrides: {},
  groups: [{ id: 'Proxy', name: '代理', selected: 'direct' }, { id: 'OpenAI', name: 'OpenAI', selected: 'Proxy' }], rules: [] });
const node = (id = 'n1', source = null) => ({ id, source, name: '节点', type: 'vmess', enabled: true, server: 'example.test', port: 443,
  uuid: '00000000-0000-4000-8000-000000000000', security: 'auto', alterId: 0 });

function harness(call) {
  // Minimal DOM surface exercises rendering without requiring npm/browser installs.
  class Element {
    constructor(tag, attrs = {}, children = []) {
      this.tag = tag; this.attrs = attrs; this.children = []; this.events = {};
      this.value = attrs.value == null ? '' : String(attrs.value);
      this.checked = !!attrs.checked; this.disabled = !!attrs.disabled; this.isConnected = true;
      if (attrs.click) this.events.click = attrs.click;
      children.forEach(c => this.appendChild(c));
    }
    appendChild(child) { this.children.push(child); return child; }
    removeChild(child) { this.children.splice(this.children.indexOf(child), 1); }
    addEventListener(event, fn) { this.events[event] = fn; }
    remove() {}
    get firstChild() { return this.children[0]; }
  }
  const E = (tag, attrs, children) => new Element(tag, attrs || {}, Array.isArray(children) ? children : children ? [children] : []);
  const document = { hidden: false, body: E('body') };
  const window = { confirm: () => true, addEventListener() {}, removeEventListener() {}, setTimeout };
  const poll = { add() {}, remove() {} };
  const ui = { showModal(title, children) { ui.modal = { title, children }; }, hideModal() { ui.modal = null; } };
  const view = loadModule(read('view/alwayroute/app.js'), ['view', 'ui', 'poll', 'api', 'model', 'E', 'L', 'window', 'document'],
    [BaseClass, ui, poll, { call }, model, E, { resource: x => x, hasViewPermission: () => true }, window, document]);
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
  assert.match(text(view.root), /核心实际选择/); assert.match(text(view.root), /scope：unverified/);
  assert.match(text(view.root), /未验证/); assert.doesNotMatch(text(view.root), /\[object Object\]/);
  for (const tab of ['nodes', 'subscriptions', 'groups', 'rules', 'settings']) { view.tab = tab; view.paint(); assert.ok(view.root.children.length); }
});

test('save persists draft without apply; select saves without claiming actual activation', async () => {
  const calls = [];
  const { view } = harness(async (method, args) => {
    calls.push([method, args]); return { ok: true, model: Object.assign(empty(), { revision: 1 }), state: { savedRevision: 1, appliedRevision: 0, healthy: 'unverified' } };
  });
  view.dirty = true; await view.save();
  assert.deepEqual(calls.map(c => c[0]), ['save']); assert.equal(view.dirty, false); assert.equal(view.state.appliedRevision, 0);
  await view.chooseNode('Proxy', 'direct'); assert.deepEqual(calls.map(c => c[0]), ['save', 'select']); assert.match(view.message.text, /请应用/);
  view.dirty = true; assert.throws(() => view.apply(), /请先保存/);
});

test('revision conflict retains the local draft and exposes error; concurrent mutation is rejected', async () => {
  let finish;
  const { view } = harness(() => new Promise(resolve => { finish = resolve; }));
  view.draft.mode = 'global'; view.dirty = true;
  const first = view.save(); await assert.rejects(view.mutate('apply', [0]), /另一项操作/);
  finish({ ok: true, model: view.draft, state: view.state }); await first;
  const other = harness(async () => { const e = new Error('冲突'); e.code = 'REVISION_CONFLICT'; throw e; }).view;
  other.draft.mode = 'global'; other.dirty = true;
  await assert.rejects(other.save(), /冲突/); assert.equal(other.draft.mode, 'global'); assert.equal(other.dirty, true); assert.equal(other.conflict, true);
});

test('polling pauses on hidden/non-overview pages and stale responses cannot overwrite a mutation', async () => {
  const calls = []; const pending = [];
  const { view, document } = harness((method) => { calls.push(method); return new Promise(resolve => pending.push([method, resolve])); });
  document.hidden = true; await view.refreshRuntime(); assert.equal(calls.length, 0);
  document.hidden = false; view.tab = 'nodes'; await view.refreshRuntime(); assert.equal(calls.length, 0);
  view.tab = 'overview'; const operation = view.refreshRuntime();
  assert.deepEqual(calls, ['status', 'traffic', 'logs']);
  const duplicate = view.refreshRuntime(); await duplicate; assert.equal(calls.length, 3);
  view.operationGeneration = 1;
  pending.forEach(([method, resolve]) => resolve(method === 'status' ? { state: { savedRevision: 99 } } : method === 'logs' ? { entries: [] } : { available: false }));
  await operation; assert.equal(view.conflict, undefined); assert.equal(view.revision, 0);
});

test('new node editor omits empty optional TLS and websocket fields', () => {
  const { view } = harness(async () => ({}));
  let fields, commit;
  view.modal = (_title, f, c) => { fields = f; commit = c; };
  view.editNode();
  const input = label => fields.find(f => f.tag === 'label' && text(f.children[0]) === label).children[1];
  input('名称').value = '测试'; input('服务器').value = 'example.test'; input('UUID（敏感）').value = node().uuid;
  input('VMess 加密').value = 'auto'; input('VMess alterId').value = '0'; input('传输').value = 'ws';
  commit(); const n = view.draft.nodes[0];
  assert.equal(n.tls.serverName, undefined); assert.equal(n.transport.host, undefined); assert.equal(n.transport.path, '/');
});

test('HTTP subscription permission defaults off and is scoped to the explicitly approved source', () => {
  const { view } = harness(async () => ({}));
  let fields, commit;
  view.modal = (_title, f, c) => { fields = f; commit = c; };
  const input = label => fields.find(f => f.tag === 'label' && text(f.children[0]) === label).children[1];
  view.editSubscription();
  assert.equal(input('允许此订阅使用未加密HTTP').checked, false);
  input('名称').value = '现有 HTTP 来源'; input('订阅地址（敏感）').value = 'http://example.invalid/redacted';
  assert.throws(() => commit(), /显式勾选/); assert.equal(view.draft.subscriptions.length, 0);
  input('允许此订阅使用未加密HTTP').checked = true; commit();
  assert.equal(view.draft.subscriptions[0].allowHttp, true);
  view.editSubscription();
  assert.equal(input('允许此订阅使用未加密HTTP').checked, false);
  input('名称').value = '正常 HTTPS 来源'; input('订阅地址（敏感）').value = 'https://example.invalid/redacted'; commit();
  assert.equal(view.draft.subscriptions[1].allowHttp, false);
});

test('editing a subscription preserves explicit HTTP permission and allows revoking it after moving to HTTPS', () => {
  const { view } = harness(async () => ({}));
  const original = { id: 'http_source', name: 'HTTP', url: 'http://example.invalid/redacted', enabled: true, intervalHours: 0, allowHttp: true };
  view.draft.subscriptions.push(original);
  let fields, commit;
  view.modal = (_title, f, c) => { fields = f; commit = c; };
  const input = label => fields.find(f => f.tag === 'label' && text(f.children[0]) === label).children[1];
  view.editSubscription(original); assert.equal(input('允许此订阅使用未加密HTTP').checked, true);
  input('允许此订阅使用未加密HTTP').checked = false;
  assert.throws(() => commit(), /HTTPS/); assert.equal(original.allowHttp, true);
  input('订阅地址（敏感）').value = 'https://example.invalid/redacted'; commit();
  assert.equal(view.draft.subscriptions[0].allowHttp, false);
  assert.equal(view.draft.subscriptions[0].id, original.id);
  const legacy = { id: 'legacy', name: '旧 HTTPS', url: 'https://example.invalid/redacted', enabled: true, intervalHours: 0 };
  view.draft.subscriptions.push(legacy); view.editSubscription(legacy);
  assert.equal(input('允许此订阅使用未加密HTTP').checked, false);
});

test('readonly view disables write buttons while keeping reload available', () => {
  const { view } = harness(async () => ({})); view.readonly = true; view.dirty = true; view.paint();
  assert.equal(find(view.root, n => n.attrs['aria-label'] === '保存').disabled, true);
  assert.equal(find(view.root, n => n.attrs['aria-label'] === '重新读取').disabled, false);
});

test('asynchronous job stays busy until success and reloads persisted data; check result is preserved', async () => {
  const calls = []; let polls = 0;
  const { view, window } = harness(async method => {
    calls.push(method);
    if (method === 'check') return { ok: true, job: { id: 'j1', method, status: 'running' } };
    if (method === 'job_status') return { ok: true, busy: ++polls === 1,
      job: { id: 'j1', method: 'check', status: polls === 1 ? 'running' : 'succeeded', result: { nodeId: 'n1', available: true, delay: 42, healthy: 'passed' } } };
    return { ok: true, model: empty(), state: { savedRevision: 0, appliedRevision: 0, healthy: 'unverified' } };
  });
  window.setTimeout = fn => { fn(); };
  const task = view.checkNode('n1'); assert.equal(view.busy, true);
  await task;
  assert.deepEqual(calls, ['check', 'job_status', 'job_status', 'get']);
  assert.equal(view.busy, false); assert.equal(view.checks.n1, '42 ms'); assert.equal(view.state.healthy, 'unverified');
});

test('failed background job reports error without silently replacing the draft', async () => {
  const { view, window } = harness(async method => method === 'apply' ? { ok: true, job: { id: 'j2', method, status: 'running' } } :
    { ok: true, busy: false, job: { id: 'j2', status: 'failed', error: { code: 'CORE_CHECK_FAILED', message: '核心校验失败' } } });
  window.setTimeout = fn => { fn(); };
  view.draft.mode = 'global';
  await assert.rejects(view.apply(), /核心校验失败/);
  assert.equal(view.busy, false); assert.equal(view.draft.mode, 'global'); assert.match(view.message.text, /CORE_CHECK_FAILED/);
});
