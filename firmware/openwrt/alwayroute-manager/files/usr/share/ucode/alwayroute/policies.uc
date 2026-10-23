'use strict';
import * as fs from 'fs';

export function loadPolicies() {
 // A process-local override lets host checks use the same installed data layout.
 let root=getenv('ALWAYROUTE_POLICY_DIR') ?? '/usr/share/alwayroute/policies';
 function read(name) {
  let body=fs.readfile(root+'/'+name);
  if(!body || length(body)>131072)die('ALWAYROUTE:POLICY_DATA_ERROR:服务规则文件缺失或过大');
  try {return json(body);}catch(e){die('ALWAYROUTE:POLICY_DATA_ERROR:服务规则文件格式无效');}
 }
 let names=read('catalog.json'),result=[],seen={};
 if(type(names)!='array' || length(names)>32)die('ALWAYROUTE:POLICY_DATA_ERROR:服务目录无效');
 for(let name in names) {
  if(type(name)!='string' || !match(name,/^[a-z0-9-]+\.json$/))die('ALWAYROUTE:POLICY_DATA_ERROR:服务文件名无效');
  let p=read(name);
  if(type(p)!='object' || type(p.id)!='string' || seen[p.id] || type(p.name)!='string' || type(p.description)!='string' || type(p.default)!='bool' || type(p.domains)!='array' || type(p.exactDomains)!='array')die('ALWAYROUTE:POLICY_DATA_ERROR:服务定义无效');
  for(let values in [p.domains,p.exactDomains])for(let value in values)if(type(value)!='string' || !match(value,/^[A-Za-z0-9._-]{1,253}$/))die('ALWAYROUTE:POLICY_DATA_ERROR:服务域名无效');
  seen[p.id]=true;
  push(result,{id:p.id,name:p.name,default:p.default,description:p.description,domains:p.domains,exactDomains:p.exactDomains});
 }
 if(!seen.Proxy || !seen.Other)die('ALWAYROUTE:POLICY_DATA_ERROR:服务目录缺少必要出口');
 return result;
};
