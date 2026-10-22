'use strict';
import { sha256 } from 'digest';

// In-memory adapters exercise the actual store transaction code. No host paths,
// networking, process execution, or persistent files are accessed by this suite.
let files={},locked=false,active=false,checkFails=false,allChecksFail=false,failWrite=null;
let helperAvailable=true,stopFails=false,guardCalls=0,stopCalls=0;
let fs={
 mkdir:()=>true,chmod:()=>true,
 readfile:function(path){if(path=='/proc/self/stat')return '123 (ucode)';if(path=='/proc/sys/kernel/random/uuid')return 'test-job';return files[path] ?? null;},
 access:function(path){return path=='/proc/123' || (path=='/usr/libexec/alwayroute-forwarding' && helperAvailable);},
 rename:function(from,to){files[to]=files[from];delete files[from];return true;},
 unlink:function(path){delete files[path];return true;},
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
  if(index(command,'/proxies')>=0){let cfg=json(files['/tmp/alwayroute/runtime.json']),proxies={};for(let o in cfg.outbounds)if(o.type=='selector')proxies[o.tag]={now:o.default,all:o.outbounds};body=sprintf('%J',{proxies});}
  return {read:()=>body,close:()=>0};
 }
};
function system(command){
 if(index(command,'alwayroute-forwarding guard')>=0)guardCalls++;
 if(index(command,'alwayroute-forwarding stop')>=0){stopCalls++;if(stopFails)return 1;}
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
let draft=r.model;
draft.nodes=[{id:'n1',name:'Test',type:'vmess',enabled:true,source:null,server:'example.invalid',port:443,uuid:'00000000-0000-4000-8000-000000000001',security:'auto',alterId:0}];
draft.groups[0].selected='n1';
r=call('save',{expectedRevision:0,model:draft});check(r.ok && r.model.revision==1,'save increments revision');
check(call('save',{expectedRevision:0,model:draft}).error.code=='REVISION_CONFLICT','stale save rejected with stable code');
r=call('apply',{expectedRevision:1});check(r.ok && r.job.status=='running' && !active,'apply queues without starting core in RPC');
check(call('save',{expectedRevision:1,model:r.model}).error.code=='BUSY','queued mutation excluded');
work();r=call('job_status',{});check(!r.busy && r.job.status=='succeeded' && active,'worker completes and releases transaction lock');
check(call('get',{}).state.appliedRevision==1,'applied distinct from saved');
draft=call('get',{}).model;draft.nodes[0].name='Renamed';r=call('save',{expectedRevision:1,model:draft});
check(r.model.revision==2 && r.state.appliedRevision==1,'draft save does not apply');
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
let good=clone(r.model);files['/etc/alwayroute/applying.json']='{"previousRevision":3}';files['/etc/alwayroute/previous.json']=sprintf('%J',good);files['/etc/alwayroute/service.json']='{"enabled":true}';
check(boot() && json(files['/tmp/alwayroute/state.json']).appliedRevision==null,'boot pending transaction restores without claiming loaded');
printf('PASS %d manager transaction checks\n',checks);
