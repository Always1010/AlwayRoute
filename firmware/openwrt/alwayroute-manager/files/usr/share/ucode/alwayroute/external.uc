'use strict';
import * as fs from 'fs';
import { externalController } from 'alwayroute.external-controller';
import { externalIPv4 } from 'alwayroute.external-model';
import { externalBootRules } from 'alwayroute.external-boot';

const EXT_DATA='/etc/alwayroute',EXT_TMP='/tmp/alwayroute';
const EXT_FILES={config:'external-config.json',intent:'external-intent.json',good:'external-lastgood.json',journal:'external-journal.json',mode:'external-mode.json',state:'external-state.json',dnsProbe:'external-dns-probe.json',cancel:'external-stop-request.json',permit:'external-enable-token.json',supervisor:'external-supervisor-state.json'};
function extFail(code,message) {die('ALWAYROUTE:'+code+':'+message);}
function extPrivate(path,kind,mode) {let st=fs.lstat(path);return st?.type==kind && st.uid==0 && st.mode==mode;}
function extInit() {
 for(let path in [EXT_DATA,EXT_TMP]) {
  if(!fs.lstat(path) && !fs.mkdir(path,0700))extFail('STORAGE_ERROR','无法创建外部配置目录');
  if(!extPrivate(path,'directory',0700))extFail('STORAGE_ERROR','外部配置目录不是root私有真实目录');
 }
};
function extPath(key) {if(!EXT_FILES[key])extFail('STORAGE_ERROR','外部存储键无效');return (key=='state' || key=='dnsProbe' || key=='supervisor'?EXT_TMP:EXT_DATA)+'/'+EXT_FILES[key];}
function extRead(key) {
 let path=extPath(key),info=fs.lstat(path);if(!info)return null;
 if(!extPrivate(path,'file',0600) || info.size>32768)extFail('STORAGE_CORRUPT','外部配置文件不私有或超过大小限制');
 let raw=fs.readfile(path);if(raw==null)extFail('STORAGE_ERROR','无法读取外部配置');
 try{return json(raw);}catch(e){extFail('STORAGE_CORRUPT','外部配置损坏，请显式关闭后修复');}
};
function extWritePath(path,data) {
 for(let candidate in [path,path+'.new'])if(fs.lstat(candidate) && !extPrivate(candidate,'file',0600))extFail('STORAGE_ERROR','外部配置文件不是私有普通文件');
 let file=fs.open(path+'.new','w',0600);if(!file)extFail('STORAGE_ERROR','无法创建外部候选');
 let count=file.write(data),flushed=file.flush(),closed=file.close();
 if(count!=length(data) || !flushed || !closed || !fs.rename(path+'.new',path))extFail('STORAGE_ERROR','外部配置原子保存失败');
};
function extWrite(key,value) {extWritePath(extPath(key),sprintf('%J',value));}
function extRemovePath(path) {
 if(!fs.lstat(path))return;
 if(!extPrivate(path,'file',0600) || !fs.unlink(path))extFail('STORAGE_ERROR','外部文件删除失败或归属不明');
};
function extCommand(command) {return system('/usr/libexec/alwayroute-timeout 20 '+command+' >/dev/null 2>&1')==0;}
function extGatewayDns(config,force) {
 let gateway=config?.link?.gatewayAddress,port=config?.dns?.gatewayPort;
 // These are the only interpolated values; neither can contain shell syntax.
 if(!externalIPv4(gateway) || type(port)!='int' || port<1 || port>65535)return null;
 function probe() {return {gateway,port,observedAt:time(),reachable:system('/usr/libexec/alwayroute-timeout 3 nslookup -port='+port+' example.com '+gateway+' >/dev/null 2>&1')==0};}
 function cached() {
  let value=null;try{value=extRead('dnsProbe');}catch(ignored){}
  return value?.gateway==gateway && value.port===port && (type(value.reachable)=='bool' || value.reachable===null) && type(value.observedAt)=='int' && value.observedAt<=time() && time()-value.observedAt<60?value:null;
 }
 for(let candidate in [extPath('dnsProbe'),extPath('dnsProbe')+'.new'])if(fs.lstat(candidate) && !extPrivate(candidate,'file',0600))return force?probe():null;
 if(!force) {let value=cached();if(value)return value;}
 // Status is read without manager.lock. Serialize only the expendable /tmp
 // observation cache, never transaction state. A bad cache cannot block apply.
 let path=EXT_TMP+'/external-dns-probe.lock';
 if(fs.lstat(path) && !extPrivate(path,'file',0600))return force?probe():null;
 let lock=fs.open(path,'ae',0600);
 if(!lock || !lock.lock('xn')) {lock?.close();return force?probe():null;}
 let value=null;
 try {
  if(!force)value=cached();
  if(value==null) {
   // Reserve this interval before querying. If storage cannot cache a result,
   // status must not turn every page poll into another external DNS request.
   if(!force)extWrite('dnsProbe',{gateway,port,observedAt:time(),reachable:null});
   value=probe();
   try{extWrite('dnsProbe',value);}catch(ignored){} // Cache is never a prerequisite.
  }
 }catch(ignored){lock.close();return null;}
 lock.close();return value;
};
function extJson(command) {
 let stream=fs.popen('/usr/libexec/alwayroute-timeout 3 '+command+' 2>/dev/null','r');if(!stream)return null;
 let raw=stream.read(32769),code=stream.close();
 if(code!=0 || raw==null || length(raw)>32768)return null;
 try{return json(raw);}catch(e){return null;}
};
function extService(name) {
 let result=extJson("ubus call service list '{\"name\":\""+name+"\"}'");
 if(type(result)!='object')return null;
 if(!(name in result))return false;
 if(type(result[name])!='object')return null;
 // procd keeps a registered service as {} after its last instance stops.
 if(!('instances' in result[name]))return false;
 if(type(result[name]?.instances)!='object')return null;
 for(let id,instance in result[name].instances)if(instance.running===true) {
  if(name=='alwayroute' && instance.command?.[0]=='/usr/libexec/alwayroute-external-supervisor')continue;
  if(name=='alwayroute-external-dns' && sprintf('%J',instance.command)!=sprintf('%J',['/usr/sbin/dnsmasq','-k','--conf-file='+EXT_TMP+'/external-dns.conf']))return null;
  return true;
 }
 return false;
};
function extDnsRunning() {
 let running=extService('alwayroute-external-dns');if(running!==true)return running;
 let raw=fs.readfile(EXT_TMP+'/external-runtime.json'),config;
 try{config=json(raw);}catch(e){return null;}
 if(type(config?.link?.routerAddress)!='string' || type(config?.dns?.listenPort)!='int')return null;
 let octets=split(config.link.routerAddress,'.');if(length(octets)!=4)return null;
 let address='';for(let i=3;i>=0;i--)address+=sprintf('%02X',int(octets[i]));
 let endpoint=address+sprintf(':%04X',config.dns.listenPort);
 for(let transport in ['udp','tcp']) {
  let file=fs.open('/proc/net/'+transport,'r');if(!file)return null;
  let body=file.read(131073);file.close();if(body==null || length(body)>131072)return null;
  let found=false;
  for(let line in split(body,'\n')) {
   let fields=filter(split(trim(line),' '),x=>length(x)>0);
   if(fields[1]==endpoint && (transport=='udp' || fields[3]=='0A'))found=true;
  }
  if(!found)return false;
 }
 return true;
};
function extNetwork(action) {
 if(index(['prepare','guard','activate','stop'],action)<0 || !extCommand('/usr/libexec/alwayroute-external-forwarding '+action))extFail('EXTERNAL_NETWORK_FAILED','外部转发操作失败，请检查归属和预检条件');
};
function extRuntime(config) {extWritePath(EXT_TMP+'/external-runtime.json',sprintf('%J',config));}
function extBootGuard(config) {
 let directory=EXT_DATA+'/external-boot';
 if(!fs.lstat(directory) && !fs.mkdir(directory,0700))extFail('STORAGE_ERROR','无法创建早期防护目录');
 if(!extPrivate(directory,'directory',0700))extFail('STORAGE_ERROR','早期防护目录不是root私有目录');
 let path=directory+'/guard.nft',rules=externalBootRules(config);
 if(fs.lstat(path) && !extPrivate(path,'file',0600))extFail('STORAGE_ERROR','早期防护文件不安全');
 if(fs.readfile(path)!=rules) {
  extWritePath(path,rules);
  if(system('/bin/sync')!=0)extFail('STORAGE_ERROR','早期防护未持久保存');
 }
 if(!extCommand('/usr/libexec/alwayroute-external-forwarding boot-guard'))extFail('EXTERNAL_BOOT_GUARD_FAILED','早期防护或fw4自动include尚未确认');
}
function extBootClear() {
 let directory=EXT_DATA+'/external-boot';
 if(fs.lstat(directory)) {
  if(!extPrivate(directory,'directory',0700))extFail('STORAGE_ERROR','早期防护目录不安全');
  extRemovePath(directory+'/guard.nft');extRemovePath(directory+'/guard.nft.new');
 }
 if(system('/bin/sync')!=0 || !extCommand('/usr/libexec/alwayroute-external-forwarding boot-stop'))extFail('EXTERNAL_BOOT_GUARD_FAILED','早期防护尚未清理');
}
function extDnsConfig(config) {
 let l=config.link,d=config.dns;
 let lines=['port='+d.listenPort,'listen-address='+l.routerAddress,'bind-interfaces','no-resolv','no-hosts','no-poll','cache-size=0','pid-file='+EXT_TMP+'/external-dns.pid','server='+l.gatewayAddress+'#'+d.gatewayPort,'server=//127.0.0.1#53'];
 for(let domain in d.localDomains)push(lines,'server=/'+domain+'/127.0.0.1#53');
 extWritePath(EXT_TMP+'/external-dns.conf',join('\n',lines)+'\n');
};
function extStopDns() {
 if(!extCommand('/etc/init.d/alwayroute-external-dns stop') || extService('alwayroute-external-dns')!==false)extFail('EXTERNAL_DNS_STOP_FAILED','专用DNS未确认停止');
};
export function externalSelected() {
 for(let key in ['mode','intent','journal'])if(fs.lstat(extPath(key)))return true;
 return false;
};
export function cancelExternalRecovery() {
 extInit();let nonce=trim(fs.readfile('/proc/sys/kernel/random/uuid') ?? '');
 if(!match(nonce,/^[a-f0-9-]{36}$/))extFail('STORAGE_ERROR','无法生成关闭请求标识');
 extWrite('cancel',{disabled:true,nonce});
 if(system('/bin/sync')!=0)extFail('STORAGE_ERROR','关闭请求未持久保存');
};
export function externalCancelToken() {
 extInit();let marker=extRead('cancel');if(marker==null)return null;
 if(marker.disabled!==true || type(marker.nonce)!='string' || !match(marker.nonce,/^[a-f0-9-]{36}$/))extFail('STORAGE_CORRUPT','关闭请求标识损坏，请独立关闭');
 return marker.nonce;
};
function extCancelled() {
 try {let token=externalCancelToken();return token!=null && extRead('permit')?.token!==token;}catch(e){return true;}
}
export function executeExternal(method,args,externalOnly) {
 extInit();
 let engine=externalController({
  read:extRead,write:extWrite,remove:function(key){extRemovePath(extPath(key));},
  cancelled:extCancelled,
  permit:function(expected){
   if(externalCancelToken()!==expected)return false;
   // Acknowledging the captured generation never deletes a marker. A newer
   // close can arrive between comparison and write and still remains pending.
   extWrite('permit',{token:expected});return true;
  },
  needsStop:function(){
   for(let path in [EXT_DATA+'/external-boot/guard.nft',extPath('good'),extPath('journal'),EXT_TMP+'/external-forwarding.owner',EXT_TMP+'/external-dns.conf'])if(fs.lstat(path))return true;
   return false;
  },
  now:time,
  gatewayDns:extGatewayDns,
  bootGuard:extBootGuard,bootClear:extBootClear,
  bootOpen:function(){if(!extCommand('/usr/libexec/alwayroute-external-forwarding boot-open'))extFail('EXTERNAL_BOOT_GUARD_FAILED','早期阻断尚未释放');},
  sync:function(){if(system('/bin/sync')!=0)extFail('STORAGE_ERROR','外部配置同步失败');},
  runtime:extRuntime,
  clearRuntime:function(){extRemovePath(EXT_TMP+'/external-runtime.json');extRemovePath(EXT_TMP+'/external-dns.conf');},
  localCore:function(){let value=extService('alwayroute');if(value==null)extFail('EXTERNAL_PREFLIGHT_FAILED','无法确认本机核心状态');return value;},
  prepare:function(config) {
   if(externalOnly && !extCommand('/usr/libexec/alwayroute-external-forwarding legacy-clear'))extFail('EXTERNAL_PREFLIGHT_FAILED','旧模式资源仍存在或无法核验，请先清理旧模式');
   extRuntime(config);extNetwork('prepare');extDnsConfig(config);
   if(!extCommand('/usr/sbin/dnsmasq --test --conf-file='+EXT_TMP+'/external-dns.conf'))extFail('EXTERNAL_PREFLIGHT_FAILED','专用DNS配置检查失败');
  },
  guard:function(config){extRuntime(config);extNetwork('guard');},
  startDns:function(config){
   extDnsConfig(config);if(!extCommand('/etc/init.d/alwayroute-external-dns restart'))extFail('EXTERNAL_DNS_FAILED','专用DNS启动失败');
   let ready=false;
   for(let i=0;i<3;i++){system('/bin/sleep 1');ready=extDnsRunning()===true;}
   if(!ready)extFail('EXTERNAL_DNS_FAILED','专用DNS进程与UDP/TCP监听未确认');
  },
  activate:function(config){extRuntime(config);extNetwork('activate');},
  stopDns:extStopDns,
  stop:function() {
   extNetwork('stop');extStopDns();
   // rc.common stop already holds this service's procd lock. Delete through
   // ubus directly rather than recursively invoking its init script/lock.
   if(externalOnly) {
    // Pure external packages never own legacy resources. An absent old helper
    // cannot prove that an interrupted package migration removed its rules.
    if(!extCommand('/usr/libexec/alwayroute-external-forwarding legacy-clear'))extFail('EXTERNAL_STOP_FAILED','旧模式转发仍存在或无法核验，请先使用旧包清理');
   }else if(!extCommand('/usr/libexec/alwayroute-forwarding stop'))extFail('EXTERNAL_STOP_FAILED','本机旧转发未确认停止');
   let local=extService('alwayroute');
   if(local==null || externalOnly && local===true || !externalOnly && local===true && !extCommand("ubus call service delete '{\"name\":\"alwayroute\"}'") || extService('alwayroute')!==false)extFail('EXTERNAL_STOP_FAILED','本机旧核心未确认停止');
   if(!externalOnly)extWritePath(EXT_DATA+'/service.json',sprintf('%J',{enabled:false}));
  },
  inspect:function() {
   let network=extJson('/usr/libexec/alwayroute-external-forwarding status') ?? {available:false,running:null,guarded:null,residual:null};
   network.bootGuarded=extJson('/usr/libexec/alwayroute-external-forwarding boot-status')?.guarded ?? null;
   return {network,dns:{running:extDnsRunning()},localCore:extService('alwayroute')};
  }
 });
 let action={external_get:'get',external_status:'status',external_save:'save',external_apply:'apply',external_disable:'disable',external_reconcile:'reconcile',external_shutdown:'shutdown',external_resume:'resume'}[method];
 if(!action)extFail('UNSUPPORTED','不支持的外部代理操作');
 if(action=='apply' && !('cancelToken' in (args ?? {})))args={...(args ?? {}),cancelToken:externalCancelToken()};
 return engine[action](args ?? {});
};
