'use strict';
// A bounded sampler runs outside rpcd; these adapters never start real processes.
let files={},sampling=false,now=100,epochCounter=0,launches=0,probes=0,onSample=null;
function time(){return now;}
function system(command){assert(index(command,'</dev/null >/dev/null 2>&1 &')>=0,'sampler detaches all RPC descriptors');launches++;return 0;}
let fs={
 readfile:function(path){return path=='/proc/sys/kernel/random/uuid'?sprintf('epoch-%d',++epochCounter):files[path] ?? null;},
 unlink:function(path){delete files[path];return true;},
 rename:function(from,to){files[to]=files[from];delete files[from];return true;},
 open:function(path,mode){let owns=false;return {
  write:function(body){files[path]=body;return length(body);},flush:()=>true,close:function(){if(owns)sampling=false;return true;},
  lock:function(mode){if(mode=='u'){sampling=false;owns=false;return true;}if(sampling)return false;sampling=true;owns=true;return true;}
 };},
 popen:function(command){probes++;assert(index(command,'alwayroute-timeout 3')>=0,'stream has external total deadline');assert(index(command,'--header-limits --no-proxy --no-redirect --header-file /tmp/alwayroute/core-api.headers')>=0,'stream bounds headers, bypasses ambient proxies and uses the private API header without following redirects');return {read:function(){if(onSample)onSample();return '{"up":12,"down":34}\n';},close:()=>0};}
};
// TRAFFIC_SOURCE
let checks=0;
function check(ok,message){checks++;assert(ok,message);}
check(!trafficSnapshot().available && launches==0 && probes==0,'unapplied service never launches a sampler');
files[ROOT+'/state.json']='{"appliedRevision":1}';
let reply=trafficSnapshot();trafficSnapshot();
check(!reply.available && launches==1 && probes==0,'RPC returns immediately and throttles duplicate worker launches');
sampleTraffic();reply=trafficSnapshot();
check(reply.available && reply.upload==12 && reply.download==34 && reply.sampledAt==100 && probes==1,'completed sample is exposed with its timestamp');
now=116;check(!trafficSnapshot().available,'expired samples never appear as current rates');
sampleTraffic();invalidateTraffic();check(!trafficSnapshot().available,'same-revision restart invalidates previous samples');
onSample=function(){invalidateTraffic();};sampleTraffic();onSample=null;
check(files[ROOT+'/traffic.json']==null,'a sample crossing a restart epoch is discarded');
onSample=function(){files[ROOT+'/state.json']='{"appliedRevision":2}';};sampleTraffic();onSample=null;
check(files[ROOT+'/traffic.json']==null,'a sample crossing a revision change is discarded');
sampling=true;let previousProbes=probes;sampleTraffic();sampling=false;
check(probes==previousProbes,'concurrent sampler cannot overlap an existing sample');
sampleTraffic();files[ROOT+'/state.json']='{"appliedRevision":null}';
check(!trafficSnapshot().available,'stopped or applying core never exposes a cached success');
printf('PASS %d asynchronous traffic checks\n',checks);
