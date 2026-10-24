'use strict';
// Runtime status probes run only in the detached sampler, never in the RPC call.
let files={},sampling=false,now=100,epochCounter=0,launches=0,serviceProbes=0,coreProbes=0,forwardingProbes=0;
let coreStart='700',coreReply=true,onCoreProbe=null,uuidAvailable=true;
let serviceReply={alwayroute:{instances:{instance1:{running:true,pid:700,command:['/usr/libexec/alwayroute-core-run']}}}},serviceExit=0;
function time(){return now;}
function processStat() {let fields=['S'];for(let i=1;i<20;i++)push(fields,i==19?coreStart:'0');return '700 (sing-box) '+join(' ',fields);}
function system(command){assert(index(command,'alwayroute-status </dev/null >/dev/null 2>&1 &')>=0,'status sampler detaches all RPC descriptors');launches++;return 0;}
let fs={
 readfile:function(path){if(path=='/proc/sys/kernel/random/uuid')return uuidAvailable?sprintf('status-epoch-%d',++epochCounter):null;if(path=='/proc/700/stat')return processStat();return files[path] ?? null;},
 access:function(path){return path=='/usr/libexec/alwayroute-forwarding';},
 unlink:function(path){delete files[path];return true;},
 rename:function(from,to){files[to]=files[from];delete files[from];return true;},
 open:function(path,mode){let owns=false;return {
  write:function(body){files[path]=body;return length(body);},flush:()=>true,close:function(){if(owns)sampling=false;return true;},
  lock:function(mode){if(mode=='u'){sampling=false;owns=false;return true;}if(sampling)return false;sampling=true;owns=true;return true;}
 };},
 popen:function(command){
  assert(index(command,'alwayroute-timeout 3')>=0,'every status probe has an external deadline');
  let body;
  if(index(command,'ubus call service list')>=0){serviceProbes++;body=sprintf('%J',serviceReply);}
  else if(index(command,'/proxies')>=0){coreProbes++;assert(index(command,'--header-limits --no-proxy --no-redirect --header-file /tmp/alwayroute/core-api.headers')>=0,'core status bounds headers, bypasses ambient proxies and uses the private API header without following redirects');if(onCoreProbe)onCoreProbe();body=coreReply?'{"proxies":{"Proxy":{"type":"Selector","now":"n1"}}}':'{}';}
  else {forwardingProbes++;body='{"available":true,"running":true,"scope":"test"}';}
  return {read:()=>body,close:()=>index(command,'ubus call service list')>=0?serviceExit:0};
 }
};
// STATUS_SOURCE
let checks=0;
function check(ok,message){checks++;assert(ok,message);}
files[STATUS_ROOT+'/state.json']='{"appliedRevision":7}';
let reply=statusSnapshot();statusSnapshot();
check(reply.snapshot.status=='unknown' && reply.service.running===null && launches==1 && serviceProbes==0,'RPC returns explicit unknown immediately and throttles duplicate launches');
sampleStatus();reply=statusSnapshot();
check(reply.snapshot.status=='current' && reply.snapshot.sampledAt==100 && reply.snapshot.revision==7 && reply.snapshot.coreEpoch=='700:700','current snapshot exposes timestamp, revision and core process epoch');
check(reply.service.running===true && reply.core.available===true && reply.core.groups.Proxy.now=='n1' && reply.forwarding.running===true,'completed background probes expose current component states');
coreStart='701';check(statusSnapshot().snapshot.status=='unknown','cached snapshot is rejected immediately after its core process epoch changes');coreStart='700';
now=131;reply=statusSnapshot();
check(reply.snapshot.status=='unknown' && reply.service.running===null && reply.core.available===null && reply.forwarding.running===null,'expired snapshot becomes unknown instead of a false stopped success');
invalidateStatus();delete files[STATUS_ROOT+'/status.json'];now=140;
onCoreProbe=function(){files[STATUS_ROOT+'/state.json']='{"appliedRevision":8}';};sampleStatus();onCoreProbe=null;
check(files[STATUS_ROOT+'/status.json']==null,'sample crossing an applied revision change is discarded');
files[STATUS_ROOT+'/state.json']='{"appliedRevision":8}';invalidateStatus();delete files[STATUS_ROOT+'/status.json'];
onCoreProbe=function(){invalidateStatus();};sampleStatus();onCoreProbe=null;
check(files[STATUS_ROOT+'/status.json']==null,'sample crossing a managed restart epoch is discarded');
invalidateStatus();delete files[STATUS_ROOT+'/status.json'];coreStart='700';
onCoreProbe=function(){coreStart='701';};sampleStatus();onCoreProbe=null;
check(files[STATUS_ROOT+'/status.json']==null,'sample crossing an unannounced core process restart is discarded');
coreStart='700';invalidateStatus();delete files[STATUS_ROOT+'/status.json'];coreReply=false;sampleStatus();reply=statusSnapshot();
check(reply.snapshot.status=='current' && reply.service.running===true && reply.core.status=='unknown' && reply.core.available===null,'failed core HTTP sample remains explicitly unknown while known service state is preserved');
coreReply=true;serviceReply={};serviceExit=0;invalidateStatus();delete files[STATUS_ROOT+'/status.json'];sampleStatus();reply=statusSnapshot();
check(reply.service.status=='current' && reply.service.running===false && reply.core.available===false,'successful empty service list confirms that the core is stopped');
serviceReply={alwayroute:{instances:{}}};invalidateStatus();delete files[STATUS_ROOT+'/status.json'];sampleStatus();reply=statusSnapshot();
check(reply.service.status=='current' && reply.service.running===false,'successful service entry with no instances confirms that the core is stopped');
serviceReply={alwayroute:{instances:{instance1:{running:true,pid:700,command:['/usr/libexec/alwayroute-core-run']}}}};serviceExit=1;invalidateStatus();delete files[STATUS_ROOT+'/status.json'];sampleStatus();reply=statusSnapshot();
check(reply.service.status=='unknown' && reply.service.running===null && reply.core.status=='unknown','nonzero service probe exit remains unknown even when stdout resembles a valid reply');
serviceExit=0;
sampling=true;let before=serviceProbes;sampleStatus();sampling=false;
check(serviceProbes==before,'concurrent status samplers cannot overlap');
check(serviceProbes>0 && coreProbes>0 && forwardingProbes>0,'only the background sampler executes bounded external probes');
uuidAvailable=false;invalidateStatus();before=launches;reply=statusSnapshot();
check(reply.snapshot.status=='unknown' && launches==before,'missing restart epoch fails closed without launching an unbound sample');
printf('PASS %d asynchronous status checks\n',checks);
