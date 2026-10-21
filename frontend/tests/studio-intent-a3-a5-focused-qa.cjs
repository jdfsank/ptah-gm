#!/usr/bin/env node
/* Focused regressions for semantic drafts, field guidance, report decisions, history, and candidate review. */
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const { pathToFileURL } = require('node:url');
let JSDOM;
try { ({ JSDOM } = require('jsdom')); }
catch { console.log('SKIP Studio A3/A4/A5 focused QA: jsdom is unavailable.'); process.exit(0); }

const root = path.resolve(__dirname, '..');
const dom = new JSDOM(fs.readFileSync(path.join(root, 'studio/index.html'), 'utf8'), {
  url: 'http://127.0.0.1:8123/studio/?project=intent-a3-a5&stage=iteration', pretendToBeVisual: true,
});
global.FormData = dom.window.FormData;
global.Option = dom.window.Option;
global.localStorage = dom.window.localStorage;
global.location = dom.window.location;
global.history = dom.window.history;
global.document = dom.window.document;
global.confirm = () => true;
dom.window.HTMLDialogElement.prototype.showModal = function () { this.open = true; };
dom.window.HTMLDialogElement.prototype.close = function () { this.open = false; };

const tick = () => new Promise(resolve => setTimeout(resolve, 0));

(async () => {
  const { StudioApp, DraftStore } = await import(pathToFileURL(path.join(root, 'studio/studio.js')).href);
  const app = new StudioApp({ documentImpl: dom.window.document, fetchImpl: async () => ({ ok: false, status: 404, text: async () => '{}' }) });
  const project = { id: 'intent-a3-a5', title: '意图完整性夹具', workflow: 'objects-v1', publicationRevision: 4 };
  const objects = [
    { id: 'player', kind: 'entity', name: '玩家', fields: [{ id: 'speed', label: '速度', type: 'number', value: 250 }, { id: 'health', label: '初始生命', type: 'integer', value: 100 }, { id: 'level', label: '初始等级', type: 'integer', value: 2 }], relations: [], workbench: { role: 'instance', scope: 'instance', sceneId: 'scene', definitionId: 'player-def', lock: 'free' } },
    { id: 'enemy', kind: 'entity', name: '敌人', fields: [], relations: [], workbench: { role: 'instance', sceneId: 'scene', definitionId: 'enemy-def' } },
    { id: 'player-def', kind: 'entity', name: '玩家定义', fields: [], relations: [], workbench: { role: 'definition' } },
    { id: 'enemy-def', kind: 'entity', name: '敌人定义', fields: [], relations: [], workbench: { role: 'definition' } },
    { id: 'scene', kind: 'scene', name: '测试场景', fields: [], relations: [], workbench: { role: 'scene', bounds: [800, 600] } },
  ];
  app.protocolVersion = 1;
  app.handshake = { schemaVersion: 'studio.message.v1', kind: 'handshake', storeId: 'intent-a3-a5-store', serviceInstanceId: 'intent-a3-a5-service', writeToken: 'intent-token', readable: true, capabilities: [] };
  app.token = 'intent-token'; app.manager = { storeId: 'intent-a3-a5-store', projects: [project] };
  app.workspace = { storeId: 'intent-a3-a5-store', workspaceId: 'intent-a3-a5', projects: [project], iterationReady: true, capabilities: { interactiveFrontendConfirmation: true } };
  app.projectId = project.id; app.stage = 'iteration'; app.workflow = 'objects-v1'; app.currentProject = () => project;
  app.snapshot = { projectId: project.id, publicationRevision: 4, sourceCommit: 'git-intent-base', workflow: 'objects-v1', kind: 'MVP', title: project.title, catalog: { objects }, document: { objects } };
  app.selectedObjectId = 'player';
  app.capabilities = { fields: [
    { id: 'player.speed', objectId: 'player', fieldId: 'speed', label: '速度', type: 'number', value: 250, editable: true, unit: 'px/s', min: 0, max: 500, step: 5 },
    { id: 'player.health', objectId: 'player', fieldId: 'health', label: '初始生命', type: 'integer', integer: true, value: 100, editable: true, min: 0, max: 500, step: 10 },
    { id: 'player.level', objectId: 'player', fieldId: 'level', label: '初始等级', type: 'integer', integer: true, value: 2, editable: true, min: 1, max: 20 },
  ] };
  app.projectView = { schemaVersion: 'studio.project-view.v1', storeId: 'intent-a3-a5-store', projectId: project.id, allowedActions: ['iteration.submit'], proposals: [], packets: [], jobs: [], previews: [] };
  app.readiness = { ready: true, missing: [] }; app.targetNotes = {}; app.structuralProposals = []; app.feedback = []; app.workbenchResults = [];
  app.drafts = new DraftStore(null, dom.window.localStorage); app.persistenceOK = true; app.draftKey = app.makeDraftKey(app.snapshot); app.draftRevision = 0;
  app.bind(); app.renderWorkbench();
  const wb = app.legacyWorkbench;
  wb.resetHistory();
  const field = selector => dom.window.document.querySelector(selector);

  // UR02: semantic draft comparison matches stable opinion identity, then reports target/category changes.
  const targetComparison = app.renderDraftSemanticComparison(
    { targetNotes: { player: { objectId: 'player', feedbackId: 'stable-note', text: '保留这个意见' } } },
    { targetNotes: { enemy: { objectId: 'enemy', feedbackId: 'stable-note', text: '保留这个意见' } } },
  );
  assert.match(targetComparison.textContent, /修改 · 目标变化/, 'rebinding an opinion with the same feedback ID is shown as a target change');
  assert.match(targetComparison.textContent, /玩家（player）/, 'the original target name and ID remain visible');
  assert.match(targetComparison.textContent, /敌人（enemy）/, 'the replacement target name and ID remain visible');
  const projectNote = app.semanticDraftEntries({ targetNotes: { __project__: { objectId: null, feedbackId: 'stable-project-note', text: '项目级意见' } } }).get('note:stable-project-note');
  assert.equal(projectNote?.legacy, false, 'an explicitly project-bound opinion with a stable ID is not labeled legacy or unbound');
  const categoryComparison = app.renderDraftSemanticComparison(
    { feedback: [{ feedbackId: 'category-note', objectId: 'player', category: 'behavior', message: '同一反馈' }] },
    { feedback: [{ feedbackId: 'category-note', objectId: 'player', category: 'quality', message: '同一反馈' }] },
  );
  assert.match(categoryComparison.textContent, /修改 · 分类变化/, 'a category change remains visible when feedback identity and text are unchanged');
  const namedDraftBase = {
    targetNotes: {
      'draft-scene-target': { objectId: 'draft-scene-target', feedbackId: 'draft-scene-note', text: '场景意见原文' },
      'draft-instance-target': { objectId: 'draft-instance-target', feedbackId: 'draft-instance-note', text: '实例意见原文' },
    },
    structuralProposals: [
      { operationId: 'draft-scene-operation', kind: 'new-scene', sceneId: 'draft-scene-target', name: '用户命名场景' },
      { operationId: 'draft-instance-operation', kind: 'new-instance', instanceId: 'draft-instance-target', name: '用户命名实例' },
    ],
  };
  const namedDraftNext = { ...namedDraftBase, targetNotes: {
    'draft-scene-target': { ...namedDraftBase.targetNotes['draft-scene-target'], text: '场景意见更新' },
    'draft-instance-target': { ...namedDraftBase.targetNotes['draft-instance-target'], text: '实例意见更新' },
  } };
  const namedDraftComparison = app.renderDraftSemanticComparison(namedDraftBase, namedDraftNext);
  assert.match(namedDraftComparison.textContent, /目标：用户命名场景（draft-scene-target）/, 'new-scene draft names label their target while preserving its ID');
  assert.match(namedDraftComparison.textContent, /目标：用户命名实例（draft-instance-target）/, 'new-instance draft names label their target while preserving its ID');
  const proposalInputsBefore = { proposalInputs: { 'proposal-a': { '2': { questions: { 'q-goal': '保留拾取奖励', 'q-empty': '' }, questionPrompts: { 'q-goal': '完成目标是什么？' }, readySupplement: '玩家应当能看清奖励来源。' } } } };
  const proposalInputsAfter = { proposalInputs: { 'proposal-a': { '2': { questions: { 'q-goal': '保留拾取奖励并明确来源', 'q-empty': '' }, questionPrompts: { 'q-goal': '完成目标是什么？' }, readySupplement: '玩家应当能看清奖励来源。' } } } };
  const semanticProposalInputs = app.semanticDraftEntries(proposalInputsBefore);
  assert.equal(semanticProposalInputs.size, 2, 'proposal inputs are split into populated answer and READY supplement entries');
  assert([...semanticProposalInputs.values()].some(item => item.category.includes('方案 proposal-a · 修订 r2') && item.category.includes('完成目标是什么？（问题 q-goal）') && item.content === '保留拾取奖励'), 'proposal answers are readable and identified by proposal, revision, and question');
  const proposalInputComparison = app.renderDraftSemanticComparison(proposalInputsBefore, proposalInputsAfter);
  assert.match(proposalInputComparison.textContent, /方案 proposal-a · 修订 r2.*完成目标是什么？（问题 q-goal）/);
  assert.match(proposalInputComparison.textContent, /内容变化/);
  assert.match(proposalInputComparison.textContent, /保留拾取奖励.*保留拾取奖励并明确来源/);
  assert(app.semanticDraftEntries({ feedbackInputs: { player: { message: '' } }, feedbackMessage: '旧版未绑定内容' }).has('legacy-feedback-mirror'), 'an empty bound-input shell does not hide a legacy unbound feedback mirror');

  // UR03: parameter guidance puts the exact source context beside the control and treats empty as no request.
  app.fieldDraftValues = {}; app.dirtyFields = new Set(); app.selectedObjectId = 'player'; app.renderDynamicFields(objects, app.capabilities);
  const speedGuide = field('[data-field-guidance="player.speed"]');
  assert.match(speedGuide.textContent, /来源版本 4.*来源当前值：250.*px\/s.*下限 0 至 上限 500.*步长：5.*本轮未提出修改/);
  const healthControl = field('[data-field-id="player.health"]');
  assert.equal(healthControl.step, '10', 'a declared source step overrides the integer default');
  assert.match(field('[data-field-guidance="player.health"]').textContent, /步长：10/);
  healthControl.stepUp();
  assert.equal(healthControl.value, '110', 'one native stepUp follows the declared step of 10');
  const levelControl = field('[data-field-id="player.level"]');
  assert.equal(levelControl.step, '1', 'an integer without a declared source step retains the integer input default');
  assert.match(field('[data-field-guidance="player.level"]').textContent, /步长：未声明/, 'an implicit input step is not described as a source declaration');
  let guidedSpeed = field('#dynamic-fields [data-field-id="player.speed"]');
  guidedSpeed.value = '0'; app.onDynamicFieldEdit(guidedSpeed);
  assert.match(speedGuide.textContent, /本轮期望：0 px\/s（尚未制作）/, 'zero is presented as a real requested value');
  guidedSpeed.value = ''; app.onDynamicFieldEdit(guidedSpeed);
  assert.match(speedGuide.textContent, /本轮未提出修改/, 'an empty numeric input clears the current request');
  assert.equal(app.normalizeFieldValue('boolean', false), false, 'boolean false stays false during normalization');
  assert.equal(app.normalizeFieldValue('boolean', 'false'), false, 'the boolean string false matches the boolean false value');

  // A3: the report buffer is protected and the frozen reviewed request carries its new value.
  app.targetNotes = { player: { objectId: 'player', text: '速度 250', feedbackId: 'a3-note' } };
  wb.loadCurrentNote(); wb.openReport(); wb.editReportNote('a3-note');
  const noteEditor = field('[data-report-note-editor="a3-note"]'); assert(noteEditor, 'A3 report note editor exists');
  noteEditor.value = '速度 300'; noteEditor.dispatchEvent(new dom.window.Event('input', { bubbles: true }));
  assert.equal(app.targetNotes.player.text, '速度 300', 'uncommitted text remains in the local draft');
  assert(wb.hasUncommittedReportEdit(), 'changed report text is identified as an incomplete edit');
  assert(field('#workbench-report-confirm').disabled, 'the main submit button is disabled while the report edit is incomplete');
  let submitCount = 0, reviewedReport = null;
  app.proposal = { id: 'before-a3' };
  app.submitIteration = async options => { submitCount++; reviewedReport = options.reviewedReport; app.proposal = { id: 'after-a3' }; return { status: 'submitted', proposalId: 'after-a3' }; };
  await wb.confirmReport();
  assert.equal(submitCount, 0, 'direct submission cannot send the previous text');
  assert.equal(app.targetNotes.player.text, '速度 300', 'blocked submission preserves the replacement text');
  wb.saveReportNote('a3-note');
  assert(!wb.hasUncommittedReportEdit(), 'local completion releases the report gate');
  await wb.confirmReport();
  assert.equal(submitCount, 1, 'the completed and refreshed report can submit');
  assert.equal(reviewedReport.intent.changeRequest.feedback.find(item => item.feedbackId === 'a3-note')?.message, '速度 300', 'the frozen request contains the completed report text');

  // A4: navigation preserves a decision; changing its field or source text invalidates it and excludes it outbound.
  app.selectedObjectId = 'player'; app.feedback = []; app.structuralProposals = [];
  app.targetNotes = { player: { objectId: 'player', text: '保持玩家移动反馈', feedbackId: 'a4-note' } };
  app.fieldDraftValues = {}; app.dirtyFields = new Set(); wb.loadCurrentNote();
  let speedInput = field('#dynamic-fields [data-field-id="player.speed"]'); assert(speedInput, 'A4 player speed control exists');
  speedInput.value = '280'; app.onDynamicFieldEdit(speedInput); wb.openReport();
  const choice = field('.workbench-conflict-resolution [data-conflict-decision]'); assert(choice, 'same-target field and opinion have a decision control');
  choice.value = 'control'; wb.applyConflictDecision(field('.workbench-conflict-resolution [data-workbench-action="apply-conflict-decision"]'));
  let decisionEntry = Object.entries(app.targetNotes).find(([, note]) => note.decisionFor);
  assert(decisionEntry && wb.isDecisionCurrent(decisionEntry[1], decisionEntry[0]), 'the decision is current against its saved field, scope, version, and source text');
  const decision = decisionEntry[1];
  const player = objects.find(item => item.id === 'player');
  const originalScope = player.workbench.scope;
  player.workbench.scope = 'shared';
  assert(!wb.isDecisionCurrent(decision, decisionEntry[0]), 'changing only the field scope invalidates the decision');
  player.workbench.scope = originalScope;
  assert(wb.isDecisionCurrent(decision, decisionEntry[0]), 'restoring the field scope restores the decision');
  const originalRevision = app.snapshot.publicationRevision;
  app.snapshot.publicationRevision = originalRevision + 1;
  assert(!wb.isDecisionCurrent(decision, decisionEntry[0]), 'changing only the publication version invalidates the decision');
  app.snapshot.publicationRevision = originalRevision;
  assert(wb.isDecisionCurrent(decision, decisionEntry[0]), 'restoring the publication version restores the decision');
  const originalSourceCommit = app.snapshot.sourceCommit;
  app.snapshot.sourceCommit = 'git-intent-next';
  assert(!wb.isDecisionCurrent(decision, decisionEntry[0]), 'changing only the source commit invalidates the decision');
  app.snapshot.sourceCommit = originalSourceCommit;
  assert(wb.isDecisionCurrent(decision, decisionEntry[0]), 'restoring the source commit restores the decision');
  const savedDecisionContext = decision.decisionContext;
  delete decision.decisionContext;
  assert(!wb.isDecisionCurrent(decision, decisionEntry[0]), 'a legacy decision without evidence context is stale');
  const legacyDecisionRequest = app.buildChangeRequest();
  assert(!legacyDecisionRequest.feedback.some(item => item.feedbackId === decision.feedbackId), 'a legacy decision without evidence context stays out of the request');
  assert(legacyDecisionRequest.feedback.some(item => item.feedbackId === 'a4-note' && item.message === '保持玩家移动反馈'), 'the original opinion remains available when its legacy decision is stale');
  decision.decisionContext = savedDecisionContext;
  assert(wb.isDecisionCurrent(decision, decisionEntry[0]), 'restoring a valid decision context restores the decision');
  app.selectObject('enemy'); app.selectObject('player');
  assert(wb.isDecisionCurrent(decision, decisionEntry[0]), 'ordinary navigation does not invalidate an unchanged decision');
  speedInput = field('#dynamic-fields [data-field-id="player.speed"]'); speedInput.value = '290'; app.onDynamicFieldEdit(speedInput);
  assert(!wb.isDecisionCurrent(decision, decisionEntry[0]), 'changing the decided field invalidates the prior decision');
  let outgoing = app.buildChangeRequest();
  assert.equal(outgoing.fields.find(item => item.objectId === 'player' && item.fieldId === 'speed')?.value, 290, 'the outgoing field contains the updated value');
  assert(!outgoing.feedback.some(item => item.feedbackId === decision.feedbackId), 'the stale decision is omitted from the outgoing request');
  assert(outgoing.feedback.some(item => item.feedbackId === 'a4-note' && item.message === '保持玩家移动反馈'), 'the original opinion remains outbound for fresh review');
  // Re-record a decision against the current 290 value so the next assertion isolates source-text invalidation.
  wb.refreshReport(true);
  const refreshedChoice = field('.workbench-conflict-resolution [data-conflict-decision]');
  const refreshedApply = field('.workbench-conflict-resolution [data-workbench-action="apply-conflict-decision"]');
  assert(refreshedChoice && refreshedApply, 'A4 can record a fresh decision against the updated field value');
  refreshedChoice.value = 'control'; wb.applyConflictDecision(refreshedApply);
  const textBoundDecision = Object.entries(app.targetNotes).filter(([, note]) => note.decisionFor).at(-1);
  assert(textBoundDecision && wb.isDecisionCurrent(textBoundDecision[1], textBoundDecision[0]), 'the replacement decision is current against value 290 and the current source text');
  const sourceFeedbackId = app.targetNotes.player.feedbackId;
  const editedSourceText = '原文修改后继续保留';
  field('#edit-text').value = editedSourceText;
  app.targetNotes.player.text = editedSourceText;
  assert.equal(app.targetNotes.player.feedbackId, sourceFeedbackId, 'the source text changes without changing its identity');
  assert(!wb.isDecisionCurrent(textBoundDecision[1], textBoundDecision[0]), 'changing only the source text invalidates the replacement decision');
  outgoing = app.buildChangeRequest();
  assert(!outgoing.feedback.some(item => item.feedbackId === textBoundDecision[1].feedbackId), 'the decision made against the previous source text is omitted from the outgoing request');
  assert(outgoing.feedback.some(item => item.feedbackId === sourceFeedbackId && item.message === editedSourceText), 'the edited original opinion remains outbound for fresh review');
  wb.refreshReport(true);
  assert.match(field('#workbench-report-content').textContent, /旧决定仅保留供核对/);

  // A5: full history preserves feedback identity, edit/remove transactions, and nested snapshots.
  app.selectedObjectId = 'player'; app.targetNotes = {}; app.structuralProposals = []; app.feedback = []; app.feedbackInputs = {};
  wb.loadCurrentNote(); app.renderFeedback(); wb.resetHistory();
  field('#feedback-message').value = '加入一条行为反馈'; field('#feedback-category').value = 'behavior';
  app.addFeedback();
  const feedbackId = app.feedback[0]?.feedbackId; assert(feedbackId, 'added feedback receives a stable ID');
  await wb.undo(); assert.equal(app.feedback.length, 0, 'undo returns the feedback array to its pre-add state');
  await wb.redo(); assert.equal(app.feedback[0]?.feedbackId, feedbackId, 'redo restores the same feedback ID');
  app.feedback[0].nestedEvidence = { tags: ['before'] }; wb.pushHistory();
  const beforeNestedEditIndex = wb.historyIndex;
  app.feedback[0].nestedEvidence.tags.push('after'); wb.pushHistory();
  assert.deepEqual(wb.history[beforeNestedEditIndex].feedback[0].nestedEvidence.tags, ['before'], 'nested edits cannot mutate earlier history snapshots by reference');
  await wb.undo(); assert.deepEqual(app.feedback[0].nestedEvidence.tags, ['before'], 'undo restores the deep-copied nested value');
  wb.openReport(); wb.editReportFeedback(feedbackId);
  const feedbackEditor = field(`[data-report-feedback-editor="${feedbackId}"]`); assert(feedbackEditor, 'A5 feedback editor exists');
  feedbackEditor.value = '编辑后的行为反馈'; feedbackEditor.dispatchEvent(new dom.window.Event('input', { bubbles: true }));
  assert(wb.hasUncommittedReportEdit(), 'feedback report edits are covered by the incomplete-edit guard');
  wb.saveReportFeedback(feedbackId);
  assert.equal(app.feedback[0].message, '编辑后的行为反馈');
  await wb.undo(); assert.equal(app.feedback[0].message, '加入一条行为反馈', 'undo restores pre-edit feedback text');
  await wb.redo(); assert.equal(app.feedback[0].message, '编辑后的行为反馈', 'redo restores edited feedback text');
  wb.removeReportFeedback(feedbackId); assert.equal(app.feedback.length, 0, 'removal is a separate feedback transaction');
  await wb.undo(); assert.equal(app.feedback[0].feedbackId, feedbackId, 'undo of removal restores the same ID');
  await wb.redo(); assert.equal(app.feedback.length, 0, 'redo of removal restores the removed state');

  // UR05: candidate actions and status stay visible while Git, mappings, diff, and run evidence start folded.
  app.job = { id: 'candidate-job', projectId: project.id, status: 'READY_FOR_REVIEW', candidate: {
    id: 'candidate-ready', candidateCommit: 'git-candidate-ready', summary: '候选摘要', previewAvailable: true,
    objectMappings: [{ id: 'player', name: '玩家', status: '已映射' }], objectDiff: [{ id: 'player', action: 'update' }],
    verification: { status: 'PASS', checks: [{ status: 'PASS', title: '启动检查' }] },
  } };
  app.projectView = { projectId: project.id, allowedActions: ['preview.start'] };
  app.renderCandidate(app.job.candidate, { historical: false });
  const candidateArea = field('#candidate-area');
  assert.match(candidateArea.querySelector('.candidate-status').textContent, /等待你审阅/);
  assert.match(candidateArea.textContent, /候选摘要/);
  assert(candidateArea.querySelector('button')?.textContent.includes('在 Godot 中运行此候选'), 'the candidate preview entry stays immediately reachable');
  assert(candidateArea.querySelector('.decision-actions'), 'review and candidate decision actions remain immediately reachable');
  assert([...candidateArea.querySelectorAll('details[data-candidate-detail]')].length >= 4, 'Git, complete mappings, object diff, and evidence each have a details section');
  assert([...candidateArea.querySelectorAll('details[data-candidate-detail]')].every(node => !node.open), 'technical candidate details start folded');
  const metadataDetails = candidateArea.querySelector('[data-candidate-detail="metadata"]'); metadataDetails.open = true; await tick();
  app.renderCandidate(app.job.candidate, { historical: false });
  assert(field('#candidate-area [data-candidate-detail="metadata"]').open, 'the expanded technical detail stays expanded after a candidate rerender');
  field('#candidate-area [data-candidate-detail="metadata"]').open = false;
  app.renderCandidate(app.job.candidate, { historical: false });
  assert.equal(field('#candidate-area [data-candidate-detail="metadata"]').open, false, 'an immediate rerender preserves a close before its native toggle event');
  field('#candidate-area [data-candidate-detail="metadata"]').open = true;
  app.renderCandidate(app.job.candidate, { historical: false });
  assert.equal(field('#candidate-area [data-candidate-detail="metadata"]').open, true, 'an immediate rerender preserves an open before its native toggle event');
  assert(field('#candidate-area .candidate-review-actions'), 'the candidate decision area is still available after rerender');
  const feedback = { feedbackId: 'candidate-feedback', objectId: 'player', category: '体验', message: '玩家需要更快' };
  app.job.candidate.experienceFeedback = [feedback]; app.renderCandidate(app.job.candidate, { historical: false });
  const candidateDecision = field('#candidate-area [data-feedback-id="candidate-feedback"]');
  candidateDecision.value = 'resolved'; candidateDecision.dispatchEvent(new dom.window.Event('change', { bubbles: true }));
  field('#candidate-area [aria-label*="决定理由"]').value = '试玩后已确认';
  field('#candidate-area [aria-label*="决定理由"]').dispatchEvent(new dom.window.Event('input', { bubbles: true }));
  assert.equal(candidateArea.querySelectorAll('.candidate-review-actions').length, 1, 'repeated feedback edits keep one stable decision/action group');
  assert(candidateArea.querySelector('button')?.textContent.includes('在 Godot 中运行此候选'), 'editing a feedback decision does not remove the preview entry');

  if (wb.historyTimer != null) clearTimeout(wb.historyTimer);
  app.destroy(); dom.window.close();
  console.log('PASS Studio focused QA: semantic draft comparison, parameter guidance, protected report edits, stale decisions, deep feedback undo/redo, and folded candidate details');
})().catch(error => { console.error(error.stack || error); process.exitCode = 1; dom.window.close(); });
