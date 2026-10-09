#!/usr/bin/env node
/* Object-workflow Studio contract checks. This uses mock local API data only. */
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const { pathToFileURL } = require('node:url');
let JSDOM;
try { ({ JSDOM } = require('jsdom')); }
catch { console.log('SKIP studio object QA: jsdom is unavailable.'); process.exit(0); }

const root = path.resolve(__dirname, '..');
const dom = new JSDOM(fs.readFileSync(path.join(root, 'studio/index.html'), 'utf8'), { url: 'http://127.0.0.1:8123/studio/', pretendToBeVisual: true });
global.document = dom.window.document; global.FormData = dom.window.FormData;
global.confirm = () => { throw new Error('QA must not make a user decision.'); };
const calls = [], routes = new Map(), timers = new Map(); let timerId = 0;
const workspace = { workspaceId: 'qa', projects: [{ id: 'game-1', title: '对象协议演示', workflow: 'objects-v1' }], jobs: [], proposals: [], packets: [], capabilities: { interactiveFrontendConfirmation: true, sessionDispatch: true, godotVerification: true, semanticProjection: true } };
const objectSnapshot = {
  projectId: 'game-1', workflow: 'objects-v1', publicationRevision: 7, sourceCommit: 'git-base-7', title: '对象协议演示', summary: '基于对象的 2D 游戏',
  catalog: { objects: [
    { id: 'player', kind: 'entity', name: '玩家', description: '主场景中的可控角色。', relations: [{ type: 'belongs_to', targetId: 'main' }], sourceBindings: ['scripts/player.gd'], fields: [{ id: 'speed', label: '移动速度', type: 'number', value: 220 }] },
    { id: 'main', kind: 'scene', name: '主场景', description: '游戏入口场景。', relations: [], sourceBindings: ['scenes/main.tscn'], fields: [] },
  ] },
};
const capabilities = { fields: [
  { id: 'player.speed', objectId: 'player', fieldId: 'speed', label: '移动速度', type: 'scalar', value: 220, editable: true, min: 0, max: 500 },
  { id: 'player.mode', objectId: 'player', fieldId: 'mode', label: '移动模式', type: 'choice', value: 'walk', editable: true, options: [{ value: 'walk', label: '步行' }, { value: 'dash', label: '冲刺' }] },
  { id: 'player.visible', objectId: 'player', fieldId: 'visible', label: '显示角色', type: 'boolean', value: true, editable: true },
  { id: 'player.spawn', objectId: 'player', fieldId: 'spawn', label: '出生位置', type: 'vector2', value: [0, 0], editable: true },
  { id: 'player.label', objectId: 'player', fieldId: 'label', label: '显示名称', type: 'text', value: '玩家', editable: true },
  { id: 'player.internal_seed', objectId: 'player', fieldId: 'internal_seed', label: '内部种子', type: 'integer', value: 7, editable: false, supported: true },
  { id: 'player.variant', objectId: 'player', fieldId: 'variant', label: '变体', type: 'choice', value: 1, editable: true, options: [{ value: 1, label: '数字 1' }, { value: '1', label: '文本 1' }] },
] };
routes.set('GET /api/session', { token: 'qa-token' }); routes.set('GET /api/workspace', workspace);
routes.set('GET /api/projects/game-1/workbench', { snapshot: objectSnapshot, capabilities, candidates: [] });
routes.set('POST /api/concepts', ({ body }) => ({ proposal: { id: 'proposal-objects', revision: 1, workflow: 'objects-v1', projectId: 'game-1', publicationRevision: 7, status: body.changeRequest ? 'PLANNING' : 'PLANNING', text: body.text, changeRequest: body.changeRequest, summary: '策划中' } }));
const fetchImpl = async (url, init = {}) => {
  const method = init.method || 'GET', key = `${method} ${new URL(url, 'http://127.0.0.1:8123').pathname}`;
  const body = init.body ? JSON.parse(init.body) : undefined; calls.push({ key, body });
  const route = routes.get(key); if (typeof route === 'function') return response(route({ body, init }));
  return route ? response(route) : response({ error: `missing test route ${key}` }, 404);
};
const response = (body, status = 200) => ({ ok: status >= 200 && status < 300, status, text: async () => JSON.stringify(body) });
const tick = async () => new Promise(resolve => setTimeout(resolve, 0));

(async () => {
  const { StudioApp } = await import(pathToFileURL(path.join(root, 'studio/studio.js')).href);
  const fakeTimers = { setInterval(fn) { const id = ++timerId; timers.set(id, fn); return id; }, clearInterval(id) { timers.delete(id); }, setTimeout, clearTimeout };
  const app = new StudioApp({ fetchImpl, documentImpl: dom.window.document, timers: fakeTimers }); app.bind(); await app.start(); await app.openProject('game-1');
  const earlierFailure = { id: 'proposal-old-failed', projectId: 'game-1', status: 'FAILED', createdAt: '2026-01-01T00:00:00Z' };
  const latestFailure = { id: 'proposal-latest-failed', revision: 3, workflow: 'objects-v1', projectId: 'game-1', publicationRevision: 7, status: 'FAILED', text: '原项目策划', createdAt: '2026-01-02T00:00:00Z', planningFailure: { code: 'PLANNER_TIMEOUT', retryable: false, clarificationAvailable: true }, planningTerminationConfirmed: true };
  const otherProjectFailure = { id: 'proposal-other-failed', projectId: 'game-2', status: 'FAILED', createdAt: '2026-01-03T00:00:00Z' };
  workspace.proposals = [earlierFailure, latestFailure, otherProjectFailure]; app.workspace = workspace; document.querySelector('#project').value = 'game-1';
  assert.equal(app.pendingProposal('game-1').id, latestFailure.id, 'proposal selection chooses the newest proposal within the selected project');
  assert.equal(app.pendingProposal('game-2').id, otherProjectFailure.id, 'proposal lookup is scoped to the requested project');
  await app.openProject('game-1');
  assert.equal(app.proposal.id, latestFailure.id, 'openProject restores the selected project latest FAILED proposal');
  assert(document.querySelector('[data-action="recover-clarification"]'), 'openProject restores the FAILED clarification recovery entry point');
  await app.refresh();
  assert.equal(app.proposal.id, latestFailure.id, 'refresh restores the selected project latest FAILED proposal');
  await app.start();
  assert.equal(app.proposal.id, latestFailure.id, 'a reload through start restores the selected project latest FAILED proposal');
  app.workspace.proposals.push({ id: 'proposal-newer-cancelled', projectId: 'game-1', status: 'CANCELLED', createdAt: '2026-01-04T00:00:00Z' });
  assert.equal(app.pendingProposal('game-1'), null, 'a newer terminal proposal suppresses an older FAILED diagnostic');
  workspace.proposals = [];
  workspace.projects = [{ id: 'game-1', title: '项目 A' }, { id: 'game-2', title: '项目 B' }];
  const proposalA = { id: 'proposal-A-current', projectId: 'game-1', revision: 2, status: 'FAILED', createdAt: '2026-10-01T00:00:00Z', planningFailure: { code: 'PLANNER_TIMEOUT' } };
  const staleJobB = { id: 'job-B-stale', projectId: 'game-2', status: 'RUNNING' };
  workspace.proposals = [proposalA]; workspace.jobs = [staleJobB]; app.workspace = workspace;
  routes.set('GET /api/projects/game-2/workbench', { snapshot: { ...objectSnapshot, projectId: 'game-2', title: '项目 B' }, capabilities, candidates: [] });
  document.querySelector('#project').value = 'game-1'; app.snapshot = objectSnapshot; app.proposal = proposalA; app.job = staleJobB; app.renderProposal(); document.querySelector('#job-panel').classList.remove('hidden');
  const callsBeforeProjectSwitch = calls.length;
  await app.openProject('game-1');
  assert.equal(app.snapshot.projectId, 'game-1'); assert.equal(app.proposal.id, proposalA.id); assert.equal(document.querySelector('#project').value, 'game-1', 'openProject keeps the selected project after clearing an old job panel');
  assert.equal(app.job, null); assert(document.querySelector('#job-panel').classList.contains('hidden'), 'switching projects hides stale job status without changing server state');
  assert(!calls.slice(callsBeforeProjectSwitch).some(call => call.key === 'GET /api/jobs/job-B-stale' || call.key === 'GET /api/projects/game-2/workbench'), 'openProject never requests another project job or workbench');
  app.job = staleJobB; document.querySelector('#job-panel').classList.remove('hidden'); routes.set('GET /api/workspace', workspace);
  const callsBeforeRefresh = calls.length; await app.refresh();
  assert.equal(app.snapshot.projectId, 'game-1'); assert.equal(app.proposal.id, proposalA.id); assert.equal(document.querySelector('#project').value, 'game-1', 'refresh preserves project A snapshot, proposal and selection');
  assert.equal(app.job, null); assert(document.querySelector('#job-panel').classList.contains('hidden'), 'refresh clears stale project B job display when A has no jobs');
  assert(!calls.slice(callsBeforeRefresh).some(call => call.key === 'GET /api/jobs/job-B-stale' || call.key === 'GET /api/projects/game-2/workbench'), 'refresh does not fetch the stale project B job or workbench');
  app.capabilities = capabilities; app.workflow = 'objects-v1';
  app.snapshot = { ...objectSnapshot, projectId: 'concept-p0', title: '概念阶段', publicationRevision: 0, kind: 'CONCEPT', playable: false };
  app.renderWorkbench();
  const conceptBanner = document.querySelector('#snapshot-summary').textContent;
  assert(conceptBanner.includes('当前处于概念阶段，尚未制作或验证工程'), 'CONCEPT revision zero does not claim the project was verified');
  assert(!conceptBanner.includes('已验证的工程准备基线'), 'CONCEPT stage cannot be mistaken for initialized engineering');
  app.snapshot = { ...objectSnapshot, projectId: 'init-p1', title: '初始化基线', publicationRevision: 1, kind: 'INITIALIZATION', playable: false };
  app.renderWorkbench();
  assert(document.querySelector('#snapshot-summary').textContent.includes('已验证的工程准备基线'), 'INITIALIZATION retains its verified baseline explanation');
  app.snapshot = { ...objectSnapshot, projectId: 'other-p1', title: '未验证基线', publicationRevision: 1, kind: 'OTHER', playable: false };
  app.renderWorkbench();
  const nonPlayableBanner = document.querySelector('#snapshot-summary').textContent;
  assert(nonPlayableBanner.includes('尚无可玩的 MVP') && !nonPlayableBanner.includes('已验证的工程准备基线'), 'other non-playable snapshots make no unsupported verification claim');
  app.snapshot = objectSnapshot; app.renderWorkbench();
  assert.equal(app.workflow, 'objects-v1'); assert.equal(document.querySelectorAll('#dynamic-fields [data-capability-id]:not([data-axis])').length, 7);
  const readonly = document.querySelector('#dynamic-fields [data-field-id="player.internal_seed"]');
  assert.equal(readonly.disabled, true, 'supported:true cannot make an explicitly read-only generic field editable');
  assert.equal(readonly.step, '1', 'integer capabilities use integer input steps');
  assert(document.querySelector('#object-detail').textContent.includes('内部种子 · 只读'), 'object inspector reports explicit read-only capability');
  readonly.value = '9'; readonly.dispatchEvent(new dom.window.Event('input', { bubbles: true }));
  assert(document.querySelector('#object-detail').textContent.includes('scripts/player.gd'), 'object inspector should expose source bindings');
  assert(document.querySelector('#object-detail').textContent.includes('belongs_to → main'), 'object inspector should expose relationships');

  const speed = document.querySelector('#dynamic-fields [data-field-id="player.speed"]'); speed.value = '340'; speed.dispatchEvent(new dom.window.Event('input', { bubbles: true }));
  const spawnX = document.querySelector('#dynamic-fields [data-field-id="player.spawn"][data-axis="x"]'); const spawnY = document.querySelector('#dynamic-fields [data-field-id="player.spawn"][data-axis="y"]');
  assert.equal(spawnX.value, '0'); assert.equal(spawnY.value, '0', 'vector2 array values populate both axis controls');
  spawnX.value = '12'; spawnY.value = '-4'; spawnY.dispatchEvent(new dom.window.Event('input', { bubbles: true }));
  document.querySelector('#edit-text').value = '让玩家移动更灵敏';
  document.querySelector('#feedback-message').value = '转向时有明显延迟'; document.querySelector('#feedback-category').value = 'behavior'; document.querySelector('#add-feedback').click();
  await app.submitIteration(); await tick();
  const changeCall = calls.find(call => call.key === 'POST /api/concepts');
  assert.equal(changeCall.body.workflow, undefined, 'existing project workflow is selected by server-owned project state');
  assert.equal(changeCall.body.text, '让玩家移动更灵敏', 'natural language stays separate and is not combined with numeric controls');
  assert.deepEqual(changeCall.body.changeRequest.fields, [{ objectId: 'player', fieldId: 'speed', value: 340 }, { objectId: 'player', fieldId: 'spawn', value: [12, -4] }], 'changed vector2 values serialize as protocol arrays and readonly fields stay excluded');
  assert.deepEqual(changeCall.body.changeRequest.feedback, [{ objectId: 'player', message: '转向时有明显延迟', category: 'behavior' }]);
  assert.deepEqual(changeCall.body.changeRequest.targetObjectIds, ['player']);
  assert.equal(changeCall.body.changeRequest.baseRevision, 7); assert.equal(changeCall.body.changeRequest.sourceCommit, 'git-base-7');

  document.querySelector('#project').value = ''; document.querySelector('#concept').value = '一个 2D 俯视探索游戏';
  app.proposal = null; await app.submitConcept(); await tick();
  const newConceptCall = calls.filter(call => call.key === 'POST /api/concepts').at(-1);
  assert.equal(newConceptCall.body.workflow, 'objects-v1', 'new concepts explicitly select the generic objects workflow');

  document.querySelector('#project').value = 'game-1'; app.proposal = { id: 'previous-proposal', projectId: 'game-1', status: 'CANCELLED' };
  document.querySelector('#edit-text').value = '';
  const numericChoice = document.querySelector('#dynamic-fields [data-field-id="player.speed"]'); numericChoice.value = '360'; numericChoice.dispatchEvent(new dom.window.Event('input', { bubbles: true }));
  await app.submitIteration(); await tick();
  const structuredOnly = calls.filter(call => call.key === 'POST /api/concepts').at(-1);
  assert.equal(structuredOnly.body.text, '', 'structured-only iterations preserve an empty natural language field');
  assert.deepEqual(structuredOnly.body.changeRequest.fields, [{ objectId: 'player', fieldId: 'speed', value: 360 }, { objectId: 'player', fieldId: 'spawn', value: [12, -4] }]);

  app.proposal = { id: 'proposal-question', revision: 4, workflow: 'objects-v1', status: 'NEEDS_CLARIFICATION', questions: [{ id: 'camera', prompt: '镜头模式？', type: 'choice', required: true, options: [{ value: 5, label: '跟随' }, { value: 'fixed', label: '固定' }] }] };
  app.renderProposal();
  assert.equal(document.querySelectorAll('#questions select').length, 1); assert.equal(document.querySelectorAll('#questions input, #questions textarea').length, 0, 'choice questions must not add an overriding free-text control');
  routes.set('POST /api/proposals/proposal-question/answers', { proposal: { id: 'proposal-question', revision: 5, workflow: 'objects-v1', projectId: 'game-1', status: 'PLANNING' } });
  document.querySelector('#questions select').value = '5'; await app.answerQuestions();
  const questionCall = calls.find(call => call.key === 'POST /api/proposals/proposal-question/answers');
  assert.equal(questionCall.body.answers.camera, 5, 'numeric choice values retain their JSON type');
  const timeoutFailure = { id: 'proposal-timeout-recovery', revision: 8, workflow: 'objects-v1', projectId: 'game-1', status: 'FAILED', message: 'raw execution detail', planningTerminationConfirmed: true, planningFailure: { code: 'PLANNER_TIMEOUT', retryable: false, clarificationAvailable: true } };
  app.proposal = timeoutFailure; app.renderProposal();
  assert(document.querySelector('[data-action="recover-clarification"]'), 'FAILED proposal with safe clarification and confirmed stop shows recovery action');
  const recoveredQuestions = [{ id: 'camera', prompt: '镜头模式？', type: 'choice', required: true, options: [{ value: 'follow', label: '跟随' }, { value: 'fixed', label: '固定' }] }, { id: 'goal', prompt: '胜利条件？', type: 'text', required: true }];
  const timeoutRecovery = { id: timeoutFailure.id, revision: 9, workflow: 'objects-v1', projectId: 'game-1', status: 'NEEDS_CLARIFICATION', document: null, tasks: [], planningTerminationConfirmed: true, planningRecovery: { kind: 'CLARIFICATION_FROM_TIMEOUT', nativeStatus: 'timeout', message: 'raw /Users/person/reference.png' }, questions: recoveredQuestions };
  routes.set('POST /api/proposals/proposal-timeout-recovery/reconcile', { proposal: timeoutRecovery });
  document.querySelector('[data-action="recover-clarification"]').click(); await tick();
  assert(calls.some(call => call.key === 'POST /api/proposals/proposal-timeout-recovery/reconcile'), 'recovery action calls the existing proposal reconcile endpoint');
  assert(!document.querySelector('#proposal-content').textContent.includes('raw /Users/person/reference.png') && document.querySelector('#proposal-content').textContent.includes('这里只恢复已校验的澄清问题'), 'recovered clarification shows a fixed safe warning');
  assert(!document.querySelector('#proposal-content').textContent.includes('raw execution detail'), 'recovered clarification does not render arbitrary proposal message');
  assert.equal(document.querySelectorAll('#questions [name]').length, 2, 'recovered clarification keeps its answer form visible');
  assert(document.querySelector('#freeze-area').classList.contains('hidden'), 'clarification recovery keeps the freeze panel hidden');
  assert.equal(document.querySelector('#freeze').disabled, true, 'clarification recovery cannot enable plan confirmation');
  assert(!document.querySelector('[data-action="recover-clarification"]'), 'recovered NEEDS_CLARIFICATION needs no second recovery button');
  app.proposal = { ...timeoutFailure, id: 'proposal-stop-unknown', planningTerminationConfirmed: false }; app.renderProposal();
  assert(!document.querySelector('[data-action="recover-clarification"]'), 'unconfirmed stop state never offers clarification recovery');
  const failedProposal = { id: 'proposal-failed', revision: 1, workflow: 'objects-v1', projectId: 'game-1', publicationRevision: 7, status: 'FAILED', message: 'raw stderr /Users/alice/private.png', text: '原始概念输入', assets: [{ id: 'asset-one', name: '参考一' }, { id: 'asset-two', name: '参考二' }, { id: 'asset-three', name: '参考三' }], changeRequest: { baseRevision: 7, targetObjectIds: ['player'], fields: [{ objectId: 'player', fieldId: 'speed', value: 250 }] }, planningFailure: { code: 'PLANNER_TIMEOUT', message: 'raw stderr /Users/alice/private.png', retryable: true, nativeStatus: 'failed', elapsedSeconds: 19.4, sessionId: 'native-session-17', terminationConfirmed: true } };
  workspace.proposals.push(failedProposal); app.workspace = workspace; app.snapshot = objectSnapshot; app.proposal = failedProposal; app.renderProposal();
  const diagnostic = document.querySelector('#proposal-content').textContent;
  assert(diagnostic.includes('策划 session 等待超时') && diagnostic.includes('19 秒') && diagnostic.includes('native-session-17') && diagnostic.includes('已确认停止'), 'FAILED plan exposes safe structured native diagnostics');
  assert.equal(document.querySelector('#proposal-status').textContent, '策划失败', 'FAILED proposal uses a planning-specific status label');
  assert(!diagnostic.includes('raw stderr') && !diagnostic.includes('/Users/alice/private.png'), 'failure details never expose raw stderr or user image paths');
  const retryButton = document.querySelector('[data-action="retry-planning"]'); assert(retryButton, 'retryable failed plan offers an explicit retry button');
  const proposalCountBeforeRetry = workspace.proposals.length;
  routes.set('POST /api/concepts', ({ body }) => ({ proposal: { id: 'proposal-retry', revision: 1, workflow: 'objects-v1', projectId: 'game-1', status: 'PLANNING', text: body.text, assetIds: body.assetIds, changeRequest: body.changeRequest } }));
  retryButton.click(); retryButton.click(); await tick();
  const retryCalls = calls.filter(call => call.key === 'POST /api/concepts'); const retryCall = retryCalls.at(-1);
  assert.equal(retryCalls.length, 4, 'double-click while submitting sends only one retry request');
  assert.equal(retryCall.body.text, '原始概念输入'); assert.deepEqual(retryCall.body.assetIds, ['asset-one', 'asset-two', 'asset-three'], 'server proposal assets objects retain every original asset id');
  assert.deepEqual(retryCall.body.changeRequest, failedProposal.changeRequest, 'retry retains the prior structured change request');
  assert.equal(retryCall.body.projectId, 'game-1'); assert.equal(retryCall.body.workflow, 'objects-v1', 'retry explicitly retains generic object workflow'); assert.equal(retryCall.body.expectedPublicationRevision, 7, 'retry is bound to the failed proposal publication revision');
  assert.equal(workspace.proposals.length, proposalCountBeforeRetry, 'retry does not erase the failed proposal record');
  assert.equal(app.proposal.id, 'proposal-retry'); assert.equal(app.proposal.status, 'PLANNING', 'retry creates a new planning revision');
  assert(!calls.some(call => call.key === 'POST /api/proposals/proposal-failed/freeze'), 'retry never freezes or approves automatically');
  app.proposal = { ...failedProposal, id: 'proposal-null-time', planningFailure: { ...failedProposal.planningFailure, elapsedSeconds: null, code: 'PLANNER_RESPONSE_INVALID', message: '策划结果未通过校验' } }; app.renderProposal();
  const nullElapsedText = document.querySelector('#proposal-content').textContent;
  assert(!nullElapsedText.includes('耗时') && !nullElapsedText.includes('0 秒'), 'null elapsedSeconds does not become a misleading zero');
  for (const [code, reason] of [['PLANNER_AUTH', '身份验证失败'], ['PLANNER_RESTRICTED', '超出当前角色范围'], ['PLANNER_RESPONSE_INVALID', '无法识别的结果'], ['PLANNER_WRITE', '违反只读范围'], ['PLANNER_SETUP', '未能启动'], ['PLANNER_UNCERTAIN', '停止状态尚未确认']]) {
    app.proposal = { ...failedProposal, planningFailure: { code, retryable: false } }; app.renderProposal();
    assert(document.querySelector('#proposal-content').textContent.includes(reason), `${code} has a localized diagnostic label`);
  }
  app.proposal = failedProposal; workspace.proposals = [failedProposal]; app.renderProposal();
  routes.set('POST /api/concepts', () => { throw new TypeError('network disconnected'); });
  let retryButtonForUnknown = document.querySelector('[data-action="retry-planning"]'); const postCountBeforeNetworkFailure = calls.filter(call => call.key === 'POST /api/concepts').length;
  retryButtonForUnknown.click(); await tick();
  assert.equal(calls.filter(call => call.key === 'POST /api/concepts').length, postCountBeforeNetworkFailure + 1);
  assert.equal(document.querySelector('[data-action="retry-planning"]').disabled, true, 'network failure leaves retry disabled while outcome is unknown');
  assert(document.querySelector('#proposal-content').textContent.includes('请先刷新工作台核账'), 'unknown outcome explains that workspace reconciliation is required');
  assert(document.querySelector('[data-action="reconcile-retry"]'), 'unknown outcome offers an explicit workspace refresh action');
  document.querySelector('[data-action="retry-planning"]').click(); await tick();
  assert.equal(calls.filter(call => call.key === 'POST /api/concepts').length, postCountBeforeNetworkFailure + 1, 'unknown response cannot be resubmitted before reconciliation');
  document.querySelector('[data-action="reconcile-retry"]').click(); await tick();
  assert.equal(app.proposal.id, failedProposal.id, 'successful refresh with no replacement restores the original failed record');
  assert.equal(document.querySelector('[data-action="retry-planning"]').disabled, false, 'a completed workspace reconciliation releases the retry guard');

  routes.set('POST /api/concepts', () => { const error = new Error('server error'); error.status = 503; throw error; });
  document.querySelector('[data-action="retry-planning"]').click(); await tick();
  assert.equal(document.querySelector('[data-action="retry-planning"]').disabled, true, 'server 5xx also leaves retry disabled until refresh');
  const replacement = { id: 'proposal-after-unknown', revision: 1, workflow: 'objects-v1', projectId: 'game-1', status: 'PLANNING', createdAt: '2099-01-01T00:00:00Z' };
  routes.set('GET /api/workspace', { ...workspace, proposals: [failedProposal, replacement] });
  document.querySelector('[data-action="reconcile-retry"]').click(); await tick();
  assert.equal(app.proposal.id, replacement.id, 'refresh adopts a newly created proposal and does not expose duplicate retry');
  assert(!document.querySelector('[data-action="retry-planning"]'), 'replacement proposal has no stale retry button');

  app.proposal = failedProposal; workspace.proposals = [failedProposal]; routes.set('GET /api/workspace', workspace);
  routes.set('POST /api/concepts', () => { const error = new Error('STALE_DRAFT'); error.status = 409; throw error; }); app.renderProposal();
  document.querySelector('[data-action="retry-planning"]').click(); await tick();
  assert.equal(document.querySelector('[data-action="retry-planning"]').disabled, false, 'explicit 4xx rejection permits a user-initiated retry');
  assert(!document.querySelector('[data-action="reconcile-retry"]'), 'explicit 4xx rejection does not require unknown-outcome reconciliation');
  routes.set('POST /api/concepts', () => { throw new TypeError('network disconnected'); });
  document.querySelector('[data-action="retry-planning"]').click(); await tick();
  assert.equal(document.querySelector('[data-action="retry-planning"]').disabled, true, 'network retry is locked before workspace verification');
  workspace.proposals = [failedProposal, { id: 'proposal-later-terminal', projectId: 'game-1', status: 'CANCELLED', createdAt: '2099-01-01T00:00:00Z' }];
  routes.set('GET /api/workspace', workspace); document.querySelector('#refresh').click(); await tick(); await tick();
  assert.equal(app.retryOutcomeUnknown, null, 'successful top-level refresh clears the retry guard for the selected project');
  assert.equal(app.proposal, null, 'a newer terminal proposal suppresses the older failed proposal after reconciliation');
  assert(document.querySelector('#proposal-panel').classList.contains('hidden'), 'refresh never resurrects a superseded failure retry button');
  app.proposal = { id: 'proposal-plan', revision: 5, workflow: 'objects-v1', status: 'READY', text: '计划', document: { title: '计划对象', summary: '核心循环', objects: [{ id: 'player', kind: 'entity', name: '玩家', description: '移动角色', relations: [], sourceBindings: ['scripts/player.gd'], fields: [{ id: 'speed', label: '移动速度', type: 'number', value: 340, editable: true, min: 0, max: 500 }] }], requirements: [{ id: 'r1', text: '操作玩家移动', objectIds: ['player'], verification: 'manual' }] }, tasks: [{ id: 't1', title: '实现玩家移动' }], changeRequest: changeCall.body.changeRequest };
  app.renderProposal();
  assert(document.querySelector('#proposal-content').textContent.includes('计划对象') && document.querySelector('#proposal-content').textContent.includes('移动速度 (number) = 340') && document.querySelector('#proposal-content').textContent.includes('实现玩家移动') && document.querySelector('#proposal-content').textContent.includes('人工体验验收') && document.querySelector('#proposal-content').textContent.includes('转向时有明显延迟'), 'READY proposal must expose object properties, requirements, tasks, field diff, and feedback');

  app.proposal = { id: 'proposal-planning', revision: 1, workflow: 'objects-v1', status: 'PLANNING_CANCELLING', projectId: 'game-1' }; app.renderProposal();
  assert(timers.size >= 1, 'proposal polling is independently started'); const proposalTimerId = app.proposalPollHandle; app.pollHandle = 999; app.stopProposalPolling(); assert.equal(timers.has(proposalTimerId), false, 'proposal polling stops its own timer'); assert.equal(app.pollHandle, 999, 'stopping proposal polling does not touch game job polling'); app.pollHandle = null;

  document.querySelector('#project').value = 'game-1'; app.proposal = { id: 'prior', projectId: 'game-1', status: 'CANCELLED' }; app.persistenceOK = false;
  const oldSnapshot = app.snapshot, nextSnapshot = { ...objectSnapshot, publicationRevision: 8, sourceCommit: 'git-base-8' };
  app.snapshot = nextSnapshot; app.capabilities = capabilities; app.handleRebase(oldSnapshot, nextSnapshot, app.readVisibleDraft());
  const submittedBeforeRebase = calls.filter(call => call.key === 'POST /api/concepts').length;
  await app.submitIteration(); assert.equal(calls.filter(call => call.key === 'POST /api/concepts').length, submittedBeforeRebase, 'pending object draft rebase blocks iteration');
  assert(document.querySelector('#rebase-content').textContent.includes('player.speed'), 'rebase preview names the retained object field');
  await app.confirmRebase(); assert.equal(document.querySelector('#dynamic-fields [data-field-id="player.speed"]').value, '360', 'explicit rebase carries the reviewed object field draft');

  app.feedback = [{ objectId: 'player', message: 'keep in draft', category: 'visual' }]; const draft = app.readVisibleDraft();
  assert.equal(draft.fields['player.speed'], 360); assert.deepEqual(draft.fields['player.spawn'], [12, -4], 'vector2 draft remains an array'); assert.equal(draft.feedback[0].message, 'keep in draft');
  const variant = document.querySelector('#dynamic-fields [data-field-id="player.variant"]');
  assert.equal(variant.value, '__option_0', 'ambiguous typed choices use opaque DOM option values');
  variant.selectedIndex = 2;
  assert.equal(app.readControlValue(variant), '1', 'string choice remains distinguishable from a numeric choice with the same display text');
  app.applyVisibleDraft({ fields: { 'player.internal_seed': 9 }, feedback: [], values: {} });
  assert.equal(app.fieldDraftValues['player.internal_seed'], 9, 'old draft can be retained for review even when its field is now read-only');
  assert(!app.buildChangeRequest().fields.some(field => field.fieldId === 'internal_seed'), 're-associated stale draft must not submit a field whose current capability is read-only');
  app.destroy(); dom.window.close();
  async function launchFresh(workspaceState) {
    const freshDom = new JSDOM(fs.readFileSync(path.join(root, 'studio/index.html'), 'utf8'), { url: 'http://127.0.0.1:8123/studio/', pretendToBeVisual: true });
    global.document = freshDom.window.document; global.FormData = freshDom.window.FormData;
    const freshCalls = [], freshRoutes = new Map();
    freshRoutes.set('GET /api/session', { token: 'fresh-token' }); freshRoutes.set('GET /api/workspace', workspaceState);
    for (const project of workspaceState.projects) freshRoutes.set(`GET /api/projects/${project.id}/workbench`, { snapshot: { projectId: project.id, workflow: 'objects-v1', publicationRevision: 1, sourceCommit: `git-${project.id}`, title: project.title, catalog: { objects: [] } }, capabilities: { fields: [] }, candidates: [] });
    const freshFetch = async (url, init = {}) => {
      const key = `${init.method || 'GET'} ${new URL(url, 'http://127.0.0.1:8123').pathname}`; freshCalls.push({ key, body: init.body ? JSON.parse(init.body) : undefined });
      const value = freshRoutes.get(key); if (value === undefined) return response({ error: `missing fresh route ${key}` }, 404);
      return response(typeof value === 'function' ? await value({ init }) : value);
    };
    const freshTimers = { setInterval(fn) { const id = ++timerId; timers.set(id, fn); return id; }, clearInterval(id) { timers.delete(id); }, setTimeout, clearTimeout };
    const freshApp = new StudioApp({ fetchImpl: freshFetch, documentImpl: freshDom.window.document, timers: freshTimers }); freshApp.bind(); await freshApp.start();
    return { app: freshApp, document: freshDom.window.document, window: freshDom.window, calls: freshCalls };
  }
  const recoveryWorkspace = { workspaceId: 'fresh-recovery', projects: [{ id: 'project-a', title: '项目 A' }, { id: 'project-b', title: '项目 B' }], jobs: [], packets: [], testData: true, capabilities: { interactiveFrontendConfirmation: true, sessionDispatch: true, godotVerification: true, semanticProjection: true }, proposals: [
    { id: 'project-a-old-failure', projectId: 'project-a', status: 'FAILED', createdAt: '2026-10-01T00:00:00Z' },
    { id: 'project-a-latest-cancelled', projectId: 'project-a', status: 'CANCELLED', createdAt: '2026-10-02T00:00:00Z' },
    { id: 'project-b-latest-failure', projectId: 'project-b', revision: 2, workflow: 'objects-v1', status: 'FAILED', createdAt: '2026-10-03T00:00:00Z', planningFailure: { code: 'PLANNER_TIMEOUT', clarificationAvailable: true }, planningTerminationConfirmed: true },
  ] };
  const freshFailure = await launchFresh(recoveryWorkspace);
  assert.equal(freshFailure.document.querySelector('#project').value, 'project-b', 'fresh reload selects the project of the most recent actionable proposal');
  assert.equal(freshFailure.app.proposal.id, 'project-b-latest-failure', 'fresh reload restores only that project latest FAILED proposal');
  assert(!freshFailure.document.querySelector('#proposal-content').textContent.includes('project-a-old-failure'), 'fresh reload never mixes a superseded failure from another project');
  assert.equal(freshFailure.calls.filter(call => call.key === 'POST /api/concepts').length, 0, 'fresh recovery does not create another planning session');
  freshFailure.app.destroy(); freshFailure.window.close();

  const frozenWorkspace = { workspaceId: 'fresh-frozen', projects: [{ id: 'project-frozen', title: '冻结项目' }], jobs: [], packets: [{ id: 'packet-frozen-fresh', proposalId: 'proposal-frozen-fresh', projectId: 'project-frozen', operationKind: 'IMPLEMENTATION' }], testData: true, capabilities: { interactiveFrontendConfirmation: true, sessionDispatch: true, godotVerification: true, semanticProjection: true }, proposals: [{ id: 'proposal-frozen-fresh', projectId: 'project-frozen', packetId: 'packet-frozen-fresh', revision: 4, status: 'FROZEN', createdAt: '2026-10-04T00:00:00Z' }] };
  const freshFrozen = await launchFresh(frozenWorkspace);
  assert.equal(freshFrozen.document.querySelector('#project').value, 'project-frozen', 'fresh reload restores a frozen proposal project without jobs');
  assert.equal(freshFrozen.app.proposal.id, 'proposal-frozen-fresh', 'frozen proposal remains visible when no jobs exist');
  assert(!freshFrozen.document.querySelector('#resume-packet').classList.contains('hidden'), 'frozen proposal offers its existing packet for explicit resume');
  assert.equal(freshFrozen.calls.filter(call => call.key === 'POST /api/jobs').length, 0, 'frozen recovery does not dispatch a job automatically');
  freshFrozen.app.destroy(); freshFrozen.window.close();

  const emptyWorkspace = { workspaceId: 'fresh-empty', projects: [], jobs: [], packets: [], proposals: [], testData: true, capabilities: { interactiveFrontendConfirmation: true, sessionDispatch: true, godotVerification: true, semanticProjection: true } };
  const freshEmpty = await launchFresh(emptyWorkspace);
  assert.equal(freshEmpty.document.querySelector('#project').value, '', 'empty workspace remains in the new Demo state');
  assert(freshEmpty.document.querySelector('#proposal-panel').classList.contains('hidden'), 'empty workspace does not invent a proposal recovery flow');
  freshEmpty.app.destroy(); freshEmpty.window.close();
  console.log(JSON.stringify({ status: 'PASS', checks: ['selected project A remains isolated from stale project B job during open/refresh', 'concept revision zero, initialization, and non-playable status copy', 'fresh DOM reload restores FAILED and frozen proposals without dispatch', 'project-scoped latest proposal lookup and terminal supersession', 'start/openProject/refresh restore latest FAILED diagnosis', 'top-level refresh reconciles unknown retry without reviving superseded failures', 'object catalog and relationships', 'typed dynamic fields', 'separate natural language/changeRequest', 'only changed fields', 'object feedback', 'choice clarification control', 'complete READY object plan', 'safe timeout clarification recovery and stop confirmation', 'safe structured planner failure diagnostics and planning status label', 'failure code labels and null elapsed time', 'explicit retry preserves prior inputs, assets, workflow, and revision', 'unknown network/5xx retry reconciliation and confirmed 4xx retry', 'double-click retry guard and no implicit freeze', 'independent proposal polling', 'draft field and feedback retention'] }, null, 2));
})().catch(error => { dom.window.close(); console.error(error); process.exitCode = 1; });
