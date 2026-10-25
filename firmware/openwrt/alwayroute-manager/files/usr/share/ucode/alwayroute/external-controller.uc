'use strict';
import { emptyExternal, validateExternal, validateExternalPeer } from 'alwayroute.external-model';

function externalError(code,message) {die('ALWAYROUTE:'+code+':'+message);}
// All callers serialize with manager.lock. I/O and networking are explicit
// dependencies so interruption/failure checks exercise this production engine.
export function externalController(io) {
 function readConfig() {return validateExternal(io.read('config') ?? emptyExternal());}
 function intent() {
  let value=io.read('intent');
  if(value==null)return {enabled:false,revision:null};
  if(type(value)!='object' || type(value.enabled)!='bool' || value.revision!=null && (type(value.revision)!='int' || value.revision<0))externalError('STORAGE_CORRUPT','外部启用意图损坏，请显式关闭');
  return value;
 }
 function journal() {
  let value=io.read('journal');if(value==null)return null;
  if(value.schema!==1 || index(['applying','committed'],value.phase)<0)externalError('STORAGE_CORRUPT','外部事务记录损坏，请显式关闭');
  validateExternal(value.target);if(value.previous!=null)validateExternal(value.previous);
  return value;
 }
 function checked(expected,config) {if(type(expected)!='int' || expected!==config.revision)externalError('REVISION_CONFLICT','外部配置已变化，请重新读取');}
 function state(inspection) {
  let config=readConfig(),desired=intent(),runtime=io.read('state') ?? {},pending=journal(),peer=runtime.peer ?? null;
  let fresh=peer!=null && type(peer.observedAt)=='int' && peer.observedAt<=io.now() && io.now()-peer.observedAt<=30;
  let phase=pending?'recovering':(runtime.phase ?? (desired.enabled?'unknown':'disabled'));
  let method=runtime.applicationMethod ?? (peer?'operator':'unknown'),gatewayDns=runtime.gatewayDns ?? null;
  if(inspection && phase=='active' && desired.enabled && method=='gateway-dns' && !pending) {
   // Observe the applied target, never a newly saved draft. The adapter caches
   // this separately from transaction state, since status readers do not lock.
   gatewayDns=io.gatewayDns(validateExternal(io.read('good')),false);
  }
  let dnsFresh=gatewayDns!=null && type(gatewayDns.observedAt)=='int' && gatewayDns.observedAt<=io.now() && io.now()-gatewayDns.observedAt<60;
  if(phase=='active' && (method=='operator' && !fresh || method=='gateway-dns' && (!dnsFresh || gatewayDns.reachable!==true)))phase='degraded';
  if(inspection && phase=='active' && desired.enabled && (inspection.network?.running!==true || inspection.dns?.running!==true))phase='degraded';
  return {clientScope:runtime.clientScope ?? null,savedRevision:config.revision,desiredEnabled:desired.enabled,desiredRevision:desired.revision,appliedRevision:pending?null:(runtime.appliedRevision ?? null),phase,applicationMethod:method,localForwarding:inspection?.network ?? {status:'unknown'},dns:inspection?.dns ?? {status:'unknown'},gatewayDns:{method:'udp-query',status:dnsFresh && gatewayDns.reachable!=null?(gatewayDns.reachable===true?'reachable':'unreachable'):'unknown',observedAt:gatewayDns?.observedAt ?? null,ageSeconds:gatewayDns?.observedAt!=null && gatewayDns.observedAt<=io.now()?io.now()-gatewayDns.observedAt:null,cacheSeconds:60},peer:peer?{method:'operator',generation:peer.generation,observedAt:peer.observedAt,status:fresh?'reported':'unknown'}:{status:'unknown'},lastError:runtime.lastError ?? null,observedAt:inspection?io.now():null,endToEnd:'unverified',baseConnectivity:'unverified'};
 }
 function get() {return {ok:true,config:readConfig(),state:state()};}
 function status() {return {ok:true,state:state(io.inspect())};}
 function save(args) {
  if(journal())externalError('RECOVERY_REQUIRED','存在未完成外部事务，请先恢复或关闭');
  let current=readConfig();checked(args.expectedRevision,current);
  let next=validateExternal(args.config);
  if(next.revision!==current.revision || next.revision>=2147483645)externalError('REVISION_CONFLICT','外部候选版本不匹配或已达上限');
  next.revision++;io.write('config',next);io.sync();return get();
 }
 function remember(phase,config,peer,error,gatewayDns) {
  io.write('state',{phase,clientScope:{mode:config.clientMode ?? 'selected',ipv4:config.clientCIDR ?? config.clients[0]?.address ?? null},appliedRevision:phase=='active'?config.revision:null,applicationMethod:gatewayDns?'gateway-dns':peer?'operator':'unknown',gatewayDns:gatewayDns ?? null,peer:peer ?? null,lastError:error ?? null});
 }
 function removeJournal() {io.remove('journal');io.sync();}
 function disable() {
  // Deliberately never read the config, lastgood, journal or legacy node model.
  // Persist the stop intent first, so a reboot cannot re-enable a failed close.
  let durable=true;
  try{io.write('mode',{schema:1,backend:'external'});io.write('intent',{enabled:false,revision:null});io.sync();}catch(e){durable=false;}
  try {
   io.stop();
   let actual=io.inspect();
   if(actual.network?.running!==false || actual.network?.guarded!==false || actual.network?.residual!==false || actual.dns?.running!==false || actual.localCore!==false)externalError('EXTERNAL_STOP_FAILED','外部资源或本机核心仍未确认停止');
   if(!durable)externalError('STORAGE_ERROR','关闭已尝试，但停止意图尚未持久保存');
   io.write('state',{phase:'disabled',appliedRevision:null,peer:null,lastError:null});
   io.remove('journal');io.remove('good');io.clearRuntime();io.sync();
   return {ok:true,state:{savedRevision:null,desiredEnabled:false,desiredRevision:null,appliedRevision:null,phase:'disabled',localForwarding:actual.network,dns:actual.dns,peer:{status:'unknown'},lastError:null,observedAt:io.now(),endToEnd:'unverified',baseConnectivity:'unverified'}};
  }catch(e) {
   try{io.write('state',{phase:'fault',appliedRevision:null,peer:null,lastError:'EXTERNAL_STOP_FAILED'});io.sync();}catch(ignored){}
   externalError('EXTERNAL_STOP_FAILED','关闭未完成，请检查残留并重试；未报告直连成功');
  }
 }
 function restore(previous) {
  if(previous?.enabled) {
   // No old peer observation is re-used after a failed or interrupted apply.
   io.guard(previous);io.stopDns();
   io.write('intent',{enabled:true,revision:previous.revision});
   io.write('good',previous);remember('guarded',previous,null,'RECONFIRM_REQUIRED');
  }else {
   io.stop();io.clearRuntime();io.write('intent',{enabled:false,revision:null});
   io.remove('good');io.write('state',{phase:'disabled',appliedRevision:null,peer:null,lastError:null});
  }
  io.sync();
 }
 function apply(args) {
  if(journal())externalError('RECOVERY_REQUIRED','存在未完成外部事务，请先恢复或关闭');
  let config=readConfig();checked(args.expectedRevision,config);
  if(!config.enabled)return disable();
  // rpcd supplies {} for an omitted object argument. Only an actually supplied
  // nonempty observation selects the compatibility operator path.
  let automated=args.peer==null || type(args.peer)=='object' && length(keys(args.peer))==0;
  let peer=automated?null:validateExternalPeer(args.peer,config,io.now()),gatewayDns=null;
  let previous=io.read('good');if(previous!=null)previous=validateExternal(previous);
  if(io.read('state')?.lastError=='EXTERNAL_STOP_FAILED')externalError('RECOVERY_REQUIRED','上次关闭未完成，请先重试关闭');
  function scope(c) {return sprintf('%J',[c.link.interface,c.link.routerAddress,c.link.gatewayAddress,c.link.gatewayMac,c.clientMode ?? 'selected',c.clientCIDR ?? null,c.clients,c.dns.listenPort]);}
  if(previous?.enabled && scope(previous)!=scope(config))externalError('SCOPE_CHANGE_REQUIRES_DISABLE','变更链路或来源范围前须先显式关闭旧接管范围');
  if(io.localCore())externalError('LOCAL_CORE_ACTIVE','请先显式停止本机代理，再启用外部代理');
  if(automated) {
   gatewayDns=io.gatewayDns(config,true);
   if(gatewayDns?.reachable!==true)externalError('EXTERNAL_PREFLIGHT_FAILED','网关DNS有界查询失败，原状态保持；未证明核心或端到端路径');
  }
  // Preflight can prepare private files but cannot commit network state.
  try{io.prepare(config);}catch(e){if(previous?.enabled)io.runtime(previous);else io.clearRuntime();externalError('EXTERNAL_PREFLIGHT_FAILED','外部网络或专用DNS预检失败，原状态保持');}
  let pending={schema:1,phase:'applying',target:config,previous};
  io.write('mode',{schema:1,backend:'external'});io.write('journal',pending);io.sync();
  try {
   io.write('intent',{enabled:true,revision:config.revision});io.sync();
   io.guard(config);io.startDns(config);io.activate(config);
   // A slow activation may outlive its observation. Never commit stale proof.
   if(!automated)peer=validateExternalPeer(args.peer,config,io.now());
   let actual=io.inspect();
   if(actual.network?.running!==true || actual.network?.guarded!==false || actual.dns?.running!==true || actual.localCore!==false)externalError('EXTERNAL_CONFIRM_FAILED','外部本地应用未确认');
  }catch(e) {
   try{restore(previous);removeJournal();}catch(ignored) {
    try{io.guard(previous?.enabled?previous:config);}catch(guardError){}
    try{remember('fault',config,null,'EXTERNAL_RECOVERY_FAILED');io.sync();}catch(writeError){}
    externalError('EXTERNAL_RECOVERY_FAILED','外部应用与恢复未完成，保留故障防护及事务记录');
   }
   externalError('EXTERNAL_APPLY_FAILED','外部应用失败，已恢复原关闭状态或原来源阻断；请重新核验后应用');
  }
  // After the atomic committed marker is written, even a sync/metadata error
  // must retain it for recovery rather than rolling a committed target back.
  pending.phase='committed';pending.peer=peer;
  io.write('journal',pending);io.sync(); // unique durable commit point
  // Once committed, metadata cleanup errors must not roll the target back.
  io.write('good',config);remember('active',config,peer,null,gatewayDns);io.sync();removeJournal();
  return status();
 }
 function reconcile(args) {
  let desired=intent();
  // An explicit close always wins, including over a corrupt or committed journal.
  if(!desired.enabled)return disable();
  let pending=journal(),config;
  if(pending) {
   config=pending.phase=='committed'?pending.target:pending.previous;
   if(!config?.enabled)return disable();
  }else config=validateExternal(io.read('good'));
  try {
   io.guard(config);io.stopDns();
   io.write('intent',{enabled:true,revision:config.revision});io.write('good',config);
   remember('guarded',config,null,'RECONFIRM_REQUIRED');io.sync();removeJournal();
  }catch(e) {
   try{remember('fault',config,null,'EXTERNAL_RECOVERY_FAILED');io.sync();}catch(ignored){}
   externalError('EXTERNAL_RECOVERY_FAILED','外部启动或事件恢复未完成，请检查防护和残留');
  }
  return args?.quiet?{ok:true,recovery:{status:'guarded',revision:config.revision}}:status();
 }
 function shutdown() {
  if(!intent().enabled)return disable();
  // Keep the confirmed source guard through base network shutdown. stop()
  // would remove protection while normal forwarding can still be running.
  return reconcile({quiet:true});
 }
 return {get,status,save,apply,disable,reconcile,shutdown};
};
