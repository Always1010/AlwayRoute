'use strict';
import { sha256 } from 'digest';
import { empty,validate,generate,clone,effective,normalize,policyCatalog } from 'alwayroute.model';
import { parse } from 'alwayroute.subscription';

let checks=0;
function check(ok,message){checks++;assert(ok,message);}
function rejected(fn,message){let failed=false;try{fn();}catch(e){failed=true;}check(failed,message);}
function group(model,id){for(let g in model.groups)if(g.id==id)return g;}
function outbound(config,id){for(let o in config.outbounds)if(o.tag==id)return o;}
function routeIndex(rules,id){for(let i=0;i<length(rules);i++)if(rules[i].outbound==id)return i;return -1;}
let uuid='00000000-0000-4000-8000-000000000001';
let source={v:'2',ps:'Sample',add:'example.invalid',port:'443',id:uuid,aid:'0',net:'ws',type:'none',host:'example.invalid',path:'/vmess',tls:'tls',sni:'example.invalid'};
let uri='vmess://'+b64enc(sprintf('%J',source));
let nodes=parse(uri,'demo',sha256),m=empty();
check(join(',',map(m.groups,g=>g.id))=='Proxy,OpenAI,Claude,Google,YouTube,X,Telegram,Other','new model has ordered default policy groups');
let catalog=policyCatalog();
check(length(catalog)==13 && catalog[0].id=='Proxy' && catalog[0].default && !catalog[8].default,'policy catalog exposes default and optional services');
check(index(catalog[0].domains,'github.com')>=0 && index(catalog[0].domains,'netflix.com')>=0 && index(catalog[0].domains,'spotify.com')>=0,'merged services have real Proxy match domains');
check(length(nodes)==1 && nodes[0].transport.type=='ws','VMess URI imports');
m.subscriptions=[{id:'demo',name:'Demo',url:'https://example.invalid/sub',enabled:true,intervalHours:24}];m.nodes=nodes;
let insecure=clone(m);insecure.subscriptions[0].url='http://example.invalid/sub';
rejected(()=>validate(insecure),'HTTP rejected without per-subscription flag');
insecure.subscriptions[0].allowHttp=false;rejected(()=>validate(insecure),'HTTP rejected when exception disabled');
insecure.subscriptions[0].allowHttp=true;check(validate(insecure).subscriptions[0].allowHttp,'explicit HTTP exception accepted');
insecure.subscriptions[0].allowHttp='true';rejected(()=>validate(insecure),'HTTP exception requires boolean true');
insecure.subscriptions[0].url='https://example.invalid/sub';insecure.subscriptions[0].allowHttp=false;check(validate(insecure).schema==1,'HTTPS remains valid with exception disabled');
m.groups[0].selected=nodes[0].id;validate(m);
let config=generate(m);check(config.outbounds[1].server_port==443,'typed VMess config');
check(config.experimental.clash_api.external_controller=='127.0.0.1:9090','API loopback only');
check(config.route.final=='Other' && outbound(config,'Other').default=='direct','Other is the rule-mode fallback and defaults direct');
source.ps='Renamed';check(parse('vmess://'+b64enc(sprintf('%J',source)),'demo',sha256)[0].id==nodes[0].id,'name changes keep stable IDs');
check(parse(b64enc(uri),'demo',sha256)[0].id==nodes[0].id,'base64 subscription');
m.overrides[nodes[0].id]={name:'Local',patch:{port:8443}};check(effective(m)[0].port==8443 && effective(m)[0].name=='Local','independent override');
let yamlSample='proxies:\n  - name: Sample\n    type: vmess\n    server: example.invalid\n    port: 443\n    uuid: '+uuid+'\n    alterId: 0\n    cipher: auto\n    tls: true\n    network: ws\n    ws-opts:\n      path: /vmess\n      headers:\n        Host: example.invalid\n';
check(parse(yamlSample,'demo',sha256)[0].id==nodes[0].id,'strict YAML block imports');
rejected(()=>parse('proxies:\n  - { name: x, type: vmess }','demo',sha256),'incomplete flow node rejected');
let flowFixture='port: 7890\nsocks-port: 7891\nredir-port: 7892\nallow-lan: true\nmode: global\nlog-level: debug\nexternal-controller: 0.0.0.0:9090\nsecret: synthetic-fixture-only\nproxies:\n  - { "name": "Sample, colon: value\\\"quoted", type: vmess, server: example.invalid, port: 443, uuid: '+uuid+', alterId: 0, cipher: auto, udp: true }\nproxy-groups:\n  - { name: dangerous, type: select, proxies: [DIRECT] }\nrules:\n  - MATCH,DIRECT\n';
let flowNodes=parse(flowFixture,'demo',sha256);
check(length(flowNodes)==1 && flowNodes[0].id==nodes[0].id,'complete Clash flow config extracts stable nodes only');
check(flowNodes[0].name=='Sample, colon: value"quoted','flow scanner preserves quoted comma colon and escapes');
let updated=clone(m);updated.nodes=flowNodes;check(effective(updated)[0].name=='Local' && effective(updated)[0].port==8443,'flow update preserves independent local override');
check(index(sprintf('%J',generate(updated)),'synthetic-fixture-only')<0 && generate(updated).experimental.clash_api.external_controller=='127.0.0.1:9090','Clash system settings and credentials never pass through');
check(length(parse(replace(flowFixture,'\n  - {','\n- {'),'demo',sha256))==1,'indentless flow sequence supported');
rejected(()=>parse(replace(flowFixture,'cipher: auto','cipher: { nested: value }'),'demo',sha256),'nested flow structure rejected');
rejected(()=>parse(replace(flowFixture,'cipher: auto','cipher: &anchor auto'),'demo',sha256),'flow anchor rejected');
rejected(()=>parse(flowFixture+'proxies:\n','demo',sha256),'duplicate proxies block rejected');
rejected(()=>parse(replace(yamlSample,'    tls: true','    skip-cert-verify: true'),'demo',sha256),'unsafe TLS option rejected');
rejected(()=>parse(replace(yamlSample,'    cipher: auto','    surprise: value'),'demo',sha256),'unknown field rejected');
rejected(()=>parse(replace(uri,'vmess://','vless://'),'demo',sha256),'unsupported scheme rejected');
let broken=clone(m);broken.nodes=[];rejected(()=>validate(broken),'selected missing node rejected');
broken=clone(m);broken.groups[0].selected='Netflix';rejected(()=>validate(broken),'selector cycle rejected');
broken=clone(m);broken.nodes[0].command='touch /tmp/unsafe';rejected(()=>validate(broken),'config passthrough rejected');
broken=clone(m);broken.overrides[nodes[0].id].excluded=true;rejected(()=>validate(broken),'exclude selected node rejected');
m.rules=[{id:'block_ads',enabled:true,type:'suffix',value:'ads.example.invalid',outbound:'block'},
 {id:'youtube_override',enabled:true,type:'suffix',value:'youtube.com',outbound:'direct'},
 {id:'private',enabled:true,type:'cidr',value:'10.0.0.0/8',outbound:'direct'}];
check(generate(m).route.rules[2].action=='reject','block uses sing-box route action');
let orderedRules=generate(m).route.rules;
check(orderedRules[3].outbound=='direct' && routeIndex(orderedRules,'YouTube')>3,'custom domain rule precedes matching built-in service');
check(routeIndex(orderedRules,'YouTube')<routeIndex(orderedRules,'Google') && routeIndex(orderedRules,'Proxy')>routeIndex(orderedRules,'Telegram'),'YouTube precedes Google and Proxy follows business groups');
let optional=clone(m),other=pop(optional.groups);push(optional.groups,{id:'Discord',name:'Discord',selected:'Proxy'});push(optional.groups,other);
check(routeIndex(generate(optional).route.rules,'Discord')>0,'optional catalog group emits its domain rule when present');
let misplaced=clone(m);push(misplaced.groups,shift(misplaced.groups));rejected(()=>validate(misplaced),'Other must remain the final policy group');
let blocked=clone(m);group(blocked,'Other').selected='block';let blockedConfig=generate(blocked);
check(blockedConfig.route.final=='direct' && blockedConfig.route.rules[length(blockedConfig.route.rules)-1].action=='reject' && outbound(blockedConfig,'Other').default=='direct','Other block fallback becomes a terminal reject without invalid selector members');

let legacy=clone(m);delete legacy.policyVersion;legacy.defaultOutbound='Netflix';
legacy.groups=[{id:'Proxy',name:'代理',selected:nodes[0].id},{id:'OpenAI',name:'OpenAI',selected:'Proxy'},
 {id:'Netflix',name:'Netflix',selected:'Proxy'},{id:'Disney',name:'Disney+',selected:'direct'},
 {id:'Custom',name:'自定义',selected:nodes[0].id}];
legacy.rules=[{id:'old_disney',enabled:true,type:'suffix',value:'example.invalid',outbound:'Disney'}];
let migrated=normalize(legacy);
check(migrated.policyVersion==1 && migrated.defaultOutbound=='Other' && group(migrated,'Other').selected=='Proxy','legacy fallback moves to Other');
check(!group(migrated,'Netflix') && !group(migrated,'Disney') && group(migrated,'Custom').selected==nodes[0].id && migrated.groups[length(migrated.groups)-1].id=='Other','migration removes merged fixed groups, preserves custom groups and keeps Other last');
check(migrated.rules[0].outbound=='Proxy' && validate(migrated).schema==1,'migration redirects rules that referenced merged groups');
let legacyProxy=clone(legacy);legacyProxy.defaultOutbound='Proxy';
check(group(normalize(legacyProxy),'Other').selected=='Proxy','legacy Proxy fallback keeps following the Proxy selector');
let noReadd=clone(migrated);noReadd.groups=filter(noReadd.groups,g=>g.id!='Claude');
check(!group(normalize(noReadd),'Claude'),'policy version prevents deleted built-in groups from being re-added');
let legacyBlock=clone(legacy);legacyBlock.defaultOutbound='block';
check(group(normalize(legacyBlock),'Other').selected=='block','legacy block fallback is preserved exactly');
let fullLegacy=clone(legacy);fullLegacy.groups=[{id:'Proxy',name:'代理',selected:'direct'}];
for(let i=0;i<15;i++)push(fullLegacy.groups,{id:'Custom'+i,name:'自定义'+i,selected:'Proxy'});
rejected(()=>normalize(fullLegacy),'full legacy group set is rejected instead of deleting a custom group');
m.mode='global';check(length(generate(m).route.rules)==2 && generate(m).route.final=='Proxy','global mode bypasses user rules');
m.mode='direct';check(length(generate(m).route.rules)==2 && generate(m).route.final=='direct' && generate(m).dns.final=='bootstrap','direct mode bypasses policy rules and proxy DNS');
printf('PASS %d manager contract checks\n',checks);
