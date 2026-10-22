'use strict';
import { fail, node } from 'alwayroute.model';

function unsupported() { fail('UNSUPPORTED_FORMAT','输入包含首版不支持的订阅格式、协议或参数；未修改原有节点'); }
function char(s,i) {return substr(s,i<0?length(s)+i:i,1);}
function allowed(o,list) { if(type(o)!='object') unsupported(); for(let k in keys(o)) if(index(list,k)<0) unsupported(); }
function decimal(value) {if(type(value)=='int')return value;if(type(value)!='string' || !match(value,/^[0-9]+$/))unsupported();return int(value);}
function decode(s) {
 s=replace(replace(trim(s),'-','+'),'_','/');
 while(length(s)%4) s+='=';
 let decoded=b64dec(s); if(decoded==null) unsupported(); return decoded;
};
// Deliberately small YAML tokenizer, not a general YAML parser. No regex-based
// extraction: every byte belongs to a known block token or an explicit rejection.
function scalar(s) {
 s=trim(s); if(!length(s)) return null;
 if(char(s,0)=='"') { try {let v=json(s);if(type(v)=='string')return v;}catch(e){} unsupported(); }
 if(char(s,0)=="'") {
  if(char(s,-1)!="'") unsupported();
  let value=''; for(let i=1;i<length(s)-1;i++) { if(char(s,i)=="'") {if(char(s,i+1)!="'")unsupported();i++;} value+=char(s,i); } return value;
 }
 for(let c in split(s,'')) if(index('{}[]&*!|>\t#',c)>=0) unsupported();
 if(s=='true')return true;if(s=='false')return false;
 return s;
};
function yaml(content) {
 let proxies=[], current=null, parents=[], found=false;
 for(let raw in split(content,'\n')) {
  if(length(raw) && char(raw,-1)=='\r')raw=substr(raw,0,length(raw)-1);
  if(!length(trim(raw)) || char(trim(raw),0)=='#')continue;
  let indent=0;while(char(raw,indent)==' ')indent++;
  let line=substr(raw,indent);
  if(!indent) {if(line!='proxies:' || found)unsupported();found=true;continue;}
  if(!found || indent%2)unsupported();
  if(indent==2 && substr(line,0,2)=='- ') {
   current={};push(proxies,current);parents=[{indent:2,obj:current}];line=substr(line,2);indent=4;
  }
  if(!current || indent<4)unsupported();
  let colon=index(line,':');if(colon<=0)unsupported();
  let key=substr(line,0,colon), tail=substr(line,colon+1);
  for(let c in split(key,''))if(index('abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_',c)<0)unsupported();
  if(length(tail) && char(tail,0)!=' ')unsupported();
  while(length(parents)>1 && parents[-1].indent>=indent)pop(parents);
  let parent=parents[-1];if(indent!=parent.indent+2)unsupported();
  if(key in parent.obj)unsupported();
  let value=scalar(tail);parent.obj[key]=value==null?{}:value;
  if(value==null)push(parents,{indent,obj:parent.obj[key]});
 }
 if(!found)unsupported();return proxies;
};
function clash(p) {
 allowed(p,['name','type','server','port','uuid','alterId','cipher','tls','servername','network','ws-opts','udp','skip-cert-verify']);
 if(p.type!='vmess' || p['skip-cert-verify']===true || (p.network && p.network!='tcp' && p.network!='ws'))unsupported();
 if(p.udp!=null && p.udp!==true)unsupported();
 let n={name:p.name,type:'vmess',server:p.server,port:decimal(p.port),uuid:p.uuid,security:p.cipher ?? 'auto',alterId:decimal(p.alterId ?? 0)};
 if(p.tls!=null) {if(type(p.tls)!='bool')unsupported();n.tls={enabled:p.tls,serverName:p.servername ?? p.server};}
 if(p.network=='ws') {
  let w=p['ws-opts'] ?? {};allowed(w,['path','headers']);if(w.headers)allowed(w.headers,['Host']);
  n.transport={type:'ws',path:w.path ?? '/',host:w.headers?.Host};
 } else if(p['ws-opts'])unsupported();
 return n;
};
function vmess(uri) {
 if(substr(uri,0,8)!='vmess://')unsupported();
 let p;try{p=json(decode(substr(uri,8)));}catch(e){unsupported();}
 allowed(p,['v','ps','add','port','id','aid','scy','net','type','host','path','tls','sni','alpn']);
 if((p.net && p.net!='tcp' && p.net!='ws') || (p.type && p.type!='none') || (p.tls && p.tls!='tls') || (p.alpn && p.alpn!=''))unsupported();
 if(p.v!=null && p.v!='2' && p.v!=2)unsupported();
 let n={name:p.ps ?? p.add,type:'vmess',server:p.add,port:decimal(p.port),uuid:p.id,security:p.scy ?? 'auto',alterId:decimal(p.aid ?? 0)};
 if(p.tls=='tls')n.tls={enabled:true,serverName:p.sni || p.host || p.add};
 if(p.net=='ws')n.transport={type:'ws',path:p.path || '/',host:p.host || null};
 return n;
};
export function parse(content,source,hash) {
 if(type(content)!='string' || !length(content) || length(content)>131072)fail('INPUT_LIMIT','订阅必须为 1..128KiB');
 let body=trim(content), raw=[];
 if(substr(body,0,8)!='vmess://' && char(body,0)!='{' && substr(body,0,8)!='proxies:')body=trim(decode(body));
 if(char(body,0)=='{') {let value;try{value=json(body);}catch(e){unsupported();}allowed(value,['proxies']);if(type(value.proxies)!='array')unsupported();for(let p in value.proxies)push(raw,clash(p));}
 else if(substr(body,0,8)=='proxies:') {for(let p in yaml(body))push(raw,clash(p));}
 else for(let line in split(body,'\n'))if(length(trim(line)))push(raw,vmess(trim(line)));
 if(!length(raw) || length(raw)>128)fail('INPUT_LIMIT','订阅节点数量必须为 1..128');
 let nodes=[],ids={};for(let n in raw) {
  n.sourceKey=substr(hash(sprintf('%J',[n.type,lc(n.server ?? ''),n.port,lc(n.uuid ?? '')])),0,24);
  n.id='s_'+source+'_'+n.sourceKey;n.source=source;n.enabled=true;node(n);
  if(ids[n.id])fail('DUPLICATE_NODE','订阅包含重复连接身份');ids[n.id]=true;push(nodes,n);
 }
 return nodes;
};
