// One pure construction boundary. Neither preview nor confirmation mutates this object.
export const clone = value => JSON.parse(JSON.stringify(value));
export function deepFreeze(value) { if(value && typeof value==='object') {Object.values(value).forEach(deepFreeze);Object.freeze(value);} return value; }
export function canonical(value) {if(Array.isArray(value))return '['+value.map(canonical).join(',')+']';if(value&&typeof value==='object')return '{'+Object.keys(value).sort().map(k=>JSON.stringify(k)+':'+canonical(value[k])).join(',')+'}';return JSON.stringify(value);}
export function content(snapshot) {const result=clone(snapshot);delete result.revision;for(const room of result.rooms||[])for(const object of room.objects||[])delete object.changed;return result;}
// ID-keyed collections avoid turning one insertion into misleading index changes.
export function netDiff(before, after, path='') {
 if(canonical(before)===canonical(after))return [];
 const keyed=v=>Array.isArray(v)&&v.length>0&&v.every(x=>x&&typeof x==='object'&&typeof x.id==='string')&&new Set(v.map(x=>x.id)).size===v.length;
 if((keyed(before)||Array.isArray(before)&&!before.length)&&(keyed(after)||Array.isArray(after)&&!after.length)){
  const a=Object.fromEntries(before.map(x=>[x.id,x])),b=Object.fromEntries(after.map(x=>[x.id,x]));return netDiff(a,b,path);
 }
 if(before&&after&&!Array.isArray(before)&&!Array.isArray(after)&&typeof before==='object'&&typeof after==='object')return [...new Set([...Object.keys(before),...Object.keys(after)])].sort().flatMap(k=>netDiff(before[k],after[k],path+'/'+k.replaceAll('~','~0').replaceAll('/','~1')));
 return [{path:path||'/',operation:before===undefined?'add':after===undefined?'remove':'replace',...(before===undefined?{}:{before:clone(before)}),...(after===undefined?{}:{after:clone(after)})}];
}
export function noteEntries(notes) {return Object.entries(notes).filter(([,v])=>typeof v==='string'&&v.trim()).map(([id,instruction])=>({id,instruction}));}
export function diffTarget(path) {const p=path.split('/').slice(1).map(x=>x.replaceAll('~1','/').replaceAll('~0','~'));if(p[0]==='rooms'&&p[1])return p[2]==='objects'&&p[3]?'instance:'+p[1]+':'+p[3]:p[2]==='background'?'background:'+p[1]:'scene:'+p[1];if(p[0]==='transitions'){if(!p[1])throw new Error('Transition diff requires a stable target ID');return 'transition:'+p[1];}if(p[0]==='behaviorDrafts'&&p[1])return 'behavior:'+p[1];return 'project';}
export function rangeIntent(id) {return id.startsWith('preset:')?'shared-preset':id.startsWith('spawn-rule:')?'shared-spawn-rule':id.startsWith('transition:')?'single-transition':id.startsWith('instance:')?'single-instance':id.startsWith('object:')||id.startsWith('behavior:')?'shared-definition':id==='project'?'project':'scene';}
export function submissionFingerprint(input) {
 return canonical({snapshot:content(input.snapshot),baseline:content(input.baselineSnapshot),notes:noteEntries(input.notes),scopes:input.scopes,resolvedTargets:input.resolveTarget?input.scopes.map(s=>input.resolveTarget(s.id)):null,connection:{threadId:input.connection?.threadId,storeId:input.connection?.storeId,revision:input.connection?.revision,sourceBaseline:input.connection?.sourceBaseline,sourceMatchesAdapter:input.connection?.sourceMatchesAdapter,mode:input.connection?.mode,supportedSubmissionVersions:input.connection?.supportedSubmissionVersions,gmReadiness:input.connection?.gmReadiness},version:input.version||1,feedback:input.feedback||null,allowedChangeScope:input.allowedChangeScope||'reviewed-targets-only',executionIntent:input.executionIntent||'review-and-apply'});
}
export function buildSubmission(input) {
 const {snapshot,baselineSnapshot,notes,scopes,connection,taskId,resolveTarget}=input,version=input.version||1;
 if(!connection?.threadId||!connection.storeId||!connection.sourceBaseline)throw new Error('连接缺少目标线程、存储或源基线。');
 if(!baselineSnapshot)throw new Error('缺少已审阅内容基线，无法生成净差异。');
 if(connection.sourceMatchesAdapter===false)throw new Error('源文件与已审阅适配器不一致。');
 if(version!==1&&!(connection.supportedSubmissionVersions||[]).includes(version))throw new Error('当前桥接未声明支持此提交版本。');
 const items=noteEntries(notes),orphans=items.filter(i=>!scopes.some(s=>s.id===i.id));
 if(orphans.length){const e=new Error('存在目标已删除的说明，请明确重新关联或移除。');e.orphans=orphans;throw e;}
 const diff=netDiff(content(baselineSnapshot),content(snapshot)).map(d=>({...d,targetId:diffTarget(d.path)}));
 if(!items.length&&!diff.length)throw new Error('没有净内容变化或修改说明；无需提交。');
 const baselineContext=id=>{const transition=(baselineSnapshot.transitions||[]).find(t=>id==='transition:'+t.id);if(transition)return {baselineContext:clone(transition)};for(const room of baselineSnapshot.rooms||[]){if(id==='scene:'+room.id||id==='background:'+room.id)return {baselineContext:clone(room)};for(const object of room.objects||[])if(id==='instance:'+room.id+':'+object.id)return {baselineContext:{roomId:room.id,object:clone(object)}}}return {}};
 const targets=[...new Set([...items.map(i=>i.id),...diff.map(d=>d.targetId)])].map(id=>({id,kind:id==='project'?'project':id.startsWith('object:')?'definition':id.slice(0,id.indexOf(':')),label:scopes.find(s=>s.id===id)?.label||id,rangeIntent:rangeIntent(id),...baselineContext(id),...(resolveTarget?clone(resolveTarget(id)||{}):{}),gm:clone(connection.gmReadiness?.targetMappings?.[id]?.gm||null),routeKind:connection.gmReadiness?.targetMappings?.[id]?.routeKind||null,allowedSourcePaths:clone(connection.gmReadiness?.targetMappings?.[id]?.allowedSourcePaths||[]),allowedDiffPaths:clone(connection.gmReadiness?.targetMappings?.[id]?.allowedDiffPaths||[])}));
 if(version!==2&&targets.some(t=>['transition','preset','spawn-rule'].includes(t.kind)))throw new Error('过渡节点、共享预设与生成规则需要 v2 精确范围；请切换提交协议，不会降级成整个项目。');
 const sentItems=items.length||version===2?items:[{id:'project',instruction:'Review the typed edits in this immutable snapshot.'}];
 const payload={version,taskId,submissionId:input.submissionId||crypto.randomUUID(),threadId:connection.threadId,baseRevision:connection.revision,storeId:connection.storeId,sourceBaseline:connection.sourceBaseline,draftRevision:snapshot.revision,snapshot:clone(snapshot),items:clone(sentItems)};
 if(input.feedback){if(version!==2)throw new Error('正式反馈仅可使用 v2。');const f=input.feedback;if(Object.keys(f).sort().join(',')!=='id,mechanics,platform,source_ref,text,type'||!/^[A-Za-z0-9_-]{1,80}$/.test(f.id)||!Array.isArray(f.mechanics)||!f.mechanics.length||f.mechanics.some(m=>typeof m!=='string'||!m.trim())||['platform','text','source_ref'].some(k=>typeof f[k]!=='string'||!f[k].trim())||!['implementation','experience','design_change','test_error','capability'].includes(f.type))throw new Error('正式反馈需要完整且有效的六字段。');if(connection.gmReadiness?.gm?.run?.command!=='check'||!connection.gmReadiness.gm.run.run_id)throw new Error('BLOCKED：尚未绑定真实 formal check run，不能执行反馈。');payload.feedback=clone(f);}
 const review={diff,notes:clone(sentItems),targets,destination:{threadId:connection.threadId,storeId:connection.storeId,mode:connection.mode},sourceBaseline:connection.sourceBaseline,baseRevision:connection.revision,allowedChangeScope:input.allowedChangeScope||'reviewed-targets-only',executionIntent:input.executionIntent||'review-and-apply'};
 if(version===2)Object.assign(payload,{resolvedTargets:targets,diff,reviewedSpecDigest:connection.gmReadiness?.gm?.specDigest||null,reviewedAuthorityDigest:connection.gmReadiness?.authorityDigest||null,allowedChangeScope:review.allowedChangeScope,executionIntent:review.executionIntent,planTags:[...new Set(targets.flatMap(t=>t.gm?.tag?[t.gm.tag]:[]))],mechanismRefs:[...new Set(targets.flatMap(t=>t.gm?.mechanics||[]))]});
 return deepFreeze({payload,body:JSON.stringify(payload),fingerprint:submissionFingerprint(input),review});
}
