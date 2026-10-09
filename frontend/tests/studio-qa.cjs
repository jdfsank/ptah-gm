#!/usr/bin/env node
/* DOM contract tests for the independent studio. They use a mock transport and
 * never submit a confirmation to, or claim approval for, a real project. */
const fs = require('node:fs');
const path = require('node:path');
const { pathToFileURL } = require('node:url');
let JSDOM;
try { ({ JSDOM } = require('jsdom')); }
catch { console.log('SKIP studio DOM QA: jsdom is not installed; install the existing frontend devDependencies to run it.'); process.exit(0); }

const root = path.resolve(__dirname, '..');
const dom = new JSDOM(fs.readFileSync(path.join(root, 'studio/index.html'), 'utf8'), { url: 'http://127.0.0.1:8123/', pretendToBeVisual: true });
global.document = dom.window.document;
global.FormData = dom.window.FormData;
global.HTMLElement = dom.window.HTMLElement;
global.confirm = () => { throw new Error('Tests must never impersonate a user decision.'); };
const calls = [];
let resolveProjectB = null;
let resolveLateB = null;
let resolveEarlyC = null;
let resolveLateDraftB = null;
const routes = {
  'GET /api/session': { token: 'test-token', operatorId: 'test-operator' },
  'GET /api/workspace': { workspaceId: 'ws-1', projects: [], jobs: [], testData: true, capabilities: { interactiveFrontendConfirmation: true, sessionDispatch: true, godotVerification: true, semanticProjection: true } },
  'GET /api/projects/project-1/workbench': { snapshot: { projectId: 'project-1', publicationRevision: 4, kind: 'MVP', playable: true, summary: '已发布项目快照', decisions: { goalCount: 5, durationSeconds: 30, playerSpeed: 220 } }, capabilities: { fields: { goalCount: { editable: true, min: 1, max: 8, integer: true }, durationSeconds: { editable: true, min: 10, max: 300, integer: true }, playerSpeed: { editable: true, min: 60, max: 400 } } }, candidates: [] },
  'GET /api/jobs/job-b': { job: { id: 'job-b', projectId: 'project-2', packetId: 'packet-b', status: 'READY_FOR_REVIEW', candidate: { id: 'candidate-b', candidateCommit: 'commit-b', title: '项目 B 候选' } } },
  'GET /api/projects/project-2/workbench': () => new Promise(resolve => { resolveProjectB = resolve; }),
  'POST /api/proposals/proposal-1/freeze': { packet: { id: 'packet-1', packetId: 'packet-1', projectId: 'project-1', proposalId: 'proposal-1', operationKind: 'INITIALIZATION' } },
  'POST /api/jobs': { job: { id: 'job-1', packetId: 'packet-1', projectId: 'project-1', status: 'QUEUED' } },
  'GET /api/jobs/job-1': { job: { id: 'job-1', packetId: 'packet-1', projectId: 'project-1', status: 'QUEUED' } },
  'POST /api/concepts': { proposal: { id: 'proposal-1', revision: 1, projectId: null, title: '星星收集', text: '<img src=x onerror=alert(1)>', status: 'NEEDS_CLARIFICATION', decisions: {}, questions: [{ id: 'goalCount', prompt: '需要收集几颗星？', options: [3, 5], required: true }], requirements: [] } },
  'POST /api/proposals/proposal-1/answers': { proposal: { id: 'proposal-1', revision: 2, title: '星星收集', text: '收集星星后到达出口', status: 'READY', decisions: { goalCount: 5 }, questions: [], requirements: ['收集星星', '到达出口'], initializationRequired: true, gmSpecRef: 'git:blob:spec-1', sourceRefs: { 'tests/closed_loop.gd': 'git:blob:test-1' }, templateInventory: { 'project.godot': 'git:blob:template-1' } } },
};
const fetchImpl = async (url, init = {}) => {
  const method = init.method || 'GET'; const key = `${method} ${new URL(url, 'http://127.0.0.1:8123').pathname}`;
  calls.push({ key, init, body: init.body ? JSON.parse(init.body) : null });
  if (init.headers?.['X-Workbench-Token'] && init.headers['X-Workbench-Token'] !== 'test-token') return response({ error: 'bad token' }, 403);
  if (routes[key]) return typeof routes[key] === 'function' ? await routes[key]() : response(routes[key]);
  return response({ error: `not found: ${key}` }, 404);
};
function response(data, status = 200) { return { ok: status >= 200 && status < 300, status, text: async () => JSON.stringify(data) }; }
const assert = (condition, message) => { if (!condition) throw new Error(message); };
const tick = async () => { await new Promise(resolve => setTimeout(resolve, 0)); };

(async () => {
  const { StudioApp } = await import(pathToFileURL(path.join(root, 'studio/studio.js')).href);
  const app = new StudioApp({ fetchImpl, documentImpl: dom.window.document, timers: globalThis });
  app.bind();
  await app.start();
  assert(document.querySelector('#connection').textContent === '已连接本机服务', 'workspace should show connected state');
  assert(!document.querySelector('#workspace').classList.contains('hidden'), 'workspace should be visible after valid API handshake');
  assert(!document.querySelector('#test-banner').classList.contains('hidden') && document.querySelector('#test-banner').textContent.includes('不构成生产授权'), 'test workspace must display a prominent non-production banner');
  document.querySelector('#concept').value = '一个收集星星的小 Demo';
  document.querySelector('#concept-form').dispatchEvent(new dom.window.Event('submit', { bubbles: true, cancelable: true }));
  await tick(); await tick();
  assert(calls.some(call => call.key === 'POST /api/concepts' && call.init.headers['X-Workbench-Token'] === 'test-token'), 'concept should be sent with local session token');
  const newProjectConcept = calls.find(call => call.key === 'POST /api/concepts');
  assert(!('projectId' in newProjectConcept.body) && !('expectedPublicationRevision' in newProjectConcept.body), 'new-project concepts should remain submittable without an existing project snapshot');
  assert(document.querySelector('#proposal-panel').textContent.includes('<img src=x onerror=alert(1)>'), 'proposal text should be rendered as escaped plain text');
  assert(document.querySelector('#proposal-panel').querySelector('img') === null, 'proposal response must not inject HTML');
  assert(!document.querySelector('#answers-form').classList.contains('hidden'), 'clarification question should be visible');
  const choice = document.querySelector('#questions select'); choice.value = '5';
  document.querySelector('#answers-form').dispatchEvent(new dom.window.Event('submit', { bubbles: true, cancelable: true }));
  await tick(); await tick();
  const answerCall = calls.find(call => call.key === 'POST /api/proposals/proposal-1/answers');
  assert(answerCall?.body.expectedRevision === 1 && answerCall.body.answers.goalCount === '5', 'answer must include the reviewed proposal revision and selected value');
  assert(!document.querySelector('#freeze-area').classList.contains('hidden'), 'READY proposal should display a freeze review');
  assert(document.querySelector('#freeze').disabled, 'freeze must remain disabled until the real user checks review');
  assert(document.querySelector('#review-label').textContent.includes('测试方案'), 'test confirmation must be labeled test-only');
  assert(!calls.some(call => call.key.includes('/freeze') || call.key === 'POST /api/jobs'), 'DOM QA must not approve, freeze, or create a real job');
  assert(document.querySelector('#proposal-panel').textContent.includes('最小工程准备'), 'new-project initialization scope should be disclosed before confirmation');
  assert(document.querySelector('#proposal-panel').textContent.includes('git:blob:spec-1') && document.querySelector('#proposal-panel').textContent.includes('git:blob:test-1') && document.querySelector('#proposal-panel').textContent.includes('project.godot'), 'proposal must expose GM spec, closed-loop test, and reviewed template inventory references');
  document.querySelector('#reviewed').checked = true;
  document.querySelector('#reviewed').dispatchEvent(new dom.window.Event('change', { bubbles: true }));
  await app.freezeProposal(); await tick(); await tick();
  assert(calls.some(call => call.key === 'POST /api/jobs'), 'mock workflow should reach job creation after the simulated review action');
  assert(!document.querySelector('#workbench-panel').classList.contains('hidden'), 'job creation should load the project workbench');
  assert(document.querySelector('#questions select[name="goalCount"]'), 'clarification select with overlapping parameter name should remain present');
  assert(document.querySelector('#edit-form [name="goalCount"]').closest('label') && document.querySelector('#edit-form [name="goalCount"]').min === '1', 'workbench controls should bind to their own scoped parameter fields');
  await app.loadJob('job-b', false); await tick();
  let acceptB = document.querySelector('#candidate-area .decision-actions .primary');
  assert(acceptB?.disabled, 'project B decision controls should stay disabled while project B snapshot is still loading');
  acceptB.click(); await tick();
  assert(!calls.some(call => call.key === 'POST /api/jobs/job-b/decision'), 'clicking a disabled project B decision must not submit with project A revision');
  assert(typeof resolveProjectB === 'function', 'project B workbench request should be pending before decision controls unlock');
  resolveProjectB(response({ snapshot: { projectId: 'project-2', publicationRevision: 8, kind: 'MVP', playable: true, decisions: { goalCount: 4 } }, capabilities: { fields: { goalCount: { editable: true, min: 1, max: 8 }, durationSeconds: { editable: true, min: 10, max: 300 }, playerSpeed: { editable: true, min: 60, max: 400 } } }, candidates: [] }));
  await tick(); await tick();
  acceptB = document.querySelector('#candidate-area .decision-actions .primary');
  assert(acceptB && !acceptB.disabled, 'project B decision controls should unlock after matching project B snapshot loads');
  const projectSelect = document.querySelector('#project');
  for (const [id, title] of [['project-1', '项目 A'], ['project-2', '项目 B']]) {
    if (![...projectSelect.options].some(option => option.value === id)) { const option = document.createElement('option'); option.value = id; option.textContent = title; projectSelect.append(option); }
  }
  await app.openProject('project-1');
  document.querySelector('#edit-text').value = '只属于项目 A 的草稿';
  document.querySelector('#edit-form [name="goalCount"]').value = '6';
  routes['GET /api/projects/project-2/workbench'] = () => response({ error: 'offline' }, 503);
  projectSelect.value = 'project-2';
  const conceptCallsBeforeFailedSwitch = calls.filter(call => call.key === 'POST /api/concepts').length;
  await app.openProject('project-2');
  assert(projectSelect.value === 'project-1' && app.snapshot.projectId === 'project-1', 'failed project B load should restore the matching project A selection and snapshot');
  assert(document.querySelector('#edit-text').value === '只属于项目 A 的草稿' && document.querySelector('#edit-form [name="goalCount"]').value === '6', 'failed project B load should preserve the visible project A draft');
  projectSelect.value = 'project-2'; app.applyReadinessGate();
  assert(document.querySelector('#concept-form [type="submit"]').disabled && document.querySelector('#edit-form [type="submit"]').disabled, 'existing-project submissions should remain disabled when the selected project and snapshot differ');
  await app.submitConcept('不应提交到项目 B'); await app.submitIteration();
  assert(calls.filter(call => call.key === 'POST /api/concepts').length === conceptCallsBeforeFailedSwitch, 'failed A-to-B switch must not post concept or iteration data to project B');
  if (![...projectSelect.options].some(option => option.value === 'project-3')) { const option = document.createElement('option'); option.value = 'project-3'; option.textContent = '项目 C'; projectSelect.append(option); }
  routes['GET /api/projects/project-2/workbench'] = () => new Promise(resolve => { resolveLateB = resolve; });
  routes['GET /api/projects/project-3/workbench'] = () => new Promise(resolve => { resolveEarlyC = resolve; });
  projectSelect.value = 'project-2'; const pendingB = app.openProject('project-2'); await tick();
  projectSelect.value = 'project-3'; const pendingC = app.openProject('project-3'); await tick();
  resolveEarlyC(response({ snapshot: { projectId: 'project-3', publicationRevision: 3, kind: 'MVP', playable: true, summary: '项目 C 快照先返回', decisions: { goalCount: 7 } }, capabilities: { fields: { goalCount: { editable: true, min: 1, max: 8 }, durationSeconds: { editable: true, min: 10, max: 300 }, playerSpeed: { editable: true, min: 60, max: 400 } } }, candidates: [] }));
  await pendingC;
  resolveLateB(response({ snapshot: { projectId: 'project-2', publicationRevision: 9, kind: 'MVP', playable: true, summary: '迟到的项目 B 快照', decisions: { goalCount: 2 } }, capabilities: { fields: { goalCount: { editable: true, min: 1, max: 8 }, durationSeconds: { editable: true, min: 10, max: 300 }, playerSpeed: { editable: true, min: 60, max: 400 } } }, candidates: [] }));
  await pendingB;
  assert(projectSelect.value === 'project-3' && app.snapshot.projectId === 'project-3' && document.querySelector('#workbench-title').textContent === '当前工作台' && document.querySelector('#edit-form [name="goalCount"]').value === '7', 'late project B response must not replace the newer project C selection, snapshot, or controls');
  app.persistenceOK = true;
  app.drafts.get = key => key.includes(':project-2:') ? new Promise(resolve => { resolveLateDraftB = resolve; }) : Promise.resolve(null);
  routes['GET /api/projects/project-2/workbench'] = () => response({ snapshot: { projectId: 'project-2', publicationRevision: 10, kind: 'MVP', playable: true, decisions: { goalCount: 2 } }, capabilities: { fields: { goalCount: { editable: true, min: 1, max: 8 }, durationSeconds: { editable: true, min: 10, max: 300 }, playerSpeed: { editable: true, min: 60, max: 400 } } }, candidates: [] });
  routes['GET /api/projects/project-3/workbench'] = () => response({ snapshot: { projectId: 'project-3', publicationRevision: 4, kind: 'MVP', playable: true, decisions: { goalCount: 7 } }, capabilities: { fields: { goalCount: { editable: true, min: 1, max: 8 }, durationSeconds: { editable: true, min: 10, max: 300 }, playerSpeed: { editable: true, min: 60, max: 400 } } }, candidates: [] });
  projectSelect.value = 'project-2'; const loadingBWithDraft = app.openProject('project-2'); await tick();
  assert(typeof resolveLateDraftB === 'function', 'project B draft restoration should be pending');
  projectSelect.value = 'project-3'; await app.openProject('project-3');
  resolveLateDraftB({ key: 'ws-1:project-2:10', projectId: 'project-2', publicationRevision: 10, draftRevision: 2, text: '迟到的 B 草稿', values: { goalCount: 2 } });
  await loadingBWithDraft;
  assert(app.snapshot.projectId === 'project-3' && projectSelect.value === 'project-3' && document.querySelector('#edit-text').value !== '迟到的 B 草稿' && document.querySelector('#edit-form [name="goalCount"]').value === '7', 'late project B draft restoration must not overwrite project C fields or text');
  routes['GET /api/projects/project-2/workbench'] = () => response({ error: 'offline' }, 503);
  app.job = { id: 'job-b', projectId: 'project-2', status: 'RUNNING' }; app.renderJob(); await tick(); await tick(); app.stopPolling();
  assert(projectSelect.value === 'project-3' && app.snapshot.projectId === 'project-3' && document.querySelector('#workbench-title').textContent === '当前工作台', 'job-triggered failed snapshot load must keep selector, snapshot, and title aligned');
  app.job = null;
  app.persistenceOK = false;
  app.pendingRebase = null;
  document.querySelector('#edit-text').value = '暂存的旧版本文字';
  document.querySelector('#edit-form [name="goalCount"]').value = '6';
  routes['GET /api/projects/project-3/workbench'] = () => response({ snapshot: { projectId: 'project-3', publicationRevision: 5, kind: 'MVP', playable: true, decisions: { goalCount: 3 } }, capabilities: { fields: { goalCount: { editable: true, min: 1, max: 8 }, durationSeconds: { editable: true, min: 10, max: 300 }, playerSpeed: { editable: true, min: 60, max: 400 } } }, candidates: [] });
  await app.loadWorkbench('project-3');
  assert(document.querySelector('#edit-form [name="goalCount"]').value === '3' && document.querySelector('#edit-text').value === '', 'version update should initially show new published values while retaining old text only in rebase preview');
  assert(app.pendingRebase && document.querySelector('#rebase-content').textContent.includes('不会保留'), 'no-storage rebase should require explicit confirmation and disclose in-memory-only persistence');
  const iterationCallsBeforeRebase = calls.filter(call => call.key === 'POST /api/concepts').length;
  await app.submitIteration();
  assert(calls.filter(call => call.key === 'POST /api/concepts').length === iterationCallsBeforeRebase, 'iteration submission must be blocked while rebase decision is pending');
  document.querySelector('#rebase-dialog').dispatchEvent(new dom.window.Event('close'));
  assert(!app.pendingRebase && document.querySelector('#edit-form [name="goalCount"]').value === '3', 'cancelled rebase must keep new published values and leave the old draft unapplied');
  routes['GET /api/projects/project-3/workbench'] = () => response({ snapshot: { projectId: 'project-3', publicationRevision: 6, kind: 'MVP', playable: true, decisions: { goalCount: 4 } }, capabilities: { fields: { goalCount: { editable: true, min: 1, max: 8 }, durationSeconds: { editable: true, min: 10, max: 300 }, playerSpeed: { editable: true, min: 60, max: 400 } } }, candidates: [] });
  await app.loadWorkbench('project-3');
  await app.confirmRebase();
  assert(document.querySelector('#edit-text').value === '暂存的旧版本文字' && document.querySelector('#edit-form [name="goalCount"]').value === '6' && document.querySelector('#draft-state').textContent.includes('不会持久保存'), 'explicit in-memory rebase confirmation should apply the old draft and disclose persistence limits');
  const caps = { fields: { goalCount: { editable: true, min: 1, max: 8 }, durationSeconds: { editable: true, min: 10, max: 300 }, playerSpeed: { editable: true, min: 60, max: 400 } } };
  const workbench = (projectId, revision, goalCount) => ({ snapshot: { projectId, publicationRevision: revision, kind: 'MVP', playable: true, decisions: { goalCount } }, capabilities: caps, candidates: [] });
  app.persistenceOK = true; app.draftRevision = 10;
  document.querySelector('#edit-text').value = '项目三的预览草稿'; document.querySelector('#edit-form [name="goalCount"]').value = '6';
  routes['GET /api/projects/project-3/workbench'] = () => response(workbench('project-3', 7, 5));
  let resolveRebaseGet;
  app.drafts.get = key => key.includes(':project-3:') ? new Promise(resolve => { resolveRebaseGet = resolve; }) : Promise.resolve(null);
  await app.loadWorkbench('project-3');
  const pendingGetConfirm = app.confirmRebase(); await tick();
  routes['GET /api/projects/project-2/workbench'] = () => response(workbench('project-2', 11, 2));
  await app.openProject('project-2');
  resolveRebaseGet({ key: 'ws-1:project-3:6', projectId: 'project-3', publicationRevision: 6, draftRevision: 10, text: '项目三的预览草稿', values: { goalCount: 6 } });
  await pendingGetConfirm;
  assert(app.snapshot.projectId === 'project-2' && app.draftKey === 'ws-1:project-2:11' && document.querySelector('#edit-text').value === '' && document.querySelector('#edit-form [name="goalCount"]').value === '2', 'late rebase read must not mutate another project after project switch');
  app.draftRevision = 20; document.querySelector('#edit-text').value = '项目二延迟写入草稿'; document.querySelector('#edit-form [name="goalCount"]').value = '3';
  routes['GET /api/projects/project-2/workbench'] = () => response(workbench('project-2', 12, 4));
  app.drafts.get = async key => ({ key, projectId: 'project-2', publicationRevision: 11, draftRevision: 20, text: '项目二延迟写入草稿', values: { goalCount: 3 } });
  await app.loadWorkbench('project-2');
  let resolveRebasePut;
  app.drafts.put = value => new Promise(resolve => { resolveRebasePut = () => resolve(value); });
  const pendingPutConfirm = app.confirmRebase(); await tick(); await tick();
  routes['GET /api/projects/project-3/workbench'] = () => response(workbench('project-3', 8, 7));
  app.drafts.get = async () => null;
  await app.openProject('project-3');
  resolveRebasePut(); await pendingPutConfirm;
  assert(app.snapshot.projectId === 'project-3' && app.draftKey === 'ws-1:project-3:8' && document.querySelector('#edit-text').value === '' && document.querySelector('#edit-form [name="goalCount"]').value === '7', 'late rebase write completion must not apply its draft to a newer project');
  app.draftRevision = 21; document.querySelector('#edit-text').value = '预览时的文字'; document.querySelector('#edit-form [name="goalCount"]').value = '5';
  routes['GET /api/projects/project-3/workbench'] = () => response(workbench('project-3', 9, 4));
  const driftedDraft = { key: 'ws-1:project-3:8', projectId: 'project-3', publicationRevision: 8, draftRevision: 22, text: '预览后修改的文字', values: { goalCount: 6 } };
  app.drafts.get = async () => driftedDraft; app.drafts.put = async value => value;
  await app.loadWorkbench('project-3'); await app.confirmRebase();
  assert(document.querySelector('#edit-text').value === '' && document.querySelector('#edit-form [name="goalCount"]').value === '4' && document.querySelector('#rebase-content').textContent.includes('预览后修改的文字'), 'draft content changed after preview must refresh preview and require a second confirmation');
  await app.confirmRebase();
  assert(document.querySelector('#edit-text').value === '预览后修改的文字' && document.querySelector('#edit-form [name="goalCount"]').value === '6', 'second confirmation should apply exactly the refreshed draft preview');
  app.persistenceOK = false;
  routes['GET /api/workspace'] = {
    workspaceId: 'ws-1', projects: [{ id: 'project-1', title: '已发布项目' }], testData: true,
    capabilities: { interactiveFrontendConfirmation: true, sessionDispatch: true, godotVerification: true, semanticProjection: true },
    proposals: [{ id: 'proposal-done', projectId: 'project-1', status: 'FROZEN', createdAt: '2026-10-08T00:00:00Z' }],
    packets: [{ id: 'packet-done', proposalId: 'proposal-done', projectId: 'project-1', operationKind: 'IMPLEMENTATION' }],
    jobs: [{ id: 'job-done', packetId: 'packet-done', projectId: 'project-1', status: 'PUBLISHED', createdAt: '2026-10-09T00:00:00Z' }],
  };
  routes['GET /api/jobs/job-done'] = { job: { id: 'job-done', packetId: 'packet-done', projectId: 'project-1', status: 'PUBLISHED' } };
  await app.refresh(); await tick(); await tick();
  assert(document.querySelector('#proposal-panel').classList.contains('hidden'), 'completed frozen proposal must not return as a pending confirmation after refresh');
  assert(!document.querySelector('#job-panel').classList.contains('hidden') && document.querySelector('#job-status').textContent === '已发布', 'refresh should restore the completed job instead of an obsolete freeze panel');
  routes['GET /api/workspace'] = { workspaceId: 'ws-1', projects: [], jobs: [], testData: true, capabilities: { interactiveFrontendConfirmation: true, sessionDispatch: true, godotVerification: true, semanticProjection: true }, proposals: [{ id: 'proposal-frozen', projectId: 'project-1', revision: 3, status: 'FROZEN', createdAt: '2026-10-10T00:00:00Z', packetId: 'packet-frozen' }], packets: [{ id: 'packet-frozen', proposalId: 'proposal-frozen', projectId: 'project-1', operationKind: 'IMPLEMENTATION' }] };
  await app.refresh(); await tick();
  assert(document.querySelector('#proposal-status').textContent === '已冻结，沿用原制作表单', 'frozen proposal badge should describe reuse of the frozen packet without implying job status');
  app.destroy(); dom.window.close();
  console.log('PASS studio DOM QA: session gating, concept intake, provenance display, revision-bound clarification, human-only freeze gate, and completed-workflow recovery');
})().catch(error => { console.error(error.stack || error); process.exitCode = 1; });
