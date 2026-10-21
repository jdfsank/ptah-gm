#!/usr/bin/env node
/* Focused QA for bound-resource descriptors in the main preview. */
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const { pathToFileURL } = require('node:url');
let JSDOM;
try { ({ JSDOM } = require('jsdom')); }
catch { console.log('SKIP Studio bound-resource preview QA: jsdom is unavailable.'); process.exit(0); }

const root = path.resolve(__dirname, '..');
const dom = new JSDOM(fs.readFileSync(path.join(root, 'studio/index.html'), 'utf8'), {
  url: 'http://127.0.0.1:8123/studio/?project=bound-resource-preview', pretendToBeVisual: true,
});
global.document = dom.window.document;
global.localStorage = dom.window.localStorage;

(async () => {
  const { LegacyWorkbench } = await import(pathToFileURL(path.join(root, 'studio/workbench.js')).href);
  const object = {
    id: 'hero-art', name: '英雄图集', kind: 'asset', sourceBindings: ['resources/hero.tres'], fields: [],
    workbench: { role: 'resource', provenance: { kind: 'fact', sourcePaths: ['resources/hero.tres'] }, preview: { type: 'image', label: '运行剪辑' } },
  };
  const requestedPaths = [];
  const app = {
    selectedObjectId: object.id, projectId: 'bound-project', fieldDraftValues: {},
    objectItems: () => [object], targetNotes: {}, structuralProposals: [],
    request: async path => {
      requestedPaths.push(path);
      return {
        projectId: 'bound-project', objectId: object.id, kind: 'static_source', sourceCommit: 'git-bound-atlas',
        imagePreview: { resourcePath: 'resources/hero.tres', imagePath: 'assets/hero-sheet.png', region: [16, 0, 32, 24], clipName: 'run', frameCount: 6, fps: 12 },
      };
    },
  };
  const wb = new LegacyWorkbench(app);
  wb.bind();
  const mainPreview = document.querySelector('#workbench-preview');
  wb.renderPreview();
  const loadButton = mainPreview.querySelector('[data-workbench-action="load-bound-preview"]');
  assert(loadButton, 'the resource preview offers a bound-resource detail action');
  loadButton.click();
  await new Promise(resolve => setTimeout(resolve, 0));
  assert.deepEqual(requestedPaths, ['/projects/bound-project/objects/hero-art/source'], 'the main preview reads the published source descriptor');

  const descriptor = mainPreview.querySelector('.workbench-bound-image .workbench-source-image-preview');
  assert(descriptor, 'the shared bound-source descriptor renderer populates the main preview');
  assert.equal(mainPreview.querySelectorAll('.workbench-bound-image .workbench-source-image-preview').length, 1, 'one click renders exactly one bound-resource descriptor');
  assert.match(descriptor.textContent, /resources\/hero\.tres/);
  assert.match(descriptor.textContent, /Atlas 区域：16, 0 · 32 × 24 像素/);
  assert.match(descriptor.textContent, /run.*6 帧 · 12 FPS/);
  assert.match(descriptor.textContent, /真实首帧/);
  assert.equal(new URL(descriptor.querySelector('img').src).pathname, '/api/projects/bound-project/objects/hero-art/preview');

  loadButton.click();
  assert.deepEqual(requestedPaths, ['/projects/bound-project/objects/hero-art/source'], 'the second click reuses the cached descriptor without another request');
  assert.equal(mainPreview.querySelectorAll('.workbench-bound-image .workbench-source-image-preview').length, 1, 'the cached click replaces rather than duplicates the descriptor');

  wb.sourceCache.clear(); wb.renderPreview();
  let resolveBoundSource;
  app.request = () => new Promise(resolve => { resolveBoundSource = resolve; });
  const pendingBoundSource = wb.loadBoundPreview(object.id);
  assert.equal(typeof resolveBoundSource, 'function', 'the delayed bound-source request is in flight');
  app.snapshot = { publicationRevision: 2, sourceCommit: 'git-new-version' };
  resolveBoundSource({ projectId: 'bound-project', objectId: object.id, kind: 'static_source', sourceCommit: 'git-old-version', imagePreview: { imagePath: 'old.png' } });
  await pendingBoundSource;
  assert.equal(wb.sourceCache.has(object.id), false, 'a response for the previous publication version never enters the cache for the same object ID');

  const sourceDetails = document.createElement('details');
  sourceDetails.innerHTML = '<div class="workbench-source-result"></div>';
  document.body.append(sourceDetails);
  let resolveObjectSource;
  app.request = () => new Promise(resolve => { resolveObjectSource = resolve; });
  const pendingObjectSource = wb.loadSource(object.id, sourceDetails);
  assert.equal(typeof resolveObjectSource, 'function', 'the delayed object-source request is in flight');
  app.projectId = 'next-project';
  resolveObjectSource({ projectId: 'bound-project', objectId: object.id, kind: 'static_source', sourceCommit: 'git-old-version', sources: [] });
  await pendingObjectSource;
  assert.equal(wb.sourceCache.has(object.id), false, 'a response from the previous project never enters the cache for the same object ID');

  wb.stopPreview();
  dom.window.close();
  console.log('PASS Studio bound-resource preview QA: source path, Atlas region, animation first frame, frame count/FPS, and exact-version image reuse');
})().catch(error => { console.error(error.stack || error); process.exitCode = 1; dom.window.close(); });
