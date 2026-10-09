const API = '/api';
const DRAFT_DB = 'ptah-studio-drafts-v1';
const TEMPLATE_FIELDS = ['goalCount', 'durationSeconds', 'playerSpeed'];
const LABELS = { goalCount: '收集目标', durationSeconds: '时限（秒）', playerSpeed: '移动速度' };
const PLANNING = new Set(['PLANNING', 'PLANNING_CANCELLING', 'PLANNING_UNCERTAIN']);
const JOB_LABELS = { QUEUED: '排队中', DISPATCHING: '准备制作', RUNNING: '制作中', VERIFYING: '运行验证', PROJECTING: '整理结果', READY_FOR_REVIEW: '等待你审阅', PUBLISHED: '已发布', REJECTED: '已拒绝', FAILED: '制作失败', BLOCKED: '暂时受阻', UNCERTAIN: '状态待核实', CANCEL_REQUESTED: '正在请求取消', CANCELLING: '正在停止', CANCELLED: '已取消', PLANNING: '策划中', PLANNING_CANCELLING: '正在停止策划', PLANNING_UNCERTAIN: '策划状态待核实' };
const TERMINAL = new Set(['PUBLISHED', 'REJECTED', 'FAILED', 'BLOCKED', 'CANCELLED']);
const ACTIVE = new Set(['QUEUED', 'DISPATCHING', 'RUNNING', 'VERIFYING', 'PROJECTING', 'READY_FOR_REVIEW', 'CANCEL_REQUESTED', 'CANCELLING', 'UNCERTAIN']);
const REQUIRED_CAPABILITIES = {
  interactiveFrontendConfirmation: '前端确认记录', sessionDispatch: '制作 session 调度',
  godotVerification: 'Godot 运行验证', semanticProjection: '结果语义回流',
};
const $ = (selector, root = document) => root.querySelector(selector);
const el = (tag, className, text) => { const node = document.createElement(tag); if (className) node.className = className; if (text != null) node.textContent = String(text); return node; };
const hide = (node, value = true) => { if (node) node.classList.toggle('hidden', value); };
const setStatus = (node, status, label = null) => { if (!node) return; node.textContent = label || JOB_LABELS[status] || status || '未知'; node.className = `status-pill ${String(status || '').toLowerCase().replaceAll('_', '-')}`; };
const safeJson = async response => { const body = await response.text(); let data = {}; try { data = body ? JSON.parse(body) : {}; } catch { data = { message: body.slice(0, 500) }; } if (!response.ok) { const error = new Error(data.message || data.error || `服务返回 ${response.status}`); error.status = response.status; error.body = data; throw error; } return data; };

export class DraftStore {
  constructor(indexedDBImpl = globalThis.indexedDB) { this.impl = indexedDBImpl; this.db = null; this.error = null; }
  async open() {
    if (!this.impl) throw new Error('此浏览器没有可用的本地草稿存储。');
    if (this.db) return this.db;
    this.db = await new Promise((resolve, reject) => {
      const request = this.impl.open(DRAFT_DB, 1);
      request.onupgradeneeded = () => request.result.createObjectStore('drafts', { keyPath: 'key' });
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error || new Error('无法打开草稿存储。'));
      request.onblocked = () => reject(new Error('草稿存储正被其他页面占用。'));
    });
    return this.db;
  }
  async get(key) { const db = await this.open(); return new Promise((resolve, reject) => { const req = db.transaction('drafts').objectStore('drafts').get(key); req.onsuccess = () => resolve(req.result || null); req.onerror = () => reject(req.error); }); }
  async put(value) { const db = await this.open(); return new Promise((resolve, reject) => { const req = db.transaction('drafts', 'readwrite').objectStore('drafts').put(value); req.onsuccess = () => resolve(value); req.onerror = () => reject(req.error || new Error('草稿保存失败。')); }); }
}

export class StudioApp {
  constructor({ fetchImpl = globalThis.fetch?.bind(globalThis), documentImpl = globalThis.document, timers = globalThis } = {}) {
    this.fetch = fetchImpl; this.document = documentImpl; this.timers = timers; this.token = null; this.session = null; this.workspace = null;
    this.proposal = null; this.packet = null; this.job = null; this.snapshot = null; this.capabilities = null; this.candidates = [];
    this.assets = []; this.pollHandle = null; this.drafts = new DraftStore(); this.draftRevision = 0; this.draftKey = null; this.persistenceOK = false;
    this.draftTimer = null; this.destroyed = false; this.bound = false; this.selectionBusy = false; this.workbenchLoad = null; this.workbenchGeneration = 0;
    this.proposalPollHandle = null; this.proposalGeneration = 0; this.workflow = null; this.selectedObjectId = null; this.feedback = []; this.dirtyFields = new Set(); this.fieldDraftValues = {};
    this.selectionGeneration = 0; this.conceptGeneration = 0; this.proposalMutationGeneration = 0; this.jobLoadGeneration = 0; this.jobMutationGeneration = 0; this.retryOutcomeUnknown = null;
  }
  async request(path, { method = 'GET', body, token = false } = {}) {
    const headers = { Accept: 'application/json' };
    if (body !== undefined) headers['Content-Type'] = 'application/json';
    if (token) { if (!this.token) throw new Error('本机服务会话尚未建立。'); headers['X-Workbench-Token'] = this.token; }
    const response = await this.fetch(`${API}${path}`, { method, headers, ...(body !== undefined ? { body: JSON.stringify(body) } : {}) });
    return safeJson(response);
  }
  async start() {
    if (!this.fetch || !this.document) return;
    this.bind();
    try {
      this.session = await this.request('/session'); this.token = this.session.token;
      if (!this.token) throw new Error('服务没有建立工作台会话，写入功能已暂停。');
      this.workspace = await this.request('/workspace');
      if (!this.workspace || !Array.isArray(this.workspace.projects) || !Array.isArray(this.workspace.jobs)) throw new Error('工作区响应格式不完整。');
      $('#connection').textContent = '已连接本机服务'; $('#connection').className = 'connection connected';
      $('#api-version').textContent = this.workspace.apiVersion ? `· 接口 ${this.workspace.apiVersion}` : '';
      hide($('#blocked')); hide($('#workspace'), false); this.renderWorkspace();
      hide($('#test-banner'), !this.workspace.testData);
      this.applyReadinessGate();
      try { await this.drafts.open(); this.persistenceOK = true; $('#persistence-note').textContent = '此浏览器的草稿存储可用。'; }
      catch (error) { this.persistenceOK = false; $('#persistence-note').textContent = `草稿无法持久保存：${error.message}`; $('#persistence-note').className = 'muted danger-text'; }
      let selectedProject = $('#project')?.value || '';
      if (!selectedProject) selectedProject = this.latestRecoverableProposal()?.projectId || '';
      if (selectedProject) await this.openProject(selectedProject);
      const jobs = this.workspace.jobs.filter(item => !selectedProject || item.projectId === selectedProject);
      const latest = jobs.find(item => ACTIVE.has(item.status)) || this.latestByDate(jobs);
      if (latest) await this.loadJob(latest.id);
    } catch (error) { this.showBlocked(error); }
  }
  bind() {
    if (this.bound) return; this.bound = true;
    $('#retry')?.addEventListener('click', () => this.start());
    $('#refresh')?.addEventListener('click', () => this.refresh());
    $('#concept-form')?.addEventListener('submit', event => { event.preventDefault(); this.submitConcept(); });
    $('#project')?.addEventListener('change', async event => {
      const projectId = event.target.value;
      if (!projectId) this.advanceSelection();
      try {
        if (projectId) await this.openProject(projectId);
        else { this.snapshot = null; this.capabilities = null; this.workflow = null; this.selectedObjectId = null; this.candidates = []; this.draftKey = null; hide($('#workbench-panel')); $('#edit-text').value = ''; this.applyReadinessGate(); }
      } catch (error) { this.notify(`无法读取所选项目：${error.message}`); }
    });
    $('#images')?.addEventListener('change', event => this.uploadImages(event.target.files));
    $('#answers-form')?.addEventListener('submit', event => { event.preventDefault(); this.answerQuestions(); });
    $('#reviewed')?.addEventListener('change', event => { $('#freeze').disabled = !event.target.checked || !this.readiness?.ready; });
    $('#freeze')?.addEventListener('click', () => this.freezeProposal());
    $('#resume-packet')?.addEventListener('click', () => this.resumeFrozenPacket());
    $('#cancel')?.addEventListener('click', () => this.cancelJob());
    $('#reconcile')?.addEventListener('click', () => this.reconcileJob());
    $('#edit-form')?.addEventListener('submit', event => { event.preventDefault(); this.submitIteration(); });
    $('#dynamic-fields')?.addEventListener('input', event => { if (event.target?.dataset?.fieldId) this.onDynamicFieldEdit(event.target); });
    $('#dynamic-fields')?.addEventListener('change', event => { if (event.target?.dataset?.fieldId) this.onDynamicFieldEdit(event.target); });
    $('#object-list')?.addEventListener('click', event => { const button = event.target.closest('[data-object-id]'); if (button) this.selectObject(button.dataset.objectId); });
    $('#add-feedback')?.addEventListener('click', () => this.addFeedback());
    $('#confirm-rebase')?.addEventListener('click', event => { event.preventDefault(); this.confirmRebase(); });
    $('#rebase-dialog')?.addEventListener('cancel', () => { this.pendingRebase = null; });
    $('#rebase-dialog')?.addEventListener('close', () => { if ($('#rebase-dialog').returnValue !== 'rebase') this.pendingRebase = null; });
    for (const field of ['#edit-text', '#feedback-message', '#feedback-category', ...TEMPLATE_FIELDS.map(name => `#edit-form [name="${name}"]`)]) $(field)?.addEventListener('input', () => this.queueDraftSave());
    $('#feedback-category')?.addEventListener('change', () => this.queueDraftSave());
  }
  showBlocked(error) {
    $('#connection').textContent = '服务未就绪'; $('#connection').className = 'connection disconnected';
    $('#blocked-copy').textContent = `目前无法启动新工作流：${error.message}。当前 bridge 尚未提供或无法确认所需能力，页面没有创建作业。`;
    hide($('#blocked'), false); hide($('#workspace'));
    $('#notice').textContent = '原工作台仍可使用。服务接口完成后，可从这里重新连接。'; hide($('#notice'), false);
  }
  showWorkflowBlock(message) {
    const blocked = $('#blocked'); hide(blocked, false);
    $('#blocked-title').textContent = '本轮流程已阻塞'; $('#blocked-copy').textContent = message;
    const heading = blocked.querySelector('.panel-heading');
    if (heading && !heading.querySelector('.readiness-pill')) heading.append(el('span', 'status-pill blocked-pill readiness-pill', '未派发'));
    $('#retry').textContent = '重新读取工作区';
  }
  async refresh() {
    let context = this.captureSelectionContext();
    try {
      const workspace = await this.request('/workspace');
      if (context.generation !== this.selectionGeneration) return;
      this.workspace = workspace; this.renderWorkspace();
      context = this.captureSelectionContext();
      const selectedProject = $('#project')?.value || '';
      if (this.retryOutcomeUnknown && selectedProject) {
        const uncertain = (this.workspace.proposals || []).find(item => item.id === this.retryOutcomeUnknown);
        const latestForProject = this.latestProposalForProject(selectedProject);
        if (uncertain?.projectId === selectedProject && latestForProject) this.retryOutcomeUnknown = null;
      }
      const pending = this.pendingProposal(selectedProject || null);
      const belongsToSelection = !selectedProject || !pending?.projectId || pending.projectId === selectedProject;
      if (pending && belongsToSelection && (!this.proposal || this.proposal.status === 'FROZEN' || this.proposal.id === pending.id || pending.projectId === selectedProject)) {
        this.proposal = pending;
        if (pending.status === 'FROZEN') {
          this.packet = this.packetFor(pending);
          if (this.packet) {
            this.renderProposal(); this.renderFrozenPacket();
            const associated = this.jobFor(pending, this.packet);
            if (associated && (!selectedProject || associated.projectId === selectedProject)) await this.loadJob(associated.id, false);
            else hide($('#resume-packet'), false);
          }
        } else { this.packet = null; this.renderProposal(); }
      } else if (!pending && this.proposal) {
        this.proposal = null; this.packet = null; hide($('#proposal-panel'));
      }
      if (!this.selectionContextMatches(context)) return;
      const scopedJobs = selectedProject ? (this.workspace.jobs || []).filter(item => item.projectId === selectedProject) : (this.workspace.jobs || []);
      if (this.job && scopedJobs.some(item => item.id === this.job.id)) await this.loadJob(this.job.id, false);
      else {
        const latest = scopedJobs.find(item => ACTIVE.has(item.status)) || this.latestByDate(scopedJobs);
        if (latest) await this.loadJob(latest.id, false);
        else if (selectedProject && this.job && this.job.projectId !== selectedProject) {
          this.jobLoadGeneration++; this.stopPolling(); this.job = null; hide($('#job-panel'));
        }
      }
      const projectId = selectedProject || this.job?.projectId || this.snapshot?.projectId || this.snapshot?.id;
      if (projectId) await this.ensureWorkbench(projectId);
      if (!this.selectionContextMatches(context)) return;
      $('#connection').textContent = '已连接本机服务'; $('#connection').className = 'connection connected'; return true;
    } catch (error) { this.notify(`刷新失败：${error.message}`); return false; }
  }
  latestByDate(items) { return [...items].sort((a, b) => String(b.updatedAt || b.createdAt || '').localeCompare(String(a.updatedAt || a.createdAt || '')))[0] || null; }
  packetFor(proposal) { return (this.workspace?.packets || []).find(item => item.id === proposal.packetId || item.packetId === proposal.packetId || item.proposalId === proposal.id) || null; }
  jobFor(proposal, packet) { return (this.workspace?.jobs || []).find(item => item.packetId === proposal.packetId || item.packetId === packet?.id || item.id === packet?.jobId) || null; }
  ensureWorkbench(projectId) {
    if ((this.snapshot?.projectId || this.snapshot?.id) === projectId) return Promise.resolve(this.snapshot);
    if (this.workbenchLoad?.projectId === projectId) return this.workbenchLoad.promise;
    const promise = this.loadWorkbench(projectId).finally(() => {
      if (this.workbenchLoad?.promise === promise) this.workbenchLoad = null;
    });
    this.workbenchLoad = { projectId, promise };
    return promise;
  }
  pendingProposal(projectId = $('#project')?.value || null) {
    if (!projectId) return null;
    const latest = this.latestProposalForProject(projectId);
    if (!latest) return null;
    if (['FAILED', 'NEEDS_CLARIFICATION', 'READY'].includes(latest.status) || PLANNING.has(latest.status)) return latest;
    if (latest.status === 'FROZEN') {
      const packet = this.packetFor(latest);
      if (!packet) return null;
      const job = this.jobFor(latest, packet);
      return !job || ACTIVE.has(job.status) ? latest : null;
    }
    return null;
  }
  latestProposalForProject(projectId) {
    const proposals = this.workspace?.proposals || [];
    if (!projectId) return null;
    return [...proposals].filter(item => item.projectId === projectId).sort((a, b) =>
      String(b.createdAt || b.updatedAt || '').localeCompare(String(a.createdAt || a.updatedAt || '')) ||
      String(b.updatedAt || '').localeCompare(String(a.updatedAt || '')))[0] || null;
  }
  latestRecoverableProposal() {
    const projectIds = [...new Set((this.workspace?.proposals || []).map(item => item.projectId).filter(Boolean))];
    return projectIds.map(projectId => this.pendingProposal(projectId)).filter(Boolean).sort((a, b) =>
      String(b.createdAt || b.updatedAt || '').localeCompare(String(a.createdAt || a.updatedAt || '')) ||
      String(b.updatedAt || '').localeCompare(String(a.updatedAt || '')))[0] || null;
  }
  renderWorkspace() {
    const projects = this.workspace?.projects || [], jobs = this.workspace?.jobs || [];
    $('#workspace-name').textContent = this.workspace?.name || '我的工作区';
    const select = $('#project'); const selected = select.value; select.replaceChildren();
    const fresh = el('option', '', '创建一个新 Demo'); fresh.value = ''; select.append(fresh);
    for (const project of projects) { const option = el('option', '', project.title || project.name || project.id); option.value = project.id; select.append(option); }
    if (projects.some(p => p.id === selected)) select.value = selected;
    const projectList = $('#project-list'); projectList.replaceChildren();
    if (!projects.length) projectList.append(el('p', 'muted', '还没有项目，从一个想法开始。'));
    for (const project of projects) { const row = el('button', 'list-row', project.title || project.name || project.id); row.type = 'button'; row.addEventListener('click', () => this.openProject(project.id)); projectList.append(row); }
    const jobList = $('#job-list'); jobList.replaceChildren();
    if (!jobs.length) jobList.append(el('p', 'muted', '还没有制作记录'));
    for (const job of jobs.slice(0, 8)) { const row = el('button', 'job-row'); row.type = 'button'; row.append(el('span', '', job.title || job.projectTitle || job.id)); const status = el('span', 'mini-status', JOB_LABELS[job.status] || job.status); row.append(status); row.addEventListener('click', () => this.loadJob(job.id)); jobList.append(row); }
  }
  async openProject(projectId) {
    this.advanceSelection();
    const selectionGeneration = this.selectionGeneration;
    const previousSnapshot = this.snapshot;
    const previousCapabilities = this.capabilities;
    const previousCandidates = this.candidates;
    const previousProjectId = previousSnapshot?.projectId || previousSnapshot?.id || $('#project').value;
    const previousDraft = previousSnapshot ? this.readVisibleDraft() : null;
    this.selectionBusy = true; this.applyReadinessGate();
    const load = this.loadWorkbench(projectId);
    const generation = this.workbenchGeneration;
    try {
      await load;
      if (generation !== this.workbenchGeneration || selectionGeneration !== this.selectionGeneration || (this.snapshot?.projectId || this.snapshot?.id) !== projectId) return;
      if (this.job && this.job.projectId !== projectId) { this.jobLoadGeneration++; this.stopPolling(); this.job = null; hide($('#job-panel')); }
      const proposal = this.pendingProposal(projectId);
      if (!proposal) { this.proposal = null; this.packet = null; hide($('#proposal-panel')); hide($('#freeze-area')); return; }
      this.proposal = proposal;
      if (proposal.status === 'FROZEN') {
        this.packet = this.packetFor(proposal); this.renderProposal(); this.renderFrozenPacket();
        const associatedJob = this.jobFor(proposal, this.packet);
        if (associatedJob) await this.loadJob(associatedJob.id);
        else hide($('#resume-packet'), false);
      } else { this.packet = null; this.renderProposal(); }
    }
    catch (error) {
      if (generation !== this.workbenchGeneration) return;
      if (previousSnapshot) {
        this.snapshot = previousSnapshot; this.capabilities = previousCapabilities; this.candidates = previousCandidates;
        this.draftKey = this.makeDraftKey(previousSnapshot);
        this.renderWorkbench(); if (previousDraft) this.applyVisibleDraft(previousDraft);
      } else { this.snapshot = null; this.capabilities = null; this.candidates = []; this.draftKey = null; hide($('#workbench-panel')); }
      $('#project').value = previousProjectId || '';
      this.notify(`无法读取所选项目：${error.message}。已保留原项目与草稿。`);
    }
    finally { if (generation === this.workbenchGeneration) { this.selectionBusy = false; this.applyReadinessGate(); } }
  }
  advanceSelection() {
    this.selectionGeneration++;
    this.conceptGeneration++; this.proposalMutationGeneration++; this.jobMutationGeneration++; this.jobLoadGeneration++;
    $('#cancel').disabled = false; $('#reconcile').disabled = false; $('#resume-packet').disabled = false;
    $('#freeze').textContent = '确认方案并继续'; $('#freeze').disabled = !$('#reviewed').checked || !this.readiness?.ready;
    this.applyReadinessGate();
  }
  captureSelectionContext() { return { generation: this.selectionGeneration, projectId: $('#project')?.value || '' }; }
  selectionContextMatches(context) { return !!context && context.generation === this.selectionGeneration && context.projectId === ($('#project')?.value || ''); }
  proposalBelongsToSelection(proposal, context) { return !proposal?.projectId || !context?.projectId || proposal.projectId === context.projectId; }
  snapshotMatchesProject(projectId) {
    return !!projectId && (this.snapshot?.projectId || this.snapshot?.id) === projectId && Number.isInteger(this.snapshot.publicationRevision) && this.snapshot.publicationRevision >= 0;
  }
  capabilityReady(key) {
    const caps = this.workspace?.capabilities || {};
    const value = caps[key];
    if (value === true) return true;
    if (value && typeof value === 'object') return value.available === true || value.ready === true || value.status === 'READY';
    return false;
  }
  applyReadinessGate() {
    const missing = Object.entries(REQUIRED_CAPABILITIES).filter(([key]) => !this.capabilityReady(key));
    this.readiness = { ready: missing.length === 0, missing };
    const submit = $('#concept-form [type="submit"]');
    const selectedProject = $('#project')?.value || '';
    const projectReady = !selectedProject || this.snapshotMatchesProject(selectedProject);
    if (submit) submit.disabled = !this.readiness.ready || this.selectionBusy || !projectReady;
    const iteration = $('#edit-form [type="submit"]');
    if (iteration) iteration.disabled = !this.readiness.ready || this.selectionBusy || !projectReady;
    const blocked = $('#blocked');
    if (!this.readiness.ready) {
      hide(blocked, false);
      $('#blocked-title').textContent = '新工作流尚未通过启动检查';
      const reasons = missing.map(([key, label]) => { const state = this.workspace?.capabilities?.[key]; return `${label}${state && typeof state === 'object' && state.reason ? `（${state.reason}）` : ''}`; });
      $('#blocked-copy').textContent = `当前项目仍可只读查看；制作入口已暂停。服务尚未声明以下能力就绪：${reasons.join('、')}。`;
      $('#blocked-pill')?.remove();
      const heading = blocked.querySelector('.panel-heading'); if (heading && !heading.querySelector('.readiness-pill')) { const pill = el('span', 'status-pill blocked-pill readiness-pill', '暂不可用'); heading.append(pill); }
    }
  }
  async uploadImages(files) {
    if (!files?.length) return;
    const input = $('#images'); input.disabled = true;
    try {
      for (const file of Array.from(files)) {
        if (!['image/png', 'image/jpeg', 'image/webp'].includes(file.type)) throw new Error(`${file.name} 不是支持的图片格式。`);
        if (this.assets.length >= 6) throw new Error('本轮最多添加 6 张图片。');
        if (file.size > 5 * 1024 * 1024) throw new Error(`${file.name} 超过 5 MB。`);
        const dataBase64 = await new Promise((resolve, reject) => { const reader = new FileReader(); reader.onload = () => resolve(String(reader.result).split(',')[1]); reader.onerror = () => reject(reader.error); reader.readAsDataURL(file); });
        const result = await this.request('/assets', { method: 'POST', token: true, body: { name: file.name, mimeType: file.type, dataBase64, purpose: $('#asset-purpose').value } });
        const asset = result.asset || result; if (!asset.id) throw new Error('服务没有返回图片编号。'); this.assets.push(asset);
      }
      this.renderAssets();
    } catch (error) { this.notify(`图片尚未添加：${error.message}`); }
    finally { input.disabled = false; input.value = ''; }
  }
  renderAssets() {
    const list = $('#image-list'); list.replaceChildren();
    for (const asset of this.assets) {
      const chip = el('span', 'asset-chip'); const thumb = el('img', 'asset-thumb'); thumb.src = `${API}/assets/${encodeURIComponent(asset.id)}`; thumb.alt = `${asset.name || '参考图片'} 预览`;
      const text = el('span', '', `${asset.name || '参考图片'} · ${asset.purpose || '已添加'}`); const remove = el('button', '', '移除'); remove.type = 'button'; remove.setAttribute('aria-label', `移除 ${asset.name || '参考图片'}`); remove.addEventListener('click', () => { this.assets = this.assets.filter(item => item.id !== asset.id); this.renderAssets(); }); chip.append(thumb, text, remove); list.append(chip);
    }
  }
  async submitConcept(iterationText = '', isIteration = false) {
    if (!this.readiness?.ready) return this.notify('制作入口暂不可用；请先完成服务能力启动检查。');
    if (this.selectionBusy) return this.notify('正在读取所选项目版本，请稍后再提交。');
    const selectedProject = $('#project').value;
    const context = this.captureSelectionContext(), requestGeneration = ++this.conceptGeneration;
    if (selectedProject && !this.snapshotMatchesProject(selectedProject)) return this.notify('所选项目的版本尚未读取成功；请刷新该项目后再提交。');
    if (selectedProject && !Number.isInteger(this.snapshot.publicationRevision)) return this.notify('所选项目缺少有效发布版本号；没有提交提案。');
    const form = $('#concept-form'); const text = isIteration ? iterationText : $('#concept').value.trim();
    const changeRequest = isIteration && selectedProject && this.objectsWorkflow() ? this.buildChangeRequest() : undefined;
    if (!text && !(changeRequest?.fields?.length || changeRequest?.feedback?.length)) return this.notify('先写下一个想法或调整目标。');
    const button = (isIteration ? $('#edit-form') : form).querySelector('[type="submit"]'); button.disabled = true;
    try {
      const expectedPublicationRevision = selectedProject ? this.snapshot.publicationRevision : undefined;
      const requestBody = { text, ...(selectedProject ? { projectId: selectedProject } : {}), ...(expectedPublicationRevision != null ? { expectedPublicationRevision } : {}), assetIds: this.assets.map(asset => asset.id), ...(!selectedProject ? { workflow: 'objects-v1' } : {}), ...(changeRequest ? { changeRequest } : {}) };
      const response = await this.request('/concepts', { method: 'POST', token: true, body: requestBody });
      if (!this.selectionContextMatches(context) || requestGeneration !== this.conceptGeneration) return;
      this.proposal = response.proposal || response; if (!this.proposal.id || !Number.isInteger(this.proposal.revision)) throw new Error('服务返回的提案缺少身份或修订号。');
      this.packet = null;
      this.renderProposal(); this.assets = []; this.renderAssets(); $('#proposal-panel').scrollIntoView?.({ behavior: 'smooth', block: 'start' });
      this.startProposalPolling();
    } catch (error) { if (this.selectionContextMatches(context) && requestGeneration === this.conceptGeneration) this.notify(`提案没有提交：${error.message}`); }
    finally { if (this.selectionContextMatches(context) && requestGeneration === this.conceptGeneration) button.disabled = false; }
  }
  objectsWorkflow() { return this.workflow === 'objects-v1' || this.proposal?.workflow === 'objects-v1' || this.snapshot?.workflow === 'objects-v1'; }
  startProposalPolling() {
    this.stopProposalPolling();
    if (!this.proposal?.id || !PLANNING.has(this.proposal.status)) return;
    const id = this.proposal.id, generation = ++this.proposalGeneration;
    this.proposalPollHandle = this.timers.setInterval(async () => {
      if (this.destroyed || generation !== this.proposalGeneration || this.proposal?.id !== id) return;
      try {
        const response = await this.request(`/proposals/${encodeURIComponent(id)}`);
        const latest = response.proposal || response;
        if (generation !== this.proposalGeneration || this.proposal?.id !== id || latest.id !== id) return;
        if (Number(latest.revision) < Number(this.proposal.revision)) return;
        this.proposal = latest; this.renderProposal();
      } catch (error) {
        if (generation === this.proposalGeneration) this.renderPlanningStatus(this.proposal, `暂时无法读取策划进度：${error.message}`);
      }
    }, 2000);
  }
  stopProposalPolling() { this.proposalGeneration++; if (this.proposalPollHandle != null) this.timers.clearInterval(this.proposalPollHandle); this.proposalPollHandle = null; }
  renderPlanningStatus(proposal, message = null) {
    const node = $('#planning-status'); if (!node) return;
    node.replaceChildren(el('p', '', message || (proposal.status === 'PLANNING_UNCERTAIN' ? '策划会话状态待核实；正在读取原提案状态，不会自动创建新会话。' : '策划正在整理对象、需求和制作计划。此阶段不会修改游戏工程。')));
    this.renderPlanningControls(proposal); hide(node, false);
  }
  renderPlanningControls(proposal) {
    const node = $('#planning-status'); if (!node || !proposal?.id) return;
    let actions = node.querySelector('.planning-actions');
    if (!actions) { actions = el('div', 'planning-actions'); node.append(actions); }
    actions.replaceChildren();
    if (proposal.status === 'PLANNING' || proposal.status === 'PLANNING_UNCERTAIN') {
      const available = proposal.status === 'PLANNING' ? [['取消策划', 'cancel']] : [['对账策划状态', 'reconcile']];
      for (const [label, action] of available) {
        const button = el('button', 'button secondary', label); button.type = 'button'; button.addEventListener('click', () => this.proposalAction(action)); actions.append(button);
      }
    }
  }
  renderPlanningFailure(proposal, root) {
    const failure = proposal?.planningFailure;
    if (!failure || typeof failure !== 'object') return;
    const section = el('section', 'notice planning-failure'); section.setAttribute('aria-label', '策划执行诊断');
    section.append(el('h3', '', '策划执行诊断'));
    const labels = {
      PLANNER_TIMEOUT: '策划 session 等待超时。', PLANNER_NETWORK: '与策划 session 的通信中断。',
      PLANNER_FAILED: '策划 session 执行失败。', PLANNER_CANCELLED: '策划 session 已停止。',
      PLANNER_AUTH: '策划 session 身份验证失败。', PLANNER_RESTRICTED: '策划请求超出当前角色范围。',
      PLANNER_RESPONSE_INVALID: '策划 session 返回了无法识别的结果。', PLANNER_WRITE: '策划违反只读范围。',
      PLANNER_SETUP: '策划 session 未能启动。', PLANNER_UNCERTAIN: '策划 session 停止状态尚未确认。',
    };
    section.append(el('p', '', labels[failure.code] || '策划 session 未能完成。'));
    const summary = typeof failure.message === 'string' ? failure.message.trim() : '';
    if (summary && summary.length <= 160 && !/[\\/]|stderr|traceback|\.(?:png|jpe?g|webp)\b/i.test(summary)) section.append(el('p', '', summary));
    const details = el('dl', 'planning-diagnostic');
    const seconds = failure.elapsedSeconds;
    if (seconds != null && seconds !== '' && Number.isFinite(Number(seconds)) && Number(seconds) >= 0) details.append(el('dt', '', '耗时'), el('dd', '', `${Math.round(Number(seconds))} 秒`));
    const sessionId = typeof failure.sessionId === 'string' && /^[A-Za-z0-9][A-Za-z0-9._:-]{0,119}$/.test(failure.sessionId) ? failure.sessionId : null;
    if (sessionId) details.append(el('dt', '', 'Session'), el('dd', '', sessionId));
    const nativeLabels = { completed: '已结束', failed: '执行失败', stopped: '已停止', running: '仍在运行', timeout: '等待超时', unavailable: '状态不可用' };
    const nativeStatus = typeof failure.nativeStatus === 'string' ? failure.nativeStatus.toLowerCase() : '';
    if (nativeLabels[nativeStatus]) details.append(el('dt', '', '原生状态'), el('dd', '', nativeLabels[nativeStatus]));
    if (typeof failure.terminationConfirmed === 'boolean') details.append(el('dt', '', '停止确认'), el('dd', '', failure.terminationConfirmed ? '已确认停止' : '未确认停止'));
    if (details.childNodes.length) section.append(details);
    root.append(section);
    if (failure.clarificationAvailable === true && proposal.planningTerminationConfirmed === true) {
      const button = el('button', 'button secondary', '恢复已返回的澄清问题'); button.type = 'button'; button.dataset.action = 'recover-clarification';
      button.addEventListener('click', () => this.proposalAction('reconcile')); root.append(button);
      return;
    }
    if (failure.retryable === true) {
      const unknown = this.retryOutcomeUnknown === proposal.id;
      const button = el('button', 'button secondary', unknown ? '重试结果待核账' : '使用原输入重试策划'); button.type = 'button'; button.dataset.action = 'retry-planning'; button.disabled = unknown;
      button.addEventListener('click', () => this.retryPlanning(proposal, button)); root.append(button);
      if (unknown) {
        root.append(el('p', 'notice', '上次请求可能已创建新方案。请先刷新工作台核账；核账完成前不能再次提交。'));
        const refreshButton = el('button', 'button secondary', '刷新工作台核账'); refreshButton.type = 'button'; refreshButton.dataset.action = 'reconcile-retry';
        refreshButton.addEventListener('click', () => this.reconcileRetry(proposal, refreshButton)); root.append(refreshButton);
      }
    }
  }
  renderPlanningRecovery(proposal, root) {
    if (proposal?.status !== 'NEEDS_CLARIFICATION' || proposal.planningRecovery?.kind !== 'CLARIFICATION_FROM_TIMEOUT') return;
    root.append(el('div', 'notice', '原生策划在时限内未确认完成；这里只恢复已校验的澄清问题。回答后会继续策划，不代表方案已通过或可以制作。'));
  }
  async reconcileRetry(proposal, button) {
    if (button.disabled || this.retryOutcomeUnknown !== proposal?.id || this.proposal?.id !== proposal.id) return;
    const context = this.captureSelectionContext(); button.disabled = true;
    const refreshed = await this.refresh();
    if (!this.selectionContextMatches(context)) return;
    if (!refreshed) { button.disabled = false; return; }
    this.retryOutcomeUnknown = null;
    if (this.proposal?.id === proposal.id) this.renderProposal();
  }
  async retryPlanning(proposal, button) {
    if (button.disabled || this.retryOutcomeUnknown === proposal?.id || this.proposal?.id !== proposal?.id || proposal.status !== 'FAILED' || proposal.planningFailure?.retryable !== true) return;
    const context = this.captureSelectionContext(), generation = ++this.conceptGeneration;
    if (!this.proposalBelongsToSelection(proposal, context) || !proposal.projectId || !Number.isInteger(proposal.publicationRevision)) return this.notify('无法确认原项目版本；请刷新工作区后重试。');
    if (this.snapshot?.projectId !== proposal.projectId && this.snapshot?.id !== proposal.projectId) return this.notify('原项目尚未选中；请先选择该项目再重试。');
    button.disabled = true;
    try {
      const body = {
        text: typeof proposal.text === 'string' ? proposal.text : '', projectId: proposal.projectId,
        workflow: proposal.workflow || (this.objectsWorkflow() ? 'objects-v1' : undefined),
        expectedPublicationRevision: proposal.publicationRevision,
        assetIds: Array.isArray(proposal.assets) ? proposal.assets.map(asset => typeof asset === 'string' ? asset : asset?.id).filter(id => typeof id === 'string' && id) : Array.isArray(proposal.assetIds) ? [...proposal.assetIds] : [],
        ...(proposal.changeRequest ? { changeRequest: structuredClone(proposal.changeRequest) } : {}),
      };
      const response = await this.request('/concepts', { method: 'POST', token: true, body });
      const latest = response.proposal || response;
      if (!this.selectionContextMatches(context) || generation !== this.conceptGeneration || this.proposal?.id !== proposal.id) return;
      if (!latest.id || !Number.isInteger(latest.revision) || latest.id === proposal.id) throw new Error('服务没有创建新的策划修订。');
      this.proposal = latest; this.packet = null; this.renderProposal(); this.startProposalPolling();
    } catch (error) {
      if (this.selectionContextMatches(context) && generation === this.conceptGeneration && this.proposal?.id === proposal.id) {
        const outcomeUnknown = !Number.isInteger(error.status) || error.status >= 500;
        if (outcomeUnknown) { this.retryOutcomeUnknown = proposal.id; this.renderProposal(); this.notify('策划重试结果待确认；请先刷新工作台核账，避免重复创建。'); }
        else this.notify(`策划重试没有提交：${error.message}`);
      }
    } finally {
      if (this.selectionContextMatches(context) && generation === this.conceptGeneration && this.proposal?.id === proposal.id && this.retryOutcomeUnknown !== proposal.id) button.disabled = false;
    }
  }
  async proposalAction(action) {
    const context = this.captureSelectionContext(), proposal = this.proposal && structuredClone(this.proposal), generation = ++this.proposalMutationGeneration;
    const clarificationRecovery = action === 'reconcile' && proposal?.status === 'FAILED'
      && proposal.planningFailure?.clarificationAvailable === true && proposal.planningTerminationConfirmed === true;
    if (!proposal?.id || !(PLANNING.has(proposal.status) || clarificationRecovery) || !this.proposalBelongsToSelection(proposal, context)) return;
    const existingAnswers = clarificationRecovery ? Object.fromEntries([...($('#questions')?.querySelectorAll('[name]') || [])].map(control => [control.name, control.value])) : null;
    try {
      const response = await this.request(`/proposals/${encodeURIComponent(proposal.id)}/${action}`, { method: 'POST', token: true, body: {} });
      const latest = response.proposal || response;
      if (this.selectionContextMatches(context) && generation === this.proposalMutationGeneration && this.proposal?.id === proposal.id && latest.id === proposal.id && Number(latest.revision) >= Number(proposal.revision)) {
        this.proposal = latest; this.renderProposal();
        if (existingAnswers && latest.status === 'NEEDS_CLARIFICATION') for (const control of $('#questions')?.querySelectorAll('[name]') || []) if (Object.hasOwn(existingAnswers, control.name)) control.value = existingAnswers[control.name];
      }
    } catch (error) { if (this.selectionContextMatches(context) && generation === this.proposalMutationGeneration && this.proposal?.id === proposal.id) this.notify(`策划${action === 'cancel' ? '取消' : '对账'}未确认：${error.message}`); }
  }
  objectDocument(proposal = this.proposal) { return proposal?.document || proposal?.designDocument || proposal?.objectDocument || null; }
  objectItems(source = this.snapshot) { const catalog = source?.catalog || {}; const document = source?.document || source?.objectDocument || {}; return catalog.objects || document.objects || source?.objects || []; }
  renderObjectsProposal(root, proposal) {
    const document = this.objectDocument(proposal); if (!document) return;
    const section = el('section', 'object-plan'); section.append(el('h3', '', document.title || '对象计划'));
    if (document.summary) section.append(el('p', 'proposal-summary', document.summary));
    for (const [label, content] of [['GDD', document.gdd || document.gddMarkdown], ['制作计划', document.plan || document.planMarkdown], ['补充说明', document.markdown]]) {
      if (typeof content === 'string' && content.trim()) { const article = el('details', 'plan-document'); article.append(el('summary', '', label)); article.append(el('pre', 'object-diff', content)); section.append(article); }
    }
    if (Array.isArray(document.sections)) for (const item of document.sections) { const block = el('section', 'plan-section'); block.append(el('h4', '', item.title || item.id || '计划章节')); const body = item.content || item.text || item.markdown; if (body) block.append(el('pre', 'object-diff', body)); section.append(block); }
    const objects = Array.isArray(document.objects) ? document.objects : [];
    if (objects.length) { section.append(el('h4', '', '对象、属性与关系')); const list = el('div', 'object-plan-list'); for (const object of objects) { const card = el('article', 'object-plan-card'); card.append(el('b', '', `${object.name || object.id} · ${object.kind || '对象'} · ${object.id}`)); if (object.description) card.append(el('p', '', object.description)); if (object.parentId) card.append(el('p', 'muted', `父对象：${object.parentId}`)); const relations = object.relations || []; if (relations.length) card.append(el('p', 'muted', `关系：${relations.map(r => `${r.type || '关联'} → ${r.targetId || r.target}`).join('、')}`)); if (object.sourceBindings?.length) card.append(el('p', 'meta-line', `文件绑定：${object.sourceBindings.join('、')}`)); if (object.fields?.length) { const fields = el('ul', 'requirement-list'); for (const field of object.fields) { const bounds = field.min != null || field.max != null ? ` · 范围 ${field.min ?? '不限'}–${field.max ?? '不限'}` : ''; const options = field.options?.length ? ` · 选项 ${field.options.map(option => typeof option === 'object' ? option.label || option.value : option).join('、')}` : ''; fields.append(el('li', '', `${field.label || field.id} (${field.type}) = ${JSON.stringify(field.value)}${field.editable === false ? ' · 只读' : ' · 可调整'}${bounds}${options}`)); } card.append(fields); } list.append(card); } section.append(list); }
    const tasks = proposal.tasks || document.tasks || []; if (tasks.length) { section.append(el('h4', '', '制作任务')); const list = el('ol', 'requirement-list'); for (const task of tasks) list.append(el('li', '', typeof task === 'string' ? task : task.title || task.text || task.description || JSON.stringify(task))); section.append(list); }
    const requirements = proposal.requirements || document.requirements || [];
    if (requirements.length) { section.append(el('h4', '', '需求与验证方式')); const list = el('ul', 'requirement-list'); for (const req of requirements) { const text = typeof req === 'string' ? req : `${req.text || req.title || req.id}${req.objectIds?.length ? ` · 对象 ${req.objectIds.join('、')}` : ''}${req.verification ? ` · ${req.verification === 'manual' || req.verification === 'human' ? '人工体验验收' : req.verification}` : ''}`; list.append(el('li', '', text)); } section.append(list); }
    const acceptance = proposal.acceptance || document.acceptance || document.acceptanceCriteria || [];
    if (acceptance.length) { section.append(el('h4', '', '验收条件')); const list = el('ul', 'requirement-list'); for (const item of acceptance) list.append(el('li', '', typeof item === 'string' ? item : item.text || item.title || JSON.stringify(item))); section.append(list); }
    const blockers = proposal.blockers || []; if (blockers.length) { section.append(el('h4', '', '待解决问题')); const list = el('ul', 'requirement-list'); for (const item of blockers) list.append(el('li', '', typeof item === 'string' ? item : item.message || item.text || JSON.stringify(item))); section.append(list); }
    if (proposal.changeRequest?.targetObjectIds?.length) section.append(el('p', 'meta-line', `本轮对象：${proposal.changeRequest.targetObjectIds.join('、')}`));
    if (proposal.changeRequest?.fields?.length) { section.append(el('h4', '', '属性修改')); const list = el('ul', 'requirement-list'); for (const field of proposal.changeRequest.fields) list.append(el('li', '', `${field.objectId}.${field.fieldId} → ${JSON.stringify(field.value)}`)); section.append(list); }
    if (proposal.changeRequest?.feedback?.length) { section.append(el('h4', '', '本轮反馈')); const list = el('ul', 'requirement-list'); for (const item of proposal.changeRequest.feedback) list.append(el('li', '', `${item.objectId} · ${item.category}: ${item.message}`)); section.append(list); }
    const diff = proposal.objectDiff || proposal.objectChanges || proposal.diff?.objects || document.objectDiff; if (diff) { section.append(el('h4', '', '对象差异')); section.append(el('pre', 'object-diff', typeof diff === 'string' ? diff : JSON.stringify(diff, null, 2))); }
    root.append(section);
  }
  renderProposal() {
    const proposal = this.proposal; if (!proposal) return;
    hide($('#planning-status'));
    $('#review-label').textContent = this.workspace?.testData ? '我已阅读并确认本次测试方案和制作范围' : '我已阅读并确认上面的方案和制作范围';
    hide($('#proposal-panel'), false); $('#proposal-title').textContent = proposal.title || '初步方案';
    const proposalStatusLabel = proposal.status === 'FAILED' ? '策划失败' : proposal.status === 'READY' ? '方案待确认' : proposal.status === 'NEEDS_CLARIFICATION' ? '需要补充信息' : proposal.status === 'FROZEN' ? '已冻结，沿用原制作表单' : JOB_LABELS[proposal.status] || `服务状态：${proposal.status || '未知'}`;
    setStatus($('#proposal-status'), proposal.status, proposalStatusLabel);
    const area = $('#proposal-content'); area.replaceChildren();
    area.append(el('p', 'proposal-summary', proposal.text || '服务尚未提供方案摘要。'));
    if (proposal.projectId) area.append(el('p', 'meta-line', `项目：${proposal.projectId} · 方案修订 ${proposal.revision}`));
    if (proposal.workflow !== 'objects-v1' && proposal.initializationRequired) { const hint = el('div', 'notice', '这是一个新项目。确认范围后，服务会按受控初始化流程准备项目；初始化通过后才会制作玩法。'); area.append(hint); }
    if (proposal.baseCommit) area.append(el('p', 'meta-line', `工程基线：${proposal.baseCommit}`));
    if (proposal.gmSpecRef) area.append(el('p', 'meta-line', `GM 规格引用：${proposal.gmSpecRef}`));
    const closedLoopRef = proposal.sourceRefs?.['tests/closed_loop.gd'];
    if (closedLoopRef) area.append(el('p', 'meta-line', `闭环测试引用：${closedLoopRef}`));
    const inventory = proposal.templateInventory;
    if (inventory && typeof inventory === 'object' && Object.keys(inventory).length) {
      const entries = inventory.files || inventory.entries || inventory.items || Object.entries(inventory).map(([path, git]) => ({ path, git }));
      const revision = inventory.revision || inventory.git || inventory.commit || inventory.rootCommit || '已绑定';
      const section = el('section', 'notice'); section.append(el('b', '', `受审查模板清单 · ${revision} · ${Array.isArray(entries) ? entries.length : 0} 项`));
      if (Array.isArray(entries) && entries.length) {
        const list = el('ul', 'requirement-list');
        for (const item of entries.slice(0, 12)) list.append(el('li', '', typeof item === 'string' ? item : `${item.path || item.name || item.file || '模板文件'}${item.git ? ` · ${item.git}` : item.blob ? ` · ${item.blob}` : ''}`));
        section.append(list);
        if (entries.length > 12) section.append(el('p', 'muted', `另有 ${entries.length - 12} 项，均由冻结表单绑定。`));
      }
      area.append(section);
    }
    const decisions = proposal.decisions || {}; const decisionList = el('dl', 'decision-list');
    for (const key of TEMPLATE_FIELDS) if (decisions[key] != null) { decisionList.append(el('dt', '', LABELS[key]), el('dd', '', String(decisions[key]))); }
    if (decisionList.childNodes.length) area.append(decisionList);
    if (proposal.workflow === 'objects-v1' || this.objectsWorkflow()) this.renderObjectsProposal(area, proposal);
    const requirements = proposal.requirements || proposal.document?.requirements || []; if (requirements.length && proposal.workflow !== 'objects-v1' && !this.objectsWorkflow()) { const heading = el('h3', '', '本轮目标'); const list = el('ul', 'requirement-list'); for (const req of requirements) list.append(el('li', '', typeof req === 'string' ? req : req.text || req.title || JSON.stringify(req))); area.append(heading, list); }
    const questions = proposal.questions || [];
    const ask = $('#answers-form'); const freeze = $('#freeze-area');
    if (PLANNING.has(proposal.status) || proposal.status === 'PLANNING_UNCERTAIN') { hide(ask); hide(freeze); this.renderPlanningStatus(proposal); this.startProposalPolling(); }
    else if (proposal.status === 'FROZEN') { this.stopProposalPolling(); hide(ask); hide(freeze, false); $('#review-label').textContent = '此制作表单已冻结，恢复时沿用原表单'; $('#reviewed').checked = false; $('#reviewed').disabled = true; $('#freeze').disabled = true; hide($('#resume-packet'), true); }
    else if (proposal.status === 'NEEDS_CLARIFICATION' || questions.length) { this.stopProposalPolling(); this.renderQuestions(questions); this.renderPlanningRecovery(proposal, area); hide(ask, false); hide(freeze); $('#reviewed').disabled = false; $('#freeze').disabled = true; }
    else if (proposal.status === 'READY') { this.stopProposalPolling(); hide(ask); this.renderPacketPreview(proposal); hide(freeze, false); $('#reviewed').checked = false; $('#reviewed').disabled = false; $('#freeze').disabled = true; }
    else if (['FAILED', 'CANCELLED', 'BLOCKED'].includes(proposal.status)) { this.stopProposalPolling(); hide(ask); hide(freeze); area.append(el('div', 'notice', proposal.status === 'FAILED' && proposal.planningFailure ? '策划 session 未能完成。' : proposal.message || `策划状态：${proposal.status}`)); if (proposal.status === 'FAILED') this.renderPlanningFailure(proposal, area); this.renderPlanningControls(proposal); }
    else { this.stopProposalPolling(); hide(ask); hide(freeze); area.append(el('p', 'muted', `当前方案状态为 ${proposal.status || '未知'}，服务未声明可以确认。`)); }
  }
  parameterInput(key) { return $(`#edit-form [name="${key}"]`); }
  renderQuestions(questions) {
    const root = $('#questions'); root.replaceChildren();
    const decisions = this.proposal.decisions || {};
    for (const q of questions) {
      const fieldset = el('fieldset', 'question'); const legend = el('legend', '', q.prompt || q.id); fieldset.append(legend);
      const choices = Array.isArray(q.options) ? q.options : [];
      let control;
      if (q.type === 'choice' || choices.length) { control = el('select'); this.configureChoice(control, choices); }
      else if (q.type === 'boolean') { control = el('select'); for (const [value, label] of [['', '请选择'], ['true', '是'], ['false', '否']]) { const opt = el('option', '', label); opt.value = value; control.append(opt); } }
      else { control = q.type === 'text' ? el('textarea') : el('input'); if (q.type !== 'text') control.type = 'number'; else control.rows = 3; if (q.type === 'number' && q.integer) control.step = '1'; }
      control.name = q.id; control.required = q.required !== false; control.dataset.answerType = q.type || (choices.length ? 'choice' : 'text');
      const existing = decisions[q.id] ?? q.value ?? q.currentValue;
      if (existing != null) control.value = String(existing);
      fieldset.append(control); root.append(fieldset);
    }
    if (!questions.length) root.append(el('p', 'muted', '服务没有返回待回答的问题。'));
  }
  renderPacketPreview(proposal) {
    let existing = $('#packet-preview'); if (!existing) { existing = el('section', 'packet-preview'); existing.id = 'packet-preview'; $('#freeze-area').prepend(existing); }
    existing.replaceChildren(el('h3', '', '本轮制作表单'));
    const rows = [
      ['方案与修订', `${proposal.id} · r${proposal.revision}`], ['工程', proposal.projectId || '由服务分配'],
      ['Git 基线', proposal.baseCommit || '等待服务绑定'], ['发布版本', proposal.publicationRevision ?? '等待服务绑定'],
      ['本轮模式', proposal.workflow === 'objects-v1' || this.objectsWorkflow() ? '审阅完整对象计划后制作候选' : proposal.initializationRequired ? '最小工程准备；验收通过后再规划与制作' : '现有工程内增量修改'],
      ['本轮角色', (proposal.roles || proposal.roleScope || []).map?.(item => typeof item === 'string' ? item : item.name || item.id).join('、') || proposal.role || '由服务按项目规则分配'],
      ['精确范围', typeof proposal.scope === 'string' ? proposal.scope : JSON.stringify(proposal.scope || proposal.targets || proposal.requirements || [])],
      ['验收条件', JSON.stringify(proposal.acceptance || proposal.acceptanceCriteria || proposal.tests || proposal.requirements || [])],
      ['决定记录', JSON.stringify(proposal.decisions || {})],
    ];
    const list = el('dl', 'packet-list'); for (const [name, value] of rows) list.append(el('dt', '', name), el('dd', '', String(value))); existing.append(list);
    const scope = proposal.packetSummary || proposal.scope; if (scope) existing.append(el('p', 'muted', typeof scope === 'string' ? scope : JSON.stringify(scope)));
    if (proposal.workflow === 'objects-v1' || this.objectsWorkflow()) this.renderObjectsProposal(existing, proposal);
  }
  async answerQuestions() {
    const context = this.captureSelectionContext(), proposal = this.proposal && structuredClone(this.proposal), generation = ++this.proposalMutationGeneration;
    if (!proposal?.id || !this.proposalBelongsToSelection(proposal, context)) return;
    const form = $('#answers-form'); const answers = {};
    for (const control of form.querySelectorAll('[name]')) {
      if (control.value === '') continue;
      const type = control.dataset.answerType;
      if (type === 'boolean') answers[control.name] = control.value === 'true';
      else if (type === 'number') answers[control.name] = Number(control.value);
      else if (type === 'choice') answers[control.name] = (proposal.workflow === 'objects-v1' || this.objectsWorkflow() || control.dataset.optionMode === 'index') ? this.readChoiceValue(control) : control.value;
      else answers[control.name] = control.value;
    }
    try {
      const response = await this.request(`/proposals/${encodeURIComponent(proposal.id)}/answers`, { method: 'POST', token: true, body: { expectedRevision: proposal.revision, answers } });
      if (!this.selectionContextMatches(context) || generation !== this.proposalMutationGeneration || this.proposal?.id !== proposal.id || Number(this.proposal?.revision) !== Number(proposal.revision)) return;
      this.proposal = response.proposal || response; this.renderProposal(); this.startProposalPolling();
    } catch (error) { if (this.selectionContextMatches(context) && generation === this.proposalMutationGeneration && this.proposal?.id === proposal.id) this.notify(`回答没有保存：${error.message}${error.status === 409 ? ' 方案已更新，请刷新后重新核对。' : ''}`); }
  }
  async freezeProposal() {
    if (!this.readiness?.ready || !$('#reviewed').checked || !this.proposal) return;
    const context = this.captureSelectionContext(), proposal = structuredClone(this.proposal), generation = ++this.proposalMutationGeneration;
    if (!this.proposalBelongsToSelection(proposal, context)) return;
    const button = $('#freeze'); button.disabled = true; button.textContent = '正在冻结方案…';
    try {
      if (this.packet && proposal.status === 'FROZEN' && (!this.packet.proposalId || this.packet.proposalId === proposal.id) && (!this.packet.projectId || !proposal.projectId || this.packet.projectId === proposal.projectId)) { await this.createJob(this.packet, { context, proposal }); return; }
      const reviewedProposal = proposal;
      const response = await this.request(`/proposals/${encodeURIComponent(proposal.id)}/freeze`, { method: 'POST', token: true, body: { expectedRevision: proposal.revision, expectedPublicationRevision: proposal.publicationRevision, reviewedProposal } });
      if (!this.selectionContextMatches(context) || generation !== this.proposalMutationGeneration || this.proposal?.id !== proposal.id || Number(this.proposal?.revision) !== Number(proposal.revision)) return;
      const frozenPacket = response.packet || response;
      if (!frozenPacket.id && !frozenPacket.packetId) throw new Error('服务没有返回冻结表单编号；请先按方案编号对账，页面不会创建新作业。');
      this.packet = frozenPacket;
      this.renderFrozenPacket();
      const expectedKind = proposal.initializationRequired ? 'INITIALIZATION' : 'IMPLEMENTATION';
      if (this.packet.operationKind !== expectedKind) {
        this.showWorkflowBlock(`本轮需要 ${expectedKind} 阶段的冻结表单；服务没有返回匹配的表单类型，制作未派发。`);
        return;
      }
      await this.createJob(frozenPacket, { context, proposal });
    } catch (error) { if (this.selectionContextMatches(context) && generation === this.proposalMutationGeneration && this.proposal?.id === proposal.id) { this.notify(`方案未能冻结或派发：${error.message}${error.status === 409 ? ' 版本发生变化，请刷新并重新审阅。' : ''}`); button.textContent = '重新尝试确认'; button.disabled = !$('#reviewed').checked || !this.readiness?.ready; } }
  }
  async resumeFrozenPacket() {
    if (!this.packet || this.proposal?.status !== 'FROZEN') return;
    const context = this.captureSelectionContext(), packet = this.packet, proposal = structuredClone(this.proposal);
    if (!this.proposalBelongsToSelection(proposal, context)) return;
    const button = $('#resume-packet'); button.disabled = true; button.textContent = '正在恢复原制作表单…';
    try { await this.createJob(packet, { context, proposal }); if (this.selectionContextMatches(context) && this.packet === packet) hide(button); }
    catch (error) { if (this.selectionContextMatches(context) && this.packet === packet) { this.notify(`无法恢复此制作表单：${error.message}。页面仍保留原表单编号。`); button.disabled = false; button.textContent = '恢复并继续此制作表单'; } }
  }
  renderFrozenPacket() {
    const packet = this.packet; if (!packet) return;
    const container = $('#packet-preview'); if (!container) return;
    container.replaceChildren(el('h3', '', '已冻结的制作表单'));
    const fields = [
      ['表单编号', packet.packetId || packet.id], ['表单版本', packet.schemaVersion || packet.version || '服务返回'], ['阶段', packet.operationKind || '未声明'],
      ['项目 / 方案', `${packet.projectId || '待分配'} · ${packet.proposalId || this.proposal?.id || ''} r${packet.proposalRevision ?? this.proposal?.revision ?? ''}`],
      ['Git 基线', packet.baseCommit || this.proposal?.baseCommit || '服务未提供'],
      ['角色', (packet.roles || packet.roleScope || []).map?.(item => typeof item === 'string' ? item : item.name || item.id).join('、') || packet.role || '服务按项目规则分配'],
      ['实施范围', typeof packet.scope === 'string' ? packet.scope : JSON.stringify(packet.scope || packet.targets || packet.requirements || [])],
      ['验收条件', JSON.stringify(packet.acceptance || packet.acceptanceCriteria || packet.tests || [])],
      ['保留约束', JSON.stringify(packet.preservationConstraints || packet.constraints || [])],
      ['停止条件', JSON.stringify(packet.stopConditions || packet.stopCondition || '遵循冻结表单与项目规则')],
    ];
    const list = el('dl', 'packet-list'); for (const [label, value] of fields) list.append(el('dt', '', label), el('dd', '', String(value ?? '未提供'))); container.append(list);
  }
  async createJob(packet = this.packet, { context = this.captureSelectionContext(), proposal = this.proposal } = {}) {
    if (!packet) throw new Error('没有可恢复的冻结制作表单。');
    const packetId = packet.packetId || packet.id, proposalId = proposal?.id;
    // A frozen packet identifies one dispatch intent. Retrying after an uncertain
    // network outcome must address the same intent, never create a replacement job.
    const idempotencyKey = `packet:${packetId}`;
    const response = await this.request('/jobs', { method: 'POST', token: true, body: { packetId, idempotencyKey } });
    const job = response.job || response;
    if (!job.id) throw new Error('服务没有返回作业编号。');
    if (!this.selectionContextMatches(context) || this.packet?.id !== packet.id && this.packet?.packetId !== packetId || proposalId && this.proposal?.id !== proposalId) return null;
    this.job = job;
    this.renderJob(); this.beginPolling(); if (this.job.projectId) await this.loadWorkbench(this.job.projectId);
    return this.job;
  }
  async loadJob(id, poll = true) {
    const context = this.captureSelectionContext(), generation = ++this.jobLoadGeneration;
    try { const response = await this.request(`/jobs/${encodeURIComponent(id)}`); const job = response.job || response; if (!this.selectionContextMatches(context) || generation !== this.jobLoadGeneration || job.id !== id) return; this.job = job; this.renderJob(); if (poll && !TERMINAL.has(this.job.status)) this.beginPolling(); }
    catch (error) { if (this.selectionContextMatches(context) && generation === this.jobLoadGeneration) this.notify(`无法读取作业状态：${error.message}`); }
  }
  renderJob() {
    if (!this.job) return; hide($('#job-panel'), false); setStatus($('#job-status'), this.job.status);
    $('#job-message').textContent = this.job.message || (this.job.sessionId ? `制作会话已建立：${this.job.sessionId}` : '正在等待服务更新进度。');
    const evidence = $('#job-evidence'); evidence.replaceChildren();
    if (this.job.verification) this.renderEvidence(this.job.verification, evidence);
    const canCancel = ['QUEUED', 'DISPATCHING', 'RUNNING', 'VERIFYING', 'PROJECTING'].includes(this.job.status);
    hide($('#cancel-area'), !canCancel);
    hide($('#reconcile-area'), this.job.status !== 'UNCERTAIN');
    const candidate = this.job.candidate || this.job.response?.candidate;
    if (candidate) { this.renderCandidate(candidate); hide($('#candidate-area'), false); } else hide($('#candidate-area'));
    if ((this.packet?.operationKind || this.job.operationKind) === 'INITIALIZATION' && this.job.status === 'PUBLISHED') {
      const nextProposal = this.job.nextProposal || this.job.response?.nextProposal;
      if (nextProposal) { this.proposal = nextProposal; this.renderProposal(); }
      else {
        const stage = el('div', 'notice', '工程准备阶段已完成。玩法实现尚未开始；需要服务返回项目内规划、测试基线和新的精确制作提案，完成后再单独确认。');
        $('#job-evidence').append(stage);
      }
    }
    if (this.job.projectId && (this.snapshot?.projectId || this.snapshot?.id) !== this.job.projectId) this.ensureWorkbench(this.job.projectId).catch(() => {});
    if (TERMINAL.has(this.job.status)) this.stopPolling();
  }
  renderEvidence(verification, root) {
    const card = el('div', 'evidence-card'); card.append(el('h3', '', `运行验证：${verification.status || '状态未知'}`));
    if (verification.runId) card.append(el('p', 'meta-line', `运行记录 ${verification.runId}`));
    const checks = verification.requirements || verification.checks || [];
    if (checks.length) { const list = el('ul', 'evidence-list'); for (const check of checks) list.append(el('li', '', `${check.status || '未知'} · ${check.requirement || check.title || check.id || ''}${check.message ? `：${check.message}` : ''}`)); card.append(list); }
    if (this.objectsWorkflow()) card.append(el('p', 'muted', '技术检查结果只表示服务实际运行并记录的检查项。未被自动验证的玩法体验、平衡和视觉质量仍需用户实际体验确认。'));
    root.append(card);
  }
  renderCandidate(candidate) {
    const area = $('#candidate-area'); area.replaceChildren(el('h3', '', '制作候选结果'));
    const rows = [['Git 版本', candidate.candidateCommit || candidate.commit || '未提供'], ['映射状态', candidate.catalogStatus || candidate.mappingStatus || '未声明'], ['可编辑能力', (candidate.capabilities || []).map(c => c.label || c.id || c).join('、') || '服务未提供'], ['变更摘要', candidate.summary || candidate.message || '查看下方候选详情']];
    const list = el('dl', 'packet-list'); for (const [label, value] of rows) list.append(el('dt', '', label), el('dd', '', String(value))); area.append(list);
    if (this.objectsWorkflow()) {
      const mappings = candidate.objectMappings || candidate.catalog?.objects || candidate.objects || [];
      if (mappings.length) { area.append(el('h4', '', '候选对象映射')); const mappingList = el('ul', 'requirement-list'); for (const item of mappings) mappingList.append(el('li', '', `${item.name || item.id} · ${item.status || item.mappingStatus || (item.sourceBindings?.length ? item.sourceBindings.join('、') : '映射待核对')}`)); area.append(mappingList); }
      const diff = candidate.objectDiff || candidate.objectChanges || candidate.diff?.objects; if (diff) { area.append(el('h4', '', '对象差异')); area.append(el('pre', 'object-diff', typeof diff === 'string' ? diff : JSON.stringify(diff, null, 2))); }
      area.append(el('p', 'muted', '对象映射与技术证据供你审阅。未被自动观察的玩法和视觉体验仍需你运行候选并决定是否接受。'));
    }
    if (candidate.previewAvailable === true) { const preview = el('button', 'button secondary', '在 Godot 中运行此候选'); preview.type = 'button'; preview.addEventListener('click', () => this.previewCandidate()); area.append(preview); }
    if (candidate.verification) this.renderEvidence(candidate.verification, area);
    const commit = candidate.candidateCommit || candidate.commit;
    if (this.job.status === 'READY_FOR_REVIEW' && commit) {
      const review = el('div', 'decision-actions');
      const testing = !!this.workspace?.testData;
      const accept = el('button', 'button primary', testing ? '接受此测试候选' : '接受并发布此版本'); accept.type = 'button'; accept.disabled = !this.reviewSnapshotMatchesJob(); accept.addEventListener('click', () => this.decideCandidate('accept', commit));
      const reject = el('button', 'button danger', testing ? '拒绝此测试候选' : '拒绝此候选'); reject.type = 'button'; reject.disabled = !this.reviewSnapshotMatchesJob(); reject.addEventListener('click', () => this.decideCandidate('reject', commit));
      review.append(accept, reject); area.append(review, el('p', 'muted', testing ? '测试工作区决定仅用于验证服务流程，不代表生产用户验收。' : '你的选择会作为工作台决定发送到本机服务。'));
    }
  }
  async previewCandidate() {
    if (!this.job?.id) return;
    const status = el('p', 'muted', '正在请求本机 Godot 打开已验证的候选版本…'); $('#candidate-area').append(status);
    try {
      const response = await this.request(`/jobs/${encodeURIComponent(this.job.id)}/preview`, { method: 'POST', token: true, body: {} });
      status.textContent = `${response.message || '本机 Godot 已接受运行请求。'}${response.sourceCommit ? ` · Git ${response.sourceCommit}` : ''}`;
      status.className = 'success-notice';
    } catch (error) { status.textContent = `运行预览没有确认：${error.message}`; status.className = 'notice'; }
  }
  async decideCandidate(decision, candidateCommit) {
    if (!this.job?.id || !this.reviewSnapshotMatchesJob()) return;
    const context = this.captureSelectionContext(), jobId = this.job.id, expectedRevision = this.snapshot.publicationRevision, generation = ++this.jobMutationGeneration;
    const testing = !!this.workspace?.testData;
    const label = testing ? (decision === 'accept' ? '接受测试候选' : '拒绝测试候选') : (decision === 'accept' ? '接受并发布' : '拒绝');
    if (typeof globalThis.confirm === 'function' && !globalThis.confirm(`确认${label}候选版本 ${candidateCommit}？`)) return;
    try {
      const response = await this.request(`/jobs/${encodeURIComponent(jobId)}/decision`, { method: 'POST', token: true, body: { decision, candidateCommit, expectedPublicationRevision: expectedRevision } });
      if (!this.selectionContextMatches(context) || generation !== this.jobMutationGeneration || this.job?.id !== jobId) return;
      this.job = response.job || this.job;
      if (response.snapshot && (response.snapshot.projectId || response.snapshot.id) === (this.snapshot?.projectId || this.snapshot?.id)) this.snapshot = response.snapshot;
      this.renderJob();
      if (decision === 'accept' && this.job.projectId && this.selectionContextMatches(context)) await this.loadWorkbench(this.job.projectId);
      this.notify(testing ? `服务已记录${label}；此结果属于测试工作区。` : (decision === 'accept' ? '服务已记录接受决定；请核对返回的发布版本。' : '服务已记录拒绝决定；当前已发布版本保持不变。'));
    } catch (error) { if (this.selectionContextMatches(context) && generation === this.jobMutationGeneration && this.job?.id === jobId) this.notify(`决定未被确认：${error.message}${error.status === 409 ? ' 版本已变化，请刷新并重新审阅。' : ''}`); }
  }
  reviewSnapshotMatchesJob() { return !!this.job?.projectId && (!$('#project')?.value || $('#project').value === this.job.projectId) && this.snapshotMatchesProject(this.job.projectId); }
  beginPolling() { this.stopPolling(); if (!this.job?.id) return; this.pollHandle = this.timers.setInterval(() => this.loadJob(this.job.id, false), 2500); }
  stopPolling() { if (this.pollHandle != null) this.timers.clearInterval(this.pollHandle); this.pollHandle = null; }
  async cancelJob() {
    if (!this.job?.id) return; const context = this.captureSelectionContext(), jobId = this.job.id, generation = ++this.jobMutationGeneration; $('#cancel').disabled = true;
    try { const response = await this.request(`/jobs/${encodeURIComponent(jobId)}/cancel`, { method: 'POST', token: true, body: {} }); if (!this.selectionContextMatches(context) || generation !== this.jobMutationGeneration || this.job?.id !== jobId) return; this.job = response.job || response; this.renderJob(); }
    catch (error) { if (this.selectionContextMatches(context) && generation === this.jobMutationGeneration && this.job?.id === jobId) this.notify(`取消请求没有确认：${error.message}`); }
    finally { if (this.selectionContextMatches(context) && generation === this.jobMutationGeneration) $('#cancel').disabled = false; }
  }
  async reconcileJob() {
    if (!this.job?.id) return; const context = this.captureSelectionContext(), jobId = this.job.id, generation = ++this.jobMutationGeneration;
    $('#reconcile').disabled = true;
    try { const response = await this.request(`/jobs/${encodeURIComponent(jobId)}/reconcile`, { method: 'POST', token: true, body: {} }); if (!this.selectionContextMatches(context) || generation !== this.jobMutationGeneration || this.job?.id !== jobId) return; this.job = response.job || response; this.renderJob(); }
    catch (error) { if (this.selectionContextMatches(context) && generation === this.jobMutationGeneration && this.job?.id === jobId) this.notify(`对账结果未确认：${error.message}。系统不会自动重新派发。`); }
    finally { if (this.selectionContextMatches(context) && generation === this.jobMutationGeneration) $('#reconcile').disabled = false; }
  }
  async loadWorkbench(projectId) {
    const generation = ++this.workbenchGeneration;
    const previous = this.snapshot;
    const switchingProject = previous && (previous.projectId || previous.id) !== projectId;
    let priorDraft = previous ? this.readVisibleDraft() : null;
    if (this.draftTimer != null) {
      this.timers.clearTimeout(this.draftTimer); this.draftTimer = null; await this.saveDraft();
      if (generation === this.workbenchGeneration && this.snapshot === previous && previous) priorDraft = this.readVisibleDraft();
    }
    if (!previous || switchingProject) $('#edit-text').value = '';
    const response = await this.request(`/projects/${encodeURIComponent(projectId)}/workbench`);
    if (generation !== this.workbenchGeneration) return null;
    const loadedSnapshot = response.snapshot || response;
    if ((loadedSnapshot.projectId || loadedSnapshot.id) !== projectId) throw new Error('服务返回的项目版本与所选项目不匹配。');
    const sameProject = previous && (previous.projectId || previous.id) === projectId;
    const publicationChanged = sameProject && previous.publicationRevision !== loadedSnapshot.publicationRevision;
    if (!sameProject || publicationChanged) this.fieldDraftValues = {};
    this.snapshot = loadedSnapshot; this.capabilities = response.capabilities || this.snapshot.capabilities || null; this.workflow = this.snapshot.workflow || response.workflow || this.workspace?.projects?.find(p => p.id === projectId)?.workflow || null; this.candidates = response.candidates || [];
    if (this.pendingRebase && (this.pendingRebase.generation !== generation || this.pendingRebase.nextSnapshot !== loadedSnapshot)) {
      this.pendingRebase = null;
      const dialog = $('#rebase-dialog'); if (dialog?.open) dialog.close();
    }
    const projectSelect = $('#project'); if (projectSelect) projectSelect.value = projectId;
    hide($('#workbench-panel'), false); this.renderWorkbench();
    const changed = previous && (previous.projectId || previous.id) === (this.snapshot.projectId || this.snapshot.id) && previous.publicationRevision !== this.snapshot.publicationRevision;
    if (changed) {
      $('#edit-text').value = '';
      const oldKey = this.makeDraftKey(previous);
      const carryDraft = this.unrebasedDraft?.projectId === (previous.projectId || previous.id) ? this.unrebasedDraft.draft : priorDraft;
      this.handleRebase(previous, this.snapshot, carryDraft);
    } else if (!previous || (previous.projectId || previous.id) !== (this.snapshot.projectId || this.snapshot.id)) await this.restoreDraft(generation);
    if (generation !== this.workbenchGeneration || (this.snapshot.projectId || this.snapshot.id) !== projectId) return null;
    this.renderCandidates();
    if (this.job?.candidate || this.job?.response?.candidate) this.renderJob();
  }
  readVisibleDraft() {
    const values = {}; for (const key of TEMPLATE_FIELDS) { const input = this.parameterInput(key); if (input?.value) values[key] = Number(input.value); }
    if (this.objectsWorkflow()) this.captureVisibleFields();
    return { text: $('#edit-text')?.value || '', values, fields: { ...this.fieldDraftValues }, feedback: this.feedback || [], feedbackMessage: $('#feedback-message')?.value || '', feedbackCategory: $('#feedback-category')?.value || 'general', selectedObjectId: this.selectedObjectId, draftRevision: this.draftRevision };
  }
  applyVisibleDraft(draft) {
    $('#edit-text').value = draft.text || ''; this.feedback = Array.isArray(draft.feedback) ? draft.feedback : []; $('#feedback-message').value = draft.feedbackMessage || ''; $('#feedback-category').value = draft.feedbackCategory || 'general'; this.selectedObjectId = draft.selectedObjectId || this.selectedObjectId; this.fieldDraftValues = { ...(draft.fields || {}) };
    if (this.objectsWorkflow()) { this.renderDynamicFields(this.objectItems(), this.capabilities); this.renderObjectCatalog(this.objectItems()); }
    for (const key of TEMPLATE_FIELDS) { const input = this.parameterInput(key); if (draft.values?.[key] != null && input && !input.disabled) input.value = draft.values[key]; }
    for (const input of $('#dynamic-fields')?.querySelectorAll('[data-field-id]:not([data-axis])') || []) { if (draft.fields?.[input.dataset.fieldId] != null && !input.disabled) this.writeControlValue(input, draft.fields[input.dataset.fieldId]); }
    this.renderObjectDetail(); this.renderFeedback();
  }
  renderCandidates() {
    const root = $('#candidate-preview'); root.replaceChildren();
    if (!this.candidates.length) { hide(root); return; }
    root.append(el('h3', '', '待审阅的候选结果'));
    for (const candidate of this.candidates) {
      const card = el('article', 'candidate-card'); card.append(el('b', '', candidate.title || candidate.summary || candidate.candidateCommit || candidate.commit || '候选结果'));
      card.append(el('p', 'meta-line', `状态：${JOB_LABELS[candidate.status] || candidate.status || '等待审阅'} · Git ${candidate.candidateCommit || candidate.commit || '未提供'}`));
      if (candidate.jobId) { const open = el('button', 'button secondary', '查看结果与证据'); open.type = 'button'; open.addEventListener('click', () => this.loadJob(candidate.jobId)); card.append(open); }
      root.append(card);
    }
    hide(root, false);
  }
  renderWorkbench() {
    if (!this.snapshot) return; const snap = this.snapshot;
    $('#workbench-title').textContent = snap.title || snap.projectTitle || '当前工作台'; setStatus($('#snapshot-version'), 'PUBLISHED', `版本 ${snap.publicationRevision ?? '未知'}`);
    const summary = $('#snapshot-summary'); summary.replaceChildren();
    summary.append(el('p', 'proposal-summary', snap.summary || snap.description || '这是项目当前已发布的工作台快照。'));
    if (snap.kind === 'CONCEPT') summary.append(el('div', 'notice', '当前处于概念阶段，尚未制作或验证工程；完成策划并确认范围后进入制作。'));
    else if (snap.kind === 'INITIALIZATION') summary.append(el('div', 'notice', '当前版本是已验证的工程准备基线，尚不包含可玩的 MVP。玩法实现需要独立规划和确认。'));
    else if (snap.playable === false) summary.append(el('div', 'notice', '当前版本尚无可玩的 MVP。玩法实现需要独立策划和确认。'));
    else if (snap.kind === 'MVP' && snap.playable === true) summary.append(el('div', 'success-notice', this.objectsWorkflow()
      ? '已通过 Godot 技术检查；玩法与视觉体验仍需你实际确认。'
      : '可运行的 MVP 已通过服务声明的验证。'));
    if (snap.baseCommit || snap.sourceCommit) summary.append(el('p', 'meta-line', `Git 版本：${snap.baseCommit || snap.sourceCommit}`));
    const objects = this.objectItems(snap);
    if (this.objectsWorkflow()) this.renderObjectCatalog(objects);
    else if (objects.length) { summary.append(el('h3', '', '可编辑内容')); const list = el('div', 'object-list'); for (const object of objects.slice(0, 12)) { const row = el('div', 'object-row'); row.append(el('b', '', object.name || object.label || object.id)); row.append(el('span', 'muted', object.editable === false ? '只读' : '可编辑')); list.append(row); } summary.append(list); }
    const capabilities = this.capabilities?.fields || this.capabilities?.parameters || this.capabilities || {};
    const pendingInitialization = snap.kind === 'INITIALIZATION' || snap.playable === false;
    if (this.objectsWorkflow()) { this.selectedObjectId = objects.some(o => o.id === this.selectedObjectId) ? this.selectedObjectId : (objects[0]?.id || null); this.renderDynamicFields(objects, capabilities); this.renderObjectCatalog(objects); this.renderObjectDetail(); this.renderFeedback(); this.draftKey = this.makeDraftKey(snap); this.showDraftState(); return; }
    this.renderDynamicFields(objects, capabilities);
    for (const key of TEMPLATE_FIELDS) {
      const input = this.parameterInput(key); if (!input) continue;
      const cap = Array.isArray(capabilities) ? capabilities.find(item => item.id === key || item.name === key) : capabilities[key];
      const range = Array.isArray(cap?.range) ? cap.range : null;
      const min = Number(cap?.min ?? cap?.limits?.min ?? range?.[0]);
      const max = Number(cap?.max ?? cap?.limits?.max ?? range?.[1]);
      const bounded = Number.isFinite(min) && Number.isFinite(max) && max >= min;
      const declared = cap === true || (cap && typeof cap === 'object' && (cap.editable === true || cap.supported === true || cap.enabled === true));
      const supported = !!declared && bounded && !pendingInitialization;
      input.min = bounded ? String(min) : ''; input.max = bounded ? String(max) : '';
      input.step = cap?.integer === true || key === 'goalCount' ? '1' : String(cap?.step || 'any');
      const boundLabel = $(`[data-bound-for="${key}"]`); if (boundLabel) boundLabel.textContent = bounded ? `${min}–${max}` : '服务未提供范围';
      input.disabled = !supported; input.value = supported && snap.decisions?.[key] != null ? snap.decisions[key] : '';
      input.closest('label').classList.toggle('unsupported', !supported);
    }
    $('#capability-note').textContent = '灰色项目表示此工程尚未声明支持；提交前会由服务再次校验。';
    this.draftKey = this.makeDraftKey(snap); this.showDraftState();
  }
  allCapabilities(capabilities = this.capabilities) {
    const source = capabilities?.fields || capabilities?.parameters || capabilities || {};
    if (Array.isArray(source)) return source;
    return Object.entries(source).map(([id, value]) => typeof value === 'object' ? { id, ...value } : { id, editable: value === true, type: 'scalar' });
  }
  splitCapability(cap) {
    const pieces = String(cap.objectId && cap.fieldId ? `${cap.objectId}.${cap.fieldId}` : cap.id || cap.name || '').split('.');
    return { objectId: cap.objectId || pieces.shift() || '', fieldId: cap.fieldId || pieces.join('.') };
  }
  capabilityValue(cap, object) {
    const [, fieldId] = [null, this.splitCapability(cap).fieldId];
    const objField = (object.fields || []).find(field => field.id === fieldId) || object[fieldId];
    return cap.currentValue ?? cap.value ?? objField?.currentValue ?? objField?.value ?? '';
  }
  renderObjectCatalog(objects) {
    const root = $('#object-catalog'), list = $('#object-list'); list.replaceChildren();
    if (!objects.length) { hide(root); return; }
    for (const object of objects) {
      const button = el('button', `object-row${object.id === this.selectedObjectId ? ' selected' : ''}`); button.type = 'button'; button.dataset.objectId = object.id;
      button.append(el('b', '', object.name || object.label || object.id), el('span', 'muted', object.kind || '对象')); list.append(button);
    }
    hide(root, false);
  }
  renderObjectDetail() {
    const root = $('#object-detail'); if (!root) return; root.replaceChildren();
    const object = this.objectItems().find(item => item.id === this.selectedObjectId);
    $('#selected-object-label').textContent = object ? `当前对象：${object.name || object.id}（${object.id}）` : '未选择对象；可先从项目对象中选择。';
    if (!object) return;
    root.append(el('h4', '', object.name || object.id)); if (object.description) root.append(el('p', '', object.description));
    const relations = object.relations || []; if (relations.length) root.append(el('p', 'muted', `关系：${relations.map(r => `${r.type || '关联'} → ${r.targetId || r.target}`).join('、')}`));
    if (object.parentId) root.append(el('p', 'muted', `父对象：${object.parentId}`));
    if (object.sourceBindings?.length) root.append(el('p', 'meta-line', `源文件：${object.sourceBindings.join('、')}`));
    const fieldRoot = $('#dynamic-fields'); const caps = this.allCapabilities();
    const fields = caps.filter(cap => this.splitCapability(cap).objectId === object.id);
    if (fields.length) {
      const heading = el('h4', '', '可编辑属性'); root.append(heading);
      for (const cap of fields) { const fieldId = this.splitCapability(cap).fieldId; const field = (object.fields || []).find(item => item.id === fieldId); root.append(el('p', 'muted', `${cap.label || field?.label || fieldId} · ${this.capabilityEditable(cap, object) ? '可编辑' : '只读'}`)); }
    }
    if (fieldRoot) fieldRoot.dataset.selectedObjectId = object.id;
  }
  capabilityEditable(cap, object) {
    if (object?.editable === false) return false;
    if (this.objectsWorkflow()) return cap.editable === true;
    return cap.editable === true || cap.supported === true || cap.enabled === true;
  }
  selectObject(objectId) { if (!this.objectItems().some(object => object.id === objectId)) return; this.captureVisibleFields(); this.selectedObjectId = objectId; this.renderDynamicFields(this.objectItems(), this.capabilities); this.renderObjectCatalog(this.objectItems()); this.renderObjectDetail(); this.renderFeedback(); this.queueDraftSave(); }
  renderDynamicFields(objects, capabilities) {
    const root = $('#dynamic-fields'); if (!root) return; root.replaceChildren();
    const caps = this.allCapabilities(capabilities).filter(cap => this.splitCapability(cap).objectId === this.selectedObjectId);
    const object = objects.find(item => item.id === this.selectedObjectId);
    for (const cap of caps) {
      const { objectId, fieldId } = this.splitCapability(cap); const field = (object?.fields || []).find(item => item.id === fieldId) || {};
      const type = cap.type || field.type || 'text'; const editable = this.capabilityEditable(cap, object);
      const label = el('label', 'dynamic-field'); label.append(el('span', 'field-label', cap.label || field.label || fieldId));
      if (cap.description || field.description) label.append(el('small', 'muted', cap.description || field.description));
      const current = this.capabilityValue(cap, object || {}); let control;
      if (type === 'choice') { const options = cap.options || field.options || []; control = el('select'); this.configureChoice(control, options); }
      else if (type === 'boolean') { control = el('select'); for (const [value, title] of [['', '请选择'], ['true', '是'], ['false', '否']]) { const opt = el('option', '', title); opt.value = value; control.append(opt); } }
      else if (type === 'vector2') {
        control = el('div', 'vector2-control'); control.dataset.vector = 'true'; control.append(el('span', 'muted', 'X'));
        for (const axis of ['x', 'y']) { const input = el('input'); input.type = 'number'; input.step = String(cap.step || field.step || 'any'); input.dataset.axis = axis; input.setAttribute('aria-label', `${cap.label || field.label || fieldId} ${axis.toUpperCase()}`); control.append(input); }
      }
      else if (type === 'text') { control = el('textarea'); control.rows = 2; control.maxLength = Number(cap.maxLength || field.maxLength || 2000); }
      else { control = el('input'); control.type = 'number'; control.step = type === 'integer' || cap.integer ? '1' : String(cap.step || field.step || 'any'); for (const bound of ['min', 'max']) { const value = cap[bound] ?? field[bound]; if (value != null) control[bound] = String(value); } }
      control.name = this.legacyFieldName(objectId, fieldId); control.dataset.fieldId = `${objectId}.${fieldId}`; control.dataset.capabilityId = cap.id || `${objectId}.${fieldId}`; control.dataset.objectId = objectId; control.dataset.type = type; control.disabled = !editable;
      if (type === 'vector2') { const v = Object.hasOwn(this.fieldDraftValues, control.dataset.fieldId) ? this.fieldDraftValues[control.dataset.fieldId] : current; this.writeControlValue(control, v); for (const input of control.querySelectorAll('input')) { input.dataset.fieldId = control.dataset.fieldId; input.dataset.capabilityId = control.dataset.capabilityId; input.dataset.objectId = objectId; input.dataset.type = type; input.disabled = !editable; } }
      else this.writeControlValue(control, Object.hasOwn(this.fieldDraftValues, control.dataset.fieldId) ? this.fieldDraftValues[control.dataset.fieldId] : current);
      if (!this.objectsWorkflow() && TEMPLATE_FIELDS.includes(fieldId)) control.name = fieldId;
      label.append(control); root.append(label);
    }
    if (!caps.length) root.append(el('p', 'muted', object ? '此对象当前没有服务声明可编辑的属性。' : '请选择对象查看可编辑属性。'));
    // Keep the legacy three-field contract available only for legacy projects.
    if (!this.objectsWorkflow()) this.renderLegacyFields(capabilities);
  }
  legacyFieldName(objectId, fieldId) { return fieldId; }
  renderLegacyFields(capabilities) {
    const root = $('#dynamic-fields');
    for (const key of TEMPLATE_FIELDS) {
      if (root.querySelector(`[name="${key}"]`)) continue;
      const cap = Array.isArray(capabilities?.fields) ? capabilities.fields.find(item => item.id === key || item.name === key) : (capabilities?.fields || capabilities?.parameters || capabilities || {})[key];
      const range = Array.isArray(cap?.range) ? cap.range : null; const min = cap?.min ?? cap?.limits?.min ?? range?.[0]; const max = cap?.max ?? cap?.limits?.max ?? range?.[1];
      const label = el('label', 'dynamic-field'); label.append(el('span', 'field-label', LABELS[key]));
      const input = el('input'); input.type = 'number'; input.name = key; input.dataset.fieldId = key; input.dataset.capabilityId = key; input.dataset.objectId = 'player'; input.dataset.type = 'scalar'; input.min = min ?? ''; input.max = max ?? ''; input.step = cap?.integer === true || key === 'goalCount' ? '1' : String(cap?.step || 'any');
      input.disabled = !(cap === true || cap && (cap.editable === true || cap.supported === true || cap.enabled === true)) || min == null || max == null;
      input.value = this.snapshot?.decisions?.[key] ?? ''; label.append(input); root.append(label);
    }
  }
  readControlValue(control) {
    const type = control.dataset.type || 'text';
    if (type === 'vector2') { const x = control.querySelector('[data-axis="x"]')?.value, y = control.querySelector('[data-axis="y"]')?.value; return x === '' || y === '' ? '' : [Number(x), Number(y)]; }
    if (type === 'boolean') return control.value === '' ? '' : control.value === 'true';
    if (type === 'choice') return this.readChoiceValue(control);
    if (['scalar', 'number', 'integer'].includes(type)) return control.value === '' ? '' : Number(control.value);
    return control.value;
  }
  configureChoice(control, options) {
    const values = options.map(option => typeof option === 'object' ? option.value : option);
    const labels = options.map(option => typeof option === 'object' ? option.label || option.value : option);
    const ambiguous = new Set(values.map(value => String(value))).size !== values.length;
    control.dataset.optionValues = JSON.stringify(values); control.dataset.optionMode = ambiguous ? 'index' : 'value';
    const placeholder = el('option', '', '请选择'); placeholder.value = ''; control.append(placeholder);
    for (const [index, label] of labels.entries()) { const opt = el('option', '', label); opt.value = ambiguous ? `__option_${index}` : String(values[index]); control.append(opt); }
  }
  readChoiceValue(control) {
    if (control.value === '') return '';
    const values = JSON.parse(control.dataset.optionValues || '[]');
    if (control.dataset.optionMode === 'index') { const index = Number(control.value.slice('__option_'.length)); return Number.isInteger(index) ? values[index] ?? '' : ''; }
    return values.find(value => String(value) === control.value) ?? control.value;
  }
  writeControlValue(control, value) {
    if (value == null) return;
    if (control.dataset.type === 'vector2') { for (const [index, axis] of ['x', 'y'].entries()) { const input = control.querySelector(`[data-axis="${axis}"]`); if (input) input.value = value[index] ?? ''; } }
    else if (control.dataset.type === 'choice') { const values = JSON.parse(control.dataset.optionValues || '[]'); const index = values.findIndex(candidate => JSON.stringify(candidate) === JSON.stringify(value)); control.value = index < 0 ? '' : control.dataset.optionMode === 'index' ? `__option_${index}` : String(value); }
    else if (control.dataset.type === 'boolean') control.value = value === true ? 'true' : value === false ? 'false' : '';
    else control.value = String(value);
  }
  captureVisibleFields() { for (const control of $('#dynamic-fields')?.querySelectorAll('[data-capability-id]:not([data-axis])') || []) { if (!control.disabled) { const value = this.readControlValue(control); if (value !== '') this.fieldDraftValues[control.dataset.fieldId] = value; } } }
  onDynamicFieldEdit(control) { if (control.disabled) return; const root = control.closest('[data-vector="true"]') || control; const id = root.dataset.fieldId; if (id) { this.dirtyFields.add(id); const value = this.readControlValue(root); if (value === '' && root.dataset.type !== 'text') delete this.fieldDraftValues[id]; else this.fieldDraftValues[id] = value; } this.queueDraftSave(); }
  addFeedback() {
    const message = $('#feedback-message').value.trim(); if (!message) return this.notify('先写下反馈内容。');
    if (!this.selectedObjectId) return this.notify('先选择一个关联对象。');
    this.feedback.push({ objectId: this.selectedObjectId, message, category: $('#feedback-category').value || 'general' }); $('#feedback-message').value = ''; this.renderFeedback(); this.queueDraftSave();
  }
  renderFeedback() {
    const list = $('#feedback-list'); if (!list) return; list.replaceChildren();
    for (const [index, item] of (this.feedback || []).entries()) { const row = el('li', 'feedback-item', `${item.objectId} · ${item.category}：${item.message}`); const remove = el('button', 'quiet', '移除'); remove.type = 'button'; remove.addEventListener('click', () => { this.feedback.splice(index, 1); this.renderFeedback(); this.queueDraftSave(); }); row.append(remove); list.append(row); }
  }
  buildChangeRequest() {
    const fields = [];
    this.captureVisibleFields();
    for (const [id, value] of Object.entries(this.fieldDraftValues)) {
      const [objectId, ...rest] = id.split('.'), fieldId = rest.join('.');
      const currentCap = this.allCapabilities().find(cap => { const parts = this.splitCapability(cap); return parts.objectId === objectId && parts.fieldId === fieldId; });
      const object = this.objectItems().find(item => item.id === objectId);
      if (!currentCap || !this.capabilityEditable(currentCap, object)) continue;
      if (value === '' && currentCap.type !== 'text') continue;
      const current = this.capabilityValue(currentCap, object || {});
      const type = currentCap.type || 'text';
      const normalizedValue = type === 'boolean' ? Boolean(value) : ['scalar', 'number', 'integer'].includes(type) ? Number(value) : value;
      const normalizedCurrent = type === 'boolean' ? Boolean(current) : ['scalar', 'number', 'integer'].includes(type) && current !== '' ? Number(current) : current;
      if (JSON.stringify(normalizedValue) === JSON.stringify(normalizedCurrent)) continue;
      fields.push({ objectId, fieldId, value });
    }
    const feedback = [...(this.feedback || [])]; const targetObjectIds = [...new Set([...(this.selectedObjectId ? [this.selectedObjectId] : []), ...fields.map(field => field.objectId), ...feedback.map(item => item.objectId)])];
    return { baseRevision: this.snapshot.publicationRevision, sourceCommit: this.snapshot.sourceCommit || this.snapshot.baseCommit, targetObjectIds, fields, feedback };
  }
  makeDraftKey(snap) { return `${this.workspace?.workspaceId || 'workspace'}:${snap.projectId || snap.id}:${snap.publicationRevision ?? 'unknown'}`; }
  async restoreDraft(expectedGeneration = this.workbenchGeneration) {
    if (!this.persistenceOK || !this.snapshot) return;
    const targetSnapshot = this.snapshot;
    const key = this.makeDraftKey(targetSnapshot);
    try {
      const draft = await this.drafts.get(key);
      if (expectedGeneration !== this.workbenchGeneration || this.snapshot !== targetSnapshot || (this.snapshot.projectId || this.snapshot.id) !== (targetSnapshot.projectId || targetSnapshot.id)) return;
      this.draftKey = key;
      if (draft) { this.applyVisibleDraft(draft); this.draftRevision = draft.draftRevision || 0; }
    }
    catch (error) {
      this.persistenceOK = false;
      if (this.draftContextMatches(key, expectedGeneration, targetSnapshot)) { $('#persistence-note').textContent = `读取草稿失败：${error.message}`; $('#persistence-note').className = 'muted danger-text'; }
    }
  }
  queueDraftSave() {
    if (this.draftTimer != null) this.timers.clearTimeout(this.draftTimer);
    this.draftTimer = this.timers.setTimeout(() => this.saveDraft(), 250);
  }
  async saveDraft() {
    this.draftTimer = null; if (!this.draftKey) return;
    if (!this.persistenceOK) { this.showDraftState('本地存储不可用，当前修改只在页面内暂存。请先复制保存文字。', true); return; }
    const key = this.draftKey, targetSnapshot = this.snapshot, generation = this.workbenchGeneration;
    try {
      const visible = this.readVisibleDraft();
      const record = { key, projectId: targetSnapshot.projectId || targetSnapshot.id, publicationRevision: targetSnapshot.publicationRevision, draftRevision: ++this.draftRevision, ...visible, updatedAt: new Date().toISOString() };
      await this.drafts.put(record);
      if (this.draftContextMatches(key, generation, targetSnapshot)) this.showDraftState(`已保存在此浏览器 · 草稿修订 ${record.draftRevision}`);
    } catch (error) {
      this.persistenceOK = false;
      if (this.draftContextMatches(key, generation, targetSnapshot)) { this.showDraftState(`草稿保存失败：${error.message}。请先复制保存文字。`, true); $('#persistence-note').textContent = '草稿存储写入失败。'; $('#persistence-note').className = 'muted danger-text'; }
    }
  }
  draftContextMatches(key, generation, snapshot) { return generation === this.workbenchGeneration && this.draftKey === key && this.snapshot === snapshot && this.makeDraftKey(snapshot) === key && ($('#project')?.value || '') === (snapshot.projectId || snapshot.id); }
  showDraftState(text = null, error = false) { const node = $('#draft-state'); if (!node) return; node.textContent = text || (this.draftKey ? '草稿按项目与已发布版本分别保存。' : '等待项目版本信息。'); node.className = `draft-state${error ? ' danger-text' : ''}`; }
  handleRebase(oldSnapshot, nextSnapshot, visibleDraft = null) {
    if (!this.draftKey || oldSnapshot.projectId !== nextSnapshot.projectId) return;
    const oldKey = this.unrebasedDraft?.projectId === (oldSnapshot.projectId || oldSnapshot.id) ? this.unrebasedDraft.key : this.makeDraftKey(oldSnapshot), newKey = this.makeDraftKey(nextSnapshot);
    if (oldKey === newKey) return;
    this.pendingRebase = { oldKey, newKey, oldSnapshot, nextSnapshot, draft: visibleDraft || this.readVisibleDraft(), persistenceOK: this.persistenceOK, generation: this.workbenchGeneration };
    this.unrebasedDraft = { key: oldKey, projectId: oldSnapshot.projectId || oldSnapshot.id, draft: this.pendingRebase.draft };
    this.renderRebasePreview(this.pendingRebase);
    const dialog = $('#rebase-dialog'); if (typeof dialog.showModal === 'function') dialog.showModal(); else this.showDraftState('版本已更新。请检查旧草稿与新基线后再继续。', true);
  }
  renderRebasePreview(pending) {
    const { oldSnapshot, nextSnapshot } = pending;
    const content = $('#rebase-content'); content.replaceChildren(el('p', '', `已发布版本从 ${oldSnapshot.publicationRevision} 更新到 ${nextSnapshot.publicationRevision}。当前草稿不会自动迁移。`));
    if (!pending.persistenceOK) content.append(el('p', 'muted danger-text', '本地存储不可用；确认后仅在当前页面内重关联，刷新或关闭页面后不会保留。'));
    const changes = el('ul', 'requirement-list'); changes.append(el('li', '', `旧基线：${oldSnapshot.baseCommit || oldSnapshot.sourceCommit || '未知'}`), el('li', '', `新基线：${nextSnapshot.baseCommit || nextSnapshot.sourceCommit || '未知'}`)); content.append(changes);
    const preview = el('div', 'rebase-preview'); preview.append(el('h3', '', '草稿预览'));
    if (pending.draft.text) preview.append(el('p', '', `保留自然语言调整：${pending.draft.text}`));
    const fieldPreview = el('ul', 'requirement-list');
    for (const [key, value] of Object.entries(pending.draft.values || {})) {
      const published = nextSnapshot.decisions?.[key];
      fieldPreview.append(el('li', '', `${LABELS[key]}：草稿 ${value}；新版本当前值 ${published ?? '未提供'}${published != null && Number(published) !== value ? '（需要人工核对）' : ''}`));
    }
    for (const [key, value] of Object.entries(pending.draft.fields || {})) {
      const [objectId, ...fieldParts] = key.split('.'), fieldId = fieldParts.join('.');
      const nextCaps = this.allCapabilities(nextSnapshot.capabilities || this.capabilities);
      const cap = nextCaps.find(item => { const parts = this.splitCapability(item); return parts.objectId === objectId && parts.fieldId === fieldId; });
      const type = cap?.type || 'text', valid = !!cap && cap.editable === true && ['scalar', 'number', 'integer', 'choice', 'text', 'boolean', 'vector2'].includes(type);
      fieldPreview.append(el('li', '', `${objectId}.${fieldId}：草稿 ${JSON.stringify(value)}${valid ? '；新版本仍声明支持此属性' : '；能力缺失或类型变化，需要人工修复'}`));
    }
    for (const feedback of pending.draft.feedback || []) fieldPreview.append(el('li', '', `${feedback.objectId} · ${feedback.category} 反馈：${feedback.message}`));
    if (fieldPreview.childNodes.length) preview.append(fieldPreview);
    if (!pending.draft.text && !fieldPreview.childNodes.length) preview.append(el('p', 'muted', '当前没有待重关联的修改内容。'));
    preview.append(el('p', 'muted', '此操作只复制草稿并标记待核对，不会发布或覆盖项目。')); content.append(preview);
  }
  rebaseContextMatches(pending) { return this.pendingRebase === pending && pending.generation === this.workbenchGeneration && this.snapshot === pending.nextSnapshot && this.makeDraftKey(this.snapshot) === pending.newKey && ($('#project')?.value || '') === (pending.nextSnapshot.projectId || pending.nextSnapshot.id); }
  sameReviewedDraft(preview, stored) {
    const canonical = values => JSON.stringify(Object.fromEntries(Object.entries(values || {}).sort(([a], [b]) => a.localeCompare(b))));
    return !!stored && preview.text === stored.text && (preview.draftRevision || 0) === (stored.draftRevision || 0) && canonical(preview.values) === canonical(stored.values) && canonical(preview.fields) === canonical(stored.fields) && canonical(preview.feedback) === canonical(stored.feedback) && (preview.feedbackMessage || '') === (stored.feedbackMessage || '') && (preview.feedbackCategory || 'general') === (stored.feedbackCategory || 'general') && (preview.selectedObjectId || null) === (stored.selectedObjectId || null);
  }
  async confirmRebase() {
    const pending = this.pendingRebase; if (!pending) return;
    try {
      if (!this.rebaseContextMatches(pending)) return;
      if (pending.persistenceOK) {
        const stored = await this.drafts.get(pending.oldKey);
        if (!this.rebaseContextMatches(pending)) return;
        if (!stored) { this.notify('未找到旧草稿；没有修改当前版本。'); return; }
        if (!this.sameReviewedDraft(pending.draft, stored)) { pending.draft = { ...stored, values: { ...(stored.values || {}) }, fields: { ...(stored.fields || {}) }, feedback: [...(stored.feedback || [])] }; this.unrebasedDraft = { ...this.unrebasedDraft, draft: pending.draft }; this.renderRebasePreview(pending); this.notify('旧草稿在预览后发生变化；已更新预览，请重新确认。'); return; }
      }
      const old = pending.draft;
      const migrated = { ...old, key: pending.newKey, previousKey: pending.oldKey, projectId: pending.nextSnapshot.projectId || pending.nextSnapshot.id, publicationRevision: pending.nextSnapshot.publicationRevision, draftRevision: (old.draftRevision || 0) + 1, rebaseNeedsReview: true, updatedAt: new Date().toISOString() };
      if (pending.persistenceOK) {
        await this.drafts.put(migrated);
        if (!this.rebaseContextMatches(pending)) return;
      }
      if (!this.rebaseContextMatches(pending)) return;
      this.draftKey = pending.newKey; this.applyVisibleDraft(migrated); this.draftRevision = migrated.draftRevision; this.pendingRebase = null; this.unrebasedDraft = null;
      $('#rebase-dialog').close?.(); this.showDraftState(pending.persistenceOK ? '草稿已复制到新基线并标记为待核对；原草稿仍保留。' : '草稿已在当前页面内重关联；本次修改不会持久保存。', true);
    } catch (error) { if (this.rebaseContextMatches(pending)) this.notify(`草稿迁移失败：${error.message}。旧草稿仍保留。`); }
  }
  async submitIteration() {
    if (this.pendingRebase) return this.notify('请先确认或取消草稿重关联，再提交迭代。');
    if (!this.readiness?.ready) return this.notify('新工作流尚未通过启动检查，调整不会提交。');
    if (this.selectionBusy) return this.notify('正在读取所选项目版本，请稍后再提交。');
    const selectedProject = $('#project').value;
    if (!selectedProject || !this.snapshotMatchesProject(selectedProject)) return this.notify('所选项目的版本尚未读取成功；当前调整没有提交。');
    if (this.proposal?.projectId === selectedProject && ['PLANNING', 'PLANNING_UNCERTAIN', 'NEEDS_CLARIFICATION', 'READY'].includes(this.proposal.status)) return this.notify('当前提案仍在策划或等待确认；请先完成、取消或对账本轮提案。');
    const text = $('#edit-text').value.trim(); const values = {};
    if (this.objectsWorkflow()) {
      const changeRequest = this.buildChangeRequest();
      if (!text && !changeRequest.fields.length && !changeRequest.feedback.length) return this.notify('写下对象调整或反馈，或修改一项明确支持的属性。');
      for (const field of changeRequest.fields) {
        const cap = this.allCapabilities().find(item => { const parts = this.splitCapability(item); return parts.objectId === field.objectId && parts.fieldId === field.fieldId; });
        if (cap?.min != null && Number(field.value) < Number(cap.min) || cap?.max != null && Number(field.value) > Number(cap.max)) return this.notify(`${cap.label || field.fieldId}超出允许范围。`);
        if (cap?.type === 'choice' && !(cap.options || []).some(option => String(typeof option === 'object' ? option.value : option) === String(field.value))) return this.notify(`${cap.label || field.fieldId}不在服务声明的选项中。`);
      }
      return this.submitConcept(text, true);
    }
    for (const key of TEMPLATE_FIELDS) { const input = this.parameterInput(key); if (!input || input.disabled || !input.value) continue; const value = Number(input.value); if (value < Number(input.min) || value > Number(input.max)) return this.notify(`${LABELS[key]}超出允许范围。`); values[key] = value; }
    if (!text && !Object.keys(values).length) return this.notify('写下调整内容，或修改一个受支持的选项。');
    const details = Object.entries(values).map(([key, value]) => `${LABELS[key]}调整为 ${value}`).join('；');
    await this.submitConcept([text, details].filter(Boolean).join('\n'), true);
  }
  notify(message) { const box = $('#notice'); if (!box) return; box.textContent = message; hide(box, false); box.scrollIntoView?.({ behavior: 'smooth', block: 'nearest' }); }
  destroy() { this.destroyed = true; this.stopPolling(); this.stopProposalPolling(); if (this.draftTimer != null) this.timers.clearTimeout(this.draftTimer); }
}

if (typeof document !== 'undefined' && document.getElementById('app')) {
  const studio = new StudioApp(); studio.start();
  globalThis.ptahStudio = studio;
  globalThis.addEventListener?.('pagehide', () => studio.destroy(), { once: true });
}
