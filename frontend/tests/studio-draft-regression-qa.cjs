#!/usr/bin/env node
/* Regression coverage for dirty iteration drafts, reviewed rebases, and store/project races. */
const fs = require('node:fs');
const path = require('node:path');
const strict = require('node:assert/strict');
const { pathToFileURL } = require('node:url');
let JSDOM;
try { ({ JSDOM } = require('jsdom')); } catch { console.log('SKIP Studio draft QA: jsdom is unavailable.'); process.exit(0); }

const root = path.resolve(__dirname, '..');
const dom = new JSDOM(fs.readFileSync(path.join(root, 'studio/index.html'), 'utf8'), {
  url: 'http://127.0.0.1:8123/studio/', pretendToBeVisual: true,
});
const projectA = { id: 'draft-project', title: '草稿项目', workflow: 'objects-v1' };
const projectB = { id: 'other-project', title: '另一个项目', workflow: 'objects-v1' };
const capabilities = { interactiveFrontendConfirmation: true, sessionDispatch: true, godotVerification: true, semanticProjection: true };
const calls = [];
let revisionA = 1;
let revisionB = 1;
const response = data => ({ ok: true, status: 200, text: async () => JSON.stringify(data) });
const fixture = (id, revision) => ({
  snapshot: {
    id: `snapshot-${id}-${revision}`, projectId: id, publicationRevision: revision,
    workflow: 'objects-v1', kind: 'MVP', playable: true, sourceCommit: `git-${id}-${revision}`,
    decisions: {}, catalog: { objects: [{ id: 'player', name: '玩家', fields: [{ id: 'speed', label: '速度', type: 'scalar', value: 220 }] }] },
  },
  capabilities: { fields: [{ id: 'player.speed', objectId: 'player', fieldId: 'speed', label: '速度', type: 'scalar', value: 220, editable: true, min: 0, max: 500 }] },
  candidates: [], iterationReady: true,
});
const projects = [projectA, projectB];
const fetchImpl = async (url, init = {}) => {
  const method = init.method || 'GET';
  const pathname = new URL(url, 'http://127.0.0.1:8123').pathname;
  calls.push({ method, pathname, body: init.body ? JSON.parse(init.body) : undefined });
  if (pathname === '/api/session') return response({ token: 'draft-qa-token' });
  if (pathname === '/api/workspace') return response({
    apiVersion: 'objects-v1', storeId: 'store-current', workspaceId: 'test', projects,
    jobs: [], proposals: [], packets: [], testData: false, capabilities,
  });
  const workspaceMatch = pathname.match(/^\/api\/projects\/([^/]+)\/workspace$/);
  if (method === 'GET' && workspaceMatch) {
    const project = projects.find(item => item.id === workspaceMatch[1]);
    return project ? response({
      apiVersion: 'objects-v1', storeId: 'store-current', workspaceId: 'test',
      projects: [project], jobs: [], proposals: [], packets: [], testData: false,
      capabilities, iterationReady: true,
    }) : { ok: false, status: 404, text: async () => '{"error":"missing"}' };
  }
  const workbenchMatch = pathname.match(/^\/api\/projects\/([^/]+)\/workbench$/);
  if (method === 'GET' && workbenchMatch) {
    const id = workbenchMatch[1];
    if (id === projectA.id) return response(fixture(id, revisionA));
    if (id === projectB.id) return response(fixture(id, revisionB));
  }
  return { ok: false, status: 404, text: async () => JSON.stringify({ error: `missing route ${method} ${pathname}` }) };
};
const tick = () => new Promise(resolve => setTimeout(resolve, 0));

(async () => {
  const savedDocument = global.document;
  delete global.document;
  global.FormData = dom.window.FormData;
  global.HTMLElement = dom.window.HTMLElement;
  global.confirm = () => { throw new Error('Draft QA must not impersonate a user approval.'); };
  const { StudioApp } = await import(pathToFileURL(path.join(root, 'studio/studio.js')).href);
  global.document = dom.window.document;
  global.location = dom.window.location;
  global.history = dom.window.history;
  const app = new StudioApp({ fetchImpl, documentImpl: dom.window.document, timers: globalThis });
  const records = new Map();
  const reads = [];
  app.drafts = {
    open: async () => ({}),
    get: async key => { reads.push(key); return records.get(key) || null; },
    put: async record => { records.set(record.key, record); return record; },
    delete: async key => records.delete(key),
  };
  await app.start();
  app.persistenceOK = true;
  await app.openProject(projectA.id, 'iteration');
  strict.equal(app.snapshot.publicationRevision, 1);
  strict.equal(app.storageId(), 'store-current');

  // A legacy draft key uses only the shared "test" workspace label. A different
  // SQLite store with the same project ID must never adopt that content.
  const legacyKey = 'test:draft-project:1';
  records.set(legacyKey, {
    key: legacyKey, projectId: projectA.id, publicationRevision: 1, draftRevision: 99,
    text: '另一个存储中的私有草稿', values: {}, fields: {}, feedback: [],
  });
  const currentKey = app.makeDraftKey(app.snapshot);
  strict.notEqual(currentKey, legacyKey);
  await app.restoreDraft();
  strict.equal(document.querySelector('#edit-text').value, '', 'legacy drafts from another store must not be adopted');
  strict.equal(reads.includes(legacyKey), false, 'store migration must not read the ambiguous legacy key');

  // Save an exact current-store draft, then verify publication changes require an
  // explicit review and preserve text, object fields, feedback and project identity.
  const speed = document.querySelector('#dynamic-fields [data-field-id="player.speed"]');
  strict.ok(speed, 'fixture exposes a supported object field');
  document.querySelector('#edit-text').value = '只属于 A 的未提交说明';
  speed.value = '340';
  app.feedback = [{ objectId: 'player', category: 'behavior', message: '转向迟缓' }];
  app.draftRevision = 4;
  const visible = app.readVisibleDraft();
  const saved = {
    key: currentKey, projectId: projectA.id, stage: 'iteration', publicationRevision: 1,
    ...visible, updatedAt: new Date().toISOString(),
  };
  await app.drafts.put(saved);
  revisionA = 2;
  await app.loadWorkbench(projectA.id);
  strict.ok(app.pendingRebase, 'a dirty draft must pause when its published base changes');
  strict.match(document.querySelector('#rebase-content').textContent, /只属于 A 的未提交说明/);
  strict.match(document.querySelector('#rebase-content').textContent, /player\.speed/);
  strict.match(document.querySelector('#rebase-content').textContent, /转向迟缓/);
  const beforeSubmit = calls.filter(call => call.method === 'POST' && call.pathname.endsWith('/concepts')).length;
  await app.submitIteration();
  strict.equal(calls.filter(call => call.method === 'POST' && call.pathname.endsWith('/concepts')).length, beforeSubmit,
    'iteration must remain blocked until the rebase is reviewed');
  await app.confirmRebase();
  const key2 = app.makeDraftKey(app.snapshot);
  strict.equal(app.pendingRebase, null);
  strict.equal(document.querySelector('#edit-text').value, '只属于 A 的未提交说明');
  strict.equal(document.querySelector('#dynamic-fields [data-field-id="player.speed"]').value, '340');
  strict.equal(app.feedback[0].message, '转向迟缓');
  strict.ok(records.has(key2), 'approved rebase copies the draft under the new publication revision');

  // A draft edited after the preview must refresh the preview and require a second
  // confirmation; the newer content is the only version that can be applied.
  document.querySelector('#edit-text').value = '第二次修改后的内容';
  document.querySelector('#dynamic-fields [data-field-id="player.speed"]').value = '360';
  app.draftRevision += 1;
  const newest = {
    ...records.get(key2), ...app.readVisibleDraft(), key: key2,
    projectId: projectA.id, stage: 'iteration', publicationRevision: 2,
    updatedAt: new Date().toISOString(),
  };
  await app.drafts.put(newest);
  revisionA = 3;
  await app.loadWorkbench(projectA.id);
  const changedAfterPreview = { ...newest, text: '预览之后又修改的版本', draftRevision: newest.draftRevision + 1 };
  await app.drafts.put(changedAfterPreview);
  await app.confirmRebase();
  strict.match(document.querySelector('#rebase-content').textContent, /预览之后又修改的版本/);
  strict.ok(app.pendingRebase, 'changed stored content must require another review');
  await app.confirmRebase();
  strict.equal(document.querySelector('#edit-text').value, '预览之后又修改的版本');
  strict.equal(app.pendingRebase, null);

  // A delayed rebase read from A must become inert after navigating to B.
  document.querySelector('#edit-text').value = 'A 的延迟草稿';
  app.draftRevision += 1;
  revisionA = 4;
  await app.loadWorkbench(projectA.id);
  let resolveRebaseRead;
  const originalGet = app.drafts.get;
  const lateRead = new Promise(resolve => { resolveRebaseRead = resolve; });
  const oldAKey = app.pendingRebase.oldKey;
  app.drafts.get = key => key === oldAKey ? lateRead : originalGet(key);
  const pendingRead = app.confirmRebase();
  await tick();
  await app.openProject(projectB.id, 'iteration');
  resolveRebaseRead(records.get(oldAKey));
  await pendingRead;
  strict.equal(app.projectId, projectB.id);
  strict.equal(app.snapshot.projectId, projectB.id);
  strict.notEqual(document.querySelector('#edit-text').value, 'A 的延迟草稿');
  app.drafts.get = originalGet;

  // A delayed persistence write from B must not overwrite the newly selected A UI.
  document.querySelector('#edit-text').value = 'B 的延迟草稿';
  app.draftRevision = 7;
  const bKey = app.makeDraftKey(app.snapshot);
  const bSaved = { key: bKey, projectId: projectB.id, publicationRevision: 1, stage: 'iteration', ...app.readVisibleDraft() };
  records.set(bKey, bSaved);
  revisionB = 2;
  await app.loadWorkbench(projectB.id);
  let releaseWrite;
  const originalPut = app.drafts.put;
  app.drafts.put = record => new Promise(resolve => { releaseWrite = () => { records.set(record.key, record); resolve(record); }; });
  const pendingWrite = app.confirmRebase();
  await tick(); await tick();
  strict.equal(typeof releaseWrite, 'function', 'reviewed rebase should be waiting on persistence');
  await app.openProject(projectA.id, 'iteration');
  const aText = document.querySelector('#edit-text').value;
  releaseWrite(); await pendingWrite;
  strict.equal(app.projectId, projectA.id);
  strict.equal(app.snapshot.projectId, projectA.id);
  strict.equal(document.querySelector('#edit-text').value, aText);
  strict.notEqual(document.querySelector('#edit-text').value, 'B 的延迟草稿');
  app.drafts.put = originalPut;

  app.destroy(); dom.window.close();
  if (savedDocument) global.document = savedDocument;
  console.log('PASS Studio draft regression QA: store isolation, dirty-draft rebase, explicit review, drift refresh, and stale async guards');
})().catch(error => { console.error(error.stack || error); process.exitCode = 1; });
