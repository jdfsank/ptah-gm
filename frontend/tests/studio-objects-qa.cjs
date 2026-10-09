#!/usr/bin/env node
/* Object editing and safe planner diagnostics in the project-scoped Studio. */
const fs = require('node:fs');
const path = require('node:path');
const strict = require('node:assert/strict');
const { pathToFileURL } = require('node:url');
let JSDOM;
try { ({ JSDOM } = require('jsdom')); } catch { console.log('SKIP studio object QA: jsdom is unavailable.'); process.exit(0); }
const root = path.resolve(__dirname, '..');
const dom = new JSDOM(fs.readFileSync(path.join(root, 'studio/index.html'), 'utf8'), { url: 'http://127.0.0.1:8123/studio/', pretendToBeVisual: true });
const savedDocument = global.document; delete global.document;
global.FormData = dom.window.FormData; global.HTMLElement = dom.window.HTMLElement;
const calls = []; const timers = new Map(); let timerId = 0;
const capabilities = { interactiveFrontendConfirmation: true, sessionDispatch: true, godotVerification: true, semanticProjection: true };
const project = { id: 'game-1', title: '对象协议演示', workflow: 'objects-v1', publicationRevision: 7 };
const snapshot = { projectId: 'game-1', workflow: 'objects-v1', publicationRevision: 7, sourceCommit: 'git-base-7', kind: 'MVP', playable: true, title: '对象协议演示', summary: '对象工作区', catalog: { objects: [
  { id: 'player', kind: 'entity', name: '玩家', description: '可控角色', relations: [{ type: 'belongs_to', targetId: 'main' }], sourceBindings: ['scripts/player.gd'], fields: [{ id: 'speed', label: '速度', type: 'number', value: 220 }] },
  { id: 'main', kind: 'scene', name: '主场景', relations: [], sourceBindings: ['scenes/main.tscn'], fields: [] },
] } };
const fieldCapabilities = { fields: [
  { id: 'player.speed', objectId: 'player', fieldId: 'speed', label: '速度', type: 'scalar', value: 220, editable: true, min: 0, max: 500 },
  { id: 'player.spawn', objectId: 'player', fieldId: 'spawn', label: '出生点', type: 'vector2', value: [0, 0], editable: true },
  { id: 'player.seed', objectId: 'player', fieldId: 'seed', label: '内部种子', type: 'integer', value: 3, editable: false, supported: true },
] };
const workspace = { storeId: 'store-a', workspaceId: 'workspace-a', projects: [project], jobs: [], proposals: [], packets: [], capabilities, iterationReady: true, testData: false };
const response = (data, status = 200) => ({ ok: status >= 200 && status < 300, status, text: async () => JSON.stringify(data) });
const routes = new Map([
  ['GET /api/session', { token: 'qa-token' }], ['GET /api/workspace', { ...workspace, jobs: undefined, proposals: undefined, packets: undefined }],
  ['GET /api/projects/game-1/workspace', workspace], ['GET /api/projects/game-1/workbench', { snapshot, capabilities: fieldCapabilities, candidates: [], iterationReady: true }],
  ['POST /api/projects/game-1/concepts', ({ body }) => ({ proposal: { id: 'proposal-iteration', projectId: 'game-1', revision: 1, workflow: 'objects-v1', status: 'PLANNING', text: body.text, changeRequest: body.changeRequest } })],
]);
const fetchImpl = async (url, init = {}) => {
  const key = `${init.method || 'GET'} ${new URL(url, 'http://127.0.0.1:8123').pathname}`; const body = init.body ? JSON.parse(init.body) : undefined; calls.push({ key, body });
  if (init.headers?.['X-Workbench-Token'] !== (init.method ? 'qa-token' : undefined) && init.headers?.['X-Workbench-Token']) return response({ error: 'bad token' }, 403);
  const route = routes.get(key); if (!route) return response({ error: `missing route ${key}` }, 404);
  return response(typeof route === 'function' ? route({ body, init }) : route);
};
const assert = Object.assign((condition, message) => strict.ok(condition, message), { equal: strict.equal, deepEqual: strict.deepEqual });

(async () => {
  const { StudioApp } = await import(pathToFileURL(path.join(root, 'studio/studio.js')).href); global.document = dom.window.document;
  const fakeTimers = { setInterval(fn) { const id = ++timerId; timers.set(id, fn); return id; }, clearInterval(id) { timers.delete(id); }, setTimeout, clearTimeout };
  const app = new StudioApp({ fetchImpl, documentImpl: dom.window.document, timers: fakeTimers });
  const draftReads = [], storedDrafts = new Map([['workspace-a:game-1:7', { projectId: 'game-1', publicationRevision: 7, fields: { 'player.speed': 111 } }]]);
  app.drafts = { open: async () => ({}), get: async key => { draftReads.push(key); return storedDrafts.get(key) || null; }, put: async item => { storedDrafts.set(item.key, item); return item; }, delete: async key => storedDrafts.delete(key) };
  app.bind(); await app.start(); await app.openProject('game-1');
  app.enterIterationStage();
  assert(document.querySelector('#workbench-title').textContent === '迭代工作台', 'object editor opens only after the server-provided iteration gate');
  assert(document.querySelector('#object-detail').textContent.includes('scripts/player.gd'), 'object detail exposes project source bindings');
  assert(document.querySelector('#object-detail').textContent.includes('belongs_to → main'), 'object detail exposes relationships');
  const readonly = document.querySelector('#dynamic-fields [data-field-id="player.seed"]');
  assert(readonly?.disabled, 'supported metadata cannot override explicit read-only capability');
  assert(app.draftKey.includes('store-a:game-1:iteration:7'), 'iteration drafts use stable store identity, project and publication revision');
  assert(!draftReads.includes('workspace-a:game-1:7'), 'legacy workspace-scoped drafts are never read or silently reassociated');
  assert.equal(document.querySelector('#dynamic-fields [data-field-id="player.speed"]').value, '220', 'untrusted legacy content cannot override the current project baseline');
  const speed = document.querySelector('#dynamic-fields [data-field-id="player.speed"]'); speed.value = '340'; speed.dispatchEvent(new dom.window.Event('input', { bubbles: true }));
  const spawnX = document.querySelector('#dynamic-fields [data-field-id="player.spawn"][data-axis="x"]'); const spawnY = document.querySelector('#dynamic-fields [data-field-id="player.spawn"][data-axis="y"]');
  spawnX.value = '12'; spawnY.value = '-4'; spawnY.dispatchEvent(new dom.window.Event('input', { bubbles: true }));
  document.querySelector('#edit-text').value = '让玩家移动更灵敏';
  document.querySelector('#feedback-message').value = '转向时有明显延迟'; document.querySelector('#feedback-category').value = 'behavior'; document.querySelector('#add-feedback').click();
  await app.submitIteration();
  const changeCall = calls.find(call => call.key === 'POST /api/projects/game-1/concepts');
  assert(changeCall, 'iteration request uses the project-scoped endpoint');
  assert.equal(changeCall.body.workflow, undefined, 'workflow remains project-owned');
  assert.equal(changeCall.body.text, '让玩家移动更灵敏', 'natural language remains separate from structured field edits');
  assert.deepEqual(changeCall.body.changeRequest.fields, [{ objectId: 'player', fieldId: 'speed', value: 340 }, { objectId: 'player', fieldId: 'spawn', value: [12, -4] }], 'vector values use the existing object protocol');
  assert.deepEqual(changeCall.body.changeRequest.feedback, [{ objectId: 'player', message: '转向时有明显延迟', category: 'behavior' }]);
  assert.deepEqual(changeCall.body.changeRequest.targetObjectIds, ['player']);
  assert.equal(changeCall.body.changeRequest.baseRevision, 7); assert.equal(changeCall.body.changeRequest.sourceCommit, 'git-base-7');
  assert(document.querySelector('#workflow-status-copy').textContent.includes('AI 策划'), 'iteration planning state is shown in the persistent header');

  app.proposal = null;
  const dirtyDraft = app.readVisibleDraft(); dirtyDraft.fields['player.speed'] = 340; const oldSnapshot = app.snapshot;
  const nextSnapshot = { ...snapshot, publicationRevision: 8, sourceCommit: 'git-base-8', summary: '新发布版本' };
  app.persistenceOK = false; app.snapshot = nextSnapshot; app.handleRebase(oldSnapshot, nextSnapshot, dirtyDraft);
  const requestsBeforeRebaseGate = calls.filter(call => call.key === 'POST /api/projects/game-1/concepts').length;
  await app.submitIteration();
  assert.equal(calls.filter(call => call.key === 'POST /api/projects/game-1/concepts').length, requestsBeforeRebaseGate, 'an unreviewed old draft cannot be submitted against a new publication revision');
  assert(document.querySelector('#rebase-content').textContent.includes('player.speed'), 'rebase preview identifies a retained object field');
  await app.confirmRebase();
  assert.equal(document.querySelector('#dynamic-fields [data-field-id="player.speed"]').value, '340', 'explicit rebase keeps the reviewed dirty field value');
  assert.equal(app.buildChangeRequest().baseRevision, 8, 'rebased changes bind to the new publication revision');
  assert(!app.buildChangeRequest().fields.some(field => field.fieldId === 'seed'), 'a retained read-only field is never sent in the next change request');

  const failure = { id: 'proposal-failed', projectId: 'game-1', revision: 2, workflow: 'objects-v1', status: 'FAILED', text: '用户概念', planningFailure: { code: 'PLANNER_TIMEOUT', message: 'raw stderr /private/image.png', retryable: false, nativeStatus: 'timeout', elapsedSeconds: 19, sessionId: 'native-session-1', terminationConfirmed: true } };
  app.proposal = failure; app.renderProposal();
  const diagnostic = document.querySelector('#proposal-content').textContent;
  assert(diagnostic.includes('策划 session 等待超时') && diagnostic.includes('19 秒') && diagnostic.includes('native-session-1'), 'safe native planner diagnostics remain visible');
  assert(!diagnostic.includes('raw stderr') && !diagnostic.includes('/private/image.png'), 'raw local paths and stderr remain hidden');
  app.destroy(); dom.window.close();
  console.log('PASS Studio object QA: scoped object iteration protocol, read-only fields, source mappings, feedback, and safe planner diagnostics');
})().catch(error => { console.error(error.stack || error); process.exitCode = 1; });
