'use strict';
import { sha256 } from 'digest';
import { empty,validate,generate,generateRuntimeValidated,clone,effective,normalize,policyCatalog } from 'alwayroute.model';
import { parse } from 'alwayroute.subscription';

let checks=0;
function check(ok,message){checks++;assert(ok,message);}
function rejected(fn,message){let failed=false;try{fn();}catch(e){failed=true;}check(failed,message);}
function group(model,id){for(let g in model.groups)if(g.id==id)return g;}
function outbound(config,id){for(let o in config.outbounds)if(o.tag==id)return o;}
function routeIndex(rules,id){for(let i=0;i<length(rules);i++)if(rules[i].outbound==id)return i;return -1;}
function route(rules,id){let i=routeIndex(rules,id);return i<0?null:rules[i];}
let uuid='00000000-0000-4000-8000-000000000001';
let source={v:'2',ps:'Sample',add:'example.invalid',port:'443',id:uuid,aid:'0',net:'ws',type:'none',host:'example.invalid',path:'/vmess',tls:'tls',sni:'example.invalid'};
let uri='vmess://'+b64enc(sprintf('%J',source));
let nodes=parse(uri,'demo',sha256),m=empty();
check(join(',',map(m.groups,g=>g.id))=='Proxy,OpenAI,Claude,Google,YouTube,TikTok,X,Telegram,Domestic,Other','new model has ordered default policy groups');
let catalog=policyCatalog();
check(length(catalog)==15 && catalog[0].id=='Proxy' && catalog[0].default && !catalog[10].default,'policy catalog exposes default and optional services');
check(index(catalog[0].domains,'github.com')>=0 && index(catalog[0].domains,'netflix.com')>=0 && index(catalog[0].domains,'spotify.com')>=0,'merged services have real Proxy match domains');
check(length(nodes)==1 && nodes[0].transport.type=='ws','VMess URI imports');
m.subscriptions=[{id:'demo',name:'Demo',url:'https://example.invalid/sub',enabled:true,intervalHours:24}];m.nodes=nodes;
let insecure=clone(m);insecure.subscriptions[0].url='http://example.invalid/sub';
rejected(()=>validate(insecure),'HTTP rejected without per-subscription flag');
insecure.subscriptions[0].allowHttp=false;rejected(()=>validate(insecure),'HTTP rejected when exception disabled');
insecure.subscriptions[0].allowHttp=true;check(validate(insecure).subscriptions[0].allowHttp,'explicit HTTP exception accepted');
insecure.subscriptions[0].allowHttp='true';rejected(()=>validate(insecure),'HTTP exception requires boolean true');
insecure.subscriptions[0].url='https://example.invalid/sub';insecure.subscriptions[0].allowHttp=false;check(validate(insecure).schema==1,'HTTPS remains valid with exception disabled');
for(let url in ['https:///missing-host','https://#fragment','https://?query','https://user@:443/sub','https://:443/sub']){insecure.subscriptions[0].url=url;rejected(()=>validate(insecure),'subscription URL requires a nonempty authority and host: '+url);}
insecure.subscriptions[0].url=' HTTPS://user:pass@example.test/sub?token=%2fA+z#keep ';
let canonical=normalize(insecure);check(validate(insecure).schema==1 && canonical.subscriptions[0].url=='https://user:pass@example.test/sub?token=%2fA+z#keep','uppercase HTTPS and surrounding whitespace normalize only scheme without rewriting URL credentials or signed query');
insecure.subscriptions[0].url=' HTTP://example.test/sub ';rejected(()=>validate(insecure),'uppercase HTTP still requires an explicit exception');
insecure.subscriptions[0].allowHttp=true;check(validate(normalize(insecure)).subscriptions[0].url=='http://example.test/sub','explicit HTTP exception accepts a normalized uppercase scheme');
for(let url in ['https://example.test:8443/sub','https://[::1]/sub','https://[::1]:8443/sub']){insecure.subscriptions[0].url=url;check(validate(insecure).schema==1,'subscription accepts hostname and IPv6 authorities with optional port');}
m.groups[0].selected=nodes[0].id;validate(m);
let config=generate(m);check(config.outbounds[1].server_port==443,'typed VMess config');
check(config.dns.cache_capacity==1024,'DNS budget matches the pinned core minimum of 1024 entries');
check(config.experimental.clash_api.external_controller=='127.0.0.1:9090','API loopback only');
check(join(',',config.experimental.clash_api.access_control_allow_origin)=='http://127.0.0.1' && config.experimental.clash_api.secret==null,'public generation restricts CORS to loopback and never contains the internal API secret');
let runtimeConfig=generateRuntimeValidated(m,'00000000-0000-4000-8000-000000000099');
check(runtimeConfig.experimental.clash_api.secret=='00000000-0000-4000-8000-000000000099' && config.experimental.clash_api.secret==null,'runtime generation adds a secret without mutating the pure generated config');
check(config.route.final=='Other' && outbound(config,'Other').default=='direct','Other is the rule-mode fallback and defaults direct');
check(config.route.rules[0].action=='hijack-dns' && config.route.rules[0].port==53 && config.route.rules[1].action=='sniff' && join(',',config.route.rules[1].sniffer)=='http,tls,quic','DNS hijack precedes only the hostname sniffers needed for routing');
check(join(',',outbound(config,'Proxy').outbounds)=='direct,'+nodes[0].id && join(',',outbound(config,'OpenAI').outbounds)=='direct,'+nodes[0].id+',Proxy','every selector includes all effective nodes, even those not currently selected');
source.ps='Renamed';check(parse('vmess://'+b64enc(sprintf('%J',source)),'demo',sha256)[0].id==nodes[0].id,'name changes keep stable IDs');
let variants=[uri];
for(let field,value in {scy:'aes-128-gcm',aid:'1',path:'/other',host:'other.invalid',sni:'tls.invalid',tls:''}) {let v=clone(source);v[field]=value;push(variants,'vmess://'+b64enc(sprintf('%J',v)));}
let tcp=clone(source);tcp.net='tcp';push(variants,'vmess://'+b64enc(sprintf('%J',tcp)));
let distinct=parse(join('\n',variants),'demo',sha256),distinctIds={};for(let n in distinct)distinctIds[n.id]=true;
check(length(distinct)==8 && length(keys(distinctIds))==8,'security alterId WS path Host TLS SNI and transport each distinguish connection identities');
rejected(()=>parse(uri+'\n'+'vmess://'+b64enc(sprintf('%J',source)),'demo',sha256),'renamed duplicate connections remain rejected');
let legacyNodes=clone(nodes);legacyNodes[0].sourceKey=substr(sha256(sprintf('%J',['vmess',lc(source.add),443,lc(uuid)])),0,24);legacyNodes[0].id='s_demo_'+legacyNodes[0].sourceKey;
let legacyRefresh=clone(m);legacyRefresh.nodes=legacyNodes;legacyRefresh.groups[0].selected=legacyNodes[0].id;legacyRefresh.overrides={};legacyRefresh.overrides[legacyNodes[0].id]={name:'Kept override',patch:{port:8443}};
legacyRefresh.rules=[{id:'legacy_ref',enabled:true,type:'domain',value:'selected.invalid',outbound:legacyNodes[0].id}];
legacyRefresh.nodes=parse(join('\n',variants),'demo',sha256,legacyNodes);
check(validate(legacyRefresh).nodes[0].id==legacyNodes[0].id && legacyRefresh.nodes[0].sourceKey==legacyNodes[0].sourceKey && effective(legacyRefresh)[0].name=='Kept override' && effective(legacyRefresh)[0].port==8443,'upgrade reuses exact legacy identity preserving selection rule references and local overrides alongside new variants');
let reordered=[];for(let i=length(variants)-1;i>=0;i--)push(reordered,variants[i]);
check(parse(join('\n',reordered),'demo',sha256,legacyRefresh.nodes)[7].id==legacyNodes[0].id,'refresh ordering and display name changes retain migrated node identity');
check(parse(uri,'other',sha256,legacyNodes)[0].id!='s_demo_'+legacyNodes[0].sourceKey,'identity reuse never crosses subscription ownership');
check(parse(b64enc(uri),'demo',sha256)[0].id==nodes[0].id,'base64 subscription');
m.overrides[nodes[0].id]={name:'Local',patch:{port:8443}};check(effective(m)[0].port==8443 && effective(m)[0].name=='Local','independent override');
let yamlSample='proxies:\n  - name: Sample\n    type: vmess\n    server: example.invalid\n    port: 443\n    uuid: '+uuid+'\n    alterId: 0\n    cipher: auto\n    tls: true\n    network: ws\n    ws-opts:\n      path: /vmess\n      headers:\n        Host: example.invalid\n';
check(parse(yamlSample,'demo',sha256)[0].id==nodes[0].id,'strict YAML block imports');
rejected(()=>parse('proxies:\n  - { name: x, type: vmess }','demo',sha256),'incomplete flow node rejected');
let flowFixture='port: 7890\nsocks-port: 7891\nredir-port: 7892\nallow-lan: true\nmode: global\nlog-level: debug\nexternal-controller: 0.0.0.0:9090\nsecret: synthetic-fixture-only\nproxies:\n  - { "name": "Sample, colon: value\\\"quoted", type: vmess, server: example.invalid, port: 443, uuid: '+uuid+', alterId: 0, cipher: auto, udp: true }\nproxy-groups:\n  - { name: dangerous, type: select, proxies: [DIRECT] }\nrules:\n  - MATCH,DIRECT\n';
let flowNodes=parse(flowFixture,'demo',sha256);
check(length(flowNodes)==1 && flowNodes[0].id!=nodes[0].id,'complete Clash flow config extracts a distinct TCP connection without importing settings');
check(flowNodes[0].name=='Sample, colon: value"quoted','flow scanner preserves quoted comma colon and escapes');
let updated=clone(m);updated.nodes=flowNodes;updated.groups[0].selected=flowNodes[0].id;updated.overrides={};updated.overrides[flowNodes[0].id]={name:'Local',patch:{port:8443}};
updated.nodes=parse(flowFixture,'demo',sha256,updated.nodes);check(effective(updated)[0].name=='Local' && effective(updated)[0].port==8443,'flow refresh preserves independent local override');
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
let dnsModel=clone(m);
dnsModel.rules=[{id:'exception',enabled:true,type:'domain',value:'overseas.example.cn',outbound:'YouTube'},
 {id:'domestic',enabled:true,type:'suffix',value:'cn',outbound:'Domestic'},
 {id:'disabled',enabled:false,type:'suffix',value:'disabled.invalid',outbound:'direct'},
 {id:'ip',enabled:true,type:'cidr',value:'192.0.2.0/24',outbound:'direct'}];
let dnsConfig=generate(dnsModel);
check(dnsConfig.dns.rules[0].domain[0]=='overseas.example.cn' && dnsConfig.dns.rules[0].server=='proxy-dns' && dnsConfig.dns.rules[1].domain_suffix[0]=='cn' && dnsConfig.dns.rules[1].server=='bootstrap','DNS preserves a proxy exception before a direct custom group suffix');
let domainRoutes=filter(dnsConfig.route.rules,r=>r.domain!=null || r.domain_suffix!=null || r.domain_regex!=null || r.rule_set?.[0]=='domestic-domain');
check(length(dnsConfig.dns.rules)==length(domainRoutes),'disabled, IP and resolve rules do not become domain DNS rules');
group(dnsModel,'Domestic').selected='Proxy';group(dnsModel,'Proxy').selected='direct';
check(generate(dnsModel).dns.rules[1].server=='bootstrap','DNS follows a custom group through Proxy to direct');
group(dnsModel,'Proxy').selected=nodes[0].id;
check(generate(dnsModel).dns.rules[1].server=='proxy-dns','DNS follows a changed group selection back to proxy');
group(dnsModel,'YouTube').selected='direct';dnsConfig=generate(dnsModel);
check(dnsConfig.dns.rules[0].server=='bootstrap' && dnsConfig.dns.rules[4].domain_suffix[0]=='youtube.com' && dnsConfig.dns.rules[4].server=='bootstrap','built-in direct groups and explicit overrides use local DNS in routing order');
for(let mode in ['global','direct']){dnsModel.mode=mode;check(length(generate(dnsModel).dns.rules)==0,'DNS custom and service rules are omitted in '+mode+' mode');}
let optional=clone(m),other=pop(optional.groups);push(optional.groups,{id:'Discord',name:'Discord',selected:'Proxy'});push(optional.groups,other);
check(routeIndex(generate(optional).route.rules,'Discord')>0,'optional catalog group emits its domain rule when present');
let baseRules=generate(m).route.rules;
check(index(route(baseRules,'Proxy').domain_suffix,'microsoft.com')>=0,'disabled optional service domains fall through to Proxy');
let withoutOpenAI=clone(m);withoutOpenAI.groups=filter(withoutOpenAI.groups,g=>g.id!='OpenAI');let withoutOpenAIRules=generate(withoutOpenAI).route.rules;
check(routeIndex(withoutOpenAIRules,'OpenAI')<0 && index(route(withoutOpenAIRules,'Proxy').domain_suffix,'openai.com')>=0,'deleted default service domains fall through to Proxy');
let misplaced=clone(m);push(misplaced.groups,shift(misplaced.groups));rejected(()=>validate(misplaced),'Other must remain the final policy group');
let blocked=clone(m);group(blocked,'Other').selected='block';let blockedConfig=generate(blocked);
check(blockedConfig.route.final=='direct' && blockedConfig.route.rules[length(blockedConfig.route.rules)-1].action=='reject' && outbound(blockedConfig,'Other').default=='direct' && join(',',outbound(blockedConfig,'Other').outbounds)=='direct,'+nodes[0].id+',Proxy','Other block fallback becomes a terminal reject while retaining all valid selector members');
blocked.rules=[{id:'other_domain',enabled:true,type:'domain',value:'blocked.invalid',outbound:'Other'},
 {id:'other_regex',enabled:true,type:'regex',value:'blocked\\.invalid$',outbound:'Other'},
 {id:'other_ip',enabled:true,type:'cidr',value:'192.0.2.0/24',outbound:'Other'},
 {id:'explicit_block',enabled:true,type:'suffix',value:'ads.invalid',outbound:'block'}];
blockedConfig=generate(blocked);
check(length(filter(blockedConfig.route.rules,r=>r.outbound=='Other'))==0 && blockedConfig.route.rules[2].action=='reject' && blockedConfig.route.rules[3].action=='reject' && blockedConfig.route.rules[4].action=='reject','manual domain regex and IP rules following blocked Other reject before any direct selector');
check(blockedConfig.dns.rules[0].action=='reject' && blockedConfig.dns.rules[1].action=='reject' && blockedConfig.dns.rules[2].action=='reject' && blockedConfig.dns.rules[length(blockedConfig.dns.rules)-1].action=='reject','explicit blocks and blocked Other reject matching DNS and the unmatched DNS fallback');
check(blockedConfig.route.rules[length(blockedConfig.route.rules)-3].action=='reject' && blockedConfig.route.rules[length(blockedConfig.route.rules)-3].ip_cidr[0]=='192.0.2.0/24','resolved domains recheck IP rules following blocked Other as reject');

let scale=clone(m);scale.nodes=[];scale.groups=[{id:'Proxy',name:'Proxy',selected:'n127'}];
for(let i=0;i<128;i++){let n=clone(nodes[0]);n.id='n'+i;n.name='Node '+i;push(scale.nodes,n);}
for(let i=0;i<14;i++)push(scale.groups,{id:'G'+i,name:'Group '+i,selected:i%2?'Proxy':'n'+i});
push(scale.groups,{id:'Other',name:'Other',selected:'block'});
scale.rules=[];for(let i=0;i<512;i++)push(scale.rules,{id:'r'+i,enabled:true,type:'suffix',value:'rule'+i+'.example.invalid',outbound:'direct'});
let scaleConfig=generate(scale),selectorMembers=0,complete=true,allChoices=['direct'];
for(let n in effective(scale))push(allChoices,n.id);
for(let g in scale.groups){let o=outbound(scaleConfig,g.id),selected=g.selected=='block'?'direct':g.selected,expected=clone(allChoices);if(g.id!='Proxy')push(expected,'Proxy');selectorMembers+=length(o.outbounds);if(o.default!=selected || index(o.outbounds,selected)<0 || join(',',o.outbounds)!=join(',',expected))complete=false;}
check(length(scaleConfig.outbounds)==145 && outbound(scaleConfig,'n127') && outbound(scaleConfig,'Proxy').default=='n127' && selectorMembers==2079 && complete,'128 nodes and 16 groups retain complete ordered memberships without duplicate Proxy references');
check(length(scaleConfig.route.rules)==516 && scaleConfig.route.rules[1].action=='sniff' && join(',',scaleConfig.route.rules[1].sniffer)=='http,tls,quic' && scaleConfig.route.rules[515].action=='reject','maximum rule model retains all 512 custom rules, hostname sniffing and terminal block fallback');
for(let mode in ['global','direct']){scale.mode=mode;let c=generate(scale);check(length(c.route.rules)==1 && c.route.rules[0].action=='hijack-dns' && c.route.final==(mode=='global'?'Proxy':'direct') && length(outbound(c,'Other').outbounds)==130,'maximum '+mode+' model skips sniffing and preserves complete selectors without applying custom rules or terminal reject');}

let multi=clone(m);multi.rules=[{id:'many',enabled:true,type:'suffix',values:['one.example.cn','two.example.cn'],outbound:'Domestic'},
 {id:'pattern',enabled:true,type:'regex',values:['(^|\\.)tiktokcdn(-us|-eu)?\\.com$'],outbound:'TikTok'}];
let multiConfig=generate(multi);
check(length(multiConfig.route.rules[2].domain_suffix)==2 && multiConfig.route.rules[3].domain_regex[0]==multi.rules[1].values[0] && multiConfig.dns.rules[0].server=='bootstrap' && multiConfig.dns.rules[1].server=='proxy-dns','multi-value and regex rules produce one matching route and DNS block each');
let badMulti=clone(multi);badMulti.rules[0].value='ambiguous.invalid';rejected(()=>validate(badMulti),'scalar and list values cannot be mixed');
badMulti=clone(multi);badMulti.rules[0].values=['same.invalid','same.invalid'];rejected(()=>validate(badMulti),'duplicate values rejected');
badMulti=clone(multi);badMulti.rules[0].values=[];rejected(()=>validate(badMulti),'empty value lists rejected');
badMulti=clone(multi);badMulti.rules[0].values=[];for(let i=0;i<129;i++)push(badMulti.rules[0].values,'host'+i+'.invalid');rejected(()=>validate(badMulti),'per-rule list limit enforced');
let migratedProfile=clone(m);migratedProfile.policyVersion=1;migratedProfile.rules=[];
for(let p in catalog)if(index(['YouTube','TikTok','Domestic'],p.id)>=0)for(let type,values in {domain:p.exactDomains,suffix:p.domains})for(let value in values)push(migratedProfile.rules,{id:'route_'+substr(sha256(p.id+chr(0)+type+chr(0)+value),0,16),enabled:true,type,value,outbound:p.id});
let edited=clone(migratedProfile.rules[0]);edited.enabled=false;let editedId=edited.id;
migratedProfile.rules[0]=edited;push(migratedProfile.rules,{id:'manual',enabled:true,type:'suffix',value:'manual.invalid',outbound:'direct'});
let profileResult=normalize(migratedProfile);
check(profileResult.policyVersion==2 && length(profileResult.rules)==2 && profileResult.rules[0].id==editedId && profileResult.rules[1].id=='manual','migration removes only unchanged generated service rules and preserves edited or manual overrides');
let native=generate(profileResult);
check(index(route(native.route.rules,'YouTube').domain_suffix,'ggpht.com')>=0 && index(route(native.route.rules,'YouTube').domain,'youtubei.googleapis.com')>=0 && length(route(native.route.rules,'TikTok').domain_suffix)==30 && join(',',route(native.route.rules,'Domestic').domain_suffix)=='cn','service data uses native rules without embedding domestic application lists');
let domesticSet=native.route.rule_set[0],lastDomainRule=native.route.rules[length(native.route.rules)-3],lastDns=native.dns.rules[length(native.dns.rules)-1];
check(length(native.route.rule_set)==2 && domesticSet.type=='local' && domesticSet.tag=='domestic-domain' && domesticSet.path=='/usr/share/alwayroute/rules/domestic-domain.srs','domestic community data loads from local binary rule sets');
check(lastDomainRule.rule_set[0]=='domestic-domain' && lastDomainRule.outbound=='Domestic' && lastDns.rule_set[0]=='domestic-domain' && lastDns.server=='bootstrap','route and DNS share the same domain set after explicit services and overrides');
let ipFallback=native.route.rules[length(native.route.rules)-1],resolveFallback=native.route.rules[length(native.route.rules)-2];
check(native.route.rule_set[1].tag=='domestic-ip' && ipFallback.rule_set[0]=='domestic-ip' && ipFallback.outbound=='Domestic' && resolveFallback.action=='resolve' && resolveFallback.server==null && resolveFallback.strategy=='ipv4_only','IP fallback follows all domain rules and resolves only through the existing DNS policy');
let overrideIP=clone(profileResult);overrideIP.rules=[{id:'address_override',enabled:true,type:'cidr',value:'192.0.2.0/24',outbound:'block'}];let overrideRules=generate(overrideIP).route.rules;
check(overrideRules[2].action=='reject' && overrideRules[length(overrideRules)-3].action=='resolve' && overrideRules[length(overrideRules)-2].action=='reject' && overrideRules[length(overrideRules)-2].ip_cidr[0]=='192.0.2.0/24' && overrideRules[length(overrideRules)-1].rule_set[0]=='domestic-ip','unmatched domains recheck user IP overrides after resolution and before the country fallback');
let blockedDomestic=clone(profileResult);group(blockedDomestic,'Other').selected='block';let ipBlocked=generate(blockedDomestic);
check(ipBlocked.route.rules[length(ipBlocked.route.rules)-2].rule_set[0]=='domestic-ip' && ipBlocked.route.rules[length(ipBlocked.route.rules)-1].action=='reject','domestic IP fallback remains before the Other terminal rejection');
for(let mode in ['direct','global']){let isolated=clone(profileResult);isolated.mode=mode;let c=generate(isolated);check(length(c.route.rule_set)==0 && length(c.route.rules)==1 && length(c.dns.rules)==0,'domestic domain and IP data are omitted in '+mode+' mode');}
let followDomestic=clone(profileResult);group(followDomestic,'Domestic').selected='Proxy';let followConfig=generate(followDomestic);
check(followConfig.dns.rules[length(followConfig.dns.rules)-1].server=='proxy-dns','community domain DNS follows Domestic selection through Proxy');
check(index(route(native.route.rules,'Proxy').domain_suffix,'cn')<0,'disabled domestic group cannot make the Proxy fallback claim all cn domains');
let noDomestic=clone(profileResult);noDomestic.groups=filter(noDomestic.groups,g=>g.id!='Domestic');
check(routeIndex(generate(noDomestic).route.rules,'Domestic')<0 && length(generate(noDomestic).route.rule_set)==0 && normalize(noDomestic).groups[length(noDomestic.groups)-1].id=='Other','deleted domestic group does not load or apply community data and is not re-added');
let noYouTube=clone(profileResult);noYouTube.rules=[];noYouTube.groups=filter(noYouTube.groups,g=>g.id!='YouTube');let fallbackRules=generate(noYouTube).route.rules;
check(routeIndex(fallbackRules,'Proxy')<routeIndex(fallbackRules,'Domestic') && index(route(fallbackRules,'Proxy').domain_suffix,'ggpht.cn')>=0,'known overseas cn domains retain Proxy fallback when a dedicated service group is deleted');

let legacy=clone(m);delete legacy.policyVersion;legacy.defaultOutbound='Netflix';
legacy.groups=[{id:'Proxy',name:'代理',selected:nodes[0].id},{id:'OpenAI',name:'OpenAI',selected:'Proxy'},
 {id:'Netflix',name:'Netflix',selected:'Proxy'},{id:'Disney',name:'Disney+',selected:'direct'},
 {id:'Custom',name:'自定义',selected:nodes[0].id}];
legacy.rules=[{id:'old_disney',enabled:true,type:'suffix',value:'example.invalid',outbound:'Disney'}];
let migrated=normalize(legacy);
check(migrated.policyVersion==2 && migrated.defaultOutbound=='Other' && group(migrated,'Other').selected=='Proxy','legacy fallback moves to Other');
check(group(migrated,'Domestic').selected=='direct','unversioned models initialize the new domestic service with direct');
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
m.mode='global';let globalConfig=generate(m);check(length(globalConfig.route.rules)==1 && globalConfig.route.rules[0].action=='hijack-dns' && globalConfig.route.final=='Proxy','global mode keeps DNS hijack without sniffing or applying user rules');
m.mode='direct';let directConfig=generate(m);check(length(directConfig.route.rules)==1 && directConfig.route.rules[0].action=='hijack-dns' && directConfig.route.final=='direct' && directConfig.dns.final=='bootstrap','direct mode keeps DNS hijack without sniffing, policy rules or proxy DNS');
printf('PASS %d manager contract checks\n',checks);
