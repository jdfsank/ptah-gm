#!/usr/bin/env node
const fs = require('node:fs');
const path = require('node:path');
const { pathToFileURL } = require('node:url');
const assert = require('node:assert/strict');
let JSDOM;
try { ({ JSDOM } = require('jsdom')); } catch { console.log('SKIP Studio result context QA: jsdom is not installed.'); process.exit(0); }

const root = path.resolve(__dirname, '..');
const dom = new JSDOM(fs.readFileSync(path.join(root, 'studio/index.html'), 'utf8'), { url: 'http://127.0.0.1:8123/studio/' });
global.document = dom.window.document;
global.location = dom.window.location;
global.history = dom.window.history;
global.localStorage = dom.window.localStorage;

(async () => {
  const { StudioApp } = await import(pathToFileURL(path.join(root, 'studio/studio.js')).href);
  let requests = 0;
  const app = new StudioApp({ fetchImpl: async () => { requests++; return { ok: true, status: 200, text: async () => '{}' }; }, documentImpl: dom.window.document, timers: globalThis });
  const projectId = 'project-result-context';
  const currentFeedback = { feedbackId: 'feedback-current', objectId: 'player', category: '体验', message: '当前方案的新反馈' };
  const historicalFeedback = { feedbackId: 'feedback-old', objectId: 'player', category: '体验', message: '旧方案的历史反馈' };
  const currentProposal = { id: 'proposal-current', projectId, status: 'PLANNING', changeRequest: { feedback: [currentFeedback] } };
  const historicalProposal = { id: 'proposal-old', projectId, packetId: 'packet-old', status: 'FROZEN', changeRequest: { feedback: [historicalFeedback] } };
  const historicalJob = {
    id: 'job-old', projectId, proposalId: 'proposal-old', packetId: 'packet-old', status: 'READY_FOR_REVIEW',
    verification: { status: 'PASS', runId: 'run-old', requirements: [{ status: 'PASS', requirement: '旧轮验证' }] },
    candidate: { id: 'candidate-old', candidateCommit: 'commit-old', previewAvailable: true, verification: { status: 'PASS', runId: 'candidate-run-old' } },
  };

  app.projectId = projectId;
  app.proposal = currentProposal;
  app.packet = null;
  app.snapshot = { id: projectId, projectId, publicationRevision: 4, playable: false };
  app.projectView = { projectId, phase: 'discussion', step: 'planning', job: historicalJob, allowedActions: ['preview.start', 'candidate.accept', 'candidate.reject'] };
  app.workspace = {
    projects: [{ id: projectId, workflow: 'objects-v1' }],
    proposals: [currentProposal, historicalProposal],
    packets: [{ id: 'packet-old', packetId: 'packet-old', projectId, proposalId: 'proposal-old', jobId: historicalJob.id }],
    jobs: [historicalJob],
  };
  app.job = historicalJob;
  app.renderJob();

  assert.equal(document.querySelector('#job-title').textContent, '历史制作记录', 'a prior round stays historical when the current proposal is planning, even if the project view still references that job');
  assert.match(document.querySelector('#job-status').textContent, /^历史 · /);
  assert.match(document.querySelector('#job-message').textContent, /该历史制作轮次/);
  assert.match(document.querySelector('#job-evidence').textContent, /历史制作轮次/);
  assert.match(document.querySelector('#job-evidence').textContent, /历史运行验证：PASS/, 'verification is explicitly labeled as historical');
  assert.match(document.querySelector('#candidate-area h3').textContent, /历史制作候选结果/);
  assert.match(document.querySelector('#candidate-area').textContent, /历史运行验证：PASS/, 'candidate-level verification is also labeled as historical');
  assert.match(document.querySelector('#candidate-area').textContent, /旧方案的历史反馈/, 'historical result may show only its associated proposal feedback');
  assert.doesNotMatch(document.querySelector('#candidate-area').textContent, /当前方案的新反馈/, 'feedback from the current planning proposal is not borrowed by an older candidate');
  assert.equal(document.querySelector('#candidate-area').querySelector('select'), null, 'historical feedback is read-only');
  assert.equal(document.querySelector('#candidate-area').querySelector('textarea'), null, 'historical feedback has no editable decision reason');
  assert.equal([...document.querySelectorAll('#candidate-area button')].some(button => /在 Godot 中运行此候选|接受并发布|接受此测试候选|拒绝此候选/.test(button.textContent)), false, 'historical candidates cannot be run or accepted/rejected from the current review');
  assert.match(document.querySelector('#workflow-status-copy').textContent, /等待策划反馈/, 'a stale ready-for-review job does not override the current planning step');
  const readsBeforeActions = requests;
  await app.previewCandidate(historicalJob.candidate);
  await app.decideCandidate('accept', historicalJob.candidate.candidateCommit, historicalJob.candidate.id);
  assert.equal(requests, readsBeforeActions, 'direct calls cannot launch or decide a historical candidate either');

  // A candidate tied to the active proposal may use that proposal's feedback
  // when the candidate does not carry a separate experienceFeedback list.
  const reviewProposal = { ...currentProposal, status: 'READY' };
  const currentJob = { id: 'job-current', projectId, packetId: 'packet-current', status: 'READY_FOR_REVIEW', candidate: { id: 'candidate-current', candidateCommit: 'commit-current' } };
  app.proposal = reviewProposal;
  app.packet = { id: 'packet-current', packetId: 'packet-current', projectId, proposalId: reviewProposal.id };
  app.projectView = { projectId, job: currentJob, allowedActions: ['candidate.accept', 'candidate.reject'] };
  app.workspace.proposals = [reviewProposal, historicalProposal];
  app.workspace.packets.push(app.packet);
  app.workspace.jobs.push(currentJob);
  app.job = currentJob;
  app.renderJob();
  assert.match(document.querySelector('#candidate-area').textContent, /当前方案的新反馈/, 'current feedback is available when the job and candidate belong to that proposal');
  assert.ok(document.querySelector('#candidate-area select'), 'the current associated round exposes review decisions');

  app.destroy();
  dom.window.close();
  console.log('PASS Studio result context QA: historical candidates keep their round-specific feedback, verification, and read-only status');
})().catch(error => { console.error(error.stack || error); process.exitCode = 1; });
