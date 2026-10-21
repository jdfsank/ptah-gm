import { mountVisual, referenceModel, releaseVisuals } from './visual-feedback.js';

// Presentation and per-revision drafts only. Business changes use proposal.revise.
export function installVisualPlanning(StudioApp, { $, el, hide, cloneValue, sameValue, ACTIVE, PLANNING }) {
  Object.assign(StudioApp.prototype, {
    visualProjectArchived() {
      return !![...(this.manager?.projects || []), ...(this.workspace?.projects || []), this.projectView?.project]
        .find(project => project?.id === this.projectId && project.archived);
    },
    hasPendingProposalReferences(proposal = this.proposal) {
      const refs = this.proposalRevisionDraft(proposal)?.visualReferences;
      return Array.isArray(refs) && !sameValue(refs, proposal?.visualReferences || []);
    },
    proposalReferenceChange(proposal = this.proposal) {
      if (!this.hasPendingProposalReferences(proposal)) return null;
      const refs = cloneValue(this.proposalRevisionDraft(proposal).visualReferences);
      if (refs.some(ref => !ref.intent?.trim())) throw new Error('请填写每个参考的采纳用途。');
      const assets = [...(proposal.assets || []), ...(this.conceptGenerationRequests || []).map(r => r.asset).filter(Boolean)];
      if (refs.some(ref => assets.find(a => a.id === ref.assetId)?.generation?.provenance && (!ref.preserve?.trim() || !ref.unknown?.trim()))) {
        throw new Error('请为视觉策划参考填写需要保持和尚未确定的内容。');
      }
      return { assetRefs: refs.map(ref => ref.assetId).filter(Boolean), visualReferences: refs };
    },
    canSubmitVisualRevision(proposal = this.proposal) {
      return !!proposal && !this.visualProjectArchived() && ['READY', 'FROZEN', 'FAILED', 'CANCELLED'].includes(proposal.status) &&
        ![this.job, this.projectView?.job, ...(this.workspace?.jobs || [])].some(job => job?.projectId === this.projectId && ACTIVE.has(job.status)) &&
        (!this.snapshot || this.snapshot.publicationRevision === proposal.publicationRevision);
    },
    updateReferenceDraftStatus() {
      const node = $('#visual-reference-draft-status');
      if (node) node.textContent = this.hasPendingProposalReferences() ? '参考草稿有未提交变更。请提交重新策划，或明确撤销；当前方案与冻结输入保持原记录。' : '尚无待提交的参考变更。查看与出图不会改变方案。';
      const results = $('#proposal-visual-results');
      if (results && this.visualPlanning?.open) this.renderReferenceRequestCards(results, this.proposal);
    },
    syncVisualPlanningEntries() {
      const state = this.visualPlanning;
      const expanded = !!(state?.open && state.projectId === this.projectId && state.proposalId === this.proposal?.id && state.revision === this.proposal?.revision);
      for (const entry of document.querySelectorAll('[data-action="open-visual-planning"], #project-visual-entry')) {
        entry.setAttribute('aria-controls', 'proposal-visual-planning');
        entry.setAttribute('aria-expanded', String(expanded));
      }
    },
    renderVisualPlanningEntry(proposal, area) {
      const open = event => this.openVisualPlanning({ reveal: true, entry: event.currentTarget });
      const button = el('button', 'button secondary', '开启视觉策划'); button.type = 'button'; button.dataset.action = 'open-visual-planning';
      button.addEventListener('click', open); (area.querySelector('.ai-info') || area).append(button);
      let shortcut = $('#project-visual-entry');
      if (!shortcut) {
        shortcut = el('button', 'button quiet', '开启视觉策划'); shortcut.id = 'project-visual-entry'; shortcut.type = 'button';
        shortcut.addEventListener('click', open); $('#project-view .heading-actions')?.prepend(shortcut);
      }
      hide(shortcut, !proposal);
      this.syncVisualPlanningEntries();
      const state = this.visualPlanning;
      if (state?.open && state.projectId === this.projectId) {
        const signature = JSON.stringify([proposal.id, proposal.revision, proposal.status, proposal.updatedAt, proposal.discussion]);
        if (state.signature !== signature) this.openVisualPlanning();
      } else hide($('#proposal-visual-planning'));
    },
    async openVisualPlanning({ reveal = false, entry = null } = {}) {
      const proposal = this.proposal;
      if (!proposal?.id || proposal.projectId !== this.projectId) return;
      const context = this.captureSelectionContext();
      const signature = JSON.stringify([proposal.id, proposal.revision, proposal.status, proposal.updatedAt, proposal.discussion]);
      const previous = this.visualPlanning;
      const state = this.visualPlanning = { projectId: this.projectId, proposalId: proposal.id, revision: proposal.revision, signature, open: true, loading: true, archived: this.visualProjectArchived(), entry: entry || previous?.entry };
      if (previous?.proposalId === proposal.id && previous.revision === proposal.revision) state.context = previous.context;
      hide($('#proposal-panel'), false); this.renderVisualPlanningPanel();
      if (reveal) {
        const panel = $('#proposal-visual-planning');
        panel.focus({ preventScroll: true });
        panel.scrollIntoView?.({ block: 'start', behavior: 'instant' });
      }
      try {
        const result = await this.request(`/proposals/${encodeURIComponent(proposal.id)}/visual-context`, { projectId: proposal.projectId });
        if (!this.selectionContextMatches(context) || this.visualPlanning !== state || this.proposal?.id !== proposal.id || this.proposal.revision !== proposal.revision) return;
        if (result.projectId !== proposal.projectId || result.source?.proposalId !== proposal.id || result.source?.proposalRevision !== proposal.revision || !Array.isArray(result.materials)) throw new Error('生成依据的项目或修订不匹配。');
        state.context = result;
        await this.loadVisualPlanningRecords({ render: false });
      } catch (error) { if (this.visualPlanning === state) state.error = `无法读取已提交依据：${error.message}。请刷新核对后再生成。`; }
      finally { if (this.selectionContextMatches(context) && this.visualPlanning === state) { state.loading = false; this.renderVisualPlanningPanel(); } }
    },
    visualPlanningPrompt() {
      const state = this.visualPlanning, context = state?.context;
      if (!context) return '';
      const draft = this.proposalRevisionDraft()?.visualPlanning;
      const ids = sameValue(draft?.source, context.source) && Array.isArray(draft?.materialIds) ? draft.materialIds : context.materials.map(m => m.id);
      return context.promptHeader + context.materials.filter(m => ids.includes(m.id)).map(m => `${m.label}\n${m.text}`).join('\n\n') + context.instructionLabel + (draft?.interpretation || '');
    },
    renderVisualPlanningPanel() {
      const root = $('#proposal-visual-planning'), state = this.visualPlanning, proposal = this.proposal;
      if (!root || !proposal || !state?.open || state.projectId !== this.projectId || state.proposalId !== proposal.id || state.revision !== proposal.revision) return;
      releaseVisuals(root); root.replaceChildren(); hide(root, false);
      root.tabIndex = -1; this.syncVisualPlanningEntries();
      const close = el('button', 'button quiet', '收起视觉策划'); close.type = 'button';
      close.addEventListener('click', () => {
        state.open = false; hide(root); this.syncVisualPlanningEntries(); this.renderWorkflowStages();
        const entry = state.entry?.isConnected ? state.entry : $('#project-visual-entry');
        entry?.focus();
      });
      const refresh = el('button', 'button quiet', '刷新已提交依据'); refresh.type = 'button'; refresh.addEventListener('click', () => this.openVisualPlanning());
      root.append(el('h3', '', '视觉策划 · 概念、风格与构图核对'), close, refresh);
      if (state.loading) root.append(el('p', 'muted', '正在核对服务端已提交记录；没有调用 ImageGen。'));
      if (state.error) root.append(el('p', 'notice', state.error));
      const context = state.context, archived = this.visualProjectArchived();
      if (context) {
        const planned = el('div'); planned.id = 'image-planning-area'; root.append(planned);
        this.renderImagePlanningArea();
        const advanced = el('details', 'legacy-single-image'); advanced.append(el('summary', '', '高级：按整份材料手动生成单图')); root.append(advanced);
        const draft = this.proposalRevisionDraft(proposal)?.visualPlanning || {};
        const selected = new Set(sameValue(draft.source, context.source) && Array.isArray(draft.materialIds) ? draft.materialIds : context.materials.map(m => m.id));
        const materials = el('details', 'visual-materials'); materials.append(el('summary', '', '已提交依据 · 展开核对与选择材料'));
        root.append(el('p', 'meta-line', `项目：${context.projectId} · ${context.source.proposalId} r${context.source.proposalRevision} · 反馈位置：${context.source.feedbackId} · 反馈修订：${context.feedbackRevision ?? '尚未回复'}`));
        const persist = () => {
          this.proposalRevisionDraft(proposal, true).visualPlanning = { source: cloneValue(context.source), materialIds: [...selected], interpretation: instruction.value };
          this.persistProposalInputs(); updatePrompt();
        };
        for (const material of context.materials) {
          const label = el('label', 'check-row'), input = el('input'); input.type = 'checkbox'; input.checked = selected.has(material.id); input.disabled = archived; input.dataset.materialId = material.id;
          input.addEventListener('change', () => { input.checked ? selected.add(material.id) : selected.delete(material.id); persist(); });
          label.append(input, el('span', '', material.label));
          const body = el('pre', 'visual-material-text', material.text); materials.append(label, body);
        }
        const field = el('label', 'field-label', '本次视觉说明（只影响这次出图）'), instruction = el('textarea'); instruction.rows = 3; instruction.maxLength = 8000; instruction.id = 'proposal-visual-instructions'; instruction.value = draft.interpretation || ''; instruction.disabled = archived;
        instruction.addEventListener('input', persist); field.append(instruction);
        const promptDetails = el('details', 'visual-prompt-preview'); promptDetails.append(el('summary', '', '查看本次实际提示词'));
        const prompt = el('textarea'); prompt.readOnly = true; prompt.rows = 8; prompt.setAttribute('aria-label', '本次实际提示词'); promptDetails.append(prompt);
        const count = el('p', 'muted'); count.setAttribute('role', 'status');
        const generate = el('button', 'button secondary', '使用 ImageGen 生成一张检查图'); generate.type = 'button'; generate.id = 'generate-proposal-reference';
        const updatePrompt = () => {
          prompt.value = context.promptHeader + context.materials.filter(m => selected.has(m.id)).map(m => `${m.label}\n${m.text}`).join('\n\n') + context.instructionLabel + instruction.value;
          const length = [...prompt.value].length;
          count.textContent = `实际提示词 ${length} / ${context.promptLimit} 字符。${length > context.promptLimit ? '已超限，请显式减少材料范围；不会截断或另开策划 session。' : '未提交回答、补充及工作台草稿不会自动进入依据。'}`;
          generate.disabled = archived || state.loading || !!state.error || !selected.size || length > context.promptLimit || this.referenceGenerating || this.hasPendingConceptGeneration();
        };
        generate.addEventListener('click', () => { persist(); this.generateProposalReference(); });
        advanced.append(materials, field, promptDetails, count, generate, el('p', 'muted', archived ? '归档项目只允许查看。' : '点击才生成一张，默认低质量、1536×1024。结果仅供检查；玩法规则、数值和运行效果仍以文字与实际游戏验证为准。'));
        updatePrompt();
      }
      const compare = el('div'); root.append(compare);
      const feedbackSummary = [...(proposal.discussion || [])].reverse().find(item => item.role === 'planner')?.summary || proposal.aiSummary || proposal.summary || proposal.document?.summary || '尚未收到策划回复';
      mountVisual(compare, { title: '当前反馈与已采纳参考', status: PLANNING.has(proposal.status) ? '策划执行中；显示上次已提交反馈与已有参考' : '以服务端方案和采纳用途为准',
        rows: [{ label: '当前可查看的反馈', value: feedbackSummary }], references: referenceModel(proposal, this.projectId) }, `visual-compare:${this.projectId}:${proposal.id}:${proposal.revision}`);
      const results = el('div'); results.id = 'proposal-visual-results'; root.append(results); this.renderReferenceRequestCards(results, proposal);
      const status = el('p', 'notice'); status.id = 'visual-reference-draft-status'; root.append(status);
      this.renderReferenceRevisionEditor(root, proposal); this.updateReferenceDraftStatus();
      this.renderPriorProposalInputs(proposal, root, { includeQuestions: false, includeSupplement: false, includeReferences: true });
      if (this.hasPendingProposalReferences(proposal) && !this.canSubmitVisualRevision(proposal) && this.canEnterIteration()) {
        const transfer = el('button', 'button secondary', '转入当前迭代参考草稿'); transfer.type = 'button'; transfer.disabled = archived;
        transfer.addEventListener('click', () => {
          let change; try { change = this.proposalReferenceChange(proposal); } catch (error) { return this.notify(error.message); }
          if (!change) return;
          const assets = [...(proposal.assets || []), ...(this.conceptGenerationRequests || []).map(r => r.asset).filter(Boolean)];
          this.assets = change.assetRefs.map(id => cloneValue(assets.find(a => a.id === id))).filter(Boolean);
          this.referenceIntents = Object.fromEntries(change.visualReferences.map((ref, i) => [ref.assetId || `text-${i}`, ref]));
          this.renderAssets(); this.queueConceptDraftSave(); this.queueDraftSave(); this.notify('参考已放入当前迭代草稿；请在统一申报中核对后提交。冻结记录未改变。');
        }); root.append(transfer);
      }
    },
    hasPendingConceptGeneration() {
      return (this.conceptGenerationRequests || []).some(item => ['QUEUED', 'RUNNING', 'UNCERTAIN', 'LOCAL_PENDING'].includes(item.status)) ||
        (this.referenceBatches || []).some(b => b.projectId === this.projectId && !['COMPLETED', 'CANCELLED'].includes(b.status)) || !!this.proposalRevisionDraft()?.imageBatchIntent;
    },
    visualReferenceGenerationBlocked() {
      const state = this.visualPlanning, context = state?.context;
      if (!context || state.loading || state.error || this.visualProjectArchived() || this.referenceGenerating || this.hasPendingConceptGeneration()) return true;
      const draft = this.proposalRevisionDraft()?.visualPlanning;
      const ids = sameValue(draft?.source, context.source) && Array.isArray(draft?.materialIds) ? draft.materialIds : context.materials.map(m => m.id);
      return !ids.length || [...this.visualPlanningPrompt()].length > context.promptLimit;
    },
    async generateProposalReference() {
      const state = this.visualPlanning, context = state?.context;
      if (!context || state.loading || state.error || this.visualProjectArchived()) return;
      const draft = this.proposalRevisionDraft()?.visualPlanning;
      if (!draft || !sameValue(draft.source, context.source)) return this.notify('请重新核对已提交依据。');
      if ([...this.visualPlanningPrompt()].length > context.promptLimit || !draft.materialIds.length) return this.notify('请显式缩小或选择生成材料。');
      return this.dispatchConceptReference({ requestId: crypto.randomUUID(), sourceText: '', interpretation: draft.interpretation, size: '1536x1024', quality: 'low', source: cloneValue(context.source), materialIds: [...draft.materialIds] });
    },
    renderReferenceRequestCards(root, proposal = null) {
      releaseVisuals(root); root.replaceChildren();
      for (const request of this.conceptGenerationRequests || []) {
        if (request.projectId !== this.projectId) continue;
        const card = el('section', 'reference-editor');
        const refs = this.proposalRevisionDraft(proposal)?.visualReferences ?? proposal?.visualReferences ?? [];
        const selected = proposal ? refs.some(r => r.assetId === request.asset?.id) : this.assets.some(a => a.id === request.asset?.id);
        const source = request.sourceSnapshot?.source || request.request?.source;
        const provenance = source ? `${request.projectId} · ${source.proposalId} r${source.proposalRevision} · ${source.feedbackId}` : `${request.projectId} · 初始概念`;
        card.append(el('p', 'meta-line', `图片原来源：${provenance}`));
        if (proposal && source && !sameValue(source, this.visualPlanning?.context?.source)) card.append(el('p', 'notice', '此图来源与当前生成依据不同；继续保留原来源，不视为新版方案。'));
        const adopted = proposal?.visualReferences?.some(ref => ref.assetId === request.asset?.id) && !this.hasPendingProposalReferences(proposal);
        const selectedText = proposal ? adopted ? '已纳入当前方案；图片仍保留生成时的原来源。' : '已选入本修订参考草稿；尚未提交本轮。' : '此图已选入当前草稿；尚未提交本轮。';
        card.append(el('p', '', `${({ QUEUED: '排队中', RUNNING: '生成中', GENERATED: '概念图已保存', FAILED: '请求未执行', UNCERTAIN: '待核实', LOCAL_PENDING: '等待收单' })[request.status] || request.status} · ${request.status === 'GENERATED' ? (selected ? selectedText : '仅供检查；当前草稿尚未选作参考，历史采纳以各版冻结记录为准。') : request.message || ''}`));
        if (['UNCERTAIN', 'LOCAL_PENDING'].includes(request.status) && request.request) {
          const recover = el('button', 'button quiet', '使用原请求编号核实收单'); recover.type = 'button'; recover.disabled = this.referenceGenerating || this.visualProjectArchived();
          card.append(el('p', 'muted', '沿用原编号和原文；服务未收单时会生成一次，已收单只返回原记录。'));
          recover.addEventListener('click', () => this.recoverConceptRequest(request)); card.append(recover);
        }
        if (request.asset) {
          mountVisual(card, { title: request.sourceSnapshot?.imagePlan?.title || '生成候选', rawText: source ? undefined : request.request?.sourceText,
            rows: request.sourceSnapshot?.imagePlan ? [{ label: '计划用途（未经读图验证）', value: request.sourceSnapshot.imagePlan.quickDescription }, { label: '覆盖概念', value: request.sourceSnapshot.imagePlan.concepts.join('、') }] : [{ label: '本次视觉说明', value: request.request?.interpretation }],
            references: referenceModel({ assets: [request.asset], visualReferences: [{ assetId: request.asset.id, intent: selected ? selectedText : '当前草稿尚未选作参考；仅供检查。' }] }, this.projectId),
            details: [{ label: '图片原来源', value: provenance }, { label: '请求编号', value: request.id }, { label: '模型', value: request.model }, { label: '提示词版本', value: request.promptVersion }, { label: '已提交依据快照', value: request.sourceSnapshot }, { label: '实际提示词', value: request.prompt }] }, `generated:${this.projectId}:${request.id}`);
          const use = el('button', 'button secondary', selected ? adopted ? '此图已纳入方案' : '此图已选入草稿' : proposal ? '纳入下轮参考' : '选作参考并填写用途'); use.type = 'button'; use.dataset.action = 'select-concept-reference'; use.disabled = selected || this.visualProjectArchived();
          use.addEventListener('click', () => {
            if (proposal) {
              if (this.proposal?.id !== proposal.id || this.proposal.revision !== proposal.revision) return;
              const current = cloneValue(this.proposalRevisionDraft(proposal)?.visualReferences ?? proposal.visualReferences ?? []);
              if (current.filter(r => r.assetId).length >= 6 || current.length >= 12) return this.notify('每轮最多六张参考、十二条用途。');
              current.push({ assetId: request.asset.id, intent: '', targetObjectIds: [], preserve: '', unknown: '' });
              this.proposalRevisionDraft(proposal, true).visualReferences = current; this.persistProposalInputs(); this.renderVisualPlanningPanel();
              const editor = $('#proposal-visual-planning .reference-revision-editor'); if (editor) editor.open = true;
            } else {
              if (this.assets.length >= 6) return this.notify('每轮最多六张参考。');
              this.assets.push(cloneValue(request.asset)); this.referenceIntents[request.asset.id] = { assetId: request.asset.id, intent: '', targetObjectIds: [], preserve: '', unknown: '' };
              this.renderAssets(); this.queueConceptDraftSave(); this.renderConceptReferenceResults();
            }
          }); card.append(use);
        }
        root.append(card);
      }
    },
  });
}
