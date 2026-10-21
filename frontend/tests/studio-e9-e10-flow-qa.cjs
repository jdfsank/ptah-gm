#!/usr/bin/env node
/* Accepted iteration receipts clear only the submitted snapshot; rebases retain the latest old-version draft. */
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const { pathToFileURL } = require('node:url');
const { JSDOM } = require('jsdom');

const root = path.resolve(__dirname, '..');
const response = value => ({ ok: true, status: 200, text: async () => JSON.stringify(value) });
const deferred = () => { let resolve; const promise = new Promise(done => { resolve = done; }); return { promise, resolve }; };
const tick = () => new Promise(resolve => setTimeout(resolve, 0));

(async () => {
  const { StudioApp } = await import(pathToFileURL(path.join(root, 'studio/studio.js')).href);

  // E9: an in-flight load keeps the previous publication visible while it reads;
  // draft changes made during that wait must enter the normal explicit rebase.
  const e9Dom = new JSDOM(fs.readFileSync(path.join(root, 'studio/index.html'), 'utf8'), {
    url: 'http://127.0.0.1:8123/studio/?project=e9-game&stage=iteration&target=player', pretendToBeVisual: true,
  });
  global.document = e9Dom.window.document; global.Option = e9Dom.window.Option;
  global.localStorage = e9Dom.window.localStorage; global.location = e9Dom.window.location; global.history = e9Dom.window.history;
  const e9Project = { id: 'e9-game', title: 'E9 旧来源重关联', workflow: 'objects-v1' };
  const arena = { id: 'arena', kind: 'scene', name: '竞技场', fields: [], workbench: { role: 'scene', bounds: [800, 600] } };
  const player = { id: 'player', kind: 'entity', name: '玩家', fields: [{ id: 'speed', value: 220 }] };
  const oldSnapshot = { projectId: e9Project.id, publicationRevision: 7, sourceCommit: 'git-e9-old', kind: 'MVP', playable: true, workflow: 'objects-v1', catalog: { objects: [arena, player] }, document: { objects: [arena, player] } };
  const newSnapshot = { ...oldSnapshot, publicationRevision: 8, sourceCommit: 'git-e9-new' };
  const loadStarted = deferred(), finishLoad = deferred();
  const e9App = new StudioApp({ documentImpl: e9Dom.window.document, timers: globalThis, fetchImpl: async url => {
    const pathname = new URL(url, 'http://127.0.0.1:8123').pathname;
    if (pathname === `/api/projects/${e9Project.id}/workbench`) { loadStarted.resolve(); return finishLoad.promise; }
    return { ok: false, status: 404, text: async () => JSON.stringify({ error: `unexpected ${pathname}` }) };
  } });
  e9App.manager = { storeId: 'e9-store', projects: [e9Project] };
  e9App.workspace = { storeId: 'e9-store', projects: [e9Project], iterationReady: true };
  e9App.projectId = e9Project.id; e9App.stage = 'iteration'; e9App.workflow = 'objects-v1';
  e9App.snapshot = oldSnapshot; e9App.capabilities = { fields: [] }; e9App.selectedObjectId = 'player';
  e9App.targetNotes = { player: { objectId: 'player', text: '旧版本已有意见。', feedbackId: 'e9-note' } };
  e9App.structuralProposals = [{ operationId: 'e9-op-old', kind: 'delete-instance', objectId: 'old-object', scope: '旧场景' }];
  e9App.draftKey = 'e9-store:e9-game:iteration:7'; e9App.persistenceOK = false;
  e9App.bind(); e9App.renderWorkbench(); e9App.legacyWorkbench.loadCurrentNote();
  const loadingE9 = e9App.loadWorkbench(e9Project.id);
  await loadStarted.promise;
  const editor = e9Dom.window.document.querySelector('#edit-text');
  editor.value = '刷新期间新增的意见。'; editor.dispatchEvent(new e9Dom.window.Event('input', { bubbles: true }));
  e9App.structuralProposals = [...e9App.structuralProposals, { operationId: 'e9-op-new', kind: 'new-scene', name: '刷新期间新增场景' }];
  finishLoad.resolve(response({ projectId: e9Project.id, snapshot: newSnapshot, capabilities: { fields: [] }, candidates: [], iterationReady: true }));
  await loadingE9;
  assert.equal(e9App.snapshot.sourceCommit, 'git-e9-new', 'loadWorkbench installs the newly published source snapshot');
  assert.equal(e9App.pendingRebase.oldSnapshot.sourceCommit, 'git-e9-old', 'the existing rebase keeps the old source identity');
  assert.equal(e9App.pendingRebase.nextSnapshot.sourceCommit, 'git-e9-new');
  assert.equal(e9App.pendingRebase.draft.targetNotes.player.text, '刷新期间新增的意见。', 'the rebase captures note edits made while the source refresh was in flight');
  assert.deepEqual(e9App.pendingRebase.draft.structuralProposals.map(item => item.operationId), ['e9-op-old', 'e9-op-new'], 'the rebase captures old and newly added structural proposals');
  assert.match(e9Dom.window.document.querySelector('#rebase-content').textContent, /刷新期间新增的意见/);
  assert.match(e9Dom.window.document.querySelector('#rebase-content').textContent, /刷新期间新增场景/);
  e9App.destroy(); e9Dom.window.close();

  // E10: only state still equal to the accepted command snapshot is cleared.
  const e10Dom = new JSDOM(fs.readFileSync(path.join(root, 'studio/index.html'), 'utf8'), {
    url: 'http://127.0.0.1:8123/studio/?project=e10-game&stage=iteration&target=player', pretendToBeVisual: true,
  });
  global.document = e10Dom.window.document; global.Option = e10Dom.window.Option;
  global.localStorage = e10Dom.window.localStorage; global.location = e10Dom.window.location; global.history = e10Dom.window.history;
  const e10Project = { id: 'e10-game', title: 'E10 回执快照', workflow: 'objects-v1', protocolVersion: 1 };
  const e10Arena = { id: 'arena', kind: 'scene', name: '竞技场', fields: [], workbench: { role: 'scene', bounds: [800, 600] } };
  const e10Player = { id: 'player', kind: 'entity', name: '玩家', fields: [{ id: 'speed', value: 220 }, { id: 'health', value: 10 }] };
  const dice = { id: 'dice', kind: 'entity', name: '骰子', fields: [], workbench: { role: 'instance', sceneId: 'arena' } };
  const frozenChangeRequest = {
    baseRevision: 7, sourceCommit: 'git-e10-base', targetObjectIds: ['player', 'dice'],
    fields: [{ objectId: 'player', fieldId: 'speed', value: 250 }, { objectId: 'player', fieldId: 'health', value: 25 }],
    feedback: [
      { feedbackId: 'e10-explicit-unchanged', objectId: 'player', message: '提交时的对象反馈。', category: 'general' },
      { feedbackId: 'e10-explicit-edited', objectId: 'player', message: '提交时的另一条反馈。', category: 'general' },
      { feedbackId: 'e10-player-note', objectId: 'player', message: '提交时的玩家意见。', category: 'general' },
      { feedbackId: 'e10-dice-note', objectId: 'dice', message: '提交时的骰子意见。', category: 'general' },
    ],
    operations: [{ operationId: 'e10-op-remove-dice', kind: 'delete-instance', objectId: 'dice', scope: '提交时的场景' }],
  };
  const commandStarted = deferred(), finishCommand = deferred();
  let submittedEnvelope = null;
  const e10App = new StudioApp({ documentImpl: e10Dom.window.document, timers: globalThis, fetchImpl: async (url, init = {}) => {
    if (new URL(url, 'http://127.0.0.1:8123').pathname === `/api/v1/projects/${e10Project.id}/commands` && init.method === 'POST') {
      submittedEnvelope = JSON.parse(init.body); commandStarted.resolve(); return finishCommand.promise;
    }
    return { ok: false, status: 404, text: async () => JSON.stringify({ error: `unexpected ${url}` }) };
  } });
  e10App.protocolVersion = 1;
  e10App.handshake = { storeId: 'e10-store', serviceInstanceId: 'e10-service', writeToken: 'e10-token', capabilities: [] };
  e10App.token = 'e10-token'; e10App.manager = { storeId: 'e10-store', projects: [e10Project] };
  e10App.workspace = { storeId: 'e10-store', projects: [e10Project], iterationReady: true };
  e10App.projectId = e10Project.id; e10App.stage = 'iteration'; e10App.workflow = 'objects-v1'; e10App.selectedObjectId = 'player';
  e10App.snapshot = { projectId: e10Project.id, publicationRevision: 7, sourceCommit: 'git-e10-base', kind: 'MVP', playable: true, workflow: 'objects-v1', catalog: { objects: [e10Arena, e10Player, dice] }, document: { objects: [e10Arena, e10Player, dice] } };
  e10App.capabilities = { fields: [
    { id: 'player.speed', objectId: 'player', fieldId: 'speed', value: 220, type: 'number', editable: true, min: 0, max: 500 },
    { id: 'player.health', objectId: 'player', fieldId: 'health', value: 10, type: 'number', editable: true, min: 0, max: 100 },
  ] };
  e10App.projectView = { projectId: e10Project.id, allowedActions: ['iteration.submit'] };
  e10App.sessionPreferences = { revision: 0 }; e10App.readiness = { ready: true };
  e10App.persistenceOK = true; e10App.draftKey = 'e10-store:e10-game:iteration:7';
  e10App.dirtyFields = new Set(); e10App.fieldDraftValues = { 'player.speed': 250, 'player.health': 25 };
  e10App.targetNotes = {
    player: { objectId: 'player', text: '提交时的玩家意见。', feedbackId: 'e10-player-note' },
    dice: { objectId: 'dice', text: '提交时的骰子意见。', feedbackId: 'e10-dice-note' },
  };
  e10App.feedback = [
    { feedbackId: 'e10-explicit-unchanged', objectId: 'player', message: '提交时的对象反馈。', category: 'general' },
    { feedbackId: 'e10-explicit-edited', objectId: 'player', message: '提交时的另一条反馈。', category: 'general' },
  ];
  e10App.structuralProposals = [{ operationId: 'e10-op-remove-dice', kind: 'delete-instance', objectId: 'dice', scope: '提交时的场景' }];
  const writes = [];
  e10App.drafts = { put: async value => { writes.push(structuredClone(value)); return value; } };
  const preservedResults = [{ kind: 'operation', operationId: 'earlier-result', workflowStatus: 'PUBLISHED' }];
  e10App.workbenchResults = preservedResults;
  e10App.bind(); e10App.renderWorkbench(); e10App.legacyWorkbench.loadCurrentNote();
  const speed = e10Dom.window.document.querySelector('[data-field-id="player.speed"]');
  assert(speed, 'E10 player speed control is rendered for the selected player object');
  const health = e10Dom.window.document.querySelector('[data-field-id="player.health"]');
  assert(health, 'E10 player health control is rendered for the selected player object');
  speed.value = '250'; speed.dispatchEvent(new e10Dom.window.Event('input', { bubbles: true }));
  const submitting = e10App.submitIteration();
  await commandStarted.promise;
  assert.equal(submittedEnvelope.type, 'iteration.submit');
  assert.deepEqual(submittedEnvelope.payload.fields, frozenChangeRequest.fields);
  assert.deepEqual(submittedEnvelope.payload.operations, frozenChangeRequest.operations);
  assert.deepEqual(submittedEnvelope.payload.feedback, frozenChangeRequest.feedback);

  speed.value = '280'; speed.dispatchEvent(new e10Dom.window.Event('input', { bubbles: true }));
  const editorE10 = e10Dom.window.document.querySelector('#edit-text');
  editorE10.value = '请求期间新写的玩家意见。'; editorE10.dispatchEvent(new e10Dom.window.Event('input', { bubbles: true }));
  e10App.feedback[1].message = '请求期间改写的反馈。';
  e10App.feedback.push({ feedbackId: 'e10-explicit-added', objectId: 'dice', message: '请求期间新增的反馈。', category: 'general' });
  e10App.structuralProposals = [
    { ...e10App.structuralProposals[0], scope: '请求期间改写的场景' },
    { operationId: 'e10-op-new-scene', kind: 'new-scene', name: '请求期间新增的场景' },
  ];
  const acceptedProposal = { id: 'e10-proposal', projectId: e10Project.id, revision: 1, publicationRevision: 7, status: 'PLANNING', workflow: 'objects-v1', changeRequest: structuredClone(frozenChangeRequest) };
  finishCommand.resolve(response({
    schemaVersion: 'studio.message.v1', kind: 'receipt', type: submittedEnvelope.type, storeId: 'e10-store', projectId: e10Project.id,
    commandId: submittedEnvelope.commandId, status: 'accepted', resource: { kind: 'proposal', id: acceptedProposal.id }, result: { proposal: acceptedProposal },
  }));
  await submitting;

  assert.equal(e10App.proposal.id, 'e10-proposal');
  assert.deepEqual(e10App.proposal.changeRequest, frozenChangeRequest, 'the accepted proposal keeps the exact submitted change record');
  assert.equal(e10App.fieldDraftValues['player.speed'], 280, 'a field edited during the request remains in the next draft');
  assert.equal(e10App.fieldDraftValues['player.health'], undefined, 'an unchanged submitted field is cleared from the next draft');
  assert.equal(health.value, '10', 'the visible control returns to the published value after acknowledgement');
  assert.equal(e10App.targetNotes.player.text, '请求期间新写的玩家意见。', 'a note edited during the request remains in the next draft');
  assert.equal(e10App.targetNotes.dice, undefined, 'an unchanged submitted note is cleared from the next draft');
  assert.deepEqual(e10App.feedback, [
    { feedbackId: 'e10-explicit-edited', objectId: 'player', message: '请求期间改写的反馈。', category: 'general' },
    { feedbackId: 'e10-explicit-added', objectId: 'dice', message: '请求期间新增的反馈。', category: 'general' },
  ], 'only explicit feedback entries still matching the accepted feedbackId and content are cleared');
  assert.deepEqual(e10App.structuralProposals.map(item => item.operationId), ['e10-op-remove-dice', 'e10-op-new-scene'], 'an edited operation and a new operation survive acknowledgement');
  assert.equal(e10App.structuralProposals[0].scope, '请求期间改写的场景');
  assert.equal(e10App.workbenchResults, preservedResults, 'receipt handling does not create or overwrite a task library');
  assert.ok(writes.length); assert.equal(writes.at(-1).fields['player.speed'], 280); assert.equal(writes.at(-1).fields['player.health'], undefined);
  assert.equal(writes.at(-1).targetNotes.dice, undefined, 'the post-receipt saved draft excludes acknowledged unchanged notes');
  assert.deepEqual(writes.at(-1).feedback, e10App.feedback, 'post-receipt draft saves the edited and added explicit feedback');
  assert.deepEqual(writes.at(-1).structuralProposals.map(item => item.operationId), ['e10-op-remove-dice', 'e10-op-new-scene']);
  e10App.destroy(); e10Dom.window.close();
  console.log('PASS Studio E9/E10 QA: delayed publication refresh rebases the latest notes/operations; accepted receipt clears only unchanged submitted draft state');
})().catch(error => { console.error(error.stack || error); process.exitCode = 1; });
