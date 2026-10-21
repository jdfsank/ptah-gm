#!/usr/bin/env node
/* Focused QA for history baselining after an asynchronously restored draft. */
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const { pathToFileURL } = require('node:url');
let JSDOM;
try { ({ JSDOM } = require('jsdom')); }
catch { console.log('SKIP Studio restore-history QA: jsdom is unavailable.'); process.exit(0); }

const root = path.resolve(__dirname, '..');
const dom = new JSDOM(fs.readFileSync(path.join(root, 'studio/index.html'), 'utf8'), {
  url: 'http://127.0.0.1:8123/studio/?project=restore-history&stage=iteration', pretendToBeVisual: true,
});
global.document = dom.window.document;
global.localStorage = dom.window.localStorage;
global.location = dom.window.location;
global.history = dom.window.history;

(async () => {
  const { StudioApp } = await import(pathToFileURL(path.join(root, 'studio/studio.js')).href);
  const app = new StudioApp({ documentImpl: dom.window.document });
  const fieldInput = document.createElement('input');
  fieldInput.dataset.fieldId = 'dice.warning-duration'; fieldInput.dataset.capabilityId = 'dice.warning-duration';
  fieldInput.dataset.objectId = 'dice'; fieldInput.dataset.type = 'number';
  document.querySelector('#dynamic-fields').append(fieldInput);
  const snapshot = {
    projectId: 'restore-history', publicationRevision: 7, sourceCommit: 'git-history-base', workflow: 'objects-v1', kind: 'MVP',
    catalog: { objects: [
      { id: 'player', kind: 'entity', name: '玩家', fields: [], relations: [], workbench: { role: 'instance' } },
      { id: 'arena-instance', kind: 'entity', name: '竞技场实例', fields: [], relations: [], workbench: { role: 'instance' } },
      { id: 'dice', kind: 'entity', name: '骰子', fields: [], relations: [], workbench: { role: 'behavior', preview: { type: 'action', stages: [{ label: '预警', durationFieldId: 'warning-duration', duration: 1.5 }] } } },
    ] },
    document: { objects: [
      { id: 'player', fields: [], relations: [] }, { id: 'arena-instance', fields: [], relations: [] },
      { id: 'dice', fields: [{ id: 'warning-duration', type: 'number', value: 1.5 }], relations: [] },
    ] },
  };
  const restoredDraft = {
    selectedObjectId: 'dice', fields: { 'dice.warning-duration': 1.5 },
    targetNotes: { dice: { objectId: 'dice', text: '270+aceb', feedbackId: 'aceb' } },
    structuralProposals: [], feedback: [], feedbackMessage: '', feedbackCategory: 'general', values: {}, draftRevision: 3,
  };
  app.projectId = snapshot.projectId; app.stage = 'iteration'; app.snapshot = snapshot;
  app.workspace = { storeId: 'restore-history-store' }; app.workflow = 'objects-v1'; app.persistenceOK = true;
  app.workbenchGeneration = 1; app.draftKey = app.makeDraftKey(snapshot);
  let storedRaw = JSON.stringify({ ...restoredDraft, key: app.draftKey, projectId: snapshot.projectId,
    publicationRevision: snapshot.publicationRevision, sourceCommit: snapshot.sourceCommit, baseCommit: null });
  app.drafts = {
    get: async key => key === app.draftKey ? JSON.parse(storedRaw) : null,
    raw: () => storedRaw,
    readStored: (key, raw) => {
      const record = JSON.parse(raw);
      if (record.key !== key) throw new Error('draft record key mismatch');
      return record;
    },
  };
  app.showDraftState = () => {};
  app.queueDraftSave = async () => { storedRaw = JSON.stringify(app.currentDraftRecord()); return true; };
  app.bind();
  app.readVisibleDraft = () => {
    const activeFeedback = app.selectedObjectId ? app.feedbackInputs?.[app.selectedObjectId] : null;
    return {
      text: document.querySelector('#edit-text').value || '', values: {}, fields: { ...app.fieldDraftValues },
      feedback: structuredClone(app.feedback || []), feedbackInputs: structuredClone(app.feedbackInputs || {}),
      feedbackInputTargetId: activeFeedback?.message ? app.selectedObjectId : null,
      legacyUnboundFeedback: structuredClone(app.legacyUnboundFeedback || null),
      feedbackMessage: activeFeedback?.message || app.legacyUnboundFeedback?.message || '',
      feedbackCategory: activeFeedback?.category || app.legacyUnboundFeedback?.category || 'general',
      targetNotes: structuredClone(app.targetNotes), structuralProposals: structuredClone(app.structuralProposals),
      proposalInputs: structuredClone(app.proposalInputs || {}),
      selectedObjectId: app.selectedObjectId, draftRevision: app.draftRevision,
    };
  };
  app.renderDynamicFields = () => {};
  app.renderObjectCatalog = () => {};
  app.renderObjectDetail = () => {};
  app.renderFeedback = () => {};
  app.legacyWorkbench.render = () => {};

  await app.restoreDraft();
  const wb = app.legacyWorkbench;
  assert.equal(app.fieldDraftValues['dice.warning-duration'], 1.5, 'the stored numeric field is restored');
  assert.equal(app.targetNotes.dice.text, '270+aceb', 'the stored target note is restored');
  assert.equal(wb.history.length, 1, 'the restored draft becomes a single clean undo baseline');

  const pendingTimers = [];
  const originalSetTimeout = globalThis.setTimeout, originalClearTimeout = globalThis.clearTimeout;
  globalThis.setTimeout = (callback, delay) => { pendingTimers.push({ callback, delay }); return pendingTimers.length; };
  globalThis.clearTimeout = () => {};
  fieldInput.value = '2'; fieldInput.dispatchEvent(new dom.window.Event('input', { bubbles: true }));
  await Promise.resolve();
  assert.equal(app.fieldDraftValues['dice.warning-duration'], 2, 'the first post-restore input is captured by the app');
  pendingTimers.at(-1).callback();
  assert.deepEqual(wb.resolvePreview(app.objectItems().find(object => object.id === 'dice')).stages.map(stage => stage.duration), [2], 'the restored field edit also refreshes the preview duration');
  assert.equal(wb.history.length, 2, 'the first post-restore field edit is one step after the restored baseline');
  await wb.undo();
  assert.equal(app.fieldDraftValues['dice.warning-duration'], 1.5, 'undo restores the previously saved field value');
  assert.equal(fieldInput.value, '1.5', 'undo restores the visible control');
  assert.equal(app.targetNotes.dice.text, '270+aceb', 'undo preserves the restored note');
  await wb.redo();
  assert.equal(app.fieldDraftValues['dice.warning-duration'], 2, 'redo restores the new field value');
  assert.equal(fieldInput.value, '2', 'redo restores the visible control');
  assert.equal(app.targetNotes.dice.text, '270+aceb', 'redo preserves the restored note');

  globalThis.setTimeout = originalSetTimeout;
  globalThis.clearTimeout = originalClearTimeout;

  class MemoryDrafts {
    constructor() { this.records = new Map(); this.writes = 0; this.corruptRecords = new Map(); }
    raw(key) { return this.records.get(key) ?? null; }
    readStored(key, raw) {
      const record = JSON.parse(raw);
      if (!record || typeof record !== 'object' || Array.isArray(record) || record.key !== key) throw new Error('draft record key mismatch');
      return record;
    }
    async get(key) { const raw = this.raw(key); return raw === null ? null : this.readStored(key, raw); }
    putIfUnchanged(record, expectedRaw) {
      if (this.raw(record.key) !== expectedRaw) {
        const error = new Error('draft record changed before compare-and-set'); error.name = 'DraftConflictError';
        error.latestRaw = this.raw(record.key); error.latest = error.latestRaw == null ? null : this.readStored(record.key, error.latestRaw);
        throw error;
      }
      this.records.set(record.key, JSON.stringify(record)); this.writes++;
      return record;
    }
    async put(record) { return this.putIfUnchanged(record, this.raw(record.key)); }
  }
  const routeCalls = { push: 0, replace: 0 };
  const nativePushState = history.pushState.bind(history), nativeReplaceState = history.replaceState.bind(history);
  history.pushState = (...args) => { routeCalls.push++; return nativePushState(...args); };
  history.replaceState = (...args) => { routeCalls.replace++; return nativeReplaceState(...args); };
  const routeTarget = () => new URL(location.href).searchParams.get('target') || 'project';
  const projectKey = app.draftKey;
  const checkpointKey = wb.savedCheckpointKey(projectKey), backupKey = wb.savedCheckpointBackupKey(projectKey);
  const makeRouteDraft = (name, targetId, fieldValue) => {
    const noteKey = targetId || '__project__';
    return {
      text: '', values: {}, fields: { 'dice.warning-duration': fieldValue },
      feedback: [{ feedbackId: 'feedback-' + name, objectId: targetId || 'project', category: 'note', message: '完整反馈 ' + name }],
      feedbackInputs: {}, feedbackInputTargetId: null, legacyUnboundFeedback: null,
      feedbackMessage: '', feedbackCategory: 'general', selectedObjectId: targetId,
      targetNotes: { [noteKey]: { objectId: targetId, text: '完整意见 ' + name, feedbackId: 'note-' + name } },
      structuralProposals: [{ operationId: 'operation-' + name, kind: 'move-instance', objectId: targetId || 'player', requestedPosition: [10, 20] }],
      proposalInputs: {}, draftRevision: name === 'B' ? 3 : 4,
    };
  };
  const draftA = makeRouteDraft('A', 'arena-instance', 1.5);
  const draftB = makeRouteDraft('B', 'player', 2.5);
  const recordFor = (recordKey, draft, extra = {}) => ({ ...structuredClone(draft), key: recordKey,
    projectId: snapshot.projectId, publicationRevision: snapshot.publicationRevision,
    sourceCommit: snapshot.sourceCommit, baseCommit: null, updatedAt: '2026-10-17T00:00:00.000Z', ...extra });
  const memoryDrafts = new MemoryDrafts();
  const activeRecord = recordFor(projectKey, draftB);
  memoryDrafts.records.set(projectKey, JSON.stringify(activeRecord));
  const checkpointRecord = recordFor(checkpointKey, draftA, { baseDraftKey: projectKey,
    savedAt: '2026-10-17T00:01:00.000Z', checkpoint: true });
  const backupRecord = recordFor(backupKey, draftB, { baseDraftKey: projectKey,
    savedAt: '2026-10-17T00:00:00.000Z', checkpoint: false, checkpointBackup: true });
  memoryDrafts.records.set(checkpointKey, JSON.stringify(checkpointRecord));
  memoryDrafts.records.set(backupKey, JSON.stringify(backupRecord));
  const checkpointRawBefore = memoryDrafts.raw(checkpointKey), backupRawBefore = memoryDrafts.raw(backupKey);
  const activeRawBefore = memoryDrafts.raw(projectKey);
  app.drafts = memoryDrafts; app.draftKey = projectKey; app.draftRevision = draftB.draftRevision;
  app.draftBaselineKey = projectKey; app.draftStorageBaseline = activeRawBefore; app.draftAlternates = [];
  app.persistenceOK = true; app.pendingDraftConflict = null; app.draftSaveQueuedDuringRestore = false;
  app.queueDraftSave = async () => false;
  let lastDraftState = '';
  app.showDraftState = message => { lastDraftState = String(message || ''); };
  app.applyVisibleDraft(draftB);
  wb.syncUrl();
  wb.resetHistory();
  routeCalls.push = 0; routeCalls.replace = 0;
  const navigateWithoutCapturingFixtureControl = targetId => {
    const wasDisabled = fieldInput.disabled;
    fieldInput.disabled = true;
    wb.locateTarget(targetId);
    fieldInput.disabled = wasDisabled;
  };

  const assertVisibleRouteDraft = (draft, label) => {
    const keyForNote = draft.selectedObjectId || '__project__';
    assert.equal(app.selectedObjectId, draft.selectedObjectId, label + ': selected target follows the applied draft');
    assert.equal(routeTarget(), draft.selectedObjectId || 'project', label + ': URL follows the applied target');
    assert.equal(app.legacyWorkbench.currentNote(), draft.targetNotes[keyForNote].text, label + ': note binding follows the applied target');
    assert.equal(document.querySelector('#edit-text').value, draft.targetNotes[keyForNote].text, label + ': visible note text follows the target');
    assert.deepEqual(app.feedback, draft.feedback, label + ': complete feedback remains');
    assert.deepEqual(app.fieldDraftValues, draft.fields, label + ': field values remain');
    assert.deepEqual(app.structuralProposals, draft.structuralProposals, label + ': structure remains');
  };

  await wb.restoreSavedDraft();
  assertVisibleRouteDraft(draftA, 'explicit checkpoint restore');
  assert.equal(routeCalls.replace, 1, 'checkpoint replacement updates the route with replaceState');
  assert.equal(routeCalls.push, 0, 'checkpoint replacement does not add a navigation history entry');
  assert.equal(memoryDrafts.raw(projectKey), activeRawBefore, 'a blocked follow-up save leaves the active raw draft untouched');
  assert.match(lastDraftState, /未完成持久保存/, 'the page keeps the existing unsaved state after a blocked follow-up save');
  assert.equal(memoryDrafts.raw(checkpointKey), checkpointRawBefore, 'restore never rewrites the saved checkpoint raw record');
  assert.equal(memoryDrafts.raw(backupKey), backupRawBefore, 'restore never rewrites the first backup raw record');

  await wb.restoreHistory(0);
  assertVisibleRouteDraft(draftB, 'undo after checkpoint restore');
  assert.equal(routeCalls.push, 0, 'undo uses route replacement rather than ordinary navigation');
  await wb.restoreHistory(1);
  assertVisibleRouteDraft(draftA, 'redo after checkpoint restore');
  assert.equal(routeCalls.push, 0, 'redo uses route replacement rather than ordinary navigation');

  let finishDelayedSave;
  app.queueDraftSave = () => new Promise(resolve => { finishDelayedSave = resolve; });
  const delayedUndo = wb.restoreHistory(0);
  assertVisibleRouteDraft(draftB, 'undo before delayed save');
  const replaceCountBeforeNavigation = routeCalls.replace;
  app.queueDraftSave = async () => false;
  navigateWithoutCapturingFixtureControl('dice');
  assert.equal(routeTarget(), 'dice', 'ordinary target navigation remains visible during the old save');
  const pushCountAfterNavigation = routeCalls.push;
  assert.equal(pushCountAfterNavigation, 1, 'ordinary target navigation keeps its existing pushState behavior');
  finishDelayedSave(true);
  await delayedUndo;
  assert.equal(routeTarget(), 'dice', 'an older save completion cannot restore the previous route');
  assert.equal(routeCalls.replace, replaceCountBeforeNavigation, 'the save continuation performs no route replacement');

  const savedCheckpoint = memoryDrafts.readStored(checkpointKey, checkpointRawBefore);
  const savedBackup = memoryDrafts.readStored(backupKey, backupRawBefore);
  const originalGet = memoryDrafts.get.bind(memoryDrafts);
  let finishStaleRead;
  memoryDrafts.get = requestedKey => requestedKey === checkpointKey
    ? new Promise(resolve => { finishStaleRead = resolve; }) : originalGet(requestedKey);
  const replaceCountBeforeStaleRead = routeCalls.replace;
  const staleRestore = wb.restoreSavedDraft();
  await Promise.resolve();
  assert.equal(typeof finishStaleRead, 'function', 'the checkpoint read is held at its existing asynchronous boundary');
  app.workbenchGeneration++;
  navigateWithoutCapturingFixtureControl('player');
  const routeAfterNewerNavigation = routeTarget();
  assert.equal(routeAfterNewerNavigation, 'player');
  finishStaleRead(savedCheckpoint);
  await staleRestore;
  memoryDrafts.get = originalGet;
  assert.equal(app.selectedObjectId, 'player', 'a checkpoint read from an older generation cannot apply');
  assert.equal(routeTarget(), 'player', 'a stale checkpoint read cannot replace a newer route');
  assert.equal(routeCalls.replace, replaceCountBeforeStaleRead, 'the stale read performs no route replacement');
  assert.equal(memoryDrafts.raw(checkpointKey), checkpointRawBefore, 'the stale read leaves the checkpoint raw record intact');
  assert.equal(memoryDrafts.raw(backupKey), backupRawBefore, 'the stale read leaves the first backup raw record intact');

  const setConflict = (remoteDraft, recovery = false) => {
    const currentRaw = memoryDrafts.raw(projectKey);
    const currentStored = memoryDrafts.readStored(projectKey, currentRaw);
    const conflict = { key: projectKey, local: app.currentDraftRecord(), remote: structuredClone(remoteDraft),
      activeRaw: currentRaw, remoteRaw: currentRaw, comparisonActive: currentStored, prior: null,
      recovery, refreshing: false, scopeChanged: false, generation: app.workbenchGeneration,
      snapshot: app.snapshot, scope: app.draftConflictTarget(app.snapshot) };
    app.pendingDraftConflict = conflict; app.draftBaselineKey = projectKey; app.draftStorageBaseline = currentRaw;
    return conflict;
  };
  const beforeRemote = { ...routeCalls };
  setConflict(draftA);
  assert.equal(await app.resolveDraftConflict('remote'), true, 'explicit remote conflict resolution succeeds through the original CAS path');
  assertVisibleRouteDraft(draftA, 'explicit remote resolution');
  assert.equal(routeCalls.replace, beforeRemote.replace + 1, 'explicit remote resolution replaces the route');
  assert.equal(routeCalls.push, beforeRemote.push, 'explicit remote resolution adds no navigation entry');
  assert.equal(memoryDrafts.raw(checkpointKey), checkpointRawBefore, 'remote resolution leaves the checkpoint untouched');
  assert.equal(memoryDrafts.raw(backupKey), backupRawBefore, 'remote resolution leaves the first backup untouched');

  const beforeLocal = { ...routeCalls };
  setConflict(draftB);
  assert.equal(await app.resolveDraftConflict('local'), true, 'explicit local resolution keeps the current complete draft');
  assert.equal(app.selectedObjectId, 'arena-instance', 'local resolution does not select the remote target');
  assert.equal(routeTarget(), 'arena-instance', 'local resolution does not change the route');
  assert.deepEqual(routeCalls, beforeLocal, 'local resolution makes no route history changes');

  const projectDraft = makeRouteDraft('project', null, 3.5);
  const beforeProject = { ...routeCalls };
  setConflict(projectDraft);
  assert.equal(await app.resolveDraftConflict('remote'), true, 'remote resolution accepts an explicitly selected project draft');
  assertVisibleRouteDraft(projectDraft, 'explicit project-target resolution');
  assert.equal(routeCalls.replace, beforeProject.replace + 1, 'a null selected target maps to project with replaceState');
  assert.equal(routeCalls.push, beforeProject.push, 'the project-target replacement adds no navigation entry');

  const beforeDefer = { ...routeCalls };
  const deferredConflict = setConflict(draftB, true);
  assert.equal(app.deferDraftConflict(deferredConflict), true, 'safe historical defer ends browsing without applying the retained target');
  assert.equal(app.selectedObjectId, null, 'defer keeps the current project target');
  assert.equal(routeTarget(), 'project', 'defer does not change the route');
  assert.deepEqual(routeCalls, beforeDefer, 'defer makes no route history changes');
  assert.equal(memoryDrafts.raw(checkpointKey), checkpointRawBefore, 'the focused route paths preserve the saved checkpoint');
  assert.equal(memoryDrafts.raw(backupKey), backupRawBefore, 'the focused route paths preserve the first backup');

  wb.stopPreview();
  dom.window.close();
  console.log('PASS Studio restore-history QA: restore baseline, undo/redo, guarded replacement routes, resolver CAS choice, stale read and delayed save navigation');
})().catch(error => { console.error(error.stack || error); process.exitCode = 1; dom.window.close(); });
