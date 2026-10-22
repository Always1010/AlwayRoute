'use strict';
'require baseclass';
'require rpc';

var definitions = {
	capabilities: [], get: [], save: ['expectedRevision', 'model'], import: ['expectedRevision', 'content'],
	refresh: ['expectedRevision', 'subscriptionId', 'content'],
	apply: ['expectedRevision'], select: ['expectedRevision', 'group', 'nodeId'],
	rollback: ['expectedRevision'], service: ['action'], status: [], traffic: [],
	export: ['includeSecrets'], job_status: [], check: ['nodeId'], logs: ['limit']
};
var calls = {};
Object.keys(definitions).forEach(function(method) {
	calls[method] = rpc.declare({ object: 'alwayroute', method: method, params: definitions[method] });
});

return baseclass.extend({
	call: function(method, args) {
		if (!calls[method]) return Promise.reject(new Error('未知管理操作'));
		return calls[method].apply(null, args || []).then(function(result) {
			if (!result || result.ok !== true) {
				var detail = result && result.error || {};
				var error = new Error(detail.message || '管理服务没有返回有效结果');
				error.code = detail.code || 'RPC_ERROR';
				error.details = detail.details;
				throw error;
			}
			return result;
		});
	}
});
