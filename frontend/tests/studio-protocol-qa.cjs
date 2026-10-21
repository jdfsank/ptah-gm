#!/usr/bin/env node
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { pathToFileURL } = require('node:url');
const assert = require('node:assert/strict');
let JSDOM;
try { ({ JSDOM } = require('jsdom')); } catch { console.log('SKIP Studio protocol QA: jsdom is not installed.'); process.exit(0); }
const root = path.resolve(__dirname, '..');
const projectViewSchema = JSON.parse(fs.readFileSync(path.resolve(root, '../contracts/studio/project-view.v1.schema.json'), 'utf8'));
function assertProjectViewContract(view) {
  for (const key of projectViewSchema.required) assert.ok(Object.hasOwn(view, key), `project-view fixture must include schema-required ${key}`);
  for (const [key, rule] of Object.entries(projectViewSchema.properties)) {
    if (!Object.hasOwn(view, key)) continue;
    if (rule.const !== undefined) assert.equal(view[key], rule.const, `project-view fixture ${key} must match shared schema`);
    if (rule.enum) assert.ok(rule.enum.includes(view[key]), `project-view fixture ${key} must match shared schema enum`);
    const types = Array.isArray(rule.type) ? rule.type : [rule.type];
    if (rule.type) assert.ok(types.some(type => type === 'null' ? view[key] === null : type === 'array' ? Array.isArray(view[key]) : type === 'object' ? !!view[key] && typeof view[key] === 'object' && !Array.isArray(view[key]) : type === 'integer' ? Number.isInteger(view[key]) : typeof view[key] === type), `project-view fixture ${key} must match shared schema type`);
  }
}
const dom = new JSDOM(fs.readFileSync(path.join(root, 'studio/index.html'), 'utf8'), { url: 'http://127.0.0.1:8123/studio/' });
global.document = dom.window.document; global.Option = dom.window.Option; global.location = dom.window.location; global.history = dom.window.history; global.localStorage = dom.window.localStorage;
const ok = value => ({ ok: true, status: 200, text: async () => typeof value === 'string' ? value : JSON.stringify(value) });
const tick = () => new Promise(resolve => setTimeout(resolve, 0));

(async () => {
  const { StudioApp } = await import(pathToFileURL(path.join(root, 'studio/studio.js')).href);
  let getCount = 0, finishJobRead, failCommand = true, firstCommandId, viewCount = 0; const commandBodies = [];
  const fetchImpl = async (url, init = {}) => {
    const path = new URL(url, 'http://127.0.0.1').pathname;
    if (path === '/api/invalid') return ok('<html>not json</html>');
    if (path === '/api/duplicate') return ok('{"value":1,"value":2}');
    if (path === '/api/nonfinite') return ok('{"value":1e309}');
    if (path === '/api/projects/project-a/jobs/job-a') { getCount++; return new Promise(resolve => { finishJobRead = () => resolve(ok({ id: 'job-a', projectId: 'project-a', status: 'RUNNING' })); }); }
    if (path === '/api/v1/projects/project-a/view') {
      viewCount++; const revision = viewCount - 1;
      const activePreview = { id: 'preview-a', projectId: 'project-a', attemptId: 'attempt-preview-a', status: 'RUNNING' };
      const view = { schemaVersion: 'studio.project-view.v1', storeId: 'store-a', serviceInstanceId: 'instance-a', projectId: 'project-a', throughSequence: viewCount, phase: 'discussion', step: 'concept', attention: null, allowedActions: viewCount > 1 ? ['proposal.revise', 'preview.stop'] : ['proposal.revise'], apiVersion: 'objects-v1', workspaceId: 'local', name: '本地工作区', testData: false, productionAuthorized: false, projects: [{ id: 'project-a', title: 'A', protocolVersion: 1 }], proposals: [], packets: [], jobs: [], capabilities: {}, iterationReady: false, iterationReadyReason: '', project: { id: 'project-a', protocolVersion: 1 }, proposal: null, packet: null, job: null, snapshot: { id: 'project-a', projectId: 'project-a', publicationRevision: revision, workflow: 'objects-v1', kind: revision ? 'MVP' : 'CONCEPT', playable: revision > 0 }, candidates: [], previews: viewCount > 1 ? [activePreview] : [], observations: null, sessionPreferences: {}, sessionCatalog: {}, feedback: [], publicationRevision: revision };
      assertProjectViewContract(view);
      return ok(view);
    }
    if (path === '/api/v1/projects/project-a/commands') {
      const command = JSON.parse(init.body); firstCommandId ||= command.commandId; commandBodies.push(command);
      if (failCommand) { failCommand = false; throw new Error('connection lost after send'); }
      if (command.type === 'preview.stop') {
        const preview = { id: command.payload.previewId, projectId: 'project-a', attemptId: 'attempt-preview-a', status: 'STOP_REQUESTED' };
        return ok({ schemaVersion: 'studio.message.v1', kind: 'receipt', type: command.type, storeId: 'store-a', projectId: 'project-a', commandId: command.commandId, status: 'accepted', resource: { kind: 'preview', id: preview.id }, result: { preview } });
      }
      return ok({ schemaVersion: 'studio.message.v1', kind: 'receipt', type: command.type, storeId: 'store-a', projectId: 'project-a', commandId: command.commandId, status: 'accepted', resource: { kind: 'proposal', id: 'proposal-a' }, result: { proposal: { id: 'proposal-a' } } });
    }
    if (path.startsWith('/api/v1/projects/project-a/commands/')) { const id = path.split('/').at(-1); return ok({ schemaVersion: 'studio.message.v1', kind: 'command_lookup', storeId: 'store-a', projectId: 'project-a', commandId: id, known: false, receipt: null }); }
    return { ok: false, status: 404, text: async () => JSON.stringify({ error: 'missing' }) };
  };
  const app = new StudioApp({ fetchImpl, documentImpl: dom.window.document, timers: globalThis });
  let malformedError; try { await app.request('/invalid'); } catch (error) { malformedError = error; }
  assert.match(malformedError?.message || '', /无效 JSON/, 'HTTP 200 malformed JSON must not be accepted as success');
  await assert.rejects(app.request('/duplicate'), /重复 JSON 键/);
  await assert.rejects(app.request('/nonfinite'), /非有限数字/);

  const manualTimers = () => {
    let nextId = 0; const callbacks = new Map();
    return {
      callbacks,
      setTimeout(fn, ms) { const id = ++nextId; callbacks.set(id, { fn, ms }); return id; },
      clearTimeout(id) { callbacks.delete(id); },
      fire(ms) { const entry = [...callbacks.entries()].find(([, item]) => item.ms === ms); assert.ok(entry, `expected a ${ms}ms timer`); callbacks.delete(entry[0]); entry[1].fn(); },
    };
  };
  const requestTimers = manualTimers(); let headerSignal, bodySignal;
  const timeoutApp = new StudioApp({ fetchImpl: async (url, init) => {
    if (url.endsWith('/timeout-header')) {
      headerSignal = init.signal;
      return new Promise((_, reject) => init.signal.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')), { once: true }));
    }
    bodySignal = init.signal;
    return { ok: true, status: 200, text: () => new Promise((_, reject) => init.signal.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')), { once: true })) };
  }, documentImpl: dom.window.document, timers: requestTimers });
  const headerTimeout = timeoutApp.request('/timeout-header'); requestTimers.fire(20000);
  await assert.rejects(headerTimeout, error => error.message.includes('读取服务超时') && error.name !== 'AbortError', 'a response-header timeout must be reported as an actionable service timeout');
  assert.equal(headerSignal.aborted, true, 'a response-header timeout aborts the actual fetch');
  const bodyTimeout = timeoutApp.request('/timeout-body'); requestTimers.fire(20000);
  await assert.rejects(bodyTimeout, error => error.message.includes('读取服务超时') && error.name !== 'AbortError', 'the same timeout boundary must cover response-body parsing');
  assert.equal(bodySignal.aborted, true, 'a response-body timeout aborts the actual fetch and body read');
  assert.equal(requestTimers.callbacks.size, 0, 'request timeout handles are cleared after completion');
  const delayedAuthTimers = manualTimers(); let finishHandshakeBody, delayedAuthFetches = 0;
  const delayedAuthApp = new StudioApp({ fetchImpl: async url => {
    delayedAuthFetches++;
    if (url.endsWith('/secure')) return { ok: false, status: 401, text: async () => '{"message":"expired"}' };
    return { ok: true, status: 200, text: () => new Promise(resolve => { finishHandshakeBody = () => resolve(JSON.stringify({ schemaVersion: 'studio.message.v1', kind: 'handshake', storeId: 'store-a', serviceInstanceId: 'instance-b', writeToken: 'late-token', readable: true })); }) };
  }, documentImpl: dom.window.document, timers: delayedAuthTimers });
  delayedAuthApp.protocolVersion = 1; delayedAuthApp.handshake = { storeId: 'store-a', serviceInstanceId: 'instance-a' }; delayedAuthApp.token = 'original-token';
  const delayedAuthRequest = delayedAuthApp.request('/secure', { token: true }); await tick();
  assert.equal(delayedAuthFetches, 2, 'the expired-token request begins its handshake body read');
  delayedAuthTimers.fire(20000);
  await assert.rejects(delayedAuthRequest, /读取服务超时/);
  finishHandshakeBody(); await tick();
  assert.equal(delayedAuthApp.token, 'original-token', 'a late handshake body cannot change the session after timeout');
  assert.equal(delayedAuthFetches, 2, 'a late handshake body cannot start an authorized retry after timeout');

  let finishRefresh; let refreshReads = 0;
  const refreshApp = new StudioApp({ fetchImpl, documentImpl: dom.window.document, timers: globalThis });
  refreshApp.projectId = 'project-a'; refreshApp.protocolVersion = 1; refreshApp.manager = { projects: [{ id: 'project-a' }] };
  refreshApp.renderWorkspace = () => {}; refreshApp.mergeProjectSummary = () => {}; refreshApp.pendingProposal = () => null;
  refreshApp.request = async () => { refreshReads++; return new Promise(resolve => { finishRefresh = resolve; }); };
  refreshApp.ensureWorkbench = async projectId => { refreshApp.projectView = { projectId, throughSequence: 13 }; };
  refreshApp.projectView = { projectId: 'project-a', phase: 'discussion', step: 'concept', throughSequence: 12 };
  document.querySelector('#concept').value = '刷新过程中继续写下的新场景';
  refreshApp.targetNotes = { player: '保留的本地说明' }; refreshApp.structuralProposals = [{ id: 'local-structure' }];
  const firstRefresh = refreshApp.refresh(); const overlappingRefresh = refreshApp.refresh();
  assert.strictEqual(firstRefresh, overlappingRefresh, 'overlapping same-scope refreshes share one promise');
  assert.equal(refreshReads, 1, 'overlapping refreshes issue one status read');
  assert.match(document.querySelector('#workflow-status-copy').textContent, /正在刷新项目状态/, 'refresh progress is visible while the request is pending');
  finishRefresh({ projects: [{ id: 'project-a' }], proposals: [], jobs: [] });
  assert.equal(await firstRefresh, true);
  assert.equal(document.querySelector('#concept').value, '刷新过程中继续写下的新场景', 'refresh completion preserves current text input');
  assert.equal(refreshApp.targetNotes.player, '保留的本地说明');
  assert.equal(refreshApp.structuralProposals[0].id, 'local-structure', 'refresh completion preserves local structure');
  assert.equal(document.querySelector('#notice').textContent, '项目状态已刷新。', 'refresh completion reports a clear success result');

  const refreshStreamTimers = manualTimers(); let releaseCurrentAttempt; let refreshStreamReconnects = 0; let refreshStreamReads = 0;
  const refreshStreamApp = new StudioApp({ fetchImpl, documentImpl: dom.window.document, timers: refreshStreamTimers });
  refreshStreamApp.projectId = 'project-a'; refreshStreamApp.protocolVersion = 1; refreshStreamApp.manager = { projects: [{ id: 'project-a' }] };
  refreshStreamApp.renderWorkspace = () => {}; refreshStreamApp.mergeProjectSummary = () => {}; refreshStreamApp.pendingProposal = () => null;
  refreshStreamApp.request = async () => { refreshStreamReads++; return { projects: [{ id: 'project-a' }], proposals: [], jobs: [] }; };
  refreshStreamApp.ensureWorkbench = async projectId => { refreshStreamApp.projectView = { projectId, throughSequence: 14 }; };
  refreshStreamApp.streamProjectId = 'project-a'; refreshStreamApp.streamController = new AbortController();
  refreshStreamApp.streamAttemptDone = new Promise(resolve => { releaseCurrentAttempt = resolve; });
  refreshStreamApp.streamConnect = () => { refreshStreamReconnects++; };
  const refreshController = refreshStreamApp.streamController; const streamBoundRefresh = refreshStreamApp.refresh();
  assert.equal(refreshController.signal.aborted, true, 'a user refresh stops the active stream attempt before its view read');
  assert.equal(refreshStreamReads, 0, 'a refresh waits for the stream attempt cleanup before starting its GET');
  releaseCurrentAttempt(); assert.equal(await streamBoundRefresh, true);
  assert.equal(refreshStreamReads, 1); assert.equal(refreshStreamApp.streamPaused, false, 'refresh resumes the subscription after the view read');
  refreshStreamTimers.fire(1200); assert.equal(refreshStreamReconnects, 1, 'the resumed stream reconnects after the existing delay');

  let finishStaleRefresh; const switchedApp = new StudioApp({ fetchImpl, documentImpl: dom.window.document, timers: globalThis });
  switchedApp.projectId = 'project-a'; switchedApp.protocolVersion = 1; switchedApp.request = () => new Promise(resolve => { finishStaleRefresh = resolve; });
  const newProjectWorkspace = { projects: [{ id: 'project-b' }] }; const staleRefresh = switchedApp.refresh({ announce: false });
  switchedApp.selectionGeneration++; switchedApp.projectId = 'project-b'; switchedApp.workspace = newProjectWorkspace;
  finishStaleRefresh({ projects: [{ id: 'project-a' }], proposals: [], jobs: [] });
  assert.equal(await staleRefresh, false, 'an old selection refresh is rejected');
  assert.strictEqual(switchedApp.workspace, newProjectWorkspace, 'an old refresh response cannot overwrite a newly selected project');

  let finishDestroyedRefresh, destroyedRenders = 0, destroyedWorkbenchLoads = 0;
  const destroyedApp = new StudioApp({ fetchImpl, documentImpl: dom.window.document, timers: globalThis });
  destroyedApp.projectId = 'project-a'; destroyedApp.protocolVersion = 1; destroyedApp.manager = { projects: [{ id: 'project-a' }] };
  destroyedApp.request = () => new Promise(resolve => { finishDestroyedRefresh = resolve; });
  destroyedApp.renderWorkspace = () => { destroyedRenders++; }; destroyedApp.mergeProjectSummary = () => {};
  destroyedApp.pendingProposal = () => null; destroyedApp.ensureWorkbench = async () => { destroyedWorkbenchLoads++; };
  const noticeBeforeDestroy = document.querySelector('#notice').textContent;
  const destroyedRefresh = destroyedApp.refresh(); await tick(); destroyedApp.destroy();
  finishDestroyedRefresh({ projects: [{ id: 'project-a' }], proposals: [], jobs: [] });
  assert.equal(await destroyedRefresh, false, 'destroy invalidates a refresh whose workspace response arrives late');
  assert.equal(destroyedRenders, 0, 'a destroyed refresh cannot render stale workspace data');
  assert.equal(destroyedWorkbenchLoads, 0, 'a destroyed refresh cannot continue into a workbench load');
  assert.equal(document.querySelector('#notice').textContent, noticeBeforeDestroy, 'a destroyed refresh cannot announce late success');
  assert.equal(destroyedApp.streamRetry, null, 'destroy prevents refresh cleanup from reconnecting the old stream');

  let finishDestroyedWorkbench, lateWorkbenchRenders = 0;
  const lateWorkbenchApp = new StudioApp({ fetchImpl, documentImpl: dom.window.document, timers: globalThis });
  lateWorkbenchApp.projectId = 'project-a'; lateWorkbenchApp.protocolVersion = 1;
  lateWorkbenchApp.handshake = { storeId: 'store-a' }; lateWorkbenchApp.workspace = { projects: [{ id: 'project-a' }] };
  lateWorkbenchApp.request = () => new Promise(resolve => { finishDestroyedWorkbench = resolve; });
  lateWorkbenchApp.renderWorkbench = () => { lateWorkbenchRenders++; };
  const lateWorkbenchRead = lateWorkbenchApp.loadWorkbench('project-a'); await tick(); lateWorkbenchApp.destroy();
  const pageAtDestroy = document.body.innerHTML;
  finishDestroyedWorkbench({ schemaVersion: 'studio.project-view.v1', storeId: 'store-a', projectId: 'project-a',
    project: { id: 'project-a' }, snapshot: { id: 'project-a', projectId: 'project-a', publicationRevision: 9, summary: 'late snapshot' } });
  assert.equal(await lateWorkbenchRead, null, 'destroy invalidates an in-flight workbench response');
  assert.equal(lateWorkbenchApp.snapshot, null, 'a destroyed workbench read cannot apply a late snapshot');
  assert.equal(lateWorkbenchRenders, 0, 'a destroyed workbench read cannot rerender stale data');
  assert.equal(document.body.innerHTML, pageAtDestroy, 'a late workbench response cannot alter the page after destroy');

  // boot.js exposes a bounded wait status, clears it on a delayed import, and
  // preserves the existing reload action on a real import failure.
  const bootSource = fs.readFileSync(path.join(root, 'studio/boot.js'), 'utf8');
  const runBoot = promise => {
    const state = { reloads: 0, timer: null, cleared: false, elements: new Map() };
    const makeElement = id => {
      const classes = new Set(id === 'blocked' ? ['hidden'] : []);
      const item = { textContent: '', className: '', onclick: null, classList: {
        add: name => classes.add(name), remove: name => classes.delete(name), contains: name => classes.has(name),
      }, dataset: {} };
      state.elements.set(id, item); return item;
    };
    for (const id of ['connection', 'blocked', 'blocked-title', 'blocked-copy', 'retry']) makeElement(id);
    state.elements.get('connection').textContent = '正在连接本机服务…';
    const documentImpl = { getElementById: id => state.elements.get(id) };
    const source = bootSource.replace("import('./studio.js')", 'modulePromise');
    vm.runInNewContext(source, {
      document: documentImpl, location: { reload: () => { state.reloads++; } }, modulePromise: promise,
      setTimeout: (fn, ms) => { assert.equal(ms, 8000); state.timer = fn; return 1; },
      clearTimeout: () => { state.cleared = true; },
    });
    return state;
  };
  let resolveModule; const delayedModule = new Promise(resolve => { resolveModule = resolve; });
  const delayedBoot = runBoot(delayedModule); delayedBoot.timer();
  assert.equal(delayedBoot.elements.get('connection').textContent, '页面模块仍在加载');
  assert.equal(delayedBoot.elements.get('blocked').classList.contains('hidden'), false, 'slow module loading shows a bounded visible wait state');
  resolveModule({}); await tick();
  assert.equal(delayedBoot.cleared, true); assert.equal(delayedBoot.elements.get('blocked').classList.contains('hidden'), true, 'late module success clears only the boot wait notice');
  assert.equal(delayedBoot.elements.get('connection').textContent, '正在连接本机服务…', 'late module success returns to the normal single-app startup path');
  let resolveSecondModule; const secondDelayedModule = new Promise(resolve => { resolveSecondModule = resolve; });
  const bootWithRealFailure = runBoot(secondDelayedModule); bootWithRealFailure.timer();
  bootWithRealFailure.elements.get('blocked').dataset.bootWait = '';
  bootWithRealFailure.elements.get('connection').textContent = '服务未就绪';
  bootWithRealFailure.elements.get('blocked-copy').textContent = '真实启动失败';
  resolveSecondModule({}); await tick();
  assert.equal(bootWithRealFailure.elements.get('blocked').classList.contains('hidden'), false, 'late import success cannot hide a real startup failure');
  assert.equal(bootWithRealFailure.elements.get('blocked-copy').textContent, '真实启动失败', 'late import success preserves the real failure text');
  assert.equal(bootWithRealFailure.elements.get('retry').onclick, null, 'late import success removes only the boot reload handler, leaving the app retry handler intact');
  let rejectModule; const failedModule = new Promise((_, reject) => { rejectModule = reject; });
  const failedBoot = runBoot(failedModule); rejectModule(new Error('fixture import failure')); await tick();
  assert.equal(failedBoot.elements.get('connection').textContent, '页面模块加载失败');
  failedBoot.elements.get('retry').onclick(); assert.equal(failedBoot.reloads, 1, 'module failure keeps the explicit reload action');
  app.projectId = 'project-a'; app.protocolVersion = 1; app.handshake = { storeId: 'store-a', serviceInstanceId: 'instance-a', writeToken: 'token-a' }; app.token = 'token-a'; app.manager = { projects: [{ id: 'project-a', protocolVersion: 1 }] };
  app.manager.projects.push({ id: 'legacy-project', title: 'Legacy' });
  assert.equal(app.usesV1Commands('project-a'), true, 'new project uses negotiated v1 commands');
  assert.equal(app.usesV1Commands('legacy-project'), false, 'v1-capable service must retain legacy commands for an old project');
  app.projectId = 'legacy-project';
  await assert.rejects(app.sendCommand('proposal.revise', { proposalId: 'old-proposal', supplement: 'no migration' }), /旧项目保留原有流程协议/);
  app.projectId = 'project-a';
  app.projectView = { allowedActions: ['proposal.revise'] };
  const first = app.loadJob('job-a', false); await tick();
  const second = app.loadJob('job-a', false); await tick();
  assert.equal(getCount, 1, 'overlapping slow status reads must be serialized');
  finishJobRead(); await Promise.all([first, second]);
  await assert.rejects(app.sendCommand('proposal.revise', { proposalId: 'proposal-a', supplement: '继续' }), /connection lost/);
  const persisted = JSON.parse(localStorage.getItem('ptah-pending:store-a:project-a:proposal.revise'));
  assert.equal(persisted.commandId, firstCommandId, 'command ID must survive app recreation while outcome is unknown');
  const resumed = new StudioApp({ fetchImpl, documentImpl: dom.window.document, timers: globalThis });
  resumed.projectId = 'project-a'; resumed.protocolVersion = 1; resumed.handshake = app.handshake; resumed.token = 'token-a'; resumed.projectView = app.projectView;
  resumed.workspace = { projects: [{ id: 'project-a', protocolVersion: 1 }], proposals: [], packets: [], jobs: [] }; resumed.manager = { projects: [{ id: 'project-a', protocolVersion: 1 }] };
  await resumed.loadWorkbench('project-a');
  assert.equal(resumed.previews[0]?.id, 'preview-a', 'a reload must restore the active preview from the authoritative project view');
  const previewControls = document.createElement('div'); resumed.renderPreviewControls(previewControls);
  const stopPreview = previewControls.querySelector('button');
  assert.ok(stopPreview, 'a restored active preview must expose a stop control');
  assert.equal(stopPreview.disabled, false, 'the stop control must follow the backend allowedActions projection');
  const initialViewCount = viewCount;
  await resumed.ensureWorkbench('project-a', true);
  assert.ok(viewCount > initialViewCount, 'same-project refresh must fetch a fresh exact project view');
  assert.equal(resumed.snapshot.publicationRevision, viewCount - 1, 'same-project refresh must replace the cached publication snapshot');
  await assert.rejects(resumed.sendCommand('proposal.revise', { proposalId: 'proposal-a', supplement: '新内容' }), /核实上一条请求/);
  assert.equal(commandBodies[1].commandId, firstCommandId, 'unknown command recovery must replay the same identity');
  assert.equal(commandBodies[1].payload.supplement, '继续', 'unknown command recovery must replay the original content, never the edited content');
  assert.equal(localStorage.getItem('ptah-pending:store-a:project-a:proposal.revise'), null);
  const result = await resumed.sendCommand('proposal.revise', { proposalId: 'proposal-a', supplement: '新内容' });
  assert.equal(result.proposal.id, 'proposal-a');
  assert.notEqual(commandBodies[2].commandId, firstCommandId, 'a new intent gets a new ID only after the first intent is known');
  assert.equal(localStorage.getItem('ptah-pending:store-a:project-a:proposal.revise'), null, 'accepted receipt clears persisted pending identity');
  const stoppedPreview = await resumed.sendCommand('preview.stop', { previewId: 'preview-a' });
  assert.equal(stoppedPreview.preview.status, 'STOP_REQUESTED', 'the restored preview ID must be usable for the stop command');
  assert.equal(commandBodies.at(-1).payload.previewId, 'preview-a');

  // A v1 candidate flag alone cannot authorize opening a Godot preview: the
  // current, project-matched view must also permit preview.start. Legacy
  // projects retain their existing preview affordance.
  const candidateArea = document.querySelector('#candidate-area');
  const previewCandidateFixture = { id: 'candidate-preview-a', candidateCommit: 'commit-a', previewAvailable: true };
  resumed.manager.projects.push({ id: 'legacy-project', title: 'Legacy' });
  resumed.projectId = 'project-a';
  resumed.job = { id: 'job-preview-a', projectId: 'project-a', status: 'READY_FOR_REVIEW', candidate: previewCandidateFixture };
  resumed.previews = [];
  resumed.projectView = { projectId: 'project-a', allowedActions: ['candidate.accept', 'candidate.reject'] };
  const previewStartButton = () => [...candidateArea.querySelectorAll('button')].find(button => button.textContent === '在 Godot 中运行此候选');
  candidateArea.replaceChildren(); resumed.renderCandidate(previewCandidateFixture);
  assert.equal(previewStartButton(), undefined, 'v1 hides candidate preview when the current view does not authorize preview.start');
  resumed.projectView = { projectId: 'project-a', allowedActions: ['preview.start'] };
  candidateArea.replaceChildren(); resumed.renderCandidate(previewCandidateFixture);
  assert.ok(previewStartButton(), 'v1 shows candidate preview when the matching project view authorizes preview.start');
  resumed.previews = [{ id: 'preview-a', projectId: 'project-a', status: 'RUNNING' }];
  resumed.projectView = { projectId: 'project-a', allowedActions: ['preview.stop'] };
  candidateArea.replaceChildren(); resumed.renderCandidate(previewCandidateFixture);
  assert.equal(previewStartButton(), undefined, 'an active preview cannot expose a second preview start');
  assert.ok([...candidateArea.querySelectorAll('button')].some(button => button.textContent === '停止预览' && !button.disabled), 'the same view still exposes its authorized stop control');
  resumed.projectId = 'legacy-project';
  resumed.job = { id: 'legacy-job-preview', projectId: 'legacy-project', status: 'READY_FOR_REVIEW' };
  resumed.previews = [];
  resumed.projectView = { projectId: 'legacy-project', allowedActions: [] };
  candidateArea.replaceChildren(); resumed.renderCandidate(previewCandidateFixture);
  assert.ok(previewStartButton(), 'legacy candidate preview remains available without a v1 action projection');
  resumed.projectId = 'project-a';
  resumed.job = null;
  resumed.previews = [];
  resumed.projectView = { projectId: 'project-a', allowedActions: ['proposal.revise'] };

  // A v1 project's draft namespace includes the authoritative store identity and
  // a reviewed publication rebase copies the draft only after explicit approval.
  resumed.workspace = { storeId: 'store-a', projects: [{ id: 'project-a', protocolVersion: 1 }] };
  resumed.manager.projects = [{ id: 'project-a', protocolVersion: 1 }];
  resumed.projectId = 'project-a'; resumed.persistenceOK = true; resumed.workbenchGeneration = 9;
  const oldSnapshot = { id: 'project-a', projectId: 'project-a', publicationRevision: 4, sourceCommit: 'base-4', capabilities: {} };
  const nextSnapshot = { id: 'project-a', projectId: 'project-a', publicationRevision: 5, sourceCommit: 'base-5', capabilities: {} };
  resumed.snapshot = oldSnapshot;
  const oldDraftKey = resumed.makeDraftKey(oldSnapshot);
  assert.equal(oldDraftKey, 'store-a:project-a:iteration:4', 'draft namespace is scoped to store, project, stage, and publication');
  resumed.draftKey = oldDraftKey;
  resumed.drafts = { get: async key => key === oldDraftKey ? { ...resumed.pendingRebase.draft } : null, put: async record => { resumed.rebasedRecord = record; } };
  resumed.handleRebase(oldSnapshot, nextSnapshot, { text: '迁移前必须审阅', values: {}, fields: {}, feedback: [], draftRevision: 3 });
  resumed.snapshot = nextSnapshot;
  assert.ok(resumed.pendingRebase, 'publication change opens a reviewed rebase');
  await resumed.confirmRebase();
  assert.equal(resumed.draftKey, 'store-a:project-a:iteration:5');
  assert.equal(resumed.rebasedRecord.rebaseNeedsReview, true);
  assert.equal(resumed.rebasedRecord.text, '迁移前必须审阅');
  const feedback = resumed.ensureFeedbackIds([{ objectId: 'player', message: '反馈', category: 'visual' }]);
  assert.ok(feedback[0].feedbackId);
  assert.equal(resumed.ensureFeedbackIds(feedback)[0].feedbackId, feedback[0].feedbackId, 'feedback identity survives normalization');
  resumed.sessionPreferences = { revision: 2, roles: { producer: { modelKey: null, effort: null, limits: { maxDurationSeconds: 1800, softTotalTokens: null } } } };
  resumed.sessionCatalog = { available: true, models: [{ modelKey: 'gpt-6-luna', supportedReasoningEfforts: ['low', 'max'] }] };
  resumed.renderSessionSettings();
  const producerModel = document.querySelector('[aria-label="producer 模型"]');
  producerModel.value = 'gpt-6-luna'; producerModel.dispatchEvent(new dom.window.Event('change'));
  document.querySelector('[aria-label="producer 推理档位"]').value = 'max';
  const producerDuration = document.querySelector('[aria-label="producer最长执行秒数"]');
  producerDuration.value = '180'; producerDuration.focus();
  resumed.applyProjectView({ projectId: 'project-a', throughSequence: 100, sessionPreferences: structuredClone(resumed.sessionPreferences), sessionCatalog: { ...structuredClone(resumed.sessionCatalog), observedAt: 'later heartbeat' } });
  assert.equal(document.querySelector('[aria-label="producer 模型"]').value, 'gpt-6-luna', 'unrelated project updates preserve unsaved role selection');
  assert.equal(document.querySelector('[aria-label="producer 推理档位"]').value, 'max');
  assert.equal(document.querySelector('[aria-label="producer最长执行秒数"]').value, '180');
  assert.equal(document.activeElement, producerDuration, 'state updates preserve focus while editing settings');
  resumed.projectId = 'project-b'; resumed.renderSessionSettings();
  assert.equal(document.querySelector('[aria-label="producer 模型"]').value, 'gpt-6-luna', 'new project resolves the service default model');
  assert.equal(document.querySelector('[aria-label="producer 推理档位"]').value, 'low', 'unsaved effort never crosses project boundaries');
  assert.equal(document.querySelector('[aria-label="producer最长执行秒数"]').value, '1800', 'new project restores its persisted limit instead of an unsaved edit');
  assert.equal(resumed.sessionPreferences.roles.producer.modelKey, null, 'displaying the service default does not persist a model preference');
  resumed.projectId = 'project-a';
  resumed.workspace.capabilities = { interactiveFrontendConfirmation: true, sessionDispatch: true, godotVerification: true, semanticProjection: true };
  resumed.applyProjectView({ projectId: 'project-a', sessionCatalog: { available: false, models: [], capabilities: [] } });
  assert.equal(document.querySelector('#concept-form [type="submit"]').disabled, true, 'an unavailable runner closes the execution gate');
  assert.equal(document.querySelector('#blocked').classList.contains('hidden'), false);
  resumed.applyProjectView({ projectId: 'project-a', sessionCatalog: { available: true, models: [{ modelKey: 'gpt-6-luna', supportedReasoningEfforts: ['low', 'max'] }], capabilities: ['planning-readonly-v1', 'production-private-v1'] } });
  assert.equal(document.querySelector('#concept-form [type="submit"]').disabled, false, 'a fresh runner view restores the execution gate');
  assert.equal(document.querySelector('#blocked').classList.contains('hidden'), true, 'the obsolete startup failure disappears once checks pass');
  resumed.showWorkflowBlock('A separate workflow failure'); resumed.applyReadinessGate();
  assert.equal(document.querySelector('#blocked').classList.contains('hidden'), false, 'runner readiness does not conceal a separate workflow failure');
  const dispatchApp = new StudioApp({ documentImpl: dom.window.document, timers: globalThis });
  const dispatchPacket = { id: 'packet-dispatch', projectId: 'project-a', proposalId: 'proposal-dispatch' };
  dispatchApp.projectId = 'project-a'; dispatchApp.protocolVersion = 1; dispatchApp.manager = resumed.manager;
  dispatchApp.packet = dispatchPacket; dispatchApp.proposal = { id: 'proposal-dispatch', projectId: 'project-a', revision: 1 };
  dispatchApp.projectView = { allowedActions: ['proposal.freeze'] };
  const dispatchOrder = [];
  dispatchApp.ensureWorkbench = async (projectId, refresh) => { assert.equal(projectId, 'project-a'); assert.equal(refresh, true); dispatchOrder.push('view'); dispatchApp.projectView = { allowedActions: ['production.start'] }; };
  dispatchApp.sendCommand = async (type, payload) => { assert.equal(type, 'production.start'); assert.equal(payload.packetId, 'packet-dispatch'); assert.ok(dispatchApp.projectView.allowedActions.includes(type)); dispatchOrder.push('start'); return { job: { id: 'job-dispatch' } }; };
  dispatchApp.renderJob = () => {}; dispatchApp.beginPolling = () => {};
  await dispatchApp.createJob(dispatchPacket);
  assert.deepEqual(dispatchOrder, ['view', 'start'], 'freeze acknowledgement must refresh authoritative allowed actions before production dispatch');
  const retryDelays = [], pollDelays = [], eventTimers = { setTimeout: (_fn, ms) => { retryDelays.push(ms); return retryDelays.length; }, clearTimeout: () => {}, setInterval: (_fn, ms) => { pollDelays.push(ms); return pollDelays.length; }, clearInterval: () => {} };
  const badEvent = { schemaVersion: 'studio.message.v1', kind: 'event', storeId: 'wrong-store', projectId: 'project-a', sequence: 8, eventId: 'event-8', type: 'project.changed', payload: {} };
  const eventApp = new StudioApp({ fetchImpl: async () => ({ ok: true, status: 200, body: { getReader: () => ({ read: async () => ({ value: new TextEncoder().encode(`id: 8\nevent: project.changed\ndata: ${JSON.stringify(badEvent)}\n\n`), done: false }) }) } }), documentImpl: dom.window.document, timers: eventTimers });
  eventApp.projectId = 'project-a'; eventApp.protocolVersion = 1; eventApp.handshake = app.handshake; eventApp.token = app.token; eventApp.manager = app.manager; eventApp.job = { id: 'job-a', projectId: 'project-a', status: 'RUNNING' }; eventApp.projectView = { throughSequence: 7, phase: 'execution', step: 'producing' };
  eventApp.startEventStream('project-a', 7); await tick();
  assert.equal(eventApp.streamFresh, false, 'an SSE event with mismatched store identity marks the stream stale');
  assert.ok(pollDelays.includes(10000), 'SSE schema failure resumes serialized low-frequency job polling');
  assert.ok(retryDelays.includes(1200), 'SSE failure schedules a bounded reconnect attempt');
  let replayReconnect, refreshFailed = true, releasedStreams = 0; const replayUrls = [];
  const replayEvent = { ...badEvent, storeId: 'store-a' };
  const replayTimers = { setTimeout: fn => { replayReconnect = fn; return 1; }, clearTimeout: () => {}, setInterval: () => 1, clearInterval: () => {} };
  const replayApp = new StudioApp({ fetchImpl: async url => {
    replayUrls.push(url); let delivered = false;
    return { ok: true, status: 200, body: { getReader: () => ({ cancel: async () => { releasedStreams++; }, releaseLock: () => {}, read: async () => {
      if (delivered) return { done: true }; delivered = true;
      return { value: new TextEncoder().encode(`id: 8\nevent: project.changed\ndata: ${JSON.stringify(replayEvent)}\n\n`), done: false };
    } }) } };
  }, documentImpl: dom.window.document, timers: replayTimers });
  replayApp.projectId = 'project-a'; replayApp.protocolVersion = 1; replayApp.handshake = app.handshake; replayApp.token = app.token;
  replayApp.refresh = async () => { assert.equal(releasedStreams, replayUrls.length, 'a view read starts only after the current SSE reader is released'); if (refreshFailed) return false; replayApp.projectView = { step: 'proposal_review', throughSequence: 8 }; return true; };
  replayApp.startEventStream('project-a', 7); await tick();
  assert.equal(replayApp.eventSequence, 7, 'a failed view read cannot acknowledge an unread completion event');
  assert.equal(replayApp.streamFresh, false);
  assert.equal(replayApp.streamReconnecting, false, 'a failed view refresh cannot be described as a healthy reconnect');
  assert.equal(releasedStreams, 1, 'a failed view read closes the old HTTP stream before reconnecting');
  refreshFailed = false; await replayReconnect();
  assert.ok(replayUrls.every(url => url.endsWith('after=7')), 'reconnection replays from the last successfully applied sequence');
  assert.equal(replayApp.projectView.step, 'proposal_review', 'replayed completion updates the page after connection recovery');
  assert.equal(replayApp.eventSequence, 8);
  assert.equal(replayApp.streamReconnecting, true, 'an applied completion event reconnects without a stale-state warning');

  const leaseTimers = manualTimers(); let leaseSignal, leaseReader, leaseCancels = 0, leaseReleases = 0; const leaseUrls = [];
  const leaseApp = new StudioApp({ fetchImpl: async (url, init = {}) => {
    leaseUrls.push(url); leaseSignal = init.signal;
    if (leaseUrls.length === 1) return { ok: true, status: 200, body: { getReader: () => {
      let finishRead;
      leaseReader = {
        read: () => new Promise(resolve => { finishRead = resolve; }),
        deliver: text => finishRead({ done: false, value: new TextEncoder().encode(text) }),
        cancel: async () => { leaseCancels++; finishRead?.({ done: true }); },
        releaseLock: () => { leaseReleases++; },
      };
      return leaseReader;
    } } };
    return { ok: false, status: 503 };
  }, documentImpl: dom.window.document, timers: leaseTimers });
  leaseApp.projectId = 'project-a'; leaseApp.protocolVersion = 1; leaseApp.handshake = app.handshake; leaseApp.token = 'token-a'; leaseApp.eventSequence = 6;
  leaseApp.startEventStream('project-a', 6); await tick();
  assert.ok(leaseReader, 'the finite-lease fixture acquired its first stream reader');
  const firstIdleTimer = [...leaseTimers.callbacks.keys()][0];
  leaseReader.deliver(': keepalive\n\n'); await tick();
  assert.equal(leaseTimers.callbacks.has(firstIdleTimer), false, 'a server keepalive replaces the old inactivity deadline');
  assert.equal(leaseApp.streamFresh, true, 'a healthy keepalive keeps the stream live');
  assert.equal(leaseTimers.callbacks.size, 1, 'renewing keepalives retain one bounded inactivity deadline');
  leaseTimers.fire(20000); await tick();
  assert.equal(leaseSignal.aborted, true, 'twenty seconds without data aborts the actual fetch');
  assert.ok(leaseCancels >= 1 && leaseReleases >= 1, 'the attempt deadline cancels and releases the active reader');
  assert.equal(leaseApp.eventSequence, 6, 'an attempt deadline preserves the last successfully applied sequence');
  assert.equal(leaseApp.streamFresh, false, 'a released finite attempt cannot continue claiming live stream freshness');
  assert.equal(leaseApp.streamReconnecting, false, 'a real inactivity timeout remains visibly stale');
  assert.equal(leaseApp.streamController, null, 'a released attempt clears its owned controller');
  leaseTimers.fire(1200); await tick();
  assert.equal(leaseUrls.length, 2, 'a timed-out attempt reconnects after the existing delay');
  assert.ok(leaseUrls.every(url => url.endsWith('after=6')), 'a finite reconnect resumes from the last successful sequence');
  leaseApp.stopEventStream();

  const staleChunkTimers = manualTimers(); let deliverStaleChunk;
  const staleChunkApp = new StudioApp({ fetchImpl: async () => ({ ok: true, status: 200, body: { getReader: () => ({
    read: () => new Promise(resolve => { deliverStaleChunk = resolve; }), cancel: async () => {}, releaseLock: () => {},
  }) } }), documentImpl: dom.window.document, timers: staleChunkTimers });
  staleChunkApp.projectId = 'project-a'; staleChunkApp.handshake = app.handshake;
  staleChunkApp.startEventStream('project-a', 6); await tick();
  staleChunkApp.stopEventStream(); staleChunkApp.projectId = 'project-b';
  deliverStaleChunk({ done: false, value: new TextEncoder().encode(': keepalive\n\n') }); await tick();
  assert.equal(staleChunkTimers.callbacks.size, 0, 'late chunks from a released project cannot rearm its timeout');
  assert.equal(staleChunkApp.streamAttemptTimeout, null);
  staleChunkApp.destroy();

  let authReconnect, authRefreshes = 0, replacementStore = 'store-a'; const streamTokens = [], authMethods = [];
  const authTimers = { setTimeout: (fn, ms) => { if (ms === 1200) authReconnect = fn; return 1; }, clearTimeout: () => {}, setInterval: () => 1, clearInterval: () => {} };
  const authApp = new StudioApp({ fetchImpl: async (url, init = {}) => {
    authMethods.push(init.method || 'GET');
    if (url.endsWith('/v1/handshake')) return ok({ schemaVersion: 'studio.message.v1', kind: 'handshake', storeId: replacementStore, serviceInstanceId: 'restarted-instance', writeToken: 'renewed-token', readable: true });
    streamTokens.push(init.headers['X-Workbench-Token']);
    if (streamTokens.length === 1) return { ok: false, status: 403 };
    return { ok: true, status: 200, body: { getReader: () => ({ read: async () => ({ done: true }) }) } };
  }, documentImpl: dom.window.document, timers: authTimers });
  authApp.projectId = 'project-a'; authApp.protocolVersion = 1; authApp.handshake = app.handshake; authApp.token = 'expired-token';
  authApp.refresh = async () => { authRefreshes++; assert.equal(authApp.token, 'renewed-token'); return true; };
  authApp.startEventStream('project-a', 8); await tick();
  assert.equal(authRefreshes, 1, 'backend restart renews the same-store handshake and refreshes its view');
  await authReconnect();
  assert.deepEqual(streamTokens, ['expired-token', 'renewed-token'], 'stream reconnect must use the renewed token');
  assert.ok(authMethods.every(method => method === 'GET'), 'restart recovery must not replay business commands');
  replacementStore = 'different-store'; streamTokens.length = 0; authRefreshes = 0;
  authApp.startEventStream('project-a', 8); await tick();
  assert.equal(authApp.handshake.storeId, 'store-a', 'a replacement store cannot adopt the current project or pending commands');
  assert.equal(authApp.token, 'renewed-token');
  assert.equal(authRefreshes, 0, 'a mismatched store keeps the current view unconfirmed');
  const blockedProposal = { id: 'proposal-blocked', projectId: 'project-a', revision: 1, status: 'BLOCKED', workflow: 'objects-v1', document: { objects: [] }, summary: '无法读取前置材料', blockers: ['工程材料尚未准备'] };
  replayApp.workspace = { projects: [{ id: 'project-a' }], proposals: [blockedProposal] };
  replayApp.proposal = blockedProposal; replayApp.stage = 'initial'; replayApp.job = null;
  assert.equal(replayApp.pendingProposal('project-a'), blockedProposal, 'a completed blocked plan remains visible instead of disappearing');
  replayApp.renderProposal(); replayApp.renderWorkflowStages();
  assert.ok(dom.window.document.querySelector('#proposal-content').textContent.includes('工程材料尚未准备'));
  assert.equal(dom.window.document.querySelector('#concept-form').closest('.panel').classList.contains('hidden'), false, 'a blocked plan allows an explicit revised concept');
  assert.equal(dom.window.document.querySelector('#freeze-area').classList.contains('hidden'), true, 'a blocked plan cannot be approved');
  // User-selected history must survive authoritative current-job updates and
  // the extra workbench read performed by refresh().
  const historyJob = { id: 'history-job', projectId: 'project-a', status: 'FAILED', message: 'Historical failure' };
  const currentJob = { id: 'current-job', projectId: 'project-a', status: 'READY_FOR_REVIEW' };
  resumed.workspace = { projects: [{ id: 'project-a', protocolVersion: 1 }], proposals: [], packets: [], jobs: [currentJob, historyJob] };
  resumed.request = async path => path.includes('/jobs/') ? (path.endsWith(historyJob.id) ? historyJob : currentJob) : { ...resumed.workspace, projectId: 'project-a', job: currentJob };
  resumed.ensureWorkbench = async () => resumed.applyProjectView({ projectId: 'project-a', job: currentJob, previews: [] });
  resumed.job = currentJob; resumed.streamFresh = true;
  await resumed.selectJob(historyJob.id);
  resumed.applyProjectView({ projectId: 'project-a', job: currentJob, previews: [] });
  await resumed.refresh();
  assert.equal(resumed.job.id, historyJob.id, 'refresh and SSE keep the selected historical failure visible');
  assert.match(document.querySelector('#job-message').textContent, /Historical failure/);
  resumed.projectId = 'project-b';
  resumed.applyProjectView({ projectId: 'project-b', job: { ...currentJob, projectId: 'project-b' } });
  assert.equal(resumed.job.id, currentJob.id, 'a history selection cannot affect another project');
  resumed.projectId = 'project-a'; resumed.selectedJob = null;
  const frozenProposal = { id: 'frozen-plan', projectId: 'project-a', revision: 2, status: 'FROZEN', workflow: 'objects-v1', reviewedPlanRef: 'plan-ref' };
  resumed.proposal = frozenProposal;
  resumed.reviewedPlan = { schemaVersion: 'studio.message.v1', projectId: 'project-a', reviewedPlanRef: 'plan-ref', plan: { ...frozenProposal, assetBundle: { bundleId: 'bundle-a', paths: ['assets/player.png'] } } };
  resumed.renderProposal(); await tick();
  const frozenDetails = document.querySelector('#reviewed-plan-content');
  assert.equal(frozenDetails.tagName, 'DETAILS');
  assert.equal(frozenDetails.querySelector('img').alt, 'assets/player.png', 'frozen review retains image previews');
  assert.equal(document.querySelector('#freeze-area').classList.contains('hidden'), true, 'frozen review offers no new approval action');
  assert.equal(document.querySelector('#freeze').disabled, true);
  frozenDetails.open = true; await tick(); resumed.renderProposal(); await tick();
  assert.equal(document.querySelector('#reviewed-plan-content').open, true, 'state refresh preserves the expanded frozen plan');
  app.destroy(); resumed.destroy(); dispatchApp.destroy(); eventApp.destroy(); replayApp.destroy(); authApp.destroy(); dom.window.close();
  console.log('PASS Studio protocol/transport QA: bounded request/SSE lifetimes, refresh coalescing, replay-safe recovery, boot wait, strict JSON, and command identity');
})().catch(error => { console.error(error.stack || error); process.exitCode = 1; });
