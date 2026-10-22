'use strict';
'require baseclass';

function clone(value) { return JSON.parse(JSON.stringify(value)); }
function effectiveNode(model, node) {
	var result = clone(node), override = (model.overrides || {})[node.id] || {};
	if (override.name != null) result.name = override.name;
	if (override.patch) Object.keys(override.patch).forEach(function(key) { result[key] = clone(override.patch[key]); });
	result.excluded = override.excluded === true;
	return result;
}
function references(model, id) {
	var refs = [];
	(model.groups || []).forEach(function(g) { if (g.selected === id) refs.push('策略组 ' + g.name); });
	(model.rules || []).forEach(function(r, i) { if (r.outbound === id) refs.push('规则 ' + (i + 1)); });
	if (model.defaultOutbound === id) refs.push('默认出口');
	return refs;
}
function label(model, id) {
	if (id === 'direct') return '直连';
	if (id === 'block') return '阻断';
	var group = (model.groups || []).filter(function(g) { return g.id === id; })[0];
	if (group) return group.name;
	var node = (model.nodes || []).filter(function(n) { return n.id === id; })[0];
	return node ? effectiveNode(model, node).name : id || '未知';
}
return baseclass.extend({
	clone: clone, effectiveNode: effectiveNode, references: references, label: label,
	id: function(prefix) { return prefix + '_' + Date.now().toString(36) + '_' + Math.random().toString(36).slice(2, 9); },
	removeNode: function(model, id) {
		var refs = references(model, id);
		if (refs.length) throw new Error('请先处理引用：' + refs.join('、'));
		model.nodes = model.nodes.filter(function(n) { return n.id !== id; });
		delete model.overrides[id];
	},
	removeSubscription: function(model, id) {
		var children = model.nodes.filter(function(n) { return n.source === id; });
		children.forEach(function(n) {
			var refs = references(model, n.id);
			if (refs.length) throw new Error(n.name + '仍被引用：' + refs.join('、'));
		});
		model.subscriptions = model.subscriptions.filter(function(s) { return s.id !== id; });
		model.nodes = model.nodes.filter(function(n) { return n.source !== id; });
		children.forEach(function(n) { delete model.overrides[n.id]; });
	},
	formatRate: function(value) {
		if (typeof value !== 'number' || !isFinite(value) || value < 0) return '不可用';
		var units = ['B/s', 'KiB/s', 'MiB/s', 'GiB/s'], n = 0;
		while (value >= 1024 && n < units.length - 1) { value /= 1024; n++; }
		return value.toFixed(n ? 1 : 0) + ' ' + units[n];
	},
	validPort: function(value) { return /^\d+$/.test(String(value)) && Number(value) > 0 && Number(value) <= 65535; },
	stateLabel: function(state) {
		return ({ passed: '检查通过', failed: '检查失败', unverified: '未验证' })[state] || '未知';
	},
	forwardingLabel: function(value) {
		if (typeof value === 'string') return value;
		if (!value || typeof value !== 'object') return '未验证';
		return Object.keys(value).map(function(key) {
			var item = value[key];
			return key + '：' + (typeof item === 'object' ? JSON.stringify(item) : String(item));
		}).join('；') || '未验证';
	}
});
