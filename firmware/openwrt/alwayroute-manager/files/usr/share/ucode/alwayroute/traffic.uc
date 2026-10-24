'use strict';
import * as fs from 'fs';

const ROOT='/tmp/alwayroute';
function readTrafficFile(name) {
 try {let raw=fs.readfile(ROOT+'/'+name);return raw==null?null:json(raw);}catch(e){return null;}
}
function writeTrafficFile(name,value) {
 let path=ROOT+'/'+name,f=fs.open(path+'.new','w',0600);
 if(!f)return false;
 let body=sprintf('%J',value),written=f.write(body),flushed=f.flush(),closed=f.close();
 return written==length(body) && flushed && closed && fs.rename(path+'.new',path);
}
export function invalidateTraffic() {
 fs.unlink(ROOT+'/traffic.json');
 // A separate epoch also rejects a sample spanning a restart of the same revision.
 if(!writeTrafficFile('traffic-epoch.json',{id:trim(fs.readfile('/proc/sys/kernel/random/uuid') ?? sprintf('%d',time()))}))fs.unlink(ROOT+'/traffic-epoch.json');
};
export function trafficSnapshot() {
 let revision=readTrafficFile('state.json')?.appliedRevision,epoch=readTrafficFile('traffic-epoch.json');
 if(revision==null)return {ok:true,available:false,upload:null,download:null,unit:'bytes/s',reason:'当前配置尚未应用'};
 if(!epoch){invalidateTraffic();epoch=readTrafficFile('traffic-epoch.json');}
 let sample=readTrafficFile('traffic.json'),request=readTrafficFile('traffic-request.json'),now=time();
 if(epoch && (!request || request.epoch!=epoch.id || now-request.time>=5 || now<request.time)) {
  if(writeTrafficFile('traffic-request.json',{epoch:epoch.id,time:now}))system('/usr/libexec/alwayroute-traffic </dev/null >/dev/null 2>&1 &');
 }
 let valid=epoch && sample?.epoch==epoch.id && sample.revision==revision && sample.available===true && now>=sample.time && now-sample.time<=15;
 return {ok:true,available:!!valid,upload:valid?sample.upload:null,download:valid?sample.download:null,unit:'bytes/s',sampledAt:valid?sample.time:null,reason:valid?null:'等待核心流量采样'};
};
export function sampleTraffic() {
 let lock=fs.open(ROOT+'/traffic.lock','ae',0600);
 if(!lock || !lock.lock('xn')){lock?.close();return;}
 try {
  let epoch=readTrafficFile('traffic-epoch.json'),revision=readTrafficFile('state.json')?.appliedRevision;
  if(epoch && revision!=null) {
   let p=fs.popen('/usr/libexec/alwayroute-timeout 3 /bin/uclient-fetch --no-redirect --header-file /tmp/alwayroute/core-api.headers -q -T 2 -O - http://127.0.0.1:9090/traffic 2>/dev/null | /bin/busybox head -n 1','r'),sample=null;
   if(p){let body=p.read(4097);p.close();try{if(body && length(body)<=4096)sample=json(trim(body));}catch(e){}}
   if(readTrafficFile('traffic-epoch.json')?.id==epoch.id && readTrafficFile('state.json')?.appliedRevision===revision) {
    let valid=type(sample?.up)=='int' && sample.up>=0 && type(sample?.down)=='int' && sample.down>=0;
    writeTrafficFile('traffic.json',{epoch:epoch.id,revision,time:time(),available:valid,upload:valid?sample.up:null,download:valid?sample.down:null});
   }
  }
 }catch(e){}
 lock.lock('u');lock.close();
};
