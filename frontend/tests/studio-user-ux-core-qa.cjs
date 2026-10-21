#!/usr/bin/env node
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { pathToFileURL } = require('node:url');
const { JSDOM } = require('jsdom');

const root = path.resolve(__dirname, '..');
const dom = new JSDOM(fs.readFileSync(path.join(root, 'studio/index.html'), 'utf8'), {
  url: 'http://127.0.0.1:8123/studio/?project=project-a&stage=iteration', pretendToBeVisual: true,
});
global.FormData = dom.window.FormData;
global.Option = dom.window.Option;
global.localStorage = dom.window.localStorage;
global.location = dom.window.location;
global.history = dom.window.history;
global.document = dom.window.document;

const ok = value => ({ ok: true, status: 200, text: async () => JSON.stringify(value) });
const tick = () => new Promise(resolve => setTimeout(resolve, 0));
const projectA = { id: 'project-a', title: '项目 A', protocolVersion: 1 };
const projectB = { id: 'project-b', title: '项目 B', protocolVersion: 1 };
const receiptFor = (command, status = 'accepted') => ({
  schemaVersion: 'studio.message.v1', kind: 'receipt', type: command.type,
  storeId: command.storeId, projectId: command.projectId, commandId: command.commandId, status,
  ...(status === 'accepted' ? { resource: { kind: 'proposal', id: 'proposal-' + command.projectId }, result: { proposal: { id: 'proposal-' + command.projectId, projectId: command.projectId, revision: 1, status: 'NEEDS_CLARIFICATION' } } }
    : { error: { message: '此修订已过期' } }),
});

(async () => {
  const { StudioApp } = await import(pathToFileURL(path.join(root, 'studio/studio.js')).href);
  const appFor = fetchImpl => {
    const app = new StudioApp({ fetchImpl, documentImpl: dom.window.document, timers: globalThis });
    app.protocolVersion = 1;
    app.handshake = { schemaVersion: 'studio.message.v1', kind: 'handshake', storeId: 'user-ux-store', serviceInstanceId: 'user-ux-service', writeToken: 'user-ux-token', capabilities: [] };
    app.token = 'user-ux-token';
    app.manager = { projects: [projectA, projectB] };
    app.projectId = projectA.id;
    app.projectView = { projectId: projectA.id, allowedActions: ['iteration.submit'] };
    app.snapshot = { projectId: projectA.id, publicationRevision: 3, sourceCommit: 'git-user-ux-base', workflow: 'general-v1' };
    app.workflow = 'general-v1';
    app.readiness = { ready: true, missing: [] };
    return app;
  };

  // A valid explicit rejection is definitive; a mismatched receipt identity stays unknown.
  localStorage.clear();
  const rejectionBodies = [];
  const rejected = appFor(async (url, options) => {
    const command = JSON.parse(options.body); rejectionBodies.push(command);
    return ok(receiptFor(command, 'rejected'));
  });
  await assert.rejects(rejected.sendCommand('iteration.submit', { text: '拒绝也需要可核对' }, { projectId: projectA.id }), error => {
    assert.equal(error.commandOutcome.status, 'rejected');
    assert.equal(error.commandOutcome.commandId, rejectionBodies[0].commandId);
    assert.equal(error.commandOutcome.receipt.commandId, rejectionBodies[0].commandId);
    return /此修订已过期/.test(error.message);
  });
  assert.equal(localStorage.getItem(`ptah-pending:user-ux-store:${projectA.id}:iteration.submit`), null, 'a valid rejection clears the resolved pending command');
  rejected.destroy();

  localStorage.clear();
  const wrongIdentityBodies = [];
  const wrongIdentity = appFor(async (_url, options) => {
    const command = JSON.parse(options.body); wrongIdentityBodies.push(command);
    return ok({ ...receiptFor(command), commandId: 'command-from-another-request' });
  });
  await assert.rejects(wrongIdentity.sendCommand('iteration.submit', { text: '身份错配' }, { projectId: projectA.id }), error => {
    assert.equal(error.commandOutcome.status, 'unknown');
    assert.equal(error.commandOutcome.commandId, wrongIdentityBodies[0].commandId);
    return /身份不匹配/.test(error.message);
  });
  assert.equal(JSON.parse(localStorage.getItem(`ptah-pending:user-ux-store:${projectA.id}:iteration.submit`)).envelope.commandId, wrongIdentityBodies[0].commandId, 'a receipt with the wrong identity does not discard the pending request');
  wrongIdentity.destroy();

  // A negative lookup replays the saved envelope byte-for-byte at the protocol level.
  localStorage.clear();
  let firstPost = true;
  const replayBodies = [];
  const replayApp = appFor(async (url, options = {}) => {
    const pathname = new URL(url, 'http://127.0.0.1').pathname;
    if (options.method === 'POST') {
      const command = JSON.parse(options.body); replayBodies.push(command);
      if (firstPost) { firstPost = false; throw new Error('connection lost after send'); }
      return ok(receiptFor(command));
    }
    const commandId = pathname.split('/').at(-1);
    return ok({ schemaVersion: 'studio.message.v1', kind: 'command_lookup', storeId: 'user-ux-store', projectId: projectA.id, commandId, known: false, receipt: null });
  });
  await assert.rejects(replayApp.sendCommand('iteration.submit', { text: '只发送此原文' }, { projectId: projectA.id }), error => error.commandOutcome.status === 'unknown');
  const pendingBeforeReplay = JSON.parse(localStorage.getItem(`ptah-pending:user-ux-store:${projectA.id}:iteration.submit`));
  const replayOutcome = await replayApp.reconcilePendingCommand('iteration.submit', projectA.id);
  assert.equal(replayOutcome.status, 'submitted');
  assert.equal(replayOutcome.commandId, pendingBeforeReplay.envelope.commandId);
  assert.deepEqual(replayBodies[1], pendingBeforeReplay.envelope, 'the not-known path posts the same persisted command ID, expected context, and payload');
  assert.equal(localStorage.getItem(`ptah-pending:user-ux-store:${projectA.id}:iteration.submit`), null);
  replayApp.destroy();

  const acceptedResultFor = (app, projectId, proposalId = `proposal-${projectId}`) => {
    const proposal = { id: proposalId, projectId, revision: 1, status: 'NEEDS_CLARIFICATION' };
    const result = { proposal };
    Object.defineProperty(result, '__commandOutcome', { configurable: true, value: app.submissionOutcome('submitted', { type: 'iteration.submit', projectId, commandId: 'accepted-command', proposalId, reason: '服务已确认接收。' }) });
    return result;
  };
  const configureSubmissionUi = app => {
    app.renderWorkflowStatus = () => {};
    app.renderProposal = () => {};
    app.startProposalPolling = () => {};
    app.saveDraft = async () => true;
    dom.window.document.querySelector('#edit-text').value = '本轮初始请求';
  };

  // A local render failure after an accepted receipt must keep the submitted outcome and proposal identity.
  localStorage.clear();
  const renderFailureApp = appFor(async () => ok({}));
  configureSubmissionUi(renderFailureApp);
  renderFailureApp.sendCommand = async () => acceptedResultFor(renderFailureApp, projectA.id, 'proposal-render-failure');
  renderFailureApp.renderProposal = () => { throw new Error('local proposal view failed'); };
  const renderFailureOutcome = await renderFailureApp.submitIteration();
  assert.equal(renderFailureOutcome.status, 'submitted');
  assert.equal(renderFailureOutcome.proposalId, 'proposal-render-failure');
  assert.match(renderFailureOutcome.reason, /本地草稿清理或页面更新失败：local proposal view failed/);
  assert.equal(renderFailureApp.proposal.id, 'proposal-render-failure', 'the accepted proposal remains available after rendering fails');
  renderFailureApp.destroy();

  // Edits during an in-flight request survive its receipt, and a second submit does not dispatch again.
  localStorage.clear();
  let dispatchCount = 0, releaseSubmission;
  const submissionGate = new Promise(resolve => { releaseSubmission = resolve; });
  const editsApp = appFor(async () => ok({}));
  configureSubmissionUi(editsApp);
  editsApp.sendCommand = async () => { dispatchCount++; await submissionGate; return acceptedResultFor(editsApp, projectA.id); };
  const firstSubmission = editsApp.submitIteration();
  await tick();
  const duplicateOutcome = await editsApp.submitIteration();
  assert.equal(duplicateOutcome.status, 'blocked');
  assert.equal(duplicateOutcome.commandId, null, 'a duplicate click does not invent a second command identity');
  assert.equal(dispatchCount, 1, 'a duplicate click does not dispatch another request');
  const editor = dom.window.document.querySelector('#edit-text');
  editor.value = '提交期间新写的下一轮请求';
  releaseSubmission();
  const acceptedWithEdits = await firstSubmission;
  assert.equal(acceptedWithEdits.status, 'submitted');
  assert.equal(acceptedWithEdits.hasPostSubmitEdits, true);
  assert.equal(editor.value, '提交期间新写的下一轮请求', 'the in-flight receipt does not clear later user edits');
  editsApp.destroy();

  // An active job for this project blocks locally, preserving the draft and review identities.
  localStorage.clear();
  const reviewCandidateApp = appFor(async () => ok({}));
  configureSubmissionUi(reviewCandidateApp);
  const reviewDraft = '保留这条尚未提交的迭代草稿';
  dom.window.document.querySelector('#edit-text').value = reviewDraft;
  reviewCandidateApp.projectView.job = {
    id: 'job-project-a-review', projectId: projectA.id, status: 'READY_FOR_REVIEW', candidateId: 'candidate-project-a-review',
  };
  let blockedDispatches = 0, blockedRequests = 0;
  reviewCandidateApp.sendCommand = async () => { blockedDispatches++; throw new Error('active job should block before dispatch'); };
  reviewCandidateApp.request = async () => { blockedRequests++; throw new Error('active job should block before request'); };
  const reviewBlocked = await reviewCandidateApp.submitIteration();
  assert.equal(reviewBlocked.status, 'blocked');
  assert.equal(reviewBlocked.jobId, 'job-project-a-review');
  assert.equal(reviewBlocked.candidateId, 'candidate-project-a-review');
  assert.match(reviewBlocked.reason, /当前制作记录入口/);
  assert.equal(blockedDispatches, 0, 'a review candidate does not dispatch another iteration');
  assert.equal(blockedRequests, 0, 'a review candidate is blocked before any request');
  assert.equal(dom.window.document.querySelector('#edit-text').value, reviewDraft, 'a local blocker retains the iteration draft');
  assert.equal(reviewCandidateApp.lastSubmissionOutcome, reviewBlocked);
  reviewCandidateApp.destroy();

  // Active work in another project and terminal jobs for this project do not block submission.
  for (const [label, jobs] of [
    ['foreign project', [{ id: 'job-project-b-active', projectId: projectB.id, status: 'RUNNING' }]],
    ['terminal job', [{ id: 'job-project-a-finished', projectId: projectA.id, status: 'PUBLISHED' }]],
  ]) {
    localStorage.clear();
    const nonBlockingApp = appFor(async () => ok({}));
    configureSubmissionUi(nonBlockingApp);
    nonBlockingApp.workspace = { jobs };
    let nonBlockingDispatches = 0;
    nonBlockingApp.sendCommand = async () => { nonBlockingDispatches++; return acceptedResultFor(nonBlockingApp, projectA.id, `proposal-${label.replaceAll(' ', '-')}`); };
    const nonBlockingOutcome = await nonBlockingApp.submitIteration();
    assert.equal(nonBlockingOutcome.status, 'submitted', `${label} jobs do not block an iteration`);
    assert.equal(nonBlockingDispatches, 1, `${label} jobs allow the normal dispatch path`);
    nonBlockingApp.destroy();
  }

  // A response from a prior project context cannot overwrite the project now on screen.
  localStorage.clear();
  let releaseStaleResponse;
  const staleGate = new Promise(resolve => { releaseStaleResponse = resolve; });
  const isolationApp = appFor(async () => ok({}));
  configureSubmissionUi(isolationApp);
  isolationApp.sendCommand = async () => { await staleGate; return acceptedResultFor(isolationApp, projectA.id, 'proposal-from-a'); };
  const projectARequest = isolationApp.submitIteration();
  await tick();
  isolationApp.advanceSelection();
  isolationApp.projectId = projectB.id;
  isolationApp.snapshot = { projectId: projectB.id, publicationRevision: 8, sourceCommit: 'git-project-b', workflow: 'general-v1' };
  isolationApp.proposal = { id: 'proposal-already-on-b', projectId: projectB.id, revision: 4, status: 'NEEDS_CLARIFICATION' };
  releaseStaleResponse();
  const staleOutcome = await projectARequest;
  assert.equal(staleOutcome.status, 'stale');
  assert.equal(staleOutcome.projectId, projectA.id);
  assert.equal(staleOutcome.proposalId, 'proposal-from-a');
  assert.equal(isolationApp.proposal.id, 'proposal-already-on-b', 'a late project A response cannot replace project B state');
  isolationApp.destroy();

  dom.window.close();
  console.log('PASS Studio user UX core QA: rejection and receipt identity, original-envelope replay, accepted-render failure, edit preservation, duplicate submission blocking, and project-switch isolation');
})().catch(error => {
  console.error(error.stack || error);
  dom.window.close();
  process.exitCode = 1;
});
