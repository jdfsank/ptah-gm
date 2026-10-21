#!/usr/bin/env node
/* Focused N2 coverage for cross-tab draft conflicts and restoring each input. */
const fs = require('node:fs');
const path = require('node:path');
const strict = require('node:assert/strict');
const { pathToFileURL } = require('node:url');
let JSDOM;
try { ({ JSDOM } = require('jsdom')); } catch { console.log('SKIP Studio N2 cross-tab draft QA: jsdom is unavailable.'); process.exit(0); }

const root = path.resolve(__dirname, '..');
class SharedStorage {
  constructor() { this.values = new Map(); }
  get length() { return this.values.size; }
  key(index) { return [...this.values.keys()][index] ?? null; }
  getItem(key) { return this.values.has(String(key)) ? this.values.get(String(key)) : null; }
  setItem(key, value) { this.values.set(String(key), String(value)); }
  removeItem(key) { this.values.delete(String(key)); }
}
const tick = () => new Promise(resolve => setTimeout(resolve, 0));
const projectId = 'n2-project';
const project = { id: projectId, title: '双标签草稿', workflow: 'template-v1' };
const snapshot = { id: 'n2-snapshot', projectId, publicationRevision: 7, sourceCommit: 'n2-source',
  workflow: 'template-v1', kind: 'MVP', playable: true, decisions: {}, catalog: { objects: [] } };
const calls = [];
let nextWorkbenchResponse = null, nextWorkbenchError = null, nextWorkbenchPending = null;
const fetchImpl = async (url, init = {}) => {
  calls.push({ url, method: init.method || 'GET' });
  if ((init.method || 'GET') !== 'GET') throw new Error('N2 draft actions must not start or submit Agent work.');
  if (String(url).endsWith(`/projects/${projectId}/workbench`)) {
    if (nextWorkbenchPending) { const pending = nextWorkbenchPending; nextWorkbenchPending = null; return pending; }
    if (nextWorkbenchError) { const error = nextWorkbenchError; nextWorkbenchError = null; throw error; }
    if (nextWorkbenchResponse) {
      const result = nextWorkbenchResponse; nextWorkbenchResponse = null;
      return { ok: true, status: 200, text: async () => JSON.stringify(result) };
    }
  }
  return { ok: false, status: 404, text: async () => '{"error":"unexpected read"}' };
};
class AutoStorageEventHub {
  constructor(storageKey) { this.storageKey = storageKey; this.values = new Map(); this.ports = []; this.queue = []; this.writes = []; this.failNextWrite = false; }
  port(handle) {
    const hub = this;
    const port = { handle,
      get length() { return hub.values.size; },
      key(index) { return [...hub.values.keys()][index] ?? null; },
      getItem(key) { return hub.values.get(String(key)) ?? null; },
      setItem(key, value) {
        key = String(key); value = String(value);
        const oldValue = hub.values.get(key) ?? null;
        if (oldValue === value) return;
        if (key === hub.storageKey && hub.failNextWrite) { hub.failNextWrite = false; throw new Error('controlled storage write failure'); }
        hub.values.set(key, value);
        if (key !== hub.storageKey) return;
        hub.writes.push({ by: handle.name, record: JSON.parse(value) });
        for (const other of hub.ports) if (other !== port) hub.queue.push({ to: other.handle, key, oldValue, newValue: value });
      },
      removeItem(key) { hub.values.delete(String(key)); },
    };
    this.ports.push(port); return port;
  }
  async drain(limit = 1000) {
    let delivered = 0;
    while (this.queue.length && delivered < limit) {
      const event = this.queue.shift(), handle = event.to;
      for (const key of ['document', 'location', 'history', 'FormData', 'Option', 'HTMLElement']) global[key] = handle.dom.window[key];
      handle.eventPromise = null;
      handle.dom.window.dispatchEvent(new handle.dom.window.StorageEvent('storage', {
        key: event.key, oldValue: event.oldValue, newValue: event.newValue, url: 'http://127.0.0.1:8123/studio/',
      }));
      if (handle.eventPromise) await handle.eventPromise;
      delivered++;
    }
    return { delivered, remaining: this.queue.length };
  }
}
const objectProjectId = 'n2-object-project';
const objectProject = { id: objectProjectId, title: '跨标签对象草稿', workflow: 'objects-v1' };
const objectSnapshot = { id: 'n2-object-snapshot', projectId: objectProjectId, publicationRevision: 11,
  sourceCommit: 'n2-object-source', baseCommit: 'n2-object-base', workflow: 'objects-v1', kind: 'MVP', playable: true,
  decisions: {}, catalog: { objects: [
    { id: 'hero', kind: 'entity', name: '角色', fields: [{ id: 'speed', label: '速度', type: 'scalar', value: 220 }] },
    { id: 'guard-one', kind: 'entity', name: '守卫实例', workbench: { role: 'instance', definitionId: 'hero' } },
  ] } };
const objectCapabilities = { fields: [
  { id: 'hero.speed', objectId: 'hero', fieldId: 'speed', label: '速度', type: 'scalar', value: 220, editable: true, min: 0, max: 500, step: 1 },
] };
const objectKey = `n2-store:${objectProjectId}:iteration:${objectSnapshot.publicationRevision}`;
const objectStorageKey = `ptah-studio-draft-v2:${objectKey}`;
const objectBase = { key: objectKey, projectId: objectProjectId, publicationRevision: objectSnapshot.publicationRevision,
  sourceCommit: objectSnapshot.sourceCommit, baseCommit: objectSnapshot.baseCommit, draftRevision: 1,
  text: '角色原始意见', values: {}, fields: { 'hero.speed': 280 }, feedback: [], feedbackInputs: {},
  feedbackInputTargetId: null, legacyUnboundFeedback: null, feedbackMessage: '', feedbackCategory: 'general', selectedObjectId: 'hero',
  targetNotes: { hero: { objectId: 'hero', text: '角色原始意见', feedbackId: 'hero-note', updatedAt: '2026-10-15T00:00:00.000Z' },
    'guard-one': { objectId: 'guard-one', text: '守卫实例原文', feedbackId: 'guard-note', updatedAt: '2026-10-15T00:00:00.000Z' } },
  structuralProposals: [{ operationId: 'base-operation-01', kind: 'new-scene', name: '基础场景', sceneId: 'base-scene-01', width: 640, height: 480 }],
  proposalInputs: {}, draftConflictAlternates: [] };
const objectDraft = (label, { selectedObjectId = 'hero', speed = 280, operationId = 'base-operation-01', noteTarget = selectedObjectId,
  noteText = `${label}角色意见`, text = noteText, feedback = [] } = {}) => ({ ...structuredClone(objectBase), text, selectedObjectId,
  fields: { 'hero.speed': speed }, feedback: structuredClone(feedback),
  targetNotes: { ...structuredClone(objectBase.targetNotes), [selectedObjectId || '__project__']: {
    objectId: noteTarget || null, text: noteText, feedbackId: `${label}-note`, updatedAt: `2026-10-16T00:00:00.000Z`,
  } }, structuralProposals: [{ operationId, kind: 'new-scene', name: `${label}练习场`, sceneId: `${operationId}-scene`, width: 960, height: 640 }],
  draftConflictAlternates: [] });

async function runR08SingleWriterQA(StudioApp, DraftStore) {
  const saved = Object.fromEntries(['document', 'location', 'history', 'window', 'Option', 'FormData', 'HTMLElement'].map(key => [key, global[key]]));
  const evidenceDir = path.resolve(root, '../evidence/workflow/studio-trial-fix-cycle-20261016/round-08');
  const startDraft = JSON.parse(fs.readFileSync(path.join(evidenceDir, 'start-visible-current-draft.json'), 'utf8'));
  const expectedDraft = JSON.parse(fs.readFileSync(path.join(evidenceDir, 'final-visible-current-draft.json'), 'utf8'));
  const isolatedProjectId = 'r08-isolated-project', isolatedStoreId = 'r08-isolated-store';
  const isolatedKey = `${isolatedStoreId}:${isolatedProjectId}:iteration:4`;
  const isolatedStorageKey = `ptah-studio-draft-v2:${isolatedKey}`;
  const isolatedProject = { id: isolatedProjectId, title: 'R08 隔离内存项目', workflow: 'objects-v1', publicationRevision: 4 };
  const isolatedSnapshot = {
    id: 'r08-isolated-snapshot', projectId: isolatedProjectId, publicationRevision: 4,
    sourceCommit: 'r08-isolated-source', baseCommit: 'r08-isolated-base', workflow: 'objects-v1',
    kind: 'MVP', playable: true, decisions: {},
    catalog: { objects: [
      { id: 'arena-scene', name: '赌场战斗场景', kind: 'scene', fields: [], relations: [], workbench: { role: 'scene', scope: 'scene', bounds: [1152, 768] } },
      { id: 'player-arena-instance', name: '赌场游侠 · 战斗场景实例', kind: 'entity', fields: [], relations: [], workbench: { role: 'instance', sceneId: 'arena-scene', definitionId: 'player', scope: 'scene' } },
      { id: 'player', name: '赌场游侠', kind: 'entity', fields: [
        { id: 'move-speed', label: '移动速度', type: 'scalar', value: 300 },
        { id: 'max-health', label: '初始生命', type: 'integer', value: 130 },
      ], relations: [], workbench: { role: 'definition' } },
      { id: 'dice-burst', name: '骰子落点与 burst 筹码', kind: 'system', fields: [
        { id: 'warning-duration', label: '落点预告时长', type: 'scalar', value: 2.5 },
        { id: 'reward-lifetime', label: 'burst 筹码存在时长', type: 'scalar', value: 9 },
      ], relations: [], workbench: { role: 'system' } },
    ], capabilities: [
      { id: 'player.move-speed', objectId: 'player', fieldId: 'move-speed', label: '移动速度', type: 'scalar', editable: true, value: 300, min: 0, max: 1000, step: 1 },
      { id: 'player.max-health', objectId: 'player', fieldId: 'max-health', label: '初始生命', type: 'integer', editable: true, value: 130, min: 1, max: 1000, step: 1 },
      { id: 'dice-burst.warning-duration', objectId: 'dice-burst', fieldId: 'warning-duration', label: '落点预告时长', type: 'scalar', editable: true, value: 2.5, min: 0, max: 10, step: 0.5 },
      { id: 'dice-burst.reward-lifetime', objectId: 'dice-burst', fieldId: 'reward-lifetime', label: 'burst 筹码存在时长', type: 'scalar', editable: true, value: 9, min: 1, max: 20, step: 1 },
    ] },
  };
  const memoryStorage = new SharedStorage();
  const isolatedStart = { ...structuredClone(startDraft), key: isolatedKey, projectId: isolatedProjectId,
    publicationRevision: 4, sourceCommit: isolatedSnapshot.sourceCommit, baseCommit: isolatedSnapshot.baseCommit, draftRevision: 1 };
  memoryStorage.setItem(isolatedStorageKey, JSON.stringify(isolatedStart));
  const trace = { cas: [], baselines: [], fetches: [], refresh: null };
  let activeApp = null, activeDom = null;
  const makeIsolatedApp = async () => {
    const dom = new JSDOM(fs.readFileSync(path.join(root, 'studio/index.html'), 'utf8'), {
      url: `http://127.0.0.1:8123/studio/?project=${isolatedProjectId}&stage=iteration&target=dice-burst&view=design&scene=arena-scene`,
      pretendToBeVisual: true,
    });
    for (const dialog of dom.window.document.querySelectorAll('dialog')) {
      dialog.showModal = function () { this.open = true; };
      dialog.close = function () { this.open = false; };
    }
    global.document = dom.window.document; global.location = dom.window.location;
    global.history = dom.window.history; global.window = dom.window;
    for (const key of ['Option', 'FormData', 'HTMLElement']) global[key] = dom.window[key];
    const fetchImpl = async (url, init = {}) => {
      const method = init.method || 'GET'; trace.fetches.push({ method, url: String(url) });
      if (method !== 'GET') throw new Error('R08 isolation QA permits reads only; no service writes are available.');
      if (String(url).endsWith(`/projects/${isolatedProjectId}/workbench`)) {
        const nextSnapshot = { ...structuredClone(isolatedSnapshot), catalog: structuredClone(isolatedSnapshot.catalog) };
        return { ok: true, status: 200, text: async () => JSON.stringify({ project: isolatedProject, snapshot: nextSnapshot, workbenchResults: [] }) };
      }
      return { ok: false, status: 404, text: async () => '{"error":"unexpected isolated read"}' };
    };
    const app = new StudioApp({ fetchImpl, documentImpl: dom.window.document, timers: globalThis });
    app.drafts = new DraftStore(null, memoryStorage); await app.drafts.open();
    app.persistenceOK = true; app.workspace = { storeId: isolatedStoreId, projects: [isolatedProject], iterationReady: true };
    app.manager = app.workspace; app.projectId = isolatedProjectId; app.stage = 'iteration';
    const pendingSaves = [];
    const queueDraftSave = app.queueDraftSave.bind(app);
    app.queueDraftSave = (...args) => {
      const promise = queueDraftSave(...args);
      if (promise && typeof promise.then === 'function') pendingSaves.push(promise);
      return promise;
    };
    const flush = async () => {
      while (pendingSaves.length) await Promise.all(pendingSaves.splice(0));
      await tick();
      while (pendingSaves.length) await Promise.all(pendingSaves.splice(0));
    };
    const putIfUnchanged = app.drafts.putIfUnchanged.bind(app.drafts);
    app.drafts.putIfUnchanged = (record, expectedRaw) => {
      const currentRaw = app.drafts.raw(record.key);
      const event = { key: record.key, operationId: app.draftOperationSequence, generation: app.workbenchGeneration,
        expectedEqualsCurrent: currentRaw === expectedRaw, success: false, baselinePaired: false,
        caller: new Error().stack.split('\n').find(line => /studio\.js:\d+:\d+/.test(line)) || null };
      try {
        const result = putIfUnchanged(record, expectedRaw);
        event.success = true; event.serializedEqualsStored = JSON.stringify(record) === app.drafts.raw(record.key);
        event.writtenRaw = app.drafts.raw(record.key); trace.cas.push(event); return result;
      } catch (error) { event.errorName = error.name; trace.cas.push(event); throw error; }
    };
    const updateDraftBaseline = app.updateDraftBaseline.bind(app);
    app.updateDraftBaseline = (key, record, raw) => {
      const operationId = app.draftOperationSequence, generation = app.workbenchGeneration;
      const pairedWrite = [...trace.cas].reverse().find(item => item.success && item.key === key && item.operationId === operationId &&
        item.generation === generation && item.writtenRaw === raw && !item.baselinePaired);
      if (pairedWrite) pairedWrite.baselinePaired = true;
      trace.baselines.push({ key, operationId, generation, rawProvided: raw !== undefined,
        pairsWithSuccessfulWrite: !!pairedWrite, rawEqualsCurrentStorage: app.drafts.raw(key) === raw });
      return updateDraftBaseline(key, record, raw);
    };
    app.bind(); await app.loadWorkbench(isolatedProjectId); await flush();
    activeApp = app; activeDom = dom; return { app, dom, flush };
  };
  const clickTarget = async (dom, app, id, flush) => {
    const button = dom.window.document.querySelector(`#object-catalog [data-object-id="${id}"]`);
    strict.ok(button, `actual Studio navigation exposes target ${id}`); button.click(); await flush();
    strict.equal(app.selectedObjectId, id, `actual navigation selects ${id}`);
  };
  const editNote = async (dom, text, flush) => {
    const editor = dom.window.document.querySelector('#edit-text'); strict.ok(editor && !editor.disabled);
    editor.value = text; editor.dispatchEvent(new dom.window.Event('input', { bubbles: true })); await flush();
  };
  const editField = async (dom, fieldId, value, flush) => {
    const control = dom.window.document.querySelector(`#dynamic-fields [data-field-id="${fieldId}"]`);
    strict.ok(control && !control.disabled, `declared field ${fieldId} is editable`);
    control.value = String(value); control.dispatchEvent(new dom.window.Event('input', { bubbles: true })); await flush();
  };

  try {
    let { app, dom, flush } = await makeIsolatedApp();
    strict.equal(app.draftKey, isolatedKey); strict.equal(app.selectedObjectId, 'dice-burst');
    strict.deepEqual(JSON.parse(memoryStorage.getItem(isolatedStorageKey)).targetNotes, startDraft.targetNotes,
      'startup recovery retains the full original notes and identities');
    strict.equal(app.draftStorageBaseline, memoryStorage.getItem(isolatedStorageKey), 'startup pairs the exact raw baseline');

    await clickTarget(dom, app, 'arena-scene', flush);
    await clickTarget(dom, app, 'player-arena-instance', flush);
    await editNote(dom, expectedDraft.targetNotes['player-arena-instance'].text, flush);
    await clickTarget(dom, app, 'player', flush);
    await editNote(dom, expectedDraft.targetNotes.player.text, flush);
    await editField(dom, 'player.move-speed', 280, flush);
    await editField(dom, 'player.max-health', 120, flush);
    await clickTarget(dom, app, 'arena-scene', flush);
    await clickTarget(dom, app, 'dice-burst', flush);
    await editNote(dom, expectedDraft.targetNotes['dice-burst'].text, flush);
    await editField(dom, 'dice-burst.warning-duration', 3, flush);
    await editField(dom, 'dice-burst.reward-lifetime', 10, flush);

    const beforeRefreshRaw = memoryStorage.getItem(isolatedStorageKey), generationBefore = app.workbenchGeneration;
    await app.loadWorkbench(isolatedProjectId); await flush();
    trace.refresh = { generationBefore, generationAfter: app.workbenchGeneration, keyAfter: app.draftKey,
      rawUnchangedByRead: memoryStorage.getItem(isolatedStorageKey) === beforeRefreshRaw,
      pendingConflict: !!app.pendingDraftConflict };
    strict.equal(app.workbenchGeneration, generationBefore + 1, 'same-version status response advances the page generation');
    strict.equal(app.draftKey, isolatedKey); strict.equal(memoryStorage.getItem(isolatedStorageKey), beforeRefreshRaw);
    strict.equal(app.pendingDraftConflict, null, 'same-version response handoff opens no conflict');
    await clickTarget(dom, app, 'dice-burst', flush);
    strict.equal(await app.saveDraft(), true, 'the next ordinary save succeeds after the status response handoff');

    const activeRecord = JSON.parse(memoryStorage.getItem(isolatedStorageKey));
    strict.deepEqual(activeRecord.fields, expectedDraft.fields, 'all four requested field values are active');
    for (const id of ['player', 'player-arena-instance', 'dice-burst']) {
      const before = startDraft.targetNotes[id], after = activeRecord.targetNotes[id];
      strict.equal(after.text, expectedDraft.targetNotes[id].text, `${id} contains the full expected appended note`);
      strict.ok(after.text.startsWith(before.text), `${id} retains its entire original text`);
      strict.equal(after.feedbackId, before.feedbackId, `${id} feedbackId remains stable`);
      strict.equal(after.objectId, before.objectId, `${id} objectId remains stable`);
    }
    for (const [id, note] of Object.entries(startDraft.targetNotes)) {
      if (!['player', 'player-arena-instance', 'dice-burst'].includes(id)) strict.deepEqual(activeRecord.targetNotes[id], note, `untouched note ${id} remains complete`);
    }
    strict.equal(Object.keys(activeRecord.targetNotes).length, Object.keys(startDraft.targetNotes).length);
    strict.deepEqual(activeRecord.structuralProposals, startDraft.structuralProposals, 'all original structures remain complete');
    strict.deepEqual(activeRecord.draftConflictAlternates, startDraft.draftConflictAlternates, 'all 64 retained objects remain complete');
    strict.ok(trace.cas.length >= 7, 'the actual chain performed multiple conditional writes');
    strict.ok(trace.cas.every(item => item.key === isolatedKey && item.expectedEqualsCurrent && item.success && item.serializedEqualsStored),
      'every chain CAS observed equal expected/current raw bytes and stored its own serialization');
    strict.ok(trace.cas.every(item => item.operationId > 0 && item.generation > 0 && item.caller),
      'each CAS records the real operation ID, workbench generation, and Studio call site');
    strict.ok(trace.cas.every(item => item.baselinePaired), 'every successful CAS advanced its exact same-operation raw baseline');
    strict.ok(trace.baselines.some(item => item.pairsWithSuccessfulWrite && item.rawEqualsCurrentStorage), 'baseline trace confirms exact write/raw pairing');
    strict.equal(trace.fetches.some(item => item.method !== 'GET'), false, 'no service write or submission was attempted');

    const rawBeforeReload = memoryStorage.getItem(isolatedStorageKey), chainCasCount = trace.cas.length;
    if (activeApp.legacyWorkbench?.historyTimer != null) global.clearTimeout(activeApp.legacyWorkbench.historyTimer);
    activeApp.destroy(); activeApp = null; activeDom.window.close(); activeDom = null;
    ({ app, dom, flush } = await makeIsolatedApp());
    const reloadedRecord = app.currentDraftRecord();
    strict.equal(memoryStorage.getItem(isolatedStorageKey), rawBeforeReload, 'a fresh app reload reads the active raw record without modifying it');
    strict.ok(app.sameDraftContent(reloadedRecord, activeRecord), 'same-storage reload restores the exact active business content');
    strict.deepEqual(reloadedRecord.targetNotes, activeRecord.targetNotes, 'reload keeps every full note and identity');
    strict.deepEqual(reloadedRecord.fields, activeRecord.fields, 'reload restores all four edited fields');
    strict.deepEqual(reloadedRecord.structuralProposals, activeRecord.structuralProposals, 'reload keeps all original structures');
    strict.deepEqual(reloadedRecord.draftConflictAlternates, activeRecord.draftConflictAlternates, 'reload keeps all 64 complete retained versions');
    strict.equal(dom.window.document.querySelector('#edit-text').value, activeRecord.targetNotes['dice-burst'].text,
      'the ordinary route reload shows the active draft text rather than restoring a retained version');
    strict.equal(trace.cas.length, chainCasCount, 'ordinary reload did not need to rewrite the active draft');
    const sameStorageReloadVerified = app.sameDraftContent(reloadedRecord, activeRecord);

    app.legacyWorkbench.openProposal('new-scene');
    const proposalName = 'R08 本地空态回归场景';
    dom.window.document.querySelector('#workbench-proposal-form [name="name"]').value = proposalName;
    dom.window.document.querySelector('#workbench-proposal-form').dispatchEvent(new dom.window.Event('submit', { bubbles: true, cancelable: true }));
    await flush();
    const localScene = app.structuralProposals.at(-1), localSceneId = localScene.sceneId;
    strict.equal(localScene.kind, 'new-scene');
    strict.equal(app.selectedObjectId, localSceneId, 'creating a local scene selects its draft target');
    strict.equal(app.legacyWorkbench.draftTarget(localSceneId).name, proposalName, 'the selected local target resolves to the proposal');
    strict.match(dom.window.document.querySelector('#selected-object-label').textContent, new RegExp(proposalName), 'the current target label names the selected local proposal');
    strict.match(dom.window.document.querySelector('#dynamic-fields').textContent, /此本地提案当前没有服务声明可编辑的属性/, 'the local scene shows its local-proposal empty state');
    strict.match(dom.window.document.querySelector('#dynamic-fields').textContent, /可以继续编辑本目标意见/, 'the empty state explains that target notes remain editable');
    const sceneNote = `${proposalName}的本地意见全文，继续保留本目标身份。`;
    await editNote(dom, sceneNote, flush);
    const sceneRecord = JSON.parse(memoryStorage.getItem(isolatedStorageKey));
    strict.equal(sceneRecord.targetNotes[localSceneId].text, sceneNote, 'a local scene opinion edits and saves against the proposal target');
    strict.equal(sceneRecord.targetNotes[localSceneId].objectId, localSceneId, 'the local opinion remains bound to the selected scene ID');
    const selectedSceneId = app.selectedObjectId;
    app.selectedObjectId = null; app.renderDynamicFields(app.objectItems(), app.capabilities);
    strict.match(dom.window.document.querySelector('#dynamic-fields').textContent, /请选择对象查看可编辑属性/, 'a truly unselected target keeps the ordinary selection prompt');
    app.selectedObjectId = selectedSceneId; app.renderDynamicFields(app.objectItems(), app.capabilities);

    // These raw mutations are explicit in-memory regression controls, not reproductions of the original R08 failure.
    const beforeEnvelope = JSON.parse(memoryStorage.getItem(isolatedStorageKey));
    const envelopeBranch = { label: 'R08 envelope-only memory control', capturedAt: '2026-10-17T00:00:00.000Z', draft: structuredClone(startDraft) };
    const envelopeOnly = { ...beforeEnvelope, draftRevision: beforeEnvelope.draftRevision + 1, updatedAt: '2026-10-17T00:00:01.000Z',
      draftConflictAlternates: [...beforeEnvelope.draftConflictAlternates, envelopeBranch] };
    memoryStorage.setItem(isolatedStorageKey, JSON.stringify(envelopeOnly));
    await editNote(dom, `${sceneNote}\n信封漂移后继续输入，保留整段意见。`, flush);
    const afterEnvelope = JSON.parse(memoryStorage.getItem(isolatedStorageKey));
    strict.equal(app.pendingDraftConflict, null, 'a retained-branch-only envelope drift does not interrupt the local edit');
    strict.ok(app.sameDraftContent(afterEnvelope, app.currentDraftRecord()), 'the continued local input becomes active after envelope-only coordination');
    strict.ok(afterEnvelope.draftConflictAlternates.some(item => item.label === envelopeBranch.label && app.sameDraftContent(item.draft, startDraft)),
      'envelope-only coordination preserves the complete incoming retained branch');
    strict.equal(app.draftStorageBaseline, memoryStorage.getItem(isolatedStorageKey), 'envelope coordination pairs its exact merged raw baseline');

    const independentLocalText = `${dom.window.document.querySelector('#edit-text').value}\n独立分歧控制：本页另有完整意见。`;
    const independentRemote = JSON.parse(memoryStorage.getItem(isolatedStorageKey));
    const originalDiceNote = independentRemote.targetNotes['dice-burst'];
    independentRemote.targetNotes['dice-burst'] = { ...originalDiceNote,
      text: `${originalDiceNote.text}\n独立分歧控制：内存中的另一写入者修改了骰子意见。`,
      updatedAt: '2026-10-17T00:00:02.000Z' };
    independentRemote.draftRevision += 1; independentRemote.updatedAt = '2026-10-17T00:00:02.000Z';
    memoryStorage.setItem(isolatedStorageKey, JSON.stringify(independentRemote));
    const pendingEditor = dom.window.document.querySelector('#edit-text'); pendingEditor.value = independentLocalText;
    pendingEditor.dispatchEvent(new dom.window.Event('input', { bubbles: true })); await flush();
    strict.ok(app.pendingDraftConflict, 'one explicit independent-content memory control still requires comparison');
    strict.match(dom.window.document.querySelector('#draft-conflict-dialog .draft-conflict-semantic').textContent, /存储活动稿/, 'the normal conflict comparison labels the remote side as the stored active draft');
    strict.equal(dom.window.document.querySelector('#draft-conflict-dialog [data-draft-conflict-action="keep-local"]').textContent, '保留本页当前稿');
    strict.equal(dom.window.document.querySelector('#draft-conflict-dialog [data-draft-conflict-action="use-remote"]').textContent, '采用存储活动稿');
    const protectedRecord = JSON.parse(memoryStorage.getItem(isolatedStorageKey));
    strict.equal(protectedRecord.targetNotes['dice-burst'].text, independentRemote.targetNotes['dice-burst'].text,
      'the explicit independent remote content remains active instead of being overwritten');
    strict.ok(protectedRecord.draftConflictAlternates.some(item => item.draft.targetNotes[localSceneId]?.text === independentLocalText),
      'the full unsaved local scene opinion is retained as a comparison branch');
    strict.equal(app.pendingDraftConflict.remote.targetNotes['dice-burst'].text, independentRemote.targetNotes['dice-burst'].text,
      'the complete independent remote opinion remains visible in the comparison');
    strict.equal(trace.fetches.some(item => item.method !== 'GET'), false, 'the memory regression controls still made no service writes');

    app.pendingDraftConflict = null;
    app.openDraftConflict();
    strict.ok(app.pendingDraftConflict?.recovery, 'opening a retained version uses the explicit recovery comparison path');
    const recoveryDialog = dom.window.document.querySelector('#draft-conflict-dialog');
    strict.match(recoveryDialog.querySelector('.draft-conflict-semantic').textContent, /所选保留稿/, 'recovery comparison labels the chosen branch rather than calling it active');
    strict.equal(recoveryDialog.querySelector('[data-draft-conflict-action="use-remote"]').textContent, '恢复这份保留稿');

    console.log(JSON.stringify({ result: 'single-writer mechanism not reproduced',
      chain: ['startup restore', 'dice-burst', 'published scene', 'battle instance', 'shared player definition',
        'three full note appends', 'four field edits', 'same-version status response', 'ordinary save', 'same-storage reload',
        'local-scene note edit', 'envelope-only control', 'independent-divergence memory control'],
      cas: trace.cas.map(({ key, operationId, generation, expectedEqualsCurrent, success, baselinePaired, caller }) =>
        ({ key, operationId, generation, expectedEqualsCurrent, success, baselinePaired, caller })),
      refresh: trace.refresh,
      retained: { notes: Object.keys(activeRecord.targetNotes).length,
        structures: activeRecord.structuralProposals.length, fullBranches: activeRecord.draftConflictAlternates.length },
      fields: activeRecord.fields, reloaded: sameStorageReloadVerified,
      localSceneTarget: localSceneId, controls: { envelopeOnlyDidNotConflict: true,
        independentDivergenceProtected: true, syntheticMemoryRegressionControls: true }, noServiceWrites: true,
    }, null, 2));

    if (activeApp.legacyWorkbench?.historyTimer != null) global.clearTimeout(activeApp.legacyWorkbench.historyTimer);
    activeApp.destroy(); activeApp = null; activeDom.window.close(); activeDom = null;
    for (const [key, value] of Object.entries(saved)) { if (value === undefined) delete global[key]; else global[key] = value; }
  } finally {
    if (activeApp) { if (activeApp.legacyWorkbench?.historyTimer != null) global.clearTimeout(activeApp.legacyWorkbench.historyTimer); activeApp.destroy(); }
    if (activeDom) activeDom.window.close();
    for (const [key, value] of Object.entries(saved)) { if (value === undefined) delete global[key]; else global[key] = value; }
  }
}

(async () => {
  const savedDocument = global.document;
  const savedLocation = global.location;
  const savedHistory = global.history;
  delete global.document;
  const { StudioApp, DraftStore } = await import(pathToFileURL(path.join(root, 'studio/studio.js')).href);
  if (process.argv.includes('--r08-single-writer')) {
    await runR08SingleWriterQA(StudioApp, DraftStore);
    console.log('PASS R08 single-writer in-memory Studio QA.');
    return;
  }
  const storage = new SharedStorage();
  const key = `n2-store:${projectId}:iteration:${snapshot.publicationRevision}`;
  const storageKey = `ptah-studio-draft-v2:${key}`;
  const base = { key, projectId, publicationRevision: snapshot.publicationRevision, sourceCommit: snapshot.sourceCommit,
    draftRevision: 1, text: '', values: {}, fields: {}, feedback: [], feedbackMessage: '', feedbackCategory: 'general',
    selectedObjectId: null, targetNotes: {}, structuralProposals: [], draftConflictAlternates: [] };
  storage.setItem(storageKey, JSON.stringify(base));

  const makeApp = async () => {
    const dom = new JSDOM(fs.readFileSync(path.join(root, 'studio/index.html'), 'utf8'), {
      url: 'http://127.0.0.1:8123/studio/', pretendToBeVisual: true,
    });
    global.document = dom.window.document; global.location = dom.window.location; global.history = dom.window.history;
    const app = new StudioApp({ fetchImpl, documentImpl: dom.window.document, timers: globalThis });
    app.drafts = new DraftStore(null, storage);
    await app.drafts.open();
    app.persistenceOK = true; app.workspace = { storeId: 'n2-store', projects: [project], iterationReady: true };
    app.manager = app.workspace; app.projectId = projectId; app.stage = 'iteration'; app.snapshot = { ...snapshot };
    app.workflow = 'template-v1'; app.bind(); app.renderWorkbench(); await app.restoreDraft();
    return { app, dom };
  };
  const first = await makeApp();
  const second = await makeApp();
  const { app: oldTab, dom: oldDom } = first;
  const { app: newTab, dom: newDom } = second;
  strict.equal(oldDom.window.document.querySelector('#edit-text').value, '');
  strict.equal(newDom.window.document.querySelector('#edit-text').value, '');

  // Each page edits independently from the same stored base. Delivering the
  // storage event exercises the browser's cross-tab notification path.
  oldDom.window.document.querySelector('#edit-text').value = '旧标签原文 A';
  newDom.window.document.querySelector('#edit-text').value = '新标签原文 B';
  global.document = oldDom.window.document; global.location = oldDom.window.location; global.history = oldDom.window.history;
  strict.equal(await oldTab.saveDraft(), true);
  const afterA = storage.getItem(storageKey);
  global.document = newDom.window.document; global.location = newDom.window.location; global.history = newDom.window.history;
  await newTab.handleDraftStorageEvent({ key: storageKey, oldValue: JSON.stringify(base), newValue: afterA });
  strict.ok(newTab.pendingDraftConflict, 'a different draft in another tab raises a visible comparison state');
  strict.match(newDom.window.document.querySelector('#draft-state').textContent, /比较并选择/);
  let envelope = JSON.parse(storage.getItem(storageKey));
  strict.equal(envelope.text, '旧标签原文 A', 'the newer stored version remains active after conflict detection');
  strict.ok(envelope.draftConflictAlternates.some(item => item.draft.text === '新标签原文 B'), 'the other tab input is persisted as a recoverable alternate');

  // The old tab has not yet observed the storage event. The raw record now
  // contains only a newly retained branch, so the stale page can safely retry
  // against those exact bytes and make its newer input active.
  oldDom.window.document.querySelector('#edit-text').value = '旧标签继续编辑 A2';
  global.document = oldDom.window.document; global.location = oldDom.window.location; global.history = oldDom.window.history;
  strict.equal(await oldTab.saveDraft(), true);
  strict.equal(oldTab.pendingDraftConflict, null, 'an envelope-only stale write does not open a false comparison');
  envelope = JSON.parse(storage.getItem(storageKey));
  strict.equal(envelope.text, '旧标签继续编辑 A2', 'the newest page input becomes the active draft after an envelope-only retry');
  strict.ok(envelope.draftConflictAlternates.some(item => item.draft.text === '新标签原文 B'), 'the other tab input remains recoverable after the retry');
  strict.equal(calls.filter(call => call.method === 'POST').length, 0, 'draft comparison performs no Agent POST');

  // A failed refresh must release the temporarily disabled choice against the
  // still-current snapshot; a later same-publication refresh must bind that
  // choice to its new snapshot object without replacing the visible edit.
  for (const key of ['document', 'location', 'history', 'FormData', 'Option', 'HTMLElement']) global[key] = newDom.window[key];
  const priorSnapshot = newTab.snapshot;
  nextWorkbenchError = new Error('controlled workbench read failure');
  await newTab.loadWorkbench(projectId).then(() => strict.fail('the controlled workbench read should fail'), error => strict.match(error.message, /controlled workbench read failure/));
  strict.equal(newTab.snapshot, priorSnapshot, 'a failed refresh leaves the old snapshot active');
  strict.equal(newTab.pendingDraftConflict.refreshing, false, 'a failed refresh releases the pending comparison');
  strict.equal(newTab.pendingDraftConflict.generation, newTab.workbenchGeneration, 'a failed refresh rebinds the comparison to the live generation');
  strict.equal(newDom.window.document.querySelector('#draft-conflict-dialog .dialog-actions button').disabled, false, 'the explicit choice is usable after a failed read');

  let releaseInterruptedRead;
  nextWorkbenchPending = new Promise(resolve => { releaseInterruptedRead = resolve; });
  const interruptedRefresh = newTab.loadWorkbench(projectId);
  await tick();
  strict.equal(newTab.pendingDraftConflict.refreshing, true, 'a new in-flight refresh again holds the explicit choice');
  newTab.advanceSelection();
  strict.equal(newTab.pendingDraftConflict.refreshing, false, 'a newer page selection releases a cancelled refresh');
  strict.equal(newTab.pendingDraftConflict.generation, newTab.workbenchGeneration, 'a cancelled refresh rebinds the comparison to the live generation');
  strict.equal(newDom.window.document.querySelector('#draft-conflict-dialog .dialog-actions button').disabled, false, 'the choice is available after a refresh is interrupted');
  releaseInterruptedRead({ ok: true, status: 200, text: async () => JSON.stringify({ projectId, project, snapshot: { ...snapshot }, workbenchResults: [] }) });
  strict.equal(await interruptedRefresh, null, 'the interrupted response cannot replace the current snapshot');

  const refreshedSnapshot = { ...snapshot };
  const refreshedResponse = { projectId, project, snapshot: refreshedSnapshot, workbenchResults: [] };
  let releaseWorkbenchRead;
  nextWorkbenchPending = new Promise(resolve => { releaseWorkbenchRead = resolve; });
  const refreshPromise = newTab.loadWorkbench(projectId);
  await tick();
  strict.equal(newTab.pendingDraftConflict.refreshing, true, 'choice is held while the same-scope refresh is in progress');
  strict.equal(newDom.window.document.querySelector('#draft-conflict-dialog .dialog-actions button').disabled, true, 'the visible choice is disabled only while its scope is being read');
  strict.equal(newDom.window.document.querySelector('#edit-text').value, '新标签原文 B', 'the local input remains visible during refresh');
  releaseWorkbenchRead({ ok: true, status: 200, text: async () => JSON.stringify(refreshedResponse) });
  await refreshPromise;
  strict.notEqual(newTab.snapshot, priorSnapshot, 'same-publication refresh returns a new snapshot object');
  strict.equal(newTab.snapshot.id, refreshedSnapshot.id);
  strict.equal(newTab.snapshot.publicationRevision, refreshedSnapshot.publicationRevision);
  strict.equal(newTab.pendingDraftConflict.generation, newTab.workbenchGeneration, 'same-scope refresh rebinds the comparison generation');
  strict.equal(newTab.pendingDraftConflict.snapshot, newTab.snapshot, 'same-scope refresh rebinds the comparison snapshot');
  strict.equal(newDom.window.document.querySelector('#edit-text').value, '新标签原文 B', 'refresh keeps the latest visible local input');

  // Choose through the visible action, then check the actual active record and
  // a regular save. The other original branch remains recoverable.
  let useLatest = newDom.window.document.querySelectorAll('#draft-conflict-dialog .dialog-actions button')[1];
  strict.ok(useLatest && !useLatest.disabled, 'the remote-choice button is enabled after a same-scope refresh');
  useLatest.click(); await tick();
  strict.ok(newTab.pendingDraftConflict, 'a real active-content change during comparison requires a fresh comparison');
  strict.equal(JSON.parse(storage.getItem(storageKey)).text, '旧标签继续编辑 A2', 'the first stale confirmation cannot replace the newer active draft');
  useLatest = newDom.window.document.querySelectorAll('#draft-conflict-dialog .dialog-actions button')[1];
  useLatest.click(); await tick();
  strict.equal(newTab.pendingDraftConflict, null, 'an explicit remote choice clears the pending comparison');
  strict.equal(JSON.parse(storage.getItem(storageKey)).text, '旧标签继续编辑 A2', 'the visible local choice becomes the stored active draft');
  strict.equal(await newTab.saveDraft(), true, 'normal saving succeeds after resolving the refreshed conflict');
  strict.equal(JSON.parse(storage.getItem(storageKey)).text, '旧标签继续编辑 A2', 'the resolved draft remains active after a regular save');

  // A source identity change can reuse the existing local-storage key. The
  // old comparison still must not be rebound or written into that new source.
  const beforeSourceChange = storage.getItem(storageKey);
  global.document = newDom.window.document; global.location = newDom.window.location; global.history = newDom.window.history;
  newTab.openDraftConflict();
  const changedSourceSnapshot = { ...snapshot, sourceCommit: 'n2-source-new' };
  nextWorkbenchResponse = { projectId, project, snapshot: changedSourceSnapshot, workbenchResults: [] };
  await newTab.loadWorkbench(projectId);
  strict.equal(newTab.draftKey, key, 'the existing draft key remains unchanged when only source identity changes');
  strict.equal(newTab.pendingDraftConflict.scopeChanged, true, 'the old comparison is invalidated when its source identity changes');
  strict.equal(newDom.window.document.querySelector('#draft-conflict-dialog .dialog-actions button').disabled, true, 'the old visible choice is disabled for a different source');
  await newTab.resolveDraftConflict('local');
  strict.equal(storage.getItem(storageKey), beforeSourceChange, 'an old comparison cannot write into a different source that reuses the same key');

  // Use the recovery picker to restore each original branch from DraftStore.
  strict.equal(oldDom.window.document.querySelector('#edit-text').value, '旧标签继续编辑 A2');
  strict.ok(oldTab.draftAlternates.some(item => item.draft.text === '旧标签原文 A'));
  strict.ok(oldTab.draftAlternates.some(item => item.draft.text === '新标签原文 B'));
  const restoreAlternate = async wantedText => {
    global.document = oldDom.window.document; global.location = oldDom.window.location; global.history = oldDom.window.history;
    oldTab.openDraftConflict();
    const dialog = oldDom.window.document.querySelector('#draft-conflict-dialog');
    const selected = oldTab.draftAlternates.find(item => item.draft.text === wantedText);
    strict.ok(selected, `alternate ${wantedText} is available to restore`);
    const choose = [...dialog.querySelectorAll('.draft-conflict-alternate')]
      .find(button => oldTab.sameDraftContent(button.__draftAlternate, selected.draft));
    if (choose) choose.click();
    else strict.equal(oldTab.draftAlternates.length, 1, 'a single alternate is already selected');
    await oldTab.resolveDraftConflict('remote');
    strict.equal(oldDom.window.document.querySelector('#edit-text').value, wantedText);
  };
  await restoreAlternate('新标签原文 B');
  await restoreAlternate('旧标签原文 A');
  strict.equal(JSON.parse(storage.getItem(storageKey)).text, '旧标签原文 A', 'each original version can become the active draft by explicit choice');
  strict.equal(calls.filter(call => call.method === 'POST').length, 0, 'restoring alternatives performs no Agent POST');

  const activateHandle = handle => {
    for (const key of ['document', 'location', 'history', 'FormData', 'Option', 'HTMLElement']) global[key] = handle.dom.window[key];
  };
  const drainObservations = [];
  const makeObjectApp = async (hub, name, seed = objectBase) => {
    const dom = new JSDOM(fs.readFileSync(path.join(root, 'studio/index.html'), 'utf8'), {
      url: 'http://127.0.0.1:8123/studio/', pretendToBeVisual: true,
    });
    const handle = { dom, name };
    activateHandle(handle);
    for (const dialog of dom.window.document.querySelectorAll('dialog')) {
      dialog.showModal = function () { this.open = true; };
      dialog.close = function () { this.open = false; };
    }
    const app = new StudioApp({ fetchImpl, documentImpl: dom.window.document, timers: globalThis });
    handle.app = app;
    const originalStorageHandler = app.handleDraftStorageEvent.bind(app);
    app.handleDraftStorageEvent = event => { handle.eventPromise = originalStorageHandler(event); return handle.eventPromise; };
    app.drafts = new DraftStore(null, hub.port(handle));
    await app.drafts.open();
    app.persistenceOK = true; app.workspace = { storeId: 'n2-store', projects: [objectProject], iterationReady: true };
    app.manager = app.workspace; app.projectId = objectProjectId; app.stage = 'iteration'; app.snapshot = structuredClone(objectSnapshot);
    app.workflow = 'objects-v1'; app.capabilities = structuredClone(objectCapabilities);
    app.bind(); app.renderWorkbench(); await app.restoreDraft();
    return handle;
  };
  const assertNaturallyDrained = async (hub, label) => {
    const result = await hub.drain(1000);
    const tail = hub.writes.slice(-6).map(write => ({ by: write.by, revision: write.record.draftRevision,
      text: write.record.text, branches: write.record.draftConflictAlternates.map(item => item.draft.text) }));
    const firstWrites = hub.writes.slice(0, 8).map(write => ({ by: write.by, revision: write.record.draftRevision, branches: write.record.draftConflictAlternates.map(item => item.draft.text) }));
    strict.ok(result.delivered < 1000, `${label}: automatic storage-event queue drains before reaching the 1000-event safety cap; delivered=${result.delivered}, remaining=${result.remaining}, writes=${hub.writes.length}, first=${JSON.stringify(firstWrites)}, tail=${JSON.stringify(tail)}`);
    strict.equal(result.remaining, 0, `${label}: automatic storage-event queue naturally empties before the safety cap; delivered=${result.delivered}, writes=${hub.writes.length}, first=${JSON.stringify(firstWrites)}, tail=${JSON.stringify(tail)}`);
    const finalRecord = JSON.parse(hub.values.get(hub.storageKey) || 'null');
    const writers = Object.fromEntries(hub.writes.reduce((counts, write) => {
      const entry = counts.get(write.by) || { writes: 0, lastRevision: null };
      entry.writes++; entry.lastRevision = write.record.draftRevision; counts.set(write.by, entry); return counts;
    }, new Map()));
    drainObservations.push({ label, delivered: result.delivered, remaining: result.remaining, writes: hub.writes.length,
      activeRevision: finalRecord?.draftRevision ?? null, writers });
    return result;
  };
  const readObjectRecord = hub => JSON.parse(hub.values.get(objectStorageKey));
  const hasBranch = (record, app, wanted) => record.draftConflictAlternates.some(item => app.sameDraftContent(item.draft, wanted));
  const cancelHistoryTimer = handle => {
    if (handle.app.legacyWorkbench.historyTimer != null) {
      clearTimeout(handle.app.legacyWorkbench.historyTimer); handle.app.legacyWorkbench.historyTimer = null;
    }
  };
  const cancelDraftTimer = handle => {
    if (handle.app.draftTimer != null) {
      (handle.app.timers || globalThis).clearTimeout(handle.app.draftTimer); handle.app.draftTimer = null;
    }
  };
  const closeHandles = handles => { for (const handle of handles) { cancelHistoryTimer(handle); handle.app.destroy(); handle.dom.window.close(); } };

  // R04-01: replacing content with an older explicit checkpoint archives the
  // complete active draft and its branches before the normal CAS save.
  const recoveryHub = new AutoStorageEventHub(objectStorageKey);
  const completeDraft = (label, speed, operationId) => {
    const draft = objectDraft(label, { speed, operationId, noteText: `${label} 主目标完整意见` });
    draft.targetNotes['guard-one'] = { objectId: 'guard-one', feedbackId: `${label}-instance-note`,
      text: `${label} 第二目标完整意见全文` };
    draft.feedback = [{ feedbackId: `${label}-classified-id`, objectId: 'hero', category: 'behavior', message: `${label} 分类意见全文` }];
    draft.feedbackInputs = { hero: { category: 'visual', message: `${label} 待添加意见全文` } };
    draft.feedbackInputTargetId = 'hero'; draft.feedbackMessage = `${label} 待添加意见全文`; draft.feedbackCategory = 'visual';
    draft.proposalInputs = { [`${label}-proposal`]: { 2: {
      questionPrompts: { why: '为何保留此结构' }, questions: { why: `${label} 策划回答全文` }, readySupplement: `${label} 待续写补充全文`,
    } } };
    return draft;
  };
  const r06EarlierA = completeDraft('R06 现有 A', 300, 'r06-a-operation');
  r06EarlierA.targetNotes.hero = { objectId: 'hero', feedbackId: 'r06-hero-note', text: '角色意见原文，含原有全部内容。', updatedAt: '2026-10-16T00:00:00.000Z' };
  r06EarlierA.text = r06EarlierA.targetNotes.hero.text;
  r06EarlierA.targetNotes['guard-one'] = { objectId: 'guard-one', feedbackId: 'r06-guard-note', text: '守卫意见原文，保留已有身份。', updatedAt: '2026-10-16T00:00:00.000Z' };
  r06EarlierA.targetNotes.__project__ = { objectId: null, feedbackId: 'r06-project-note', text: '项目级意见原文，继续保留。', updatedAt: '2026-10-16T00:00:00.000Z' };
  r06EarlierA.structuralProposals[0].operationId = 'r06-stable-operation';
  r06EarlierA.feedback = [{ feedbackId: 'r06-stable-feedback', objectId: 'hero', category: 'behavior', message: '保留的分类反馈全文。' }];
  const r06BranchB = completeDraft('R06 恢复 B', 260, 'r06-b-operation');
  const r06OlderC = completeDraft('R06 更早 C', 240, 'r06-c-operation');
  const r06StoredA = { ...structuredClone(r06EarlierA), key: objectKey, projectId: objectProjectId,
    publicationRevision: objectSnapshot.publicationRevision, sourceCommit: objectSnapshot.sourceCommit,
    baseCommit: objectSnapshot.baseCommit, draftRevision: 40,
    draftConflictAlternates: [
      { label: 'R06 更早完整 C', capturedAt: '2026-10-16T11:00:00.000Z', draft: structuredClone(r06OlderC) },
      { label: 'R06 完整 B', capturedAt: '2026-10-16T12:00:00.000Z', draft: structuredClone(r06BranchB) },
    ] };
  const exerciseR06Replacement = async (label, inputAlreadyInHistory) => {
    const hub = new AutoStorageEventHub(objectStorageKey);
    hub.values.set(objectStorageKey, JSON.stringify(structuredClone(r06StoredA)));
    const handle = await makeObjectApp(hub, label);
    activateHandle(handle);
    const editor = handle.dom.window.document.querySelector('#edit-text');
    const uniqueTail = `\n第六轮窄屏讲解补充 · ${label}`;
    editor.value += uniqueTail;
    editor.dispatchEvent(new handle.dom.window.Event('input', { bubbles: true }));
    strict.ok(handle.app.legacyWorkbench.historyTimer != null, `${label}: the full input has a pending history debounce`);
    cancelDraftTimer(handle);
    if (inputAlreadyInHistory) {
      cancelHistoryTimer(handle);
      handle.app.legacyWorkbench.pushHistory();
      strict.ok(handle.app.legacyWorkbench.history.at(-1).targetNotes.hero.text.includes(uniqueTail), `${label}: latest A is already the history top`);
    }
    const latestA = handle.app.currentDraftRecord();
    strict.ok(latestA.targetNotes.hero.text.includes(uniqueTail), `${label}: current A includes the just-entered complete tail`);
    strict.equal(latestA.targetNotes.hero.feedbackId, 'r06-hero-note', `${label}: current A keeps the hero note identity`);
    strict.equal(latestA.targetNotes['guard-one'].feedbackId, 'r06-guard-note', `${label}: current A keeps the instance note identity`);
    strict.equal(latestA.targetNotes.__project__.feedbackId, 'r06-project-note', `${label}: current A keeps the project note identity`);
    handle.app.openDraftConflict();
    strict.ok(handle.app.sameDraftContent(handle.app.pendingDraftConflict.remote, r06BranchB), `${label}: the exact B branch is selected for recovery`);
    strict.equal(await handle.app.resolveDraftConflict('remote'), true, `${label}: the selected B replacement is saved`);
    strict.ok(handle.app.sameDraftContent(readObjectRecord(hub), r06BranchB), `${label}: B is active after replacement`);
    await handle.app.legacyWorkbench.undo();
    let active = readObjectRecord(hub);
    strict.ok(handle.app.sameDraftContent(active, latestA), `${label}: one undo returns to the complete latest A`);
    strict.ok(active.targetNotes.hero.text.includes(uniqueTail), `${label}: undo retains the exact last supplement`);
    strict.equal(active.targetNotes.hero.feedbackId, 'r06-hero-note', `${label}: undo preserves the stable hero feedback ID`);
    strict.equal(active.targetNotes['guard-one'].feedbackId, 'r06-guard-note', `${label}: undo preserves the stable instance feedback ID`);
    strict.equal(active.targetNotes.__project__.feedbackId, 'r06-project-note', `${label}: undo preserves the stable project feedback ID`);
    strict.equal(active.feedback[0].feedbackId, 'r06-stable-feedback', `${label}: undo preserves the classified feedback ID`);
    strict.equal(active.structuralProposals[0].operationId, 'r06-stable-operation', `${label}: undo preserves the structural operation ID`);
    await handle.app.legacyWorkbench.redo();
    strict.ok(handle.app.sameDraftContent(readObjectRecord(hub), r06BranchB), `${label}: redo returns to B`);
    await handle.app.legacyWorkbench.undo();
    active = readObjectRecord(hub);
    strict.ok(handle.app.sameDraftContent(active, latestA) && active.targetNotes.hero.text.includes(uniqueTail), `${label}: undo after redo returns to the same complete A`);
    strict.ok(hasBranch(active, handle.app, r06BranchB), `${label}: the selected B remains independently recoverable`);
    strict.ok(hasBranch(active, handle.app, r06OlderC), `${label}: the pre-existing older C branch remains independently recoverable`);
    closeHandles([handle]);
  };
  await exerciseR06Replacement('R06 input-before-history', false);
  await exerciseR06Replacement('R06 history-already-current', true);

  const r06InvalidHub = new AutoStorageEventHub(objectStorageKey);
  r06InvalidHub.values.set(objectStorageKey, JSON.stringify(structuredClone(r06StoredA)));
  const r06Invalid = await makeObjectApp(r06InvalidHub, 'R06 invalid-scope');
  r06Invalid.app.openDraftConflict();
  const invalidHistoryLength = r06Invalid.app.legacyWorkbench.history.length;
  const invalidText = r06Invalid.dom.window.document.querySelector('#edit-text').value;
  r06Invalid.app.pendingDraftConflict.scopeChanged = true;
  await r06Invalid.app.resolveDraftConflict('remote');
  strict.equal(r06Invalid.dom.window.document.querySelector('#edit-text').value, invalidText, 'an invalid comparison scope does not apply the selected replacement');
  strict.equal(r06Invalid.app.legacyWorkbench.history.length, invalidHistoryLength, 'an invalid comparison scope does not create replacement history');
  strict.ok(r06Invalid.app.sameDraftContent(readObjectRecord(r06InvalidHub), r06StoredA), 'an invalid comparison scope leaves the persisted active A unchanged');
  closeHandles([r06Invalid]);

  const checkpointA = completeDraft('检查点 A', 290, 'checkpoint-a-operation');
  const activeB = completeDraft('活动稿 B', 315, 'active-b-operation');
  const branchC = completeDraft('跨页分支 C', 340, 'cross-page-c-operation');
  const recoverySavedCheckpointKey = `${objectKey}:saved`, recoverySavedBackupKey = `${objectKey}:saved:backup`;
  const checkpointRecord = { ...structuredClone(checkpointA), key: recoverySavedCheckpointKey, baseDraftKey: objectKey,
    projectId: objectProjectId, publicationRevision: objectSnapshot.publicationRevision, savedAt: '2026-10-16T00:00:00.000Z', checkpoint: true };
  const backupRecord = { ...structuredClone(objectBase), key: recoverySavedBackupKey, baseDraftKey: objectKey,
    projectId: objectProjectId, publicationRevision: objectSnapshot.publicationRevision,
    savedAt: '2026-10-15T00:00:00.000Z', checkpointBackup: true };
  const recoverySavedCheckpointRaw = JSON.stringify(checkpointRecord), recoverySavedBackupRaw = JSON.stringify(backupRecord);
  recoveryHub.values.set(objectStorageKey, JSON.stringify({ ...structuredClone(activeB), draftConflictAlternates: [
    { label: '更早的完整版本', capturedAt: '2026-10-15T12:00:00.000Z', draft: structuredClone(objectBase) },
  ] }));
  recoveryHub.values.set(`ptah-studio-draft-v2:${recoverySavedCheckpointKey}`, recoverySavedCheckpointRaw);
  recoveryHub.values.set(`ptah-studio-draft-v2:${recoverySavedBackupKey}`, recoverySavedBackupRaw);
  const recoveryWriter = await makeObjectApp(recoveryHub, 'checkpoint-replacement-writer');
  activateHandle(recoveryWriter);
  await recoveryWriter.app.legacyWorkbench.restoreSavedDraft();
  let recoveryRecord = readObjectRecord(recoveryHub);
  strict.ok(recoveryWriter.app.sameDraftContent(recoveryRecord, checkpointA), 'restoring checkpoint A applies its complete active content');
  strict.ok(hasBranch(recoveryRecord, recoveryWriter.app, activeB), 'the displaced complete active B is archived even though it was not an alternate');
  strict.ok(hasBranch(recoveryRecord, recoveryWriter.app, objectBase), 'the pre-existing complete alternate remains available');
  strict.equal(recoveryHub.values.get(`ptah-studio-draft-v2:${recoverySavedCheckpointKey}`), recoverySavedCheckpointRaw, 'checkpoint restoration leaves the saved checkpoint raw unchanged');
  strict.equal(recoveryHub.values.get(`ptah-studio-draft-v2:${recoverySavedBackupKey}`), recoverySavedBackupRaw, 'checkpoint restoration leaves the first backup raw unchanged');
  closeHandles([recoveryWriter]);

  const recoveryReader = await makeObjectApp(recoveryHub, 'checkpoint-replacement-reader');
  activateHandle(recoveryReader);
  strict.ok(recoveryReader.app.sameDraftContent(recoveryReader.app.currentDraftRecord(), checkpointA), 'a fresh page reads checkpoint A back as the complete active draft');
  strict.ok(recoveryReader.app.draftAlternates.some(item => recoveryReader.app.sameDraftContent(item.draft, activeB)), 'a fresh page can independently recover complete B');
  const restoreBranch = async wanted => {
    recoveryReader.app.openDraftConflict();
    const choice = [...recoveryReader.dom.window.document.querySelectorAll('.draft-conflict-alternate')]
      .find(button => recoveryReader.app.sameDraftContent(button.__draftAlternate, wanted));
    strict.ok(choice, `the full ${wanted.text} version remains selectable`);
    choice.click();
    await recoveryReader.app.resolveDraftConflict('remote');
    strict.ok(recoveryReader.app.sameDraftContent(readObjectRecord(recoveryHub), wanted), `the full ${wanted.text} version restores through the picker`);
  };
  await restoreBranch(activeB);
  await recoveryReader.app.legacyWorkbench.restoreSavedDraft();
  recoveryRecord = readObjectRecord(recoveryHub);
  strict.ok(recoveryReader.app.sameDraftContent(recoveryRecord, checkpointA), 'a later checkpoint restore selects A again');
  strict.ok(hasBranch(recoveryRecord, recoveryReader.app, activeB), 'the B that was active after recovery is re-archived by the later replacement');
  const recoveryWorkbench = recoveryReader.app.legacyWorkbench;
  const resetConfirm = globalThis.confirm;
  globalThis.confirm = () => true;
  await recoveryWorkbench.resetDraft();
  globalThis.confirm = resetConfirm;
  await recoveryWorkbench.undo();
  strict.ok(recoveryReader.app.sameDraftContent(readObjectRecord(recoveryHub), checkpointA), 'undo after reset restores complete A');
  await recoveryWorkbench.redo();
  await recoveryWorkbench.undo();
  recoveryRecord = readObjectRecord(recoveryHub);
  strict.ok(recoveryReader.app.sameDraftContent(recoveryRecord, checkpointA), 'reset, undo, redo, and undo leave complete A active');
  strict.ok(hasBranch(recoveryRecord, recoveryReader.app, activeB), 'the mixed reset/history chain keeps B independently recoverable');
  strict.ok(hasBranch(recoveryRecord, recoveryReader.app, objectBase), 'the mixed reset/history chain keeps the earlier full version');
  strict.equal(recoveryHub.values.get(`ptah-studio-draft-v2:${recoverySavedCheckpointKey}`), recoverySavedCheckpointRaw, 'reset and history actions leave the saved checkpoint raw unchanged');
  strict.equal(recoveryHub.values.get(`ptah-studio-draft-v2:${recoverySavedBackupKey}`), recoverySavedBackupRaw, 'reset and history actions leave the first backup raw unchanged');
  const currentRecoveryRaw = recoveryHub.values.get(objectStorageKey);
  await recoveryReader.app.saveConflictEnvelope(readObjectRecord(recoveryHub), [branchC], currentRecoveryRaw);
  await restoreBranch(branchC);
  await restoreBranch(checkpointA);
  await restoreBranch(activeB);
  await restoreBranch(checkpointA);
  recoveryRecord = readObjectRecord(recoveryHub);
  strict.ok(hasBranch(recoveryRecord, recoveryReader.app, branchC), 'complete C remains recoverable after returning to A');
  strict.ok(hasBranch(recoveryRecord, recoveryReader.app, activeB), 'complete B remains recoverable after restoring C and returning to A');
  strict.ok(hasBranch(recoveryRecord, recoveryReader.app, objectBase), 'the pre-existing complete version remains recoverable after all replacements');
  strict.equal(recoveryHub.values.get(`ptah-studio-draft-v2:${recoverySavedCheckpointKey}`), recoverySavedCheckpointRaw, 'all branch selections leave the saved checkpoint raw unchanged');
  strict.equal(recoveryHub.values.get(`ptah-studio-draft-v2:${recoverySavedBackupKey}`), recoverySavedBackupRaw, 'all branch selections leave the first backup raw unchanged');
  closeHandles([recoveryReader]);

  // A page cache is only a merge source, never proof that a branch already
  // exists in the active persisted record.
  const cacheBranchHub = new AutoStorageEventHub(objectStorageKey);
  cacheBranchHub.values.set(objectStorageKey, JSON.stringify(structuredClone(objectBase)));
  const cacheBranchApp = await makeObjectApp(cacheBranchHub, 'cache-only-branch');
  const cacheOnlyMixed = objectDraft('完整缓存混合稿', { speed: 290, operationId: 'cache-only-mixed-operation' });
  cacheBranchApp.app.draftAlternates = [{ label: '页面缓存分支', capturedAt: '2026-10-16T00:00:00.000Z', draft: structuredClone(cacheOnlyMixed) }];
  const cacheBranchRaw = cacheBranchHub.values.get(objectStorageKey);
  const cachedMerge = await cacheBranchApp.app.saveConflictEnvelope(readObjectRecord(cacheBranchHub), [structuredClone(cacheOnlyMixed)], cacheBranchRaw);
  strict.ok(hasBranch(readObjectRecord(cacheBranchHub), cacheBranchApp.app, cacheOnlyMixed), 'a cache-only complete branch is actually written to the active DraftStore record');
  strict.ok(hasBranch(cachedMerge, cacheBranchApp.app, cacheOnlyMixed), 'the merged result contains the complete cache-only branch');
  strict.equal(cacheBranchHub.writes.length, 1, 'a cache-only branch missing from storage causes one conditional write');
  await assertNaturallyDrained(cacheBranchHub, 'cache-only branch persistence');
  cacheBranchApp.app.destroy(); cacheBranchApp.dom.window.close();
  const cacheBranchFresh = await makeObjectApp(cacheBranchHub, 'cache-branch-fresh-reader');
  activateHandle(cacheBranchFresh);
  strict.ok(cacheBranchFresh.app.draftAlternates.some(item => cacheBranchFresh.app.sameDraftContent(item.draft, cacheOnlyMixed)), 'a fresh app reads the persisted complete cache-only branch');
  cacheBranchFresh.app.openDraftConflict();
  strict.equal(cacheBranchFresh.app.pendingDraftConflict?.recovery, true, 'the fresh app presents the branch through the recovery picker');
  const cacheOnlyIndex = cacheBranchFresh.app.draftAlternates.findIndex(item => cacheBranchFresh.app.sameDraftContent(item.draft, cacheOnlyMixed));
  strict.ok(cacheOnlyIndex >= 0, 'the fresh app can select the exact cache-only branch');
  [...cacheBranchFresh.dom.window.document.querySelectorAll('.draft-conflict-alternate')]
    .find(button => cacheBranchFresh.app.sameDraftContent(button.__draftAlternate, cacheOnlyMixed))?.click();
  await cacheBranchFresh.app.resolveDraftConflict('remote');
  strict.ok(cacheBranchFresh.app.sameDraftContent(readObjectRecord(cacheBranchHub), cacheOnlyMixed), 'the fresh app restores the full cached branch as active content');
  await assertNaturallyDrained(cacheBranchHub, 'fresh-app cache-only branch recovery');
  cacheBranchFresh.app.destroy(); cacheBranchFresh.dom.window.close();

  // R03-P1: a raw conflict caused only by new alternates/revision metadata is
  // rebased with the latest exact bytes while keeping this page's edit active.
  const envelopeHub = new AutoStorageEventHub(objectStorageKey);
  envelopeHub.values.set(objectStorageKey, JSON.stringify(structuredClone(objectBase)));
  const envelopeA = await makeObjectApp(envelopeHub, 'envelope-A');
  const envelopeB = await makeObjectApp(envelopeHub, 'envelope-B');
  const envelopeBranch = objectDraft('仅保留分支 B', { speed: 270, operationId: 'envelope-b-operation', selectedObjectId: 'guard-one' });
  activateHandle(envelopeB);
  await envelopeB.app.saveConflictEnvelope(readObjectRecord(envelopeHub), [envelopeBranch], envelopeB.app.draftStorageBaseline);
  activateHandle(envelopeA);
  const currentA = objectDraft('封套漂移后继续输入 A', { speed: 310, operationId: 'envelope-a-operation' });
  envelopeA.app.applyVisibleDraft(structuredClone(currentA));
  strict.equal(await envelopeA.app.saveDraft(), true, 'a stale CAS retries when only the stored envelope changed');
  await assertNaturallyDrained(envelopeHub, 'envelope drift before the next input save');
  let envelopeRecord = readObjectRecord(envelopeHub);
  strict.ok(envelopeA.app.sameDraftContent(envelopeRecord, currentA), 'the newest local input becomes active after an envelope-only raw drift');
  strict.ok(hasBranch(envelopeRecord, envelopeA.app, envelopeBranch), 'the newly arrived complete alternate remains recoverable after the retry');
  strict.equal(envelopeA.app.pendingDraftConflict, null, 'the envelope-only retry does not create a false comparison');
  const envelopeFresh = await makeObjectApp(envelopeHub, 'envelope-fresh-reader');
  strict.ok(envelopeFresh.app.sameDraftContent(envelopeFresh.app.currentDraftRecord(), currentA), 'a new app reads back the retried active content');
  strict.ok(envelopeFresh.app.draftAlternates.some(item => envelopeFresh.app.sameDraftContent(item.draft, envelopeBranch)), 'a new app can recover the merged envelope branch');
  closeHandles([envelopeA, envelopeB, envelopeFresh]);

  // The same raw drift is safe when its event arrives before the next edit.
  const eventFirstHub = new AutoStorageEventHub(objectStorageKey);
  eventFirstHub.values.set(objectStorageKey, JSON.stringify(structuredClone(objectBase)));
  const eventFirstA = await makeObjectApp(eventFirstHub, 'event-first-A');
  const eventFirstB = await makeObjectApp(eventFirstHub, 'event-first-B');
  activateHandle(eventFirstB);
  const eventBranch = objectDraft('先到达的保留分支', { speed: 275, operationId: 'event-first-branch-op' });
  await eventFirstB.app.saveConflictEnvelope(readObjectRecord(eventFirstHub), [eventBranch], eventFirstB.app.draftStorageBaseline);
  await assertNaturallyDrained(eventFirstHub, 'envelope-only storage event before input');
  strict.equal(eventFirstA.app.pendingDraftConflict, null, 'an envelope-only event does not interrupt editing');
  activateHandle(eventFirstA);
  const afterEventA = { ...objectDraft('事件后输入的新稿', { speed: 305, operationId: 'event-first-a-op' }),
    draftConflictAlternates: structuredClone(eventFirstA.app.draftAlternates) };
  eventFirstA.app.applyVisibleDraft(structuredClone(afterEventA));
  strict.equal(await eventFirstA.app.saveDraft(), true, 'a later save uses the refreshed exact baseline');
  await assertNaturallyDrained(eventFirstHub, 'input saved after envelope-only event');
  envelopeRecord = readObjectRecord(eventFirstHub);
  strict.ok(eventFirstA.app.sameDraftContent(envelopeRecord, afterEventA), 'the later edit becomes active without a false conflict');
  strict.ok(hasBranch(envelopeRecord, eventFirstA.app, eventBranch), 'the prior event branch remains complete after the later save');
  closeHandles([eventFirstA, eventFirstB]);

  // A successful write returns its own exact raw even if a newer same-scope
  // input starts before the awaiting reconciliation callback resumes.
  const pairingHub = new AutoStorageEventHub(objectStorageKey);
  pairingHub.values.set(objectStorageKey, JSON.stringify(structuredClone(objectBase)));
  const pairing = await makeObjectApp(pairingHub, 'operation-pairing');
  const pairingBaselineRaw = pairing.app.draftStorageBaseline;
  const pairingBranch = objectDraft('配对分支', { speed: 265, operationId: 'pairing-branch-op' });
  const pairingDrift = { ...structuredClone(objectBase), draftRevision: 2,
    draftConflictAlternates: [{ label: '配对分支', draft: structuredClone(pairingBranch) }] };
  const pairingDriftRaw = JSON.stringify(pairingDrift);
  pairingHub.values.set(objectStorageKey, pairingDriftRaw);
  activateHandle(pairing);
  const pairingPromise = pairing.app.reconcileEnvelopeDrift({ baselineRaw: pairingBaselineRaw,
    latestRaw: pairingDriftRaw, latest: pairingDrift });
  const pairingInput = pairing.dom.window.document.querySelector('#edit-text');
  pairingInput.value += '\n同范围新输入';
  pairingInput.dispatchEvent(new pairing.dom.window.Event('input', { bubbles: true }));
  cancelHistoryTimer(pairing);
  const pairingResult = await pairingPromise;
  strict.equal(pairingResult.status, 'stale', 'a newer same-scope input owns state after the older envelope continuation resumes');
  strict.equal(pairingResult.latest.draftStorageRaw, pairingResult.latestRaw, 'the envelope result carries its own exact serialized raw');
  strict.ok(pairing.app.sameDraftContent(pairingResult.latest, pairing.app.drafts.readStored(objectKey, pairingResult.latestRaw)),
    'the returned record and raw describe the same verified envelope write');
  strict.ok(readObjectRecord(pairingHub).targetNotes.hero.text.includes('同范围新输入'), 'the newer input remains stored after the older continuation finishes');
  closeHandles([pairing]);

  // A same branch set cannot make a changed candidate active without a write.
  const noOpHub = new AutoStorageEventHub(objectStorageKey);
  noOpHub.values.set(objectStorageKey, JSON.stringify(structuredClone(objectBase)));
  const noOp = await makeObjectApp(noOpHub, 'no-op-active-guard');
  const beforeNoOpRaw = noOpHub.values.get(objectStorageKey);
  const noOpCandidate = objectDraft('必须实际写入的候选', { speed: 333, operationId: 'no-op-active-op' });
  const noOpResult = await noOp.app.saveConflictEnvelope(noOpCandidate, [], beforeNoOpRaw);
  const afterNoOp = readObjectRecord(noOpHub);
  strict.ok(noOp.app.sameDraftContent(afterNoOp, noOpCandidate), 'a different active candidate is conditionally written even when branches match');
  strict.notEqual(noOpHub.values.get(objectStorageKey), beforeNoOpRaw, 'the active-content change does not take the no-op path');
  strict.equal(noOpResult.draftStorageRaw, noOpHub.values.get(objectStorageKey), 'the successful helper result is paired with the exact stored raw');
  closeHandles([noOp]);

  // A genuine third writer lands after the real input write but before its
  // baseline is captured. The same input's next save must compare against the
  // first write's raw, detect the peer record, and retain both full drafts.
  const thirdRaceHub = new AutoStorageEventHub(objectStorageKey);
  thirdRaceHub.values.set(objectStorageKey, JSON.stringify(structuredClone(objectBase)));
  const thirdRaceLocal = await makeObjectApp(thirdRaceHub, 'third-race-local');
  const thirdRacePeer = await makeObjectApp(thirdRaceHub, 'third-race-peer');
  activateHandle(thirdRaceLocal);
  const localStoragePort = thirdRaceLocal.app.drafts.storage;
  const nativeSetItem = localStoragePort.setItem.bind(localStoragePort);
  const nativeConditionalWrite = thirdRaceLocal.app.drafts.putIfUnchanged.bind(thirdRaceLocal.app.drafts);
  let firstLocalRaw = null, peerThirdRaw = null, peerThirdRecord = null, injectedThirdWrite = false;
  const localExpectedRaws = [];
  localStoragePort.setItem = (storageKey, value) => {
    nativeSetItem(storageKey, value);
    if (storageKey !== objectStorageKey || injectedThirdWrite) return;
    injectedThirdWrite = true;
    firstLocalRaw = String(value);
    const firstLocalRecord = JSON.parse(firstLocalRaw);
    peerThirdRecord = structuredClone(firstLocalRecord);
    peerThirdRecord.draftRevision += 1;
    peerThirdRecord.targetNotes.hero = { ...peerThirdRecord.targetNotes.hero,
      text: `${peerThirdRecord.targetNotes.hero.text}\n真实第三写者内容`, feedbackId: 'third-race-peer-note' };
    peerThirdRecord.text = peerThirdRecord.targetNotes.hero.text;
    thirdRacePeer.app.drafts.putIfUnchanged(peerThirdRecord, firstLocalRaw);
    peerThirdRaw = thirdRaceHub.values.get(objectStorageKey);
  };
  thirdRaceLocal.app.drafts.putIfUnchanged = (record, expectedRaw) => {
    localExpectedRaws.push(expectedRaw);
    return nativeConditionalWrite(record, expectedRaw);
  };
  const raceInput = thirdRaceLocal.dom.window.document.querySelector('#edit-text');
  raceInput.value += '\n本地真实输入';
  raceInput.dispatchEvent(new thirdRaceLocal.dom.window.Event('input', { bubbles: true }));
  cancelHistoryTimer(thirdRaceLocal);
  const latestLocalInput = thirdRaceLocal.app.currentDraftRecord();
  await tick(); await tick();
  await assertNaturallyDrained(thirdRaceHub, 'third writer after real input save');
  localStoragePort.setItem = nativeSetItem;
  strict.ok(peerThirdRaw && firstLocalRaw && peerThirdRaw !== firstLocalRaw, 'the peer conditionally committed a genuine third raw after the local write');
  strict.ok(localExpectedRaws.length >= 3, 'the real input path attempted its later save and the conflict-retention save');
  strict.equal(localExpectedRaws[1], firstLocalRaw, 'the later save compares against this operation’s write, not the unexamined third raw');
  strict.equal(localExpectedRaws[2], peerThirdRaw, 'conflict retention is based on the exact third-party record it compared');
  const thirdRaceFinal = readObjectRecord(thirdRaceHub);
  strict.ok(thirdRaceLocal.app.sameDraftContent(thirdRaceFinal, peerThirdRecord), 'the third writer remains the actual active draft');
  strict.ok(hasBranch(thirdRaceFinal, thirdRaceLocal.app, latestLocalInput), 'the newest complete local input is retained as a branch');
  strict.equal(thirdRaceFinal.targetNotes.hero.feedbackId, 'third-race-peer-note',
    'the third writer’s full active target note identity remains intact');
  const thirdRaceFresh = await makeObjectApp(thirdRaceHub, 'third-race-fresh-reader');
  strict.ok(thirdRaceFresh.app.sameDraftContent(thirdRaceFresh.app.currentDraftRecord(), peerThirdRecord), 'a new app reads the preserved third active draft');
  strict.ok(hasBranch(readObjectRecord(thirdRaceHub), thirdRaceFresh.app, latestLocalInput), 'a new app reads the retained full local branch');
  closeHandles([thirdRaceLocal, thirdRacePeer, thirdRaceFresh]);

  // The mixed A-to-input chain checks active storage before constructing a
  // fresh reader, while the saved checkpoint and first backup keep exact bytes.
  const mixedChainHub = new AutoStorageEventHub(objectStorageKey);
  mixedChainHub.values.set(objectStorageKey, JSON.stringify(structuredClone(objectBase)));
  const savedCheckpointKey = `${objectKey}:saved`, savedBackupKey = `${objectKey}:saved:backup`;
  const savedCheckpointRaw = JSON.stringify({ key: savedCheckpointKey, baseDraftKey: objectKey,
    projectId: objectProjectId, publicationRevision: objectSnapshot.publicationRevision, checkpoint: true,
    savedAt: '2026-10-16T00:00:00.000Z', draft: structuredClone(objectBase) });
  const savedBackupRaw = JSON.stringify({ key: savedBackupKey, baseDraftKey: objectKey,
    projectId: objectProjectId, publicationRevision: objectSnapshot.publicationRevision, checkpointBackup: true,
    savedAt: '2026-10-15T00:00:00.000Z', draft: structuredClone(objectBase) });
  mixedChainHub.values.set(`ptah-studio-draft-v2:${savedCheckpointKey}`, savedCheckpointRaw);
  mixedChainHub.values.set(`ptah-studio-draft-v2:${savedBackupKey}`, savedBackupRaw);
  const mixedChainA = await makeObjectApp(mixedChainHub, 'mixed-chain-A');
  activateHandle(mixedChainA);
  const historicalSentence = '\n第三轮回看历史补充：先保留本地方案；当前候选尚未决定，待本人试玩后再申报。';
  const originalNoteId = objectBase.targetNotes.hero.feedbackId;
  const mixedInput = mixedChainA.dom.window.document.querySelector('#edit-text');
  mixedInput.value += historicalSentence;
  mixedInput.dispatchEvent(new mixedChainA.dom.window.Event('input', { bubbles: true }));
  cancelHistoryTimer(mixedChainA);
  await tick(); await tick();
  const immediatelySavedA = readObjectRecord(mixedChainHub);
  strict.ok(immediatelySavedA.targetNotes.hero.text.includes(historicalSentence), 'the exact appended historical sentence is the persisted active input');
  strict.equal(immediatelySavedA.targetNotes.hero.feedbackId, originalNoteId, 'ordinary continuation preserves the existing feedback identity');
  const editedNoteDiff = mixedChainA.app.renderDraftSemanticComparison(objectBase, immediatelySavedA).textContent;
  strict.match(editedNoteDiff, /修改 · 内容变化 · 意见原文/, 'the same note ID presents a full-text edit instead of delete plus add');
  strict.ok(editedNoteDiff.includes(objectBase.targetNotes.hero.text) && editedNoteDiff.includes(immediatelySavedA.targetNotes.hero.text),
    'semantic comparison retains both complete sides of the edited note');
  strict.equal(mixedChainHub.values.get(`ptah-studio-draft-v2:${savedCheckpointKey}`), savedCheckpointRaw, 'automatic saves leave the current restore point byte-for-byte unchanged');
  strict.equal(mixedChainHub.values.get(`ptah-studio-draft-v2:${savedBackupKey}`), savedBackupRaw, 'automatic saves leave the first backup byte-for-byte unchanged');
  const mixedChainFresh = await makeObjectApp(mixedChainHub, 'mixed-chain-fresh-reader');
  strict.ok(mixedChainFresh.app.sameDraftContent(mixedChainFresh.app.currentDraftRecord(), immediatelySavedA), 'a fresh app reads the full active draft with the appended historical sentence');
  closeHandles([mixedChainA, mixedChainFresh]);

  // R06-03: an absent field override inherits the current source context;
  // only this comparison row gets the explanation, while content removals stay removals.
  const propertyHub = new AutoStorageEventHub(objectStorageKey);
  propertyHub.values.set(objectStorageKey, JSON.stringify(structuredClone(objectBase)));
  const propertyApp = await makeObjectApp(propertyHub, 'property-source-comparison');
  const propertySnapshot = structuredClone(objectSnapshot);
  propertySnapshot.catalog.objects[0].fields.push(
    { id: 'max-health', label: '最大生命', type: 'scalar', value: 100, unit: '点' },
    { id: 'zero-value', label: '零值', type: 'scalar', value: 0 },
    { id: 'enabled', label: '启用', type: 'boolean', value: false },
    { id: 'nullable', label: '可空值', type: 'text', value: null },
    { id: 'empty-text', label: '空文本', type: 'text', value: '' },
    { id: 'undeclared', label: '未声明值', type: 'text' },
  );
  propertyApp.app.snapshot = propertySnapshot;
  propertyApp.app.capabilities = { fields: [
    ...structuredClone(objectCapabilities.fields),
    { id: 'hero.max-health', objectId: 'hero', fieldId: 'max-health', label: '最大生命', type: 'scalar', value: 100, unit: '点' },
    { id: 'hero.zero-value', objectId: 'hero', fieldId: 'zero-value', label: '零值', type: 'scalar', value: 0 },
    { id: 'hero.enabled', objectId: 'hero', fieldId: 'enabled', label: '启用', type: 'boolean', value: false },
    { id: 'hero.nullable', objectId: 'hero', fieldId: 'nullable', label: '可空值', type: 'text', value: null },
    { id: 'hero.empty-text', objectId: 'hero', fieldId: 'empty-text', label: '空文本', type: 'text', value: '' },
    { id: 'hero.capability-only', objectId: 'hero', fieldId: 'capability-only', label: '仅能力声明', type: 'scalar', editable: true },
  ] };
  propertyApp.app.pendingDraftConflict = { key: propertyApp.app.draftKey, snapshot: propertySnapshot,
    generation: propertyApp.app.workbenchGeneration, scope: propertyApp.app.draftConflictTarget(propertySnapshot) };
  const renderPropertyComparison = (leftFields, rightFields) => propertyApp.app.renderDraftSemanticComparison(
    { fields: leftFields }, { fields: rightFields });
  const rowsFor = comparison => [...comparison.querySelectorAll('.draft-conflict-diff')].map(row => row.textContent);
  const maxHealth = rowsFor(renderPropertyComparison({ 'hero.max-health': 120 }, {}));
  strict.equal(maxHealth.length, 1, 'a one-sided max-health override renders one property row');
  strict.match(maxHealth[0], /本轮属性修改不同/);
  strict.match(maxHealth[0], /本轮期望 120 点（尚未制作）/);
  strict.match(maxHealth[0], /无本轮覆盖；沿用来源版本 11 的当前值：100 点/);
  strict.doesNotMatch(maxHealth[0], /删除/);
  const reversedHealth = rowsFor(renderPropertyComparison({}, { 'hero.max-health': 120 }));
  strict.match(reversedHealth[0], /本页当前稿：无本轮覆盖；沿用来源版本 11 的当前值：100 点/);
  strict.match(reversedHealth[0], /存储活动稿：目标 角色/);
  const sourceCase = (fieldId, expected) => {
    const row = rowsFor(renderPropertyComparison({ [`hero.${fieldId}`]: 1 }, {}))[0];
    strict.ok(row, `${fieldId}: the one-sided field comparison is present`);
    strict.ok(row.includes(expected), `${fieldId}: source context is represented as ${expected}; actual=${row}`);
  };
  sourceCase('zero-value', '来源版本 11 的当前值：0');
  sourceCase('enabled', '来源版本 11 的当前值：false');
  sourceCase('nullable', '来源版本 11 的当前值：null（来源声明）');
  sourceCase('empty-text', '来源版本 11 的当前值：空文本');
  sourceCase('undeclared', '无本轮覆盖；来源当前值未声明');
  sourceCase('capability-only', '无本轮覆盖；来源当前值未声明');
  const unresolvedObject = rowsFor(renderPropertyComparison({ 'missing-object.health': 1 }, {}))[0];
  strict.match(unresolvedObject, /无本轮覆盖；来源当前值无法确认/);
  const removedNote = rowsFor(propertyApp.app.renderDraftSemanticComparison(
    { targetNotes: { hero: { objectId: 'hero', feedbackId: 'r06-removed-note', text: '保留非属性删除语义' } } },
    { targetNotes: {} }))[0];
  strict.match(removedNote, /删除 · 意见原文/);
  strict.match(removedNote, /存储活动稿：无此内容/);
  closeHandles([propertyApp]);

  // A same-scope input and explicit choice supersede unfinished envelope
  // callbacks; they must not restore the old pending state afterward.
  const overlapHub = new AutoStorageEventHub(objectStorageKey);
  overlapHub.values.set(objectStorageKey, JSON.stringify(structuredClone(objectBase)));
  const overlapWriter = await makeObjectApp(overlapHub, 'overlap-writer');
  const overlapLocal = await makeObjectApp(overlapHub, 'overlap-local');
  const overlapActive = objectDraft('overlap-remote', { operationId: 'overlap-remote-op' });
  const overlapLocalDraft = objectDraft('overlap-local', { speed: 315, operationId: 'overlap-local-op' });
  const overlapBranch = objectDraft('overlap-extra-branch', { speed: 345, operationId: 'overlap-extra-op' });
  activateHandle(overlapWriter); overlapWriter.app.applyVisibleDraft(structuredClone(overlapActive));
  activateHandle(overlapLocal); overlapLocal.app.applyVisibleDraft(structuredClone(overlapLocalDraft));
  activateHandle(overlapWriter); strict.equal(await overlapWriter.app.saveDraft(), true);
  await assertNaturallyDrained(overlapHub, 'overlap initial comparison');
  strict.ok(overlapLocal.app.pendingDraftConflict, 'the local app has an explicit comparison before the overlap');
  activateHandle(overlapWriter);
  await overlapWriter.app.saveConflictEnvelope(readObjectRecord(overlapHub), [overlapBranch], overlapWriter.app.draftStorageBaseline);
  const overlapEnvelopeRaw = overlapHub.values.get(objectStorageKey);
  const lateEnvelope = overlapLocal.app.handleDraftStorageEvent({ key: objectStorageKey,
    oldValue: overlapLocal.app.pendingDraftConflict.activeRaw, newValue: overlapEnvelopeRaw });
  activateHandle(overlapLocal);
  const overlapInput = overlapLocal.dom.window.document.querySelector('#edit-text');
  overlapInput.value += '\n同范围最新明确稿';
  overlapInput.dispatchEvent(new overlapLocal.dom.window.Event('input', { bubbles: true }));
  cancelHistoryTimer(overlapLocal);
  const selectedLocal = overlapLocal.app.currentDraftRecord();
  const latestChoice = overlapLocal.app.resolveDraftConflict('local');
  strict.equal(await latestChoice, true, 'the current same-scope explicit selection completes while older envelope callbacks are pending');
  await lateEnvelope;
  await assertNaturallyDrained(overlapHub, 'same-scope input and explicit choice during envelope handling');
  strict.equal(overlapLocal.app.pendingDraftConflict, null, 'late same-scope continuations do not rebuild the resolved pending comparison');
  strict.ok(overlapLocal.app.sameDraftContent(readObjectRecord(overlapHub), selectedLocal), 'the most recent explicitly selected local content remains active');
  const overlapFresh = await makeObjectApp(overlapHub, 'overlap-fresh-reader');
  strict.ok(overlapFresh.app.sameDraftContent(overlapFresh.app.currentDraftRecord(), selectedLocal), 'a new app reads the latest explicit choice');
  closeHandles([overlapWriter, overlapLocal, overlapFresh]);

  // Three current-code pages automatically deliver every storage write. A and
  // B retain distinct full drafts while C remains active; repeated notifications
  // must stop writing once that complete branch set exists.
  const propagationHub = new AutoStorageEventHub(objectStorageKey);
  propagationHub.values.set(objectStorageKey, JSON.stringify(structuredClone(objectBase)));
  const tabA = await makeObjectApp(propagationHub, 'A-mixed');
  const tabB = await makeObjectApp(propagationHub, 'B-alternative');
  const tabC = await makeObjectApp(propagationHub, 'C-current');
  const mixedDraft = objectDraft('混合稿', { speed: 290, operationId: 'mixed-operation-01' });
  const branchDraft = objectDraft('方案B', { speed: 270, operationId: 'branch-b-operation-01', selectedObjectId: 'guard-one' });
  const cCurrentDraft = objectDraft('C 当前稿', { speed: 300, operationId: 'current-c-operation-01' });
  activateHandle(tabA); tabA.app.applyVisibleDraft(structuredClone(mixedDraft));
  activateHandle(tabB); tabB.app.applyVisibleDraft(structuredClone(branchDraft));
  activateHandle(tabC); tabC.app.applyVisibleDraft(structuredClone(cCurrentDraft));
  strict.equal(await tabC.app.saveDraft(), true, 'the active page writes through the real DraftStore');
  const firstPropagation = await assertNaturallyDrained(propagationHub, 'three-page branch retention');
  strict.ok(firstPropagation.delivered > 0, 'the automatic storage-event queue delivered cross-page events');
  strict.equal(!!tabA.app.pendingDraftConflict, true, 'A retains an explicit decision while its content differs from the active draft');
  strict.equal(!!tabB.app.pendingDraftConflict, true, 'B retains an explicit decision while its content differs from the active draft');
  let propagated = readObjectRecord(propagationHub);
  strict.ok(hasBranch(propagated, tabA.app, mixedDraft), 'the complete mixed draft is retained as a recoverable branch');
  strict.ok(hasBranch(propagated, tabA.app, branchDraft), 'the complete B draft is retained as a recoverable branch');
  strict.ok(propagated.draftConflictAlternates.some(item => item.draft.fields['hero.speed'] === 270 && item.draft.structuralProposals[0].operationId === 'branch-b-operation-01'),
    'a retained branch keeps its field value and stable structural operation ID');
  const writesAtConvergence = propagationHub.writes.length, revisionAtConvergence = propagated.draftRevision;
  activateHandle(tabC); strict.equal(await tabC.app.saveDraft(), true, 'a later same-content save remains allowed');
  await assertNaturallyDrained(propagationHub, 'same-content notification after branch convergence');
  propagated = readObjectRecord(propagationHub);
  strict.equal(propagationHub.writes.length, writesAtConvergence + 1, 'only the deliberate same-content save writes; the other pages do not echo it');
  strict.equal(propagated.draftRevision, revisionAtConvergence + 1, 'conflict revisions stop increasing after all branches are retained');

  activateHandle(tabA);
  tabA.dom.window.document.querySelector('#draft-conflict-dialog .dialog-actions button').click();
  await tick();
  strict.equal(tabA.app.pendingDraftConflict, null, 'an explicit local choice clears A’s conflict');
  await assertNaturallyDrained(propagationHub, 'explicit selection propagation');
  propagated = readObjectRecord(propagationHub);
  strict.ok(tabA.app.sameDraftContent(propagated, mixedDraft), 'the explicitly selected mixed draft remains active after all events drain');
  strict.ok(tabA.dom.window.document.querySelector('#draft-state').textContent.includes('查看/恢复另一份草稿'), 'A exposes the preserved recovery entry after resolving the conflict');
  strict.ok(hasBranch(propagated, tabA.app, branchDraft), 'the unselected B branch remains recoverable after A is selected');
  const tabD = await makeObjectApp(propagationHub, 'D-fresh-reader');
  activateHandle(tabD);
  strict.ok(tabD.app.sameDraftContent(tabD.app.currentDraftRecord(), mixedDraft), 'a fresh page reads back the selected mixed draft');
  strict.ok(tabD.app.draftAlternates.some(item => tabD.app.sameDraftContent(item.draft, branchDraft)), 'a fresh page reads back the B branch');
  tabD.app.openDraftConflict();
  strict.equal(tabD.app.pendingDraftConflict.recovery, true, 'the branch picker is a recovery conflict, not a stale storage conflict');
  const bIndex = tabD.app.draftAlternates.findIndex(item => tabD.app.sameDraftContent(item.draft, branchDraft));
  strict.ok(bIndex >= 0, 'the exact B branch is selectable in the fresh page');
  [...tabD.dom.window.document.querySelectorAll('.draft-conflict-alternate')]
    .find(button => tabD.app.sameDraftContent(button.__draftAlternate, branchDraft))?.click();
  await tabD.app.resolveDraftConflict('remote');
  strict.ok(tabD.app.sameDraftContent(tabD.app.currentDraftRecord(), branchDraft), 'the fresh page explicitly restores the preserved B branch');
  await assertNaturallyDrained(propagationHub, 'fresh-page branch recovery');

  // A selected-object change plus exactly bound text/feedback editor mirrors and
  // known timestamps are navigation/representation differences only.
  const mirrorHub = new AutoStorageEventHub(objectStorageKey);
  const mirrorBase = structuredClone(objectBase);
  mirrorBase.feedbackInputs = { hero: { message: '角色待添加反馈', category: 'general' },
    'guard-one': { message: '守卫待添加反馈', category: 'bug' } };
  mirrorHub.values.set(objectStorageKey, JSON.stringify(mirrorBase));
  const mirrorA = await makeObjectApp(mirrorHub, 'mirror-hero', mirrorBase);
  const mirrorB = await makeObjectApp(mirrorHub, 'mirror-guard', mirrorBase);
  const guardView = { ...structuredClone(mirrorBase), selectedObjectId: 'guard-one', text: mirrorBase.targetNotes['guard-one'].text,
    feedbackMessage: '守卫待添加反馈', feedbackCategory: 'bug', feedbackInputTargetId: 'guard-one',
    targetNotes: structuredClone(mirrorBase.targetNotes) };
  guardView.targetNotes.hero.updatedAt = '2026-10-16T01:00:00.000Z';
  activateHandle(mirrorB);
  mirrorB.app.selectedObjectId = 'guard-one'; mirrorB.app.targetNotes = structuredClone(guardView.targetNotes);
  mirrorB.app.feedbackInputs = structuredClone(mirrorBase.feedbackInputs);
  mirrorB.dom.window.document.querySelector('#edit-text').value = guardView.text;
  mirrorB.app.loadFeedbackInputForCurrentTarget('guard-one');
  activateHandle(mirrorB);
  const mirrorLeft = mirrorB.app.draftContent(mirrorB.app.currentDraftRecord()), mirrorRight = mirrorB.app.draftContent(mirrorBase);
  strict.equal(mirrorB.app.sameDraftContent(mirrorB.app.currentDraftRecord(), mirrorBase), true,
    'navigation and accurately bound text/feedback mirrors compare as the same content');
  activateHandle(mirrorA);
  strict.equal(await mirrorA.app.saveDraft(), true, 'the comparison fixture writes a metadata-only update');
  await assertNaturallyDrained(mirrorHub, 'navigation and editor mirror update');
  strict.equal(mirrorB.app.pendingDraftConflict, null, 'matching target-bound editor mirrors do not open a false conflict');
  strict.equal(mirrorHub.writes.length, 1, 'matching mirrors do not cause an echo write');
  const wronglyBound = structuredClone(mirrorBase);
  wronglyBound.targetNotes.hero.objectId = 'guard-one';
  strict.equal(mirrorB.app.sameDraftContent(mirrorBase, wronglyBound), false, 'a true note target-binding change remains content');
  const legacyUnbound = { ...structuredClone(mirrorBase), text: '旧版未绑定原文', selectedObjectId: 'hero' };
  strict.equal(mirrorB.app.sameDraftContent(mirrorBase, legacyUnbound), false, 'an old unbound original text remains content');
  const changedPendingFeedback = structuredClone(mirrorBase);
  changedPendingFeedback.feedbackInputs.hero.message = '不同的待添加反馈';
  strict.equal(mirrorB.app.sameDraftContent(mirrorBase, changedPendingFeedback), false, 'a real pending feedback edit remains content');
  const zeroField = structuredClone(mirrorBase); zeroField.fields['hero.speed'] = 0;
  strict.equal(mirrorB.app.sameDraftContent(mirrorBase, zeroField), false, 'numeric zero remains a meaningful field value');
  activateHandle(mirrorB);
  mirrorB.app.selectedObjectId = 'reward'; mirrorB.app.legacyWorkbench.loadCurrentNote();
  strict.equal(mirrorB.dom.window.document.querySelector('#edit-text').value, '', 'navigating to a target without a note loads an empty text editor');
  strict.equal(mirrorB.app.sameDraftContent(mirrorB.app.currentDraftRecord(), mirrorBase), true,
    'an empty editor on a target without a note is not a content difference');
  closeHandles([mirrorA, mirrorB]);

  // If the visible page converges with the active content, a later matching
  // storage event clears only the stale non-recovery conflict. Recovery pickers
  // remain open and selectable through unrelated same-content events.
  const cleanupHub = new AutoStorageEventHub(objectStorageKey);
  cleanupHub.values.set(objectStorageKey, JSON.stringify(structuredClone(objectBase)));
  const cleanupWriter = await makeObjectApp(cleanupHub, 'cleanup-writer');
  const cleanupLocal = await makeObjectApp(cleanupHub, 'cleanup-local');
  const cleanupObserver = await makeObjectApp(cleanupHub, 'cleanup-observer');
  const activeDraft = objectDraft('活动稿', { speed: 300, operationId: 'cleanup-active-op' });
  const pendingDraft = objectDraft('本地分支', { speed: 310, operationId: 'cleanup-local-op' });
  activateHandle(cleanupWriter); cleanupWriter.app.applyVisibleDraft(structuredClone(activeDraft));
  activateHandle(cleanupLocal); cleanupLocal.app.applyVisibleDraft(structuredClone(pendingDraft));
  activateHandle(cleanupObserver); cleanupObserver.app.applyVisibleDraft(structuredClone(activeDraft));
  activateHandle(cleanupWriter); strict.equal(await cleanupWriter.app.saveDraft(), true);
  await assertNaturallyDrained(cleanupHub, 'initial conflict and local-branch preservation');
  strict.ok(cleanupLocal.app.pendingDraftConflict && !cleanupLocal.app.pendingDraftConflict.recovery, 'the differing local branch opens a normal conflict');
  activateHandle(cleanupLocal); cleanupLocal.app.applyVisibleDraft(structuredClone(activeDraft));
  activateHandle(cleanupObserver); strict.equal(await cleanupObserver.app.saveDraft(), true, 'a synchronized peer saves the now-matching content');
  await assertNaturallyDrained(cleanupHub, 'same-content arrival after a pending conflict');
  strict.equal(cleanupLocal.app.pendingDraftConflict, null, 'same-content arrival clears the stale non-recovery conflict');
  strict.ok(cleanupLocal.dom.window.document.querySelector('#draft-state').textContent.includes('查看/恢复另一份草稿'), 'the formerly conflicting local branch remains recoverable');
  activateHandle(cleanupLocal);
  cleanupLocal.app.openDraftConflict();
  strict.equal(cleanupLocal.app.pendingDraftConflict.recovery, true, 'opening the branch picker creates a recovery choice');
  activateHandle(cleanupObserver); strict.equal(await cleanupObserver.app.saveDraft(), true, 'the observer sends another matching-content notification');
  await assertNaturallyDrained(cleanupHub, 'same-content arrival during recovery selection');
  strict.equal(cleanupLocal.app.pendingDraftConflict?.recovery, true, 'an unrelated same-content event does not cancel recovery selection');
  strict.ok(cleanupLocal.dom.window.document.querySelector('#draft-conflict-dialog .dialog-actions button:last-child'), 'recovery actions remain available');
  closeHandles([cleanupWriter, cleanupLocal, cleanupObserver]);

  // R03-P2: recovery choices show readable timestamps and content summaries,
  // and selection stays bound to the complete branch when another is appended.
  const pickerHub = new AutoStorageEventHub(objectStorageKey);
  const pickerActive = objectDraft('选择器活动稿', { speed: 280, operationId: 'picker-active-op' });
  const pickerA = objectDraft('意见甲：窄屏下动作偏快', { speed: 310, operationId: 'picker-a-op', noteText: '意见甲：窄屏下动作偏快' });
  const pickerALong = { ...structuredClone(pickerA), targetNotes: { ...structuredClone(pickerA.targetNotes), reward: {
    objectId: 'reward', feedbackId: 'picker-reward-note', text: `既有的奖励目标意见内容用于测试摘要尾部仍可辨识${'早期描述'.repeat(8)}窄屏最后追加的新意见`,
  } } };
  const pickerB = objectDraft('意见乙：转向反馈不足', { speed: 270, operationId: 'picker-b-op', selectedObjectId: 'guard-one', noteText: '意见乙：转向反馈不足' });
  const pickerC = objectDraft('第三份新保留版本', { speed: 320, operationId: 'picker-c-op', noteText: '第三份新保留版本意见' });
  const pickerBranches = [
    { label: '较早保留版本 A', capturedAt: '2026-10-16T09:15:00.000Z', draft: structuredClone(pickerALong) },
    { label: '缺少时间的保留版本 B', draft: structuredClone(pickerB) },
  ];
  for (let index = 2; index < 54; index++) {
    const branch = objectDraft(`长列表版本 ${index + 1}`, { speed: 330 + index, operationId: `picker-long-${index}-op`, noteText: `长列表完整正文 ${index}` });
    pickerBranches.push({ label: `保留版本 ${index + 1}`, capturedAt: new Date(Date.UTC(2026, 9, 16, 9, 16 + index)).toISOString(), draft: structuredClone(branch) });
  }
  const pickerSeed = { ...structuredClone(pickerActive), draftConflictAlternates: [
    ...pickerBranches,
  ] };
  pickerHub.values.set(objectStorageKey, JSON.stringify(pickerSeed));
  const picker = await makeObjectApp(pickerHub, 'stable-picker');
  activateHandle(picker); picker.app.openDraftConflict();
  let pickerButtons = [...picker.dom.window.document.querySelectorAll('.draft-conflict-alternate')];
  strict.equal(pickerButtons.length, 54, 'the picker renders a large version history without dropping stored branches');
  strict.ok(pickerButtons[0].textContent.includes('383') && pickerButtons[0].textContent.includes('保留版本 54'), 'the most recent retained draft appears first');
  strict.ok(pickerButtons.at(-1).textContent.includes('2026') && pickerButtons.at(-1).textContent.includes('310') && pickerButtons.at(-1).textContent.includes('意见甲'), 'an earlier draft remains selectable at the end of recent-first order');
  strict.ok(pickerButtons.at(-1).textContent.includes('reward') && pickerButtons.at(-1).textContent.includes('窄屏最后追加的新意见'), 'the complete summary source retains a long note tail');
  strict.ok(pickerButtons.find(button => picker.app.sameDraftContent(button.__draftAlternate, pickerB)).textContent.includes('时间未知'), 'missing capturedAt is shown as unknown rather than invented');
  const chooseA = pickerButtons.find(button => picker.app.sameDraftContent(button.__draftAlternate, pickerALong));
  chooseA.focus();
  chooseA.click();
  strict.ok(picker.app.sameDraftContent(picker.app.pendingDraftConflict.remote, pickerALong), 'selection binds to the chosen full draft content');
  strict.ok(picker.app.sameDraftContent(picker.dom.window.document.activeElement?.__draftAlternate, pickerALong), 'rerendering after a choice restores keyboard focus to the same full draft identity');
  const search = picker.dom.window.document.querySelector('[data-draft-alternate-search="true"]');
  search.focus(); search.value = '窄屏最后追加的新意见'; search.dispatchEvent(new picker.dom.window.Event('input', { bubbles: true }));
  pickerButtons = [...picker.dom.window.document.querySelectorAll('.draft-conflict-alternate')];
  strict.equal(pickerButtons.length, 1, 'filtering matches the complete note tail even when the two-line summary is clipped');
  strict.ok(picker.app.sameDraftContent(pickerButtons[0].__draftAlternate, pickerALong), 'filtering does not substitute a different complete draft');
  strict.equal(picker.dom.window.document.querySelector('.draft-conflict-filter-count').textContent, '找到 1 / 54 份保留版本');
  search.value = '没有这样的完整内容'; search.dispatchEvent(new picker.dom.window.Event('input', { bubbles: true }));
  strict.equal(picker.dom.window.document.querySelectorAll('.draft-conflict-alternate').length, 0, 'a nonmatching query shows no stale choices');
  strict.match(picker.dom.window.document.querySelector('.draft-conflict-empty').textContent, /没有匹配/);
  search.value = '窄屏最后追加的新意见'; search.dispatchEvent(new picker.dom.window.Event('input', { bubbles: true }));
  picker.dom.window.document.querySelector('[data-draft-conflict-action="clear-filter"]').click();
  strict.equal(picker.dom.window.document.querySelectorAll('.draft-conflict-alternate').length, 54, 'clearing the filter restores every full version');
  strict.equal(picker.dom.window.document.activeElement, search, 'clearing the filter keeps keyboard focus in the search field');
  strict.ok(picker.dom.window.document.querySelector('.draft-conflict-compare') && picker.dom.window.document.querySelector('.draft-conflict-full-json'), 'the full semantic and JSON comparisons remain available');
  strict.equal(picker.dom.window.document.querySelector('#draft-conflict-dialog').lastElementChild.className, 'dialog-actions', 'confirmation actions remain outside and after the version list and comparison scroller');
  const pickerPeer = await makeObjectApp(pickerHub, 'picker-peer');
  activateHandle(pickerPeer);
  await pickerPeer.app.saveConflictEnvelope(readObjectRecord(pickerHub), [pickerC], pickerPeer.app.draftStorageBaseline);
  await assertNaturallyDrained(pickerHub, 'new unrelated branch during recovery selection');
  strict.equal(picker.app.pendingDraftConflict?.recovery, true, 'an envelope-only append keeps the recovery comparison open');
  strict.ok(picker.app.sameDraftContent(picker.app.pendingDraftConflict.remote, pickerALong), 'the selected branch remains the same full content after the list changes');
  pickerButtons = [...picker.dom.window.document.querySelectorAll('.draft-conflict-alternate')];
  strict.equal(pickerButtons.length, 55, 'the new complete branch is available without replacing existing choices');
  strict.equal(pickerButtons.filter(button => button.getAttribute('aria-pressed') === 'true').length, 1);
  strict.ok(pickerButtons.find(button => picker.app.sameDraftContent(button.__draftAlternate, pickerALong)).getAttribute('aria-pressed') === 'true', 'pressed state follows content identity rather than an old array index');
  await picker.app.resolveDraftConflict('remote');
  strict.ok(picker.app.sameDraftContent(readObjectRecord(pickerHub), pickerALong), 'confirming the stable choice activates the exact selected version');
  strict.ok(hasBranch(readObjectRecord(pickerHub), picker.app, pickerB) && hasBranch(readObjectRecord(pickerHub), picker.app, pickerC), 'unselected complete branches remain recoverable');
  closeHandles([picker, pickerPeer]);

  // A third real write after comparison must survive the first confirmation;
  // only a later explicit choice may replace it.
  const thirdWriteHub = new AutoStorageEventHub(objectStorageKey);
  thirdWriteHub.values.set(objectStorageKey, JSON.stringify(structuredClone(objectBase)));
  const thirdWriter = await makeObjectApp(thirdWriteHub, 'third-writer');
  const thirdLocal = await makeObjectApp(thirdWriteHub, 'third-local');
  const thirdPeer = await makeObjectApp(thirdWriteHub, 'third-peer');
  const draftX = objectDraft('第一份', { speed: 320, operationId: 'third-x-op' });
  const draftY = objectDraft('第二份', { speed: 330, operationId: 'third-y-op' });
  const draftZ = objectDraft('第三份', { speed: 340, operationId: 'third-z-op' });
  activateHandle(thirdWriter); thirdWriter.app.applyVisibleDraft(structuredClone(draftX));
  activateHandle(thirdLocal); thirdLocal.app.applyVisibleDraft(structuredClone(draftY));
  activateHandle(thirdPeer); thirdPeer.app.applyVisibleDraft(structuredClone(draftX));
  activateHandle(thirdWriter); strict.equal(await thirdWriter.app.saveDraft(), true);
  await assertNaturallyDrained(thirdWriteHub, 'first comparison before third write');
  strict.ok(thirdLocal.app.pendingDraftConflict, 'the local page is comparing against draft X');
  activateHandle(thirdPeer); thirdPeer.app.applyVisibleDraft(structuredClone(draftZ));
  strict.equal(await thirdPeer.app.saveDraft(), true, 'the synchronized peer creates a genuine third write');
  const thirdBeforeConfirm = readObjectRecord(thirdWriteHub);
  strict.ok(thirdLocal.app.sameDraftContent(thirdBeforeConfirm, draftZ), 'draft Z is active immediately before the stale confirmation');
  activateHandle(thirdLocal); await thirdLocal.app.resolveDraftConflict('local');
  strict.ok(thirdLocal.app.pendingDraftConflict, 'the first confirmation refreshes comparison instead of resolving over a third write');
  strict.ok(thirdLocal.app.sameDraftContent(readObjectRecord(thirdWriteHub), draftZ), 'the third write remains active after the first confirmation');
  await assertNaturallyDrained(thirdWriteHub, 'third-write recompare propagation');
  strict.ok(thirdLocal.app.pendingDraftConflict, 'the refreshed comparison remains explicit');
  activateHandle(thirdLocal);
  await thirdLocal.app.resolveDraftConflict('local');
  await assertNaturallyDrained(thirdWriteHub, 'explicit choice after third-write recompare');
  strict.ok(thirdLocal.app.sameDraftContent(readObjectRecord(thirdWriteHub), draftY), 'a second explicit choice can select the preserved local draft');
  closeHandles([thirdWriter, thirdLocal, thirdPeer]);

  // A storage failure while adding a branch preserves both the pending choice
  // and current input and never reports a successful retention.
  const failureHub = new AutoStorageEventHub(objectStorageKey);
  failureHub.values.set(objectStorageKey, JSON.stringify(structuredClone(objectBase)));
  const failureWriter = await makeObjectApp(failureHub, 'failure-writer');
  const failureLocal = await makeObjectApp(failureHub, 'failure-local');
  activateHandle(failureWriter); failureWriter.app.applyVisibleDraft(structuredClone(activeDraft));
  activateHandle(failureLocal); failureLocal.app.applyVisibleDraft(structuredClone(pendingDraft));
  strict.equal(await failureWriter.app.saveDraft(), true);
  const rawBeforeFailure = failureHub.values.get(objectStorageKey);
  failureHub.failNextWrite = true;
  await assertNaturallyDrained(failureHub, 'write-failure branch retention');
  strict.ok(failureLocal.app.pendingDraftConflict, 'write failure keeps the explicit comparison pending');
  strict.equal(failureLocal.dom.window.document.querySelector('#edit-text').value, pendingDraft.text, 'write failure leaves local input visible');
  strict.equal(failureHub.values.get(objectStorageKey), rawBeforeFailure, 'write failure leaves the active stored record byte-for-byte unchanged');
  closeHandles([failureWriter, failureLocal]);

  oldTab.destroy(); newTab.destroy(); oldDom.window.close(); newDom.window.close();
  if (savedDocument) global.document = savedDocument; else delete global.document;
  if (savedLocation) global.location = savedLocation; else delete global.location;
  if (savedHistory) global.history = savedHistory; else delete global.history;
  console.log('PASS Studio N2 cross-tab draft QA: storage-event conflict, same-publication refresh recovery, scope-change protection, conditional writes, persisted alternates, explicit restore choices, and zero Agent POSTs');
  console.log(`N2 automatic storage-event propagation: ${JSON.stringify(drainObservations)}`);
})().catch(error => { console.error(error.stack || error); process.exitCode = 1; });
