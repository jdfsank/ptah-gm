/* C4 user-visible regressions; isolated checks do not constitute user acceptance. */
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
const tick = () => new Promise(resolve => setTimeout(resolve, 0));

(async () => {
  const { StudioApp, DraftStore } = await import(pathToFileURL(path.join(root, 'studio/studio.js')).href);
  global.document = dom.window.document; global.window = dom.window;
  const app = new StudioApp({ documentImpl: document });
  const project = { id: 'cycle-c4', title: '雨巷回归', workflow: 'objects-v1', protocolVersion: 1 };
  app.projectId = project.id; app.workflow = project.workflow; app.protocolVersion = 1;
  app.handshake = { storeId: 'cycle-store' }; app.manager = { projects: [project] };
  app.workspace = { storeId: 'cycle-store', projects: [project], jobs: [] };
  app.notify = () => {}; app.queueConceptDraftSave = () => {}; app.queueDraftSave = () => {};
  app.bind();
  const question = { id: 'initial-layout', type: 'choice', prompt: '是否采用建议布局？',
    options: [{ value: 'use-proposed-layout', label: '采用建议布局' }, { value: 'custom', label: '另行指定位置' }] };
  const boolean = { id: 'sound', type: 'boolean', prompt: '需要音效吗？' };
  const number = { id: 'count', type: 'number', prompt: '额外目标数量' };
  const discussion = [
    { role: 'user', text: '制作雨巷避雨小样' },
    { role: 'planner', text: '不要把策划摘要当成用户原文', questions: [question, boolean, number] },
    { role: 'user', answers: [{ questionId: question.id, text: 'use-proposed-layout' },
      { questionId: boolean.id, value: false }, { questionId: number.id, value: 0 }] },
  ];
  const proposal = { id: 'c4-plan', projectId: project.id, workflow: project.workflow, revision: 1,
    status: 'NEEDS_CLARIFICATION', questions: [question, boolean, number], discussion };
  app.proposal = proposal;
  const packet = { userDiscussion: discussion.filter(turn => turn.role === 'user'), approvedProposal: proposal };
  for (const source of [proposal, packet]) {
    const text = app.visualRequestText(source);
    assert.match(text, /补充回答：是否采用建议布局？\n选择：采用建议布局/);
    assert.match(text, /需要音效吗？\n回答：否/);
    assert.match(text, /额外目标数量\n回答：0/);
    assert.ok(!text.includes('use-proposed-layout') && !text.includes('不要把策划摘要'));
  }
  const revised = structuredClone(proposal);
  revised.discussion.push({ role: 'planner', questions: [{ ...question, prompt: '改用第二版布局？',
    options: [{ value: 'custom', label: '采用第二版' }] }] }, { role: 'user', answers: { 'initial-layout': 'custom' } });
  assert.match(app.visualRequestText(revised), /改用第二版布局？\n选择：采用第二版/);
  assert.match(app.visualRequestText({ userDiscussion: [{ role: 'user', answers: { lost: 'unknown-value' } }] }), /未保留问题说明/);
  assert.match(app.visualRequestText({ discussion: [discussion[1], { role: 'user', answers: { 'initial-layout': 'missing' } }] }), /未找到对应的选项说明/);
  assert.deepEqual(packet.approvedProposal.discussion, discussion, 'display does not mutate frozen input');

  app.renderQuestions(proposal.questions);
  const choose = (id, value) => { const control = document.querySelector(`#questions [name="${id}"]`);
    control.value = value; control.dispatchEvent(new dom.window.Event('change', { bubbles: true })); return control; };
  choose(question.id, 'use-proposed-layout'); choose(boolean.id, 'false'); choose(number.id, '0');
  const record = app.proposalInputs[proposal.id]['1'];
  assert.equal(record.questions[question.id], 'use-proposed-layout');
  assert.equal(record.questionLabels[question.id], '采用建议布局');
  assert.equal(record.questionLabels.sound, '否');
  app.drafts = new DraftStore(null, dom.window.localStorage); app.persistenceOK = true;
  await app.saveConceptDraft();
  const saved = await app.drafts.get(app.conceptDraftKey(project.id));
  assert.deepEqual(saved.proposalInputs[proposal.id]['1'], record, 'raw answers and labels persist together');
  const prior = document.createElement('section');
  app.renderPriorProposalInputs({ ...proposal, revision: 2 }, prior);
  assert.match(prior.textContent, /是否采用建议布局？：采用建议布局/);
  assert.ok(!prior.textContent.includes('use-proposed-layout'));
  const ambiguous = { id: 'typed', type: 'choice', prompt: '精确类型',
    options: [{ value: 1, label: '数字一' }, { value: '1', label: '文字一' }] };
  const ambiguousText = app.visualRequestText({ discussion: [{ role: 'planner', questions: [ambiguous] },
    { role: 'user', answers: [{ questionId: 'typed', text: '1' }] }] });
  assert.match(ambiguousText, /无法确认选项说明/);
  assert.ok(!ambiguousText.includes('文字一') && !ambiguousText.includes('数字一'), 'text-only legacy answers cannot recover an ambiguous original type');
  app.proposal = { ...proposal, revision: 2, questions: [ambiguous] };
  app.renderQuestions([ambiguous]);
  const typed = choose('typed', '__option_0');
  assert.equal(app.proposalRevisionDraft().questions.typed, '__option_0');
  assert.equal(app.proposalRevisionDraft().questionLabels.typed, '数字一');
  assert.equal(app.readChoiceValue(typed), 1);
  choose('typed', '__option_1');
  assert.equal(app.proposalRevisionDraft().questionLabels.typed, '文字一');
  assert.equal(app.readChoiceValue(typed), '1');
  const inputDraft = value => ({ proposalInputs: { 'c4-plan': { '2': {
    questions: { typed: value }, questionLabels: { typed: '相同显示文字' }, questionPrompts: { typed: '精确类型' },
  } } } });
  const comparison = app.renderDraftSemanticComparison(inputDraft('__option_0'), inputDraft('__option_1'));
  assert.match(comparison.textContent, /内容变化/);
  assert.ok(comparison.textContent.includes('__option_0') && comparison.textContent.includes('__option_1'), 'duplicate display labels cannot hide different stored answers');
  choose('typed', '');
  assert.equal(app.proposalRevisionDraft().questionLabels.typed, undefined);

  const objects = [
    { id: 'scene', kind: 'scene', name: '雨巷', fields: [], workbench: { role: 'scene', bounds: [960, 540] } },
    { id: 'roof-definition', kind: 'entity', name: '屋檐定义', fields: [], workbench: { role: 'definition', size: [192, 50], anchor: [0, 0], lock: 'free' } },
    { id: 'roof', kind: 'entity', name: '暖光屋檐', fields: [], workbench: { role: 'instance', sceneId: 'scene',
      definitionId: 'roof-definition', position: [660, 160], size: [192, 50], anchor: [0, 0], lock: 'free' } },
  ];
  app.snapshot = { projectId: project.id, workflow: project.workflow, publicationRevision: 1,
    sourceCommit: 'c4-base', catalog: { objects }, document: { objects } };
  const feedback = [{ feedbackId: 'f1', objectId: null, category: 'general', message: '完成后显示新文案' }];
  app.proposal = { ...proposal, status: 'READY', revision: 2, questions: [], document: { objects }, changeRequest: { feedback } };
  app.renderReviewedPlan({ reviewedPlanRef: 'review-c4', plan: { ...app.proposal, feedback } });
  const reviewed = document.querySelector('#reviewed-plan-content').textContent;
  assert.match(reviewed, /项目 · 一般：完成后显示新文案/);
  assert.ok(!reviewed.includes('null · general'));
  assert.equal(app.feedbackDescription({ objectId: 'roof', category: 'visual', message: '暖一些' }, objects), '暖光屋檐 · 视觉：暖一些');
  app.job = { id: 'old-job', projectId: project.id, status: 'PUBLISHED', experienceDecisions: [{ feedbackId: 'f1', status: 'resolved', reason: '已真实试玩此文案' }],
    candidate: { id: 'old-candidate', projectId: project.id, jobId: 'old-job', candidateCommit: 'old-source', experienceFeedback: feedback } };
  app.isHistoricalJob = () => true; app.renderCandidateVisual = () => {}; app.renderJob();
  assert.match(document.querySelector('#candidate-area').textContent, /项目 · 一般：完成后显示新文案 · 已解决/);

  app.observations = { attemptId: 'preview-c4', taskKind: 'preview', status: 'COMPLETED',
    lastActivity: { activityKind: 'preview_started', summary: 'Godot preview process started in an isolated artifact copy.' } };
  app.projectView = { projectId: project.id, step: 'accepted' };
  app.previews = [{ id: 'preview', projectId: project.id, attemptId: 'preview-c4', status: 'STOPPED' }];
  app.renderExecutionMonitor(); await tick();
  const monitor = document.querySelector('#execution-monitor-content').textContent;
  assert.ok(monitor.includes('本候选预览已停止') && monitor.includes('Godot 已在隔离的候选副本中启动预览。'));
  assert.ok(!monitor.includes('Godot preview process started'));

  app.stage = 'iteration'; app.currentProject = () => project;
  app.projectView = { projectId: project.id, allowedActions: ['iteration.submit'], proposals: [], jobs: [], packets: [], previews: [] };
  app.targetNotes = {}; app.structuralProposals = []; app.workbenchResults = [];
  app.selectedObjectId = 'roof'; app.renderWorkbench(); app.legacyWorkbench.resetHistory();
  const viewport = document.querySelector('.workbench-coordinate-viewport');
  const canvas = viewport.querySelector('.workbench-coordinate-canvas');
  assert.equal(viewport.tabIndex, 0); assert.equal(viewport.getAttribute('role'), 'region');
  assert.match(viewport.getAttribute('aria-label'), /横向滚动/);
  assert.equal(canvas.style.aspectRatio, '960 / 540');
  const roof = canvas.querySelector('[data-object-id="roof"]');
  assert.equal(roof.style.left, '68.75%');
  canvas.getBoundingClientRect = () => ({ left: -200, top: 0, width: 500, height: 281.25 });
  const wb = app.legacyWorkbench;
  wb.beginDrag({ target: roof, isPrimary: true, button: 0, pointerId: 7, preventDefault() {} });
  assert.ok(wb.drag, 'wrapping does not break the existing canvas ancestor');
  wb.moveDrag({ pointerId: 7, clientX: 133.333333, clientY: 83.333333 });
  assert.deepEqual(wb.drag.last, [640, 160], 'drag uses the scrolled canvas position');
  wb.endDrag({ pointerId: 7, type: 'pointercancel' });
  assert.equal(app.structuralProposals.length, 0, 'cancelled drag does not submit a change');
  document.querySelector('.workbench-coordinate-viewport').scrollLeft = 244;
  wb.renderCanvas();
  assert.equal(document.querySelector('.workbench-coordinate-viewport').scrollLeft, 244, 'same-scene selection redraw must keep the right-hand objects visible');
  if (process.env.C4_LAYOUT_OUTPUT) fs.writeFileSync(process.env.C4_LAYOUT_OUTPUT, JSON.stringify({ html: document.querySelector('#workbench-panel').innerHTML }));
  app.destroy(); dom.window.close();
  console.log('PASS C4 regressions: Chinese clarification and persisted labels, exact choice values, readable feedback/history, truthful preview terminal state, scrolled coordinate drag');
})().catch(error => { console.error(error.stack || error); dom.window.close(); process.exitCode = 1; });
