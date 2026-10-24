'use strict';
let requestFixture={},calls=0,lastCommand='';
let fs={
 readfile:()=>sprintf('%J',requestFixture),unlink:()=>true,chmod:()=>true,
 popen:function(command){calls++;lastCommand=command;return {read:()=>'fixture body',close:()=>0};},
 open:()=>({write:value=>length(value),close:()=>true})
};
function exit(code){die('FETCH_EXIT:'+code);}
function download(){
// FETCH_SOURCE
}
function runFixture(request){
 requestFixture=request;calls=0;lastCommand='';
 try{download();}catch(e){let marker='FETCH_EXIT:';assert(index(e.message,marker)==0,'unexpected downloader exception');return int(substr(e.message,length(marker)));}
 die('downloader did not return an exit status');
}
let checks=0;
function check(ok,message){checks++;assert(ok,message);}
check(runFixture({url:'https://example.invalid/sub'})==0 && calls==1,'HTTPS accepted without HTTP exception');
check(index(lastCommand,'--no-check-certificate')<0,'HTTPS retains default certificate validation');
check(index(lastCommand,'--https-only')>=0,'default subscription policy enforces HTTPS on the complete redirect chain');
check(index(lastCommand,'--header-limits')>=0 && index(lastCommand,'--no-proxy')>=0,'subscription downloader bounds parser metadata and ignores ambient proxy credentials');
check(runFixture({url:'http://example.invalid/sub'})==1 && calls==0,'HTTP rejected without flag');
check(runFixture({url:'http://example.invalid/sub',allowHttp:false})==1 && calls==0,'HTTP rejected with disabled flag');
check(runFixture({url:'http://example.invalid/sub',allowHttp:'true'})==1 && calls==0,'HTTP string true is not permission');
check(runFixture({url:'http://example.invalid/sub',allowHttp:true})==0 && calls==1,'explicit boolean HTTP exception accepted');
check(index(lastCommand,'--https-only')<0,'only the explicitly approved source can use an HTTP redirect');
check(runFixture({url:'ftp://example.invalid/sub',allowHttp:true})==1 && calls==0,'exception cannot allow arbitrary scheme');
check(runFixture({url:'https://example.invalid/sub',allowHttp:false})==0 && calls==1,'HTTPS accepted with disabled exception');
for(let url in ['https:///missing-host','https://#fragment','https://?query','https://user@:443/sub','https://:443/sub'])check(runFixture({url})==1 && calls==0,'downloader rejects URL without authority and host: '+url);
check(runFixture({url:' HTTPS://user:pass@example.test/sub?token=%2fA+z#keep '})==0 && index(lastCommand,"'https://user:pass@example.test/sub?token=%2fA+z#keep'")>=0 && index(lastCommand,'--https-only')>=0,'downloader normalizes HTTPS scheme while preserving URL bytes and downgrade protection');
check(runFixture({url:'HTTP://example.test/sub'})==1 && calls==0,'uppercase HTTP cannot bypass explicit permission');
check(runFixture({url:'HTTP://example.test/sub',allowHttp:true})==0 && index(lastCommand,"'http://example.test/sub'")>=0 && index(lastCommand,'--https-only')<0,'uppercase HTTP works only with explicit boolean permission');
printf('PASS %d downloader permission checks\n',checks);
