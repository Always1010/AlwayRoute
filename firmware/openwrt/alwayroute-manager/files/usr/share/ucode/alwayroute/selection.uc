'use strict';
import { clone, generate } from 'alwayroute.model';

// A selector PUT cannot update DNS rules, routes, members, or node parameters.
// Compare both the model and generated config, failing closed to a full apply.
export function selectionPlan(previous, next, runtime) {
 let before=clone(previous),after=clone(next),changes=[];
 delete before.revision;delete after.revision;
 // get() overlays download status on subscriptions; this is not core config.
 for(let s in before.subscriptions)delete s.lastError;
 for(let s in after.subscriptions)delete s.lastError;
 for(let i,g in before.groups) {
  if(after.groups[i]?.id!=g.id)return null;
  if(g.selected!=after.groups[i].selected)push(changes,{id:g.id,before:g.selected,after:after.groups[i].selected});
  delete g.selected;delete after.groups[i].selected;
 }
 if(!length(changes) || sprintf('%J',before)!=sprintf('%J',after))return null;
 let original=generate(previous),candidate=generate(next);
 if(sprintf('%J',runtime)!=sprintf('%J',original))return null;
 let comparable=clone(candidate);
 for(let o in original.outbounds)if(o.type=='selector')delete o.default;
 for(let o in comparable.outbounds)if(o.type=='selector')delete o.default;
 if(sprintf('%J',original)!=sprintf('%J',comparable))return null;
 return {changes,config:candidate};
};
