#!/usr/bin/env node
/* Focused QA for restoring deep links whose target is introduced by the saved draft. */
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const { pathToFileURL } = require('node:url');
let JSDOM;
try { ({ JSDOM } = require('jsdom')); }
catch { console.log('SKIP Studio route hydration QA: jsdom is unavailable.'); process.exit(0); }

const root = path.resolve(__dirname, '..');
const dom = new JSDOM(fs.readFileSync(path.join(root, 'studio/index.html'), 'utf8'), {
  url: 'http://127.0.0.1:8123/studio/?project=route-project&stage=iteration&target=draft-scene-route&scene=draft-scene-route&view=design',
});
global.document = dom.window.document;
global.localStorage = dom.window.localStorage;
global.location = dom.window.location;
global.history = dom.window.history;

(async () => {
  const { LegacyWorkbench } = await import(pathToFileURL(path.join(root, 'studio/workbench.js')).href);
  const objects = [{ id: 'published-scene', name: '已发布场景', fields: [], relations: [], workbench: { role: 'scene' } }];
  const app = {
    projectId: 'route-project', stage: 'iteration', snapshot: { projectId: 'route-project', publicationRevision: 1, sourceCommit: 'git-route-base' },
    selectedObjectId: 'published-scene', fieldDraftValues: {}, targetNotes: {
      'draft-scene-route': { objectId: 'draft-scene-route', text: '草稿场景意见', feedbackId: 'route-note' },
    }, structuralProposals: [], objectItems: () => objects,
    currentProject: () => ({ title: '路由测试项目' }),
  };
  const wb = new LegacyWorkbench(app);
  for (const method of ['renderCatalog', 'renderTabs', 'renderBreadcrumb', 'renderCanvas', 'renderPreview', 'renderInspector', 'renderResults', 'renderOrphanNotes', 'renderOperationList', 'applyFoldState', 'setMobilePane', 'updateHistoryButtons']) wb[method] = () => {};

  wb.applyInitialRoute();
  const preservedUrl = new URL(globalThis.location.href);
  assert.equal(preservedUrl.searchParams.get('target'), 'draft-scene-route', 'initial routing keeps a draft-only deep link while saved proposals are loading');
  assert.equal(preservedUrl.searchParams.get('scene'), 'draft-scene-route');
  assert.equal(wb.pendingInitialRoute?.target, 'draft-scene-route', 'unresolved initial routing remains pending for draft hydration');
  assert.equal(app.selectedObjectId, 'published-scene', 'the missing draft target does not prematurely replace current selection');

  app.structuralProposals = [{ kind: 'new-scene', operationId: 'route-op', sceneId: 'draft-scene-route', name: '草稿场景', bounds: [320, 180] }];
  wb.render();
  assert.equal(app.selectedObjectId, 'draft-scene-route', 'the pending deep link selects the restored draft scene');
  assert.equal(wb.activeSceneId, 'draft-scene-route', 'the restored selection activates its requested draft scene');
  assert.equal(wb.sceneCanvasSelection, 'draft-scene-route', 'the canvas scene selection matches the URL scene');
  assert.equal(document.querySelector('#edit-text').value, '草稿场景意见', 'route hydration preserves and reloads the draft scene opinion');
  const resolvedUrl = new URL(globalThis.location.href);
  assert.equal(resolvedUrl.searchParams.get('target'), 'draft-scene-route', 'the normalized URL retains the restored draft target');
  assert.equal(resolvedUrl.searchParams.get('scene'), 'draft-scene-route', 'the normalized URL matches the selected active scene');
  assert.equal(wb.pendingInitialRoute, null, 'a resolved initial deep link is consumed exactly once');

  wb.removeProposal('route-op');
  assert.equal(app.selectedObjectId, null, 'removing the selected draft scene clears the deleted target');
  assert.equal(wb.activeSceneId, 'published-scene', 'removing a draft scene selects an available published scene');
  assert.equal(wb.sceneCanvasSelection, 'published-scene', 'the canvas selection is reconciled with the active scene');
  const normalizedUrl = new URL(globalThis.location.href);
  assert.equal(normalizedUrl.searchParams.get('target'), 'project', 'removing the draft scene normalizes the deleted target out of the URL');
  assert.equal(normalizedUrl.searchParams.get('scene'), 'published-scene', 'removing the draft scene normalizes its stale URL scene');

  wb.stopPreview();
  dom.window.close();
  console.log('PASS Studio route hydration QA: deferred draft-only deep link, restored target, deleted-scene route normalization, and preserved target opinion');
})().catch(error => { console.error(error.stack || error); process.exitCode = 1; dom.window.close(); });
