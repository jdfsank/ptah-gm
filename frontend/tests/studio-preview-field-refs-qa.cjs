#!/usr/bin/env node
/* Focused QA for data-driven Studio preview speed and stage duration references. */
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const { pathToFileURL } = require('node:url');
let JSDOM;
try { ({ JSDOM } = require('jsdom')); }
catch { console.log('SKIP Studio preview field-reference QA: jsdom is unavailable.'); process.exit(0); }

const root = path.resolve(__dirname, '..');
const dom = new JSDOM(fs.readFileSync(path.join(root, 'studio/index.html'), 'utf8'), {
  url: 'http://127.0.0.1:8123/studio/?project=preview-field-refs', pretendToBeVisual: true,
});
global.document = dom.window.document;
global.localStorage = dom.window.localStorage;

(async () => {
  const { LegacyWorkbench } = await import(pathToFileURL(path.join(root, 'studio/workbench.js')).href);
  const object = {
    id: 'motion-object', name: '运动对象', fields: [
      { id: 'speed', label: '巡航速度', type: 'number', value: 4, unit: '米/秒' },
      { id: 'warning-time', label: '预告时长', type: 'integer', value: 2 },
    ],
    workbench: { role: 'behavior', provenance: { kind: 'fact' }, preview: {
      type: 'motion', label: '对象运动', speed: 6, speedFieldId: 'speed', stages: [
        { label: '预告', duration: 3, durationFieldId: 'warning-time' },
        { label: '淡出', duration: 0.75 },
      ],
    } },
  };
  const app = { selectedObjectId: object.id, fieldDraftValues: {}, objectItems: () => [object], targetNotes: {}, structuralProposals: [] };
  const wb = new LegacyWorkbench(app);
  const previewRoot = document.querySelector('#workbench-preview');
  const speedText = () => previewRoot.querySelector('.workbench-preview-speed')?.textContent;
  const timelineTexts = () => [...previewRoot.querySelectorAll('.workbench-timeline small')].map(item => item.textContent);

  wb.renderPreview();
  assert.equal(speedText(), '巡航速度：4 米/秒', 'without a draft, the referenced property value takes priority over metadata speed');
  assert.deepEqual(timelineTexts(), ['2 秒', '0.75 秒'], 'the timeline uses the referenced integer property and the unlinked static stage duration');

  app.fieldDraftValues = { 'motion-object.speed': 9, 'motion-object.warning-time': 5 };
  wb.renderPreview();
  assert.equal(speedText(), '巡航速度：9 米/秒', 'a draft value overrides the referenced property and preview metadata');
  assert.deepEqual(timelineTexts(), ['5 秒', '0.75 秒'], 'the timeline reflects the draft duration');

  app.fieldDraftValues['motion-object.warning-time'] = 2.5;
  app.fieldDraftValues['motion-object.speed'] = -1;
  wb.renderPreview();
  assert.equal(speedText(), undefined, 'an invalid negative draft is unknown rather than displayed as the published property');
  assert.deepEqual(timelineTexts(), ['时长未提供', '0.75 秒'], 'an invalid integer draft never becomes a valid timeline duration');
  assert.equal(previewRoot.querySelector('[data-workbench-action="play-preview"]').disabled, true, 'unknown timing cannot be played with a fabricated fallback duration');
  app.fieldDraftValues['motion-object.speed'] = 9;
  app.fieldDraftValues['motion-object.warning-time'] = 5;

  const fallback = wb.resolvePreview({ ...object, fields: [] });
  assert.equal(fallback.speed, 6, 'when a referenced field is unavailable, speed falls back to preview.speed');
  assert.deepEqual(fallback.stages.map(stage => stage.duration), [3, 0.75], 'referenced durations fall back to stage.duration');
  assert.equal(object.workbench.preview.speed, 6, 'resolving preview values never mutates the source metadata');
  assert.equal(object.workbench.preview.stages[0].duration, 3);
  assert.equal(wb.resolvePreviewFieldValue({ ...object, fields: [{ id: 'speed', type: 'text', value: '9' }] }, 'speed', 6).value,
    null, 'a wrong-type bound field remains unknown instead of being presented as a valid static speed');

  const catalogMotion = {
    id: 'catalog-motion', name: '目录中的运动对象', fields: [],
    workbench: { role: 'behavior', provenance: { kind: 'fact' }, preview: object.workbench.preview },
  };
  const documentMotion = { ...catalogMotion, fields: object.fields };
  app.objectItems = () => [catalogMotion];
  app.snapshot = { document: { objects: [documentMotion] } };
  app.selectedObjectId = catalogMotion.id;
  app.fieldDraftValues = {};
  wb.renderPreview();
  assert.equal(speedText(), '巡航速度：4 米/秒', 'when the catalog object omits fields, the published document supplies the same-ID field value');
  assert.deepEqual(timelineTexts(), ['2 秒', '0.75 秒'], 'the published document field also supplies the timeline duration');
  app.fieldDraftValues = { 'catalog-motion.speed': 9, 'catalog-motion.warning-time': 5 };
  wb.renderPreview();
  assert.equal(speedText(), '巡航速度：9 米/秒', 'draft values remain keyed to the stable catalog object ID');
  assert.deepEqual(timelineTexts(), ['5 秒', '0.75 秒'], 'document-backed preview fields resolve the current draft duration');

  const dynamicFields = document.querySelector('#dynamic-fields');
  const durationInput = document.createElement('input');
  durationInput.dataset.fieldId = 'catalog-motion.warning-time'; durationInput.dataset.type = 'integer';
  dynamicFields.append(durationInput);
  wb.bind();
  dynamicFields.addEventListener('input', event => {
    if (event.target?.dataset?.fieldId) app.fieldDraftValues[event.target.dataset.fieldId] = Number(event.target.value);
  });

  const scheduled = [], cleared = [];
  const originalSetTimeout = globalThis.setTimeout, originalClearTimeout = globalThis.clearTimeout;
  globalThis.setTimeout = (callback, delay) => { scheduled.push({ callback, delay }); return scheduled.length; };
  globalThis.clearTimeout = id => { cleared.push(id); };
  try {
    wb.playPreview();
    assert.equal(scheduled[0].delay, 5000, 'the current playback timer uses the displayed duration');
    durationInput.value = '2'; durationInput.dispatchEvent(new dom.window.Event('input', { bubbles: true }));
    await Promise.resolve();
    assert.equal(app.fieldDraftValues['catalog-motion.warning-time'], 2, 'the field input handler captures the latest value before preview rendering');
    assert.equal(wb.playingTargetId, null, 'editing a preview-backed field stops the prior playback timer');
    assert(cleared.includes(1), 'editing the preview-backed field cancels the stale timer');
    assert.deepEqual(timelineTexts(), ['2 秒', '0.75 秒'], 'a real input event immediately updates the preview timeline');

    let playbackStart = scheduled.length;
    wb.playPreview();
    assert.equal(scheduled[playbackStart].delay, 2000, 'playback uses the newly entered duration');
    const stop = previewRoot.querySelector('[data-workbench-action="stop-preview"]');
    stop.click();
    assert.equal(wb.playingTargetId, null, 'the Stop action clears playback state');
    assert(cleared.includes(playbackStart + 1), 'the Stop action cancels the active timer');
    assert.equal(previewRoot.querySelector('[data-workbench-action="play-preview"]').textContent, '播放示意', 'stopping rerenders the playback controls');
    assert.equal(previewRoot.querySelector('[data-workbench-action="stop-preview"]').disabled, true, 'the rerendered Stop control is disabled');

    durationInput.value = '5'; durationInput.dispatchEvent(new dom.window.Event('input', { bubbles: true }));
    await Promise.resolve();
    assert.deepEqual(timelineTexts(), ['5 秒', '0.75 秒'], 'a later input replaces the old timeline value');
    playbackStart = scheduled.length;
    wb.playPreview();
    assert.equal(scheduled[playbackStart].delay, 5000, 'playback schedules from the same resolved duration displayed by the timeline');
    assert.deepEqual(timelineTexts(), ['5 秒', '0.75 秒']);
    scheduled[playbackStart].callback();
    assert.equal(scheduled[playbackStart + 1].delay, 750, 'the next stage timer uses its resolved static duration');
    assert.deepEqual(timelineTexts(), ['5 秒', '0.75 秒']);
    scheduled[playbackStart + 1].callback();
    assert.equal(wb.playingTargetId, null, 'playback stops when the resolved stage sequence completes');
  } finally {
    if (wb.historyTimer != null) { globalThis.clearTimeout(wb.historyTimer); wb.historyTimer = null; }
    globalThis.setTimeout = originalSetTimeout;
    globalThis.clearTimeout = originalClearTimeout;
    wb.stopPreview();
    dom.window.close();
  }
  console.log('PASS Studio preview field-reference QA: field fallbacks, live input refresh, stale timer cancellation, Stop rerender, and timeline/playback alignment');
})().catch(error => { console.error(error.stack || error); process.exitCode = 1; dom.window.close(); });
