#!/usr/bin/env node
/* Corrupt local drafts/checkpoints remain exportable as raw, scoped recovery data. */
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const { pathToFileURL } = require('node:url');
let JSDOM;
try { ({ JSDOM } = require('jsdom')); }
catch { console.log('SKIP Studio corrupt draft raw recovery QA: jsdom is unavailable.'); process.exit(0); }

const root = path.resolve(__dirname, '..');
const prefix = 'ptah-studio-draft-v2:';
const projectId = 'raw-recovery-project';
const storeId = 'raw-recovery-store';
const pageText = '仍在页面中的新输入：玩家移动应更平滑。';
const tick = () => new Promise(resolve => setTimeout(resolve, 0));
let StudioApp, DraftStore;

async function makeApp({ revision = 3, currentRaw, savedRaw, backupRaw, olderRaw } = {}) {
  const dom = new JSDOM(fs.readFileSync(path.join(root, 'studio/index.html'), 'utf8'), {
    url: `http://127.0.0.1:8123/studio/?project=${projectId}&stage=iteration&target=player`, pretendToBeVisual: true,
  });
  global.document = dom.window.document; global.FormData = dom.window.FormData; global.Option = dom.window.Option;
  global.localStorage = dom.window.localStorage; global.location = dom.window.location; global.history = dom.window.history;
  const project = { id: projectId, title: '损坏存档恢复', workflow: 'objects-v1', publicationRevision: revision };
  const object = { id: 'player', kind: 'entity', name: '玩家', fields: [{ id: 'speed', label: '速度', type: 'scalar', value: 220 }], workbench: { role: 'entity', lock: 'free' } };
  const app = new StudioApp({ fetchImpl: async () => { throw new Error('unexpected backend request'); }, documentImpl: dom.window.document, timers: globalThis });
  app.manager = { storeId, projects: [project] }; app.workspace = { storeId, projects: [project], iterationReady: true };
  app.projectId = projectId; app.stage = 'iteration'; app.workflow = 'objects-v1'; app.snapshot = {
    id: projectId, projectId, publicationRevision: revision, sourceCommit: `git-raw-${revision}`, baseCommit: `git-raw-${revision}`,
    kind: 'MVP', playable: true, workflow: 'objects-v1', catalog: { objects: [object] }, document: { objects: [object] },
  };
  app.capabilities = { fields: [{ id: 'player.speed', objectId: 'player', fieldId: 'speed', label: '速度', type: 'scalar', value: 220, editable: true, min: 0, max: 500 }] };
  app.selectedObjectId = 'player'; app.drafts = new DraftStore(null, dom.window.localStorage); app.persistenceOK = true;
  app.bind(); app.renderWorkbench(); app.targetNotes = { player: { objectId: 'player', text: pageText, feedbackId: 'raw-page-note' } };
  document.querySelector('#edit-text').value = pageText;
  const key = app.makeDraftKey(app.snapshot);
  if (currentRaw !== undefined) dom.window.localStorage.setItem(prefix + key, currentRaw);
  if (savedRaw !== undefined) dom.window.localStorage.setItem(prefix + `${key}:saved`, savedRaw);
  if (backupRaw !== undefined) dom.window.localStorage.setItem(prefix + `${key}:saved:backup`, backupRaw);
  if (olderRaw !== undefined) dom.window.localStorage.setItem(prefix + `${storeId}:${projectId}:iteration:${revision - 1}`, olderRaw);
  return { app, dom, key, project };
}

async function captureDownload(dom, action) {
  let blob = null;
  const originalCreate = URL.createObjectURL, originalRevoke = URL.revokeObjectURL;
  const originalClick = dom.window.HTMLAnchorElement.prototype.click;
  URL.createObjectURL = value => { blob = value; return 'blob:raw-recovery-test'; };
  URL.revokeObjectURL = () => {};
  dom.window.HTMLAnchorElement.prototype.click = () => {};
  try {
    await action();
    assert.ok(blob, 'the recovery action creates a downloadable UTF-8 file');
    return JSON.parse(await blob.text());
  } finally {
    URL.createObjectURL = originalCreate; URL.revokeObjectURL = originalRevoke;
    dom.window.HTMLAnchorElement.prototype.click = originalClick;
  }
}

(async () => {
  ({ StudioApp, DraftStore } = await import(pathToFileURL(path.join(root, 'studio/studio.js')).href));
  const invalidRawCases = [
    ['malformed JSON', '{"fields":\n  {broken, "原文保持": "exact"}'],
    ['wrong key identity', JSON.stringify({ key: 'another-project:key', projectId, fields: {}, targetNotes: {} })],
    ['future schema', JSON.stringify({ key: `${storeId}:${projectId}:iteration:3`, schemaVersion: 'ptah.workbench-draft.v99', fields: {}, targetNotes: {} })],
    ['invalid fields shape', JSON.stringify({ key: `${storeId}:${projectId}:iteration:3`, fields: [], targetNotes: {} })],
    ['invalid notes shape', JSON.stringify({ key: `${storeId}:${projectId}:iteration:3`, fields: {}, targetNotes: [] })],
  ];
  for (const [label, raw] of invalidRawCases) {
    const { app, dom, key } = await makeApp({ currentRaw: raw });
    await app.restoreDraft();
    assert.equal(app.persistenceOK, false, `${label} pauses writes for the current draft`);
    assert.equal(document.querySelector('#edit-text').value, pageText, `${label} leaves current page input untouched`);
    assert.equal(dom.window.localStorage.getItem(prefix + key), raw, `${label} does not rewrite the original storage string`);
    assert.equal(app.drafts.corruptRecords.get(key)?.raw, raw, `${label} retains exact raw text from DraftStore.raw`);
    assert(document.querySelector('[data-action="download-corrupt-drafts"]'), `${label} exposes the raw archive action in draft state`);
    const archive = await captureDownload(dom, () => document.querySelector('[data-action="download-corrupt-drafts"]').click());
    assert.equal(archive.projectId, projectId); assert.equal(archive.publicationRevision, 3);
    assert.equal(archive.corruptRawRecords[0].key, key); assert.equal(archive.corruptRawRecords[0].raw, raw);
    assert.equal(archive.currentPageDraft.text, pageText, `${label} recovery file also preserves current page input`);
    const downloadNotice = document.querySelector('#notice').textContent;
    assert(downloadNotice.includes('已准备') && downloadNotice.includes('查看/复制原始存档'), 'download notice reports a prepared download and points to the text fallback');
    assert(!downloadNotice.includes('已下载') && !downloadNotice.includes('已保存'), 'download notice does not claim the file was saved');
    const viewButton = document.querySelector('[data-action="view-corrupt-drafts"]');
    assert(viewButton, `${label} exposes the read-only text fallback`);
    const recoveryDialog = document.querySelector('#raw-draft-recovery-dialog');
    recoveryDialog.showModal = function () { this.open = true; };
    recoveryDialog.close = function () { this.open = false; this.dispatchEvent(new dom.window.Event('close')); };
    viewButton.focus(); viewButton.click();
    assert(recoveryDialog.open, 'the raw archive fallback opens in a dialog');
    assert.equal(document.querySelector('#raw-draft-recovery-title').textContent, '查看/复制原始存档');
    const recoveryText = document.querySelector('#raw-draft-recovery-content');
    const dialogArchive = JSON.parse(recoveryText.value);
    assert.deepEqual({ ...dialogArchive, exportedAt: null }, { ...archive, exportedAt: null }, 'the dialog exposes the complete recovery JSON');
    assert.equal(recoveryText.readOnly, true, 'the recovery JSON is selectable and read-only');
    let clipboardWriteCalled = false;
    Object.defineProperty(dom.window.navigator, 'clipboard', { configurable: true, value: { writeText: () => { clipboardWriteCalled = true; return new Promise(() => {}); } } });
    const originalTimers = app.timers;
    app.timers = { ...originalTimers, setTimeout: (callback, delay) => { assert.equal(delay, 1500); queueMicrotask(callback); return 1; }, clearTimeout: () => {} };
    try {
      document.querySelector('[data-action="copy-raw-draft-recovery"]').click();
      const copyStatus = document.querySelector('#raw-draft-recovery-status').textContent;
      assert(clipboardWriteCalled, 'copy starts the browser clipboard request');
      assert(copyStatus.includes('可按 Ctrl+C 或 ⌘C 复制'), 'manual-copy guidance appears immediately while clipboard writing is pending');
      assert.equal(recoveryText.selectionStart, 0); assert.equal(recoveryText.selectionEnd, recoveryText.value.length, 'copy immediately selects all JSON text');
      await tick();
      assert.equal(document.querySelector('#raw-draft-recovery-status').textContent, copyStatus, 'a clipboard promise that remains pending times out without replacing the manual-copy guidance');
      assert.equal(recoveryText.selectionStart, 0); assert.equal(recoveryText.selectionEnd, recoveryText.value.length, 'timeout keeps the JSON selected for manual copying');
    } finally { app.timers = originalTimers; }
    assert.equal(dom.window.localStorage.getItem(prefix + key), raw, 'viewing and copying leave the corrupt storage string unchanged');
    document.querySelector('[data-action="close-raw-draft-recovery"]').click();
    assert(!recoveryDialog.open, 'the raw archive dialog closes');
    assert.equal(document.activeElement, viewButton, 'closing the raw archive restores focus to its opener');
    app.destroy(); dom.window.close();
  }

  const checkpointRaw = JSON.stringify({ key: 'wrong-saved-key', baseDraftKey: `${storeId}:${projectId}:iteration:3`, projectId, publicationRevision: 3, checkpoint: true, fields: {}, targetNotes: {} });
  const saved = await makeApp({ savedRaw: checkpointRaw });
  await saved.app.restoreDraft();
  assert.equal(saved.app.persistenceOK, true, 'a bad separate checkpoint does not disable the current draft store');
  assert.equal(saved.app.drafts.corruptRecords.get(`${saved.key}:saved`)?.raw, checkpointRaw, 'bad checkpoint identity retains its exact stored string');
  assert(document.querySelector('[data-action="download-corrupt-drafts"]'), 'bad checkpoint exposes the archive action');
  const savedExport = await captureDownload(saved.dom, () => saved.app.legacyWorkbench.exportDraft());
  assert.equal(savedExport.savedCheckpointRaw.key, `${saved.key}:saved`);
  assert.equal(savedExport.savedCheckpointRaw.raw, checkpointRaw, 'ordinary draft export includes the checkpoint raw string and error');
  assert.equal(savedExport.savedCheckpointBackupRaw, null);
  assert(savedExport.corruptRawRecords.some(record => record.key === `${saved.key}:saved`));
  assert.equal(saved.dom.window.localStorage.getItem(prefix + `${saved.key}:saved`), checkpointRaw, 'export does not overwrite the bad checkpoint');
  saved.app.destroy(); saved.dom.window.close();

  const backupRaw = JSON.stringify({ key: `${storeId}:${projectId}:iteration:3:saved:backup`, baseDraftKey: `${storeId}:${projectId}:iteration:3`, projectId, publicationRevision: 3, checkpointBackup: true, fields: [], targetNotes: {} });
  const backup = await makeApp({ backupRaw });
  await backup.app.restoreDraft();
  assert.equal(backup.app.drafts.corruptRecords.get(`${backup.key}:saved:backup`)?.raw, backupRaw, 'bad immutable checkpoint backup retains exact raw text');
  const backupExport = await captureDownload(backup.dom, () => backup.app.legacyWorkbench.exportDraft());
  assert.equal(backupExport.savedCheckpointBackupRaw.key, `${backup.key}:saved:backup`);
  assert.equal(backupExport.savedCheckpointBackupRaw.raw, backupRaw, 'ordinary export includes the checkpoint backup raw string');
  backup.app.destroy(); backup.dom.window.close();

  const oldRaw = '{historical draft is still here\n\t原字节保留';
  const older = await makeApp({ olderRaw: oldRaw });
  await older.app.restoreDraft();
  const oldKey = `${storeId}:${projectId}:iteration:2`;
  assert.equal(older.app.persistenceOK, true, 'a malformed older key does not replace the current draft or stop current-version editing');
  assert.equal(older.app.drafts.corruptRecords.get(oldKey)?.raw, oldRaw, 'historical malformed draft remains retained under its original key');
  assert.equal(older.app.drafts.corruptRecords.get(oldKey)?.kind, 'older');
  assert(document.querySelector('[data-action="download-corrupt-drafts"]'), 'historical malformed key is surfaced for download');
  const olderArchive = await captureDownload(older.dom, () => document.querySelector('[data-action="download-corrupt-drafts"]').click());
  assert(olderArchive.corruptRawRecords.some(record => record.key === oldKey && record.raw === oldRaw), 'historical archive identifies the exact old storage key and value');
  assert.equal(older.app.drafts.raw(oldKey), oldRaw, 'historical raw record remains unchanged');
  older.app.destroy(); older.dom.window.close();

  const event = await makeApp();
  const baseline = { key: event.key, projectId, publicationRevision: 3, fields: {}, targetNotes: {} };
  const baselineRaw = JSON.stringify(baseline); event.app.drafts.putIfUnchanged(baseline, null);
  event.app.draftBaselineKey = event.key; event.app.draftStorageBaseline = baselineRaw;
  const remoteRaw = '{remote tab wrote malformed JSON';
  event.dom.window.localStorage.setItem(prefix + event.key, remoteRaw);
  event.dom.window.dispatchEvent(new event.dom.window.StorageEvent('storage', { key: prefix + event.key, oldValue: baselineRaw, newValue: remoteRaw }));
  await tick();
  assert.equal(event.app.persistenceOK, false, 'malformed cross-tab storage pauses automatic writes');
  assert.equal(document.querySelector('#edit-text').value, pageText, 'malformed cross-tab storage keeps current page input');
  assert.equal(event.app.drafts.corruptRecords.get(event.key)?.raw, remoteRaw, 'malformed cross-tab storage is retained verbatim');
  assert(document.querySelector('#draft-state').textContent.includes('草稿活动版本或基线无法读取'));
  assert(document.querySelector('[data-action="download-corrupt-drafts"]'), 'cross-tab corruption exposes raw archive recovery');
  event.app.destroy(); event.dom.window.close();

  console.log('PASS Studio corrupt draft raw recovery QA: malformed, incompatible and historical raw records stay scoped and exportable without overwrites');
})().catch(error => { console.error(error.stack || error); process.exitCode = 1; });
