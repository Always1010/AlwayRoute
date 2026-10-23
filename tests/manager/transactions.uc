'use strict';
import { sha256 } from 'digest';

// In-memory adapters exercise the actual store transaction code. No host paths,
// networking, process execution, or persistent files are accessed by this suite.
let files={},locked=false,active=false,checkFails=false,allChecksFail=false,failWrite=null,failRename=null,failUnlink=null,onLock=null,currentReads=0;
let helperAvailable=true,stopFails=false,activateFails=false,guardCalls=0,stopCalls=0,delayCalls=0,forwardingMode='stopped',lastProxyReadLimit=0,lastProxyBodyLength=0,onDelay=null;
let liveChoices={},restartCalls=0,putCalls=0,putFails=false,putMismatch=false,putFailAt=null;
let fs={
 mkdir:()=>true,chmod:()=>true,
 readfile:function(path){if(path=='/proc/self/stat')return '123 (ucode)';if(path=='/proc/sys/kernel/random/uuid')return 'test-job';if(path=='/etc/alwayroute/current.json')currentReads++;return files[path] ?? null;},
 access:function(path){return path=='/proc/123' || (path=='/usr/libexec/alwayroute-forwarding' && helperAvailable);},
 rename:function(from,to){if(to==failRename){failRename=null;return false;}files[to]=files[from];delete files[from];return true;},
 unlink:function(path){if(path==failUnlink){failUnlink=null;return false;}delete files[path];return true;},
 open:function(path,mode){
  if(path==failWrite){failWrite=null;return null;}
  let owns=false;
  return {
   write:function(value){files[path]=value;return length(value);},flush:()=>true,
   close:function(){if(owns)locked=false;return true;},
   lock:function(mode){if(mode=='u'){locked=false;owns=false;return true;}if(locked)return null;locked=true;owns=true;if(onLock){let callback=onLock;onLock=null;callback();}return true;}
  };
 },
 popen:function(command){
  let body='{}';
  if(index(command,'/delay?')>=0){delayCalls++;body='{"delay":9}';if(onDelay)body=onDelay(command) ?? body;}
  else if(index(command,'alwayroute-forwarding status')>=0)body=sprintf('%J',{available:true,running:forwardingMode=='active',guarded:forwardingMode=='guarded'});
  else if(index(command,'/proxies')>=0){let cfg=json(files['/tmp/alwayroute/runtime.json']),proxies={};for(let o in cfg.outbounds)proxies[o.tag]=o.type=='selector'?{type:'Selector',now:liveChoices[o.tag] ?? o.default,all:o.outbounds,history:[]}:{type:'VMess',name:o.tag,history:[]};body=sprintf('%J',{proxies});lastProxyBodyLength=length(body);}
  return {read:function(limit){if(index(command,'/proxies')>=0)lastProxyReadLimit=limit;return substr(body,0,limit);},close:()=>0};
 }
};
function system(command){
 if(index(command,'--method PUT')>=0){putCalls++;if(putFails || putCalls==putFailAt){putFails=false;return 1;}let id=split(split(command,'/proxies/')[1],' ')[0],value=json(files['/tmp/alwayroute/selection.json']).name;if(!putMismatch)liveChoices[id]=value;return 0;}
 if(index(command,'alwayroute-forwarding guard')>=0){guardCalls++;forwardingMode='guarded';}
 if(index(command,'alwayroute-forwarding stop')>=0){stopCalls++;if(stopFails)return 1;forwardingMode='stopped';}
 if(index(command,'alwayroute-forwarding activate')>=0){if(activateFails){activateFails=false;return 1;}forwardingMode='active';}
 if(index(command,'sing-box check')>=0 && allChecksFail)return 1;
 if(index(command,'sing-box check')>=0 && checkFails){checkFails=false;return 1;}
 if(index(command,'alwayroute running')>=0)return active?0:1;
 if(index(command,'alwayroute restart')>=0){restartCalls++;active=true;liveChoices={};let cfg=json(files['/tmp/alwayroute/runtime.json']);for(let o in cfg.outbounds)if(o.type=='selector')liveChoices[o.tag]=o.default;}
 if(index(command,'alwayroute stop')>=0)active=false;
 return 0;
}

// MANAGER_SOURCE

let checks=0;
function check(ok,message){checks++;assert(ok,message);}
let savedJob=files['/tmp/alwayroute/job.json'];
files['/tmp/alwayroute/job.json']=sprintf('%J',{id:'old-live-job',status:'running',started:time()-121,pid:123});
let observedJob=call('job_status',{});
check(observedJob.busy && observedJob.job.status=='running','live worker remains busy beyond UI timeout and cannot be mistaken for a completed transaction');
files['/tmp/alwayroute/job.json']=sprintf('%J',{id:'old-dead-job',status:'running',started:time()-121,pid:999});
observedJob=call('job_status',{});
check(!observedJob.busy && observedJob.job.status=='failed' && observedJob.job.error.code=='JOB_INTERRUPTED','missing worker PID confirms an interrupted transaction');
if(savedJob==null)delete files['/tmp/alwayroute/job.json'];else files['/tmp/alwayroute/job.json']=savedJob;
files['/tmp/alwayroute/job.json']=sprintf('%J',{id:'claim-race-job',status:'running',started:time()-11});
locked=true;let contendedJob=call('job_status',{});locked=false;
onLock=function(){files['/tmp/alwayroute/job.json']=sprintf('%J',{id:'claim-race-job',status:'running',started:time()-11,pid:123});};
observedJob=call('job_status',{});
check(contendedJob.busy && observedJob.busy && observedJob.job.pid==123 && json(files['/tmp/alwayroute/job.json']).status=='running','interruption detection tolerates a held manager lock and rechecks a worker claim under the same lock');
if(savedJob==null)delete files['/tmp/alwayroute/job.json'];else files['/tmp/alwayroute/job.json']=savedJob;
let savedRequest=files['/tmp/alwayroute/job.request.json'],savedCurrent=files['/etc/alwayroute/current.json'],lateModel=empty();lateModel.mode='direct';
files['/tmp/alwayroute/job.json']=sprintf('%J',{id:'late-job',method:'configure',status:'running',started:time()-11});
files['/tmp/alwayroute/job.request.json']=sprintf('%J',{id:'late-job',method:'configure',args:{expectedRevision:0,model:lateModel}});
call('job_status',{});work();observedJob=call('job_status',{});
check(!observedJob.busy && observedJob.job.status=='failed' && observedJob.job.error.code=='JOB_INTERRUPTED' && files['/etc/alwayroute/current.json']==savedCurrent && !active && !files['/tmp/alwayroute/job.request.json'],'late worker cannot take over or commit a job already declared interrupted');
if(savedJob==null)delete files['/tmp/alwayroute/job.json'];else files['/tmp/alwayroute/job.json']=savedJob;
if(savedRequest==null)delete files['/tmp/alwayroute/job.request.json'];else files['/tmp/alwayroute/job.request.json']=savedRequest;
currentReads=0;let r=call('get',{});check(r.ok && r.model.revision==0 && currentReads==1,'initial get loads and validates the current model once');
let oversized='x';while(length(oversized)<=131072)oversized+=oversized;
r=call('configure',{expectedRevision:0,model:{padding:oversized}});
check(r.error?.code=='INPUT_LIMIT' && !files['/tmp/alwayroute/job.request.json'],'oversized configure is rejected before writing a background request');
r=call('import',{expectedRevision:0,content:oversized,activate:true});
check(r.error?.code=='INPUT_LIMIT' && !files['/tmp/alwayroute/job.request.json'],'oversized activated import is rejected before writing a background request');
r=call('get',{});
let beforeCurrent=files['/etc/alwayroute/current.json'],unconfigured=clone(r.model);unconfigured.mode='global';
call('configure',{expectedRevision:0,model:unconfigured});work();r=call('get',{});
check(call('job_status',{}).job.error.code=='UNCONFIGURED' && !active && r.model.revision==0 && r.model.mode=='rule' && files['/etc/alwayroute/current.json']==beforeCurrent,'stopped global mode rejects an unconfigured Proxy without changing current');
let draft=r.model;
draft.nodes=[{id:'n1',name:'Test',type:'vmess',enabled:true,source:null,server:'example.invalid',port:443,uuid:'00000000-0000-4000-8000-000000000001',security:'auto',alterId:0}];
draft.groups[0].selected='n1';
r=call('save',{expectedRevision:0,model:draft});check(r.ok && r.model.revision==1,'save increments revision');
check(call('save',{expectedRevision:0,model:draft}).error.code=='REVISION_CONFLICT','stale save rejected with stable code');
r=call('apply',{expectedRevision:1});check(r.ok && r.job.status=='running' && !active,'apply queues without starting core in RPC');
check(call('save',{expectedRevision:1,model:r.model}).error.code=='BUSY','queued mutation excluded');
work();r=call('job_status',{});check(!r.busy && r.job.status=='succeeded' && active,'worker completes and releases transaction lock');
check(call('get',{}).state.appliedRevision==1,'applied distinct from saved');
let normalRuntime=files['/tmp/alwayroute/runtime.json'],largeRuntime={outbounds:[]},largeChoices=[];
for(let i=0;i<128;i++){let tag=sprintf('n%03d_',i);while(length(tag)<64)tag+='x';push(largeChoices,tag);push(largeRuntime.outbounds,{type:'vmess',tag});}
for(let i=0;i<16;i++)push(largeRuntime.outbounds,{type:'selector',tag:'group_'+i,outbounds:largeChoices,default:largeChoices[i]});
files['/tmp/alwayroute/runtime.json']=sprintf('%J',largeRuntime);currentReads=0;let largeStatus=call('status',{});
check(currentReads==1 && lastProxyBodyLength>65536 && lastProxyReadLimit==262145 && largeStatus.core.available && length(keys(largeStatus.core.groups))==16,'maximum node and group status loads the model once and reads the bounded response beyond the old 64KiB cutoff');
check(largeStatus.core.groups.group_15.now==largeChoices[15] && length(keys(largeStatus.core.groups.group_15))==1 && largeStatus.core.groups[largeChoices[0]]==null,'core status retains only selector choices needed for runtime confirmation');
files['/tmp/alwayroute/runtime.json']=normalRuntime;
call('check',{nodeId:'n1'});work();let checked=call('job_status',{}).job;
check(checked.status=='succeeded' && checked.result.checkedRevision==1 && checked.result.delay==9,'node check uses matching applied revision');
let originalModel=files['/etc/alwayroute/current.json'],batchModel=clone(call('get',{}).model);
batchModel.subscriptions=[{id:'demo',name:'Demo',url:'https://example.invalid/sub',enabled:true,intervalHours:0}];
batchModel.nodes=[];
for(let i=0;i<4;i++){let item=clone(draft.nodes[0]);item.id='b'+i;item.source='demo';item.enabled=i!=2;push(batchModel.nodes,item);}
batchModel.nodes[0].id='n1';batchModel.overrides={b3:{excluded:true}};
files['/etc/alwayroute/current.json']=sprintf('%J',batchModel);
let batchBefore=delayCalls,beforeGuards=guardCalls,beforeStops=stopCalls,beforeRuntime=files['/tmp/alwayroute/runtime.json'];
onDelay=function(){let observed=call('job_status',{}).job,p=observed.progress;assert(locked && p.completed==delayCalls-batchBefore-1 && length(keys(observed.checks))==p.completed,'progress and completed results published before serial probe');return delayCalls-batchBefore==2?'{}':null;};
call('check',{subscriptionId:'demo'});work();onDelay=null;let batchJob=call('job_status',{}).job;
check(batchJob.status=='succeeded' && batchJob.progress.total==2 && batchJob.progress.completed==2 && batchJob.result.passed==1 && batchJob.result.failed==1 && delayCalls-batchBefore==2,'subscription check skips disabled/excluded nodes and continues after a failed probe');
check(guardCalls==beforeGuards && stopCalls==beforeStops && active && files['/tmp/alwayroute/runtime.json']==beforeRuntime && files['/etc/alwayroute/current.json']==sprintf('%J',batchModel),'detection leaves forwarding, runtime and persistent configuration untouched');
batchBefore=delayCalls;
onDelay=function(){assert(call('save',{}).error.code=='BUSY','configuration excluded during checks');assert(call('cancel_check',{jobId:'stale'}).ok==false,'stale cancellation rejected');assert(call('cancel_check',{jobId:'test-job'}).ok,'cancel bypasses held transaction lock');};
call('check',{subscriptionId:'demo'});work();onDelay=null;batchJob=call('job_status',{}).job;
check(batchJob.status=='cancelled' && batchJob.result.completed==1 && batchJob.result.cancelled && delayCalls-batchBefore==1 && batchJob.result.checks.n1.delay==9,'cancel stops before next node and retains completed results');
check(call('cancel_check',{jobId:'test-job'}).ok==false && !files['/tmp/alwayroute/check-cancel-test-job'],'finished jobs reject cancel and marker is cleaned');
batchBefore=delayCalls;call('check',{nodeId:'n1'});call('cancel_check',{jobId:'test-job'});work();
check(call('job_status',{}).job.status=='cancelled' && delayCalls==batchBefore,'queued cancellation prevents even the first probe');
let manual=clone(batchModel.nodes[0]);manual.id='manual';manual.source=null;push(batchModel.nodes,manual);
files['/etc/alwayroute/current.json']=sprintf('%J',batchModel);
batchBefore=delayCalls;
call('check',{scope:'selected',nodeIds:['manual','manual','b2','b3']});work();batchJob=call('job_status',{}).job;
check(batchJob.status=='succeeded' && batchJob.result.scope=='selected' && batchJob.result.total==1 && batchJob.result.skipped==2 && delayCalls-batchBefore==1 && batchJob.result.checks.manual.delay==9,'selected check deduplicates IDs and skips disabled/excluded nodes');
batchBefore=delayCalls;
for(let args in [{},{scope:'selected',nodeIds:[]},{scope:'all',nodeId:'n1'},{scope:'all',subscriptionId:'demo'},
 {scope:'all',nodeIds:['n1']},{scope:'selected',nodeIds:'n1'},{scope:'selected',nodeIds:['missing']},{scope:'all',nodeIds:null},{scope:'all',retryFailed:null},
 {scope:'selected',nodeIds:['n1/escape']},{nodeId:5},{subscriptionId:[]},{scope:'all',retryFailed:'true'},
 {nodeId:'n1',subscriptionId:'demo'}]) {
 call('check',args);work();check(call('job_status',{}).job.status=='failed' && delayCalls==batchBefore,'invalid or ambiguous check request never probes or accidentally scans all');
}
onDelay=function(command){return index(command,'/b1/delay')>=0?'{}':null;};
call('check',{scope:'all'});work();onDelay=null;batchJob=call('job_status',{}).job;
check(batchJob.status=='succeeded' && batchJob.result.scope=='all' && batchJob.result.total==3 && batchJob.result.skipped==2 && batchJob.result.checks.manual && batchJob.result.checks.b1.healthy=='failed','all check covers subscriptions and manual nodes');
let stale=clone(json(files['/tmp/alwayroute/checks.json']));stale.manual.healthy='failed';stale.manual.checkedRevision=0;files['/tmp/alwayroute/checks.json']=sprintf('%J',stale);
batchBefore=delayCalls;
call('check',{scope:'all',retryFailed:true});work();batchJob=call('job_status',{}).job;
check(batchJob.status=='succeeded' && batchJob.result.retryFailed && batchJob.result.total==1 && batchJob.result.checks.b1 && !batchJob.result.checks.manual && delayCalls-batchBefore==1,'retry targets only current-revision failed eligible nodes');
batchBefore=delayCalls;call('check',{scope:'all',retryFailed:true});work();
check(call('job_status',{}).job.error.code=='NO_NODES' && delayCalls==batchBefore,'retry without failed current nodes never becomes full scan');
check(files['/etc/alwayroute/current.json']==sprintf('%J',batchModel) && files['/tmp/alwayroute/runtime.json']==beforeRuntime && guardCalls==beforeGuards && stopCalls==beforeStops,'batch checks do not change configuration, exit or service');
files['/etc/alwayroute/current.json']=originalModel;
draft=call('get',{}).model;draft.nodes[0].name='Renamed';r=call('save',{expectedRevision:1,model:draft});
check(r.model.revision==2 && r.state.appliedRevision==1,'draft save does not apply');
let previousDelayCalls=delayCalls;call('check',{nodeId:'n1'});work();
check(call('job_status',{}).job.error.code=='NOT_APPLIED' && delayCalls==previousDelayCalls,'saved unapplied revision rejects check before core API request');
checkFails=true;call('apply',{expectedRevision:2});work();r=call('job_status',{});
check(r.job.status=='failed' && r.job.error.code=='CORE_CHECK_FAILED','failed core validation is reported');
check(call('get',{}).state.appliedRevision==1 && active,'failed apply restores last good');
failWrite='/etc/alwayroute/lastgood.json.new';call('apply',{expectedRevision:2});work();r=call('job_status',{});
check(r.job.status=='failed' && r.job.error.code=='STORAGE_ERROR','commit write failure is reported');
check(call('get',{}).state.appliedRevision==1 && active,'commit failure recovers running core first');
call('rollback',{expectedRevision:2});work();r=call('get',{});
check(r.model.revision==3 && r.model.nodes[0].name=='Test','rollback restores content with new revision');
check(call('export',{includeSecrets:false}).model.nodes[0].uuid=='[redacted]','default export redacts credentials');
stopFails=true;call('service',{action:'stop'});work();
check(call('job_status',{}).job.error.code=='FORWARDING_STOP_FAILED' && active && json(files['/etc/alwayroute/service.json']).enabled,'failed forwarding stop preserves core and enabled state');stopFails=false;
helperAvailable=false;call('apply',{expectedRevision:3});work();
check(call('job_status',{}).job.status=='failed','missing forwarding helper cannot report apply success');helperAvailable=true;
call('service',{action:'start'});work();
let previousStops=stopCalls,previousGuards=guardCalls;allChecksFail=true;call('apply',{expectedRevision:3});work();allChecksFail=false;
check(call('job_status',{}).job.status=='failed' && guardCalls>previousGuards && stopCalls==previousStops,'failed core recovery requests guard without removing interception');
check(call('get',{}).state.appliedRevision==null,'failed recovery does not claim a restored revision');
call('service',{action:'start'});work();
call('service',{action:'stop'});work();check(!active && json(files['/etc/alwayroute/service.json']).enabled==false,'stop persists disabled state');

// Immediate configuration confirms a single revision and preserves the old
// choice on core, flash, and final commit-marker failures.
draft=call('get',{}).model;draft.mode='direct';draft.groups[0].selected='direct';
call('configure',{expectedRevision:2,model:draft});work();
check(call('job_status',{}).job.error.code=='REVISION_CONFLICT' && call('get',{}).model.revision==3,'configure rejects stale revision inside worker');
checkFails=true;call('configure',{expectedRevision:3,model:draft});work();
check(call('job_status',{}).job.error.code=='CORE_CHECK_FAILED' && call('get',{}).model.revision==3 && !active,'stopped configure validates before saving and never starts core');
failRename='/etc/alwayroute/current.json';call('configure',{expectedRevision:3,model:draft});work();
check(call('job_status',{}).job.error.code=='STORAGE_ERROR' && call('get',{}).model.revision==3 && !active,'stopped configure current write failure preserves old choice');
call('configure',{expectedRevision:3,model:draft});work();r=call('get',{});
check(call('job_status',{}).job.status=='succeeded' && r.model.revision==4 && r.model.mode=='direct' && !active && !json(files['/etc/alwayroute/service.json']).enabled,'stopped configure saves one revision while preserving disabled service');
check(json(files['/etc/alwayroute/lastgood.json']).revision==3 && r.state.appliedRevision==null,'stopped configure does not claim its checked candidate is applied');
call('service',{action:'start'});work();r=call('get',{});
check(call('job_status',{}).job.status=='succeeded' && active && r.state.appliedRevision==4 && json(files['/etc/alwayroute/lastgood.json']).revision==4,'start applies latest current instead of stale lastgood');
draft=clone(r.model);draft.mode='global';draft.groups[0].selected='n1';
checkFails=true;call('configure',{expectedRevision:4,model:draft});work();r=call('get',{});
check(call('job_status',{}).job.error.code=='CORE_CHECK_FAILED' && r.model.revision==4 && r.model.mode=='direct' && r.state.appliedRevision==4 && active,'failed running configure restores old choice and running revision');
call('configure',{expectedRevision:4,model:draft});work();r=call('get',{});
check(call('job_status',{}).job.status=='succeeded' && r.model.revision==5 && r.model.mode=='global' && r.state.appliedRevision==5 && active,'running configure commits current and confirmed applied revision together');
draft=clone(r.model);draft.mode='direct';
activateFails=true;call('configure',{expectedRevision:5,model:draft});work();r=call('get',{});
check(call('job_status',{}).job.error.code=='FORWARDING_APPLY_FAILED' && r.model.revision==5 && r.model.mode=='global' && r.state.appliedRevision==5 && active,'forwarding failure restores old choice and confirmed running revision');
failRename='/etc/alwayroute/current.json';call('configure',{expectedRevision:5,model:draft});work();r=call('get',{});
check(call('job_status',{}).job.error.code=='STORAGE_ERROR' && r.model.revision==5 && r.model.mode=='global' && r.state.appliedRevision==5 && json(files['/etc/alwayroute/lastgood.json']).revision==5 && active,'failed current rename restores old current lastgood and live core');
failWrite='/etc/alwayroute/lastgood.json.new';call('configure',{expectedRevision:5,model:draft});work();r=call('get',{});
check(call('job_status',{}).job.error.code=='STORAGE_ERROR' && r.model.revision==5 && r.state.appliedRevision==5 && active,'failed lastgood write cannot save a new immediate choice');
failUnlink='/etc/alwayroute/applying.json';call('configure',{expectedRevision:5,model:draft});work();r=call('get',{});
check(call('job_status',{}).job.error.code=='STORAGE_ERROR' && r.model.revision==5 && r.model.mode=='global' && r.state.appliedRevision==5 && active,'failure after current write restores old current before reporting failure');
draft=clone(r.model);draft.mode='rule';for(let g in draft.groups)if(g.id=='Other')g.selected='block';
call('configure',{expectedRevision:5,model:draft});work();r=call('get',{});
check(call('job_status',{}).job.status=='succeeded' && r.model.revision==6 && r.state.appliedRevision==6,'Other block is confirmed against its direct selector representation');
call('service',{action:'stop'});work();failWrite='/etc/alwayroute/lastgood.json.new';call('service',{action:'start'});work();
check(call('job_status',{}).job.error.code=='STORAGE_ERROR' && !active && !json(files['/etc/alwayroute/service.json']).enabled && call('get',{}).state.appliedRevision==null && forwardingMode=='stopped','failed start restores stopped core and inactive forwarding even after candidate core started');
stopFails=true;failWrite='/etc/alwayroute/lastgood.json.new';call('service',{action:'start'});work();
check(call('job_status',{}).job.error.code=='STORAGE_ERROR' && !active && forwardingMode=='guarded','failed restoration of inactive forwarding falls back to guard');
stopFails=false;call('service',{action:'stop'});work();

let good=clone(r.model);files['/etc/alwayroute/applying.json']=sprintf('%J',{previousRevision:6,previousCurrent:good,previousService:{enabled:true}});files['/etc/alwayroute/previous.json']=sprintf('%J',good);files['/etc/alwayroute/service.json']='{"enabled":true}';
let interrupted=clone(good);interrupted.revision=7;interrupted.mode='direct';files['/etc/alwayroute/current.json']=sprintf('%J',interrupted);files['/etc/alwayroute/lastgood.json']=sprintf('%J',interrupted);
check(call('get',{}).model.revision==6,'uncleared configure marker hides half-committed current from readers');
check(boot() && json(files['/tmp/alwayroute/state.json']).appliedRevision==null,'boot pending transaction restores without claiming loaded');
check(json(files['/etc/alwayroute/current.json']).revision==6 && json(files['/tmp/alwayroute/runtime.json']).experimental.clash_api.default_mode=='Rule','boot restores previous current and runtime rather than half-committed lastgood');
call('service',{action:'start'});work();
check(call('job_status',{}).job.status=='succeeded' && call('get',{}).model.revision==6 && call('get',{}).state.appliedRevision==6 && !files['/etc/alwayroute/applying.json'],'start after interrupted configure confirms and commits restored model');
call('service',{action:'stop'});work();
files['/etc/alwayroute/applying.json']=sprintf('%J',{previousRevision:6,previousCurrent:good,previousService:{enabled:false},previousRunning:false});files['/etc/alwayroute/current.json']=sprintf('%J',interrupted);files['/etc/alwayroute/lastgood.json']=sprintf('%J',interrupted);files['/etc/alwayroute/service.json']='{"enabled":true}';
draft=clone(good);draft.mode='global';call('configure',{expectedRevision:6,model:draft});work();r=call('get',{});
check(call('job_status',{}).job.status=='succeeded' && r.model.revision==7 && r.model.mode=='global' && !active && !json(files['/etc/alwayroute/service.json']).enabled && !files['/etc/alwayroute/applying.json'],'stopped configure first restores interrupted metadata and does not hide the new confirmed current');

let source={v:'2',ps:'Import',add:'import.example.invalid',port:'443',id:'00000000-0000-4000-8000-000000000002',aid:'0',net:'tcp',type:'none',tls:''};
let uri='vmess://'+b64enc(sprintf('%J',source));
checkFails=true;call('import',{expectedRevision:7,content:uri,activate:true});work();r=call('get',{});
check(call('job_status',{}).job.error.code=='CORE_CHECK_FAILED' && r.model.revision==7 && length(r.model.nodes)==1 && !active,'activated import validates before persisting nodes while stopped');
let queued=call('import',{expectedRevision:7,content:uri,activate:true});
check(queued.job.status=='running' && length(call('get',{}).model.nodes)==1,'activated import queues without early node persistence');
work();r=call('get',{});
check(call('job_status',{}).job.status=='succeeded' && r.model.revision==8 && length(r.model.nodes)==2 && !active,'activated import saves checked candidate once without starting a stopped service');
call('service',{action:'start'});work();source.id='00000000-0000-4000-8000-000000000003';let secondUri='vmess://'+b64enc(sprintf('%J',source));
checkFails=true;call('import',{expectedRevision:8,content:secondUri,activate:true});work();r=call('get',{});
check(call('job_status',{}).job.error.code=='CORE_CHECK_FAILED' && r.model.revision==8 && length(r.model.nodes)==2 && r.state.appliedRevision==8 && active,'running activated import failure preserves nodes and applied revision');
draft=clone(r.model);draft.subscriptions=[{id:'demo',name:'Demo',url:'https://example.invalid/sub',enabled:true,intervalHours:24}];
call('configure',{expectedRevision:8,model:draft});work();
checkFails=true;call('refresh',{expectedRevision:9,subscriptionId:'demo',content:uri,activate:true});work();r=call('get',{});
check(call('job_status',{}).job.error.code=='CORE_CHECK_FAILED' && r.model.revision==9 && length(r.model.nodes)==2 && r.state.appliedRevision==9 && active,'activated subscription refresh failure does not persist its parsed candidate');
call('refresh',{expectedRevision:9,subscriptionId:'demo',content:uri,activate:true});work();r=call('get',{});
check(call('job_status',{}).job.status=='succeeded' && r.model.revision==10 && length(r.model.nodes)==3 && r.state.appliedRevision==10 && active,'activated subscription refresh commits nodes and loaded revision together');
call('refresh',{expectedRevision:10,subscriptionId:'demo',content:uri});work();r=call('get',{});
check(r.model.revision==11 && r.state.appliedRevision==10,'legacy subscription refresh remains save-only without activate');
r=call('import',{expectedRevision:11,content:secondUri});
check(r.ok && r.imported==1 && r.model.revision==12 && r.state.appliedRevision==10,'legacy import remains synchronous and save-only without activate');

// Live choices are independent from runtime.json, so a file write cannot fake
// a successful core acknowledgement. Failure uses the original full recovery.
let hotFixture=clone(call('get',{}).model);hotFixture.mode='rule';files['/etc/alwayroute/current.json']=sprintf('%J',hotFixture);
call('apply',{expectedRevision:12});work();r=call('get',{});
let hotBase=clone(r.model),hotNext=clone(hotBase),hotTarget=hotBase.nodes[1].id;
hotNext.groups[0].selected=hotTarget;
let beforeRestarts=restartCalls,beforePuts=putCalls;
call('configure',{expectedRevision:12,model:hotNext});work();r=call('get',{});
check(call('job_status',{}).job.status=='succeeded' && r.model.revision==13 && r.state.appliedRevision==13 && liveChoices.Proxy==hotTarget && restartCalls==beforeRestarts && putCalls==beforePuts+1,'proxy-to-proxy selection commits without restarting the live core');
check(sprintf('%J',generate(r.model))==files['/tmp/alwayroute/runtime.json'] && json(files['/etc/alwayroute/lastgood.json']).revision==13 && !files['/etc/alwayroute/applying.json'],'hot switch commits runtime defaults and persistent recovery metadata together');
hotBase=clone(r.model);
for(let failure in ['put','readback','runtime','lastgood','current','marker','partial']) {
 hotNext=clone(hotBase);hotNext.groups[0].selected='n1';
 if(failure=='put')putFails=true;
 if(failure=='readback')putMismatch=true;
 if(failure=='runtime')failWrite='/tmp/alwayroute/runtime.json.new';
 if(failure=='lastgood')failWrite='/etc/alwayroute/lastgood.json.new';
 if(failure=='current')failRename='/etc/alwayroute/current.json';
 if(failure=='marker')failUnlink='/etc/alwayroute/applying.json';
 if(failure=='partial'){hotNext.groups[1].selected='n1';putFailAt=putCalls+2;}
 beforeRestarts=restartCalls;
 call('configure',{expectedRevision:13,model:hotNext});work();r=call('get',{});putMismatch=false;putFailAt=null;
 check(call('job_status',{}).job.status=='failed' && r.model.revision==13 && r.state.appliedRevision==13 && liveChoices.Proxy==hotTarget && restartCalls>beforeRestarts && sprintf('%J',generate(hotBase))==files['/tmp/alwayroute/runtime.json'] && !files['/etc/alwayroute/applying.json'],'hot '+failure+' failure fully restores old core, metadata and revision');
}
hotNext=clone(hotBase);hotNext.groups[1].selected='direct';beforeRestarts=restartCalls;
call('configure',{expectedRevision:13,model:hotNext});work();r=call('get',{});
check(call('job_status',{}).job.status=='succeeded' && restartCalls>beforeRestarts && r.state.appliedRevision==14,'DNS-changing selection retains full validated apply');
// A power interruption before clearing the same durable marker must boot old.
files['/etc/alwayroute/previous.json']=sprintf('%J',hotBase);
files['/etc/alwayroute/applying.json']=sprintf('%J',{previousCurrent:hotBase,previousRevision:13,previousService:{enabled:true},previousRunning:true});
check(boot() && json(files['/etc/alwayroute/current.json']).revision==13 && filter(json(files['/tmp/alwayroute/runtime.json']).outbounds,o=>o.tag=='Proxy')[0].default==hotTarget && !files['/etc/alwayroute/applying.json'],'interrupted selector transaction boots previous confirmed choice');
printf('PASS %d manager transaction checks\n',checks);
