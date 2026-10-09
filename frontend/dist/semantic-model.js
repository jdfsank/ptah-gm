/* Engine-neutral semantic contract. No game-specific identifiers or source parsing. */
(function (root, factory) { const api=factory(); if(typeof module==='object'&&module.exports)module.exports=api; else root.SemanticModel=api; })(typeof window==='object'?window:globalThis, function(){
'use strict';
const VERSION=2;
const kinds=['actor','environment','rule','session','progression','interface','resource'];
const behaviorTypes=['continuous','action','response','interaction','rule'];
function validate(model){
 const errors=[],ids=new Set(),all=new Map();
 const issue=(x,msg)=>errors.push(`${x}: ${msg}`);
 if(model?.schemaVersion!==VERSION)issue('schemaVersion','unsupported version');
 if(!model?.scope?.claim)issue('scope','explicit extraction claim required');
 const sources=new Map((model.sources||[]).map(s=>[s.id,s]));
 function register(x){if(!x?.id||ids.has(x.id))issue(x?.id||'id','missing or duplicate stable ID');else {ids.add(x.id);all.set(x.id,x)}}
 function evidence(x){if(!['fact','intent','inference','proposal'].includes(x.evidence))issue(x.id,'invalid evidence class');if(x.evidence==='fact'&&!x.sourceRefs?.length)issue(x.id,'fact requires evidence');for(const r of x.sourceRefs||[])if(!sources.has(r))issue(x.id,`unknown source ${r}`);if(!x.status||!x.status.implementation||!x.status.mapping||!x.status.editability||!x.status.verification)issue(x.id,'implementation / mapping / editability / verification must remain separate');else{if(!['implemented','specification','proposal','unknown'].includes(x.status.implementation))issue(x.id,'invalid implementation status');if(!['read-only','browser-draft','proposal-only','source-writeback'].includes(x.status.editability))issue(x.id,'invalid editability status');if(!['static-source','model-test','dom-test','engine-tested','unverified'].includes(x.status.verification))issue(x.id,'invalid verification status');}if(x.status?.editability==='source-writeback'&&!x.writeback?.verified)issue(x.id,'source writeback needs verified adapter');}
 for(const o of model.objects||[]){register(o);if(!kinds.includes(o.kind))issue(o.id,'invalid semantic kind');if(!o.body||!Array.isArray(o.drivers))issue(o.id,'body and drivers required');evidence(o);for(const b of o.behaviors||[]){register(b);if(!behaviorTypes.includes(b.type))issue(b.id,'invalid behavior type');evidence(b);for(const p of Object.values(b.parameters||{})){if(p.editable&&!['browser-draft','proposal-only'].includes(b.status?.editability))issue(b.id,'editable parameter contradicts status');if(p.evidence==='fact'&&!p.sourceRefs?.length)issue(b.id,'factual parameter requires evidence');for(const r of p.sourceRefs||[])if(!sources.has(r))issue(b.id,'unknown parameter source');if(p.editable&&(typeof p.value!=='number'||!Number.isFinite(p.value)))issue(b.id,'editable parameter must be finite numeric');}}}
 for(const i of model.instances||[]){register(i);if(!(model.objects||[]).some(o=>o.id===i.definitionId))issue(i.id,'instance definition missing');if(!['placed','spawn-marker'].includes(i.layer))issue(i.id,'invalid instance layer');evidence(i);}
 for(const s of model.spawnRules||[]){register(s);if(!(model.objects||[]).some(o=>o.id===s.definitionId))issue(s.id,'spawn definition missing');evidence(s);}
 for(const e of model.ledger||[]){if(!['mapped','excluded','unmapped'].includes(e.disposition))issue(e.id,'invalid ledger disposition');if(e.disposition==='mapped'&&!e.targets?.length)issue(e.id,'mapped record requires targets');for(const t of e.targets||[])if(!ids.has(t))issue(e.id,`unresolved semantic target ${t}`);if(e.disposition==='excluded'&&!e.reason)issue(e.id,'exclusion needs reason');for(const r of e.sourceRefs||[])if(!sources.has(r))issue(e.id,'unknown evidence');}
 for(const o of model.objects||[])for(const id of o.relations||[])if(!all.has(id))issue(o.id,'unknown relation '+id);
 const covered=new Set((model.ledger||[]).flatMap(e=>e.targets||[]));
 for(const [id,x] of all)if(x.evidence==='fact'&&!covered.has(id))issue(id,'no reverse coverage entry');
 return {ok:!errors.length,errors,counts:{objects:(model.objects||[]).length,behaviors:(model.objects||[]).reduce((n,o)=>n+(o.behaviors||[]).length,0),instances:(model.instances||[]).length,spawnRules:(model.spawnRules||[]).length,sources:sources.size,ledger:(model.ledger||[]).length,unmapped:(model.ledger||[]).filter(e=>e.disposition==='unmapped').length}};
}
function behavior(model,id){return (model.objects||[]).flatMap(o=>o.behaviors||[]).find(b=>b.id===id)}
function defaults(model){return Object.fromEntries((model.objects||[]).flatMap(o=>o.behaviors||[]).filter(b=>Object.values(b.parameters||{}).some(p=>p.editable)).map(b=>[b.id,Object.fromEntries(Object.entries(b.parameters).filter(([k,p])=>p.editable).map(([k,p])=>[k,p.value]))]));}
const transitionPresets=Object.freeze({black_fade:Object.freeze({id:'black_fade',label:'黑场淡入淡出',kind:'fade',coverMs:180,revealMs:220,maskResourceRef:null}),mask_wipe:Object.freeze({id:'mask_wipe',label:'遮罩擦除示意',kind:'mask',coverMs:180,revealMs:220,maskResourceRef:null})});
function deriveTransitions(rooms,existing=[]){
 if(!Array.isArray(existing))throw Error('过渡草稿结构不兼容');
 const records=new Map();
 for(const t of existing){if(!t||typeof t.id!=='string'||records.has(t.id)||!t.sourceExitRef||typeof t.sourceExitRef.roomId!=='string'||typeof t.sourceExitRef.exitId!=='string'||!t.sourceExitRef.roomId||!t.sourceExitRef.exitId||Object.keys(t.sourceExitRef).sort().join(',')!=='exitId,roomId'||Object.keys(t).sort().join(',')!=='config,id,sourceExitRef'||t.id!==transitionId(t.sourceExitRef.roomId,t.sourceExitRef.exitId)||!t.config||typeof t.config!=='object'||Array.isArray(t.config)||!['unset','none','preset'].includes(t.config.mode)||Object.keys(t.config).some(k=>!['mode','presetId'].includes(k))||(t.config.mode==='preset'?(typeof t.config.presetId!=='string'||!Object.hasOwn(transitionPresets,t.config.presetId)):Object.hasOwn(t.config,'presetId')))throw Error('过渡配置不兼容');records.set(t.id,t);}
 return rooms.flatMap(r=>r.objects.filter(o=>o.kind==='door').map(o=>{const id=transitionId(r.id,o.id);return records.get(id)||{id,sourceExitRef:{roomId:r.id,exitId:o.id},config:{mode:'unset'}}}));
}
function transitionId(roomId,exitId){return 'route:'+roomId+':'+exitId;}
function migrate(d,model){
 if(!d||d.format!=='dna-concept-local'||![1,2].includes(d.schema)||!d.data||!Array.isArray(d.data.rooms)||!d.data.rooms.length)throw Error('草稿格式或版本不兼容');
 const out=JSON.parse(JSON.stringify(d));const data=out.data;
 if(!data.rooms.every(r=>typeof r.id==='string'&&typeof r.name==='string'&&Array.isArray(r.bounds)&&r.bounds.length===4&&r.bounds.every(Number.isFinite)&&Array.isArray(r.objects)&&r.objects.every(o=>typeof o.id==='string'&&Number.isFinite(o.x)&&Number.isFinite(o.y))))throw Error('场景草稿结构不兼容');
 let warning=null;
 if(d.schema===1){if(!data.attack||!Object.values(data.attack).every(v=>typeof v==='number'&&Number.isFinite(v)&&v>=0&&v<=6))throw Error('旧版剑击草稿不兼容');data.behaviorDrafts=defaults(model);const legacy=model.migrations?.legacyAttackBehavior;if(!legacy||!data.behaviorDrafts[legacy])throw Error('缺少迁移映射');Object.assign(data.behaviorDrafts[legacy],data.attack);delete data.attack;warning='已迁移旧草稿，布局、锁定、出口与剑击参数原样保留。旧 VFX 0.14 秒仍作为草稿保留，当前源值为 0.20 秒。';}
 else {
  if(!data.behaviorDrafts||typeof data.behaviorDrafts!=='object')throw Error('动作草稿结构不兼容');
  for(const [id,fields] of Object.entries(data.behaviorDrafts)){const b=behavior(model,id);if(!b)throw Error('定义版本不兼容，请先导出原始草稿');for(const [k,v] of Object.entries(fields)){const p=b.parameters?.[k];if(!p?.editable||typeof v!=='number'||!Number.isFinite(v)||v<(p.min??0)||v>(p.max??Infinity))throw Error('动作草稿参数不兼容');}}
 }
 const base=defaults(model);for(const [id,fields] of Object.entries(base)){if(!data.behaviorDrafts[id])data.behaviorDrafts[id]=fields;else data.behaviorDrafts[id]={...fields,...data.behaviorDrafts[id]};}
 data.transitions=deriveTransitions(data.rooms,data.transitions);data.schema=2;out.schema=2;data.catalogVersion=model.catalogVersion;return {saved:out,warning};
}
return {VERSION,validate,behavior,defaults,migrate,deriveTransitions,transitionId,transitionPresets};
});
