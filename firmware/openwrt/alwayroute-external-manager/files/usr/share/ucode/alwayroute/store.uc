'use strict';
import * as fs from 'fs';
import { executeExternal } from 'alwayroute.external';
import { runManagerWorker } from 'alwayroute.job-worker';

const JOB_TMP='/tmp/alwayroute';
const EXTERNAL_ACTIONS=['external_apply','external_disable','external_reconcile','external_shutdown'];
function jobFail(code,message) {die('ALWAYROUTE:'+code+':'+message);}
function jobPrivate(path,kind,mode) {let info=fs.lstat(path);return info?.type==kind && info.uid==0 && info.mode==mode;}
function jobInit() {
 for(let path in ['/etc/alwayroute',JOB_TMP]) {
  if(!fs.lstat(path) && !fs.mkdir(path,0700))jobFail('STORAGE_ERROR','无法创建外接私有目录');
  if(!jobPrivate(path,'directory',0700))jobFail('STORAGE_ERROR','外接目录不是root私有真实目录');
 }
}
function jobPath(path) {
 if(index([JOB_TMP+'/job.json',JOB_TMP+'/job.request.json'],path)<0)jobFail('STORAGE_ERROR','外接任务存储路径无效');
}
function jobRead(path,fallback) {
 jobPath(path);let info=fs.lstat(path);if(!info)return fallback;
 if(!jobPrivate(path,'file',0600) || info.size>32768)jobFail('STORAGE_CORRUPT','外接任务文件不安全或超过限制');
 let raw=fs.readfile(path);if(raw==null)jobFail('STORAGE_ERROR','无法读取外接任务');
 try{return json(raw);}catch(e){jobFail('STORAGE_CORRUPT','外接任务记录损坏');}
}
function jobWrite(path,value) {
 jobPath(path);
 for(let candidate in [path,path+'.new'])if(fs.lstat(candidate) && !jobPrivate(candidate,'file',0600))jobFail('STORAGE_ERROR','外接任务文件归属不安全');
 let data=sprintf('%J',value),file=fs.open(path+'.new','w',0600);if(!file)jobFail('STORAGE_ERROR','无法创建外接任务');
 let n=file.write(data),flushed=file.flush(),closed=file.close();
 if(n!=length(data) || !flushed || !closed || !fs.rename(path+'.new',path))jobFail('STORAGE_ERROR','外接任务原子保存失败');
}
function jobLock() {
 let path=JOB_TMP+'/manager.lock';
 if(fs.lstat(path) && !jobPrivate(path,'file',0600))jobFail('STORAGE_ERROR','外接任务锁归属不安全');
 return fs.open(path,'ae',0600);
}
function safeError(error) {
 let message=error.message ?? '';
 if(index(message,'ALWAYROUTE:')==0) {
  let parts=split(substr(message,11),':'),code=shift(parts);
  if(match(code,/^[A-Z_]+$/))return {code,message:join(':',parts)};
 }
 return {code:'INTERNAL_ERROR',message:'外接操作失败；敏感诊断不写日志'};
}
function externalJobStatus() {
 let job=jobRead(JOB_TMP+'/job.json',null);
 if(job?.status=='running' && (job.pid?!fs.access('/proc/'+job.pid):time()-job.started>10)) {
  let lock=jobLock();
  if(lock && lock.lock('xn')) {
   try {
    job=jobRead(JOB_TMP+'/job.json',null);
    if(job?.status=='running' && (job.pid?!fs.access('/proc/'+job.pid):time()-job.started>10)) {
     job.status='failed';job.error={code:'JOB_INTERRUPTED',message:'后台外接事务中断；请检查状态并恢复或独立关闭'};
     jobWrite(JOB_TMP+'/job.json',job);
    }
   }catch(e){lock.close();die(e.message);}
   lock.lock('u');lock.close();
  }else lock?.close();
 }
 return {ok:true,busy:job?.status=='running',job};
}
export function call(method,args,inline) {
 let lock=null,response;
 try {
  jobInit();args=args ?? {};
  if(method=='capabilities')return {ok:true,schema:1,backend:'external',externalOnly:true,protocols:[],subscriptionFormats:[],logs:false,externalProxy:{schema:1,family:'ipv4',clientModes:['selected','lan'],selectedMaxClients:1,faultPolicy:'block',gatewayObservation:'udp-dns',peerObservation:'operator',endToEnd:'unverified'}};
  if(method=='job_status')return externalJobStatus();
  if(index(['external_get','external_status'],method)>=0)return executeExternal(method,args,true);
  if(method!='external_save' && index(EXTERNAL_ACTIONS,method)<0)jobFail('UNSUPPORTED','纯外接包只支持外部配置、状态、应用与关闭');
  lock=jobLock();
  if(!lock || !lock.lock('xn')) {lock?.close();return {ok:false,error:{code:'BUSY',message:'已有外接事务进行中，请稍后重试'}};}
  if(method=='external_apply') {
   let peer=args.peer ?? {};
   if(type(peer)!='object' || length(sprintf('%J',peer))>2048)jobFail('INPUT_LIMIT','对端观察须为不超过2KiB的对象');
   args={expectedRevision:args.expectedRevision,peer};
  }else if(method=='external_save') {
   if(type(args.config)!='object' || length(sprintf('%J',args.config))>8192)jobFail('INPUT_LIMIT','外部配置须为不超过8KiB的对象');
   args={expectedRevision:args.expectedRevision,config:args.config};
  }else args={};
  let pending=jobRead(JOB_TMP+'/job.json',null);
  if(!inline && pending?.status=='running')jobFail('BUSY','后台外接事务尚未完成');
  if(!inline && index(EXTERNAL_ACTIONS,method)>=0) {
   let job={id:trim(fs.readfile('/proc/sys/kernel/random/uuid') ?? sprintf('%d',time())),method,status:'running',started:time()};
   jobWrite(JOB_TMP+'/job.request.json',{method,args,id:job.id});jobWrite(JOB_TMP+'/job.json',job);
   if(system('/usr/libexec/alwayroute-job >/dev/null 2>&1 &')!=0) {
    job.status='failed';job.error={code:'JOB_START_FAILED',message:'后台外接任务启动失败'};jobWrite(JOB_TMP+'/job.json',job);jobFail('JOB_START_FAILED','后台外接任务启动失败');
   }
   response={ok:true,job};
  }else response=executeExternal(method,args,true);
 }catch(e){response={ok:false,error:safeError(e)};}
 lock?.lock('u');lock?.close();return response;
};
export function work() {
 // The shared worker remains the same process/lock/job protocol as local mode.
 // Validate its paths before handing over its mechanically extracted body.
 jobInit();let lock=jobLock();lock?.close();
 return runManagerWorker({init:jobInit,read:jobRead,write:jobWrite,call,state:function(){return executeExternal('external_status',{},true).state;},methods:EXTERNAL_ACTIONS});
};
