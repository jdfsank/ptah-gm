#!/usr/bin/env node
/* Legacy object workbench remains usable through the durable iteration command. */
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const { pathToFileURL } = require('node:url');
let JSDOM;
try { ({ JSDOM } = require('jsdom')); }
catch { console.log('SKIP Studio legacy workbench QA: jsdom is unavailable.'); process.exit(0); }

const root = path.resolve(__dirname, '..');
const dom = new JSDOM(fs.readFileSync(path.join(root, 'studio/index.html'), 'utf8'), {
  url: 'http://127.0.0.1:8123/studio/?project=legacy-game&stage=iteration',
  pretendToBeVisual: true,
});
dom.window.HTMLDialogElement.prototype.showModal = function () { this.open = true; };
dom.window.HTMLDialogElement.prototype.close = function () { this.open = false; };
global.document = dom.window.document;
global.Option = dom.window.Option;
global.localStorage = dom.window.localStorage;
global.location = dom.window.location;
global.history = dom.window.history;

const calls = [];
const timerHandles = new Map();
let timerId = 0;
const response = (data, status = 200) => ({ ok: status >= 200 && status < 300, status, text: async () => JSON.stringify(data) });
const storeId = 'legacy-store';
const projectId = 'legacy-game';
const feedback = [
  { feedbackId: 'existing-note', objectId: 'player', message: '保留玩家当前已有意见。', category: 'general' },
  { feedbackId: 'reassigned-note', objectId: 'player', message: '失效意见重新关联到玩家。', category: 'general' },
];
const fetchImpl = async (url, init = {}) => {
  const pathname = new URL(url, 'http://127.0.0.1:8123').pathname;
  const method = init.method || 'GET';
  const body = init.body ? JSON.parse(init.body) : undefined;
  calls.push({ pathname, method, body, headers: init.headers });
  if (pathname === `/api/v1/projects/${projectId}/commands` && method === 'POST') {
    return response({
      schemaVersion: 'studio.message.v1', kind: 'receipt', type: body.type,
      storeId, projectId, commandId: body.commandId, status: 'accepted',
      resource: { kind: 'proposal', id: 'proposal-legacy-iteration' },
      result: { proposal: { id: 'proposal-legacy-iteration', projectId, revision: 1, publicationRevision: 7, status: 'PLANNING', workflow: 'objects-v1' } },
    });
  }
  if (pathname === `/api/projects/${projectId}/jobs/job-legacy/source-changes` && method === 'GET') {
    return response({
      projectId, jobId: 'job-legacy', candidateId: 'candidate-8',
      kind: 'retained_git_diff', baseCommit: 'git-base-7', sourceCommit: 'git-candidate-8', truncated: false,
      changes: [
        { path: 'scripts/player.gd', diff: 'diff -- player: speed += 10', truncated: false },
        { path: 'scripts/hud.gd', diff: 'diff -- hud: update label', truncated: false },
      ],
    });
  }
  return response({ error: `unexpected route ${method} ${pathname}` }, 404);
};

const tick = () => new Promise(resolve => setTimeout(resolve, 0));

(async () => {
  const { StudioApp } = await import(pathToFileURL(path.join(root, 'studio/studio.js')).href);
  const timers = {
    setTimeout(fn) { const id = ++timerId; timerHandles.set(id, fn); return id; },
    clearTimeout(id) { timerHandles.delete(id); },
    setInterval(fn) { const id = ++timerId; timerHandles.set(id, fn); return id; },
    clearInterval(id) { timerHandles.delete(id); },
  };
  const app = new StudioApp({ fetchImpl, documentImpl: dom.window.document, timers });
  const project = { id: projectId, title: '旧项目', workflow: 'objects-v1', publicationRevision: 7 };
  const arena = { id: 'arena', kind: 'scene', name: '主竞技场', relations: [], fields: [], workbench: { role: 'scene', bounds: [1152, 768] } };
  const player = { id: 'player', kind: 'entity', name: '玩家', description: '可控角色', relations: [], sourceBindings: ['scripts/player.gd'], fields: [], workbench: { role: 'instance', sceneId: 'arena', position: [576, 415], lock: 'free' } };
  const environmentPreset = { id: 'environment-default', kind: 'configuration', name: '环境默认参数', relations: [], workbench: { role: 'preset' } };
  const transitionPreset = { id: 'fade-preset', kind: 'configuration', name: '淡入淡出', relations: [], workbench: { role: 'preset' } };
  const transition = { id: 'arena-exit', kind: 'transition', name: '离场连接', relations: [{ type: 'uses_preset', targetId: 'fade-preset' }], workbench: { role: 'transition', sceneId: 'arena', presetId: 'fade-preset' } };
  app.protocolVersion = 1;
  app.handshake = { schemaVersion: 'studio.message.v1', kind: 'handshake', storeId, serviceInstanceId: 'legacy-service', writeToken: 'legacy-token', readable: true, capabilities: ['legacy-iteration-commands'] };
  app.token = 'legacy-token';
  app.manager = { storeId, projects: [project] };
  app.workspace = { storeId, workspaceId: 'local', projects: [project], iterationReady: true, capabilities: { interactiveFrontendConfirmation: true, sessionDispatch: true, godotVerification: true, semanticProjection: true } };
  app.projectId = projectId;
  app.stage = 'iteration';
  app.workflow = 'objects-v1';
  app.snapshot = { projectId, publicationRevision: 7, sourceCommit: 'git-base-7', kind: 'MVP', playable: true, workflow: 'objects-v1', title: '旧项目', catalog: { objects: [arena, player, environmentPreset, transitionPreset, transition] }, document: { objects: [arena, player, environmentPreset, transitionPreset, transition] } };
  app.selectedObjectId = 'player';
  app.projectView = { schemaVersion: 'studio.project-view.v1', storeId, projectId, allowedActions: ['iteration.submit'], proposals: [], packets: [], jobs: [], previews: [] };
  app.readiness = { ready: true, missing: [] };
  app.workbenchResults = [{
    kind: 'feedback', objectId: 'player', originalText: '让玩家移动时反馈更清楚。', workflowStatus: 'PUBLISHED',
    versionDecision: 'published', sourceCommit: 'git-candidate-8', jobId: 'job-legacy', candidateId: 'candidate-8',
    changedSourcePaths: ['scripts/player.gd'], technicalVerification: 'PASS', userAcceptance: 'NOT_PERFORMED',
    linkedTasks: [{ id: 'task-player-motion', title: '调整玩家移动反馈', status: 'COMPLETED' }],
    verificationRequirements: [{ requirement: '玩家能响应方向输入', status: 'PASS' }],
  }];
  app.bind();
  app.renderWorkbench();
  app.targetNotes = {
    deletedTarget: { objectId: 'deleted-object', text: '失效意见重新关联到玩家。', feedbackId: 'reassigned-note' },
    player: { objectId: 'player', text: '保留玩家当前已有意见。', feedbackId: 'existing-note' },
  };
  app.legacyWorkbench.loadCurrentNote();
  app.legacyWorkbench.render();

  assert(app.legacyWorkbench.scenes().some(scene => scene.id === 'arena'), 'scene-role objects are included in the scene list');
  assert.equal(app.legacyWorkbench.roleLabel(arena), '场景', 'scene-role objects receive a scene label');
  assert.equal(document.querySelector('.workbench-coordinate-canvas .workbench-grid-label')?.textContent, '边界 1152, 768 · 单位按来源数据', 'the scene preview uses the mapped world bounds');
  assert.equal(app.legacyWorkbench.roleLabel(environmentPreset), '配置预设', 'general configuration presets do not imply transition use');
  assert.equal(app.legacyWorkbench.roleLabel(transitionPreset), '过渡预设', 'only a preset referenced by a transition is labeled as a transition preset');

  const outcome = document.querySelector('.workbench-result-card');
  assert(outcome?.textContent.includes('候选版本决定：已接受为当前版本'), 'legacy per-item results should show their explicit version decision');
  assert(outcome.textContent.includes('整版决定不代表此项需求已获认可'), 'a published version must not imply per-item completion or user approval');
  assert(outcome.textContent.includes('技术验证：PASS · 用户认可：未进行'), 'technical verification and user acceptance remain separate in readable Chinese');
  assert(outcome.textContent.includes('任务与技术证据'), 'linked tasks and verification requirements should be available in a collapsed section');
  const evidence = outcome.querySelector('.workbench-result-evidence');
  assert(evidence && !evidence.open, 'task and verification evidence stays collapsed until requested');

  const diff = outcome.querySelector('.workbench-result-source-diff');
  assert(diff && !diff.open, 'source diffs load only when expanded');
  assert(!calls.some(call => call.pathname.endsWith('/source-changes')), 'the source-diff endpoint is lazy');
  diff.open = true; diff.dispatchEvent(new dom.window.Event('toggle'));
  await tick(); await tick();
  assert(outcome.textContent.includes('diff -- player: speed += 10'), 'the relevant bound source change is shown');
  assert(!outcome.textContent.includes('diff -- hud: update label'), 'unrelated source changes are omitted when bound-path evidence exists');

  const originalRequest = app.request;
  const sourceResult = app.workbenchResults[0];
  const exactDiff = { projectId, jobId: sourceResult.jobId, candidateId: sourceResult.candidateId,
    kind: 'retained_git_diff', baseKind: 'production_input', baseCommit: 'git-input-8',
    sourceCommit: sourceResult.sourceCommit, changes: [], truncated: false };
  try {
    for (const key of ['projectId', 'jobId', 'candidateId', 'sourceCommit']) {
      app.request = async () => ({ ...exactDiff, [key]: 'another-identity' });
      await assert.rejects(app.legacyWorkbench.loadResultSourceDiff(sourceResult, document.createElement('div')), /不匹配/,
        `a diff from another ${key} must not become evidence for this result`);
    }
    app.request = async () => exactDiff;
    const inputDiff = document.createElement('div');
    await app.legacyWorkbench.loadResultSourceDiff(sourceResult, inputDiff);
    assert.match(inputDiff.textContent, /Git 制作输入 git-input-8/);
  } finally { app.request = originalRequest; }

  const orphan = document.querySelector('.workbench-orphan-row');
  assert(orphan, 'a stale feedback target is kept visible for explicit reassociation');
  orphan.querySelector('select').value = 'player';
  orphan.querySelector('button').click();
  assert.equal(app.targetNotes.player.text, '保留玩家当前已有意见。', 'reassociation must preserve the target object\'s existing feedback');
  const reassigned = Object.entries(app.targetNotes).find(([, note]) => note.feedbackId === 'reassigned-note');
  assert(reassigned, 'reassociated feedback retains a separate stable identity');
  assert.equal(reassigned[1].objectId, 'player');
  assert.equal(reassigned[1].text, '失效意见重新关联到玩家。');

  app.legacyWorkbench.openReport();
  const report = document.querySelector('#workbench-report-content').textContent;
  assert(report.includes('保留玩家当前已有意见。') && report.includes('失效意见重新关联到玩家。'), 'the unified report preview contains both distinct target opinions');
  assert.equal(document.querySelector('#workbench-report-confirm').disabled, false, 'a nonempty opinion report can be confirmed');
  await app.legacyWorkbench.confirmReport();
  const submitted = calls.find(call => call.pathname === `/api/v1/projects/${projectId}/commands` && call.method === 'POST');
  assert(submitted, `legacy iteration submits through the durable command endpoint when the capability is advertised; notice=${document.querySelector('#notice').textContent}; calls=${JSON.stringify(calls.map(call => [call.method, call.pathname]))}`);
  assert.equal(submitted.body.type, 'iteration.submit');
  assert.equal(submitted.body.expected.preferencesRevision, 0, 'legacy iteration includes the required compatibility revision without implying settings were applied');
  assert.equal(submitted.body.expected.publicationRevision, 7);
  assert.equal(submitted.body.expected.sourceCommit, 'git-base-7');
  assert.deepEqual(submitted.body.payload.feedback.map(item => [item.feedbackId, item.objectId, item.message]), feedback.map(item => [item.feedbackId, item.objectId, item.message]));
  assert.equal(submitted.body.payload.text, '', 'object-scoped feedback is sent in the structured feedback payload');

  app.destroy(); dom.window.close();
  console.log('PASS Studio legacy workbench QA: result evidence, exact lazy diff, safe feedback reassociation, report preview, and durable iteration command');
})().catch(error => { console.error(error.stack || error); process.exitCode = 1; dom.window.close(); });
