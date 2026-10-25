'use strict';
// Production installer runs against metadata-only synthetic storage. Any file
// read, process start, or external utility access is absent from this adapter.
let metadata=null,changes=[],mkdirFails=false,chmodFails=false,verifyFails=false;
let fs={
 lstat:function(path){assert(path=='/etc/alwayroute','only the fixed configuration directory is inspected');return metadata;},
 mkdir:function(path,mode){push(changes,['mkdir',path,mode]);if(mkdirFails)return false;metadata={type:'directory',uid:0,mode:verifyFails?0755:mode};return true;},
 chmod:function(path,mode){push(changes,['chmod',path,mode]);if(chmodFails)return false;metadata.mode=verifyFails?0755:mode;return true;}
};
// EXTERNAL_STORAGE_SOURCE
let checks=0;
function check(value,message){checks++;assert(value,message);}
function rejected(){let error=null;try{prepareExternalStorage();}catch(e){error=e;}return error!=null;}
prepareExternalStorage();
check(metadata.mode==0700 && length(changes)==1 && changes[0][0]=='mkdir','fresh installation creates only a private directory');
changes=[];prepareExternalStorage();check(length(changes)==0,'private directory remains untouched');
metadata={type:'directory',uid:0,mode:0755};changes=[];prepareExternalStorage();
check(metadata.mode==0700 && length(changes)==1 && changes[0][0]=='chmod','recognized root-owned legacy 0755 is tightened');
for(let mode in [0777,0775,0733,0702,0744,0750,01755,04755]) {
 metadata={type:'directory',uid:0,mode};changes=[];
 check(rejected() && length(changes)==0,'unsafe or unrecognized modes are rejected without mutation');
}
for(let kind in ['link','file','fifo']) {
 metadata={type:kind,uid:0,mode:0755};changes=[];
 check(rejected() && length(changes)==0,'links and non-directory objects are rejected without mutation');
}
metadata={type:'directory',uid:1000,mode:0755};changes=[];
check(rejected() && length(changes)==0,'non-root ownership is rejected without mutation');
metadata={type:'directory',uid:0,mode:0755};chmodFails=true;
check(rejected() && metadata.mode==0755,'failed tightening does not report successful migration');chmodFails=false;
metadata=null;mkdirFails=true;
check(rejected(),'failed first creation is refused');mkdirFails=false;
metadata={type:'directory',uid:0,mode:0755};verifyFails=true;
check(rejected(),'post-change metadata must confirm private directory');
print(sprintf('PASS external storage migration: %d checks\n',checks));
