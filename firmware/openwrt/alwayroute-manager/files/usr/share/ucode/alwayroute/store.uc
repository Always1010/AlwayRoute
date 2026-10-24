'use strict';
import * as fs from 'fs';
import { sha256 } from 'digest';
import { fail, clone, empty, normalize, validate, effective, generateRuntimeValidated, policyCatalog, modelLimits } from 'alwayroute.model';
import { parse } from 'alwayroute.subscription';
import { selectionPlan } from 'alwayroute.selection';
import { trafficSnapshot, invalidateTraffic } from 'alwayroute.traffic';
import { statusSnapshot, invalidateStatus } from 'alwayroute.status';

const DATA='/etc/alwayroute', TMP='/tmp/alwayroute', CORE_HEADER=TMP+'/core-api.headers', CORE_LOCK=TMP+'/core.lock', CORE_HEADER_PREFIX='Authorization: Bearer ';
let verifiedModelBytes=null,verifiedModel=null;
let verifiedModels=[];
function privatePath(path,type,mode) {let info=fs.lstat(path);return info?.type==type && info.uid==0 && info.mode==mode;}
function init() {
 if(!fs.access(DATA))fs.mkdir(DATA,0700);
 let info=fs.lstat(TMP);
 if(!info && !fs.mkdir(TMP,0700))fail('STORAGE_ERROR','无法创建临时配置目录');
 if(!privatePath(TMP,'directory',0700))fail('STORAGE_ERROR','临时配置目录不是root私有真实目录');
}
function read(path, fallback) {let s=fs.readfile(path);if(s==null)return fallback;try{return json(s);}catch(e){fail('STORAGE_CORRUPT','持久配置损坏，拒绝覆盖；请使用恢复功能');}}
function write(path,value,raw) {
 let data=raw===true?value:sprintf('%J',value), f=fs.open(path+'.new','w',0600);
 if(!f)fail('STORAGE_ERROR','无法创建配置候选');
 fs.chmod(path+'.new',0600);
 let n=f.write(data),flushed=f.flush(),closed=f.close();
 if(n!=length(data) || !flushed || !closed || !fs.rename(path+'.new',path))fail('STORAGE_ERROR','配置原子保存失败');
};
function writePrivate(path,data) {
 if(fs.lstat(path+'.new'))fail('STORAGE_ERROR','私密运行候选路径已存在');
 let f=fs.open(path+'.new','w',0600);
 if(!f || !fs.chmod(path+'.new',0600) || !privatePath(path+'.new','file',0600)) {f?.close();fs.unlink(path+'.new');fail('STORAGE_ERROR','无法创建私密运行文件');}
 let n=f.write(data),flushed=f.flush(),closed=f.close();
 if(n!=length(data) || !flushed || !closed) {fs.unlink(path+'.new');fail('STORAGE_ERROR','私密运行文件原子保存失败');}
 if(!fs.rename(path+'.new',path)) {fs.unlink(path+'.new');fail('STORAGE_ERROR','私密运行文件原子保存失败');}
 if(!privatePath(path,'file',0600)) {fs.unlink(path);fail('STORAGE_ERROR','私密运行文件原子保存失败');}
}
function withCoreLock(callback) {
 let existing=fs.lstat(CORE_LOCK);
 if(existing && !privatePath(CORE_LOCK,'file',0600))fail('STORAGE_ERROR','核心运行锁不是root私有普通文件');
 let lock=fs.open(CORE_LOCK,'ae',0600);
 if(!lock || !existing && (!fs.chmod(CORE_LOCK,0600) || !privatePath(CORE_LOCK,'file',0600)) || !lock.lock('x')) {lock?.close();fail('STORAGE_ERROR','无法取得核心运行配置锁');}
 let result,error;
 try {result=callback();}catch(e){error=e;}
 lock.lock('u');lock.close();if(error)die(error.message);return result;
}
function clearCoreRuntimeUnlocked() {fs.unlink(CORE_HEADER);fs.unlink(CORE_HEADER+'.new');fs.unlink(TMP+'/runtime.json');fs.unlink(TMP+'/runtime.json.new');}
function clearCoreRuntime() {return withCoreLock(clearCoreRuntimeUnlocked);}
function newCoreSecret() {
 let secret=trim(fs.readfile('/proc/sys/kernel/random/uuid') ?? '');
 if(!match(secret,/^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$/))fail('CORE_CREDENTIAL_FAILED','内核随机源不可用，拒绝启动核心接口');
 return secret;
}
function installCoreSecretUnlocked(config,secret) {
 clearCoreRuntimeUnlocked();
 try {
  secret=secret ?? newCoreSecret();
  config=clone(config);config.experimental.clash_api.secret=secret;
  writePrivate(CORE_HEADER,CORE_HEADER_PREFIX+secret);writePrivate(TMP+'/runtime.json',sprintf('%J',config));
  return config;
 }catch(e){clearCoreRuntimeUnlocked();die(e.message);}
}
function installCoreModel(m) {
 return withCoreLock(function() {
  clearCoreRuntimeUnlocked();
  try {let secret=newCoreSecret();return installCoreSecretUnlocked(generateRuntimeValidated(m,secret),secret);}
  catch(e){clearCoreRuntimeUnlocked();die(e.message);}
 });
}
function coreHeaderSecret() {
 let header=fs.readfile(CORE_HEADER,1025);
 if(type(header)!='string' || substr(header,0,length(CORE_HEADER_PREFIX))!=CORE_HEADER_PREFIX)return null;
 let secret=substr(header,length(CORE_HEADER_PREFIX));
 return length(header)<=1024 && match(secret,/^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$/)?secret:null;
}
function normalized(m) {
 if(m==null)return null;
 let bytes=sprintf('%J',m);
 for(let cached in verifiedModels)if(cached.bytes==bytes)return clone(cached.model);
 let current=validate(normalize(m));
 push(verifiedModels,{bytes,model:clone(current)});while(length(verifiedModels)>3)shift(verifiedModels);
 return current;
}
function model() {
 let pending=read(DATA+'/applying.json',null);
 if(pending?.previousCurrent)return normalized(pending.previousCurrent);
 let raw=fs.readfile(DATA+'/current.json');
 if(raw==null)return normalized(empty());
 // Cache only byte-identical, already validated data. Another worker or an
 // external edit invalidates this immediately; readers always receive a copy.
 if(raw===verifiedModelBytes && verifiedModel!=null)return clone(verifiedModel);
 let decoded;
 try{decoded=json(raw);}catch(e){fail('STORAGE_CORRUPT','持久配置损坏，拒绝覆盖；请使用恢复功能');}
 let current=normalized(decoded);
 verifiedModelBytes=raw;verifiedModel=clone(current);
 return current;
}
function lastGood() {
 let pending=read(DATA+'/applying.json',null);
 if(!pending)return normalized(read(DATA+'/lastgood.json',null));
 return pendingGood(pending);
}
function pendingGood(pending) {
 // Old deployed markers stored their transaction snapshot in previous.json.
 // New markers own that snapshot, leaving previous.json as rollback history.
 let good=pending.previousRevision==null?null:normalized(pending.previousGood ?? read(DATA+'/previous.json',null));
 return good?.revision==pending.previousRevision?good:null;
}
function restoreMetadata(pending,good,service) {
 if(pending.previousCurrent)write(DATA+'/current.json',normalized(pending.previousCurrent));
 if(good)write(DATA+'/lastgood.json',good);
 else if(fs.readfile(DATA+'/lastgood.json')!=null && !fs.unlink(DATA+'/lastgood.json'))fail('STORAGE_ERROR','候选应用副本无法撤销');
 write(DATA+'/service.json',service);
 if('previousHistory' in pending) {
  if(pending.previousHistory!=null)write(DATA+'/previous.json',pending.previousHistory,true);
  else if(fs.readfile(DATA+'/previous.json')!=null && !fs.unlink(DATA+'/previous.json'))fail('STORAGE_ERROR','历史配置副本无法撤销');
 }
 system('/bin/sync');
 if(!fs.unlink(DATA+'/applying.json'))fail('STORAGE_ERROR','恢复提交标志无法清除');system('/bin/sync');
}
function state(m) {
 m=m ?? model();let runtime=read(TMP+'/state.json',{}),timeout=read(TMP+'/restore-timeout.json',null),error=runtime.lastError;
 if(!error && runtime.restoringRevision!=null && timeout?.revision===runtime.restoringRevision && timeout.epoch===read(TMP+'/status-epoch.json',null)?.id)error=timeout.message;
 return {savedRevision:m.revision,appliedRevision:runtime.appliedRevision ?? null,healthy:runtime.healthy ?? 'unverified',lastError:error ?? null,lastFailure:runtime.lastFailure ?? null};
}
function jobStatus() {
 let job=read(TMP+'/job.json',null);
 if(job?.status=='running' && (job.pid?!fs.access('/proc/'+job.pid):time()-job.started>10)) {
  // Recheck under the worker claim lock; the snapshot may precede PID registration.
  let lock=fs.open(TMP+'/manager.lock','ae',0600);
  if(lock && lock.lock('xn')) {
   try {
    job=read(TMP+'/job.json',null);
    if(job?.status=='running' && (job.pid?!fs.access('/proc/'+job.pid):time()-job.started>10)) {
     let failed=clone(job);failed.status='failed';failed.error={code:'JOB_INTERRUPTED',message:'后台事务中断；请检查状态，启动服务会从上一份可用配置恢复'};
     write(TMP+'/job.json',failed);job=failed;
    }
   }catch(e){}
   lock.lock('u');lock.close();
  }else lock?.close();
 }
 return {ok:true,busy:job?.status=='running',job};
};
function event(message,level) {let entries=read(TMP+'/events.json',[]);push(entries,{time:time(),level:level ?? 'info',message});while(length(entries)>20)shift(entries);write(TMP+'/events.json',entries);}
function result(m) {
 m=m ?? model();let updates=read(DATA+'/subscription-status.json',{});
 for(let s in m.subscriptions)if(updates[s.id])s.lastError=updates[s.id].ok?null:'订阅更新失败：'+updates[s.id].code;
 return {ok:true,model:m,state:state(m)};
};
function expected(args,m) {if(type(args.expectedRevision)!='int' || args.expectedRevision!=m.revision)fail('REVISION_CONFLICT','配置已由其他操作更新，请重新加载');}
function saved(m) {validate(m);write(DATA+'/current.json',m);system('/bin/sync');event('配置已保存');return result(m);}
function command(cmd) {return system(cmd+' >/dev/null 2>&1')==0;}
function running() {return command('/usr/libexec/alwayroute-timeout 3 /etc/init.d/alwayroute running');}
function fetchJson(path, stream, limit) {
 limit=limit ?? 65536;
 let command='/usr/libexec/alwayroute-timeout 3 /bin/uclient-fetch --header-limits --no-proxy --no-redirect --header-file /tmp/alwayroute/core-api.headers -q -T 2 -O - '+"'http://127.0.0.1:9090"+path+"' 2>/dev/null";
 if(stream)command+=' | /bin/busybox head -n 1';
 let p=fs.popen(command,'r');if(!p)return null;
 let s=p.read(limit+1),status=p.close();if(status!=0 || !s || length(s)>limit)return null;
 try{return json(trim(s));}catch(e){return null;}
};
function forwarding(action) {
 if(!fs.access('/usr/libexec/alwayroute-forwarding','x'))return action=='status'?{available:false,scope:'unverified'}:false;
 if(action=='status') {let p=fs.popen('/usr/libexec/alwayroute-timeout 3 /usr/libexec/alwayroute-forwarding status 2>/dev/null','r');if(!p)return {available:false,scope:'unverified'};let s=p.read(8192),status=p.close();if(status!=0)return {available:false,scope:'unverified'};try{return json(s);}catch(e){return {available:false,scope:'unverified'};}}
 return command('/usr/libexec/alwayroute-forwarding '+action);
};
function coreStatus() {
 let p=fetchJson('/proxies',false,262144),groups={};
 if(!p?.proxies)return {available:false,groups};
 for(let tag,proxy in p.proxies)if(proxy?.type=='Selector' && type(proxy.now)=='string')groups[tag]={now:proxy.now};
 return {available:true,groups};
}
function checkConfig(m) {
 installCoreModel(m);
 if(!command('/usr/bin/sing-box check -c /tmp/alwayroute/runtime.json')){clearCoreRuntime();fail('CORE_CHECK_FAILED','核心拒绝配置，原应用保持可恢复');}
}
function selected(g) {return g.id=='Other' && g.selected=='block'?'direct':g.selected;}
function choicesMatch(m,core) {
 if(!core?.available)return false;
 for(let g in m.groups)if(core.groups[g.id]?.now!=selected(g))return false;
 return true;
}
function processIdentity(pid) {
 if(type(pid)!='int' || pid<=0)return null;
 let stat=fs.readfile('/proc/'+pid+'/stat');if(!stat)return null;
 let started=split(split(trim(stat),') ')[1] ?? '', ' ')[19];
 return match(started ?? '',/^[0-9]+$/)?sprintf('%d:%s',pid,started):null;
}
function coreProcess() {
 let p=fs.popen("/usr/libexec/alwayroute-timeout 3 ubus call service list '{\"name\":\"alwayroute\"}' 2>/dev/null",'r');if(!p)return null;
 let body=p.read(8193),status=p.close();if(status!=0 || !body || length(body)>8192)return null;
 try {
  let service=json(body),found=null;
  for(let name,instance in service.alwayroute?.instances ?? {})if(instance.running && index(['/usr/bin/sing-box','/usr/libexec/alwayroute-core-run'],instance.command?.[0])>=0) {
   let identity=processIdentity(instance.pid);if(!identity || found)return null;
   found={pid:instance.pid,identity};
  }
  return found;
 }catch(e){return null;}
}
function waitCore(m,previous,attempts) {
 // Each API read has its own bounded timeout. A procd restart is asynchronous:
 // reject even matching choices until the old process has actually exited.
 attempts=attempts ?? 10;
 for(let i=0;i<attempts;i++) {
  let current=coreProcess(),retired=!previous || processIdentity(previous.pid)!=previous.identity;
  if(current && retired && running() && choicesMatch(m,coreStatus()))return true;
  if(i<attempts-1)system('/bin/sleep 1');
 }
 return false;
}
function failureCode(error) {
 let text=error.message ?? '',marker=index(text,'ALWAYROUTE:'),code=marker>=0?split(substr(text,marker+11),':')[0]:null;
 return index(['UNCONFIGURED','CORE_CREDENTIAL_FAILED','CORE_CHECK_FAILED','CORE_START_FAILED','CORE_LOAD_FAILED','CORE_SELECT_FAILED','FORWARDING_CHECK_FAILED','FORWARDING_GUARD_FAILED','FORWARDING_APPLY_FAILED','STORAGE_ERROR'],code)>=0?code:'INTERNAL';
}
function putSelection(id,target) {
 // IDs are model-validated, and JSON is passed in a private file, never shell input.
 target=target=='block'?'direct':target;
 write(TMP+'/selection.json',{name:target});
 let status=system('/usr/libexec/alwayroute-timeout 3 /bin/uclient-fetch --header-limits --no-proxy --no-redirect --header-file /tmp/alwayroute/core-api.headers -q -T 2 --method PUT --header "Content-Type: application/json" --body-file /tmp/alwayroute/selection.json -O /dev/null http://127.0.0.1:9090/proxies/'+id+' >/dev/null 2>&1');
 fs.unlink(TMP+'/selection.json');
 if(status!=0) {
  // A lost response does not prove that the PUT was rejected. Only this
  // validated selector target may acknowledge an ambiguous transport result;
  // switchSelections still confirms every group before committing anything.
  for(let i=0;i<3;i++) {
   if(running() && coreStatus().groups?.[id]?.now==target)return;
   if(i<2)system('/bin/sleep 1');
  }
  fail('CORE_SELECT_FAILED','核心选择请求未确认（退出状态 '+status+'），正在恢复上一份配置');
 }
}
function liveSelectionPlan(next) {
 let previous=model(),current=state(previous),good=lastGood();
 if(current.appliedRevision!==previous.revision || good?.revision!==previous.revision || sprintf('%J',good)!=sprintf('%J',previous))return null;
 let runtime=read(TMP+'/runtime.json',null),secret=coreHeaderSecret();
 if(!secret || runtime?.experimental?.clash_api?.secret!==secret)return null;
 let plan=selectionPlan(previous,next,runtime,true);
 if(!plan || !choicesMatch(previous,coreStatus()))return null;
 let f=forwarding('status');
 if(f.available!==true || f.guarded || f.running!==(previous.mode!='direct'))return null;
 return plan;
}
function switchSelections(m,plan) {
 for(let change in plan.changes)putSelection(change.id,change.after);
 // Keep a service respawn on the same confirmed choice; persistent boot recovery
 // remains governed by lastgood and the durable applying marker.
 withCoreLock(function() {
  let runtime=read(TMP+'/runtime.json',null),secret=coreHeaderSecret(),planned=plan.config?.experimental?.clash_api?.secret;
  if(!secret || secret!==planned || runtime?.experimental?.clash_api?.secret!==secret)fail('CORE_SELECT_FAILED','核心凭据在选择提交期间已变化，正在恢复上一份配置');
  writePrivate(TMP+'/runtime.json',sprintf('%J',plan.config));
 });
 if(!waitCore(m,null,3))fail('CORE_SELECT_FAILED','核心实际选择未确认，正在恢复上一份配置');
}
function restart(m) {
 if(m.mode!='direct')for(let g in m.groups)if(g.id=='Proxy' && g.selected=='direct')fail('UNCONFIGURED','请先为 Proxy 选择已启用代理节点');
 let previous=coreProcess();
 if(!previous && running())fail('CORE_LOAD_FAILED','无法确认现有核心进程身份，拒绝把旧实例当作新配置');
 checkConfig(m);
 invalidateTraffic();invalidateStatus();
 if(!forwarding('prepare'))fail('FORWARDING_CHECK_FAILED','转发预检失败');
 if(!forwarding('guard'))fail('FORWARDING_GUARD_FAILED','无法建立故障阻断，保留当前核心');
 write(TMP+'/state.json',{appliedRevision:null,healthy:'unverified'});
 write(TMP+'/restarting.json',{guarded:true});
 let restarted=command('/etc/init.d/alwayroute restart');fs.unlink(TMP+'/restarting.json');
 if(!restarted)fail('CORE_START_FAILED','核心启动失败或转发状态转换失败');
 if(!waitCore(m,previous))fail('CORE_LOAD_FAILED','新核心进程及全部策略选择未在等待窗口内确认');
 if(!forwarding('activate'))fail('FORWARDING_APPLY_FAILED','转发应用失败');
};
function recover(good,wasRunning) {
 let recoveryCode=null;
 if(good && wasRunning) {try{restart(good);return {restored:true,guarded:false};}catch(e){recoveryCode=failureCode(e);}}
 if(!wasRunning) {
  // Keep interception guarded while removing a candidate started by this attempt.
  try {
   let stopped=!running();
   if(!stopped) {
    write(TMP+'/restarting.json',{guarded:true});
    stopped=command('/etc/init.d/alwayroute stop') && !running();fs.unlink(TMP+'/restarting.json');
   }
   if(stopped && forwarding('stop')){clearCoreRuntime();return {restored:false,stopped:true,guarded:false};}
  }catch(e){}
 }
 return {restored:false,guarded:forwarding('guard'),errorCode:recoveryCode ?? 'RECOVERY_UNCONFIRMED'};
};
function sameContent(a,b) {
 if(!a || !b)return false;
 a=clone(a);b=clone(b);delete a.revision;delete b.revision;
 return sprintf('%J',a)==sprintf('%J',b);
}
function applyModel(m,commitCurrent,plan,previousCurrent) {
 let good=lastGood(),wasRunning=running(),service=read(DATA+'/service.json',{enabled:false}),before=commitCurrent?(previousCurrent ?? model()):null;
 let pending={previousRevision:good?.revision ?? null,previousGood:good,previousHistory:fs.readfile(DATA+'/previous.json'),previousService:service,previousRunning:wasRunning};
 if(commitCurrent)pending.previousCurrent=before;
 // The candidate is only in tmp; current and lastgood remain valid across power loss.
 try {
  write(DATA+'/applying.json',pending);system('/bin/sync');
  if(plan)switchSelections(m,plan);else restart(m);
  write(DATA+'/lastgood.json',m);write(DATA+'/service.json',{enabled:true});
  write(TMP+'/state.json',{appliedRevision:m.revision,healthy:'unverified'});
  if(commitCurrent)write(DATA+'/current.json',m);
  if(good && !sameContent(good,m))write(DATA+'/previous.json',good);
  system('/bin/sync');
  if(!fs.unlink(DATA+'/applying.json'))fail('STORAGE_ERROR','应用提交标志无法清除');system('/bin/sync');
 }catch(e) {
  let recovery=recover(good,wasRunning);
  // Recovery runs even if flash is full or read-only. An uncleared marker makes
  // the next boot uses its own snapshot instead of a half-committed candidate.
  try {restoreMetadata(pending,good,service);}catch(storageError){}
  let message=recovery.restored?'应用失败，已恢复上一份可用配置':recovery.stopped?'应用失败，服务已恢复停止状态':recovery.guarded?'应用及恢复失败，已进入故障阻断':'应用及恢复失败，故障阻断未确认；保留核心并需人工处理';
  let lastFailure={code:failureCode(e),recoveryCode:recovery.errorCode ?? null};
  if(lastFailure.recoveryCode)message+='（恢复阶段：'+lastFailure.recoveryCode+'）';
  try {write(TMP+'/state.json',{appliedRevision:recovery.restored?good.revision:null,healthy:'unverified',lastError:message,lastFailure});event(message,'error');}catch(stateError){}
  die(e.message);
 }
 try {event('核心加载已确认；出口与终端接管仍须实测');}catch(logError){}
 return {ok:true,state:state(m),activation:plan?'selector':'restart'};
};
function configureCandidate(next) {
 next=normalized(next);
 if(next.mode=='global')for(let g in next.groups)if(g.id=='Proxy' && g.selected=='direct')fail('UNCONFIGURED','请先为 Proxy 选择已启用代理节点');
 if(running())return applyModel(next,true,liveSelectionPlan(next));
 // A stopped service validates the next start without changing its enabled state.
 checkConfig(next);clearCoreRuntime();write(DATA+'/current.json',next);system('/bin/sync');
 try {event('配置已确认，将用于下次启动');}catch(logError){}
 return {ok:true,state:state(next)};
}
function refresh(args,m) {
 let s=null;for(let candidate in m.subscriptions)if(candidate.id==args.subscriptionId)s=candidate;
 if(!s || !s.enabled)fail('INVALID_SUBSCRIPTION','订阅不存在或已停用');
 let content=args.content;
 if(!content) {
  // URL is staged in a root-only file; downloader diagnostics are suppressed.
  write(TMP+'/fetch.json',{url:s.url,allowHttp:s.allowHttp===true});
  if(!command('/usr/libexec/alwayroute-fetch'))fail('FETCH_FAILED','HTTPS 订阅获取失败，原节点保持不变');
  content=fs.readfile(TMP+'/subscription.body',131073);
 }
 let incoming=parse(content,s.id,sha256,m.nodes), next=clone(m);
 next.nodes=filter(next.nodes,n=>n.source!=s.id);for(let n in incoming)push(next.nodes,n);next.revision++;
 for(let item in next.subscriptions)if(item.id==s.id){item.lastUpdate=time();delete item.lastError;}
 // validate rejects removal of selected or rule-referenced node. No silent fallback.
 validate(next);let response=args.activate===true?configureCandidate(next):saved(next);response.imported=length(incoming);return response;
};
function redact(m) {m=clone(m);for(let n in m.nodes)n.uuid='[redacted]';for(let s in m.subscriptions)s.url='https://redacted.invalid/';for(let k,o in m.overrides)if(o.patch?.uuid)o.patch.uuid='[redacted]';return m;}
function cancelCheck(args) {
 let job=read(TMP+'/job.json',null);
 if(type(args.jobId)!='string' || !match(args.jobId,/^[A-Za-z0-9_-]{1,64}$/) || job?.id!=args.jobId || job.method!='check' || job.status!='running')fail('INVALID_JOB','检测任务已结束或已变化，请重新读取');
 // A separate marker bypasses manager.lock without modifying the worker snapshot.
 write(TMP+'/check-cancel-'+job.id,{cancelled:true});
 return {ok:true,jobId:job.id,cancelling:true};
}
function checkNodes(args,m) {
 for(let key,kind in {nodeId:'string',subscriptionId:'string',nodeIds:'array',scope:'string',retryFailed:'bool'})if(index(keys(args),key)>=0 && type(args[key])!=kind)fail('INVALID_CHECK','检测范围或参数类型无效');
 let nodeId=args.nodeId ?? '',subscriptionId=args.subscriptionId ?? '',ids=args.nodeIds ?? [],scope=args.scope ?? '',retry=args.retryFailed ?? false;
 if(type(nodeId)!='string' || type(subscriptionId)!='string' || type(scope)!='string' || type(ids)!='array' || type(retry)!='bool' || length(ids)>modelLimits().nodes)fail('INVALID_CHECK','检测范围或参数类型无效');
 if(length(nodeId) && !match(nodeId,/^[A-Za-z0-9_-]{1,64}$/) || length(subscriptionId) && !match(subscriptionId,/^[A-Za-z0-9_-]{1,64}$/))fail('INVALID_CHECK','检测标识无效');
 let wanted={};
 for(let id in ids) {
  if(type(id)!='string' || !match(id,/^[A-Za-z0-9_-]{1,64}$/))fail('INVALID_NODE','节点标识无效');
  if(!length(filter(m.nodes,n=>n.id==id)))fail('INVALID_NODE','所选节点不存在，请重新读取');
  wanted[id]=true;
 }
 if(!length(scope))scope=length(nodeId)?'node':length(subscriptionId)?'subscription':'';
 if(index(['node','subscription','selected','all'],scope)<0 ||
    scope=='node' && (!length(nodeId) || length(subscriptionId) || length(ids)) ||
    scope=='subscription' && (!length(subscriptionId) || length(nodeId) || length(ids)) ||
    scope=='selected' && (!length(ids) || length(nodeId) || length(subscriptionId)) ||
    scope=='all' && (length(nodeId) || length(subscriptionId) || length(ids)))fail('INVALID_CHECK','请明确选择单节点、订阅、非空节点列表或全部节点，不能混合范围');
 if(scope=='node' && !length(filter(m.nodes,n=>n.id==nodeId)))fail('INVALID_NODE','节点不存在');
 if(scope=='subscription' && !length(filter(m.subscriptions,s=>s.id==subscriptionId)))fail('INVALID_SUBSCRIPTION','订阅不存在');
 let current=state(m),nodes=effective(m),checks=read(TMP+'/checks.json',{}),candidates=filter(m.nodes,n=>scope=='all' || scope=='node' && n.id==nodeId || scope=='subscription' && n.source==subscriptionId || scope=='selected' && wanted[n.id]);
 if(current.appliedRevision==null || current.savedRevision!==current.appliedRevision || !running())fail('NOT_APPLIED','请先启动服务并应用当前配置，再检查节点');
 nodes=filter(nodes,n=>length(filter(candidates,c=>c.id==n.id)));
 let skipped=length(candidates)-length(nodes);
 if(retry)nodes=filter(nodes,n=>checks[n.id]?.checkedRevision===current.appliedRevision && checks[n.id]?.healthy=='failed');
 if(!length(nodes))fail(scope=='node'?'INVALID_NODE':'NO_NODES',retry?'此范围没有当前配置下已失败的可检测节点':'此范围没有已启用且未排除的节点');
 let job=read(TMP+'/job.json',null),owned=args._jobId!=null && job?.id==args._jobId && job.method=='check';
 let progress={scope,retryFailed:retry,skipped,total:length(nodes),completed:0,passed:0,failed:0,currentNodeId:null},outcomes={},cancelled=false;
 for(let n in nodes) {
  if(owned && fs.readfile(TMP+'/check-cancel-'+job.id)!=null){cancelled=true;break;}
  progress.currentNodeId=n.id;
  if(owned){job.progress=clone(progress);job.checks=clone(outcomes);write(TMP+'/job.json',job);}
  let r=fetchJson('/proxies/'+n.id+'/delay?timeout=2000&url=https%3A%2F%2Fwww.gstatic.com%2Fgenerate_204'),passed=type(r?.delay)=='int' && r.delay>0;
  let outcome={ok:true,nodeId:n.id,available:passed,delay:passed?r.delay:null,healthy:passed?'passed':'failed',reason:passed?null:'探测失败或超时',checkedRevision:current.appliedRevision,time:time()};
  checks[n.id]=outcome;outcomes[n.id]=outcome;progress.completed++;
  if(passed)progress.passed++;else progress.failed++;
  for(let key in keys(checks))if(!length(filter(m.nodes,item=>item.id==key)))delete checks[key];
  write(TMP+'/checks.json',checks);
  progress.currentNodeId=null;
  if(owned){job.progress=clone(progress);job.checks=clone(outcomes);write(TMP+'/job.json',job);}
 }
 if(owned && fs.readfile(TMP+'/check-cancel-'+job.id)!=null)cancelled=true;
 let response={ok:true,scope,retryFailed:retry,skipped,cancelled,checks:outcomes,total:progress.total,completed:progress.completed,passed:progress.passed,failed:progress.failed};
 if(scope=='node' && outcomes[nodeId])for(let key,value in outcomes[nodeId])response[key]=value;
 return response;
}
function execute(method,args) {
 if(method=='capabilities')return {ok:true,schema:1,protocols:['vmess'],subscriptionFormats:['vmess-uri','base64-vmess-list','clash-json','clash-yaml-block-subset','clash-yaml-flow-scalars'],limits:modelLimits(),forwarding:'unverified',nodeCheck:true,subscriptionCheck:true,batchCheck:true,allNodesCheck:true,retryFailedCheck:true,logs:true,policyPresets:policyCatalog()};
 if(method=='get')return result();
 if(method=='job_status')return jobStatus();
 if(method=='status') {let current=model(),runtime=statusSnapshot();runtime.state=state(current);runtime.checks=read(TMP+'/checks.json',{});return runtime;}
 if(method=='traffic')return trafficSnapshot();
 if(method=='logs') {let entries=read(TMP+'/events.json',[]),limit=int(args.limit ?? 20);if(limit<1 || limit>20)limit=20;return {ok:true,entries:slice(entries,-limit)};}
 if(method=='export')return {ok:true,model:args.includeSecrets?model():redact(model()),redacted:!args.includeSecrets};
 let interrupted=read(DATA+'/applying.json',null);
 if(method=='check') {
  if(interrupted)fail('NOT_APPLIED','配置事务尚未恢复，请先确认服务状态');
  return checkNodes(args,model());
 }
 if(interrupted && !(method=='service' && args.action=='stop')) {
  let good=lastGood(),service=interrupted.previousService ?? read(DATA+'/service.json',{enabled:false});
  let recovery=recover(good,interrupted.previousRunning ?? service.enabled);
  if(!recovery.restored && !recovery.stopped)fail('RECOVERY_FAILED','上次事务尚未恢复，已请求故障阻断；请重试或显式停止服务');
  restoreMetadata(interrupted,good,service);
  write(TMP+'/state.json',{appliedRevision:recovery.restored?good.revision:null,healthy:'unverified'});
 }
 let m,damagedCurrent=null;
 try {m=model();}catch(e) {
  // Stopping must not depend on the file being stopped. Recovery can use a
  // validated lastgood even when current cannot supply a revision or model.
  if(method=='service' && args.action=='stop')m={revision:null};
  else if(method=='rollback') {
   damagedCurrent=lastGood() ?? normalized(read(DATA+'/previous.json',null));
   if(!damagedCurrent)fail('NO_ROLLBACK','没有可恢复的历史配置');
   if(type(args.expectedRevision)!='int' || args.expectedRevision<damagedCurrent.revision || args.expectedRevision>2147483645)fail('REVISION_CONFLICT','损坏配置恢复需要不早于可用副本的有效版本号');
   m=clone(damagedCurrent);m.revision=args.expectedRevision;
  }else die(e.message);
 }
 if(method=='service') {
  if(args.action=='stop') {
   if(!forwarding('stop'))fail('FORWARDING_STOP_FAILED','转发撤销失败，保留核心及启动设置');
   if(!command('/etc/init.d/alwayroute stop') || running())fail('CORE_STOP_FAILED','核心停止失败，启动设置保持不变');
   clearCoreRuntime();
   if(interrupted)restoreMetadata(interrupted,lastGood(),{enabled:false});
   invalidateTraffic();invalidateStatus();write(DATA+'/service.json',{enabled:false});write(TMP+'/state.json',{appliedRevision:null,healthy:'unverified'});system('/bin/sync');event('服务已停止');return {ok:true,state:state(m)};
  }
  if(args.action=='start') {
   return applyModel(m);
  }
  fail('INVALID_ACTION','仅支持 start/stop');
 }
 expected(args,m);
 if(method=='configure') {
  let next=normalize(clone(args.model));
  if(!next)fail('INVALID_MODEL','需要配置模型');
  if(next.revision!=m.revision)fail('REVISION_CONFLICT','模型版本不匹配');
  next.revision=m.revision+1;
  return configureCandidate(next);
 }
 if(method=='save') {
  let next=clone(args.model);validate(next);
  if(next.revision!=m.revision)fail('REVISION_CONFLICT','模型版本不匹配');
  next.revision=m.revision+1;return saved(next);
 }
 if(method=='select') {
  let found=false;for(let g in m.groups)if(g.id==args.group){g.selected=args.nodeId;found=true;}
  if(!found)fail('INVALID_GROUP','策略组不存在');m.revision++;return saved(m);
 }
 if(method=='import') {
  let incoming=parse(args.content,'manual',sha256);
  for(let n in incoming) {n.id='m_'+n.sourceKey;n.source=null;delete n.sourceKey;push(m.nodes,n);}
  m.revision++;let r=args.activate===true?configureCandidate(m):saved(m);r.imported=length(incoming);return r;
 }
 if(method=='refresh')return refresh(args,m);
 if(method=='apply')return applyModel(m);
 if(method=='rollback') {
  let good=lastGood(),target=damagedCurrent ?? ((good && good.revision!=m.revision)?good:normalized(read(DATA+'/previous.json',null)));
  if(!target)fail('NO_ROLLBACK','没有可恢复的历史配置');
  target=clone(target);target.revision=m.revision+1;validate(target);applyModel(target,true,null,damagedCurrent);return result(target);
 }
 fail('UNSUPPORTED','该方法尚未支持');
};
export function call(method,args,inline) {
 init();
 if(method=='job_status')return jobStatus();
 if(method=='cancel_check') {
  try{return cancelCheck(args ?? {});}catch(e){return {ok:false,error:{code:'INVALID_JOB',message:'无法取消：检测任务已结束、已变化或取消标志写入失败'}};}
 }
 if(index(['capabilities','get','status','traffic','logs','export'],method)>=0) {
  try{return execute(method,args ?? {});}catch(e){return {ok:false,error:{code:'READ_FAILED',message:'读取状态失败，请检查持久配置及核心状态'}};}
 }
 let lock=fs.open(TMP+'/manager.lock','ae',0600);
 if(!lock || !lock.lock('xn')) {lock?.close();return {ok:false,error:{code:'BUSY',message:'已有配置事务进行中，请稍后重试'}};}
 let response;
 try {
  let long=index(['refresh','apply','rollback','check','service','configure'],method)>=0 || (method=='import' && args?.activate===true);
  let pending=read(TMP+'/job.json',null);
  if(!inline && pending?.status=='running' && index(['capabilities','get','status','traffic','logs','export'],method)<0)fail('BUSY','后台事务尚未完成');
  if(!inline && long) {
   if(pending?.status=='running')fail('BUSY','后台事务尚未完成');
   if(index(['refresh','import'],method)>=0 && (type(args?.content)!='string' || length(args.content)>131072))fail('INPUT_LIMIT','导入或订阅正文须为字符串且不得超过128KiB');
   if(method=='configure' && type(args?.model)!='object')fail('INVALID_MODEL','需要配置模型对象');
   if(method=='configure' && length(sprintf('%J',args.model))>131072)fail('INPUT_LIMIT','配置模型不得超过128KiB');
   let job={id:trim(fs.readfile('/proc/sys/kernel/random/uuid') ?? sprintf('%d',time())),method,status:'running',started:time()};
   write(TMP+'/job.request.json',{method,args:args ?? {},id:job.id});write(TMP+'/job.json',job);
   if(system('/usr/libexec/alwayroute-job >/dev/null 2>&1 &')!=0) {job.status='failed';job.error={code:'JOB_START_FAILED',message:'后台事务启动失败'};write(TMP+'/job.json',job);fail('JOB_START_FAILED','后台事务启动失败');}
   response={ok:true,job};
  } else response=execute(method,args ?? {});
 } catch(e) {
  // No raw exception, command output, subscription body or credentials cross RPC.
  let message=e.message ?? '', marker=index(message,'ALWAYROUTE:'),known=null;
  if(marker==0){let parts=split(substr(message,11),':'),code=shift(parts);if(match(code,/^[A-Z_]+$/))known={code,message:join(':',parts)};}
  response={ok:false,error:known ?? {code:'INTERNAL_ERROR',message:'操作失败；敏感诊断不写日志'}};
 }
 if(inline && method=='refresh' && type(args?.subscriptionId)=='string' && match(args.subscriptionId,/^[A-Za-z0-9_-]{1,20}$/)) {
  try {
   let previous=read(DATA+'/subscription-status.json',{}),updates={};
   for(let s in model().subscriptions)if(previous[s.id])updates[s.id]=previous[s.id];
   updates[args.subscriptionId]={ok:response.ok,time:time(),code:response.error?.code ?? null};
   write(DATA+'/subscription-status.json',updates);system('/bin/sync');
   if(!response.ok)event('订阅更新失败，旧节点保持可用','error');
  }catch(e){}
 }
 lock.lock('u');lock.close();return response;
};
export function work() {
 init();let lock=fs.open(TMP+'/manager.lock','ae',0600),owned=false;
 if(!lock)return;
 for(let i=0;i<4;i++){if(lock.lock('xn')){owned=true;break;}system('/bin/sleep 1');}
 if(!owned){lock.close();return;}
 let request=null,job=null,claimed=false;
 try {
  request=read(TMP+'/job.request.json',null);job=read(TMP+'/job.json',null);
  if(request && job && request.id==job.id && index(['refresh','apply','rollback','check','service','configure','import'],request.method)>=0) {
   if(job.status!='running')fs.unlink(TMP+'/job.request.json');
   else {job.pid=int(split(fs.readfile('/proc/self/stat') ?? '0',' ')[0]);write(TMP+'/job.json',job);claimed=true;}
  }
 }catch(e){}
 // call() acquires manager.lock itself, so release the claim before execution.
 lock.lock('u');lock.close();
 if(!claimed)return;
 let response;
 if(request.method=='check'){request.args=request.args ?? {};request.args._jobId=job.id;}
 for(let i=0;i<4;i++){response=call(request.method,request.args,true);if(response.error?.code!='BUSY')break;system('/bin/sleep 1');}
 let latest=read(TMP+'/job.json',null);if(latest?.id==job.id)job=latest;
 job.status=response.ok?(response.cancelled?'cancelled':'succeeded'):'failed';job.finished=time();
 if(response.ok) {job.state=response.state ?? state();if(request.method=='check')job.result=response;}
 else job.error=response.error;
 write(TMP+'/job.json',job);fs.unlink(TMP+'/job.request.json');fs.unlink(TMP+'/subscription.body');
 if(request.method=='check')fs.unlink(TMP+'/check-cancel-'+job.id);
};
export function boot() {
 init();invalidateTraffic();invalidateStatus();let config=read(DATA+'/service.json',{enabled:false}),good=lastGood();
 let pending=read(DATA+'/applying.json',null);
 if(pending) {
  config=pending.previousService ?? config;
  good=pendingGood(pending);
 }
 if(!config.enabled || !good) {if(pending)restoreMetadata(pending,good,config);return false;}
 installCoreModel(good);write(TMP+'/state.json',{appliedRevision:null,restoringRevision:good.revision,healthy:'unverified'});
 if(!forwarding('guard')){clearCoreRuntime();fail('FORWARDING_GUARD_FAILED','启动时无法建立故障阻断');}
 // Persistent recovery may fail on a full or read-only overlay. Establish the
 // guard first, so refusing this start cannot expose unprotected base routing.
 if(pending)restoreMetadata(pending,good,config);
 return true;
};
export function due() {
 let m=model(),now=time(),responses=[];
 for(let s in m.subscriptions)if(s.enabled && s.intervalHours>0 && now-(s.lastUpdate ?? 0)>=s.intervalHours*3600) {
  let r=call('refresh',{expectedRevision:m.revision,subscriptionId:s.id,content:''},true);push(responses,{id:s.id,ok:r.ok});if(r.ok)m=r.model;
 }
 return responses;
};
export function started() {
 init();invalidateStatus();let restoring=read(TMP+'/state.json',{}),epoch=read(TMP+'/status-epoch.json',null)?.id;
 if(restoring.restoringRevision==null)return true;
 let lock=fs.open(TMP+'/manager.lock','ae',0600);
 if(!lock)return false;
 // This detached confirmer is the only boot activation attempt. A queued
 // subscription or the largest bounded node check may already own the lock.
 let owned=false;
 for(let i=0;i<600;i++){
  if(lock.lock('xn')){owned=true;break;}
  if(read(TMP+'/state.json',{})?.restoringRevision==null || read(TMP+'/status-epoch.json',null)?.id!==epoch){lock.close();return false;}
  if(i<599)system('/bin/sleep 1');
 }
 if(!owned) {
  lock.close();
  // Never overwrite state.json without its owner lock. Readers accept this
  // separate error only while the same boot recovery and epoch remain pending.
  try {if(epoch!=null)write(TMP+'/restore-timeout.json',{epoch,revision:restoring.restoringRevision,message:'启动恢复等待配置事务超时，故障阻断保持；请重试启动'});}catch(e){}
  return false;
 }
 try {
  let runtime=read(TMP+'/state.json',{});
  if(runtime.restoringRevision!=null) {
   let pending=read(DATA+'/applying.json',null),good=pending?pendingGood(pending):normalized(read(DATA+'/lastgood.json',null));
   if(good?.revision==runtime.restoringRevision) {
    if(waitCore(good,null) && forwarding('activate'))write(TMP+'/state.json',{appliedRevision:good.revision,healthy:'unverified'});
    else {forwarding('guard');write(TMP+'/state.json',{appliedRevision:null,healthy:'unverified',lastError:'启动恢复未通过核心/转发检查，已请求故障阻断'});}
   }
  }
 }catch(e){forwarding('guard');}
 lock.lock('u');lock.close();
};
// Called by the procd command wrapper immediately before every process spawn,
// including automatic respawns. Only the internal runtime secret changes.
export function prepareCoreStart() {
 init();return withCoreLock(function() {
  let config=read(TMP+'/runtime.json',null);
  if(type(config)!='object' || config?.experimental?.clash_api?.external_controller!='127.0.0.1:9090')fail('CORE_CREDENTIAL_FAILED','核心运行配置不可用');
  installCoreSecretUnlocked(config);return true;
 });
};
