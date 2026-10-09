const API = '/api';
const DRAFT_DB = 'ptah-studio-drafts-v1';
const TEMPLATE_FIELDS = ['goalCount', 'durationSeconds', 'playerSpeed'];
const LABELS = { goalCount: '收集目标', durationSeconds: '时限（秒）', playerSpeed: '移动速度' };
const JOB_LABELS = { QUEUED: '排队中', DISPATCHING: '准备制作', RUNNING: '制作中', VERIFYING: '运行验证', PROJECTING: '整理结果', READY_FOR_REVIEW: '等待你审阅', PUBLISHED: '已发布', REJECTED: '已拒绝', FAILED: '制作失败', BLOCKED: '暂时受阻', UNCERTAIN: '状态待核实', CANCEL_REQUESTED: '正在请求取消', CANCELLING: '正在停止', CANCELLED: '已取消' };
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
      const latestProposal = this.pendingProposal();
      if (latestProposal) {
        this.proposal = latestProposal;
        if (latestProposal.status === 'FROZEN') {
          this.packet = this.packetFor(latestProposal);
          this.renderProposal(); this.renderFrozenPacket();
          const associatedJob = this.jobFor(latestProposal, this.packet);
          if (associatedJob) await this.loadJob(associatedJob.id);
          else hide($('#resume-packet'), false);
        } else this.renderProposal();
      }
      const jobs = this.workspace.jobs;
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
      try {
        if (projectId) await this.openProject(projectId);
        else { this.snapshot = null; this.capabilities = null; this.candidates = []; this.draftKey = null; hide($('#workbench-panel')); $('#edit-text').value = ''; this.applyReadinessGate(); }
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
    $('#confirm-rebase')?.addEventListener('click', event => { event.preventDefault(); this.confirmRebase(); });
    $('#rebase-dialog')?.addEventListener('cancel', () => { this.pendingRebase = null; });
    $('#rebase-dialog')?.addEventListener('close', () => { if ($('#rebase-dialog').returnValue !== 'rebase') this.pendingRebase = null; });
    for (const field of ['#edit-text', ...TEMPLATE_FIELDS.map(name => `#edit-form [name="${name}"]`)]) $(field)?.addEventListener('input', () => this.queueDraftSave());
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
    try {
      this.workspace = await this.request('/workspace'); this.renderWorkspace();
      const pending = this.pendingProposal();
      if (pending && (!this.proposal || this.proposal.status === 'FROZEN' || this.proposal.id === pending.id)) {
        this.proposal = pending;
        if (pending.status === 'FROZEN') {
          this.packet = this.packetFor(pending);
          if (this.packet) {
            this.renderProposal(); this.renderFrozenPacket();
            const associated = this.jobFor(pending, this.packet);
            if (associated) await this.loadJob(associated.id, false);
            else hide($('#resume-packet'), false);
          }
        } else this.renderProposal();
      } else if (!pending && this.proposal) {
        this.proposal = null; this.packet = null; hide($('#proposal-panel'));
      }
      if (this.job && (this.workspace.jobs || []).some(item => item.id === this.job.id)) await this.loadJob(this.job.id, false);
      else {
        const latest = (this.workspace.jobs || []).find(item => ACTIVE.has(item.status)) || this.latestByDate(this.workspace.jobs || []);
        if (latest) await this.loadJob(latest.id, false);
      }
      const projectId = this.job?.projectId || this.snapshot?.projectId || this.snapshot?.id;
      if (projectId) await this.ensureWorkbench(projectId);
      $('#connection').textContent = '已连接本机服务'; $('#connection').className = 'connection connected';
    } catch (error) { this.notify(`刷新失败：${error.message}`); }
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
  pendingProposal() {
    const proposals = this.workspace?.proposals || [];
    return [...proposals].filter(item => {
      if (item.status === 'NEEDS_CLARIFICATION' || item.status === 'READY') return true;
      if (item.status !== 'FROZEN') return false;
      const packet = this.packetFor(item);
      if (!packet) return false;
      const job = this.jobFor(item, packet);
      return !job || ACTIVE.has(job.status);
    }).sort((a, b) => String(b.updatedAt || b.createdAt || '').localeCompare(String(a.updatedAt || a.createdAt || '')))[0] || null;
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
    const previousSnapshot = this.snapshot;
    const previousCapabilities = this.capabilities;
    const previousCandidates = this.candidates;
    const previousProjectId = previousSnapshot?.projectId || previousSnapshot?.id || $('#project').value;
    const previousDraft = previousSnapshot ? this.readVisibleDraft() : null;
    this.selectionBusy = true; this.applyReadinessGate();
    const load = this.loadWorkbench(projectId);
    const generation = this.workbenchGeneration;
    try { await load; }
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
  async submitConcept(iterationText = '') {
    if (!this.readiness?.ready) return this.notify('制作入口暂不可用；请先完成服务能力启动检查。');
    if (this.selectionBusy) return this.notify('正在读取所选项目版本，请稍后再提交。');
    const selectedProject = $('#project').value;
    if (selectedProject && !this.snapshotMatchesProject(selectedProject)) return this.notify('所选项目的版本尚未读取成功；请刷新该项目后再提交。');
    if (selectedProject && !Number.isInteger(this.snapshot.publicationRevision)) return this.notify('所选项目缺少有效发布版本号；没有提交提案。');
    const form = $('#concept-form'); const text = iterationText || $('#concept').value.trim();
    if (!text) return this.notify('先写下一个想法或调整目标。');
    const button = form.querySelector('[type="submit"]'); button.disabled = true;
    try {
      const expectedPublicationRevision = selectedProject ? this.snapshot.publicationRevision : undefined;
      const response = await this.request('/concepts', { method: 'POST', token: true, body: { text, ...(selectedProject ? { projectId: selectedProject } : {}), ...(expectedPublicationRevision != null ? { expectedPublicationRevision } : {}), assetIds: this.assets.map(asset => asset.id) } });
      this.proposal = response.proposal || response; if (!this.proposal.id || !Number.isInteger(this.proposal.revision)) throw new Error('服务返回的提案缺少身份或修订号。');
      this.renderProposal(); this.assets = []; this.renderAssets(); $('#proposal-panel').scrollIntoView?.({ behavior: 'smooth', block: 'start' });
    } catch (error) { this.notify(`提案没有提交：${error.message}`); }
    finally { button.disabled = false; }
  }
  renderProposal() {
    const proposal = this.proposal; if (!proposal) return;
    $('#review-label').textContent = this.workspace?.testData ? '我已阅读并确认本次测试方案和制作范围' : '我已阅读并确认上面的方案和制作范围';
    hide($('#proposal-panel'), false); $('#proposal-title').textContent = proposal.title || '初步方案';
    const proposalStatusLabel = proposal.status === 'READY' ? '方案待确认' : proposal.status === 'NEEDS_CLARIFICATION' ? '需要补充信息' : proposal.status === 'FROZEN' ? '已冻结，沿用原制作表单' : `服务状态：${proposal.status || '未知'}`;
    setStatus($('#proposal-status'), proposal.status, proposalStatusLabel);
    const area = $('#proposal-content'); area.replaceChildren();
    area.append(el('p', 'proposal-summary', proposal.text || '服务尚未提供方案摘要。'));
    if (proposal.projectId) area.append(el('p', 'meta-line', `项目：${proposal.projectId} · 方案修订 ${proposal.revision}`));
    if (proposal.initializationRequired) { const hint = el('div', 'notice', '这是一个新项目。确认范围后，服务会按受控初始化流程准备项目；初始化通过后才会制作玩法。'); area.append(hint); }
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
    const requirements = proposal.requirements || []; if (requirements.length) { const heading = el('h3', '', '本轮目标'); const list = el('ul', 'requirement-list'); for (const req of requirements) list.append(el('li', '', typeof req === 'string' ? req : req.text || req.title || JSON.stringify(req))); area.append(heading, list); }
    const questions = proposal.questions || [];
    const ask = $('#answers-form'); const freeze = $('#freeze-area');
    if (proposal.status === 'FROZEN') { hide(ask); hide(freeze, false); $('#review-label').textContent = '此制作表单已冻结，恢复时沿用原表单'; $('#reviewed').checked = false; $('#reviewed').disabled = true; $('#freeze').disabled = true; hide($('#resume-packet'), true); }
    else if (proposal.status === 'NEEDS_CLARIFICATION' || questions.length) { this.renderQuestions(questions); hide(ask, false); hide(freeze); $('#reviewed').disabled = false; }
    else if (proposal.status === 'READY') { hide(ask); this.renderPacketPreview(proposal); hide(freeze, false); $('#reviewed').checked = false; $('#reviewed').disabled = false; $('#freeze').disabled = true; }
    else { hide(ask); hide(freeze); area.append(el('p', 'muted', `当前方案状态为 ${proposal.status || '未知'}，服务未声明可以确认。`)); }
  }
  parameterInput(key) { return $(`#edit-form [name="${key}"]`); }
  renderQuestions(questions) {
    const root = $('#questions'); root.replaceChildren();
    const decisions = this.proposal.decisions || {};
    for (const q of questions) {
      const fieldset = el('fieldset', 'question'); const legend = el('legend', '', q.prompt || q.id); fieldset.append(legend);
      const choices = Array.isArray(q.options) ? q.options : [];
      if (choices.length) { const select = el('select'); select.name = q.id; select.required = q.required !== false; select.append(el('option', '', '请选择')); select.options[0].value = ''; for (const option of choices) { const value = typeof option === 'object' ? option.value : option; const label = typeof option === 'object' ? option.label || option.value : option; const opt = el('option', '', label); opt.value = value; select.append(opt); } if (decisions[q.id] != null) select.value = decisions[q.id]; fieldset.append(select); }
      const free = el('input'); free.type = 'text'; free.name = `${q.id}__text`; free.placeholder = '也可以用自己的话回答'; free.maxLength = 1000; fieldset.append(free); root.append(fieldset);
    }
    if (!questions.length) { root.append(el('p', 'muted', '服务报告需要补充信息，但尚未给出具体问题。')); const free = el('textarea'); free.name = 'clarification'; free.placeholder = '请补充说明'; free.required = true; root.append(free); }
  }
  renderPacketPreview(proposal) {
    let existing = $('#packet-preview'); if (!existing) { existing = el('section', 'packet-preview'); existing.id = 'packet-preview'; $('#freeze-area').prepend(existing); }
    existing.replaceChildren(el('h3', '', '本轮制作表单'));
    const rows = [
      ['方案与修订', `${proposal.id} · r${proposal.revision}`], ['工程', proposal.projectId || '由服务分配'],
      ['Git 基线', proposal.baseCommit || '等待服务绑定'], ['发布版本', proposal.publicationRevision ?? '等待服务绑定'],
      ['初始化范围', proposal.initializationRequired ? '最小工程准备；验收通过后再规划与制作' : '现有工程内增量修改'],
      ['本轮角色', (proposal.roles || proposal.roleScope || []).map?.(item => typeof item === 'string' ? item : item.name || item.id).join('、') || proposal.role || '由服务按项目规则分配'],
      ['精确范围', typeof proposal.scope === 'string' ? proposal.scope : JSON.stringify(proposal.scope || proposal.targets || proposal.requirements || [])],
      ['验收条件', JSON.stringify(proposal.acceptance || proposal.acceptanceCriteria || proposal.tests || proposal.requirements || [])],
      ['决定记录', JSON.stringify(proposal.decisions || {})],
    ];
    const list = el('dl', 'packet-list'); for (const [name, value] of rows) list.append(el('dt', '', name), el('dd', '', String(value))); existing.append(list);
    const scope = proposal.packetSummary || proposal.scope; if (scope) existing.append(el('p', 'muted', typeof scope === 'string' ? scope : JSON.stringify(scope)));
  }
  async answerQuestions() {
    const form = $('#answers-form'); const answers = {};
    for (const [name, value] of new FormData(form)) if (String(value).trim()) answers[name.endsWith('__text') ? name.slice(0, -6) : name] = String(value).trim();
    try {
      const response = await this.request(`/proposals/${encodeURIComponent(this.proposal.id)}/answers`, { method: 'POST', token: true, body: { expectedRevision: this.proposal.revision, answers } });
      this.proposal = response.proposal || response; this.renderProposal();
    } catch (error) { this.notify(`回答没有保存：${error.message}${error.status === 409 ? ' 方案已更新，请刷新后重新核对。' : ''}`); }
  }
  async freezeProposal() {
    if (!this.readiness?.ready || !$('#reviewed').checked || !this.proposal) return;
    const button = $('#freeze'); button.disabled = true; button.textContent = '正在冻结方案…';
    try {
      if (this.packet) { await this.createJob(); return; }
      const reviewedProposal = structuredClone(this.proposal);
      const response = await this.request(`/proposals/${encodeURIComponent(this.proposal.id)}/freeze`, { method: 'POST', token: true, body: { expectedRevision: this.proposal.revision, expectedPublicationRevision: this.proposal.publicationRevision, reviewedProposal } });
      const frozenPacket = response.packet || response;
      if (!frozenPacket.id && !frozenPacket.packetId) throw new Error('服务没有返回冻结表单编号；请先按方案编号对账，页面不会创建新作业。');
      this.packet = frozenPacket;
      this.renderFrozenPacket();
      const expectedKind = this.proposal.initializationRequired ? 'INITIALIZATION' : 'IMPLEMENTATION';
      if (this.packet.operationKind !== expectedKind) {
        this.showWorkflowBlock(`本轮需要 ${expectedKind} 阶段的冻结表单；服务没有返回匹配的表单类型，制作未派发。`);
        return;
      }
      await this.createJob();
    } catch (error) { this.notify(`方案未能冻结或派发：${error.message}${error.status === 409 ? ' 版本发生变化，请刷新并重新审阅。' : ''}`); button.textContent = '重新尝试确认'; button.disabled = !$('#reviewed').checked || !this.readiness?.ready; }
  }
  async resumeFrozenPacket() {
    if (!this.packet || this.proposal?.status !== 'FROZEN') return;
    const button = $('#resume-packet'); button.disabled = true; button.textContent = '正在恢复原制作表单…';
    try { await this.createJob(); hide(button); }
    catch (error) { this.notify(`无法恢复此制作表单：${error.message}。页面仍保留原表单编号。`); button.disabled = false; button.textContent = '恢复并继续此制作表单'; }
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
  async createJob() {
    const packetId = this.packet.packetId || this.packet.id;
    // A frozen packet identifies one dispatch intent. Retrying after an uncertain
    // network outcome must address the same intent, never create a replacement job.
    const idempotencyKey = `packet:${packetId}`;
    const response = await this.request('/jobs', { method: 'POST', token: true, body: { packetId, idempotencyKey } });
    this.job = response.job || response; if (!this.job.id) throw new Error('服务没有返回作业编号。');
    this.renderJob(); this.beginPolling(); if (this.job.projectId) await this.loadWorkbench(this.job.projectId);
  }
  async loadJob(id, poll = true) {
    try { const response = await this.request(`/jobs/${encodeURIComponent(id)}`); this.job = response.job || response; this.renderJob(); if (poll && !TERMINAL.has(this.job.status)) this.beginPolling(); }
    catch (error) { this.notify(`无法读取作业状态：${error.message}`); }
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
    root.append(card);
  }
  renderCandidate(candidate) {
    const area = $('#candidate-area'); area.replaceChildren(el('h3', '', '制作候选结果'));
    const rows = [['Git 版本', candidate.candidateCommit || candidate.commit || '未提供'], ['映射状态', candidate.catalogStatus || candidate.mappingStatus || '未声明'], ['可编辑能力', (candidate.capabilities || []).map(c => c.label || c.id || c).join('、') || '服务未提供'], ['变更摘要', candidate.summary || candidate.message || '查看下方候选详情']];
    const list = el('dl', 'packet-list'); for (const [label, value] of rows) list.append(el('dt', '', label), el('dd', '', String(value))); area.append(list);
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
    const testing = !!this.workspace?.testData;
    const label = testing ? (decision === 'accept' ? '接受测试候选' : '拒绝测试候选') : (decision === 'accept' ? '接受并发布' : '拒绝');
    if (typeof globalThis.confirm === 'function' && !globalThis.confirm(`确认${label}候选版本 ${candidateCommit}？`)) return;
    try {
      const response = await this.request(`/jobs/${encodeURIComponent(this.job.id)}/decision`, { method: 'POST', token: true, body: { decision, candidateCommit, expectedPublicationRevision: this.snapshot.publicationRevision } });
      this.job = response.job || this.job;
      if (response.snapshot) this.snapshot = response.snapshot;
      this.renderJob();
      if (decision === 'accept' && this.job.projectId) await this.loadWorkbench(this.job.projectId);
      this.notify(testing ? `服务已记录${label}；此结果属于测试工作区。` : (decision === 'accept' ? '服务已记录接受决定；请核对返回的发布版本。' : '服务已记录拒绝决定；当前已发布版本保持不变。'));
    } catch (error) { this.notify(`决定未被确认：${error.message}${error.status === 409 ? ' 版本已变化，请刷新并重新审阅。' : ''}`); }
  }
  reviewSnapshotMatchesJob() { return !!this.job?.projectId && this.snapshotMatchesProject(this.job.projectId); }
  beginPolling() { this.stopPolling(); if (!this.job?.id) return; this.pollHandle = this.timers.setInterval(() => this.loadJob(this.job.id, false), 2500); }
  stopPolling() { if (this.pollHandle != null) this.timers.clearInterval(this.pollHandle); this.pollHandle = null; }
  async cancelJob() {
    if (!this.job?.id) return; $('#cancel').disabled = true;
    try { const response = await this.request(`/jobs/${encodeURIComponent(this.job.id)}/cancel`, { method: 'POST', token: true, body: {} }); this.job = response.job || response; this.renderJob(); }
    catch (error) { this.notify(`取消请求没有确认：${error.message}`); }
    finally { $('#cancel').disabled = false; }
  }
  async reconcileJob() {
    if (!this.job?.id) return;
    $('#reconcile').disabled = true;
    try { const response = await this.request(`/jobs/${encodeURIComponent(this.job.id)}/reconcile`, { method: 'POST', token: true, body: {} }); this.job = response.job || response; this.renderJob(); }
    catch (error) { this.notify(`对账结果未确认：${error.message}。系统不会自动重新派发。`); }
    finally { $('#reconcile').disabled = false; }
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
    this.snapshot = loadedSnapshot; this.capabilities = response.capabilities || this.snapshot.capabilities || null; this.candidates = response.candidates || [];
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
  readVisibleDraft() { const values = {}; for (const key of TEMPLATE_FIELDS) { const input = this.parameterInput(key); if (input?.value) values[key] = Number(input.value); } return { text: $('#edit-text')?.value || '', values, draftRevision: this.draftRevision }; }
  applyVisibleDraft(draft) { $('#edit-text').value = draft.text || ''; for (const key of TEMPLATE_FIELDS) { const input = this.parameterInput(key); if (draft.values?.[key] != null && input && !input.disabled) input.value = draft.values[key]; } }
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
    if (snap.kind === 'INITIALIZATION' || snap.playable === false) summary.append(el('div', 'notice', '当前版本是已验证的工程准备基线，尚不包含可玩的 MVP。玩法实现需要独立规划和确认。'));
    else if (snap.kind === 'MVP' && snap.playable === true) summary.append(el('div', 'success-notice', '可运行的 MVP 已通过服务声明的验证。'));
    if (snap.baseCommit || snap.sourceCommit) summary.append(el('p', 'meta-line', `Git 版本：${snap.baseCommit || snap.sourceCommit}`));
    const objects = snap.catalog?.objects || snap.objects || []; if (objects.length) { summary.append(el('h3', '', '可编辑内容')); const list = el('div', 'object-list'); for (const object of objects.slice(0, 12)) { const row = el('div', 'object-row'); row.append(el('b', '', object.name || object.label || object.id)); row.append(el('span', 'muted', object.editable === false ? '只读' : '可编辑')); list.append(row); } summary.append(list); }
    const capabilities = this.capabilities?.fields || this.capabilities?.parameters || this.capabilities || {};
    const pendingInitialization = snap.kind === 'INITIALIZATION' || snap.playable === false;
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
  makeDraftKey(snap) { return `${this.workspace?.workspaceId || 'workspace'}:${snap.projectId || snap.id}:${snap.publicationRevision ?? 'unknown'}`; }
  async restoreDraft(expectedGeneration = this.workbenchGeneration) {
    if (!this.persistenceOK || !this.snapshot) return;
    const targetSnapshot = this.snapshot;
    const key = this.makeDraftKey(targetSnapshot);
    try {
      const draft = await this.drafts.get(key);
      if (expectedGeneration !== this.workbenchGeneration || this.snapshot !== targetSnapshot || (this.snapshot.projectId || this.snapshot.id) !== (targetSnapshot.projectId || targetSnapshot.id)) return;
      this.draftKey = key;
      if (draft) { $('#edit-text').value = draft.text || ''; for (const field of TEMPLATE_FIELDS) { const input = this.parameterInput(field); if (draft.values?.[field] != null && input && !input.disabled) input.value = draft.values[field]; } this.draftRevision = draft.draftRevision || 0; }
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
      const values = {}; for (const key of TEMPLATE_FIELDS) { const input = this.parameterInput(key); if (input?.value) values[key] = Number(input.value); }
      const record = { key, projectId: targetSnapshot.projectId || targetSnapshot.id, publicationRevision: targetSnapshot.publicationRevision, draftRevision: ++this.draftRevision, text: $('#edit-text').value, values, updatedAt: new Date().toISOString() };
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
    if (fieldPreview.childNodes.length) preview.append(fieldPreview);
    if (!pending.draft.text && !fieldPreview.childNodes.length) preview.append(el('p', 'muted', '当前没有待重关联的修改内容。'));
    preview.append(el('p', 'muted', '此操作只复制草稿并标记待核对，不会发布或覆盖项目。')); content.append(preview);
  }
  rebaseContextMatches(pending) { return this.pendingRebase === pending && pending.generation === this.workbenchGeneration && this.snapshot === pending.nextSnapshot && this.makeDraftKey(this.snapshot) === pending.newKey && ($('#project')?.value || '') === (pending.nextSnapshot.projectId || pending.nextSnapshot.id); }
  sameReviewedDraft(preview, stored) {
    const canonical = values => JSON.stringify(Object.fromEntries(Object.entries(values || {}).sort(([a], [b]) => a.localeCompare(b))));
    return !!stored && preview.text === stored.text && (preview.draftRevision || 0) === (stored.draftRevision || 0) && canonical(preview.values) === canonical(stored.values);
  }
  async confirmRebase() {
    const pending = this.pendingRebase; if (!pending) return;
    try {
      if (!this.rebaseContextMatches(pending)) return;
      if (pending.persistenceOK) {
        const stored = await this.drafts.get(pending.oldKey);
        if (!this.rebaseContextMatches(pending)) return;
        if (!stored) { this.notify('未找到旧草稿；没有修改当前版本。'); return; }
        if (!this.sameReviewedDraft(pending.draft, stored)) { pending.draft = { ...stored, values: { ...(stored.values || {}) } }; this.unrebasedDraft = { ...this.unrebasedDraft, draft: pending.draft }; this.renderRebasePreview(pending); this.notify('旧草稿在预览后发生变化；已更新预览，请重新确认。'); return; }
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
    const text = $('#edit-text').value.trim(); const values = {};
    for (const key of TEMPLATE_FIELDS) { const input = this.parameterInput(key); if (!input || input.disabled || !input.value) continue; const value = Number(input.value); if (value < Number(input.min) || value > Number(input.max)) return this.notify(`${LABELS[key]}超出允许范围。`); values[key] = value; }
    if (!text && !Object.keys(values).length) return this.notify('写下调整内容，或修改一个受支持的选项。');
    const details = Object.entries(values).map(([key, value]) => `${LABELS[key]}调整为 ${value}`).join('；');
    await this.submitConcept([text, details].filter(Boolean).join('\n'));
  }
  notify(message) { const box = $('#notice'); if (!box) return; box.textContent = message; hide(box, false); box.scrollIntoView?.({ behavior: 'smooth', block: 'nearest' }); }
  destroy() { this.destroyed = true; this.stopPolling(); if (this.draftTimer != null) this.timers.clearTimeout(this.draftTimer); }
}

if (typeof document !== 'undefined' && document.getElementById('app')) {
  const studio = new StudioApp(); studio.start();
  globalThis.ptahStudio = studio;
  globalThis.addEventListener?.('pagehide', () => studio.destroy(), { once: true });
}
