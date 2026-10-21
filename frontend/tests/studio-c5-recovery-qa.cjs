/* C5 failure recovery DOM contracts; no native model or user acceptance. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { pathToFileURL } = require('node:url');
const { JSDOM } = require('jsdom');
const root = path.resolve(__dirname, '..');
const dom = new JSDOM(fs.readFileSync(path.join(root, 'studio/index.html'), 'utf8'), {
  url: 'http://127.0.0.1:8123/', pretendToBeVisual: true,
});
delete global.document; delete global.window;
for (const key of ['location', 'history', 'localStorage', 'Option']) global[key] = dom.window[key];

(async () => {
  const { StudioApp } = await import(pathToFileURL(path.join(root, 'studio/studio.js')).href);
  global.document = dom.window.document; global.window = dom.window;
  const app = new StudioApp({ documentImpl: document });
  const project = { id: 'c5-project', title: 'C5 恢复', workflow: 'objects-v1', protocolVersion: 1 };
  app.projectId = project.id; app.workflow = project.workflow; app.protocolVersion = 1;
  app.handshake = { storeId: 'c5-store' }; app.manager = { projects: [project] };
  app.workspace = { storeId: 'c5-store', projects: [project], proposals: [], packets: [], jobs: [] };
  app.snapshot = { projectId: project.id, kind: 'CONCEPT', publicationRevision: 0, sourceCommit: null };
  const notices = [];
  app.notify = message => notices.push(message); app.queueConceptDraftSave = () => {}; app.queueDraftSave = () => {};
  const question = { id: 'layout', type: 'choice', prompt: '采用哪些位置？',
    options: [{ value: 'precise', label: '采用已列明的精确位置' }] };
  const approved = { id: 'original-plan', projectId: project.id, text: '显示已避雨', assets: [], visualReferences: [],
    discussion: [{ role: 'user', text: '显示已避雨' },
      { role: 'planner', summary: '不要冒充用户要求', questions: [question] },
      { role: 'user', answers: [{ questionId: 'layout', text: 'precise' }] },
      { role: 'user', text: '改成显示这里淋不到雨；角色脚底(160,460)，连续3秒完成。' }] };
  const packet = { id: 'c5-packet', projectId: project.id, jobId: 'c5-job', approvedProposal: approved, assets: [] };
  const job = { id: packet.jobId, projectId: project.id, status: 'CANCELLED', packetId: packet.id,
    productionFailure: { stopReason: 'time_limit', terminationConfirmed: true, nextAction: 'NEW_PLANNING' } };
  app.workspace.packets = [packet]; app.job = job; app.proposal = null; app.stage = 'initial';
  const original = structuredClone(packet), area = document.createElement('section');
  app.renderFailedInitialRecovery(job, area);
  document.body.append(area);
  document.querySelector('#concept').value = approved.text;
  area.querySelector('[data-action="restore-approved-input"]').click();
  const recovered = document.querySelector('#concept').value;
  assert.match(recovered, /显示已避雨/);
  assert.match(recovered, /补充回答：采用哪些位置？\n选择：采用已列明的精确位置/);
  assert.match(recovered, /改成显示这里淋不到雨/);
  assert.ok(!recovered.includes('不要冒充用户要求') && !recovered.includes('precise'));
  assert.deepEqual(packet, original, 'recovery never mutates frozen user history');
  document.querySelector('#concept').value = '真正的新编辑';
  area.querySelector('[data-action="restore-approved-input"]').click();
  assert.equal(document.querySelector('#concept').value, '真正的新编辑');
  assert.match(area.textContent, /制作超时/);

  app.renderJob();
  assert.match(document.querySelector('#job-status').textContent, /制作超时/);
  app.workspace.jobs = [job]; app.renderWorkspace();
  assert.match(document.querySelector('#job-list').textContent, /制作超时/);
  const failedPlan = { ...approved, id: 'timed-plan', status: 'FAILED', publicationRevision: 0, baseCommit: null,
    planningFailure: { code: 'PLANNER_TIMEOUT', retryable: true, terminationConfirmed: true }, createdAt: '2026-10-20T12:00:00Z' };
  app.workspace.proposals = [failedPlan];
  assert.equal(app.pendingProposal(project.id), failedPlan, 'terminal planner failure survives project return');
  app.proposal = failedPlan;
  assert.equal(app.isHistoricalJob(job), true, 'old maker failure stays historical under a newer failed plan');
  const failureRoot = document.createElement('section'); app.renderPlanningFailure(failedPlan, failureRoot);
  assert.match(failureRoot.textContent, /超时/); assert.ok(failureRoot.querySelector('[data-action="retry-planning"]'));
  let command;
  app.sendCommand = async (type, payload) => { command = { type, payload }; return { proposal: { ...failedPlan, id: 'retry-plan', revision: 1 } }; };
  app.renderProposal = () => {}; app.startProposalPolling = () => {};
  await app.retryPlanning(failedPlan, failureRoot.querySelector('[data-action="retry-planning"]'));
  assert.equal(command.type, 'concept.submit'); assert.equal(command.payload.text, recovered);

  const coolingPlan = { ...failedPlan, planningFailure: { code: 'PLANNER_SETUP', retryable: true,
    terminationConfirmed: true, retryNotBefore: new Date(Date.now() + 60000).toISOString(),
    message: '策划沙箱自检未通过，已确认模型未启动；失败详情已保留。' } };
  app.proposal = coolingPlan; command = null;
  const coolingRoot = document.createElement('section'); app.renderPlanningFailure(coolingPlan, coolingRoot);
  assert.match(coolingRoot.textContent, /未能启动/);
  assert.match(coolingRoot.textContent, /冷却/);
  await app.retryPlanning(coolingPlan, coolingRoot.querySelector('[data-action="retry-planning"]'));
  assert.equal(command, null, 'rapid retries during cooldown create no command or session');
  assert.match(notices.at(-1), /冷却/);
  coolingPlan.planningFailure.retryNotBefore = new Date(Date.now() - 1000).toISOString();
  await app.retryPlanning(coolingPlan, coolingRoot.querySelector('[data-action="retry-planning"]'));
  assert.equal(command.type, 'concept.submit', 'explicit retry is available after cooldown');
  assert.equal(command.payload.text, recovered);

  const verification = { status: 'FAIL', checks: [
    { id: 'project.document', status: 'PASS', summary: 'schema valid' },
    { id: 'godot.main_scene_smoke', status: 'FAIL', summary: 'ERROR: Invalid metadata body-size' },
    { id: 'user.acceptance', status: 'SKIPPED', summary: 'not performed' },
  ] };
  const evidence = document.createElement('section'); app.renderEvidence(verification, evidence);
  assert.match(evidence.textContent, /通过 · 对象计划格式/);
  assert.match(evidence.textContent, /失败 · 主场景运行：ERROR: Invalid metadata body-size/);
  assert.match(evidence.textContent, /未执行 · 人工体验验收/);

  app.job = { ...job, status: 'FAILED', productionFailure: undefined, verificationFailure: { terminationConfirmed: true }, verification };
  app.proposal = null; app.renderJob();
  assert.equal(document.querySelector('#job-status').textContent, '验证未通过');
  const repair = { projectId: project.id, jobId: job.id, candidateId: null, kind: 'REPAIR', playable: false,
    repairReason: 'VERIFICATION_FAILED', sourceCommit: 'failed-git', publicationRevision: 0,
    document: { objects: [] }, catalog: { objects: [] }, verification };
  app.snapshot = repair; app.workspace.repairContext = structuredClone(repair); app.stage = 'iteration';
  assert.equal(app.canEnterIteration(), true);
  app.renderWorkbench();
  const summary = document.querySelector('#snapshot-summary');
  assert.match(summary.textContent, /尚无可试玩候选/);
  assert.match(summary.textContent, /这里淋不到雨/);
  summary.querySelector('[data-action="prepare-verification-repair"]').click();
  assert.match(document.querySelector('#edit-text').value, /独立验证失败项/);
  document.querySelector('#edit-text').value = '已编辑的返修说明';
  summary.querySelector('[data-action="prepare-verification-repair"]').click();
  assert.equal(document.querySelector('#edit-text').value, '已编辑的返修说明');
  app.workspace.repairContext.jobId = 'other-job';
  assert.equal(app.canEnterIteration(), false, 'same source without exact repair owner is insufficient');
  const key = app.makeDraftKey(repair);
  assert.notEqual(key, app.makeDraftKey({ ...repair, jobId: 'other-job' }));
  app.projectId = 'other-project';
  document.querySelector('#edit-text').value = '';
  summary.querySelector('[data-action="prepare-verification-repair"]').click();
  assert.equal(document.querySelector('#edit-text').value, '', 'retained UI cannot change another project');
  dom.window.close();
  console.log('Studio C5 recovery contracts passed');
})().catch(error => { console.error(error); dom.window.close(); process.exitCode = 1; });
