// Hosted UI demo only. No request leaves this browser; local bridge stays unchanged.
export const browserDemo = location.hostname.endsWith('.chatgpt.site') || new URLSearchParams(location.search).get('demo') === '1';
const key = 'dna-browser-submit-demo-v1';
function failure(message){const error=new Error(message);error.definite=true;throw error;}
function resultFor(payload,message){return {message,schemaVersion:2,receipt:{status:'ACCEPTED',submissionId:payload.submissionId},delivery:{status:'NOT_DELIVERED',reason:'Browser-local simulation only; no Agent delivery.'},turn:{status:'NOT_STARTED'},implementation:'BLOCKED',verification:'BLOCKED',humanRequired:null,capabilityMessage:'No real execution or formal check run exists in this browser demo. A reviewed local GM binding is required.',certified:false,refs:{submissionId:payload.submissionId,turnId:null,taskIds:[],runId:null,reportRefs:[]},items:(payload.version===2?payload.resolvedTargets:payload.items).map(i=>({id:i.id,status:'demo_validated',implementation:'BLOCKED',verification:'BLOCKED',humanRequired:null}))};}
function validate(payload){
 if(!payload||![1,2].includes(payload.version))failure('不支持的提交版本');
 if(typeof payload.submissionId!=='string'||!payload.submissionId||!payload.snapshot||!Number.isInteger(payload.draftRevision)||payload.snapshot.revision!==payload.draftRevision||!Array.isArray(payload.items)||(!payload.items.length&&!(payload.version===2&&Array.isArray(payload.diff)&&payload.diff.length))||payload.items.some(i=>typeof i.id!=='string'||typeof i.instruction!=='string'||i.instruction.length>10000))failure('无效提交内容');
 if(payload.version===2){
 if(payload.feedback)failure('BLOCKED：浏览器演示没有真实 formal check run，不能提交正式反馈');
 for(const key of ['reviewedSpecDigest','reviewedAuthorityDigest'])if(!(key in payload)||(payload[key]!==null&&typeof payload[key]!=='string'))failure('缺少已审阅的GM权威基线');
  if(payload.allowedChangeScope!=='reviewed-targets-only'||payload.executionIntent!=='review-and-apply'||!Array.isArray(payload.resolvedTargets)||!Array.isArray(payload.diff)||!Array.isArray(payload.planTags)||!Array.isArray(payload.mechanismRefs))failure('无效 v2 提交范围');
  const ids=payload.resolvedTargets.map(t=>t.id),expected=[...new Set([...payload.items.map(i=>i.id),...payload.diff.map(d=>d.targetId)])];if(new Set(ids).size!==ids.length||expected.some(id=>!ids.includes(id))||ids.some(id=>!expected.includes(id)))failure('v2 目标与说明 / 差异不一致');
  if(payload.resolvedTargets.some(t=>!t||typeof t.id!=='string'||typeof t.kind!=='string')||payload.diff.some(d=>!d||typeof d.path!=='string'||typeof d.targetId!=='string'||!['add','remove','replace'].includes(d.operation)||(d.operation!=='add'&&!Object.hasOwn(d,'before'))||(d.operation!=='remove'&&!Object.hasOwn(d,'after'))))failure('无效 v2 目标或净差异');
 }
}
function read(){const raw=localStorage.getItem(key);if(raw)return JSON.parse(raw);const store={storeId:crypto.randomUUID(),threadId:'browser-demo-only',revision:0,last:null,submissions:{}};localStorage.setItem(key,JSON.stringify(store));return store;}
function update(store){const last=store.last;if(last&&['accepted','processing'].includes(last.state)){
 const age=Date.now()-last.acceptedAt;
 if(age>=2200){last.state='succeeded';last.result=resultFor(last.payload,'模拟验证通过：快照仅保存在此浏览器。未发送给 Agent，未调用模型，未修改 Godot 项目。');}
 else if(age>=500){last.state='processing';last.result=resultFor(last.payload,'正在本浏览器模拟检查冻结快照；未发送给 Agent。');}
 store.submissions[last.submissionId]=last;localStorage.setItem(key,JSON.stringify(store));
 }return store;}
export async function demoApi(path,options){
 const run=()=>{const store=update(read());
 if(path==='/api/session')return {token:'browser-demo-no-network'};
 if(path==='/api/status')return {...store,supportedSubmissionVersions:[1,2],gmReadiness:{status:'BLOCKED',checks:[{id:'real-gm',ok:false,message:'Browser demo has no real GM execution binding.'}]},mode:'demo',sourceMatchesAdapter:true,sourceBaseline:'browser-demo-not-source-validation'};
 if(path.startsWith('/api/submission/'))return {submission:store.submissions[decodeURIComponent(path.slice('/api/submission/'.length))]||null};
 if(path==='/api/submit'){
 const payload=JSON.parse(options.body);validate(payload);const old=store.submissions[payload.submissionId];
 if(old){if(JSON.stringify(old.payload)!==JSON.stringify(payload))failure('同一提交编号对应不同内容');return old;}
 if(payload.storeId!==store.storeId||payload.threadId!==store.threadId||payload.baseRevision!==store.revision)failure('演示状态已改变，请刷新状态');
 if(store.last&&['accepted','processing'].includes(store.last.state))failure('已有模拟提交处理中');
 const receipt={submissionId:payload.submissionId,payload:structuredClone(payload),state:'accepted',acceptedAt:Date.now(),result:resultFor(payload,'演示快照已保存到此浏览器，正在模拟处理；未发送给 Agent。')};
 store.last=receipt;store.submissions[receipt.submissionId]=receipt;store.revision++;localStorage.setItem(key,JSON.stringify(store));return receipt;
 }failure('不支持的演示操作');};
 return navigator.locks ? navigator.locks.request(key,run) : run();
}
