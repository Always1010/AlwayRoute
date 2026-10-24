'use strict';
import * as fs from 'fs';

const STATUS_ROOT='/tmp/alwayroute',STATUS_TTL=30,STATUS_THROTTLE=5;
function readStatusFile(name) {
 try {let raw=fs.readfile(STATUS_ROOT+'/'+name);return raw==null?null:json(raw);}catch(e){return null;}
}
function writeStatusFile(name,value) {
 let path=STATUS_ROOT+'/'+name,f=fs.open(path+'.new','w',0600);
 if(!f)return false;
 let body=sprintf('%J',value),written=f.write(body),flushed=f.flush(),closed=f.close();
 return written==length(body) && flushed && closed && fs.rename(path+'.new',path);
}
function unknownService() {return {status:'unknown',running:null};}
function unknownCore() {return {status:'unknown',available:null,groups:{}};}
function unknownForwarding() {return {status:'unknown',available:null,running:null,guarded:null,scope:'unknown'};}
function unknownStatus(reason) {
 return {ok:true,snapshot:{status:'unknown',sampledAt:null,expiresAt:null,reason},service:unknownService(),core:unknownCore(),forwarding:unknownForwarding()};
}
function validService(value) {return value?.status=='current' && type(value.running)=='bool' || value?.status=='unknown' && value.running===null;}
function validCore(value) {return type(value?.groups)=='object' && (value.status=='current' && type(value.available)=='bool' || value.status=='unknown' && value.available===null);}
function validForwarding(value) {return value?.status=='unknown' && value.available===null && value.running===null || value?.status=='current' && type(value.available)=='bool' && (value.available===false && value.running===null || value.available===true && type(value.running)=='bool');}
function boundedJson(command,limit) {
 let p=fs.popen('/usr/libexec/alwayroute-timeout 3 '+command+' 2>/dev/null','r');if(!p)return null;
 let body=p.read(limit+1),status=p.close();if(status!=0 || !body || length(body)>limit)return null;
 try{return {value:json(trim(body))};}catch(e){return null;}
}
function statusProcessIdentity(pid) {
 if(type(pid)!='int' || pid<=0)return null;
 let value=fs.readfile('/proc/'+pid+'/stat');if(!value)return null;
 let started=split(split(trim(value),') ')[1] ?? '', ' ')[19];
 return match(started ?? '',/^[0-9]+$/)?sprintf('%d:%s',pid,started):null;
}
function sampleService() {
 let result=boundedJson("ubus call service list '{\"name\":\"alwayroute\"}'",8192);
 if(!result || type(result.value)!='object')return {service:unknownService(),coreEpoch:null,pid:null};
 let response=result.value,entry=response.alwayroute;
 if(entry==null)return {service:{status:'current',running:false},coreEpoch:null,pid:null};
 let instances=entry?.instances;
 if(type(entry)!='object' || type(instances)!='object')return {service:unknownService(),coreEpoch:null,pid:null};
 let found=null;
  for(let name,instance in instances)if(index(['/usr/bin/sing-box','/usr/libexec/alwayroute-core-run'],instance.command?.[0])>=0) {
  if(found)return {service:unknownService(),coreEpoch:null,pid:null};
  found=instance;
 }
 if(!found)return {service:{status:'current',running:false},coreEpoch:null,pid:null};
 if(type(found.running)!='bool')return {service:unknownService(),coreEpoch:null,pid:null};
 if(!found.running)return {service:{status:'current',running:false},coreEpoch:null,pid:null};
 let identity=statusProcessIdentity(found.pid);
 return identity?{service:{status:'current',running:true},coreEpoch:identity,pid:found.pid}:{service:unknownService(),coreEpoch:null,pid:null};
}
function sampleCore(service) {
 if(service.service.status!='current')return unknownCore();
 if(!service.service.running)return {status:'current',available:false,groups:{}};
 let response=boundedJson("/bin/uclient-fetch --header-limits --no-proxy --no-redirect --header-file /tmp/alwayroute/core-api.headers -q -T 2 -O - 'http://127.0.0.1:9090/proxies'",262144)?.value,groups={};
 if(!response?.proxies)return unknownCore();
 for(let tag,proxy in response.proxies)if(proxy?.type=='Selector' && type(proxy.now)=='string')groups[tag]={now:proxy.now};
 return {status:'current',available:true,groups};
}
function sampleForwarding() {
 if(!fs.access('/usr/libexec/alwayroute-forwarding','x'))return {status:'current',available:false,running:null,guarded:null,scope:'unverified'};
 let result=boundedJson('/usr/libexec/alwayroute-forwarding status',8192)?.value;
 if(type(result?.available)!='bool' || type(result?.running)!='bool')return unknownForwarding();
 result.status='current';return result;
}
export function invalidateStatus() {
 fs.unlink(STATUS_ROOT+'/status.json');fs.unlink(STATUS_ROOT+'/status-request.json');
 let id=trim(fs.readfile('/proc/sys/kernel/random/uuid') ?? '');
 if(!length(id) || !writeStatusFile('status-epoch.json',{id}))fs.unlink(STATUS_ROOT+'/status-epoch.json');
};
export function statusSnapshot() {
 let epoch=readStatusFile('status-epoch.json');if(!epoch){invalidateStatus();epoch=readStatusFile('status-epoch.json');}
 let revision=readStatusFile('state.json')?.appliedRevision ?? null,sample=readStatusFile('status.json'),request=readStatusFile('status-request.json'),now=time();
 if(epoch && (!request || request.epoch!=epoch.id || request.revision!==revision || now<request.time || now-request.time>=STATUS_THROTTLE)) {
  if(writeStatusFile('status-request.json',{epoch:epoch.id,revision,time:now}))system('/usr/libexec/alwayroute-status </dev/null >/dev/null 2>&1 &');
 }
 let coreCurrent=!sample?.coreEpoch || statusProcessIdentity(int(split(sample.coreEpoch,':')[0]))==sample.coreEpoch;
 let valid=epoch && sample?.epoch==epoch.id && sample.revision===revision && type(sample.time)=='int' && now>=sample.time && now-sample.time<=STATUS_TTL &&
   validService(sample.service) && validCore(sample.core) && validForwarding(sample.forwarding) && coreCurrent;
 if(!valid)return unknownStatus(sample?'运行状态快照已过期或配置已变化':'等待运行状态采样');
 return {ok:true,snapshot:{status:'current',sampledAt:sample.time,expiresAt:sample.time+STATUS_TTL,revision:sample.revision,epoch:sample.epoch,coreEpoch:sample.coreEpoch ?? null},service:sample.service,core:sample.core,forwarding:sample.forwarding};
};
export function sampleStatus() {
 let lock=fs.open(STATUS_ROOT+'/status.lock','ae',0600);
 if(!lock || !lock.lock('xn')){lock?.close();return;}
 try {
  let epoch=readStatusFile('status-epoch.json'),revision=readStatusFile('state.json')?.appliedRevision ?? null;
  if(epoch) {
   let service=sampleService(),core=sampleCore(service),forwarding=sampleForwarding();
   let sameProcess=!service.coreEpoch || statusProcessIdentity(service.pid)==service.coreEpoch;
   if(sameProcess && readStatusFile('status-epoch.json')?.id==epoch.id && (readStatusFile('state.json')?.appliedRevision ?? null)===revision) {
    writeStatusFile('status.json',{epoch:epoch.id,revision,coreEpoch:service.coreEpoch,time:time(),service:service.service,core,forwarding});
   }
  }
 }catch(e){}
 lock.lock('u');lock.close();
};
