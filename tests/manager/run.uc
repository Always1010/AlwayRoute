'use strict';
import { sha256 } from 'digest';
import { empty,validate,generate,clone,effective } from 'alwayroute.model';
import { parse } from 'alwayroute.subscription';

let checks=0;
function check(ok,message){checks++;assert(ok,message);}
function rejected(fn,message){let failed=false;try{fn();}catch(e){failed=true;}check(failed,message);}
let uuid='00000000-0000-4000-8000-000000000001';
let source={v:'2',ps:'Sample',add:'example.invalid',port:'443',id:uuid,aid:'0',net:'ws',type:'none',host:'example.invalid',path:'/vmess',tls:'tls',sni:'example.invalid'};
let uri='vmess://'+b64enc(sprintf('%J',source));
let nodes=parse(uri,'demo',sha256),m=empty();
check(length(nodes)==1 && nodes[0].transport.type=='ws','VMess URI imports');
m.subscriptions=[{id:'demo',name:'Demo',url:'https://example.invalid/sub',enabled:true,intervalHours:24}];m.nodes=nodes;
m.groups[0].selected=nodes[0].id;validate(m);
let config=generate(m);check(config.outbounds[1].server_port==443,'typed VMess config');
check(config.experimental.clash_api.external_controller=='127.0.0.1:9090','API loopback only');
source.ps='Renamed';check(parse('vmess://'+b64enc(sprintf('%J',source)),'demo',sha256)[0].id==nodes[0].id,'name changes keep stable IDs');
check(parse(b64enc(uri),'demo',sha256)[0].id==nodes[0].id,'base64 subscription');
m.overrides[nodes[0].id]={name:'Local',patch:{port:8443}};check(effective(m)[0].port==8443 && effective(m)[0].name=='Local','independent override');
let yamlSample='proxies:\n  - name: Sample\n    type: vmess\n    server: example.invalid\n    port: 443\n    uuid: '+uuid+'\n    alterId: 0\n    cipher: auto\n    tls: true\n    network: ws\n    ws-opts:\n      path: /vmess\n      headers:\n        Host: example.invalid\n';
check(parse(yamlSample,'demo',sha256)[0].id==nodes[0].id,'strict YAML block imports');
rejected(()=>parse('proxies:\n  - { name: x, type: vmess }','demo',sha256),'flow YAML explicitly rejected');
rejected(()=>parse(replace(yamlSample,'    tls: true','    skip-cert-verify: true'),'demo',sha256),'unsafe TLS option rejected');
rejected(()=>parse(replace(yamlSample,'    cipher: auto','    surprise: value'),'demo',sha256),'unknown field rejected');
rejected(()=>parse(replace(uri,'vmess://','vless://'),'demo',sha256),'unsupported scheme rejected');
let broken=clone(m);broken.nodes=[];rejected(()=>validate(broken),'selected missing node rejected');
broken=clone(m);broken.groups[0].selected='Netflix';rejected(()=>validate(broken),'selector cycle rejected');
broken=clone(m);broken.nodes[0].command='touch /tmp/unsafe';rejected(()=>validate(broken),'config passthrough rejected');
broken=clone(m);broken.overrides[nodes[0].id].excluded=true;rejected(()=>validate(broken),'exclude selected node rejected');
m.rules=[{id:'block_ads',enabled:true,type:'suffix',value:'ads.example.invalid',outbound:'block'}, {id:'private',enabled:true,type:'cidr',value:'10.0.0.0/8',outbound:'direct'}];
check(generate(m).route.rules[2].action=='reject','block uses sing-box route action');
m.mode='global';check(length(generate(m).route.rules)==2 && generate(m).route.final=='Proxy','global mode bypasses user rules');
m.mode='direct';check(generate(m).route.final=='direct','direct mode');
printf('PASS %d manager contract checks\n',checks);
