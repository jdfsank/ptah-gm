#!/usr/bin/env node
/* Focused QA for local grid-alignment previews and minimal-scene template markers. */
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const { pathToFileURL } = require('node:url');
let JSDOM;
try { ({ JSDOM } = require('jsdom')); }
catch { console.log('SKIP Studio local-layout proposal QA: jsdom is unavailable.'); process.exit(0); }

const root = path.resolve(__dirname, '..');
const dom = new JSDOM(fs.readFileSync(path.join(root, 'studio/index.html'), 'utf8'), {
  url: 'http://127.0.0.1:8123/studio/?project=layout-proposal', pretendToBeVisual: true,
});
global.document = dom.window.document;
global.localStorage = dom.window.localStorage;
global.Option = dom.window.Option;
global.location = dom.window.location;
global.history = dom.window.history;

(async () => {
  const { LegacyWorkbench } = await import(pathToFileURL(path.join(root, 'studio/workbench.js')).href);
  const objects = [
    { id: 'scene-a', kind: 'scene', name: '大厅', fields: [], relations: [], workbench: { role: 'scene', bounds: [400, 300] } },
    { id: 'free-guard', kind: 'entity', name: '自由守卫', fields: [], relations: [], workbench: { role: 'instance', sceneId: 'scene-a', position: [89, 89], size: [20, 20], anchor: [0.5, 0.5], lock: 'free' } },
    { id: 'nudge-guard', kind: 'entity', name: '微调守卫', fields: [], relations: [], workbench: { role: 'instance', sceneId: 'scene-a', position: [110, 110], size: [20, 20], anchor: [0.5, 0.5], lock: 'nudge', nudgeStep: 10 } },
    { id: 'fixed-guard', kind: 'entity', name: '固定守卫', fields: [], relations: [], workbench: { role: 'instance', sceneId: 'scene-a', position: [160, 160], size: [20, 20], anchor: [0.5, 0.5], lock: 'fixed' } },
    { id: 'edge-guard', kind: 'entity', name: '边界守卫', fields: [], relations: [], workbench: { role: 'instance', sceneId: 'scene-a', position: [390, 290], size: [20, 20], anchor: [0.5, 0.5], lock: 'free' } },
  ];
  let serial = 0;
  let wb = null;
  const notifications = [];
  const app = {
    projectId: 'layout-proposal', selectedObjectId: 'free-guard', fieldDraftValues: {}, targetNotes: {}, structuralProposals: [],
    snapshot: { projectId: 'layout-proposal', publicationRevision: 3, sourceCommit: 'git-layout-base' },
    objectItems: () => objects,
    selectObject: objectId => { app.selectedObjectId = objectId; wb?.renderCanvas(); },
    newFeedbackId: () => `operation-${++serial}`,
    queueDraftSave: () => {}, notify: message => notifications.push(message),
    readVisibleDraft: () => ({ fields: {}, feedback: [], feedbackMessage: '', feedbackCategory: 'general' }),
    applyVisibleDraft: state => {
      app.selectedObjectId = state.selectedObjectId || null;
      app.structuralProposals = structuredClone(state.structuralProposals || []);
      app.targetNotes = structuredClone(state.targetNotes || {});
    },
  };
  wb = new LegacyWorkbench(app);
  wb.sceneCanvasSelection = 'scene-a'; wb.activeSceneId = 'scene-a';
  wb.bind(); wb.resetHistory();
  wb.render = () => wb.renderCanvas();
  wb.renderCanvas();
  const inputFor = id => document.querySelector(`.workbench-layout-target input[data-object-id="${id}"]`);
  const select = id => {
    const input = inputFor(id);
    assert(input, `layout-selection control exists for ${id}`);
    assert(!input.disabled, `${id} is selectable for a layout preview`);
    const selectedBeforeClick = app.selectedObjectId;
    input.click();
    const afterClick = inputFor(id);
    assert.equal(afterClick?.checked, true, `a real checkbox click keeps ${id} checked after delegated handlers run`);
    assert(wb.layoutSelectionByScene.get('scene-a')?.includes(id), `a real checkbox click records ${id} in the selected layout set`);
    assert.equal(app.selectedObjectId, selectedBeforeClick, `selecting ${id} for layout does not navigate to that object`);
  };
  const click = selector => {
    const control = document.querySelector(selector);
    assert(control, `control exists: ${selector}`);
    control.click();
    return control;
  };

  assert(inputFor('fixed-guard')?.disabled, 'fixed instances are shown as read-only and cannot be selected');
  select('free-guard'); select('nudge-guard'); select('edge-guard');
  click('[data-workbench-action="preview-layout-proposal"]');
  let proposal = wb.localLayoutProposal;
  assert.equal(proposal.changes.length, 2, 'only the explicitly selected valid free and nudge instances enter the proposal');
  assert.equal(proposal.skipped, 1, 'the selected move that would cross the scene boundary is skipped');
  assert.deepEqual(proposal.changes.map(change => [change.objectId, change.requested]), [
    ['free-guard', [80, 80]], ['nudge-guard', [100, 100]],
  ], 'free instances snap to the selected grid while nudge instances move by only their declared step');
  assert.equal(document.querySelectorAll('.workbench-local-layout-marker').length, 2, 'the proposal preview marks both proposed locations on the canvas');

  click('[data-workbench-action="cancel-layout-proposal"]');
  assert.equal(wb.localLayoutProposal, null, 'cancel clears the preview without creating draft operations');
  assert.equal(app.structuralProposals.length, 0, 'cancel leaves the operation draft untouched');

  click('[data-workbench-action="preview-layout-proposal"]');
  app.structuralProposals.push({ operationId: 'external-edit', kind: 'feedback', text: 'new draft input' });
  const staleOperationCount = app.structuralProposals.length;
  assert.equal(wb.applyLocalLayoutProposal(), false, 'a preview generated against an older draft is rejected');
  assert.equal(app.structuralProposals.length, staleOperationCount, 'stale rejection changes no operation');
  assert.match(notifications.at(-1), /已过期/);
  app.structuralProposals = [];
  wb.localLayoutProposal = null;
  wb.resetHistory();
  wb.renderCanvas();
  click('[data-workbench-action="preview-layout-proposal"]');
  const historyBeforeApply = wb.history.length;
  click('[data-workbench-action="apply-layout-proposal"]');
  assert.equal(app.structuralProposals.filter(item => item.kind === 'move').length, 2, 'apply adds move proposals for the selected instances only');
  assert(!app.structuralProposals.some(item => item.objectId === 'fixed-guard' || item.objectId === 'edge-guard'), 'apply excludes fixed and out-of-bounds instances');
  assert.equal(wb.history.length, historyBeforeApply + 1, 'the whole batch is exactly one undo step');
  await wb.undo();
  assert.equal(app.structuralProposals.length, 0, 'one undo removes the complete applied batch');
  await wb.redo();
  assert.equal(app.structuralProposals.filter(item => item.kind === 'move').length, 2, 'one redo restores the complete batch');

  app.structuralProposals = [];
  wb.resetHistory();
  const lockControlRoot = document.createElement('div'); document.querySelector('#object-catalog').append(lockControlRoot);
  wb.renderPositionControls(lockControlRoot, wb.object('free-guard'));
  const requestedLock = lockControlRoot.querySelector('[name="requestedLock"]');
  assert(requestedLock, 'existing instances expose a requested edit-constraint selector');
  requestedLock.value = 'nudge';
  lockControlRoot.querySelector('[data-workbench-action="set-instance-lock"]').click();
  let lockOperation = app.structuralProposals.find(item => item.kind === 'set-lock' && item.objectId === 'free-guard');
  assert.deepEqual({ before: lockOperation.before, lock: lockOperation.lock, scope: lockOperation.scope }, { before: 'free', lock: 'nudge', scope: '用户显式修改约束' }, 'a lock change records the exact published baseline and explicit scope');
  assert.equal(wb.effectiveLock(wb.object('free-guard')), 'nudge', 'the proposed lock becomes the effective local editing constraint');
  wb.proposeMove(wb.object('free-guard'), [100, 100]);
  let moveOperation = app.structuralProposals.find(item => item.kind === 'move' && item.objectId === 'free-guard');
  assert.equal(moveOperation.lock, 'nudge', 'a move paired with set-lock carries the requested effective lock');
  const operationsBeforeDelete = app.structuralProposals.length;
  wb.proposeDelete('free-guard');
  assert.equal(app.structuralProposals.length, operationsBeforeDelete, 'same-target set-lock and delete proposals are rejected');
  wb.setInstanceLock('free-guard', 'free');
  assert(!app.structuralProposals.some(item => item.kind === 'set-lock' && item.objectId === 'free-guard'), 'returning to the published lock removes the net-zero set-lock operation');
  assert.equal(app.structuralProposals.find(item => item.kind === 'move' && item.objectId === 'free-guard').lock, 'free', 'a retained move returns to the published lock value');
  wb.setInstanceLock('free-guard', 'fixed');
  assert.equal(wb.effectiveLock(wb.object('free-guard')), 'fixed', 'an explicit fixed request takes effect for local editing');
  assert(!app.structuralProposals.some(item => item.kind === 'move' && item.objectId === 'free-guard'), 'setting fixed clears an existing move in the same atomic change');
  assert(app.structuralProposals.some(item => item.kind === 'set-lock' && item.objectId === 'free-guard'), 'the explicit fixed request remains a set-lock proposal');
  await wb.undo();
  assert.equal(wb.effectiveLock(wb.object('free-guard')), 'free', 'undo restores the prior effective lock');
  assert(app.structuralProposals.some(item => item.kind === 'move' && item.objectId === 'free-guard'), 'undo restores the move removed by the fixed request');
  await wb.redo();
  assert.equal(wb.effectiveLock(wb.object('free-guard')), 'fixed', 'redo reapplies the lock change');
  assert(!app.structuralProposals.some(item => item.kind === 'move' && item.objectId === 'free-guard'), 'redo atomically reapplies move removal');

  const sceneOperation = { operationId: 'minimal-scene', kind: 'new-scene', sceneId: 'draft-scene-minimal-scene', name: '草稿大厅', template: 'minimal', bounds: [1600, 720], scope: '新场景' };
  app.structuralProposals = [sceneOperation];
  app.selectedObjectId = 'free-guard';
  app.targetNotes[sceneOperation.sceneId] = { objectId: sceneOperation.sceneId, text: '玩家入口放在左侧。' };
  wb.sceneCanvasSelection = sceneOperation.sceneId; wb.activeSceneId = sceneOperation.sceneId;
  wb.renderCanvas();
  const templateMarkers = [...document.querySelectorAll('.workbench-template-marker')];
  assert.equal(templateMarkers.length, 2, 'the minimal template shows floor and player-entry intent markers');
  assert.equal(templateMarkers[1].style.getPropertyValue('--anchor-y'), '0%', 'the player-entry marker starts at the floor edge and remains inside the canvas');
  assert.match(document.querySelector('.workbench-template-note').textContent, /尚未创建 Godot 节点/);
  templateMarkers[1].click();
  assert.equal(app.selectedObjectId, sceneOperation.sceneId, 'template markers select the draft scene as their comment target');
  assert.equal(document.querySelector('#edit-text').value, '玩家入口放在左侧。', 'marker selection restores the scene note without creating a child note identity');

  wb.stopPreview(); dom.window.close();
  console.log('PASS Studio local-layout proposal QA: explicit selection, lock/bounds checks, cancel, stale rejection, grouped undo/redo, and minimal template markers');
})().catch(error => { console.error(error.stack || error); process.exitCode = 1; dom.window.close(); });
