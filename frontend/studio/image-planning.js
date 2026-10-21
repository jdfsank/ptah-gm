import { mountVisual, releaseVisuals } from './visual-feedback.js';

const imageKeys = ['id', 'title', 'quickDescription', 'purpose', 'concepts', 'materialIds', 'subject', 'composition', 'style', 'preserve', 'unknown'];
const labels = { title: '短标题', quickDescription: '计划用途（80 字以内，未经读图验证）', purpose: '本图检查目的', subject: '主体', composition: '构图', style: '本图风格', preserve: '必须保持', unknown: '未知项（不从图片推断）' };
const limits = { title: 40, quickDescription: 80, purpose: 200, subject: 2000, composition: 2000, style: 1000, preserve: 2000, unknown: 1000 };
const pendingPlans = new Set(['QUEUED', 'RUNNING', 'UNCERTAIN', 'LOCAL_PENDING']);
const terminalBatches = new Set(['COMPLETED', 'CANCELLED']);
const statusNames = { WAITING: '待生成', QUEUED: '排队中', RUNNING: '生成中', GENERATED: '已生成', FAILED: '失败', UNCERTAIN: '待核实', BLOCKED: '来源变化', CANCELLED: '已取消', SKIPPED: '已跳过', PAUSED: '已暂停', COMPLETED: '已完成', READY: '规划完成', LOCAL_PENDING: '等待收单' };

export function imageInstructions(image, sharedStyle) {
  const fields = [['title', 'Plan title'], ['quickDescription', 'Planned use (not observed verification)'], ['purpose', 'Inspection purpose'], ['subject', 'Subject'], ['composition', 'Composition'], ['style', 'Style'], ['preserve', 'Must preserve'], ['unknown', 'Unknowns (do not invent)']];
  return `Shared style: ${sharedStyle}\n${fields.map(([key, label]) => `${label}: ${image[key]}`).join('\n')}`;
}

export function installImagePlanning(StudioApp, { $, el, cloneValue, sameValue }) {
  Object.assign(StudioApp.prototype, {
    async loadVisualPlanningRecords({ render = true } = {}) {
      if (!this.visualPlanning || (!this.visualPlanning.open && !this.hasPendingImageWorkflow())) return;
      const selection = this.captureSelectionContext(), state = this.visualPlanning;
      try {
        const [plans, batches] = await Promise.all([this.request('/visual-plans'), this.request('/concept-reference-batches')]);
        if (!this.selectionContextMatches(selection) || this.visualPlanning !== state) return;
        state.plans = plans.plans || []; this.referenceBatches = batches.batches || [];
        state.recordsError = null;
        if (render) this.renderImagePlanningArea();
      } catch (error) {
        if (this.selectionContextMatches(selection) && this.visualPlanning === state) {
          state.recordsError = `规划和批次记录暂不可读取：${error.message}`;
          if (render) this.renderImagePlanningArea();
        }
      }
      this.scheduleConceptReferencePoll();
    },
    imagePlanningDraft() {
      const context = this.visualPlanning?.context;
      if (!context) return null;
      const owner = this.proposalRevisionDraft() || {};
      const latest = [...(this.visualPlanning.plans || [])].reverse().find(p => p.status === 'READY' && sameValue(p.source, context.source));
      if (!sameValue(this.visualPlanning.imageDraft?.source, context.source)) {
        this.visualPlanning.priorImagePlanning = cloneValue(owner.priorImagePlanning || []);
        if (owner.imagePlanning?.images?.length) {
          if (!sameValue(owner.imagePlanning.source, context.source)) this.visualPlanning.priorImagePlanning.push(cloneValue(owner.imagePlanning));
        }
        this.visualPlanning.priorImagePlanning = this.visualPlanning.priorImagePlanning.slice(-12);
        this.visualPlanning.imageDraft = sameValue(owner.imagePlanning?.source, context.source) ? cloneValue(owner.imagePlanning) :
          { source: cloneValue(context.source), planId: null, sharedStyle: '', images: [] };
      }
      const draft = this.visualPlanning.imageDraft;
      // Never replace user edits when a newly completed planning record arrives.
      if (latest && draft.planId !== latest.id && !draft.edited) {
        Object.assign(draft, { planId: latest.id, sharedStyle: latest.result.sharedStyle,
          images: latest.result.images.map(i => ({ ...cloneValue(i), selected: true })), coverage: cloneValue(latest.result.coverage) });
      }
      return draft;
    },
    hasPendingImageWorkflow() {
      const owner = this.proposalRevisionDraft();
      return (this.referenceBatches || []).some(b => b.projectId === this.projectId && !terminalBatches.has(b.status)) ||
        !!owner?.imageBatchIntent || (this.visualPlanning?.plans || []).some(p => pendingPlans.has(p.status));
    },
    async requestImagePlan(recover = false) {
      const state = this.visualPlanning, context = state?.context, selection = this.captureSelectionContext();
      if (!context || this.visualProjectArchived() || state.planSubmitting || state.loading || state.error || state.recordsError) return;
      const owner = this.proposalRevisionDraft(this.proposal, true);
      if (!recover && ((state.plans || []).some(p => pendingPlans.has(p.status)) || owner.imagePlanIntent)) return this.notify('请先查看或核实原视觉规划请求。');
      const body = recover ? owner.imagePlanIntent : { requestId: crypto.randomUUID(), source: cloneValue(context.source), preferencesRevision: this.sessionPreferences?.revision ?? 0 };
      if (!body) return;
      owner.imagePlanIntent = cloneValue(body); this.persistProposalInputs();
      state.planSubmitting = true; this.renderImagePlanningArea();
      try {
        if (await this.saveConceptDraft(this.projectId) !== true) throw new Error('请求编号未能保存，尚未提交视觉规划');
        if (!this.selectionContextMatches(selection)) return;
        const result = await this.request('/visual-plans', { method: 'POST', token: true, body });
        if (!this.selectionContextMatches(selection) || this.visualPlanning !== state) return;
        delete owner.imagePlanIntent; this.persistProposalInputs();
        state.plans = [...(state.plans || []).filter(p => p.id !== result.plan.id), result.plan];
      } catch (error) {
        if (this.selectionContextMatches(selection)) {
          if (error.status >= 400 && error.status < 500) { delete owner.imagePlanIntent; this.persistProposalInputs(); }
          this.notify(`视觉规划尚未完成：${error.message}。未知结果请核实原编号。`);
        }
      } finally {
        state.planSubmitting = false;
        if (this.selectionContextMatches(selection) && this.visualPlanning === state) { this.renderImagePlanningArea(); this.scheduleConceptReferencePoll(); }
      }
    },
    imagePlanningPrompt(image, draft = this.imagePlanningDraft()) {
      const context = this.visualPlanning?.context;
      if (!context || !draft) return '';
      return context.promptHeader + (context.imageMaterials || []).filter(m => image.materialIds.includes(m.id)).map(m => `${m.label}\n${m.text}`).join('\n\n') + context.instructionLabel + imageInstructions(image, draft.sharedStyle);
    },
    imagePlanError(image) {
      for (const [key, max] of Object.entries(limits)) if (!image[key]?.trim() || [...image[key]].length > max) return `请填写${labels[key]}（最多 ${max} 字）`;
      if (!image.concepts?.length || image.concepts.length > 12 || image.concepts.some(c => !c.trim() || [...c].length > 120)) return '请填写一至十二个覆盖概念，每项最多 120 字';
      if (!image.materialIds?.length || image.materialIds.length > 100) return '请选择一至一百项相关已提交材料';
      if ([...this.imagePlanningPrompt(image)].length > (this.visualPlanning?.context?.promptLimit || 32000)) return '本图提示词超限，请显式缩小材料范围或拆图';
      return '';
    },
    async submitImageBatch(recover = false) {
      const state = this.visualPlanning, draft = this.imagePlanningDraft(), selection = this.captureSelectionContext();
      if (!draft || this.visualProjectArchived() || state.batchSubmitting || state.recordsError || state.error || state.loading) return;
      const owner = this.proposalRevisionDraft(this.proposal, true);
      if (!recover && this.hasPendingConceptGeneration()) return this.notify('请先处理原图像请求或批次。');
      const selected = draft.images.filter(i => i.selected);
      if (!recover && (!selected.length || selected.length > 6)) return this.notify('每批请选择一至六张图片。');
      if (!recover) for (const image of selected) { const error = this.imagePlanError(image); if (error) return this.notify(`${image.title || '未命名图片'}：${error}`); }
      const body = recover ? owner.imageBatchIntent : { requestId: crypto.randomUUID(), source: cloneValue(draft.source), visualPlanId: draft.planId,
        sharedStyle: draft.sharedStyle, images: selected.map(image => Object.fromEntries(imageKeys.map(key => [key, cloneValue(image[key])]))) };
      if (!body) return;
      owner.imageBatchIntent = cloneValue(body); this.persistProposalInputs();
      state.batchSubmitting = true; this.renderImagePlanningArea();
      try {
        if (await this.saveConceptDraft(this.projectId) !== true) throw new Error('批次编号未能保存，尚未提交生成');
        if (!this.selectionContextMatches(selection)) return;
        const result = await this.request('/concept-reference-batches', { method: 'POST', token: true, body });
        if (!this.selectionContextMatches(selection) || this.visualPlanning !== state) return;
        delete owner.imageBatchIntent; this.persistProposalInputs();
        this.referenceBatches = [...(this.referenceBatches || []).filter(b => b.id !== result.batch.id), result.batch];
      } catch (error) {
        if (this.selectionContextMatches(selection)) {
          if (error.status >= 400 && error.status < 500) { delete owner.imageBatchIntent; this.persistProposalInputs(); }
          this.notify(`批次提交未完成：${error.message}。未知结果请用原编号核实。`);
        }
      } finally {
        state.batchSubmitting = false;
        if (this.selectionContextMatches(selection) && this.visualPlanning === state) { this.renderImagePlanningArea(); this.scheduleConceptReferencePoll(); }
      }
    },
    async controlImageBatch(batch, action) {
      if (this.visualProjectArchived()) return;
      const selection = this.captureSelectionContext();
      try {
        const result = await this.request(`/concept-reference-batches/${encodeURIComponent(batch.id)}/${action}`, { method: 'POST', token: true, body: {} });
        if (!this.selectionContextMatches(selection)) return;
        this.referenceBatches = (this.referenceBatches || []).map(b => b.id === batch.id ? result.batch : b);
        this.renderImagePlanningArea(); this.scheduleConceptReferencePoll();
      } catch (error) { if (this.selectionContextMatches(selection)) this.notify(error.message); }
    },
    renderImagePlanningArea() {
      const root = $('#image-planning-area'), state = this.visualPlanning, context = state?.context;
      if (!root || !context || !state.open) return;
      if (!this.visualProjectArchived() && root.contains(document.activeElement) && ['TEXTAREA', 'INPUT'].includes(document.activeElement.tagName)) return;
      const expanded = new Set([...root.querySelectorAll('details[open][data-detail-key]')].map(d => d.dataset.detailKey));
      releaseVisuals(root); root.replaceChildren();
      const draft = this.imagePlanningDraft(), archived = this.visualProjectArchived(), owner = this.proposalRevisionDraft() || {};
      const persist = () => {
        draft.edited = true;
        const record = this.proposalRevisionDraft(this.proposal, true);
        record.imagePlanning = cloneValue(draft);
        record.priorImagePlanning = cloneValue(state.priorImagePlanning || []);
        this.persistProposalInputs();
      };
      const button = (title, action, disabled = archived) => { const node = el('button', 'button quiet', title); node.type = 'button'; node.disabled = disabled; node.addEventListener('click', action); return node; };
      const request = button('规划本轮图片', () => this.requestImagePlan(), archived || state.loading || !!state.error || !!state.recordsError || state.planSubmitting || !!owner.imagePlanIntent || (state.plans || []).some(p => pendingPlans.has(p.status)));
      request.id = 'plan-proposal-images'; root.append(request);
      if (owner.imagePlanIntent) root.append(button('使用原编号核实视觉规划', () => this.requestImagePlan(true), archived || state.planSubmitting));
      if (owner.imageBatchIntent) root.append(button('使用原编号核实图片批次', () => this.submitImageBatch(true), archived || state.batchSubmitting));
      if (state.recordsError) root.append(el('p', 'notice', state.recordsError));
      for (const plan of state.plans || []) {
        const current = sameValue(plan.source, context.source);
        const line = el('p', 'meta-line', `${statusNames[plan.status] || plan.status} · ${plan.source?.proposalId} r${plan.source?.proposalRevision} · ${plan.source?.feedbackId}${current ? '' : ' · 历史来源，不能作为当前依据'} · ${plan.message || ''}`);
        root.append(line);
        if (current && plan.status === 'READY' && draft.planId !== plan.id) root.append(button('采用这份分图建议（替换本地分图草稿）', () => {
          Object.assign(draft, { planId: plan.id, sharedStyle: plan.result.sharedStyle,
            images: plan.result.images.map(i => ({ ...cloneValue(i), selected: true })), coverage: cloneValue(plan.result.coverage), edited: true });
          persist(); this.renderImagePlanningArea();
        }));
        if (plan.attemptId && pendingPlans.has(plan.status)) {
          for (const [action, label] of [['cancel', '停止视觉规划'], ['reconcile', '核实视觉规划执行']]) root.append(button(label, async () => {
            try { await this.sendCommand(`execution.${action}`, { attemptId: plan.attemptId, ownerRef: { kind: 'visual-plan', id: plan.id } }); await this.loadVisualPlanningRecords(); }
            catch (error) { this.notify(error.message); }
          }));
        }
      }
      root.append(el('h4', '', draft.images.length ? `建议生成 ${draft.images.length} 张 · 可调整后分批确认` : '先规划图片，再确认生成'));
      const sharedLabel = el('label', 'field-label', '共同风格（本次视觉说明）'), shared = el('textarea'); shared.rows = 2; shared.maxLength = 2000; shared.value = draft.sharedStyle; shared.disabled = archived;
      shared.addEventListener('input', () => { draft.sharedStyle = shared.value; persist(); for (const update of updates) update(); updateBatch(); }); sharedLabel.append(shared); root.append(sharedLabel);
      const grid = el('div', 'image-plan-grid'), updates = [];
      const batchButton = button('', () => this.submitImageBatch()); batchButton.id = 'generate-image-batch'; batchButton.className = 'button secondary';
      const updateBatch = () => {
        const selected = draft.images.filter(i => i.selected); batchButton.textContent = `确认生成选中的 ${selected.length} 张`;
        batchButton.disabled = archived || state.loading || !!state.error || !!state.recordsError || state.batchSubmitting || this.hasPendingConceptGeneration() || !selected.length || selected.length > 6 || selected.some(i => this.imagePlanError(i));
      };
      draft.images.forEach((image, index) => {
        const card = el('section', 'image-plan-editor'); card.dataset.imageId = image.id;
        const summary = el('div'); card.append(summary);
        const item = [...(this.referenceBatches || [])].reverse().filter(b => sameValue(b.source, draft.source)).flatMap(b => b.items || []).find(i => i.imageId === image.id);
        mountVisual(summary, { title: `${index + 1}. ${image.title || '待命名图片'}`, status: statusNames[item?.status] || '待确认',
          rows: [{ label: '计划用途', value: image.quickDescription || '请填写一句话用途' }, { label: '覆盖概念', value: image.concepts.join('、') }] }, `image-plan:${this.projectId}:${draft.planId}:${image.id}`);
        const selectedLabel = el('label', 'check-row'), selected = el('input'); selected.type = 'checkbox'; selected.checked = image.selected; selected.disabled = archived; selected.dataset.action = 'select-planned-image';
        selected.addEventListener('change', () => { image.selected = selected.checked; persist(); updateBatch(); }); selectedLabel.append(selected, el('span', '', '本批生成此图')); card.append(selectedLabel);
        const controls = el('div', 'image-plan-actions');
        controls.append(button('上移', () => { [draft.images[index - 1], draft.images[index]] = [image, draft.images[index - 1]]; persist(); this.renderImagePlanningArea(); }, archived || index === 0),
          button('下移', () => { [draft.images[index + 1], draft.images[index]] = [image, draft.images[index + 1]]; persist(); this.renderImagePlanningArea(); }, archived || index === draft.images.length - 1),
          button('拆分此图', () => { draft.images.splice(index + 1, 0, { ...cloneValue(image), id: `image-${crypto.randomUUID().slice(0, 20)}`, title: `${image.title.slice(0, 34)}·拆分`, selected: false }); persist(); this.renderImagePlanningArea(); this.notify('已复制为第二张图，请分别调整两图的目的、概念与材料后选择生成。'); }, archived || draft.images.length >= 12),
          button('删除', () => { draft.images.splice(index, 1); persist(); this.renderImagePlanningArea(); })); card.append(controls);
        const editor = el('details', 'image-plan-details'); editor.append(el('summary', '', '编辑本图、材料及实际提示词'));
        editor.dataset.detailKey = image.id;
        for (const [key, label] of Object.entries(labels)) {
          const field = el('label', 'field-label', label), input = el('textarea'); input.rows = ['title', 'quickDescription', 'purpose'].includes(key) ? 2 : 3; input.maxLength = limits[key]; input.value = image[key]; input.disabled = archived; input.dataset.imageField = key;
          input.addEventListener('input', () => { image[key] = input.value; persist(); update(); updateBatch(); }); field.append(input); editor.append(field);
          input.addEventListener('blur', () => queueMicrotask(() => this.renderImagePlanningArea()));
        }
        const conceptsLabel = el('label', 'field-label', '覆盖概念（每行一个）'), concepts = el('textarea'); concepts.rows = 2; concepts.value = image.concepts.join('\n'); concepts.disabled = archived;
        concepts.addEventListener('input', () => { image.concepts = concepts.value.split('\n').map(s => s.trim()).filter(Boolean); persist(); update(); updateBatch(); }); conceptsLabel.append(concepts); editor.append(conceptsLabel);
        const materials = el('details', 'visual-materials'); materials.append(el('summary', '', '选择本图相关已提交材料'));
        materials.dataset.detailKey = `${image.id}:materials`;
        for (const material of context.imageMaterials || []) {
          const label = el('label', 'check-row'), input = el('input'); input.type = 'checkbox'; input.checked = image.materialIds.includes(material.id); input.disabled = archived; input.dataset.fragmentId = material.id;
          input.addEventListener('change', () => { image.materialIds = input.checked ? [...image.materialIds, material.id] : image.materialIds.filter(id => id !== material.id); persist(); update(); updateBatch(); });
          label.append(input, el('span', '', `${material.label} · ${[...material.text].length} 字`));
          const body = el('details'); body.append(el('summary', '', '查看原文'), el('pre', 'visual-material-text', material.text)); materials.append(label, body);
        }
        const prompt = el('textarea'); prompt.readOnly = true; prompt.rows = 6; prompt.setAttribute('aria-label', `${image.title}实际提示词`);
        const count = el('p', 'muted'); count.setAttribute('role', 'status');
        const update = () => { prompt.value = this.imagePlanningPrompt(image, draft); count.textContent = `实际提示词 ${[...prompt.value].length} / ${context.promptLimit} 字符。${this.imagePlanError(image) || '仅包含所选原文与本次视觉说明。'}`; };
        updates.push(update); editor.append(materials, el('label', 'field-label', '本图实际提示词'), prompt, count); card.append(editor); grid.append(card); update();
      });
      root.append(grid, button('添加一张图片', () => {
        draft.images.push({ id: `image-${crypto.randomUUID().slice(0, 20)}`, title: `图片 ${draft.images.length + 1}`, quickDescription: '', purpose: '', concepts: [], materialIds: (context.imageMaterials || []).some(m => m.id === 'original') ? ['original'] : [], subject: '', composition: '', style: '', preserve: '', unknown: '', selected: true });
        persist(); this.renderImagePlanningArea();
      }, archived || draft.images.length >= 12), batchButton);
      updateBatch();
      root.append(el('p', 'muted', '确认后逐张生成，每批最多六张，默认低质量、1536×1024。打开、刷新、编辑和切换项目不调用 ImageGen。'));
      for (const prior of state.priorImagePlanning || []) {
        const history = el('details'); history.append(el('summary', '', `历史分图草稿 · r${prior.source.proposalRevision} · ${prior.source.feedbackId}（原来源）`));
        for (const image of prior.images) history.append(el('p', '', `${image.title}：${image.quickDescription}`), el('pre', 'visual-material-text', imageInstructions(image, prior.sharedStyle)));
        root.append(history);
      }
      if (draft.coverage?.length) {
        const coverage = el('details'); coverage.append(el('summary', '', '查看原分图建议的覆盖关系（编辑后请重新核对）'));
        for (const row of draft.coverage) coverage.append(el('p', '', `${row.concept} → ${row.imageIds.map(id => draft.images.find(i => i.id === id)?.title || '已移除图片').join('、') || '后续安排'}：${row.reason}`));
        root.append(coverage);
      }
      for (const batch of this.referenceBatches || []) {
        const section = el('section', 'reference-editor');
        section.append(el('h4', '', `图片批次 · ${statusNames[batch.status] || batch.status}`), el('p', 'meta-line', `${batch.source?.proposalId} r${batch.source?.proposalRevision} · ${batch.source?.feedbackId} · ${batch.id}`), el('p', '', batch.message || ''));
        for (const item of batch.items || []) section.append(el('p', '', `${item.imagePlan.title} · ${statusNames[item.status] || item.status} · 计划用途：${item.imagePlan.quickDescription}`));
        if (!terminalBatches.has(batch.status)) section.append(button('暂停批次', () => this.controlImageBatch(batch, 'pause')), button('继续余下图片（跳过已确认失败项）', () => this.controlImageBatch(batch, 'resume')), button('取消未派发图片', () => this.controlImageBatch(batch, 'cancel')));
        root.append(section);
      }
      for (const detail of root.querySelectorAll('details[data-detail-key]')) detail.open = expanded.has(detail.dataset.detailKey);
    },
  });
}
