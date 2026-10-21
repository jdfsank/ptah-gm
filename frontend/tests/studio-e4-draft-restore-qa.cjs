#!/usr/bin/env node
/* Deep links must not overwrite restored per-target notes during first render. */
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const { pathToFileURL } = require('node:url');
let JSDOM;
try { ({ JSDOM } = require('jsdom')); }
catch { console.log('SKIP Studio E4 draft restore QA: jsdom is unavailable.'); process.exit(0); }

const root = path.resolve(__dirname, '..');
const projectId = 'e4-game';
const storeId = 'e4-store';
const dom = new JSDOM(fs.readFileSync(path.join(root, 'studio/index.html'), 'utf8'), {
  url: `http://127.0.0.1:8123/studio/?project=${projectId}&stage=iteration&target=dice`,
  pretendToBeVisual: true,
});
global.document = dom.window.document;
global.Option = dom.window.Option;
global.localStorage = dom.window.localStorage;
global.location = dom.window.location;
global.history = dom.window.history;
const response = data => ({ ok: true, status: 200, text: async () => JSON.stringify(data) });

(async () => {
  const { StudioApp } = await import(pathToFileURL(path.join(root, 'studio/studio.js')).href);
  const project = { id: projectId, title: 'E4 深链恢复', workflow: 'objects-v1' };
  const workspace = { storeId, projects: [project], iterationReady: true, capabilities: {} };
  const arena = { id: 'arena', name: '竞技场', kind: 'scene', fields: [], workbench: { role: 'scene', bounds: [800, 600] } };
  const player = { id: 'player', name: '玩家', kind: 'entity', fields: [], workbench: { role: 'instance', sceneId: 'arena' } };
  const dice = { id: 'dice', name: '骰子', kind: 'entity', fields: [], workbench: { role: 'instance', sceneId: 'arena' } };
  const snapshot = {
    projectId, publicationRevision: 3, kind: 'MVP', playable: true, workflow: 'objects-v1', sourceCommit: 'git-e4-3',
    catalog: { objects: [arena, player, dice] }, document: { objects: [arena, player, dice] },
  };
  const fetchImpl = async url => {
    const pathname = new URL(url, 'http://127.0.0.1:8123').pathname;
    if (pathname === `/api/projects/${projectId}/workbench`) return response({ snapshot, capabilities: { fields: [] }, candidates: [], iterationReady: true });
    return { ok: false, status: 404, text: async () => JSON.stringify({ error: `missing route ${pathname}` }) };
  };
  const app = new StudioApp({ fetchImpl, documentImpl: dom.window.document, timers: globalThis });
  app.workspace = workspace; app.manager = workspace; app.projectId = projectId; app.stage = 'iteration'; app.workflow = 'objects-v1'; app.persistenceOK = true;
  const key = `${storeId}:${projectId}:iteration:3`;
  const targetNotes = {
    player: { objectId: 'player', text: '骰子预警更清楚，保留现有奖励规则。', feedbackId: 'note-player' },
    dice: { objectId: 'dice', text: '骰子测试原文：切换目标与刷新后保留。', feedbackId: 'note-dice' },
  };
  const storedDraft = { key, projectId, publicationRevision: 3, draftRevision: 8, selectedObjectId: 'player', targetNotes, structuralProposals: [], fields: {}, feedback: [] };
  let finishRead, signalReadStarted;
  const readStarted = new Promise(resolve => { signalReadStarted = resolve; });
  const writes = [];
  app.drafts = {
    get: requestedKey => {
      assert.equal(requestedKey, key);
      signalReadStarted();
      return new Promise(resolve => { finishRead = () => resolve(storedDraft); });
    },
    put: async value => { writes.push(value); return value; },
    delete: async () => {},
  };
  app.bind();
  const loading = app.loadWorkbench(projectId);
  await readStarted;
  assert.equal(writes.length, 0, 'applying the initial URL target cannot write an empty draft before hydration');
  finishRead();
  await loading;

  assert.deepEqual(app.targetNotes, targetNotes, 'notes for both targets survive a reload');
  assert.equal(app.selectedObjectId, 'dice', 'the URL target takes precedence over the saved selection');
  assert.equal(dom.window.document.querySelector('#edit-text').value, targetNotes.dice.text);
  assert.equal(app.draftRevision, 8);
  assert.equal(writes.length, 0, 'route application and draft hydration perform no redundant write');

  const previousSnapshot = { ...snapshot, publicationRevision: 2, sourceCommit: 'git-e4-2' };
  const structuralProposals = [{ operationId: 'op-remove-dice', kind: 'delete-instance', objectId: 'dice', scope: '竞技场' }];
  const rebaseDraft = { ...storedDraft, text: '', targetNotes, structuralProposals };
  app.draftKey = `${storeId}:${projectId}:iteration:2`;
  app.handleRebase(previousSnapshot, snapshot, rebaseDraft);
  const rebasePreview = dom.window.document.querySelector('#rebase-content').textContent;
  assert.match(rebasePreview, /意见 · 玩家（ID player） · note-player：骰子预警更清楚，保留现有奖励规则。/);
  assert.match(rebasePreview, /意见 · 骰子（ID dice） · note-dice：骰子测试原文：切换目标与刷新后保留。/);
  assert.match(rebasePreview, /结构提案 · 移除实例提案 · 骰子/);
  assert.equal(app.sameReviewedDraft(rebaseDraft, structuredClone(rebaseDraft)), true, 'unchanged target notes and structure match the reviewed rebase');
  const changedNotes = structuredClone(rebaseDraft); changedNotes.targetNotes.dice.text += ' 新增内容';
  assert.equal(app.sameReviewedDraft(rebaseDraft, changedNotes), false, 'a target note changed after preview requires renewed review');
  const changedOperations = structuredClone(rebaseDraft); changedOperations.structuralProposals[0].scope = '新区域';
  assert.equal(app.sameReviewedDraft(rebaseDraft, changedOperations), false, 'a structural proposal changed after preview requires renewed review');
  app.destroy(); dom.window.close();
  console.log('PASS Studio E4 draft QA: deep-link reload preserves target notes; reviewed rebase previews and detects later target/structure edits');
})().catch(error => { console.error(error.stack || error); process.exitCode = 1; dom.window.close(); });
