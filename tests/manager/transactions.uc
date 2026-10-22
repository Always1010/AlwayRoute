'use strict';
import { sha256 } from 'digest';

// In-memory adapters exercise the actual store transaction code. No host paths,
// networking, process execution, or persistent files are accessed by this suite.
let files={},locked=false,active=false,checkFails=false,allChecksFail=false,failWrite=null,failRename=null,failUnlink=null;
let helperAvailable=true,stopFails=false,activateFails=false,guardCalls=0,stopCalls=0,delayCalls=0;
let fs={
 mkdir:()=>true,chmod:()=>true,
 readfile:function(path){if(path=='/proc/self/stat')return '123 (ucode)';if(path=='/proc/sys/kernel/random/uuid')return 'test-job';return files[path] ?? null;},
 access:function(path){return path=='/proc/123' || (path=='/usr/libexec/alwayroute-forwarding' && helperAvailable);},
 rename:function(from,to){if(to==failRename){failRename=null;return false;}files[to]=files[from];delete files[from];return true;},
 unlink:function(path){if(path==failUnlink){failUnlink=null;return false;}delete files[path];return true;},
 open:function(path,mode){
  if(path==failWrite){failWrite=null;return null;}
  let owns=false;
  return {
   write:function(value){files[path]=value;return length(value);},flush:()=>true,
   close:function(){if(owns)locked=false;return true;},
   lock:function(mode){if(mode=='u'){locked=false;owns=false;return true;}if(locked)return null;locked=true;owns=true;return true;}
  };
 },
 popen:function(command){
  let body='{}';
  if(index(command,'/delay?')>=0){delayCalls++;body='{"delay":9}';}
  else if(index(command,'/proxies')>=0){let cfg=json(files['/tmp/alwayroute/runtime.json']),proxies={};for(let o in cfg.outbounds)if(o.type=='selector')proxies[o.tag]={now:o.default,all:o.outbounds};body=sprintf('%J',{proxies});}
  return {read:()=>body,close:()=>0};
 }
};
function system(command){
 if(index(command,'alwayroute-forwarding guard')>=0)guardCalls++;
 if(index(command,'alwayroute-forwarding stop')>=0){stopCalls++;if(stopFails)return 1;}
 if(index(command,'alwayroute-forwarding activate')>=0 && activateFails){activateFails=false;return 1;}
 if(index(command,'sing-box check')>=0 && allChecksFail)return 1;
 if(index(command,'sing-box check')>=0 && checkFails){checkFails=false;return 1;}
 if(index(command,'alwayroute running')>=0)return active?0:1;
 if(index(command,'alwayroute restart')>=0)active=true;
 if(index(command,'alwayroute stop')>=0)active=false;
 return 0;
}

// MANAGER_SOURCE

let checks=0;
function check(ok,message){checks++;assert(ok,message);}
let r=call('get',{});check(r.ok && r.model.revision==0,'initial state');
let oversized='x';while(length(oversized)<=131072)oversized+=oversized;
r=call('configure',{expectedRevision:0,model:{padding:oversized}});
check(r.error?.code=='INPUT_LIMIT' && !files['/tmp/alwayroute/job.request.json'],'oversized configure is rejected before writing a background request');
r=call('import',{expectedRevision:0,content:oversized,activate:true});
check(r.error?.code=='INPUT_LIMIT' && !files['/tmp/alwayroute/job.request.json'],'oversized activated import is rejected before writing a background request');
r=call('get',{});
let draft=r.model;
draft.nodes=[{id:'n1',name:'Test',type:'vmess',enabled:true,source:null,server:'example.invalid',port:443,uuid:'00000000-0000-4000-8000-000000000001',security:'auto',alterId:0}];
draft.groups[0].selected='n1';
r=call('save',{expectedRevision:0,model:draft});check(r.ok && r.model.revision==1,'save increments revision');
check(call('save',{expectedRevision:0,model:draft}).error.code=='REVISION_CONFLICT','stale save rejected with stable code');
r=call('apply',{expectedRevision:1});check(r.ok && r.job.status=='running' && !active,'apply queues without starting core in RPC');
check(call('save',{expectedRevision:1,model:r.model}).error.code=='BUSY','queued mutation excluded');
work();r=call('job_status',{});check(!r.busy && r.job.status=='succeeded' && active,'worker completes and releases transaction lock');
check(call('get',{}).state.appliedRevision==1,'applied distinct from saved');
call('check',{nodeId:'n1'});work();let checked=call('job_status',{}).job;
check(checked.status=='succeeded' && checked.result.checkedRevision==1 && checked.result.delay==9,'node check uses matching applied revision');
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
check(call('job_status',{}).job.error.code=='STORAGE_ERROR' && !active && !json(files['/etc/alwayroute/service.json']).enabled && call('get',{}).state.appliedRevision==null,'failed start restores previously stopped service even after candidate core started');

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
printf('PASS %d manager transaction checks\n',checks);
