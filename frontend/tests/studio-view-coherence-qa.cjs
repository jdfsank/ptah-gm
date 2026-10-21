/* Async project-view regressions from the third trial; fixtures are not acceptance. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { pathToFileURL } = require('node:url');
const { JSDOM } = require('jsdom');
const root = path.resolve(__dirname, '..');
const dom = new JSDOM(fs.readFileSync(path.join(root, 'studio/index.html'), 'utf8'), { url: 'http://127.0.0.1:8123/studio/', pretendToBeVisual: true });
global.document = dom.window.document; global.window = dom.window; global.Option = dom.window.Option;
global.location = dom.window.location; global.history = dom.window.history; global.localStorage = dom.window.localStorage;

(async () => {
  const { StudioApp } = await import(pathToFileURL(path.join(root, 'studio/studio.js')).href);
  const projectId = 'coherence-project', storeId = 'coherence-store';
  const project = { id: projectId, workflow: 'objects-v1', protocolVersion: 1, title: '雨巷试用' };
  const snapshot = { projectId, publicationRevision: 0, kind: 'CONCEPT', workflow: 'objects-v1', catalog: { objects: [] }, document: { objects: [] } };
  const planning = { id: 'coherence-proposal', projectId, workflow: 'objects-v1', status: 'PLANNING', revision: 2, publicationRevision: 0, visualReferences: [] };
  const ready = { ...planning, status: 'READY', reviewedPlanRef: 'coherence-plan-r2', summary: '速度300，保留两种重置。' };
  const view = (proposal, sequence) => ({ schemaVersion: 'studio.project-view.v1', storeId, projectId,
    projects: [project], proposals: [proposal], packets: [], jobs: [], candidates: [], previews: [], snapshot,
    phase: 'discussion', step: proposal.status === 'READY' ? 'proposal_review' : 'planning', throughSequence: sequence, allowedActions: ['proposal.revise'] });
  const app = new StudioApp({ documentImpl: document });
  app.projectId = projectId; app.protocolVersion = 1; app.handshake = { storeId }; app.workflow = 'objects-v1';
  app.manager = { projects: [project] }; app.workspace = view(planning, 10); app.projectView = app.workspace;
  app.snapshot = snapshot; app.proposal = planning; app.draftKey = app.makeDraftKey(snapshot);
  app.loadReviewedPlan = async () => null;
  let reads = 0;
  app.request = async () => structuredClone(view(++reads === 1 ? planning : ready, reads + 10));
  app.renderProposal();
  document.querySelector('#reviewed').checked = true;
  const failures = [];
  const check = (name, run) => { try { run(); } catch (error) { failures.push(`${name}: ${error.message}`); } };
  assert.equal(await app.refresh({ announce: false }), true);
  assert.equal(reads, 2, 'the status read and workbench read straddle planner completion');
  check('latest view reaches proposal card', () => {
    assert.equal(app.proposal.status, 'READY');
    assert.equal(document.querySelector('#proposal-status').textContent, '方案待确认');
    assert.equal(document.querySelector('#freeze-area').classList.contains('hidden'), false);
    assert.equal(document.querySelector('#reviewed').checked, false, 'the new plan requires fresh review');
    assert.equal(app.eventSequence, 12);
  });
  app.proposal = structuredClone(ready);
  document.querySelector('#reviewed').checked = true;
  app.applyProjectView(structuredClone(view(ready, 13)));
  assert.equal(document.querySelector('#reviewed').checked, true, 'an unchanged view does not reset review');
  const selected = app.proposal;
  app.applyProjectView({ ...view({ ...ready, projectId: 'other-project', status: 'FAILED' }, 14), projectId: 'other-project' });
  assert.equal(app.proposal, selected, 'another project cannot replace the selected proposal');
  app.applyProjectView(view({ ...planning, revision: 1 }, 15));
  assert.equal(app.proposal, selected, 'a lower revision cannot replace the selected proposal');
  app.applyProjectView(view({ ...ready, id: 'another-proposal', status: 'FAILED' }, 16));
  assert.equal(app.proposal, selected, 'view refreshes do not select another proposal');

  app.proposalInputs = { earlier: { 1: { questions: {}, questionPrompts: {}, readySupplement: '', visualReferences: [{ assetId: 'old-image', intent: '原用途' }] } } };
  const before = structuredClone(app.proposalInputs);
  const references = [{ assetId: 'rain-image', intent: '只参考冷暖配色', preserve: '保留程序图形', unknown: '纹理不约束' }];
  app.proposal = { ...ready, visualReferences: references };
  app.renderProposal(); app.renderProposal();
  app.request = async () => ({ projectId, source: { proposalId: ready.id, proposalRevision: ready.revision, feedbackId: 'initial', contextVersion: 'coherence-context' },
    materials: [], promptHeader: '', instructionLabel: '', promptLimit: 32000 });
  await app.openVisualPlanning();
  check('rendering preserves the reviewed draft', () => {
    assert.deepEqual(app.proposalInputs, before, 'opening a reference editor must not create unsaved revision records');
    assert.equal(app.sameReviewedDraft({ proposalInputs: before }, { proposalInputs: app.proposalInputs }), true);
  });
  let saves = 0;
  app.persistProposalInputs = () => { saves++; };
  const intent = document.querySelector('[aria-label="本轮参考 采纳用途"]');
  assert.equal(intent.value, references[0].intent);
  intent.value = '仅参考黄色轮廓，保持运行程序图形';
  intent.dispatchEvent(new dom.window.Event('input', { bubbles: true }));
  assert.equal(saves, 1, 'an actual edit still persists the revision input');
  assert.equal(app.proposalInputs[ready.id][2].visualReferences[0].intent, intent.value);
  assert.equal(references[0].intent, '只参考冷暖配色', 'editing a draft never changes the approved proposal');
  assert.equal(app.sameReviewedDraft({ proposalInputs: before }, { proposalInputs: app.proposalInputs }), false, 'an actual reference edit still requires renewed review');
  app.destroy(); dom.window.close();
  assert.deepEqual(failures, []);
  console.log('PASS Studio project-view coherence: completion race, review identity, read-only rendering and explicit reference edits');
})().catch(error => { console.error(error.stack || error); dom.window.close(); process.exitCode = 1; });
