#!/usr/bin/env node
/* Focused regression coverage for the user-facing workbench fixes UR01/04/05/06. */
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const { pathToFileURL } = require('node:url');
let JSDOM;
try { ({ JSDOM } = require('jsdom')); }
catch { console.log('SKIP Studio user UX workbench QA: jsdom is unavailable.'); process.exit(0); }

const root = path.resolve(__dirname, '..');
const dom = new JSDOM(fs.readFileSync(path.join(root, 'studio/index.html'), 'utf8'), {
  url: 'http://127.0.0.1:8123/studio/?project=user-ux-workbench&stage=iteration', pretendToBeVisual: true,
});
const savedGlobals = Object.fromEntries(['document', 'FormData', 'Option', 'localStorage', 'location', 'history'].map(key => [key, global[key]]));
global.document = dom.window.document;
global.FormData = dom.window.FormData;
global.Option = dom.window.Option;
global.localStorage = dom.window.localStorage;
global.location = dom.window.location;
global.history = dom.window.history;

const clone = value => structuredClone(value);
const field = selector => dom.window.document.querySelector(selector);
const tick = () => new Promise(resolve => setTimeout(resolve, 0));

function installDialogPolyfills() {
  for (const dialog of dom.window.document.querySelectorAll('dialog')) {
    dialog.showModal = function () { this.open = true; };
    dialog.close = function () {
      this.open = false;
      this.dispatchEvent(new dom.window.Event('close'));
    };
  }
}

function makeApp() {
  let id = 0;
  const app = {
    projectId: 'ux-project',
    snapshot: { projectId: 'ux-project', publicationRevision: 6, sourceCommit: 'git-ux-base' },
    draftKey: 'ux-project:revision-6',
    handshake: { storeId: 'ux-store' },
    selectedObjectId: null,
    targetNotes: {},
    structuralProposals: [],
    workbenchResults: [],
    objectList: [],
    fieldDraftValues: {},
    feedback: [],
    feedbackInputs: {},
    proposalInputs: {},
    legacyUnboundFeedback: null,
    dirtyFields: new Set(),
    notify() {},
    showDraftState(message) { this.actionStatus = message; },
    persistenceOK: true,
    captureVisibleFields() {},
    saveDraft: async () => true,
    queueDraftSave() {},
    newFeedbackId: () => `ux-feedback-${++id}`,
    objectItems() { return this.objectList; },
    allCapabilities() { return []; },
    splitCapability(capability) { return capability; },
    capabilityEditable(capability) { return capability.editable === true; },
    currentProject() { return { id: this.projectId, title: '用户体验夹具' }; },
    selectedJobForProject() { return null; },
    captureSelectionContext() { return { projectId: this.projectId, selectedObjectId: this.selectedObjectId || null }; },
    selectionContextMatches(context) {
      return context.projectId === this.projectId && context.selectedObjectId === (this.selectedObjectId || null);
    },
    objectsWorkflow() { return true; },
    buildIterationIntent() {
      return { text: field('#edit-text')?.value || '', changeRequest: { fields: [], feedback: [] } };
    },
    pendingCommandRecord() { return null; },
    captureIterationSubmissionDraft(text, changeRequest) {
      return {
        text, changeRequest: clone(changeRequest), targetNotes: clone(this.targetNotes),
        structuralProposals: clone(this.structuralProposals), fields: clone(this.fieldDraftValues),
      };
    },
    renderObjectDetail() {},
    renderProposal() {},
    startProposalPolling() {},
    selectJob() {},
    clearSubmittedIterationDraft() { return true; },
  };
  return app;
}

(async () => {
  installDialogPolyfills();
  const { LegacyWorkbench } = await import(pathToFileURL(path.join(root, 'studio/workbench.js')).href);
  const app = makeApp();
  const wb = new LegacyWorkbench(app);
  wb.bind();

  // UR01: all five report outcomes remain distinguishable and are bound to the active dialog session.
  const report = field('#workbench-report-dialog');
  field('#edit-text').value = '先保留这条项目意见';
  wb.openReport();
  const statusLabels = {
    blocked: '未发送', rejected: '服务明确拒绝', unknown: '结果待核实',
    submitted: '已提交', stale: '项目或版本上下文已变化',
  };
  const firstSession = wb.reportSessionSequence;
  for (const [status, label] of Object.entries(statusLabels)) {
    wb.submissionOutcome = {
      status, type: 'iteration.submit', projectId: app.projectId,
      publicationRevision: app.snapshot.publicationRevision, sourceCommit: app.snapshot.sourceCommit,
      dialogSequence: firstSession, reason: `受控原因：${status}`,
    };
    wb.renderSubmissionStatus();
    assert.equal(field('#workbench-submission-status').dataset.status, status, `${status} is exposed as its own report outcome`);
    assert.match(field('#workbench-submission-status').textContent, new RegExp(label));
    assert.match(field('#workbench-submission-status').textContent, new RegExp(`受控原因：${status}`), 'the report keeps the original outcome reason');
  }
  const priorOutcome = wb.submissionOutcome;
  wb.closeWorkbenchDialog(report);
  wb.renderSubmissionStatus();
  assert(field('#workbench-submission-status').classList.contains('hidden'), 'a closed report session hides its old outcome');
  wb.openReport();
  assert(wb.reportSessionSequence > firstSession, 'reopening the report creates a new session');
  assert.equal(wb.submissionOutcome.dialogSequence, wb.reportSessionSequence, 'a matching outcome is carried into the new report session');
  wb.renderSubmissionStatus();
  assert(!field('#workbench-submission-status').classList.contains('hidden'), 'the matching outcome remains available after reopening');

  // An unknown receipt is reconciled against its original command and workspace, while later edits survive.
  wb.submissionOutcome = null;
  field('#edit-text').value = '未知回执对应的原始意见';
  wb.persistCurrentNote();
  wb.refreshReport(true);
  app.submitIteration = async () => ({
    status: 'unknown', type: 'iteration.submit', projectId: app.projectId,
    commandId: 'ux-command-1', storeId: 'ux-store', reason: '发送后连接中断',
  });
  await wb.confirmReport();
  const unknown = wb.submissionOutcome;
  assert.equal(unknown.status, 'unknown');
  assert.equal(unknown.commandId, 'ux-command-1');
  const pendingKey = wb.reportDraftKey(app.projectId, 'ux-store', 'ux-command-1');
  assert(wb.pendingReportDrafts.has(pendingKey), 'the submitted draft snapshot is retained while the result is unknown');
  assert.equal(app.targetNotes.__project__.text, '未知回执对应的原始意见', 'unknown results do not clear the original draft');

  app.reconcilePendingCommand = async () => ({
    status: 'submitted', type: 'iteration.submit', projectId: app.projectId,
    commandId: 'ux-command-1', storeId: 'different-workspace', reason: '身份错配回执',
  });
  await wb.reconcileSubmission(unknown);
  assert.equal(wb.submissionOutcome.status, 'unknown', 'a receipt from a different workspace cannot resolve the command');
  assert.match(wb.submissionOutcome.reason, /命令 ID 和工作区匹配/);
  assert(wb.pendingReportDrafts.has(pendingKey), 'an identity mismatch keeps the original submission snapshot');

  field('#edit-text').value = '未知回执之后新写的意见';
  wb.persistCurrentNote();
  let clearDraftCalls = 0;
  app.clearSubmittedIterationDraft = submitted => {
    clearDraftCalls += 1;
    assert.equal(submitted.targetNotes.__project__.text, '未知回执对应的原始意见');
    return true; // The host reports that edits made after submission remain in the working draft.
  };
  app.reconcilePendingCommand = async (type, projectId) => ({
    status: 'submitted', type, projectId, commandId: 'ux-command-1', storeId: 'ux-store', reason: '原命令已确认接收',
  });
  await wb.reconcileSubmission(wb.submissionOutcome);
  assert.equal(clearDraftCalls, 1, 'only a matching receipt reaches submitted-draft cleanup');
  assert.equal(wb.submissionOutcome.status, 'submitted');
  assert.equal(wb.submissionOutcome.hasPostSubmitEdits, true);
  assert.equal(app.targetNotes.__project__.text, '未知回执之后新写的意见', 'edits made after submission stay in the current draft');
  assert(!wb.pendingReportDrafts.has(pendingKey), 'the matched command snapshot is retired after reconciliation');

  // A late receipt from an earlier modal session cannot clear a newer draft.
  wb.refreshReport(true);
  app.submitIteration = async () => ({
    status: 'unknown', type: 'iteration.submit', projectId: app.projectId,
    commandId: 'ux-command-2', storeId: 'ux-store', reason: '等待对账',
  });
  await wb.confirmReport();
  const staleSessionOutcome = wb.submissionOutcome;
  let resolveLateReceipt;
  app.reconcilePendingCommand = () => new Promise(resolve => { resolveLateReceipt = resolve; });
  const reconciliation = wb.reconcileSubmission(staleSessionOutcome);
  await tick();
  wb.closeWorkbenchDialog(report);
  wb.openReport();
  field('#edit-text').value = '新会话中的另一条意见';
  wb.persistCurrentNote();
  resolveLateReceipt({
    status: 'submitted', type: 'iteration.submit', projectId: app.projectId,
    commandId: 'ux-command-2', storeId: 'ux-store', reason: '迟到的成功回执',
  });
  await reconciliation;
  assert.equal(clearDraftCalls, 1, 'the late receipt is ignored after its report session ends');
  assert.equal(app.targetNotes.__project__.text, '新会话中的另一条意见', 'a late result cannot remove the new session draft');

  // UR04: target range explains the selected instance, shared definition, declared capabilities, and lifecycle facts.
  app.objectList = [
    { id: 'guard-definition', kind: 'entity', name: '守卫定义', workbench: { role: 'definition' } },
    { id: 'guard-one', kind: 'entity', name: '场景守卫', workbench: { role: 'instance', definitionId: 'guard-definition', presence: 'runtime-generated', lifecycle: 'per-round' } },
    { id: 'guard-two', kind: 'entity', name: '另一只守卫', workbench: { role: 'instance', definitionId: 'guard-definition' } },
  ];
  app.allCapabilities = () => [];
  const targetFacts = wb.targetRangeFacts(app.objectList[1]);
  assert.match(targetFacts.target, /场景实例.*场景守卫.*guard-one/);
  assert.match(targetFacts.impact, /意见目标只指向此场景实例/);
  assert.match(targetFacts.impact, /关联共享定义“守卫定义”/);
  assert.match(targetFacts.impact, /共见 2 个关联实例/);
  assert.match(targetFacts.impact, /未声明此实例独立可编辑字段/);
  assert.match(targetFacts.impact, /仍须明确影响对象/);
  assert.equal(targetFacts.presence, '运行时生成');
  assert.equal(targetFacts.lifecycle, '每轮');
  app.allCapabilities = () => [{ id: 'guard-one.tint', objectId: 'guard-one', fieldId: 'tint', label: '色调', editable: true }];
  const editableFacts = wb.targetRangeFacts(app.objectList[1]);
  assert.match(editableFacts.impact, /列出此实例独立可编辑字段：色调/);

  // UR05: revisions of one proposal remain separate; failed jobs without candidates expose only their job route.
  app.projectId = 'ux-project';
  app.proposal = { id: 'proposal-ux', projectId: app.projectId, revision: 2 };
  app.projectView = null; app.job = null; app.workspace = { jobs: [] };
  const fullOriginalText = '新修订的完整原文需要保留。'.repeat(32);
  app.workbenchResults = [
    { itemId: 'revision-one-item', kind: 'feedback', objectId: 'guard-one', originalText: '旧修订意见', status: 'completed', proposalId: 'proposal-ux', proposalRevision: 1, jobId: 'job-ux-1', candidateId: 'candidate-ux-1' },
    { itemId: 'revision-two-failure', kind: 'feedback', objectId: 'guard-one', originalText: fullOriginalText, status: 'failed', reason: 'Agent 处理失败', proposalId: 'proposal-ux', proposalRevision: 2, jobId: 'job-ux-2' },
  ];
  wb.renderResults();
  const resultRoot = field('#workbench-results-list');
  const resultGroups = [...resultRoot.querySelectorAll('details[data-result-group]')];
  assert.equal(resultGroups.length, 2, 'one proposal with two revisions renders two result groups');
  assert(resultGroups.some(group => /修订 1/.test(group.textContent)));
  const currentGroup = resultGroups.find(group => group.classList.contains('workbench-result-group-current'));
  assert(currentGroup && /修订 2/.test(currentGroup.textContent), 'the current proposal revision is the only highlighted group');
  assert.match(currentGroup.querySelector('summary').textContent, /失败 1/);
  const failedCard = currentGroup.querySelector('.workbench-result-card');
  assert.match(failedCard.textContent, /Agent 处理失败/);
  assert.match(failedCard.textContent, /候选 ID：身份未提供/);
  assert([...failedCard.querySelectorAll('button')].some(button => button.textContent === '查看本轮处理状态'), 'a failed job without a candidate still exposes its job status route');
  assert(![...failedCard.querySelectorAll('button')].some(button => button.textContent === '查看此候选与试玩入口'), 'a failed job without a candidate does not show a candidate-play route');
  const stableGroup = currentGroup, rawDetails = failedCard.querySelector('.workbench-result-raw');
  assert(rawDetails && !rawDetails.open, 'the full original text details are collapsed by default');
  assert(rawDetails.textContent.includes(fullOriginalText), 'the collapsed details retain the complete original text');
  wb.renderResults();
  assert.strictEqual(resultRoot.querySelector('details[data-result-group].workbench-result-group-current'), stableGroup, 'an unchanged poll preserves the existing result DOM nodes');
  rawDetails.open = true;
  app.workbenchResults = app.workbenchResults.map(result => result.itemId === 'revision-two-failure'
    ? { ...result, reason: 'Agent 在重试后仍处理失败' } : result);
  wb.renderResults();
  const updatedCurrentGroup = resultRoot.querySelector('details[data-result-group].workbench-result-group-current');
  const updatedRawDetails = updatedCurrentGroup.querySelector('.workbench-result-raw');
  assert(updatedRawDetails.open, 'updating result data preserves the expanded original-text details for the stable item');
  assert(updatedRawDetails.textContent.includes(fullOriginalText), 'the updated result keeps the same full original text');

  // Keep the review job reachable in iteration and put the editable workbench before proposal/job details.
  const reviewJob = { id: 'job-review-route', projectId: app.projectId, status: 'READY_FOR_REVIEW' };
  app.projectView = { projectId: app.projectId, job: reviewJob };
  app.workspace = { jobs: [reviewJob] }; app.job = reviewJob;
  wb.syncIterationLayout(true);
  const panel = field('#workbench-panel'), proposalPanel = field('#proposal-panel'), jobPanel = field('#job-panel');
  const position = node => [...node.parentNode.children].indexOf(node);
  assert(position(panel) < position(proposalPanel) && position(panel) < position(jobPanel), 'the iteration workbench comes before proposal and job details');
  assert(!field('#workbench-flow-summary').classList.contains('hidden'));
  assert.match(field('#workbench-flow-summary').textContent, /可继续编辑本地草稿/);
  assert([...field('#workbench-flow-summary').querySelectorAll('button')].some(button => button.textContent === '查看待审候选'), 'the iteration summary preserves a direct route to the pending review candidate');
  assert.doesNotMatch(failedCard.textContent, /查看此候选与试玩入口/);

  // UR06: resetting a mixed draft is undoable and redoable without touching its explicit checkpoint.
  const draftSnapshot = {
    text: '主目标意见', values: { movement: 275 }, fields: { 'hero.speed': 275, 'dice.warning': 3 },
    feedback: [{ feedbackId: 'feedback-mixed', objectId: 'hero', message: '动作偏慢', category: 'behavior' }],
    feedbackInputs: { hero: { message: '待加入的目标反馈', category: 'visual' } }, feedbackInputTargetId: 'hero',
    feedbackMessage: '待加入的目标反馈', feedbackCategory: 'visual',
    legacyUnboundFeedback: { message: '尚未绑定的意见', category: 'general' },
    proposalInputs: { 'new-scene': { name: '大厅草稿' } }, selectedObjectId: 'hero',
    targetNotes: {
      hero: { objectId: 'hero', text: '主目标意见', feedbackId: 'hero-note' },
      dice: { objectId: 'dice', text: '第二目标意见', feedbackId: 'dice-note' },
    },
    structuralProposals: [{ operationId: 'scene-op', kind: 'new-scene', name: '新大厅', sceneId: 'draft-scene-scene-op', scope: '新场景' }],
  };
  let activeDraft = clone(draftSnapshot);
  const checkpoint = { savedAt: '2026-10-15T00:00:00.000Z', draft: clone(draftSnapshot) };
  const savedRecords = new Map([[app.draftKey, clone(activeDraft)], [`${app.draftKey}:saved`, clone(checkpoint)]]);
  app.selectedObjectId = 'hero'; app.targetNotes = clone(draftSnapshot.targetNotes);
  app.structuralProposals = clone(draftSnapshot.structuralProposals);
  app.fieldDraftValues = clone(draftSnapshot.fields); app.feedback = clone(draftSnapshot.feedback);
  app.feedbackInputs = clone(draftSnapshot.feedbackInputs); app.proposalInputs = clone(draftSnapshot.proposalInputs);
  app.legacyUnboundFeedback = clone(draftSnapshot.legacyUnboundFeedback);
  field('#edit-text').value = draftSnapshot.text;
  app.dirtyFields = new Set(Object.keys(draftSnapshot.fields));
  app.readVisibleDraft = () => ({
    ...clone(activeDraft), text: field('#edit-text').value,
    fields: clone(app.fieldDraftValues), feedback: clone(app.feedback), feedbackInputs: clone(app.feedbackInputs),
    feedbackInputTargetId: activeDraft.feedbackInputTargetId, feedbackMessage: activeDraft.feedbackMessage,
    feedbackCategory: activeDraft.feedbackCategory, legacyUnboundFeedback: clone(app.legacyUnboundFeedback),
    proposalInputs: clone(app.proposalInputs), selectedObjectId: app.selectedObjectId,
    targetNotes: clone(app.targetNotes), structuralProposals: clone(app.structuralProposals),
  });
  app.applyVisibleDraft = draft => {
    activeDraft = clone(draft);
    app.selectedObjectId = draft.selectedObjectId || null;
    app.targetNotes = clone(draft.targetNotes || {});
    app.structuralProposals = clone(draft.structuralProposals || []);
    app.fieldDraftValues = clone(draft.fields || {});
    app.feedback = clone(draft.feedback || []);
    app.feedbackInputs = clone(draft.feedbackInputs || {});
    app.proposalInputs = clone(draft.proposalInputs || {});
    app.legacyUnboundFeedback = clone(draft.legacyUnboundFeedback || null);
    field('#edit-text').value = draft.text || '';
  };
  app.drafts = { put: async (key, value) => { savedRecords.set(key, clone(value)); }, get: async key => clone(savedRecords.get(key) || null) };
  let failNextActionSave = false;
  app.queueDraftSave = () => {
    if (failNextActionSave || app.pendingDraftConflict?.key === app.draftKey) { failNextActionSave = false; return false; }
    savedRecords.set(app.draftKey, clone(app.readVisibleDraft())); return true;
  };
  wb.render = () => {};
  wb.clearTransientInteractions = () => false;
  wb.resetHistory();
  const checkpointBeforeReset = clone(savedRecords.get(`${app.draftKey}:saved`));
  const resetConfirm = globalThis.confirm;
  const beforeCancelledReset = clone(app.readVisibleDraft());
  globalThis.confirm = () => false;
  await wb.resetDraft();
  assert.deepEqual(app.readVisibleDraft(), beforeCancelledReset, 'canceling reset preserves the complete draft');
  globalThis.confirm = () => true;
  await wb.resetDraft();
  globalThis.confirm = resetConfirm;
  assert.deepEqual(app.targetNotes, {}, 'reset clears opinions for every target');
  assert.deepEqual(app.fieldDraftValues, {}, 'reset clears property values');
  assert.deepEqual(app.feedback, [], 'reset clears added feedback');
  assert.deepEqual(app.structuralProposals, [], 'reset clears structural proposals');
  assert.deepEqual(app.proposalInputs, {}, 'reset clears incomplete proposal form drafts');
  assert.deepEqual(savedRecords.get(app.draftKey).targetNotes, {}, 'reset writes the empty active work draft before returning');
  assert.match(app.actionStatus, /已重置并保存/, 'reset status reports persistence only after the active write');
  assert.equal(field('[data-workbench-action="undo"]').disabled, false);
  assert.match(field('[data-workbench-action="undo"]').getAttribute('aria-label'), /撤销重置/);
  assert(field('[data-workbench-action="undo"]').classList.contains('workbench-undo-highlight'));
  assert.deepEqual(savedRecords.get(`${app.draftKey}:saved`), checkpointBeforeReset, 'reset leaves the explicit checkpoint unchanged');

  await wb.undo();
  assert.deepEqual(savedRecords.get(app.draftKey).targetNotes, draftSnapshot.targetNotes, 'undo writes the restored active draft before returning');
  assert.deepEqual(app.targetNotes, draftSnapshot.targetNotes, 'undo restores notes on both targets');
  assert.deepEqual(app.fieldDraftValues, draftSnapshot.fields, 'undo restores the mixed field draft');
  assert.deepEqual(app.feedback, draftSnapshot.feedback, 'undo restores classified feedback');
  assert.deepEqual(app.feedbackInputs, draftSnapshot.feedbackInputs, 'undo restores unsubmitted feedback input');
  assert.deepEqual(app.structuralProposals, draftSnapshot.structuralProposals, 'undo restores structural proposals');
  assert.deepEqual(app.proposalInputs, draftSnapshot.proposalInputs, 'undo restores incomplete proposal input');
  await wb.redo();
  assert.deepEqual(savedRecords.get(app.draftKey).targetNotes, {}, 'redo writes the reset active draft before returning');
  assert.deepEqual(app.targetNotes, {}, 'redo reapplies the reset across all targets');
  assert.deepEqual(app.fieldDraftValues, {}, 'redo keeps reset field state');
  assert.deepEqual(app.structuralProposals, [], 'redo keeps reset structure state');
  assert.deepEqual(savedRecords.get(`${app.draftKey}:saved`), checkpointBeforeReset, 'undo and redo still leave the checkpoint unchanged');

  app.pendingDraftConflict = { key: app.draftKey };
  await wb.undo();
  assert.match(app.actionStatus, /未完成持久保存/, 'an unresolved draft conflict cannot be reported as a saved undo');
  assert.deepEqual(savedRecords.get(app.draftKey).targetNotes, {}, 'a blocked undo stays visible but leaves the stored active draft unchanged');
  app.pendingDraftConflict = null;

  // R03-P3: the unified report shows the structure data saved in its operations.
  wb.openProposal('new-scene');
  const templateSelect = field('#workbench-proposal-fields [name="template"]');
  assert.deepEqual([...templateSelect.options].map(option => [option.value, option.textContent]), [
    ['blank', '空白场景'], ['minimal', '最小结构模板（待 Agent 确认）'],
  ], 'the scene proposal form retains its readable template choices');
  wb.closeWorkbenchDialog(field('#workbench-proposal-dialog'));
  const completeConnections = '从东侧入口进入大厅\n离开大厅时连接到庭院';
  const sceneOperation = { operationId: 'scene-report-op', kind: 'new-scene', name: '大厅', sceneId: 'draft-scene-report',
    template: 'minimal', bounds: [960, 640], connections: completeConnections, scope: '新场景' };
  const unspecifiedScene = { operationId: 'scene-report-unspecified', kind: 'new-scene', name: '储藏室', sceneId: 'draft-scene-unspecified', scope: '新场景' };
  const blankScene = { operationId: 'scene-report-blank', kind: 'new-scene', name: '大厅入口', sceneId: 'draft-scene-blank', template: 'blank', scope: '新场景' };
  const unknownScene = { operationId: 'scene-report-unknown', kind: 'new-scene', name: '未知模板', sceneId: 'draft-scene-unknown', template: 'custom-blueprint', scope: '新场景' };
  app.structuralProposals = [sceneOperation, blankScene, unspecifiedScene, unknownScene];
  wb.refreshReport(false);
  const reportData = wb.reportData();
  assert.deepEqual(reportData.operations, [sceneOperation, blankScene, unspecifiedScene, unknownScene], 'the report cards use the same complete operation records as the preview payload');
  const structureCards = [...field('#workbench-report-content').querySelectorAll('article.workbench-report-item')]
    .filter(card => card.textContent.includes('新场景提案'));
  assert.equal(structureCards.length, 4);
  assert.match(structureCards[0].textContent, /世界尺寸：960 × 640/);
  assert.match(structureCards[0].textContent, /起始结构：最小结构模板（待 Agent 确认）/);
  assert.match(structureCards[0].querySelector('.workbench-report-item-title').textContent, /最小结构模板（待 Agent 确认）/);
  const connectionLine = structureCards[0].querySelector('.workbench-report-operation-connections');
  assert.equal(connectionLine.textContent, `出入口或连接说明：${completeConnections}`, 'the report keeps the complete multiline connection text');
  assert.equal(connectionLine.style.whiteSpace, 'pre-wrap', 'multiline connection text retains visible line breaks');
  assert.equal(structureCards[0].querySelector('[data-workbench-action="locate-target"]').dataset.targetId, sceneOperation.sceneId,
    'the structure preview returns to its original draft target');
  assert.match(structureCards[1].textContent, /起始结构：空白场景/);
  assert.match(structureCards[1].textContent, /世界尺寸：未提供/);
  assert.match(structureCards[1].textContent, /出入口或连接说明：未提供/);
  assert.match(structureCards[2].textContent, /起始结构：未提供/);
  assert.match(structureCards[3].textContent, /起始结构：未知起始结构（custom-blueprint）/);

  // R04-02: each ordinary continuation path keeps the same opinion identity,
  // while a decision tied to the old full source text becomes stale.
  app.objectList = [
    { id: 'hero', kind: 'entity', name: '角色', fields: [{ id: 'speed', label: '速度', value: 220 }], relations: [] },
    { id: 'guard-one', kind: 'entity', name: '守卫实例', fields: [], relations: [] },
  ];
  app.selectedObjectId = 'hero'; app.fieldDraftValues = { 'hero.speed': 280 };
  const sourceNoteId = 'ux-stable-source-note', decisionKey = '__test-decision__';
  app.targetNotes = {
    hero: { objectId: 'hero', text: '原始完整意见', feedbackId: sourceNoteId },
    'guard-one': { objectId: 'guard-one', text: '关联意见原文', feedbackId: 'ux-associated-note' },
  };
  field('#edit-text').value = '原始完整意见';
  field('#edit-text').value += '\n主编辑框续写全文'; wb.persistCurrentNote();
  assert.equal(app.targetNotes.hero.feedbackId, sourceNoteId, 'the main editor keeps the same note ID after appending text');
  const oldContext = wb.decisionContextFor({ objectId: 'hero', fieldId: 'speed', value: 280 }, {
    key: 'hero', feedbackId: sourceNoteId, objectId: 'hero', text: '原始完整意见',
  });
  const oldDecision = { objectId: 'hero', text: '用户决定：控件值优先。', feedbackId: 'ux-old-decision',
    decisionFor: 'hero.speed:ux-stable-source-note', decisionContext: oldContext };
  app.targetNotes[decisionKey] = oldDecision;
  assert.equal(wb.isDecisionCurrent(oldDecision, decisionKey), false, 'a decision bound to the pre-edit complete source text is stale');
  assert.equal(app.targetNotes[decisionKey].text, oldDecision.text, 'the stale decision remains available for review');

  const associatedEditor = dom.window.document.createElement('textarea');
  associatedEditor.dataset.associatedNoteKey = 'guard-one';
  associatedEditor.value = '关联意见原文\n关联意见编辑器续写';
  field('#object-detail').append(associatedEditor);
  associatedEditor.dispatchEvent(new dom.window.Event('input', { bubbles: true }));
  assert.equal(app.targetNotes['guard-one'].feedbackId, 'ux-associated-note', 'the associated-note editor keeps its existing note ID');
  assert.match(app.targetNotes['guard-one'].text, /关联意见编辑器续写/);

  const currentContext = wb.decisionContextFor({ objectId: 'hero', fieldId: 'speed', value: 280 }, {
    key: 'hero', feedbackId: sourceNoteId, objectId: 'hero', text: app.targetNotes.hero.text,
  });
  const currentDecision = { objectId: 'hero', text: '用户重新决定：控件值优先。', feedbackId: 'ux-current-decision',
    decisionFor: oldDecision.decisionFor, decisionContext: currentContext };
  app.targetNotes['__test-decision-new__'] = currentDecision;
  assert.equal(wb.isDecisionCurrent(currentDecision, '__test-decision-new__'), true, 'a new decision is current for the complete edited note');

  wb.editReportNote(sourceNoteId);
  const reportEditor = field('[data-report-note-editor="ux-stable-source-note"]');
  assert(reportEditor, 'the unified preview opens the existing opinion by its stable ID');
  reportEditor.value += '\n统一预览续写全文';
  reportEditor.dispatchEvent(new dom.window.Event('input', { bubbles: true }));
  wb.saveReportNote(sourceNoteId);
  assert.equal(app.targetNotes.hero.feedbackId, sourceNoteId, 'the unified preview keeps the same note ID after continuation');
  assert.match(app.targetNotes.hero.text, /统一预览续写全文/);
  assert.equal(wb.isDecisionCurrent(currentDecision, '__test-decision-new__'), false, 'a further source-text edit expires the newer decision too');
  assert.equal(app.targetNotes[decisionKey].text, oldDecision.text, 'expired decision text remains intact after later editing');

  console.log('PASS Studio user UX workbench QA: report outcomes/session, target facts, revision grouping, persisted reset/undo/redo status, checkpoint preservation, complete structure preview, stable opinion IDs, and decision expiry');
})().catch(error => {
  console.error(error.stack || error);
  process.exitCode = 1;
}).finally(() => {
  dom.window.close();
  for (const [key, value] of Object.entries(savedGlobals)) {
    if (value === undefined) delete global[key]; else global[key] = value;
  }
});
