'use strict';

// Generates a self-contained, offline preview. It never starts a listener/browser.
const fs = require('node:fs');
const path = require('node:path');
const root = path.resolve(__dirname, '../..');
const resources = path.join(root, 'firmware/openwrt/luci-app-alwayroute/htdocs/luci-static/resources');
const output = process.argv[2] ? path.resolve(process.argv[2]) : path.join(root, '.local/ui-preview/alwayroute.html');
const production = {
  'alwayroute.api': fs.readFileSync(path.join(resources, 'alwayroute/api.js'), 'utf8'),
  'alwayroute.model': fs.readFileSync(path.join(resources, 'alwayroute/model.js'), 'utf8'),
  'view.alwayroute.app': fs.readFileSync(path.join(resources, 'view/alwayroute/app.js'), 'utf8')
};
const payload = JSON.stringify(production).replace(/</g, '\\u003c');
const runtime = fs.readFileSync(path.join(__dirname, 'preview-runtime.js'), 'utf8');
const css = fs.readFileSync(path.join(resources, 'alwayroute/style.css'), 'utf8');
const policyDirectory = path.join(root, 'firmware/openwrt/alwayroute-manager/files/usr/share/alwayroute/policies');
const policyFiles = JSON.parse(fs.readFileSync(path.join(policyDirectory, 'catalog.json'), 'utf8'));
const catalog = JSON.stringify(policyFiles.map(file => JSON.parse(fs.readFileSync(path.join(policyDirectory, file), 'utf8')))).replace(/</g, '\\u003c');
const theme = process.argv[3] || 'bootstrap';
if (!['bootstrap', 'material', 'openwrt-2020'].includes(theme)) throw new Error('Unknown preview theme: ' + theme);
const themeDirectory = theme === 'openwrt-2020' ? 'openwrt2020' : theme;
const themeFile = path.join(root, '.local/sources/luci/themes', 'luci-theme-' + theme, 'htdocs/luci-static', themeDirectory, 'cascade.css');
if (!fs.existsSync(themeFile)) throw new Error('LuCI theme source is missing. Prepare .local/sources/luci with scripts/fetch-sources.py first.');
const themeCss = fs.readFileSync(themeFile, 'utf8');
const shellCss = `body{margin:0;padding:0}#view{display:block;width:100%;max-width:1180px;margin:auto;padding:24px;box-sizing:border-box}.preview-routerbar{background:#333;color:#fff;padding:12px 24px;font:14px sans-serif}.preview-routerbar strong{margin-right:28px}.preview-banner{padding:10px 24px;background:#fff8df;border-bottom:1px solid #dcc387;color:#70561a;font:13px sans-serif}.preview-controls{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin-top:8px}.preview-overlay{position:fixed;inset:0;background:#0008;display:grid;place-items:center;padding:18px;z-index:1000}.preview-modal{background:var(--background-color-high,#fff);color:var(--text-color-high,inherit);padding:24px;max-width:760px;width:100%;box-sizing:border-box;max-height:94vh;overflow:auto}.preview-modal h2{margin-top:0}.right{justify-content:flex-end}#preview-error{white-space:pre-wrap;color:#922b35}@media(max-width:600px){#view{padding:14px}.preview-banner{padding:10px 14px}.preview-modal{padding:16px}.preview-routerbar{padding:12px 14px}}`;

const child = `<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>AlwayRoute · 本地测试预览</title><style>${themeCss}\n${shellCss}\n${css}</style><body><div class="preview-routerbar"><strong>LuCI</strong> 服务 / AlwayRoute</div><aside class="preview-banner"><strong>本地预览 · 模拟 RPC · 不连接任何设备</strong><br>LuCI ${theme} 原生样式 + 生产 JS/CSS；样例仅用于布局与交互检查，不代表代理已验证。<div class="preview-controls"><label>测试场景 <select id="preview-scenario"><option value="normal">正常响应</option><option value="unavailable">核心/流量不可用</option><option value="conflict">写入时版本冲突</option><option value="job-failed">后台任务失败</option></select></label><button id="preview-reset" type="button">重置脱敏样例</button><span id="preview-status" role="status">正在加载生产模块…</span></div></aside><main id="view"></main><pre id="preview-error" role="alert"></pre><script>window.PREVIEW_POLICIES=${catalog};window.PREVIEW_MODULES=${payload};<\/script><script>${runtime.replace(/<\/script/gi, '<\\/script')}<\/script></body></html>`;
const childJson = JSON.stringify(child).replace(/</g, '\\u003c');
const html = `<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>AlwayRoute 浏览器预览</title><style>body{margin:0;background:#eee;font:14px system-ui,sans-serif}header{padding:12px 18px;background:#333;color:white;display:flex;align-items:center;gap:12px;flex-wrap:wrap}header button{font:inherit;padding:6px 12px;cursor:pointer}iframe{display:block;border:0;width:100%;height:calc(100vh - 62px);min-height:700px;margin:auto;background:#fff;box-shadow:0 0 22px #15283820}iframe.mobile{width:390px;max-width:100%}</style><body><header><strong>AlwayRoute 真实 DOM 预览</strong><button id="desktop" type="button">桌面 / 自适应</button><button id="mobile" type="button">手机 · 390px</button><span>LuCI ${theme} 主题；此文件包含测试模拟器</span></header><iframe id="preview-frame" title="AlwayRoute 测试预览"></iframe><script>const frame=document.getElementById('preview-frame');frame.srcdoc=${childJson};document.getElementById('desktop').onclick=()=>frame.classList.remove('mobile');document.getElementById('mobile').onclick=()=>frame.classList.add('mobile');<\/script></body></html>`;
fs.mkdirSync(path.dirname(output), { recursive: true });
fs.writeFileSync(output, html, 'utf8');
console.log(output);
console.log('Generated offline HTML only; no listener, device connection, or browser was started.');
