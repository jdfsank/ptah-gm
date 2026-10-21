#!/usr/bin/env node
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const { pathToFileURL } = require('node:url');
const { JSDOM } = require('jsdom');

(async () => {
  const root = path.resolve(__dirname, '..');
  const dom = new JSDOM(fs.readFileSync(path.join(root, 'studio/index.html'), 'utf8'), { url: 'http://localhost/studio/' });
  const { StudioApp } = await import(pathToFileURL(path.join(root, 'studio/studio.js')).href);
  global.document = dom.window.document; global.Option = dom.window.Option; global.location = dom.window.location; global.history = dom.window.history;
  const project = { id: 'repair-project', workflow: 'objects-v1', publicationRevision: 0, snapshotId: null };
  const repair = { projectId: project.id, kind: 'REPAIR', workflow: 'objects-v1', playable: false,
    publicationRevision: 0, jobId: 'job-1', candidateId: 'candidate-1', sourceCommit: 'candidate-commit-1',
    document: { objects: [{ id: 'player', name: '玩家', fields: [{ id: 'speed', value: 220, type: 'scalar' }] }] },
    catalog: { capabilities: [{ objectId: 'player', fieldId: 'speed', id: 'player.speed', value: 220, editable: true, type: 'scalar', min: 0, max: 500 }] } };
  const records = new Map(), calls = [];
  let currentRepair = repair;
  const response = value => ({ ok: true, status: 200, text: async () => JSON.stringify(value) });
  const app = new StudioApp({ documentImpl: document, timers: globalThis, fetchImpl: async (url, init = {}) => {
    calls.push({ url, body: init.body && JSON.parse(init.body) });
    if (url.includes('/workbench')) return response({ snapshot: null, repairContext: currentRepair, iterationReady: false, candidates: [] });
    if (url.endsWith('/concepts')) return response({ proposal: { id: 'repair-proposal', projectId: project.id, status: 'PLANNING', revision: 1,
      workflow: 'objects-v1', publicationRevision: 0, repairBase: { candidateId: currentRepair.candidateId, sourceCommit: currentRepair.sourceCommit } } });
    if (url.endsWith('/decision')) return response({ job: { id: 'job-1', projectId: project.id, status: 'REJECTED' } });
    throw new Error(`Unexpected request ${url}`);
  } });
  app.projectId = project.id; app.manager = { projects: [project] }; app.workspace = { storeId: 'repair-store', projects: [project] };
  app.readiness = { ready: true }; app.persistenceOK = true; app.token = 'fixture';
  app.drafts = { get: async key => records.get(key), put: async value => records.set(value.key, structuredClone(value)) };
  await app.loadWorkbench(project.id);
  assert.equal(app.stage, 'iteration'); assert.equal(app.canEnterIteration(), true);
  assert.equal(document.querySelector('#edit-form').classList.contains('hidden'), false);
  assert.equal(document.querySelector('#object-catalog').classList.contains('hidden'), false);
  assert.match(document.querySelector('#snapshot-version').textContent, /未发布/);
  assert.match(document.querySelector('#workbench-title').textContent, /返修/);
  assert.equal(document.querySelector('#proposal-panel').classList.contains('hidden'), true);
  assert.ok(!document.querySelector('#snapshot-summary').textContent.includes('尚无可玩的 MVP'));
  document.querySelector('#edit-text').value = '修正移动手感';
  app.feedback = [{ objectId: 'player', category: 'behavior', message: '移动迟缓' }];
  document.querySelector('[data-field-id="player.speed"]').value = '240';
  await app.saveDraft(); const firstKey = app.draftKey;
  await app.loadWorkbench(project.id);
  assert.equal(document.querySelector('#edit-text').value, '修正移动手感');
  assert.equal(app.feedback[0].message, '移动迟缓');
  await app.submitIteration();
  const submitted = calls.find(item => item.url.endsWith('/concepts'));
  assert.equal(submitted.body.changeRequest.sourceCommit, repair.sourceCommit);
  assert.equal(submitted.body.changeRequest.baseRevision, 0);
  assert.equal(submitted.body.changeRequest.fields[0].value, 240);
  assert.equal(submitted.body.changeRequest.feedback[0].message, '移动迟缓');
  assert.equal(app.isIterationProposal(), true, 'first candidate repair proposals must be visible at publication revision zero');
  app.stopProposalPolling();
  currentRepair = { ...repair, candidateId: 'candidate-2', sourceCommit: 'candidate-commit-2', jobId: 'job-2' };
  await app.loadWorkbench(project.id);
  assert.notEqual(app.draftKey, firstKey, 'separate repair candidates must not share drafts');
  assert.equal(document.querySelector('#edit-text').value, '');
  assert.equal(app.feedback.length, 0);
  assert.ok(!app.pendingRebase, 'rejection must open feedback directly without a spurious publication rebase dialog');
  assert.equal(records.get(firstKey).text, '', 'submitted feedback is removed from the working draft after the receipt');
  assert.equal(submitted.body.changeRequest.feedback[0].message, '移动迟缓', 'submitted feedback remains in the retained request');
  currentRepair = repair; await app.loadWorkbench(project.id);
  app.proposal = null;
  app.job = { id: 'job-1', projectId: project.id, status: 'READY_FOR_REVIEW' };
  global.confirm = () => true; // Fixture-only simulated rejection, never a real approval.
  await app.decideCandidate('reject', repair.sourceCommit, repair.candidateId);
  assert.equal(app.stage, 'iteration'); assert.equal(app.canEnterIteration(), true);
  assert.equal(document.querySelector('#edit-form').classList.contains('hidden'), false);
  assert.equal(document.querySelector('#job-panel').classList.contains('hidden'), true, 'rejected history must not obscure repair controls');
  document.querySelector('#snapshot-summary button').click();
  assert.equal(document.querySelector('#job-panel').classList.contains('hidden'), false, 'history remains available on request');
  document.querySelector('#snapshot-summary button').click();
  assert.equal(document.querySelector('#job-panel').classList.contains('hidden'), true);
  app.destroy(); dom.window.close();
  console.log('PASS Studio repair QA: automatic rejection transition, object edits/feedback, revision zero planning, reload and candidate draft isolation');
})().catch(error => { console.error(error.stack || error); process.exitCode = 1; });
