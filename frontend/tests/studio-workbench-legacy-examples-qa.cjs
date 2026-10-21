#!/usr/bin/env node
/* Focused QA for the two explicit legacy workbench example entries. */
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const { pathToFileURL } = require('node:url');
let JSDOM;
try { ({ JSDOM } = require('jsdom')); }
catch { console.log('SKIP Studio legacy examples QA: jsdom is unavailable.'); process.exit(0); }

const root = path.resolve(__dirname, '..');
const dom = new JSDOM(fs.readFileSync(path.join(root, 'studio/index.html'), 'utf8'), {
  url: 'http://127.0.0.1:8123/studio/?project=legacy-examples', pretendToBeVisual: true,
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
    { id: 'player', kind: 'entity', name: '玩家', fields: [], relations: [], workbench: { role: 'instance', sceneId: 'scene-a', position: [90, 90], size: [24, 24], anchor: [0.5, 0.5], lock: 'free' } },
    { id: 'decor-a', kind: 'entity', name: '明确映射的装饰', fields: [], relations: [], workbench: { role: 'instance', sceneId: 'scene-a', decoration: true, position: [91, 90], size: [20, 20], anchor: [0.5, 0.5], lock: 'free' } },
    { id: 'decor-fixed', kind: 'entity', name: '固定装饰', fields: [], relations: [], workbench: { role: 'instance', sceneId: 'scene-a', decoration: true, position: [160, 160], size: [20, 20], anchor: [0.5, 0.5], lock: 'fixed' } },
    { id: 'decor-outside', kind: 'entity', name: '越界装饰', fields: [], relations: [], workbench: { role: 'instance', sceneId: 'scene-a', decoration: true, position: [395, 290], size: [20, 20], anchor: [0.5, 0.5], lock: 'free' } },
    { id: 'dice-burst', kind: 'mechanic', name: '骰子事件', fields: [{ id: 'warning-duration', label: '落点预警时长', type: 'number', value: 1.5, min: 0, max: 10 }], relations: [], workbench: { role: 'behavior', sceneId: 'scene-a' } },
  ];
  let serial = 0;
  const notifications = [];
  const app = {
    projectId: 'legacy-examples', selectedObjectId: 'player', fieldDraftValues: {}, dirtyFields: new Set(), targetNotes: {}, structuralProposals: [],
    snapshot: { projectId: 'legacy-examples', publicationRevision: 4, sourceCommit: 'git-example-base' },
    capabilities: { fields: [{ id: 'dice-burst.warning-duration', label: '落点预警时长', type: 'scalar', editable: true, min: 1, max: 3, step: 0.5, currentValue: 1.5 }] },
    objectItems: () => objects,
    selectObject: objectId => { app.selectedObjectId = objectId; wb?.renderCanvas(); },
    allCapabilities: () => app.capabilities.fields,
    splitCapability: capability => {
      const parts = String(capability.objectId && capability.fieldId ? `${capability.objectId}.${capability.fieldId}` : capability.id || '').split('.');
      return { objectId: capability.objectId || parts.shift() || '', fieldId: capability.fieldId || parts.join('.') };
    },
    capabilityEditable: capability => capability.editable === true,
    capabilityValue: (capability, object) => capability.currentValue ?? object.fields.find(field => field.id === 'warning-duration')?.value,
    newFeedbackId: () => `operation-${++serial}`,
    queueDraftSave: () => {}, notify: message => notifications.push(message),
    captureVisibleFields: () => {}, renderDynamicFields: () => {}, renderObjectDetail: () => {},
    readVisibleDraft: () => ({ fields: { ...app.fieldDraftValues }, feedback: [], feedbackMessage: '', feedbackCategory: 'general', selectedObjectId: app.selectedObjectId }),
    applyVisibleDraft: state => {
      app.selectedObjectId = state.selectedObjectId || null;
      app.fieldDraftValues = { ...(state.fields || {}) };
      app.structuralProposals = structuredClone(state.structuralProposals || []);
      app.targetNotes = structuredClone(state.targetNotes || {});
    },
  };
  let wb = null;
  wb = new LegacyWorkbench(app);
  wb.sceneCanvasSelection = 'scene-a'; wb.activeSceneId = 'scene-a';
  wb.bind(); wb.resetHistory();
  wb.render = () => wb.renderCanvas();
  wb.refreshReport = () => {};
  const click = selector => {
    const control = document.querySelector(selector);
    assert(control, `control exists: ${selector}`);
    control.click();
    return control;
  };

  wb.renderCanvas();
  assert(document.body.textContent.includes('整理装饰布局'), 'the exact decoration example remains visible');
  assert(document.body.textContent.includes('缩短骰子事件预警'), 'the exact timing example remains visible');
  assert.match(document.querySelector('.workbench-legacy-example .workbench-example-status').textContent, /显式装饰映射/);
  click('[data-workbench-action="preview-decor-example"]');
  assert.deepEqual(wb.localDecorationProposal.changes.map(change => change.objectId), ['decor-a'], 'only an explicitly mapped, positioned, movable decoration is previewed');
  assert(!wb.localDecorationProposal.changes.some(change => change.objectId === 'player' || change.objectId === 'decor-fixed' || change.objectId === 'decor-outside'), 'player, fixed decoration, and invalid-position decoration are excluded');
  assert.match(document.querySelector('.workbench-legacy-examples').textContent, /不包含通路验证|没有进行寻路/);
  click('[data-workbench-action="cancel-decor-example"]');
  assert.equal(wb.localDecorationProposal, null, 'cancelling the decoration preview creates no operation');
  assert.equal(app.structuralProposals.length, 0);
  click('[data-workbench-action="preview-decor-example"]');
  const historyBeforeDecor = wb.history.length;
  click('[data-workbench-action="apply-decor-example"]');
  assert.deepEqual(app.structuralProposals.filter(operation => operation.kind === 'move').map(operation => operation.objectId), ['decor-a'], 'apply creates only the mapped decoration move');
  assert.equal(wb.history.length, historyBeforeDecor + 1, 'the decoration example is one undo step');
  await wb.undo();
  assert.equal(app.structuralProposals.length, 0, 'one undo removes the decoration move');
  await wb.redo();
  assert.equal(app.structuralProposals.filter(operation => operation.kind === 'move').length, 1, 'one redo restores the decoration move');
  app.structuralProposals = []; wb.resetHistory();

  app.selectedObjectId = 'player'; wb.renderCanvas();
  assert.match(document.querySelectorAll('.workbench-legacy-example')[1].textContent, /选择 dice-burst/);
  app.selectedObjectId = 'dice-burst'; wb.renderCanvas();
  click('[data-workbench-action="preview-timing-example"]');
  assert.deepEqual(
    { objectId: wb.localTimingProposal.objectId, fieldId: wb.localTimingProposal.fieldId, before: wb.localTimingProposal.before, requested: wb.localTimingProposal.requested },
    { objectId: 'dice-burst', fieldId: 'warning-duration', before: 1.5, requested: 1 },
    'the timing example previews the exact mapped dice-event warning field using its scalar type, 0.5 step, and min=1 range',
  );
  assert(document.querySelectorAll('.workbench-layout-diff li').length >= 1);
  assert.match(document.querySelectorAll('.workbench-legacy-example')[1].textContent, /dice-burst\.warning-duration/);
  click('[data-workbench-action="cancel-timing-example"]');
  assert.equal(wb.localTimingProposal, null, 'cancelling timing leaves the field draft unchanged');
  assert.deepEqual(app.fieldDraftValues, {});

  click('[data-workbench-action="preview-timing-example"]');
  const historyBeforeTiming = wb.history.length;
  click('[data-workbench-action="apply-timing-example"]');
  assert.equal(app.fieldDraftValues['dice-burst.warning-duration'], 1, 'timing apply writes the exact field draft');
  assert(app.dirtyFields.has('dice-burst.warning-duration'), 'the field participates in normal dirty-field reporting');
  assert.equal(wb.history.length, historyBeforeTiming + 1, 'timing apply is one undo step');
  await wb.undo();
  assert(!Object.hasOwn(app.fieldDraftValues, 'dice-burst.warning-duration'), 'one undo restores the prior field draft');
  await wb.redo();
  assert.equal(app.fieldDraftValues['dice-burst.warning-duration'], 1, 'one redo restores the timing field change');

  app.fieldDraftValues = {}; wb.resetHistory(); wb.renderCanvas();
  click('[data-workbench-action="preview-timing-example"]');
  app.fieldDraftValues['dice-burst.warning-duration'] = 1.4;
  assert.equal(wb.applyTimingExample(), false, 'a timing preview rejects a changed field draft');
  assert.equal(app.fieldDraftValues['dice-burst.warning-duration'], 1.4, 'stale rejection preserves the newer field value');
  assert.match(notifications.at(-1), /过期/);

  const editableCapabilities = app.capabilities;
  app.capabilities = { fields: [{ id: 'dice-burst.warning-duration', type: 'scalar', editable: false, min: 1, max: 3, step: 0.5, currentValue: 1.5 }] };
  app.fieldDraftValues = {}; app.selectedObjectId = 'dice-burst'; wb.localTimingProposal = null; wb.timingExampleStatus = '';
  assert.equal(wb.previewTimingExample(), false, 'a read-only capability cannot produce a timing preview');
  assert.match(wb.timingExampleStatus, /无法应用/);
  app.capabilities = { fields: [] };
  assert.equal(wb.previewTimingExample(), false, 'a missing exact capability cannot produce a timing preview');
  assert.match(wb.timingExampleStatus, /无法应用/);
  app.capabilities = { fields: [{ id: 'dice-burst.warning-duration', label: '落点预警时长', type: 'scalar', editable: true, min: 1, max: 3, step: 0.5, currentValue: 1 }] };
  assert.equal(wb.previewTimingExample(), false, 'the declared minimum prevents another timing reduction');
  assert.match(wb.timingExampleStatus, /下限/);
  app.capabilities = { fields: [{ id: 'dice-burst.warning-duration', label: '落点预警时长', type: 'scalar', editable: true, min: 1, max: 3, step: 0.5, currentValue: 3.5 }] };
  assert.equal(wb.previewTimingExample(), false, 'a current value above the declared maximum cannot be previewed');
  assert.match(wb.timingExampleStatus, /数值范围/);
  app.capabilities = { fields: [{ id: 'dice-burst.warning-duration', label: '落点预警时长', type: 'integer', editable: true, min: 1, max: 3, step: 0.5, currentValue: 2 }] };
  assert.equal(wb.previewTimingExample(), true, 'integer timing capabilities remain supported');
  assert.equal(wb.localTimingProposal.requested, 1, 'integer timing changes use integer steps even if metadata advertises a fractional step');
  wb.localTimingProposal = null;
  app.capabilities = editableCapabilities;

  app.selectedObjectId = 'player'; wb.view = 'design';
  const originalPushState = history.pushState.bind(history);
  let pushCount = 0;
  history.pushState = (...args) => { pushCount += 1; return originalPushState(...args); };
  wb.syncUrl(); wb.syncUrl(); wb.syncUrl();
  assert.equal(pushCount, 1, 'repeated syncUrl with the same route does not add duplicate browser-history entries');

  wb.stopPreview(); dom.window.close();
  console.log('PASS Studio legacy examples QA: explicit decoration filtering, no path guarantee, timing capability gating, exact field diff, cancel/stale rejection, grouped undo/redo, and duplicate-route history suppression');
})().catch(error => { console.error(error.stack || error); process.exitCode = 1; dom.window.close(); });
