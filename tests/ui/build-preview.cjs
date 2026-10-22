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
const shellCss = `*{box-sizing:border-box}body{margin:0;background:#f3f6f8;color:#253943;font-family:system-ui,-apple-system,"Segoe UI",sans-serif;font-size:14px}main{padding:24px;max-width:1420px;margin:auto}button,input,select,textarea{font:inherit}button{border:1px solid #bbcbd4;border-radius:4px;background:#f7fafb;color:#253943;padding:.4rem .8rem}input,select,textarea{border:1px solid #b9c9d2;border-radius:4px;padding:.45rem .6rem;background:#fff;color:#253943}button:disabled{opacity:.45}.cbi-button-action{background:#176b83;color:white;border-color:#176b83}h2{font-size:24px}h3{font-size:17px}p{line-height:1.55}.preview-banner{padding:12px 24px;background:#fdf1ce;border-bottom:1px solid #dcc387;color:#70561a}.preview-controls{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin:8px 0 0}.preview-overlay{position:fixed;inset:0;background:#0b253d80;display:grid;place-items:center;padding:18px;z-index:100}.preview-modal{background:#fff;padding:24px;border-radius:8px;box-shadow:0 10px 50px #0004;max-width:760px;width:100%;max-height:94vh;overflow:auto}.preview-modal h2{margin-top:0}.right{justify-content:flex-end}#preview-error{white-space:pre-wrap;color:#922b35}@media(max-width:600px){main{padding:12px}.preview-banner{padding:12px}.preview-modal{padding:16px}}`;
const child = `<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>AlwayRoute · 本地测试预览</title><style>${shellCss}\n${css}</style><body><aside class="preview-banner"><strong>本地预览 · 模拟 RPC · 不连接任何设备</strong><br>生产 JS/CSS + 浏览器原生 DOM；样例仅用于布局与交互检查，不代表代理已验证。<div class="preview-controls"><label>测试场景 <select id="preview-scenario"><option value="normal">正常响应</option><option value="unavailable">核心/流量不可用</option><option value="conflict">写入时版本冲突</option><option value="job-failed">后台任务失败</option></select></label><button id="preview-reset" type="button">重置脱敏样例</button><span id="preview-status" role="status">正在加载生产模块…</span></div></aside><main id="view"></main><pre id="preview-error" role="alert"></pre><script>window.PREVIEW_MODULES=${payload};<\/script><script>${runtime.replace(/<\/script/gi, '<\\/script')}<\/script></body></html>`;
const childJson = JSON.stringify(child).replace(/</g, '\\u003c');
const html = `<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>AlwayRoute 浏览器预览</title><style>body{margin:0;background:#dae3e9;font:14px system-ui,sans-serif}header{padding:12px 18px;background:#193d50;color:white;display:flex;align-items:center;gap:12px;flex-wrap:wrap}header button{font:inherit;padding:6px 12px;cursor:pointer}iframe{display:block;border:0;width:100%;height:calc(100vh - 62px);min-height:700px;margin:auto;background:#f3f6f8;box-shadow:0 0 22px #15283820}iframe.mobile{width:390px;max-width:100%}</style><body><header><strong>AlwayRoute 真实 DOM 预览</strong><button id="desktop" type="button">桌面 / 自适应</button><button id="mobile" type="button">手机 · 390px</button><span>无需服务器；此文件包含测试模拟器</span></header><iframe id="preview-frame" title="AlwayRoute 测试预览"></iframe><script>const frame=document.getElementById('preview-frame');frame.srcdoc=${childJson};document.getElementById('desktop').onclick=()=>frame.classList.remove('mobile');document.getElementById('mobile').onclick=()=>frame.classList.add('mobile');<\/script></body></html>`;
fs.mkdirSync(path.dirname(output), { recursive: true });
fs.writeFileSync(output, html, 'utf8');
console.log(output);
console.log('Generated offline HTML only; no listener, device connection, or browser was started.');
