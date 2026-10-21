#!/usr/bin/env node
/* Focused regressions for target-scoped intent, revision inputs, uploads, and plan review. */
const fs = require('node:fs');
const path = require('node:path');
const strict = require('node:assert/strict');
const { pathToFileURL } = require('node:url');
let JSDOM;
try { ({ JSDOM } = require('jsdom')); } catch { console.log('SKIP Studio intent input QA: jsdom is unavailable.'); process.exit(0); }

const root = path.resolve(__dirname, '..');
const dom = new JSDOM(fs.readFileSync(path.join(root, 'studio/index.html'), 'utf8'), {
  url: 'http://127.0.0.1:8123/studio/', pretendToBeVisual: true,
});

(async () => {
  const priorDocument = global.document;
  const priorLocation = global.location;
  const priorHistory = global.history;
  global.document = dom.window.document;
  global.location = dom.window.location;
  global.history = dom.window.history;
  global.Option = dom.window.Option;
  const { StudioApp } = await import(pathToFileURL(path.join(root, 'studio/studio.js')).href);
  const app = new StudioApp({ fetchImpl: async () => { throw new Error('Focused UI QA must not contact a service.'); }, documentImpl: dom.window.document });
  const writes = new Map();
  app.drafts = {
    put: async record => { writes.set(record.key, structuredClone(record)); return record; },
    get: async key => writes.get(key) || null,
    delete: async key => writes.delete(key),
  };
  app.persistenceOK = true;
  app.projectId = 'intent-project'; app.stage = 'iteration'; app.workflow = 'objects-v1';
  app.workspace = { storeId: 'intent-store', projects: [{ id: app.projectId, protocolVersion: 1 }] };
  app.snapshot = {
    id: 'snapshot-1', projectId: app.projectId, publicationRevision: 4, sourceCommit: 'git-4', workflow: 'objects-v1', playable: true,
    catalog: { objects: [
      { id: 'player', name: '玩家', fields: [{ id: 'speed', label: '速度', type: 'scalar', value: 220 }] },
      { id: 'enemy', name: '敌人', fields: [{ id: 'speed', label: '速度', type: 'scalar', value: 180 }] },
    ] },
  };
  app.capabilities = { fields: [
    { id: 'player.speed', objectId: 'player', fieldId: 'speed', type: 'scalar', value: 220, editable: true },
    { id: 'enemy.speed', objectId: 'enemy', fieldId: 'speed', type: 'scalar', value: 180, editable: true },
  ] };
  app.draftKey = app.makeDraftKey(app.snapshot);
  app.readiness = { ready: true };
  const notices = [];
  app.notify = message => notices.push(message);
  app.renderWorkflowStatus = () => {};
  app.bind();

  // A2: unsent feedback stays with its object while selection changes, and submit is gated.
  app.selectedObjectId = 'player'; app.loadFeedbackInputForCurrentTarget();
  document.querySelector('#feedback-message').value = '玩家只需要更平滑地转向';
  document.querySelector('#feedback-category').value = 'behavior';
  app.saveFeedbackInputForCurrentTarget();
  app.selectedObjectId = 'enemy'; app.loadFeedbackInputForCurrentTarget();
  strict.equal(document.querySelector('#feedback-message').value, '', 'switching targets must not display another object’s pending text');
  document.querySelector('#feedback-message').value = '敌人需要更清楚的受击提示';
  document.querySelector('#feedback-category').value = 'visual';
  app.saveFeedbackInputForCurrentTarget();
  app.selectedObjectId = 'player'; app.loadFeedbackInputForCurrentTarget();
  strict.equal(document.querySelector('#feedback-message').value, '玩家只需要更平滑地转向');
  strict.equal(document.querySelector('#feedback-category').value, 'behavior');
  const postsBeforePendingSubmit = notices.length;
  await app.submitIteration();
  strict.match(notices.at(-1), /尚未加入本轮/);
  strict.equal(notices.length, postsBeforePendingSubmit + 1);
  strict.equal(app.feedback.length, 0, 'pending feedback remains a draft until explicitly added');
  app.addFeedback();
  strict.equal(app.feedback[0].objectId, 'player');
  strict.equal(app.feedback[0].message, '玩家只需要更平滑地转向');
  strict.equal(app.feedback[0].category, 'behavior');
  strict.equal(app.feedbackInputs.player, undefined, 'adding a feedback item clears only the active target input');
  strict.equal(app.feedbackInputs.enemy.message, '敌人需要更清楚的受击提示', 'other target drafts must remain intact');
  app.legacyUnboundFeedback = { message: '旧版意见没有目标', category: 'general' };
  strict.equal(app.hasUnsubmittedDraft({ legacyUnboundFeedback: app.legacyUnboundFeedback }), true);
  app.renderRebasePreview({
    oldSnapshot: { publicationRevision: 3, sourceCommit: 'git-3', projectId: app.projectId },
    nextSnapshot: app.snapshot, persistenceOK: true,
    draft: { text: '', feedback: [], values: {}, fields: {}, targetNotes: {}, structuralProposals: [],
      feedbackInputs: { enemy: { message: '待添加受击提示', category: 'visual' } },
      legacyUnboundFeedback: { message: '目标未知的旧意见', category: 'general' },
      proposalInputs: { 'proposal-1': { '2': { questions: { q1: '保留每关三个奖励' }, questionPrompts: { q1: '要保留哪个规则？' } } } } },
  });
  const rebasePreview = document.querySelector('#rebase-content').textContent;
  strict.match(rebasePreview, /待添加受击提示/);
  strict.match(rebasePreview, /目标未知的旧意见/);
  strict.match(rebasePreview, /保留每关三个奖励/);
  app.selectedObjectId = null;
  await app.submitIteration();
  strict.match(notices.at(-1), /目标不明/);
  app.selectedObjectId = 'player';

  // A6: question and READY supplement text is stored under its exact proposal revision.
  app.proposal = { id: 'proposal-1', projectId: app.projectId, revision: 2, status: 'NEEDS_CLARIFICATION', questions: [{ id: 'q1', prompt: '要保留哪个规则？', type: 'text' }] };
  app.renderQuestions(app.proposal.questions);
  const answer = document.querySelector('#questions [name="q1"]');
  answer.value = '保留每关三个奖励';
  answer.dispatchEvent(new dom.window.Event('input', { bubbles: true }));
  strict.equal(app.proposalInputs['proposal-1']['2'].questions.q1, '保留每关三个奖励');
  app.proposal = { ...app.proposal, revision: 3, questions: [{ id: 'q1', prompt: '要保留哪个规则？', type: 'text' }] };
  app.renderQuestions(app.proposal.questions);
  strict.equal(document.querySelector('#questions [name="q1"]').value, '', 'a new revision must not inherit the previous answer');
  strict.match(document.querySelector('#questions').textContent, /保留每关三个奖励/);
  strict.equal(app.hasUnsubmittedDraft({ proposalInputs: app.proposalInputs }), true);
  app.usesV1Commands = () => true;
  app.proposal = { id: 'proposal-1', projectId: app.projectId, revision: 3, status: 'READY', questions: [] };
  app.renderReadyRevision(app.proposal, document.querySelector('#proposal-content'));
  const supplement = document.querySelector('#ready-supplement');
  supplement.value = '验收时确认奖励数量不变';
  supplement.dispatchEvent(new dom.window.Event('input', { bubbles: true }));
  strict.equal(app.proposalInputs['proposal-1']['3'].readySupplement, '验收时确认奖励数量不变');
  app.proposal = { ...app.proposal, revision: 4, status: 'NEEDS_CLARIFICATION' };
  const priorInputs = document.createElement('div');
  app.renderPriorProposalInputs(app.proposal, priorInputs);
  strict.match(priorInputs.textContent, /验收时确认奖励数量不变/);
  strict.equal(app.proposalRevisionDraft(app.proposal, true).readySupplement, '', 'the new revision must have an independent supplement field');

  // A7: one rejected file must not abort later uploads; successful files stay visible and saved.
  const priorFileReader = global.FileReader;
  global.FileReader = class {
    readAsDataURL() { this.result = 'data:image/png;base64,YQ=='; this.onload?.(); }
  };
  const uploads = [];
  app.saveConceptDraft = async () => true;
  app.request = async (_route, { body }) => {
    uploads.push(body.name);
    if (body.name === 'retry.png') throw new Error('服务暂时拒绝上传');
    return { asset: { id: `asset-${body.name}`, name: body.name, purpose: body.purpose } };
  };
  const files = [
    { name: 'first.png', type: 'image/png', size: 10 },
    { name: 'unsupported.gif', type: 'image/gif', size: 10 },
    { name: 'retry.png', type: 'image/png', size: 10 },
    { name: 'last.png', type: 'image/png', size: 10 },
  ];
  await app.uploadImages(files);
  strict.deepEqual(uploads, ['first.png', 'retry.png', 'last.png']);
  strict.deepEqual(app.assets.map(asset => asset.name), ['first.png', 'last.png']);
  strict.equal(document.querySelectorAll('#image-list .asset-chip').length, 2);
  strict.match(notices.at(-1), /unsupported\.gif/);
  strict.match(notices.at(-1), /retry\.png/);
  strict.match(notices.at(-1), /已上传并显示 2 张/);
  if (priorFileReader === undefined) delete global.FileReader; else global.FileReader = priorFileReader;

  // P3: show each available planning dimension and label absent source data explicitly.
  const review = document.createElement('div');
  app.renderPlanReviewCard(review, {
    userRequest: '提升玩家转向响应',
    changeRequest: { fields: [{ objectId: 'player', fieldId: 'speed', value: 250 }], feedback: [{ objectId: 'enemy', category: 'visual', message: '受击时更醒目' }], operations: [{ kind: 'new-scene', sceneId: 'bonus-room', name: '奖励房间' }] },
    summary: '只调整玩家转向，并新增奖励房间。',
    preservationRequirements: ['敌人数量保持不变'],
    acceptance: ['验证玩家转向', '确认奖励数量不变'],
  });
  for (const label of ['你的要求', 'AI 准备怎样做', '影响谁', '保持什么', '怎样验证']) strict.ok(review.textContent.includes(label));
  strict.match(review.textContent, /提升玩家转向响应/);
  strict.match(review.textContent, /敌人数量保持不变/);
  const discussionReview = document.createElement('div');
  app.renderPlanReviewCard(discussionReview, {
    text: '奖励更醒目',
    discussion: [
      { role: 'user', text: '奖励更醒目' },
      { role: 'planner', summary: 'AI摘要不能成为用户原文' },
      { role: 'user', text: '数量保持不变', answers: { scope: '只改当前实例' } },
    ],
  });
  const requestSection = [...discussionReview.querySelectorAll('.plan-review-item')].find(section => section.querySelector('h4')?.textContent === '你的要求');
  strict.equal(requestSection.textContent.split('奖励更醒目').length - 1, 1, 'the initial user turn must not duplicate the request');
  strict.match(requestSection.textContent, /数量保持不变/);
  strict.match(requestSection.textContent, /补充回答：问题 scope（未保留问题说明）\n回答：只改当前实例/);
  strict.doesNotMatch(requestSection.textContent, /AI摘要不能成为用户原文|planner/);
  const missing = document.createElement('div'); app.renderPlanReviewCard(missing, { tasks: [{ id: 'inspect-only', description: '检查目标', objectIds: ['player', 'movement-input'] }] });
  strict.match(missing.textContent, /没有提供保持条件或可关联的需求原文/);
  strict.match(missing.textContent, /没有提供明确的验收或验证条件/);
  strict.match(missing.textContent, /不能从任务关联对象推断哪些对象会改变/);
  strict.match(missing.textContent, /任务关联对象（包含检查对象，不代表都会改变）/);

  // Project the exact field-iteration service record and the resulting candidate facts.
  const fieldEvidence = JSON.parse(fs.readFileSync(path.join(root, '../evidence/workflow/studio-legacy-replication-20261014/real-iteration-field.json'), 'utf8'));
  const fieldProposal = {
    ...fieldEvidence.proposal,
    document: fieldEvidence.job.candidate.document,
    requirements: fieldEvidence.job.candidate.document.requirements,
    objectChanges: fieldEvidence.job.candidate.objectChanges,
  };
  const fieldReview = document.createElement('div'); app.renderPlanReviewCard(fieldReview, fieldProposal);
  strict.match(fieldReview.textContent, /用户请求目标：赌场游侠（player）/);
  strict.match(fieldReview.textContent, /player · move-speed → 250/);
  strict.match(fieldReview.textContent, /方案中的对象差异记录：modified · 赌场游侠（player） · 属性差异 移动速度：240 → 250/);
  const fieldImpact = [...fieldReview.querySelectorAll('.plan-review-item')].find(section => section.querySelector('h4')?.textContent === '影响谁');
  const fieldDiffLine = [...fieldImpact.querySelectorAll('p')].find(line => line.textContent.startsWith('方案中的对象差异记录：'));
  strict.equal(fieldDiffLine.textContent, '方案中的对象差异记录：modified · 赌场游侠（player） · 属性差异 移动速度：240 → 250');
  strict.match(fieldReview.textContent, /任务关联对象（包含检查对象，不代表都会改变）/);
  strict.match(fieldReview.textContent, /StudioRuntime\.object_value\(\)/);
  strict.match(fieldReview.textContent, /WASD与方向键的基础移动速度是否为250像素\/秒/);
  strict.match(fieldReview.textContent, /architecture · 所有冻结字段/);
  strict.match(fieldReview.textContent, /movement-only · WASD与方向键均可移动/);
  strict.match(fieldReview.textContent, /growth-choices · 拾取筹码积累经验/);
  strict.match(fieldReview.textContent, /验证方式：人工体验验收/);
  strict.doesNotMatch(fieldReview.textContent, /supported-scope|run-loop ·/);
  const structuredTaskReview = document.createElement('div'); app.renderPlanReviewCard(structuredTaskReview, {
    tasks: [{ id: 'task-x', description: '任务原文', constraints: ['不改其他对象'], acceptance: ['速度保持250'], verification: ['人工运行检查'] }],
  });
  for (const value of ['任务原文', '任务约束：不改其他对象', '任务验收条件：速度保持250', '任务验证方式：人工运行检查']) strict.ok(structuredTaskReview.textContent.includes(value));

  const languageEvidence = JSON.parse(fs.readFileSync(path.join(root, '../evidence/workflow/studio-legacy-replication-20261014/real-iteration-language.json'), 'utf8'));
  const decisionReview = document.createElement('div'); app.renderPlanReviewCard(decisionReview, languageEvidence.retry);
  strict.match(decisionReview.textContent, /逐条反馈处理决定：[^\n]*adopted/);
  strict.match(decisionReview.textContent, /反馈明确指定失败结算文案及必须保留的按钮和信息/);

  // Keep object links and file bindings available without crowding the normal details and fields.
  app.snapshot.catalog.objects[0] = {
    ...app.snapshot.catalog.objects[0], description: '玩家对象说明', parentId: 'project-casino',
    relations: [{ type: 'has_scene_instance', targetId: 'player-arena-instance' }],
    sourceBindings: ['scenes/player.tscn', 'scripts/simulation/player.gd'],
  };
  app.selectedObjectId = 'player';
  app.renderDynamicFields(app.objectItems(), app.capabilities);
  app.renderObjectDetail();
  const objectDetail = document.querySelector('#object-detail');
  const associations = objectDetail.querySelector('details.object-associations');
  strict.ok(associations, 'object links should be available in a disclosure');
  strict.equal(associations.open, false, 'object links should be collapsed by default');
  strict.equal(associations.querySelector('summary').textContent, '查看对象关联与源文件');
  strict.match(associations.textContent, /父对象：project-casino/);
  strict.match(associations.textContent, /has_scene_instance → player-arena-instance/);
  strict.match(associations.textContent, /scenes\/player\.tscn/);
  strict.match(objectDetail.querySelector('p').textContent, /玩家对象说明/);
  strict.ok(document.querySelector('#dynamic-fields [data-field-id="player.speed"]'), 'editable properties should remain visible outside the collapsed links');

  // C5: the status line leads with the current action and does not repeat the project heading.
  app.projectView = { phase: 'iteration', step: 'accepted', attention: 'user' };
  app.streamFresh = true; app.activity = null;
  app.workspace.projects[0].title = 'Project Casino';
  StudioApp.prototype.renderWorkflowStatus.call(app);
  const workflowStatus = document.querySelector('#workflow-status-copy');
  strict.equal(workflowStatus.textContent, '进入迭代工作台 · 状态流实时');
  strict.doesNotMatch(workflowStatus.textContent, /Project Casino|迭代工作台 · 进入迭代工作台/);
  app.activity = '正在保存方案补充';
  StudioApp.prototype.renderWorkflowStatus.call(app);
  strict.equal(workflowStatus.textContent, '正在保存方案补充 · 迭代工作台 · 状态流实时', 'active work should lead while retaining the current phase');

  app.destroy(); dom.window.close();
  if (priorDocument === undefined) delete global.document; else global.document = priorDocument;
  if (priorLocation === undefined) delete global.location; else global.location = priorLocation;
  if (priorHistory === undefined) delete global.history; else global.history = priorHistory;
  console.log('PASS Studio intent input QA: target-scoped feedback, proposal revisions, partial uploads, and pre-production review.');
})().catch(error => { console.error(error); process.exitCode = 1; });
