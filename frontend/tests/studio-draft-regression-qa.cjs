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
  global.Option = dom.window.Option;
  global.confirm = () => { throw new Error('Draft QA must not impersonate a user approval.'); };
  const { StudioApp, DraftStore } = await import(pathToFileURL(path.join(root, 'studio/studio.js')).href);
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
  if (app.draftTimer != null) { clearTimeout(app.draftTimer); app.draftTimer = null; }
  const speed = document.querySelector('#dynamic-fields [data-field-id="player.speed"]');
  strict.ok(speed, 'fixture exposes a supported object field');
  document.querySelector('#edit-text').value = '只属于 A 的未提交说明';
  speed.value = '340';
  app.feedback = [{ objectId: 'player', category: 'behavior', message: '转向迟缓' }];
  app.draftRevision = 4;
  await app.saveDraft();
  strict.equal(records.get(currentKey).draftRevision, 5, 'a save must increment the stored revision instead of copying the previous visible value');
  strict.match(document.querySelector('#draft-state').textContent, /草稿修订 5/);
  await app.saveDraft();
  strict.equal(records.get(currentKey).draftRevision, 6, 'successive saves must retain their increasing revisions');
  strict.equal(records.get(currentKey).text, '只属于 A 的未提交说明');
  strict.equal(records.get(currentKey).feedback[0].message, '转向迟缓');
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
  const changedAfterPreview = { ...newest, text: '预览之后又修改的版本',
    targetNotes: { ...(newest.targetNotes || {}), player: { ...(newest.targetNotes?.player || {}), text: '预览之后又修改的版本' } },
    draftRevision: newest.draftRevision + 1 };
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

  app.destroy();

  // No debounce, pagehide callback, or IndexedDB completion may be needed to
  // retain an input event that has just returned to the browser.
  const instantDom = new JSDOM(fs.readFileSync(path.join(root, 'studio/index.html'), 'utf8'), { url: 'http://127.0.0.1:8123/studio/' });
  global.document = instantDom.window.document;
  const storage = instantDom.window.localStorage;
  const instant = new StudioApp({ fetchImpl: () => { throw new Error('Draft edits must not contact the backend.'); }, documentImpl: instantDom.window.document });
  instant.drafts = new DraftStore(null, storage); await instant.drafts.open(); instant.persistenceOK = true;
  instant.workspace = { storeId: 'store-current', projects, iterationReady: true }; instant.projectId = projectA.id; instant.stage = 'iteration';
  instant.snapshot = fixture(projectA.id, 1).snapshot; instant.capabilities = fixture(projectA.id, 1).capabilities; instant.workflow = 'objects-v1';
  instant.bind(); instant.renderWorkbench();
  const instantKey = instant.makeDraftKey(instant.snapshot), storageKey = 'ptah-studio-draft-v2:' + instantKey;
  const input = (selector, value, event = 'input') => { const node = document.querySelector(selector); node.value = value; node.dispatchEvent(new instantDom.window.Event(event, { bubbles: true })); };
  input('#edit-text', '输入后立刻重载');
  strict.equal(JSON.parse(storage.getItem(storageKey)).text, '输入后立刻重载', 'input handler must finish its durable write without awaiting a timer');
  input('#dynamic-fields [data-field-id="player.speed"]', '375');
  input('#feedback-message', '还没有点击添加的反馈');
  input('#feedback-category', 'behavior', 'change');
  strict.equal(JSON.parse(storage.getItem(storageKey)).feedbackMessage, '还没有点击添加的反馈');
  document.querySelector('#add-feedback').click();
  const lastInputRevision = JSON.parse(storage.getItem(storageKey)).draftRevision;
  instant.projectId = projectB.id;
  input('#concept', '初始概念输入后立即重载');
  const conceptKey = instant.conceptDraftKey(projectB.id);
  strict.equal(JSON.parse(storage.getItem('ptah-studio-draft-v2:' + conceptKey)).text, '初始概念输入后立即重载');
  strict.equal((await new DraftStore(null, storage).get(conceptKey)).text, '初始概念输入后立即重载');
  strict.equal(instant.conceptDraftTimer, null);
  instant.projectId = projectA.id;
  instant.destroy();
  const reopened = new StudioApp({ documentImpl: instantDom.window.document });
  reopened.drafts = new DraftStore(null, storage); reopened.persistenceOK = true;
  reopened.workspace = instant.workspace; reopened.projectId = projectA.id; reopened.stage = 'iteration'; reopened.workflow = 'objects-v1';
  reopened.snapshot = fixture(projectA.id, 1).snapshot; reopened.capabilities = fixture(projectA.id, 1).capabilities;
  document.querySelector('#edit-text').value = ''; document.querySelector('#feedback-message').value = '';
  reopened.renderWorkbench(); await reopened.restoreDraft();
  strict.equal(document.querySelector('#edit-text').value, '输入后立刻重载');
  strict.equal(document.querySelector('#dynamic-fields [data-field-id="player.speed"]').value, '375');
  strict.equal(reopened.feedback[0].message, '还没有点击添加的反馈');
  strict.equal(reopened.feedback[0].category, 'behavior');
  strict.equal(reopened.draftRevision, lastInputRevision);
  strict.equal(reopened.draftTimer, null);
  strict.equal(await reopened.drafts.get('another-store:draft-project:iteration:1'), null);
  strict.equal(await reopened.drafts.get('store-current:other-project:iteration:1'), null);
  strict.equal(await reopened.drafts.get('store-current:draft-project:iteration:2'), null);

  // A first render applies the URL target before IndexedDB/localStorage has
  // restored per-target notes. That route change must not persist its empty
  // placeholder over the saved draft, and the deep link must win over the
  // previously selected target stored in that draft.
  const reloadDom = new JSDOM(fs.readFileSync(path.join(root, 'studio/index.html'), 'utf8'), {
    url: 'http://127.0.0.1:8123/studio/?project=draft-project&stage=iteration&target=dice',
  });
  global.document = reloadDom.window.document; global.location = reloadDom.window.location; global.history = reloadDom.window.history;
  const player = { id: 'player', kind: 'entity', name: '玩家', fields: [], workbench: { role: 'instance', sceneId: 'arena' } };
  const dice = { id: 'dice', kind: 'entity', name: '骰子', fields: [], workbench: { role: 'instance', sceneId: 'arena' } };
  const reloadSnapshot = { ...fixture(projectA.id, 1).snapshot, catalog: { objects: [player, dice] }, document: { objects: [player, dice] } };
  const reloadApp = new StudioApp({
    documentImpl: reloadDom.window.document,
    fetchImpl: async url => new URL(url, 'http://127.0.0.1:8123').pathname === `/api/projects/${projectA.id}/workbench`
      ? response({ snapshot: reloadSnapshot, capabilities: { fields: [] }, candidates: [], iterationReady: true })
      : { ok: false, status: 404, text: async () => '{"error":"missing"}' },
  });
  reloadApp.workspace = { storeId: 'store-current', projects: [projectA], iterationReady: true };
  reloadApp.manager = reloadApp.workspace; reloadApp.projectId = projectA.id; reloadApp.stage = 'iteration'; reloadApp.workflow = 'objects-v1';
  const reloadKey = 'store-current:draft-project:iteration:1';
  const savedTargetNotes = {
    player: { objectId: 'player', text: '骰子预警更清楚，保留现有奖励规则。', feedbackId: 'player-feedback' },
    dice: { objectId: 'dice', text: '骰子测试原文：切换目标与刷新后保留。', feedbackId: 'dice-feedback' },
  };
  const savedReloadDraft = { key: reloadKey, projectId: projectA.id, publicationRevision: 1, draftRevision: 22, selectedObjectId: 'player', targetNotes: savedTargetNotes, structuralProposals: [], fields: {}, feedback: [] };
  let completeReloadRead, signalReloadRead;
  const reloadReadStarted = new Promise(resolve => { signalReloadRead = resolve; });
  const reloadWrites = [];
  reloadApp.drafts = {
    get: key => { strict.equal(key, reloadKey); signalReloadRead(); return new Promise(resolve => { completeReloadRead = () => resolve(savedReloadDraft); }); },
    put: async record => { reloadWrites.push(record); return record; },
    delete: async () => {},
  };
  reloadApp.persistenceOK = true; reloadApp.bind();
  const loadingReload = reloadApp.loadWorkbench(projectA.id);
  await reloadReadStarted;
  strict.equal(reloadWrites.length, 0, 'the initial deep-link route cannot overwrite a saved draft while restoration is pending');
  completeReloadRead(); await loadingReload;
  strict.deepEqual(reloadApp.targetNotes, savedTargetNotes, 'all target-specific notes survive the deep-link reload');
  strict.equal(reloadApp.selectedObjectId, 'dice', 'a deep-link target takes precedence over the older selected target in the draft');
  strict.equal(reloadDom.window.document.querySelector('#edit-text').value, savedTargetNotes.dice.text, 'the deep-linked target text is restored into the editor');
  strict.equal(reloadWrites.length, 0, 'restoring a route and draft performs no unnecessary write');
  reloadApp.destroy(); reloadDom.window.close();

  // A cold start on a newer publication discovers an older, same-store draft
  // and requires an explicit rebase. It preserves missing historical source
  // identity honestly and never overwrites a draft created on the new key.
  const coldDom = new JSDOM(fs.readFileSync(path.join(root, 'studio/index.html'), 'utf8'), { url: 'http://127.0.0.1:8123/studio/' });
  global.document = coldDom.window.document; global.location = coldDom.window.location; global.history = coldDom.window.history; global.Option = coldDom.window.Option;
  const coldStorage = coldDom.window.localStorage;
  const coldOldKey = 'store-current:draft-project:iteration:1';
  const coldNewKey = 'store-current:draft-project:iteration:2';
  const coldOldDraft = { key: coldOldKey, projectId: projectA.id, publicationRevision: 1, draftRevision: 31,
    text: '', values: {}, fields: { 'player.speed': 260 }, feedback: [], feedbackMessage: '', feedbackCategory: 'behavior',
    selectedObjectId: 'player', targetNotes: {
      player: { objectId: 'player', feedbackId: 'cold-player-note', text: '冷启动保留玩家意见。', category: 'behavior' },
      dice: { objectId: 'dice', feedbackId: 'cold-dice-note', text: '冷启动保留骰子意见。', category: 'visual' },
    }, structuralProposals: [], updatedAt: '2026-10-13T12:00:00Z' };
  coldStorage.setItem('ptah-studio-draft-v2:' + coldOldKey, JSON.stringify(coldOldDraft));
  const coldApp = new StudioApp({ documentImpl: coldDom.window.document,
    fetchImpl: async url => new URL(url, 'http://127.0.0.1:8123').pathname === `/api/projects/${projectA.id}/workbench`
      ? response({ snapshot: fixture(projectA.id, 2).snapshot, capabilities: fixture(projectA.id, 2).capabilities, candidates: [], iterationReady: true })
      : { ok: false, status: 404, text: async () => '{"error":"missing"}' } });
  coldApp.drafts = new DraftStore(null, coldStorage); coldApp.persistenceOK = true;
  coldApp.workspace = { storeId: 'store-current', projects: [projectA], iterationReady: true };
  coldApp.manager = coldApp.workspace; coldApp.projectId = projectA.id; coldApp.stage = 'iteration'; coldApp.workflow = 'objects-v1';
  await coldApp.loadWorkbench(projectA.id);
  strict.ok(coldApp.pendingRebase, 'cold start finds same-store historical draft and opens an explicit rebase preview');
  strict.equal(coldApp.pendingRebase.oldKey, coldOldKey);
  strict.equal(coldApp.pendingRebase.newKey, coldNewKey);
  strict.match(coldDom.window.document.querySelector('#rebase-content').textContent, /旧草稿未记录 Git 来源/);
  strict.match(coldDom.window.document.querySelector('#rebase-content').textContent, /player\.speed：草稿 260/);
  strict.match(coldDom.window.document.querySelector('#rebase-content').textContent, /冷启动保留骰子意见/);
  strict.equal(coldStorage.getItem('ptah-studio-draft-v2:' + coldNewKey), null, 'discovery cannot write over the new key before confirmation');
  const competingNewDraft = { key: coldNewKey, projectId: projectA.id, publicationRevision: 2, draftRevision: 1,
    text: '新版本中另一标签保存的内容', values: {}, fields: {}, feedback: [], targetNotes: {}, structuralProposals: [] };
  await coldApp.drafts.put(competingNewDraft);
  await coldApp.confirmRebase();
  strict.equal((await coldApp.drafts.get(coldNewKey)).text, competingNewDraft.text, 'a reviewed old draft cannot overwrite content created on the new key');
  strict.equal((await coldApp.drafts.get(coldOldKey)).fields['player.speed'], 260, 'the original draft remains intact after a key conflict');
  strict.ok(coldApp.pendingRebase, 'a new-key conflict keeps the old content available for review');
  coldStorage.removeItem('ptah-studio-draft-v2:' + coldNewKey);
  await coldApp.drafts.delete(coldOldKey); await coldApp.confirmRebase();
  strict.equal(await coldApp.drafts.get(coldNewKey), null, 'a submitted old-key tombstone cannot be rebased back to life');
  await coldApp.drafts.put(coldOldDraft);
  await coldApp.confirmRebase();
  const coldMigrated = await coldApp.drafts.get(coldNewKey);
  strict.equal(coldMigrated.fields['player.speed'], 260);
  strict.equal(coldMigrated.targetNotes.dice.text, '冷启动保留骰子意见。');
  strict.equal(coldMigrated.sourceCommit, fixture(projectA.id, 2).snapshot.sourceCommit, 'the rebased draft records the new source while retaining the old identity separately');
  strict.equal(coldMigrated.rebasedFrom.sourceCommit, null, 'missing old source identity stays missing');
  strict.equal(coldMigrated.rebasedFrom.publicationRevision, 1);
  strict.equal((await coldApp.drafts.get(coldOldKey)).fields['player.speed'], 260, 'the old source record remains available');
  coldApp.destroy(); coldDom.window.close();

  // Migrate only the exact scoped legacy key. A delayed legacy read must defer
  // to a newer synchronous edit or deletion, including changes from another tab.
  const migration = new DraftStore(null, storage);
  let completeLegacyRead;
  migration.openLegacy = async () => ({ transaction: () => ({ objectStore: () => ({ get: () => {
    const req = {}; completeLegacyRead = value => { req.result = value; req.onsuccess(); }; return req;
  } }) }) });
  const migrationKey = 'store-current:migration-project:iteration:1';
  const oldRecord = { key: migrationKey, text: '旧 IndexedDB 草稿', draftRevision: 1 };
  const oldRead = migration.get(migrationKey); await tick(); completeLegacyRead(oldRecord);
  strict.deepEqual(await oldRead, oldRecord);
  strict.deepEqual(await new DraftStore(null, storage).get(migrationKey), oldRecord);
  storage.removeItem('ptah-studio-draft-v2:' + migrationKey);
  const legacyLateRead = migration.get(migrationKey); await tick();
  const newer = { ...oldRecord, text: '读取期间的新输入', draftRevision: 2 };
  const write = migration.put(newer); completeLegacyRead(oldRecord);
  strict.deepEqual(await legacyLateRead, newer); await write;
  storage.removeItem('ptah-studio-draft-v2:' + migrationKey);
  const deletedRead = migration.get(migrationKey); await tick();
  const finishDeletedRead = completeLegacyRead; migration.openLegacy = async () => null;
  await migration.delete(migrationKey); finishDeletedRead(oldRecord);
  strict.equal(await deletedRead, null, 'submitted draft cannot reappear from a delayed legacy read');
  strict.equal(await new DraftStore(null, storage).get(migrationKey), null);
  await migration.put(newer);
  strict.deepEqual(await migration.get(migrationKey), newer, 'new edits replace the deletion tombstone');

  const unavailable = new DraftStore(null, { setItem: () => { throw new Error('QuotaExceededError'); }, removeItem: () => {}, getItem: () => null });
  await strict.rejects(unavailable.open(), /QuotaExceededError/);
  // Match the replacement store's actual empty key so the CAS reaches the
  // failing write instead of correctly reporting a different stored version.
  reopened.draftBaselineKey = reopened.draftKey; reopened.draftStorageBaseline = null;
  reopened.drafts = unavailable; await reopened.saveDraft();
  strict.equal(reopened.persistenceOK, false);
  strict.match(document.querySelector('#draft-state').textContent, /草稿保存失败/);
  reopened.destroy(); instantDom.window.close(); dom.window.close();
  if (savedDocument) global.document = savedDocument;
  console.log('PASS Studio draft regression QA: immediate input persistence/reopen, concept/fields/feedback, legacy migration races, quota failure, store isolation, reviewed rebase, and stale async guards');
})().catch(error => { console.error(error.stack || error); process.exitCode = 1; });
