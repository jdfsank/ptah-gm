// JS producer -> Python validator against the actual server-owned adapter baseline.
const fs=require('fs'),path=require('path'),assert=require('assert'),{spawnSync}=require('child_process');
(async()=>{const root=path.resolve(__dirname,'..'),module=await import('data:text/javascript;base64,'+fs.readFileSync(path.join(root,'src/submission-contract.js')).toString('base64'));
const baseline=JSON.parse(fs.readFileSync(path.join(root,'dist/adapter-baseline.json'),'utf8')),snapshot=structuredClone(baseline);snapshot.revision++;
snapshot.rooms[0].objects.find(o=>o.id==='entry_arch').x+=10;
const id='instance:grand_lobby:entry_arch',scope={id,label:'Arch',kind:'instance',roomId:'grand_lobby',draftId:'entry_arch'};
const connection={threadId:'fixture',storeId:'fixture',revision:0,sourceBaseline:'fixture',mode:'codex',supportedSubmissionVersions:[1,2],gmReadiness:{authorityDigest:'fixture-authority',gm:{specDigest:'fixture-spec'},targetMappings:{[id]:{kind:'instance',routeKind:'runtime',gm:{tag:'v0.1.0',planRef:'PLAN.md',mechanics:['v0.1.0-M4'],taskIds:['M04']},allowedDiffPaths:['/rooms/grand_lobby/objects/entry_arch/x'],allowedSourcePaths:['data/rooms/grand_lobby.json']}}}};
const p=module.buildSubmission({snapshot,baselineSnapshot:baseline,notes:{},scopes:[scope],connection,version:2,taskId:'velvet-eclipse',resolveTarget:()=>scope,submissionId:'cross-language-fixture'}).payload;
assert.equal(p.reviewedSpecDigest,'fixture-spec');assert.equal(p.reviewedAuthorityDigest,'fixture-authority');assert.deepEqual(p.resolvedTargets[0].allowedSourcePaths,['data/rooms/grand_lobby.json']);assert.deepEqual(p.items,[]);
const code="import sys,json;sys.path.insert(0,'bridge');import gm_contract as gm;p=json.load(sys.stdin);gm.validate_v2(p);gm.verify_reviewed_diff(p,gm.adapter_baseline());print('PASS')";
const result=spawnSync('python3',['-c',code],{cwd:root,input:JSON.stringify(p),encoding:'utf8'});assert.equal(result.status,0,result.stderr);assert.equal(result.stdout.trim(),'PASS');
const bad=structuredClone(p);bad.diff[0].before=123456;const rejected=spawnSync('python3',['-c',code],{cwd:root,input:JSON.stringify(bad),encoding:'utf8'});assert.notEqual(rejected.status,0);console.log('cross-contract: actual JS v2 payload passes Python schema/baseline; forged before rejected');})().catch(e=>{console.error(e);process.exit(1)});
