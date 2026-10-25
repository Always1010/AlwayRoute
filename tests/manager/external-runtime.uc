'use strict';
// Exercises the real filesystem/command adapter with private in-memory paths.
let runtimeFiles={},metadata={},networkMode='inactive',dnsLive=false,legacyLive=false,commands=[],dnsSocketMissing=false,registeredEmpty=false,gatewayReachable=true,probeLock=true,runtimeNow=100,cacheWriteFailure=false,legacyResidual=false;
function time(){return runtimeNow;}
let fs={
 access:function(path){return false;},
 lstat:function(path){return metadata[path] ?? null;},
 mkdir:function(path,mode){metadata[path]={type:'directory',uid:0,mode};return true;},
 readfile:function(path){return runtimeFiles[path] ?? null;},
 rename:function(from,to){runtimeFiles[to]=runtimeFiles[from];metadata[to]=metadata[from];delete runtimeFiles[from];delete metadata[from];return true;},
 unlink:function(path){delete runtimeFiles[path];delete metadata[path];return true;},
 open:function(path,mode,permissions){
  if(mode=='r')return {read:function(limit){return substr(runtimeFiles[path] ?? '',0,limit);},close:()=>true};
  if(mode=='w' && cacheWriteFailure && index(path,'external-dns-probe.json')>=0)return null;
  metadata[path]={type:'file',uid:0,mode:permissions};
  if(mode=='ae')return {lock:()=>probeLock,close:()=>true};
  return {write:function(value){runtimeFiles[path]=value;return length(value);},flush:()=>true,close:()=>true};
 },
 popen:function(command){
  push(commands,command);let body;
  if(index(command,'alwayroute-external-forwarding status')>=0)body={available:true,running:networkMode=='active',guarded:networkMode=='guarded',residual:networkMode!='inactive'};
  else if(index(command,'ubus call service list')>=0) {
   body={};let name=index(command,'alwayroute-external-dns')>=0?'alwayroute-external-dns':'alwayroute';
   if(registeredEmpty)body[name]={};
   if(name=='alwayroute-external-dns' && dnsLive)body[name]={instances:{external_dns:{running:true,command:['/usr/sbin/dnsmasq','-k','--conf-file=/tmp/alwayroute/external-dns.conf']}}};
   if(name=='alwayroute' && legacyLive)body[name]={instances:{core:{running:true,command:['/usr/bin/sing-box']}}};
  }else die('unexpected command');
  return {read:function(limit){return substr(sprintf('%J',body),0,limit);},close:()=>0};
 }
};
function system(command) {
 push(commands,command);
 if(index(command,'alwayroute-external-forwarding legacy-clear')>=0)return legacyResidual?1:0;
 if(index(command,' nslookup ')>=0)return gatewayReachable?0:1;
 if(index(command,'alwayroute-external-forwarding guard')>=0)networkMode='guarded';
 if(index(command,'alwayroute-external-forwarding activate')>=0)networkMode='active';
 if(index(command,'alwayroute-external-forwarding stop')>=0)networkMode='inactive';
 if(index(command,'alwayroute-external-dns restart')>=0) {
  dnsLive=true;
  for(let transport in ['udp','tcp'])runtimeFiles['/proc/net/'+transport]=dnsSocketMissing?'':sprintf(' 0: 010200C0:041D 00000000:0000 %s\n',transport=='tcp'?'0A':'07');
 }
 if(index(command,'alwayroute-external-dns stop')>=0)dnsLive=false;
 if(index(command,'ubus call service delete')>=0)legacyLive=false;
 return 0;
}
// EXTERNAL_RUNTIME_SOURCE
let checks=0;
function check(ok,message){checks++;assert(ok,message);}
registeredEmpty=true;
let inactive=executeExternal('external_status',{});
check(inactive.state.dns.running===false,'registered procd service without instances is stopped');
check(extService('alwayroute')===false,'empty legacy procd service cannot prevent first external application');
registeredEmpty=false;commands=[];
let config={schema:1,revision:0,enabled:true,family:'ipv4',faultPolicy:'block',link:{interface:'br-lan',routerAddress:'192.0.2.1',gatewayAddress:'192.0.2.2',gatewayMac:'02:00:00:00:00:02'},clients:[{address:'192.0.2.3',mac:'02:00:00:00:00:03'}],dns:{gatewayPort:1053,listenPort:1053,localDomains:['lan']},bypass4:[]};
executeExternal('external_save',{expectedRevision:0,config});
check(length(commands)==1 && commands[0]=='/bin/sync','external save has no core or network calls');
let peer={gateway:'192.0.2.2',revision:1,generation:'synthetic-generation',observedAt:time(),coreReady:true,captureReady:true,dnsReady:true,egressViaRouter:true,returnViaRouter:true,sourcePreserved:true};
let result=executeExternal('external_apply',{expectedRevision:1,peer});
check(result.state.phase=='active' && result.state.dns.running && result.state.localForwarding.running,'production adapter confirms owned forwarding and both DNS sockets');
let dnsConfig=runtimeFiles['/tmp/alwayroute/external-dns.conf'];
check(index(dnsConfig,'server=192.0.2.2#1053')>=0 && index(dnsConfig,'server=//127.0.0.1#53')>=0 && index(dnsConfig,'server=/lan/127.0.0.1#53')>=0,'dedicated DNS separates public, local and unqualified names');
check(index(dnsConfig,'no-resolv')>=0 && runtimeFiles['/etc/config/dhcp']==null,'does not modify shared DNS configuration');
check(length(filter(commands,c=>index(c,'sing-box check')>=0 || index(c,'sing-box run')>=0 || index(c,'127.0.0.1:9090')>=0))==0,'external path never starts, checks or calls the old core');
check(externalSelected(),'explicit external mode prevents legacy boot');
runtimeFiles['/etc/alwayroute/external-config.json']='broken';runtimeFiles['/etc/alwayroute/external-journal.json']='broken';legacyLive=true;
result=executeExternal('external_disable',{});check(result.state.phase=='disabled' && !dnsLive && networkMode=='inactive','real adapter can close with corrupt configuration and journal');
check(json(runtimeFiles['/etc/alwayroute/service.json']).enabled===false,'successful close also persists old core disabled');
check(length(filter(commands,c=>index(c,'ubus call service delete')>=0))>0 && length(filter(commands,c=>index(c,'/etc/init.d/alwayroute stop')>=0))==0,'local core stop avoids recursive init/procd locking');
runtimeFiles['/etc/alwayroute/external-config.json']=sprintf('%J',config);
executeExternal('external_save',{expectedRevision:0,config});dnsSocketMissing=true;
let error=null;try{executeExternal('external_apply',{expectedRevision:1,peer});}catch(e){error=e.message;}
check(error!=null && networkMode=='inactive' && !dnsLive,'DNS process without TCP/UDP listeners cannot commit application');
metadata['/etc/alwayroute/external-config.json'].mode=0644;
error=null;try{executeExternal('external_get',{});}catch(e){error=e.message;}
check(error!=null,'world-readable external config is refused');
executeExternal('external_disable',{});check(networkMode=='inactive','unsafe current file still cannot prevent explicit resource close');
metadata['/etc/alwayroute/external-config.json'].mode=0600;dnsSocketMissing=false;commands=[];
gatewayReachable=false;error=null;
try{executeExternal('external_apply',{expectedRevision:1});}catch(e){error=e.message;}
check(error!=null && networkMode=='inactive' && length(filter(commands,c=>index(c,'alwayroute-external-forwarding guard')>=0 || index(c,'alwayroute-external-forwarding prepare')>=0))==0,'failed real DNS query precedes all forwarding operations');
gatewayReachable=true;commands=[];
result=executeExternal('external_apply',{expectedRevision:1});
check(result.state.phase=='active' && result.state.gatewayDns.status=='reachable' && result.state.peer.status=='unknown','real adapter supports ordinary apply without inventing peer');
check(length(filter(commands,c=>index(c,'/usr/libexec/alwayroute-timeout 3 nslookup -port=1053 example.com 192.0.2.2 >/dev/null 2>&1')==0))==1,'apply forces a new three second bounded query even when failed result was cached');
let probeState=runtimeFiles['/tmp/alwayroute/external-state.json'];commands=[];runtimeNow=131;
result=executeExternal('external_status',{});executeExternal('external_status',{});
check(result.state.phase=='active' && result.state.gatewayDns.ageSeconds==31 && length(filter(commands,c=>index(c,' nslookup ')>=0))==0 && runtimeFiles['/tmp/alwayroute/external-state.json']==probeState,'polling reuses minute cache with honest age and no queries or transaction-state writes');
runtimeNow=160;gatewayReachable=false;commands=[];result=executeExternal('external_status',{});
check(result.state.phase=='degraded' && result.state.gatewayDns.status=='unreachable' && networkMode=='active' && length(filter(commands,c=>index(c,' nslookup ')>=0))==1,'expired observation rechecks once and reports failure without removing fail-closed forwarding');
runtimeNow=220;probeLock=false;commands=[];result=executeExternal('external_status',{});
check(result.state.gatewayDns.status=='unknown' && result.state.phase=='degraded' && length(filter(commands,c=>index(c,' nslookup ')>=0))==0,'busy cache lock never extends expired reachability or causes query storms');
probeLock=true;cacheWriteFailure=true;commands=[];result=executeExternal('external_status',{});executeExternal('external_status',{});
check(result.state.gatewayDns.status=='unknown' && length(filter(commands,c=>index(c,' nslookup ')>=0))==0,'unwritable observation cache prevents repeated polling queries');
cacheWriteFailure=false;gatewayReachable=true;runtimeFiles['/tmp/alwayroute/external-dns-probe.json']='corrupt';
metadata['/tmp/alwayroute/external-dns-probe.json'].mode=0644;
metadata['/tmp/alwayroute/external-dns-probe.lock']={type:'link',uid:0,mode:0600};
result=executeExternal('external_apply',{expectedRevision:1});
check(result.state.appliedRevision==1 && metadata['/tmp/alwayroute/external-dns-probe.json'].mode==0644 && metadata['/tmp/alwayroute/external-dns-probe.lock'].type=='link','unsafe expendable cache never blocks apply or gets permissions repaired');
commands=[];let injection=json(sprintf('%J',config));injection.link.gatewayAddress='192.0.2.2;exit';
check(extGatewayDns(injection,true)==null && length(commands)==0,'probe rejects shell injection before command execution');
executeExternal('external_disable',{});
check(networkMode=='inactive' && length(filter(commands,c=>index(c,' nslookup ')>=0))==0,'independent close ignores corrupt cache and never queries gateway');
print(sprintf('PASS external runtime adapter: %d checks\n',checks));
