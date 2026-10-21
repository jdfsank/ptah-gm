#!/usr/bin/env node
/* Focused QA for directional transition editing, target entries and net changes. */
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const { pathToFileURL } = require('node:url');
let JSDOM;
try { ({ JSDOM } = require('jsdom')); }
catch { console.log('SKIP Studio transition operation QA: jsdom is unavailable.'); process.exit(0); }

const root = path.resolve(__dirname, '..');
const dom = new JSDOM(fs.readFileSync(path.join(root, 'studio/index.html'), 'utf8'), {
  url: 'http://127.0.0.1:8123/studio/?project=transition-operation', pretendToBeVisual: true,
});
global.document = dom.window.document;
global.FormData = dom.window.FormData;
global.Option = dom.window.Option;
global.localStorage = dom.window.localStorage;

(async () => {
  const { LegacyWorkbench } = await import(pathToFileURL(path.join(root, 'studio/workbench.js')).href);
  const objects = [
    { id: 'scene-a', kind: 'scene', name: '甲场景', fields: [], relations: [], workbench: { role: 'scene' } },
    { id: 'scene-b', kind: 'scene', name: '乙场景', fields: [], relations: [], workbench: { role: 'scene' } },
    { id: 'scene-c', kind: 'scene', name: '丙场景', fields: [], relations: [], workbench: { role: 'scene' } },
    { id: 'entry-a', kind: 'marker', name: '甲入口', fields: [], relations: [], workbench: { role: 'entry', sceneId: 'scene-a' } },
    { id: 'entry-b-1', kind: 'marker', name: '乙入口一', fields: [], relations: [], workbench: { role: 'entry', sceneId: 'scene-b' } },
    { id: 'entry-b-2', kind: 'marker', name: '乙入口二', fields: [], relations: [], workbench: { role: 'entry', sceneId: 'scene-b' } },
    { id: 'entry-c', kind: 'marker', name: '丙入口', fields: [], relations: [], workbench: { role: 'entry', sceneId: 'scene-c' } },
    { id: 'fade-preset', kind: 'configuration', name: '淡入淡出', fields: [], relations: [], workbench: { role: 'preset' } },
    { id: 'marked-preset', kind: 'configuration', name: '遮罩擦除', fields: [], relations: [], workbench: { role: 'preset', presetType: 'transition' } },
    { id: 'preview-preset', kind: 'configuration', name: '预览过渡', fields: [], relations: [], workbench: { role: 'preset', preview: { type: 'transition' } } },
    { id: 'environment-preset', kind: 'configuration', name: '环境配置', fields: [], relations: [], workbench: { role: 'preset' } },
    { id: 'edge-forward', kind: 'transition', name: '甲到乙', fields: [], relations: [{ type: 'uses_preset', targetId: 'fade-preset' }], workbench: {
      role: 'transition', sceneId: 'scene-a', targetSceneId: 'scene-b', entryId: 'entry-b-1', condition: '持有钥匙', mode: 'preset', presetId: 'fade-preset',
    } },
    { id: 'edge-invalid', kind: 'transition', name: '失效目标入口', fields: [], relations: [], workbench: {
      role: 'transition', sceneId: 'scene-a', targetSceneId: 'scene-c', entryId: 'entry-b-1', mode: 'none',
    } },
    { id: 'edge-reverse', kind: 'transition', name: '乙到甲', fields: [], relations: [], workbench: {
      role: 'transition', sceneId: 'scene-b', targetSceneId: 'scene-a', entryId: 'entry-a', mode: 'none',
    } },
  ];
  let serial = 0;
  const notifications = [];
  const reverseOperation = { operationId: 'reverse-operation', kind: 'transition', objectId: 'edge-reverse', from: 'scene-b', sceneId: 'scene-a', entryId: 'entry-a', condition: '等候', mode: '共享预设', presetId: 'marked-preset', scope: '单向场景过渡' };
  const app = {
    selectedObjectId: 'edge-forward', fieldDraftValues: {}, targetNotes: {}, structuralProposals: [reverseOperation],
    objectItems: () => objects,
    newFeedbackId: () => `operation-${++serial}`,
    queueDraftSave: () => {}, notify: text => notifications.push(text),
    readVisibleDraft: () => ({}),
    applyVisibleDraft: state => { app.selectedObjectId = state.selectedObjectId; app.structuralProposals = state.structuralProposals; },
  };
  const wb = new LegacyWorkbench(app);
  wb.render = () => {};
  const dialog = document.querySelector('#workbench-proposal-dialog');
  dialog.showModal = function () { this.open = true; };
  dialog.close = function () { this.open = false; };
  const formField = name => document.querySelector(`#workbench-proposal-form [name="${name}"]`);
  const setSelect = (name, value) => {
    const select = formField(name); assert(select, `${name} selector exists`);
    select.value = value;
    select.dispatchEvent(new dom.window.Event('change', { bubbles: true }));
    return select;
  };

  wb.resetHistory();
  app.selectedObjectId = 'edge-invalid';
  wb.openProposal('transition');
  const invalidEntry = formField('entryId');
  const entryWarning = document.querySelector('.workbench-transition-entry-warning');
  assert.equal(formField('sceneId').value, 'scene-c', 'the destination scene is prefilled from this directed edge');
  assert.equal(invalidEntry.value, 'entry-b-1', 'the invalid published reference remains visible for repair');
  assert(invalidEntry.selectedOptions[0].disabled && invalidEntry.selectedOptions[0].dataset.invalidReference === 'true', 'invalid references are clearly marked and are not offered as legal entries');
  assert(!entryWarning.classList.contains('hidden') && entryWarning.textContent.includes('entry-b-1'), 'the invalid reference has an explicit visible warning');
  const legalEntryIds = [...invalidEntry.options].filter(option => option.value && !option.disabled).map(option => option.value);
  assert.deepEqual(legalEntryIds, ['entry-c'], 'entry choices are restricted to the selected destination scene');
  wb.addProposalFromForm();
  assert.equal(app.structuralProposals.length, 1, 'an invalid retained entry reference cannot be submitted');
  assert.match(notifications.at(-1), /入口引用无效/);
  setSelect('entryId', '');
  assert(entryWarning.classList.contains('hidden'), 'clearing the invalid entry removes its warning');

  app.selectedObjectId = 'edge-forward';
  wb.openProposal('transition');
  assert.equal(wb.pendingProposalObjectId, 'edge-forward', 'the edit remains attached to the exact selected direction');
  assert.equal(formField('from').value, 'scene-a');
  assert.equal(formField('entryId').value, 'entry-b-1');
  assert.equal(formField('condition').value, '持有钥匙');
  assert.equal(formField('mode').value, '共享预设');
  assert.equal(formField('presetId').value, 'fade-preset');
  const presetIds = [...formField('presetId').options].map(option => option.value);
  assert(presetIds.includes('fade-preset') && presetIds.includes('marked-preset') && presetIds.includes('preview-preset'));
  assert(!presetIds.includes('environment-preset'), 'general presets remain excluded');
  setSelect('sceneId', 'scene-c');
  const dynamicEntry = formField('entryId');
  assert.deepEqual([...dynamicEntry.options].filter(option => option.value && !option.disabled).map(option => option.value), ['entry-c'], 'changing destination replaces the selectable entries with only that scene’s entries');
  assert(!document.querySelector('.workbench-transition-entry-warning').classList.contains('hidden'), 'changing destination preserves the now-invalid old reference with a warning');
  setSelect('sceneId', 'scene-b');
  assert.equal(formField('entryId').value, 'entry-b-1', 'returning to the original destination restores the valid entry choice');
  assert(document.querySelector('.workbench-transition-entry-warning').classList.contains('hidden'));

  wb.addProposalFromForm();
  assert.equal(app.structuralProposals.length, 1, 'submitting the published values creates no unchanged transition operation');
  assert.match(notifications.at(-1), /没有新增净变化/);

  wb.openProposal('transition');
  const initialHistoryLength = wb.history.length;
  setSelect('mode', '无过渡');
  wb.addProposalFromForm();
  let forward = app.structuralProposals.filter(item => item.kind === 'transition' && item.objectId === 'edge-forward');
  assert.equal(forward.length, 1, 'the forward transition has only one operation after editing');
  assert.equal(forward[0].mode, '无过渡');
  assert(!Object.hasOwn(forward[0], 'presetId'), 'leaving shared-preset mode removes its preset reference');
  assert.equal(app.structuralProposals.find(item => item.objectId === 'edge-reverse'), reverseOperation, 'editing one direction leaves the reverse proposal untouched');
  assert.equal(wb.history.length, initialHistoryLength + 1, 'adding a transition change is one undoable history step');
  const firstOperationId = forward[0].operationId;
  const firstLabel = wb.operationLabel(forward[0]);
  assert(firstLabel.includes('共享预设 · 淡入淡出') && firstLabel.includes('→') && firstLabel.includes('无过渡'), 'the operation label shows the published-to-proposed mode change');

  wb.openProposal('transition');
  assert.equal(formField('mode').value, '无过渡', 'reopening the edge pre-fills its pending operation');
  const updateHistoryLength = wb.history.length;
  formField('condition').value = '再确认钥匙';
  wb.addProposalFromForm();
  forward = app.structuralProposals.filter(item => item.kind === 'transition' && item.objectId === 'edge-forward');
  assert.equal(forward.length, 1, 'editing an existing edge updates its operation instead of appending a conflicting duplicate');
  assert.equal(forward[0].operationId, firstOperationId, 'an updated edge operation keeps its stable identity');
  assert.equal(forward[0].condition, '再确认钥匙');
  assert.equal(wb.history.length, updateHistoryLength + 1, 'updating an existing operation is one undoable history step');
  await wb.undo();
  assert.equal(app.structuralProposals.find(item => item.objectId === 'edge-forward').condition, '持有钥匙', 'undo restores the prior edge operation in one step');
  await wb.redo();
  assert.equal(app.structuralProposals.find(item => item.objectId === 'edge-forward').condition, '再确认钥匙', 'redo reapplies the updated edge operation in one step');

  wb.openProposal('transition');
  const removalHistoryLength = wb.history.length;
  setSelect('mode', '共享预设');
  setSelect('presetId', 'fade-preset');
  formField('condition').value = '持有钥匙';
  wb.addProposalFromForm();
  assert.equal(app.structuralProposals.filter(item => item.objectId === 'edge-forward').length, 0, 'returning to the published shared-preset state removes the now-empty net change');
  assert.deepEqual(app.structuralProposals.find(item => item.objectId === 'edge-reverse'), reverseOperation, 'reverting the forward edge still leaves its reverse independent');
  assert.equal(wb.history.length, removalHistoryLength + 1, 'reverting a transition change is one undoable history step');
  await wb.undo();
  assert.equal(app.structuralProposals.find(item => item.objectId === 'edge-forward').condition, '再确认钥匙', 'undo restores the removed pending edge change');
  await wb.redo();
  assert.equal(app.structuralProposals.some(item => item.objectId === 'edge-forward'), false, 'redo removes the transition change again');

  wb.stopPreview();
  dom.window.close();
  console.log('PASS Studio transition operation QA: scoped entry choices, invalid-reference repair, net transition states, direction isolation, and single-step updates');
})().catch(error => { console.error(error.stack || error); process.exitCode = 1; dom.window.close(); });
