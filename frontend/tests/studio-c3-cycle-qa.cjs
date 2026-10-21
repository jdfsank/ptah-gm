/* C3 regressions at real UI boundaries; isolated checks are not user acceptance. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { pathToFileURL } = require('node:url');
const { JSDOM } = require('jsdom');
const root = path.resolve(__dirname, '..');
const dom = new JSDOM(fs.readFileSync(path.join(root, 'studio/index.html'), 'utf8'), { url: 'http://127.0.0.1:8123/', pretendToBeVisual: true });
delete global.document; delete global.window;
for (const key of ['location', 'history', 'localStorage', 'Option']) global[key] = dom.window[key];
const tick = () => new Promise(resolve => setTimeout(resolve, 0));

(async () => {
  const { StudioApp } = await import(pathToFileURL(path.join(root, 'studio/studio.js')).href);
  global.document = dom.window.document; global.window = dom.window;
  const app = new StudioApp({ documentImpl: document });
  app.projectId = 'cycle-c3'; app.workflow = 'objects-v1'; app.protocolVersion = 1;
  app.handshake = { storeId: 'cycle-store' };
  app.manager = { projects: [{ id: app.projectId, protocolVersion: 1, workflow: 'objects-v1' }] };
  app.workspace = { storeId: app.handshake.storeId, projects: app.manager.projects, jobs: [] };
  app.notify = () => {}; app.readiness = { ready: true };

  for (const [body, expected] of [[{ error: { code: 'PROTOCOL_ERROR', message: '参数请求格式错误' } }, '参数请求格式错误'],
    [{ error: '服务忙碌' }, '服务忙碌'], [{ error: { code: 'NO_MESSAGE' } }, '服务返回 400；未提供可读的错误说明。'],
    ['<html>PRIVATE_RAW_GATEWAY_BODY</html>', '服务返回 400；未提供可读的错误说明。']]) {
    app.fetch = async () => ({ ok: false, status: 400, text: async () => typeof body === 'string' ? body : JSON.stringify(body) });
    await assert.rejects(app.request('/probe'), error => error.message === expected && error.status === 400 && !error.message.includes('[object Object]'));
  }

  app.observations = { attemptId: 'plan-1', taskKind: 'plan', status: 'COMPLETED', lastActivity: {
    summary: 'Native session activity observed.', observedAt: '2026-10-20T10:00:00Z' }, runner: { online: true } };
  app.projectView = { projectId: app.projectId, step: 'proposal_review' };
  app.renderExecutionMonitor(); await tick();
  const monitor = document.getElementById('execution-monitor-content');
  assert.ok(monitor.textContent.includes('完整方案已返回') && !monitor.textContent.includes('策划返回后'));
  assert.ok(monitor.textContent.includes('已观察到原生执行活动') && !monitor.textContent.includes('Native session'));
  monitor.querySelector('details').open = true; app.renderExecutionMonitor(); await tick();
  assert.equal(monitor.querySelector('details').open, true, 'refresh preserves current attempt details');
  app.observations = { ...app.observations, attemptId: 'plan-2' }; app.renderExecutionMonitor(); await tick();
  assert.equal(monitor.querySelector('details').open, false, 'another attempt starts collapsed');
  app.projectView.step = 'accepted'; app.observations.status = 'FAILED'; app.renderExecutionMonitor(); await tick();
  assert.ok(monitor.textContent.includes('策划执行失败') && monitor.textContent.includes('查看执行诊断'));
  app.observations.status = 'COMPLETED';
  app.observations = { ...app.observations, attemptId: 'preview-1', taskKind: 'preview' };
  app.previews = [{ id: 'preview', projectId: app.projectId, attemptId: 'preview-1', status: 'STOPPED' }];
  app.renderExecutionMonitor(); await tick();
  assert.ok(monitor.textContent.includes('本候选预览已停止') && monitor.textContent.includes('预览已停止；可回看'));

  const reference = { assetId: 'rain', intent: '黄雨衣\n与暖光', preserve: '保留中文', unknown: '精确位置未确定', targetObjectIds: [] };
  const baseline = { projectId: app.projectId, workflow: 'objects-v1', kind: 'MVP', publicationRevision: 1,
    sourceCommit: 'accepted-source', assets: [{ id: 'rain', name: 'rain.png' }], visualReferences: [reference],
    document: { objects: [], requirements: [] }, catalog: { objects: [] } };
  app.snapshot = { ...baseline, kind: 'CONCEPT', publicationRevision: 0, sourceCommit: null, assets: [], visualReferences: [] };
  app.persistenceOK = true;
  await app.saveConceptDraft(); // Old empty draft left by the concept session.
  app.request = async () => ({ schemaVersion: 'studio.project-view.v1', storeId: app.handshake.storeId,
    projectId: app.projectId, snapshot: structuredClone(baseline), project: app.manager.projects[0], candidates: [] });
  app.renderWorkbench = () => {}; app.renderCandidates = () => {}; app.restoreDraft = async () => {};
  app.applyProjectView = () => {}; app.legacyWorkbench.applyInitialRoute = () => {};
  app.loadConceptReferences = () => {};
  await app.loadWorkbench(app.projectId);
  assert.deepEqual(app.referencePayload(), [reference]);
  app.assets = []; app.referenceIntents = {};
  await app.restoreConceptDraft(app.projectId, app.selectionGeneration);
  assert.deepEqual(app.referencePayload(), [reference], 'reload retains accepted references and exact adoption text');
  const report = app.legacyWorkbench.reportData();
  assert.deepEqual(report.visualReferences, [reference]);
  const calls = [];
  app.sendCommand = async (type, payload) => {
    calls.push({ type, payload: structuredClone(payload) });
    const error = new Error('Synthetic capture stops before planning'); error.status = 400; throw error;
  };
  await app.submitConcept('', true, null, { reviewedReport: report });
  assert.deepEqual(calls[0].payload.visualReferences, report.visualReferences, 'reviewed references reach the actual command');
  assert.deepEqual(calls[0].payload.assetRefs, ['rain']);
  app.assets = []; app.referenceIntents = {}; await app.saveConceptDraft();
  await app.restoreConceptDraft(app.projectId, app.selectionGeneration);
  assert.deepEqual(app.referencePayload(), [], 'explicit saved cancellation remains empty');

  const reason = '逐字体验理由\n只属于这一候选';
  const card = app.legacyWorkbench.renderResultCard({ itemId: 'note', kind: 'feedback', objectId: null,
    originalText: '修改完成文案', userAcceptance: 'resolved', experienceDecision: { status: 'resolved', reason },
    proposalId: 'old-plan', proposalRevision: 2, jobId: 'old-job', candidateId: 'old-candidate' });
  assert.ok(card.textContent.includes('用户认可：已解决') && card.textContent.includes(reason));
  app.snapshot = baseline;
  app.job = { id: 'old-job', projectId: app.projectId, status: 'PUBLISHED', experienceDecisions: [{ feedbackId: 'note', status: 'resolved', reason }],
    candidate: { id: 'old-candidate', projectId: app.projectId, jobId: 'old-job', candidateCommit: 'old-source',
      experienceFeedback: [{ feedbackId: 'note', objectId: 'hud', message: '修改完成文案', category: 'general' }] } };
  app.isHistoricalJob = () => true;
  app.renderCandidateVisual = () => {};
  app.renderJob();
  assert.ok(document.getElementById('candidate-area').textContent.includes(reason));
  assert.ok(document.getElementById('candidate-area').textContent.includes('已解决'));
  app.destroy(); dom.window.close();
  console.log('PASS C3 regressions: structured errors, terminal progress, scoped expansion, reference reload and command integrity, exact historical reasons');
})().catch(error => { console.error(error.stack || error); dom.window.close(); process.exitCode = 1; });
