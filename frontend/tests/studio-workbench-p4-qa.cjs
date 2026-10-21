#!/usr/bin/env node
/* Targeted coverage for P4 direct composition plus N1/N3 workbench operations. */
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const { pathToFileURL } = require('node:url');
let JSDOM;
try { ({ JSDOM } = require('jsdom')); }
catch { console.log('SKIP Studio P4 workbench QA: jsdom is unavailable.'); process.exit(0); }

const root = path.resolve(__dirname, '..');
const dom = new JSDOM(fs.readFileSync(path.join(root, 'studio/index.html'), 'utf8'), {
  url: 'http://127.0.0.1:8123/studio/?project=p4-project&stage=iteration', pretendToBeVisual: true,
});
global.FormData = dom.window.FormData;
global.Option = dom.window.Option;
global.localStorage = dom.window.localStorage;
global.location = dom.window.location;
global.history = dom.window.history;
global.confirm = () => true;
const savedDocument = global.document;
delete global.document;

const fetchImpl = async () => ({ ok: false, status: 404, text: async () => '{"error":"unexpected request"}' });
const tick = () => new Promise(resolve => setTimeout(resolve, 0));

(async () => {
  const { StudioApp, DraftStore } = await import(pathToFileURL(path.join(root, 'studio/studio.js')).href);
  global.document = dom.window.document;
  const app = new StudioApp({ fetchImpl, documentImpl: dom.window.document, timers: globalThis });
  const project = { id: 'p4-project', title: '场景编排夹具', workflow: 'objects-v1', publicationRevision: 4 };
  const objects = [
    { id: 'scene-a', kind: 'scene', name: '甲场景', relations: [], fields: [], workbench: { role: 'scene', bounds: [200, 100] } },
    { id: 'scene-b', kind: 'scene', name: '乙场景', relations: [], fields: [], workbench: { role: 'scene', bounds: [300, 200] } },
    { id: 'guard-def', kind: 'entity', name: '守卫定义', relations: [], fields: [], workbench: { role: 'definition', size: [20, 10], anchor: [0.5, 0.5], lock: 'free' } },
    { id: 'free-guard', kind: 'entity', name: '自由守卫', relations: [], fields: [{ id: 'speed', label: '速度', type: 'scalar', value: 1 }], workbench: { role: 'instance', sceneId: 'scene-a', definitionId: 'guard-def', position: [60, 50], size: [20, 10], anchor: [0.5, 0.5], lock: 'free' } },
    { id: 'fixed-guard', kind: 'entity', name: '固定守卫', relations: [], fields: [], workbench: { role: 'instance', sceneId: 'scene-a', definitionId: 'guard-def', position: [40, 40], size: [20, 10], anchor: [0.5, 0.5], lock: 'fixed' } },
    { id: 'entry-b', kind: 'marker', name: '乙入口', relations: [], fields: [], workbench: { role: 'entry', sceneId: 'scene-b', position: [280, 180] } },
    { id: 'env-preset', kind: 'configuration', name: '环境配置', relations: [], fields: [], workbench: { role: 'preset' } },
    { id: 'hero-art', kind: 'asset', name: '英雄图集', relations: [], fields: [], sourceBindings: ['resources/hero.tres'], workbench: { role: 'resource', preview: { type: 'image', label: '运行剪辑' } } },
    { id: 'use-door', kind: 'interaction', name: '开门交互', relations: [{ type: 'targets', targetId: 'guard-def' }, { type: 'uses_preset', targetId: 'fade-preset' }], fields: [], workbench: { role: 'behavior', scope: 'shared', lifecycle: 'per-round', provenance: { kind: 'fact', sourcePaths: ['scripts/use-door.gd'] }, preview: { type: 'interaction', condition: '持有钥匙', result: '门打开' } } },
    { id: 'fade-preset', kind: 'configuration', name: '淡入淡出', relations: [], fields: [], workbench: { role: 'preset' } },
    { id: 'marked-preset', kind: 'configuration', name: '遮罩擦除', relations: [], fields: [], workbench: { role: 'preset', presetType: 'transition' } },
    { id: 'transition-a-b', kind: 'transition', name: '甲到乙', relations: [{ type: 'uses_preset', targetId: 'fade-preset' }], fields: [], workbench: { role: 'transition', sceneId: 'scene-a', targetSceneId: 'scene-b', entryId: 'entry-b', condition: '持有钥匙', mode: 'preset', presetId: 'fade-preset' } },
    { id: 'transition-b-a', kind: 'transition', name: '乙到甲', relations: [], fields: [], workbench: { role: 'transition', sceneId: 'scene-b', targetSceneId: 'scene-a', mode: 'none' } },
  ];
  app.protocolVersion = 1;
  app.handshake = { schemaVersion: 'studio.message.v1', kind: 'handshake', storeId: 'p4-store', serviceInstanceId: 'p4-service', writeToken: 'p4-token', readable: true, capabilities: [] };
  app.token = 'p4-token'; app.manager = { storeId: 'p4-store', projects: [project] };
  app.workspace = { storeId: 'p4-store', workspaceId: 'p4', projects: [project], iterationReady: true, capabilities: { interactiveFrontendConfirmation: true } };
  app.projectId = project.id; app.stage = 'iteration'; app.workflow = 'objects-v1'; app.currentProject = () => project;
  app.snapshot = { projectId: project.id, publicationRevision: 4, sourceCommit: 'git-p4-base', workflow: 'objects-v1', title: project.title, catalog: { objects }, document: { objects } };
  app.selectedObjectId = 'free-guard';
  app.capabilities = { fields: [{ id: 'free-guard.speed', objectId: 'free-guard', fieldId: 'speed', label: '速度', type: 'scalar', value: 1, editable: true, min: 0, max: 10 }] };
  app.projectView = { schemaVersion: 'studio.project-view.v1', storeId: 'p4-store', projectId: project.id, allowedActions: ['iteration.submit'], proposals: [], packets: [], jobs: [], previews: [] };
  app.readiness = { ready: true, missing: [] };
  app.targetNotes = {}; app.structuralProposals = []; app.workbenchResults = [];
  app.drafts = new DraftStore(null, dom.window.localStorage); app.persistenceOK = true; app.draftKey = app.makeDraftKey(app.snapshot); app.draftRevision = 0;
  app.bind(); app.renderWorkbench(); app.legacyWorkbench.resetHistory();
  const wb = app.legacyWorkbench;
  const notify = () => document.querySelector('#notice').textContent;
  const field = selector => document.querySelector(selector);
  const setDialogField = (name, value) => { const control = field(`#workbench-proposal-form [name="${name}"]`); assert(control, `proposal field ${name} exists`); control.value = value; };
  const canvasRect = canvas => { canvas.getBoundingClientRect = () => ({ left: 0, top: 0, width: 600, height: 400, right: 600, bottom: 400, x: 0, y: 0, toJSON() {} }); };

  app.selectObject('use-door');
  const semanticPreview = field('#workbench-preview .workbench-semantic-preview[data-semantic-type="interaction"]');
  assert(semanticPreview?.textContent.includes('持有钥匙') && semanticPreview.textContent.includes('门打开'), 'the main preview mounts the declared interaction semantics');
  const coverageLedger = field('#object-detail .workbench-coverage-ledger');
  assert(coverageLedger?.querySelector('[data-object-id="use-door"]'), 'the inspector mounts the stable-ID source coverage ledger');
  assert.match(field('#object-detail .workbench-metadata').textContent, /作用范围所有同类/);
  assert.match(field('#object-detail .workbench-metadata').textContent, /生命周期每轮/);
  const relationLink = field('#object-detail .workbench-relations .workbench-relation-link[data-object-id="guard-def"]');
  assert(relationLink?.textContent.includes('作用于'), 'relation type codes are translated for object users');
  assert(!relationLink.textContent.includes('guard-def'), 'exact object IDs stay out of the default relation label');
  const relationIdentity = relationLink.nextElementSibling;
  assert.equal(relationIdentity.open, false, 'relation IDs are collapsed by default');
  relationIdentity.open = true;
  assert.equal(relationIdentity.querySelector('code').textContent, 'guard-def', 'the exact related ID remains available on demand');
  const selectedLabel = field('#selected-object-label');
  assert.equal(selectedLabel.querySelector('span').textContent, '当前目标：开门交互', 'normal object selection uses the shared name plus expandable identity label');
  assert.equal(selectedLabel.querySelector('details code').textContent, 'use-door');
  semanticPreview.querySelector('[data-object-id="guard-def"]').click();
  assert.equal(app.selectedObjectId, 'guard-def', 'a semantic relation target selects its stable object from the main preview');
  const exactIdSearch = field('#workbench-search'); exactIdSearch.value = 'guard-def';
  exactIdSearch.dispatchEvent(new dom.window.KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true }));
  assert.equal(app.selectedObjectId, 'guard-def', 'the existing exact-ID search still selects a matching object');
  assert.match(field('#workbench-search-status').textContent, /精确 ID 定位：guard-def/);
  app.selectObject('free-guard');
  wb.openProposal('new-instance');
  assert.equal(field('#workbench-proposal-form [name="definitionId"]').value, 'guard-def', 'an instance with a mapped definition preselects that definition');
  assert.equal(field('#workbench-proposal-form [name="sceneId"]').value, 'scene-a', 'new instance creation keeps the active scene selected');
  assert.equal(field('.workbench-proposal-options').open, false, 'secondary instance options stay collapsed until requested');
  assert.match(field('.workbench-proposal-options').textContent, /固定 · 不可移动或删除/);
  field('#workbench-proposal-dialog [data-workbench-action="close-proposal"]').click();

  assert(wb.scenes().some(scene => scene.id === 'scene-a'), 'published scenes project from the object catalog');
  wb.openProposal('new-scene');
  setDialogField('name', '草稿大厅'); setDialogField('worldWidth', '300'); setDialogField('worldHeight', '200');
  wb.addProposalFromForm();
  const sceneProposal = app.structuralProposals.find(item => item.kind === 'new-scene');
  assert(sceneProposal?.sceneId.startsWith('draft-scene-'), 'new scenes receive stable draft IDs');
  assert(wb.scenes().some(scene => scene.id === sceneProposal.sceneId), 'new scenes immediately project into scene navigation and scene lookup');
  assert.equal(app.selectedObjectId, sceneProposal.sceneId, 'the draft scene becomes the selected target');
  assert.equal(wb.draftTarget(sceneProposal.sceneId).id, sceneProposal.sceneId, 'the draft scene is addressable as a target');

  const countBeforeCancelledPlacement = app.structuralProposals.length;
  wb.openProposal('new-instance');
  setDialogField('name', '守卫草稿'); setDialogField('definitionId', 'guard-def'); setDialogField('sceneId', sceneProposal.sceneId);
  wb.addProposalFromForm();
  assert(wb.pendingPlacementOperationId, 'new instance first enters placement mode');
  const previewCanvas = field('.workbench-coordinate-canvas'); canvasRect(previewCanvas);
  wb.previewPendingInstance({ clientX: 300, clientY: 200 }, previewCanvas);
  assert(field('.workbench-placement-cursor'), 'placement mode previews a marker at the pointer');
  wb.cancelPendingPlacement();
  assert.equal(app.structuralProposals.length, countBeforeCancelledPlacement, 'cancel leaves no placed operation or net structural change');
  assert.equal(wb.pendingPlacementOperationId, null, 'cancel clears temporary placement state');

  wb.openProposal('new-instance');
  setDialogField('name', '守卫草稿'); setDialogField('definitionId', 'guard-def'); setDialogField('sceneId', sceneProposal.sceneId);
  wb.addProposalFromForm();
  const placeCanvas = field('.workbench-coordinate-canvas'); canvasRect(placeCanvas);
  const placeEvent = { clientX: 300, clientY: 200 };
  wb.previewPendingInstance(placeEvent, placeCanvas);
  wb.placePendingInstance(placeEvent, placeCanvas);
  const placed = app.structuralProposals.find(item => item.kind === 'new-instance');
  assert.deepEqual(placed.requestedPosition, [150, 100], 'placement maps screen coordinates into the selected scene world');
  assert(placed.instanceId.startsWith('draft-instance-'), 'placed instances receive stable draft IDs');
  assert.equal(app.selectedObjectId, placed.instanceId, 'the placed draft instance becomes the selected target');
  assert(wb.draftTarget(placed.instanceId), 'the placed instance immediately projects as a draft target');
  let draftToken = field(`.workbench-object-token[data-object-id="${placed.instanceId}"]`);
  assert(draftToken?.classList.contains('is-draft'), 'the placed draft instance renders as an interactive canvas token');
  assert.equal(draftToken.dataset.lock, 'free', 'new draft instances default to the explicit free lock mode');
  assert.equal(field('#workbench-proposal-form [name="lock"]').value, 'free', 'the proposal form explicitly defaults new instances to free movement');

  const lockedDraftSize = placed.size, lockedDraftAnchor = placed.anchor;
  placed.size = [30, 20]; placed.anchor = [1, 1];
  assert.deepEqual(wb.metadata(wb.draftTarget(placed.instanceId)).size, [30, 20], 'instance size overrides the shared definition metadata');
  assert.deepEqual(wb.metadata(wb.draftTarget(placed.instanceId)).anchor, [1, 1], 'instance anchor overrides the shared definition metadata');
  assert.equal(wb.proposalPositionValid(placed.sceneId, wb.object('guard-def'), [299, 199], placed), null, 'placement validation uses operation size and anchor overrides');
  placed.size = lockedDraftSize; placed.anchor = lockedDraftAnchor;

  const stableScene = sceneProposal.sceneId;
  app.selectObject('free-guard'); wb.sceneCanvasSelection = stableScene; wb.render();
  draftToken = field(`.workbench-object-token[data-object-id="${placed.instanceId}"]`);
  draftToken.dispatchEvent(new dom.window.MouseEvent('click', { bubbles: true }));
  assert.equal(app.selectedObjectId, placed.instanceId, 'clicking a canvas draft token selects its stable draft target');
  draftToken = field(`.workbench-object-token[data-object-id="${placed.instanceId}"]`);
  const draftCanvas = draftToken.closest('.workbench-coordinate-canvas'); canvasRect(draftCanvas);
  wb.beginDrag({ target: draftToken, isPrimary: true, button: 0, pointerId: 7, preventDefault() {} });
  assert(wb.drag, 'free draft tokens can enter canvas drag mode');
  wb.moveDrag({ pointerId: 7, clientX: 500, clientY: 300 }); wb.endDrag({ pointerId: 7, type: 'pointerup' });
  assert.deepEqual(app.structuralProposals.find(item => item.operationId === placed.operationId).requestedPosition, [250, 150], 'dragging a draft token edits its new-instance requestedPosition');
  assert(!app.structuralProposals.some(item => item.kind === 'move' && item.objectId === placed.instanceId), 'dragging a draft does not create a detached move operation');

  wb.setDraftInstancePosition(placed.operationId, [180, 100]);
  assert.deepEqual(app.structuralProposals.find(item => item.operationId === placed.operationId).requestedPosition, [180, 100], 'coordinate controls update the placement proposal');
  await wb.undo();
  assert.deepEqual(app.structuralProposals.find(item => item.operationId === placed.operationId).requestedPosition, [250, 150], 'coordinate updates are one undoable change after the canvas drag');
  await wb.redo();
  assert.deepEqual(app.structuralProposals.find(item => item.operationId === placed.operationId).requestedPosition, [180, 100], 'redo reapplies the coordinate update');
  wb.setDraftInstancePosition(placed.operationId, [299, 10]);
  assert.deepEqual(app.structuralProposals.find(item => item.operationId === placed.operationId).requestedPosition, [180, 100], 'out-of-bounds anchored positions leave the draft unchanged');
  assert.match(notify(), /越过(?:场景)?世界边界/);

  wb.openProposal('new-instance');
  setDialogField('name', '微调守卫'); setDialogField('definitionId', 'guard-def'); setDialogField('sceneId', 'scene-a'); setDialogField('lock', 'nudge');
  wb.addProposalFromForm();
  const nudgeCanvas = field('.workbench-coordinate-canvas'); canvasRect(nudgeCanvas);
  wb.placePendingInstance({ clientX: 300, clientY: 200 }, nudgeCanvas);
  const nudgeDraft = app.structuralProposals.find(item => item.kind === 'new-instance' && item.lock === 'nudge');
  assert(nudgeDraft, 'new instance form keeps the selected nudge lock');
  assert(field(`.workbench-object-token[data-object-id="${nudgeDraft.instanceId}"][data-lock="nudge"]`), 'nudge draft tokens remain selectable without becoming draggable');
  wb.nudgeSelected(1, 0, nudgeDraft.instanceId);
  assert.deepEqual(nudgeDraft.requestedPosition, [101, 50], 'nudge updates the new-instance operation in place');
  assert(!app.structuralProposals.some(item => item.kind === 'move' && item.objectId === nudgeDraft.instanceId), 'nudge does not create a separate move operation for a draft target');

  wb.openProposal('new-instance');
  setDialogField('name', '固定守卫草稿'); setDialogField('definitionId', 'guard-def'); setDialogField('sceneId', 'scene-a'); setDialogField('lock', 'fixed');
  wb.addProposalFromForm();
  const fixedDraftCanvas = field('.workbench-coordinate-canvas'); canvasRect(fixedDraftCanvas);
  wb.placePendingInstance({ clientX: 240, clientY: 160 }, fixedDraftCanvas);
  const fixedDraft = app.structuralProposals.find(item => item.kind === 'new-instance' && item.lock === 'fixed');
  const fixedDraftToken = field(`.workbench-object-token[data-object-id="${fixedDraft.instanceId}"]`);
  assert(fixedDraftToken && field('.workbench-draft-instance-row button[disabled]'), 'fixed draft coordinates are disabled after placement');
  wb.beginDrag({ target: fixedDraftToken, isPrimary: true, button: 0, pointerId: 8, preventDefault() {} });
  assert.equal(wb.drag, null, 'fixed draft tokens cannot enter drag mode');

  app.selectObject('fixed-guard');
  const fixedToken = field('.workbench-object-token[data-object-id="fixed-guard"]');
  wb.beginDrag({ target: fixedToken, isPrimary: true, button: 0, pointerId: 4, preventDefault() {} });
  assert.equal(wb.drag, null, 'fixed instances cannot enter drag mode');
  assert.equal(wb.proposeMove(wb.object('fixed-guard'), [50, 40]), false, 'fixed instances reject direct move proposals');
  assert.match(notify(), /固定/);

  app.selectObject('free-guard');
  let freeToken = field('.workbench-object-token[data-object-id="free-guard"]');
  let freeCanvas = freeToken.closest('.workbench-coordinate-canvas'); canvasRect(freeCanvas);
  wb.beginDrag({ target: freeToken, isPrimary: true, button: 0, pointerId: 5, preventDefault() {} });
  assert(wb.drag, 'free instances can enter drag mode');
  wb.moveDrag({ pointerId: 5, clientX: 540, clientY: 360 });
  wb.endDrag({ pointerId: 5, type: 'pointerup' });
  const freeMove = app.structuralProposals.find(item => item.kind === 'move' && item.objectId === 'free-guard');
  assert.deepEqual(freeMove.requested, [180, 90], 'free-instance dragging creates one world-coordinate move proposal');
  freeToken = field('.workbench-object-token[data-object-id="free-guard"]'); freeCanvas = freeToken.closest('.workbench-coordinate-canvas'); canvasRect(freeCanvas);
  wb.beginDrag({ target: freeToken, isPrimary: true, button: 0, pointerId: 6, preventDefault() {} });
  wb.moveDrag({ pointerId: 6, clientX: 120, clientY: 80 }); wb.endDrag({ pointerId: 6, type: 'pointercancel' });
  assert.deepEqual(app.structuralProposals.find(item => item.kind === 'move' && item.objectId === 'free-guard').requested, [180, 90], 'pointer cancellation does not leave a partial move');

  app.selectObject('transition-a-b'); wb.openProposal('transition');
  assert.equal(field('#workbench-proposal-form [name="from"]').value, 'scene-a', 'transition editing pre-fills the source direction');
  assert.equal(field('#workbench-proposal-form [name="sceneId"]').value, 'scene-b', 'transition editing pre-fills the destination');
  assert.equal(field('#workbench-proposal-form [name="entryId"]').value, 'entry-b', 'transition editing pre-fills its destination entry');
  assert.equal(field('#workbench-proposal-form [name="condition"]').value, '持有钥匙');
  assert.equal(field('#workbench-proposal-form [name="mode"]').value, '共享预设');
  const presetValues = [...field('#workbench-proposal-form [name="presetId"]').options].map(option => option.value);
  assert(presetValues.includes('fade-preset') && presetValues.includes('marked-preset'), 'referenced and explicitly classified transition presets are selectable');
  assert(!presetValues.includes('env-preset'), 'environment configuration is excluded from transition presets');
  const transitionCountBeforeNoOp = app.structuralProposals.filter(item => item.kind === 'transition').length;
  wb.addProposalFromForm();
  assert.equal(app.structuralProposals.filter(item => item.kind === 'transition').length, transitionCountBeforeNoOp, 'submitting the published transition values creates no operation');
  assert.match(notify(), /没有新增净变化/);
  wb.openProposal('transition'); setDialogField('condition', '持有钥匙且守卫在岗'); wb.addProposalFromForm();
  const forward = app.structuralProposals.find(item => item.kind === 'transition' && item.objectId === 'transition-a-b');
  assert.equal(forward.objectId, 'transition-a-b', 'the proposal stays bound to the selected transition object');
  assert.equal(forward.from, 'scene-a'); assert.equal(forward.sceneId, 'scene-b'); assert.equal(forward.entryId, 'entry-b'); assert.equal(forward.condition, '持有钥匙且守卫在岗');
  assert.equal(forward.mode, '共享预设'); assert.equal(forward.presetId, 'fade-preset');
  app.selectObject('transition-b-a'); wb.openProposal('transition'); setDialogField('condition', '返回通道开放'); wb.addProposalFromForm();
  const reverse = app.structuralProposals.find(item => item.kind === 'transition' && item.objectId === 'transition-b-a');
  assert.equal(reverse.objectId, 'transition-b-a', 'the reverse direction has its own target identity');
  assert.equal(reverse.from, 'scene-b'); assert.equal(reverse.sceneId, 'scene-a'); assert.equal(reverse.condition, '返回通道开放');
  assert.notEqual(forward.objectId, reverse.objectId, 'editing one direction does not overwrite its reverse');

  app.targetNotes = { 'free-guard': { objectId: 'free-guard', text: '速度调整为 3。', feedbackId: 'speed-note' } };
  app.fieldDraftValues = { 'free-guard.speed': 2 }; app.dirtyFields = new Set(['free-guard.speed']);
  app.renderWorkbench(); wb.openReport();
  assert(field('[data-report-note-id="speed-note"]'), 'the report previews the stable opinion item');
  assert(field('[data-field-change-id="free-guard.speed"]'), 'the report previews the individual field change');
  wb.editReportNote('speed-note');
  const noteEditor = field('[data-report-note-editor="speed-note"]'); noteEditor.value = '速度调整为 3，维持高于 2。'; wb.saveReportNote('speed-note');
  assert.equal(app.targetNotes['free-guard'].text, '速度调整为 3，维持高于 2。', 'report editing updates the saved target opinion');
  const conflictSelect = field('.workbench-conflict-resolution [data-conflict-decision]');
  assert(conflictSelect, 'same-target field and opinion changes receive an explicit conflict decision control');
  conflictSelect.value = 'clarify'; field('.workbench-conflict-resolution [data-conflict-explanation]').value = '先问用户要 2 还是 3。';
  wb.applyConflictDecision(field('.workbench-conflict-resolution [data-workbench-action="apply-conflict-decision"]'));
  const clarification = Object.values(app.targetNotes).find(note => note.decisionFor);
  assert.match(clarification.text, /用户要求先澄清/); assert.match(clarification.text, /先问用户要 2 还是 3/);
  const frozen = app.buildChangeRequest();
  assert(!frozen.fields.some(item => item.objectId === 'free-guard' && item.fieldId === 'speed'), 'clarification leaves no confirmed numeric execution target');
  assert.equal(app.fieldDraftValues['free-guard.speed'], 2, 'the control draft remains available for later editing');
  assert(frozen.feedback.some(item => item.message === '速度调整为 3，维持高于 2。'), 'the original opinion remains in the outgoing request');
  assert(frozen.feedback.some(item => item.message === clarification.text), 'the chosen clarification decision also reaches the outgoing request');
  wb.removeReportNote('speed-note');
  assert(!Object.values(app.targetNotes).some(note => note.feedbackId === 'speed-note'), 'an individual opinion can be removed from the report');
  app.selectObject('free-guard');
  app.targetNotes['free-guard'] = { objectId: 'free-guard', text: '恢复意见', feedbackId: 'restore-note' };
  wb.loadCurrentNote();
  app.renderWorkbench(); wb.openReport(); wb.removeFieldChange('free-guard', 'speed');
  assert.equal(app.fieldDraftValues['free-guard.speed'], undefined, 'an individual property change can be removed from the report');
  assert.equal(field('#dynamic-fields [data-field-id="free-guard.speed"]').value, '1', 'removing a change restores the published control value');

  app.targetNotes = { 'free-guard': { objectId: 'free-guard', text: '保存版本 A', feedbackId: 'saved-a' } };
  wb.loadCurrentNote(); app.renderWorkbench(); await wb.saveDraft();
  const savedKey = wb.savedCheckpointKey(app.draftKey);
  assert.equal((await app.drafts.get(savedKey)).targetNotes['free-guard'].text, '保存版本 A', 'explicit save captures checkpoint A in the existing DraftStore');
  app.targetNotes['free-guard'].text = '自动保存版本 B'; wb.loadCurrentNote(); app.queueDraftSave(); await tick();
  assert.equal((await app.drafts.get(savedKey)).targetNotes['free-guard'].text, '保存版本 A', 'automatic saves do not overwrite explicit checkpoint A');
  assert.equal((await app.drafts.get(app.draftKey)).targetNotes['free-guard'].text, '自动保存版本 B', 'the active working draft continues to autosave B');

  let exportedBlob = null;
  const originalCreateObjectURL = URL.createObjectURL, originalRevokeObjectURL = URL.revokeObjectURL;
  URL.createObjectURL = blob => { exportedBlob = blob; return 'blob:p4-test'; };
  URL.revokeObjectURL = () => {};
  const originalClick = dom.window.HTMLAnchorElement.prototype.click;
  dom.window.HTMLAnchorElement.prototype.click = () => {};
  await wb.exportDraft();
  const exported = JSON.parse(await exportedBlob.text());
  assert.equal(exported.draft.targetNotes['free-guard'].text, '自动保存版本 B');
  assert.equal(exported.savedCheckpoint.draft.targetNotes['free-guard'].text, '保存版本 A', 'export includes the explicit saved checkpoint alongside the current draft');
  URL.createObjectURL = originalCreateObjectURL; URL.revokeObjectURL = originalRevokeObjectURL; dom.window.HTMLAnchorElement.prototype.click = originalClick;

  wb.resetDraft();
  assert.deepEqual(app.targetNotes, {}, 'reset clears current opinions');
  assert.deepEqual(app.structuralProposals, [], 'reset clears current structural proposals');
  await wb.undo();
  assert.equal(app.targetNotes['free-guard'].text, '自动保存版本 B', 'undo restores the draft that reset cleared');
  await wb.restoreSavedDraft();
  assert.equal(app.targetNotes['free-guard'].text, '保存版本 A', 'opening the checkpoint restores A after the reset is undone');
  await wb.undo();
  assert.equal(app.targetNotes['free-guard'].text, '自动保存版本 B', 'opening A is itself an undoable workspace transaction');

  app.selectObject('hero-art');
  const sourceDetails = field('.workbench-source-details'), sourceCalls = [];
  app.request = async path => {
    sourceCalls.push(path);
    return { projectId: project.id, objectId: 'hero-art', kind: 'static_source', sourceCommit: 'git-p4-base',
      sources: [{ path: 'resources/hero.tres', available: true, content: '[resource] AtlasTexture' }],
      imagePreview: { resourcePath: 'resources/hero.tres', imagePath: 'assets/sheet.png', region: [16, 0, 16, 16], clipName: 'run', frameCount: 4, fps: 8 },
    };
  };
  sourceDetails.querySelector('[data-workbench-action="load-source"]').click();
  await tick();
  assert(sourceDetails.isConnected, 'clicking the source action does not navigate and detach its details panel');
  assert.equal(sourceDetails.querySelector('.workbench-source-result').dataset.loaded, 'true', 'the connected source panel receives the async result');
  const imageSource = field('.workbench-source-image-preview');
  assert(sourceCalls.includes('/projects/p4-project/objects/hero-art/source'), 'source inspection reads the selected object source endpoint');
  assert.match(imageSource.textContent, /Atlas 区域：16, 0 · 16 × 16 像素/);
  assert.match(imageSource.textContent, /run.*4 帧 · 8 FPS/);
  assert.match(imageSource.textContent, /真实首帧/);
  assert.equal(new URL(imageSource.querySelector('img').src).pathname, '/api/projects/p4-project/objects/hero-art/preview', 'the source descriptor uses the existing exact-version image endpoint');
  const loadPreviewButton = field('#workbench-preview [data-workbench-action="load-bound-preview"]');
  loadPreviewButton.click(); await tick();
  assert.equal(new URL(field('#workbench-preview img').src).pathname, '/api/projects/p4-project/objects/hero-art/preview', 'resource preview action is delegated and displays the selected object image');

  const reportDialog = field('#workbench-report-dialog');
  reportDialog.showModal = function () { this.open = true; };
  reportDialog.close = function () { this.open = false; };
  app.proposal = { id: 'before-pending-report' };
  let finishSubmit, submittedRequest;
  app.submitIteration = () => {
    submittedRequest = app.buildChangeRequest();
    return new Promise(resolve => { finishSubmit = () => { app.proposal = { id: 'accepted-pending-report' }; resolve(); }; });
  };
  wb.openReport();
  const pendingSubmit = wb.confirmReport();
  assert(wb.reportSubmitting, 'the report locks duplicate confirmation while its request is pending');
  const closePending = field('#workbench-report-dialog [data-workbench-action="close-report"]');
  assert.equal(closePending.disabled, false, 'the user may close the report while the request is pending');
  closePending.click(); assert.equal(reportDialog.open, false, 'closing a pending report remains available');
  field('#edit-text').value = '申报期间的新编辑'; field('#edit-text').dispatchEvent(new dom.window.Event('input', { bubbles: true }));
  assert(!submittedRequest.feedback.some(item => item.objectId === 'hero-art'), 'the pending request keeps the report-time payload');
  finishSubmit(); await pendingSubmit;
  assert.equal(app.targetNotes['hero-art'].text, '申报期间的新编辑', 'a later edit survives the older pending request');
  assert.equal(wb.reportSubmitting, false, 'the in-flight lock clears when a request succeeds');

  let sequentialSubmits = 0;
  app.proposal = { id: 'before-sequential-report' };
  app.submitIteration = async () => { app.proposal = { id: `sequential-report-${++sequentialSubmits}` }; };
  wb.openReport(); await wb.confirmReport();
  assert.equal(wb.reportSubmitting, false, 'first success resets the report submission lock');
  wb.openReport(); await wb.confirmReport();
  assert.equal(sequentialSubmits, 2, 'the same page can confirm a second iteration after the first succeeds');
  assert.equal(wb.reportSubmitting, false, 'second success also leaves the report available for later iteration');

  if (wb.historyTimer != null) clearTimeout(wb.historyTimer);
  app.destroy(); dom.window.close(); global.document = savedDocument;
  console.log('PASS Studio P4/N1/N3 QA: scene and instance projection, placement cancel/commit, bounds and drag history, directional transitions, report item decisions, and saved draft checkpoints');
})().catch(error => { console.error(error.stack || error); process.exitCode = 1; dom.window.close(); global.document = savedDocument; });
