/* Isolated regressions for C2; these checks do not constitute user acceptance. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { pathToFileURL } = require('node:url');
const { JSDOM } = require('jsdom');
const root = path.resolve(__dirname, '..');
const dom = new JSDOM(fs.readFileSync(path.join(root, 'studio/index.html'), 'utf8'), { url: 'http://127.0.0.1:8123/studio/', pretendToBeVisual: true });
for (const key of ['document', 'location', 'history', 'localStorage', 'Option']) global[key] = dom.window[key];
const tick = () => new Promise(resolve => setTimeout(resolve, 0));
const control = label => document.querySelector(`[aria-label="${label}"]`);
const change = (label, value) => { const input = control(label); input.value = value; input.dispatchEvent(new dom.window.Event('change', { bubbles: true })); };

(async () => {
  const { StudioApp } = await import(pathToFileURL(path.join(root, 'studio/studio.js')).href);
  const app = new StudioApp({ documentImpl: document });
  app.projectId = 'cycle-a'; app.workflow = 'objects-v1'; app.protocolVersion = 1;
  app.handshake = { storeId: 'cycle-store' };
  app.manager = { storeId: 'cycle-store', projects: [{ id: app.projectId, protocolVersion: 1, workflow: 'objects-v1' }] };
  app.workspace = { storeId: 'cycle-store', projects: app.manager.projects, jobs: [] };
  app.sessionPreferences = { revision: 0, roles: {
    planner: { modelKey: 'sol', effort: 'low', limits: { maxDurationSeconds: 420, softTotalTokens: null } },
    producer: { modelKey: 'sol', effort: 'low', limits: { maxDurationSeconds: 1800, softTotalTokens: null } },
  } };
  app.sessionCatalog = { available: true, models: [
    { modelKey: 'sol', supportedReasoningEfforts: ['low', 'high'], defaultReasoningEffort: 'low' },
    { modelKey: 'luna', supportedReasoningEfforts: ['low', 'max'], defaultReasoningEffort: 'low' },
  ] };
  app.notify = () => {};
  app.renderSessionSettings();
  change('producer 模型', 'luna'); change('producer 推理档位', 'max');
  const calls = [], releases = [];
  app.sendCommand = (type, payload, options) => new Promise(resolve => {
    calls.push({ type, payload: structuredClone(payload), options });
    releases.push(() => {
      const preferences = structuredClone(app.sessionPreferences);
      preferences.revision++; preferences.roles[payload.role] = structuredClone(payload);
      resolve({ preferences });
    });
  });
  const first = app.saveSessionPreference('planner', 'sol', 'high', app.sessionPreferences.roles.planner.limits);
  await tick();
  assert.equal(control('producer 模型').value, 'luna', 'saving planner retains unsaved producer choice');
  assert.equal(control('producer 推理档位').value, 'max');
  const second = app.saveSessionPreference('producer', control('producer 模型').value, control('producer 推理档位').value, app.sessionPreferences.roles.producer.limits);
  await tick(); assert.equal(calls.length, 1, 'role updates serialize their shared revision');
  releases.shift()(); await first; await tick();
  assert.equal(calls[1].options.expected.preferencesRevision, 1);
  assert.equal(calls[1].payload.modelKey, 'luna'); assert.equal(calls[1].payload.effort, 'max');
  releases.shift()(); await second;
  assert.equal(app.sessionPreferences.revision, 2); assert.equal(control('producer 推理档位').value, 'max');

  const delayed = app.saveSessionPreference('planner', 'sol', 'low', app.sessionPreferences.roles.planner.limits);
  await tick(); app.projectId = 'cycle-b'; app.selectionGeneration++; app.renderSessionSettings();
  releases.shift()(); await delayed;
  assert.equal(app.sessionPreferences.revision, 2, 'late response does not overwrite another project');
  app.projectId = 'cycle-a'; app.renderSessionSettings();
  assert.equal(document.querySelector('.session-role button').disabled, false);

  const supplement = '  屋檐内逐字显示：这里淋不到雨\n';
  const raw = app.visualRequestText({ userText: '雨巷', userDiscussion: [{ role: 'user', text: supplement }], document: { objects: [] } });
  assert.ok(raw.includes(supplement), 'public frozen projection retains exact supplement');
  const planRoot = document.createElement('div');
  app.renderPlanReviewCard(planRoot, { text: '雨巷', document: { objects: [], requirements: [{ id: 'shelter', text: '进入屋檐后停止淋雨，离开后恢复', verification: 'manual' }] }, tasks: [] });
  assert.ok(planRoot.textContent.includes('进入屋檐后停止淋雨，离开后恢复（试玩核对）'));
  assert.ok(!planRoot.textContent.includes('verification=manual'));

  const reference = { assetId: 'rain', intent: '保持黄雨衣', preserve: '保持中文', unknown: '不确定坐标', targetObjectIds: [] };
  app.snapshot = { projectId: app.projectId, kind: 'REPAIR', publicationRevision: 0, sourceCommit: 'candidate-git', assets: [{ id: 'rain', name: 'rain.png' }], visualReferences: [reference], document: { objects: [] }, catalog: { objects: [] } };
  app.restoreBaselineReferences(app.snapshot);
  assert.deepEqual(app.referencePayload(), [reference]);
  app.persistenceOK = true;
  app.drafts = { get: async () => ({ text: '', assets: [], referenceIntents: {} }) };
  app.loadConceptReferences = () => {};
  await app.restoreConceptDraft(app.projectId, app.selectionGeneration);
  assert.equal(app.assets.length, 0, 'saved explicit empty reference selection overrides inheritance');
  app.restoreBaselineReferences({ ...app.snapshot, projectId: 'another-project' });
  assert.equal(app.assets.length, 0, 'inheritance never crosses project identity');

  const wb = app.legacyWorkbench, exampleRoot = document.createElement('div');
  wb.renderLegacyExamples(exampleRoot, null);
  assert.equal(exampleRoot.childElementCount, 0, 'a generic project does not show unavailable dice examples');

  app.job = { id: 'cycle-job', projectId: app.projectId, status: 'READY_FOR_REVIEW' };
  app.isHistoricalJob = () => false; app.reviewSnapshotMatchesJob = () => true;
  app.renderJob = () => {}; app.loadWorkbench = async () => {};
  app.experienceDecisions = { 'note-a': 'needs_followup' };
  app.experienceDecisionReasons = { 'note-a': '灰屏仍未解决' };
  let rejection;
  app.sendCommand = async (type, payload) => { rejection = { type, payload }; return { job: { ...app.job, status: 'REJECTED' } }; };
  await app.decideCandidate('reject', 'candidate-git', 'candidate', [{ feedbackId: 'note-a' }, { feedbackId: 'not-tried' }]);
  assert.equal(rejection.type, 'candidate.reject');
  assert.deepEqual(rejection.payload.experienceDecisions, [{ feedbackId: 'note-a', status: 'needs_followup', reason: '灰屏仍未解决' }]);

  wb.reportSessionSequence = 1; wb.reportSubmissionSequence = 1; wb.reportFingerprint = 'new-empty-draft';
  wb.submissionOutcome = { status: 'submitted', signature: 'previous-draft', projectId: app.projectId, publicationRevision: 0, sourceCommit: 'candidate-git', dialogSequence: 1, sequence: 1 };
  wb.renderSubmissionStatus();
  assert.equal(document.querySelector('#workbench-submission-status').dataset.status, 'previous');
  assert.ok(document.querySelector('#workbench-submission-status').textContent.includes('当前草稿尚未提交'));
  wb.stopPreview(); dom.window.close();
  console.log('PASS C2 regressions: deferred role settings, frozen supplement, references, truthful validation, rejection decisions, receipt identity, relevant examples');
})().catch(error => { console.error(error.stack || error); dom.window.close(); process.exitCode = 1; });
