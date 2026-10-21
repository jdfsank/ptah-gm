#!/usr/bin/env node
/* Focused fixture for safe historical-browse defer followed by the original CAS save. */
const assert = require('node:assert/strict');
const { pathToFileURL } = require('node:url');
const path = require('node:path');
let JSDOM;
try { ({ JSDOM } = require('jsdom')); }
catch { console.log('SKIP studio history defer CAS QA: jsdom is unavailable.'); process.exit(0); }
let StudioApp;

const dom = new JSDOM('<!doctype html><body><textarea id="edit-text"></textarea><div id="draft-state"></div></body>', {
  url: 'http://127.0.0.1:8123/studio/?project=history-defer-test', pretendToBeVisual: true,
});
global.document = dom.window.document;
global.localStorage = dom.window.localStorage;

class MemoryDrafts {
  constructor() { this.records = new Map(); this.writes = 0; this.corruptRecords = new Map(); }
  raw(key) { return this.records.get(key) ?? null; }
  readStored(key, raw) {
    const record = JSON.parse(raw);
    if (!record || typeof record !== 'object' || Array.isArray(record) || record.key !== key) throw new Error('Draft identity mismatch');
    return record;
  }
  externalSet(key, value) { this.records.set(key, JSON.stringify(value)); }
  putIfUnchanged(value, expectedRaw) {
    if (this.raw(value.key) !== expectedRaw) {
      const error = new Error('Draft changed during save'); error.name = 'DraftConflictError';
      error.latestRaw = this.raw(value.key); error.latest = error.latestRaw == null ? null : this.readStored(value.key, error.latestRaw);
      throw error;
    }
    const raw = JSON.stringify(value); this.records.set(value.key, raw); this.writes++;
    return value;
  }
  async put(value) { this.putIfUnchanged(value, this.raw(value.key)); return value; }
  rememberCorrupt(key, error, metadata = {}) {
    const record = { key, error: String(error?.message || error), ...metadata };
    this.corruptRecords.set(key, record); return record;
  }
}

const key = 'history-store:history-project:iteration:17';
const snapshot = { id: 'history-project', projectId: 'history-project', publicationRevision: 17,
  sourceCommit: 'source-17', baseCommit: 'base-17', workflow: 'objects-v1' };
const clone = value => structuredClone(value);
const content = record => ({ text: record.text, values: record.values, fields: record.fields,
  feedback: record.feedback, feedbackInputs: record.feedbackInputs, feedbackInputTargetId: record.feedbackInputTargetId,
  legacyUnboundFeedback: record.legacyUnboundFeedback, feedbackMessage: record.feedbackMessage,
  feedbackCategory: record.feedbackCategory, targetNotes: record.targetNotes,
  structuralProposals: record.structuralProposals, proposalInputs: record.proposalInputs });
const makeDraft = (name, { fieldValue = 120, operationId = 'operation-A' } = {}) => ({
  text: `意见 ${name}`,
  selectedObjectId: 'player-1',
  values: { goalCount: 12 },
  fields: { 'player-1.health': fieldValue },
  feedback: [{ feedbackId: `feedback-${name}`, objectId: 'player-1', category: 'note', message: `完整反馈 ${name}` }],
  feedbackInputs: {}, feedbackInputTargetId: null, legacyUnboundFeedback: null,
  feedbackMessage: '', feedbackCategory: 'general',
  targetNotes: { 'player-1': { text: `意见 ${name}`, objectId: 'player-1', feedbackId: `note-${name}` } },
  structuralProposals: [{ operationId, kind: 'move-instance', objectId: 'player-1', requestedPosition: [10, 20] }],
  proposalInputs: { plan: { revision1: { questions: { q1: `回答 ${name}` }, readySupplement: `补充 ${name}` } } },
});

function makeApp({ active = makeDraft('A'), retained = makeDraft('B', { operationId: 'operation-B' }), visible = active } = {}) {
  const drafts = new MemoryDrafts();
  const activeRecord = { ...clone(active), key, projectId: snapshot.projectId,
    publicationRevision: snapshot.publicationRevision, sourceCommit: snapshot.sourceCommit,
    baseCommit: snapshot.baseCommit, draftRevision: 8, updatedAt: '2026-10-17T00:00:00.000Z',
    draftConflictAlternates: [{ label: '完整保留稿 B', capturedAt: '2026-10-16T00:00:00.000Z', draft: clone(retained) }] };
  drafts.externalSet(key, activeRecord);
  const raw = drafts.raw(key);
  const app = Object.create(StudioApp.prototype);
  Object.assign(app, {
    document: dom.window.document, workspace: { storeId: 'history-store' }, projectId: snapshot.projectId,
    snapshot, workflow: 'objects-v1', draftKey: key, draftBaselineKey: key, draftStorageBaseline: raw,
    draftRevision: activeRecord.draftRevision, draftAlternates: clone(activeRecord.draftConflictAlternates),
    pendingDraftConflict: null, persistenceOK: true, drafts, workbenchGeneration: 3, draftOperationSequence: 0,
    draftRestoreContext: null, draftSaveQueuedDuringRestore: false, draftConflictRefresh: null, draftTimer: null,
    destroyed: false, dirtyFields: new Set(), fieldDraftValues: {},
    visibleDraft: { ...clone(visible), draftRevision: activeRecord.draftRevision,
      draftConflictAlternates: clone(activeRecord.draftConflictAlternates) },
    selectedObjectId: 'player-1', targetNotes: clone(visible.targetNotes),
    structuralProposals: clone(visible.structuralProposals), feedback: clone(visible.feedback), feedbackInputs: {},
    feedbackInputTargetId: null, legacyUnboundFeedback: null, proposalInputs: clone(visible.proposalInputs),
    objectItems: () => [{ id: 'player-1', name: 'Player', fields: [{ id: 'health', value: 100 }] }],
    allCapabilities: () => [],
    readVisibleDraft() { return clone(this.visibleDraft); },
    legacyWorkbench: { noteTargetId: (noteKey, note) => Object.hasOwn(note, 'objectId') ? note.objectId : noteKey },
    notify(message) { this.lastNotice = message; },
  });
  const updateDraftBaseline = app.updateDraftBaseline.bind(app);
  app.baselineUpdates = 0;
  app.updateDraftBaseline = (...args) => { app.baselineUpdates++; return updateDraftBaseline(...args); };
  return app;
}

function clickRetainedVersion(app, expected) {
  app.openDraftConflict();
  let dialog = document.querySelector('#draft-conflict-dialog');
  const target = [...dialog.querySelectorAll('.draft-conflict-alternate')]
    .find(button => app.sameDraftContent(button.__draftAlternate, expected));
  assert.ok(target, 'the complete retained version is available in the actual comparison dialog');
  target.click();
  dialog = document.querySelector('#draft-conflict-dialog');
  return dialog;
}

async function main() {
  ({ StudioApp } = await import(pathToFileURL(path.resolve(__dirname, '../studio/studio.js')).href));
  try {
    // Main path: actual recovery browsing and rendered defer handler, then actual saveDraft CAS.
    const activeA = makeDraft('A');
    const retainedB = makeDraft('B', { operationId: 'operation-B' });
    const app = makeApp({ active: activeA, retained: retainedB });
    let resolverCalls = 0;
    app.resolveDraftConflict = () => { resolverCalls++; };
    const baselineRaw = app.draftStorageBaseline;
    const fullA = clone(content(app.drafts.readStored(key, baselineRaw)));
    const fullB = clone(content(retainedB));
    const dialog = clickRetainedVersion(app, retainedB);
    const conflict = app.pendingDraftConflict;
    assert.equal(conflict.recovery, true, 'openDraftConflict creates the historical recovery browsing state');
    assert.equal(dialog.querySelector('[data-draft-conflict-action="keep-local"]').disabled, false);
    assert.equal(dialog.querySelector('[data-draft-conflict-action="use-remote"]').disabled, false);
    assert.match(dialog.textContent, /纯历史浏览/);
    assert.equal(app.drafts.writes, 0, 'opening and selecting retained B performs no storage write');
    dialog.querySelector('[data-draft-conflict-action="defer"]').click();
    assert.equal(app.pendingDraftConflict, null, 'safe explicit defer ends only the historical browsing pending state');
    assert.equal(dialog.open, false, 'safe defer closes the comparison dialog');
    assert.equal(app.drafts.writes, 0, 'defer performs zero business storage writes');
    assert.equal(app.baselineUpdates, 0, 'defer does not advance the exact raw baseline');
    assert.equal(app.draftStorageBaseline, baselineRaw);
    assert.deepEqual(content(app.drafts.readStored(key, app.drafts.raw(key))), fullA, 'active A remains complete after defer');
    assert.deepEqual(content(app.draftAlternates[0].draft), fullB, 'the retained B remains complete after defer');
    assert.deepEqual(content(app.visibleDraft), content(activeA), 'the visible A working draft is not switched');
    assert.equal(resolverCalls, 0, 'defer invokes no explicit recovery resolver');
    assert.doesNotMatch(document.querySelector('#draft-state').textContent, /活动草稿与本页基线不同/);
    assert.match(document.querySelector('#draft-state').textContent, /已结束保留稿比较/);
    assert.equal(app.drafts.raw(`${key}:saved`), null, 'defer creates no saved checkpoint');
    assert.equal(app.drafts.raw(`${key}:saved:backup`), null, 'defer creates no first backup');

    const appended = ' · 后续普通意见';
    app.visibleDraft.text += appended;
    app.visibleDraft.targetNotes['player-1'].text += appended;
    app.visibleDraft.feedback.push({ feedbackId: 'feedback-followup', objectId: 'player-1', category: 'note', message: '后续普通意见' });
    document.querySelector('#edit-text').value = app.visibleDraft.text;
    const saveResult = await app.saveDraft();
    assert.equal(saveResult, true, 'the next ordinary StudioApp.saveDraft uses the original CAS and succeeds');
    assert.equal(app.drafts.writes, 1, 'the ordinary CAS produces exactly one current draft write');
    assert.equal(app.baselineUpdates, 1, 'the original save path advances the baseline after success');
    const saved = app.drafts.readStored(key, app.drafts.raw(key));
    assert.equal(saved.text, activeA.text + appended, 'the appended note is saved after defer');
    assert.deepEqual(saved.fields, activeA.fields, 'the original complete fields remain');
    assert.deepEqual(saved.feedback.slice(0, activeA.feedback.length), activeA.feedback, 'the original feedback identity and body remain');
    assert.equal(saved.feedback.at(-1).feedbackId, 'feedback-followup', 'the new feedback has a stable identity');
    assert.deepEqual(saved.structuralProposals, activeA.structuralProposals, 'the original structure remains');
    assert.deepEqual(content(saved.draftConflictAlternates[0].draft), fullB, 'the entire retained B remains available after ordinary save');

    // No storage event is dispatched for C: the defer guard must detect its exact raw change.
    const changedC = makeDraft('C', { fieldValue: 121, operationId: 'operation-C' });
    const appWithUnannouncedC = makeApp({ active: activeA, retained: retainedB });
    const cDialog = clickRetainedVersion(appWithUnannouncedC, retainedB);
    const cPending = appWithUnannouncedC.pendingDraftConflict;
    const cBaseline = appWithUnannouncedC.draftStorageBaseline;
    const cRecord = { ...clone(changedC), key, projectId: snapshot.projectId,
      publicationRevision: snapshot.publicationRevision, sourceCommit: snapshot.sourceCommit,
      baseCommit: snapshot.baseCommit, draftRevision: 9, updatedAt: '2026-10-17T00:01:00.000Z' };
    const cRaw = JSON.stringify(cRecord);
    appWithUnannouncedC.drafts.externalSet(key, cRecord);
    cDialog.querySelector('[data-draft-conflict-action="defer"]').click();
    assert.equal(appWithUnannouncedC.pendingDraftConflict, cPending, 'an unannounced active C keeps the recovery pending state');
    assert.equal(appWithUnannouncedC.draftStorageBaseline, cBaseline, 'unsafe defer does not advance the baseline');
    assert.equal(appWithUnannouncedC.drafts.writes, 0, 'unsafe defer performs no write');
    assert.equal(appWithUnannouncedC.drafts.raw(key), cRaw, 'unsafe defer leaves active C raw untouched');
    assert.equal(cDialog.open, false, 'unsafe defer closes only the unchanged comparison dialog');
    const refusedSave = await appWithUnannouncedC.saveDraft();
    assert.equal(refusedSave, false, 'the following ordinary save is not reported as a successful current write');
    assert.equal(appWithUnannouncedC.pendingDraftConflict, cPending, 'ordinary save keeps the pending comparison');
    const preservedC = appWithUnannouncedC.drafts.readStored(key, appWithUnannouncedC.drafts.raw(key));
    assert.deepEqual(content(preservedC), content(changedC), 'the actual active C business content is preserved');

    // A real active-draft conflict is created by beginDraftConflict and cannot be cleared by defer.
    const activeConflictPage = makeDraft('LOCAL', { fieldValue: 119, operationId: 'operation-local' });
    const appWithRealConflict = makeApp({ active: activeA, retained: retainedB, visible: activeConflictPage });
    let resolverChoices = [];
    appWithRealConflict.resolveDraftConflict = choice => { resolverChoices.push(choice); };
    const activeRaw = appWithRealConflict.drafts.raw(key);
    assert.equal(await appWithRealConflict.beginDraftConflict(
      appWithRealConflict.currentDraftRecord(), appWithRealConflict.drafts.readStored(key, activeRaw), activeRaw), true);
    const realConflict = appWithRealConflict.pendingDraftConflict;
    assert.equal(realConflict.recovery, false, 'beginDraftConflict creates the real active difference form');
    const conflictBaseline = appWithRealConflict.draftStorageBaseline;
    const conflictRaw = appWithRealConflict.drafts.raw(key);
    appWithRealConflict.openDraftConflict();
    const conflictDialog = document.querySelector('#draft-conflict-dialog');
    assert.ok(conflictDialog.querySelector('[data-draft-conflict-action="keep-local"]'));
    assert.ok(conflictDialog.querySelector('[data-draft-conflict-action="use-remote"]'));
    conflictDialog.querySelector('[data-draft-conflict-action="keep-local"]').click();
    conflictDialog.querySelector('[data-draft-conflict-action="use-remote"]').click();
    assert.deepEqual(resolverChoices, ['local', 'remote'], 'the existing explicit choice buttons still call the resolver');
    conflictDialog.querySelector('[data-draft-conflict-action="defer"]').click();
    assert.equal(appWithRealConflict.pendingDraftConflict, realConflict, 'defer never clears a recovery:false active conflict');
    assert.equal(appWithRealConflict.draftStorageBaseline, conflictBaseline, 'active-conflict defer leaves its baseline unchanged');
    assert.equal(appWithRealConflict.drafts.raw(key), conflictRaw, 'active-conflict defer performs no additional write');
    assert.match(document.querySelector('#draft-state').textContent, /存储中的活动草稿与本页基线不同/);

    console.log('PASS studio history defer CAS QA: safe history exit, next original CAS save, unannounced C guard, and recovery:false conflict retention');
  } finally {
    dom.window.close();
  }
}

main().catch(error => {
  dom.window.close();
  console.error(error.stack || error);
  process.exitCode = 1;
});
