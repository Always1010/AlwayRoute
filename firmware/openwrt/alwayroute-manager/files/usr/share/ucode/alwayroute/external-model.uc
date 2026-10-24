'use strict';

function invalid(message) { die('ALWAYROUTE:INVALID_EXTERNAL:'+message); }
function objectFields(value, allowed) {
 if(type(value)!='object')invalid('需要外部配置对象');
 for(let key in keys(value))if(index(allowed,key)<0)invalid('存在不支持的外部配置字段');
};
export function externalIPv4(value) {
 if(type(value)!='string' || !match(value,/^[0-9]{1,3}(\.[0-9]{1,3}){3}$/))return false;
 let octets=split(value,'.');
 for(let octet in octets)if(int(octet)>255 || sprintf('%d',int(octet))!=octet)return false;
 return int(octets[0])>0 && int(octets[0])<224 && int(octets[0])!=127 && value!='255.255.255.255';
};
function mac(value) {return type(value)=='string' && match(value,/^[0-9a-f]{2}(:[0-9a-f]{2}){5}$/) && index(['0','2','4','6','8','a','c','e'],substr(value,1,1))>=0 && value!='00:00:00:00:00:00';}
function port(value) {return type(value)=='int' && value>=1 && value<=65535;}
export function emptyExternal() {
 return {schema:1,revision:0,enabled:false,family:'ipv4',faultPolicy:'block',link:null,clients:[],dns:{gatewayPort:1053,listenPort:1053,localDomains:['lan']},bypass4:[]};
};
export function validateExternal(value) {
 objectFields(value,['schema','revision','enabled','family','faultPolicy','link','clients','dns','bypass4']);
 if(value.schema!==1 || type(value.revision)!='int' || value.revision<0 || value.revision>2147483645 || type(value.enabled)!='bool' || value.family!='ipv4' || value.faultPolicy!='block')invalid('外部配置版本、开关或故障策略无效');
 if(type(value.clients)!='array' || length(value.clients)>1 || type(value.bypass4)!='array' || length(value.bypass4)>32)invalid('首版只允许一台测试终端及最多32个目的例外');
 if(value.link!=null) {
  objectFields(value.link,['interface','routerAddress','gatewayAddress','gatewayMac']);
  let l=value.link;
  if(type(l.interface)!='string' || !match(l.interface,/^[A-Za-z0-9_][A-Za-z0-9_.:-]{0,14}$/) || !externalIPv4(l.routerAddress) || !externalIPv4(l.gatewayAddress) || l.routerAddress==l.gatewayAddress || !mac(l.gatewayMac))invalid('链路接口、地址或MAC无效');
 }
 for(let client in value.clients) {
  objectFields(client,['address','mac']);
  if(!externalIPv4(client.address) || !mac(client.mac) || !value.link || client.address==value.link.routerAddress || client.address==value.link.gatewayAddress || client.mac==value.link.gatewayMac)invalid('测试终端身份无效或与网关冲突');
 }
 if(value.enabled && (!value.link || length(value.clients)!=1))invalid('开启需要完整链路与一台测试终端');
 objectFields(value.dns,['gatewayPort','listenPort','localDomains']);
 if(!port(value.dns.gatewayPort) || !port(value.dns.listenPort) || value.dns.listenPort==53 || type(value.dns.localDomains)!='array' || length(value.dns.localDomains)<1 || length(value.dns.localDomains)>16)invalid('专用DNS端口或本地域无效');
 let seen={};
 for(let domain in value.dns.localDomains) {
  if(type(domain)!='string' || length(domain)>253 || !match(domain,/^[a-z0-9]([a-z0-9.-]*[a-z0-9])?$/) || index(domain,'..')>=0 || seen[domain])invalid('本地域格式无效或重复');
  for(let label in split(domain,'.'))if(length(label)>63 || !match(label,/^[a-z0-9]([a-z0-9-]*[a-z0-9])?$/))invalid('本地域标签无效');
  seen[domain]=true;
 }
 seen={};
 for(let cidr in value.bypass4) {
  if(type(cidr)!='string')invalid('目的例外需要IPv4 CIDR');
  let parts=split(cidr,'/');
  if(length(parts)!=2 || !externalIPv4(parts[0]) || !match(parts[1],/^([1-9]|[12][0-9]|3[0-2])$/) || seen[cidr])invalid('目的例外CIDR无效、过宽或重复');
  let prefix=int(parts[1]),octets=split(parts[0],'.'),number=0;
  for(let octet in octets)number=number*256+int(octet);
  if(number % (2 ** (32-prefix))!=0)invalid('目的例外必须使用网络地址');
  seen[cidr]=true;
 }
 if(length(sprintf('%J',value))>8192)invalid('外部配置超过大小限制');
 return json(sprintf('%J',value));
};
export function validateExternalPeer(peer,config,now) {
 objectFields(peer,['gateway','revision','generation','observedAt','coreReady','captureReady','dnsReady','egressViaRouter','returnViaRouter','sourcePreserved']);
 if(peer.gateway!=config.link.gatewayAddress || peer.revision!==config.revision || type(peer.generation)!='string' || !match(peer.generation,/^[A-Za-z0-9_-]{1,128}$/) || type(peer.observedAt)!='int' || peer.observedAt>now || now-peer.observedAt>30)invalid('对端观察目标、代次或新鲜度不匹配');
 for(let key in ['coreReady','captureReady','dnsReady','egressViaRouter','returnViaRouter','sourcePreserved'])if(peer[key]!==true)invalid('对端核心、接管、DNS、来源或路径尚未确认');
 let result=json(sprintf('%J',peer));result.method='operator';return result;
};
