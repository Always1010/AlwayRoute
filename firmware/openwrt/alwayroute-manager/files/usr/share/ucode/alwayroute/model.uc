'use strict';

export function fail(code, message) { die('ALWAYROUTE:'+code+':'+message); };
export function clone(value) { return json(sprintf('%J', value)); };
function require(ok, message) { if (!ok) fail('INVALID_MODEL', message); }
function fields(value, allowed) {
 require(type(value) == 'object', '需要对象');
 for (let k in keys(value)) require(index(allowed, k) >= 0, '存在不支持的字段');
};
function text(value, max) {
 if(type(value)!='string' || !length(value) || length(value)>max)return false;
 for(let c in split(value,''))if(ord(c)<32 || ord(c)==127)return false;
 return true;
};
function id(value) { return type(value) == 'string' && match(value, /^[A-Za-z0-9_-]{1,64}$/) != null; }
function integer(value, min, max) { return type(value) == 'int' && value >= min && value <= max; }
const POLICY_VERSION = 1;
const POLICIES = [
 {id:'Proxy',name:'代理',default:true,description:'未命中业务组的常用境外网站',domains:['github.com','githubassets.com','githubusercontent.com','github.io','netflix.com','nflxext.com','nflximg.com','nflxso.net','nflxvideo.net','disneyplus.com','disney-plus.net','dssott.com','spotify.com','scdn.co','reddit.com','redd.it','wikipedia.org','wikimedia.org','twitch.tv','medium.com','stackoverflow.com']},
 {id:'OpenAI',name:'OpenAI',default:true,description:'OpenAI、ChatGPT 及静态内容',domains:['openai.com','chatgpt.com','oaistatic.com','oaiusercontent.com']},
 {id:'Claude',name:'Claude',default:true,description:'Anthropic 与 Claude',domains:['anthropic.com','claude.ai','claude.com']},
 {id:'Google',name:'Google',default:true,description:'Google 通用服务；YouTube 规则优先',domains:['google.com','googleapis.com','gstatic.com','googleusercontent.com','googleadservices.com','google-analytics.com','withgoogle.com','blogger.com','blogspot.com']},
 {id:'YouTube',name:'YouTube',default:true,description:'YouTube 页面、短链、视频与静态内容',domains:['youtube.com','youtu.be','youtube-nocookie.com','googlevideo.com','ytimg.com']},
 {id:'X',name:'X',default:true,description:'X（原 Twitter）页面、短链与静态内容',domains:['x.com','twitter.com','t.co','twimg.com']},
 {id:'Telegram',name:'Telegram',default:true,description:'Telegram 官方网页与公开链接',domains:['telegram.org','telegram.me','telegram.dog','t.me','telesco.pe','telegra.ph']},
 {id:'Other',name:'Other',default:true,description:'所有规则均未命中时的最终出口',domains:[]},
 {id:'Microsoft',name:'Microsoft',default:false,description:'Microsoft、Microsoft 365 与常用消费服务',domains:['microsoft.com','microsoftonline.com','live.com','office.com','office365.com','outlook.com','windows.com','azure.com','bing.com','xbox.com','cloud.microsoft','static.microsoft','usercontent.microsoft']},
 {id:'Apple',name:'Apple',default:false,description:'Apple、iCloud、商店与静态内容',domains:['apple.com','icloud.com','icloud-content.com','itunes.apple.com','apps.apple.com','mzstatic.com','cdn-apple.com','apple-dns.net']},
 {id:'Meta',name:'Meta',default:false,description:'Meta、Facebook、Instagram 与 WhatsApp',domains:['meta.com','facebook.com','fb.com','fbcdn.net','instagram.com','cdninstagram.com','whatsapp.com','whatsapp.net']},
 {id:'Discord',name:'Discord',default:false,description:'Discord 页面、API 与内容分发',domains:['discord.com','discord.gg','discordapp.com','discordapp.net']},
 {id:'Steam',name:'Steam',default:false,description:'Steam 商店、社区、内容与 API',domains:['steampowered.com','steamcommunity.com','steamstatic.com','steamcontent.com','steamserver.net','steam-api.com','valvesoftware.com']}
];
export function policyCatalog() { return clone(POLICIES); };
function policyDomains(id) {
 let domains=[],seen={};
 for(let p in POLICIES)if(id=='Proxy' || p.id==id)for(let domain in p.domains)if(!seen[domain]){push(domains,domain);seen[domain]=true;}
 return domains;
};
export function empty() {
 return { schema: 1, policyVersion: POLICY_VERSION, revision: 0, mode: 'rule', defaultOutbound: 'Other', nodes: [], subscriptions: [], overrides: {},
 groups: [{id:'Proxy',name:'代理',selected:'direct'}, {id:'OpenAI',name:'OpenAI',selected:'Proxy'},
 {id:'Claude',name:'Claude',selected:'Proxy'}, {id:'Google',name:'Google',selected:'Proxy'},
 {id:'YouTube',name:'YouTube',selected:'Proxy'}, {id:'X',name:'X',selected:'Proxy'},
 {id:'Telegram',name:'Telegram',selected:'Proxy'}, {id:'Other',name:'Other',selected:'direct'}], rules: [] };
};
function legacyFallback(m) {
 let target=m.defaultOutbound;
 if(target=='Proxy')return target;
 if(type(m.groups)!='array')return target;
 for(let g in m.groups)if(g.id==target)return g.selected;
 return target;
};
export function normalize(m) {
 let n=clone(m);
 if(type(n)!='object' || n.policyVersion==POLICY_VERSION)return n;
 if(n.policyVersion!=null)return n;
 if(type(n.groups)!='array' || type(n.rules)!='array')return n;
 let fallback=legacyFallback(n), merged={GitHub:true,Netflix:true,Disney:true,Spotify:true}, kept=[];
 for(let g in n.groups)if(!merged[g.id])push(kept,g);
 for(let g in kept)if(merged[g.selected])g.selected='Proxy';
 for(let r in n.rules)if(merged[r.outbound])r.outbound='Proxy';
 n.groups=kept;
 let present={};for(let g in n.groups)present[g.id]=true;
 if(!present.Other && length(n.groups)<16){push(n.groups,{id:'Other',name:'Other',selected:fallback});present.Other=true;}
 else if(present.Other)for(let g in n.groups)if(g.id=='Other')g.selected=fallback;
 for(let p in POLICIES)if(p.default && p.id!='Other' && !present[p.id] && length(n.groups)<16){push(n.groups,{id:p.id,name:p.name,selected:p.id=='Proxy'?'direct':'Proxy'});present[p.id]=true;}
 if(!present.Other)fail('MIGRATION_REQUIRED','策略组已满，无法在不删除自定义组的情况下添加 Other');
 let ordered=[],orderedIds={};
 for(let p in POLICIES)if(p.default && p.id!='Other')for(let g in n.groups)if(g.id==p.id){push(ordered,g);orderedIds[g.id]=true;}
 for(let g in n.groups)if(g.id!='Other' && !orderedIds[g.id])push(ordered,g);
 for(let g in n.groups)if(g.id=='Other')push(ordered,g);
 n.groups=ordered;n.defaultOutbound='Other';n.policyVersion=POLICY_VERSION;
 return n;
};
export function node(n) {
 fields(n, ['id','name','type','enabled','source','sourceKey','server','port','uuid','security','alterId','tls','transport']);
 require(id(n.id) && text(n.name,128) && type(n.enabled) == 'bool', '节点标识、名称或开关无效');
 if (n.type != 'vmess') fail('UNSUPPORTED_PROTOCOL', '首版仅支持 VMess');
 require(n.source == null || id(n.source), '节点来源无效');
 require(text(n.server,253) && match(n.server, /^[A-Za-z0-9._:-]+$/), '服务器地址无效');
 require(integer(n.port,1,65535), '端口必须为 1..65535');
 require(type(n.uuid) == 'string' && match(n.uuid,/^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$/), 'VMess UUID 无效');
 require(index(['auto','aes-128-gcm','chacha20-poly1305','none','zero'],n.security ?? 'auto') >= 0, 'VMess 加密方式不支持');
 require(integer(n.alterId ?? 0,0,65535), 'alterId 无效');
 if (n.tls != null) {
  fields(n.tls,['enabled','serverName']);
  require(type(n.tls.enabled) == 'bool' && (n.tls.serverName == null || (text(n.tls.serverName,253) && match(n.tls.serverName,/^[A-Za-z0-9._-]+$/))), 'TLS 参数无效');
 }
 if (n.transport != null) {
  fields(n.transport,['type','path','host']);
  require(n.transport.type == 'ws', '首版仅支持 TCP 或 WebSocket 传输');
  require(n.transport.path == null || text(n.transport.path,1024), 'WebSocket 路径无效');
  require(n.transport.host == null || text(n.transport.host,253), 'WebSocket Host 无效');
 }
 return n;
};
export function effective(m) {
 let result = [];
 for (let original in m.nodes) {
  let n = clone(original), o = m.overrides[n.id];
  if (o?.excluded) continue;
  if (o?.name != null) n.name = o.name;
  if (o?.patch) for (let k,v in o.patch) n[k] = v;
  node(n);
  if (n.enabled) push(result,n);
 }
 return result;
};
export function validate(m) {
 fields(m,['schema','policyVersion','revision','mode','defaultOutbound','nodes','subscriptions','overrides','groups','rules']);
 require(m.schema == 1 && m.policyVersion == POLICY_VERSION && integer(m.revision,0,2147483646), '模型版本无效');
 require(index(['rule','global','direct'],m.mode)>=0,'模式无效');
 for (let key,limit in {nodes:128,subscriptions:16,groups:16,rules:128}) require(type(m[key])=='array' && length(m[key])<=limit,'数量超限或列表无效');
 require(type(m.overrides)=='object' && length(keys(m.overrides)) <= 128,'覆盖设置无效');
 let ids = {direct:true,block:true}, sourceIds = {};
 for (let s in m.subscriptions) {
  fields(s,['id','name','url','enabled','intervalHours','allowHttp','lastUpdate','lastError']);
  require(id(s.id) && !sourceIds[s.id] && length(s.id)<=20 && text(s.name,128),'订阅标识无效或重复'); sourceIds[s.id]=true;
  require(type(s.enabled)=='bool' && integer(s.intervalHours,0,168),'订阅开关或周期无效');
  require(s.allowHttp==null || type(s.allowHttp)=='bool','HTTP 例外必须为布尔开关');
  let schemeAllowed=type(s.url)=='string' && (index(s.url,'https://')==0 || (s.allowHttp===true && index(s.url,'http://')==0));
  require(text(s.url,2048) && schemeAllowed && !match(s.url,/[ "'<>\\]/),'订阅需要 HTTPS；HTTP 须对此订阅显式允许');
 }
 for (let n in m.nodes) { node(n); require(!ids[n.id],'节点ID重复'); ids[n.id]=true; require(n.source == null || sourceIds[n.source], '节点引用未知订阅'); }
 for (let key,o in m.overrides) {
  require(id(key),'覆盖标识无效'); fields(o,['excluded','name','patch']);
  require(o.excluded == null || type(o.excluded)=='bool','排除开关无效');
  require(o.name == null || text(o.name,128),'覆盖名称无效');
  if(o.patch) fields(o.patch,['server','port','uuid','security','alterId','tls','transport']);
 }
 let usable={direct:true,block:true}; for(let n in effective(m)) usable[n.id]=true;
 let groupIds={};
 for (let g in m.groups) {
  fields(g,['id','name','selected']); require(id(g.id) && !ids[g.id] && !groupIds[g.id] && text(g.name,128),'策略组标识重复或无效');
  groupIds[g.id]=true;
 }
 require(groupIds.Proxy && groupIds.Other && m.groups[length(m.groups)-1].id=='Other', '必须保留 Proxy，并将 Other 保持在最后');
 for(let g in m.groups) require((g.selected!='block' && usable[g.selected]) || (g.id!='Proxy' && g.selected=='Proxy') || (g.id=='Other' && g.selected=='block'), '策略组选择不存在、被停用或形成循环');
 for(let k in keys(groupIds)) usable[k]=true;
 require(m.defaultOutbound=='Other', '默认出口必须由 Other 策略组管理');
 let ruleIds={};
 for(let r in m.rules) {
  fields(r,['id','enabled','type','value','outbound']);
  require(id(r.id) && !ruleIds[r.id] && type(r.enabled)=='bool','规则标识或开关无效'); ruleIds[r.id]=true;
  require(usable[r.outbound] && text(r.value,253),'规则出口或值无效');
  require(index(['domain','suffix','ip','cidr'],r.type)>=0,'规则类型不支持');
  if(r.type=='ip' || r.type=='cidr') {
   let parts=split(r.value,'/'), octets=split(parts[0],'.');
   require(length(octets)==4 && length(parts)==(r.type=='cidr'?2:1),'仅支持 IPv4/IP CIDR');
   for(let octet in octets) require(match(octet,/^[0-9]{1,3}$/) && int(octet)<=255,'IPv4 地址无效');
   if(r.type=='cidr') require(match(parts[1],/^[0-9]{1,2}$/) && int(parts[1])<=32,'CIDR 前缀无效');
  } else require(match(r.value,/^[A-Za-z0-9._-]+$/),'域名规则无效');
 }
 require(length(sprintf('%J',m))<=131072,'配置超过128KiB');
 return m;
};
export function generate(m) {
 validate(m);
 let outbounds=[{type:'direct',tag:'direct'}], choices=['direct'], rules=[{port:53,action:'hijack-dns'},{action:'sniff'}],dnsRules=[];
 let selections={};for(let g in m.groups)selections[g.id]=g.selected;
 function domainDns(rule, target) {
  // Validation permits only one group reference: a non-Proxy group may follow Proxy.
  target=selections[target] ?? target;
  if(target=='Proxy')target=selections.Proxy;
  let d={server:target=='direct'?'bootstrap':'proxy-dns'};
  for(let key,value in rule)d[key]=value;
  push(dnsRules,d);
 }
 for(let n in effective(m)) {
  let o={type:'vmess',tag:n.id,server:n.server,server_port:n.port,uuid:n.uuid,security:n.security ?? 'auto',alter_id:n.alterId ?? 0};
  if(n.tls?.enabled) o.tls={enabled:true,server_name:n.tls.serverName ?? n.server};
  if(n.transport) o.transport={type:'ws',path:n.transport.path ?? '/',headers: n.transport.host ? {Host:n.transport.host}: {}};
  push(outbounds,o);push(choices,n.id);
 }
 for(let g in m.groups) {
  let selected=g.selected=='block'?'direct':g.selected,members=clone(choices);
  if(g.id!='Proxy' && index(members,'Proxy')<0)push(members,'Proxy');
  push(outbounds,{type:'selector',tag:g.id,outbounds:members,default:selected,interrupt_exist_connections:false});
 }
 if(m.mode=='rule') for(let r in m.rules) {
  if(!r.enabled) continue;
  let rule={}; rule[r.type=='domain'?'domain':r.type=='suffix'?'domain_suffix':'ip_cidr']=[r.type=='ip'?r.value+'/32':r.value];
  if(r.outbound=='block') rule.action='reject'; else {rule.action='route';rule.outbound=r.outbound;}
  push(rules,rule);
  if(r.type=='domain' || r.type=='suffix') {let d={};d[r.type=='domain'?'domain':'domain_suffix']=[r.value];domainDns(d,r.outbound);}
 }
 if(m.mode=='rule') {
  let groupIds={};for(let g in m.groups)groupIds[g.id]=true;
  for(let wanted in ['OpenAI','Claude','YouTube','Google','X','Telegram','Microsoft','Apple','Meta','Discord','Steam','Proxy']) {
   let domains=policyDomains(wanted);
   if(groupIds[wanted] && length(domains)) {
    push(rules,{domain_suffix:domains,action:'route',outbound:wanted});
    domainDns({domain_suffix:domains},wanted);
   }
  }
 }
 let final=m.mode=='direct'?'direct':m.mode=='global'?'Proxy':'Other';
 if(m.mode=='rule')for(let g in m.groups)if(g.id=='Other' && g.selected=='block'){push(rules,{action:'reject'});final='direct';}
 return {log:{disabled:true},inbounds:[{type:'mixed',tag:'local-mixed',listen:'127.0.0.1',listen_port:7890},
 {type:'tproxy',tag:'lan-tproxy',listen:'0.0.0.0',listen_port:7893}],outbounds,
 dns:{servers:[{type:'local',tag:'bootstrap'},{type:'https',tag:'proxy-dns',server:'1.1.1.1',tls:{enabled:true,server_name:'cloudflare-dns.com'},detour:'Proxy'}],rules:dnsRules,final:m.mode=='direct'?'bootstrap':'proxy-dns',reverse_mapping:true,strategy:'ipv4_only',cache_capacity:512},
 route:{rules,final,auto_detect_interface:true,default_domain_resolver:'bootstrap'},experimental:{clash_api:{external_controller:'127.0.0.1:9090',default_mode:m.mode=='direct'?'Direct':m.mode=='global'?'Global':'Rule'}}};
};
