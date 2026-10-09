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
  console.log(JSON.stringify({ status: 'PASS', checks: ['object catalog and relationships', 'typed dynamic fields', 'separate natural language/changeRequest', 'only changed fields', 'object feedback', 'choice clarification control', 'complete READY object plan', 'independent proposal polling', 'draft field and feedback retention'] }, null, 2));
})().catch(error => { dom.window.close(); console.error(error); process.exitCode = 1; });
