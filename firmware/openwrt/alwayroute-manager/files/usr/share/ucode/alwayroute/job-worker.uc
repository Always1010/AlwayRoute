'use strict';
import * as fs from 'fs';
const WORK_TMP='/tmp/alwayroute';
// Mechanical worker extraction: dispatch, storage and allowed methods are explicit.
export function runManagerWorker(io) {
 io.init();let lock=fs.open(WORK_TMP+'/manager.lock','ae',0600),owned=false;
 if(!lock)return;
 for(let i=0;i<4;i++){if(lock.lock('xn')){owned=true;break;}system('/bin/sleep 1');}
 if(!owned){lock.close();return;}
 let request=null,job=null,claimed=false;
 try {
  request=io.read(WORK_TMP+'/job.request.json',null);job=io.read(WORK_TMP+'/job.json',null);
  if(request && job && request.id==job.id && index(io.methods,request.method)>=0) {
   if(job.status!='running')fs.unlink(WORK_TMP+'/job.request.json');
   else {job.pid=int(split(fs.readfile('/proc/self/stat') ?? '0',' ')[0]);io.write(WORK_TMP+'/job.json',job);claimed=true;}
  }
 }catch(e){}
 // call() acquires manager.lock itself, so release the claim before execution.
 lock.lock('u');lock.close();
 if(!claimed)return;
 let response;
 if(request.method=='check'){request.args=request.args ?? {};request.args._jobId=job.id;}
 for(let i=0;i<4;i++){response=io.call(request.method,request.args,true);if(response.error?.code!='BUSY')break;system('/bin/sleep 1');}
 let latest=io.read(WORK_TMP+'/job.json',null);if(latest?.id==job.id)job=latest;
 job.status=response.ok?(response.cancelled?'cancelled':'succeeded'):'failed';job.finished=time();
 if(response.ok) {job.state=response.state ?? io.state();if(request.method=='check')job.result=response;}
 else job.error=response.error;
 io.write(WORK_TMP+'/job.json',job);fs.unlink(WORK_TMP+'/job.request.json');if(io.legacyCleanup)fs.unlink(WORK_TMP+'/subscription.body');
 if(request.method=='check')fs.unlink(WORK_TMP+'/check-cancel-'+job.id);
};
