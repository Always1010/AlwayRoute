'use strict';
import { empty, clone, generate, generateRuntimeValidated, validate } from 'alwayroute.model';
import { selectionPlan } from 'alwayroute.selection';

let m=empty(),checks=0;
function check(ok,message){checks++;assert(ok,message);}
m.nodes=[{id:'n1',name:'One',type:'vmess',enabled:true,source:null,server:'one.invalid',port:443,uuid:'00000000-0000-4000-8000-000000000001'},
 {id:'n2',name:'Two',type:'vmess',enabled:true,source:null,server:'two.invalid',port:443,uuid:'00000000-0000-4000-8000-000000000002'}];
m.groups[0].selected='n1';
let next=clone(m);next.revision++;next.groups[0].selected='n2';
let secret='00000000-0000-4000-8000-000000000099',runtime=generateRuntimeValidated(m,secret);
let plan=selectionPlan(m,next,runtime);
check(length(plan?.changes)==1 && plan.changes[0].before=='n1' && plan.changes[0].after=='n2','proxy-to-proxy switch uses existing selectors');
check(plan.config.outbounds[3].default=='n2' && plan.config.experimental.clash_api.secret==secret,'runtime defaults follow live choice and preserve its internal credential');
let dns=clone(next);dns.groups[1].selected='direct';
check(selectionPlan(m,dns,runtime)==null,'a choice changing domain DNS policy requires full apply');
let blocked=clone(next);for(let g in blocked.groups)if(g.id=='Other')g.selected='block';
check(selectionPlan(m,blocked,runtime)==null,'Other block route change cannot use a selector PUT');
let manualOther=clone(m);manualOther.rules=[{id:'follow_other',enabled:true,type:'domain',value:'blocked.invalid',outbound:'Other'}];
let blockedOther=clone(manualOther);for(let g in blockedOther.groups)if(g.id=='Other')g.selected='block';
check(selectionPlan(manualOther,blockedOther,generateRuntimeValidated(manualOther,secret))==null && selectionPlan(blockedOther,manualOther,generateRuntimeValidated(blockedOther,secret))==null,'blocking or unblocking manual rules following Other requires full route and DNS replacement');
let changed=clone(next);changed.nodes[0].port=8443;
check(selectionPlan(m,changed,runtime)==null,'node parameter edits require full apply');
changed=clone(next);changed.groups[0].name='Renamed';
check(selectionPlan(m,changed,runtime)==null,'mixed metadata and selection edits use complete transaction');
let foreign=generateRuntimeValidated(next,secret);check(selectionPlan(m,next,foreign)==null,'stale or foreign runtime config cannot enter hot path');
check(selectionPlan(m,m,runtime)==null,'unchanged selection is not a hot switch');
let tampered=clone(runtime);tampered.experimental.clash_api.access_control_allow_origin=['http://evil.invalid'];
check(selectionPlan(m,next,tampered)==null,'only the internal secret difference is tolerated in a runtime candidate');
check(selectionPlan(m,next,generate(m))==null,'runtime without an internal secret cannot use the hot path');
let patched=clone(m);patched.overrides.n1={patch:{port:0}};let rejected=false;
try{validate(patched);}catch(e){rejected=true;}
check(rejected,'avoiding duplicate source validation still fully validates patched node fields');
printf('PASS %d selection planning checks\n',checks);
