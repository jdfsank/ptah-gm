#!/usr/bin/env node
/* Focused QA for explicit saved-checkpoint replacement and its one-version backup. */
const assert = require('node:assert/strict');
const { pathToFileURL } = require('node:url');
let JSDOM;
try { ({ JSDOM } = require('jsdom')); }
catch { console.log('SKIP saved-checkpoint overwrite QA: jsdom is unavailable.'); process.exit(0); }

const dom = new JSDOM('<!doctype html><div id="notice" class="hidden"></div><textarea id="edit-text"></textarea><div id="draft-state"></div><p id="workbench-checkpoint-status"></p>', {
  url: 'http://127.0.0.1:8123/studio/?project=checkpoint-test', pretendToBeVisual: true,
});
global.document = dom.window.document;
global.localStorage = dom.window.localStorage;

class MemoryDrafts {
  constructor() { this.records = new Map(); }
  raw(key) { return this.records.get(key) ?? null; }
  async get(key) {
    const raw = this.raw(key);
    if (raw === null) return null;
    const record = JSON.parse(raw);
    if (!record || typeof record !== 'object' || Array.isArray(record) || record.key !== key) throw new Error('Malformed checkpoint');
    return record;
  }
  async put(value) { this.records.set(value.key, JSON.stringify(value)); return value; }
  putIfUnchanged(value, expectedRaw) {
    if (this.raw(value.key) !== expectedRaw) throw new Error('Checkpoint changed during save');
    this.records.set(value.key, JSON.stringify(value));
    return value;
  }
}

(async () => {
  const { LegacyWorkbench } = await import(pathToFileURL(require('node:path').resolve(__dirname, '../studio/workbench.js')).href);
  const { StudioApp } = await import(pathToFileURL(require('node:path').resolve(__dirname, '../studio/studio.js')).href);
  const drafts = new MemoryDrafts();
  const snapshot = { projectId: 'checkpoint-project', publicationRevision: 7 };
  const notices = [];
  let currentDraftSaveResult = true;
  const app = {
    projectId: snapshot.projectId, snapshot, draftKey: 'checkpoint-store:checkpoint-project:iteration:7',
    draftRevision: 4, persistenceOK: true, targetNotes: {}, structuralProposals: [], fieldDraftValues: {},
    drafts, objectItems: () => [], saveDraft: async () => currentDraftSaveResult,
    readVisibleDraft: () => ({ text: '', ...structuredClone(app.visiblePayload), targetNotes: structuredClone(app.targetNotes) }),
    newFeedbackId: () => 'checkpoint-note', showDraftState: message => { app.lastDraftState = message; document.querySelector('#draft-state').textContent = message; },
    notify: message => { app.lastNotice = message; notices.push(message); const node = document.querySelector('#notice'); node.textContent = message; node.classList.remove('hidden'); },
    pendingDraftConflict: null, workbenchGeneration: 1, openConflictCount: 0,
    openDraftConflict: () => { app.openConflictCount++; },
    visiblePayload: { values: {}, fields: {}, feedback: [], structuralProposals: [] },
  };
  app.draftConflictScopeIsCurrent = () => {
    const scopeGuard = Object.create(StudioApp.prototype);
    Object.assign(scopeGuard, {
      pendingDraftConflict: app.pendingDraftConflict, snapshot: app.snapshot, draftKey: app.draftKey,
      projectId: app.projectId, workbenchGeneration: app.workbenchGeneration,
      storageId: () => 'checkpoint-test-storage', makeDraftKey: () => app.draftKey,
    });
    return scopeGuard.draftConflictScopeIsCurrent();
  };
  const wb = new LegacyWorkbench(app);
  const input = document.querySelector('#edit-text');
  const originalConfirm = global.confirm;
  let confirmResult = true, confirmations = [];
  global.confirm = message => { confirmations.push(message); return confirmResult; };
  const payload = marker => ({ values: { playerSpeed: 300 + marker }, fields: { 'player.health': 120 + marker },
    feedback: [{ objectId: 'player-1', category: 'note', message: `意见 ${marker}` }],
    structuralProposals: [{ operationId: `proposal-${marker}`, kind: 'move', objectId: 'player-1' }] });
  const businessContent = record => ({ text: record.text, values: record.values, fields: record.fields,
    feedback: record.feedback, targetNotes: record.targetNotes, structuralProposals: record.structuralProposals });
  try {
    app.visiblePayload = payload(0);
    input.value = '版本 A'; await wb.saveDraft();
    const savedKey = wb.savedCheckpointKey(app.draftKey), backupKey = wb.savedCheckpointBackupKey(app.draftKey);
    const first = await drafts.get(savedKey);
    assert.equal(first.targetNotes.__project__.text, '版本 A', 'the first explicit save creates the project/version checkpoint');
    assert.equal(await drafts.get(backupKey), null, 'the first explicit save does not create an empty backup');
    assert.deepEqual(first.values, payload(0).values, 'the first checkpoint retains supported values');
    assert.deepEqual(first.fields, payload(0).fields, 'the first checkpoint retains scoped fields');
    assert.deepEqual(first.feedback, payload(0).feedback, 'the first checkpoint retains complete feedback');
    assert.deepEqual(first.structuralProposals, payload(0).structuralProposals, 'the first checkpoint retains structural proposals');
    assert.equal(document.querySelector('#notice').textContent, app.lastDraftState, 'successful creation replaces the notice with the same success shown in draft state');

    const savedRawBeforeReject = drafts.raw(savedKey), backupRawBeforeReject = drafts.raw(backupKey);
    const confirmsBeforeReject = confirmations.length;
    const currentConflictScope = { storeId: 'checkpoint-test-storage', key: app.draftKey, projectId: app.projectId,
      publicationRevision: snapshot.publicationRevision, kind: null, sourceCommit: null, baseCommit: null,
      candidateId: null, snapshotId: null };
    app.pendingDraftConflict = { key: app.draftKey, snapshot: app.snapshot, generation: app.workbenchGeneration,
      scope: currentConflictScope, scopeChanged: false };
    currentDraftSaveResult = false;
    app.visiblePayload = payload(1);
    input.value = '拒绝后仍在本页'; await wb.saveDraft();
    assert.equal(drafts.raw(savedKey), savedRawBeforeReject, 'a same-scope save refusal leaves the complete checkpoint untouched');
    assert.equal(drafts.raw(backupKey), backupRawBeforeReject, 'a same-scope save refusal leaves the first backup untouched');
    assert.equal(confirmations.length, confirmsBeforeReject, 'a save refusal does not ask to replace the checkpoint');
    assert.equal(app.openConflictCount, 1, 'a current conflict opens the existing comparison');
    assert.match(app.lastNotice, /恢复点未更新/);
    assert.match(app.lastNotice, /比较并明确选择/);
    assert.match(app.lastNotice, /再次点击“创建 \/ 更新恢复点”/);

    app.pendingDraftConflict = null;
    await wb.saveDraft();
    assert.equal(app.openConflictCount, 1, 'a refusal without a current conflict does not open unrelated comparison history');
    assert.match(app.lastNotice, /当前工作草稿没有完成持久保存/);
    app.pendingDraftConflict = { key: 'stale-scope', snapshot: { ...snapshot, publicationRevision: 6 },
      generation: app.workbenchGeneration, scope: { ...currentConflictScope, key: 'stale-scope', publicationRevision: 6 }, scopeChanged: false };
    await wb.saveDraft();
    assert.equal(app.openConflictCount, 1, 'a stale conflict scope does not open comparison in the current scope');
    assert.equal(drafts.raw(savedKey), savedRawBeforeReject, 'refusals outside the current conflict scope do not write the checkpoint');
    assert.equal(drafts.raw(backupKey), backupRawBeforeReject, 'refusals outside the current conflict scope do not write the backup');

    currentDraftSaveResult = true;
    app.pendingDraftConflict = null;
    app.visiblePayload = payload(2);
    input.value = '版本 B'; confirmResult = false;
    const noticeBeforeCancel = document.querySelector('#notice').textContent, noticesBeforeCancel = notices.length;
    await wb.saveDraft();
    assert.equal((await drafts.get(savedKey)).targetNotes.__project__.text, '版本 A', 'declining replacement leaves the existing checkpoint intact');
    assert.equal(await drafts.get(backupKey), null, 'declining replacement does not write a backup');
    assert.equal(confirmations.length, 1, 'replacing a checkpoint requires explicit confirmation');
    assert.equal(notices.length, noticesBeforeCancel, 'cancelling replacement does not report checkpoint success');
    assert.equal(document.querySelector('#notice').textContent, noticeBeforeCancel, 'cancelling replacement does not replace the prior notice with success');

    confirmResult = true; await wb.saveDraft();
    const replaced = await drafts.get(savedKey), backup = await drafts.get(backupKey);
    assert.equal(replaced.targetNotes.__project__.text, '版本 B', 'confirmed replacement stores the new checkpoint');
    assert.deepEqual(businessContent(backup), businessContent(first), 'the first backup preserves the complete original working draft');
    assert.deepEqual(replaced.values, payload(2).values, 'replacement stores the current supported values');
    assert.deepEqual(replaced.fields, payload(2).fields, 'replacement stores the current scoped fields');
    assert.deepEqual(replaced.feedback, payload(2).feedback, 'replacement stores the current complete feedback');
    assert.deepEqual(replaced.structuralProposals, payload(2).structuralProposals, 'replacement stores the current structural proposals');
    assert.equal(document.querySelector('#notice').textContent, app.lastDraftState, 'successful replacement replaces the old failure notice with its success state');
    assert.equal(backup.projectId, snapshot.projectId, 'the backup retains the same project identity');
    assert.equal(backup.publicationRevision, snapshot.publicationRevision, 'the backup retains the same publication version');
    assert.equal(backup.baseDraftKey, app.draftKey, 'the backup remains scoped to the active draft key');
    assert.equal(backup.checkpointBackup, true, 'the previous checkpoint is explicitly marked as a backup');
    assert.equal(wb.savedCheckpointBackupKey(`${app.draftKey}:other`), `${app.draftKey}:other:saved:backup`, 'backup keys derive from the exact project/version draft key');

    app.visiblePayload = payload(3);
    input.value = '版本 C'; await wb.saveDraft();
    const current = await drafts.get(savedKey), firstBackup = await drafts.get(backupKey);
    assert.equal(current.targetNotes.__project__.text, '版本 C', 'a later confirmed replacement updates the current checkpoint');
    assert.deepEqual(businessContent(firstBackup), businessContent(first), 'later replacements preserve the complete first overwritten checkpoint');
    assert.deepEqual(current.values, payload(3).values, 'the latest checkpoint stores the current supported values');
    assert.deepEqual(current.fields, payload(3).fields, 'the latest checkpoint stores the current scoped fields');
    assert.deepEqual(current.feedback, payload(3).feedback, 'the latest checkpoint stores the current complete feedback');
    assert.deepEqual(current.structuralProposals, payload(3).structuralProposals, 'the latest checkpoint stores the current structural proposals');
    assert.equal(document.querySelector('#notice').textContent, app.lastDraftState, 'successful later replacement keeps top notice and draft status consistent');
    assert.match(app.lastDraftState, /首次备份仍保留/, 'successful replacement explicitly says the first backup remains');
    assert.doesNotMatch(app.lastDraftState, /时间未知/, 'successful replacement displays a usable checkpoint time');
    await new Promise(resolve => setTimeout(resolve, 0));
    const checkpointStatus = document.querySelector('#workbench-checkpoint-status').textContent;
    assert.match(checkpointStatus, /当前恢复点：/);
    assert.match(checkpointStatus, /作用范围：当前项目与发布版本 7/);
    assert.match(checkpointStatus, /首次备份仍保留/);
    assert.doesNotMatch(checkpointStatus, /时间未知/);

    const comparisonChoices = [];
    const comparison = Object.create(StudioApp.prototype);
    comparison.document = document;
    comparison.pendingDraftConflict = { recovery: false, refreshing: false, scopeChanged: false,
      local: { text: '本页稿' }, remote: { text: '存储稿' } };
    comparison.draftAlternates = [];
    comparison.renderDraftSemanticComparison = () => document.createElement('div');
    comparison.resolveDraftConflict = choice => comparisonChoices.push(choice);
    comparison.renderDraftConflictDialog();
    const dialog = document.querySelector('#draft-conflict-dialog');
    assert.match(dialog.textContent, /本页工作稿与存储活动稿或保留稿/);
    assert.match(dialog.textContent, /独立恢复点不会更新/);
    assert.match(dialog.textContent, /再次点击“创建 \/ 更新恢复点”/);
    dialog.querySelector('[data-draft-conflict-action="keep-local"]').click();
    dialog.querySelector('[data-draft-conflict-action="use-remote"]').click();
    assert.deepEqual(comparisonChoices, ['local', 'remote'], 'the existing explicit local and remote choices remain available');
    assert.ok(dialog.querySelector('[data-draft-conflict-action="defer"]'), 'the existing defer action remains available');

    const selectedKey = 'checkpoint-store:checkpoint-project:iteration:7';
    const selectedSnapshot = { projectId: 'checkpoint-project', publicationRevision: 7 };
    const localDraft = { key: selectedKey, projectId: 'checkpoint-project', publicationRevision: 7, text: '明确保留的本页稿', draftRevision: 4 };
    const storedDraft = { ...localDraft, text: '先前存储的工作稿', draftRevision: 3 };
    const selectionDrafts = new MemoryDrafts();
    await selectionDrafts.put(storedDraft);
    const selectionConflict = { key: selectedKey, local: localDraft, remote: storedDraft, activeRaw: selectionDrafts.raw(selectedKey),
      comparisonActive: storedDraft, refreshing: false, scopeChanged: false, generation: 5, snapshot: selectedSnapshot };
    const selection = Object.create(StudioApp.prototype);
    Object.assign(selection, {
      pendingDraftConflict: selectionConflict, draftKey: selectedKey, snapshot: selectedSnapshot,
      projectId: 'checkpoint-project', workbenchGeneration: 5, draftRevision: 4, drafts: selectionDrafts,
      makeDraftKey: () => selectedKey, sameDraftConflictTarget: () => true,
      beginDraftOperation: () => 1, draftOperationMatches: () => true,
      currentDraftRecord: () => localDraft, readDraftRawRecord: (key, raw) => JSON.parse(raw),
      draftCopy: value => structuredClone(value), sameDraftContent: (left, right) => JSON.stringify(left) === JSON.stringify(right),
      mergeDraftAlternates: () => [], updateDraftBaseline: () => {}, showDraftState: message => { selection.lastDraftState = message; },
    });
    assert.equal(await selection.resolveDraftConflict('local'), true, 'an explicit local choice saves the selected working draft');
    assert.match(selection.lastDraftState, /已保留本页当前稿为当前工作稿并已保存/);
    assert.match(selection.lastDraftState, /独立恢复点未更新/);
    assert.match(selection.lastDraftState, /再次点击“创建 \/ 更新恢复点”/);

    let exportedBlob = null;
    const originalCreateObjectURL = URL.createObjectURL, originalRevokeObjectURL = URL.revokeObjectURL;
    const originalClick = dom.window.HTMLAnchorElement.prototype.click;
    URL.createObjectURL = blob => { exportedBlob = blob; return 'blob:checkpoint-test'; };
    URL.revokeObjectURL = () => {};
    dom.window.HTMLAnchorElement.prototype.click = () => {};
    await wb.exportDraft();
    const exported = JSON.parse(await exportedBlob.text());
    assert.equal(exported.savedCheckpoint.draft.targetNotes.__project__.text, '版本 C', 'export describes the current checkpoint C');
    assert.equal(exported.savedCheckpointBackup.draft.targetNotes.__project__.text, '版本 A', 'export describes the original first backup A');
    URL.createObjectURL = originalCreateObjectURL; URL.revokeObjectURL = originalRevokeObjectURL;
    dom.window.HTMLAnchorElement.prototype.click = originalClick;

    console.log('PASS saved-checkpoint overwrite QA: refusal routing, notice replacement, explicit comparison choices, cancellation, full first-backup preservation, and project/version key scope');
  } finally {
    global.confirm = originalConfirm;
    dom.window.close();
  }
})().catch(error => {
  dom.window.close();
  console.error(error.stack || error);
  process.exitCode = 1;
});
