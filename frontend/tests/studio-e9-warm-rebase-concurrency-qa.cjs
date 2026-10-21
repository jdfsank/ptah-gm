#!/usr/bin/env node
/* A repeated publication read must keep the warm draft's reviewed rebase alive. */
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const { pathToFileURL } = require('node:url');
let JSDOM;
try { ({ JSDOM } = require('jsdom')); }
catch { console.log('SKIP Studio E9 warm rebase QA: jsdom is unavailable.'); process.exit(0); }

const root = path.resolve(__dirname, '..');
const projectId = 'e9-warm-project';
const storeId = 'e9-warm-store';
const noteId = 'aceb0a1f-35f6-43a2-aede-84f7aee86378';
const dom = new JSDOM(fs.readFileSync(path.join(root, 'studio/index.html'), 'utf8'), {
  url: `http://127.0.0.1:8123/studio/?project=${projectId}&stage=iteration&target=player`,
  pretendToBeVisual: true,
});
global.document = dom.window.document;
global.Option = dom.window.Option;
global.localStorage = dom.window.localStorage;
global.location = dom.window.location;
global.history = dom.window.history;

const response = data => ({ ok: true, status: 200, text: async () => JSON.stringify(data) });
const project = { id: projectId, title: '温态发布重关联', workflow: 'objects-v1', publicationRevision: 2 };
const player = { id: 'player', kind: 'entity', name: '玩家', fields: [{ id: 'speed', value: 220 }] };
const oldSnapshot = { id: 'snapshot-e9-rev2', projectId, publicationRevision: 2, sourceCommit: 'git-e9-rev2', baseCommit: 'git-e9-rev2', kind: 'MVP', playable: true, workflow: 'objects-v1', catalog: { objects: [player] }, document: { objects: [player] } };
const publishedSnapshot = { id: 'snapshot-e9-rev3', projectId, publicationRevision: 3, sourceCommit: 'git-e9-rev3', baseCommit: 'git-e9-rev3', kind: 'MVP', playable: true, workflow: 'objects-v1', catalog: { objects: [player] }, document: { objects: [player] } };
const capability = { id: 'player.speed', objectId: 'player', fieldId: 'speed', value: 220, type: 'number', editable: true, min: 0, max: 500 };
let workbenchRead = 0;
const fetchImpl = async url => {
  const pathname = new URL(url, 'http://127.0.0.1:8123').pathname;
  if (pathname === `/api/projects/${projectId}/workbench`) {
    workbenchRead += 1;
    const summary = { ...project, publicationRevision: 3 };
    // Exercise both accepted legacy response forms while returning fresh object
    // identities for the same immutable publication.
    return response(workbenchRead === 1
      ? { project: summary, snapshot: structuredClone(publishedSnapshot), capabilities: { fields: [capability] }, candidates: [], iterationReady: true }
      : { project: summary, repairContext: null, snapshot: structuredClone(publishedSnapshot), capabilities: { fields: [capability] }, candidates: [], iterationReady: true });
  }
  return { ok: false, status: 404, text: async () => JSON.stringify({ error: `unexpected ${pathname}` }) };
};

(async () => {
  const { StudioApp, DraftStore } = await import(pathToFileURL(path.join(root, 'studio/studio.js')).href);
  const app = new StudioApp({ fetchImpl, documentImpl: dom.window.document, timers: globalThis });
  app.manager = { storeId, projects: [project] };
  app.workspace = { storeId, projects: [project], iterationReady: true };
  app.projectId = projectId; app.stage = 'iteration'; app.workflow = 'objects-v1';
  app.snapshot = oldSnapshot; app.capabilities = { fields: [capability] }; app.selectedObjectId = 'player';
  app.persistenceOK = true; app.drafts = new DraftStore(null, dom.window.localStorage);
  app.draftKey = app.makeDraftKey(oldSnapshot); app.draftRevision = 8;
  app.fieldDraftValues = { 'player.speed': 270 };
  app.targetNotes = { player: { objectId: 'player', text: '发布后仍需保留的玩家意见。', feedbackId: noteId } };
  app.bind(); app.renderWorkbench(); app.legacyWorkbench.loadCurrentNote();
  const oldDraft = {
    ...app.readVisibleDraft(), key: app.draftKey, projectId, publicationRevision: 2,
    sourceCommit: oldSnapshot.sourceCommit, baseCommit: oldSnapshot.baseCommit,
    draftRevision: 8, updatedAt: '2026-10-14T00:00:00.000Z',
  };
  await app.drafts.put(oldDraft);

  await app.loadWorkbench(projectId);
  assert.equal(app.snapshot.publicationRevision, 3, 'the first response installs the accepted publication');
  assert.ok(app.pendingRebase, 'the first response opens a reviewed rebase for the old-version draft');
  assert.equal(app.pendingRebase.draft.fields['player.speed'], 270, 'the rebase captures the warm field edit');
  assert.equal(app.pendingRebase.draft.targetNotes.player.feedbackId, noteId, 'the rebase captures the stable feedback identity');

  await app.loadWorkbench(projectId, { force: true });
  assert.equal(workbenchRead, 2, 'the focused fixture returned two consecutive workbench reads');
  assert.equal(app.snapshot.publicationRevision, 3, 'the second response confirms the same publication revision');
  assert.ok(app.pendingRebase, 'a fresh response object for the same revision keeps the reviewed rebase open');
  assert.equal(app.pendingRebase.draft.fields['player.speed'], 270, 'the duplicate read does not clear the carried field value');
  assert.equal(app.pendingRebase.draft.targetNotes.player.feedbackId, noteId, 'the duplicate read does not detach the feedback identity');

  const nextKey = app.makeDraftKey(publishedSnapshot);
  await app.confirmRebase();
  const rebased = await app.drafts.get(nextKey);
  assert.ok(rebased, 'confirming the retained rebase writes the new publication key');
  assert.equal(rebased.fields['player.speed'], 270, 'the new-key record retains the warm field edit');
  assert.equal(rebased.targetNotes.player.feedbackId, noteId, 'the new-key record retains the feedback identity');
  assert.ok(await app.drafts.get(oldDraft.key), 'the old publication draft remains available after rebase');

  app.destroy(); dom.window.close();
  console.log('PASS Studio E9 warm rebase QA: repeated same-revision response keeps the rebase and writes the new-key draft');
})().catch(error => { console.error(error.stack || error); process.exitCode = 1; dom.window.close(); });
