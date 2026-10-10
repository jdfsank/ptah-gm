#!/usr/bin/env node
/* Planner retry/recovery and typed-choice regressions in project-scoped Studio. */
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const { pathToFileURL } = require('node:url');
let JSDOM;
try { ({ JSDOM } = require('jsdom')); } catch { console.log('SKIP Studio planner QA: jsdom is unavailable.'); process.exit(0); }

const root = path.resolve(__dirname, '..');
const dom = new JSDOM(fs.readFileSync(path.join(root, 'studio/index.html'), 'utf8'), { url: 'http://127.0.0.1:8123/studio/', pretendToBeVisual: true });
const savedDocument = global.document; delete global.document;
global.FormData = dom.window.FormData; global.HTMLElement = dom.window.HTMLElement;
const project = { id: 'planner-project', title: '策划回归项目', workflow: 'objects-v1', publicationRevision: 7 };
const capabilities = { interactiveFrontendConfirmation: true, sessionDispatch: true, godotVerification: true, semanticProjection: true };
const baseline = { projectId: project.id, workflow: 'objects-v1', publicationRevision: 7, sourceCommit: 'git-base-7', kind: 'MVP', playable: true, catalog: { objects: [] } };
let proposals = [];
const calls = [];
const routes = new Map();
const response = (data, status = 200) => ({ ok: status >= 200 && status < 300, status, text: async () => JSON.stringify(data) });
const workspace = () => ({ storeId: 'planner-store', projects: [project], proposals, packets: [], jobs: [], capabilities, iterationReady: true, testData: false });
const fetchImpl = async (url, init = {}) => {
  const method = init.method || 'GET'; const pathname = new URL(url, 'http://127.0.0.1:8123').pathname; const body = init.body ? JSON.parse(init.body) : undefined;
  calls.push({ method, pathname, body });
  if (pathname === '/api/session') return response({ token: 'planner-token' });
  if (pathname === '/api/workspace' || pathname === `/api/projects/${project.id}/workspace`) return response(workspace());
  if (pathname === `/api/projects/${project.id}/workbench`) return response({ snapshot: baseline, capabilities: { fields: [] }, candidates: [], iterationReady: true });
  const route = routes.get(`${method} ${pathname}`);
  if (route === undefined) return response({ error: `missing route ${method} ${pathname}` }, 404);
  return typeof route === 'function' ? route({ body, init }) : route;
};
const tick = () => new Promise(resolve => setTimeout(resolve, 0));

(async () => {
  const { StudioApp } = await import(pathToFileURL(path.join(root, 'studio/studio.js')).href);
  global.document = dom.window.document; global.location = dom.window.location; global.history = dom.window.history;
  const app = new StudioApp({ fetchImpl, documentImpl: dom.window.document, timers: globalThis });
  app.drafts = { open: async () => ({}), get: async () => null, put: async item => item, delete: async () => {} };
  app.bind(); await app.start(); await app.openProject(project.id); app.enterIterationStage();

  const question = { id: 'proposal-question', projectId: project.id, revision: 4, workflow: 'objects-v1', status: 'NEEDS_CLARIFICATION', questions: [{ id: 'camera', prompt: '镜头模式？', type: 'choice', required: true, options: [{ value: 5, label: '数字值' }, { value: '5', label: '文本值' }] }] };
  app.proposal = question; app.renderProposal();
  const choice = document.querySelector('#questions select'); choice.value = '__option_0';
  routes.set(`POST /api/projects/${project.id}/proposals/${question.id}/answers`, response({ proposal: { ...question, revision: 5, status: 'PLANNING', questions: [] } }));
  await app.answerQuestions();
  const answerCall = calls.find(call => call.pathname.endsWith(`/proposals/${question.id}/answers`));
  assert.equal(answerCall.body.answers.camera, 5, 'numeric option stays numeric when labels and values are ambiguous');
  assert.equal(app.readChoiceValue(choice), 5, 'typed option decoding preserves number values');
  choice.value = '__option_1'; assert.equal(app.readChoiceValue(choice), '5', 'typed option decoding distinguishes numeric and string values');

  const failed = { id: 'proposal-failed', projectId: project.id, revision: 8, publicationRevision: 7, workflow: 'objects-v1', status: 'FAILED', text: '保留原始概念', assets: [{ id: 'asset-a' }, { id: 'asset-b' }], changeRequest: { baseRevision: 7, targetObjectIds: ['player'], fields: [{ objectId: 'player', fieldId: 'speed', value: 260 }] }, planningTerminationConfirmed: true, planningFailure: { code: 'PLANNER_TIMEOUT', retryable: false, clarificationAvailable: true, terminationConfirmed: true, elapsedSeconds: 12, sessionId: 'native-session' } };
  proposals = [failed]; app.workspace.proposals = proposals; app.proposal = failed; app.renderProposal();
  assert(document.querySelector('[data-action="recover-clarification"]'), 'confirmed planner timeout offers clarification recovery');
  routes.set(`POST /api/projects/${project.id}/proposals/${failed.id}/reconcile`, response({ proposal: { ...failed, revision: 9, status: 'NEEDS_CLARIFICATION', questions: [{ id: 'goal', prompt: '目标？', type: 'text' }], planningRecovery: { kind: 'CLARIFICATION_FROM_TIMEOUT', message: 'raw /private/user/image.png' } } }));
  document.querySelector('[data-action="recover-clarification"]').click(); await tick(); await tick();
  assert(document.querySelector('#proposal-content').textContent.includes('这里只恢复已校验的澄清问题'), 'recovered clarification explains its limited scope');
  assert(!document.querySelector('#proposal-content').textContent.includes('/private/user/image.png'), 'recovery output never renders raw local paths');
  app.proposal = { ...failed, planningTerminationConfirmed: false }; app.renderProposal();
  assert(!document.querySelector('[data-action="recover-clarification"]'), 'unconfirmed native stop never offers recovery');

  const retryFailure = { ...failed, id: 'proposal-retry-source', status: 'FAILED', planningTerminationConfirmed: true, planningFailure: { code: 'PLANNER_TIMEOUT', retryable: true, terminationConfirmed: true } };
  proposals = [retryFailure]; app.workspace.proposals = proposals; app.proposal = retryFailure; app.renderProposal();
  let finishRetry;
  routes.set(`POST /api/projects/${project.id}/concepts`, () => new Promise(resolve => { finishRetry = () => resolve(response({ proposal: { id: 'proposal-retry-created', projectId: project.id, revision: 1, publicationRevision: 7, workflow: 'objects-v1', status: 'PLANNING' } })); }));
  const retryButton = document.querySelector('[data-action="retry-planning"]'); retryButton.click(); retryButton.click(); await tick();
  assert.equal(calls.filter(call => call.pathname === `/api/projects/${project.id}/concepts`).length, 1, 'double click creates at most one retry request');
  const retryCall = calls.find(call => call.pathname === `/api/projects/${project.id}/concepts`);
  assert.equal(retryCall.body.text, '保留原始概念'); assert.deepEqual(retryCall.body.assetIds, ['asset-a', 'asset-b']);
  assert.deepEqual(retryCall.body.changeRequest, retryFailure.changeRequest); assert.equal(retryCall.body.expectedPublicationRevision, 7);
  finishRetry(); await tick(); await tick(); assert.equal(app.proposal.id, 'proposal-retry-created', 'successful retry adopts the new planning session');

  const checkOutcomeUnknown = async (statusOrNetwork) => {
    app.proposal = retryFailure; proposals = [retryFailure]; app.workspace.proposals = proposals; app.retryOutcomeUnknown = null; app.renderProposal();
    if (statusOrNetwork === 'network') routes.set(`POST /api/projects/${project.id}/concepts`, () => { throw new TypeError('disconnected'); });
    else routes.set(`POST /api/projects/${project.id}/concepts`, response({ error: 'server unavailable' }, statusOrNetwork));
    document.querySelector('[data-action="retry-planning"]').click(); await tick(); await tick();
    assert.equal(app.retryOutcomeUnknown, retryFailure.id, `${statusOrNetwork} failure locks retry pending reconciliation`);
    assert(document.querySelector('[data-action="reconcile-retry"]'), 'unknown retry outcome has an explicit refresh action');
    const getWorkspace = routes.get(`GET /api/projects/${project.id}/workspace`);
    routes.set(`GET /api/projects/${project.id}/workspace`, response(workspace()));
    document.querySelector('[data-action="reconcile-retry"]').click(); await tick(); await tick(); await tick();
    routes.set(`GET /api/projects/${project.id}/workspace`, getWorkspace);
    assert.equal(app.retryOutcomeUnknown, null, 'workspace reconciliation clears retry uncertainty when the source proposal remains latest');
  };
  await checkOutcomeUnknown('network');
  await checkOutcomeUnknown(503);
  app.proposal = retryFailure; proposals = [retryFailure]; app.workspace.proposals = proposals; app.renderProposal();
  routes.set(`POST /api/projects/${project.id}/concepts`, response({ error: 'stale revision' }, 409));
  document.querySelector('[data-action="retry-planning"]').click(); await tick(); await tick();
  assert.equal(app.retryOutcomeUnknown, null, 'definitive client rejection does not require unknown-outcome reconciliation');
  assert.equal(document.querySelector('[data-action="retry-planning"]').disabled, false, 'definitive rejection leaves an explicit retry available');

  app.proposal = { id: 'proposal-ready', projectId: project.id, revision: 10, workflow: 'objects-v1', status: 'READY', document: { title: '对象计划', summary: '核心循环', objects: [{ id: 'player', kind: 'entity', name: '玩家', fields: [{ id: 'speed', label: '移动速度', type: 'scalar', value: 340 }] }], requirements: [{ text: '操作玩家移动', verification: 'manual' }] }, tasks: [{ title: '实现移动' }] }; app.renderProposal();
  const planText = document.querySelector('#proposal-content').textContent;
  assert(planText.includes('对象计划') && planText.includes('移动速度 (scalar) = 340') && planText.includes('实现移动') && planText.includes('人工体验验收'), 'READY output shows objects, typed properties, tasks, and verification requirements');

  app.stage = 'iteration'; app.workspace.iterationReady = true; app.snapshot = { ...baseline, publicationRevision: 1, playable: true }; app.proposal = null; app.job = null;
  routes.set(`POST /api/projects/${project.id}/concepts`, ({ body }) => response({ proposal: { id: 'iteration-planning', projectId: project.id, revision: 1, publicationRevision: 1, workflow: 'objects-v1', status: 'PLANNING', text: body.text, changeRequest: { baseRevision: 1, targetObjectIds: ['player'] } } }));
  document.querySelector('#edit-text').value = '让敌人移动更慢'; await app.submitIteration();
  assert(!document.querySelector('#proposal-panel').classList.contains('hidden'), 'iteration planning remains visible alongside the object editor');
  assert.equal(document.querySelector('#proposal-title').textContent, '本轮调整讨论');
  assert(document.querySelector('#proposal-content').textContent.includes('用户本轮调整'), 'iteration proposal labels its user input as the current adjustment');
  app.proposal = { ...app.proposal, status: 'NEEDS_CLARIFICATION', questions: [{ id: 'pace', prompt: '减慢多少？', type: 'number', required: true }] }; app.renderProposal();
  assert(!document.querySelector('#answers-form').classList.contains('hidden'), 'iteration clarification form stays visible');
  document.querySelector('#questions [name="pace"]').value = '25';
  routes.set(`POST /api/projects/${project.id}/proposals/iteration-planning/answers`, response({ proposal: { ...app.proposal, revision: 2, status: 'READY', questions: [], aiSummary: '迭代方案已整理', document: { title: '迭代计划', summary: '本轮改变敌人速度', objects: [{ id: 'enemy', kind: 'entity', name: '敌人', fields: [] }] } } }));
  await app.answerQuestions();
  assert(!document.querySelector('#proposal-panel').classList.contains('hidden'), 'iteration READY plan remains visible for review');
  assert(!document.querySelector('#freeze-area').classList.contains('hidden'), 'iteration READY plan exposes its explicit confirmation controls');
  assert(document.querySelector('#proposal-content').textContent.includes('迭代计划'), 'iteration READY object plan is displayed in the current stage');
  app.proposal = { ...app.proposal, status: 'FAILED', planningFailure: { code: 'PLANNER_TIMEOUT', retryable: true } }; app.renderProposal();
  assert(!document.querySelector('#proposal-panel').classList.contains('hidden') && document.querySelector('[data-action="retry-planning"]'), 'iteration planning failure remains visible with its recovery action');
  app.proposal = { id: 'historical-baseline', projectId: project.id, revision: 1, publicationRevision: 0, workflow: 'objects-v1', status: 'FROZEN' }; app.packet = { id: 'historical-packet', proposalId: 'historical-baseline', projectId: project.id }; app.job = { id: 'historical-job', projectId: project.id, proposalId: 'historical-baseline', packetId: 'historical-packet', status: 'PUBLISHED' }; app.renderProposal(); app.renderWorkflowStages();
  assert(document.querySelector('#proposal-panel').classList.contains('hidden'), 'completed initial proposal history stays hidden during iteration');
  app.proposal = { id: 'iteration-frozen', projectId: project.id, revision: 3, publicationRevision: 1, workflow: 'objects-v1', status: 'FROZEN', changeRequest: { baseRevision: 1 } }; app.packet = { id: 'new-iteration-packet', proposalId: 'iteration-frozen', projectId: project.id };
  app.renderProposal(); app.renderWorkflowStages();
  assert(!document.querySelector('#proposal-panel').classList.contains('hidden'), 'new iteration packet remains visible while a previous baseline job is published');

  app.stage = 'initial'; app.workspace.iterationReady = false; app.snapshot = { ...baseline, publicationRevision: 0, playable: false };
  const approvedPacket = { id: 'failed-first-packet', packetId: 'failed-first-packet', projectId: project.id, assets: [{ id: 'asset-project', name: '项目参考图', purpose: 'style' }], approvedProposal: { projectId: project.id, text: '保留原来的玩家移动想法', assets: [{ id: 'asset-project', name: '项目参考图', purpose: 'style' }, { id: 'asset-foreign', projectId: 'other-project' }] } };
  app.workspace.packets = [approvedPacket]; app.proposal = null; app.packet = null; app.assets = []; app.job = { id: 'failed-first-job', projectId: project.id, packetId: approvedPacket.id, status: 'FAILED', message: '首个 Demo 制作失败', productionFailure: { terminationConfirmed: true, nextAction: 'NEW_PLANNING' } }; app.renderJob();
  let restoreInput = document.querySelector('[data-action="restore-approved-input"]');
  assert(restoreInput, 'failed initial Demo offers an explicit original-input recovery action');
  assert(document.querySelector('#job-panel').textContent.includes('可手动提交新策划；之后仍需审阅确认'), 'confirmed stop with NEW_PLANNING permits only a user-started planning flow');
  app.job = { ...app.job }; delete app.job.productionFailure; app.renderJob();
  restoreInput = document.querySelector('[data-action="restore-approved-input"]');
  assert(restoreInput, 'legacy GM gate failure without structured productionFailure keeps its recovery entry');
  const postCountBeforeRestore = calls.filter(call => call.method === 'POST').length;
  app.projectId = 'other-project'; restoreInput.click(); assert.equal(document.querySelector('#concept').value, '', 'stale recovery action cannot cross into another selected project'); app.projectId = project.id;
  app.renderJob(); restoreInput = document.querySelector('[data-action="restore-approved-input"]');
  document.querySelector('#concept').value = '只有文字的新草稿'; restoreInput.click();
  assert.equal(document.querySelector('#concept').value, '只有文字的新草稿', 'concept-only edits block recovery before replacement');
  assert.deepEqual(app.assets, [], 'concept-only recovery conflict leaves references unchanged');
  document.querySelector('#concept').value = ''; app.assets = [{ id: 'asset-user-edit', name: '用户当前参考图', purpose: 'style' }]; restoreInput.click();
  assert.equal(document.querySelector('#concept').value, '', 'reference-only edits block recovery before concept replacement');
  assert.deepEqual(app.assets.map(asset => asset.id), ['asset-user-edit'], 'reference-only recovery conflict preserves the selected images');
  document.querySelector('#concept').value = '用户正在编辑的新概念'; app.assets = [{ id: 'asset-user-edit', name: '用户当前参考图', purpose: 'style' }]; app.renderAssets(); restoreInput.click();
  assert.equal(document.querySelector('#concept').value, '用户正在编辑的新概念', 'recovery action preserves a non-empty concept edit instead of overwriting it');
  assert.deepEqual(app.assets.map(asset => asset.id), ['asset-user-edit'], 'recovery action preserves a different non-empty reference set');
  assert(document.querySelector('#notice').textContent.includes('当前概念或参考图已有编辑，已保留'), 'edit conflict explains how to retry recovery safely');
  document.querySelector('#concept').value = ''; app.assets = []; app.renderAssets(); restoreInput.click();
  assert.equal(document.querySelector('#concept').value, '保留原来的玩家移动想法', 'recovery copies the user text from the approved packet into the editable concept');
  assert.deepEqual(app.assets.map(asset => asset.id), ['asset-project'], 'recovery restores only references owned by the current project');
  assert.equal(calls.filter(call => call.method === 'POST').length, postCountBeforeRestore, 'recovery does not automatically submit planning or production');

  app.job = { id: 'timeout-job', projectId: project.id, packetId: approvedPacket.id, status: 'FAILED', message: '旧失败记录：执行器异常退出', executionEvidence: [{ stderr: 'PRIVATE_STDERR_SECRET' }], response: { authorization: 'PRIVATE_RESPONSE_SECRET' }, command: ['PRIVATE_COMMAND_SECRET'], productionFailure: { code: 'PRODUCTION_TIMEOUT', message: '制作达到运行时限；期间模型连接中断并尝试重连，之后仍在执行。', nativeStatus: 'timeout', elapsedSeconds: 900, terminationConfirmed: true, effectsMayHaveOccurred: true, connectionInterrupted: true, nextAction: 'RECONCILE' } };
  app.renderJob();
  const failurePanelText = document.querySelector('#job-panel').textContent;
  assert(document.querySelector('#job-message').textContent.includes('制作达到运行时限'), 'structured failure is shown as the current diagnosis');
  assert(failurePanelText.includes('timeout') && failurePanelText.includes('900 秒（15 分钟）'), 'diagnostic shows native status and 900-second duration');
  assert(failurePanelText.includes('期间有连接中断记录') && !failurePanelText.includes('网络中断导致失败'), 'connection history is visible without being presented as the timeout cause');
  assert(failurePanelText.includes('制作停止已确认') && failurePanelText.includes('部分改动可能保留在隔离工程中'), 'diagnostic explains stop confirmation and possible partial effects');
  assert(failurePanelText.includes('旧失败记录：执行器异常退出'), 'legacy job message remains readable under the original-record disclosure');
  assert(!failurePanelText.includes('PRIVATE_STDERR_SECRET') && !failurePanelText.includes('PRIVATE_RESPONSE_SECRET') && !failurePanelText.includes('PRIVATE_COMMAND_SECRET'), 'raw evidence, response fields, and commands are never rendered');
  assert(!document.querySelector('[data-action="restore-approved-input"]'), 'production failures requiring reconciliation cannot restore inputs into a new plan');
  app.job = { ...app.job, id: 'missing-stop-job', status: 'FAILED', productionFailure: { code: 'PRODUCTION_TIMEOUT', message: '制作结束状态待核实。', nextAction: 'NEW_PLANNING' } }; app.renderJob();
  assert(!document.querySelector('[data-action="restore-approved-input"]'), 'production failure with missing stop confirmation cannot start a new plan');
  assert(document.querySelector('#job-panel').textContent.includes('向服务对账'), 'missing stop confirmation overrides NEW_PLANNING with reconciliation');
  assert(!document.querySelector('#reconcile-area').classList.contains('hidden'), 'missing stop confirmation exposes the existing reconcile action');
  const postCountBeforeUncertain = calls.filter(call => call.method === 'POST').length;
  app.job = { ...app.job, id: 'uncertain-job', status: 'UNCERTAIN', productionFailure: { ...app.job.productionFailure, terminationConfirmed: false } }; app.renderJob();
  assert(document.querySelector('#reconcile-area').classList.contains('hidden') === false, 'uncertain execution exposes its reconcile control');
  assert(!document.querySelector('[data-action="restore-approved-input"]'), 'UNCERTAIN never offers approved-input recovery');
  assert.equal(calls.filter(call => call.method === 'POST').length, postCountBeforeUncertain, 'rendering FAILED or UNCERTAIN diagnostics does not start an action');

  const reviewJob = status => ({ id: 'first-demo-job', projectId: project.id, status, candidate: { candidateCommit: 'git-candidate-1', summary: '首个 Demo 候选' }, message: '候选决定已记录' });
  app.stage = 'initial'; app.workspace.iterationReady = false;
  app.proposal = { id: 'frozen-first-demo', projectId: project.id, status: 'FROZEN' }; app.packet = { id: 'first-packet', proposalId: app.proposal.id, projectId: project.id };
  app.job = reviewJob('READY_FOR_REVIEW'); app.renderJob();
  routes.set(`POST /api/projects/${project.id}/jobs/first-demo-job/decision`, response({ job: reviewJob('REJECTED') }));
  await app.decideCandidate('reject', 'git-candidate-1');
  assert.equal(app.proposal, null, 'rejecting the first Demo releases the frozen proposal form for revision');
  assert(!document.querySelector('#concept-form').closest('.panel').classList.contains('hidden'), 'first Demo rejection returns to the initial concept form');
  assert(document.querySelector('#job-panel').textContent.includes('候选决定已记录'), 'rejected job diagnosis and history remain visible');
  assert(document.querySelector('#workflow-status-copy').textContent.includes('修改初始想法并重新策划'), 'initial rejection status points to the correct next action');
  routes.set(`POST /api/projects/${project.id}/concepts`, response({ proposal: { id: 'proposal-after-rejection', projectId: project.id, revision: 1, publicationRevision: 0, workflow: 'objects-v1', status: 'PLANNING', text: '调整后的初始概念' } }));
  document.querySelector('#concept').value = '调整后的初始概念'; await app.submitConcept();
  assert.equal(app.job.status, 'REJECTED', 'starting a revised plan preserves the rejected job history');
  assert(document.querySelector('#workflow-status-copy').textContent.includes('AI 策划'), 'a new active planning session takes priority over stale terminal job status');
  app.job.status = 'BLOCKED'; app.renderWorkflowStatus();
  assert(document.querySelector('#workflow-status-copy').textContent.includes('AI 策划'), 'a historical blocked job cannot mask a new planning session');

  app.workspace.iterationReady = true; app.snapshot = { ...baseline, publicationRevision: 1, playable: true }; app.stage = 'iteration';
  app.job = { ...reviewJob('READY_FOR_REVIEW'), id: 'iteration-job' }; app.proposal = { id: 'iteration-frozen', projectId: project.id, status: 'FROZEN' }; app.packet = { id: 'iteration-packet', proposalId: app.proposal.id, projectId: project.id };
  routes.set(`POST /api/projects/${project.id}/jobs/iteration-job/decision`, response({ job: { ...app.job, status: 'REJECTED' } }));
  await app.decideCandidate('reject', 'git-candidate-1');
  assert.equal(app.stage, 'iteration', 'rejecting an iteration candidate stays in iteration');
  assert(app.canEnterIteration() && !document.querySelector('#workbench-panel').classList.contains('hidden'), 'iteration baseline remains available after rejecting an iteration candidate');
  assert(document.querySelector('#concept-form').closest('.panel').classList.contains('hidden'), 'iteration rejection does not return to initial concept entry');

  app.destroy(); dom.window.close(); if (savedDocument) global.document = savedDocument;
  console.log('PASS Studio planner regression QA: typed choices, safe recovery, retry preservation and idempotence, uncertain outcome reconciliation, and complete READY plan');
})().catch(error => { console.error(error.stack || error); process.exitCode = 1; });
