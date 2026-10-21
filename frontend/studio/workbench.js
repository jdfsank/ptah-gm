import { mountVisual, referenceModel, releaseVisuals } from './visual-feedback.js';
import { renderSemanticPreview, renderSourceCoverage } from './workbench-semantics.js';

const $ = (selector, root = document) => root.querySelector(selector);
const el = (tag, className = '', text = null) => {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text != null) node.textContent = String(text);
  return node;
};
const hide = (node, value = true) => node?.classList.toggle('hidden', value);
const copy = value => value == null ? value : structuredClone(value);
const ROLE_LABELS = {
  definition: '共享定义', scene: '场景', instance: '场景实例', entry: '入口 / 定位', spawn: '生成规则',
  behavior: '行为', state: '状态', resource: '资源', transition: '场景过渡', preset: '配置预设', system: '系统',
};
const PROVENANCE_LABELS = { fact: '源码事实', intent: '设计意图', inference: '推断', proposal: '待实现提案', runtime: '运行结果' };
const SCENE_TEMPLATE_OPTIONS = [
  { value: 'blank', label: '空白场景' },
  { value: 'minimal', label: '最小结构模板（待 Agent 确认）' },
];
const WORKFLOW_LABELS = {
  received: '已收单', accepted: '已收单', queued: '排队中', running: '处理中', planning: '策划中',
  completed: 'Agent 回合结束', finished: 'Agent 回合结束', source_changed: '已记录源码变化',
  verified: '技术验证完成', accepted_by_user: '用户已认可', pending: '等待处理', blocked: '受阻', failed: '失败',
  dispatching: '正在派发', verifying: '正在验证', projecting: '正在整理结果', uncertain: '结果待核实',
  ready_for_review: '候选待审阅', rejected: '候选已拒绝', cancelled: '已取消',
  cancel_requested: '已请求停止', cancelling: '正在停止',
};

export class LegacyWorkbench {
  constructor(app) {
    this.app = app;
    this.view = 'design';
    this.category = 'all';
    this.search = '';
    this.activeSceneId = null;
    this.sceneCanvasSelection = null;
    this.pendingPlacementOperationId = null;
    this.pendingProposalObjectId = null;
    this.pendingPlacement = null;
    this.drag = null;
    this.folded = this.readPreference('ptah-studio-workbench-nav') === 'folded';
    this.mobilePane = 'stage';
    this.playTimer = null;
    this.playingTargetId = null;
    this.playStageIndex = 0;
    this.playPreviewData = null;
    this.sourceCache = new Map();
    this.previewCache = new Map();
    this.gridVisible = this.readPreference('ptah-studio-workbench-grid') === 'shown';
    this.guidesVisible = this.readPreference('ptah-studio-workbench-guides') === 'shown';
    this.layoutSelectionByScene = new Map();
    this.localLayoutProposal = null;
    this.localDecorationProposal = null;
    this.localTimingProposal = null;
    this.timingExampleStatus = '';
    this.decorationExampleStatus = '';
    this.history = [];
    this.historyIndex = -1;
    this.historyTimer = null;
    this.historyRestoring = false;
    this.historySignature = '';
    this.reportFingerprint = null;
    this.reportSubmitting = false;
    this.reportSessionSequence = 0;
    this.reportSubmissionSequence = 0;
    this.activeReportSubmission = null;
    this.pendingReportDrafts = new Map();
    this.reportHasBlockingContent = true;
    this.submissionOutcome = null;
    this.resultGroupExpanded = new Map();
    this.resultDetailsExpanded = new Map();
    this.resultRenderSignature = null;
    this.resetUndoIndex = null;
    this.resetHistoryIndex = null;
    this.checkpointStatusContext = null;
    this.checkpointStatusSnapshot = null;
    this.checkpointStatusSequence = 0;
    this.editingReportNoteId = null;
    this.editingReportNoteBase = null;
    this.editingReportFeedbackId = null;
    this.editingReportFeedbackBase = null;
    this.navGroupOpen = new Map();
    this.dialogLifecycle = new WeakMap();
    this.initialRouteApplied = false;
    this.routeSelectionOverride = undefined;
    this.pendingInitialRoute = null;
    app.targetNotes ||= {};
    app.structuralProposals ||= [];
  }

  readPreference(key) { try { return globalThis.localStorage?.getItem(key) || null; } catch { return null; } }
  savePreference(key, value) { try { globalThis.localStorage?.setItem(key, value); } catch {} }
  objects() { return this.app.objectItems?.() || []; }
  object(id) { return this.objects().find(item => item.id === id) || this.draftTarget(id); }
  draftTargetId(operation) {
    const operationId = operation?.operationId || operation?.proposalId;
    if (!operationId) return null;
    if (operation.kind === 'new-scene') return operation.sceneId || `draft-scene-${operationId}`;
    if (operation.kind === 'new-instance') return operation.instanceId || `draft-instance-${operationId}`;
    return null;
  }
  draftInstanceOperation(targetId) {
    return (this.app.structuralProposals || []).find(operation => operation.kind === 'new-instance' && this.draftTargetId(operation) === targetId && Array.isArray(operation.requestedPosition)) || null;
  }
  draftInstanceMetadata(operation, definition = null) {
    const definitionMeta = this.metadata(definition || this.objects().find(object => object.id === operation?.definitionId));
    return {
      role: 'instance', scope: operation?.scope || 'scene', sceneId: operation?.sceneId,
      definitionId: operation?.definitionId,
      position: operation?.requestedPosition,
      size: Array.isArray(operation?.size) ? operation.size : definitionMeta.size,
      anchor: Array.isArray(operation?.anchor) ? operation.anchor : definitionMeta.anchor,
      lock: operation?.lock || 'free',
      nudgeStep: operation?.nudgeStep ?? definitionMeta.nudgeStep,
    };
  }
  draftTargets() {
    const targets = [];
    for (const operation of this.app.structuralProposals || []) {
      const id = this.draftTargetId(operation);
      if (!id) continue;
      if (operation.kind === 'new-scene') {
        targets.push({ id, name: operation.name || id, label: operation.name || id, kind: 'scene', fields: [], relations: [], draft: true, operationId: operation.operationId || operation.proposalId,
          workbench: { role: 'scene', scope: 'scene', bounds: operation.bounds || null } });
      } else if (Array.isArray(operation.requestedPosition)) {
        const definition = this.objects().find(object => object.id === operation.definitionId);
        targets.push({ id, name: operation.name || id, label: operation.name || id, kind: 'entity', description: operation.description || '', fields: [], relations: [], draft: true, operationId: operation.operationId || operation.proposalId,
          workbench: { ...this.draftInstanceMetadata(operation, definition), bounds: operation.bounds } });
      }
    }
    return targets;
  }
  draftTarget(id) { return this.draftTargets().find(item => item.id === id) || null; }
  isDraftTarget(id) { return !!this.draftTarget(id); }
  sourceMetadata(object) { return object?.workbench && typeof object.workbench === 'object' ? object.workbench : {}; }
  objectField(object, fieldId) {
    const documented = (this.app.snapshot?.document?.objects || this.app.snapshot?.objectDocument?.objects || [])
      .find(item => item?.id === object?.id);
    return object?.fields?.find(field => field.id === fieldId) || documented?.fields?.find(field => field.id === fieldId) || null;
  }
  geometryBinding(object, key) {
    const meta = this.sourceMetadata(object), fieldId = meta[`${key}FieldId`];
    if (fieldId) return { object, fieldId };
    if (key === 'size' && meta.role === 'instance' && !Object.hasOwn(meta.overrides || {}, 'size')) {
      const definition = this.objects().find(item => item.id === meta.definitionId);
      const definitionMeta = this.sourceMetadata(definition);
      if (definitionMeta.role === 'definition' && definitionMeta.sizeFieldId) return { object: definition, fieldId: definitionMeta.sizeFieldId };
    }
    return null;
  }
  resolveGeometry(object, key, { draft = true } = {}) {
    const meta = this.sourceMetadata(object), binding = this.geometryBinding(object, key);
    if (!binding) return key === 'size' && Object.hasOwn(meta.overrides || {}, key) ? meta.overrides[key] : meta[key];
    const owner = binding.object, field = this.objectField(owner, binding.fieldId);
    if (field?.type !== 'vector2') return null;
    const draftKey = `${owner.id}.${binding.fieldId}`, values = this.app.fieldDraftValues || {};
    if (draft && ['text', 'clarify'].includes(this.fieldDecision(owner.id, binding.fieldId))) return null;
    const value = draft && Object.hasOwn(values, draftKey) ? values[draftKey] : field.value;
    if (!Array.isArray(value) || value.length !== 2 || !value.every(item => typeof item === 'number' && Number.isFinite(item) && (key !== 'size' || item > 0))) return null;
    return [...value];
  }
  metadata(object, options = {}) {
    const meta = this.sourceMetadata(object);
    return { ...meta, position: this.resolveGeometry(object, 'position', options), size: this.resolveGeometry(object, 'size', options) };
  }
  role(object) {
    const role = this.metadata(object).role || object?.role;
    return Object.hasOwn(ROLE_LABELS, role) ? role : 'unmapped';
  }
  roleLabel(object) {
    const role = this.role(object);
    if (role === 'unmapped') return `未映射${object?.kind ? ` · ${object.kind}` : ''}`;
    if (role === 'preset' && this.isTransitionPreset(object.id)) return '过渡预设';
    return ROLE_LABELS[role];
  }
  isTransitionPreset(objectId) {
    if (!objectId) return false;
    const object = this.object(objectId), meta = this.metadata(object);
    const markers = [meta.presetType, meta.presetKind, meta.appliesTo, meta.category, object?.presetType, object?.presetKind]
      .flatMap(value => Array.isArray(value) ? value : [value])
      .map(value => String(value || '').toLowerCase().replace(/[_\s]+/g, '-'));
    const explicitlyTransition = meta.transitionPreset === true || object?.transitionPreset === true || meta.preview?.type === 'transition' || markers.some(value =>
      ['transition', 'scene-transition', 'transition-preset', 'scene-transition-preset'].includes(value)
    );
    const referencedByTransition = this.objects().some(candidate => this.role(candidate) === 'transition' && (
      this.metadata(candidate).presetId === objectId || this.metadata(candidate).transitionPresetId === objectId ||
      this.relations(candidate).some(relation => /preset/i.test(relation.type || '') && (relation.targetId || relation.target) === objectId)
    ));
    return explicitlyTransition || referencedByTransition;
  }
  targetKey(id = this.app.selectedObjectId) { return id || '__project__'; }
  targetName(id = this.app.selectedObjectId) { return id ? (this.object(id)?.name || this.object(id)?.label || id) : (this.app.currentProject?.()?.title || '当前项目'); }
  routeTarget() { return this.app.selectedObjectId || 'project'; }
  currentTarget() { return this.object(this.app.selectedObjectId); }
  noteTargetId(key, note = this.app.targetNotes?.[key]) { return note && Object.hasOwn(note, 'objectId') ? note.objectId : key === '__project__' ? null : key; }
  currentNote() { return this.app.targetNotes?.[this.targetKey()]?.text || ''; }

  bind() {
    if (this.bound) return;
    this.bound = true;
    $('#workbench-nav-toggle')?.addEventListener('click', () => this.toggleNav());
    $('#workbench-search')?.addEventListener('input', event => { this.search = event.target.value; this.renderCatalog(); });
    $('#workbench-search')?.addEventListener('keydown', event => {
      if (event.key !== 'Enter') return;
      event.preventDefault();
      const query = event.target.value.trim();
      const found = this.objects().find(item => item.id === query);
      if (found) { this.app.selectObject(found.id); this.syncUrl(); $('#workbench-search-status').textContent = `已按精确 ID 定位：${found.id}`; }
      else $('#workbench-search-status').textContent = query ? `没有精确 ID 为“${query}”的对象；当前按名称或 ID 片段筛选。` : '输入 ID 后回车可精确定位。';
    });
    $('#workbench-category')?.addEventListener('change', event => { this.category = event.target.value; this.renderCatalog(); });
    $('#object-catalog')?.addEventListener('click', event => this.onWorkbenchClick(event));
    $('#workbench-report-confirm')?.addEventListener('click', () => this.confirmReport());
    $('#workbench-submit')?.addEventListener('click', () => this.openReport());
    $('#workbench-report-content')?.addEventListener('input', event => {
      const noteEditor = event.target.closest('[data-report-note-editor]');
      if (noteEditor) { this.updateReportNoteBuffer(noteEditor.dataset.reportNoteEditor, noteEditor.value); return; }
      const feedbackEditor = event.target.closest('[data-report-feedback-editor]');
      if (feedbackEditor) this.updateReportFeedbackBuffer(feedbackEditor.dataset.reportFeedbackEditor, feedbackEditor.value);
    });
    $('#workbench-report-content')?.addEventListener('change', event => {
      const feedbackCategory = event.target.closest('[data-report-feedback-category]');
      if (feedbackCategory) this.updateReportFeedbackCategory(feedbackCategory.dataset.reportFeedbackCategory, feedbackCategory.value);
    });
    $('#workbench-proposal-form')?.addEventListener('submit', event => { event.preventDefault(); this.addProposalFromForm(); });
    $('#workbench-report-dialog')?.addEventListener('cancel', () => { this.invalidateReportSession(); });
    $('#workbench-proposal-dialog')?.addEventListener('cancel', () => { this.pendingProposalType = null; });
    for (const dialog of [$('#workbench-report-dialog'), $('#workbench-proposal-dialog'), $('#raw-draft-recovery-dialog')].filter(Boolean)) {
      dialog.addEventListener('keydown', event => this.trapDialogTab(event, dialog));
      dialog.addEventListener('close', () => this.restoreDialogLifecycle(dialog));
    }
    $('#edit-text')?.addEventListener('input', () => { this.persistCurrentNote(); this.queueHistory(); });
    $('#edit-text')?.addEventListener('change', () => this.pushHistory());
    $('#dynamic-fields')?.addEventListener('input', () => {
      this.queueHistory();
      this.stopPreview();
      queueMicrotask(() => { this.renderCanvas(); this.renderPreview(); this.renderInspector(); });
    });
    $('#dynamic-fields')?.addEventListener('change', () => this.pushHistory());
    $('#feedback-message')?.addEventListener('input', () => this.queueHistory());
    $('#feedback-category')?.addEventListener('change', () => this.queueHistory());
    $('#object-detail')?.addEventListener('input', event => {
      const editor = event.target.closest('[data-associated-note-key]');
      if (!editor) return;
      const key = editor.dataset.associatedNoteKey, previous = this.app.targetNotes?.[key];
      if (!previous) return;
      if (previous.text !== editor.value) this.app.targetNotes[key] = { ...previous, text: editor.value, feedbackId: previous.feedbackId || this.app.newFeedbackId?.(), objectId: Object.hasOwn(previous, 'objectId') ? previous.objectId : (this.app.selectedObjectId || null), updatedAt: new Date().toISOString() };
      this.app.queueDraftSave?.(); this.queueHistory();
    });
    $('#object-detail')?.addEventListener('click', event => {
      const remove = event.target.closest('[data-remove-associated-note]');
      if (!remove) return;
      this.pushHistory(); delete this.app.targetNotes[remove.dataset.removeAssociatedNote]; this.app.queueDraftSave?.(); this.pushHistory(); this.render();
    });
    $('#workbench-mobile-panes')?.addEventListener('click', event => {
      const button = event.target.closest('[data-mobile-pane]');
      if (button) this.setMobilePane(button.dataset.mobilePane);
    });
    $('#theme-toggle')?.addEventListener('click', () => this.toggleTheme());
    globalThis.addEventListener?.('popstate', () => this.restoreRoute());
    this.installActionHandlers();
    this.applyTheme(this.readPreference('ptah-studio-theme') || 'light');
    this.applyFoldState();
  }

  dialogFocusableElements(dialog) {
    const selector = 'a[href], area[href], input:not([type="hidden"]), select, textarea, button, iframe, object, embed, [contenteditable="true"], [tabindex], summary, audio[controls], video[controls]';
    const view = dialog.ownerDocument.defaultView;
    return [...dialog.querySelectorAll(selector)].filter(element => {
      if (element.tabIndex < 0 || element.matches(':disabled') || element.getAttribute('aria-disabled') === 'true') return false;
      for (let parent = element; parent; parent = parent.parentElement) {
        if (parent.hidden || parent.inert || parent.getAttribute('aria-hidden') === 'true' || parent.classList?.contains('hidden')) return false;
        if (parent.tagName === 'DETAILS' && !parent.open && !element.closest('summary')) return false;
        const style = view?.getComputedStyle?.(parent);
        if (style && (style.display === 'none' || style.visibility === 'hidden' || style.visibility === 'collapse')) return false;
        if (parent === dialog) break;
      }
      return true;
    });
  }

  trapDialogTab(event, dialog) {
    if (event.key !== 'Tab' || !dialog.open) return;
    const focusable = this.dialogFocusableElements(dialog);
    if (!focusable.length) {
      event.preventDefault();
      dialog.focus?.({ preventScroll: true });
      return;
    }
    const first = focusable[0], last = focusable.at(-1), active = dialog.ownerDocument.activeElement;
    if (event.shiftKey && (active === first || !focusable.includes(active))) {
      event.preventDefault(); last.focus({ preventScroll: true });
    } else if (!event.shiftKey && (active === last || !focusable.includes(active))) {
      event.preventDefault(); first.focus({ preventScroll: true });
    }
  }

  showWorkbenchDialog(dialog) {
    if (!dialog || dialog.open) return false;
    const doc = dialog.ownerDocument, view = doc.defaultView, body = doc.body;
    const state = {
      focusTarget: doc.activeElement,
      scrollX: view?.scrollX ?? 0,
      scrollY: view?.scrollY ?? view?.pageYOffset ?? 0,
      overflow: body?.style.getPropertyValue('overflow') || '',
      overflowPriority: body?.style.getPropertyPriority('overflow') || '',
    };
    this.dialogLifecycle.set(dialog, state);
    body?.style.setProperty('overflow', 'hidden');
    try {
      dialog.showModal?.();
    } catch (error) {
      this.restoreDialogLifecycle(dialog);
      throw error;
    }
    if (!dialog.open) this.restoreDialogLifecycle(dialog);
    return dialog.open;
  }

  restoreDialogLifecycle(dialog) {
    const state = dialog && this.dialogLifecycle.get(dialog);
    if (!state) return;
    this.dialogLifecycle.delete(dialog);
    const doc = dialog.ownerDocument, view = doc.defaultView, body = doc.body;
    if (body) {
      if (state.overflow) body.style.setProperty('overflow', state.overflow, state.overflowPriority);
      else body.style.removeProperty('overflow');
    }
    let focusTarget = state.focusTarget;
    if (!focusTarget?.isConnected || focusTarget === doc.body || focusTarget === doc.documentElement) focusTarget = doc.querySelector('#edit-text');
    try { focusTarget?.focus?.({ preventScroll: true }); }
    catch { focusTarget?.focus?.(); }
    const currentX = view?.scrollX ?? 0, currentY = view?.scrollY ?? view?.pageYOffset ?? 0;
    if (view?.scrollTo && (currentX !== state.scrollX || currentY !== state.scrollY)) {
      try { view.scrollTo(state.scrollX, state.scrollY); } catch {}
    }
  }

  closeWorkbenchDialog(dialog) {
    if (!dialog) return;
    if (dialog === $('#workbench-report-dialog')) this.invalidateReportSession();
    try { dialog.close?.(); }
    finally { this.restoreDialogLifecycle(dialog); }
  }

  invalidateReportSession() {
    this.reportSessionSequence += 1;
    this.reportFingerprint = null;
  }

  installActionHandlers() {
    for (const root of [$('#object-catalog'), $('#workbench-stage'), $('#workbench-report-dialog'), $('#workbench-proposal-dialog')].filter(Boolean)) {
      root.addEventListener('click', event => {
        const actionElement = event.target.closest('[data-workbench-action]');
        const action = actionElement?.dataset.workbenchAction;
        if (!action) return;
        const actionRoot = actionElement.closest('#workbench-stage, #object-catalog, #workbench-report-dialog, #workbench-proposal-dialog');
        if (actionRoot !== root) return;
        event.preventDefault();
        const targetButton = actionElement.closest('[data-target-id]');
        const proposalButton = actionElement.closest('[data-proposal-id]');
        const operationButton = actionElement.closest('[data-operation-id]');
        const reportButton = actionElement.closest('[data-report-note-id], [data-report-feedback-id], [data-field-change-id]');
        const conflictButton = actionElement.closest('.workbench-conflict-resolution [data-object-id][data-field-id][data-note-id]');
        if (targetButton && action === 'locate-target') return this.locateTarget(targetButton.dataset.targetId);
        if (proposalButton && action === 'remove-proposal') return this.removeProposal(proposalButton.dataset.proposalId);
        if (operationButton && action === 'remove-operation') return this.removeProposal(operationButton.dataset.operationId);
        if (reportButton && action === 'edit-report-note') return this.editReportNote(reportButton.dataset.reportNoteId);
        if (reportButton && action === 'save-report-note') return this.saveReportNote(reportButton.dataset.reportNoteId);
        if (reportButton && action === 'cancel-report-note-edit') return this.cancelReportNoteEdit();
        if (reportButton && action === 'remove-report-note') return this.removeReportNote(reportButton.dataset.reportNoteId);
        if (reportButton && action === 'edit-report-feedback') return this.editReportFeedback(reportButton.dataset.reportFeedbackId);
        if (reportButton && action === 'save-report-feedback') return this.saveReportFeedback(reportButton.dataset.reportFeedbackId);
        if (reportButton && action === 'cancel-report-feedback-edit') return this.cancelReportFeedbackEdit();
        if (reportButton && action === 'remove-report-feedback') return this.removeReportFeedback(reportButton.dataset.reportFeedbackId);
        if (reportButton && action === 'remove-field-change') return this.removeFieldChange(reportButton.dataset.objectId, reportButton.dataset.fieldId);
        if (conflictButton && action === 'apply-conflict-decision') return this.applyConflictDecision(conflictButton);
        if (action === 'new-scene') return this.openProposal('new-scene');
        if (action === 'new-instance') return this.openProposal('new-instance');
        if (action === 'new-transition') return this.openProposal('transition');
        if (action === 'delete-instance') return this.proposeDelete(actionElement.closest('[data-object-id]')?.dataset.objectId);
        if (action === 'save') return this.saveDraft();
        if (action === 'restore') return this.restoreSavedDraft();
        if (action === 'export') return this.exportDraft();
        if (action === 'reset-draft') return this.resetDraft();
        if (action === 'undo') return this.undo();
        if (action === 'redo') return this.redo();
        if (action === 'preview-report') return this.openReport();
        if (action === 'clear-note') return this.clearCurrentNote();
        if (action === 'close-report') return this.closeWorkbenchDialog($('#workbench-report-dialog'));
        if (action === 'close-proposal') { this.pendingProposalType = null; this.pendingProposalObjectId = null; return this.closeWorkbenchDialog($('#workbench-proposal-dialog')); }
        if (action === 'nudge') return this.nudgeSelected(Number(actionElement.dataset.dx || 0), Number(actionElement.dataset.dy || 0), actionElement.dataset.objectId);
        if (action === 'set-instance-lock') return this.setInstanceLock(actionElement.dataset.objectId, actionElement.closest('.workbench-lock-control')?.querySelector('[name="requestedLock"]')?.value);
        if (action === 'set-draft-instance-lock') return this.setDraftInstanceLock(actionElement.dataset.operationId, actionElement.closest('.workbench-draft-instance-row')?.querySelector('[name="draftLock"]')?.value);
        if (action === 'toggle-grid') { this.gridVisible = !this.gridVisible; this.savePreference('ptah-studio-workbench-grid', this.gridVisible ? 'shown' : 'hidden'); return this.render(); }
        if (action === 'toggle-guides') { this.guidesVisible = !this.guidesVisible; this.savePreference('ptah-studio-workbench-guides', this.guidesVisible ? 'shown' : 'hidden'); return this.render(); }
        if (action === 'preview-layout-proposal') return this.previewLocalLayoutProposal(actionElement.dataset.sceneId, Number(actionElement.closest('.workbench-layout-tools')?.querySelector('[name="gridStep"]')?.value || 80));
        if (action === 'cancel-layout-proposal') { this.localLayoutProposal = null; return this.render(); }
        if (action === 'apply-layout-proposal') return this.applyLocalLayoutProposal();
        if (action === 'preview-decor-example') return this.previewDecorationExample(actionElement.dataset.sceneId);
        if (action === 'cancel-decor-example') { this.localDecorationProposal = null; this.decorationExampleStatus = ''; return this.render(); }
        if (action === 'apply-decor-example') return this.applyDecorationExample();
        if (action === 'preview-timing-example') return this.previewTimingExample();
        if (action === 'cancel-timing-example') { this.localTimingProposal = null; this.timingExampleStatus = ''; return this.render(); }
        if (action === 'apply-timing-example') return this.applyTimingExample();
        if (action === 'select-template-scene') { this.selectDraftTarget(actionElement.dataset.sceneId); return; }
        if (action === 'play-preview') return this.playPreview();
        if (action === 'stop-preview') { this.stopPreview(); this.renderPreview(); return; }
        if (action === 'switch-scene') return this.switchScene(actionElement.dataset.sceneId);
        if (action === 'load-source') return this.loadSource(actionElement.dataset.objectId, actionElement.closest('details'));
        if (action === 'load-bound-preview') return this.loadBoundPreview(actionElement.dataset.objectId);
      });
    }
    $('#workbench-stage')?.addEventListener('click', event => {
      const action = event.target.closest('[data-workbench-action]');
      if (action) {
        if (action.dataset.workbenchAction === 'cancel-placement') { event.preventDefault(); this.cancelPendingPlacement(); }
        return;
      }
      if (event.target.closest('input, textarea, select, [contenteditable="true"]')) return;
      const target = event.target.closest('[data-object-id]');
      if (target && this.object(target.dataset.objectId)) {
        if (this.isDraftTarget(target.dataset.objectId)) this.selectDraftTarget(target.dataset.objectId);
        else { this.app.selectObject(target.dataset.objectId); this.syncUrl(); }
        return;
      }
      const canvas = event.target.closest('.workbench-coordinate-canvas[data-canvas]');
      if (canvas && this.pendingPlacementOperationId) this.placePendingInstance(event, canvas);
      if (event.target.closest('[data-action="move-op"]')) this.openMoveEditor();
    });
    $('#workbench-stage')?.addEventListener('pointerdown', event => this.beginDrag(event));
    $('#workbench-stage')?.addEventListener('pointermove', event => {
      if (this.drag) this.moveDrag(event);
      else if (this.pendingPlacementOperationId) {
        const canvas = event.target.closest('.workbench-coordinate-canvas[data-canvas]');
        if (canvas) this.previewPendingInstance(event, canvas);
      }
    });
    $('#workbench-stage')?.addEventListener('pointerup', event => this.endDrag(event));
    $('#workbench-stage')?.addEventListener('pointercancel', event => this.endDrag(event));
    globalThis.addEventListener?.('keydown', event => {
      if (event.key === 'Escape') {
        if (this.pendingPlacementOperationId) { event.preventDefault(); this.cancelPendingPlacement(); }
        else if (this.drag) { event.preventDefault(); this.cancelDrag(); }
        return;
      }
      if (event.altKey || (!event.ctrlKey && !event.metaKey)) return;
      const target = event.target;
      if (target?.closest?.('input, textarea, select, [contenteditable="true"]')) return;
      if (document.querySelector('dialog[open]') || this.pendingPlacementOperationId || this.drag) return;
      const key = String(event.key || '').toLowerCase();
      if (key === 'z') { event.preventDefault(); return event.shiftKey ? this.redo() : this.undo(); }
      if (key === 'y') { event.preventDefault(); return this.redo(); }
    });
    $('#workbench-nav')?.addEventListener('click', event => {
      const project = event.target.closest('[data-workbench-project]');
      if (project) { this.selectProject(); return; }
      const button = event.target.closest('[data-object-id]');
      if (button && this.isDraftTarget(button.dataset.objectId)) this.selectDraftTarget(button.dataset.objectId);
      else if (button && this.object(button.dataset.objectId)) this.syncUrl();
    });
  }

  onWorkbenchClick(event) {
    if (event.target.closest('[data-workbench-action], input, textarea, select, [contenteditable="true"]')) return;
    const tab = event.target.closest('[data-workbench-view]');
    if (tab) return this.setView(tab.dataset.workbenchView);
    const pane = event.target.closest('#workbench-mobile-panes button[data-mobile-pane]');
    if (pane) return this.setMobilePane(pane.dataset.mobilePane);
    const target = event.target.closest('[data-target-id="project"]');
    if (target) this.selectProject();
    if (event.target.closest('#workbench-stage')) return;
    const objectButton = event.target.closest('[data-object-id]');
    if (objectButton && this.object(objectButton.dataset.objectId)) {
      if (this.isDraftTarget(objectButton.dataset.objectId)) this.selectDraftTarget(objectButton.dataset.objectId);
      else { this.app.selectObject(objectButton.dataset.objectId); this.syncUrl(); }
    }
  }

  onViewTab(event) { const button = event.target.closest('[data-workbench-view]'); if (button) this.setView(button.dataset.workbenchView); }

  applyInitialRoute() {
    if (this.initialRouteApplied || !this.app.snapshot) return;
    this.initialRouteApplied = true;
    const params = new URLSearchParams(globalThis.location?.search || '');
    const route = this.app.routeOnLoad || { target: params.get('target'), view: params.get('view'), scene: params.get('scene') };
    this.app.routeOnLoad = null;
    const canResolveTarget = !route.target || route.target === 'project' || !!this.object(route.target);
    const canResolveScene = !route.scene || this.scenes().some(scene => scene.id === route.scene);
    const deferUntilDraftRestore = !canResolveTarget || !canResolveScene;
    this.routeSelectionOverride = route.target === 'project' ? null : (route.target && !deferUntilDraftRestore ? route.target : undefined);
    if (['design', 'narrative', 'art'].includes(route.view)) this.view = route.view;
    if (deferUntilDraftRestore) this.pendingInitialRoute = route;
    this.restoringRoute = true;
    if (route.target === 'project') this.selectProject({ route: false, saveCurrent: false });
    else if (route.target && this.isDraftTarget(route.target)) this.selectDraftTarget(route.target, { route: false, saveCurrent: false });
    else if (route.target && this.object(route.target)) this.app.selectObject(route.target);
    if (!deferUntilDraftRestore && route.scene && this.scenes().some(scene => scene.id === route.scene)) { this.activeSceneId = route.scene; this.sceneCanvasSelection = route.scene; }
    this.restoringRoute = false;
    this.render();
    if (!deferUntilDraftRestore) this.syncUrl(true);
    this.resetHistory();
  }

  initialRouteIsAvailable(route) {
    const targetAvailable = !route?.target || route.target === 'project' || !!this.object(route.target);
    const sceneAvailable = !route?.scene || this.scenes().some(scene => scene.id === route.scene);
    return targetAvailable && sceneAvailable;
  }

  resolvePendingInitialRoute() {
    const route = this.pendingInitialRoute;
    if (!route || !this.initialRouteIsAvailable(route)) return false;
    this.pendingInitialRoute = null;
    this.routeSelectionOverride = route.target === 'project' ? null : (route.target || undefined);
    if (['design', 'narrative', 'art'].includes(route.view)) this.view = route.view;
    this.restoringRoute = true;
    try {
      if (route.target === 'project') this.selectProject({ route: false, saveCurrent: false });
      else if (route.target && this.isDraftTarget(route.target)) this.selectDraftTarget(route.target, { route: false, saveCurrent: false });
      else if (route.target && this.object(route.target)) this.app.selectObject(route.target);
      if (route.scene && this.scenes().some(scene => scene.id === route.scene)) {
        this.activeSceneId = route.scene;
        this.sceneCanvasSelection = route.scene;
      }
      this.render();
    } finally {
      this.restoringRoute = false;
    }
    this.syncUrl(true);
    this.resetHistory();
    return true;
  }

  finishInitialRouteHydration() {
    if (!this.pendingInitialRoute) return false;
    if (this.resolvePendingInitialRoute()) return true;
    const invalid = this.pendingInitialRoute;
    this.pendingInitialRoute = null;
    this.routeSelectionOverride = undefined;
    this.syncUrl(true);
    const missing = invalid.target && invalid.target !== 'project' && !this.object(invalid.target)
      ? `对象“${invalid.target}”不在当前项目中。`
      : invalid.scene ? `场景“${invalid.scene}”不在当前项目中。` : '此链接中的对象或场景已不可用。';
    this.app.notify?.(`${missing}当前项目草稿已保留，已回到可用的项目上下文。`);
    return false;
  }

  restoreRoute() {
    const params = new URLSearchParams(globalThis.location?.search || '');
    const projectId = params.get('project');
    const target = params.get('target');
    const view = params.get('view');
    if (!projectId) {
      this.pendingInitialRoute = null;
      this.routeSelectionOverride = undefined;
      this.app.showProjectManager?.();
      return;
    }
    if (projectId !== this.app.projectId) {
      this.app.routeOnLoad = { target, view, scene: params.get('scene') };
      this.app.openProject(projectId, params.get('stage') === 'iteration' ? 'iteration' : 'initial', false);
      return;
    }
    const scene = params.get('scene');
    const targetAvailable = !target || target === 'project' || !!this.object(target);
    const sceneAvailable = !scene || this.scenes().some(item => item.id === scene);
    if ((!targetAvailable || !sceneAvailable) && this.app.draftRestoreContext) {
      this.pendingInitialRoute = { target, view, scene };
      this.routeSelectionOverride = undefined;
      return;
    }
    if (!targetAvailable || !sceneAvailable) {
      const missing = !targetAvailable ? `对象“${target}”不在当前项目中。` : `场景“${scene}”不在当前项目中。`;
      this.app.notify?.(`${missing}当前草稿已保留，仍显示现有项目上下文。`);
      this.syncUrl(true);
      return;
    }
    if (['design', 'narrative', 'art'].includes(view)) this.view = view;
    this.restoringRoute = true;
    if (!target || target === 'project') this.selectProject({ route: false });
    else if (target && this.isDraftTarget(target)) this.selectDraftTarget(target, { route: false });
    else if (target && this.object(target)) this.app.selectObject(target);
    if (scene) { this.activeSceneId = scene; this.sceneCanvasSelection = scene; }
    this.restoringRoute = false;
    this.render();
    this.syncUrl(true);
    this.setMobilePane('stage');
  }

  syncUrl(replace = false) {
    if (!globalThis.history?.pushState || !this.app.projectId) return;
    const params = new URLSearchParams(globalThis.location.search || '');
    params.set('project', this.app.projectId);
    if (this.app.stage === 'iteration') params.set('stage', 'iteration'); else params.delete('stage');
    params.set('target', this.routeTarget());
    params.set('view', this.view);
    if (this.activeSceneId) params.set('scene', this.activeSceneId); else params.delete('scene');
    const url = `${globalThis.location.pathname}?${params.toString()}${globalThis.location.hash || ''}`;
    if (replace) globalThis.history.replaceState({ workbench: true }, '', url);
    else if (url !== `${globalThis.location.pathname}${globalThis.location.search}${globalThis.location.hash}`) globalThis.history.pushState({ workbench: true }, '', url);
  }

  setView(view) {
    if (!['design', 'narrative', 'art'].includes(view) || this.view === view) return;
    this.view = view;
    this.stopPreview();
    this.render();
    this.syncUrl();
  }

  setMobilePane(pane) {
    if (!['nav', 'stage', 'inspect'].includes(pane)) return;
    this.mobilePane = pane;
    $('#workbench-body')?.setAttribute('data-mobile-pane', pane);
    for (const button of $('#workbench-mobile-panes')?.querySelectorAll('[data-mobile-pane]') || []) button.setAttribute('aria-pressed', String(button.dataset.mobilePane === pane));
  }

  toggleNav() {
    this.folded = !this.folded;
    this.savePreference('ptah-studio-workbench-nav', this.folded ? 'folded' : 'open');
    this.applyFoldState();
  }
  applyFoldState() {
    $('#workbench-body')?.classList.toggle('nav-folded', this.folded);
    const button = $('#workbench-nav-toggle');
    if (button) { button.textContent = this.folded ? '展开导航' : '折叠导航'; button.setAttribute('aria-expanded', String(!this.folded)); }
  }

  toggleTheme() { this.applyTheme(document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark'); }
  applyTheme(theme) {
    const value = theme === 'dark' ? 'dark' : 'light';
    document.documentElement.dataset.theme = value;
    this.savePreference('ptah-studio-theme', value);
    const button = $('#theme-toggle');
    if (button) { button.textContent = value === 'dark' ? '浅色主题' : '深色主题'; button.setAttribute('aria-pressed', String(value === 'dark')); }
    $('meta[name="theme-color"]')?.setAttribute('content', value === 'dark' ? '#141b28' : '#f5f7fb');
  }

  selectProject({ route = true, saveCurrent = true } = {}) {
    if (saveCurrent) this.persistCurrentNote();
    this.app.captureVisibleFields?.();
    this.app.saveFeedbackInputForCurrentTarget?.();
    this.app.selectedObjectId = null;
    if (route) this.sceneCanvasSelection = null;
    this.app.renderDynamicFields?.(this.objects(), this.app.capabilities);
    this.app.renderObjectDetail?.();
    this.app.renderFeedback?.();
    this.app.loadFeedbackInputForCurrentTarget?.();
    this.loadCurrentNote();
    this.render();
    if (!this.restoringRoute) this.app.queueDraftSave?.();
    if (route) this.syncUrl();
  }

  selectDraftTarget(targetId, { route = true, saveCurrent = true } = {}) {
    const target = this.draftTarget(targetId);
    if (!target) return false;
    if (saveCurrent) this.beforeTargetChange();
    this.app.captureVisibleFields?.();
    this.app.saveFeedbackInputForCurrentTarget?.();
    this.app.selectedObjectId = target.id;
    const meta = this.metadata(target);
    const sceneId = this.role(target) === 'scene' ? target.id : meta.sceneId;
    if (sceneId) { this.activeSceneId = sceneId; this.sceneCanvasSelection = sceneId; }
    this.app.renderDynamicFields?.(this.objects(), this.app.capabilities);
    this.app.renderObjectCatalog?.(this.objects());
    this.app.renderObjectDetail?.();
    this.app.renderFeedback?.();
    this.app.loadFeedbackInputForCurrentTarget?.();
    this.onTargetChange({ route });
    return true;
  }

  beforeTargetChange() { this.persistCurrentNote(); }
  onTargetChange({ route = true } = {}) {
    this.stopPreview();
    const target = this.currentTarget(), metadata = this.metadata(target);
    const sceneId = metadata.sceneId || (this.role(target) === 'scene' ? target.id : null);
    if (sceneId) { this.activeSceneId = sceneId; this.sceneCanvasSelection = sceneId; }
    this.loadCurrentNote();
    this.render();
    if (!this.restoringRoute) this.app.queueDraftSave?.();
    if (route && !this.restoringRoute) this.syncUrl();
  }

  persistCurrentNote() {
    if (!this.app.targetNotes) this.app.targetNotes = {};
    const key = this.targetKey();
    const text = $('#edit-text')?.value || '';
    if (!text) { delete this.app.targetNotes[key]; return; }
    const previous = this.app.targetNotes[key] || {};
    if (previous.text === text) return;
    this.app.targetNotes[key] = { ...previous, text, objectId: Object.hasOwn(previous, 'objectId') ? previous.objectId : (this.app.selectedObjectId || null), feedbackId: previous.feedbackId || this.app.newFeedbackId?.() || `note-${Date.now()}`, updatedAt: new Date().toISOString() };
    this.app.queueDraftSave?.();
  }

  loadCurrentNote() {
    const input = $('#edit-text');
    if (input) input.value = this.currentNote();
    this.renderSelectedTargetLabel(this.currentTarget());
    const selected = this.currentTarget();
    const status = $('#workbench-target-status');
    if (status) status.textContent = selected ? '意见将关联当前对象' : '意见将关联当前项目';
  }

  renderSelectedTargetLabel(selected) {
    const label = $('#selected-object-label');
    if (!label) return;
    label.replaceChildren(el('span', '', selected ? `当前目标：${selected.name || selected.label || selected.id}` : '当前目标：项目'));
    if (!selected?.id) return;
    const identity = el('details', 'workbench-target-identity');
    identity.append(el('summary', '', '查看对象 ID'), el('code', '', selected.id));
    const copyButton = el('button', 'button quiet', '复制 ID'); copyButton.type = 'button';
    copyButton.addEventListener('click', async () => {
      try {
        if (!globalThis.navigator?.clipboard?.writeText) throw new Error('剪贴板不可用');
        await globalThis.navigator.clipboard.writeText(selected.id); this.app.notify?.('对象 ID 已复制。');
      } catch { this.app.notify?.(`对象 ID：${selected.id}`); }
    });
    identity.append(copyButton); label.append(identity);
  }

  render() {
    if (!this.app.snapshot) return;
    this.resolvePendingInitialRoute();
    const context = this.sourceContextKey();
    if (this.workbenchContext && this.workbenchContext !== context) {
      this.clearTransientInteractions(); this.stopPreview();
      this.sourceCache.clear(); this.previewCache.clear();
      this.localLayoutProposal = null; this.localDecorationProposal = null; this.localTimingProposal = null; this.layoutSelectionByScene.clear();
    }
    this.workbenchContext = context;
    this.renderCatalog();
    this.renderTabs();
    this.renderBreadcrumb();
    this.renderSceneChoices();
    this.renderCanvas();
    this.renderPreview();
    this.renderInspector();
    this.renderResults();
    this.renderOrphanNotes();
    this.renderOperationList();
    this.applyFoldState();
    this.setMobilePane(this.mobilePane);
    this.refreshCheckpointStatus();
    this.updateHistoryButtons();
  }

  sourceContextKey() {
    const snapshot = this.app.snapshot || {};
    return JSON.stringify({
      projectId: this.app.projectId || null,
      publicationRevision: snapshot.publicationRevision ?? null,
      sourceCommit: snapshot.sourceCommit || snapshot.baseCommit || null,
    });
  }

  syncIterationLayout(iterationOpen) {
    const panel = $('#workbench-panel'), proposal = $('#proposal-panel'), jobPanel = $('#job-panel');
    if (!panel || !proposal || !jobPanel || panel.parentNode !== proposal.parentNode) return;
    if (iterationOpen) {
      if (panel.nextElementSibling !== proposal) panel.parentNode.insertBefore(panel, proposal);
    } else if (jobPanel.nextElementSibling !== panel) jobPanel.after(panel);
    const summary = $('#workbench-flow-summary');
    if (!summary) return;
    hide(summary, !iterationOpen);
    if (!iterationOpen) return;
    const blockingStatuses = new Set(['QUEUED', 'DISPATCHING', 'RUNNING', 'VERIFYING', 'PROJECTING', 'UNCERTAIN', 'CANCEL_REQUESTED', 'CANCELLING', 'READY_FOR_REVIEW']);
    const projectId = this.app.projectId;
    const jobs = [this.app.projectView?.job, this.app.job, ...(this.app.workspace?.jobs || [])]
      .filter(job => job?.projectId === projectId);
    const blocking = jobs.find(job => blockingStatuses.has(String(job.status || '').toUpperCase()));
    const job = blocking || jobs.find(job => this.app.isHistoricalJob?.(job) !== true);
    const signature = JSON.stringify([projectId, job?.id, job?.status, !!blocking]);
    if (summary.dataset.context === signature) return;
    summary.dataset.context = signature;
    summary.replaceChildren();
    const text = blocking
      ? `${this.workflowLabel(blocking.status)}：可继续编辑本地草稿；新的申报需先处理现有作业。`
      : '先选择对象，在预览和本目标意见中继续调整。';
    summary.append(el('p', '', text));
    if (job?.id) {
      const view = el('button', 'button secondary', String(job.status).toUpperCase() === 'READY_FOR_REVIEW' ? '查看待审候选' : '查看当前处理状态');
      view.type = 'button';
      view.addEventListener('click', () => {
        if (this.app.job?.id !== job.id) this.app.selectJob?.(job.id);
        jobPanel.scrollIntoView?.({ behavior: 'smooth', block: 'start' });
      });
      summary.append(view);
    }
  }

  renderCatalog() {
    const root = $('#object-catalog');
    const list = $('#object-list');
    if (!root || !list) return;
    hide(root, false);
    const all = [...this.objects(), ...this.draftTargets()];
    const roleValues = [...new Set(all.map(object => this.role(object)))].sort((a, b) => (ROLE_LABELS[a] || '未映射').localeCompare(ROLE_LABELS[b] || '未映射', 'zh-CN'));
    const category = $('#workbench-category');
    if (category) {
      const current = this.category;
      category.replaceChildren(new Option('全部分类', 'all'));
      for (const role of roleValues) category.append(new Option(role === 'unmapped' ? '未映射' : ROLE_LABELS[role], role));
      category.value = roleValues.includes(current) || current === 'all' ? current : 'all';
      this.category = category.value;
    }
    list.replaceChildren();
    const project = el('button', `workbench-nav-project${this.app.selectedObjectId ? '' : ' selected'}`);
    project.type = 'button'; project.dataset.workbenchProject = 'true'; project.dataset.targetId = 'project'; project.append(el('b', '', '项目级'), el('span', 'muted', '项目意见与概览')); list.append(project);
    const query = this.search.trim().toLocaleLowerCase();
    const filtered = all.filter(object => {
      const role = this.role(object);
      if (this.category !== 'all' && role !== this.category) return false;
      if (!query) return true;
      return `${object.name || object.label || ''} ${object.id || ''}`.toLocaleLowerCase().includes(query);
    });
    const groups = new Map();
    for (const object of filtered) { const role = this.role(object); if (!groups.has(role)) groups.set(role, []); groups.get(role).push(object); }
    for (const [role, objects] of groups) {
      const group = el('details', 'workbench-nav-group'); group.open = this.navGroupOpen.has(role) ? this.navGroupOpen.get(role) : true;
      group.addEventListener('toggle', () => { if (group.isConnected) this.navGroupOpen.set(role, group.open); });
      group.append(el('summary', '', `${role === 'unmapped' ? '未映射' : ROLE_LABELS[role]} · ${objects.length}`));
      for (const object of objects) {
        const metadata = this.metadata(object);
        const button = el('button', `workbench-nav-item${object.id === this.app.selectedObjectId ? ' selected' : ''}`);
        button.type = 'button'; button.dataset.objectId = object.id; button.dataset.targetId = object.id;
        button.setAttribute('aria-label', `${object.name || object.label || '未命名对象'}，选择此对象`);
        button.title = `对象 ID：${object.id}`;
        button.append(el('b', '', object.name || object.label || object.id));
        if (metadata.sceneId) button.append(el('span', 'workbench-nav-context', `场景 ${metadata.sceneId}`));
        group.append(button);
      }
      list.append(group);
    }
    if (!filtered.length) list.append(el('p', 'muted workbench-empty', all.length ? '没有符合条件的对象。若知道对象编号，可输入完整编号并回车定位。' : '当前公开快照未提供对象清单。可先写项目级意见，或等待项目对象映射。'));
    const status = $('#workbench-search-status');
    if (status) status.textContent = `显示 ${filtered.length} / ${all.length} 个对象${query ? '；名称与 ID 均参与搜索' : ''}。`;
    const toggle = $('#workbench-nav-toggle');
    if (toggle && !this.bound) toggle.setAttribute('aria-expanded', String(!this.folded));
  }

  renderTabs() {
    for (const button of document.querySelectorAll('[data-workbench-view]')) {
      const selected = button.dataset.workbenchView === this.view;
      button.setAttribute('aria-selected', String(selected));
      button.classList.toggle('selected', selected);
    }
  }

  scenes() {
    const snapshot = this.app.snapshot || {};
    const documentData = snapshot.document || snapshot.objectDocument || {};
    const sceneLists = [snapshot.scenes, snapshot.catalog?.scenes, documentData.scenes, snapshot.objectDocument?.scenes].filter(Array.isArray);
    const result = [];
    for (const list of sceneLists) for (const item of list) if (item?.id && !result.some(scene => scene.id === item.id)) result.push(item);
    for (const object of this.objects()) {
      if (this.role(object) === 'scene') {
        const index = result.findIndex(scene => scene.id === object.id);
        if (index < 0) result.push(object);
        else result[index] = { ...result[index], ...object, bounds: object.bounds || result[index].bounds, workbench: object.workbench || result[index].workbench };
      }
      const sceneId = this.metadata(object).sceneId;
      if (sceneId && !result.some(scene => scene.id === sceneId)) result.push({ id: sceneId, name: sceneId, inferredFromInstances: true });
    }
    for (const operation of this.app.structuralProposals || []) {
      if (operation?.kind !== 'new-scene' || !operation.sceneId || result.some(scene => scene.id === operation.sceneId)) continue;
      result.push({
        id: operation.sceneId,
        name: operation.name || operation.sceneId,
        template: operation.template || 'blank',
        bounds: operation.bounds || operation.workbench?.bounds || null,
        workbench: { role: 'scene', ...(operation.workbench || {}) },
        draft: true,
        operationId: operation.operationId || operation.proposalId,
      });
    }
    return result;
  }

  sceneBounds(sceneId) {
    const scene = this.scenes().find(item => item.id === sceneId);
    const bounds = this.metadata(scene).bounds || scene?.bounds;
    return Array.isArray(bounds) && bounds.length === 2 && bounds.every(value => Number.isFinite(Number(value)) && Number(value) > 0)
      ? bounds.map(Number) : null;
  }

  renderSceneChoices() {
    const root = $('#workbench-scene-list');
    if (!root) return;
    root.replaceChildren();
    const scenes = this.scenes();
    if (!scenes.length) {
      this.activeSceneId = null;
      this.sceneCanvasSelection = null;
      root.append(el('p', 'muted', '当前快照未提供场景清单或实例场景归属。'));
      return;
    }
    if (!this.activeSceneId || !scenes.some(scene => scene.id === this.activeSceneId)) {
      const target = this.currentTarget();
      this.activeSceneId = this.metadata(target).sceneId || (this.role(target) === 'scene' ? target.id : null) || scenes[0].id;
    }
    if (!this.sceneCanvasSelection || !scenes.some(scene => scene.id === this.sceneCanvasSelection)) this.sceneCanvasSelection = this.activeSceneId;
    root.append(el('span', 'workbench-scene-label', '场景 / 房间'));
    for (const scene of scenes) {
      const button = el('button', `workbench-scene-chip${scene.id === this.activeSceneId ? ' selected' : ''}`);
      button.type = 'button'; button.dataset.workbenchAction = 'switch-scene'; button.dataset.sceneId = scene.id;
      button.append(el('b', '', scene.name || scene.label || '未命名场景'), el('small', '', scene.draft ? '本地场景草稿' : scene.inferredFromInstances ? '名称来自实例归属' : '已发布场景')); button.title = `场景 ID：${scene.id}`; root.append(button);
    }
  }

  renderBreadcrumb() {
    const root = $('#workbench-breadcrumb');
    if (!root) return;
    root.replaceChildren();
    const project = el('button', 'breadcrumb-link', this.app.currentProject?.()?.title || '项目'); project.type = 'button'; project.dataset.workbenchProject = 'true'; root.append(project);
    const object = this.currentTarget();
    if (!object) { root.append(el('span', 'breadcrumb-current', '项目概览')); return; }
    const sceneId = this.metadata(object).sceneId || (this.role(object) === 'scene' ? object.id : null);
    if (sceneId) { root.append(el('span', 'breadcrumb-separator', '›')); const scene = el('button', 'breadcrumb-link', this.sceneName(sceneId)); scene.type = 'button'; scene.dataset.workbenchAction = 'switch-scene'; scene.dataset.sceneId = sceneId; root.append(scene); }
    root.append(el('span', 'breadcrumb-separator', '›'), el('span', 'breadcrumb-current', object.name || object.label || object.id));
  }

  sceneName(id) { return this.scenes().find(scene => scene.id === id)?.name || id; }
  objectByRelationId(id) { return this.object(id); }
  displayValue(value) { return value == null || value === '' ? '未提供' : Array.isArray(value) ? value.map(item => typeof item === 'number' ? this.formatNumber(item) : item).join(', ') : typeof value === 'object' ? JSON.stringify(value) : String(value); }
  formatNumber(value) { return Number.isFinite(Number(value)) ? String(Number(Number(value).toFixed(3))) : String(value); }

  renderCanvas() {
    const root = $('#workbench-canvas');
    if (!root) return;
    const previousViewport = root.querySelector('.workbench-coordinate-viewport');
    const previousScroll = previousViewport ? { projectId: previousViewport.dataset.projectId,
      sceneId: previousViewport.firstElementChild?.dataset.sceneId, left: previousViewport.scrollLeft } : null;
    root.replaceChildren();
    const selectedScene = this.sceneCanvasSelection && this.scenes().find(scene => scene.id === this.sceneCanvasSelection);
    const target = this.currentTarget() || (selectedScene ? { ...selectedScene, workbench: { role: 'scene', ...(selectedScene.workbench || {}) } } : null);
    if (this.view !== 'design') { this.renderFacet(root, target, this.view); return; }
    if (!target) { this.renderProjectOverview(root); return; }
    const meta = this.metadata(target);
    const role = this.role(target);
    const heading = el('div', 'workbench-canvas-heading');
    const headingSceneId = selectedScene?.id || meta.sceneId || (role === 'scene' ? target.id : this.activeSceneId);
    heading.append(el('div', '', `${headingSceneId ? `${this.sceneName(headingSceneId)} · 场景视图` : '项目对象'}`));
    heading.append(el('span', 'semantic-badge', selectedScene?.draft ? '本地场景草稿 · 尚未写入源码' : '依据公开场景与实例元数据'));
    const canvasTools = el('div', 'workbench-canvas-tools');
    const gridToggle = el('button', `button quiet${this.gridVisible ? ' active' : ''}`, '网格');
    gridToggle.type = 'button'; gridToggle.dataset.workbenchAction = 'toggle-grid'; gridToggle.setAttribute('aria-pressed', String(this.gridVisible));
    const guideToggle = el('button', `button quiet${this.guidesVisible ? ' active' : ''}`, '入口 / 出口标记');
    guideToggle.type = 'button'; guideToggle.dataset.workbenchAction = 'toggle-guides'; guideToggle.setAttribute('aria-pressed', String(this.guidesVisible));
    canvasTools.append(gridToggle, guideToggle);
    root.append(heading, canvasTools);
    const pendingPlacement = this.pendingPlacement?.operationId === this.pendingPlacementOperationId ? this.pendingPlacement : null;
    const sceneId = pendingPlacement?.sceneId || selectedScene?.id || meta.sceneId || (role === 'scene' ? target.id : this.activeSceneId);
    const scene = this.scenes().find(item => item.id === sceneId);
    const bounds = this.sceneBounds(sceneId);
    const sceneObjects = [...this.objects(), ...this.draftTargets()].filter(item => {
      const itemMeta = this.metadata(item); const itemRole = this.role(item);
      return ['instance', 'entry', 'spawn'].includes(itemRole) && (!sceneId || itemMeta.sceneId === sceneId);
    });
    const positioned = sceneObjects.filter(item => Array.isArray(this.metadata(item).position) && Array.isArray(bounds));
    const validBounds = Array.isArray(bounds) && bounds.length === 2 && Number(bounds[0]) > 0 && Number(bounds[1]) > 0;
    const canvas = el('div', `workbench-coordinate-canvas${positioned.length || validBounds ? ' mapped' : ' semantic'}`);
    canvas.classList.toggle('grid-hidden', !this.gridVisible);
    canvas.classList.toggle('guides-hidden', !this.guidesVisible);
    canvas.dataset.canvas = 'true';
    canvas.dataset.sceneId = sceneId || '';
    const planeBounds = bounds || [100, 60];
    const width = Number(planeBounds[0]), height = Number(planeBounds[1]);
    if (validBounds) canvas.style.aspectRatio = `${width} / ${height}`;
    if (positioned.length || validBounds) {
      canvas.setAttribute('aria-label', `使用已提供边界 ${this.displayValue(planeBounds)} 展示的场景编排`);
      canvas.append(el('div', 'workbench-grid-label', `边界 ${this.displayValue(planeBounds)} · 单位按来源数据`));
      if (!positioned.length) canvas.append(el('div', 'workbench-semantic-note', '场景世界边界已映射；当前没有已定位的公开实例。'));
      for (const item of positioned) this.renderCanvasToken(canvas, item, width, height);
    } else {
      canvas.append(el('div', 'workbench-semantic-note', '没有完整的位置和世界边界数据。下面按已映射的场景归属列出对象，不代表真实游戏布局。'));
      const list = el('div', 'semantic-object-grid');
      const related = sceneObjects.length ? sceneObjects : (selectedScene ? [] : [target]);
      for (const item of related) {
        const button = el('button', `semantic-object-card${item.id === target.id ? ' selected' : ''}`);
        button.type = 'button'; button.dataset.objectId = item.id; button.append(el('b', '', item.name || item.id), el('span', '', this.roleLabel(item)), el('small', '', `ID ${item.id}`)); list.append(button);
      }
      canvas.append(list);
    }
    if (scene?.draft && scene.template === 'minimal') this.renderMinimalTemplateMarkers(canvas, scene, width, height, validBounds);
    if (pendingPlacement?.sceneId === sceneId) {
      const instruction = el('div', 'workbench-placement-instruction');
      instruction.append(el('span', '', `放置“${pendingPlacement.name || '新实例'}”：点击场景中的目标位置`));
      const cancel = el('button', 'button quiet', '取消放置'); cancel.type = 'button'; cancel.dataset.workbenchAction = 'cancel-placement'; instruction.append(cancel); canvas.append(instruction);
    }
    if (positioned.length || validBounds) {
      const viewport = el('div', 'workbench-coordinate-viewport');
      viewport.dataset.projectId = this.app.projectId || '';
      viewport.tabIndex = 0;
      viewport.setAttribute('role', 'region');
      viewport.setAttribute('aria-label', '场景编排，可横向滚动查看完整边界');
      viewport.append(canvas);
      root.append(viewport, el('p', 'workbench-coordinate-scroll-hint', '窄屏可左右滚动查看完整场景；标记位置按公开坐标显示。'));
      if (previousScroll?.projectId === viewport.dataset.projectId && previousScroll.sceneId === canvas.dataset.sceneId) viewport.scrollLeft = previousScroll.left;
    } else root.append(canvas);
    this.renderLocalLayoutTools(root, sceneId);
    this.renderLegacyExamples(root, sceneId);
    this.renderDraftInstanceControls(root, sceneId);
    if (sceneObjects.some(item => !Array.isArray(this.metadata(item).position))) {
      const unpositioned = sceneObjects.filter(item => !Array.isArray(this.metadata(item).position));
      const list = el('div', 'workbench-unpositioned'); list.append(el('b', '', `位置未提供 · ${unpositioned.length}`));
      for (const item of unpositioned) { const button = el('button', 'text-link'); button.type = 'button'; button.dataset.objectId = item.id; button.textContent = item.name || item.label || '未命名对象'; button.title = `对象 ID：${item.id}`; list.append(button); }
      root.append(list);
    }
    if (role === 'transition' || role === 'entry') this.renderTransitionSummary(root, target);
    const maps = this.workbenchResults();
    const relatedResult = maps.find(item => item.objectId === target.id);
    if (relatedResult) root.append(el('p', 'workbench-result-hint', `最近处理结果：${this.workflowLabel(relatedResult.workflowStatus)} · ${relatedResult.itemId || '未提供条目 ID'}`));
  }

  renderMinimalTemplateMarkers(canvas, scene, width, height, validBounds) {
    const note = el('p', 'workbench-template-note', validBounds
      ? '最小结构模板意图 · 本地位置示意，尚未创建 Godot 节点或获得 Agent 确认。点击标记后在此场景意见中说明位置。'
      : '最小结构模板意图 · 世界边界未提供，画布位置按比例示意；尚未创建 Godot 节点或获得 Agent 确认。点击标记后在此场景意见中说明位置。');
    canvas.append(note);
    const floorHeight = validBounds ? Math.min(80, height * 0.12) : null;
    const floor = el('button', 'workbench-template-marker workbench-template-floor', '地板意图');
    floor.type = 'button'; floor.dataset.workbenchAction = 'select-template-scene'; floor.dataset.sceneId = scene.id;
    floor.setAttribute('aria-label', '模板地板意图；选择此草稿场景并在场景意见中说明位置');
    floor.style.left = '0'; floor.style.width = '100%';
    floor.style.height = validBounds ? `${floorHeight / height * 100}%` : '11%';
    floor.style.bottom = '0';
    const spawn = el('button', 'workbench-template-marker workbench-template-spawn', '玩家入口意图');
    spawn.type = 'button'; spawn.dataset.workbenchAction = 'select-template-scene'; spawn.dataset.sceneId = scene.id;
    spawn.setAttribute('aria-label', '模板玩家入口意图；选择此草稿场景并在场景意见中说明位置');
    const x = validBounds ? Math.min(220, width * 0.15) : null;
    const spawnWidth = validBounds ? Math.min(80, width * 0.1) : null;
    const spawnHeight = validBounds ? Math.min(105, height * 0.2) : null;
    spawn.style.left = validBounds ? `${x / width * 100}%` : '14%';
    spawn.style.width = validBounds ? `${spawnWidth / width * 100}%` : '6%';
    spawn.style.height = validBounds ? `${spawnHeight / height * 100}%` : '15%';
    spawn.style.bottom = validBounds ? `${floorHeight / height * 100}%` : '11%';
    spawn.style.setProperty('--anchor-x', '-50%');
    spawn.style.setProperty('--anchor-y', '0%');
    canvas.append(floor, spawn);
  }

  renderLocalLayoutTools(root, sceneId) {
    const candidates = this.objects().filter(object => this.role(object) === 'instance' && this.metadata(object).sceneId === sceneId && Array.isArray(this.metadata(object).position));
    if (!sceneId || !candidates.length) return;
    const section = el('section', 'workbench-layout-tools');
    section.append(el('h4', '', '手动网格对齐预览 · 本地算法示意'));
    section.append(el('p', 'muted', '仅处理你勾选的实例；不会移动未声明为 free / nudge 的对象，也不会调用或模拟 Agent。应用只会加入待申报移动提案。'));
    const selected = new Set(this.layoutSelectionByScene.get(sceneId) || []);
    for (const object of candidates) {
      const meta = this.metadata(object), lock = this.effectiveLock(object), movable = ['free', 'nudge'].includes(lock);
      const label = el('label', 'workbench-layout-target');
      const checkbox = el('input'); checkbox.type = 'checkbox'; checkbox.checked = selected.has(object.id); checkbox.disabled = !movable;
      checkbox.dataset.objectId = object.id;
      checkbox.addEventListener('change', () => {
        const next = new Set(this.layoutSelectionByScene.get(sceneId) || []);
        if (checkbox.checked) next.add(object.id); else next.delete(object.id);
        this.layoutSelectionByScene.set(sceneId, [...next]);
      });
      label.append(checkbox, el('span', '', `${object.name || object.id} · ${this.displayValue(this.proposedPosition(object) || meta.position)} · ${this.lockLabel(lock)}${movable ? '' : ' · 只读'}`));
      section.append(label);
    }
    const controls = el('div', 'workbench-layout-actions');
    const stepLabel = el('label', '', '网格间距');
    const stepInput = el('input'); stepInput.type = 'number'; stepInput.name = 'gridStep'; stepInput.min = '1'; stepInput.step = 'any'; stepInput.value = String(this.localLayoutProposal?.sceneId === sceneId ? this.localLayoutProposal.gridStep : 80);
    stepLabel.append(stepInput, el('small', 'muted', '场景单位'));
    const previewButton = el('button', 'button secondary', this.localLayoutProposal?.sceneId === sceneId ? '重新生成预览' : '预览所选实例');
    previewButton.type = 'button'; previewButton.dataset.workbenchAction = 'preview-layout-proposal'; previewButton.dataset.sceneId = sceneId;
    controls.append(stepLabel, previewButton); section.append(controls);
    const proposal = this.localLayoutProposal?.sceneId === sceneId ? this.localLayoutProposal : null;
    if (proposal) {
      const stale = proposal.baseSignature !== this.localLayoutSourceSignature();
      section.append(el('p', stale ? 'workbench-layout-stale' : 'workbench-layout-status', stale ? '此预览已过期：草稿或发布版本已变化，应用时会拒绝。' : `本地示意 · ${proposal.changes.length} 项可用移动${proposal.skipped ? ` · ${proposal.skipped} 项锁定、越界或无需调整` : ''}`));
      const list = el('ul', 'workbench-layout-diff');
      for (const change of proposal.changes) list.append(el('li', '', `${this.object(change.objectId)?.name || change.objectId}：${this.displayValue(change.before)} → ${this.displayValue(change.requested)} · ${this.lockLabel(change.lock)}`));
      section.append(list);
      const actions = el('div', 'workbench-layout-actions');
      const cancel = el('button', 'button quiet', '取消预览'); cancel.type = 'button'; cancel.dataset.workbenchAction = 'cancel-layout-proposal';
      const apply = el('button', 'button primary', '应用到本地草稿'); apply.type = 'button'; apply.dataset.workbenchAction = 'apply-layout-proposal';
      actions.append(cancel, apply); section.append(actions);
      section.append(el('p', 'muted', '应用后，所有移动会作为一组成组可撤销的待申报提案；不会写入源码。'));
    }
    root.append(section);
  }

  explicitDecoration(object) {
    return this.role(object) === 'instance' && this.metadata(object).decoration === true;
  }

  decorationCandidates(sceneId) {
    if (!sceneId || !this.sceneBounds(sceneId)) return [];
    return this.objects().filter(object => {
      const meta = this.metadata(object), lock = this.effectiveLock(object);
      const position = this.proposedPosition(object) || meta.position;
      return this.explicitDecoration(object) && meta.sceneId === sceneId && ['free', 'nudge'].includes(lock)
        && Array.isArray(position) && !this.positionIssue(sceneId, meta, position);
    });
  }

  renderLegacyExamples(root, sceneId) {
    const section = el('section', 'workbench-legacy-examples');
    section.append(el('h4', '', '可用操作示例 · 仅生成可审阅的本地草稿'));

    const decoration = el('article', 'workbench-legacy-example');
    decoration.append(el('b', '', '整理装饰布局'));
    decoration.append(el('p', 'muted', '只对当前场景中明确映射为装饰、位置有效且锁定为 free / nudge 的实例做局部 X 网格对齐。对齐不测试或保证通路。'));
    const decorationButton = el('button', 'button secondary', '预览装饰对齐');
    decorationButton.type = 'button'; decorationButton.dataset.workbenchAction = 'preview-decor-example'; decorationButton.dataset.sceneId = sceneId || '';
    decoration.append(decorationButton);
    const decorationStatus = this.decorationExampleStatus || (this.decorationCandidates(sceneId).length
      ? `当前场景有 ${this.decorationCandidates(sceneId).length} 个合格的显式装饰映射。`
      : '当前场景没有带有效位置和可移动锁定状态的显式装饰映射；此示例无法应用。');
    decoration.append(el('p', 'workbench-example-status', decorationStatus));
    const decorationProposal = this.localDecorationProposal;
    if (decorationProposal) this.renderDecorationExampleProposal(decoration, decorationProposal);
    if (this.decorationCandidates(sceneId).length || decorationProposal) section.append(decoration);

    const timing = el('article', 'workbench-legacy-example');
    timing.append(el('b', '', '缩短骰子事件预警'));
    const timingDetails = el('details', 'muted'); timingDetails.append(el('summary', '', '查看示例来源与范围'));
    timingDetails.append(el('p', '', '历史示例名称是“缩短剑击前摇”。当前项目没有映射剑击前摇；若骰子事件预警时长字段可编辑，预览只会调整该字段，不会模拟攻击动画。'));
    timing.append(timingDetails);
    const timingButton = el('button', 'button secondary', '预览时长调整');
    timingButton.type = 'button'; timingButton.dataset.workbenchAction = 'preview-timing-example';
    timing.append(timingButton);
    const timingData = this.timingExampleData();
    let timingStatus = this.timingExampleStatus;
    if (!timingStatus) {
      if (!timingData) timingStatus = '当前快照没有可编辑的 dice-burst.warning-duration 数值 capability；此示例无法应用。';
      else if (this.app.selectedObjectId !== timingData.object.id) timingStatus = '选择 dice-burst 后才能预览实际的骰子事件落点预警时长。';
      else timingStatus = `当前可审阅目标：${timingData.object.name || timingData.object.id} · ${timingData.capability.label || timingData.field.label || timingData.fieldId}。`;
    }
    timing.append(el('p', 'workbench-example-status', timingStatus));
    if (this.localTimingProposal) this.renderTimingExampleProposal(timing, this.localTimingProposal);
    if (timingData || this.localTimingProposal) section.append(timing);
    if (section.querySelector('article')) root.append(section);
  }

  renderDecorationExampleProposal(root, proposal) {
    const stale = proposal.baseSignature !== this.decorationExampleSignature();
    root.append(el('p', stale ? 'workbench-example-stale' : 'workbench-example-status', stale
      ? '此装饰预览已过期；草稿或发布版本发生变化，应用时会拒绝。'
      : `本地示意 · ${proposal.changes.length} 个装饰位置变化${proposal.skipped ? ` · ${proposal.skipped} 个无变化或越界目标已跳过` : ''}。不包含通路验证。`));
    const list = el('ul', 'workbench-layout-diff');
    for (const change of proposal.changes) list.append(el('li', '', `${this.object(change.objectId)?.name || change.objectId}：${this.displayValue(change.before)} → ${this.displayValue(change.requested)} · X 坐标`));
    root.append(list);
    const actions = el('div', 'workbench-layout-actions');
    const cancel = el('button', 'button quiet', '取消预览'); cancel.type = 'button'; cancel.dataset.workbenchAction = 'cancel-decor-example';
    const apply = el('button', 'button primary', '应用到本地草稿'); apply.type = 'button'; apply.dataset.workbenchAction = 'apply-decor-example'; apply.disabled = stale;
    actions.append(cancel, apply); root.append(actions);
  }

  previewDecorationExample(sceneId) {
    const candidates = this.decorationCandidates(sceneId);
    if (!candidates.length) {
      this.localDecorationProposal = null;
      this.decorationExampleStatus = '当前场景没有带有效位置和可移动锁定状态的显式装饰映射；此示例无法应用。';
      this.render();
      return false;
    }
    const bounds = this.sceneBounds(sceneId);
    const changes = []; let skipped = 0;
    for (const object of candidates) {
      const meta = this.metadata(object), lock = this.effectiveLock(object);
      const before = (this.proposedPosition(object) || meta.position).map(Number);
      let requestedX = Math.round(before[0] / 80) * 80;
      if (requestedX === before[0]) requestedX += before[0] > Number(bounds[0]) / 2 ? -32 : 32;
      if (lock === 'nudge') {
        const amount = Number(meta.nudgeStep) > 0 ? Number(meta.nudgeStep) : 1;
        requestedX = before[0] + Math.sign(requestedX - before[0]) * Math.min(Math.abs(requestedX - before[0]), amount);
      }
      const requested = [Number(this.formatNumber(requestedX)), before[1]];
      if (JSON.stringify(requested) === JSON.stringify(before) || this.positionIssue(sceneId, meta, requested)) { skipped += 1; continue; }
      changes.push({ objectId: object.id, sceneId, before, requested, lock });
    }
    if (!changes.length) {
      this.localDecorationProposal = null;
      this.decorationExampleStatus = `没有可应用的位置变化${skipped ? `；${skipped} 个显式装饰已跳过` : ''}。`;
      this.render(); return false;
    }
    this.localDecorationProposal = { sceneId, changes, skipped, baseSignature: this.decorationExampleSignature(sceneId) };
    this.decorationExampleStatus = '预览只对齐显式映射装饰的 X 坐标；没有进行寻路、碰撞或通路检查。';
    this.render(); return true;
  }

  applyDecorationExample() {
    const proposal = this.localDecorationProposal;
    if (!proposal) return false;
    if (proposal.baseSignature !== this.decorationExampleSignature()) {
      this.decorationExampleStatus = '此装饰预览已过期；请重新生成。';
      this.app.notify?.('此装饰示例预览已过期；发布版本或草稿发生变化，请重新生成。');
      this.render(); return false;
    }
    const operations = [];
    for (const change of proposal.changes) {
      const object = this.objects().find(item => item.id === change.objectId), meta = this.metadata(object);
      const current = this.proposedPosition(object) || meta.position;
      const lock = object ? this.effectiveLock(object) : null;
      if (!object || !this.explicitDecoration(object) || meta.sceneId !== change.sceneId || lock !== change.lock
        || !['free', 'nudge'].includes(lock) || JSON.stringify(current?.map(Number)) !== JSON.stringify(change.before)
        || this.positionIssue(change.sceneId, meta, change.requested)) {
        this.app.notify?.('装饰对象、位置或编辑约束已变化；整批拒绝，请重新预览。');
        return false;
      }
      const existing = this.app.structuralProposals.find(item => item.kind === 'move' && item.objectId === object.id);
      operations.push({
        operationId: existing?.operationId || existing?.proposalId || this.app.newFeedbackId?.() || `decor-${Date.now()}-${operations.length}`,
        kind: 'move', objectId: object.id, before: existing?.before || meta.position,
        requested: change.requested, scope: meta.scope || '当前实例', lock,
        createdAt: existing?.createdAt || new Date().toISOString(),
      });
    }
    this.pushHistory();
    const changedIds = new Set(operations.map(item => item.objectId));
    this.app.structuralProposals = [...this.app.structuralProposals.filter(item => !(item.kind === 'move' && changedIds.has(item.objectId))), ...operations];
    this.localDecorationProposal = null;
    this.decorationExampleStatus = `已将 ${operations.length} 个显式装饰移动提案加入本地草稿；没有验证通路。`;
    this.app.queueDraftSave?.(); this.pushHistory(); this.render();
    this.app.notify?.(`已将 ${operations.length} 个显式装饰移动提案加入本地草稿；可以一次撤销。`);
    return true;
  }

  decorationExampleSignature(sceneId = this.sceneCanvasSelection || this.activeSceneId) {
    return JSON.stringify({ source: this.localLayoutSourceSignature(), sceneId: sceneId || null });
  }

  timingExampleData() {
    const object = this.objects().find(item => item.id === 'dice-burst');
    if (!object || typeof this.app.allCapabilities !== 'function' || typeof this.app.splitCapability !== 'function'
      || typeof this.app.capabilityEditable !== 'function' || typeof this.app.capabilityValue !== 'function') return null;
    const capability = this.app.allCapabilities().find(item => {
      const parts = this.app.splitCapability(item);
      return parts.objectId === 'dice-burst' && parts.fieldId === 'warning-duration';
    });
    const field = object.fields?.find(item => item.id === 'warning-duration')
      || (this.app.snapshot?.document?.objects || this.app.snapshot?.objectDocument?.objects || []).find(item => item.id === object.id)?.fields?.find(item => item.id === 'warning-duration');
    const type = capability?.type || field?.type;
    if (!capability || !this.app.capabilityEditable(capability, object) || !['number', 'integer', 'scalar'].includes(type)) return null;
    return { object, capability, field: field || {}, fieldId: 'warning-duration', id: 'dice-burst.warning-duration' };
  }

  timingExampleBounds(data) {
    const numberOrNull = value => {
      if (value == null || value === '') return null;
      const number = Number(value);
      return Number.isFinite(number) ? number : null;
    };
    const type = data.capability.type || data.field.type || 'scalar';
    const integer = type === 'integer' || data.capability.integer === true || data.field.integer === true;
    const declaredMin = numberOrNull(data.capability.min ?? data.field.min);
    const min = Math.max(0.02, declaredMin ?? 0.02);
    const max = numberOrNull(data.capability.max ?? data.field.max);
    const declaredStep = numberOrNull(data.capability.step ?? data.field.step);
    const step = integer ? 1 : declaredStep > 0 ? declaredStep : 0.02;
    const stepBase = integer ? Math.ceil(declaredMin ?? 0) : declaredMin ?? 0;
    return { integer, min, max, step, stepBase };
  }

  shortenedTimingValue(data, before) {
    const { integer, min, max, step, stepBase } = this.timingExampleBounds(data);
    if (before < min || (max != null && before > max) || (integer && !Number.isInteger(before))) return null;
    const stepsBelow = Math.ceil((before - stepBase) / step - 1e-10) - 1;
    const requested = Number((stepBase + stepsBelow * step).toFixed(10));
    if (!Number.isFinite(requested) || requested < min || (max != null && requested > max) || requested >= before) return null;
    return requested;
  }

  timingExampleCurrentValue(data) {
    const draft = this.app.fieldDraftValues || {};
    const value = Object.hasOwn(draft, data.id) ? draft[data.id] : this.app.capabilityValue(data.capability, data.object);
    if (value == null || value === '' || typeof value === 'boolean') return null;
    const number = Number(value);
    return Number.isFinite(number) ? number : null;
  }

  timingExampleSignature() {
    const data = this.timingExampleData();
    return JSON.stringify({
      source: this.localLayoutSourceSignature(), selectedObjectId: this.app.selectedObjectId || null,
      capability: data ? {
        editable: this.app.capabilityEditable(data.capability, data.object),
        editableFlag: data.capability.editable === true, supported: data.capability.supported === true,
        enabled: data.capability.enabled === true, type: data.capability.type || data.field.type,
        currentValue: data.capability.currentValue ?? data.capability.value ?? null,
        min: data.capability.min ?? data.field.min ?? null, max: data.capability.max ?? data.field.max ?? null,
        step: data.capability.step ?? data.field.step ?? null,
      } : null,
    });
  }

  renderTimingExampleProposal(root, proposal) {
    const stale = proposal.baseSignature !== this.timingExampleSignature();
    root.append(el('p', stale ? 'workbench-example-stale' : 'workbench-example-status', stale
      ? '此时长预览已过期；字段值、能力或草稿已变化，应用时会拒绝。'
      : '只修改骰子事件落点预警时长；这不是剑击前摇，也不模拟攻击动画。'));
    const list = el('ul', 'workbench-layout-diff');
    list.append(el('li', '', `${proposal.objectName} · ${proposal.objectId}.${proposal.fieldId}：${this.displayValue(proposal.before)} → ${this.displayValue(proposal.requested)} 秒`));
    root.append(list);
    const actions = el('div', 'workbench-layout-actions');
    const cancel = el('button', 'button quiet', '取消预览'); cancel.type = 'button'; cancel.dataset.workbenchAction = 'cancel-timing-example';
    const apply = el('button', 'button primary', '应用到本地草稿'); apply.type = 'button'; apply.dataset.workbenchAction = 'apply-timing-example'; apply.disabled = stale;
    actions.append(cancel, apply); root.append(actions);
  }

  previewTimingExample() {
    this.app.captureVisibleFields?.();
    const data = this.timingExampleData();
    if (!data) {
      this.localTimingProposal = null;
      this.timingExampleStatus = '当前快照没有可编辑的 dice-burst.warning-duration 数值 capability；此示例无法应用。';
      this.render(); return false;
    }
    if (this.app.selectedObjectId !== data.object.id) {
      this.localTimingProposal = null;
      this.timingExampleStatus = '请先选择 dice-burst，才能预览实际的骰子事件落点预警时长。';
      this.render(); return false;
    }
    const before = this.timingExampleCurrentValue(data);
    if (before == null || before <= 0) {
      this.localTimingProposal = null;
      this.timingExampleStatus = '当前落点预警时长不是可缩短的有效正数值。';
      this.render(); return false;
    }
    const bounds = this.timingExampleBounds(data);
    if (before < bounds.min || (bounds.max != null && before > bounds.max) || (bounds.integer && !Number.isInteger(before))) {
      this.localTimingProposal = null;
      this.timingExampleStatus = '当前落点预警时长不符合 capability 声明的数值范围或整数类型。';
      this.render(); return false;
    }
    const requested = this.shortenedTimingValue(data, before);
    if (requested == null) {
      this.localTimingProposal = null;
      this.timingExampleStatus = '当前落点预警时长已达到 capability 声明的下限或没有更低的合法步进值。';
      this.render(); return false;
    }
    this.localTimingProposal = {
      objectId: data.object.id, objectName: data.object.name || data.object.id, fieldId: data.fieldId,
      before, requested, baseSignature: this.timingExampleSignature(),
    };
    this.timingExampleStatus = '已生成本地字段差异；实际目标为骰子事件预警时长。';
    this.render(); return true;
  }

  applyTimingExample() {
    const proposal = this.localTimingProposal;
    if (!proposal) return false;
    this.app.captureVisibleFields?.();
    const data = this.timingExampleData();
    const current = data && this.timingExampleCurrentValue(data);
    if (!data || this.app.selectedObjectId !== proposal.objectId || proposal.baseSignature !== this.timingExampleSignature()
      || current == null || current !== proposal.before || proposal.requested >= current) {
      this.timingExampleStatus = '此时长预览已过期或 capability 已不可编辑；请重新预览。';
      this.app.notify?.('此时长示例预览已过期或目标字段不可编辑，请重新生成。');
      this.render(); return false;
    }
    const previous = this.app.fieldDraftValues || {};
    this.pushHistory();
    this.app.fieldDraftValues = { ...previous, [data.id]: proposal.requested };
    this.app.dirtyFields?.add(data.id);
    this.localTimingProposal = null;
    this.timingExampleStatus = `已将 ${data.object.name || data.object.id} · ${data.fieldId} = ${proposal.requested} 秒写入本地字段草稿。`;
    this.app.renderDynamicFields?.(this.objects(), this.app.capabilities);
    this.app.renderObjectDetail?.();
    this.app.queueDraftSave?.(); this.pushHistory(); this.render(); this.refreshReport(false);
    this.app.notify?.('已将骰子事件落点预警时长加入本地字段草稿；可以一次撤销。');
    return true;
  }

  localLayoutSourceSignature() {
    const snapshot = this.app.snapshot || {};
    return JSON.stringify({
      projectId: this.app.projectId || null,
      publicationRevision: snapshot.publicationRevision ?? null,
      sourceCommit: snapshot.sourceCommit || snapshot.baseCommit || null,
      draft: this.signature(this.historyState()),
    });
  }

  previewLocalLayoutProposal(sceneId, gridStep) {
    const selected = new Set(this.layoutSelectionByScene.get(sceneId) || []);
    if (!selected.size) return this.app.notify?.('请先明确勾选要预览的可移动实例。');
    if (!Number.isFinite(gridStep) || gridStep <= 0) return this.app.notify?.('网格间距必须是有效的正数。');
    const changes = []; let skipped = 0;
    for (const object of this.objects().filter(item => selected.has(item.id))) {
      const meta = this.metadata(object);
      const lock = this.effectiveLock(object);
      if (this.role(object) !== 'instance' || meta.sceneId !== sceneId || !['free', 'nudge'].includes(lock) || !Array.isArray(meta.position)) { skipped += 1; continue; }
      const before = (this.proposedPosition(object) || meta.position).map(Number);
      const snap = value => Math.round(value / gridStep) * gridStep;
      let requested = [snap(before[0]), snap(before[1])];
      if (lock === 'nudge') {
        const amount = Number(meta.nudgeStep) > 0 ? Number(meta.nudgeStep) : 1;
        requested = before.map((value, index) => value + Math.sign(requested[index] - value) * Math.min(Math.abs(requested[index] - value), amount));
      }
      if (JSON.stringify(requested) === JSON.stringify(before)) { skipped += 1; continue; }
      const issue = this.positionIssue(sceneId, meta, requested);
      if (issue) { skipped += 1; continue; }
      changes.push({ objectId: object.id, before, requested, lock, sceneId });
    }
    if (!changes.length) { this.localLayoutProposal = null; this.render(); return this.app.notify?.(`所选实例没有可应用的网格对齐变化${skipped ? `；${skipped} 项跳过` : ''}。`); }
    this.localLayoutProposal = { sceneId, gridStep, changes, skipped, baseSignature: this.localLayoutSourceSignature() };
    this.render();
    return true;
  }

  applyLocalLayoutProposal() {
    const proposal = this.localLayoutProposal;
    if (!proposal) return false;
    if (proposal.baseSignature !== this.localLayoutSourceSignature()) {
      this.app.notify?.('此本地预览已过期；发布版本或草稿发生变化，请重新生成。');
      this.render(); return false;
    }
    const operations = [];
    for (const change of proposal.changes) {
      const object = this.objects().find(item => item.id === change.objectId), meta = this.metadata(object);
      const lock = this.effectiveLock(object);
      if (!object || this.role(object) !== 'instance' || meta.sceneId !== change.sceneId || lock !== change.lock || !['free', 'nudge'].includes(lock) || this.positionIssue(change.sceneId, meta, change.requested)) {
        this.app.notify?.('此批次中有实例、锁定状态或坐标边界已变化；整批拒绝，请重新预览。');
        return false;
      }
      const existing = this.app.structuralProposals.find(item => item.kind === 'move' && item.objectId === object.id);
      operations.push({
        operationId: existing?.operationId || existing?.proposalId || this.app.newFeedbackId?.() || `layout-${Date.now()}-${operations.length}`,
        kind: 'move', objectId: object.id, before: existing?.before || meta.position,
        requested: change.requested, scope: meta.scope || '当前实例', lock,
        createdAt: existing?.createdAt || new Date().toISOString(),
      });
    }
    this.pushHistory();
    const changedIds = new Set(operations.map(item => item.objectId));
    this.app.structuralProposals = [...this.app.structuralProposals.filter(item => !(item.kind === 'move' && changedIds.has(item.objectId))), ...operations];
    this.localLayoutProposal = null;
    this.app.queueDraftSave?.(); this.pushHistory(); this.render();
    this.app.notify?.(`已将 ${operations.length} 项移动提案加入本地草稿；可以一次撤销。`);
    return true;
  }

  renderDraftInstanceControls(root, sceneId) {
    const proposals = this.app.structuralProposals.filter(item => item.kind === 'new-instance' && item.sceneId === sceneId && Array.isArray(item.requestedPosition));
    if (!proposals.length) return;
    const section = el('section', 'workbench-draft-instance-controls');
    section.append(el('h4', '', '本地新增实例 · 坐标与移除'), el('p', 'muted', '这些对象仍是草稿提案；坐标以所选场景的公开世界边界校验。'));
    for (const proposal of proposals) {
      const lock = ['fixed', 'nudge', 'free'].includes(proposal.lock) ? proposal.lock : 'free';
      const row = el('div', 'workbench-draft-instance-row');
      row.append(el('b', '', `${proposal.name || '新实例'} · ${this.object(proposal.definitionId)?.name || proposal.definitionId} · ${this.lockLabel(lock)}`));
      const x = el('input'); x.type = 'number'; x.step = 'any'; x.value = String(proposal.requestedPosition[0]); x.setAttribute('aria-label', `${proposal.name || '新实例'} X 坐标`);
      const y = el('input'); y.type = 'number'; y.step = 'any'; y.value = String(proposal.requestedPosition[1]); y.setAttribute('aria-label', `${proposal.name || '新实例'} Y 坐标`);
      if (lock === 'fixed') { x.disabled = true; y.disabled = true; }
      const save = el('button', 'button secondary', '更新坐标'); save.type = 'button'; save.disabled = lock === 'fixed'; save.addEventListener('click', () => this.setDraftInstancePosition(proposal.operationId || proposal.proposalId, [Number(x.value), Number(y.value)]));
      const lockControl = el('div', 'workbench-draft-lock-control');
      const lockLabel = el('label', '', '此新实例的编辑约束');
      const lockSelect = el('select'); lockSelect.name = 'draftLock';
      lockSelect.append(new Option('自由', 'free'), new Option('可微调', 'nudge'), new Option('固定', 'fixed')); lockSelect.value = lock;
      lockLabel.append(lockSelect);
      const setLock = el('button', 'button quiet', '更新约束'); setLock.type = 'button'; setLock.dataset.workbenchAction = 'set-draft-instance-lock'; setLock.dataset.operationId = proposal.operationId || proposal.proposalId;
      lockControl.append(lockLabel, setLock); row.append(lockControl);
      if (lock === 'nudge') {
        const controls = el('div', 'workbench-nudge');
        const step = Number(proposal.nudgeStep) > 0 ? Number(proposal.nudgeStep) : Number(this.metadata(this.object(proposal.definitionId)).nudgeStep) > 0 ? Number(this.metadata(this.object(proposal.definitionId)).nudgeStep) : 1;
        for (const [title, dx, dy] of [['↑', 0, -step], ['←', -step, 0], ['→', step, 0], ['↓', 0, step]]) {
          const button = el('button', 'button quiet', title); button.type = 'button'; button.dataset.workbenchAction = 'nudge'; button.dataset.objectId = this.draftTargetId(proposal); button.dataset.dx = String(dx); button.dataset.dy = String(dy); button.setAttribute('aria-label', `微调${proposal.name || '新实例'}位置 ${title}`); controls.append(button);
        }
        row.append(controls);
      }
      const remove = el('button', 'button quiet', '删除草稿实例'); remove.type = 'button'; remove.setAttribute('aria-label', `删除草稿实例 ${proposal.name || proposal.operationId}`); remove.addEventListener('click', () => this.deleteDraftInstance(proposal.operationId || proposal.proposalId));
      row.append(el('label', '', 'X'), x, el('label', '', 'Y'), y, save, remove); section.append(row);
    }
    root.append(section);
  }

  renderProjectOverview(root) {
    root.append(el('div', 'workbench-canvas-heading', '项目总览'));
    const scenes = this.scenes();
    const sceneList = el('div', 'semantic-scene-grid');
    if (scenes.length) {
      for (const scene of scenes) {
        const card = el('article', 'semantic-scene-card');
        card.append(el('b', '', scene.name || scene.id), el('small', '', `ID ${scene.id}`));
        const members = this.objects().filter(object => this.metadata(object).sceneId === scene.id);
        card.append(el('p', 'muted', `${members.length} 个对象明确关联到此场景`));
        if (scene.inferredFromInstances) card.append(el('small', 'muted', '名称来自实例元数据，场景本体尚未映射'));
        sceneList.append(card);
      }
    } else sceneList.append(el('p', 'muted', '公开快照未提供场景、入口或有向连接数据。'));
    root.append(sceneList);
    const connections = this.objects().filter(object => this.role(object) === 'transition');
    root.append(el('h4', '', '有向过渡'));
    if (!connections.length) root.append(el('p', 'muted', '当前对象映射没有 transition 角色；不生成虚构连接。'));
    else for (const transition of connections) this.renderTransitionSummary(root, transition);
    const summary = el('p', 'workbench-semantic-note', '没有场景对象时，场景卡片只来自快照明确列出的场景或实例的 sceneId。'); root.append(summary);
  }

  renderCanvasToken(canvas, object, planeWidth, planeHeight) {
    const meta = this.metadata(object), position = this.proposedPosition(object) || meta.position;
    if (!(planeWidth > 0 && planeHeight > 0)) return;
    if (!Array.isArray(position)) return;
    const anchor = Array.isArray(meta.anchor) ? meta.anchor : [0, 0];
    const size = Array.isArray(meta.size) ? meta.size : null;
    const isDraft = this.isDraftTarget(object.id);
    const button = el('button', `workbench-object-token role-${this.role(object)}${isDraft ? ' is-draft' : ''}${object.id === this.app.selectedObjectId ? ' selected' : ''}`);
    button.type = 'button'; button.dataset.objectId = object.id;
    if (isDraft) button.dataset.operationId = object.operationId || '';
    button.style.left = `${Math.max(0, Math.min(100, Number(position[0]) / planeWidth * 100))}%`;
    button.style.top = `${Math.max(0, Math.min(100, Number(position[1]) / planeHeight * 100))}%`;
    button.style.setProperty('--anchor-x', String(Number(anchor[0]) * 100));
    button.style.setProperty('--anchor-y', String(Number(anchor[1]) * 100));
    if (size && Number(size[0]) > 0 && Number(size[1]) > 0) {
      button.style.width = `${Number(size[0]) / planeWidth * 100}%`;
      button.style.height = `${Number(size[1]) / planeHeight * 100}%`;
    }
    const lock = this.effectiveLock(object) || 'unmapped';
    button.dataset.lock = lock;
    button.append(el('b', '', object.name || object.id), el('small', '', `${isDraft ? '草稿实例' : this.roleLabel(object)} · ${this.displayValue(position)}`));
    if (lock === 'free') { button.draggable = false; button.setAttribute('aria-label', `${object.name || object.id}，可拖动调整提案位置 ${this.displayValue(position)}`); }
    else if (lock === 'nudge') button.setAttribute('aria-label', `${object.name || object.id}，可微调，位置 ${this.displayValue(position)}`);
    else button.setAttribute('aria-label', `${object.name || object.id}，位置固定或未声明锁定状态 ${this.displayValue(position)}`);
    if (isDraft) button.setAttribute('aria-label', `${object.name || object.id}，草稿实例，${lock === 'free' ? '可拖动' : lock === 'nudge' ? '可微调' : '固定'}，位置 ${this.displayValue(position)}`);
    canvas.append(button);
    const operation = this.app.structuralProposals.find(item => item.kind === 'move' && item.objectId === object.id);
    const positionBinding = this.geometryBinding(object, 'position');
    const fieldMoved = positionBinding && Object.hasOwn(this.app.fieldDraftValues || {}, `${positionBinding.object.id}.${positionBinding.fieldId}`);
    if (operation || fieldMoved) {
      const mark = el('span', 'workbench-proposed-mark', '待申报位置');
      mark.style.left = `clamp(4px, ${button.style.left}, calc(100% - 7rem))`;
      mark.style.top = `clamp(4px, ${button.style.top}, calc(100% - 1.8rem))`;
      canvas.append(mark);
    }
    const localChange = this.localLayoutProposal?.changes.find(item => item.objectId === object.id);
    if (localChange) {
      const marker = el('div', 'workbench-local-layout-marker', '本地示意');
      marker.setAttribute('aria-hidden', 'true');
      marker.style.left = `${Number(localChange.requested[0]) / planeWidth * 100}%`;
      marker.style.top = `${Number(localChange.requested[1]) / planeHeight * 100}%`;
      marker.style.setProperty('--anchor-x', String(Number(anchor[0]) * 100));
      marker.style.setProperty('--anchor-y', String(Number(anchor[1]) * 100));
      if (size && Number(size[0]) > 0 && Number(size[1]) > 0) {
        marker.style.width = `${Number(size[0]) / planeWidth * 100}%`;
        marker.style.height = `${Number(size[1]) / planeHeight * 100}%`;
      }
      canvas.append(marker);
    }
  }

  renderFacet(root, object, facetName) {
    const metadata = this.metadata(object), facets = metadata.facets || {};
    const facet = facets[facetName];
    root.append(el('div', 'workbench-canvas-heading', `${facetName === 'narrative' ? 'Narrative · 叙事' : 'Art · 表现'} · ${object ? (object.name || object.id) : '当前项目'}`));
    if (!object) { root.append(el('p', 'workbench-missing-source', '项目级此观察面没有源数据。你仍可在右侧对项目提出意见。')); return; }
    if (facet == null || facet === '') {
      root.append(el('div', 'workbench-missing-source', `${facetName === 'narrative' ? '未提供叙事信息' : '未提供表现信息'}。可以直接在右侧提出修改期望；当前视图不会补造内容。`));
      return;
    }
    const display = typeof facet === 'string' ? facet : facet.summary || facet.description || facet.text || JSON.stringify(facet, null, 2);
    const panel = el('article', 'workbench-facet-card');
    if (facet.title || facet.name) panel.append(el('h4', '', facet.title || facet.name));
    panel.append(el(typeof facet === 'string' ? 'p' : 'pre', 'workbench-facet-copy', display));
    const provenance = metadata.provenance || facet.provenance;
    if (provenance) panel.append(el('p', 'muted', `来源类型：${PROVENANCE_LABELS[provenance.kind] || provenance.kind || '未声明'}`));
    root.append(panel);
  }

  renderTransitionSummary(root, object) {
    const meta = this.metadata(object);
    const rels = this.relations(object).filter(item => /transition|target|exit|entry|destination/i.test(item.type || ''));
    const section = el('article', 'workbench-transition-card');
    section.append(el('b', '', `有向连接 · ${object.name || object.id}`));
    const target = rels.map(item => item.targetId || item.target).filter(Boolean).join('、') || meta.destinationSceneId || meta.targetSceneId;
    section.append(el('p', '', `方向：${this.sceneName(meta.sceneId || this.activeSceneId || '来源场景未提供')} → ${target ? this.sceneName(target) : '目标场景 / 入口未映射'}`));
    const state = this.transitionMetadataValues(meta);
    section.append(el('p', 'muted', `通行条件：${this.displayValue(state.condition)} · 当前模式：${this.transitionStateLabel(state)}`));
    section.append(el('p', 'muted', `表现类型：${this.displayValue(meta.preview?.type)} · 来源：${this.provenanceLabel(meta)}`));
    const button = el('button', 'button secondary', '提出过渡修改'); button.type = 'button'; button.dataset.workbenchAction = 'new-transition'; section.append(button);
    root.append(section);
  }

  normalizeTransitionMode(mode, presetId = '') {
    const value = String(mode || '').trim().toLowerCase();
    if (['none', 'no-transition', '無過渡', '无过渡'].includes(value)) return '无过渡';
    if (['preset', 'shared-preset', '共享预设'].includes(value) || (!value && presetId)) return '共享预设';
    return '未设置';
  }

  transitionMetadataValues(meta = {}) {
    const presetId = meta.presetId || meta.transitionPresetId || '';
    const mode = this.normalizeTransitionMode(meta.mode || meta.transitionMode, presetId);
    return {
      from: String(meta.from || meta.exitId || meta.sourceSceneId || meta.sceneId || '').trim(),
      sceneId: String(meta.targetSceneId || meta.destinationSceneId || meta.to || '').trim(),
      entryId: String(meta.targetEntryId || meta.entryId || '').trim(),
      condition: String(meta.condition || meta.guard || '').trim(),
      mode,
      presetId: mode === '共享预设' ? String(presetId).trim() : '',
    };
  }

  transitionOperationValues(operation = {}, fallback = {}) {
    const values = { from: '', sceneId: '', entryId: '', condition: '', mode: '未设置', presetId: '', ...fallback };
    for (const key of ['from', 'sceneId', 'entryId', 'condition']) {
      if (Object.hasOwn(operation, key)) values[key] = String(operation[key] || '').trim();
    }
    const presetId = Object.hasOwn(operation, 'presetId') ? operation.presetId : values.presetId;
    const mode = Object.hasOwn(operation, 'mode') ? operation.mode : values.mode;
    values.mode = this.normalizeTransitionMode(mode, presetId);
    values.presetId = values.mode === '共享预设' ? String(presetId || '').trim() : '';
    return values;
  }

  transitionValuesEqual(left, right) {
    return ['from', 'sceneId', 'entryId', 'condition', 'mode', 'presetId'].every(key => (left?.[key] || '') === (right?.[key] || ''));
  }

  transitionStateLabel(values) {
    if (values.mode !== '共享预设') return values.mode || '未设置';
    const preset = values.presetId ? this.object(values.presetId) : null;
    return `共享预设 · ${preset?.name || values.presetId || '预设未映射'}`;
  }

  transitionSnapshotLabel(values) {
    const from = values.from || '来源未设置';
    const scene = values.sceneId ? this.sceneName(values.sceneId) : '目标未设置';
    const entry = values.entryId ? (this.object(values.entryId)?.name || values.entryId) : '入口未设置';
    const condition = values.condition || '未设置';
    return `${from} → ${scene} / ${entry} · 条件 ${condition} · ${this.transitionStateLabel(values)}`;
  }

  updateTransitionEntrySelector(sceneSelect, entrySelect, warning) {
    if (!sceneSelect || !entrySelect) return;
    const requestedEntryId = entrySelect.value || entrySelect.dataset.referenceValue || '';
    const sceneId = sceneSelect.value;
    const entries = sceneId ? this.objects().filter(object => this.role(object) === 'entry' && this.metadata(object).sceneId === sceneId) : [];
    entrySelect.replaceChildren(new Option('未设置入口', ''));
    for (const entry of entries) entrySelect.append(new Option(`${entry.name || entry.id} · ${entry.id}`, entry.id));
    const isValid = entries.some(entry => entry.id === requestedEntryId);
    if (requestedEntryId && !isValid) {
      const existing = this.object(requestedEntryId);
      const reason = !existing ? '当前对象列表中不存在' : this.role(existing) !== 'entry' ? '该对象不是入口' : !sceneId ? '尚未选择目标场景' : `该入口属于 ${this.sceneName(this.metadata(existing).sceneId || '未映射场景')}`;
      const invalid = new Option(`无效引用 · ${requestedEntryId} · ${reason}`, requestedEntryId);
      invalid.disabled = true;
      invalid.dataset.invalidReference = 'true';
      entrySelect.append(invalid);
    }
    entrySelect.value = requestedEntryId || '';
    entrySelect.dataset.referenceValue = entrySelect.value;
    if (warning) {
      warning.textContent = requestedEntryId && !isValid
        ? `现有入口引用“${requestedEntryId}”与当前目标场景不匹配或已失效；请选择该场景内的合法入口，或清除入口。`
        : '';
      hide(warning, !(requestedEntryId && !isValid));
    }
  }

  renderInspector() {
    const root = $('#object-detail');
    if (!root) return;
    this.app.renderObjectDetail?.();
    const object = this.currentTarget();
    this.renderSelectedTargetLabel(object);
    if (!object) {
      root.append(el('p', 'workbench-data-note', `已发布基线版本 ${this.app.snapshot?.publicationRevision ?? '未知'}。项目级意见会作为本轮原文提交。`));
      this.renderSupplementalNotes(root, null);
      this.renderFacetSummary(root, null);
      const coverageMount = el('div', 'workbench-coverage-mount');
      root.append(coverageMount);
      renderSourceCoverage(coverageMount, this.objects(), { metadataFor: item => this.metadata(item) });
      return;
    }
    const meta = this.metadata(object);
    const facts = this.targetRangeFacts(object);
    mountVisual(root, { title: '当前目标与此项影响', status: `来源：当前对象快照 · 基线版本 ${this.app.snapshot?.publicationRevision ?? '未知'}；本轮草稿尚未制作`,
      rows: [{ label: '目标', value: facts.target }, { label: '此项影响', value: facts.impact }],
      details: [{ label: '对象编号', value: object.id }, { label: '角色', value: this.roleLabel(object) }, { label: '来源', value: object.sourceBindings || [] }] }, `target:${this.app.projectId}:${object.id}`);
    root.append(el('div', 'workbench-inspector-heading', `${this.roleLabel(object)} · ${object.name || object.label || '未命名对象'}`));
    if (this.isDraftTarget(object.id)) {
      const draftNote = el('p', 'workbench-data-note', '这是本地结构草稿目标；意见会绑定到此稳定草稿 ID，并与结构操作一起申报。');
      root.append(draftNote);
    }
    this.appendTargetRange(root, object, object.id);
    const metadataList = el('dl', 'workbench-metadata');
    this.addMetadataRow(metadataList, '作用范围', meta.scope == null ? null : this.scopeLabel(meta.scope));
    this.addMetadataRow(metadataList, '共享定义', meta.definitionId, meta.definitionId && this.object(meta.definitionId) ? meta.definitionId : null);
    this.addMetadataRow(metadataList, '所属场景', meta.sceneId, meta.sceneId);
    this.addMetadataRow(metadataList, '锁定状态', this.lockLabel(this.effectiveLock(object)));
    this.addMetadataRow(metadataList, '生命周期', meta.lifecycle == null ? null : this.lifecycleLabel(meta.lifecycle));
    if (meta.position || this.geometryBinding(object, 'position')) this.addMetadataRow(metadataList, '位置', meta.position ? this.displayValue(this.proposedPosition(object) || meta.position) : '字段草稿未确认');
    if (meta.size || this.geometryBinding(object, 'size')) this.addMetadataRow(metadataList, '大小', meta.size ? this.displayValue(meta.size) : '字段草稿未确认');
    if (meta.bounds) this.addMetadataRow(metadataList, '边界', this.displayValue(meta.bounds));
    if (meta.anchor) this.addMetadataRow(metadataList, '锚点', this.displayValue(meta.anchor));
    if (metadataList.childNodes.length) root.append(metadataList);
    this.renderPositionControls(root, object);
    this.renderRelations(root, object);
    this.renderFacetSummary(root, object);
    const source = el('details', 'workbench-source-details');
    source.append(el('summary', '', '来源、覆盖与诊断'));
    const provenance = meta.provenance;
    source.append(el('p', '', `信息类型：${PROVENANCE_LABELS[provenance?.kind] || provenance?.kind || '未声明'}`));
    if (meta.driver) source.append(el('p', '', `驱动来源：${meta.driver}`));
    const paths = [...(provenance?.sourcePaths || []), ...(object.sourceBindings || [])];
    if (paths.length) { const list = el('ul', 'workbench-path-list'); for (const path of [...new Set(paths)]) list.append(el('li', '', path)); source.append(list); }
    else source.append(el('p', 'muted', '未提供源文件路径。'));
    source.append(el('p', 'muted', this.metadataCoverage(object)));
    const sourceButton = el('button', 'button secondary', '按当前发布版本读取来源'); sourceButton.type = 'button'; sourceButton.dataset.workbenchAction = 'load-source'; sourceButton.dataset.objectId = object.id; source.append(sourceButton);
    const sourceResult = el('div', 'workbench-source-result'); sourceResult.dataset.sourceObjectId = object.id; source.append(sourceResult);
    source.addEventListener('toggle', () => { if (source.open) this.loadSource(object.id, source); });
    root.append(source);
    this.renderSupplementalNotes(root, object.id);
    const coverageMount = el('div', 'workbench-coverage-mount');
    root.append(coverageMount);
    renderSourceCoverage(coverageMount, this.objects(), { metadataFor: item => this.metadata(item) });
  }

  targetRangeFacts(object, targetId = object?.id || null) {
    if (!object) return {
      target: targetId ? `公开对象目录中暂不可见的目标 ${targetId}` : '当前项目',
      impact: targetId ? '意见仍绑定此目标编号；当前快照没有足够信息判断影响范围，请在方案中明确后再审阅。' : '项目级意见针对当前项目；具体会改动哪些对象仍需在方案中明确。',
      presence: '未声明', lifecycle: '未声明',
    };
    const meta = this.metadata(object), role = this.role(object);
    const name = object.name || object.label || object.id;
    const target = `${this.roleLabel(object)} · ${name}（${object.id}）`;
    const normalizedScope = String(meta.scope || '').trim().toLowerCase().replaceAll('_', '-').replaceAll(' ', '-');
    const runtimeScopes = new Set(['runtime', 'runtime-generated', 'runtime-instance']);
    const explicitImpact = meta.impactScope || meta.changeScope || meta.editScope
      || (!runtimeScopes.has(normalizedScope) ? meta.scope : null);
    let impact;
    if (role === 'instance') {
      const definitionId = meta.definitionId;
      const definition = definitionId ? this.object(definitionId) : null;
      const siblingCount = definitionId ? this.objects().filter(item => this.role(item) === 'instance' && this.metadata(item).definitionId === definitionId).length : 0;
      const capabilities = (this.app.allCapabilities?.() || []).filter(capability => this.app.splitCapability?.(capability)?.objectId === object.id
        && (this.app.capabilityEditable ? this.app.capabilityEditable(capability, object) : capability.editable === true));
      const capabilityLabels = capabilities.map(capability => capability.label || this.app.splitCapability?.(capability)?.fieldId).filter(Boolean);
      const capabilityText = capabilityLabels.length
        ? `快照列出此实例独立可编辑字段：${capabilityLabels.join('、')}。`
        : '当前快照未声明此实例独立可编辑字段。';
      const definitionText = definitionId
        ? `它关联共享定义“${definition?.name || definitionId}”${siblingCount > 1 ? `，目录中共见 ${siblingCount} 个关联实例` : ''}。`
        : '共享定义关系未提供。';
      impact = `意见目标只指向此场景实例。${definitionText}${capabilityText}${explicitImpact ? `公开影响范围：${this.scopeLabel(explicitImpact)}。` : '共享定义或其他实例是否受影响尚无快照依据；策划方案仍须明确影响对象并供你审阅。'}`;
    } else if (explicitImpact) {
      impact = `公开元数据声明的影响范围：${this.scopeLabel(explicitImpact)}。该范围描述快照事实，不表示本轮修改已经制作。`;
    } else {
      impact = '当前快照没有声明修改影响范围；意见仍只绑定上述目标，具体影响对象须在策划方案中明确。';
    }
    const presenceSource = meta.presence || meta.runtimePresence || meta.creationMode || (runtimeScopes.has(normalizedScope) ? meta.scope : null);
    return {
      target,
      impact,
      presence: object.draft ? '这是尚未制作的结构草稿；运行时出现方式待方案说明' : presenceSource ? this.scopeLabel(presenceSource) : '当前快照未声明对象如何在运行中出现',
      lifecycle: object.draft ? '尚未制作；生命周期待方案说明' : meta.lifecycle ? this.lifecycleLabel(meta.lifecycle) : '当前快照未声明生命周期',
    };
  }

  appendTargetRange(root, object, targetId = object?.id || null) {
    const facts = this.targetRangeFacts(object, targetId);
    const details = el('dl', 'workbench-target-range');
    for (const [label, value] of [['意见目标', facts.target], ['已知修改影响', facts.impact], ['运行存在方式', facts.presence], ['生命周期', facts.lifecycle]]) {
      details.append(el('dt', '', label), el('dd', '', value));
    }
    root.append(details);
  }

  renderSupplementalNotes(root, targetObjectId) {
    const targetKey = targetObjectId || '__project__';
    const notes = Object.entries(this.app.targetNotes || {}).filter(([key, note]) => key !== targetKey && this.noteTargetId(key, note) === (targetObjectId || null) && String(note?.text || '').trim());
    if (!notes.length) return;
    const section = el('section', 'workbench-associated-notes'); section.append(el('h4', '', '另有关联意见'), el('p', 'muted', '这些意见与当前目标分别保存、分别追踪。'));
    for (const [key, note] of notes) {
      const item = el('article', 'workbench-associated-note');
      item.append(el('small', 'muted', `意见 ${note.feedbackId || '尚未编号'}${note.originalObjectId ? ` · 原目标 ${note.originalObjectId}` : ''}`));
      const editor = el('textarea'); editor.rows = 3; editor.maxLength = 4000; editor.value = note.text || ''; editor.dataset.associatedNoteKey = key; editor.setAttribute('aria-label', `编辑关联意见 ${note.feedbackId || key}`); item.append(editor);
      const remove = el('button', 'button quiet', '移除此意见'); remove.type = 'button'; remove.dataset.removeAssociatedNote = key; item.append(remove); section.append(item);
    }
    root.append(section);
  }

  async loadSource(objectId, details) {
    const result = details?.querySelector('.workbench-source-result');
    if (!result || result.dataset.loaded === 'true') return;
    const projectId = this.app.projectId;
    const context = this.sourceContextKey();
    const expectedSourceCommit = this.app.snapshot?.sourceCommit || this.app.snapshot?.baseCommit || null;
    result.dataset.loaded = 'true'; result.replaceChildren(el('p', 'muted', '正在读取公开的版本化来源…'));
    try {
      const response = await this.app.request(`/projects/${encodeURIComponent(projectId)}/objects/${encodeURIComponent(objectId)}/source`, { projectId: null });
      if (!result.isConnected || this.sourceContextKey() !== context) return;
      if (this.app.projectId !== projectId || response.projectId !== projectId || response.objectId !== objectId || response.kind !== 'static_source') throw new Error('来源响应身份与目标不匹配。');
      if (expectedSourceCommit && response.sourceCommit !== expectedSourceCommit) throw new Error('来源响应的 Git 版本与当前发布快照不匹配。');
      result.replaceChildren(el('p', 'muted', `精确发布版本：${response.sourceCommit || '未提供'}`));
      const sources = Array.isArray(response.sources) ? response.sources : [];
      if (!sources.length) result.append(el('p', 'muted', '当前版本没有为此对象提供可读取的源文件。'));
      for (const source of sources) {
        const article = el('article', 'workbench-source-file'); article.append(el('b', '', source.path || '未命名来源'));
        if (source.available && typeof source.content === 'string') article.append(el('pre', '', source.content));
        else article.append(el('p', 'muted', source.reason || '此来源当前不可读取。'));
        if (source.truncated) article.append(el('p', 'muted', '输出已截断；完整来源仍留在原文件中。'));
        result.append(article);
      }
      this.sourceCache.set(objectId, response);
      this.renderBoundSourcePreview(result, objectId, response);
    } catch (error) {
      if (!result.isConnected || this.sourceContextKey() !== context) return;
      result.dataset.loaded = 'false'; result.replaceChildren(el('p', 'muted danger-text', `来源读取失败：${error.message}`));
    }
  }

  renderBoundSourcePreview(root, objectId, response) {
    const context = this.sourceContextKey();
    const description = response.imagePreview;
    const section = el('section', 'workbench-source-image-preview');
    section.append(el('b', '', '绑定资源预览'));
    if (!description || typeof description !== 'object') {
      section.append(el('p', 'muted', response.imagePreviewUnavailableReason || '当前发布版本没有可确认的静态图片、Atlas 区域或动画剪辑首帧。'));
      root.append(section);
      return;
    }
    const path = description.resourcePath || description.imagePath;
    if (path) section.append(el('p', 'muted', `来源资源：${path}`));
    if (Array.isArray(description.region) && description.region.length === 4) {
      section.append(el('p', 'muted', `Atlas 区域：${description.region[0]}, ${description.region[1]} · ${description.region[2]} × ${description.region[3]} 像素。`));
    }
    if (description.clipName) {
      const frameCount = Number(description.frameCount), fps = Number(description.fps);
      const details = [`动画剪辑“${description.clipName}”`];
      if (Number.isInteger(frameCount) && frameCount >= 0) details.push(`${frameCount} 帧`);
      if (description.fps != null && Number.isFinite(fps)) details.push(`${this.formatNumber(fps)} FPS`);
      section.append(el('p', 'muted', `${details.join(' · ')}。下图显示此剪辑的真实首帧；工作台不会把静态首帧说成动画播放。`));
    } else if (!Array.isArray(description.region)) section.append(el('p', 'muted', '此图来自目标绑定的静态图片资源。'));
    const image = el('img', 'workbench-resource-image workbench-source-resource-image');
    image.alt = `${this.object(objectId)?.name || objectId} · 精确发布版本绑定资源首帧`;
    image.loading = 'lazy';
    image.src = `/api/projects/${encodeURIComponent(response.projectId)}/objects/${encodeURIComponent(objectId)}/preview`;
    image.addEventListener('load', () => {
      if (!image.isConnected || this.sourceContextKey() !== context) return;
      this.previewCache.set(objectId, { state: 'loaded', sourceCommit: response.sourceCommit || '当前发布版本' });
    });
    image.addEventListener('error', () => {
      if (!image.isConnected || this.sourceContextKey() !== context) return;
      this.previewCache.set(objectId, { state: 'missing', reason: response.imagePreviewUnavailableReason || '绑定图片读取失败，当前仍可查看对象语义和源文件。' });
      image.remove();
      section.append(el('p', 'muted danger-text', '首帧图片读取失败；保留上述来源描述和语义预览。'));
    });
    section.append(image, el('small', 'muted', `显示版本：${response.sourceCommit || '未提供'}。`));
    root.append(section);
  }

  addMetadataRow(list, label, value, targetId = null) {
    if (value == null || value === '') return;
    const term = el('dt', '', label), detail = el('dd');
    if (targetId) { const link = el('button', 'text-link', this.object(targetId)?.name || targetId); link.type = 'button'; link.dataset.objectId = targetId; detail.append(link); }
    else detail.textContent = this.displayValue(value);
    list.append(term, detail);
  }

  lockLabel(lock) { return ({ fixed: '固定', nudge: '可微调', free: '自由' })[lock] || (lock ? `未识别 · ${lock}` : '未声明'); }
  effectiveLock(object) {
    const baseline = this.metadata(object).lock;
    const proposal = this.app.structuralProposals.find(item => item.kind === 'set-lock' && item.objectId === object?.id);
    return proposal && proposal.before === baseline && ['fixed', 'nudge', 'free'].includes(proposal.lock) ? proposal.lock : baseline;
  }
  provenanceLabel(meta) { const p = meta.provenance || {}; return `${PROVENANCE_LABELS[p.kind] || p.kind || '未声明'}${p.sourcePaths?.length ? ` · ${p.sourcePaths.join('、')}` : ''}`; }
  metadataCoverage(object) {
    const meta = this.metadata(object);
    const gaps = [];
    for (const key of ['role', 'scope', 'provenance']) if (meta[key] == null) gaps.push(key);
    if (['instance', 'entry', 'spawn'].includes(this.role(object)) && !meta.sceneId) gaps.push('sceneId');
    if (meta.preview == null) gaps.push('preview');
    return gaps.length ? `对象元数据尚未提供：${gaps.join('、')}。当前详情只使用公开快照中的现有信息。` : '当前显示公开快照提供的元数据。';
  }

  renderPositionControls(root, object) {
    const meta = this.metadata(object), role = this.role(object);
    if (this.isDraftTarget(object.id)) return;
    if (!['instance', 'entry', 'spawn'].includes(role) || !Array.isArray(meta.position)) return;
    const position = this.proposedPosition(object) || meta.position;
    const baselineLock = meta.lock;
    const lock = this.effectiveLock(object) || 'fixed';
    const section = el('section', 'workbench-position-controls');
    section.append(el('h4', '', '场景位置提案'), el('p', 'muted', `当前编辑约束：${this.lockLabel(lock)}。调整只作为申报草稿，源码位置仍为 ${this.displayValue(this.metadata(object, { draft: false }).position)}。${meta.positionFieldId ? '位置控件与绑定属性共用同一草稿。' : ''}`));
    if (role === 'instance' && ['fixed', 'nudge', 'free'].includes(baselineLock)) {
      const lockControl = el('div', 'workbench-lock-control');
      const label = el('label', '', '请求的编辑约束');
      const select = el('select'); select.name = 'requestedLock';
      select.append(new Option('自由 · 可拖动', 'free'), new Option('可微调 · 方向按钮', 'nudge'), new Option('固定 · 禁止移动和删除', 'fixed'));
      select.value = lock;
      label.append(select);
      const update = el('button', 'button secondary', '变更此实例编辑约束'); update.type = 'button'; update.dataset.workbenchAction = 'set-instance-lock'; update.dataset.objectId = object.id;
      lockControl.append(label, update);
      lockControl.append(el('small', 'muted', `发布基线：${this.lockLabel(baselineLock)}。变更会作为显式 set-lock 提案；移动提案与之绑定，可一并撤销。`));
      section.append(lockControl);
    }
    if (lock === 'fixed') { section.append(el('p', 'workbench-readonly', '此对象标记为固定，禁止移动和删除；工作台不会生成移动或删除提案。可以通过意见描述其他期望。')); root.append(section); return; }
    const bounds = this.sceneBounds(meta.sceneId || this.sceneCanvasSelection || this.activeSceneId);
    const x = el('input'); x.type = 'number'; x.step = 'any'; x.value = String(position[0]); x.dataset.positionAxis = '0'; x.setAttribute('aria-label', '提案位置 X');
    const y = el('input'); y.type = 'number'; y.step = 'any'; y.value = String(position[1]); y.dataset.positionAxis = '1'; y.setAttribute('aria-label', '提案位置 Y');
    const save = el('button', 'button secondary', '记录位置提案'); save.type = 'button'; save.addEventListener('click', () => this.proposeMove(object, [Number(x.value), Number(y.value)]));
    section.append(el('label', 'field-label', 'X'), x, el('label', 'field-label', 'Y'), y);
    if (lock === 'nudge') {
      const controls = el('div', 'workbench-nudge');
      const step = Number(meta.nudgeStep) > 0 ? Number(meta.nudgeStep) : 1;
      for (const [title, dx, dy] of [['↑', 0, -step], ['←', -step, 0], ['→', step, 0], ['↓', 0, step]]) { const button = el('button', 'button quiet', title); button.type = 'button'; button.dataset.workbenchAction = 'nudge'; button.dataset.dx = String(dx); button.dataset.dy = String(dy); button.setAttribute('aria-label', `微调位置 ${title}`); controls.append(button); }
      section.append(controls, el('small', 'muted', `每次微调 ${step} 个坐标单位；边界按所属场景世界尺寸校验。`));
    } else section.append(el('small', 'muted', bounds ? `可拖动预览对象；边界 ${this.displayValue(bounds)}。` : '可拖动预览对象；没有边界数据时不会声称坐标有效。'));
    if (!bounds) section.append(el('p', 'workbench-readonly', '此实例所属场景没有公开世界边界，不能校验坐标；实例自身 bounds 不会用作场景边界。'));
    section.append(save);
    root.append(section);
  }

  renderRelations(root, object) {
    const related = this.relatedObjects(object);
    const section = el('section', 'workbench-relations');
    section.append(el('h4', '', '关联与使用处'));
    if (!related.length) section.append(el('p', 'muted', '快照未提供可反查的关系、实例、规则或资源使用处。'));
    for (const { item, label } of related) {
      const button = el('button', 'workbench-relation-link'); button.type = 'button'; button.dataset.objectId = item.id;
      button.append(el('span', '', this.relationTypeLabel(label)), el('b', '', item.name || item.label || '未命名对象'));
      button.addEventListener('click', () => this.app.selectObject(item.id));
      const identity = el('details', 'workbench-relation-identity');
      identity.append(el('summary', '', '查看对象编号'), el('code', '', item.id));
      section.append(button, identity);
    }
    root.append(section);
  }

  relations(object) {
    const relations = Array.isArray(object?.relations) ? object.relations : [];
    const meta = this.metadata(object);
    return [...relations, ...(Array.isArray(meta.usage) ? meta.usage.map(target => ({ type: '使用处', targetId: typeof target === 'string' ? target : target.id })) : [])];
  }

  relatedObjects(object) {
    if (!object) return [];
    const results = new Map();
    const add = (id, label) => { const item = this.object(id); if (item && item.id !== object.id && !results.has(item.id)) results.set(item.id, { item, label }); };
    const meta = this.metadata(object);
    if (meta.definitionId) add(meta.definitionId, '共享定义');
    for (const relation of this.relations(object)) add(relation.targetId || relation.target, relation.type || '关联');
    for (const other of this.objects()) {
      const otherMeta = this.metadata(other);
      if (otherMeta.definitionId === object.id) add(other.id, '使用此定义的实例');
      if ((other.relations || []).some(relation => (relation.targetId || relation.target) === object.id)) add(other.id, '反向关联');
      if (otherMeta.sceneId === object.id) add(other.id, '场景实例 / 入口');
    }
    return [...results.values()];
  }

  renderFacetSummary(root, object) {
    const facets = this.metadata(object).facets || {};
    const section = el('section', 'workbench-facet-status'); section.append(el('h4', '', '观察面'));
    for (const [key, label] of [['narrative', '叙事'], ['art', '表现']]) {
      const value = facets[key];
      section.append(el('p', value == null || value === '' ? 'muted' : 'workbench-facet-present', `${label}：${value == null || value === '' ? '未提供' : '有来源内容'}`));
    }
    root.append(section);
  }

  renderOrphanNotes() {
    const root = $('#object-detail');
    const orphans = this.orphanNotes();
    if (!root || !orphans.length) return;
    const section = el('section', 'workbench-orphan-notes');
    section.append(el('h4', '', '意见目标已失效'), el('p', '', '这些意见仍保存在本地，没有自动扩大到全项目。请重新关联或移除后再申报。'));
    for (const key of orphans) {
      const note = this.app.targetNotes[key], originalId = note.originalObjectId || this.noteTargetId(key, note) || key;
      const row = el('div', 'workbench-orphan-row'); row.append(el('b', '', originalId), el('p', '', note?.text || ''));
      const select = el('select'); select.setAttribute('aria-label', `为 ${originalId} 重新关联目标`); select.append(new Option('选择新目标', ''));
      select.append(new Option('当前项目', '__project__'));
      for (const object of this.objects()) select.append(new Option(`${object.name || object.id} · ${object.id}`, object.id));
      const reassign = el('button', 'button secondary', '重新关联'); reassign.type = 'button'; reassign.addEventListener('click', () => {
        if (!select.value) return;
        const target = select.value === '__project__' ? null : select.value;
        const identity = note.feedbackId || this.app.newFeedbackId();
        let nextKey = `__workbench_note__${identity}`, suffix = 1;
        while (Object.hasOwn(this.app.targetNotes, nextKey) && nextKey !== key) nextKey = `__workbench_note__${identity}_${suffix++}`;
        this.pushHistory();
        delete this.app.targetNotes[key];
        this.app.targetNotes[nextKey] = { ...note, objectId: target, originalObjectId: note.originalObjectId || originalId, feedbackId: identity, updatedAt: new Date().toISOString() };
        this.app.queueDraftSave?.(); this.pushHistory();
        if (target) this.app.selectObject(target); else this.selectProject();
        this.render();
      });
      const remove = el('button', 'button quiet', '移除此意见'); remove.type = 'button'; remove.addEventListener('click', () => { this.pushHistory(); delete this.app.targetNotes[key]; this.app.queueDraftSave?.(); this.pushHistory(); this.render(); });
      row.append(select, reassign, remove); section.append(row);
    }
    root.append(section);
  }

  orphanNotes() { return Object.entries(this.app.targetNotes || {}).filter(([key, note]) => { const target = this.noteTargetId(key, note); return target != null && !this.object(target) && String(note?.text || '').trim(); }).map(([key]) => key); }

  proposedPosition(object) { return this.app.structuralProposals.find(item => item.kind === 'move' && item.objectId === object.id)?.requested || null; }
  positionGeometry(meta) {
    if (meta.size === null) return { error: '绑定的大小字段尚未确认，无法校验实例边界。' };
    const rawSize = Array.isArray(meta.size) ? meta.size : [0, 0], rawAnchor = Array.isArray(meta.anchor) ? meta.anchor : [0, 0];
    const size = [Number(rawSize[0] ?? 0), Number(rawSize[1] ?? 0)], anchor = [Number(rawAnchor[0] ?? 0), Number(rawAnchor[1] ?? 0)];
    if (rawSize.length !== 2 || !size.every(value => Number.isFinite(value) && value >= 0)) return { error: '实例大小必须是两个有效的非负坐标值。' };
    if (rawAnchor.length !== 2 || !anchor.every(value => Number.isFinite(value) && value >= 0 && value <= 1)) return { error: '实例锚点必须是 0 到 1 之间的两个有效比例。' };
    return { size, anchor };
  }
  positionIssue(sceneId, meta, position) {
    if (!Array.isArray(position) || position.length !== 2 || !position.every(value => Number.isFinite(Number(value)))) return '坐标必须是两个有效数字。';
    const bounds = this.sceneBounds(sceneId);
    if (!bounds) return '所属场景没有提供世界边界，工作台无法校验坐标；实例自身 bounds 不会替代场景边界。';
    const width = Number(bounds[0]), height = Number(bounds[1]);
    if (!(width > 0 && height > 0)) return '所属场景的世界边界必须是两个有效的正数。';
    if (position[0] < 0 || position[1] < 0 || position[0] > width || position[1] > height) return `坐标必须位于世界边界 0–${width}, 0–${height} 内。`;
    const geometry = this.positionGeometry(meta);
    if (geometry.error) return geometry.error;
    const { size, anchor } = geometry;
    if (position[0] - size[0] * anchor[0] < 0 || position[0] + size[0] * (1 - anchor[0]) > width || position[1] - size[1] * anchor[1] < 0 || position[1] + size[1] * (1 - anchor[1]) > height) return '实例的大小和锚点会使其越过世界边界。';
    return null;
  }
  proposalMoveValid(object, position) {
    const meta = this.metadata(object), sceneId = meta.sceneId || this.sceneCanvasSelection || this.activeSceneId;
    return this.positionIssue(sceneId, meta, position);
  }

  setInstanceLock(objectId, requestedLock) {
    const object = this.objects().find(item => item.id === objectId), meta = this.metadata(object);
    if (!object || this.role(object) !== 'instance' || !['fixed', 'nudge', 'free'].includes(meta.lock)) return this.app.notify?.('只有声明了 fixed、nudge 或 free 的现有场景实例可以提出编辑约束变更。');
    if (!['fixed', 'nudge', 'free'].includes(requestedLock)) return this.app.notify?.('请选择有效的实例编辑约束。');
    if (this.app.structuralProposals.some(item => item.kind === 'delete-instance' && item.objectId === object.id)) return this.app.notify?.('同一实例不能同时申报编辑约束变更和移除；请先移除删除提案。');
    const baselineLock = meta.lock, currentLock = this.effectiveLock(object);
    const existingLock = this.app.structuralProposals.find(item => item.kind === 'set-lock' && item.objectId === object.id);
    const existingMove = this.app.structuralProposals.find(item => item.kind === 'move' && item.objectId === object.id);
    if (requestedLock === currentLock && !(requestedLock === 'fixed' && existingMove)) return false;
    const next = this.app.structuralProposals.filter(item => !(item.kind === 'set-lock' && item.objectId === object.id));
    if (requestedLock !== baselineLock) {
      next.push({
        operationId: existingLock?.operationId || existingLock?.proposalId || this.app.newFeedbackId?.() || `set-lock-${Date.now()}`,
        kind: 'set-lock', objectId: object.id, before: baselineLock, lock: requestedLock,
        scope: '用户显式修改约束', createdAt: existingLock?.createdAt || new Date().toISOString(),
      });
    }
    let finalOperations = next;
    if (requestedLock === 'fixed') finalOperations = finalOperations.filter(item => !(item.kind === 'move' && item.objectId === object.id));
    else if (existingMove) finalOperations = finalOperations.map(item => item === existingMove ? { ...item, lock: requestedLock } : item);
    this.pushHistory();
    this.app.structuralProposals = finalOperations;
    this.app.queueDraftSave?.(); this.pushHistory(); this.render();
    this.app.notify?.(requestedLock === baselineLock
      ? `已将 ${object.name || object.id} 的编辑约束提案恢复到发布基线。`
      : `已记录 ${object.name || object.id} 的显式编辑约束变更；不会修改源码。`);
    return true;
  }

  proposeMove(object, position) {
    if (!object) return;
    const meta = this.metadata(object);
    const lock = this.effectiveLock(object);
    if (lock === 'fixed') { this.app.notify?.('此实例当前编辑约束为固定，不能记录移动提案。'); return false; }
    if (!['free', 'nudge'].includes(lock)) { this.app.notify?.('此实例未声明 free 或 nudge 锁定状态；位置保持只读。'); return false; }
    const issue = this.proposalMoveValid(object, position);
    if (issue) { this.app.notify?.(issue); return false; }
    const binding = this.geometryBinding(object, 'position');
    if (binding) {
      const field = this.objectField(object, binding.fieldId);
      const capability = this.app.allCapabilities?.().find(item => {
        const parts = this.app.splitCapability?.(item);
        return parts?.objectId === object.id && parts?.fieldId === binding.fieldId;
      });
      const editable = typeof this.app.allCapabilities === 'function'
        ? !!capability && this.app.capabilityEditable?.(capability, object) === true : field?.editable === true;
      if (!editable) { this.app.notify?.('绑定的位置属性当前不可编辑；请通过意见说明期望。'); return false; }
      this.app.captureVisibleFields?.(); this.pushHistory();
      const key = `${object.id}.${binding.fieldId}`, requested = position.map(value => Number(this.formatNumber(value)));
      this.app.fieldDraftValues ||= {};
      if (JSON.stringify(requested) === JSON.stringify(field.value)) { delete this.app.fieldDraftValues[key]; this.app.dirtyFields?.delete(key); }
      else { this.app.fieldDraftValues[key] = requested; this.app.dirtyFields?.add(key); }
      this.app.structuralProposals = this.app.structuralProposals.filter(item => !(item.kind === 'move' && item.objectId === object.id));
      this.app.renderDynamicFields?.(this.objects(), this.app.capabilities);
      this.stopPreview(); this.app.queueDraftSave?.(); this.pushHistory(); this.render(); return true;
    }
    this.pushHistory();
    const existing = this.app.structuralProposals.find(item => item.kind === 'move' && item.objectId === object.id);
    const proposal = { operationId: existing?.operationId || existing?.proposalId || this.app.newFeedbackId(), kind: 'move', objectId: object.id, before: existing?.before || this.metadata(object, { draft: false }).position, requested: position.map(value => Number(this.formatNumber(value))), scope: this.metadata(object).scope || '当前实例', lock, createdAt: existing?.createdAt || new Date().toISOString() };
    this.app.structuralProposals = [...this.app.structuralProposals.filter(item => !(item.kind === 'move' && item.objectId === object.id)), proposal];
    this.app.queueDraftSave?.(); this.pushHistory(); this.render(); return true;
  }

  nudgeSelected(dx, dy, objectId = this.app.selectedObjectId) {
    const object = this.object(objectId), meta = this.metadata(object);
    if (!object || this.effectiveLock(object) !== 'nudge' || !Array.isArray(meta.position)) return this.app.notify?.('只有当前编辑约束声明 nudge 且包含位置数据的对象可微调。');
    const current = this.proposedPosition(object) || meta.position;
    const position = [Number(current[0]) + dx, Number(current[1]) + dy];
    const draft = this.draftInstanceOperation(object.id);
    if (draft) this.setDraftInstancePosition(draft.operationId || draft.proposalId, position);
    else this.proposeMove(object, position);
  }

  beginDrag(event) {
    if (this.pendingPlacementOperationId) return;
    const token = event.target.closest('.workbench-object-token[data-object-id]');
    if (!token || token.dataset.lock !== 'free' || !event.isPrimary || event.button !== 0) return;
    const object = this.object(token.dataset.objectId);
    const sceneId = this.metadata(object).sceneId || token.closest('.workbench-coordinate-canvas')?.dataset.sceneId;
    const bounds = this.sceneBounds(sceneId);
    if (!object || !bounds || !Array.isArray(this.metadata(object).position)) return;
    const draft = this.draftInstanceOperation(object.id);
    this.drag = { pointerId: event.pointerId, token, object, canvas: token.closest('.workbench-coordinate-canvas'), sceneId, bounds, start: this.proposedPosition(object) || this.metadata(object).position, last: null, draftOperationId: draft?.operationId || draft?.proposalId || null };
    token.setPointerCapture?.(event.pointerId);
    event.preventDefault();
  }
  moveDrag(event) {
    if (!this.drag || event.pointerId !== this.drag.pointerId) return;
    const rect = this.drag.canvas.getBoundingClientRect(), [width, height] = this.drag.bounds;
    if (!(rect.width > 0 && rect.height > 0)) return;
    const rawX = Math.max(0, Math.min(1, (event.clientX - rect.left) / rect.width)) * width;
    const rawY = Math.max(0, Math.min(1, (event.clientY - rect.top) / rect.height)) * height;
    const meta = this.metadata(this.drag.object), geometry = this.positionGeometry(meta);
    if (geometry.error) return this.app.notify?.(geometry.error);
    const { size, anchor } = geometry;
    const x = Math.round(Math.max(Number(size[0] || 0) * Number(anchor[0] || 0), Math.min(width - Number(size[0] || 0) * (1 - Number(anchor[0] || 0)), rawX)));
    const y = Math.round(Math.max(Number(size[1] || 0) * Number(anchor[1] || 0), Math.min(height - Number(size[1] || 0) * (1 - Number(anchor[1] || 0)), rawY)));
    this.drag.last = [x, y];
    this.drag.token.style.left = `${x / width * 100}%`; this.drag.token.style.top = `${y / height * 100}%`;
    this.drag.token.style.setProperty('--anchor-x', String(Number(anchor[0]) * 100)); this.drag.token.style.setProperty('--anchor-y', String(Number(anchor[1]) * 100));
  }
  endDrag(event) {
    if (!this.drag || event.pointerId !== this.drag.pointerId) return;
    const { object, last, draftOperationId } = this.drag; this.drag = null;
    if (event.type === 'pointercancel') { this.render(); return; }
    if (!last) return;
    const current = this.proposedPosition(object) || this.metadata(object).position;
    if (JSON.stringify(last) === JSON.stringify(current)) return;
    if (draftOperationId) {
      const operation = this.app.structuralProposals.find(item => (item.operationId || item.proposalId) === draftOperationId && item.kind === 'new-instance');
      if (operation) this.setDraftInstancePosition(draftOperationId, last);
    } else this.proposeMove(object, last);
  }

  cancelDrag() { if (!this.drag) return; this.drag = null; this.render(); }

  positionForEvent(event, canvas, sceneId, object) {
    const bounds = this.sceneBounds(sceneId), rect = canvas?.getBoundingClientRect?.();
    if (!bounds) return { error: '所属场景没有公开世界边界，无法放置或校验实例。' };
    if (!rect || !(rect.width > 0 && rect.height > 0)) return { error: '场景画布尺寸不可用，无法换算坐标。' };
    const meta = this.metadata(object), geometry = this.positionGeometry(meta);
    if (geometry.error) return { error: geometry.error };
    const { size, anchor } = geometry;
    const minX = Number(size[0] || 0) * Number(anchor[0] || 0), maxX = bounds[0] - Number(size[0] || 0) * (1 - Number(anchor[0] || 0));
    const minY = Number(size[1] || 0) * Number(anchor[1] || 0), maxY = bounds[1] - Number(size[1] || 0) * (1 - Number(anchor[1] || 0));
    if (minX > maxX || minY > maxY) return { error: '实例尺寸与锚点无法放入此场景边界。' };
    const x = Math.max(0, Math.min(1, (event.clientX - rect.left) / rect.width)) * bounds[0];
    const y = Math.max(0, Math.min(1, (event.clientY - rect.top) / rect.height)) * bounds[1];
    return { position: [Math.round(Math.max(minX, Math.min(maxX, x))), Math.round(Math.max(minY, Math.min(maxY, y)))], bounds };
  }

  previewPendingInstance(event, canvas) {
    const operation = this.pendingPlacement?.operationId === this.pendingPlacementOperationId ? this.pendingPlacement : null;
    if (!operation || canvas.dataset.sceneId !== operation.sceneId) return;
    const definition = this.object(operation.definitionId), draft = { ...definition, workbench: this.draftInstanceMetadata(operation, definition) };
    const result = this.positionForEvent(event, canvas, operation.sceneId, draft);
    if (result.error) return;
    let marker = canvas.querySelector('.workbench-placement-cursor');
    if (!marker) { marker = el('div', 'workbench-placement-cursor'); marker.setAttribute('aria-hidden', 'true'); canvas.append(marker); }
    const draftMeta = this.metadata(draft), size = Array.isArray(draftMeta.size) ? draftMeta.size : null;
    marker.style.left = `${result.position[0] / result.bounds[0] * 100}%`; marker.style.top = `${result.position[1] / result.bounds[1] * 100}%`;
    const anchor = Array.isArray(draftMeta.anchor) ? draftMeta.anchor : [0, 0];
    marker.style.setProperty('--anchor-x', String(Number(anchor[0]) * 100)); marker.style.setProperty('--anchor-y', String(Number(anchor[1]) * 100));
    if (size) { marker.style.width = `${Number(size[0]) / result.bounds[0] * 100}%`; marker.style.height = `${Number(size[1]) / result.bounds[1] * 100}%`; }
    marker.textContent = operation.name || '待放置实例';
  }

  placePendingInstance(event, canvas) {
    const operation = this.pendingPlacement?.operationId === this.pendingPlacementOperationId ? this.pendingPlacement : null;
    if (!operation || canvas.dataset.sceneId !== operation.sceneId) return;
    const definition = this.object(operation.definitionId);
    if (!definition || this.role(definition) !== 'definition') return this.app.notify?.('待放置实例引用的共享定义已不可用。');
    const draft = { ...definition, workbench: this.draftInstanceMetadata(operation, definition) };
    const result = this.positionForEvent(event, canvas, operation.sceneId, draft);
    if (result.error) return this.app.notify?.(result.error);
    const issue = this.proposalPositionValid(operation.sceneId, definition, result.position, operation);
    if (issue) return this.app.notify?.(issue);
    const placed = { ...operation, requestedPosition: result.position, scope: '单个新实例' };
    this.pushHistory(); this.app.structuralProposals = [...this.app.structuralProposals, placed];
    this.pendingPlacement = null; this.pendingPlacementOperationId = null; this.sceneCanvasSelection = operation.sceneId; this.activeSceneId = operation.sceneId;
    this.app.queueDraftSave?.(); this.pushHistory(); this.selectDraftTarget(placed.instanceId, { route: false }); this.syncUrl();
  }

  cancelPendingPlacement() {
    if (!this.pendingPlacementOperationId) return;
    this.pendingPlacement = null; this.pendingPlacementOperationId = null;
    this.render();
  }

  clearTransientInteractions() {
    const hadTransient = !!(this.pendingPlacementOperationId || this.drag);
    this.pendingPlacement = null; this.pendingPlacementOperationId = null; this.drag = null;
    return hadTransient;
  }

  proposalPositionValid(sceneId, definition, position, operation = null) {
    const meta = operation ? this.draftInstanceMetadata(operation, definition) : this.metadata(definition);
    return this.positionIssue(sceneId, meta, position);
  }

  setDraftInstancePosition(operationId, position) {
    const operation = this.app.structuralProposals.find(item => (item.operationId || item.proposalId) === operationId && item.kind === 'new-instance');
    if (!operation) return;
    if (!['free', 'nudge'].includes(operation.lock || 'free')) return this.app.notify?.('此草稿实例标记为固定，不能调整位置。');
    const definition = this.object(operation.definitionId), issue = this.proposalPositionValid(operation.sceneId, definition, position, operation);
    if (issue) return this.app.notify?.(issue);
    this.pushHistory(); operation.requestedPosition = position.map(value => Number(this.formatNumber(value)));
    this.app.queueDraftSave?.(); this.pushHistory(); this.render();
    this.selectDraftTarget(this.draftTargetId(operation), { route: false }); this.syncUrl();
    return true;
  }

  setDraftInstanceLock(operationId, requestedLock) {
    const operation = this.app.structuralProposals.find(item => (item.operationId || item.proposalId) === operationId && item.kind === 'new-instance' && Array.isArray(item.requestedPosition));
    if (!operation || !['fixed', 'nudge', 'free'].includes(requestedLock)) return this.app.notify?.('只能更新已放置的新实例，并选择有效编辑约束。');
    const currentLock = ['fixed', 'nudge', 'free'].includes(operation.lock) ? operation.lock : 'free';
    if (requestedLock === currentLock) return false;
    this.pushHistory(); operation.lock = requestedLock;
    this.app.queueDraftSave?.(); this.pushHistory(); this.render();
    this.app.notify?.(`已直接更新新实例提案的 ${this.lockLabel(requestedLock)} 约束；没有新增 set-lock 操作。`);
    return true;
  }

  deleteDraftInstance(operationId) {
    const operation = this.app.structuralProposals.find(item => (item.operationId || item.proposalId) === operationId && item.kind === 'new-instance' && Array.isArray(item.requestedPosition));
    if (!operation) return;
    this.pushHistory(); this.app.structuralProposals = this.app.structuralProposals.filter(item => (item.operationId || item.proposalId) !== operationId);
    this.removeSelectedDraftTarget(this.draftTargetId(operation), operation.sceneId);
    this.app.queueDraftSave?.(); this.pushHistory(); this.render();
  }

  renderPreview() {
    const root = $('#workbench-preview');
    if (!root) return;
    root.replaceChildren();
    const object = this.currentTarget();
    const previewSignature = JSON.stringify({ preview: this.metadata(object).preview, fields: this.app.fieldDraftValues || {} });
    if (this.playingTargetId && (object?.id !== this.playingTargetId || previewSignature !== this.playSignature)) this.stopPreview();
    const resolvedPreview = this.playingTargetId === object?.id && this.playPreviewData ? this.playPreviewData : this.resolvePreview(object);
    const preview = resolvedPreview.preview;
    const isResource = this.role(object) === 'resource';
    const stages = resolvedPreview.stages;
    root.append(el('div', 'workbench-preview-title', '对象预览能力'));
    if (!object) { root.append(el('p', 'muted', '项目级没有独立资源预览；场景和素材信息缺失时不使用虚构图片。')); return; }
    if (!preview && !isResource) { root.append(el('p', 'workbench-missing-source', '此对象未声明 preview 元数据。当前仅展示上方语义卡片和对象关系。')); return; }
    if (preview) root.append(el('p', 'muted', `${this.previewTypeLabel(preview.type)} · ${preview.label || '未提供预览标签'}`));
    else root.append(el('p', 'muted', '资源对象未声明 preview 元数据；仅尝试读取此对象当前版本绑定的真实图片。'));
    if (resolvedPreview.speedOwner && resolvedPreview.speedOwner.id !== object.id) root.append(el('p', 'muted', `速度按共享定义“${resolvedPreview.speedOwner.name || resolvedPreview.speedOwner.id}”的明确声明与当前草稿推导。`));
    if (resolvedPreview.speed != null) {
      const fieldLabel = resolvedPreview.speedField?.label || '速度';
      const unit = resolvedPreview.speedField?.unit ? ` ${resolvedPreview.speedField.unit}` : '';
      root.append(el('p', 'muted workbench-preview-speed', `${fieldLabel}：${resolvedPreview.speed}${unit}`));
    }
    if (preview?.imagePath) root.append(el('p', 'muted', `元数据提到路径 ${preview.imagePath}；这条信息本身不证明它是对象的现有游戏资源。`));
    const semanticMount = el('div', 'workbench-semantic-preview-mount');
    if (renderSemanticPreview(semanticMount, object, {
      metadata: this.metadata(object), objects: this.objects(), speed: resolvedPreview.speed,
      speedField: resolvedPreview.speedField, stages,
    })) root.append(semanticMount);
    if (preview?.type === 'image' || isResource) {
      const button = el('button', 'button secondary', '读取此对象绑定资源详情'); button.type = 'button'; button.dataset.workbenchAction = 'load-bound-preview'; button.dataset.objectId = object.id; root.append(button);
      const imageRoot = el('div', 'workbench-bound-image'); imageRoot.dataset.previewObjectId = object.id; root.append(imageRoot);
      const boundSource = this.sourceCache.get(object.id);
      const cached = this.previewCache.get(object.id);
      if (boundSource) this.renderBoundSourcePreview(imageRoot, object.id, boundSource);
      else if (cached?.state === 'loaded') this.showBoundPreview(object.id, imageRoot, cached.sourceCommit);
      else if (cached?.state === 'missing') imageRoot.append(el('p', 'muted', cached.reason || '当前发布版本没有绑定图片。'));
    }
    if (stages.length) {
      const timeline = el('ol', 'workbench-timeline');
      for (const [index, stage] of stages.entries()) { const hasDuration = stage.duration != null && stage.duration !== '' && Number.isFinite(Number(stage.duration)) && Number(stage.duration) >= 0; const time = hasDuration ? `${Number(stage.duration)} 秒` : '时长未提供'; const item = el('li', this.playingTargetId === object.id && index === this.playStageIndex ? 'active' : ''); item.append(el('b', '', stage.label || `阶段 ${index + 1}`), el('small', '', time)); timeline.append(item); }
      root.append(timeline);
      const controls = el('div', 'workbench-preview-controls');
      const hasUnknownDuration = stages.some(stage => stage.duration == null);
      const play = el('button', 'button secondary', this.playingTargetId === object.id ? '播放中' : '播放示意'); play.type = 'button'; play.dataset.workbenchAction = 'play-preview'; play.disabled = this.playingTargetId === object.id || hasUnknownDuration;
      const stop = el('button', 'button quiet', '停止'); stop.type = 'button'; stop.dataset.workbenchAction = 'stop-preview'; stop.disabled = this.playingTargetId !== object.id;
      controls.append(play, stop); root.append(controls, el('p', 'muted', '阶段轮播只用于浏览器理解，不能代表游戏引擎中的真实播放效果。'));
      if (hasUnknownDuration) root.append(el('p', 'muted', '有阶段时长尚未确认；确认有效字段值后才能播放示意。'));
    }
    root.append(el('p', 'muted', `数据来源：${this.provenanceLabel(this.metadata(object))}`));
  }

  previewNumber(value, minimum = 0) {
    if (value == null || value === '' || typeof value === 'boolean' || (typeof value !== 'number' && typeof value !== 'string')) return null;
    const number = Number(value);
    return Number.isFinite(number) && (minimum == null || number >= minimum) ? number : null;
  }

  resolvePreviewFieldValue(object, fieldId, fallback) {
    const field = this.objectField(object, fieldId);
    if (field && !['number', 'integer'].includes(field.type)) return { value: null, field };
    if (field && ['number', 'integer'].includes(field.type)) {
      const draftKey = `${object.id}.${fieldId}`;
      const draftValues = this.app.fieldDraftValues || {};
      if (['text', 'clarify'].includes(this.fieldDecision(object.id, fieldId))) return { value: null, field };
      const value = this.previewNumber(Object.hasOwn(draftValues, draftKey) ? draftValues[draftKey] : field.value);
      const valid = value != null && (field.type !== 'integer' || Number.isInteger(value))
        && (field.min == null || value >= field.min) && (field.max == null || value <= field.max);
      return { value: valid ? value : null, field };
    }
    return { value: this.previewNumber(fallback), field };
  }

  resolvePreview(object) {
    const preview = this.metadata(object).preview || null;
    if (!preview) return { preview: null, speed: null, speedField: null, stages: [] };
    const meta = this.sourceMetadata(object);
    const definition = meta.role === 'instance' ? this.objects().find(item => item.id === meta.definitionId) : null;
    const definitionMeta = this.sourceMetadata(definition);
    const definitionPreview = definitionMeta.role === 'definition' && definitionMeta.preview?.type === 'motion' ? definitionMeta.preview : null;
    const inheritSpeed = preview.type === 'motion' && definitionPreview && !Object.hasOwn(preview, 'speed') && !preview.speedFieldId;
    const speedOwner = inheritSpeed ? definition : object, speedPreview = inheritSpeed ? definitionPreview : preview;
    const speed = speedPreview.speedFieldId
      ? this.resolvePreviewFieldValue(speedOwner, speedPreview.speedFieldId, speedPreview.speed)
      : { value: this.previewNumber(speedPreview.speed), field: null };
    const inheritStages = preview.type === 'motion' && definitionPreview && !preview.stages?.length;
    const stageOwner = inheritStages ? definition : object, stagePreview = inheritStages ? definitionPreview : preview;
    const stages = Array.isArray(stagePreview.stages) ? stagePreview.stages.map(stage => ({
      ...stage,
      duration: stage.durationFieldId
        ? this.resolvePreviewFieldValue(stageOwner, stage.durationFieldId, stage.duration).value
        : this.previewNumber(stage.duration),
    })) : [];
    return { preview, speed: speed.value, speedField: speed.field, speedOwner, stages };
  }

  previewTypeLabel(type) { return ({ semantic: '语义预览', image: '图片资源', motion: '连续运动', action: '离散动作', response: '被动响应', interaction: '交互', rule: '规则', spawn: '生成', transition: '场景过渡' })[type] || `未识别类型 ${type || ''}`; }
  async loadBoundPreview(objectId) {
    const root = [...document.querySelectorAll('[data-preview-object-id]')].find(node => node.dataset.previewObjectId === objectId);
    if (!root) return;
    const cached = this.sourceCache.get(objectId);
    if (cached) {
      root.replaceChildren();
      return this.renderBoundSourcePreview(root, objectId, cached);
    }
    root.replaceChildren(el('p', 'muted', '正在读取当前发布版本中绑定资源的描述和首帧…'));
    const projectId = this.app.projectId;
    const context = this.sourceContextKey();
    const expectedSourceCommit = this.app.snapshot?.sourceCommit || this.app.snapshot?.baseCommit || null;
    try {
      const response = await this.app.request(`/projects/${encodeURIComponent(projectId)}/objects/${encodeURIComponent(objectId)}/source`, { projectId: null });
      if (!root.isConnected || this.sourceContextKey() !== context) return;
      if (this.app.projectId !== projectId || response.projectId !== projectId || response.objectId !== objectId || response.kind !== 'static_source') throw new Error('来源响应身份与目标不匹配。');
      if (expectedSourceCommit && response.sourceCommit !== expectedSourceCommit) throw new Error('来源响应的 Git 版本与当前发布快照不匹配。');
      this.sourceCache.set(objectId, response);
      root.replaceChildren();
      this.renderBoundSourcePreview(root, objectId, response);
    } catch (error) {
      if (!root.isConnected || this.sourceContextKey() !== context) return;
      root.replaceChildren(el('p', 'muted danger-text', `绑定资源描述读取失败：${error.message}`));
    }
  }

  showBoundPreview(objectId, root, sourceCommit, existingImage = null) {
    if (!root) return;
    const context = this.sourceContextKey();
    const image = existingImage || el('img', 'workbench-resource-image'); image.alt = `${this.object(objectId)?.name || objectId} · 当前发布版本绑定资源`; image.loading = 'lazy'; if (!existingImage) image.src = `/api/projects/${encodeURIComponent(this.app.projectId)}/objects/${encodeURIComponent(objectId)}/preview`;
    const note = el('p', 'muted', `实际对象资源 · 发布版本 ${sourceCommit || '未提供'}`); root.replaceChildren(image, note);
    image.addEventListener('error', () => {
      if (!image.isConnected || this.sourceContextKey() !== context) return;
      this.previewCache.set(objectId, { state: 'missing', reason: '绑定资源读取失败，当前显示语义预览。' });
      root.replaceChildren(el('p', 'muted', '绑定资源读取失败，当前显示语义预览。'));
    });
  }

  playPreview() {
    const object = this.currentTarget(), resolvedPreview = this.resolvePreview(object), stages = resolvedPreview.stages;
    if (!object || !Array.isArray(stages) || !stages.length || stages.some(stage => stage.duration == null)) return;
    this.stopPreview(); this.playingTargetId = object.id; this.playStageIndex = 0; this.playPreviewData = resolvedPreview; this.playSignature = JSON.stringify({ preview: this.metadata(object).preview, fields: this.app.fieldDraftValues || {} }); this.renderPreview();
    const delayFor = stage => { const duration = stage?.duration; return duration != null && Number.isFinite(duration) && duration >= 0 ? Math.min(2147483647, duration * 1000) : 1000; };
    const tick = () => {
      if (this.playingTargetId !== object.id) return;
      if (this.playStageIndex + 1 >= stages.length) { this.stopPreview(); this.renderPreview(); return; }
      this.playStageIndex += 1; this.renderPreview();
      if (this.playingTargetId !== object.id) return;
      this.playTimer = globalThis.setTimeout(tick, delayFor(stages[this.playStageIndex]));
    };
    this.playTimer = globalThis.setTimeout(tick, delayFor(stages[0]));
  }
  stopPreview() {
    if (this.playTimer != null) globalThis.clearTimeout(this.playTimer);
    this.playTimer = null; this.playingTargetId = null; this.playStageIndex = 0; this.playPreviewData = null; this.playSignature = null;
  }

  renderResults() {
    const section = $('#workbench-results'), root = $('#workbench-results-list');
    if (!section || !root) return;
    const results = this.workbenchResults();
    hide(section, !results.length);
    const groups = this.groupWorkbenchResults(results), currentGroup = this.currentWorkbenchResultGroup(groups);
    const signature = JSON.stringify([this.sourceContextKey(), currentGroup?.key || null, results]);
    if (this.resultRenderSignature === signature && (!results.length || root.childElementCount)) return;
    for (const node of root.querySelectorAll('[data-result-group]')) this.resultGroupExpanded.set(node.dataset.resultGroup, node.open);
    for (const node of root.querySelectorAll('[data-result-detail-key]')) this.resultDetailsExpanded.set(node.dataset.resultDetailKey, node.open);
    this.resultRenderSignature = signature;
    root.replaceChildren();
    if (!results.length) return;
    root.classList.add('workbench-result-groups');
    root.append(el('p', 'muted workbench-result-hint', '以下是服务当前返回的逐项结果，按提案修订及已提供的作业 / 候选身份分组；这份投影不一定包含完整重试历史。'));
    const orderedGroups = currentGroup ? [currentGroup, ...groups.filter(group => group !== currentGroup)] : groups;
    for (const group of orderedGroups) {
      const current = group.key === currentGroup?.key;
      const counts = this.resultGroupCounts(group.results);
      const node = el('details', `workbench-result-group${current ? ' workbench-result-group-current' : ''}`);
      node.dataset.resultGroup = group.key;
      node.open = this.resultGroupExpanded.has(group.key) ? this.resultGroupExpanded.get(group.key) : current;
      const targets = [...new Set(group.results.map(result => result.objectId ? this.object(result.objectId)?.name || result.objectId : '项目'))];
      const targetSummary = targets.slice(0, 2).join('、') + (targets.length > 2 ? '等' : '');
      const summary = el('summary', '', `${current ? '当前上下文' : '历史 / 其他记录'} · 修订 ${group.proposalRevision ?? '未提供'} · ${targetSummary} · ${group.results.length} 项 · 失败 ${counts.failed} · 待处理 ${counts.pending}`);
      node.append(summary);
      const identity = el('p', 'muted workbench-result-identity', this.resultGroupIdentityLabel(group));
      node.append(identity);
      if (!group.identityComplete) node.append(el('p', 'workbench-result-hint', '服务未提供完整的提案修订或作业 / 候选身份；保留每项原有状态，不据此推断它属于哪次重试。'));
      for (const result of group.results) node.append(this.renderResultCard(result));
      node.addEventListener('toggle', () => {
        if (node.isConnected) this.resultGroupExpanded.set(group.key, node.open);
      });
      root.append(node);
    }
  }

  groupWorkbenchResults(results) {
    const groups = new Map();
    for (const result of results) {
      const proposalId = result.proposalId || null, proposalRevision = result.proposalRevision ?? null;
      const jobId = result.jobId || null, candidateId = result.candidateId || null;
      const hasAttemptIdentity = !!(jobId || candidateId);
      const identityComplete = !!proposalId && proposalRevision != null && hasAttemptIdentity;
      const itemIdentity = result.itemId || [result.kind, result.objectId, result.fieldId, result.feedbackId, result.operationId].filter(Boolean).join(':') || 'item-identity-unavailable';
      const grouping = [proposalId, proposalRevision, jobId, candidateId];
      if (!proposalId || proposalRevision == null) grouping.push(itemIdentity);
      const key = JSON.stringify(grouping);
      if (!groups.has(key)) groups.set(key, { key, proposalId, proposalRevision, jobId, candidateId, identityComplete, results: [] });
      groups.get(key).results.push(result);
    }
    return [...groups.values()];
  }

  resultGroupIdentityLabel(group) {
    return `提案 ${group.proposalId || '身份未提供'} · 修订 ${group.proposalRevision ?? '身份未提供'} · 作业 ${group.jobId || '身份未提供'} · 候选 ${group.candidateId || '身份未提供'}`;
  }

  resultGroupCounts(results) {
    const failedStatuses = new Set(['fail', 'failed', 'failure', 'error']);
    const pendingStatuses = new Set(['pending', 'queued', 'dispatching', 'running', 'planning', 'verifying', 'projecting', 'uncertain', 'blocked', 'ready_for_review', 'accepted', 'received', 'requires_item_review', 'not_performed']);
    let failed = 0, pending = 0;
    for (const result of results) {
      const values = [result.status, result.workflowStatus, typeof result.technicalVerification === 'object'
        ? result.technicalVerification?.status || result.technicalVerification?.result : result.technicalVerification]
        .filter(value => value != null && value !== '').map(value => String(value).toLowerCase().replaceAll('-', '_').replaceAll(' ', '_'));
      if (values.some(value => failedStatuses.has(value))) failed += 1;
      else if (values.some(value => pendingStatuses.has(value)) || this.statusValue(result.userAcceptance).toUpperCase() === 'NOT_PERFORMED'
        || String(result.versionDecision || '').toLowerCase() === 'pending') pending += 1;
    }
    return { failed, pending };
  }

  currentWorkbenchResultGroup(groups) {
    const projectId = this.app.projectId;
    const matchesAttempt = job => {
      if (!job || job.projectId && job.projectId !== projectId) return null;
      const candidateId = job.candidateId || job.candidate?.id || job.response?.candidate?.id || null;
      const matches = groups.filter(group => (group.jobId && group.jobId === job.id) || (candidateId && group.candidateId === candidateId));
      const exactCandidate = candidateId ? matches.filter(group => group.candidateId === candidateId) : [];
      if (exactCandidate.length === 1) return exactCandidate[0];
      return matches.length === 1 ? matches[0] : null;
    };
    const selectedJobId = this.app.selectedJobForProject?.(projectId);
    if (selectedJobId) {
      const selected = matchesAttempt([this.app.job, ...(this.app.workspace?.jobs || [])].find(job => job?.id === selectedJobId && job.projectId === projectId));
      if (selected) return selected;
    }
    const proposal = this.app.proposal?.projectId === projectId ? this.app.proposal : null;
    const currentJob = [this.app.projectView?.job, this.app.job].find(job => job?.projectId === projectId
      && (!this.app.isHistoricalJob || this.app.isHistoricalJob(job) === false));
    const attemptGroup = matchesAttempt(currentJob);
    if (attemptGroup && (!proposal || attemptGroup.proposalId === proposal.id && Number(attemptGroup.proposalRevision) === Number(proposal.revision))) return attemptGroup;
    if (!proposal) return null;
    const proposalGroups = groups.filter(group => group.proposalId === proposal.id && Number(group.proposalRevision) === Number(proposal.revision));
    return proposalGroups.length === 1 ? proposalGroups[0] : null;
  }

  renderResultCard(result) {
    const card = el('article', 'workbench-result-card');
    const target = result.objectId ? this.object(result.objectId) : null;
    card.append(el('div', 'workbench-result-title', `${this.kindLabel(result.kind)} · ${target?.name || result.objectId || '项目'} · ${this.workflowLabel(result.workflowStatus)}`));
    const shortText = (value, limit = 160) => {
      const text = String(value ?? '').replace(/\s+/g, ' ').trim();
      return text.length > limit ? `${text.slice(0, limit)}…` : text;
    };
    const original = String(result.originalText || '').trim();
    let requestSummary = original && !/^(?:\{|\[)/.test(original) ? shortText(original) : '';
    if (result.kind === 'field') {
      const fieldLabel = target?.fields?.find(field => field.id === result.fieldId)?.label || result.fieldId || '属性';
      requestSummary = `${fieldLabel}：${shortText(this.displayValue(result.before), 50)} → ${shortText(this.displayValue(result.requested), 70)}（本轮期望）`;
    } else if (!requestSummary) {
      requestSummary = typeof result.requested === 'string' ? shortText(result.requested)
        : result.requested?.kind ? this.operationLabel(result.requested) : `${this.kindLabel(result.kind)}调整；完整内容可展开查看。`;
    }
    card.append(el('p', 'workbench-result-summary', `需求摘要：${requestSummary}`));
    const factStatus = value => this.statusValue(value && typeof value === 'object' ? value.status || value.result : value);
    card.append(el('p', 'workbench-result-fact-label', `技术验证：${factStatus(result.technicalVerification)} · 用户认可：${factStatus(result.userAcceptance)}`));
    if (result.experienceDecision?.reason) card.append(el('p', 'visual-raw', `体验决定理由：${result.experienceDecision.reason}`));
    if (result.planDecision) {
      const decision = result.planDecision;
      const status = typeof decision === 'object' ? this.planDecisionStatus(decision.status || decision.result) : this.displayValue(decision);
      card.append(el('p', '', `处理决定：${shortText(status)}${decision.reason ? ` · ${shortText(decision.reason)}` : ''}`));
    }
    if (result.versionDecision != null) card.append(el('p', 'workbench-result-version', `候选版本决定：${this.versionDecisionLabel(result.versionDecision)}；整版决定不代表此项需求已获认可。`));
    if (result.kind === 'field') card.append(el('p', '', `候选配置：${result.actual !== undefined ? shortText(this.displayValue(result.actual), 90) : '尚未制作或候选未提供此值'}`));
    if (result.documentValueMatches === true) card.append(el('p', 'workbench-result-fact', '项目对象文档值与申报值一致；此项只说明文档值匹配。'));
    else if (result.documentValueMatches === false) card.append(el('p', 'workbench-result-pending', '项目对象文档值与申报值不一致或尚未映射。'));
    if (result.reason) card.append(el('p', 'workbench-result-pending', `原因 / 说明：${shortText(result.reason, 220)}`));
    const failed = this.resultGroupCounts([result]).failed > 0;
    const next = failed ? '先查看本轮处理状态与原因，再决定如何继续。'
      : result.candidateId ? '查看对应候选，并逐项检查要求。'
        : result.jobId ? '查看本轮处理状态；目前未提供候选。' : '等待处理；可回到目标继续准备意见。';
    card.append(el('p', 'workbench-result-next', `下一步：${next}`));
    const actions = el('div', 'workbench-result-actions');
    if (result.objectId && target) { const locate = el('button', 'button secondary', '回到原对象继续调整'); locate.type = 'button'; locate.dataset.workbenchAction = 'locate-target'; locate.dataset.targetId = result.objectId; actions.append(locate); }
    else if (result.objectId) {
      const identity = el('details', 'workbench-item-identity');
      identity.append(el('summary', '', '原目标暂未出现在公开对象列表中'), el('code', '', result.objectId));
      actions.append(identity, el('span', 'muted', '意见保留待关联。'));
    }
    if (result.jobId) {
      const view = el('button', 'button secondary', result.candidateId ? '查看此候选与试玩入口' : '查看本轮处理状态'); view.type = 'button';
      view.addEventListener('click', () => this.app.selectJob?.(result.jobId)); actions.append(view);
    }
    card.append(actions);
    const raw = el('details', 'workbench-result-raw');
    raw.append(el('summary', '', '查看原文与完整配置'));
    if (result.originalText) raw.append(el('p', 'workbench-result-raw-text', `用户原文：${result.originalText}`));
    const valueRow = (label, value) => {
      if (value === undefined) return;
      raw.append(el('b', '', label), el(typeof value === 'object' && value !== null ? 'pre' : 'p', 'object-diff', typeof value === 'object' && value !== null ? JSON.stringify(value, null, 2) : this.displayValue(value)));
    };
    valueRow('配置前', result.before); valueRow('本轮期望（意图）', result.requested); valueRow('候选记录的配置', result.actual);
    if (result.planDecision) this.renderPlanDecision(result.planDecision, raw);
    if (result.reason) raw.append(el('p', '', `完整原因 / 说明：${result.reason}`));
    raw.append(el('p', '', `技术验证：${this.statusValue(result.technicalVerification)} · 用户认可：${this.statusValue(result.userAcceptance)}`));
    raw.append(el('p', 'muted', '配置值匹配和自动化检查不能证明运行体验符合原要求；仍需实际试玩并逐项判断。'));
    card.append(raw);
    this.renderResultEvidence(result, card);
    if (result.changedSourcePaths?.length) {
      const paths = el('details', 'workbench-result-paths'); paths.append(el('summary', '', '查看源码变化路径'));
      for (const path of result.changedSourcePaths) paths.append(el('p', '', path));
      card.append(paths);
    }
    this.renderSourceDiff(result, card);
    const identity = el('details', 'workbench-item-identity');
    identity.append(el('summary', '', '查看提案修订、作业与候选身份'));
    identity.append(el('p', '', `提案 ID：${result.proposalId || '身份未提供'} · 修订：${result.proposalRevision ?? '身份未提供'}`));
    identity.append(el('p', '', `作业 ID：${result.jobId || '身份未提供'} · 候选 ID：${result.candidateId || '身份未提供'}`));
    card.append(identity);
    const itemKey = JSON.stringify([this.app.projectId, result.proposalId, result.proposalRevision, result.jobId, result.candidateId,
      result.itemId || [result.kind, result.objectId, result.fieldId, result.feedbackId, result.operationId]]);
    for (const [index, details] of [...card.querySelectorAll('details')].entries()) {
      const key = `${itemKey}:${details.className || index}`;
      details.dataset.resultDetailKey = key;
      details.open = this.resultDetailsExpanded.get(key) === true;
      details.addEventListener('toggle', () => { if (details.isConnected) this.resultDetailsExpanded.set(key, details.open); });
    }
    return card;
  }

  workbenchResults() { return Array.isArray(this.app.workbenchResults) ? this.app.workbenchResults : Array.isArray(this.app.projectView?.workbenchResults) ? this.app.projectView.workbenchResults : []; }
  workflowLabel(status) { const key = String(status || 'pending').toLowerCase(); return ({ ...WORKFLOW_LABELS, published: '已接受版本' })[key] || status || '状态未提供'; }
  statusValue(status) { if (status == null || status === '') return '未提供'; if (typeof status === 'object') return `${this.statusValue(status.status || status.result)}${status.reason ? ` · ${status.reason}` : ''}`; return ({ resolved: '已解决', needs_followup: '后续跟进', accepted: '已认可', NOT_PERFORMED: '未进行' })[String(status)] || String(status); }
  planDecisionStatus(status) { return ({ adopted: '已纳入计划', needs_clarification: '需要澄清', deferred: '暂缓处理', rejected: '未采纳' })[String(status || '').toLowerCase()] || this.statusValue(status); }
  renderPlanDecision(decision, card) {
    if (typeof decision !== 'object' || decision == null) { card.append(el('p', '', `处理决定：${this.displayValue(decision)}`)); return; }
    const status = this.planDecisionStatus(decision.status || decision.result);
    const reason = String(decision.reason || '').trim();
    card.append(el('p', '', `处理决定：${status}${reason ? `：${reason}` : ''}`));
    const taskIds = Array.isArray(decision.taskIds) ? decision.taskIds : [];
    const requirementIds = Array.isArray(decision.requirementIds) ? decision.requirementIds : [];
    if (!taskIds.length && !requirementIds.length) return;
    const details = el('details', 'workbench-result-decision-links');
    details.append(el('summary', '', `查看关联计划 ID${taskIds.length ? ` · ${taskIds.length} 项任务` : ''}${requirementIds.length ? ` · ${requirementIds.length} 项验收要求` : ''}`));
    if (taskIds.length) details.append(el('p', 'muted', `任务：${taskIds.join('、')}`));
    if (requirementIds.length) details.append(el('p', 'muted', `验收要求：${requirementIds.join('、')}`));
    card.append(details);
  }
  versionDecisionLabel(decision) { return ({ published: '已接受为当前版本', rejected: '未接受（候选已拒绝）', pending: '尚未决定' })[String(decision).toLowerCase()] || this.displayValue(decision); }
  evidenceItemText(item) {
    if (typeof item === 'string') return item;
    if (!item || typeof item !== 'object') return this.displayValue(item);
    const description = item.description || item.requirement || item.title || item.label || item.name || item.id || item.taskId || JSON.stringify(item);
    const status = item.status || item.result;
    return `${description}${status ? ` · ${this.statusValue(status)}` : ''}${item.message ? `：${item.message}` : ''}`;
  }
  renderResultEvidence(result, card) {
    const tasks = Array.isArray(result.linkedTasks) ? result.linkedTasks : [];
    const requirements = Array.isArray(result.verificationRequirements) ? result.verificationRequirements : [];
    if (!tasks.length && !requirements.length) return;
    const details = el('details', 'workbench-result-evidence');
    details.append(el('summary', '', `任务与技术证据${tasks.length ? ` · ${tasks.length} 项任务` : ''}${requirements.length ? ` · ${requirements.length} 项验证要求` : ''}`));
    if (tasks.length) {
      details.append(el('h4', '', '关联任务'));
      const list = el('ul');
      for (const task of tasks) list.append(el('li', '', this.evidenceItemText(task)));
      details.append(list);
    }
    if (requirements.length) {
      details.append(el('h4', '', '验证要求'));
      const list = el('ul');
      for (const requirement of requirements) list.append(el('li', '', this.evidenceItemText(requirement)));
      details.append(list);
    }
    card.append(details);
  }
  renderSourceDiff(result, card) {
    if (!result.jobId || !result.sourceCommit) return;
    const details = el('details', 'workbench-result-source-diff');
    details.append(el('summary', '', '查看本轮源码差异'));
    const content = el('div', 'workbench-source-diff-content');
    details.append(content);
    let loaded = false;
    details.addEventListener('toggle', () => {
      if (!details.open || loaded) return;
      loaded = true;
      this.loadResultSourceDiff(result, content).catch(error => {
        loaded = false;
        content.replaceChildren(el('p', 'muted danger-text', `源码差异读取失败：${error.message}`));
      });
    });
    card.append(details);
  }
  async loadResultSourceDiff(result, root) {
    root.replaceChildren(el('p', 'muted', '正在读取此轮候选的精确 Git 源码差异…'));
    const projectId = this.app.projectId;
    const response = await this.app.request(`/projects/${encodeURIComponent(projectId)}/jobs/${encodeURIComponent(result.jobId)}/source-changes`, { projectId: null });
    if (this.app.projectId !== projectId || response.projectId !== projectId || response.jobId !== result.jobId || response.candidateId !== result.candidateId || response.kind !== 'retained_git_diff' || response.sourceCommit !== result.sourceCommit || !Array.isArray(response.changes)) {
      throw new Error('源码差异与当前项目或候选 Git 版本不匹配。');
    }
    root.replaceChildren();
    if (response.baseCommit || response.sourceCommit) root.append(el('p', 'muted', `Git ${response.baseKind === 'production_input' ? '制作输入' : '基线'} ${response.baseCommit || '未提供'} → 候选 ${response.sourceCommit || '未提供'}${response.truncated ? ' · 差异输出已截断' : ''}`));
    const relevantPaths = new Set(Array.isArray(result.changedSourcePaths) ? result.changedSourcePaths : []);
    const relevant = relevantPaths.size ? response.changes.filter(change => relevantPaths.has(change.path)) : [];
    const displayed = relevant.length ? relevant : response.changes;
    if (relevantPaths.size && !relevant.length) root.append(el('p', 'muted', '申报对象的绑定路径没有与返回差异匹配；以下显示本轮可用的全部路径。'));
    if (!displayed.length) root.append(el('p', 'muted', '此候选没有可读取的源码差异。'));
    for (const change of displayed) {
      const article = el('article', 'workbench-source-diff-file');
      article.append(el('h4', '', change.path || '未命名文件'));
      if (typeof change.diff === 'string' && change.diff) article.append(el('pre', '', change.diff));
      else article.append(el('p', 'muted', '此路径没有返回可显示的差异文本。'));
      if (change.truncated) article.append(el('p', 'muted', '此文件差异已截断。'));
      root.append(article);
    }
  }
  kindLabel(kind) { return ({ field: '属性修改', feedback: '自然语言意见', operation: '结构操作' })[kind] || kind || '工作项'; }

  renderOperationList() {
    const section = $('#workbench-draft-operations'), root = $('#workbench-draft-operations-list');
    if (!section || !root) return;
    root.replaceChildren(); hide(section, !this.app.structuralProposals.length);
    if (!this.app.structuralProposals.length) return;
    for (const item of this.app.structuralProposals) {
      const row = el('div', 'workbench-operation-row'); row.append(el('span', '', this.operationLabel(item)));
      const remove = el('button', 'button quiet', '移除'); remove.type = 'button'; remove.dataset.workbenchAction = 'remove-operation'; remove.dataset.operationId = item.operationId || item.proposalId; row.append(remove); root.append(row);
    }
  }

  switchScene(sceneId) {
    if (!sceneId || !this.scenes().some(scene => scene.id === sceneId)) return;
    this.activeSceneId = sceneId; this.sceneCanvasSelection = sceneId;
    const sceneObject = this.object(sceneId);
    if (sceneObject && this.role(sceneObject) === 'scene' && this.app.selectedObjectId !== sceneId) {
      if (this.isDraftTarget(sceneId)) this.selectDraftTarget(sceneId, { route: false });
      else this.app.selectObject(sceneId);
    }
    else if (!sceneObject && this.app.selectedObjectId) { this.selectProject({ route: false }); this.sceneCanvasSelection = sceneId; }
    this.render(); this.syncUrl();
  }

  removeSelectedDraftTarget(targetId, fallbackSceneId = null) {
    if (this.app.selectedObjectId !== targetId) return;
    const fallback = fallbackSceneId && this.object(fallbackSceneId);
    if (fallback && this.role(fallback) === 'scene') {
      if (this.isDraftTarget(fallbackSceneId)) this.selectDraftTarget(fallbackSceneId, { route: false });
      else this.app.selectObject(fallbackSceneId);
    } else this.selectProject({ route: false });
  }

  operationLabel(item) {
    if (item.kind === 'move') return `移动提案 · ${this.object(item.objectId)?.name || item.objectId}：${this.displayValue(item.before)} → ${this.displayValue(item.requested)} · ${item.lock}`;
    if (item.kind === 'set-lock') return `编辑约束提案 · ${this.object(item.objectId)?.name || item.objectId}：${this.lockLabel(item.before)} → ${this.lockLabel(item.lock)} · 用户显式修改约束`;
    if (item.kind === 'new-scene') return `新场景提案 · ${item.name || '未命名'} · ${item.sceneId || this.draftTargetId(item) || '待分配 ID'} · ${this.sceneTemplateLabel(item.template)}`;
    if (item.kind === 'new-instance') return `新实例提案 · ${item.name || '未命名'} · ${item.instanceId || this.draftTargetId(item) || '待分配 ID'} · 定义 ${item.definitionId || '未提供'} · 场景 ${item.sceneId || '未提供'} · ${this.lockLabel(item.lock || 'free')}`;
    if (item.kind === 'delete-instance') return `移除实例提案 · ${this.object(item.objectId)?.name || item.objectId}`;
    if (item.kind === 'transition') {
      const target = item.objectId ? this.object(item.objectId) : null;
      const before = target ? this.transitionMetadataValues(this.metadata(target)) : { from: '', sceneId: '', entryId: '', condition: '', mode: '未设置', presetId: '' };
      const after = this.transitionOperationValues(item, before);
      return `过渡提案 · ${this.transitionSnapshotLabel(before)} → ${this.transitionSnapshotLabel(after)}`;
    }
    return `${item.kind || '结构提案'} · ${item.objectId || item.name || item.operationId || item.proposalId}`;
  }

  sceneTemplateLabel(value) {
    if (value == null || String(value).trim() === '') return '未提供';
    const template = String(value).trim();
    return SCENE_TEMPLATE_OPTIONS.find(option => option.value === template)?.label || `未知起始结构（${template}）`;
  }

  openProposal(kind) {
    const dialog = $('#workbench-proposal-dialog'), fields = $('#workbench-proposal-fields');
    if (!dialog || !fields) return;
    if (this.pendingPlacementOperationId) return this.app.notify?.('请先完成或取消当前实例放置。');
    const current = this.currentTarget(), transitionTarget = kind === 'transition' && this.role(current) === 'transition' ? current : null;
    const transitionMeta = this.metadata(transitionTarget);
    const transitionBaseline = this.transitionMetadataValues(transitionMeta);
    const existingTransitionOperation = transitionTarget
      ? this.app.structuralProposals.find(item => item.kind === 'transition' && item.objectId === transitionTarget.id)
      : null;
    const transitionValues = this.transitionOperationValues(existingTransitionOperation || {}, transitionBaseline);
    this.pendingProposalType = kind; this.pendingProposalObjectId = transitionTarget?.id || null; fields.replaceChildren();
    const input = (label, name, value = '', placeholder = '', type = 'text') => { const wrapper = el('label', 'workbench-proposal-field'); wrapper.append(el('span', '', label)); const control = el('input'); control.type = type; control.name = name; control.value = value; control.placeholder = placeholder; wrapper.append(control); fields.append(wrapper); return control; };
    if (kind === 'new-scene') {
      input('场景名称', 'name', '', '例如：大厅');
      const wrapper = el('label', 'workbench-proposal-field'); wrapper.append(el('span', '', '起始结构')); const select = el('select'); select.name = 'template';
      for (const option of SCENE_TEMPLATE_OPTIONS) select.append(new Option(option.label, option.value));
      wrapper.append(select); fields.append(wrapper);
      input('世界宽度（可选）', 'worldWidth', '', '只填已确认的场景尺寸', 'number');
      input('世界高度（可选）', 'worldHeight', '', '只填已确认的场景尺寸', 'number');
      input('出入口或连接说明（可选）', 'connections', '', '描述从哪里进入或离开');
    } else if (kind === 'new-instance') {
      input('实例名称', 'name', '', '名称');
      const definitions = this.objects().filter(object => this.role(object) === 'definition');
      const selectedDefinitionId = this.role(current) === 'definition' ? current.id : this.metadata(current).definitionId;
      const definition = el('label', 'workbench-proposal-field'); definition.append(el('span', '', '共享定义')); const select = el('select'); select.name = 'definitionId'; select.append(new Option(definitions.length ? '选择定义' : '当前未映射定义', '')); for (const object of definitions) select.append(new Option(`${object.name || object.id} · ${object.id}`, object.id)); select.value = definitions.some(object => object.id === selectedDefinitionId) ? selectedDefinitionId : ''; definition.append(select); fields.append(definition);
      const scenes = this.scenes(); const scene = el('label', 'workbench-proposal-field'); scene.append(el('span', '', '所属场景')); const sceneSelect = el('select'); sceneSelect.name = 'sceneId'; sceneSelect.append(new Option(scenes.length ? '选择场景' : '当前未映射场景', '')); for (const item of scenes) sceneSelect.append(new Option(`${item.name || item.id} · ${item.id}${this.sceneBounds(item.id) ? '' : ' · 无世界边界'}`, item.id)); sceneSelect.value = this.activeSceneId || ''; scene.append(sceneSelect); fields.append(scene);
      const extras = el('details', 'workbench-proposal-options'); extras.append(el('summary', '', '其他选项'));
      const lock = el('label', 'workbench-proposal-field'); lock.append(el('span', '', '实例锁定模式')); const lockSelect = el('select'); lockSelect.name = 'lock';
      lockSelect.append(new Option('自由 · 可拖动调整位置', 'free'), new Option('可微调 · 使用方向按钮', 'nudge'), new Option('固定 · 不可移动或删除', 'fixed')); lockSelect.value = 'free'; lock.append(lockSelect); extras.append(lock);
      const description = el('label', 'workbench-proposal-field'); description.append(el('span', '', '实例意图（可选）')); const descriptionInput = el('input'); descriptionInput.name = 'description'; descriptionInput.placeholder = '例如：入口附近的守卫'; description.append(descriptionInput); extras.append(description);
      fields.append(extras);
    } else {
      input('来源场景或出口', 'from', transitionValues.from, '场景或出口对象 ID');
      const scene = el('label', 'workbench-proposal-field'); scene.append(el('span', '', '目标场景')); const select = el('select'); select.name = 'sceneId'; select.append(new Option('未设置 / 待补充', '')); for (const item of this.objects().filter(object => object.kind === 'scene')) select.append(new Option(`${item.name || item.id} · ${item.id}`, item.id)); select.value = transitionValues.sceneId; scene.append(select); fields.append(scene);
      const entry = el('label', 'workbench-proposal-field'); entry.append(el('span', '', '目标入口')); const entrySelect = el('select'); entrySelect.name = 'entryId'; entrySelect.dataset.referenceValue = transitionValues.entryId; entry.append(entrySelect); fields.append(entry);
      const entryWarning = el('p', 'muted danger-text workbench-transition-entry-warning'); hide(entryWarning); fields.append(entryWarning);
      const updateEntries = () => this.updateTransitionEntrySelector(select, entrySelect, entryWarning);
      select.addEventListener('change', updateEntries);
      entrySelect.addEventListener('change', () => { entrySelect.dataset.referenceValue = entrySelect.value; updateEntries(); });
      updateEntries();
      input('通行条件', 'condition', transitionValues.condition, '例如：钥匙已取得');
      const mode = el('label', 'workbench-proposal-field'); mode.append(el('span', '', '过渡模式')); const modeSelect = el('select'); modeSelect.name = 'mode'; for (const value of ['未设置', '无过渡', '共享预设']) modeSelect.append(new Option(value, value));
      modeSelect.value = transitionValues.mode;
      mode.append(modeSelect); fields.append(mode);
      const presets = this.objects().filter(object => this.role(object) === 'preset' && this.isTransitionPreset(object.id));
      const preset = el('label', 'workbench-proposal-field'); preset.append(el('span', '', '过渡预设')); const presetSelect = el('select'); presetSelect.name = 'presetId'; presetSelect.append(new Option('无预设 / 未映射', '')); for (const item of presets) presetSelect.append(new Option(`${item.name || item.id} · ${item.id}`, item.id)); presetSelect.value = transitionValues.presetId; preset.append(presetSelect); fields.append(preset);
    }
    this.showWorkbenchDialog(dialog);
  }

  addProposalFromForm() {
    const form = $('#workbench-proposal-form'); if (!form || !this.pendingProposalType) return;
    const data = Object.fromEntries(new FormData(form).entries());
    const kind = this.pendingProposalType;
    const operationId = this.app.newFeedbackId();
    if (kind === 'transition' && form.querySelector('[name="entryId"]')?.selectedOptions?.[0]?.dataset.invalidReference === 'true') {
      return this.app.notify?.('当前目标入口引用无效；请选择目标场景内的合法入口，或清除入口后再申报。');
    }
    if (kind === 'new-scene' && !data.name.trim()) return this.app.notify?.('请为新场景提案填写名称。');
    if (kind === 'new-instance' && !data.name.trim()) return this.app.notify?.('请为新实例提案填写名称。');
    if (kind === 'new-instance' && (!data.definitionId || !this.object(data.definitionId) || this.role(this.object(data.definitionId)) !== 'definition')) return this.app.notify?.('请选择当前公开目录中的共享定义。');
    if (kind === 'new-instance' && (!data.sceneId || !this.sceneBounds(data.sceneId))) return this.app.notify?.('请选择已提供世界边界的场景；实例自身 bounds 不作为场景边界。');
    const cleanData = Object.fromEntries(Object.entries(data).filter(([key]) => !['worldWidth', 'worldHeight'].includes(key)).map(([key, value]) => [key, typeof value === 'string' ? value.trim() : value]));
    if (kind === 'new-instance' && !['fixed', 'nudge', 'free'].includes(cleanData.lock)) cleanData.lock = 'free';
    const operation = { operationId, kind, ...cleanData, scope: kind === 'new-scene' ? '新场景' : kind === 'new-instance' ? '新实例' : '单向场景过渡', createdAt: new Date().toISOString() };
    if (kind === 'transition' && this.pendingProposalObjectId && this.role(this.object(this.pendingProposalObjectId)) === 'transition') operation.objectId = this.pendingProposalObjectId;
    if (kind === 'new-scene') {
      const width = data.worldWidth === '' ? null : Number(data.worldWidth), height = data.worldHeight === '' ? null : Number(data.worldHeight);
      if ((width == null) !== (height == null) || width != null && (!(width > 0) || !(height > 0) || !Number.isFinite(width) || !Number.isFinite(height))) return this.app.notify?.('世界宽度和高度需同时填写为有效正数；留空时不会推测边界。');
      operation.sceneId = `draft-scene-${operationId}`;
      if (width != null) operation.bounds = [width, height];
    }
    if (kind === 'transition') {
      if (!operation.sceneId && !operation.entryId && !operation.condition && !operation.presetId && operation.mode === '未设置') return this.app.notify?.('至少填写目标、条件、模式或预设之一。');
      if (operation.mode === '共享预设' && (!operation.presetId || !this.isTransitionPreset(operation.presetId))) return this.app.notify?.('共享预设模式需要选择一个已映射的过渡预设。');
      if (operation.mode !== '共享预设') delete operation.presetId;
      if (operation.sceneId && !this.objects().some(object => object.id === operation.sceneId && object.kind === 'scene')) return this.app.notify?.('目标场景不在当前公开场景对象中。');
      if (operation.entryId) {
        const entry = this.object(operation.entryId);
        if (!entry || this.role(entry) !== 'entry') return this.app.notify?.('目标入口 ID 未映射为入口对象。');
        if (!operation.sceneId || this.metadata(entry).sceneId !== operation.sceneId) return this.app.notify?.('目标入口不属于所选目标场景。');
      }
    }
    const transitionTargetId = kind === 'transition' ? operation.objectId : null;
    const sameTargetTransitions = transitionTargetId
      ? this.app.structuralProposals.filter(item => item.kind === 'transition' && item.objectId === transitionTargetId)
      : [];
    const previousTransition = sameTargetTransitions[0] || null;
    if (transitionTargetId) {
      const transitionTarget = this.object(transitionTargetId);
      const before = this.transitionMetadataValues(this.metadata(transitionTarget));
      const requested = this.transitionOperationValues(operation, before);
      const previous = previousTransition ? this.transitionOperationValues(previousTransition, before) : null;
      if (previous && this.transitionValuesEqual(requested, previous) && sameTargetTransitions.length === 1) {
        this.pendingProposalType = null; this.pendingProposalObjectId = null;
        this.closeWorkbenchDialog($('#workbench-proposal-dialog'));
        this.app.notify?.('此有向过渡已经包含相同提案，没有新增净变化。');
        return;
      }
      if (this.transitionValuesEqual(requested, before)) {
        if (!sameTargetTransitions.length) {
          this.pendingProposalType = null; this.pendingProposalObjectId = null;
          this.closeWorkbenchDialog($('#workbench-proposal-dialog'));
          this.app.notify?.('所选值与已发布过渡一致，没有新增净变化。');
          return;
        }
        this.pendingProposalType = null; this.pendingProposalObjectId = null;
        this.pushHistory();
        this.app.structuralProposals = this.app.structuralProposals.filter(item => !(item.kind === 'transition' && item.objectId === transitionTargetId));
        this.app.queueDraftSave?.(); this.pushHistory();
        this.closeWorkbenchDialog($('#workbench-proposal-dialog')); this.render();
        this.app.notify?.('已移除此过渡修改；请求恢复到当前已发布值。');
        return;
      }
      if (previousTransition) {
        operation.operationId = previousTransition.operationId || previousTransition.proposalId || operation.operationId;
        operation.createdAt = previousTransition.createdAt || operation.createdAt;
      }
      this.pendingProposalType = null; this.pendingProposalObjectId = null;
      this.pushHistory();
      const next = [];
      let inserted = false;
      for (const item of this.app.structuralProposals) {
        if (item.kind === 'transition' && item.objectId === transitionTargetId) {
          if (!inserted) { next.push(operation); inserted = true; }
        } else next.push(item);
      }
      if (!inserted) next.push(operation);
      this.app.structuralProposals = next;
      this.app.queueDraftSave?.(); this.pushHistory();
      this.closeWorkbenchDialog($('#workbench-proposal-dialog')); this.render();
      return;
    }
    this.pendingProposalType = null; this.pendingProposalObjectId = null;
    if (kind === 'new-instance') {
      this.pushHistory();
      operation.instanceId = `draft-instance-${operationId}`;
      this.pendingPlacement = operation;
      this.pendingPlacementOperationId = operationId;
      this.activeSceneId = operation.sceneId; this.sceneCanvasSelection = operation.sceneId;
      this.closeWorkbenchDialog($('#workbench-proposal-dialog'));
      this.switchScene(operation.sceneId);
      return;
    }
    this.pushHistory(); this.app.structuralProposals = [...this.app.structuralProposals, operation]; this.app.queueDraftSave?.(); this.pushHistory();
    if (kind === 'new-scene') {
      this.activeSceneId = operation.sceneId; this.sceneCanvasSelection = operation.sceneId;
    }
    this.closeWorkbenchDialog($('#workbench-proposal-dialog')); this.render();
    if (kind === 'new-scene') { this.selectDraftTarget(operation.sceneId, { route: false }); this.syncUrl(); }
  }

  proposeDelete(objectId) {
    const object = this.object(objectId);
    if (!object || this.role(object) !== 'instance') return this.app.notify?.('只有已映射的场景实例可以提出移除。');
    if (this.effectiveLock(object) === 'fixed') return this.app.notify?.('此实例当前编辑约束为固定，不能提出移除。');
    if (this.app.structuralProposals.some(item => item.kind === 'set-lock' && item.objectId === object.id)) return this.app.notify?.('同一实例不能同时申报编辑约束变更和移除；请先移除约束提案。');
    this.addOperation({ operationId: this.app.newFeedbackId(), kind: 'delete-instance', objectId, scope: this.metadata(object).scope || '当前实例', createdAt: new Date().toISOString() });
  }

  addOperation(operation) { this.pushHistory(); this.app.structuralProposals = [...this.app.structuralProposals, operation]; this.app.queueDraftSave?.(); this.pushHistory(); this.render(); }
  removeProposal(id) {
    const removed = this.app.structuralProposals.find(item => (item.operationId || item.proposalId) === id);
    const targetId = removed && this.draftTargetId(removed);
    if (removed?.kind === 'new-scene' && this.app.structuralProposals.some(item => item.kind === 'new-instance' && item.sceneId === removed.sceneId)) {
      this.app.notify?.('此草稿场景仍被新实例引用；请先移除该场景中的草稿实例。');
      return;
    }
    this.pushHistory(); this.app.structuralProposals = this.app.structuralProposals.filter(item => (item.operationId || item.proposalId) !== id);
    this.removeSelectedDraftTarget(targetId, removed?.sceneId);
    this.app.queueDraftSave?.(); this.pushHistory(); this.render();
    if (removed?.kind === 'new-scene') this.syncUrl(true);
  }

  operationText() {
    if (!this.app.structuralProposals.length) return '';
    const operations = this.app.structuralProposals.map(item => {
      const { createdAt, proposalId, ...fields } = item;
      return { operationId: item.operationId || proposalId, ...fields, scope: item.scope || '待 Agent 确认' };
    });
    return `工作台结构操作数据（请逐项处理；这是用户意图，尚未修改源码）：\n${JSON.stringify(operations, null, 2)}`;
  }

  locateTarget(id) {
    this.closeWorkbenchDialog($('#workbench-report-dialog'));
    if (id === 'project' || id === '__project__') this.selectProject();
    else if (this.isDraftTarget(id)) this.selectDraftTarget(id);
    else if (this.object(id)) this.app.selectObject(id);
    this.mobilePane = 'stage'; this.setMobilePane('stage'); this.syncUrl();
    $('#workbench-body')?.scrollIntoView?.({ behavior: 'smooth', block: 'start' });
  }

  openReport() {
    if (this.pendingPlacementOperationId) return this.app.notify?.('请先完成或取消当前实例放置，再检查申报内容。');
    this.app.clearNotice?.();
    const dialog = $('#workbench-report-dialog');
    if (!dialog) return this.app.submitIteration?.({ skipReport: true });
    if (!dialog.open) {
      this.reportSessionSequence += 1;
      const selectionContext = this.captureReportSelectionContext();
      const prior = this.submissionOutcome;
      const snapshot = this.app.snapshot || {};
      const priorMatches = prior && prior.projectId === (this.app.projectId || null)
        && (prior.publicationRevision == null || Number(prior.publicationRevision) === Number(snapshot.publicationRevision))
        && (prior.sourceCommit == null || prior.sourceCommit === (snapshot.sourceCommit || snapshot.baseCommit || null))
        && this.reportSelectionMatches(prior.selectionContext);
      if (prior?.phase === 'sending' || !priorMatches) this.submissionOutcome = null;
      else if (priorMatches) {
        this.submissionOutcome = { ...prior, selectionContext, dialogSequence: this.reportSessionSequence };
      }
    }
    this.persistCurrentNote();
    this.refreshReport(true);
    if (!dialog.open) this.showWorkbenchDialog(dialog);
  }

  captureReportSelectionContext() {
    return this.app.captureSelectionContext?.() || { projectId: this.app.projectId || '' };
  }

  reportSelectionMatches(context) {
    if (!context) return true;
    if (typeof this.app.selectionContextMatches === 'function') return this.app.selectionContextMatches(context);
    return context.projectId === (this.app.projectId || '');
  }

  reportSubmissionContextMatches(context, { requireOpen = true } = {}) {
    const dialog = $('#workbench-report-dialog');
    if (!context || context.sequence !== this.reportSubmissionSequence || context.dialogSequence !== this.reportSessionSequence) return false;
    if (requireOpen && !dialog?.open) return false;
    if (!this.reportSelectionMatches(context.selectionContext)) return false;
    if ((this.app.projectId || null) !== context.projectId) return false;
    const snapshot = this.app.snapshot || {};
    if ((snapshot.publicationRevision ?? null) !== context.publicationRevision) return false;
    if ((snapshot.sourceCommit || snapshot.baseCommit || null) !== context.sourceCommit) return false;
    return true;
  }

  reportOutcomeMatchesCurrent(outcome) {
    const snapshot = this.app.snapshot || {};
    return !!outcome
      && (outcome.dialogSequence == null || outcome.dialogSequence === this.reportSessionSequence)
      && (outcome.sequence == null || outcome.sequence === this.reportSubmissionSequence)
      && (outcome.projectId || null) === (this.app.projectId || null)
      && (outcome.publicationRevision == null || Number(outcome.publicationRevision) === Number(snapshot.publicationRevision))
      && (outcome.sourceCommit == null || outcome.sourceCommit === (snapshot.sourceCommit || snapshot.baseCommit || null))
      && this.reportSelectionMatches(outcome.selectionContext);
  }

  reportDraftKey(projectId, storeId, commandId) {
    return `${storeId || ''}:${projectId || ''}:${commandId || ''}`;
  }

  rememberPendingReportDraft(outcome, context) {
    if (outcome?.status !== 'unknown' || !outcome.commandId) return null;
    const key = this.reportDraftKey(outcome.projectId || context.projectId, outcome.storeId || context.storeId, outcome.commandId);
    const existing = this.pendingReportDrafts.get(key);
    if (existing) return key;
    if (!context.submittedDraft || context.hadPendingCommand) return null;
    this.pendingReportDrafts.set(key, {
      commandId: outcome.commandId, signature: context.signature,
      projectId: context.projectId, storeId: outcome.storeId || context.storeId,
      publicationRevision: context.publicationRevision, sourceCommit: context.sourceCommit,
      draftKey: context.draftKey, signature: context.signature,
      selectionContext: context.selectionContext, submittedDraft: copy(context.submittedDraft),
    });
    return key;
  }

  decisionContextFor(change, sourceNote) {
    const object = this.object(change?.objectId);
    if (!object || !sourceNote || !change?.fieldId) return null;
    const field = object.fields?.find(item => item.id === change.fieldId) || null;
    const capability = this.app.allCapabilities?.().find(item => {
      const parts = this.app.splitCapability?.(item);
      return parts?.objectId === change.objectId && parts?.fieldId === change.fieldId;
    });
    const snapshot = this.app.snapshot || {};
    return {
      projectId: this.app.projectId || null,
      publicationRevision: snapshot.publicationRevision ?? null,
      sourceCommit: snapshot.sourceCommit || snapshot.baseCommit || null,
      objectId: change.objectId,
      fieldId: change.fieldId,
      baselineValue: copy(capability ? this.app.capabilityValue?.(capability, object) : field?.value),
      requestedValue: copy(change.value),
      scope: capability?.scope || field?.scope || field?.workbench?.scope || this.metadata(object).scope || '当前对象',
      sourceNoteKey: sourceNote.key,
      sourceFeedbackId: sourceNote.feedbackId || null,
      sourceObjectId: sourceNote.objectId ?? null,
      sourceText: String(sourceNote.text || ''),
    };
  }

  currentDecisionContext(context) {
    if (!context || typeof context !== 'object') return null;
    this.app.captureVisibleFields?.();
    const sourceNote = this.app.targetNotes?.[context.sourceNoteKey];
    if (!sourceNote || sourceNote.decisionFor || (sourceNote.feedbackId || null) !== context.sourceFeedbackId) return null;
    const objectId = this.noteTargetId(context.sourceNoteKey, sourceNote);
    if (objectId !== context.objectId) return null;
    const fieldKey = `${context.objectId}.${context.fieldId}`;
    if (!Object.hasOwn(this.app.fieldDraftValues || {}, fieldKey)) return null;
    const requestedValue = this.app.fieldDraftValues[fieldKey];
    if (JSON.stringify(requestedValue) !== JSON.stringify(context.requestedValue)) return null;
    return this.decisionContextFor({ objectId: context.objectId, fieldId: context.fieldId, value: requestedValue }, {
      key: context.sourceNoteKey,
      feedbackId: sourceNote.feedbackId || null,
      objectId,
      text: sourceNote.text || '',
    });
  }

  fieldDecision(objectId, fieldId) {
    for (const [key, note] of Object.entries(this.app.targetNotes || {}).reverse()) {
      if (note?.decisionContext?.objectId !== objectId || note?.decisionContext?.fieldId !== fieldId || !this.isDecisionCurrent(note, key)) continue;
      if (['both', 'control', 'text', 'clarify'].includes(note.decisionChoice)) return note.decisionChoice;
      if (note.text?.startsWith('用户决定按意见原文')) return 'text';
      if (note.text?.startsWith('用户要求先澄清意见原文')) return 'clarify';
    }
    return null;
  }

  isDecisionCurrent(note, key) {
    if (!note?.decisionFor) return true;
    if (!note.decisionContext || typeof note.decisionContext !== 'object') return false;
    const current = this.currentDecisionContext(note.decisionContext);
    if (!current || JSON.stringify(current) !== JSON.stringify(note.decisionContext)) return false;
    const siblings = Object.entries(this.app.targetNotes || {}).filter(([, item]) => item?.decisionFor === note.decisionFor);
    return siblings.at(-1)?.[0] === key;
  }

  reportData() {
    this.persistCurrentNote();
    const intent = this.app.buildIterationIntent?.() || { text: $('#edit-text')?.value || '', changeRequest: this.app.objectsWorkflow?.() ? this.app.buildChangeRequest?.() : null };
    const notes = Object.entries(this.app.targetNotes || {}).map(([key, note]) => ({ key, objectId: this.noteTargetId(key, note), sourceObjectId: note?.originalObjectId || null, text: note?.text || '', feedbackId: note?.feedbackId || null, decisionFor: note?.decisionFor || null, decisionContext: copy(note?.decisionContext || null) }));
    const operations = (this.app.structuralProposals || []).map(item => { const { createdAt, proposalId, ...fields } = item; return { operationId: item.operationId || proposalId, ...fields }; });
    return { intent, notes, operations, assets: copy(this.app.assets || []), visualReferences: this.app.referencePayload?.() || [], projectId: this.app.projectId || null, publicationRevision: this.app.snapshot?.publicationRevision, sourceCommit: this.app.snapshot?.sourceCommit || this.app.snapshot?.baseCommit || null };
  }

  refreshReport(initial = false) {
    const data = this.reportData(), signature = JSON.stringify(data);
    this.reportFingerprint = signature;
    const root = $('#workbench-report-content'); releaseVisuals(root); root.replaceChildren();
    const objectMap = new Map([...this.objects(), ...this.draftTargets()].map(object => [object.id, object]));
    const notes = data.notes.filter(note => String(note.text || '').trim());
    const operations = data.operations;
    const request = data.intent.changeRequest;
    const fieldChanges = request?.fields || [];
    const feedback = request?.feedback || [];
    const targetNoteIds = new Set(notes.map(note => note.feedbackId).filter(id => typeof id === 'string' && id));
    const additionalFeedback = feedback.filter(item => !item.feedbackId || !targetNoteIds.has(item.feedbackId));
    const empty = !String(data.intent.text || '').trim() && !fieldChanges.length && !feedback.length && !operations.length && !data.visualReferences.some(r => r.intent?.trim());
    if (empty) root.append(el('p', 'notice', '当前没有实际修改、结构提案或有效意见，不能创建空任务。'));
    const summary = el('div', 'workbench-report-summary');
    summary.append(el('span', '', `项目 ${this.app.currentProject?.()?.title || '未选择'}`), el('span', '', `版本 ${data.publicationRevision ?? '未知'}`), el('span', '', `目标 ${new Set([...notes.map(note => note.objectId || 'project'), ...fieldChanges.map(change => change.objectId), ...feedback.map(item => item.objectId || 'project'), ...operations.map(item => this.operationTargetId(item)).filter(Boolean)]).size}`));
    if (data.projectId) { const identity = el('details', 'workbench-item-identity'); identity.append(el('summary', '', '查看项目 ID'), el('code', '', data.projectId)); summary.append(identity); }
    root.append(summary);
    const visualTargets = [...new Set([...notes.map(n => n.objectId).filter(Boolean), ...fieldChanges.map(c => c.objectId), ...feedback.map(f => f.objectId).filter(Boolean), ...operations.map(o => this.operationTargetId(o)).filter(Boolean)])];
    mountVisual(root, { title: '整轮申报概览', status: '用户意图与确认期望 · 尚未制作',
      references: referenceModel(data, data.projectId),
      rows: [{ label: '范围', value: '整轮范围由下列各项汇总；关联关系不自动扩大修改范围。' }, { label: '内容', value: `${notes.length} 项原文、${fieldChanges.length} 项属性、${operations.length} 项结构提案` }],
      targets: visualTargets.map(id => ({ id, label: objectMap.get(id)?.name || id, scope: this.targetRangeFacts(objectMap.get(id), id).impact })),
      onLocate: id => { this.closeWorkbenchDialog($('#workbench-report-dialog')); this.app.selectObject(id); },
      quantities: fieldChanges.map(change => {
        const object = objectMap.get(change.objectId), field = object?.fields?.find(f => f.id === change.fieldId);
        const capability = this.app.allCapabilities?.().find(item => { const parts = this.app.splitCapability(item); return parts.objectId === change.objectId && parts.fieldId === change.fieldId; });
        const before = capability ? this.app.capabilityValue?.(capability, object || {}) : field?.value;
        return { id: `${change.objectId}.${change.fieldId}`, label: `${object?.name || change.objectId} · ${field?.label || capability?.label || change.fieldId}`,
          before, expected: change.value, unit: capability?.unit || field?.unit || '', comparable: ['scalar', 'number', 'integer'].includes(capability?.type || field?.type) };
      }),
      details: [{ label: '项目', value: data.projectId }, { label: '发布基线', value: data.publicationRevision }, { label: 'Git 来源', value: data.sourceCommit }] }, `report:${data.projectId}`);

    if (notes.length) {
      root.append(el('h3', '', '意见原文'));
      for (const note of notes) {
        const target = note.objectId ? objectMap.get(note.objectId) : null;
        const orphan = note.objectId != null && !target;
        const decisionCurrent = note.decisionFor ? this.isDecisionCurrent(note, note.key) : true;
        const card = el('article', `workbench-report-item${orphan ? ' orphan' : ''}${note.decisionFor && !decisionCurrent ? ' workbench-decision-stale' : ''}`);
        card.append(el('div', 'workbench-report-item-title', `${target?.name || note.objectId || '当前项目'} · ${note.decisionFor ? '处理决定' : '用户意见'}`));
        this.appendTargetRange(card, target, note.objectId);
        if (note.objectId || note.sourceObjectId) {
          const identity = el('details', 'workbench-item-identity'); identity.append(el('summary', '', '查看关联编号'));
          if (note.objectId) identity.append(el('p', '', `当前目标 ID：${note.objectId}`));
          if (note.sourceObjectId) identity.append(el('p', '', `原目标 ID：${note.sourceObjectId}`));
          if (note.feedbackId) identity.append(el('p', '', `意见 ID：${note.feedbackId}`));
          card.append(identity);
        }
        if (note.decisionFor && !decisionCurrent) card.append(el('p', 'workbench-conflict-note', '此决定依据的字段、原文、范围或版本已变化，旧决定仅保留供核对，不会作为有效指令发送。'));
        if (!note.decisionFor) card.append(el('small', 'muted', '来源：本轮用户原文 · 尚未制作'));
        if (this.editingReportNoteId === (note.feedbackId || note.key)) {
          const editor = el('textarea', 'workbench-report-note-editor'); editor.value = note.text; editor.rows = 4; editor.dataset.reportNoteEditor = note.feedbackId || note.key; editor.setAttribute('aria-label', `编辑 ${target?.name || note.objectId || '项目'} 意见`); card.append(editor);
          const save = el('button', 'button secondary', '完成编辑并更新预览'); save.type = 'button'; save.dataset.workbenchAction = 'save-report-note'; save.dataset.reportNoteId = note.feedbackId || note.key;
          const cancel = el('button', 'button quiet', '取消编辑'); cancel.type = 'button'; cancel.dataset.workbenchAction = 'cancel-report-note-edit'; cancel.dataset.reportNoteId = note.feedbackId || note.key; card.append(save, cancel);
        } else {
          card.append(el('p', '', note.text));
          const edit = el('button', 'button secondary', '编辑意见'); edit.type = 'button'; edit.dataset.workbenchAction = 'edit-report-note'; edit.dataset.reportNoteId = note.feedbackId || note.key;
          const remove = el('button', 'button quiet', '移除意见'); remove.type = 'button'; remove.dataset.workbenchAction = 'remove-report-note'; remove.dataset.reportNoteId = note.feedbackId || note.key; card.append(edit, remove);
        }
        if (target || note.objectId == null) { const locate = el('button', 'button quiet', '回到原目标继续调整'); locate.type = 'button'; locate.dataset.workbenchAction = 'locate-target'; locate.dataset.targetId = note.objectId || 'project'; card.append(locate); }
        root.append(card);
      }
    }
    if (fieldChanges.length) {
      root.append(el('h3', '', '结构化属性差异'));
      for (const change of fieldChanges) {
        const object = objectMap.get(change.objectId); const field = object?.fields?.find(item => item.id === change.fieldId);
        const capability = this.app.allCapabilities?.().find(item => { const parts = this.app.splitCapability(item); return parts.objectId === change.objectId && parts.fieldId === change.fieldId; });
        const before = capability ? this.app.capabilityValue?.(capability, object || {}) : field?.value;
        const card = el('article', 'workbench-report-item');
        card.append(el('div', 'workbench-report-item-title', `${object?.name || '对象'} · ${field?.label || capability?.label || '属性'}`), el('p', '', `当前值：${this.displayValue(before)} → 本轮期望：${this.displayValue(change.value)}（尚未制作）`));
        this.appendTargetRange(card, object, change.objectId);
        const scope = capability?.scope || field?.scope || field?.workbench?.scope || this.metadata(object).scope || '当前对象';
        const snapshot = this.app.snapshot || {}, repair = snapshot.kind === 'REPAIR';
        const source = repair
          ? `返修候选配置（基于已接受版本 ${data.publicationRevision ?? '未知'}）`
          : `已接受版本 ${data.publicationRevision ?? '未知'} 的对象配置`;
        card.append(el('small', 'muted', `来源：${source} · 范围：${this.scopeLabel(scope)}`));
        if (repair) {
          const identity = el('details', 'workbench-item-identity'); identity.append(el('summary', '', '查看返修候选身份'));
          identity.append(el('p', '', `候选 ID：${snapshot.candidateId || '未提供'}`), el('p', '', `源码版本：${snapshot.sourceCommit || snapshot.baseCommit || '未提供'}`));
          card.append(identity);
        }
        const identity = el('details', 'workbench-item-identity'); identity.append(el('summary', '', '查看对象与属性 ID'), el('p', '', `${change.objectId} · ${change.fieldId}`)); card.append(identity);
        const remove = el('button', 'button quiet', '移除此属性修改'); remove.type = 'button'; remove.dataset.workbenchAction = 'remove-field-change'; remove.dataset.objectId = change.objectId; remove.dataset.fieldId = change.fieldId; remove.dataset.fieldChangeId = `${change.objectId}.${change.fieldId}`; card.append(remove);
        root.append(card);
      }
    }
    if (additionalFeedback.length) {
      root.append(el('h3', '', '对象反馈与跨目标意见'));
      for (const item of additionalFeedback) {
        const object = objectMap.get(item.objectId); const card = el('article', 'workbench-report-item');
        card.append(el('div', 'workbench-report-item-title', `${object?.name || '当前项目'} · 分类意见`));
        this.appendTargetRange(card, object, item.objectId);
        card.append(el('small', 'muted', `来源：用户分类意见 · ${this.feedbackCategoryLabel(item.category)} · 尚未制作`));
        const feedbackId = item.feedbackId;
        const editing = feedbackId && this.editingReportFeedbackId === feedbackId;
        if (editing) {
          const category = el('select'); category.dataset.reportFeedbackCategory = feedbackId; category.setAttribute('aria-label', '意见类别');
          const categories = [...($('#feedback-category')?.options || [])];
          for (const option of categories) category.append(new Option(option.textContent, option.value));
          if (!categories.some(option => option.value === item.category)) category.append(new Option(this.feedbackCategoryLabel(item.category), item.category || 'general'));
          category.value = item.category || 'general'; card.append(category);
          const editor = el('textarea', 'workbench-report-note-editor'); editor.value = item.message || ''; editor.rows = 4; editor.dataset.reportFeedbackEditor = feedbackId; editor.setAttribute('aria-label', '编辑分类意见'); card.append(editor);
          const save = el('button', 'button secondary', '完成编辑并更新预览'); save.type = 'button'; save.dataset.workbenchAction = 'save-report-feedback'; save.dataset.reportFeedbackId = feedbackId;
          const cancel = el('button', 'button quiet', '取消编辑'); cancel.type = 'button'; cancel.dataset.workbenchAction = 'cancel-report-feedback-edit'; cancel.dataset.reportFeedbackId = feedbackId; card.append(save, cancel);
        } else {
          card.append(el('p', '', item.message));
          const edit = el('button', 'button secondary', '编辑意见'); edit.type = 'button'; edit.dataset.workbenchAction = 'edit-report-feedback'; edit.dataset.reportFeedbackId = feedbackId;
          const remove = el('button', 'button quiet', '移除意见'); remove.type = 'button'; remove.dataset.workbenchAction = 'remove-report-feedback'; remove.dataset.reportFeedbackId = feedbackId; card.append(edit, remove);
        }
        const identity = el('details', 'workbench-item-identity'); identity.append(el('summary', '', '查看关联编号'), el('p', '', `${item.objectId || '项目'} · ${feedbackId || '未编号'}`)); card.append(identity);
        if (item.objectId && object) { const locate = el('button', 'button quiet', '回到原目标继续调整'); locate.type = 'button'; locate.dataset.workbenchAction = 'locate-target'; locate.dataset.targetId = item.objectId; card.append(locate); }
        root.append(card);
      }
    }
    if (operations.length) {
      root.append(el('h3', '', '结构操作提案'));
      for (const item of operations) {
        const card = el('article', 'workbench-report-item'); mountVisual(card, { title: '结构前后', status: '坐标与关系来自草稿 · 未应用到工程', rows: [{ label: '操作', value: this.operationLabel(item) }, { label: '来源', value: item.before ?? '新建目标 / 未提供旧值' }, { label: '期望', value: item.position ?? item.requested ?? item.bounds ?? item.lock ?? item.name }], details: [{ label: '完整提案', value: item }] }, `operation:${data.projectId}:${item.operationId || item.proposalId}`); card.append(el('div', 'workbench-report-item-title', this.operationLabel(item)), el('p', '', `影响范围：${this.scopeLabel(item.scope || '待 Agent 确认')}。此内容是用户意图，尚未改变源码。`));
        if (item.kind === 'new-scene') {
          const bounds = Array.isArray(item.bounds) && item.bounds.length >= 2
            ? `${item.bounds[0]} × ${item.bounds[1]}` : '未提供';
          card.append(el('p', '', `世界尺寸：${bounds}`));
          card.append(el('p', '', `起始结构：${this.sceneTemplateLabel(item.template)}`));
          const connections = el('p', 'workbench-report-operation-connections', `出入口或连接说明：${String(item.connections || '').trim() || '未提供'}`);
          connections.style.whiteSpace = 'pre-wrap'; connections.style.overflowWrap = 'anywhere';
          card.append(connections);
        }
        const targetId = this.operationTargetId(item);
        if (targetId) this.appendTargetRange(card, objectMap.get(targetId) || null, targetId);
        if (targetId) { const locate = el('button', 'button quiet', '定位目标'); locate.type = 'button'; locate.dataset.workbenchAction = 'locate-target'; locate.dataset.targetId = targetId; card.append(locate); }
        root.append(card);
      }
    }
    const conflictPairs = fieldChanges.flatMap(change => notes.filter(note => note.objectId === change.objectId && String(note.text || '').trim() && !note.decisionFor).map(note => ({ change, note })));
    if (conflictPairs.length) {
      root.append(el('h3', '', '控件与原文的可选处理'));
      root.append(el('p', 'workbench-conflict-note', '同一目标的属性与原文可以互补，无需重复选择。只有要求冲突或影响执行的含义不清时，才在这里记录优先项或请 Agent 澄清；原始内容都会保留。'));
      for (const { change, note } of conflictPairs) {
        const decisionFor = `${change.objectId}.${change.fieldId}:${note.feedbackId || note.key}`;
        const decisionCandidates = Object.entries(this.app.targetNotes || {}).filter(([, item]) => item?.decisionFor === decisionFor);
        const activeEntry = [...decisionCandidates].reverse().find(([key, item]) => this.isDecisionCurrent(item, key));
        const existingEntry = activeEntry || decisionCandidates.at(-1) || null;
        const existingDecision = existingEntry?.[1] ? { ...existingEntry[1], key: existingEntry[0] } : null;
        const field = objectMap.get(change.objectId)?.fields?.find(item => item.id === change.fieldId);
        const card = el('section', 'workbench-conflict-resolution');
        card.append(el('b', '', `${this.object(change.objectId)?.name || '对象'} · ${field?.label || '属性'}`), el('p', '', `控件：${this.displayValue(change.value)} · 意见：${note.text}`));
        if (existingDecision && activeEntry) card.append(el('p', 'workbench-conflict-decision', `已记录用户决定：${existingDecision.text}`));
        else {
          if (existingDecision) card.append(el('p', 'workbench-conflict-note', `此前决定已失效并保留供核对：${existingDecision.text}`));
          const select = el('select'); select.dataset.conflictDecision = 'true'; select.setAttribute('aria-label', '控件与意见冲突处理方式');
          select.append(new Option('选择处理方式', ''), new Option('两项都执行（互补要求）', 'both'), new Option('以控件值为准', 'control'), new Option('以意见原文为准', 'text'), new Option('请 Agent 先澄清', 'clarify'));
          const explanation = el('textarea'); explanation.rows = 2; explanation.dataset.conflictExplanation = 'true'; explanation.placeholder = '可补充具体原因或边界'; explanation.setAttribute('aria-label', '冲突处理补充说明');
          const apply = el('button', 'button secondary', '记录此决定'); apply.type = 'button'; apply.dataset.workbenchAction = 'apply-conflict-decision'; apply.dataset.objectId = change.objectId; apply.dataset.fieldId = change.fieldId; apply.dataset.noteId = note.feedbackId || note.key;
          card.append(select, explanation, apply);
        }
        root.append(card);
      }
    }
    const orphanIds = notes.filter(note => note.objectId != null && !objectMap.has(note.objectId)).map(note => note.objectId);
    if (orphanIds.length) root.append(el('p', 'workbench-conflict-note', `意见目标已从公开对象目录消失：${orphanIds.join('、')}。先重新关联或移除意见再提交。`));
    if (String(data.intent.text || '').trim()) {
      const info = el('details', 'workbench-request-envelope'); info.append(el('summary', '', '本次交给 Agent 的总请求文本')); info.append(el('pre', '', data.intent.text)); root.append(info);
    }
    const status = $('#workbench-report-status');
    const editPending = this.hasUncommittedReportEdit();
    this.reportHasBlockingContent = empty || orphanIds.length > 0;
    if (status) status.textContent = editPending
      ? '申报编辑尚未完成。请点击“完成编辑并更新预览”或“取消编辑”；当前文字已保存在本地草稿，不会提交旧预览。'
      : empty ? '预览可查看；提交入口已禁用。'
        : '预览显示当前草稿、用户原文、属性差异和结构提案；上述内容仍是意图或期望，尚未制作。';
    const confirm = $('#workbench-report-confirm');
    if (confirm) confirm.disabled = empty || orphanIds.length > 0 || editPending || this.reportSubmitting;
    if (!initial && status && !editPending && !empty) status.textContent = '工作区内容发生变化，预览已更新。请检查后再提交。';
    this.renderSubmissionStatus();
  }

  operationTargetId(item) {
    if (item.kind === 'new-scene') return item.sceneId || this.draftTargetId(item);
    if (item.kind === 'new-instance') return item.instanceId || this.draftTargetId(item);
    return item.objectId || null;
  }

  reportNoteEntry(reportNoteId) {
    const entries = Object.entries(this.app.targetNotes || {});
    return entries.find(([key]) => key === reportNoteId) || entries.find(([, note]) => note?.feedbackId === reportNoteId) || null;
  }

  reportFeedbackEntry(reportFeedbackId) {
    const index = (this.app.feedback || []).findIndex(item => item?.feedbackId === reportFeedbackId);
    return index < 0 ? null : [index, this.app.feedback[index]];
  }

  hasUncommittedReportEdit() {
    if (this.editingReportNoteBase) {
      const note = this.app.targetNotes?.[this.editingReportNoteBase.key];
      if (note && note.text !== this.editingReportNoteBase.text) return true;
    }
    if (this.editingReportFeedbackBase) {
      const item = this.reportFeedbackEntry(this.editingReportFeedbackBase.feedbackId)?.[1];
      if (item && (item.message !== this.editingReportFeedbackBase.message || item.category !== this.editingReportFeedbackBase.category)) return true;
    }
    return false;
  }

  updateReportSubmitGate() {
    const pending = this.hasUncommittedReportEdit();
    const confirm = $('#workbench-report-confirm');
    if (confirm) confirm.disabled = pending || this.reportHasBlockingContent || this.reportSubmitting;
    const status = $('#workbench-report-status');
    if (status && pending) status.textContent = '申报编辑尚未完成。请完成编辑或取消编辑；缓冲文字已保存在本地草稿中，当前预览不会提交旧内容。';
  }

  updateReportNoteBuffer(reportNoteId, text) {
    const entry = this.reportNoteEntry(reportNoteId);
    if (!entry) return;
    const [key, note] = entry;
    this.app.targetNotes[key] = { ...note, text, feedbackId: note.feedbackId || this.app.newFeedbackId?.(), updatedAt: new Date().toISOString() };
    if (this.targetKey() === key) { const input = $('#edit-text'); if (input) input.value = text; }
    this.app.queueDraftSave?.();
    this.updateReportSubmitGate();
  }

  updateReportFeedbackBuffer(reportFeedbackId, message) {
    const entry = this.reportFeedbackEntry(reportFeedbackId);
    if (!entry) return;
    const [index, item] = entry;
    this.app.feedback[index] = { ...item, message };
    this.app.queueDraftSave?.();
    this.updateReportSubmitGate();
  }

  updateReportFeedbackCategory(reportFeedbackId, category) {
    const entry = this.reportFeedbackEntry(reportFeedbackId);
    if (!entry) return;
    const [index, item] = entry;
    this.app.feedback[index] = { ...item, category };
    this.app.queueDraftSave?.();
    this.updateReportSubmitGate();
  }

  editReportNote(reportNoteId) {
    const entry = this.reportNoteEntry(reportNoteId);
    if (!entry) return;
    if (this.hasUncommittedReportEdit()) return this.app.notify?.('请先完成或取消当前申报编辑。');
    const [key, note] = entry;
    this.pushHistory();
    this.editingReportNoteBase = { key, text: note.text || '' };
    this.editingReportNoteId = reportNoteId;
    this.refreshReport(true);
    const editor = [...document.querySelectorAll('[data-report-note-editor]')].find(node => node.dataset.reportNoteEditor === reportNoteId);
    editor?.focus?.();
  }

  cancelReportNoteEdit() {
    if (this.editingReportNoteBase) {
      const { key, text } = this.editingReportNoteBase;
      const note = this.app.targetNotes?.[key];
      if (note) this.app.targetNotes[key] = { ...note, text };
      if (this.targetKey() === key) { const input = $('#edit-text'); if (input) input.value = text; }
      this.app.queueDraftSave?.();
    }
    this.editingReportNoteId = null;
    this.editingReportNoteBase = null;
    this.refreshReport(true);
  }

  saveReportNote(reportNoteId) {
    const entry = this.reportNoteEntry(reportNoteId);
    const editor = [...document.querySelectorAll('[data-report-note-editor]')].find(node => node.dataset.reportNoteEditor === reportNoteId);
    if (!entry || !editor) return;
    const [key, note] = entry;
    const text = editor.value;
    if (String(text).trim()) this.app.targetNotes[key] = { ...note, text, feedbackId: note.feedbackId || this.app.newFeedbackId?.(), updatedAt: new Date().toISOString() };
    else delete this.app.targetNotes[key];
    if (this.targetKey() === key) this.loadCurrentNote();
    this.editingReportNoteId = null;
    this.editingReportNoteBase = null;
    this.app.queueDraftSave?.(); this.pushHistory(); this.refreshReport(false);
  }

  removeReportNote(reportNoteId) {
    const entry = this.reportNoteEntry(reportNoteId);
    if (!entry) return;
    const [key] = entry;
    this.pushHistory(); delete this.app.targetNotes[key];
    if (this.targetKey() === key) this.loadCurrentNote();
    if (this.editingReportNoteId === reportNoteId) { this.editingReportNoteId = null; this.editingReportNoteBase = null; }
    this.app.queueDraftSave?.(); this.pushHistory(); this.refreshReport(false);
  }

  editReportFeedback(reportFeedbackId) {
    const entry = this.reportFeedbackEntry(reportFeedbackId);
    if (!entry) return;
    if (this.hasUncommittedReportEdit()) return this.app.notify?.('请先完成或取消当前申报编辑。');
    const [, item] = entry;
    this.pushHistory();
    this.editingReportFeedbackId = reportFeedbackId;
    this.editingReportFeedbackBase = { feedbackId: reportFeedbackId, message: item.message || '', category: item.category || 'general' };
    this.refreshReport(true);
    const editor = [...document.querySelectorAll('[data-report-feedback-editor]')].find(node => node.dataset.reportFeedbackEditor === reportFeedbackId);
    editor?.focus?.();
  }

  cancelReportFeedbackEdit() {
    const base = this.editingReportFeedbackBase;
    if (base) {
      const entry = this.reportFeedbackEntry(base.feedbackId);
      if (entry) this.app.feedback[entry[0]] = { ...entry[1], message: base.message, category: base.category };
      this.app.queueDraftSave?.();
    }
    this.editingReportFeedbackId = null; this.editingReportFeedbackBase = null;
    this.refreshReport(true);
  }

  saveReportFeedback(reportFeedbackId) {
    const entry = this.reportFeedbackEntry(reportFeedbackId);
    if (!entry) return;
    const editor = [...document.querySelectorAll('[data-report-feedback-editor]')].find(node => node.dataset.reportFeedbackEditor === reportFeedbackId);
    const category = [...document.querySelectorAll('[data-report-feedback-category]')].find(node => node.dataset.reportFeedbackCategory === reportFeedbackId);
    if (editor) this.updateReportFeedbackBuffer(reportFeedbackId, editor.value);
    if (category) this.updateReportFeedbackCategory(reportFeedbackId, category.value);
    const latest = this.reportFeedbackEntry(reportFeedbackId);
    if (!String(latest?.[1]?.message || '').trim()) {
      this.app.feedback = (this.app.feedback || []).filter(item => item?.feedbackId !== reportFeedbackId);
      this.app.notify?.('空白意见已移除。');
    }
    this.editingReportFeedbackId = null; this.editingReportFeedbackBase = null;
    this.app.renderFeedback?.(); this.app.queueDraftSave?.(); this.pushHistory(); this.refreshReport(false);
  }

  removeReportFeedback(reportFeedbackId) {
    if (!this.reportFeedbackEntry(reportFeedbackId)) return;
    this.pushHistory();
    this.app.feedback = (this.app.feedback || []).filter(item => item?.feedbackId !== reportFeedbackId);
    if (this.editingReportFeedbackId === reportFeedbackId) { this.editingReportFeedbackId = null; this.editingReportFeedbackBase = null; }
    this.app.renderFeedback?.(); this.app.queueDraftSave?.(); this.pushHistory(); this.refreshReport(false);
  }

  removeFieldChange(objectId, fieldId) {
    if (!objectId || !fieldId) return;
    const id = `${objectId}.${fieldId}`;
    this.app.captureVisibleFields?.();
    if (!Object.hasOwn(this.app.fieldDraftValues || {}, id)) return;
    this.pushHistory();
    delete this.app.fieldDraftValues[id]; this.app.dirtyFields?.delete(id);
    this.app.renderDynamicFields?.(this.objects(), this.app.capabilities);
    this.app.renderObjectDetail?.();
    this.app.queueDraftSave?.(); this.pushHistory();
    this.render(); this.refreshReport(false);
  }

  applyConflictDecision(button) {
    const card = button.closest('.workbench-conflict-resolution');
    const objectId = button.dataset.objectId, fieldId = button.dataset.fieldId, noteId = button.dataset.noteId;
    const choice = card?.querySelector('[data-conflict-decision]')?.value;
    const explanation = card?.querySelector('[data-conflict-explanation]')?.value.trim() || '';
    const entry = this.reportNoteEntry(noteId), request = this.app.buildChangeRequest?.();
    const change = request?.fields?.find(item => item.objectId === objectId && item.fieldId === fieldId);
    if (!entry || !change || !['both', 'control', 'text', 'clarify'].includes(choice)) return this.app.notify?.('请选择两项都执行、控件优先、原文优先或先澄清，再记录决定。');
    const [sourceKey, sourceNote] = entry;
    const field = this.object(objectId)?.fields?.find(item => item.id === fieldId);
    const label = field?.label || fieldId;
    const detail = choice === 'both'
      ? `用户决定同时保留并执行互补要求：属性“${label} = ${this.displayValue(change.value)}”和原文意见“${sourceNote.text}”。如制作分析发现二者不能同时实现，先说明原因并澄清。`
      : choice === 'control'
        ? `用户决定按属性控件“${label} = ${this.displayValue(change.value)}”处理；相关原文意见仍保留为上下文。`
        : choice === 'text'
          ? `用户决定按意见原文“${sourceNote.text}”处理；属性控件“${label} = ${this.displayValue(change.value)}”仍作为已知草稿值一并保留。`
          : `用户要求先澄清意见原文“${sourceNote.text}”与属性控件“${label} = ${this.displayValue(change.value)}”的关系，澄清前不要自行选择其一执行。`;
    const decisionFor = `${objectId}.${fieldId}:${noteId}`;
    const feedbackId = this.app.newFeedbackId();
    const key = `__workbench_conflict__${encodeURIComponent(objectId)}__${encodeURIComponent(fieldId)}__${encodeURIComponent(noteId)}__${encodeURIComponent(feedbackId)}`;
    const decisionContext = this.decisionContextFor(change, { key: sourceKey, feedbackId: sourceNote.feedbackId || null, objectId: this.noteTargetId(sourceKey, sourceNote), text: sourceNote.text || '' });
    if (!decisionContext) return this.app.notify?.('无法取得此决定的当前版本依据；请刷新后重新核对。');
    this.pushHistory();
    this.app.targetNotes[key] = { objectId, text: [detail, explanation].filter(Boolean).join('\n补充说明：'), feedbackId, decisionFor, decisionContext, decisionChoice: choice, updatedAt: new Date().toISOString() };
    this.app.queueDraftSave?.(); this.pushHistory(); this.render(); this.refreshReport(false);
  }

  async confirmReport() {
    if (this.pendingPlacementOperationId) { this.app.notify?.('请先完成或取消当前实例放置，再提交申报。'); return; }
    if (this.reportSubmitting) return;
    if (this.hasUncommittedReportEdit()) {
      this.updateReportSubmitGate();
      this.app.notify?.('申报中有尚未完成的编辑；请完成编辑并刷新预览，或取消编辑后再提交。');
      return;
    }
    const latest = this.reportData(), signature = JSON.stringify(latest);
    if (signature !== this.reportFingerprint) { this.refreshReport(false); return; }
    if (this.submissionOutcome?.status === 'submitted' && this.submissionOutcome.signature === signature) {
      this.updateReportSubmitGate();
      return;
    }
    const dialog = $('#workbench-report-dialog');
    if (dialog && !dialog.open) return;
    const confirm = $('#workbench-report-confirm');
    this.reportSubmitting = true; if (confirm) confirm.disabled = true;
    const context = {
      sequence: ++this.reportSubmissionSequence, dialogSequence: this.reportSessionSequence,
      selectionContext: this.captureReportSelectionContext(),
      projectId: this.app.projectId || null,
      publicationRevision: this.app.snapshot?.publicationRevision ?? null,
      sourceCommit: this.app.snapshot?.sourceCommit || this.app.snapshot?.baseCommit || null,
      draftKey: this.app.draftKey || null, storeId: this.app.handshake?.storeId || null, signature,
    };
    const pending = this.app.pendingCommandRecord?.('iteration.submit', context.projectId) || null;
    context.hadPendingCommand = !!pending;
    context.submittedDraft = pending ? null : this.app.captureIterationSubmissionDraft?.(latest.intent?.text || '', latest.intent?.changeRequest || null) || null;
    this.activeReportSubmission = context;
    this.submissionOutcome = { status: 'unknown', phase: 'sending', type: 'iteration.submit', ...context, reason: '正在发送本轮申报；请勿重复点击。' };
    this.renderSubmissionStatus();
    let outcome = null;
    try {
      const result = await this.app.submitIteration?.({ skipReport: true, reviewedReport: copy(latest) });
      const validStatuses = new Set(['submitted', 'blocked', 'rejected', 'unknown', 'stale']);
      outcome = result && validStatuses.has(result.status) ? result : {
        status: 'unknown', reason: '提交流程未返回明确结果；不能仅凭提案编号变化确认成功。',
        type: 'iteration.submit', projectId: context.projectId, commandId: null,
      };
    } catch (error) {
      outcome = error.commandOutcome || { status: error.status === 409 ? 'stale' : Number.isInteger(error.status) && error.status >= 400 && error.status < 500 ? 'rejected' : 'unknown', reason: error.message || '申报未返回可核实结果。', type: 'iteration.submit', projectId: context.projectId };
    }
    finally {
      const normalized = {
        ...context, ...(outcome || {}),
        projectId: outcome?.projectId || context.projectId,
        publicationRevision: outcome?.publicationRevision ?? context.publicationRevision,
        sourceCommit: outcome?.sourceCommit || context.sourceCommit,
        type: outcome?.type || 'iteration.submit', phase: null,
      };
      if (normalized.status === 'unknown') normalized.draftRecordKey = this.rememberPendingReportDraft(normalized, context);
      else if (normalized.status === 'submitted' && normalized.commandId) this.pendingReportDrafts.delete(this.reportDraftKey(normalized.projectId, normalized.storeId || context.storeId, normalized.commandId));
      if (this.activeReportSubmission === context) {
        this.reportSubmitting = false;
        this.activeReportSubmission = null;
      }
      if (this.reportSubmissionContextMatches(context)) {
        this.submissionOutcome = normalized;
        this.renderSubmissionStatus();
        if (normalized.status === 'submitted' && normalized.hasPostSubmitEdits === false) {
          this.reportFingerprint = null;
          this.closeWorkbenchDialog(dialog);
        } else if (normalized.status === 'submitted') this.refreshReport(false);
        this.renderSubmissionStatus();
      }
      if (dialog?.open && confirm) this.updateReportSubmitGate();
    }
  }

  submissionStatusText(outcome) {
    if (!outcome) return '';
    if (outcome.phase === 'sending') return '正在发送本轮申报。';
    const reason = String(outcome.reason || '没有附带原因。');
    const status = ({ submitted: '已提交', blocked: '未发送', rejected: '服务明确拒绝', unknown: '结果待核实', stale: '项目或版本上下文已变化' })[outcome.status] || '状态未提供';
    return `${status}：${reason}`;
  }

  renderSubmissionStatus() {
    const root = $('#workbench-submission-status');
    const outcome = this.submissionOutcome;
    if (!root) return;
    root.replaceChildren();
    if (!this.reportOutcomeMatchesCurrent(outcome)) {
      hide(root, true); return;
    }
    hide(root, false); root.dataset.status = outcome.phase === 'sending' ? 'sending' : outcome.status;
    if (outcome.status === 'submitted' && outcome.signature != null && outcome.signature !== this.reportFingerprint) {
      root.dataset.status = 'previous';
      root.append(el('p', 'muted', '上一轮申报已送审；当前草稿尚未提交。'));
      return;
    }
    root.append(el('p', `workbench-submission-state ${outcome.status || ''}`, this.submissionStatusText(outcome)));
    if (outcome.commandId || outcome.proposalId || outcome.projectId) {
      const identity = el('details', 'workbench-item-identity'); identity.append(el('summary', '', '查看本次申报身份'));
      identity.append(el('p', '', `项目：${outcome.projectId || '未绑定'} · 发布版本：${outcome.publicationRevision ?? '未提供'}`));
      if (outcome.commandId) identity.append(el('p', '', `原命令 ID：${outcome.commandId}`));
      if (outcome.proposalId) identity.append(el('p', '', `提案 ID：${outcome.proposalId}`));
      if (outcome.proposalRevision != null) identity.append(el('p', '', `提案修订：${outcome.proposalRevision}`));
      if (outcome.jobId) identity.append(el('p', '', `作业 ID：${outcome.jobId}`));
      if (outcome.candidateId) identity.append(el('p', '', `候选 ID：${outcome.candidateId}`));
      root.append(identity);
    }
    if (outcome.status === 'unknown' && outcome.commandId && outcome.type === 'iteration.submit' && !this.submissionReconciling) {
      const reconcile = el('button', 'button secondary', '核实原命令状态'); reconcile.type = 'button';
      reconcile.addEventListener('click', () => { void this.reconcileSubmission(outcome); }); root.append(reconcile);
    } else if (this.submissionReconciling) root.append(el('p', 'muted', '正在使用原命令编号核实服务记录；不会创建新的申报命令。'));
    if (outcome.status !== 'sending') {
      const job = this.submissionReviewJob(outcome);
      if (job) {
        const candidate = job.candidate || job.response?.candidate;
        const hasCandidate = !!(job.candidateId || candidate?.id || job.status === 'READY_FOR_REVIEW');
        const view = el('button', 'button secondary', hasCandidate ? '查看候选与试玩入口' : '查看本轮处理状态'); view.type = 'button';
        view.addEventListener('click', () => { this.closeWorkbenchDialog($('#workbench-report-dialog')); this.app.selectJob?.(job.id); }); root.append(view);
      }
      const edit = el('button', 'button quiet', '返回编辑'); edit.type = 'button'; edit.addEventListener('click', () => this.returnToWorkbenchEdit()); root.append(edit);
    }
  }

  submissionReviewJob(outcome) {
    if (typeof this.app.selectJob !== 'function' || !outcome?.projectId) return null;
    const statusesThatBlockSubmission = new Set(['QUEUED', 'DISPATCHING', 'RUNNING', 'VERIFYING', 'PROJECTING', 'READY_FOR_REVIEW', 'UNCERTAIN', 'CANCEL_REQUESTED', 'CANCELLING']);
    const jobsById = new Map();
    for (const job of [...(this.app.workspace?.jobs || []), this.app.job, this.app.projectView?.job]) {
      if (job?.id && job.projectId === outcome.projectId) jobsById.set(job.id, job);
    }
    const packetForJob = job => {
      const candidate = job.candidate || job.response?.candidate;
      const ids = [job.packetId, typeof job.packet === 'string' ? job.packet : null, job.packet?.id, job.packet?.packetId,
        candidate?.packetId, candidate?.packet?.id, candidate?.packet?.packetId].filter(Boolean);
      return [job.packet, job.response?.packet].find(packet => packet && typeof packet === 'object')
        || (this.app.workspace?.packets || []).find(packet => packet.projectId === outcome.projectId
          && ([packet.id, packet.packetId].some(id => id && ids.includes(id)) || packet.jobId === job.id)) || null;
    };
    const identityForJob = job => {
      const candidate = job.candidate || job.response?.candidate;
      const packet = packetForJob(job);
      const proposal = this.app.proposalForJob?.(job, candidate);
      return {
        proposalId: job.proposalId || job.packet?.proposalId || candidate?.proposalId || packet?.proposalId || proposal?.id || null,
        proposalRevision: job.proposalRevision ?? job.packet?.proposalRevision ?? candidate?.proposalRevision ?? packet?.proposalRevision ?? null,
        candidateId: job.candidateId || candidate?.id || null,
      };
    };
    const attemptMatches = job => {
      const identity = identityForJob(job);
      const exactJob = !!outcome.jobId && job.id === outcome.jobId;
      const exactCandidate = !!outcome.candidateId && identity.candidateId === outcome.candidateId;
      if (!exactJob && !exactCandidate) return false;
      if (outcome.proposalId && identity.proposalId && identity.proposalId !== outcome.proposalId) return false;
      if (outcome.proposalRevision != null && identity.proposalRevision != null
        && Number(identity.proposalRevision) !== Number(outcome.proposalRevision)) return false;
      return true;
    };
    const directMatches = [...jobsById.values()].filter(attemptMatches);
    if (directMatches.length === 1) return directMatches[0];
    const proposalId = outcome.proposalId || null, proposalRevision = outcome.proposalRevision ?? null;
    if (proposalId && proposalRevision != null) {
      const associated = [...jobsById.values()].filter(job => {
        const identity = identityForJob(job);
        return identity.proposalId === proposalId && identity.proposalRevision != null
          && Number(identity.proposalRevision) === Number(proposalRevision);
      });
      const selectedJobId = this.app.selectedJobForProject?.(outcome.projectId);
      const selected = associated.find(job => job.id === selectedJobId);
      if (selected) return selected;
      const currentJob = this.app.projectView?.projectId === outcome.projectId ? this.app.projectView.job : null;
      const current = associated.find(job => job.id === currentJob?.id);
      if (current) return current;
      if (associated.length === 1) return associated[0];
    }
    const isBlocking = job => statusesThatBlockSubmission.has(String(job?.status || '').toUpperCase());
    const selectedJobId = this.app.selectedJobForProject?.(outcome.projectId);
    const selectedBlocker = [...jobsById.values()].find(job => job.id === selectedJobId && isBlocking(job));
    if (selectedBlocker) return selectedBlocker;
    const projectJob = this.app.projectView?.projectId === outcome.projectId ? this.app.projectView.job : null;
    if (projectJob?.id && isBlocking(projectJob)) return jobsById.get(projectJob.id) || projectJob;
    const activeJob = this.app.job?.projectId === outcome.projectId && this.app.isHistoricalJob?.(this.app.job) !== true && isBlocking(this.app.job)
      ? this.app.job : null;
    if (activeJob) return activeJob;
    const blockers = [...jobsById.values()].filter(isBlocking);
    return blockers.length === 1 ? blockers[0] : null;
  }

  async reconcileSubmission(previous) {
    if (this.submissionReconciling || previous?.status !== 'unknown' || !previous?.commandId || !this.reportOutcomeMatchesCurrent(previous)) return;
    this.submissionReconciling = true; this.renderSubmissionStatus();
    let outcome = null;
    try {
      outcome = await this.app.reconcilePendingCommand?.('iteration.submit', previous.projectId);
    } catch (error) {
      outcome = { status: 'unknown', type: 'iteration.submit', projectId: previous.projectId, commandId: previous.commandId, storeId: previous.storeId, reason: error.message || '无法核实原命令状态。' };
    } finally {
      this.submissionReconciling = false;
    }
    if (!this.reportOutcomeMatchesCurrent(previous)) { this.renderSubmissionStatus(); return; }
    const identityMatches = outcome?.type === previous.type
      && outcome?.projectId === previous.projectId
      && outcome?.commandId === previous.commandId
      && (!previous.storeId || outcome?.storeId === previous.storeId);
    if (!identityMatches) {
      outcome = { status: 'unknown', type: 'iteration.submit', projectId: previous.projectId, commandId: previous.commandId, storeId: previous.storeId, reason: '服务没有返回与原命令 ID 和工作区匹配的核实结果；草稿保持不变。' };
    }
    let hasPostSubmitEdits = outcome.status === 'submitted' ? true : undefined;
    if (outcome.status === 'submitted') {
      const key = previous.draftRecordKey || this.reportDraftKey(previous.projectId, previous.storeId, previous.commandId);
      const record = this.pendingReportDrafts.get(key);
      const snapshot = this.app.snapshot || {};
      const recordMatches = record && record.commandId === previous.commandId
        && record.storeId === previous.storeId
        && record.signature === previous.signature
        && record.projectId === this.app.projectId
        && record.draftKey === this.app.draftKey
        && Number(record.publicationRevision) === Number(snapshot.publicationRevision)
        && record.sourceCommit === (snapshot.sourceCommit || snapshot.baseCommit || null);
      if (recordMatches && typeof this.app.clearSubmittedIterationDraft === 'function') {
        try {
          hasPostSubmitEdits = this.app.clearSubmittedIterationDraft(copy(record.submittedDraft));
          const saved = await this.app.saveDraft?.();
          if (saved === false) hasPostSubmitEdits = true;
        } catch {
          hasPostSubmitEdits = true;
        }
        this.pendingReportDrafts.delete(key);
      } else {
        hasPostSubmitEdits = true;
        outcome = { ...outcome, reason: '原命令已接收；当前页面没有可匹配的原申报草稿快照，现有草稿保留供核对。' };
      }
      const proposal = outcome.receipt?.result?.proposal;
      if (proposal?.projectId === previous.projectId && this.app.projectId === previous.projectId) {
        this.app.proposal = proposal; this.app.renderProposal?.(); this.app.startProposalPolling?.();
      }
    }
    const resolved = {
      ...previous, ...outcome,
      status: outcome.status || 'unknown', phase: null,
      projectId: previous.projectId, publicationRevision: previous.publicationRevision,
      sourceCommit: previous.sourceCommit, signature: previous.signature,
      selectionContext: previous.selectionContext, dialogSequence: previous.dialogSequence,
      sequence: previous.sequence, hasPostSubmitEdits,
      reason: outcome.reason || previous.reason,
    };
    this.submissionOutcome = resolved;
    if (resolved.status === 'submitted' && resolved.hasPostSubmitEdits === false) {
      this.reportFingerprint = null;
      this.closeWorkbenchDialog($('#workbench-report-dialog'));
      return;
    }
    if (resolved.status === 'submitted') this.refreshReport(false);
    this.renderSubmissionStatus();
  }

  returnToWorkbenchEdit() {
    this.closeWorkbenchDialog($('#workbench-report-dialog'));
    this.mobilePane = 'inspect'; this.setMobilePane('inspect');
    const editor = $('#edit-text'); editor?.focus?.({ preventScroll: true });
  }

  openMoveEditor() { this.app.notify?.('使用右侧坐标控件或在自由对象上拖动；位置只会加入申报草稿。'); }

  effectiveText() {
    const userText = String($('#edit-text')?.value || '').trim();
    if (this.app.objectsWorkflow?.()) return '';
    const operations = this.operationText();
    const notes = Object.entries(this.app.targetNotes || {}).filter(([, note]) => String(note?.text || '').trim()).map(([id, note]) => `${id === '__project__' ? '当前项目' : `对象 ${id}`}：\n${note.text}`);
    const grouped = notes.length > 1 ? `分目标意见：\n${notes.join('\n\n')}` : userText;
    return [grouped, operations].filter(Boolean).join('\n\n');
  }

  clearCurrentNote() {
    this.app.targetNotes[this.targetKey()] = { ...(this.app.targetNotes[this.targetKey()] || {}), text: '' };
    delete this.app.targetNotes[this.targetKey()];
    const input = $('#edit-text'); if (input) input.value = '';
    this.app.queueDraftSave?.(); this.pushHistory(); this.render();
  }

  savedCheckpointKey(draftKey = this.app.draftKey) { return draftKey ? `${draftKey}:saved` : null; }
  savedCheckpointBackupKey(draftKey = this.app.draftKey) {
    const key = this.savedCheckpointKey(draftKey);
    return key ? `${key}:backup` : null;
  }

  formatCheckpointTime(value) {
    const date = value ? new Date(value) : null;
    if (!date || Number.isNaN(date.getTime())) return '时间未知';
    return new Intl.DateTimeFormat('zh-CN', { dateStyle: 'medium', timeStyle: 'short' }).format(date);
  }

  feedbackCategoryLabel(category) {
    const labels = { general: '一般', bug: '问题', visual: '视觉', behavior: '行为' };
    return String(category || 'general').split(/[\/,]/).map(value => value.trim()).filter(Boolean)
      .map(value => labels[value.toLowerCase()] || value).join(' / ');
  }

  scopeLabel(scope) {
    const value = String(scope || '').trim();
    const normalized = value.toLowerCase().replaceAll('_', '-').replaceAll(' ', '-');
    const labels = {
      shared: '所有同类', 'shared-definition': '所有同类', 'all-instances': '所有同类', 'all-same-type': '所有同类',
      runtime: '运行时生成', 'runtime-generated': '运行时生成', 'runtime-instance': '运行时生成',
      project: '整个项目', scene: '当前场景', instance: '当前实例', 'single-instance': '单个实例', 'current-object': '当前对象',
    };
    return labels[normalized] || value || '当前对象';
  }

  lifecycleLabel(lifecycle) {
    const value = String(lifecycle || '').trim();
    const normalized = value.toLowerCase().replaceAll('_', '-').replaceAll(' ', '-');
    const labels = {
      persistent: '持续存在', session: '本次会话', run: '每局', 'per-run': '每局', 'each-run': '每局',
      round: '每轮', 'per-round': '每轮', 'each-round': '每轮', scene: '场景期间', 'per-scene': '每个场景期间',
      encounter: '战斗期间', 'per-encounter': '每场战斗期间', temporary: '临时对象', transient: '临时对象',
      runtime: '运行时', 'runtime-only': '仅运行时', 'on-trigger': '触发时生成', 'until-round-end': '持续到本轮结束',
    };
    return labels[normalized] || value || '未声明';
  }

  relationTypeLabel(type) {
    const value = String(type || '').trim();
    const normalized = value.toLowerCase().replaceAll('_', '-').replaceAll(' ', '-');
    const labels = {
      association: '关联', associated: '关联', relation: '关联', related: '关联',
      targets: '作用于', target: '作用于', references: '引用', reference: '引用', 'references-object': '引用对象',
      uses: '使用', 'uses-preset': '使用过渡预设', 'used-by': '被使用', usage: '使用处',
      owns: '拥有', 'owned-by': '隶属于', contains: '包含', 'contained-by': '包含于',
      parent: '父级', child: '子级', 'has-child': '包含子对象', 'has-parent': '所属父对象',
      requires: '需要', depends: '依赖', 'depends-on': '依赖', controls: '控制', triggers: '触发',
      spawns: '生成', 'spawned-by': '由其生成', emits: '发射', receives: '接收',
      'selects-environment': '选择环境', 'starts-at': '起始入口', 'transition-to': '切换至', 'transitions-to': '切换至',
      'uses-resource': '使用资源', 'resource-for': '供其使用', 'scene-instance': '场景中的实例', 'has-scene-instance': '场景中的实例',
      'shared-definition': '共享定义', 'uses-definition': '使用此定义的实例', 'usage-instance': '使用此定义的实例', 'reverse-relation': '反向关联',
    };
    return labels[normalized] || value || '关联';
  }

  refreshCheckpointStatus(force = false) {
    const node = $('#workbench-checkpoint-status');
    if (!node) return;
    const draftKey = this.app.draftKey, snapshot = this.app.snapshot, projectId = this.app.projectId;
    if (!draftKey || !snapshot) {
      this.checkpointStatusContext = null;
      this.checkpointStatusSnapshot = null;
      node.textContent = '恢复点按项目与发布版本分别保存；自动保存不会覆盖恢复点。';
      return;
    }
    const context = `${draftKey}|${projectId || ''}|${snapshot.publicationRevision ?? ''}|${this.app.persistenceOK ? 'ready' : 'unavailable'}`;
    if (!force && context === this.checkpointStatusContext && snapshot === this.checkpointStatusSnapshot) return;
    this.checkpointStatusContext = context;
    this.checkpointStatusSnapshot = snapshot;
    const sequence = ++this.checkpointStatusSequence;
    const scope = this.checkpointScopeLabel(snapshot);
    if (!this.app.persistenceOK || !this.app.drafts) {
      node.textContent = '本地存储不可用，无法读取此项目与版本的恢复点。';
      return;
    }
    node.textContent = '正在读取此项目与版本的恢复点…';
    void (async () => {
      try {
        const key = this.savedCheckpointKey(draftKey), backupKey = this.savedCheckpointBackupKey(draftKey);
        const saved = await this.readSavedCheckpointRecord(key, { kind: 'saved-checkpoint', draftKey, projectId, publicationRevision: snapshot.publicationRevision });
        const backup = await this.readSavedCheckpointRecord(backupKey, { kind: 'saved-checkpoint-backup', draftKey, projectId, publicationRevision: snapshot.publicationRevision, backup: true });
        if (sequence !== this.checkpointStatusSequence || this.app.draftKey !== draftKey || this.app.snapshot !== snapshot || this.app.projectId !== projectId) return;
        if (saved.blocked || backup.blocked) {
          node.textContent = '恢复点或首次备份无法安全读取；原始记录已保留。';
          return;
        }
        const checkpoint = saved.record;
        if (!checkpoint) {
          node.textContent = `恢复点：尚未创建 · 作用范围：${scope}。`;
          return;
        }
        const parts = [`当前恢复点：${this.formatCheckpointTime(checkpoint.savedAt || checkpoint.updatedAt)}`, `作用范围：${scope}`];
        if (backup.record) parts.push(`首次备份仍保留：原恢复点 ${this.formatCheckpointTime(backup.record.savedAt || backup.record.updatedAt)} · 备份于 ${this.formatCheckpointTime(backup.record.backedUpAt || backup.record.updatedAt)}`);
        else parts.push('首次覆盖时会保留原恢复点作为备份。');
        node.textContent = parts.join(' · ');
      } catch (error) {
        if (sequence === this.checkpointStatusSequence && this.app.draftKey === draftKey && this.app.snapshot === snapshot && this.app.projectId === projectId) node.textContent = `恢复点状态读取失败：${error.message}`;
      }
    })();
  }

  checkpointScopeLabel(snapshot = this.app.snapshot) {
    const revision = snapshot?.publicationRevision ?? '未知';
    return snapshot?.kind === 'REPAIR'
      ? `当前项目的此返修候选（基于已接受版本 ${revision}）`
      : `当前项目与发布版本 ${revision}`;
  }

  savedCheckpointRecordError(record, { key, draftKey, projectId, publicationRevision, backup = false }) {
    if (!record || typeof record !== 'object' || Array.isArray(record)) return new Error('检查点记录不是 JSON 对象。');
    if (record.key !== key || record.baseDraftKey !== draftKey || record.projectId !== projectId || record.publicationRevision !== publicationRevision) {
      return new Error('检查点的项目、发布版本或存储身份与当前目标不匹配。');
    }
    if (backup ? record.checkpointBackup !== true : record.checkpoint !== true) return new Error(backup ? '备份记录缺少检查点备份标记。' : '保存记录缺少检查点标记。');
    return null;
  }

  rememberCorruptCheckpoint(key, error, { kind, projectId, publicationRevision, draftKey }, raw) {
    const metadata = { kind, projectId, publicationRevision, baseDraftKey: draftKey };
    if (this.app.rememberCorruptDraft) this.app.rememberCorruptDraft(key, error, metadata);
    else this.app.drafts?.rememberCorrupt?.(key, error, { ...metadata, rawFallback: raw });
    this.app.showDraftState?.('已保存检查点或备份无法安全读取；没有覆盖原记录。可在草稿状态区下载原始存档。', true);
    this.app.notify?.('已保存检查点或备份无法安全读取；原记录保持不变。请从草稿状态区导出原始存档后再处理。');
  }

  async readSavedCheckpointRecord(key, { kind, draftKey, projectId, publicationRevision, backup = false }) {
    const drafts = this.app.drafts;
    const rawBefore = typeof drafts?.raw === 'function' ? drafts.raw(key) : undefined;
    let record;
    try { record = await drafts.get(key); }
    catch (error) {
      const raw = typeof drafts?.raw === 'function' ? drafts.raw(key) : rawBefore;
      if (raw !== null && raw !== undefined || drafts?.corruptRecords?.has?.(key)) {
        this.rememberCorruptCheckpoint(key, error, { kind, projectId, publicationRevision, draftKey }, raw);
      } else this.app.notify?.(`读取已保存检查点失败：${error.message}；原记录未覆盖。`);
      return { blocked: true, raw, error };
    }
    const raw = typeof drafts?.raw === 'function' ? drafts.raw(key) : rawBefore;
    if ((raw !== undefined && raw !== null && !record) || (record && this.savedCheckpointRecordError(record, { key, draftKey, projectId, publicationRevision, backup }))) {
      const error = record ? this.savedCheckpointRecordError(record, { key, draftKey, projectId, publicationRevision, backup }) : new Error('检查点原始记录不是有效的 JSON 对象。');
      this.rememberCorruptCheckpoint(key, error, { kind, projectId, publicationRevision, draftKey }, raw);
      return { blocked: true, raw, error };
    }
    return { record: record || null, raw };
  }

  async saveDraft() {
    if (this.pendingPlacementOperationId) return this.app.notify?.('请先完成或取消当前实例放置，再保存草稿。');
    this.persistCurrentNote();
    this.app.captureVisibleFields?.();
    const draftKey = this.app.draftKey, snapshot = this.app.snapshot, projectId = this.app.projectId;
    if (!draftKey || !snapshot || !this.app.persistenceOK) return this.app.notify?.('当前项目与版本没有可用的本地草稿存储。');
    const visible = copy(this.app.readVisibleDraft?.() || {});
    try {
      const currentDraftSaved = await this.app.saveDraft?.();
      if (this.app.draftKey !== draftKey || this.app.snapshot !== snapshot || this.app.projectId !== projectId) return;
      if (currentDraftSaved === false) {
        if (this.app.draftConflictScopeIsCurrent?.()) {
          const message = this.app.pendingDraftConflict?.recovery === true
            ? '恢复点未更新：保留稿比较尚未结束。本页输入仍在页面内；请继续比较并明确选择，或在活动稿和本页内容均未变化且状态可确认时选择“稍后处理”。之后再次点击“创建 / 更新恢复点”。'
            : '恢复点未更新：活动工作稿与本页基线存在差异。当前输入仍在本页。请比较并明确选择要继续使用的完整稿；选择成功返回后，再次点击“创建 / 更新恢复点”。';
          this.app.notify?.(message);
          this.app.openDraftConflict?.();
        } else this.app.notify?.('当前工作草稿没有完成持久保存；未更新已保存检查点。');
        return;
      }
      if (!this.app.persistenceOK) return this.app.notify?.('当前草稿保存失败，未覆盖已保存检查点。');
      const key = this.savedCheckpointKey(draftKey), backupKey = this.savedCheckpointBackupKey(draftKey), publicationRevision = snapshot.publicationRevision;
      const savedResult = await this.readSavedCheckpointRecord(key, { kind: 'saved-checkpoint', draftKey, projectId, publicationRevision });
      if (savedResult.blocked || this.app.draftKey !== draftKey || this.app.snapshot !== snapshot || this.app.projectId !== projectId) return;
      const backupResult = await this.readSavedCheckpointRecord(backupKey, { kind: 'saved-checkpoint-backup', draftKey, projectId, publicationRevision, backup: true });
      if (backupResult.blocked || this.app.draftKey !== draftKey || this.app.snapshot !== snapshot || this.app.projectId !== projectId) return;
      const previous = savedResult.record;
      if (previous) {
        if (typeof globalThis.confirm !== 'function') return this.app.notify?.('此项目和版本已有显式保存检查点；当前环境无法确认覆盖，因此未替换。');
        const backupNote = backupResult.record ? '首次被替换的检查点备份会保持不变。' : '首次被替换的检查点会另存为此项目和版本的备份。';
        if (!globalThis.confirm(`此项目和发布版本已有显式保存检查点。继续会替换它。${backupNote}继续？`)) return;
      }
      const savedAt = new Date().toISOString();
      if (previous && !backupResult.record) {
        const backup = { ...previous, key: backupKey, baseDraftKey: draftKey, projectId, publicationRevision,
          savedAt: previous.savedAt || previous.updatedAt || null, updatedAt: savedAt, backedUpAt: savedAt, checkpoint: false, checkpointBackup: true };
        if (this.app.draftKey !== draftKey || this.app.snapshot !== snapshot || this.app.projectId !== projectId) return;
        if (typeof this.app.drafts.putIfUnchanged === 'function' && backupResult.raw !== undefined) this.app.drafts.putIfUnchanged(backup, backupResult.raw);
        else await this.app.drafts.put(backup);
      }
      if (this.app.draftKey !== draftKey || this.app.snapshot !== snapshot || this.app.projectId !== projectId) return;
      const checkpoint = { ...visible, key, baseDraftKey: draftKey, projectId, publicationRevision, savedAt, updatedAt: savedAt, checkpoint: true, draftRevision: this.app.draftRevision || 0 };
      if (typeof this.app.drafts.putIfUnchanged === 'function' && savedResult.raw !== undefined) this.app.drafts.putIfUnchanged(checkpoint, savedResult.raw);
      else await this.app.drafts.put(checkpoint);
      if (this.app.draftKey === draftKey && this.app.snapshot === snapshot && this.app.projectId === projectId) {
        const backupTime = previous ? (backupResult.record?.savedAt || previous.savedAt || previous.updatedAt || savedAt) : null;
        const message = previous
          ? `已更新当前项目与发布版本 ${publicationRevision ?? '未知'} 的恢复点（${this.formatCheckpointTime(savedAt)}）；首次备份仍保留（${this.formatCheckpointTime(backupTime)}），后续替换不会覆盖它。`
          : `已创建当前项目与发布版本 ${publicationRevision ?? '未知'} 的恢复点（${this.formatCheckpointTime(savedAt)}）；后续自动保存不会覆盖它。`;
        this.checkpointStatusContext = null;
        this.refreshCheckpointStatus(true);
        this.app.showDraftState?.(message);
        this.app.notify?.(message);
      }
    } catch (error) { this.app.notify?.(`保存草稿检查点失败：${error.message}。现有草稿仍保留。`); }
  }

  async restoreSavedDraft() {
    if (this.pendingPlacementOperationId) return this.app.notify?.('请先完成或取消当前实例放置，再恢复已保存草稿。');
    if (!this.app.draftKey || !this.app.persistenceOK) return this.app.notify?.('当前项目没有可用的已保存草稿。');
    if (globalThis.confirm && !globalThis.confirm('将用此项目与版本的显式保存检查点替换当前工作草稿。此操作可撤销。继续？')) return;
    const draftKey = this.app.draftKey, snapshot = this.app.snapshot, projectId = this.app.projectId;
    const generation = this.app.workbenchGeneration, scope = this.historyScope();
    try {
      const key = this.savedCheckpointKey(draftKey);
      const result = await this.readSavedCheckpointRecord(key, { kind: 'saved-checkpoint', draftKey, projectId, publicationRevision: snapshot?.publicationRevision });
      if (this.app.draftKey !== draftKey || this.app.snapshot !== snapshot || this.app.projectId !== projectId || this.app.workbenchGeneration !== generation ||
          (typeof this.app.makeDraftKey === 'function' && this.app.makeDraftKey(snapshot) !== draftKey)) return;
      if (result.blocked) return;
      const draft = result.record;
      if (!draft) return this.app.notify?.('此项目和版本还没有显式保存检查点；当前工作草稿保持不变。');
      this.pushHistory();
      const applied = this.app.applyVisibleDraftReplacement
        ? this.app.applyVisibleDraftReplacement(draft, { draftKey, snapshot, projectId, generation, scope })
        : (this.app.applyVisibleDraft(draft), true);
      if (applied === false) return this.app.notify?.('当前项目或版本已变化；恢复没有应用到其他草稿范围。');
      this.app.draftRevision = Math.max(this.app.draftRevision || 0, draft.draftRevision || 0);
      this.pushHistory(); this.render();
      await this.persistVisibleActionDraft('已恢复显式保存检查点；此版本已写入当前工作稿，可用撤销恢复打开前的内容。',
        '已在页面恢复显式保存检查点，但当前稿未完成持久保存；请处理比较冲突或写入失败。原检查点保持不变。');
    } catch (error) { this.app.notify?.(`恢复草稿失败：${error.message}。现有内容仍留在页面。`); }
  }

  async resetDraft() {
    if (this.pendingPlacementOperationId) return this.app.notify?.('请先完成或取消当前实例放置，再重置草稿。');
    if (!globalThis.confirm?.('重置当前项目和版本的工作草稿？将清除未提交的意见、参数和结构提案。确认后仍可撤销恢复。')) return;
    this.persistCurrentNote(); this.app.captureVisibleFields?.(); this.pushHistory();
    const beforeResetIndex = this.historyIndex;
    const draftKey = this.app.draftKey, snapshot = this.app.snapshot, projectId = this.app.projectId;
    const generation = this.app.workbenchGeneration, scope = this.historyScope();
    const current = this.app.readVisibleDraft?.() || {};
    const resetDraft = { ...copy(current), text: '', values: {}, fields: {}, feedback: [], feedbackMessage: '', feedbackCategory: 'general', feedbackInputs: {}, feedbackInputTargetId: null, legacyUnboundFeedback: { message: '', category: 'general' }, proposalInputs: {}, selectedObjectId: this.app.selectedObjectId || null, targetNotes: {}, structuralProposals: [] };
    const applied = this.app.applyVisibleDraftReplacement
      ? this.app.applyVisibleDraftReplacement(resetDraft, { draftKey, snapshot, projectId, generation, scope })
      : (this.app.applyVisibleDraft?.(resetDraft), true);
    if (applied === false) return this.app.notify?.('当前项目或版本已变化；重置没有应用到其他草稿范围。');
    this.app.dirtyFields?.clear?.(); this.editingReportNoteId = null; this.editingReportNoteBase = null; this.editingReportFeedbackId = null; this.editingReportFeedbackBase = null;
    this.pushHistory();
    this.resetUndoIndex = beforeResetIndex < this.historyIndex ? beforeResetIndex : null;
    this.resetHistoryIndex = this.resetUndoIndex == null ? null : this.historyIndex;
    this.updateHistoryButtons(); this.render();
    await this.persistVisibleActionDraft('当前工作草稿已重置并保存；可用撤销恢复重置前的内容。',
      '页面已重置，但当前稿未完成持久保存；请处理比较冲突或写入失败。页面内仍可撤销恢复重置前内容。');
  }

  async exportDraft() {
    if (this.pendingPlacementOperationId) return this.app.notify?.('请先完成或取消当前实例放置，再导出草稿。');
    this.persistCurrentNote();
    const draftKey = this.app.draftKey, snapshot = this.app.snapshot, projectId = this.app.projectId;
    const currentDraft = copy(this.app.readVisibleDraft?.() || {});
    let savedCheckpoint = null, savedCheckpointBackup = null;
    const stripCheckpointMetadata = record => Object.fromEntries(Object.entries(record || {}).filter(([key]) => !['key', 'baseDraftKey', 'projectId', 'publicationRevision', 'savedAt', 'updatedAt', 'checkpoint', 'checkpointBackup', 'backedUpAt'].includes(key)));
    const savedKey = draftKey ? this.savedCheckpointKey(draftKey) : null;
    const backupKey = draftKey ? this.savedCheckpointBackupKey(draftKey) : null;
    if (draftKey) {
      const savedResult = await this.readSavedCheckpointRecord(savedKey, { kind: 'saved-checkpoint', draftKey, projectId, publicationRevision: snapshot?.publicationRevision });
      if (this.app.draftKey !== draftKey || this.app.snapshot !== snapshot || this.app.projectId !== projectId) return;
      if (savedResult.record) savedCheckpoint = { savedAt: savedResult.record.savedAt || savedResult.record.updatedAt || null, draft: stripCheckpointMetadata(savedResult.record) };
      const backupResult = await this.readSavedCheckpointRecord(backupKey, { kind: 'saved-checkpoint-backup', draftKey, projectId, publicationRevision: snapshot?.publicationRevision, backup: true });
      if (this.app.draftKey !== draftKey || this.app.snapshot !== snapshot || this.app.projectId !== projectId) return;
      if (backupResult.record) savedCheckpointBackup = { savedAt: backupResult.record.savedAt || backupResult.record.updatedAt || null, draft: stripCheckpointMetadata(backupResult.record) };
    }
    const corruptRawRecords = this.app.corruptDraftsForCurrentScope?.() || [];
    const rawFor = key => corruptRawRecords.find(record => record.key === key) || null;
    const payload = { schemaVersion: 'ptah.workbench-draft-export.v1', purpose: '用于备份与人工恢复，不会自动提交或启动 Agent。draft 是当前工作草稿；savedCheckpoint 和 savedCheckpointBackup 是显式保存的独立检查点及备份；corruptRawRecords 保留无法读取的原始存档。', exportedAt: new Date().toISOString(), projectId, projectTitle: this.app.currentProject?.()?.title || null, publicationRevision: snapshot?.publicationRevision, selectedTargetId: this.routeTarget(), targetNotes: copy(this.app.targetNotes), structuralProposals: copy(this.app.structuralProposals), draft: currentDraft, savedCheckpoint, savedCheckpointBackup, savedCheckpointRaw: rawFor(savedKey), savedCheckpointBackupRaw: rawFor(backupKey), corruptRawRecords };
    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json;charset=utf-8' });
    const url = URL.createObjectURL(blob); const link = el('a'); link.href = url; link.download = `ptah-workbench-${projectId || 'project'}-draft.json`; link.click(); URL.revokeObjectURL(url);
    this.app.notify?.(savedCheckpoint ? '当前草稿与显式保存检查点已导出；此文件不会自动提交。' : '当前草稿已导出；没有可附带的显式保存检查点。');
  }

  resetHistory() {
    const hadTransient = this.clearTransientInteractions();
    this.history = []; this.historyIndex = -1; this.historySignature = '';
    this.resetUndoIndex = null; this.resetHistoryIndex = null;
    this.pushHistory();
    if (hadTransient) this.render();
  }
  historyState() {
    const draft = copy(this.app.readVisibleDraft?.() || {});
    return { ...draft, selectedObjectId: this.app.selectedObjectId || null, targetNotes: copy(this.app.targetNotes || {}), structuralProposals: copy(this.app.structuralProposals || []), _historyScope: this.historyScope() };
  }
  historyScope() {
    const snapshot = this.app.snapshot || {};
    return this.app.draftConflictTarget?.(snapshot) || {
      storeId: this.app.storageId?.() || null, key: this.app.draftKey || null,
      projectId: this.app.projectId || null, publicationRevision: snapshot.publicationRevision ?? 'unknown',
      kind: snapshot.kind || null, sourceCommit: snapshot.sourceCommit || null, baseCommit: snapshot.baseCommit || null,
      candidateId: snapshot.candidateId || null, snapshotId: snapshot.id || null,
    };
  }
  historyScopeMatches(state) {
    return !!state?._historyScope && JSON.stringify(state._historyScope) === JSON.stringify(this.historyScope());
  }
  signature(state) { return JSON.stringify({ ...state, selectedObjectId: null, draftRevision: 0 }); }
  pushHistory() {
    if (this.historyRestoring) return;
    const state = this.historyState(), signature = this.signature(state);
    if (signature === this.historySignature) return;
    if (this.historyIndex < this.history.length - 1) {
      this.history = this.history.slice(0, this.historyIndex + 1);
      this.resetUndoIndex = null; this.resetHistoryIndex = null;
    }
    this.history = this.history.slice(0, this.historyIndex + 1); this.history.push(state);
    if (this.history.length > 100) {
      this.history.shift();
      if (this.resetUndoIndex != null) this.resetUndoIndex -= 1;
      if (this.resetHistoryIndex != null) this.resetHistoryIndex -= 1;
      if (this.resetUndoIndex < 0 || this.resetHistoryIndex < 0) { this.resetUndoIndex = null; this.resetHistoryIndex = null; }
    }
    this.historyIndex = this.history.length - 1; this.historySignature = signature; this.updateHistoryButtons();
  }
  queueHistory() {
    if (this.historyTimer != null) globalThis.clearTimeout(this.historyTimer);
    this.historyTimer = globalThis.setTimeout(() => { this.historyTimer = null; this.pushHistory(); }, 350);
  }
  async restoreHistory(index) {
    if (index < 0 || index >= this.history.length) return;
    const state = this.history[index];
    if (!this.historyScopeMatches(state)) {
      this.resetHistory();
      this.app.notify?.('这份撤销/重做记录属于其他项目或版本，已重新以当前草稿建立历史起点。');
      return false;
    }
    const draftKey = this.app.draftKey, snapshot = this.app.snapshot, projectId = this.app.projectId;
    const generation = this.app.workbenchGeneration, scope = this.historyScope();
    if (this.historyTimer != null) { globalThis.clearTimeout(this.historyTimer); this.historyTimer = null; }
    const hadTransient = this.clearTransientInteractions();
    const previousIndex = this.historyIndex;
    if (this.app.draftKey !== draftKey || this.app.snapshot !== snapshot || this.app.projectId !== projectId || this.app.workbenchGeneration !== generation || !this.historyScopeMatches(state)) return false;
    this.historyRestoring = true;
    let applied = false;
    try {
      applied = this.app.applyVisibleDraftReplacement
        ? this.app.applyVisibleDraftReplacement(copy(state), { draftKey, snapshot, projectId, generation, scope })
        : (this.app.applyVisibleDraft?.(copy(state)), true);
      if (applied !== false) { this.historyIndex = index; this.historySignature = this.signature(state); }
    } finally { this.historyRestoring = false; if (hadTransient) this.render(); this.updateHistoryButtons(); }
    if (applied === false) { this.historyIndex = previousIndex; this.historySignature = this.signature(this.history[previousIndex] || {}); return false; }
    await this.persistVisibleActionDraft(previousIndex > index ? '撤销内容已保存' : '重做内容已保存',
      '页面已切换到所选历史版本，但当前稿未完成持久保存；请处理比较冲突或写入失败。');
    return true;
  }
  async persistVisibleActionDraft(successMessage, failureMessage) {
    const draftKey = this.app.draftKey, snapshot = this.app.snapshot, projectId = this.app.projectId;
    const workbenchGeneration = this.app.workbenchGeneration, selectionGeneration = this.app.selectionGeneration;
    const contextMatches = () => this.app.draftKey === draftKey && this.app.snapshot === snapshot &&
      this.app.projectId === projectId && this.app.workbenchGeneration === workbenchGeneration &&
      this.app.selectionGeneration === selectionGeneration &&
      (!draftKey || typeof this.app.makeDraftKey !== 'function' || this.app.makeDraftKey(snapshot) === draftKey);
    const timer = this.app.draftTimer;
    if (timer != null) {
      (this.app.timers || globalThis).clearTimeout?.(timer);
      this.app.draftTimer = null;
    }
    let saved = false;
    try {
      if (draftKey && this.app.persistenceOK !== false && typeof this.app.queueDraftSave === 'function') {
        const result = await this.app.queueDraftSave();
        if (!contextMatches()) return false;
        saved = result !== false && this.app.persistenceOK !== false &&
          !(this.app.pendingDraftConflict?.key === draftKey);
        if (saved && typeof this.app.drafts?.raw === 'function' && typeof this.app.drafts?.readStored === 'function' &&
            typeof this.app.sameDraftContent === 'function') {
          const raw = this.app.drafts.raw(draftKey);
          const stored = raw == null || raw === 'null' ? null : this.app.drafts.readStored(draftKey, raw);
          const visible = this.app.currentDraftRecord?.() || this.app.readVisibleDraft?.();
          saved = !!stored && !!visible && this.app.sameDraftContent(visible, stored);
        }
      }
    } catch {
      if (!contextMatches()) return false;
      saved = false;
    }
    if (!contextMatches()) return false;
    this.app.showDraftState?.(saved ? successMessage : failureMessage, !saved);
    return saved;
  }
  undo() { this.restoreHistory(this.historyIndex - 1); }
  redo() { this.restoreHistory(this.historyIndex + 1); }
  updateHistoryButtons() {
    const resetUndoAvailable = this.resetUndoIndex != null && this.historyIndex === this.resetHistoryIndex && this.historyIndex > 0;
    for (const button of document.querySelectorAll('[data-workbench-action="undo"]')) {
      button.disabled = this.historyIndex <= 0;
      button.classList.toggle('workbench-undo-highlight', resetUndoAvailable && !button.disabled);
      if (resetUndoAvailable && !button.disabled) button.setAttribute('aria-label', '撤销重置，恢复重置前的当前项目与版本草稿');
      else button.removeAttribute('aria-label');
    }
    for (const button of document.querySelectorAll('[data-workbench-action="redo"]')) button.disabled = this.historyIndex < 0 || this.historyIndex >= this.history.length - 1;
  }
}
