'use strict';
import * as fs from 'fs';
import { sha256 } from 'digest';
import { fail, clone, empty, validate, effective, generate } from 'alwayroute.model';
import { parse } from 'alwayroute.subscription';

const DATA='/etc/alwayroute', TMP='/tmp/alwayroute';
function init() {if(!fs.access(DATA))fs.mkdir(DATA,0700);if(!fs.access(TMP))fs.mkdir(TMP,0700);}
function read(path, fallback) {let s=fs.readfile(path);if(s==null)return fallback;try{return json(s);}catch(e){fail('STORAGE_CORRUPT','持久配置损坏，拒绝覆盖；请使用恢复功能');}}
function write(path,value) {
 let data=sprintf('%J',value), f=fs.open(path+'.new','w',0600);
 if(!f)fail('STORAGE_ERROR','无法创建配置候选');
 fs.chmod(path+'.new',0600);
 let n=f.write(data),flushed=f.flush(),closed=f.close();
 if(n!=length(data) || !flushed || !closed || !fs.rename(path+'.new',path))fail('STORAGE_ERROR','配置原子保存失败');
};
function model() {return validate(read(DATA+'/current.json',empty()));}
function state() {let m=model(),runtime=read(TMP+'/state.json',{});return {savedRevision:m.revision,appliedRevision:runtime.appliedRevision ?? null,healthy:runtime.healthy ?? 'unverified',lastError:runtime.lastError ?? null};}
function jobStatus() {
 let job=read(TMP+'/job.json',null);
 if(job?.status=='running' && ((time()-job.started>120) || (time()-job.started>10 && (!job.pid || !fs.access('/proc/'+job.pid))))) {
  job.status='failed';job.error={code:'JOB_INTERRUPTED',message:'后台事务中断；请检查状态，启动服务会从上一份可用配置恢复'};write(TMP+'/job.json',job);
 }
 return {ok:true,busy:job?.status=='running',job};
};
function event(message,level) {let entries=read(TMP+'/events.json',[]);push(entries,{time:time(),level:level ?? 'info',message});while(length(entries)>20)shift(entries);write(TMP+'/events.json',entries);}
function result() {
 let m=model(),updates=read(DATA+'/subscription-status.json',{});
 for(let s in m.subscriptions)if(updates[s.id])s.lastError=updates[s.id].ok?null:'订阅更新失败：'+updates[s.id].code;
 return {ok:true,model:m,state:state()};
};
function expected(args,m) {if(type(args.expectedRevision)!='int' || args.expectedRevision!=m.revision)fail('REVISION_CONFLICT','配置已由其他操作更新，请重新加载');}
function saved(m) {validate(m);write(DATA+'/current.json',m);system('/bin/sync');event('配置已保存');return result();}
function command(cmd) {return system(cmd+' >/dev/null 2>&1')==0;}
function running() {return command('/etc/init.d/alwayroute running');}
function fetchJson(path, stream) {
 let command='/usr/libexec/alwayroute-timeout 3 /bin/uclient-fetch -q -T 2 -O - '+"'http://127.0.0.1:9090"+path+"' 2>/dev/null";
 if(stream)command+=' | /bin/busybox head -n 1';
 let p=fs.popen(command,'r');if(!p)return null;
 let s=p.read(65536);p.close();if(!s)return null;
 try{return json(trim(s));}catch(e){return null;}
};
function forwarding(action) {
 if(!fs.access('/usr/libexec/alwayroute-forwarding','x'))return action=='status'?{available:false,scope:'unverified'}:false;
 if(action=='status') {let p=fs.popen('/usr/libexec/alwayroute-forwarding status 2>/dev/null','r');if(!p)return {available:false,scope:'unverified'};let s=p.read(8192);p.close();try{return json(s);}catch(e){return {available:false,scope:'unverified'};}}
 return command('/usr/libexec/alwayroute-forwarding '+action);
};
function coreStatus() {let p=fetchJson('/proxies');return p?.proxies?{available:true,groups:p.proxies}:{available:false,groups:{}};}
function restart(m) {
 if(m.mode!='direct')for(let g in m.groups)if(g.id=='Proxy' && g.selected=='direct')fail('UNCONFIGURED','请先为 Proxy 选择已启用代理节点');
 write(TMP+'/runtime.json',generate(m));
 if(!command('/usr/bin/sing-box check -c /tmp/alwayroute/runtime.json'))fail('CORE_CHECK_FAILED','核心拒绝配置，原应用保持可恢复');
 if(!forwarding('prepare'))fail('FORWARDING_CHECK_FAILED','转发预检失败');
 if(!forwarding('guard'))fail('FORWARDING_GUARD_FAILED','无法建立故障阻断，保留当前核心');
 write(TMP+'/state.json',{appliedRevision:null,healthy:'unverified'});
 write(TMP+'/restarting.json',{guarded:true});
 let restarted=command('/etc/init.d/alwayroute restart');fs.unlink(TMP+'/restarting.json');
 if(!restarted)fail('CORE_START_FAILED','核心启动失败或转发状态转换失败');
 let observed=null;
 for(let i=0;i<4;i++){observed=coreStatus();if(observed.available)break;system('/bin/sleep 1');}
 if(!observed?.available)fail('CORE_LOAD_FAILED','核心 API 未确认配置加载');
 for(let g in m.groups)if(observed.groups[g.id]?.now!=g.selected)fail('CORE_LOAD_FAILED','实际策略选择与候选不一致');
 if(!forwarding('activate'))fail('FORWARDING_APPLY_FAILED','转发应用失败');
};
function recover(good,wasRunning) {
 if(good && wasRunning) {try{restart(good);return {restored:true,guarded:false};}catch(e){}}
 return {restored:false,guarded:forwarding('guard')};
};
function applyModel(m) {
 let good=read(DATA+'/lastgood.json',null),wasRunning=running(),service=read(DATA+'/service.json',{enabled:false});
 // The candidate is only in tmp; current and lastgood remain valid across power loss.
 try {
  if(good)write(DATA+'/previous.json',good);
  write(DATA+'/applying.json',{previousRevision:good?.revision ?? null});system('/bin/sync');
  restart(m);
  write(DATA+'/lastgood.json',m);write(DATA+'/service.json',{enabled:true});
  write(TMP+'/state.json',{appliedRevision:m.revision,healthy:'unverified'});
  if(!fs.unlink(DATA+'/applying.json'))fail('STORAGE_ERROR','应用提交标志无法清除');system('/bin/sync');
 }catch(e) {
  let recovery=recover(good,wasRunning);
  // Recovery runs even if flash is full or read-only. An uncleared marker makes
  // the next boot rebuild previous.json instead of a half-committed candidate.
  try {if(good)write(DATA+'/lastgood.json',good);else fs.unlink(DATA+'/lastgood.json');write(DATA+'/service.json',service);fs.unlink(DATA+'/applying.json');system('/bin/sync');}catch(storageError){}
  let message=recovery.restored?'应用失败，已恢复上一份可用配置':recovery.guarded?'应用及恢复失败，已进入故障阻断':'应用及恢复失败，故障阻断未确认；保留核心并需人工处理';
  try {write(TMP+'/state.json',{appliedRevision:recovery.restored?good.revision:null,healthy:'unverified',lastError:message});event(message,'error');}catch(stateError){}
  die(e.message);
 }
 event('核心加载已确认；出口与终端接管仍须实测');
 return {ok:true,state:state()};
};
function refresh(args,m) {
 let s=null;for(let candidate in m.subscriptions)if(candidate.id==args.subscriptionId)s=candidate;
 if(!s || !s.enabled)fail('INVALID_SUBSCRIPTION','订阅不存在或已停用');
 let content=args.content;
 if(!content) {
  // URL is staged in a root-only file; downloader diagnostics are suppressed.
  write(TMP+'/fetch.json',{url:s.url});
  if(!command('/usr/libexec/alwayroute-fetch'))fail('FETCH_FAILED','HTTPS 订阅获取失败，原节点保持不变');
  content=fs.readfile(TMP+'/subscription.body',131073);
 }
 let incoming=parse(content,s.id,sha256), next=clone(m);
 next.nodes=filter(next.nodes,n=>n.source!=s.id);for(let n in incoming)push(next.nodes,n);next.revision++;
 for(let item in next.subscriptions)if(item.id==s.id){item.lastUpdate=time();delete item.lastError;}
 // validate rejects removal of selected or rule-referenced node. No silent fallback.
 validate(next);let response=saved(next);response.imported=length(incoming);return response;
};
function redact(m) {m=clone(m);for(let n in m.nodes)n.uuid='[redacted]';for(let s in m.subscriptions)s.url='https://redacted.invalid/';for(let k,o in m.overrides)if(o.patch?.uuid)o.patch.uuid='[redacted]';return m;}
function execute(method,args) {
 if(method=='capabilities')return {ok:true,schema:1,protocols:['vmess'],subscriptionFormats:['vmess-uri','base64-vmess-list','clash-json','clash-yaml-block-subset'],limits:{nodes:128,rules:128,subscriptions:16,inputBytes:131072},forwarding:'unverified',nodeCheck:true,logs:true};
 if(method=='get')return result();
 if(method=='job_status')return jobStatus();
 if(method=='status')return {ok:true,state:state(),service:{running:running()},core:coreStatus(),forwarding:forwarding('status'),checks:read(TMP+'/checks.json',{})};
 if(method=='traffic') {let t=fetchJson('/traffic',true);return {ok:true,available:type(t?.up)=='int' && type(t?.down)=='int',upload:t?.up ?? null,download:t?.down ?? null,unit:'bytes/s',reason:t?null:'核心流量流不可用'};}
 if(method=='logs') {let entries=read(TMP+'/events.json',[]),limit=int(args.limit ?? 20);if(limit<1 || limit>20)limit=20;return {ok:true,entries:slice(entries,-limit)};}
 if(method=='export')return {ok:true,model:args.includeSecrets?model():redact(model()),redacted:!args.includeSecrets};
 let m=model();
 if(method=='check') {
  let n=null;for(let item in effective(m))if(item.id==args.nodeId)n=item;
  if(!n)fail('INVALID_NODE','节点不存在或已停用');
  let r=fetchJson('/proxies/'+n.id+'/delay?timeout=2000&url=https%3A%2F%2Fwww.gstatic.com%2Fgenerate_204');
  let healthy=r==null?'unverified':type(r?.delay)=='int'?'passed':'failed';
  let outcome={ok:true,nodeId:n.id,available:r!=null,delay:r?.delay ?? null,healthy,checkedRevision:state().appliedRevision,time:time()},checks=read(TMP+'/checks.json',{});
  checks[n.id]=outcome;for(let key in keys(checks))if(!length(filter(m.nodes,item=>item.id==key)))delete checks[key];write(TMP+'/checks.json',checks);
  return outcome;
 }
 if(method=='service') {
  if(args.action=='stop') {
   if(!forwarding('stop'))fail('FORWARDING_STOP_FAILED','转发撤销失败，保留核心及启动设置');
   if(!command('/etc/init.d/alwayroute stop') || running())fail('CORE_STOP_FAILED','核心停止失败，启动设置保持不变');
   write(DATA+'/service.json',{enabled:false});system('/bin/sync');event('服务已停止');return {ok:true,state:state()};
  }
  if(args.action=='start') {
   let good=read(DATA+'/lastgood.json',null);if(!good)fail('NOT_APPLIED','尚无可启动的已应用配置');
   try{restart(good);}catch(e){forwarding('guard');die(e.message);}
   write(TMP+'/state.json',{appliedRevision:good.revision,healthy:'unverified'});write(DATA+'/service.json',{enabled:true});system('/bin/sync');return {ok:true,state:state()};
  }
  fail('INVALID_ACTION','仅支持 start/stop');
 }
 expected(args,m);
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
  m.revision++;let r=saved(m);r.imported=length(incoming);return r;
 }
 if(method=='refresh')return refresh(args,m);
 if(method=='apply')return applyModel(m);
 if(method=='rollback') {
  let good=read(DATA+'/lastgood.json',null),previous=read(DATA+'/previous.json',null);
  let target=(good && good.revision!=m.revision)?good:previous;
  if(!target)fail('NO_ROLLBACK','没有可恢复的历史配置');
  target=clone(target);target.revision=m.revision+1;validate(target);applyModel(target);write(DATA+'/current.json',target);system('/bin/sync');return result();
 }
 fail('UNSUPPORTED','该方法尚未支持');
};
export function call(method,args,inline) {
 init();
 if(method=='job_status')return jobStatus();
 if(index(['capabilities','get','status','traffic','logs','export'],method)>=0) {
  try{return execute(method,args ?? {});}catch(e){return {ok:false,error:{code:'READ_FAILED',message:'读取状态失败，请检查持久配置及核心状态'}};}
 }
 let lock=fs.open(TMP+'/manager.lock','ae',0600);
 if(!lock || !lock.lock('xn')) {lock?.close();return {ok:false,error:{code:'BUSY',message:'已有配置事务进行中，请稍后重试'}};}
 let response;
 try {
  let long=index(['refresh','apply','rollback','check','service'],method)>=0;
  let pending=read(TMP+'/job.json',null);
  if(!inline && pending?.status=='running' && index(['capabilities','get','status','traffic','logs','export'],method)<0)fail('BUSY','后台事务尚未完成');
  if(!inline && long) {
   if(pending?.status=='running')fail('BUSY','后台事务尚未完成');
   if(method=='refresh' && (type(args?.content)!='string' || length(args.content)>131072))fail('INPUT_LIMIT','订阅正文不得超过128KiB');
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
 init();let request=read(TMP+'/job.request.json',null),job=read(TMP+'/job.json',null);
 if(!request || !job || request.id!=job.id || index(['refresh','apply','rollback','check','service'],request.method)<0)return;
 job.pid=int(split(fs.readfile('/proc/self/stat') ?? '0',' ')[0]);write(TMP+'/job.json',job);
 let response;
 for(let i=0;i<4;i++){response=call(request.method,request.args,true);if(response.error?.code!='BUSY')break;system('/bin/sleep 1');}
 job.status=response.ok?'succeeded':'failed';job.finished=time();
 if(response.ok) {job.state=response.state ?? state();if(request.method=='check')job.result=response;}
 else job.error=response.error;
 write(TMP+'/job.json',job);fs.unlink(TMP+'/job.request.json');fs.unlink(TMP+'/subscription.body');
};
export function boot() {
 init();let config=read(DATA+'/service.json',{enabled:false}),good=read(DATA+'/lastgood.json',null);
 let pending=read(DATA+'/applying.json',null);
 if(pending) {
  good=pending.previousRevision==null?null:read(DATA+'/previous.json',null);
  if(good?.revision!=pending.previousRevision)good=null;
 }
 if(!config.enabled || !good)return false;
 write(TMP+'/runtime.json',generate(good));write(TMP+'/state.json',{appliedRevision:null,restoringRevision:good.revision,healthy:'unverified'});
 if(!forwarding('guard'))fail('FORWARDING_GUARD_FAILED','启动时无法建立故障阻断');return true;
};
export function due() {
 let m=model(),now=time(),responses=[];
 for(let s in m.subscriptions)if(s.enabled && s.intervalHours>0 && now-(s.lastUpdate ?? 0)>=s.intervalHours*3600) {
  let r=call('refresh',{expectedRevision:m.revision,subscriptionId:s.id,content:''},true);push(responses,{id:s.id,ok:r.ok});if(r.ok)m=r.model;
 }
 return responses;
};
export function started() {
 init();let lock=fs.open(TMP+'/manager.lock','ae',0600);
 if(!lock || !lock.lock('xn')){lock?.close();return;}
 try {
  let runtime=read(TMP+'/state.json',{});
  if(runtime.restoringRevision!=null) {
   let pending=read(DATA+'/applying.json',null),good=read(DATA+(pending?'/previous.json':'/lastgood.json'),null),core=null;
   if(good?.revision==runtime.restoringRevision) {
    for(let i=0;i<4;i++){core=coreStatus();if(core.available)break;system('/bin/sleep 1');}
    let matches=running() && core?.available;
    for(let g in good.groups)if(core?.groups?.[g.id]?.now!=g.selected)matches=false;
    if(matches && forwarding('activate'))write(TMP+'/state.json',{appliedRevision:good.revision,healthy:'unverified'});
    else {forwarding('guard');write(TMP+'/state.json',{appliedRevision:null,healthy:'unverified',lastError:'启动恢复未通过核心/转发检查，已请求故障阻断'});}
   }
  }
 }catch(e){forwarding('guard');}
 lock.lock('u');lock.close();
};
