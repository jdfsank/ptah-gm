#!/usr/bin/env node
/* Focused Studio lifecycle QA with a mock transport. No production decisions are submitted. */
const fs = require('node:fs');
const path = require('node:path');
const { pathToFileURL } = require('node:url');
let JSDOM;
try { ({ JSDOM } = require('jsdom')); }
catch { console.log('SKIP studio DOM QA: jsdom is not installed.'); process.exit(0); }

const root = path.resolve(__dirname, '..');
const dom = new JSDOM(fs.readFileSync(path.join(root, 'studio/index.html'), 'utf8'), { url: 'http://127.0.0.1:8123/studio/', pretendToBeVisual: true });
global.FormData = dom.window.FormData; global.Option = dom.window.Option;
global.HTMLElement = dom.window.HTMLElement;
global.confirm = () => { throw new Error('QA must not impersonate candidate approval.'); };
const calls = [];
const projects = [{ id: 'old-project', title: '此前项目' }, { id: 'project-a', title: '项目 A' }, { id: 'project-b', title: '项目 B' }, { id: 'project-c', title: '项目 C' }];
const capabilities = { interactiveFrontendConfirmation: true, sessionDispatch: true, godotVerification: true, semanticProjection: true };
const pending = {};
const response = data => ({ ok: true, status: 200, text: async () => JSON.stringify(data) });
const projectInfo = id => ({ projects: [projects.find(item => item.id === id)], proposals: [], packets: [], jobs: [], capabilities, storeId: 'store-test', workspaceId: 'workspace-test', testData: true, iterationReady: false });
const workbench = (id, revision = 0, extra = {}) => ({ snapshot: { projectId: id, publicationRevision: revision, workflow: 'objects-v1', kind: revision ? 'MVP' : 'CONCEPT', playable: revision > 0, summary: `快照 ${id}`, ...extra }, capabilities: { fields: {} }, candidates: [], iterationReady: false });
let proposalAfterAnswer;
const routes = {
  'GET /api/session': { token: 'local-token' },
  'GET /api/workspace': () => ({ storeId: 'store-test', workspaceId: 'workspace-test', projects, capabilities, testData: true }),
  'POST /api/projects': { project: { id: 'project-a', title: '项目 A', workflow: 'objects-v1' } },
  'GET /api/projects/project-a/workspace': () => projectInfo('project-a'),
  'GET /api/projects/project-a/workbench': () => workbench('project-a'),
  'POST /api/projects/project-a/concepts': { proposal: { id: 'proposal-a', projectId: 'project-a', revision: 1, publicationRevision: 0, workflow: 'objects-v1', title: '初始想法讨论', text: '用户的原始想法', status: 'PLANNING' } },
  'POST /api/projects/project-a/proposals/proposal-a/answers': () => ({ proposal: proposalAfterAnswer }),
};
const fetchImpl = async (url, init = {}) => {
  const method = init.method || 'GET'; const key = `${method} ${new URL(url, 'http://127.0.0.1:8123').pathname}`;
  calls.push({ key, body: init.body ? JSON.parse(init.body) : null, headers: init.headers });
  if (init.headers?.['X-Workbench-Token'] && init.headers['X-Workbench-Token'] !== 'local-token') return response({ error: 'bad token' });
  const route = routes[key];
  if (typeof route === 'function') return response(await route());
  if (route) return response(route);
  if (key === 'GET /api/projects/project-b/workspace') return new Promise(resolve => { pending.projectB = resolve; });
  if (key === 'GET /api/projects/project-c/workspace') return response(projectInfo('project-c'));
  if (key === 'GET /api/projects/project-b/workbench') return response(workbench('project-b'));
  if (key === 'GET /api/projects/project-c/workbench') return response(workbench('project-c'));
  return { ok: false, status: 404, text: async () => JSON.stringify({ error: `not found: ${key}` }) };
};
const assert = (value, message) => { if (!value) throw new Error(message); };
const tick = () => new Promise(resolve => setTimeout(resolve, 0));

(async () => {
  const { StudioApp } = await import(pathToFileURL(path.join(root, 'studio/studio.js')).href);
  global.document = dom.window.document; global.location = dom.window.location; global.history = dom.window.history;
  const app = new StudioApp({ fetchImpl, documentImpl: dom.window.document, timers: globalThis });
  const drafts = new Map();
  app.drafts = { open: async () => ({}), get: async key => drafts.get(key) || null, put: async item => { drafts.set(item.key, item); return item; }, delete: async key => drafts.delete(key) };
  await app.start();
  assert(!document.querySelector('#project-manager').classList.contains('hidden'), 'startup should land on project management');
  assert(document.querySelector('#project-view').classList.contains('hidden'), 'startup should not open a prior project or proposal automatically');
  assert(!calls.some(call => call.key.includes('/old-project/')), 'startup must not read a prior project workspace');

  document.querySelector('#new-project-title').value = '项目 A';
  document.querySelector('#new-project-form').dispatchEvent(new dom.window.Event('submit', { bubbles: true, cancelable: true }));
  await tick(); await tick(); await tick();
  assert(calls.some(call => call.key === 'POST /api/projects'), 'named project creation should precede concept submission');
  assert(app.projectId === 'project-a' && !document.querySelector('#project-view').classList.contains('hidden'), 'new project should open its isolated page');
  assert(!document.querySelector('#concept-form').closest('.panel').classList.contains('hidden'), 'fresh project should show only the initial concept step');

  document.querySelector('#concept').value = '用户的原始想法';
  document.querySelector('#concept').dispatchEvent(new dom.window.Event('input', { bubbles: true }));
  document.querySelector('#concept-form').dispatchEvent(new dom.window.Event('submit', { bubbles: true, cancelable: true }));
  await tick(); await tick();
  assert(calls.some(call => call.key === 'POST /api/projects/project-a/concepts' && call.headers['X-Workbench-Token'] === 'local-token'), 'concept request must be scoped to project A');
  assert(document.querySelector('#proposal-title').textContent === '初始想法讨论', 'planning must not be presented as an already-generated proposal');
  assert(document.querySelector('#proposal-content').textContent.includes('用户原始想法'), 'user concept must have an explicit role label');
  assert(document.querySelector('#proposal-content').textContent.includes('不会显示方案'), 'future proposal content must stay hidden during planning');
  assert(document.querySelector('#workflow-status-copy').textContent.includes('AI 策划'), 'top status should name the current planning actor');

  app.proposal = { id: 'proposal-a', projectId: 'project-a', revision: 1, publicationRevision: 0, workflow: 'objects-v1', title: '收集玩法', text: '用户的原始想法', status: 'NEEDS_CLARIFICATION', questions: [{ id: 'goal', prompt: '目标数量？', type: 'number', required: true }] };
  app.renderProposal();
  assert(!document.querySelector('#answers-form').classList.contains('hidden'), 'planner questions should appear only after the planner returns them');
  document.querySelector('#questions input').value = '5';
  proposalAfterAnswer = { ...app.proposal, revision: 2, status: 'READY', questions: [], aiSummary: 'AI 策划形成的 MVP 方案摘要', document: { summary: 'AI 策划形成的 MVP 方案摘要', objects: [] } };
  await app.answerQuestions();
  assert(calls.some(call => call.key === 'POST /api/projects/project-a/proposals/proposal-a/answers'), 'answers must stay project scoped');
  assert(document.querySelector('#proposal-content').textContent.includes('AI 策划反馈'), 'AI proposal output must be explicitly attributed');
  assert(document.querySelector('#workflow-status-copy').textContent.includes('审阅并确认制作范围'), 'READY status should ask the user to review the proposal');
  assert(document.querySelector('#freeze').disabled, 'proposal must not freeze without a human review action');

  app.job = { id: 'job-a', projectId: 'project-a', proposalId: 'proposal-a', status: 'RUNNING' }; app.renderJob();
  assert(document.querySelector('#workflow-status-copy').textContent.includes('AI 正在制作'), 'production status should identify the AI producer');
  app.job = { id: 'job-a', projectId: 'project-a', proposalId: 'proposal-a', status: 'VERIFYING' }; app.renderJob();
  assert(document.querySelector('#workflow-status-copy').textContent.includes('后端验证'), 'verification status should identify the backend');
  app.job = { id: 'job-a', projectId: 'project-a', proposalId: 'proposal-a', status: 'READY_FOR_REVIEW' }; app.renderJob();
  assert(document.querySelector('#workflow-status-copy').textContent.includes('等待用户反馈'), 'candidate review must be attributed to the user');

  app.job = null; app.proposal = null;
  app.workspace.iterationReady = true; app.workspace.iterationReadyTestOnly = true;
  app.snapshot = { projectId: 'project-a', publicationRevision: 1, workflow: 'objects-v1', kind: 'MVP', playable: true, objects: [{ id: 'player', name: '玩家', fields: [] }] };
  app.stage = 'initial'; app.renderWorkbench(); app.renderWorkflowStatus();
  assert(document.querySelector('#snapshot-summary').textContent.includes('不代表生产项目'), 'test data must never claim production acceptance');
  const iterationLink = document.querySelector('#snapshot-summary .iteration-link');
  assert(iterationLink, 'backend-gated accepted demo should expose an iteration link');
  assert(document.querySelector('#edit-form').classList.contains('hidden'), 'iteration editor must stay hidden in the initial stage');
  iterationLink.click();
  assert(app.stage === 'iteration' && !document.querySelector('#edit-form').classList.contains('hidden'), 'iteration link should open the separate object workbench');
  assert(document.querySelector('#workflow-status-copy').textContent.includes('迭代'), `top status should name the iteration stage: ${document.querySelector('#workflow-status-copy').textContent}`);

  app.job = null; app.proposal = { id: 'iteration-planning', projectId: 'project-a', status: 'PLANNING' }; app.renderWorkflowStatus();
  assert(document.querySelector('#workflow-status-copy').textContent.includes('AI 策划'), 'iteration planning must not be masked by the accepted baseline');
  app.proposal = null; app.job = { id: 'job-iteration', projectId: 'project-a', proposalId: 'proposal-a', status: 'RUNNING' }; app.renderWorkflowStatus();
  assert(document.querySelector('#workflow-status-copy').textContent.includes('AI 正在制作'), 'iteration production must retain its active actor');
  app.job.status = 'VERIFYING'; app.renderWorkflowStatus(); assert(document.querySelector('#workflow-status-copy').textContent.includes('后端验证'), 'iteration verification must remain visible');
  app.job.status = 'READY_FOR_REVIEW'; app.renderWorkflowStatus(); assert(document.querySelector('#workflow-status-copy').textContent.includes('等待用户反馈'), 'iteration review must remain visible');

  let resolveOldWorkbench, resolveProjectBWorkspace;
  routes['GET /api/projects/project-a/workbench'] = () => new Promise(resolve => { resolveOldWorkbench = resolve; });
  const oldWorkbench = app.loadWorkbench('project-a'); await tick();
  routes['GET /api/projects/project-b/workspace'] = () => new Promise(resolve => { resolveProjectBWorkspace = data => resolve(response(data)); });
  const openingB = app.openProject('project-b'); await tick();
  resolveOldWorkbench(response(workbench('project-a', 99))); await oldWorkbench;
  assert(app.projectId === 'project-b' && app.snapshot === null, 'late project A workbench must not mutate state while project B workspace is still loading');
  resolveProjectBWorkspace(projectInfo('project-b')); await openingB;
  routes['GET /api/projects/project-a/workbench'] = () => response(workbench('project-a'));
  routes['GET /api/projects/project-b/workspace'] = () => new Promise(resolve => { pending.projectB = resolve; });

  app.job = null; app.proposal = null; app.activity = '提交 A 的请求';
  const pendingB = app.openProject('project-b'); await tick();
  assert(typeof pending.projectB === 'function', 'project B workspace should be pending');
  const pendingC = app.openProject('project-c'); await pendingC;
  pending.projectB(response(projectInfo('project-b'))); await pendingB;
  assert(app.projectId === 'project-c' && app.snapshot.projectId === 'project-c', 'late project B response must not overwrite project C');
  assert(app.manager.projects.length === projects.length, 'opening a scoped project must preserve the independent global project catalog');
  assert(!document.querySelector('#workflow-status-copy').textContent.includes('提交 A 的请求'), 'project A activity must not leak into project C');

  document.querySelector('#concept').value = '项目 C 的草稿'; document.querySelector('#concept').dispatchEvent(new dom.window.Event('input', { bubbles: true }));
  await app.showProjectManager();
  assert(document.querySelector('#project-view').classList.contains('hidden'), 'returning should show manager home');
  assert(app.manager.projects.length === projects.length, 'returning home should retain all projects, including A and B');
  await app.openProject('project-c'); await tick();
  assert(document.querySelector('#concept').value === '项目 C 的草稿', 'immediate navigation should persist and restore the project-scoped concept draft');
  await app.showProjectManager();
  let finishCreate;
  routes['POST /api/projects'] = () => new Promise(resolve => { finishCreate = () => resolve({ project: { id: 'project-d', title: '延迟创建项目', workflow: 'objects-v1' } }); });
  document.querySelector('#new-project-title').value = '延迟创建项目';
  const delayedCreate = app.createProject(); await tick();
  assert(typeof finishCreate === 'function', 'project creation can remain pending while the user navigates');
  await app.openProject('project-c'); finishCreate(); await delayedCreate;
  assert(app.projectId === 'project-c', 'late project creation does not override a project the user opened afterward');
  assert(app.manager.projects.some(item => item.id === 'project-d'), 'late-created project is still added to the manager catalog');
  app.destroy(); dom.window.close();
  console.log('PASS Studio QA: explicit project home, scoped data, progressive roles and stages, status actors, draft isolation, and stale-response guards');
})().catch(error => { console.error(error.stack || error); process.exitCode = 1; });
