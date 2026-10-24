'use strict';
// EXTERNAL_SOURCE

let files={},network='inactive',dns=false,localCore=false,now=100,operations=[],failAt=null,failWrite=null,failRemove=null,failSequence=[],guardedConfig=null;
function copy(value) {return value==null?null:json(sprintf('%J',value));}
function operation(name) {push(operations,name);if(name==failSequence[0]){shift(failSequence);die('injected sequential failure');}if(name==failAt){failAt=null;die('injected operational failure');}}
let io={
 read:function(key){let value=files[key];if(value=='corrupt')die('corrupt file');return copy(value);},
 write:function(key,value){if(key==failWrite){failWrite=null;die('injected storage failure');}files[key]=copy(value);},
 remove:function(key){if(key==failRemove){failRemove=null;die('injected unlink failure');}delete files[key];},
 now:()=>now,sync:()=>operation('sync'),runtime:function(config){operation('runtime');},clearRuntime:()=>operation('clear'),localCore:()=>localCore,
 prepare:function(config){operation('prepare');},guard:function(config){operation('guard');network='guarded';guardedConfig=copy(config);},
 startDns:function(config){operation('dns');dns=true;},activate:function(config){operation('activate');network='active';},
 stopDns:function(){operation('stopDns');dns=false;},stop:function(){operation('stop');network='inactive';dns=false;localCore=false;},
 inspect:()=>({network:{available:true,running:network=='active',guarded:network=='guarded',residual:network!='inactive'},dns:{running:dns},localCore})
};
let engine=externalController(io),checks=0;
function check(ok,message) {checks++;assert(ok,message);}
function fails(callback,code) {let error=null;try{callback();}catch(e){error=e.message;}check(error!=null && (code==null || index(error,'ALWAYROUTE:'+code+':')==0),'expected '+(code ?? 'failure')+', got '+(error ?? 'success'));}
function reset() {files={};network='inactive';dns=false;localCore=false;now=100;operations=[];failAt=null;failWrite=null;failRemove=null;failSequence=[];guardedConfig=null;}
function config() {return {schema:1,revision:0,enabled:true,family:'ipv4',faultPolicy:'block',link:{interface:'br-lan',routerAddress:'192.0.2.1',gatewayAddress:'192.0.2.2',gatewayMac:'02:00:00:00:00:02'},clients:[{address:'192.0.2.3',mac:'02:00:00:00:00:03'}],dns:{gatewayPort:1053,listenPort:1053,localDomains:['lan']},bypass4:[]};}
function save() {return engine.save({expectedRevision:0,config:config()});}
function peer() {return {gateway:'192.0.2.2',revision:files.config.revision,generation:'synthetic-generation',observedAt:now,coreReady:true,captureReady:true,dnsReady:true,egressViaRouter:true,returnViaRouter:true,sourcePreserved:true};}
function apply() {return engine.apply({expectedRevision:files.config.revision,peer:peer()});}

check(engine.get().config.enabled===false,'no external configuration defaults to off');
save();check(files.config.revision==1 && length(filter(operations,x=>x!='sync'))==0,'save increments only revision without network effects');
fails(()=>engine.save({expectedRevision:0,config:config()}),'REVISION_CONFLICT');
check(engine.get().state.desiredEnabled===false,'saving enabled config does not enable routing');
fails(()=>engine.apply({expectedRevision:0,peer:peer()}),'REVISION_CONFLICT');
let old=peer();old.observedAt=69;fails(()=>engine.apply({expectedRevision:1,peer:old}),'INVALID_EXTERNAL');
check(network=='inactive','stale observation cannot start capture');
localCore=true;fails(apply,'LOCAL_CORE_ACTIVE');localCore=false;
let active=apply();check(active.state.phase=='active' && active.state.appliedRevision==1 && files.intent.enabled,'successful local application commits the target');
check(active.state.endToEnd=='unverified' && active.state.peer.status=='reported','operator proof never becomes terminal acceptance');
check(index(operations,'guard')<index(operations,'activate'),'guard always precedes routing activation');
now=131;check(engine.status().state.phase=='degraded' && engine.status().state.peer.status=='unknown','old observation is never reported fresh');
check(network=='active' && files.intent.enabled,'unknown peer status never silently changes intent or removes safeguards');
engine.reconcile();check(network=='guarded' && !dns && files.intent.enabled && engine.status().state.phase=='guarded','restart/event recovery guards and requires fresh explicit application');
now=140;apply();check(network=='active','fresh observation can reactivate a guarded scope');
files.config='corrupt';files.journal='corrupt';files.good='corrupt';engine.disable();
check(network=='inactive' && !dns && !files.intent.enabled,'explicit close never reads damaged config/journal/lastgood');
check(engine.disable().state.phase=='disabled','repeated close is idempotent');

reset();save();failAt='prepare';fails(apply,'EXTERNAL_PREFLIGHT_FAILED');
check(network=='inactive' && files.journal==null && files.intent==null,'preflight rejection leaves original off state');
reset();save();failAt='activate';fails(apply,'EXTERNAL_APPLY_FAILED');
check(network=='inactive' && !files.intent.enabled && files.journal==null,'initial application failure restores off without false success');
reset();save();apply();failAt='activate';fails(apply,'EXTERNAL_APPLY_FAILED');
check(network=='guarded' && files.intent.enabled && !dns,'failed reapply to an enabled scope restores fail-closed without old observation');
reset();save();apply();files.journal={schema:1,phase:'applying',target:copy(files.config),previous:copy(files.good)};
fails(apply,'RECOVERY_REQUIRED');engine.reconcile();
check(network=='guarded' && files.journal==null,'interrupted enabled apply recovers to previous scope guard');
reset();save();files.intent={enabled:true,revision:1};files.journal={schema:1,phase:'applying',target:copy(files.config),previous:null};network='guarded';
engine.reconcile();check(network=='inactive' && !files.intent.enabled,'uncommitted first apply recovers off');
reset();save();failRemove='journal';fails(apply);
check(files.journal.phase=='committed' && network=='active','post-commit cleanup failure retains durable committed target');
engine.reconcile();check(network=='guarded' && files.good.revision==1 && files.journal==null,'committed recovery retains target and requests fresh confirmation');
reset();save();apply();failAt='stop';fails(()=>engine.disable(),'EXTERNAL_STOP_FAILED');
check(!files.intent.enabled && engine.status().state.phase=='fault' && network=='active','failed close records stop intent and does not claim disabled');
engine.disable();check(network=='inactive' && !files.intent.enabled,'failed close can be retried without peer');
reset();save();apply();failWrite='intent';fails(()=>engine.disable(),'EXTERNAL_STOP_FAILED');
check(network=='inactive' && engine.status().state.phase=='fault','persistent stop intent failure still attempts network cleanup without claiming success');
engine.disable();check(!files.intent.enabled,'retry persists the explicit close after storage failure');
reset();save();apply();let changed=copy(files.config);changed.clients[0].address='192.0.2.4';engine.save({expectedRevision:1,config:changed});
fails(apply,'SCOPE_CHANGE_REQUIRES_DISABLE');check(network=='active','scope change is rejected before disrupting the old active range');
reset();save();apply();files.journal='corrupt';fails(apply);engine.disable();check(network=='inactive','corrupt transaction still permits independent close');
reset();save();apply();let wider=copy(files.config);wider.bypass4=['203.0.113.0/24'];engine.save({expectedRevision:1,config:wider});
failSequence=['activate','stopDns'];fails(apply,'EXTERNAL_RECOVERY_FAILED');
check(files.journal!=null && network=='guarded' && length(guardedConfig.bypass4)==0,'failed recovery never broadens bypass to an uncommitted candidate');
engine.reconcile();check(files.journal==null && files.intent.enabled && network=='guarded','partial recovery remains retryable with previous confirmed scope');
print(sprintf('PASS external transaction and independent close: %d checks\n',checks));
