'use strict';
import { empty, clone, generate, validate } from 'alwayroute.model';
import { selectionPlan } from 'alwayroute.selection';

let m=empty(),checks=0;
function check(ok,message){checks++;assert(ok,message);}
m.nodes=[{id:'n1',name:'One',type:'vmess',enabled:true,source:null,server:'one.invalid',port:443,uuid:'00000000-0000-4000-8000-000000000001'},
 {id:'n2',name:'Two',type:'vmess',enabled:true,source:null,server:'two.invalid',port:443,uuid:'00000000-0000-4000-8000-000000000002'}];
m.groups[0].selected='n1';
let next=clone(m);next.revision++;next.groups[0].selected='n2';
let plan=selectionPlan(m,next,generate(m));
check(length(plan?.changes)==1 && plan.changes[0].before=='n1' && plan.changes[0].after=='n2','proxy-to-proxy switch uses existing selectors');
check(plan.config.outbounds[3].default=='n2','runtime defaults follow live choice for service restart');
let dns=clone(next);dns.groups[1].selected='direct';
check(selectionPlan(m,dns,generate(m))==null,'a choice changing domain DNS policy requires full apply');
let blocked=clone(next);for(let g in blocked.groups)if(g.id=='Other')g.selected='block';
check(selectionPlan(m,blocked,generate(m))==null,'Other block route change cannot use a selector PUT');
let changed=clone(next);changed.nodes[0].port=8443;
check(selectionPlan(m,changed,generate(m))==null,'node parameter edits require full apply');
changed=clone(next);changed.groups[0].name='Renamed';
check(selectionPlan(m,changed,generate(m))==null,'mixed metadata and selection edits use complete transaction');
check(selectionPlan(m,next,generate(next))==null,'stale or foreign runtime config cannot enter hot path');
check(selectionPlan(m,m,generate(m))==null,'unchanged selection is not a hot switch');
let patched=clone(m);patched.overrides.n1={patch:{port:0}};let rejected=false;
try{validate(patched);}catch(e){rejected=true;}
check(rejected,'avoiding duplicate source validation still fully validates patched node fields');
printf('PASS %d selection planning checks\n',checks);
