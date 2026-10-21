/* Regression evidence for trial findings; synthetic state is not user acceptance. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { pathToFileURL } = require('node:url');
const { JSDOM } = require('jsdom');
const root = path.resolve(__dirname, '..');
const dom = new JSDOM(fs.readFileSync(path.join(root, 'studio/index.html'), 'utf8'), { url: 'http://127.0.0.1:8123/studio/', pretendToBeVisual: true });
global.document = dom.window.document; global.window = dom.window;
global.location = dom.window.location; global.history = dom.window.history; global.localStorage = dom.window.localStorage;
const tick = () => new Promise(resolve => setTimeout(resolve, 0));

(async () => {
  const { StudioApp } = await import(pathToFileURL(path.join(root, 'studio/studio.js')).href);
  const { releaseVisuals } = await import(pathToFileURL(path.join(root, 'studio/visual-feedback.js')).href);
  const app = new StudioApp({ documentImpl: document });
  app.projectId = 'trial-project'; app.workflow = 'objects-v1';
  app.workspace = { projects: [{ id: app.projectId }], capabilities: {} };
  const feedback = [
    { feedbackId: 'move', objectId: 'movement', category: 'general', message: '  从240提高到300；保持松键停止。\n不加积分。' },
    { feedbackId: 'look', objectId: 'player', category: 'visual', message: '<雨衣> 保持黄色轮廓和中文。' },
  ];
  const proposal = { id: 'trial-proposal', projectId: app.projectId, revision: 1, text: '', status: 'READY',
    changeRequest: { targetObjectIds: ['movement', 'player'], feedback }, document: { objects: [{ id: 'movement', name: '左右移动' }, { id: 'player', name: '黄色雨衣角色' }] },
    feedbackDecisions: [{ feedbackId: 'move', status: 'adopted', reason: '更新速度' }] };
  const packet = { id: 'trial-packet', projectId: app.projectId, proposalId: proposal.id, proposalRevision: 1,
    userText: '', approvedProposal: proposal, feedback, changeRequest: proposal.changeRequest };
  const candidate = { id: 'trial-candidate', candidateCommit: 'candidate-git', packetId: packet.id };
  app.proposal = proposal; app.packet = packet;
  app.job = { id: 'trial-job', projectId: app.projectId, status: 'READY_FOR_REVIEW', packetId: packet.id, attemptId: 'produce-attempt', candidate };
  const planRoot = document.createElement('div'); document.body.append(planRoot);
  app.renderPlanReviewCard(planRoot, proposal);
  document.querySelector('#freeze-area').append(Object.assign(document.createElement('section'), { id: 'packet-preview' }));
  app.renderFrozenPacket();
  app.renderCandidateCaptures = () => {};
  const candidateRoot = document.createElement('div'); document.body.append(candidateRoot);
  app.renderCandidateVisual(candidateRoot, candidate);
  for (const container of [planRoot, document.querySelector('#packet-preview'), candidateRoot]) {
    assert.ok(container.querySelector('.visual-raw').textContent.includes(feedback[0].message));
    assert.ok(container.querySelector('.visual-raw').textContent.includes(feedback[1].message));
    assert.ok(!container.textContent.includes('此轮没有补充文字'));
    assert.ok(container.querySelector('.visual-raw').textContent.includes('左右移动（movement）'));
    assert.equal(container.querySelector('.visual-raw').querySelector('雨衣'), null, 'feedback remains escaped text');
  }
  app.proposal = { ...proposal, revision: 2, text: '后来草稿' };
  assert.ok(!app.visualRequestText(packet).includes('后来草稿'), 'frozen feedback never reads a later draft');
  assert.equal(app.visualRequestText({ userText: '  原文\n保持空格  ' }), '  原文\n保持空格  ');
  const decisionRoot = document.createElement('div'); app.renderObjectsProposal(decisionRoot, proposal);
  assert.ok(decisionRoot.textContent.includes('已纳入计划') && !decisionRoot.textContent.includes('未说明'));

  const preview = { id: 'current-preview', projectId: app.projectId, attemptId: 'preview-attempt', status: 'STOPPED',
    artifactRef: { projectId: app.projectId, jobId: app.job.id, packetId: packet.id, sourceCommit: candidate.candidateCommit } };
  const oldPreview = { ...preview, id: 'old-preview', attemptId: 'old-preview-attempt', status: 'RUNNING', artifactRef: { ...preview.artifactRef, jobId: 'old-job', sourceCommit: 'old-git' } };
  app.previews = [preview, oldPreview]; app.projectView = { allowedActions: ['preview.stop'] };
  const previewRoot = document.createElement('div'); app.renderPreviewControls(previewRoot);
  assert.ok(previewRoot.querySelector('.preview-history').textContent.includes('old-preview'));
  assert.ok(!previewRoot.querySelector('.preview-history').textContent.includes('current-preview'));
  assert.equal(app.previewMatchesCandidate({ ...preview, artifactRef: { ...preview.artifactRef, sourceCommit: 'wrong-git' } }), false);
  assert.equal(app.previewMatchesCandidate({ ...preview, artifactRef: null }), false);
  let stopped;
  app.stopPreview = async id => { stopped = id; };
  previewRoot.querySelector('.preview-history button').click(); await tick();
  assert.equal(stopped, oldPreview.id, 'other-version active previews retain their own stop control');
  app.observations = { attemptId: preview.attemptId, taskKind: 'preview', status: 'STOPPED' };
  app.renderExecutionMonitor();
  assert.ok(document.querySelector('#execution-monitor-content').textContent.includes('本候选预览'));
  assert.ok(!document.querySelector('#execution-monitor-content').textContent.includes('不匹配'));
  app.observations.attemptId = oldPreview.attemptId; app.renderExecutionMonitor();
  assert.ok(document.querySelector('#execution-monitor-content').textContent.includes('其他候选或版本的预览'));
  app.job.status = 'RUNNING'; app.renderExecutionMonitor();
  assert.ok(document.querySelector('#execution-monitor-content').textContent.includes('不匹配'), 'a past preview cannot replace the active production attempt');

  app.renderWorkbench = () => {}; app.renderWorkflowStages = () => {}; app.renderSessionSettings = () => {}; app.applyReadinessGate = () => {};
  app.applyProjectView({ projectId: app.projectId, jobs: [{ id: app.job.id, status: 'PUBLISHED' }] });
  assert.ok(document.querySelector('#job-list').textContent.includes('已发布'));
  assert.ok(!document.querySelector('#job-list').textContent.includes('等待你审阅'));

  app.proposal = { ...proposal, initializationRequired: false }; app.readiness = { ready: true };
  app.renderProposal(); document.querySelector('#reviewed').checked = true;
  let finishFreeze, frozenCount = 0;
  app.request = async () => { frozenCount++; return new Promise(resolve => { finishFreeze = () => resolve({ packet: { ...packet, operationKind: 'IMPLEMENTATION' } }); }); };
  app.createJob = async () => { app.proposal = { ...app.proposal, status: 'FROZEN' }; };
  const freezing = app.freezeProposal(); await tick();
  assert.equal(document.querySelector('#freeze').textContent, '正在冻结方案…');
  const generation = app.proposalMutationGeneration; await app.freezeProposal();
  assert.equal(frozenCount, 1); assert.equal(app.proposalMutationGeneration, generation, 'repeat activation cannot invalidate the pending freeze');
  finishFreeze(); await freezing;
  assert.equal(app.freezingProposal, null);
  app.proposal = { ...proposal, id: 'new-proposal' }; app.renderProposal();
  assert.equal(document.querySelector('#freeze').textContent, '确认方案并继续');

  const nextSnapshot = { id: app.projectId, projectId: app.projectId, publicationRevision: 2 };
  app.snapshot = nextSnapshot;
  app.pendingRebase = { oldKey: 'old-key', newKey: app.makeDraftKey(nextSnapshot), oldSnapshot: { projectId: app.projectId, publicationRevision: 1 }, nextSnapshot,
    generation: app.workbenchGeneration, persistenceOK: true, draft: { text: '预览的旧稿' } };
  app.drafts = { get: async () => ({ text: '存储中较新的原文', fields: {}, feedback: [] }) };
  document.querySelector('#rebase-dialog').setAttribute('open', '');
  await app.confirmRebase();
  const alert = document.querySelector('#rebase-dialog [role="alert"]');
  assert.ok(alert.textContent.includes('已更新预览，请重新确认'));
  assert.ok(document.querySelector('#rebase-content').textContent.includes('存储中较新的原文'));
  app.renderRebasePreview(app.pendingRebase);
  assert.ok(document.querySelector('#rebase-dialog [role="alert"]').textContent.includes('重新确认'), 'rerender retains the modal-local explanation');
  assert.ok(app.pendingRebase, 'a changed source draft requires explicit confirmation again');
  releaseVisuals(document.body); app.destroy(); dom.window.close();
  console.log('PASS Studio trial feedback: frozen originals, preview identity, decisions, freeze lifecycle and modal notices');
})().catch(error => { console.error(error.stack || error); dom.window.close(); process.exitCode = 1; });
