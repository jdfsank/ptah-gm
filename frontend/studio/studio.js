import { installVisualPlanning } from './visual-planning.js';
import { installImagePlanning } from './image-planning.js';
import { LegacyWorkbench } from './workbench.js';
import { mountVisual, referenceModel, releaseVisuals } from './visual-feedback.js';

const API = '/api';
const DRAFT_DB = 'ptah-studio-drafts-v1';
const DRAFT_STORAGE_PREFIX = 'ptah-studio-draft-v2:';
const TEMPLATE_FIELDS = ['goalCount', 'durationSeconds', 'playerSpeed'];
const LABELS = { goalCount: '收集目标', durationSeconds: '时限（秒）', playerSpeed: '移动速度' };
const PLANNING = new Set(['PLANNING', 'PLANNING_CANCELLING', 'PLANNING_UNCERTAIN']);
const JOB_LABELS = { QUEUED: '排队中', DISPATCHING: '准备制作', RUNNING: '制作中', VERIFYING: '运行验证', PROJECTING: '整理结果', READY_FOR_REVIEW: '等待你审阅', PUBLISHED: '已发布', REJECTED: '已拒绝', FAILED: '制作失败', BLOCKED: '暂时受阻', UNCERTAIN: '状态待核实', CANCEL_REQUESTED: '正在请求取消', CANCELLING: '正在停止', CANCELLED: '已取消', PLANNING: '策划中', PLANNING_CANCELLING: '正在停止策划', PLANNING_UNCERTAIN: '策划状态待核实' };
const STOP_LABELS = { time_limit: '达到时间上限', soft_budget: '达到用量上限', cancelled: '已请求取消', requested: '已请求停止', native_error: '执行服务错误', unknown: '原因待核实' };
const jobLabel = job => {
  if (job?.status === 'UNCERTAIN') return JOB_LABELS.UNCERTAIN;
  if (job?.verificationFailure) return '验证未通过';
  if (['FAILED', 'CANCELLED'].includes(job?.status)) {
    const reason = job.productionFailure?.stopReason;
    if (reason === 'time_limit') return '制作超时';
    if (reason === 'soft_budget') return '制作达到用量上限';
  }
  return JOB_LABELS[job?.status] || job?.status || '未知';
};
const TERMINAL = new Set(['PUBLISHED', 'REJECTED', 'FAILED', 'BLOCKED', 'CANCELLED']);
const ACTIVE = new Set(['QUEUED', 'DISPATCHING', 'RUNNING', 'VERIFYING', 'PROJECTING', 'READY_FOR_REVIEW', 'CANCEL_REQUESTED', 'CANCELLING', 'UNCERTAIN']);
const REQUIRED_CAPABILITIES = {
  interactiveFrontendConfirmation: '前端确认记录', sessionDispatch: '制作 session 调度',
  godotVerification: 'Godot 运行验证', semanticProjection: '结果语义回流',
};
const $ = (selector, root = document) => root.querySelector(selector);
const el = (tag, className, text) => { const node = document.createElement(tag); if (className) node.className = className; if (text != null) node.textContent = String(text); return node; };
const hide = (node, value = true) => { if (node) node.classList.toggle('hidden', value); };
const cloneValue = value => value == null ? value : structuredClone(value);
const numberInputStep = (declaredStep, integerDefault) => declaredStep == null ? (integerDefault ? '1' : 'any') : String(declaredStep);
const canonicalValue = value => {
  if (Array.isArray(value)) return `[${value.map(canonicalValue).join(',')}]`;
  if (value && typeof value === 'object') return `{${Object.keys(value).sort().map(key => `${JSON.stringify(key)}:${canonicalValue(value[key])}`).join(',')}}`;
  return JSON.stringify(value);
};
const sameValue = (left, right) => canonicalValue(left) === canonicalValue(right);
const setStatus = (node, status, label = null) => { if (!node) return; node.textContent = label || JOB_LABELS[status] || status || '未知'; node.className = `status-pill ${String(status || '').toLowerCase().replaceAll('_', '-')}`; };
const hasDuplicateJsonKeys = source => {
  let i = 0;
  const ws = () => { while (/\s/.test(source[i] || '') && i < source.length) i++; };
  const stringToken = () => { const start = i++; let escaped = false; while (i < source.length) { const char = source[i++]; if (escaped) escaped = false; else if (char === '\\') escaped = true; else if (char === '"') return JSON.parse(source.slice(start, i)); } throw new Error('unterminated string'); };
  const value = () => {
    ws(); const char = source[i];
    if (char === '{') { i++; ws(); const keys = new Set(); if (source[i] === '}') { i++; return; } while (i < source.length) { ws(); if (source[i] !== '"') throw new Error('object key expected'); const key = stringToken(); if (keys.has(key)) throw new Error('duplicate JSON key'); keys.add(key); ws(); if (source[i++] !== ':') throw new Error('colon expected'); value(); ws(); const next = source[i++]; if (next === '}') return; if (next !== ',') throw new Error('comma expected'); } throw new Error('unterminated object'); }
    if (char === '[') { i++; ws(); if (source[i] === ']') { i++; return; } while (i < source.length) { value(); ws(); const next = source[i++]; if (next === ']') return; if (next !== ',') throw new Error('comma expected'); } throw new Error('unterminated array'); }
    if (char === '"') { stringToken(); return; }
    const match = /^(?:true|false|null|-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?)/.exec(source.slice(i)); if (!match) throw new Error('value expected'); i += match[0].length;
  };
  try { value(); ws(); return i !== source.length; } catch (error) { return error.message === 'duplicate JSON key'; }
};
const safeJson = async response => {
  const body = await response.text(); let data;
  if (body && hasDuplicateJsonKeys(body)) { if (response.ok) throw new Error('服务响应含重复 JSON 键；响应未作为成功结果使用。'); }
  try { data = body ? JSON.parse(body) : null; }
  catch { if (response.ok) throw new Error('服务返回了无效 JSON；响应未作为成功结果使用。'); data = null; }
  if (!response.ok) {
    const message = [data?.message, data?.error?.message, data?.error].find(value => typeof value === 'string' && value.trim());
    const error = new Error(message?.slice(0, 2000) || `服务返回 ${response.status}；未提供可读的错误说明。`);
    error.status = response.status; error.body = data; throw error;
  }
  if (!data || typeof data !== 'object' || Array.isArray(data)) throw new Error('服务成功响应必须是 JSON 对象。');
  const finite = value => typeof value === 'number' ? Number.isFinite(value) : Array.isArray(value) ? value.every(finite) : value && typeof value === 'object' ? Object.values(value).every(finite) : true;
  if (!finite(data)) throw new Error('服务响应包含非有限数字；响应未作为成功结果使用。');
  return data;
};

export class DraftStore {
  constructor(indexedDBImpl = globalThis.indexedDB, storageImpl) {
    this.impl = indexedDBImpl; this.db = null; this.error = null; this.corruptRecords = new Map();
    try { this.storage = storageImpl === undefined ? globalThis.localStorage : storageImpl; } catch { this.storage = null; }
  }
  async open() {
    if (!this.storage) throw new Error('此浏览器没有可用的本地草稿存储。');
    const probe = `${DRAFT_STORAGE_PREFIX}probe:${globalThis.crypto?.randomUUID?.() || Math.random()}`;
    this.storage.setItem(probe, '1'); this.storage.removeItem(probe);
    return this.storage;
  }
  async openLegacy() {
    if (!this.impl) return null;
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
  readStored(key, raw) {
    try {
      const value = JSON.parse(raw);
      if (value !== null && (!value || typeof value !== 'object' || Array.isArray(value) || value.key !== key)) throw new Error('草稿存储身份不匹配。');
      if (value && Object.hasOwn(value, 'schemaVersion') && value.schemaVersion !== 'ptah.workbench-draft.v1') throw new Error('草稿存档格式版本不兼容。');
      for (const field of ['fields', 'targetNotes']) {
        if (value && Object.hasOwn(value, field) && (!value[field] || typeof value[field] !== 'object' || Array.isArray(value[field]))) {
          throw new Error(`草稿存档字段 ${field} 的形状不兼容。`);
        }
      }
      this.corruptRecords.delete(key);
      return value;
    } catch (error) {
      this.rememberCorrupt(key, error, { rawFallback: raw });
      throw error;
    }
  }
  raw(key) { return this.storage?.getItem(DRAFT_STORAGE_PREFIX + key) ?? null; }
  rememberCorrupt(key, error, { rawFallback = null, ...metadata } = {}) {
    let storedRaw = null;
    try { storedRaw = this.raw(key); } catch {}
    const previous = this.corruptRecords.get(key) || {};
    const record = { ...previous, ...metadata, key,
      raw: storedRaw !== null ? storedRaw : previous.raw ?? rawFallback,
      error: String(error?.message || error || '草稿存档无法读取。') };
    this.corruptRecords.set(key, record);
    return record;
  }
  putIfUnchanged(value, expectedRaw) {
    const currentRaw = this.raw(value.key);
    if (currentRaw !== expectedRaw) {
      const error = new Error('存储中的活动草稿已变化；当前输入仍在本页，没有覆盖存储内容。');
      error.name = 'DraftConflictError'; error.latestRaw = currentRaw;
      error.latest = currentRaw === null || currentRaw === 'null' ? null : this.readStored(value.key, currentRaw);
      throw error;
    }
    const serialized = JSON.stringify(value);
    this.storage.setItem(DRAFT_STORAGE_PREFIX + value.key, serialized);
    return value;
  }
  async get(key) {
    const storageKey = DRAFT_STORAGE_PREFIX + key;
    const raw = this.storage.getItem(storageKey);
    if (raw !== null) return this.readStored(key, raw);
    const db = await this.openLegacy();
    if (!db) return null;
    const legacy = await new Promise((resolve, reject) => { const req = db.transaction('drafts').objectStore('drafts').get(key); req.onsuccess = () => resolve(req.result || null); req.onerror = () => reject(req.error); });
    // A slow legacy read cannot replace a newer edit or deletion from this tab or another tab.
    const latest = this.storage.getItem(storageKey);
    if (latest !== null) return this.readStored(key, latest);
    if (legacy) { this.readStored(key, JSON.stringify(legacy)); this.storage.setItem(storageKey, JSON.stringify(legacy)); }
    return legacy;
  }
  async findOlderIterationDraft({ storeId, projectId, publicationRevision, currentKey }) {
    const revision = Number(publicationRevision);
    if (!this.storage || !storeId || !projectId || !Number.isSafeInteger(revision) || revision < 1 ||
        !currentKey || currentKey !== `${storeId}:${projectId}:iteration:${revision}`) return [];
    const currentStorageKey = DRAFT_STORAGE_PREFIX + currentKey;
    // A tombstone on the current key records an intentional submission/deletion.
    // It must not be replaced by content from an older publication.
    if (this.storage.getItem(currentStorageKey) === 'null') return [];
    const prefix = `${storeId}:${projectId}:iteration:`;
    const candidates = new Map();
    const parseRevision = key => {
      if (!key.startsWith(prefix)) return null;
      const suffix = key.slice(prefix.length);
      if (!/^\d+$/.test(suffix)) return null; // excludes repair and malformed historical keys
      const value = Number(suffix);
      return Number.isSafeInteger(value) && value < revision ? value : null;
    };
    const remember = (key, value) => {
      const oldRevision = parseRevision(key);
      if (oldRevision == null || this.storage.getItem(DRAFT_STORAGE_PREFIX + key) === 'null') return;
      if (!value || typeof value !== 'object' || Array.isArray(value)) return;
      if (value.key !== undefined && value.key !== key) return;
      if (value.projectId !== undefined && value.projectId !== projectId) return;
      if (value.publicationRevision !== undefined && Number(value.publicationRevision) !== oldRevision) return;
      candidates.set(key, { ...value, key, projectId, publicationRevision: oldRevision });
    };
    for (let index = 0; index < this.storage.length; index++) {
      const storageKey = this.storage.key(index);
      if (!storageKey?.startsWith(DRAFT_STORAGE_PREFIX)) continue;
      const key = storageKey.slice(DRAFT_STORAGE_PREFIX.length);
      const oldRevision = parseRevision(key);
      if (oldRevision == null) continue;
      const raw = this.storage.getItem(storageKey);
      if (raw === null || raw === 'null') continue;
      try { remember(key, this.readStored(key, raw)); }
      catch (error) { this.rememberCorrupt(key, error, { kind: 'older', projectId, publicationRevision: oldRevision, baseDraftKey: currentKey, rawFallback: raw }); }
    }
    const db = await this.openLegacy();
    if (db) {
      const records = await new Promise((resolve, reject) => {
        const transaction = db.transaction('drafts');
        const store = transaction.objectStore('drafts');
        if (typeof store.getAll === 'function') {
          const request = store.getAll();
          request.onsuccess = () => resolve(request.result || []);
          request.onerror = () => reject(request.error || new Error('无法枚举旧版草稿。'));
          return;
        }
        if (typeof store.openCursor !== 'function') { resolve([]); return; }
        const values = [];
        const request = store.openCursor();
        request.onsuccess = () => {
          const cursor = request.result;
          if (!cursor) { resolve(values); return; }
          values.push(cursor.value); cursor.continue();
        };
        request.onerror = () => reject(request.error || new Error('无法枚举旧版草稿。'));
      });
      for (const record of records) {
        const oldRevision = record?.key ? parseRevision(record.key) : null;
        if (oldRevision == null || candidates.has(record.key) || this.corruptRecords.has(record.key)) continue;
        try { remember(record.key, this.readStored(record.key, JSON.stringify(record))); }
        catch (error) { this.rememberCorrupt(record.key, error, { kind: 'older', projectId, publicationRevision: oldRevision, baseDraftKey: currentKey, rawFallback: JSON.stringify(record) }); }
      }
    }
    const ranked = [...candidates.entries()].sort((left, right) => {
      const revisionOrder = Number(right[1].publicationRevision) - Number(left[1].publicationRevision);
      return revisionOrder || String(right[1].updatedAt || '').localeCompare(String(left[1].updatedAt || ''));
    });
    return ranked.map(([key, draft]) => ({ key, draft }));
  }
  async put(value) {
    // Persist inside the input handler, before its first await or any pagehide event.
    this.storage.setItem(DRAFT_STORAGE_PREFIX + value.key, JSON.stringify(value));
    return value;
  }
  async putIfAbsent(value) {
    const storageKey = DRAFT_STORAGE_PREFIX + value.key;
    if (this.storage.getItem(storageKey) !== null) throw new Error('新版本已有草稿或提交记录，未覆盖。');
    this.storage.setItem(storageKey, JSON.stringify(value));
    return value;
  }
  isTombstoned(key) { return this.storage?.getItem(DRAFT_STORAGE_PREFIX + key) === 'null'; }
  async delete(key) {
    // A tombstone prevents a slow IndexedDB migration from resurrecting a submitted draft.
    this.storage.setItem(DRAFT_STORAGE_PREFIX + key, 'null');
    const db = await this.openLegacy();
    if (!db) return;
    return new Promise((resolve, reject) => {
      const tx = db.transaction('drafts', 'readwrite'); tx.objectStore('drafts').delete(key);
      tx.oncomplete = () => resolve(); tx.onabort = tx.onerror = () => reject(tx.error || new Error('草稿删除失败。'));
    });
  }
}

export class StudioApp {
  constructor({ fetchImpl = globalThis.fetch?.bind(globalThis), documentImpl = globalThis.document, timers = globalThis } = {}) {
    this.fetch = fetchImpl; this.document = documentImpl; this.timers = timers; this.token = null; this.session = null; this.workspace = null; this.manager = null; this.projectId = null; this.stage = 'initial';
    this.proposal = null; this.packet = null; this.job = null; this.snapshot = null; this.capabilities = null; this.candidates = []; this.previews = [];
    this.candidateDetailsExpanded = {};
    this.referenceIntents = {}; this.conceptGenerationRequests = []; this.referenceBatches = [];
    this.assets = []; this.pollHandle = null; this.drafts = new DraftStore(); this.draftRevision = 0; this.draftKey = null; this.persistenceOK = false;
    this.draftRestoreContext = null; this.draftSaveQueuedDuringRestore = false; this.draftConflictRefresh = null;
    this.draftBaselineKey = null; this.draftStorageBaseline = undefined; this.draftAlternates = []; this.pendingDraftConflict = null; this.draftOperationSequence = 0;
    this.draftStorageTarget = this.document?.defaultView || globalThis;
    this.boundDraftStorageChange = event => { void this.handleDraftStorageEvent(event); };
    this.serializingVisibleDraft = false;
    this.draftTimer = null; this.conceptDraftTimer = null; this.destroyed = false; this.bound = false; this.selectionBusy = false; this.workbenchLoad = null; this.workbenchGeneration = 0;
    this.proposalPollHandle = null; this.proposalGeneration = 0; this.workflow = null; this.selectedObjectId = null; this.feedback = []; this.feedbackInputs = {}; this.feedbackInputTargetId = null; this.legacyUnboundFeedback = null; this.proposalInputs = {}; this.dirtyFields = new Set(); this.fieldDraftValues = {};
    this.targetNotes = {}; this.structuralProposals = []; this.workbenchResults = []; this.legacyWorkbench = new LegacyWorkbench(this);
    this.reviewedPlan = null; this.reviewPlanLoad = null; this.reviewedPlanExpandedRef = null; this.frozenPlanExpanded = null;
    this.selectionGeneration = 0; this.conceptGeneration = 0; this.conceptSubmissionInFlight = null; this.proposalMutationGeneration = 0; this.jobLoadGeneration = 0; this.jobMutationGeneration = 0; this.retryOutcomeUnknown = null; this.activity = null;
    this.protocolVersion = 0; this.handshake = null; this.jobReadInFlight = null; this.proposalReadInFlight = null; this.lastFeedbackReceipt = null; this.sessionPreferences = null; this.sessionCatalog = null; this.refreshInFlight = null; this.streamController = null; this.streamAttemptTimeout = null; this.streamAttemptDone = null; this.streamProjectId = null; this.streamConnect = null; this.streamPaused = false; this.streamRetry = null; this.streamGeneration = 0; this.eventSequence = 0; this.streamFresh = false;
  }
  async request(path, { method = 'GET', body, token = false, projectId = this.projectId, retriedAuth = false } = {}) {
    const activeProject = projectId;
    if (activeProject && /^\/(?:concepts|concept-references|concept-reference-batches|visual-plans|candidates|assets|proposals|jobs|packets)(?:\/|$)/.test(path)) path = `/projects/${encodeURIComponent(activeProject)}${path}`;
    const headers = { Accept: 'application/json' };
    if (body !== undefined) headers['Content-Type'] = 'application/json';
    if (token) { if (!this.token) throw new Error('本机服务会话尚未建立。'); headers['X-Workbench-Token'] = this.token; }
    let timeoutHandle; let timedOut = false; const controller = new AbortController();
    const timeoutError = new Error('读取服务超时；状态保持待核实，请再次刷新。');
    const timeout = new Promise((_, reject) => { timeoutHandle = this.timers.setTimeout(() => { timedOut = true; controller.abort(); reject(timeoutError); }, 20000); });
    try {
      const operation = (async () => {
        const send = async (url, requestMethod, requestHeaders, requestBody) => this.fetch(`${API}${url}`, { method: requestMethod, headers: requestHeaders, signal: controller.signal, ...(requestBody !== undefined ? { body: JSON.stringify(requestBody) } : {}) });
        let response = await send(path, method, headers, body);
        if (timedOut) throw timeoutError;
        if ((response.status === 401 || response.status === 403) && token && this.protocolVersion && !retriedAuth) {
          const handshakeResponse = await send('/v1/handshake', 'GET', { Accept: 'application/json' });
          if (timedOut) throw timeoutError;
          const fresh = await safeJson(handshakeResponse);
          if (timedOut) throw timeoutError;
          if (fresh.schemaVersion !== 'studio.message.v1' || fresh.kind !== 'handshake' || fresh.storeId !== this.handshake?.storeId || !fresh.serviceInstanceId || !fresh.writeToken) throw new Error('服务重启或存储代次变化；命令状态待核实，请重新连接后核账。');
          this.handshake = fresh; this.token = fresh.writeToken;
          if (method === 'GET') {
            headers['X-Workbench-Token'] = this.token;
            response = await send(path, method, headers, body);
            if (timedOut) throw timeoutError;
          }
        }
        const result = await safeJson(response);
        if (timedOut) throw timeoutError;
        return result;
      })();
      return await Promise.race([operation.catch(error => { if (timedOut) throw timeoutError; throw error; }), timeout]);
    } catch (error) {
      if (timedOut) throw timeoutError;
      throw error;
    } finally { if (timeoutHandle != null) this.timers.clearTimeout(timeoutHandle); }
  }
  submissionOutcome(status, { type = null, projectId = null, storeId = this.handshake?.storeId || null, commandId = null, proposalId = null, reason = '', receipt = null, priorStatus = null } = {}) {
    return { status, type, projectId: projectId || null, storeId, commandId: commandId || null, proposalId: proposalId || null, reason: String(reason || ''), ...(priorStatus ? { priorStatus } : {}), ...(receipt ? { receipt } : {}) };
  }
  pendingCommandRecord(type, projectId) {
    const scope = projectId || 'store', key = `${this.handshake?.storeId}:${scope}:${type}`;
    let pending = this.pendingCommands?.get(key) || null;
    if (!pending) { try { pending = JSON.parse(globalThis.localStorage?.getItem(`ptah-pending:${key}`) || 'null'); } catch {} }
    return pending && pending.envelope?.type === type && (pending.envelope?.projectId || null) === (projectId || null) ? pending : null;
  }
  async sendCommand(type, payload, options = {}) {
    const projectId = options.projectId === undefined ? this.projectId : options.projectId;
    try { return await this.sendCommandImpl(type, payload, options); }
    catch (error) {
      if (!error.commandOutcome) {
        const pending = this.pendingCommandRecord(type, projectId);
        const message = String(error?.message || '');
        const status = error.status === 409 ? 'stale'
          : [401, 403].includes(error.status) ? 'blocked'
            : Number.isInteger(error.status) && error.status >= 400 && error.status < 500 ? 'rejected'
              : error.commandDispatched ? 'unknown' : 'blocked';
        const identity = error.commandEnvelope || pending?.envelope;
        error.commandOutcome = this.submissionOutcome(status, { type, projectId, storeId: identity?.storeId || this.handshake?.storeId, commandId: identity?.commandId || pending?.commandId || null, reason: message || (status === 'blocked' ? '命令尚未发送。' : '命令没有返回可核实结果。') });
      }
      throw error;
    }
  }
  async sendCommandImpl(type, payload, { projectId = this.projectId, expected = {} } = {}) {
    if (!this.protocolVersion) throw new Error('当前服务没有协商新版命令协议。');
    if (!this.token || !this.handshake?.storeId || (type !== 'project.create' && !projectId)) throw new Error('命令缺少项目或有效写入会话。');
    const legacyIterationCommand = type === 'iteration.submit' && this.legacyIterationCommandsAvailable();
    if (projectId && !['session.preferences.update', 'project.settings.update'].includes(type) && !this.usesV1Commands(projectId) && !legacyIterationCommand) throw new Error('旧项目保留原有流程协议；此操作未获得兼容命令能力，命令未发送。');
    const actions = this.projectView?.allowedActions;
    if (projectId && !legacyIterationCommand && !type.startsWith('session.preferences.') && !type.startsWith('project.settings.') && Array.isArray(actions) && !actions.includes(type)) throw new Error('当前公开阶段没有允许此操作；请先刷新项目状态。');
    const scope = projectId || 'store', key = `${this.handshake.storeId}:${scope}:${type}`, indexKey = `ptah-pending-index:${scope}:${type}`;
    if (!globalThis.localStorage) throw new Error('本地命令存储不可用；请求未发送。');
    this.pendingCommands ||= new Map();
    let pending = this.pendingCommands.get(key);
    let indexed = null;
    if (!pending) { try { pending = JSON.parse(globalThis.localStorage?.getItem(`ptah-pending:${key}`) || 'null'); indexed = JSON.parse(globalThis.localStorage?.getItem(indexKey) || 'null'); } catch { pending = null; indexed = null; } }
    if (indexed && indexed.storeId !== this.handshake.storeId) throw new Error('待核实命令属于旧数据代次；当前工作区已隔离，需先在旧数据空间核对。');
    if (pending && pending.envelope?.type !== type) throw new Error('待核实命令与当前操作类型冲突；请先完成原命令核账。');
    const savePending = value => {
      this.pendingCommands.set(key, value);
      try { globalThis.localStorage?.setItem(`ptah-pending:${key}`, JSON.stringify(value)); globalThis.localStorage?.setItem(indexKey, JSON.stringify({ storeId: this.handshake.storeId, commandId: value.commandId, envelope: value.envelope })); }
      catch { throw new Error('无法持久保存待确认命令；请求未发送。'); }
    };
    const clearPending = () => { this.pendingCommands.delete(key); try { globalThis.localStorage?.removeItem(`ptah-pending:${key}`); globalThis.localStorage?.removeItem(indexKey); } catch {} };
    const envelope = pending?.envelope || { schemaVersion: 'studio.message.v1', kind: 'command', type, storeId: this.handshake.storeId, ...(projectId ? { projectId } : {}), commandId: this.newFeedbackId().replace('feedback-', 'cmd-'), expected, payload };
    if (pending && type === 'iteration.submit') {
      const error = new Error('已有命令仍待核实；本次没有再次发送。请先使用原命令编号核实结果。');
      error.commandOutcome = this.submissionOutcome('unknown', { type, projectId, commandId: envelope.commandId, reason: error.message });
      throw error;
    }
    const bodyText = JSON.stringify(payload);
    const originalDiffers = !!pending && JSON.stringify(envelope.payload) !== bodyText;
    if (originalDiffers) {
      const lookupPath = projectId ? `/v1/projects/${encodeURIComponent(projectId)}/commands/${encodeURIComponent(envelope.commandId)}` : `/v1/commands/${encodeURIComponent(envelope.commandId)}`;
      let lookup;
      try { lookup = await this.request(lookupPath, { projectId: null }); }
      catch (error) { error.commandOutcome = this.submissionOutcome('unknown', { type, projectId, commandId: envelope.commandId, reason: `上一条命令状态无法核实；本次没有发送：${error.message}` }); throw error; }
      if (lookup.schemaVersion !== 'studio.message.v1' || lookup.kind !== 'command_lookup' || lookup.storeId !== this.handshake.storeId || lookup.commandId !== envelope.commandId || typeof lookup.known !== 'boolean') {
        const error = new Error('上一条命令无法核实；原意图保持待处理，本次没有发送。'); error.commandOutcome = this.submissionOutcome('unknown', { type, projectId, commandId: envelope.commandId, reason: error.message }); throw error;
      }
      if (lookup.known && lookup.receipt) {
        this.validateReceipt(lookup.receipt, envelope); clearPending();
        const previousStatus = lookup.receipt.status === 'accepted' ? 'submitted' : 'rejected';
        const error = new Error(`上一条命令已明确${previousStatus === 'submitted' ? '接收' : '拒绝'}；本次新内容没有发送。`);
        error.commandOutcome = this.submissionOutcome('blocked', { type, projectId, commandId: envelope.commandId, priorStatus: previousStatus, reason: `${error.message}${lookup.receipt.error?.message ? ` 原因：${lookup.receipt.error.message}` : ''}`, receipt: lookup.receipt }); throw error;
      }
      if (!lookup.known) {
        savePending(pending);
        const replay = await this.postCommand(envelope, projectId);
        this.validateReceipt(replay, envelope); clearPending();
        const previousStatus = replay.status === 'accepted' ? 'submitted' : 'rejected';
        const error = new Error(`已用原命令编号核实上一条请求；本次新内容没有发送。`);
        error.commandOutcome = this.submissionOutcome('blocked', { type, projectId, commandId: envelope.commandId, priorStatus: previousStatus, reason: error.message, receipt: replay }); throw error;
      }
      const error = new Error('上一条命令记录不完整；原意图保持待处理，本次没有发送。'); error.commandOutcome = this.submissionOutcome('unknown', { type, projectId, commandId: envelope.commandId, reason: error.message }); throw error;
    }
    const current = pending || { commandId: envelope.commandId, envelope };
    savePending(current);
    let receipt;
    try { receipt = await this.postCommand(envelope, projectId); }
    catch (error) {
      const status = error.status === 409 ? 'stale'
        : [401, 403].includes(error.status) ? 'blocked'
          : Number.isInteger(error.status) && error.status >= 400 && error.status < 500 ? 'rejected'
            : 'unknown';
      error.commandOutcome = this.submissionOutcome(status, { type, projectId, commandId: envelope.commandId, reason: error.message || '命令发送后没有返回可核实结果。' });
      if (Number.isInteger(error.status) && error.status >= 400 && error.status < 500 && ![401, 403, 409].includes(error.status)) clearPending();
      throw error;
    }
    try { this.validateReceipt(receipt, envelope); }
    catch (error) {
      error.commandOutcome = this.submissionOutcome('unknown', { type, projectId, commandId: envelope.commandId, reason: error.message || '服务回执身份无法核实。' });
      throw error;
    }
    clearPending();
    if (receipt.status === 'rejected') {
      const error = new Error(receipt.error?.message || '服务明确拒绝了该命令；没有产生业务效果。');
      error.commandOutcome = this.submissionOutcome('rejected', { type, projectId, commandId: envelope.commandId, reason: error.message, receipt });
      throw error;
    }
    const result = receipt.result || {};
    try { Object.defineProperty(result, '__commandOutcome', { configurable: true, value: this.submissionOutcome('submitted', { type, projectId, commandId: envelope.commandId, proposalId: receipt.resource?.kind === 'proposal' ? receipt.resource.id : null, reason: '服务已明确接收本次命令。', receipt }) }); } catch {}
    return result;
  }
  async reconcilePendingCommand(type, projectId = this.projectId) {
    const pending = this.pendingCommandRecord(type, projectId);
    if (!pending?.envelope?.commandId) return this.submissionOutcome('blocked', { type, projectId, reason: '没有可核实的本地待处理命令。' });
    const envelope = pending.envelope;
    const base = { type, projectId, commandId: envelope.commandId, storeId: envelope.storeId };
    const pendingKey = `ptah-pending:${envelope.storeId}:${projectId || 'store'}:${type}`;
    const clearMatchingPending = () => {
      let latest = this.pendingCommands?.get(`${envelope.storeId}:${projectId || 'store'}:${type}`) || pending;
      try {
        const stored = JSON.parse(globalThis.localStorage?.getItem(pendingKey) || 'null');
        if (stored) latest = stored;
      } catch {}
      if (latest?.envelope?.commandId !== envelope.commandId) return false;
      this.pendingCommands?.delete(`${envelope.storeId}:${projectId || 'store'}:${type}`);
      try {
        const stored = JSON.parse(globalThis.localStorage?.getItem(pendingKey) || 'null');
        if (stored?.envelope?.commandId === envelope.commandId) globalThis.localStorage.removeItem(pendingKey);
        const indexKey = `ptah-pending-index:${projectId || 'store'}:${type}`;
        const indexed = JSON.parse(globalThis.localStorage?.getItem(indexKey) || 'null');
        if (indexed?.commandId === envelope.commandId) globalThis.localStorage.removeItem(indexKey);
      } catch {}
      return true;
    };
    const lookupPath = projectId ? `/v1/projects/${encodeURIComponent(projectId)}/commands/${encodeURIComponent(envelope.commandId)}` : `/v1/commands/${encodeURIComponent(envelope.commandId)}`;
    try {
      const lookup = await this.request(lookupPath, { projectId: null });
      if (lookup.schemaVersion !== 'studio.message.v1' || lookup.kind !== 'command_lookup' || lookup.storeId !== envelope.storeId || lookup.commandId !== envelope.commandId || typeof lookup.known !== 'boolean') {
        return this.submissionOutcome('unknown', { ...base, reason: '服务没有返回与原命令身份匹配的核实结果；原命令仍保留。' });
      }
      if (!lookup.known) {
        if (lookup.receipt != null) return this.submissionOutcome('unknown', { ...base, reason: '服务称原命令不存在却同时返回回执；原命令仍保留。' });
        const current = this.pendingCommandRecord(type, projectId);
        if (current?.envelope?.commandId !== envelope.commandId || current.envelope.storeId !== envelope.storeId) return this.submissionOutcome('stale', { ...base, reason: '待核实命令已变化；没有重放旧请求。' });
        if (this.handshake?.storeId !== envelope.storeId) return this.submissionOutcome('stale', { ...base, reason: '服务存储代次已变化；没有重放旧请求。' });
        // A negative lookup is not proof that the original POST never arrived.
        // Re-submit only the persisted envelope, with its original command ID and payload.
        let replay;
        try { replay = await this.postCommand(envelope, projectId); }
        catch (error) { return this.submissionOutcome(error.status === 409 ? 'stale' : 'unknown', { ...base, reason: error.message || '原命令重放仍未返回可核实回执；原命令仍保留。' }); }
        try { this.validateReceipt(replay, envelope); }
        catch (error) { return this.submissionOutcome('unknown', { ...base, reason: `原命令回执身份无法核实：${error.message}` }); }
        if (!clearMatchingPending()) return this.submissionOutcome('stale', { ...base, reason: '已取得原命令回执，但本地待核实记录已变化；没有清除新记录。', receipt: replay });
        if (replay.status === 'rejected') return this.submissionOutcome('rejected', { ...base, reason: replay.error?.message || '服务明确拒绝了原命令。', receipt: replay });
        return this.submissionOutcome('submitted', { ...base, proposalId: replay.resource?.kind === 'proposal' ? replay.resource.id : null, reason: '使用原命令编号取得服务回执，确认原命令已接收。', receipt: replay });
      }
      if (!lookup.receipt) return this.submissionOutcome('unknown', { ...base, reason: '服务报告原命令存在，但没有返回回执；原命令仍保留。' });
      try { this.validateReceipt(lookup.receipt, envelope); }
      catch (error) { return this.submissionOutcome('unknown', { ...base, reason: `原命令回执身份无法核实：${error.message}` }); }
      if (!clearMatchingPending()) return this.submissionOutcome('stale', { ...base, reason: '已取得原命令回执，但本地待核实记录已变化；没有清除新记录。', receipt: lookup.receipt });
      if (lookup.receipt.status === 'rejected') return this.submissionOutcome('rejected', { ...base, reason: lookup.receipt.error?.message || '服务明确拒绝了原命令。', receipt: lookup.receipt });
      return this.submissionOutcome('submitted', { ...base, proposalId: lookup.receipt.resource?.kind === 'proposal' ? lookup.receipt.resource.id : null, reason: '服务记录确认原命令已接收。', receipt: lookup.receipt });
    } catch (error) {
      return this.submissionOutcome(error.status === 409 ? 'stale' : 'unknown', { ...base, reason: error.message || '无法读取原命令状态；原命令仍保留。' });
    }
  }
  async postCommand(envelope, projectId) {
    const path = projectId ? `/v1/projects/${encodeURIComponent(projectId)}/commands` : '/v1/commands';
    try { return await this.request(path, { method: 'POST', token: true, body: envelope, projectId: null }); }
    catch (error) { error.commandDispatched = true; error.commandEnvelope = envelope; throw error; }
  }
  validateReceipt(receipt, envelope) {
    const projectId = envelope.projectId || null;
    if (receipt.schemaVersion !== 'studio.message.v1' || receipt.kind !== 'receipt' || receipt.type !== envelope.type || receipt.storeId !== envelope.storeId || (receipt.projectId || null) !== projectId || receipt.commandId !== envelope.commandId || !['accepted', 'rejected'].includes(receipt.status)) throw new Error('命令回执的协议、项目或命令身份不匹配。');
    if (receipt.status === 'rejected') { if (receipt.resource != null || receipt.result != null || typeof receipt.error?.message !== 'string') throw new Error('拒绝回执缺少明确错误信息。'); return; }
    const expectedKind = { 'project.create': 'project', 'project.settings.update': 'project', 'session.preferences.update': 'preferences', 'concept.submit': 'proposal', 'iteration.submit': 'proposal', 'proposal.revise': 'proposal', 'proposal.assets.attach': 'proposal', 'proposal.freeze': 'packet', 'production.start': 'job', 'production.recover': 'job', 'execution.cancel': 'attempt', 'execution.reconcile': 'attempt', 'candidate.accept': 'job', 'candidate.reject': 'job', 'preview.start': 'preview', 'preview.stop': 'preview' }[envelope.type];
    const resultKey = { project: 'project', preferences: 'preferences', proposal: 'proposal', packet: 'packet', job: 'job', attempt: 'attempt', preview: 'preview' }[expectedKind];
    if (!expectedKind || receipt.resource?.kind !== expectedKind || typeof receipt.resource?.id !== 'string' || receipt.result?.[resultKey]?.id !== receipt.resource.id) throw new Error('命令回执资源与业务结果身份不匹配。');
  }
  async start() {
    if (!this.fetch || !this.document) return;
    this.bind();
    try {
      let handshake;
      try { handshake = await this.request('/v1/handshake'); }
      catch (error) { if (error.status !== 404 && error.status !== 405) throw error; }
      if (handshake?.schemaVersion === 'studio.message.v1' && handshake.kind === 'handshake') {
        if (!handshake.storeId || !handshake.serviceInstanceId || typeof handshake.writeToken !== 'string' || !handshake.writeToken) throw new Error('握手响应缺少存储、实例或写入会话身份。');
        if (handshake.readable !== true) throw new Error('服务尚未开放只读能力。');
        this.handshake = handshake; this.protocolVersion = handshake.protocolVersion; this.session = handshake; this.token = handshake.writeToken;
      } else { this.session = await this.request('/session'); this.token = this.session.token; }
      if (!this.token) throw new Error('服务没有建立工作台会话，写入功能已暂停。');
      this.manager = this.protocolVersion ? await this.request('/v1/projects') : await this.request('/workspace'); this.workspace = this.manager;
      if (!this.workspace || !Array.isArray(this.workspace.projects)) throw new Error('项目列表响应格式不完整。');
      $('#connection').textContent = '已连接本机服务'; $('#connection').className = 'connection connected';
      $('#api-version').textContent = this.workspace.apiVersion ? `· 接口 ${this.workspace.apiVersion}` : '';
      hide($('#blocked')); hide($('#workspace'), false); this.renderWorkspace();
      hide($('#test-banner'), !this.workspace.testData);
      this.applyReadinessGate();
      try { await this.drafts.open(); this.persistenceOK = true; $('#persistence-note').textContent = '此浏览器的草稿存储可用。'; }
      catch (error) { this.persistenceOK = false; $('#persistence-note').textContent = `草稿无法持久保存：${error.message}`; $('#persistence-note').className = 'muted danger-text'; }
      this.renderWorkspace();
      const params = new URLSearchParams(globalThis.location?.search || '');
      const selectedProject = params.get('project');
      if (selectedProject && this.manager.projects.some(item => item.id === selectedProject)) await this.openProject(selectedProject, params.get('stage') === 'iteration' ? 'iteration' : 'initial', false);
      else this.showProjectManager();
    } catch (error) { this.showBlocked(error); }
  }
  bind() {
    if (this.bound) return; this.bound = true;
    this.draftStorageTarget?.addEventListener?.('storage', this.boundDraftStorageChange);
    this.legacyWorkbench.bind();
    $('#retry')?.addEventListener('click', () => this.start());
    $('#refresh')?.addEventListener('click', () => this.refresh());
    $('#back-projects')?.addEventListener('click', () => this.showProjectManager());
    $('#new-project-form')?.addEventListener('submit', event => { event.preventDefault(); this.createProject(); });
    $('#rename-project')?.addEventListener('click', () => this.updateProjectSettings({ title: globalThis.prompt?.('项目新名称', this.currentProject()?.title || '') }));
    $('#archive-project')?.addEventListener('click', () => this.updateProjectSettings({ archived: true }));
    $('#concept-form')?.addEventListener('submit', event => { event.preventDefault(); this.submitConcept(); });
    $('#concept')?.addEventListener('input', () => this.queueConceptDraftSave());
    $('#images')?.addEventListener('change', event => this.uploadImages(event.target.files));
    $('#answers-form')?.addEventListener('submit', event => { event.preventDefault(); this.answerQuestions(); });
    $('#answers-form')?.addEventListener('input', event => { const control = event.target.closest('[name][data-answer-type]'); if (control) this.saveProposalQuestionInput(control.name, control.value); });
    $('#answers-form')?.addEventListener('change', event => { const control = event.target.closest('[name][data-answer-type]'); if (control) this.saveProposalQuestionInput(control.name, control.value); });
    $('#reviewed')?.addEventListener('change', event => { $('#freeze').disabled = !event.target.checked || !this.readiness?.ready || (this.usesV1Commands(this.proposal?.projectId) && this.reviewedPlan?.reviewedPlanRef !== this.proposal?.reviewedPlanRef); });
    $('#freeze')?.addEventListener('click', () => this.freezeProposal());
    $('#resume-packet')?.addEventListener('click', () => this.resumeFrozenPacket());
    $('#cancel')?.addEventListener('click', () => this.cancelJob());
    $('#reconcile')?.addEventListener('click', () => this.reconcileJob());
    $('#edit-form')?.addEventListener('submit', event => { event.preventDefault(); if (this.objectsWorkflow()) this.legacyWorkbench.openReport(); else this.submitIteration(); });
    $('#dynamic-fields')?.addEventListener('input', event => { if (event.target?.dataset?.fieldId) this.onDynamicFieldEdit(event.target); });
    $('#dynamic-fields')?.addEventListener('change', event => { if (event.target?.dataset?.fieldId) this.onDynamicFieldEdit(event.target); });
    $('#object-list')?.addEventListener('click', event => { const button = event.target.closest('[data-object-id]'); if (button) this.selectObject(button.dataset.objectId); });
    $('#add-feedback')?.addEventListener('click', () => this.addFeedback());
    $('#confirm-rebase')?.addEventListener('click', event => { event.preventDefault(); this.confirmRebase(); });
    $('#raw-draft-recovery-dialog')?.addEventListener('click', event => {
      const action = event.target.closest('[data-action]')?.dataset.action;
      if (action === 'close-raw-draft-recovery') $('#raw-draft-recovery-dialog').close?.();
      if (action === 'copy-raw-draft-recovery') void this.copyCorruptDraftArchive();
    });
    $('#rebase-dialog')?.addEventListener('cancel', () => { this.pendingRebase = null; });
    $('#rebase-dialog')?.addEventListener('close', () => { if ($('#rebase-dialog').returnValue !== 'rebase') this.pendingRebase = null; });
    $('#feedback-message')?.addEventListener('input', () => this.handleFeedbackInput());
    $('#feedback-category')?.addEventListener('change', () => this.handleFeedbackInput());
    for (const field of ['#edit-text', ...TEMPLATE_FIELDS.map(name => `#edit-form [name="${name}"]`)]) $(field)?.addEventListener('input', () => this.queueDraftSave());
  }
  showBlocked(error) {
    if ($('#blocked')?.dataset) $('#blocked').dataset.bootWait = '';
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
  refresh({ announce = true, streamReleased = false } = {}) {
    if (this.destroyed) return Promise.resolve(false);
    const context = this.captureSelectionContext();
    const key = `${context.generation}:${context.projectId}`;
    if (this.refreshInFlight?.key === key) {
      if (announce) this.refreshInFlight.announce = true;
      return this.refreshInFlight.promise;
    }
    const refresh = { key, context, announce, streamReleased, streamGeneration: this.streamGeneration };
    this.refreshInFlight = refresh;
    this.activity = '正在刷新项目状态'; this.renderWorkflowStatus();
    refresh.promise = this.performRefresh(refresh).finally(() => {
      if (this.refreshInFlight === refresh) this.refreshInFlight = null;
    });
    return refresh.promise;
  }
  async performRefresh(refresh) {
    let context = refresh.context;
    let pausedStream = false;
    try {
      if (!refresh.streamReleased && this.protocolVersion && this.streamProjectId === context.projectId) {
        pausedStream = true; this.streamPaused = true;
        if (this.streamRetry != null) this.timers.clearTimeout(this.streamRetry); this.streamRetry = null;
        this.streamController?.abort();
        if (this.streamAttemptDone) await this.streamAttemptDone;
        if (!this.selectionContextMatches(context)) return false;
      }
      const workspace = this.protocolVersion ? (this.projectId ? await this.request(`/v1/projects/${encodeURIComponent(this.projectId)}/view`) : await this.request('/v1/projects')) : await this.request(this.projectId ? `/projects/${encodeURIComponent(this.projectId)}/workspace` : '/workspace');
      if (!this.selectionContextMatches(context)) return false;
      if (!this.projectId) { this.manager = workspace; this.workspace = workspace; this.renderWorkspace(); if (this.activity === '正在刷新项目状态') this.activity = null; this.renderWorkflowStatus(); if (refresh.announce) this.notify('项目状态已刷新。'); return true; }
      if (!workspace.projects?.some(project => project.id === this.projectId)) throw new Error('服务未返回当前项目，已拒绝加载跨项目数据。');
      this.workspace = workspace; this.mergeProjectSummary(workspace.projects[0]); this.renderWorkspace();
      const selectedProject = this.projectId || '';
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
            if (associated && (!selectedProject || associated.projectId === selectedProject) && !this.selectedJobForProject(selectedProject)) await this.loadJob(associated.id, false);
            else hide($('#resume-packet'), false);
          }
        } else { this.packet = null; this.renderProposal(); }
      } else if (!pending && this.proposal) {
        this.proposal = null; this.packet = null; hide($('#proposal-panel'));
      }
      if (!this.selectionContextMatches(context)) return false;
      const scopedJobs = selectedProject ? (this.workspace.jobs || []).filter(item => item.projectId === selectedProject) : (this.workspace.jobs || []);
      const selectedJobId = this.selectedJobForProject(selectedProject);
      if (selectedJobId && scopedJobs.some(item => item.id === selectedJobId)) await this.loadJob(selectedJobId, false);
      else if (this.job && scopedJobs.some(item => item.id === this.job.id)) await this.loadJob(this.job.id, false);
      else {
        const latest = scopedJobs.find(item => ACTIVE.has(item.status)) || this.latestByDate(scopedJobs);
        if (latest) await this.loadJob(latest.id, false);
        else if (selectedProject && this.job && this.job.projectId !== selectedProject) {
          this.jobLoadGeneration++; this.stopPolling(); this.job = null; hide($('#job-panel'));
        }
      }
      const projectId = selectedProject || this.job?.projectId || this.snapshot?.projectId || this.snapshot?.id;
      if (projectId) await this.ensureWorkbench(projectId, true);
      if (!this.selectionContextMatches(context)) return false;
      if (this.activity === '正在刷新项目状态') this.activity = null;
      $('#connection').textContent = '已连接本机服务'; $('#connection').className = 'connection connected'; this.renderWorkflowStatus();
      if (refresh.announce) this.notify('项目状态已刷新。');
      return true;
    } catch (error) { if (!this.selectionContextMatches(context)) return false; this.activity = '项目状态未确认'; this.renderWorkflowStatus(); this.notify(`刷新失败：${error.message}${/读取服务超时/.test(error.message) ? ' 请点击“刷新状态”再次读取。' : ''}`); return false; }
    finally {
      if (pausedStream && this.streamGeneration === refresh.streamGeneration && this.selectionContextMatches(context) && this.streamProjectId === context.projectId && !this.destroyed) {
        this.streamPaused = false;
        if (this.streamRetry == null && this.streamConnect) this.streamRetry = this.timers.setTimeout(() => { this.streamRetry = null; return this.streamConnect?.(); }, 1200);
      }
    }
  }
  latestByDate(items) { return [...items].sort((a, b) => String(b.updatedAt || b.createdAt || '').localeCompare(String(a.updatedAt || a.createdAt || '')))[0] || null; }
  packetFor(proposal) { return (this.workspace?.packets || []).find(item => item.id === proposal.packetId || item.packetId === proposal.packetId || item.proposalId === proposal.id) || null; }
  jobFor(proposal, packet) { return (this.workspace?.jobs || []).find(item => item.proposalId === proposal.id || item.packetId === proposal.packetId || item.packetId === packet?.id || item.id === packet?.jobId) || null; }
  ensureWorkbench(projectId, force = false) {
    if (!force && (this.snapshot?.projectId || this.snapshot?.id) === projectId) return Promise.resolve(this.snapshot);
    if (this.workbenchLoad?.projectId === projectId) return this.workbenchLoad.promise;
    const promise = this.loadWorkbench(projectId, { force }).finally(() => {
      if (this.workbenchLoad?.promise === promise) this.workbenchLoad = null;
    });
    this.workbenchLoad = { projectId, promise };
    return promise;
  }
  pendingProposal(projectId = this.projectId || null) {
    if (!projectId) return null;
    const latest = this.latestProposalForProject(projectId);
    if (!latest) return null;
    if (['FAILED', 'BLOCKED', 'NEEDS_CLARIFICATION', 'READY'].includes(latest.status) || PLANNING.has(latest.status)) return latest;
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
  projectWorkflowState(project) {
    if (!project?.id) return null;
    if (this.projectView?.projectId === project.id && this.projectView.phase) return this.projectView;
    if (project.workflowState && (project.workflowState.phase || project.workflowState.step)) return project.workflowState;
    const proposals = (this.workspace?.proposals || []).filter(item => item.projectId === project.id)
      .sort((a, b) => Number(b.revision || 0) - Number(a.revision || 0) || String(b.updatedAt || b.createdAt || '').localeCompare(String(a.updatedAt || a.createdAt || '')));
    const jobs = (this.workspace?.jobs || []).filter(item => item.projectId === project.id)
      .sort((a, b) => String(b.updatedAt || b.createdAt || '').localeCompare(String(a.updatedAt || a.createdAt || '')));
    const proposal = proposals[0], job = jobs.find(item => ACTIVE.has(item.status)) || jobs[0];
    if (job?.status === 'READY_FOR_REVIEW') return { phase: 'candidate', step: 'candidate_review', attention: 'user' };
    if (job && ['QUEUED', 'DISPATCHING', 'RUNNING', 'PROJECTING', 'VERIFYING', 'CANCEL_REQUESTED', 'CANCELLING', 'UNCERTAIN'].includes(job.status)) return { phase: 'execution', step: job.status === 'VERIFYING' ? 'verifying' : 'producing', attention: job.status === 'UNCERTAIN' ? 'uncertain' : 'none' };
    if (proposal?.status === 'READY') return { phase: 'discussion', step: 'proposal_review', attention: 'user' };
    if (proposal?.status === 'NEEDS_CLARIFICATION') return { phase: 'discussion', step: 'clarification', attention: 'user' };
    if (proposal && PLANNING.has(proposal.status)) return { phase: 'discussion', step: 'planning', attention: proposal.status === 'PLANNING_UNCERTAIN' ? 'uncertain' : 'none' };
    if (job?.status === 'REJECTED') return { phase: 'iteration', step: 'repair', attention: 'user' };
    if (project.archived) return { phase: 'archived', step: 'archived', attention: 'none' };
    if (Number(project.publicationRevision) > 0) return { phase: 'iteration', step: 'accepted', attention: 'user' };
    return null;
  }
  projectWorkflowLabel(project) {
    const state = this.projectWorkflowState(project);
    if (!state) return '状态待读取';
    if (state.attention === 'uncertain') return '状态待核实 · 读取服务记录并对账';
    const steps = { concept: '初始策划', planning: '策划中', clarification: '需要补充信息', proposal_review: '方案待审阅', frozen: '已确认 · 等待制作', producing: '制作中', verifying: '运行验证中', candidate_review: '候选待审阅', accepted: '已接受 · 可继续迭代', repair: '候选已拒绝 · 可继续返修', archived: '已归档' };
    const phases = { discussion: '讨论中', execution: '制作与验证', production: '等待制作', candidate: '候选待审阅', iteration: '迭代工作台', archived: '已归档' };
    return steps[state.step] || phases[state.phase] || '状态待读取';
  }
  renderWorkspace() {
    const projects = this.manager?.projects || this.workspace?.projects || [], jobs = this.workspace?.jobs || [];
    const projectList = $('#project-list'); projectList.replaceChildren();
    if (!projects.length) projectList.append(el('p', 'muted', '还没有项目，从一个想法开始。'));
    for (const project of projects.filter(item => !item.archived)) { const row = el('article', 'project-card'); const info = el('div'); info.append(el('h3', '', project.title || project.name || '未命名项目')); const revision = Number(project.publicationRevision || 0); if (revision > 0) info.append(el('p', 'muted', `本机已接受版本 ${revision}`)); info.append(el('p', 'muted project-stage-summary', this.projectWorkflowLabel(project))); const open = el('button', 'button primary', '继续项目'); open.type = 'button'; open.addEventListener('click', () => this.openProject(project.id)); row.append(info, open); projectList.append(row); }
    const archived = projects.filter(item => item.archived);
    if (archived.length) { const section = el('details', 'archived-projects'); section.append(el('summary', '', `已归档项目 (${archived.length})`)); for (const project of archived) { const row = el('article', 'project-card'); row.append(el('span', '', project.title || project.id)); const restore = el('button', 'button secondary', '恢复项目'); restore.type = 'button'; restore.addEventListener('click', () => this.updateProjectSettings({ archived: false }, project.id)); row.append(restore); section.append(row); } projectList.append(section); }
    const jobList = $('#job-list'); jobList.replaceChildren();
    if (!jobs.length) jobList.append(el('p', 'muted', '还没有制作记录'));
    for (const job of jobs.slice(0, 8)) { const row = el('button', 'job-row'); row.type = 'button'; row.append(el('span', '', job.title || job.projectTitle || job.id)); const status = el('span', 'mini-status', jobLabel(job)); row.append(status); row.addEventListener('click', () => this.selectJob(job.id)); jobList.append(row); }
  }
  currentProject() { return (this.manager?.projects || this.workspace?.projects || []).find(item => item.id === this.projectId) || null; }
  usesV1Commands(projectId = this.projectId) {
    if (!this.protocolVersion || !projectId) return false;
    const project = (this.manager?.projects || this.workspace?.projects || []).find(item => item.id === projectId);
    return project?.protocolVersion === 1;
  }
  legacyIterationCommandsAvailable() { return Array.isArray(this.handshake?.capabilities) && this.handshake.capabilities.includes('legacy-iteration-commands'); }
  mergeProjectSummary(project) { if (!project?.id || !this.manager) return; this.manager.projects = (this.manager.projects || []).map(item => item.id === project.id ? { ...item, ...project } : item); }
  async showProjectManager() {
    const projectId = this.projectId;
    this.advanceSelection(); this.stopPolling(); this.stopProposalPolling(); this.stopEventStream(); const generation = this.selectionGeneration;
    if (projectId && this.conceptDraftTimer != null) { this.timers.clearTimeout(this.conceptDraftTimer); this.conceptDraftTimer = null; await this.saveConceptDraft(projectId); }
    if (projectId && this.draftTimer != null) { this.timers.clearTimeout(this.draftTimer); this.draftTimer = null; await this.saveDraft(); }
    if (generation !== this.selectionGeneration) return;
    this.projectId = null; this.stage = 'initial'; this.targetNotes = {}; this.structuralProposals = []; this.workbenchResults = []; this.feedbackInputs = {}; this.feedbackInputTargetId = null; this.legacyUnboundFeedback = null; this.proposalInputs = {};
    this.selectedJob = null;
    this.proposal = null; this.packet = null; this.job = null; this.snapshot = null; this.capabilities = null; this.workflow = null; this.candidates = []; this.assets = []; this.referenceIntents = {}; this.conceptGenerationRequests = []; this.referenceBatches = []; if ($('#concept-visual-interpretation')) $('#concept-visual-interpretation').value = ''; this.renderConceptReferenceResults(); this.feedback = []; this.feedbackInputs = {}; this.feedbackInputTargetId = null; this.legacyUnboundFeedback = null; this.proposalInputs = {}; this.fieldDraftValues = {}; this.selectedObjectId = null; this.dirtyFields.clear(); this.draftKey = null; this.resetDraftConflictContext(); this.activity = null; this.retryOutcomeUnknown = null; this.pendingRebase = null;
    this.loadFeedbackInputForCurrentTarget();
    if ($('#rebase-dialog')?.open) $('#rebase-dialog').close(); $('#notice').textContent = ''; hide($('#notice')); hide($('#home-hero'), false); hide($('#project-view')); hide($('#project-manager'), false); hide($('#job-panel')); hide($('#proposal-panel')); hide($('#workbench-panel')); this.updateUrl(); this.renderWorkspace();
    try { const manager = await this.request('/workspace'); if (generation !== this.selectionGeneration || this.projectId) return; this.manager = manager; this.workspace = manager; this.renderWorkspace(); }
    catch (error) { if (generation === this.selectionGeneration) this.notify(`项目列表刷新失败：${error.message}`); }
  }
  updateUrl() {
    if (!globalThis.history?.replaceState) return;
    const previous = new URLSearchParams(globalThis.location?.search || '');
    const keepWorkbenchRoute = previous.get('project') === this.projectId && !!this.projectId;
    const params = new URLSearchParams();
    if (this.projectId) params.set('project', this.projectId);
    if (this.projectId && this.stage === 'iteration') params.set('stage', 'iteration');
    if (keepWorkbenchRoute) for (const key of ['target', 'view', 'scene']) { const value = previous.get(key); if (value) params.set(key, value); }
    globalThis.history.replaceState(null, '', `${globalThis.location.pathname}${params.size ? `?${params}` : ''}`);
  }
  async createProject() {
    const title = $('#new-project-title').value.trim(); if (!title) return;
    const submit = $('#new-project-form button[type="submit"]'); submit.disabled = true;
    const generation = this.selectionGeneration, activeProject = this.projectId;
    const selectionUnchanged = () => generation === this.selectionGeneration && activeProject === this.projectId;
    try {
      const response = this.protocolVersion
        ? await this.sendCommand('project.create', { name: title }, { projectId: null })
        : await this.request('/projects', { method: 'POST', token: true, body: { title, workflow: 'objects-v1' } }); const project = response.project || response;
      if (!project.id) throw new Error('服务没有返回项目编号。');
      this.manager.projects = [project, ...(this.manager.projects || []).filter(item => item.id !== project.id)];
      if (selectionUnchanged()) { $('#new-project-title').value = ''; await this.openProject(project.id); }
      else this.renderWorkspace();
    } catch (error) { if (selectionUnchanged()) this.notify(`项目未创建：${error.message}`); }
    finally { submit.disabled = false; }
  }
  async updateProjectSettings(changes, projectId = this.projectId) {
    const project = (this.manager?.projects || []).find(item => item.id === projectId); if (!project) return;
    const activeProjectAtStart = this.projectId, generation = this.selectionGeneration;
    if (changes.title === null) return;
    if (changes.archived === true && !globalThis.confirm?.(`归档“${project.title}”？归档项目仍可恢复查看。`)) return;
    try { const response = this.usesV1Commands(projectId)
      ? await this.sendCommand('project.settings.update', { ...(changes.title ? { name: changes.title } : {}), ...(typeof changes.archived === 'boolean' ? { archived: changes.archived } : {}) }, { projectId })
      : await this.request(`/projects/${encodeURIComponent(project.id)}/settings`, { method: 'POST', token: true, body: changes, projectId }); const updated = response.project || response; this.manager.projects = this.manager.projects.map(item => item.id === project.id ? { ...item, ...updated, title: updated.title || updated.name } : item); if (activeProjectAtStart !== this.projectId || generation !== this.selectionGeneration) return; if (changes.archived === true) return this.showProjectManager(); if (this.workspace?.projects) this.workspace.projects = this.workspace.projects.map(item => item.id === project.id ? { ...item, ...updated } : item); this.renderWorkspace(); $('#workspace-name').textContent = updated.title || updated.name || project.title; $('#sidebar-project-name').textContent = updated.title || updated.name || project.title; }
    catch (error) { if (activeProjectAtStart === this.projectId && generation === this.selectionGeneration) this.notify(`项目设置未保存：${error.message}`); }
  }
  async openProject(projectId, stage = 'initial', updateUrl = true) {
    const priorActiveProject = this.projectId;
    const previousSnapshot = this.snapshot;
    const previousWorkspace = this.workspace;
    const previousProposal = this.proposal;
    const previousPacket = this.packet;
    const previousJob = this.job;
    const previousCapabilities = this.capabilities;
    const previousCandidates = this.candidates;
    const previousProjectId = previousSnapshot?.projectId || previousSnapshot?.id || priorActiveProject;
    const previousDraft = previousSnapshot ? this.readVisibleDraft() : null;
    this.advanceSelection();
    const selectionGeneration = this.selectionGeneration;
    this.stopPolling(); this.stopProposalPolling(); this.stopEventStream();
    if (previousProjectId && previousProjectId !== projectId) {
      if (this.conceptDraftTimer != null) { this.timers.clearTimeout(this.conceptDraftTimer); this.conceptDraftTimer = null; await this.saveConceptDraft(previousProjectId); }
      if (this.draftTimer != null) { this.timers.clearTimeout(this.draftTimer); this.draftTimer = null; await this.saveDraft(); }
      if (selectionGeneration !== this.selectionGeneration) return;
    }
    this.projectId = projectId; this.stage = stage;
    this.selectedJob = null;
    if (updateUrl) this.updateUrl();
    this.activity = null; this.retryOutcomeUnknown = null; this.pendingRebase = null; this.selectedObjectId = null; this.dirtyFields.clear();
    if ($('#rebase-dialog')?.open) $('#rebase-dialog').close(); $('#notice').textContent = ''; hide($('#notice'));
    this.selectionBusy = true; this.applyReadinessGate();
    this.workspace = null;
    if (previousProjectId !== projectId) { this.proposal = null; this.packet = null; this.job = null; this.snapshot = null; this.capabilities = null; this.workflow = null; this.candidates = []; this.previews = []; this.assets = []; this.referenceIntents = {}; this.conceptGenerationRequests = []; this.referenceBatches = []; if ($('#concept-visual-interpretation')) $('#concept-visual-interpretation').value = ''; this.renderConceptReferenceResults(); this.feedback = []; this.feedbackInputs = {}; this.feedbackInputTargetId = null; this.legacyUnboundFeedback = null; this.proposalInputs = {}; this.fieldDraftValues = {}; this.targetNotes = {}; this.structuralProposals = []; this.workbenchResults = []; this.legacyWorkbench.initialRouteApplied = false; this.legacyWorkbench.view = 'design'; this.legacyWorkbench.activeSceneId = null; this.draftKey = null; this.resetDraftConflictContext(); $('#concept').value = ''; $('#images').disabled = false; $('#images').value = ''; this.loadFeedbackInputForCurrentTarget(); this.renderAssets(); hide($('#proposal-panel')); hide($('#job-panel')); hide($('#workbench-panel')); hide($('#concept-form')?.closest('.panel')); }
    let loadGeneration = this.workbenchGeneration;
    try {
      const scoped = this.protocolVersion ? await this.request(`/v1/projects/${encodeURIComponent(projectId)}/view`) : await this.request(`/projects/${encodeURIComponent(projectId)}/workspace`);
      if (this.protocolVersion && (scoped.schemaVersion !== 'studio.project-view.v1' || scoped.storeId !== this.handshake?.storeId || scoped.projectId !== projectId)) throw new Error('公开项目视图的版本、存储或项目身份不匹配。');
      if (selectionGeneration !== this.selectionGeneration) return;
      if (!scoped.projects?.some(project => project.id === projectId)) throw new Error('项目工作区响应身份不匹配。');
      this.workspace = scoped; this.mergeProjectSummary(scoped.projects.find(item => item.id === projectId)); this.applyProjectView(scoped);
      if (this.protocolVersion) await this.loadSessionSettings(projectId, selectionGeneration);
      const workbenchRequest = this.loadWorkbench(projectId); loadGeneration = this.workbenchGeneration; await workbenchRequest;
      loadGeneration = this.workbenchGeneration;
      if (selectionGeneration !== this.selectionGeneration || (this.snapshot?.projectId || this.snapshot?.id) !== projectId) return;
      const project = this.currentProject(); $('#workspace-name').textContent = project?.title || projectId; $('#sidebar-project-name').textContent = project?.title || projectId; $('#concept-project-label').textContent = project?.title || projectId;
      await this.restoreConceptDraft(projectId, selectionGeneration);
      if (this.job && this.job.projectId !== projectId) { this.jobLoadGeneration++; this.stopPolling(); this.job = null; hide($('#job-panel')); }
      const proposal = this.pendingProposal(projectId);
      if (!proposal) { this.proposal = null; this.packet = null; hide($('#proposal-panel')); hide($('#freeze-area')); }
      else {
      this.proposal = proposal;
      if (proposal.status === 'FROZEN') {
        this.packet = this.packetFor(proposal); this.renderProposal(); this.renderFrozenPacket();
        const associatedJob = this.jobFor(proposal, this.packet);
        if (associatedJob) await this.loadJob(associatedJob.id);
        else hide($('#resume-packet'), false);
      } else { this.packet = null; this.renderProposal(); }
      }
      const activeJobs = this.workspace.jobs || []; const selectedJob = activeJobs.find(item => ACTIVE.has(item.status)) || this.latestByDate(activeJobs);
      if (selectedJob) await this.loadJob(selectedJob.id);
      hide($('#home-hero')); hide($('#project-manager')); hide($('#project-view'), false);
      if (this.stage === 'iteration' && this.canEnterIteration()) this.enterIterationStage(); else if (this.stage === 'iteration') { this.stage = 'initial'; this.updateUrl(); }
      this.renderWorkflowStatus(); this.renderWorkspace();
      if (this.objectsWorkflow() && !this.legacyWorkbench.pendingInitialRoute) this.legacyWorkbench.syncUrl(true);
      if (this.protocolVersion) this.startEventStream(projectId, this.projectView?.throughSequence ?? scoped.throughSequence ?? 0);
    }
    catch (error) {
      if (selectionGeneration !== this.selectionGeneration) return;
      if (previousSnapshot && previousProjectId === projectId) {
        this.workspace = previousWorkspace; this.snapshot = previousSnapshot; this.proposal = previousProposal; this.packet = previousPacket; this.job = previousJob; this.capabilities = previousCapabilities; this.candidates = previousCandidates;
        this.draftKey = this.makeDraftKey(previousSnapshot);
        this.renderWorkbench(); if (previousDraft) this.applyVisibleDraft(previousDraft);
        this.renderWorkflowStages(); this.renderWorkflowStatus();
      } else {
        this.projectId = null; this.workspace = this.manager; this.snapshot = null; this.proposal = null; this.packet = null; this.job = null; this.capabilities = null; this.candidates = []; this.draftKey = null;
        hide($('#project-view')); hide($('#project-manager'), false); hide($('#home-hero'), false); this.updateUrl();
      }
      this.stage = 'initial'; this.notify(`无法读取所选项目：${error.message}。项目列表和原有草稿仍可访问。`);
    }
    finally { if (selectionGeneration === this.selectionGeneration && loadGeneration === this.workbenchGeneration) { this.selectionBusy = false; this.applyReadinessGate(); } }
  }
  advanceSelection() {
    this.selectionGeneration++;
    this.workbenchGeneration++; this.workbenchLoad = null;
    const interruptedDraftRefresh = this.draftConflictRefresh;
    if (interruptedDraftRefresh) this.finishDraftConflictRefresh(interruptedDraftRefresh.generation, interruptedDraftRefresh.snapshot,
      { error: new Error('状态读取已被新的页面选择中断') });
    this.visualPlanning = null; this.referenceGenerating = false; this.referenceGenerationOperation = null; hide($('#proposal-visual-planning'));
    this.conceptGeneration++; this.proposalMutationGeneration++; this.jobMutationGeneration++; this.jobLoadGeneration++;
    $('#cancel').disabled = false; $('#reconcile').disabled = false; $('#resume-packet').disabled = false;
    $('#freeze').textContent = '确认方案并继续'; $('#freeze').disabled = !$('#reviewed').checked || !this.readiness?.ready;
    this.applyReadinessGate();
  }
  captureSelectionContext() { return { generation: this.selectionGeneration, projectId: this.projectId || '' }; }
  selectionContextMatches(context) { return !this.destroyed && !!context && context.generation === this.selectionGeneration && context.projectId === (this.projectId || ''); }
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
    if (this.usesV1Commands(this.projectId)) {
      if (this.sessionCatalog?.available !== true || !(this.sessionCatalog.models || []).length) missing.push(['agentRunnerCatalog', '可用的 AgentRunner 与模型目录']);
      const capabilities = this.sessionCatalog?.capabilities || [];
      if (!capabilities.includes('planning-readonly-v1')) missing.push(['plannerIsolation', '策划只读隔离']);
      if (!capabilities.includes('production-private-v1')) missing.push(['producerIsolation', '制作私有副本隔离']);
    }
    this.readiness = { ready: missing.length === 0, missing };
    const submit = $('#concept-form [type="submit"]');
    const selectedProject = this.projectId || '';
    const projectReady = !selectedProject || this.snapshotMatchesProject(selectedProject);
    if (submit) submit.disabled = !this.readiness.ready || this.selectionBusy || !projectReady;
    const iteration = $('#edit-form [type="submit"]');
    if (iteration) iteration.disabled = !this.readiness.ready || this.selectionBusy || !projectReady;
    const blocked = $('#blocked');
    if (!this.readiness.ready) {
      hide(blocked, false);
      $('#blocked-title').textContent = '新工作流尚未通过启动检查';
      const reasons = missing.map(([key, label]) => { const state = this.workspace?.capabilities?.[key]; const reason = key === 'agentRunnerCatalog' ? this.sessionCatalog?.available === false ? 'Runner 或目录暂不可用' : '' : ''; return `${label}${reason ? `（${reason}）` : state && typeof state === 'object' && state.reason ? `（${state.reason}）` : ''}`; });
      $('#blocked-copy').textContent = `当前项目仍可只读查看；制作入口已暂停。服务尚未声明以下能力就绪：${reasons.join('、')}。`;
      $('#blocked-pill')?.remove();
      const heading = blocked.querySelector('.panel-heading'); if (heading && !heading.querySelector('.readiness-pill')) { const pill = el('span', 'status-pill blocked-pill readiness-pill', '暂不可用'); heading.append(pill); }
    } else if ($('#blocked-title').textContent === '新工作流尚未通过启动检查') {
      hide(blocked);
    }
  }
  async uploadImages(files) {
    if (!files?.length) return;
    const projectId = this.projectId, context = this.captureSelectionContext(); if (!projectId) return this.notify('请先在项目管理页创建或选择项目。');
    const input = $('#images'); input.disabled = true; const added = [], failures = [], persistenceFailures = [];
    try {
      for (const file of Array.from(files)) {
        if (!this.selectionContextMatches(context)) return;
        try {
          if (!['image/png', 'image/jpeg', 'image/webp'].includes(file.type)) throw new Error('不是支持的图片格式。');
          if (this.assets.length >= 6) throw new Error('本轮最多添加 6 张图片。');
          if (file.size > 5 * 1024 * 1024) throw new Error('超过 5 MB。');
          const dataBase64 = await new Promise((resolve, reject) => { const reader = new FileReader(); reader.onload = () => resolve(String(reader.result).split(',')[1]); reader.onerror = () => reject(reader.error || new Error('读取图片失败。')); reader.readAsDataURL(file); });
          if (!this.selectionContextMatches(context)) return;
          const result = await this.request('/assets', { method: 'POST', token: true, projectId, body: { name: file.name, mimeType: file.type, dataBase64, purpose: $('#asset-purpose').value } });
          if (!this.selectionContextMatches(context)) return;
          const asset = result.asset || result; if (!asset.id) throw new Error('服务没有返回图片编号。');
          this.assets.push(asset); added.push(asset); this.renderAssets();
          if (await this.saveConceptDraft(projectId) !== true) persistenceFailures.push(file.name);
        } catch (error) {
          if (!this.selectionContextMatches(context)) return;
          failures.push(`${file.name}：${error.message}`);
        }
      }
      if (!this.selectionContextMatches(context)) return;
      if (failures.length || persistenceFailures.length) {
        const uploaded = added.length ? `已上传并显示 ${added.length} 张` : '没有图片上传成功';
        const notAdded = failures.length ? `；未添加 ${failures.length} 张：${failures.join('；')}` : '';
        const notSaved = persistenceFailures.length ? `；${persistenceFailures.join('、')}已上传到项目但本地草稿未能保存` : '';
        this.notify(`${uploaded}${notAdded}${notSaved}。`);
      } else if (added.length) this.notify(`已上传并保存 ${added.length} 张参考图片。`);
    }
    finally { if (this.selectionContextMatches(context)) { input.disabled = false; input.value = ''; } }
  }
  referencePayload() {
    const selected = new Set(this.assets.map(asset => asset.id));
    const records = this.assets.map(asset => this.referenceIntents?.[asset.id] || {
      assetId: asset.id, intent: asset.generation ? '' : `用户上传用途：${asset.purpose || 'reference'}`,
      targetObjectIds: [], preserve: '', unknown: '',
    });
    for (const [key, record] of Object.entries(this.referenceIntents || {})) {
      if (!selected.has(key) && record.assetId === null && record.intent?.trim()) records.push(record);
    }
    return cloneValue(records);
  }
  referenceDraftValid() {
    if (this.referencePayload().some(reference => !reference.intent?.trim())) {
      this.notify('请说明已选参考的采纳用途，或取消图片选择后继续文字流程。'); return false;
    }
    return true;
  }
  renderAssets() {
    const list = $('#image-list'); if (!list) return; list.replaceChildren();
    this.referenceIntents ||= {};
    for (const asset of this.assets) {
      const record = this.referenceIntents[asset.id] ||= { assetId: asset.id,
        intent: asset.generation ? '' : `用户上传用途：${asset.purpose || 'reference'}`, targetObjectIds: [], preserve: '', unknown: '' };
      const chip = el('section', 'reference-editor asset-chip'); chip.dataset.assetId = asset.id;
      const thumb = el('img'); thumb.src = `${API}/projects/${encodeURIComponent(this.projectId)}/assets/${encodeURIComponent(asset.id)}`;
      thumb.alt = `${asset.name || '参考图片'} · 概念参考`;
      const state = el('p', 'muted', `已选参考 · 尚未纳入新方案 · 实际 ${asset.width ?? '未知'} × ${asset.height ?? '未知'}${asset.generation?.requestedSize ? `；请求 ${asset.generation.requestedSize}` : ''}`);
      thumb.addEventListener('error', () => { thumb.hidden = true; state.textContent = '图片不可读；采纳文字仍保留。可取消图片选择，继续文字流程。'; });
      chip.append(thumb, state);
      for (const [key, label] of [['intent', '采纳用途'], ['preserve', '需要保持'], ['unknown', '尚未确定']]) {
        const field = el('label', 'field-label', label), input = el('textarea'); input.rows = key === 'intent' ? 2 : 1;
        input.maxLength = 2000; input.value = record[key] || ''; input.setAttribute('aria-label', `${asset.name || '参考图片'} ${label}`);
        input.addEventListener('input', () => { record[key] = input.value; this.queueConceptDraftSave(); }); field.append(input); chip.append(field);
      }
      if (this.objectItems().length) {
        const target = el('select'); target.setAttribute('aria-label', '参考关联目标');
        target.append(new Option('本轮项目视觉方向', ''));
        for (const object of this.objectItems()) target.append(new Option(object.name || object.id, object.id));
        target.value = record.targetObjectIds?.[0] || '';
        target.addEventListener('change', () => { record.targetObjectIds = target.value ? [target.value] : []; this.queueConceptDraftSave(); }); chip.append(target);
      }
      const remove = el('button', 'button quiet', '取消图片选择，保留文字要求'); remove.type = 'button';
      remove.addEventListener('click', () => { record.assetId = null; this.assets = this.assets.filter(item => item.id !== asset.id); this.renderAssets(); this.renderConceptReferenceResults(); this.queueConceptDraftSave(); }); chip.append(remove); list.append(chip);
    }
    for (const [key, record] of Object.entries(this.referenceIntents)) {
      if (record.assetId !== null || !record.intent?.trim()) continue;
      const textCard = el('section', 'reference-editor'); textCard.append(el('strong', '', '保留的文字视觉要求（图片未选用）'));
      for (const [fieldKey, label] of [['intent', '保留的文字视觉要求'], ['preserve', '需要保持'], ['unknown', '尚未确定']]) {
        const field = el('label', 'field-label', label), editor = el('textarea');
        editor.value = record[fieldKey] || ''; editor.maxLength = 2000; editor.setAttribute('aria-label', label);
        editor.addEventListener('input', () => { record[fieldKey] = editor.value; this.queueConceptDraftSave(); }); field.append(editor); textCard.append(field);
      }
      if (record.targetObjectIds?.length) textCard.append(el('p', 'muted', `关联目标：${record.targetObjectIds.map(id => this.objectItems().find(item => item.id === id)?.name || id).join('、')}`));
      const remove = el('button', 'button quiet', '移除此文字要求'); remove.type = 'button'; remove.addEventListener('click', () => { delete this.referenceIntents[key]; this.renderAssets(); this.queueConceptDraftSave(); }); textCard.append(remove); list.append(textCard);
    }
    this.renderConceptGenerationControls();
  }
  renderConceptGenerationControls() {
    const root = $('#concept-generation'); if (!root || root.childElementCount) return;
    const label = el('label', 'field-label', '概念图解释（可修改，不替换原始想法）');
    const input = el('textarea'); input.id = 'concept-visual-interpretation'; input.rows = 2; input.maxLength = 8000;
    input.setAttribute('aria-label', '概念图解释'); input.addEventListener('input', () => this.queueConceptDraftSave()); label.append(input);
    const generate = el('button', 'button secondary', '使用 ImageGen 生成概念参考'); generate.type = 'button'; generate.id = 'generate-concept-reference';
    generate.addEventListener('click', () => this.generateConceptReference());
    const refresh = el('button', 'button quiet', '查看 / 核实已有生成'); refresh.type = 'button'; refresh.addEventListener('click', () => this.loadConceptReferences(true));
    root.append(label, el('p', 'muted', '显式点击才生成一张图；默认低质量、请求 1536×1024。生成后先选择参考并说明用途，才随方案送审。'), generate, refresh);
  }
  async loadConceptReferences(reconcile = false) {
    if (!this.projectId) return;
    const context = this.captureSelectionContext(), projectId = this.projectId;
    try {
      const result = await this.request('/concept-references', { projectId });
      if (!this.selectionContextMatches(context)) return;
      const knownIds = new Set((result.requests || []).map(r => r.id));
      const unknownLocal = (this.conceptGenerationRequests || []).filter(r => !knownIds.has(r.id) && ['UNCERTAIN', 'LOCAL_PENDING'].includes(r.status));
      this.conceptGenerationRequests = [...(result.requests || []), ...unknownLocal];
      if (reconcile) for (const request of this.conceptGenerationRequests.filter(item => item.status === 'UNCERTAIN')) {
        if (!knownIds.has(request.id)) { request.message = '服务尚未查到原请求；草稿保留，可用原编号核实收单。'; continue; }
        const result = await this.request(`/concept-references/${encodeURIComponent(request.id)}/reconcile`, { projectId, method: 'POST', token: true, body: {} });
        if (!this.selectionContextMatches(context)) return;
        Object.assign(request, result.request);
      }
      await this.loadVisualPlanningRecords();
      this.renderConceptReferenceResults();
    } catch (error) { if (this.selectionContextMatches(context) && reconcile) this.notify(`无法核实参考生成：${error.message}。原请求与草稿保留。`); }
    finally { if (this.selectionContextMatches(context)) this.scheduleConceptReferencePoll(); }
  }
  stopConceptReferencePoll() {
    if (this.conceptReferencePoll != null) this.timers.clearTimeout(this.conceptReferencePoll);
    this.conceptReferencePoll = null;
  }
  scheduleConceptReferencePoll() {
    this.stopConceptReferencePoll();
    if (this.destroyed || !this.projectId || (!(this.conceptGenerationRequests || []).some(item => ['QUEUED', 'RUNNING', 'LOCAL_PENDING', 'UNCERTAIN'].includes(item.status)) && !this.hasPendingImageWorkflow())) return;
    const context = this.captureSelectionContext();
    this.conceptReferencePoll = this.timers.setTimeout(() => {
      this.conceptReferencePoll = null;
      if (!this.selectionContextMatches(context) || this.destroyed) return;
      if (this.referenceGenerating) this.scheduleConceptReferencePoll();
      else this.loadConceptReferences();
    }, 4000);
    this.conceptReferencePoll?.unref?.();
  }
  async generateConceptReference() {
    const sourceText = $('#concept').value;
    if (!sourceText.trim()) return this.notify('请先写下原始想法。');
    return this.dispatchConceptReference({ requestId: crypto.randomUUID(), sourceText, interpretation: $('#concept-visual-interpretation')?.value || '', size: '1536x1024', quality: 'low' });
  }
  async dispatchConceptReference(request) {
    const projectId = this.projectId, context = this.captureSelectionContext();
    if (!projectId || this.referenceGenerating || this.visualProjectArchived()) return;
    if (this.hasPendingConceptGeneration()) return this.notify('此前生成尚未核实；请查看原请求，不会重复生成。');
    const operation = this.referenceGenerationOperation = {};
    this.referenceGenerating = true;
    const local = { id: request.requestId, projectId, request, status: 'LOCAL_PENDING', message: '请求已保留，正在等待服务收单；未知结果请核实原请求。' };
    this.conceptGenerationRequests ||= []; this.conceptGenerationRequests.push(local);
    this.renderConceptReferenceResults();
    try {
      if (await this.saveConceptDraft(projectId) !== true) {
        if (this.selectionContextMatches(context)) this.conceptGenerationRequests = this.conceptGenerationRequests.filter(item => item !== local);
        return this.notify('生成请求未能保存，尚未调用 ImageGen。请先恢复本地存储。');
      }
      if (!this.selectionContextMatches(context)) return;
      const result = await this.request('/concept-references', { projectId, method: 'POST', token: true, body: request });
      if (this.selectionContextMatches(context)) Object.assign(local, result.request);
    } catch (error) {
      if (this.selectionContextMatches(context)) {
        const rejected = Number.isInteger(error.status) && error.status >= 400 && error.status < 500;
        local.status = rejected ? 'FAILED' : 'UNCERTAIN'; local.message = rejected ? error.message : '响应尚未核实；请查看原请求，不要重复生成。'; this.notify(local.message);
        if ((error.body?.code === 'REFERENCE_SOURCE_STALE' || error.body?.error?.code === 'REFERENCE_SOURCE_STALE') && this.visualPlanning) this.visualPlanning.error = local.message;
      }
    } finally {
      if (this.referenceGenerationOperation === operation) { this.referenceGenerating = false; this.referenceGenerationOperation = null; }
      if (this.selectionContextMatches(context)) { await this.saveConceptDraft(projectId); this.renderConceptReferenceResults(); }
    }
  }
  async recoverConceptRequest(local) {
    const context = this.captureSelectionContext(), projectId = this.projectId;
    if (this.visualProjectArchived() || this.referenceGenerating || local.projectId !== projectId || !local.request || local.request.requestId !== local.id) return;
    const operation = this.referenceGenerationOperation = {};
    this.referenceGenerating = true; this.renderConceptReferenceResults();
    try {
      const result = await this.request('/concept-references', { projectId, method: 'POST', token: true, body: cloneValue(local.request) });
      if (this.selectionContextMatches(context)) Object.assign(local, result.request);
    } catch (error) { if (this.selectionContextMatches(context)) { local.status = Number.isInteger(error.status) && error.status >= 400 && error.status < 500 ? 'FAILED' : 'UNCERTAIN'; local.message = local.status === 'FAILED' ? error.message : '原请求结果仍待核实，原编号和原文保留。'; } }
    finally { if (this.referenceGenerationOperation === operation) { this.referenceGenerating = false; this.referenceGenerationOperation = null; } if (this.selectionContextMatches(context)) { await this.saveConceptDraft(projectId); this.renderConceptReferenceResults(); } }
  }
  renderConceptReferenceResults() {
    const root = $('#concept-generation-results');
    if (root) this.renderReferenceRequestCards(root);
    const button = $('#generate-concept-reference'); if (button) button.disabled = this.visualProjectArchived() || this.referenceGenerating || this.hasPendingConceptGeneration();
    const results = $('#proposal-visual-results'); if (results && this.visualPlanning?.open && this.visualPlanning?.projectId === this.projectId) this.renderReferenceRequestCards(results, this.proposal);
    const generate = $('#generate-proposal-reference'); if (generate) generate.disabled = this.visualReferenceGenerationBlocked();
    this.scheduleConceptReferencePoll();
  }
  async submitConcept(iterationText = '', isIteration = false, submissionFields = null, submissionOptions = {}) {
    const blocked = reason => {
      const outcome = this.submissionOutcome('blocked', { type: isIteration ? 'iteration.submit' : 'concept.submit', projectId: this.projectId, reason });
      this.lastSubmissionOutcome = outcome; this.notify(reason); return outcome;
    };
    const frozenReport = submissionOptions.reviewedReport || null;
    const submittedReferences = cloneValue(frozenReport?.visualReferences ?? this.referencePayload());
    const submittedAssetIds = (frozenReport?.assets ?? this.assets).map(asset => asset.id);
    if (submittedReferences.some(r => !r.intent?.trim())) return blocked('参考采纳用途尚未填写。');
    if (!this.readiness?.ready) return blocked('制作入口暂不可用；请先完成服务能力启动检查。');
    if (this.selectionBusy) return blocked('正在读取所选项目版本，请稍后再提交。');
    const selectedProject = this.projectId;
    if (this.conceptSubmissionInFlight?.projectId === selectedProject && this.conceptSubmissionInFlight?.selectionGeneration === this.selectionGeneration && this.conceptSubmissionInFlight?.type === (isIteration ? 'iteration.submit' : 'concept.submit')) {
      const type = isIteration ? 'iteration.submit' : 'concept.submit';
      const pending = this.pendingCommandRecord(type, selectedProject);
      const outcome = this.submissionOutcome('blocked', { type, projectId: selectedProject, commandId: this.conceptSubmissionInFlight.commandId || pending?.envelope?.commandId, reason: '本次提交仍在处理；请等待当前结果，未重复派发。' });
      this.lastSubmissionOutcome = outcome; return outcome;
    }
    const context = this.captureSelectionContext(), requestGeneration = ++this.conceptGeneration;
    if (selectedProject && !this.snapshotMatchesProject(selectedProject)) return blocked('所选项目的版本尚未读取成功；请刷新该项目后再提交。');
    if (selectedProject && !Number.isInteger(this.snapshot.publicationRevision)) return blocked('所选项目缺少有效发布版本号；没有提交提案。');
    const form = $('#concept-form'); const text = isIteration ? iterationText : $('#concept').value;
    const changeRequest = isIteration && selectedProject && this.objectsWorkflow()
      ? (frozenReport ? cloneValue(frozenReport.intent?.changeRequest) : this.buildChangeRequest()) : undefined;
    if (!text.trim() && !submittedReferences.some(r => r.intent.trim()) && !(changeRequest?.fields?.length || changeRequest?.feedback?.length || changeRequest?.operations?.length)) return blocked('先写下一个想法或调整目标。');
    const submittedIterationDraft = isIteration ? this.captureIterationSubmissionDraft(text, changeRequest, submissionFields) : null;
    const submittedConceptRaw = !isIteration ? $('#concept').value : '';
    const button = (isIteration ? $('#edit-form') : form).querySelector('[type="submit"]'); button.disabled = true;
    this.conceptSubmissionInFlight = { projectId: selectedProject, generation: requestGeneration, selectionGeneration: context.generation, type: isIteration ? 'iteration.submit' : 'concept.submit' };
    this.activity = isIteration ? '正在提交本轮对象调整和反馈' : '正在提交用户想法'; this.renderWorkflowStatus();
    let acceptedOutcome = null;
    try {
      const expectedPublicationRevision = selectedProject ? this.snapshot.publicationRevision : undefined;
    const requestBody = { text, ...(selectedProject ? { projectId: selectedProject } : {}), ...(expectedPublicationRevision != null ? { expectedPublicationRevision } : {}), assetIds: submittedAssetIds, visualReferences: submittedReferences, ...(!selectedProject ? { workflow: 'objects-v1' } : {}), ...(changeRequest ? { changeRequest: this.usesV1Commands(selectedProject) ? changeRequest : this.legacyChangeRequest(changeRequest) } : {}) };
      const response = this.usesV1Commands(selectedProject) || (isIteration && this.legacyIterationCommandsAvailable())
        ? await this.sendCommand(isIteration ? 'iteration.submit' : 'concept.submit', isIteration
          ? { text, assetRefs: submittedAssetIds, visualReferences: submittedReferences, targetObjectIds: changeRequest?.targetObjectIds || [], fields: changeRequest?.fields || [], feedback: this.ensureFeedbackIds(changeRequest?.feedback || []), operations: changeRequest?.operations || [] }
          : { text, assetRefs: submittedAssetIds, visualReferences: submittedReferences }, { projectId: selectedProject, expected: { preferencesRevision: this.sessionPreferences?.revision ?? 0, publicationRevision: expectedPublicationRevision, sourceCommit: this.snapshot?.sourceCommit ?? this.snapshot?.baseCommit ?? null } })
        : await this.request('/concepts', { method: 'POST', token: true, projectId: selectedProject, body: requestBody });
      if (!this.selectionContextMatches(context) || requestGeneration !== this.conceptGeneration) {
        const responseProposal = response.proposal || response;
        const stale = this.submissionOutcome('stale', { type: isIteration ? 'iteration.submit' : 'concept.submit', projectId: selectedProject, storeId: this.handshake?.storeId, commandId: response.__commandOutcome?.commandId || null, proposalId: responseProposal?.id || null, reason: '提交响应属于已切换的项目上下文；没有应用到当前项目。', priorStatus: response.__commandOutcome?.status === 'submitted' || responseProposal?.id ? 'submitted' : null });
        return stale;
      }
      const responseProposal = response.proposal || response;
      if (response.__commandOutcome?.status === 'submitted') acceptedOutcome = { ...response.__commandOutcome, status: 'submitted', proposalId: responseProposal?.id || response.__commandOutcome.proposalId || null };
      if (!responseProposal.id || !Number.isInteger(responseProposal.revision)) throw new Error('服务没有返回可核实身份的提案；提交结果待核实。');
      this.proposal = responseProposal;
      acceptedOutcome ||= this.submissionOutcome('submitted', { type: isIteration ? 'iteration.submit' : 'concept.submit', projectId: selectedProject, storeId: this.handshake?.storeId, proposalId: this.proposal.id, reason: '服务已返回身份与修订号匹配的提案。' });
      acceptedOutcome.proposalRevision = this.proposal.revision;
      acceptedOutcome.publicationRevision = this.snapshot?.publicationRevision ?? null;
      acceptedOutcome.hasPostSubmitEdits = false;
      this.lastSubmissionOutcome = acceptedOutcome;
      this.packet = null;
      this.activity = null; this.renderProposal();
      if (!isIteration) {
        this.assets = this.assets.filter(asset => !submittedAssetIds.includes(asset.id) || !sameValue(this.referenceIntents[asset.id], submittedReferences.find(r => r.assetId === asset.id)));
        for (const [key, value] of Object.entries(this.referenceIntents)) if (submittedReferences.some(r => sameValue(r, value))) delete this.referenceIntents[key];
        this.renderAssets();
        if ($('#concept').value === submittedConceptRaw) $('#concept').value = '';
        acceptedOutcome.hasPostSubmitEdits = !!($('#concept').value || this.assets.length || this.referencePayload().length);
        if (acceptedOutcome.hasPostSubmitEdits) await this.saveConceptDraft(selectedProject);
        else await this.deleteConceptDraft(selectedProject);
      }
      else if (submittedIterationDraft) { acceptedOutcome.hasPostSubmitEdits = this.clearSubmittedIterationDraft(submittedIterationDraft); await this.saveDraft(); }
      $('#proposal-panel').scrollIntoView?.({ behavior: 'smooth', block: 'start' });
      this.startProposalPolling();
      this.lastSubmissionOutcome = acceptedOutcome;
      if (acceptedOutcome.hasPostSubmitEdits) acceptedOutcome.reason = '本轮已接收；提交期间新增或修改的草稿仍保留在编辑区。';
      return acceptedOutcome;
    } catch (error) {
      const outcome = acceptedOutcome
        ? { ...acceptedOutcome, status: 'submitted', reason: `服务已确认接收本轮；本地草稿清理或页面更新失败：${error.message}` }
        : error.commandOutcome || this.submissionOutcome(error.status === 409 ? 'stale'
          : [401, 403].includes(error.status) ? 'blocked'
            : Number.isInteger(error.status) && error.status >= 400 && error.status < 500 ? 'rejected'
              : 'unknown', { type: isIteration ? 'iteration.submit' : 'concept.submit', projectId: selectedProject, storeId: this.handshake?.storeId, reason: error.message || '提交没有返回可核实结果。' });
      if (this.selectionContextMatches(context) && requestGeneration === this.conceptGeneration) {
        this.lastSubmissionOutcome = outcome;
        this.activity = outcome.status === 'unknown' ? '提交结果待核实' : null;
        this.notify(outcome.status === 'submitted' ? `提案已接收：${outcome.reason}` : `提案${outcome.status === 'blocked' ? '未发送' : outcome.status === 'rejected' ? '被拒绝' : outcome.status === 'stale' ? '因版本变化未确认' : '结果待核实'}：${outcome.reason}`);
      }
      return outcome;
    }
    finally {
      if (this.conceptSubmissionInFlight?.generation === requestGeneration) this.conceptSubmissionInFlight = null;
      if (this.selectionContextMatches(context) && requestGeneration === this.conceptGeneration) {
        button.disabled = false;
        if (this.activity === '正在提交用户想法' || this.activity === '正在提交本轮对象调整和反馈') this.activity = null;
        this.renderWorkflowStatus();
      }
    }
  }
  captureIterationSubmissionDraft(text, changeRequest, submissionFields) {
    this.captureVisibleFields();
    const targetNotes = {};
    const feedbackIds = new Set((changeRequest?.feedback || []).map(item => item.feedbackId).filter(Boolean));
    for (const [key, note] of Object.entries(this.targetNotes || {})) {
      if (feedbackIds.has(note?.feedbackId)) targetNotes[key] = cloneValue(note);
    }
    const operations = [];
    const operationIds = new Set((changeRequest?.operations || []).map(item => item.operationId).filter(Boolean));
    for (const item of this.structuralProposals || []) {
      if (operationIds.has(item?.operationId || item?.proposalId)) operations.push(cloneValue(item));
    }
    const submittedFeedbackIds = new Set((changeRequest?.feedback || []).map(item => item.feedbackId).filter(Boolean));
    const feedback = (this.feedback || [])
      .filter(item => submittedFeedbackIds.has(item?.feedbackId))
      .map(item => cloneValue(item));
    const fields = Array.isArray(changeRequest?.fields)
      ? changeRequest.fields.map(field => ({ id: `${field.objectId}.${field.fieldId}`, objectId: field.objectId, fieldId: field.fieldId, value: cloneValue(field.value) }))
      : Object.entries(submissionFields || {}).map(([fieldId, value]) => {
        const control = this.parameterInput(fieldId);
        return { id: control?.dataset.fieldId || fieldId, objectId: control?.dataset.objectId || null, fieldId, value: cloneValue(value) };
      });
    const editorText = String($('#edit-text')?.value || '');
    const objectScoped = this.objectsWorkflow();
    const submittedText = String(text || '').trim();
    return {
      fields, targetNotes, feedback, operations, editorText, submittedText,
      projectId: this.projectId || null, publicationRevision: this.snapshot?.publicationRevision ?? null,
      sourceCommit: this.snapshot?.sourceCommit || this.snapshot?.baseCommit || null,
      objectScoped,
      editorTextSubmitted: !objectScoped && !!editorText.trim() && submittedText.startsWith(editorText.trim()),
    };
  }
  clearSubmittedIterationDraft(submitted) {
    if (submitted?.projectId !== (this.projectId || null) || Number(submitted?.publicationRevision) !== Number(this.snapshot?.publicationRevision) || (submitted?.sourceCommit || null) !== (this.snapshot?.sourceCommit || this.snapshot?.baseCommit || null)) return true;
    if (this.objectsWorkflow()) this.legacyWorkbench.persistCurrentNote();
    this.captureVisibleFields();
    const editor = $('#edit-text');
    const editorHasNewText = submitted.editorTextSubmitted && !!String(editor?.value || '').trim() && editor?.value !== submitted.editorText;
    for (const field of submitted.fields) {
      if (!Object.hasOwn(this.fieldDraftValues, field.id) || !sameValue(this.fieldDraftValues[field.id], field.value)) continue;
      const control = [...($('#dynamic-fields')?.querySelectorAll('[data-capability-id]:not([data-axis])') || [])].find(item => item.dataset.fieldId === field.id);
      if (control && !sameValue(this.readControlValue(control), field.value)) continue;
      delete this.fieldDraftValues[field.id]; this.dirtyFields.delete(field.id);
      if (control) {
        const cap = this.allCapabilities().find(item => {
          const parts = this.splitCapability(item);
          return `${parts.objectId}.${parts.fieldId}` === field.id || parts.fieldId === field.fieldId && !field.objectId;
        });
        const object = field.objectId ? this.objectItems().find(item => item.id === field.objectId) : null;
        const baseValue = cap && object ? this.capabilityValue(cap, object) : this.snapshot?.decisions?.[field.fieldId];
        this.writeControlValue(control, baseValue == null ? '' : baseValue);
      }
    }
    let notesChanged = false;
    const currentTargetKey = this.legacyWorkbench.targetKey();
    for (const [key, note] of Object.entries(submitted.targetNotes)) {
      if (!Object.hasOwn(this.targetNotes, key) || !sameValue(this.targetNotes[key], note)) continue;
      delete this.targetNotes[key]; notesChanged = true;
      if (key === currentTargetKey && editor?.value === note.text) editor.value = '';
    }
    let feedbackChanged = false;
    const pendingFeedback = [...submitted.feedback];
    if (pendingFeedback.length) {
      this.feedback = (this.feedback || []).filter(item => {
        const index = pendingFeedback.findIndex(feedback => feedback.feedbackId === item?.feedbackId && sameValue(feedback, item));
        if (index < 0) return true;
        pendingFeedback.splice(index, 1); feedbackChanged = true; return false;
      });
      if (feedbackChanged) this.renderFeedback();
    }
    const pendingOperations = [...submitted.operations];
    if (pendingOperations.length) {
      this.structuralProposals = (this.structuralProposals || []).filter(item => {
        const index = pendingOperations.findIndex(operation => sameValue(item, operation));
        if (index < 0) return true;
        pendingOperations.splice(index, 1); return false;
      });
    }
    if (submitted.editorTextSubmitted && editor?.value === submitted.editorText) editor.value = '';
    if (notesChanged || feedbackChanged || pendingOperations.length !== submitted.operations.length) this.legacyWorkbench.render();
    const submittedFieldIds = new Set(submitted.fields.map(field => field.id));
    const submittedNoteIds = new Set(Object.keys(submitted.targetNotes));
    const submittedFeedbackIds = new Set(submitted.feedback.map(item => item.feedbackId));
    const submittedOperationIds = new Set(submitted.operations.map(item => item.operationId || item.proposalId));
    const changedFieldRemains = submitted.fields.some(field => Object.hasOwn(this.fieldDraftValues, field.id) && !sameValue(this.fieldDraftValues[field.id], field.value))
      || Object.keys(this.fieldDraftValues || {}).some(id => !submittedFieldIds.has(id));
    const changedNoteRemains = Object.entries(this.targetNotes || {}).some(([key, note]) => String(note?.text || '').trim() && (!submittedNoteIds.has(key) || !sameValue(note, submitted.targetNotes[key])));
    const changedFeedbackRemains = (this.feedback || []).some(item => String(item?.message || '').trim() && (!submittedFeedbackIds.has(item.feedbackId) || !submitted.feedback.some(prior => prior.feedbackId === item.feedbackId && sameValue(prior, item))));
    const changedOperationRemains = (this.structuralProposals || []).some(item => !submittedOperationIds.has(item.operationId || item.proposalId) || !submitted.operations.some(prior => sameValue(prior, item)));
    const changedTextRemains = editorHasNewText;
    return !!(changedFieldRemains || changedNoteRemains || changedFeedbackRemains || changedOperationRemains || changedTextRemains
      || Object.values(this.feedbackInputs || {}).some(item => String(item?.message || '').trim())
      || String(this.legacyUnboundFeedback?.message || '').trim());
  }
  objectsWorkflow() { return this.workflow === 'objects-v1' || this.proposal?.workflow === 'objects-v1' || this.snapshot?.workflow === 'objects-v1'; }
  startProposalPolling() {
    this.stopProposalPolling();
    if (!this.proposal?.id || !PLANNING.has(this.proposal.status)) return;
    if (this.protocolVersion && this.streamFresh) return;
    const id = this.proposal.id, projectId = this.proposal.projectId || this.projectId, generation = ++this.proposalGeneration;
    this.proposalPollHandle = this.timers.setInterval(async () => {
      if (this.destroyed || generation !== this.proposalGeneration || this.proposal?.id !== id) return;
      if (this.proposalReadInFlight) return;
      try {
        this.proposalReadInFlight = this.request(`/proposals/${encodeURIComponent(id)}`, { projectId });
        const response = await this.proposalReadInFlight;
        const latest = response.proposal || response;
        if (generation !== this.proposalGeneration || this.proposal?.id !== id || latest.id !== id) return;
        if (Number(latest.revision) < Number(this.proposal.revision)) return;
        this.activity = null; this.proposal = latest; this.renderProposal();
      } catch (error) {
        if (generation === this.proposalGeneration) { this.renderPlanningStatus(this.proposal, `暂时无法读取策划进度：${error.message}`); this.activity = '策划状态未确认'; this.renderWorkflowStatus(); }
      } finally { this.proposalReadInFlight = null; }
    }, this.protocolVersion ? 10000 : 2000);
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
      PLANNER_BUDGET: '策划达到本次用量上限。',
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
    const retryAt = Date.parse(failure.retryNotBefore);
    if (Number.isFinite(retryAt) && retryAt > Date.now()) section.append(el('p', '', `执行器失败后正在冷却，约 ${Math.ceil((retryAt - Date.now()) / 1000)} 秒后可重试；不会自动重复创建 session。`));
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
    const retryAt = Date.parse(proposal.planningFailure.retryNotBefore);
    if (Number.isFinite(retryAt) && retryAt > Date.now()) return this.notify(`执行器仍在冷却，请约 ${Math.ceil((retryAt - Date.now()) / 1000)} 秒后重试；原输入已保留。`);
    const context = this.captureSelectionContext(), generation = ++this.conceptGeneration;
    if (!this.proposalBelongsToSelection(proposal, context) || !proposal.projectId || !Number.isInteger(proposal.publicationRevision)) return this.notify('无法确认原项目版本；请刷新工作区后重试。');
    if (this.snapshot?.projectId !== proposal.projectId && this.snapshot?.id !== proposal.projectId) return this.notify('原项目尚未选中；请先选择该项目再重试。');
    const sourceCommit = this.snapshot?.sourceCommit ?? this.snapshot?.baseCommit ?? null;
    if (this.usesV1Commands(proposal.projectId) && (this.snapshot?.publicationRevision !== proposal.publicationRevision || sourceCommit !== (proposal.baseCommit ?? null))) return this.notify('原方案的发布或 Git 基线已变化；请刷新后重新审阅，未重试策划。');
    button.disabled = true; this.activity = '正在重新请求策划反馈'; this.renderWorkflowStatus();
    try {
      const body = {
        text: this.recoveryRequestText(proposal), projectId: proposal.projectId,
        workflow: proposal.workflow || (this.objectsWorkflow() ? 'objects-v1' : undefined),
        expectedPublicationRevision: proposal.publicationRevision,
        assetIds: Array.isArray(proposal.assets) ? proposal.assets.map(asset => typeof asset === 'string' ? asset : asset?.id).filter(id => typeof id === 'string' && id) : Array.isArray(proposal.assetIds) ? [...proposal.assetIds] : [],
        ...(proposal.changeRequest ? { changeRequest: this.usesV1Commands(proposal.projectId) ? structuredClone(proposal.changeRequest) : this.legacyChangeRequest(proposal.changeRequest) } : {}),
      };
      const response = this.usesV1Commands(proposal.projectId)
        ? await this.sendCommand(proposal.changeRequest ? 'iteration.submit' : 'concept.submit', proposal.changeRequest
          ? { text: body.text, assetRefs: body.assetIds, ...(proposal.visualReferences ? { visualReferences: cloneValue(proposal.visualReferences) } : {}), targetObjectIds: proposal.changeRequest.targetObjectIds || [], fields: proposal.changeRequest.fields || [], feedback: this.ensureFeedbackIds(proposal.changeRequest.feedback || []) }
          : { text: body.text, assetRefs: body.assetIds, ...(proposal.visualReferences ? { visualReferences: cloneValue(proposal.visualReferences) } : {}) }, { projectId: proposal.projectId, expected: { preferencesRevision: this.sessionPreferences?.revision ?? 0, publicationRevision: proposal.publicationRevision, sourceCommit } })
        : await this.request('/concepts', { method: 'POST', token: true, body });
      const latest = response.proposal || response;
      if (!this.selectionContextMatches(context) || generation !== this.conceptGeneration || this.proposal?.id !== proposal.id) return;
      if (!latest.id || !Number.isInteger(latest.revision) || latest.id === proposal.id) throw new Error('服务没有创建新的策划修订。');
      this.proposal = latest; this.packet = null; this.activity = null; this.renderProposal(); this.startProposalPolling();
    } catch (error) {
      if (this.selectionContextMatches(context) && generation === this.conceptGeneration && this.proposal?.id === proposal.id) {
        const outcomeUnknown = !Number.isInteger(error.status) || error.status >= 500;
        this.activity = outcomeUnknown ? '策划重试结果待核实' : null; this.renderWorkflowStatus();
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
    this.activity = action === 'cancel' ? '正在请求停止策划' : '正在核实策划状态'; this.renderWorkflowStatus();
    try {
      let response;
      if (this.usesV1Commands(proposal.projectId) && !clarificationRecovery) {
        const attemptId = proposal.attemptId;
        if (!attemptId) throw new Error('方案没有公开对应的执行代次；没有发送取消或对账命令。');
        const ownerRef = { kind: 'proposal', id: proposal.id, revision: proposal.revision };
        await this.sendCommand(action === 'cancel' ? 'execution.cancel' : 'execution.reconcile', { ownerRef, attemptId });
        if (!this.selectionContextMatches(context) || generation !== this.proposalMutationGeneration) return;
        this.activity = null;
        await this.refresh();
        return;
      }
      // Recovering a timed-out clarification still requires the backend's
      // dedicated evidence/file-integrity checks; the v1 execution command
      // only reconciles attempt ownership and cannot restore planner output.
      response = await this.request(`/proposals/${encodeURIComponent(proposal.id)}/${action}`, { method: 'POST', token: true, body: {} });
      const latest = response.proposal || response;
      if (this.selectionContextMatches(context) && generation === this.proposalMutationGeneration && this.proposal?.id === proposal.id && latest.id === proposal.id && Number(latest.revision) >= Number(proposal.revision)) {
        this.activity = null; this.proposal = latest; this.renderProposal();
        if (existingAnswers && latest.status === 'NEEDS_CLARIFICATION') for (const control of $('#questions')?.querySelectorAll('[name]') || []) if (Object.hasOwn(existingAnswers, control.name)) control.value = existingAnswers[control.name];
      }
    } catch (error) { if (this.selectionContextMatches(context) && generation === this.proposalMutationGeneration && this.proposal?.id === proposal.id) { this.activity = '策划状态未确认'; this.notify(`策划${action === 'cancel' ? '取消' : '对账'}未确认：${error.message}`); this.renderWorkflowStatus(); } }
  }
  objectDocument(proposal = this.proposal) { return proposal?.document || proposal?.designDocument || proposal?.objectDocument || null; }
  objectItems(source = this.snapshot) { const catalog = source?.catalog || {}; const document = source?.document || source?.objectDocument || {}; return catalog.objects || document.objects || source?.objects || []; }
  feedbackDescription(item, objects = []) {
    const target = objects.find(object => object.id === item.objectId);
    return `${target?.name || item.objectId || '项目'} · ${this.legacyWorkbench.feedbackCategoryLabel(item.category)}：${item.message || item.text || ''}`;
  }
  clarificationValueLabel(question, value, { textOnly = false } = {}) {
    if (question?.type === 'boolean' && [true, false, 'true', 'false'].includes(value)) return value === true || value === 'true' ? '是' : '否';
    if (question?.type === 'choice') {
      const options = question.options || [];
      const optionValue = option => option && typeof option === 'object' ? option.value : option;
      const exact = options.find(option => sameValue(optionValue(option), value));
      const compatible = options.filter(option => String(optionValue(option)) === String(value));
      if (textOnly && compatible.length > 1) return `${String(value)}（多个选项使用相同存档值，无法确认选项说明）`;
      const option = exact ?? (compatible.length === 1 ? compatible[0] : undefined);
      if (option !== undefined) return String(option && typeof option === 'object' ? option.label ?? option.value : option);
      return `${String(value)}（未找到对应的选项说明）`;
    }
    return String(value);
  }
  discussionRequestTexts(source) {
    const approved = source.approvedProposal || source;
    const discussion = Array.isArray(approved.discussion) && approved.discussion.length ? approved.discussion : source.userDiscussion || [];
    const questions = new Map(), texts = [];
    for (const turn of discussion) {
      if (turn.role !== 'user') {
        for (const question of turn.questions || []) questions.set(question.id, question);
        continue;
      }
      if (typeof turn.text === 'string' && turn.text.trim()) texts.push(turn.text);
      const answers = Array.isArray(turn.answers) ? turn.answers : Object.entries(turn.answers || {}).map(([questionId, value]) => ({ questionId, value }));
      for (const answer of answers) {
        const value = answer.text ?? answer.value ?? answer.answer;
        if (value == null || !String(value).trim()) continue;
        const id = answer.questionId || answer.id || '问题', question = questions.get(id);
        texts.push(`补充回答：${question?.prompt || `问题 ${id}（未保留问题说明）`}\n${question?.type === 'choice' ? '选择' : '回答'}：${this.clarificationValueLabel(question, value, { textOnly: answer.text != null })}`);
      }
    }
    return texts;
  }
  recoveryRequestText(source) {
    return this.discussionRequestTexts(source).join('\n\n') || source.approvedProposal?.text || source.userText || source.text || '';
  }
  storedQuestionLabel(record, questionId, value) {
    return record.questionLabels?.[questionId] ?? `${String(value)}（旧记录未保留显示说明）`;
  }
  renderObjectsProposal(root, proposal, { collapsible = false } = {}) {
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
    const feedbackDecisions = proposal.feedbackDecisions || document.feedbackDecisions || [];
    if (feedbackDecisions.length) { section.append(el('h4', '', '逐条反馈处理决定')); const list = el('ul', 'requirement-list'); for (const item of feedbackDecisions) list.append(el('li', '', `${item.feedbackId} · ${this.legacyWorkbench.planDecisionStatus(item.status || item.disposition || '未说明')}${item.reason ? `：${item.reason}` : ''}${item.taskIds?.length ? ` · 任务 ${item.taskIds.join('、')}` : ''}${item.requirementIds?.length ? ` · 验收 ${item.requirementIds.join('、')}` : ''}`)); section.append(list); }
    if (proposal.changeRequest?.targetObjectIds?.length) section.append(el('p', 'meta-line', `本轮对象：${proposal.changeRequest.targetObjectIds.join('、')}`));
    if (proposal.changeRequest?.fields?.length) { section.append(el('h4', '', '属性修改')); const list = el('ul', 'requirement-list'); for (const field of proposal.changeRequest.fields) list.append(el('li', '', `${field.objectId}.${field.fieldId} → ${JSON.stringify(field.value)}`)); section.append(list); }
    if (proposal.changeRequest?.feedback?.length) { section.append(el('h4', '', '本轮反馈')); const list = el('ul', 'requirement-list'); for (const item of proposal.changeRequest.feedback) list.append(el('li', '', this.feedbackDescription(item, objects))); section.append(list); }
    const diff = proposal.objectDiff || proposal.objectChanges || proposal.diff?.objects || document.objectDiff; if (diff) { section.append(el('h4', '', '对象差异')); section.append(el('pre', 'object-diff', typeof diff === 'string' ? diff : JSON.stringify(diff, null, 2))); }
    if (collapsible) {
      const tasks = proposal.tasks || document.tasks || [], requirements = proposal.requirements || document.requirements || [];
      const summary = el('summary', '', `展开完整对象计划 · ${Array.isArray(document.objects) ? document.objects.length : 0} 个对象 · ${tasks.length} 项任务 · ${requirements.length} 项需求与验证`);
      const details = el('details', 'object-plan-details'); details.append(summary, section); root.append(details);
    } else root.append(section);
  }
  renderProposal() {
    const proposal = this.proposal; if (!proposal) return;
    const freezing = this.freezingProposal?.projectId === proposal.projectId && this.freezingProposal?.id === proposal.id && this.freezingProposal?.revision === proposal.revision;
    $('#freeze').textContent = freezing ? '正在冻结方案…' : '确认方案并继续';
    const iterationProposal = this.isIterationProposal(proposal);
    hide($('#planning-status'));
    $('#review-label').textContent = this.workspace?.testData ? '我已阅读并确认本次测试方案和制作范围' : '我已阅读并确认上面的方案和制作范围';
    hide($('#proposal-panel'), false); $('#proposal-title').textContent = PLANNING.has(proposal.status) ? (iterationProposal ? '本轮调整讨论' : '初始想法讨论') : proposal.status === 'NEEDS_CLARIFICATION' ? '需要你补充的信息' : proposal.title || (iterationProposal ? '本轮调整方案' : '初步方案');
    const proposalStatusLabel = proposal.status === 'FAILED' ? '策划失败' : proposal.status === 'READY' ? '方案待确认' : proposal.status === 'NEEDS_CLARIFICATION' ? '需要补充信息' : proposal.status === 'FROZEN' ? '已冻结，沿用原制作表单' : JOB_LABELS[proposal.status] || `服务状态：${proposal.status || '未知'}`;
    setStatus($('#proposal-status'), proposal.status, proposalStatusLabel);
    const area = $('#proposal-content'); area.replaceChildren();
    const changeRequest = iterationProposal ? proposal.changeRequest : null;
    const showSubmittedChange = !!changeRequest && ['PLANNING', 'PLANNING_CANCELLING', 'PLANNING_UNCERTAIN', 'NEEDS_CLARIFICATION', 'FAILED', 'BLOCKED', 'CANCELLED'].includes(proposal.status);
    const hasSubmittedChange = showSubmittedChange && (changeRequest.targetObjectIds?.length || changeRequest.fields?.length || changeRequest.feedback?.length || changeRequest.operations?.length);
    if (proposal.text || hasSubmittedChange) {
      const block = el('section', 'role-block user-info'); block.append(el('h3', '', iterationProposal ? '用户本轮调整' : '用户原始想法'));
      if (proposal.text) block.append(el('p', 'proposal-summary', proposal.text));
      if (hasSubmittedChange) {
        if (changeRequest.targetObjectIds?.length) block.append(el('p', 'meta-line', `本轮对象：${changeRequest.targetObjectIds.join('、')}`));
        const items = [];
        for (const field of changeRequest.fields || []) items.push(`${field.objectId}.${field.fieldId} → ${JSON.stringify(field.value)}`);
        for (const item of changeRequest.feedback || []) items.push(this.feedbackDescription(item, this.objectItems()));
        for (const operation of changeRequest.operations || []) items.push(`结构提案 · ${this.legacyWorkbench.operationLabel(operation)}`);
        if (items.length) { const list = el('ul', 'requirement-list'); for (const item of items) list.append(el('li', '', item)); block.append(list); }
      }
      area.append(block);
    }
    if (PLANNING.has(proposal.status)) {
      area.append(el('p', 'muted', 'AI 策划正在梳理需求；可以检查上次反馈与已有参考。'));
      const previous = [...(proposal.discussion || [])].reverse().find(item => item.role === 'planner');
      if (previous?.summary) area.append(el('p', 'proposal-summary', `上次策划反馈：${previous.summary}`));
    }
    else {
      const aiSummary = proposal.aiSummary || proposal.summary || proposal.document?.summary || proposal.designDocument?.summary;
      if (aiSummary) { const block = el('section', 'role-block ai-info'); block.append(el('h3', '', 'AI 策划反馈')); block.append(el('p', 'proposal-summary', aiSummary)); area.append(block); }
    }
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
    if ((proposal.workflow === 'objects-v1' || this.objectsWorkflow()) && ['READY', 'BLOCKED'].includes(proposal.status)) {
      const hasBoundReviewedPlan = proposal.status === 'READY' && this.usesV1Commands(proposal.projectId) && proposal.reviewedPlanRef;
      if (hasBoundReviewedPlan) {
        const hint = el('p', 'muted reviewed-plan-hint', '完整审阅计划按需展开查看。读取成功前，制作确认保持不可用。'); hint.dataset.reviewedPlanHint = 'true'; area.append(hint);
      } else this.renderObjectsProposal(area, proposal, { collapsible: true });
    }
    const requirements = proposal.requirements || proposal.document?.requirements || []; if (requirements.length && proposal.workflow !== 'objects-v1' && !this.objectsWorkflow()) { const heading = el('h3', '', '本轮目标'); const list = el('ul', 'requirement-list'); for (const req of requirements) list.append(el('li', '', typeof req === 'string' ? req : req.text || req.title || JSON.stringify(req))); area.append(heading, list); }
    const questions = proposal.questions || [];
    const ask = $('#answers-form'); const freeze = $('#freeze-area');
    if (PLANNING.has(proposal.status) || proposal.status === 'PLANNING_UNCERTAIN') { hide(ask); hide(freeze); this.renderPlanningStatus(proposal); this.startProposalPolling(); }
    else if (proposal.status === 'FROZEN') { this.stopProposalPolling(); hide(ask); hide(freeze); $('#reviewed').checked = false; $('#reviewed').disabled = true; $('#freeze').disabled = true; hide($('#resume-packet'), true); if (this.usesV1Commands(proposal.projectId) && proposal.reviewedPlanRef) this.loadReviewedPlan(proposal).catch(error => this.notify(`冻结计划未能读取：${error.message}`)); }
    else if (proposal.status === 'NEEDS_CLARIFICATION' || questions.length) { this.stopProposalPolling(); this.renderQuestions(questions); this.renderPlanningRecovery(proposal, area); hide(ask, false); hide(freeze); $('#reviewed').disabled = false; $('#freeze').disabled = true; }
    else if (proposal.status === 'READY') { this.stopProposalPolling(); hide(ask); this.renderPacketPreview(proposal); this.renderReadyRevision(proposal, area); hide(freeze, false); $('#reviewed').checked = false; $('#reviewed').disabled = false; $('#freeze').disabled = true; if (this.usesV1Commands(proposal.projectId)) this.loadReviewedPlan(proposal).catch(error => this.notify(`完整审阅计划未能读取：${error.message}`)); }
    else if (['FAILED', 'CANCELLED', 'BLOCKED'].includes(proposal.status)) { this.stopProposalPolling(); hide(ask); hide(freeze); area.append(el('div', 'notice', proposal.status === 'FAILED' && proposal.planningFailure ? (proposal.planningFailure.code === 'PLANNER_SETUP' ? '策划 session 尚未启动。' : '策划 session 未能完成。') : proposal.message || `策划状态：${proposal.status}`)); if (proposal.status === 'FAILED') this.renderPlanningFailure(proposal, area); this.renderPlanningControls(proposal); }
    else { this.stopProposalPolling(); hide(ask); hide(freeze); area.append(el('p', 'muted', `当前方案状态为 ${proposal.status || '未知'}，服务未声明可以确认。`)); }
    this.renderVisualPlanningEntry(proposal, area);
    this.renderWorkflowStages(); this.renderWorkflowStatus();
  }
  parameterInput(key) { return $(`#edit-form [name="${key}"]`); }
  proposalRevisionDraft(proposal = this.proposal, create = false) {
    const projectId = proposal?.projectId || this.projectId;
    if (!proposal?.id || !projectId || projectId !== this.projectId || !Number.isInteger(Number(proposal.revision))) return null;
    this.proposalInputs ||= {};
    let revisions = this.proposalInputs[proposal.id];
    if (!revisions && create) revisions = this.proposalInputs[proposal.id] = {};
    if (!revisions || typeof revisions !== 'object' || Array.isArray(revisions)) return null;
    const revision = String(proposal.revision);
    let record = revisions[revision];
    if (!record && create) record = revisions[revision] = { questions: {}, questionPrompts: {}, readySupplement: '' };
    if (!record || typeof record !== 'object' || Array.isArray(record)) return null;
    if (!record.questions || typeof record.questions !== 'object' || Array.isArray(record.questions)) record.questions = {};
    if (!record.questionPrompts || typeof record.questionPrompts !== 'object' || Array.isArray(record.questionPrompts)) record.questionPrompts = {};
    if (!record.questionLabels || typeof record.questionLabels !== 'object' || Array.isArray(record.questionLabels)) record.questionLabels = {};
    return record;
  }
  persistProposalInputs() {
    if (!this.projectId) return;
    this.queueConceptDraftSave();
    this.queueDraftSave();
  }
  saveProposalQuestionInput(questionId, value) {
    const proposal = this.proposal, record = this.proposalRevisionDraft(proposal, true);
    if (!record || typeof questionId !== 'string' || !questionId) return;
    const question = (proposal.questions || []).find(item => item.id === questionId);
    record.questions[questionId] = String(value ?? '');
    if (question?.prompt) record.questionPrompts[questionId] = String(question.prompt);
    const control = [...($('#questions')?.querySelectorAll('[name]') || [])].find(item => item.name === questionId);
    const actualValue = question?.type === 'choice' && control ? this.readChoiceValue(control) : value;
    if (value !== '') record.questionLabels[questionId] = this.clarificationValueLabel(question, actualValue);
    else delete record.questionLabels[questionId];
    this.persistProposalInputs();
  }
  saveReadySupplementInput(value) {
    const record = this.proposalRevisionDraft(this.proposal, true);
    if (!record) return;
    record.readySupplement = String(value ?? '');
    this.persistProposalInputs();
  }
  renderPriorProposalInputs(proposal, root, { includeQuestions = true, includeSupplement = true, includeReferences = false } = {}) {
    const revisions = this.proposalInputs?.[proposal?.id];
    if (!revisions || typeof revisions !== 'object') return;
    const prior = Object.entries(revisions).filter(([revision, record]) => Number(revision) < Number(proposal.revision) && record && typeof record === 'object')
      .sort((a, b) => Number(a[0]) - Number(b[0]));
    const populated = prior.map(([revision, record]) => {
      const questions = Object.entries(record.questions || {}).filter(([, value]) => String(value ?? '').trim());
      const supplement = String(record.readySupplement || '').trim();
      return { revision, record, questions, supplement, references: Array.isArray(record.visualReferences) ? record.visualReferences : null };
    }).filter(item => (includeQuestions && item.questions.length) || (includeSupplement && item.supplement) || (includeReferences && item.references));
    if (!populated.length) return;
    const details = el('details', 'prior-proposal-inputs'); details.append(el('summary', '', '查看此前修订保留的文字（仅供核对，不会带入当前修订）'));
    for (const item of populated) {
      const section = el('section', 'prior-proposal-revision'); section.append(el('h4', '', `方案修订 r${item.revision}`));
      if (includeQuestions) for (const [questionId, value] of item.questions) {
        const prompt = item.record.questionPrompts?.[questionId] || questionId;
        section.append(el('p', '', `${prompt}：${this.storedQuestionLabel(item.record, questionId, value)}`));
      }
      if (includeSupplement && item.supplement) section.append(el('p', '', `READY 补充：${item.supplement}`));
      if (includeReferences && item.references) {
        const assets = [...(proposal.assets || []), ...(this.conceptGenerationRequests || []).filter(r => r.projectId === this.projectId).map(r => r.asset).filter(Boolean)];
        mountVisual(section, { title: '此前修订参考草稿（只供核对，未带入当前修订）', references: referenceModel({ assets, visualReferences: item.references }, this.projectId), details: [{ label: '原方案修订', value: item.revision }] }, `prior-references:${this.projectId}:${proposal.id}:${item.revision}`);
      }
      details.append(section);
    }
    root.append(details);
  }
  renderReadyRevision(proposal, root) {
    if (!this.usesV1Commands(proposal?.projectId)) return;
    const area = el('section', 'ready-revision'); area.append(el('h3', '', '继续讨论或补充反馈'));
    area.append(el('p', 'muted', '继续讨论会创建新修订，当前 READY 方案随即失效；完整原方案由服务保留并纳入新修订审阅。'));
    const supplement = el('textarea'); supplement.id = 'ready-supplement'; supplement.rows = 3; supplement.maxLength = 3000; supplement.placeholder = '补充目标、范围或验收要求…';
    supplement.value = this.proposalRevisionDraft(proposal)?.readySupplement || '';
    supplement.addEventListener('input', () => this.saveReadySupplementInput(supplement.value));
    const revise = el('button', 'button secondary', '提交补充并继续讨论'); revise.type = 'button'; revise.addEventListener('click', () => this.reviseReadyProposal(proposal.id, supplement.value));
    area.append(supplement, revise); this.renderPriorProposalInputs(proposal, area, { includeQuestions: false, includeSupplement: true }); root.append(area);
  }
  renderReferenceRevisionEditor(root, proposal) {
    const record = this.proposalRevisionDraft(proposal);
    const editor = el('details', 'reference-revision-editor'); editor.append(el('summary', '', '修改本轮参考和采纳用途'));
    const references = cloneValue(record?.visualReferences ?? proposal.visualReferences ?? []);
    if (this.visualProjectArchived()) { root.append(el('p', 'muted', '归档项目只允许查看参考。')); return; }
    const persist = () => {
      const edited = this.proposalRevisionDraft(proposal, true); if (!edited) return;
      edited.visualReferences = cloneValue(references); this.persistProposalInputs(); this.updateReferenceDraftStatus();
    };
    const assets = new Map([...(proposal.assets || []), ...(this.conceptGenerationRequests || []).filter(r => r.projectId === this.projectId).map(r => r.asset).filter(Boolean)].map(a => [a.id, a]));
    const render = () => {
      editor.querySelectorAll('.reference-revision-row, .reference-revision-actions').forEach(node => node.remove());
      for (const reference of references) {
        const row = el('section', 'reference-revision-row reference-editor');
        row.append(el('p', 'muted', reference.assetId ? `本轮参考：${assets.get(reference.assetId)?.name || reference.assetId}` : '文字视觉要求（图片未选用）'));
        for (const [key, label] of [['intent', '采纳用途'], ['preserve', '需要保持'], ['unknown', '尚未确定']]) {
          const field = el('label', 'field-label', label), input = el('textarea'); input.rows = 2; input.maxLength = 2000; input.value = reference[key] || '';
          input.setAttribute('aria-label', `本轮参考 ${label}`); input.addEventListener('input', () => { reference[key] = input.value; persist(); }); field.append(input); row.append(field);
        }
        if (reference.assetId) {
          const cancel = el('button', 'button quiet', '取消此图片，保留文字要求'); cancel.type = 'button'; cancel.addEventListener('click', () => { reference.assetId = null; persist(); render(); }); row.append(cancel);
        }
        const remove = el('button', 'button quiet', '移除此要求'); remove.type = 'button'; remove.addEventListener('click', () => { references.splice(references.indexOf(reference), 1); persist(); render(); }); row.append(remove); editor.append(row);
      }
      const actions = el('div', 'reference-revision-actions');
      const select = el('select'); select.setAttribute('aria-label', '本轮替换或新增参考'); select.append(new Option('选择已生成的参考版本', ''));
      for (const asset of assets.values()) if (!references.some(r => r.assetId === asset.id)) select.append(new Option(`${asset.name || '参考图'} · ${asset.id}`, asset.id));
      select.addEventListener('change', () => { if (!select.value || references.filter(r => r.assetId).length >= 6 || references.length >= 12) return; references.push({ assetId: select.value, intent: '', targetObjectIds: [], preserve: '', unknown: '' }); persist(); render(); });
      const apply = el('button', 'button secondary', '提交参考变更，重新审阅方案'); apply.type = 'button'; apply.addEventListener('click', () => this.reviseVisualReferences(proposal, references, apply));
      apply.disabled = !this.canSubmitVisualRevision(proposal);
      const discard = el('button', 'button quiet', '撤销本轮参考草稿'); discard.type = 'button'; discard.addEventListener('click', () => { const draft = this.proposalRevisionDraft(proposal); if (draft) delete draft.visualReferences; this.persistProposalInputs(); this.renderVisualPlanningPanel(); this.updateReferenceDraftStatus(); });
      actions.append(select, el('p', 'muted', proposal.status === 'NEEDS_CLARIFICATION' ? '参考变更将与必答问题一起提交；请填写回答后点击提交回答。' : '只修改草稿不会改变已审阅或冻结方案。制作期间先保留草稿，后续经确认才创建新修订。'), apply, discard); editor.append(actions);
    };
    render(); root.append(editor);
  }
  async reviseVisualReferences(proposal, references, button) {
    if (button?.disabled) return;
    const current = this.proposal;
    if (!proposal || proposal.projectId !== this.projectId || current?.id !== proposal.id || current.revision !== proposal.revision || current.publicationRevision !== proposal.publicationRevision) {
      return this.notify('方案身份或修订已变化，请刷新后重新核对参考。');
    }
    if (!this.canSubmitVisualRevision(current)) return this.notify('当前方案不能安全创建新版修订。');
    if (!sameValue(references, this.proposalRevisionDraft(current)?.visualReferences ?? current.visualReferences ?? [])) {
      this.proposalRevisionDraft(current, true).visualReferences = cloneValue(references);
      this.persistProposalInputs();
    }
    return this.reviseReadyProposal(current.id, $('#ready-supplement')?.value ?? this.proposalRevisionDraft(current)?.readySupplement ?? '');
  }
  async loadReviewedPlan(proposal) {
    const ref = proposal?.reviewedPlanRef, projectId = proposal?.projectId || this.projectId;
    if (!ref || !projectId) throw new Error('公开方案没有绑定完整审阅计划编号。');
    if (this.reviewedPlan?.projectId === projectId && this.reviewedPlan?.reviewedPlanRef === ref && this.reviewedPlan?.plan?.id === proposal.id && this.reviewedPlan?.plan?.revision === proposal.revision) { this.renderReviewedPlan(this.reviewedPlan); return this.reviewedPlan; }
    if (this.reviewPlanLoad?.ref === ref) return this.reviewPlanLoad.promise;
    const proposalId = proposal.id, revision = proposal.revision, context = this.captureSelectionContext();
    const promise = (async () => {
      const result = await this.request(`/v1/projects/${encodeURIComponent(projectId)}/plans/${encodeURIComponent(ref)}`, { projectId: null });
      if (result.schemaVersion !== 'studio.message.v1' || result.kind !== 'reviewed_plan' || result.storeId !== this.handshake.storeId || result.projectId !== projectId || result.reviewedPlanRef !== ref || !result.plan || result.plan.id !== proposalId || result.plan.revision !== revision) throw new Error('完整审阅计划的项目、修订或资源身份不匹配。');
      if (!this.selectionContextMatches(context) || this.proposal?.id !== proposalId || this.proposal?.revision !== revision) return null;
      this.reviewedPlan = result; this.renderReviewedPlan(result);
      $('#freeze').disabled = this.proposal.status !== 'READY' || !$('#reviewed').checked || !this.readiness?.ready;
      return result;
    })();
    this.reviewPlanLoad = { ref, promise };
    try { return await promise; } finally { if (this.reviewPlanLoad?.promise === promise) this.reviewPlanLoad = null; }
  }
  renderReviewedPlan(result) {
    let section = $('#reviewed-plan-content');
    const frozen = this.proposal?.status === 'FROZEN';
    if (!section) {
      section = el('details', 'reviewed-plan'); section.id = 'reviewed-plan-content';
      section.open = frozen ? this.frozenPlanExpanded === result.reviewedPlanRef : this.reviewedPlanExpandedRef === result.reviewedPlanRef;
      section.addEventListener('toggle', () => {
        if (!section.isConnected) return;
        if (frozen) this.frozenPlanExpanded = section.open ? result.reviewedPlanRef : null;
        else if (section.open) this.reviewedPlanExpandedRef = result.reviewedPlanRef;
        else if (this.reviewedPlanExpandedRef === result.reviewedPlanRef) this.reviewedPlanExpandedRef = null;
      });
      $('#proposal-content').append(section);
    }
    releaseVisuals(section);
    section.replaceChildren(el('summary', '', frozen ? '查看已冻结的完整计划与图片' : `展开完整审阅计划 · ${result.reviewedPlanRef}`));
    $('[data-reviewed-plan-hint]')?.remove();
    const plan = result.plan;
    if (frozen) {
      const input = el('section', 'frozen-plan-input'), packet = this.packet;
      const packetIds = [packet?.id, packet?.packetId].filter(Boolean);
      const matches = packet && packet.projectId === plan.projectId && plan.projectId === this.projectId &&
        packet.proposalId === plan.id && packet.proposalRevision === plan.revision &&
        packetIds.length && packetIds.every(id => id === this.proposal.packetId) &&
        packet.reviewedPlanRef === result.reviewedPlanRef && packet.publicationRevision === plan.publicationRevision &&
        (packet.baseCommit ?? null) === (plan.baseCommit ?? null);
      section.append(input);
      if (matches) this.renderFrozenPacket(input, packet);
      else input.append(el('p', 'notice', '无法核对本计划绑定的冻结输入；图片与采纳用途尚未读取。请刷新状态后核对，当前草稿不会替代冻结内容。'));
    }
    const details = el('dl', 'packet-list');
    for (const [label, value] of [['项目/方案修订', `${plan.projectId} · ${plan.id} r${plan.revision}`], ['发布基线', plan.publicationRevision], ['Git 基线', plan.baseCommit || '无工程基线'], ['GM 规格引用', plan.gmSpecRef || '未声明'], ['ImageGen 素材包', JSON.stringify(plan.assetBundle || null)], ['源清单', JSON.stringify(plan.sourceRefs || {})], ['规格清单', JSON.stringify(plan.specInventory || {})], ['模板清单', JSON.stringify(plan.templateInventory || {})], ['反馈逐条决定', JSON.stringify(plan.feedbackDecisions || [])]]) details.append(el('dt', '', label), el('dd', '', String(value ?? '未提供')));
    const technical = el('details', 'reviewed-plan-technical');
    technical.append(el('summary', '', '查看方案身份与技术清单'), details);
    if (plan.assetBundle?.bundleId && Array.isArray(plan.assetBundle.paths)) {
      section.append(el('h4', '', '生成图片 · 视觉与运行效果待验收'));
      plan.assetBundle.paths.forEach((path, index) => {
        const figure = el('figure', 'generated-asset-preview'), img = el('img');
        img.src = `/api/v1/projects/${encodeURIComponent(plan.projectId)}/image-bundles/${encodeURIComponent(plan.assetBundle.bundleId)}/images/${index}`;
        img.alt = path; img.loading = 'lazy'; img.style.maxWidth = '100%';
        figure.append(img, el('figcaption', '', path)); section.append(figure);
      });
    }
    const content = { ...this.proposal, ...plan, document: plan.document || this.proposal.document };
    if (content.workflow === 'objects-v1' || this.objectsWorkflow()) this.renderObjectsProposal(section, content);
    else if (content.document) section.append(el('pre', 'object-diff', JSON.stringify(content.document, null, 2)));
    if (Array.isArray(plan.feedback) && plan.feedback.length) { section.append(el('h4', '', '本轮反馈原文')); const list = el('ul', 'requirement-list'); for (const item of plan.feedback) list.append(el('li', '', this.feedbackDescription(item, plan.document?.objects))); section.append(list); }
    section.append(technical);
  }
  async reviseReadyProposal(proposalId, supplement) {
    const proposal = this.proposal;
    if (!this.usesV1Commands(proposal?.projectId) || !proposal || proposal.id !== proposalId || !this.canSubmitVisualRevision(proposal)) return this.notify('当前方案不能安全创建新版修订。');
    const text = supplement.trim(), pendingInput = this.feedbackInputs?.[this.selectedObjectId] || null, pendingMessage = String(pendingInput?.message || '').trim();
    let referenceChange;
    try { referenceChange = this.proposalReferenceChange(proposal); } catch (error) { return this.notify(error.message); }
    if (!text && !pendingMessage && !referenceChange) return this.notify('先写下需要补充的内容、反馈或参考变更。');
    if (pendingMessage && !this.selectedObjectId) return this.notify('未加入的反馈需要先选择关联对象。');
    const feedback = pendingMessage ? [{ feedbackId: this.pendingReadyFeedback?.message === pendingMessage && this.pendingReadyFeedback?.objectId === this.selectedObjectId ? this.pendingReadyFeedback.feedbackId : (this.pendingReadyFeedback = { message: pendingMessage, objectId: this.selectedObjectId, feedbackId: this.newFeedbackId() }).feedbackId, objectId: this.selectedObjectId, message: pendingMessage, category: pendingInput.category || 'general' }] : [];
    if (this.visualRevisionSubmitting?.proposalId === proposalId && this.visualRevisionSubmitting.revision === proposal.revision) return;
    const operation = this.visualRevisionSubmitting = { proposalId, revision: proposal.revision };
    const context = this.captureSelectionContext(), revision = proposal.revision, generation = ++this.proposalMutationGeneration;
    const button = $('.ready-revision button'); if (button) button.disabled = true;
    this.activity = '正在提交方案新修订'; this.renderWorkflowStatus();
    try {
      const response = await this.sendCommand('proposal.revise', { proposalId, supplement: text || undefined, feedback, ...referenceChange }, { expected: { preferencesRevision: this.sessionPreferences?.revision, publicationRevision: this.snapshot?.publicationRevision, proposalRevision: revision, sourceCommit: this.snapshot?.sourceCommit ?? this.snapshot?.baseCommit ?? null } });
      const latest = response.proposal || response;
      if (!this.selectionContextMatches(context) || generation !== this.proposalMutationGeneration || this.proposal?.id !== proposalId) return;
      if (latest.id !== proposalId || !Number.isInteger(latest.revision) || latest.revision <= revision) throw new Error('服务没有返回新的方案修订。');
      this.proposal = latest; this.packet = null; this.pendingReadyFeedback = null;
      if (feedback.length && sameValue(this.feedbackInputs?.[feedback[0].objectId], pendingInput)) { delete this.feedbackInputs[feedback[0].objectId]; if (this.selectedObjectId === feedback[0].objectId) this.loadFeedbackInputForCurrentTarget(); }
      this.activity = null; this.renderProposal(); this.persistProposalInputs(); this.startProposalPolling();
    } catch (error) {
      if (this.selectionContextMatches(context) && generation === this.proposalMutationGeneration) { this.activity = '方案新修订结果待核实'; this.notify(`修订没有确认：${error.message}。刷新前端账本后再重试。`); this.renderWorkflowStatus(); if (button) button.disabled = false; }
    } finally { if (this.visualRevisionSubmitting === operation) this.visualRevisionSubmitting = null; }
  }
  renderQuestions(questions) {
    const root = $('#questions'); releaseVisuals(root); root.replaceChildren();
    if (this.proposal.visualReferences?.length) mountVisual(root, { title: '澄清所依据的视觉方向', status: '选项含义以问题文字为准；参考不补成精确规则', references: referenceModel(this.proposal, this.proposal.projectId), details: [{ label: '方案修订', value: this.proposal.revision }] }, `questions:${this.proposal.id}`);
    const decisions = this.proposal.decisions || {};
    const savedAnswers = this.proposalRevisionDraft(this.proposal)?.questions || {};
    for (const q of questions) {
      const fieldset = el('fieldset', 'question'); const legend = el('legend', '', q.prompt || q.id); fieldset.append(legend);
      const choices = Array.isArray(q.options) ? q.options : [];
      let control;
      if (q.type === 'choice' || choices.length) { control = el('select'); this.configureChoice(control, choices); }
      else if (q.type === 'boolean') { control = el('select'); for (const [value, label] of [['', '请选择'], ['true', '是'], ['false', '否']]) { const opt = el('option', '', label); opt.value = value; control.append(opt); } }
      else { control = q.type === 'text' ? el('textarea') : el('input'); if (q.type !== 'text') control.type = 'number'; else control.rows = 3; if (q.type === 'number' && q.integer) control.step = '1'; }
      control.name = q.id; control.required = q.required !== false; control.dataset.answerType = q.type || (choices.length ? 'choice' : 'text');
      const existing = Object.hasOwn(savedAnswers, q.id) ? savedAnswers[q.id] : decisions[q.id] ?? q.value ?? q.currentValue;
      if (existing != null) control.value = String(existing);
      fieldset.append(control); root.append(fieldset);
    }
    if (!questions.length) root.append(el('p', 'muted', '服务没有返回待回答的问题。'));
    this.renderPriorProposalInputs(this.proposal, root, { includeQuestions: true, includeSupplement: false });
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
    if (proposal.workflow === 'objects-v1' || this.objectsWorkflow()) existing.append(el('p', 'muted', '完整对象计划已在上方方案区按需展开；此处只保留本轮制作范围与版本绑定。'));
    this.renderPlanReviewCard(existing, proposal);
  }
  renderPlanReviewCard(root, proposal) {
    mountVisual(root, { title: '方案视觉核对', status: `方案 r${proposal.revision ?? '未知'} · ${proposal.status === 'FROZEN' ? '已冻结' : '仍待审阅'}`, rawText: this.visualRequestText(proposal),
      interpretation: proposal.summary, references: referenceModel(proposal, proposal.projectId),
      rows: [{ label: '参考状态', value: (proposal.visualReferences || []).length ? '本修订已纳入的参考及文字用途；尚未制作' : '本修订没有采纳视觉参考' }],
      details: [{ label: '方案编号', value: proposal.id }, { label: '发布基线', value: proposal.publicationRevision }, { label: 'Git 来源', value: proposal.baseCommit }] }, `proposal:${proposal.projectId}:${proposal.id}`);
    const request = proposal.changeRequest || {};
    const document = this.objectDocument(proposal) || {};
    const display = value => {
      if (value == null || value === '') return '';
      if (typeof value === 'string') return value;
      if (Array.isArray(value)) return value.map(item => typeof item === 'string' ? item : item?.message || item?.text || item?.title || JSON.stringify(item)).filter(Boolean).join('；');
      if (typeof value === 'object') return value.summary || value.text || value.description || JSON.stringify(value);
      return String(value);
    };
    const list = value => Array.isArray(value) ? value : value == null || value === '' ? [] : [value];
    const firstPopulated = (...values) => values.find(value => Array.isArray(value) ? value.length > 0
      : value && typeof value === 'object' ? Object.keys(value).length > 0
        : value === false || value === 0 || (value != null && String(value).trim() !== ''))
      ?? values.find(value => value != null);
    const uniqueIds = values => [...new Set(values.filter(value => typeof value === 'string' && value))];
    const tasks = list(firstPopulated(proposal.tasks, document.tasks));
    const requirements = list(firstPopulated(proposal.requirements, document.requirements));
    const taskRequirementIds = uniqueIds(tasks.flatMap(task => typeof task === 'object' && Array.isArray(task?.requirementIds) ? task.requirementIds : []));
    const relatedRequirements = taskRequirementIds.length
      ? requirements.filter(requirement => taskRequirementIds.includes(typeof requirement === 'object' ? requirement.id : requirement))
      : requirements;
    const requirementById = new Map(requirements.filter(item => item && typeof item === 'object' && item.id).map(item => [item.id, item]));
    const requestItems = [];
    const requestText = display(firstPopulated(proposal.userRequest, proposal.inputText, proposal.text, request.text));
    const userTexts = new Set(requestText ? [requestText] : []);
    for (const text of this.discussionRequestTexts(proposal)) userTexts.add(text);
    requestItems.push(...userTexts);
    for (const field of request.fields || []) requestItems.push(`${field.objectId || '对象'} · ${field.fieldId || '属性'} → ${display(field.value)}`);
    for (const item of list(firstPopulated(request.feedback, proposal.feedback))) requestItems.push(this.feedbackDescription(item, document.objects));
    for (const operation of request.operations || []) requestItems.push(`${operation.kind || '结构操作'} · ${operation.name || operation.objectId || operation.sceneId || operation.instanceId || operation.definitionId || ''}`);
    const targetIds = [...new Set([
      ...(Array.isArray(request.targetObjectIds) ? request.targetObjectIds : []),
      ...(request.fields || []).map(item => item.objectId), ...(request.feedback || []).map(item => item.objectId),
      ...(request.operations || []).flatMap(item => [item.objectId, item.sceneId, item.instanceId, item.definitionId, item.entryId, item.presetId]),
    ].filter(value => typeof value === 'string' && value))];
    const knownTargets = new Map([...this.objectItems(), ...(Array.isArray(document.objects) ? document.objects : [])].map(item => [item.id, item.name || item.id]));
    const objectLabel = id => `${knownTargets.get(id) || id}（${id}）`;
    const requestTargets = targetIds.map(objectLabel);
    const taskObjectIds = uniqueIds(tasks.flatMap(task => typeof task === 'object' && Array.isArray(task?.objectIds) ? task.objectIds : []));
    const taskTargets = taskObjectIds.map(objectLabel);
    const objectChanges = firstPopulated(proposal.objectChanges, proposal.objectDiff, proposal.diff?.objects, document.objectChanges, document.objectDiff);
    const changeItems = Array.isArray(objectChanges) ? objectChanges : objectChanges == null || objectChanges === '' ? [] : [objectChanges];
    const changeLines = changeItems.map(change => {
      if (typeof change === 'string') return change;
      if (!change || typeof change !== 'object') return String(change);
      const objectId = change.objectId || change.id;
      if (!objectId) return display(change);
      const parts = [`${change.action || '未标注差异'} · ${objectLabel(objectId)}`];
      const beforeFields = new Map((Array.isArray(change.before?.fields) ? change.before.fields : []).filter(field => field?.id).map(field => [field.id, field]));
      const afterFields = new Map((Array.isArray(change.after?.fields) ? change.after.fields : []).filter(field => field?.id).map(field => [field.id, field]));
      const fieldChanges = [...new Set([...beforeFields.keys(), ...afterFields.keys()])].filter(id => JSON.stringify(beforeFields.get(id) ?? null) !== JSON.stringify(afterFields.get(id) ?? null)).map(id => {
        const before = beforeFields.get(id), after = afterFields.get(id);
        const label = after?.label || before?.label || id;
        return before && after && JSON.stringify(before.value) !== JSON.stringify(after.value)
          ? `${label}：${display(before.value)} → ${display(after.value)}`
          : `${label}：字段定义有变化`;
      });
      if (fieldChanges.length) parts.push(`属性差异 ${fieldChanges.join('、')}`);
      return parts.join(' · ');
    }).filter(Boolean);
    const taskLines = tasks.map((task, index) => {
      if (typeof task === 'string') return `任务 ${index + 1}：${task}`;
      if (!task || typeof task !== 'object') return '';
      const taskId = task.id || task.title || `任务 ${index + 1}`;
      const description = task.description || task.text || task.summary || task.title || JSON.stringify(task);
      const parts = [`任务 ${taskId}：${display(description)}`];
      if (Array.isArray(task.objectIds) && task.objectIds.length) parts.push(`任务关联对象（包含检查对象，不代表都会改变）：${task.objectIds.map(objectLabel).join('、')}`);
      if (Array.isArray(task.requirementIds) && task.requirementIds.length) parts.push(`关联需求：${task.requirementIds.map(id => requirementById.has(id) ? `${id} · ${display(requirementById.get(id).text || requirementById.get(id))}` : id).join('；')}`);
      for (const [label, value] of [
        ['任务约束', firstPopulated(task.constraints, task.preservationRequirements, task.preservedRequirements, task.preserve, task.invariants)],
        ['任务验收条件', firstPopulated(task.acceptance, task.acceptanceCriteria)],
        ['任务验证方式', firstPopulated(task.verification, task.validation, task.tests)],
      ]) if (display(value)) parts.push(`${label}：${display(value)}`);
      return parts.join('\n');
    }).filter(Boolean);
    const planSummary = display(proposal.summary || proposal.planSummary || document.summary);
    const planLines = [...(planSummary ? [`方案摘要：${planSummary}`] : []), ...taskLines];
    const directPreservation = [
      ['方案保持条件', firstPopulated(proposal.preservationRequirements, proposal.preservedRequirements, proposal.invariants, proposal.constraints, request.preserve)],
      ...tasks.flatMap((task, index) => typeof task === 'object' && task ? [[`任务 ${task.id || index + 1} 的原始约束`, firstPopulated(task.constraints, task.preservationRequirements, task.preservedRequirements, task.preserve, task.invariants)]] : []),
    ].filter(([, value]) => display(value)).map(([label, value]) => `${label}：${display(value)}`);
    const requirementLines = relatedRequirements.map(requirement => {
      if (typeof requirement === 'string') return requirement;
      if (!requirement || typeof requirement !== 'object') return String(requirement);
      const verification = requirement.verification ? ` · 验证方式：${['manual', 'human'].includes(requirement.verification) ? '人工体验验收' : display(requirement.verification)}` : '';
      return `${requirement.id ? `${requirement.id} · ` : ''}${display(requirement.text || requirement.title || requirement)}${verification}`;
    }).filter(Boolean);
    const preservationLines = [...directPreservation, ...(requirementLines.length
      ? [`任务关联需求原文${directPreservation.length ? '' : '（未单独结构化为保持条件；按原文供核对）'}：${requirementLines.join('；')}`]
      : [])];
    const acceptance = firstPopulated(proposal.acceptance, proposal.acceptanceCriteria, document.acceptance, document.acceptanceCriteria, proposal.tests, proposal.validation);
    const verificationLines = list(acceptance).map(item => `方案验收条件：${display(item)}`).filter(Boolean);
    for (const [index, task] of tasks.entries()) if (task && typeof task === 'object') {
      const name = task.id || task.title || `任务 ${index + 1}`;
      for (const [label, value] of [['验收条件', firstPopulated(task.acceptance, task.acceptanceCriteria)], ['验证方式', firstPopulated(task.verification, task.validation, task.tests)]]) {
        if (display(value)) verificationLines.push(`任务 ${name} · ${label}：${display(value)}`);
      }
    }
    for (const requirement of relatedRequirements) if (requirement && typeof requirement === 'object' && requirement.verification) {
      const method = { manual: '试玩核对', human: '人工核对', automated: '自动检查', runtime: '运行时检查' }[requirement.verification] || '待明确验证方式';
      verificationLines.push(`${requirement.text || requirement.id}（${method}）`);
    }
    const feedbackDecisions = list(firstPopulated(proposal.feedbackDecisions, document.feedbackDecisions));
    const decisionLines = feedbackDecisions.map(item => {
      if (typeof item === 'string') return item;
      if (!item || typeof item !== 'object') return String(item);
      const parts = [item.feedbackId || '反馈', item.status || item.disposition || '未说明'];
      if (item.reason) parts.push(item.reason);
      if (item.taskIds?.length) parts.push(`任务 ${item.taskIds.join('、')}`);
      if (item.requirementIds?.length) parts.push(`需求 ${item.requirementIds.join('、')}`);
      return parts.join(' · ');
    });
    const card = el('section', 'plan-review-card'); card.append(el('h3', '', '制作前方案核对'));
    const section = label => { const result = el('section', 'plan-review-item'); result.append(el('h4', '', label)); card.append(result); return result; };
    const appendLines = (parent, lines, fallback) => {
      const content = lines.length ? lines : [fallback];
      for (const line of content) parent.append(el('p', line === fallback ? 'muted' : '', line));
    };
    const requestSection = section('你的要求');
    if (requestTargets.length) requestItems.push(`用户请求目标：${requestTargets.join('、')}`);
    appendLines(requestSection, requestItems, '当前服务记录没有提供可展示的原始要求。');
    const planSection = section('AI 准备怎样做');
    appendLines(planSection, planLines, '当前方案没有提供具体执行说明；请展开完整方案核对。');
    appendLines(planSection, decisionLines.map(line => `逐条反馈处理决定：${line}`), feedbackDecisions.length ? '' : '当前方案没有提供逐条反馈处理决定。');
    const impactSection = section('影响谁');
    appendLines(impactSection, requestTargets.length ? [`用户请求目标：${requestTargets.join('、')}`] : [], '服务没有列出结构化用户请求目标。');
    if (changeLines.length) appendLines(impactSection, [`方案中的对象差异记录：${changeLines.join('；')}`]);
    else if (objectChanges != null) appendLines(impactSection, ['方案记录的对象差异为空。']);
    else appendLines(impactSection, ['服务未提供结构化对象差异；不能从任务关联对象推断哪些对象会改变。']);
    if (taskTargets.length) appendLines(impactSection, [`AI 任务关联对象（包含检查对象，不代表都会改变）：${taskTargets.join('、')}`]);
    const authoredScope = display(proposal.scope || proposal.targets);
    if (authoredScope) appendLines(impactSection, [`方案范围原文：${authoredScope}`]);
    const preservationSection = section('保持什么');
    appendLines(preservationSection, preservationLines, '当前方案没有提供保持条件或可关联的需求原文。');
    const verificationSection = section('怎样验证');
    appendLines(verificationSection, verificationLines, '当前服务记录没有提供明确的验收或验证条件。');
    root.append(card);
  }
  async answerQuestions() {
    const context = this.captureSelectionContext(), proposal = this.proposal && structuredClone(this.proposal), generation = ++this.proposalMutationGeneration;
    if (!proposal?.id || !this.proposalBelongsToSelection(proposal, context)) return;
    const form = $('#answers-form'); const answers = {};
    if (!form.reportValidity()) return;
    let referenceChange;
    try { referenceChange = this.proposalReferenceChange(proposal); } catch (error) { return this.notify(error.message); }
    for (const control of form.querySelectorAll('[name]')) {
      if (control.value === '') continue;
      const type = control.dataset.answerType;
      if (type === 'boolean') answers[control.name] = control.value === 'true';
      else if (type === 'number') answers[control.name] = Number(control.value);
      else if (type === 'choice') answers[control.name] = (proposal.workflow === 'objects-v1' || this.objectsWorkflow() || control.dataset.optionMode === 'index') ? this.readChoiceValue(control) : control.value;
      else answers[control.name] = control.value;
    }
    this.activity = '正在提交用户回答'; this.renderWorkflowStatus();
    try {
      const response = this.usesV1Commands(proposal.projectId)
        ? await this.sendCommand('proposal.revise', { proposalId: proposal.id, answers: Object.entries(answers).map(([questionId, value]) => ({ questionId, text: String(value) })), ...referenceChange }, { expected: { preferencesRevision: this.sessionPreferences?.revision, publicationRevision: this.snapshot?.publicationRevision, proposalRevision: proposal.revision, sourceCommit: this.snapshot?.sourceCommit ?? this.snapshot?.baseCommit ?? null } })
        : await this.request(`/proposals/${encodeURIComponent(proposal.id)}/answers`, { method: 'POST', token: true, body: { expectedRevision: proposal.revision, answers } });
      if (!this.selectionContextMatches(context) || generation !== this.proposalMutationGeneration || this.proposal?.id !== proposal.id || Number(this.proposal?.revision) !== Number(proposal.revision)) return;
      this.activity = null; this.proposal = response.proposal || response; this.renderProposal(); this.startProposalPolling();
    } catch (error) { if (this.selectionContextMatches(context) && generation === this.proposalMutationGeneration && this.proposal?.id === proposal.id) { this.activity = !Number.isInteger(error.status) || error.status >= 500 ? '回答提交结果待核实' : null; this.notify(`回答没有保存：${error.message}${error.status === 409 ? ' 方案已更新，请刷新后重新核对。' : ''}`); this.renderWorkflowStatus(); } }
  }
  async freezeProposal() {
    if (!this.readiness?.ready || !$('#reviewed').checked || !this.proposal) return;
    if (this.hasPendingProposalReferences()) return this.notify('参考草稿有未提交变更，请先提交重新策划，或在视觉策划中明确撤销本轮参考草稿。');
    if (this.freezingProposal?.projectId === this.proposal.projectId && this.freezingProposal?.id === this.proposal.id && this.freezingProposal?.revision === this.proposal.revision) return;
    const context = this.captureSelectionContext(), proposal = structuredClone(this.proposal), generation = ++this.proposalMutationGeneration;
    if (!this.proposalBelongsToSelection(proposal, context)) return;
    const freezing = { projectId: proposal.projectId, id: proposal.id, revision: proposal.revision };
    this.freezingProposal = freezing;
    const button = $('#freeze'); button.disabled = true; button.textContent = '正在冻结方案…';
    $('#notice').textContent = ''; hide($('#notice'));
    try {
      if (this.usesV1Commands(proposal.projectId)) {
        try { if (this.reviewedPlan?.reviewedPlanRef !== proposal.reviewedPlanRef) await this.loadReviewedPlan(proposal); }
        catch (error) { return this.notify(`必须先读取完整审阅计划：${error.message}`); }
        if (!this.selectionContextMatches(context) || generation !== this.proposalMutationGeneration || this.proposal?.id !== proposal.id || this.proposal?.revision !== proposal.revision) return;
        if (!this.reviewedPlan || this.reviewedPlan.reviewedPlanRef !== proposal.reviewedPlanRef || this.reviewedPlan.plan?.revision !== proposal.revision) return this.notify('完整审阅计划与当前 READY 修订不匹配，未冻结。');
      }
      if (this.hasPendingProposalReferences()) return this.notify('参考草稿有未提交变更，请先提交重新策划或明确撤销。');
      this.activity = '正在提交确认的制作表单'; this.renderWorkflowStatus();
      if (this.packet && proposal.status === 'FROZEN' && (!this.packet.proposalId || this.packet.proposalId === proposal.id) && (!this.packet.projectId || !proposal.projectId || this.packet.projectId === proposal.projectId)) { await this.createJob(this.packet, { context, proposal }); return; }
      const reviewedProposal = proposal;
      const response = this.usesV1Commands(proposal.projectId)
      ? await this.sendCommand('proposal.freeze', { proposalId: proposal.id, reviewedPlanRef: proposal.reviewedPlanRef }, { expected: { proposalRevision: proposal.revision, publicationRevision: proposal.publicationRevision } })
        : await this.request(`/proposals/${encodeURIComponent(proposal.id)}/freeze`, { method: 'POST', token: true, body: { expectedRevision: proposal.revision, expectedPublicationRevision: proposal.publicationRevision, reviewedProposal } });
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
    } catch (error) { if (this.selectionContextMatches(context) && generation === this.proposalMutationGeneration && this.proposal?.id === proposal.id) { this.activity = !Number.isInteger(error.status) || error.status >= 500 ? '制作表单提交状态待核实' : null; this.renderWorkflowStatus(); this.notify(`方案未能冻结或派发：${error.message}${error.status === 409 ? ' 版本发生变化，请刷新并重新审阅。' : ''}`); } }
    finally {
      if (this.freezingProposal === freezing) this.freezingProposal = null;
      if (this.selectionContextMatches(context) && this.proposal?.id === proposal.id && this.proposal?.revision === proposal.revision) {
        button.textContent = '确认方案并继续';
        button.disabled = this.proposal.status !== 'READY' || !$('#reviewed').checked || !this.readiness?.ready;
      }
    }
  }
  async resumeFrozenPacket() {
    if (!this.packet || this.proposal?.status !== 'FROZEN') return;
    const context = this.captureSelectionContext(), packet = this.packet, proposal = structuredClone(this.proposal);
    if (!this.proposalBelongsToSelection(proposal, context)) return;
    const button = $('#resume-packet'); button.disabled = true; button.textContent = '正在恢复原制作表单…';
    try { await this.createJob(packet, { context, proposal }); if (this.selectionContextMatches(context) && this.packet === packet) hide(button); }
    catch (error) { if (this.selectionContextMatches(context) && this.packet === packet) { this.notify(`无法恢复此制作表单：${error.message}。页面仍保留原表单编号。`); button.disabled = false; button.textContent = '恢复并继续此制作表单'; } }
  }
  renderFrozenPacket(container = $('#packet-preview'), packet = this.packet) {
    if (!packet || !container) return;
    releaseVisuals(container);
    container.replaceChildren(el('h3', '', '已冻结的制作表单'));
    mountVisual(container, { title: '本次冻结输入', status: `方案 r${packet.proposalRevision ?? '未知'} → 已冻结表单`, rawText: this.visualRequestText(packet), references: referenceModel(packet, packet.projectId), warning: '制作将使用此表单中的参考与要求；后来草稿另行审阅。', details: [{ label: '表单编号', value: packet.id }, { label: '方案编号', value: packet.proposalId }, { label: 'Git 基线', value: packet.baseCommit }] }, `packet:${packet.id}`);
    const fields = [
      ['表单编号', packet.packetId || packet.id], ['表单版本', packet.schemaVersion || packet.version || '服务返回'], ['阶段', packet.operationKind || '未声明'],
      ['项目 / 方案', `${packet.projectId || '待分配'} · ${packet.proposalId || this.proposal?.id || ''} r${packet.proposalRevision ?? this.proposal?.revision ?? ''}`],
      ['Git 基线', packet.baseCommit || this.proposal?.baseCommit || '服务未提供'],
      ['角色', (packet.roles || packet.roleScope || []).map?.(item => typeof item === 'string' ? item : item.name || item.id).join('、') || packet.role || '服务按项目规则分配'],
      ['冻结执行配置', JSON.stringify(packet.profileSnapshot || packet.profile || '服务未提供')],
      ['实施范围', typeof packet.scope === 'string' ? packet.scope : JSON.stringify(packet.scope || packet.targets || packet.requirements || [])],
      ['验收条件', JSON.stringify(packet.acceptance || packet.acceptanceCriteria || packet.tests || [])],
      ['保留约束', JSON.stringify(packet.preservationConstraints || packet.constraints || [])],
      ['停止条件', JSON.stringify(packet.stopConditions || packet.stopCondition || '遵循冻结表单与项目规则')],
    ];
    const list = el('dl', 'packet-list'); for (const [label, value] of fields) list.append(el('dt', '', label), el('dd', '', String(value ?? '未提供')));
    const technical = el('details', 'frozen-packet-technical'); technical.append(el('summary', '', '查看冻结配置与技术详情'), list); container.append(technical);
  }
  async createJob(packet = this.packet, { context = this.captureSelectionContext(), proposal = this.proposal } = {}) {
    if (!packet) throw new Error('没有可恢复的冻结制作表单。');
    const packetId = packet.packetId || packet.id, proposalId = proposal?.id;
    // A frozen packet identifies one dispatch intent. Retrying after an uncertain
    // network outcome must address the same intent, never create a replacement job.
    const idempotencyKey = `packet:${packetId}`;
    this.activity = '已提交制作请求，等待 agent session'; this.renderWorkflowStatus();
    if (this.usesV1Commands(packet.projectId || proposal?.projectId)) {
      await this.ensureWorkbench(packet.projectId || proposal.projectId, true);
      if (!this.selectionContextMatches(context)) return null;
    }
    let response;
    try { response = this.usesV1Commands(packet.projectId || proposal?.projectId)
      ? await this.sendCommand('production.start', { packetId }, { expected: { proposalRevision: proposal?.revision, publicationRevision: this.snapshot?.publicationRevision, preferencesRevision: this.sessionPreferences?.revision } })
      : await this.request('/jobs', { method: 'POST', token: true, body: { packetId, idempotencyKey } }); }
    catch (error) {
      const packetStillSelected = this.packet?.id === packetId || this.packet?.packetId === packetId;
      if (this.selectionContextMatches(context) && packetStillSelected && (!proposalId || this.proposal?.id === proposalId)) { this.activity = !Number.isInteger(error.status) || error.status >= 500 ? '制作派发状态待核实' : null; this.renderWorkflowStatus(); }
      throw error;
    }
    const job = response.job || response;
    if (!job.id) throw new Error('服务没有返回作业编号。');
    if (!this.selectionContextMatches(context) || this.packet?.id !== packet.id && this.packet?.packetId !== packetId || proposalId && this.proposal?.id !== proposalId) return null;
    this.selectedJob = null; this.job = job;
    this.renderJob(); this.beginPolling(); if (this.job.projectId) await this.loadWorkbench(this.job.projectId);
    return this.job;
  }
  selectedJobForProject(projectId = this.projectId) { return this.selectedJob?.projectId === projectId ? this.selectedJob.id : null; }
  async selectJob(id) {
    this.selectedJob = { projectId: this.projectId, id }; this.stopPolling();
    await this.loadJob(id);
    $('#job-panel')?.scrollIntoView?.({ behavior: 'smooth', block: 'start' });
  }
  async loadJob(id, poll = true) {
    if (this.jobReadInFlight?.id === id) return this.jobReadInFlight.promise;
    const context = this.captureSelectionContext(), generation = ++this.jobLoadGeneration;
    const promise = (async () => {
    try { const response = await this.request(`/jobs/${encodeURIComponent(id)}`, { projectId: context.projectId }); const job = response.job || response; if (!this.selectionContextMatches(context) || generation !== this.jobLoadGeneration || job.id !== id || job.projectId !== context.projectId) return; this.activity = null; this.job = job; this.renderJob(); if (poll && !TERMINAL.has(this.job.status)) this.beginPolling(); }
    catch (error) { if (this.selectionContextMatches(context) && generation === this.jobLoadGeneration) { this.activity = '制作状态未确认'; this.renderWorkflowStatus(); this.notify(`无法读取作业状态：${error.message}`); } }
    })();
    this.jobReadInFlight = { id, promise };
    try { return await promise; } finally { if (this.jobReadInFlight?.promise === promise) this.jobReadInFlight = null; }
  }
  renderJob() {
    if (!this.job) return; hide($('#job-panel'), false); setStatus($('#job-status'), this.job.status, jobLabel(this.job));
    const historical = this.isHistoricalJob(this.job);
    if (historical) $('#job-status').textContent = `历史 · ${jobLabel(this.job)}`;
    $('#job-title').textContent = historical ? '历史制作记录' : '本轮进度';
    const productionFailure = ['FAILED', 'UNCERTAIN', 'CANCELLED'].includes(this.job.status) && this.job.productionFailure && typeof this.job.productionFailure === 'object' ? this.job.productionFailure : null;
    const originalMessage = this.job.message;
    const readyMessage = this.job.status === 'READY_FOR_REVIEW' && this.job.verification?.status === 'PASS'
      ? historical ? '该历史制作轮次的候选当时已封存，独立技术验证通过。' : '制作交付已封存，独立技术验证通过；请试玩并审阅候选。'
      : originalMessage || (this.job.sessionId ? `制作会话已建立：${this.job.sessionId}` : '正在等待服务更新进度。');
    $('#job-message').textContent = (typeof productionFailure?.message === 'string' && productionFailure.message) || readyMessage || '正在等待服务更新进度。';
    const evidence = $('#job-evidence'); releaseVisuals(evidence); evidence.replaceChildren();
    if (historical) evidence.append(el('div', 'notice historical-result-notice', `历史制作轮次：${this.job.id}。以下候选与验证只记录该轮结果，不代表当前方案或当前项目状态。`));
    if (productionFailure) this.renderProductionFailure(this.job, evidence);
    if (productionFailure && typeof originalMessage === 'string' && originalMessage && originalMessage !== productionFailure.message) {
      const prior = el('details', 'production-failure-history'); prior.append(el('summary', '', '原失败记录'), el('p', '', originalMessage)); evidence.append(prior);
    }
    if (this.job.verification) this.renderEvidence(this.job.verification, evidence, { historical });
    const canCancel = !historical && ['QUEUED', 'DISPATCHING', 'RUNNING', 'VERIFYING', 'PROJECTING'].includes(this.job.status);
    hide($('#cancel-area'), !canCancel);
    const reconcileRequested = !!productionFailure && (productionFailure.terminationConfirmed !== true || String(productionFailure.nextAction || '').toUpperCase() === 'RECONCILE');
    hide($('#reconcile-area'), historical || this.job.status !== 'UNCERTAIN' && !reconcileRequested);
    const candidate = this.job.candidate || this.job.response?.candidate;
    if (candidate) { this.renderCandidate(candidate, { historical }); hide($('#candidate-area'), false); } else hide($('#candidate-area'));
    if (!historical) this.renderFailedInitialRecovery(this.job, evidence);
    if (!historical && (this.packet?.operationKind || this.job.operationKind) === 'INITIALIZATION' && this.job.status === 'PUBLISHED') {
      const nextProposal = this.job.nextProposal || this.job.response?.nextProposal;
      if (nextProposal) { this.proposal = nextProposal; this.renderProposal(); }
      else {
        const stage = el('div', 'notice', '工程准备阶段已完成。玩法实现尚未开始；需要服务返回项目内规划、测试基线和新的精确制作提案，完成后再单独确认。');
        $('#job-evidence').append(stage);
      }
    }
    if (this.job.projectId && (this.snapshot?.projectId || this.snapshot?.id) !== this.job.projectId) this.ensureWorkbench(this.job.projectId).catch(() => {});
    if (TERMINAL.has(this.job.status)) this.stopPolling();
    this.renderWorkflowStages(); this.renderWorkflowStatus();
  }
  renderProductionFailure(job, root) {
    const failure = job?.productionFailure;
    if (!failure || !['FAILED', 'UNCERTAIN', 'CANCELLED'].includes(job.status)) return;
    const card = el('section', 'notice production-failure'); card.setAttribute('aria-label', '制作执行诊断');
    card.append(el('h3', '', '制作执行诊断'));
    if (typeof failure.message === 'string' && failure.message) card.append(el('p', '', failure.message));
    const details = el('dl', 'planning-diagnostic');
    if (typeof failure.code === 'string' && failure.code) details.append(el('dt', '', '诊断代码'), el('dd', '', failure.code));
    if (typeof failure.nativeStatus === 'string' && failure.nativeStatus) details.append(el('dt', '', '原生状态'), el('dd', '', failure.nativeStatus));
    if (typeof failure.diagnosticRef === 'string' && failure.diagnosticRef) details.append(el('dt', '', '后台诊断引用'), el('dd', '', failure.diagnosticRef));
    if (failure.connectionInterrupted === true) details.append(el('dt', '', '连接记录'), el('dd', '', '期间有连接中断记录'));
    const seconds = Number(failure.elapsedSeconds);
    if (failure.elapsedSeconds != null && failure.elapsedSeconds !== '' && Number.isFinite(seconds) && seconds >= 0) {
      const rounded = Math.round(seconds), minutes = Number((rounded / 60).toFixed(1));
      details.append(el('dt', '', '耗时'), el('dd', '', rounded >= 60 ? `${rounded} 秒（${minutes} 分钟）` : `${rounded} 秒`));
    }
    details.append(el('dt', '', '停止状态'), el('dd', '', failure.terminationConfirmed === true ? '制作停止已确认' : '制作停止待核实'));
    if (details.childNodes.length) card.append(details);
    if (failure.effectsMayHaveOccurred === true) card.append(el('p', 'notice', '部分改动可能保留在隔离工程中，但尚未验证，也未生成可审阅候选。'));
    const nextActionLabels = { RECONCILE: '向服务对账', CHECK_SERVICE: '先修复服务，再手动重新策划', NEW_PLANNING: '可手动提交新策划；之后仍需审阅确认', RETRY_FROM_APPROVED_INPUT: '沿用原输入重新策划', REVIEW: '查看当前作业诊断' };
    const nextAction = failure.terminationConfirmed !== true ? 'RECONCILE' : typeof failure.nextAction === 'string' ? failure.nextAction.toUpperCase() : '';
    if (nextActionLabels[nextAction]) card.append(el('p', 'muted', `建议下一步：${nextActionLabels[nextAction]}`));
    root.append(card);
  }
  renderFailedInitialRecovery(job, root) {
    const failure = job?.productionFailure;
    const recoveryMustWait = !!failure && (failure.terminationConfirmed !== true || String(failure.nextAction || '').toUpperCase() === 'RECONCILE');
    if (!['FAILED', 'CANCELLED'].includes(job?.status) || recoveryMustWait || this.canEnterIteration() || this.stage !== 'initial' || this.proposal || job.projectId !== this.projectId) return;
    const packet = job.packet || job.response?.packet || (job.packetId && (this.workspace?.packets || []).find(item =>
      item.projectId === this.projectId && [item.id, item.packetId].includes(job.packetId)));
    const approved = packet?.approvedProposal || (packet?.userText !== undefined ? { text: packet.userText, assets: packet.assets, visualReferences: packet.visualReferences, projectId: packet.projectId } : null);
    if (!packet || packet.projectId !== this.projectId || !approved || (approved.projectId && approved.projectId !== this.projectId) || typeof approved.text !== 'string' || !approved.text.trim()) return;
    const restoredText = this.recoveryRequestText(packet);
    const button = el('button', 'button secondary', '恢复本轮原文与参考'); button.type = 'button'; button.dataset.action = 'restore-approved-input';
    const projectId = this.projectId, jobId = job.id, packetId = packet.id || packet.packetId;
    button.addEventListener('click', () => {
      const currentFailure = this.job?.productionFailure;
      const currentRecoveryMustWait = !!currentFailure && (currentFailure.terminationConfirmed !== true || String(currentFailure.nextAction || '').toUpperCase() === 'RECONCILE');
      if (this.projectId !== projectId || this.job?.id !== jobId || !['FAILED', 'CANCELLED'].includes(this.job?.status) || currentRecoveryMustWait || this.canEnterIteration() || this.stage !== 'initial' || this.proposal) return;
      const currentPacket = this.job.packet || this.job.response?.packet || (this.job.packetId && (this.workspace?.packets || []).find(item => item.projectId === projectId && [item.id, item.packetId].includes(this.job.packetId)));
      if (!currentPacket || currentPacket.projectId !== projectId || (currentPacket.id || currentPacket.packetId) !== packetId || (currentPacket.approvedProposal && currentPacket.approvedProposal !== approved)) return;
      const packetAssets = Array.isArray(currentPacket.assets) ? currentPacket.assets : [];
      const rawAssets = Array.isArray(approved.assets) ? approved.assets : Array.isArray(approved.assetIds) ? approved.assetIds : packetAssets;
      const assets = [...new Map(rawAssets.map(item => {
        const id = typeof item === 'string' ? item : item?.id;
        if (typeof id !== 'string' || !id || (item?.projectId && item.projectId !== projectId)) return null;
        const metadata = typeof item === 'object' ? item : packetAssets.find(candidate => candidate?.id === id) || {};
        return [id, { ...metadata, id, name: metadata.name || '参考图片', purpose: metadata.purpose || 'reference', mimeType: metadata.mimeType || '' }];
      }).filter(Boolean))].map(([, item]) => item);
      const currentText = $('#concept').value;
      const currentAssetIds = this.assets.map(asset => asset.id).filter(Boolean).sort();
      const restoredAssetIds = assets.map(asset => asset.id).sort();
      const assetsDiffer = currentAssetIds.length > 0 && JSON.stringify(currentAssetIds) !== JSON.stringify(restoredAssetIds);
      const restoredIntents = Object.fromEntries((approved.visualReferences || []).map((reference, index) => [reference.assetId || `text-${index}`, cloneValue(reference)]));
      const intentsDiffer = Object.values(this.referenceIntents || {}).some(record => record.intent?.trim() || record.preserve?.trim() || record.unknown?.trim()) && !sameValue(this.referenceIntents, restoredIntents);
      if ((currentText.trim() && currentText !== approved.text && currentText !== restoredText) || assetsDiffer || intentsDiffer) {
        this.notify('当前概念或参考用途已有编辑，已保留。原文和参考可在恢复预览中查看；恢复不会覆盖当前编辑。');
        return;
      }
      $('#concept').value = restoredText;
      this.referenceIntents = restoredIntents;
      const interpretation = $('#concept-visual-interpretation');
      const originalGeneration = (this.conceptGenerationRequests || []).find(request => assets.some(asset => asset.id === request.asset?.id));
      if (interpretation && !interpretation.value) interpretation.value = originalGeneration?.request?.interpretation || '';
      this.assets = assets; this.renderAssets(); this.renderWorkflowStages(); this.queueConceptDraftSave();
      this.renderConceptReferenceResults();
      this.notify('已恢复本轮全部用户原文、补充回答和参考图。请核对后提交；系统没有自动启动策划或制作。');
      $('#concept').focus(); $('#concept-form')?.scrollIntoView?.({ behavior: 'smooth', block: 'center' });
    });
    const preview = el('details', 'approved-input-recovery');
    preview.append(el('summary', '', '查看可恢复的本轮原文与参考'));
    mountVisual(preview, { title: '恢复预览', rawText: restoredText,
      references: referenceModel({ ...packet, visualReferences: approved.visualReferences || packet.visualReferences || [] }, projectId),
      warning: '仅恢复到编辑区；不会自动重新策划、制作或生成图片。已有新编辑时保留新稿。' }, `recovery:${projectId}:${packetId}`);
    root.append(el('div', 'notice', `${jobLabel(job)}。可查看并恢复本轮全部已确认输入与参考，再继续策划。`), preview, button);
  }
  renderEvidence(verification, root, { historical = false } = {}) {
    const card = el('div', historical ? 'evidence-card historical-evidence' : 'evidence-card'); card.append(el('h3', '', `${historical ? '历史运行验证' : '运行验证'}：${verification.status || '状态未知'}`));
    if (verification.runId) card.append(el('p', 'meta-line', `运行记录 ${verification.runId}`));
    const checks = verification.requirements || verification.checks || [];
    const names = { 'project.document': '对象计划格式', 'git.write_scope': '源码修改范围', 'object.source_bindings': '对象与源码绑定', 'git.frozen_document': '冻结计划保持', 'godot.available': 'Godot 引擎可用', 'godot.fresh_import': '全新工程导入', 'godot.main_scene_smoke': '主场景运行', 'verification_copy.source_immutable': '验证副本源码保持', 'user.acceptance': '人工体验验收' };
    const statuses = { PASS: '通过', FAIL: '失败', SKIPPED: '未执行', NOT_TESTED: '未执行', BLOCKED: '未执行（前置条件受阻）' };
    if (checks.length) { const list = el('ul', 'evidence-list'); for (const check of checks) { const summary = check.summary || check.message; const name = check.requirement || check.title || names[check.id] || (check.id?.startsWith('godot.engine_error.') ? 'Godot 运行错误' : check.id) || ''; list.append(el('li', '', `${statuses[check.status] || check.status || '未知'} · ${name}${summary ? `：${summary}` : ''}`)); } card.append(list); }
    if (this.objectsWorkflow()) card.append(el('p', 'muted', '技术检查结果只表示服务实际运行并记录的检查项。未被自动验证的玩法体验、平衡和视觉质量仍需用户实际体验确认。'));
    root.append(card);
  }
  renderCandidate(candidate, { historical = this.isHistoricalJob(this.job) } = {}) {
    const area = $('#candidate-area');
    const captureKey = this.candidateCaptureKey(candidate, this.packetForCandidate(this.job, candidate), historical);
    const previousCaptures = area.querySelector('.candidate-captures');
    const retainedCaptures = captureKey && previousCaptures?.dataset.captureKey === captureKey ? previousCaptures : null;
    const active = retainedCaptures?.contains(document.activeElement) ? document.activeElement : null;
    const selection = active && typeof active.selectionStart === 'number' ? [active.selectionStart, active.selectionEnd, active.selectionDirection] : null;
    // Native toggle events may still be queued when a state update rerenders.
    // Read the visible controls before removing them, including on selection changes.
    if (area.dataset.candidateKey) for (const node of area.querySelectorAll('details[data-candidate-detail]')) {
      this.candidateDetailsExpanded[`${area.dataset.candidateKey}:${node.dataset.candidateDetail}`] = node.open;
    }
    retainedCaptures?.remove();
    releaseVisuals(area); area.replaceChildren(el('h3', '', historical ? '历史制作候选结果' : '制作候选结果'));
    if (historical) area.append(el('p', 'notice historical-result-notice', '此候选属于历史制作轮次；不会在当前方案下运行或提交验收决定。'));
    const candidateKey = `${this.job?.projectId || this.projectId}:${candidate.id || candidate.candidateCommit || candidate.commit || this.job?.id || 'candidate'}`;
    area.dataset.candidateKey = candidateKey;
    const details = (section, label, content) => {
      const key = `${candidateKey}:${section}`, node = el('details', 'candidate-detail');
      node.dataset.candidateDetail = section; node.open = this.candidateDetailsExpanded?.[key] === true;
      node.addEventListener('toggle', () => { if (node.isConnected) { this.candidateDetailsExpanded ||= {}; this.candidateDetailsExpanded[key] = node.open; } });
      node.append(el('summary', '', label), content); return node;
    };
    const status = candidate.status || this.job?.status;
    if (status) area.append(el('p', 'meta-line candidate-status', `当前状态：${JOB_LABELS[status] || status}`));
    const summary = status === 'PUBLISHED' ? '此候选的接受与发布决定已记录。' : status === 'REJECTED' ? '此候选未被接受，可在返修上下文中继续调整。' : candidate.summary || candidate.message;
    if (summary) area.append(el('p', 'candidate-summary', summary));
    const rows = [['Git 版本', candidate.candidateCommit || candidate.commit || '未提供'], ['映射状态', candidate.catalogStatus || candidate.mappingStatus || '未声明'], ['可编辑能力', (candidate.capabilities || []).map(c => c.label || c.id || c).join('、') || '服务未提供']];
    const list = el('dl', 'packet-list'); for (const [label, value] of rows) list.append(el('dt', '', label), el('dd', '', String(value)));
    area.append(details('metadata', '候选技术信息 · Git 版本、映射状态与可编辑能力', list));
    if (this.objectsWorkflow()) {
      const mappings = candidate.objectMappings || candidate.catalog?.objects || candidate.objects || [];
      if (Array.isArray(mappings) && mappings.length) {
        const mappingList = el('ul', 'requirement-list');
        for (const item of mappings) mappingList.append(el('li', '', `${item.name || item.id} · ${item.status || item.mappingStatus || (item.sourceBindings?.length ? item.sourceBindings.join('、') : '映射待核对')}`));
        area.append(details('mappings', `候选对象映射 · ${mappings.length} 个对象`, mappingList));
      }
      const diff = candidate.objectDiff || candidate.objectChanges || candidate.diff?.objects;
      if (diff) area.append(details('diff', `对象差异${Array.isArray(diff) ? ` · ${diff.length} 项` : ''}`, el('pre', 'object-diff', typeof diff === 'string' ? diff : JSON.stringify(diff, null, 2))));
    }
    const previewProjectId = this.job?.projectId || this.projectId;
    const previewAllowed = !this.usesV1Commands(previewProjectId) || (
      this.projectView?.projectId === previewProjectId && this.projectView.allowedActions?.includes('preview.start') === true
    );
    if (!historical && candidate.previewAvailable === true && previewAllowed) { const preview = el('button', 'button secondary', '在 Godot 中运行此候选'); preview.type = 'button'; preview.addEventListener('click', () => this.previewCandidate(candidate)); area.append(preview); }
    if (!historical) this.renderPreviewControls(area);
    const commit = candidate.candidateCommit || candidate.commit;
    const associatedProposal = this.proposalForJob(this.job, candidate);
    this.renderCandidateVisual(area, candidate, { retainedCaptures, historical });
    const feedback = Array.isArray(candidate.experienceFeedback) ? candidate.experienceFeedback : associatedProposal?.changeRequest?.feedback || [];
    if (feedback.length && (historical || ['PUBLISHED', 'REJECTED'].includes(this.job.status))) {
      area.append(el('h4', '', '该轮体验反馈'));
      const list = el('ul', 'requirement-list');
      for (const item of feedback) {
        const decision = (this.job.experienceDecisions || []).find(value => value.feedbackId === item.feedbackId);
        const status = { resolved: '已解决', needs_followup: '后续跟进' }[decision?.status] || '未记录逐条决定';
        const row = el('li', '', `${this.feedbackDescription(item, this.packetForCandidate(this.job, candidate)?.document?.objects)} · ${status}`);
        if (decision?.reason) row.append(el('p', 'visual-raw', `体验决定理由：${decision.reason}`));
        list.append(row);
      }
      area.append(list);
    } else if (feedback.length) {
      area.append(el('h4', '', '逐条体验反馈决定'));
      for (const item of feedback) {
        const row = el('label', 'candidate-feedback'); row.append(el('span', '', this.feedbackDescription(item, this.packetForCandidate(this.job, candidate)?.document?.objects)));
        const select = el('select'); select.dataset.feedbackId = item.feedbackId || ''; select.setAttribute('aria-label', `反馈 ${item.feedbackId || item.message} 的验收决定`);
        for (const [value, label] of [['', '请选择'], ['resolved', '已解决'], ['needs_followup', '后续跟进']]) { const option = el('option', '', label); option.value = value; select.append(option); }
        select.value = this.experienceDecisions?.[item.feedbackId] || '';
        select.addEventListener('change', () => { this.experienceDecisions ||= {}; this.experienceDecisions[item.feedbackId] = select.value; this.renderCandidateButtons(candidate, commit, feedback); });
        const reason = el('textarea'); reason.maxLength = 2000; reason.rows = 2; reason.placeholder = '说明为什么作出此决定'; reason.setAttribute('aria-label', `反馈 ${item.feedbackId || item.message} 的决定理由`);
        reason.value = this.experienceDecisionReasons?.[item.feedbackId] || '';
        reason.addEventListener('input', () => { this.experienceDecisionReasons ||= {}; this.experienceDecisionReasons[item.feedbackId] = reason.value; this.renderCandidateButtons(candidate, commit, feedback); });
        row.append(select, reason); area.append(row);
      }
    }
    if (!historical && this.job.status === 'READY_FOR_REVIEW' && commit) {
      this.renderCandidateButtons(candidate, commit, feedback);
      area.append(el('p', 'muted', this.workspace?.testData ? '测试工作区决定仅用于验证服务流程，不代表生产用户验收。' : '技术验证与逐条体验反馈分别记录；没有选择的反馈不会被默认标为已解决。'));
    }
    const supportingDetails = el('section', 'candidate-supporting-details');
    if (candidate.verification) {
      const verification = candidate.verification, checks = verification.requirements || verification.checks || [];
      const content = el('div', 'candidate-evidence-content'); this.renderEvidence(verification, content, { historical });
      supportingDetails.append(details('verification', `运行验证：${verification.status || '状态未知'} · ${checks.length} 项检查`, content));
    }
    const guidance = el('p', 'muted', historical ? '对象映射与技术证据属于该历史轮次，仅供追溯。' : '对象映射与技术证据供你审阅。未被自动观察的玩法和视觉体验仍需你运行候选并决定是否接受。');
    if (this.objectsWorkflow()) supportingDetails.prepend(guidance);
    if (supportingDetails.childElementCount) area.append(supportingDetails);
    if (active?.isConnected) { active.focus({ preventScroll: true }); if (selection) active.setSelectionRange(...selection); }
  }
  candidateCaptureKey(candidate, packet, historical = this.isHistoricalJob(this.job)) {
    if (!packet || !candidate?.id || !this.job?.id || this.job.projectId !== this.projectId) return null;
    return JSON.stringify([this.selectionGeneration, this.projectId, this.job.id, packet.id || packet.packetId,
      packet.proposalId, packet.proposalRevision, candidate.id, candidate.candidateCommit || candidate.commit,
      !!historical, this.job.status === 'READY_FOR_REVIEW']);
  }
  packetForCandidate(job, candidate) {
    if (!job?.projectId) return null;
    const id = job.packetId || candidate?.packetId;
    const packet = [job.packet, job.response?.packet, this.packet, ...(this.workspace?.packets || [])]
      .find(item => item && typeof item === 'object' && item.projectId === job.projectId &&
        (id ? [item.id, item.packetId].includes(id) : item.jobId === job.id));
    if (!packet || (candidate?.projectId && candidate.projectId !== job.projectId) || (candidate?.jobId && candidate.jobId !== job.id)) return null;
    if (candidate?.packetId && ![packet.id, packet.packetId].includes(candidate.packetId)) return null;
    if (packet.jobId && packet.jobId !== job.id) return null;
    if ([job.proposalId, candidate?.proposalId, job.packet?.proposalId].filter(Boolean).some(id => id !== packet.proposalId)) return null;
    if ([job.proposalRevision, candidate?.proposalRevision, job.packet?.proposalRevision].filter(value => value != null).some(value => value !== packet.proposalRevision)) return null;
    return packet;
  }
  visualRequestText(source) {
    if (!source) return undefined;
    const approved = source.approvedProposal || source;
    const request = source.changeRequest || approved.changeRequest || {};
    const texts = new Set();
    const add = value => { if (typeof value === 'string' && value.trim()) texts.add(value); };
    add(source.userText ?? source.text ?? approved.text ?? request.text);
    for (const text of this.discussionRequestTexts(source)) add(text);
    const feedback = request.feedback ?? source.feedback ?? approved.feedback ?? [];
    const objects = source.document?.objects || approved.document?.objects || [];
    const messages = feedback.filter(item => typeof item.message === 'string' && item.message.trim())
      .map(item => {
        const object = objects.find(value => value.id === item.objectId);
        const target = object?.name ? `${object.name}（${item.objectId}）` : item.objectId || '当前项目';
        return `${target} · ${this.legacyWorkbench.feedbackCategoryLabel(item.category)}：\n${item.message}`;
      });
    return [...texts, ...messages].join('\n\n');
  }
  renderCandidateVisual(root, candidate, { retainedCaptures = null, historical = this.isHistoricalJob(this.job) } = {}) {
    const packet = this.packetForCandidate(this.job, candidate);
    const comparison = el('div', 'candidate-visual-comparison'); root.append(comparison);
    const request = packet?.changeRequest || {}, objects = packet?.document?.objects || [];
    const ids = [...new Set([...(request.targetObjectIds || []), ...(request.fields || []).map(f => f.objectId), ...(request.feedback || []).map(f => f.objectId).filter(Boolean), ...(packet?.visualReferences || []).flatMap(r => r.targetObjectIds || [])])];
    mountVisual(comparison, { title: '本轮要求与候选对照', status: `已接受基线 ${packet?.publicationRevision ?? '未知'} → 本候选 ${candidate.status || this.job?.status || '状态未知'}`,
      rawText: this.visualRequestText(packet),
      warning: !packet ? '缺少此候选绑定的冻结输入；无法核对本轮参考。当前草稿不会补作历史依据。' : '参考与要求来自本轮冻结输入。技术检查、静态画面与用户体验分别核对；未采集的画面不作视觉符合结论。',
      references: referenceModel(packet, this.job.projectId),
      targets: ids.map(id => ({ id, label: objects.find(o => o.id === id)?.name || id, scope: '按本轮冻结计划逐项目标核对' })),
      details: [{ label: '候选编号', value: candidate.id }, { label: '作业编号', value: this.job.id }, { label: '表单编号', value: packet?.id }, { label: '方案修订', value: packet?.proposalRevision }, { label: '候选 Git', value: candidate.candidateCommit || candidate.commit }] }, `candidate:${candidate.id || this.job.id}`);
    if (packet && candidate.id) {
      const key = this.candidateCaptureKey(candidate, packet, historical);
      if (retainedCaptures && retainedCaptures.dataset.captureKey === key) { comparison.append(retainedCaptures); retainedCaptures.refreshCaptures?.(); }
      else this.renderCandidateCaptures(comparison, candidate, packet, { historical });
    }
  }
  renderCandidateCaptures(root, candidate, packet, { historical = this.isHistoricalJob(this.job) } = {}) {
    const context = this.captureSelectionContext(), jobId = this.job.id, projectId = this.job.projectId;
    const panel = el('section', 'candidate-captures reference-editor');
    const captureKey = this.candidateCaptureKey(candidate, packet, historical);
    panel.dataset.captureKey = captureKey || '';
    panel.append(el('h4', '', '本候选运行画面'), el('p', 'muted', '画面由用户或操作员提供，采集条件未独立验证。仅在场景、视口、相机与状态可比时人工对照；静态图不证明规则与手感。'));
    const results = el('div', 'visual-reference-grid'); results.append(el('p', 'muted', '正在读取本候选采集；没有画面时视觉符合尚未验证。')); panel.append(results); root.append(panel);
    const current = () => panel.isConnected && this.selectionContextMatches(context) && this.job?.id === jobId
      && captureKey != null && this.candidateCaptureKey(this.job?.candidate || this.job?.response?.candidate || candidate,
        this.packetForCandidate(this.job, this.job?.candidate || this.job?.response?.candidate || candidate)) === captureKey;
    const show = captures => {
      releaseVisuals(results); results.replaceChildren();
      if (!captures.length) results.append(el('p', 'notice', '尚未保存本候选运行画面，视觉符合未验证。'));
      for (const capture of captures) {
        if (capture.candidateId !== candidate.id || capture.jobId !== jobId || capture.packetId !== packet.id || capture.projectId !== projectId) continue;
        mountVisual(results, { title: '操作员提供的候选截图', status: '采集条件未独立验证',
          references: [{ key: capture.id, url: `${API}/projects/${encodeURIComponent(projectId)}/assets/${encodeURIComponent(capture.asset.id)}`, intent: '运行采集 · 按以下条件人工核对', kind: 'capture', dimensions: `${capture.asset.width} × ${capture.asset.height}` }],
          rows: Object.entries(capture.conditions).map(([key, value]) => ({ label: ({ scene: '场景', viewport: '视口', camera: '相机', state: '状态/操作', capturedAt: '采集时点' })[key], value })),
          details: [{ label: '候选 Git', value: capture.candidateCommit }, { label: '采集编号', value: capture.id }] }, `capture:${capture.id}`);
      }
    };
    let loading = false, readVersion = 0;
    panel.refreshCaptures = async () => {
      if (loading || !current()) return;
      const version = ++readVersion; loading = true;
      try {
        const value = await this.request(`/candidates/${encodeURIComponent(candidate.id)}/visuals`, { projectId });
        if (current() && version === readVersion) show(value.captures || []);
      } catch (error) { if (current() && version === readVersion) results.textContent = `画面读取失败：${error.message}。视觉符合未验证。`; }
      finally { if (version === readVersion) loading = false; }
    };
    panel.refreshCaptures();
    if (historical || this.job.status !== 'READY_FOR_REVIEW') return;
    const form = el('form', 'candidate-capture-form');
    const file = el('input'); file.type = 'file'; file.accept = 'image/png,image/jpeg,image/webp'; file.setAttribute('aria-label', '本候选截图文件'); file.required = true; form.append(file);
    const inputs = {};
    for (const [key, label] of [['scene', '场景'], ['viewport', '视口'], ['camera', '相机'], ['state', '状态/操作'], ['capturedAt', '采集时点']]) {
      const field = el('label', 'field-label', label), input = el('input'); input.required = true; input.maxLength = 500; input.placeholder = '请填写实际条件；不清楚时明确填写未知'; input.setAttribute('aria-label', `截图${label}`); inputs[key] = input; field.append(input); form.append(field);
    }
    const submit = el('button', 'button secondary', '保存此候选截图与采集条件'); submit.type = 'submit'; form.append(submit);
    let pending = null;
    form.addEventListener('submit', async event => {
      event.preventDefault(); if (!current() || submit.disabled || !file.files?.[0]) return;
      submit.disabled = true;
      const controls = [file, ...Object.values(inputs)]; controls.forEach(input => { input.disabled = true; });
      const conditions = Object.fromEntries(Object.entries(inputs).map(([key, input]) => [key, input.value]));
      try {
        const image = file.files[0]; if (image.size > 5 * 1024 * 1024) throw new Error('截图不得超过 5 MB');
        const dataBase64 = await new Promise((resolve, reject) => { const reader = new FileReader(); reader.onload = () => resolve(String(reader.result).split(',')[1]); reader.onerror = () => reject(reader.error || new Error('读取截图失败')); reader.readAsDataURL(image); });
        if (!current()) return;
        const body = { name: image.name, mimeType: image.type, dataBase64, conditions };
        if (!pending || !sameValue(pending.body, body)) pending = { id: crypto.randomUUID(), body };
        await this.request(`/candidates/${encodeURIComponent(candidate.id)}/visuals`, { projectId, method: 'POST', token: true, body: { requestId: pending.id, ...body } });
        if (!current()) return;
        readVersion++; loading = false;
        const value = await this.request(`/candidates/${encodeURIComponent(candidate.id)}/visuals`, { projectId });
        if (current()) { show(value.captures || []); pending = null; form.reset(); }
      } catch (error) { if (current()) this.notify(`截图保存未确认：${error.message}。保留原文件与条件，可用原内容重试。`); }
      finally { if (current()) { submit.disabled = false; controls.forEach(input => { input.disabled = false; }); } }
    }); panel.append(form);
  }
  renderCandidateButtons(candidate, commit, feedback = []) {
    const area = $('#candidate-area'), prior = area.querySelector('.candidate-review-actions'); prior?.remove();
    if (this.isHistoricalJob(this.job)) return;
    const group = el('section', 'candidate-review-actions'), review = el('div', 'decision-actions'), testing = !!this.workspace?.testData;
    const complete = !this.usesV1Commands(this.projectId) || feedback.every(item => item.feedbackId && ['resolved', 'needs_followup'].includes(this.experienceDecisions?.[item.feedbackId]) && typeof this.experienceDecisionReasons?.[item.feedbackId] === 'string' && this.experienceDecisionReasons[item.feedbackId].trim());
    const candidateId = candidate.id || this.job?.candidateId;
    const accept = el('button', 'button primary', testing ? '接受为测试工作区当前版本' : '接受为当前版本'); accept.type = 'button'; accept.disabled = !this.reviewSnapshotMatchesJob() || !candidateId || !complete; accept.addEventListener('click', () => this.decideCandidate('accept', commit, candidateId, feedback));
    const reject = el('button', 'button danger', testing ? '继续修改此测试候选' : '继续修改此候选'); reject.type = 'button'; reject.disabled = !this.reviewSnapshotMatchesJob() || !candidateId; reject.addEventListener('click', () => this.decideCandidate('reject', commit, candidateId, feedback));
    review.append(accept, reject); group.append(review, el('p', 'muted', '“当前版本”指本机服务记录为已接受的发布版本；尚未接受的候选不会替换它。'));
    const details = area.querySelector('.candidate-supporting-details');
    area.insertBefore(group, details || null);
  }
  async previewCandidate(candidate = this.job?.candidate) {
    if (!this.job?.id) return;
    if (this.isHistoricalJob(this.job)) return this.notify('这是历史制作候选；请从当前方案关联的候选结果启动预览。');
    const candidateId = candidate?.id || this.job?.candidateId;
    if (this.usesV1Commands(this.job.projectId) && !candidateId) return this.notify('候选结果缺少可核对的候选编号；没有启动预览。');
    const status = el('p', 'muted', '正在请求本机 Godot 打开已验证的候选版本…'); $('#candidate-area').append(status);
    try {
      const response = this.usesV1Commands(this.job.projectId)
        ? await this.sendCommand('preview.start', { candidateId }, { expected: { publicationRevision: this.snapshot?.publicationRevision } })
        : await this.request(`/jobs/${encodeURIComponent(this.job.id)}/preview`, { method: 'POST', token: true, body: {} });
      if (response.preview?.id) {
        this.previews = [...this.previews.filter(item => item.id !== response.preview.id), response.preview];
        if (this.job?.candidate || this.job?.response?.candidate) this.renderJob();
      }
      status.textContent = `${response.message || '本机 Godot 已接受运行请求。'}${response.sourceCommit ? ` · Git ${response.sourceCommit}` : ''}`;
      status.className = 'success-notice';
    } catch (error) { status.textContent = `运行预览没有确认：${error.message}`; status.className = 'notice'; }
  }
  previewMatchesCandidate(preview, job = this.job, candidate = job?.candidate || job?.response?.candidate) {
    const ref = preview?.artifactRef;
    if (!job?.id || !candidate || preview?.projectId !== job.projectId || !ref || ref.jobId !== job.id) return false;
    if (ref.projectId && ref.projectId !== job.projectId) return false;
    const packetId = job.packetId || candidate.packetId;
    if (packetId && ref.packetId !== packetId) return false;
    const commit = candidate.candidateCommit || candidate.commit;
    return !!commit && ref.sourceCommit === commit;
  }
  renderPreviewControls(area = $('#candidate-area')) {
    if (!area || !this.previews?.length) return;
    const section = el('section', 'preview-sessions'); section.append(el('h4', '', '本候选预览'));
    const history = el('details', 'preview-history'); history.append(el('summary', '', '其他候选或版本的预览记录'));
    let matched = false;
    for (const preview of this.previews) {
      if (!preview?.id || preview.projectId !== this.projectId) continue;
      const row = el('div', 'preview-session');
      row.append(el('span', '', `预览 ${preview.id} · ${preview.status || '状态未知'}`));
      const current = this.previewMatchesCandidate(preview);
      if (!current) row.append(el('p', 'meta-line', `其他候选或版本 · 作业 ${preview.artifactRef?.jobId || '身份未提供'} · Git ${preview.artifactRef?.sourceCommit || '未知'}`));
      if (['QUEUED', 'RUNNING', 'STARTING', 'STOP_REQUESTED', 'CANCEL_REQUESTED', 'UNKNOWN', 'UNCERTAIN'].includes(preview.status)) {
        const stopping = ['STOP_REQUESTED', 'CANCEL_REQUESTED'].includes(preview.status);
        const stop = el('button', 'button danger', stopping ? '正在停止…' : '停止预览');
        stop.type = 'button'; stop.disabled = stopping || !this.projectView?.allowedActions?.includes('preview.stop');
        stop.addEventListener('click', () => this.stopPreview(preview.id, stop)); row.append(stop);
      }
      if (current) { matched = true; section.append(row); } else history.append(row);
    }
    if (!matched) section.append(el('p', 'muted', '本候选尚无匹配的预览记录。'));
    if (history.childElementCount > 1) section.append(history);
    area.append(section);
  }
  async stopPreview(previewId, button) {
    if (!this.usesV1Commands(this.projectId) || !previewId) return;
    button.disabled = true;
    try {
      const result = await this.sendCommand('preview.stop', { previewId });
      this.previews = this.previews.map(item => item.id === previewId ? result.preview : item);
      if (this.job?.candidate || this.job?.response?.candidate) this.renderJob();
      await this.ensureWorkbench(this.projectId, true);
    } catch (error) {
      button.disabled = false; this.notify(`停止预览未确认：${error.message}`);
    }
  }
  async decideCandidate(decision, candidateCommit, candidateId = this.job?.candidateId || this.job?.candidate?.id, feedback = this.proposalForJob(this.job)?.changeRequest?.feedback || []) {
    if (!this.job?.id || this.isHistoricalJob(this.job) || !this.reviewSnapshotMatchesJob()) return;
    const context = this.captureSelectionContext(), jobId = this.job.id, expectedRevision = this.snapshot.publicationRevision, generation = ++this.jobMutationGeneration;
    const testing = !!this.workspace?.testData;
    const label = testing ? (decision === 'accept' ? '接受测试候选为测试工作区当前版本' : '继续修改此测试候选') : (decision === 'accept' ? '接受为当前版本' : '继续修改此候选');
    if (typeof globalThis.confirm === 'function' && !globalThis.confirm(`确认${label}候选版本 ${candidateCommit}？`)) return;
    try {
      const experienceDecisions = feedback.map(item => ({ feedbackId: item.feedbackId, status: this.experienceDecisions?.[item.feedbackId] || 'needs_followup', reason: this.experienceDecisionReasons?.[item.feedbackId]?.trim() || '' }));
      const response = this.usesV1Commands(this.job.projectId)
        ? await this.sendCommand(decision === 'accept' ? 'candidate.accept' : 'candidate.reject', { candidateId, sourceCommit: candidateCommit, experienceDecisions: decision === 'accept' ? experienceDecisions : experienceDecisions.filter(item => item.reason) }, { expected: { publicationRevision: expectedRevision, preferencesRevision: this.sessionPreferences?.revision } })
        : await this.request(`/jobs/${encodeURIComponent(jobId)}/decision`, { method: 'POST', token: true, body: { decision, candidateCommit, expectedPublicationRevision: expectedRevision } });
      if (!this.selectionContextMatches(context) || generation !== this.jobMutationGeneration || this.job?.id !== jobId) return;
      this.job = response.job || this.job;
      // Reload the authoritative repair context after either decision.
      this.renderJob();
      if (this.job.projectId && this.selectionContextMatches(context)) await this.loadWorkbench(this.job.projectId);
      this.notify(testing ? `服务已记录${label}；此结果属于测试工作区。` : (decision === 'accept' ? '服务已记录接受决定；请核对本机已接受的当前发布版本。' : '已记录继续修改决定；候选保留为返修基线，请填写问题与调整后重新策划。'));
    } catch (error) { if (this.selectionContextMatches(context) && generation === this.jobMutationGeneration && this.job?.id === jobId) this.notify(`决定未被确认：${error.message}${error.status === 409 ? ' 版本已变化，请刷新并重新审阅。' : ''}`); }
  }
  reviewSnapshotMatchesJob() { return !!this.job?.projectId && this.projectId === this.job.projectId && this.snapshotMatchesProject(this.job.projectId); }
  beginPolling() { this.stopPolling(); if (!this.job?.id || (this.protocolVersion && this.streamFresh)) return; this.pollHandle = this.timers.setInterval(() => this.loadJob(this.job.id, false), this.protocolVersion ? 10000 : 2500); }
  stopPolling() { if (this.pollHandle != null) this.timers.clearInterval(this.pollHandle); this.pollHandle = null; }
  async cancelJob() {
    if (!this.job?.id) return; const context = this.captureSelectionContext(), jobId = this.job.id, generation = ++this.jobMutationGeneration; $('#cancel').disabled = true;
    try { const attemptId = this.job?.attemptId || this.observations?.attemptId; const response = this.usesV1Commands(this.job.projectId)
      ? await this.sendCommand('execution.cancel', { ownerRef: { kind: 'job', id: jobId }, attemptId })
      : await this.request(`/jobs/${encodeURIComponent(jobId)}/cancel`, { method: 'POST', token: true, body: {} }); if (!this.selectionContextMatches(context) || generation !== this.jobMutationGeneration || this.job?.id !== jobId) return; this.job = response.job || this.job; this.renderJob(); }
    catch (error) { if (this.selectionContextMatches(context) && generation === this.jobMutationGeneration && this.job?.id === jobId) this.notify(`取消请求没有确认：${error.message}`); }
    finally { if (this.selectionContextMatches(context) && generation === this.jobMutationGeneration) $('#cancel').disabled = false; }
  }
  async reconcileJob() {
    if (!this.job?.id) return; const context = this.captureSelectionContext(), jobId = this.job.id, generation = ++this.jobMutationGeneration;
    $('#reconcile').disabled = true;
    try { const attemptId = this.job?.attemptId || this.observations?.attemptId; const response = this.usesV1Commands(this.job.projectId)
      ? await this.sendCommand('execution.reconcile', { ownerRef: { kind: 'job', id: jobId }, attemptId })
      : await this.request(`/jobs/${encodeURIComponent(jobId)}/reconcile`, { method: 'POST', token: true, body: {} }); if (!this.selectionContextMatches(context) || generation !== this.jobMutationGeneration || this.job?.id !== jobId) return; this.job = response.job || this.job; this.renderJob(); }
    catch (error) { if (this.selectionContextMatches(context) && generation === this.jobMutationGeneration && this.job?.id === jobId) this.notify(`对账结果未确认：${error.message}。系统不会自动重新派发。`); }
    finally { if (this.selectionContextMatches(context) && generation === this.jobMutationGeneration) $('#reconcile').disabled = false; }
  }
  async loadWorkbench(projectId, { force = false } = {}) {
    if (this.destroyed) return null;
    const generation = ++this.workbenchGeneration;
    const previous = this.snapshot;
    const switchingProject = previous && (previous.projectId || previous.id) !== projectId;
    this.beginDraftConflictRefresh(generation, projectId, previous);
    let priorDraft = previous ? cloneValue(this.readVisibleDraft()) : null;
    if (this.draftTimer != null) {
      this.timers.clearTimeout(this.draftTimer); this.draftTimer = null; await this.saveDraft();
      if (generation === this.workbenchGeneration && this.snapshot === previous && previous) priorDraft = this.readVisibleDraft();
      if (this.destroyed || generation !== this.workbenchGeneration || this.projectId !== projectId) return null;
    }
    if (!previous || switchingProject) $('#edit-text').value = '';
    let response;
    try {
      response = this.protocolVersion ? await this.request(`/v1/projects/${encodeURIComponent(projectId)}/view`) : await this.request(`/projects/${encodeURIComponent(projectId)}/workbench`);
      if (this.destroyed || generation !== this.workbenchGeneration || this.projectId !== projectId) return null;
      if (this.protocolVersion && (response.schemaVersion !== 'studio.project-view.v1' || response.storeId !== this.handshake?.storeId || response.projectId !== projectId)) throw new Error('公开项目视图的版本、存储或项目身份不匹配。');
    } catch (error) {
      if (!this.destroyed && generation === this.workbenchGeneration) this.finishDraftConflictRefresh(generation, previous, { error });
      throw error;
    }
    if (generation !== this.workbenchGeneration || this.projectId !== projectId || !this.workspace?.projects?.some(project => project.id === projectId)) return null;
    // The fetch can take long enough for the user to keep editing the old version.
    // Capture those edits after the response arrives but before replacing the old
    // snapshot, so the existing explicit rebase previews the actual visible draft.
    if (previous && (previous.projectId || previous.id) === projectId && this.snapshot === previous) {
      if (this.draftTimer != null) {
        this.timers.clearTimeout(this.draftTimer); this.draftTimer = null; await this.saveDraft();
        if (generation !== this.workbenchGeneration || this.snapshot !== previous || this.projectId !== projectId) return null;
      }
      priorDraft = cloneValue(this.readVisibleDraft());
    }
    const projectSummary = response.project || this.currentProject() || this.workspace?.projects?.find(p => p.id === projectId);
    const loadedSnapshot = response.repairContext || response.snapshot || { projectId, publicationRevision: projectSummary?.publicationRevision ?? response.publicationRevision ?? 0, workflow: projectSummary?.workflow || response.workflow || 'objects-v1', kind: 'CONCEPT', playable: false, sourceCommit: null, baseCommit: null, catalog: { objects: [] }, document: { objects: [] } };
    if ((loadedSnapshot.projectId || loadedSnapshot.id) !== projectId) {
      const error = new Error('服务返回的项目版本与所选项目不匹配。');
      this.finishDraftConflictRefresh(generation, previous, { error });
      throw error;
    }
    const sameProject = previous && (previous.projectId || previous.id) === projectId;
    const publicationChanged = sameProject && this.makeDraftKey(previous) !== this.makeDraftKey(loadedSnapshot);
    const willRestoreDraft = !sameProject || (publicationChanged && loadedSnapshot.kind === 'REPAIR');
    if (!sameProject || publicationChanged) this.fieldDraftValues = {};
    this.snapshot = loadedSnapshot; this.finishDraftConflictRefresh(generation, loadedSnapshot, { preservedDraft: priorDraft }); this.capabilities = loadedSnapshot.catalog?.capabilities ? { fields: loadedSnapshot.catalog.capabilities } : response.capabilities || this.snapshot.capabilities || null; this.workflow = this.snapshot.workflow || response.workflow || this.workspace?.projects?.find(p => p.id === projectId)?.workflow || null; this.candidates = response.candidates || [];
    if (publicationChanged && !this.assets.length && !Object.keys(this.referenceIntents).length) {
      this.restoreBaselineReferences(loadedSnapshot);
      // Persist inherited selection with the accepted baseline before reload can
      // restore an older, empty concept draft. Explicit saved removals still win.
      if (this.persistenceOK) await this.saveConceptDraft(projectId);
      if (generation !== this.workbenchGeneration || this.projectId !== projectId) return null;
    }
    if (willRestoreDraft && this.persistenceOK && this.makeDraftKey(loadedSnapshot)) this.beginDraftRestore(generation, loadedSnapshot);
    else this.draftRestoreContext = null;
    // Legacy workbench views have no projectId, so applyProjectView intentionally
    // ignores them. Keep their per-item outcomes explicitly for this project.
    this.workbenchResults = Array.isArray(response.workbenchResults) ? response.workbenchResults : [];
    this.workspace.repairContext = response.repairContext || null;
    if (loadedSnapshot.kind === 'REPAIR') { this.stage = 'iteration'; this.updateUrl(); }
    this.applyProjectView(response);
    if (typeof response.iterationReady === 'boolean') this.workspace.iterationReady = response.iterationReady;
    if (response.iterationReadyReason) this.workspace.iterationReadyReason = response.iterationReadyReason;
    if (typeof response.iterationReadyTestOnly === 'boolean') this.workspace.iterationReadyTestOnly = response.iterationReadyTestOnly;
    if (this.pendingRebase) {
      if (this.sameRebaseTarget(this.pendingRebase, loadedSnapshot)) {
        // A later refresh can return a fresh object for the exact same published
        // snapshot. Rebind the reviewed rebase to this load instead of discarding
        // it; otherwise a duplicate refresh silently loses the only copy of the
        // old-version draft.
        this.pendingRebase.nextSnapshot = loadedSnapshot;
        this.pendingRebase.generation = generation;
      } else {
        this.pendingRebase = null;
        const dialog = $('#rebase-dialog'); if (dialog?.open) dialog.close();
      }
    }
    if (this.projectId !== projectId) return null;
    hide($('#workbench-panel'), false); this.renderWorkbench();
    if (this.objectsWorkflow()) this.legacyWorkbench.applyInitialRoute();
    const changed = previous && (previous.projectId || previous.id) === (this.snapshot.projectId || this.snapshot.id) && this.makeDraftKey(previous) !== this.makeDraftKey(this.snapshot);
    if (changed) {
      $('#edit-text').value = '';
      const oldKey = this.makeDraftKey(previous);
      const carryDraft = this.unrebasedDraft?.projectId === (previous.projectId || previous.id) ? this.unrebasedDraft.draft : priorDraft;
      if (this.snapshot.kind === 'REPAIR') {
        // Submitted feedback stays on its old draft; each rejected candidate gets a fresh repair draft.
        this.feedback = []; this.fieldDraftValues = {}; this.dirtyFields.clear();
        $('#feedback-message').value = ''; this.renderWorkbench();
        await this.restoreDraft(generation);
      } else if (this.hasUnsubmittedDraft(carryDraft)) this.handleRebase(previous, this.snapshot, carryDraft);
      else await this.restoreDraft(generation);
    } else if (!previous || (previous.projectId || previous.id) !== (this.snapshot.projectId || this.snapshot.id)) await this.restoreDraft(generation);
    if (generation !== this.workbenchGeneration || (this.snapshot.projectId || this.snapshot.id) !== projectId) return null;
    this.renderCandidates();
    if (this.job?.candidate || this.job?.response?.candidate) this.renderJob();
  }
  applyProjectView(view) {
    if (!view || view.projectId !== this.projectId) return;
    this.projectView = view; this.observations = view.observations || null;
    if (this.visualPlanning?.open && this.visualPlanning.archived !== this.visualProjectArchived()) {
      this.visualPlanning.archived = this.visualProjectArchived();
      this.renderVisualPlanningPanel();
    }
    if (Object.hasOwn(view, 'job') && (!this.selectedJobForProject() || view.job?.id === this.selectedJobForProject())) this.job = view.job;
    if (view.proposals) this.workspace.proposals = view.proposals;
    if (view.packets) this.workspace.packets = view.packets;
    if (view.jobs) this.workspace.jobs = view.jobs;
    // Planner completion can fall between the refresh and workbench reads.
    // Apply the selected proposal before advancing the view's event cursor.
    const selected = this.proposal;
    const latest = selected && view.proposals?.find(item => item.id === selected.id && item.projectId === this.projectId);
    if (latest && Number(latest.revision) >= Number(selected.revision) && !sameValue(latest, selected)) {
      this.proposal = latest; this.packet = latest.status === 'FROZEN' ? this.packetFor(latest) : null;
      this.renderProposal(); if (this.packet) this.renderFrozenPacket();
    }
    if (Number.isInteger(view.throughSequence)) this.eventSequence = Math.max(this.eventSequence || 0, view.throughSequence);
    if (view.candidates) this.candidates = view.candidates;
    this.previews = Array.isArray(view.previews) ? view.previews : [];
    if (view.sessionPreferences || view.preferences) this.sessionPreferences = view.sessionPreferences || view.preferences;
    if (view.sessionCatalog || view.catalog) this.sessionCatalog = view.sessionCatalog || view.catalog;
    if (view.jobs) this.renderWorkspace();
    this.renderWorkflowStages(); this.renderExecutionMonitor(); this.renderSessionSettings(); this.applyReadinessGate();
  }
  async loadSessionSettings(projectId, generation = this.selectionGeneration) {
    const [prefEnvelope, catalog] = await Promise.all([
      this.request(`/v1/projects/${encodeURIComponent(projectId)}/session-preferences`, { projectId: null }),
      this.request(`/v1/projects/${encodeURIComponent(projectId)}/session-catalog`, { projectId: null }),
    ]);
    if (generation !== this.selectionGeneration || this.projectId !== projectId) return;
    if (prefEnvelope.schemaVersion !== 'studio.message.v1' || prefEnvelope.kind !== 'preferences' || prefEnvelope.storeId !== this.handshake.storeId || prefEnvelope.projectId !== projectId) throw new Error('策划/制作偏好响应身份不匹配。');
    if (catalog.schemaVersion !== 'studio.message.v1' || catalog.storeId !== this.handshake.storeId || catalog.projectId !== projectId) throw new Error('模型目录响应身份不匹配。');
    this.sessionPreferences = prefEnvelope.preferences; this.sessionCatalog = catalog; this.renderSessionSettings();
  }
  stopEventStream() {
    this.streamGeneration++; this.streamController?.abort(); this.streamController = null;
    if (this.streamAttemptTimeout != null) this.timers.clearTimeout(this.streamAttemptTimeout); this.streamAttemptTimeout = null;
    if (this.streamRetry != null) this.timers.clearTimeout(this.streamRetry); this.streamRetry = null; this.streamFresh = false; this.streamReconnecting = false; this.streamProjectId = null; this.streamConnect = null; this.streamPaused = false;
  }
  startEventStream(projectId, after = 0) {
    this.stopEventStream(); const generation = this.streamGeneration; this.eventSequence = Number(after) || 0; this.streamProjectId = projectId;
    const connect = async () => {
      if (generation !== this.streamGeneration || this.destroyed || this.projectId !== projectId) return;
      const controller = new AbortController(); this.streamController = controller;
      let reader, attemptExpired = false, streamOpened = false, streamFailed = false, refreshRequest = null, attemptTimeout, finishAttempt;
      const attemptDone = new Promise(resolve => { finishAttempt = resolve; }); this.streamAttemptDone = attemptDone;
      const isCurrent = () => generation === this.streamGeneration && !this.destroyed && this.projectId === projectId;
      // The server sends keepalives every 15 seconds. Bound inactivity, not
      // the lifetime of a healthy connection, and renew on each received chunk.
      const renewTimeout = () => {
        if (attemptTimeout != null) this.timers.clearTimeout(attemptTimeout);
        attemptTimeout = this.timers.setTimeout(() => {
          attemptExpired = true;
          controller.abort();
          try { void reader?.cancel?.(); } catch {}
        }, 20000);
        this.streamAttemptTimeout = attemptTimeout;
      };
      renewTimeout();
      try {
        const url = `${API}/v1/projects/${encodeURIComponent(projectId)}/events?after=${encodeURIComponent(this.eventSequence)}`;
        const response = await this.fetch(url, { headers: { Accept: 'text/event-stream', 'X-Workbench-Token': this.token, ...(this.eventSequence ? { 'Last-Event-ID': String(this.eventSequence) } : {}) }, signal: controller.signal });
        if (!isCurrent() || controller.signal.aborted) return;
        if (response.status === 401 || response.status === 403) refreshRequest = { kind: 'auth' };
        else if (response.status === 409) refreshRequest = { kind: 'resync' };
        else if (!response.ok || !response.body?.getReader) throw new Error(`状态流返回 ${response.status || '无效响应'}`);
        else {
          renewTimeout();
          streamOpened = true; this.streamFresh = true; this.streamReconnecting = false; this.stopPolling(); this.stopProposalPolling(); this.renderWorkflowStatus(); reader = response.body.getReader(); const decoder = new TextDecoder(); let buffer = '';
          let resync = false;
          while (isCurrent() && !controller.signal.aborted && !resync) {
            const { value, done } = await reader.read(); if (!isCurrent() || controller.signal.aborted || done) break; renewTimeout(); buffer += decoder.decode(value, { stream: true });
            let boundary; while ((boundary = buffer.indexOf('\n\n')) >= 0) {
              const frame = buffer.slice(0, boundary); buffer = buffer.slice(boundary + 2);
              const lines = frame.split(/\r?\n/), eventName = lines.find(line => line.startsWith('event:'))?.slice(6).trim();
              const dataLine = lines.find(line => line.startsWith('data:'))?.slice(5).trim(); const idLine = lines.find(line => line.startsWith('id:'))?.slice(3).trim();
              const frameSequence = idLine && /^\d+$/.test(idLine) ? Number(idLine) : null;
              if (eventName === 'resync_required') { refreshRequest = { kind: 'resync' }; resync = true; break; }
              if (!dataLine) continue;
              let event; try { event = JSON.parse(dataLine); } catch { throw new Error('状态流包含非法 JSON。'); }
              if (event.schemaVersion !== 'studio.message.v1' || event.kind !== 'event' || event.storeId !== this.handshake.storeId || event.projectId !== projectId || !Number.isInteger(event.sequence)) throw new Error('状态流事件身份或序号不匹配。');
              if (event.sequence <= this.eventSequence) continue;
              if (event.sequence !== this.eventSequence + 1) { refreshRequest = { kind: 'resync' }; resync = true; break; }
              if (frameSequence != null && frameSequence !== event.sequence) throw new Error('状态流事件 ID 与事件序号不匹配。');
              if (event.type === 'project.changed') {
                refreshRequest = { kind: 'event', sequence: event.sequence }; resync = true; break;
              }
              this.eventSequence = Math.max(this.eventSequence, event.sequence);
            }
          }
        }
      } catch (error) {
        streamFailed = true;
        if (isCurrent() && !controller.signal.aborted) { this.streamFresh = false; this.streamReconnecting = false; this.renderWorkflowStatus(); }
      } finally {
        // Release this bounded attempt before a resync GET or the next attempt.
        if (attemptTimeout != null) this.timers.clearTimeout(attemptTimeout);
        if (this.streamController === controller) this.streamController = null;
        if (this.streamAttemptTimeout === attemptTimeout) this.streamAttemptTimeout = null;
        controller.abort();
        try { await reader?.cancel(); } catch {}
        reader?.releaseLock?.();
        const ownsAttempt = generation === this.streamGeneration && this.streamAttemptDone === attemptDone && this.streamProjectId === projectId && !this.destroyed && this.projectId === projectId;
        if (this.streamAttemptDone === attemptDone) this.streamAttemptDone = null;
        finishAttempt();
        if (ownsAttempt) {
          this.streamFresh = false;
          this.streamReconnecting = streamOpened && !streamFailed && !attemptExpired && (!refreshRequest || refreshRequest.kind === 'event');
          this.beginPolling(); if (PLANNING.has(this.proposal?.status)) this.startProposalPolling();
          this.renderWorkflowStatus();
        }
      }
      if (!isCurrent()) return;
      if (refreshRequest && !attemptExpired) {
        try {
          if (refreshRequest.kind === 'auth') {
            const fresh = await this.request('/v1/handshake', { projectId: null });
            if (!isCurrent()) return;
            if (fresh.schemaVersion !== 'studio.message.v1' || fresh.kind !== 'handshake' || fresh.storeId !== this.handshake?.storeId || !fresh.serviceInstanceId || typeof fresh.writeToken !== 'string' || !fresh.writeToken || fresh.readable !== true) throw new Error('状态流重新握手身份不匹配；当前项目保持待核实。');
            this.handshake = fresh; this.token = fresh.writeToken;
          }
          const previousSequence = this.eventSequence;
          if (!await this.refresh({ announce: false, streamReleased: true })) throw new Error('状态流恢复读取失败。');
          if (!isCurrent()) return;
          const throughSequence = Number(this.projectView?.throughSequence);
          if (Number.isInteger(throughSequence) && throughSequence >= previousSequence) {
            if (refreshRequest.kind !== 'event' || throughSequence >= refreshRequest.sequence) this.eventSequence = throughSequence;
          }
        } catch {
          // Keep the last successfully applied sequence so reconnect replays it.
          if (isCurrent()) this.streamReconnecting = false;
        }
      }
      if (!isCurrent()) return;
      this.renderWorkflowStatus();
      if (!this.streamPaused) this.streamRetry = this.timers.setTimeout(() => { this.streamRetry = null; return connect(); }, 1200);
    };
    this.streamConnect = connect;
    connect();
  }
  renderExecutionMonitor() {
    const root = $('#execution-monitor'), content = $('#execution-monitor-content'); if (!root || !content) return;
    const obs = this.observations; if (!obs) { hide(root); return; }
    this.executionDetailState ||= new Map();
    const oldDetails = content.querySelector('.execution-technical');
    if (oldDetails) this.executionDetailState.set(oldDetails.dataset.scope, oldDetails.open);
    releaseVisuals(content); content.replaceChildren();
    const preview = obs.taskKind === 'preview' ? this.previews?.find(item => item.projectId === this.projectId && item.attemptId === obs.attemptId) : null;
    const activeOwnerAttempt = ACTIVE.has(this.job?.status) && (this.job.status !== 'READY_FOR_REVIEW' || !preview) ? this.job?.attemptId : PLANNING.has(this.proposal?.status) ? this.proposal?.attemptId : null;
    if (activeOwnerAttempt && obs.attemptId !== activeOwnerAttempt) {
      content.append(el('p', 'notice', '服务观察到的执行代次与当前作业/策划编号不匹配；此处不显示另一代次的运行状态。'));
      hide(root, false); return;
    }
    if (obs.taskKind === 'preview') {
      if (!preview) { content.append(el('p', 'notice', '此执行代次缺少匹配的预览记录，无法确认预览对象。')); hide(root, false); return; }
      content.append(el('p', 'meta-line', `${this.previewMatchesCandidate(preview) ? '本候选预览' : '其他候选或版本的预览'} · ${preview.id} · 作业 ${preview.artifactRef?.jobId || '身份未提供'} · Git ${preview.artifactRef?.sourceCommit || '未知'}`));
    }
    const activity = obs.taskKind === 'preview' && obs.lastActivity?.activityKind === 'preview_started'
      ? 'Godot 已在隔离的候选副本中启动预览。'
      : obs.lastActivity?.summary === 'Native session activity observed.' ? '已观察到原生执行活动；未提供具体阶段。' : obs.lastActivity?.summary;
    const rows = [['阶段', this.projectView?.phase], ['步骤', this.projectView?.step], ['待处理', this.projectView?.attention], ['任务', obs.taskKind], ['执行状态', obs.status], ['Runner', obs.runner?.runnerId], ['Runner 心跳', obs.runner?.lastHeartbeatAt], ['最后活动', activity || obs.lastActivity?.activityKind], ['请求配置', obs.requested ? JSON.stringify(obs.requested) : null], ['实际配置', obs.actualProfile ? JSON.stringify(obs.actualProfile) : null], ['用量', obs.usage?.totalTokens == null ? '未知' : `${obs.usage.totalTokens} tokens · ${obs.usage.coverage || 'unknown'}`], ['停止原因', STOP_LABELS[obs.stopReason] || obs.stopReason], ['租约截止', obs.leaseExpiresAt]];
    const list = el('dl', 'execution-observations'); for (const [name, value] of rows) list.append(el('dt', '', name), el('dd', '', String(value ?? '未知')));
    const phaseLabels = { planning: '策划正在整理本轮要求', proposal_review: '完整方案已返回，等待你审阅', clarification: '策划需要补充信息', frozen: '方案已冻结，等待开始制作', producing: '制作执行器正在落实冻结方案', verifying: '独立执行器正在验证候选', candidate_review: '候选已返回，等待试玩与审阅', repair: '候选已保留，等待返修意见', accepted: '当前版本已接受，可准备下一轮', uncertain: '执行状态待核实' };
    const jobStatus = this.projectView?.job?.status || this.job?.status;
    const failed = ['FAILED', 'STOPPED', 'CANCELLED'].includes(obs.status) && !preview;
    const progress = preview ? ({ RUNNING: '本候选正在 Godot 中预览', STOPPED: '本候选预览已停止', STOP_REQUESTED: '已请求停止本候选预览', UNKNOWN: '本候选预览状态待核实', QUEUED: '本候选预览等待启动' }[preview.status] || `本候选预览：${preview.status}`)
      : failed ? `${obs.taskKind === 'plan' ? '策划' : obs.taskKind === 'verify' ? '独立验证' : '制作'}${obs.stopReason === 'time_limit' ? '达到时间上限' : obs.stopReason === 'soft_budget' ? '达到用量上限' : obs.status === 'FAILED' ? '执行失败' : '已停止'}，停止已确认`
        : this.job?.verificationFailure && obs.taskKind === 'verify' && obs.attemptId === this.job.verificationAttemptId ? '独立验证已完成检查，结果未通过'
        : ['QUEUED', 'DISPATCHING'].includes(jobStatus) ? '冻结方案正在等待制作执行器接单'
        : phaseLabels[this.projectView?.step] || jobLabel(this.job) || '等待服务提供本轮阶段';
    const nextByStep = { proposal_review: '阅读完整方案，确认范围与要求后再决定是否制作。', clarification: '回答尚未解决的问题，再查看完整方案。', frozen: '确认冻结输入后开始制作。', candidate_review: '运行本候选并逐项核对，再记录体验决定。', repair: '填写返修意见，重新策划并审阅。', accepted: '继续准备下一轮调整；已接受版本保留。', uncertain: '先核实当前执行状态，再决定后续操作。' };
    const next = preview?.status === 'STOPPED' ? '预览已停止；可回看该候选证据和体验记录。' : preview ? '预览启停以本候选运行记录为准。'
      : failed ? '查看执行诊断与停止状态，再手动准备新策划。'
        : nextByStep[this.projectView?.step] || (obs.taskKind === 'plan' ? '策划返回后，阅读完整方案并决定是否制作。' : obs.taskKind === 'produce' ? '制作结束后独立验证，再返回候选供你试玩。' : '技术检查结果返回后，仍需试玩核对玩法和视觉。');
    mountVisual(content, { title: '本轮执行进度', status: progress,
      rows: [{ label: '最近活动记录', value: activity || '尚无新的执行活动报告' },
        { label: '活动时间', value: obs.lastActivity?.observedAt || '尚未报告' },
        { label: '接下来', value: next }],
      details: [{ label: '执行代次', value: obs.attemptId }, { label: '执行状态', value: obs.status }] }, `execution:${obs.attemptId}`);
    const technical = el('details', 'execution-technical');
    technical.dataset.scope = `${this.storageId()}:${this.projectId}:${obs.attemptId}`;
    technical.open = this.executionDetailState.get(technical.dataset.scope) === true;
    technical.append(el('summary', '', '查看执行配置、用量与连接详情'), list); content.append(technical);
    const live = obs.runner?.online === true && this.projectView?.attention !== 'uncertain';
    const terminal = ['COMPLETED', 'FAILED', 'STOPPED', 'CANCELLED'].includes(obs.status);
    content.prepend(el('p', live ? 'success-notice' : 'notice', terminal ? '本执行代次已结束；以下保留最近活动与配置。Runner 心跳只说明执行器连接情况。' : live ? 'Runner 心跳已报告在线；回合活动和用量使用原生报告。' : '连接或执行状态待核实；此状态不能证明任务成功或失败。'));
    hide(root, false);
  }
  renderSessionSettings() {
    const root = $('#session-settings-content'); if (!root) return;
    const preferences = this.sessionPreferences, catalog = this.sessionCatalog;
    const scope = `${this.storageId() || ''}:${this.projectId || ''}`;
    if (this.sessionPreferenceScope !== scope) { this.sessionPreferenceScope = scope; this.sessionPreferenceDrafts = {}; this.sessionPreferenceSaving = new Set(); }
    // Project events and reconnects must not discard edits to unchanged settings.
    const renderKey = JSON.stringify([scope, preferences, catalog?.available, catalog?.runnerOnline, catalog?.catalogFresh, catalog?.models, [...this.sessionPreferenceSaving]]);
    if (root.dataset.renderKey === renderKey) return;
    root.dataset.renderKey = renderKey; root.replaceChildren();
    if (!preferences || !catalog) { root.append(el('p', 'muted', '服务尚未返回角色偏好或动态模型目录。')); return; }
    if (catalog.available === false) root.append(el('p', 'notice', catalog.runnerOnline === true && catalog.catalogFresh === false
      ? 'Runner 心跳在线，模型目录的上次观察已过期；当前任务继续使用冻结配置，新的执行等待目录重新观察。'
      : 'Runner 或模型目录当前不可用；草稿可继续编辑，执行设置不会自动替换。'));
    for (const role of ['planner', 'producer']) {
      const current = this.sessionPreferenceDrafts[role] || preferences.roles?.[role] || {}, section = el('section', 'session-role'); section.append(el('h3', '', role === 'planner' ? '策划' : '制作'));
      const model = el('select'); model.setAttribute('aria-label', `${role} 模型`);
      const models = (catalog.models || []).filter(item => item.available !== false && catalog.available !== false);
      for (const item of models) { const option = el('option', '', item.modelKey); option.value = item.modelKey; model.append(option); }
      const defaultModel = models.find(item => item.isDefault) || models[0];
      if (current.modelKey && !models.some(item => item.modelKey === current.modelKey)) {
        const unavailable = el('option', '', `${current.modelKey}（当前不可用，请重新选择）`); unavailable.value = current.modelKey; model.append(unavailable);
      }
      model.value = current.modelKey || defaultModel?.modelKey || '';
      const effort = el('select'); effort.setAttribute('aria-label', `${role} 推理档位`);
      const fillEfforts = (savedEffort = null) => {
        effort.replaceChildren(); const selected = models.find(item => item.modelKey === model.value);
        const values = (selected?.supportedReasoningEfforts || []).map(item => typeof item === 'object' ? item.reasoningEffort : item);
        for (const value of values) { const option = el('option', '', value); option.value = value; effort.append(option); }
        if (savedEffort && !values.includes(savedEffort)) { const option = el('option', '', `${savedEffort}（当前不可用）`); option.value = savedEffort; effort.append(option); }
        effort.value = savedEffort || selected?.defaultReasoningEffort || values[0] || '';
      };
      fillEfforts(current.effort); model.addEventListener('change', () => { fillEfforts(); remember(); });
      if (!current.modelKey) section.append(el('p', 'muted', defaultModel ? `尚未保存专用模型；服务当前默认 ${defaultModel.modelKey}。保存后才固定本页选择。` : '当前没有可用模型；原偏好保留。'));
      const duration = el('input'); duration.type = 'number'; duration.min = '1'; duration.max = '7200'; duration.value = current.limits?.maxDurationSeconds ?? 900; duration.setAttribute('aria-label', `${role}最长执行秒数`);
      const tokens = el('input'); tokens.type = 'number'; tokens.min = '0'; tokens.max = '2000000'; tokens.value = current.limits?.softTotalTokens ?? ''; tokens.placeholder = '不设置'; tokens.setAttribute('aria-label', `${role}软 token 阈值`);
      const remember = () => { this.sessionPreferenceDrafts[role] = { modelKey: model.value, effort: effort.value, limits: { maxDurationSeconds: Number(duration.value), softTotalTokens: tokens.value === '' ? null : Number(tokens.value) } }; };
      for (const input of [effort, duration, tokens]) for (const event of ['input', 'change']) input.addEventListener(event, remember);
      const save = el('button', 'button secondary', this.sessionPreferenceSaving.has(role) ? '正在保存…' : '保存角色偏好'); save.type = 'button'; save.disabled = this.sessionPreferenceSaving.has(role); save.addEventListener('click', () => this.saveSessionPreference(role, model.value, effort.value, { maxDurationSeconds: Number(duration.value), softTotalTokens: tokens.value === '' ? null : Number(tokens.value) }));
      section.append(el('label', 'field-label', '模型'), model, el('label', 'field-label', '推理档位'), effort, el('label', 'field-label', '最长执行时间（秒）'), duration, el('label', 'field-label', '软 token 阈值'), tokens, save); root.append(section);
    }
  }
  async saveSessionPreference(role, modelKey, effort, limits) {
    if (!modelKey || !effort) return this.notify('目录中没有可用的模型或推理档位。');
    if (!Number.isInteger(limits.maxDurationSeconds) || limits.maxDurationSeconds < 1 || limits.maxDurationSeconds > 7200 || (limits.softTotalTokens != null && (!Number.isInteger(limits.softTotalTokens) || limits.softTotalTokens < 0 || limits.softTotalTokens > 2000000))) return this.notify('最长执行时间或软 token 阈值超出服务允许范围。');
    this.sessionPreferenceSaving ||= new Set();
    if (this.sessionPreferenceSaving.has(role)) return;
    const projectId = this.projectId, generation = this.selectionGeneration, submitted = { modelKey, effort, limits };
    const selected = () => this.projectId === projectId && this.selectionGeneration === generation;
    this.sessionPreferenceDrafts ||= {}; this.sessionPreferenceDrafts[role] = cloneValue(submitted);
    const savingRoles = this.sessionPreferenceSaving;
    savingRoles.add(role); this.renderSessionSettings();
    const previous = this.sessionPreferenceSaveQueue || Promise.resolve();
    const saving = previous.catch(() => {}).then(async () => {
      try {
        if (!selected()) return;
        const result = await this.sendCommand('session.preferences.update', { role, ...submitted }, { projectId, expected: { preferencesRevision: this.sessionPreferences?.revision } });
        if (!selected()) return;
        this.sessionPreferences = result.sessionPreferences || result.preferences || this.sessionPreferences;
        if (sameValue(this.sessionPreferenceDrafts[role], submitted)) delete this.sessionPreferenceDrafts[role];
        this.notify('角色偏好已保存；已运行任务继续使用冻结配置。');
      } catch (error) { if (selected()) this.notify(`角色偏好未保存：${error.message}`); }
      finally { savingRoles.delete(role); if (this.sessionPreferenceSaving === savingRoles) this.renderSessionSettings(); }
    });
    this.sessionPreferenceSaveQueue = saving;
    await saving;
  }
  readVisibleDraft() {
    const values = {}; for (const key of TEMPLATE_FIELDS) { const input = this.parameterInput(key); if (input?.value) values[key] = Number(input.value); }
    this.saveFeedbackInputForCurrentTarget();
    if (this.objectsWorkflow()) {
      this.captureVisibleFields();
      this.serializingVisibleDraft = true;
      try { this.legacyWorkbench.persistCurrentNote(); }
      finally { this.serializingVisibleDraft = false; }
    }
    const activeFeedback = this.selectedObjectId ? this.feedbackInputs?.[this.selectedObjectId] : null;
    const feedbackMessage = activeFeedback?.message || this.legacyUnboundFeedback?.message || '';
    const feedbackCategory = activeFeedback?.category || this.legacyUnboundFeedback?.category || 'general';
    return {
      text: $('#edit-text')?.value || '', values: cloneValue(values), fields: cloneValue(this.fieldDraftValues || {}),
      feedback: cloneValue(this.feedback || []), feedbackInputs: cloneValue(this.feedbackInputs || {}),
      feedbackInputTargetId: activeFeedback?.message ? this.selectedObjectId : null,
      legacyUnboundFeedback: cloneValue(this.legacyUnboundFeedback),
      feedbackMessage, feedbackCategory, selectedObjectId: this.selectedObjectId,
      targetNotes: cloneValue(this.targetNotes || {}), structuralProposals: cloneValue(this.structuralProposals || []),
      proposalInputs: cloneValue(this.proposalInputs || {}), draftConflictAlternates: cloneValue(this.draftAlternates || []), draftRevision: this.draftRevision,
    };
  }
  applyVisibleDraft(draft) {
    this.feedback = Array.isArray(draft.feedback) ? cloneValue(draft.feedback) : [];
    this.feedbackInputs = draft.feedbackInputs && typeof draft.feedbackInputs === 'object' && !Array.isArray(draft.feedbackInputs) ? cloneValue(draft.feedbackInputs) : {};
    if (Object.hasOwn(draft, 'legacyUnboundFeedback')) this.legacyUnboundFeedback = draft.legacyUnboundFeedback && typeof draft.legacyUnboundFeedback === 'object' ? cloneValue(draft.legacyUnboundFeedback) : null;
    else if (String(draft.feedbackMessage || '').trim()) {
      const targetId = typeof draft.feedbackInputTargetId === 'string' ? draft.feedbackInputTargetId : null;
      if (targetId) this.feedbackInputs[targetId] ||= { message: String(draft.feedbackMessage), category: draft.feedbackCategory || 'general' };
      else this.legacyUnboundFeedback = { message: String(draft.feedbackMessage), category: draft.feedbackCategory || 'general' };
    } else this.legacyUnboundFeedback = null;
    if (Object.hasOwn(draft, 'proposalInputs') && draft.proposalInputs && typeof draft.proposalInputs === 'object' && !Array.isArray(draft.proposalInputs)) this.proposalInputs = cloneValue(draft.proposalInputs);
    if (Object.hasOwn(draft, 'draftConflictAlternates')) this.draftAlternates = this.draftAlternatesFrom(draft);
    this.selectedObjectId = Object.hasOwn(draft, 'selectedObjectId') ? draft.selectedObjectId : this.selectedObjectId;
    this.fieldDraftValues = cloneValue(draft.fields || {});
    if (this.objectsWorkflow()) {
      this.targetNotes = draft.targetNotes && typeof draft.targetNotes === 'object' && !Array.isArray(draft.targetNotes) ? cloneValue(draft.targetNotes) : {};
      this.structuralProposals = Array.isArray(draft.structuralProposals) ? cloneValue(draft.structuralProposals) : [];
      if (!Object.keys(this.targetNotes).length && String(draft.text || '').trim()) this.targetNotes[this.selectedObjectId || '__project__'] = { text: draft.text, feedbackId: this.newFeedbackId() };
      this.legacyWorkbench.loadCurrentNote();
    } else $('#edit-text').value = draft.text || '';
    this.loadFeedbackInputForCurrentTarget();
    if (this.objectsWorkflow()) { this.renderDynamicFields(this.objectItems(), this.capabilities); this.renderObjectCatalog(this.objectItems()); }
    for (const key of TEMPLATE_FIELDS) { const input = this.parameterInput(key); if (draft.values?.[key] != null && input && !input.disabled) input.value = draft.values[key]; }
    for (const input of $('#dynamic-fields')?.querySelectorAll('[data-field-id]:not([data-axis])') || []) { if (draft.fields?.[input.dataset.fieldId] != null && !input.disabled) this.writeControlValue(input, draft.fields[input.dataset.fieldId]); }
    this.renderObjectDetail(); this.renderFeedback();
    if (this.objectsWorkflow()) this.legacyWorkbench.render();
  }
  applyVisibleDraftReplacement(draft, { draftKey = this.draftKey, snapshot = this.snapshot,
    projectId = this.projectId, generation = this.workbenchGeneration, scope = this.draftConflictTarget(snapshot) } = {}) {
    const contextMatches = () => this.draftContextMatches(draftKey, generation, snapshot) &&
      this.projectId === projectId && this.sameDraftConflictTarget({ scope }, snapshot);
    if (!draft || typeof draft !== 'object' || !contextMatches()) return false;
    const current = this.currentDraftRecord();
    if (!contextMatches() || !this.draftRecordMatchesScope(current, draftKey, snapshot)) return false;
    const alternatives = this.mergeDraftAlternates(draft, [current]);
    if (!contextMatches()) return false;
    this.applyVisibleDraft({ ...cloneValue(draft), draftConflictAlternates: alternatives });
    if (!contextMatches()) return false;
    if (this.objectsWorkflow() && this.legacyWorkbench) this.legacyWorkbench.syncUrl(true);
    return contextMatches();
  }
  renderCandidates() {
    const root = $('#candidate-preview'); root.replaceChildren();
    if (!this.candidates.length) { hide(root); return; }
    root.append(el('h3', '', '待审阅的候选结果'));
    for (const candidate of this.candidates) {
      const card = el('article', 'candidate-card'); card.append(el('b', '', candidate.title || candidate.summary || candidate.candidateCommit || candidate.commit || '候选结果'));
      card.append(el('p', 'meta-line', `状态：${JOB_LABELS[candidate.status] || candidate.status || '等待审阅'} · Git ${candidate.candidateCommit || candidate.commit || '未提供'}`));
      if (candidate.jobId) { const open = el('button', 'button secondary', '查看结果与证据'); open.type = 'button'; open.addEventListener('click', () => this.selectJob(candidate.jobId)); card.append(open); }
      root.append(card);
    }
    hide(root, false);
  }
  renderWorkbench() {
    if (!this.snapshot) return; const snap = this.snapshot;
    $('#workbench-title').textContent = snap.title || snap.projectTitle || '当前工作台'; setStatus($('#snapshot-version'), snap.kind === 'REPAIR' ? 'REJECTED' : 'PUBLISHED', snap.kind === 'REPAIR' ? '未发布 · 待返修' : `版本 ${snap.publicationRevision ?? '未知'}`);
    const summary = $('#snapshot-summary'); releaseVisuals(summary); summary.replaceChildren();
    summary.append(el('p', 'proposal-summary', snap.summary || snap.description || '这是项目当前已发布的工作台快照。'));
    if (snap.kind === 'REPAIR') summary.append(el('div', 'notice', snap.repairReason === 'VERIFICATION_FAILED'
      ? '制作源码已保留，技术验证未通过，尚无可试玩候选。重新策划后仍需审阅、工程准备、制作和独立验证。'
      : '候选未发布。修改基于被拒绝候选，保留已有实现；本轮方案仍需审阅确认，完成制作与验证后再次验收。'));
    if (snap.kind === 'CONCEPT') summary.append(el('div', 'notice', '当前处于概念阶段，尚未制作或验证工程；完成策划并确认范围后进入制作。'));
    else if (snap.kind === 'INITIALIZATION') summary.append(el('div', 'notice', '当前版本是已验证的工程准备基线，尚不包含可玩的 MVP。玩法实现需要独立规划和确认。'));
    else if (snap.playable === false && snap.kind !== 'REPAIR') summary.append(el('div', 'notice', '当前版本尚无可玩的 MVP。玩法实现需要独立策划和确认。'));
    else if (snap.kind === 'MVP' && snap.playable === true) summary.append(el('div', 'success-notice', this.workspace?.testData
      ? '测试数据中的 MVP 样例；不代表生产项目已完成或被用户验收。'
      : '首个 Demo 已完成服务验证并由用户接受。'));
    if (snap.baseCommit || snap.sourceCommit) summary.append(el('p', 'meta-line', `Git 版本：${snap.baseCommit || snap.sourceCommit}`));
    if (snap.kind === 'REPAIR') {
      if (snap.repairReason === 'VERIFICATION_FAILED') {
        if (snap.verification) this.renderEvidence(snap.verification, summary);
        const packet = (this.workspace?.packets || []).find(item => item.projectId === this.projectId && item.jobId === snap.jobId);
        if (packet) {
          const prior = el('details', 'approved-input-recovery'); prior.append(el('summary', '', '查看上轮全部已确认输入与参考'));
          mountVisual(prior, { title: '上轮已确认要求', rawText: this.recoveryRequestText(packet), references: referenceModel(packet, this.projectId) }, `repair-input:${this.projectId}:${snap.jobId}`);
          summary.append(prior);
        }
        const prepare = el('button', 'button secondary', '准备按验证错误修复'); prepare.type = 'button'; prepare.dataset.action = 'prepare-verification-repair';
        const projectId = this.projectId, sourceCommit = snap.sourceCommit, jobId = snap.jobId;
        prepare.addEventListener('click', () => {
          if (this.projectId !== projectId || this.snapshot?.jobId !== jobId || this.snapshot?.sourceCommit !== sourceCommit || !this.canEnterIteration()) return;
          if ($('#edit-text').value.trim()) return this.notify('已有返修说明，已保留；请核对验证失败项后提交。');
          $('#edit-text').value = '依据独立验证失败项修复本轮实现，保留已确认的玩法、布局和视觉要求。';
          this.queueDraftSave(); $('#edit-text').focus(); $('#edit-form')?.scrollIntoView?.({ behavior: 'smooth', block: 'center' });
        });
        summary.append(prepare);
      }
      const history = el('button', 'button secondary', this.repairHistoryJobId === snap.jobId ? '收起上轮制作与验证记录' : '查看上轮制作与验证记录'); history.type = 'button';
      history.addEventListener('click', () => { this.repairHistoryJobId = this.repairHistoryJobId === snap.jobId ? null : snap.jobId; this.renderWorkbench(); });
      summary.append(history);
    }
    if (this.canEnterIteration() && this.stage === 'initial') { const link = el('a', 'button primary iteration-link', '进入迭代工作台 →'); link.href = `?project=${encodeURIComponent(this.projectId)}&stage=iteration`; link.addEventListener('click', event => { event.preventDefault(); this.enterIterationStage(); }); summary.append(link); }
    const objects = this.objectItems(snap);
    if (this.objectsWorkflow()) this.renderObjectCatalog(objects);
    else if (objects.length) { summary.append(el('h3', '', '可编辑内容')); const list = el('div', 'object-list'); for (const object of objects.slice(0, 12)) { const row = el('div', 'object-row'); row.append(el('b', '', object.name || object.label || object.id)); row.append(el('span', 'muted', object.editable === false ? '只读' : '可编辑')); list.append(row); } summary.append(list); }
    const capabilities = this.capabilities?.fields || this.capabilities?.parameters || this.capabilities || {};
    const pendingInitialization = snap.kind === 'INITIALIZATION' || snap.playable === false;
    if (this.objectsWorkflow()) { this.selectedObjectId = objects.some(o => o.id === this.selectedObjectId) || this.legacyWorkbench.isDraftTarget(this.selectedObjectId) ? this.selectedObjectId : (objects[0]?.id || null); this.loadFeedbackInputForCurrentTarget(); this.renderDynamicFields(objects, capabilities); this.renderObjectCatalog(objects); this.renderObjectDetail(); this.renderFeedback(); this.draftKey = this.makeDraftKey(snap); this.showDraftState(); this.legacyWorkbench.render(); this.renderWorkflowStages(); return; }
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
      const sourceObject = objects.find(object => object.id === (input.dataset.objectId || 'player'));
      const sourceField = sourceObject?.fields?.find(field => field.id === (input.dataset.fieldKey || key));
      input.step = numberInputStep(cap?.step ?? sourceField?.step, cap?.integer === true || input.dataset.type === 'integer' || key === 'goalCount');
      const boundLabel = $(`[data-bound-for="${key}"]`); if (boundLabel) boundLabel.textContent = bounded ? `${min}–${max}` : '服务未提供范围';
      input.disabled = !supported; input.value = supported && snap.decisions?.[key] != null ? snap.decisions[key] : '';
      input.closest('label').classList.toggle('unsupported', !supported);
    }
    $('#capability-note').textContent = '灰色项目表示此工程尚未声明支持；提交前会由服务再次校验。';
    this.draftKey = this.makeDraftKey(snap); this.showDraftState();
    this.renderWorkflowStages();
  }
  canEnterIteration() {
    const snapshot = this.snapshot;
    if (snapshot?.kind === 'REPAIR') {
      const repair = this.workspace?.repairContext;
      return !!repair && snapshot.projectId === this.projectId && repair.projectId === this.projectId && repair.jobId === snapshot.jobId && repair.candidateId === snapshot.candidateId && repair.sourceCommit === snapshot.sourceCommit;
    }
    return this.workspace?.iterationReady === true && !!snapshot && (snapshot.projectId || snapshot.id) === this.projectId && Number.isInteger(snapshot.publicationRevision) && snapshot.publicationRevision > 0 && snapshot.playable === true;
  }
  enterIterationStage() {
    if (!this.canEnterIteration()) { this.notify('需要已接受的 Demo 或服务提供的精确返修源码，才能继续。'); return; }
    this.stage = 'iteration'; this.updateUrl(); this.renderWorkflowStages(); this.renderWorkflowStatus();
  }
  renderWorkflowStages() {
    const project = !!this.projectId, proposal = this.proposal, accepted = this.canEnterIteration();
    hide($('#project-visual-entry'), !proposal);
    hide($('#concept-form')?.closest('.panel'), !project || this.stage === 'iteration' || !!proposal && proposal.status !== 'BLOCKED' || !!this.job && ACTIVE.has(this.job.status) || accepted);
    const iterationOpen = project && this.stage === 'iteration' && accepted;
    if (iterationOpen && this.snapshot?.kind === 'REPAIR' && this.job?.id === this.snapshot.jobId && ['REJECTED', 'FAILED'].includes(this.job.status)) hide($('#job-panel'), this.repairHistoryJobId !== this.snapshot.jobId);
    $('#project-view')?.classList.toggle('iteration-mode', iterationOpen);
    this.legacyWorkbench?.syncIterationLayout?.(iterationOpen);
    hide($('#workbench-panel'), !iterationOpen && !accepted);
    hide($('#object-catalog'), !iterationOpen); hide($('#edit-form'), !iterationOpen); hide($('#draft-state'), !iterationOpen);
    if (accepted && proposal?.status === 'FROZEN' && this.jobMatchesProposal() && this.job.status === 'PUBLISHED') hide($('#proposal-panel'), !this.visualPlanning?.open);
    if (iterationOpen) { $('#workbench-title').textContent = this.snapshot?.kind === 'REPAIR' ? this.snapshot.repairReason === 'VERIFICATION_FAILED' ? '验证失败返修工作台' : '候选返修工作台' : '迭代工作台'; hide($('#proposal-panel'), !this.isIterationProposal(proposal) && !this.visualPlanning?.open); }
    else if (project && accepted) { hide($('#workbench-panel'), false); $('#workbench-title').textContent = '已完成的首个 Demo'; }
    const link = $('#snapshot-summary .iteration-link'); if (link) hide(link, this.stage !== 'initial');
    const stageRoot = $('#stage-status'), stageList = $('#stage-list');
    if (stageRoot && stageList) {
      const phase = String(this.projectView?.phase || this.proposal?.status || this.job?.status || (accepted ? 'ACCEPTED' : 'DISCUSSION')).toUpperCase();
      const step = String(this.projectView?.step || '').toUpperCase();
      const stages = [['讨论', ['DISCUSSION', 'PLANNING', 'PLANNING_UNCERTAIN', 'NEEDS_CLARIFICATION'].includes(phase) && !['PROPOSAL_REVIEW'].includes(step)], ['方案审阅', ['READY', 'FROZEN'].includes(phase) || ['PROPOSAL_REVIEW', 'FROZEN'].includes(step)], ['制作与验证', ['QUEUED', 'DISPATCHING', 'RUNNING', 'VERIFYING', 'PROJECTING', 'READY_FOR_REVIEW', 'EXECUTION', 'PRODUCTION'].includes(phase) || ['PRODUCING', 'VERIFYING'].includes(step)], ['试玩与验收', ['READY_FOR_REVIEW', 'PUBLISHED', 'ACCEPTED', 'REJECTED', 'CANDIDATE'].includes(phase) || step === 'CANDIDATE_REVIEW'], ['迭代', accepted && this.stage === 'iteration']];
      stageList.replaceChildren(); for (const [label, current] of stages) stageList.append(el('li', current ? 'current' : '', label)); hide(stageRoot, !project);
    }
    hide($('#project-manager'), project); hide($('#project-view'), !project);
  }
  isIterationProposal(proposal = this.proposal) {
    if (this.stage !== 'iteration' || !this.canEnterIteration() || !proposal || proposal.projectId !== this.projectId) return false;
    const boundRevision = proposal.changeRequest?.baseRevision ?? proposal.publicationRevision;
    if (proposal.repairBase && this.snapshot?.kind === 'REPAIR' && proposal.repairBase.sourceCommit !== this.snapshot.sourceCommit) return false;
    if (!Number.isInteger(Number(boundRevision)) || (Number(boundRevision) <= 0 && !proposal.repairBase)) return false;
    if (['PLANNING', 'PLANNING_UNCERTAIN', 'PLANNING_CANCELLING', 'NEEDS_CLARIFICATION', 'READY', 'FAILED', 'BLOCKED', 'CANCELLED'].includes(proposal.status)) return true;
    if (proposal.status === 'FROZEN') return !!this.packet && (!this.jobMatchesProposal() || ACTIVE.has(this.job.status));
    return false;
  }
  jobMatchesProposal(job = this.job, proposal = this.proposal, packet = this.packet) {
    if (!job || !proposal) return false;
    if (job.projectId && proposal.projectId && job.projectId !== proposal.projectId) return false;
    const candidate = job.candidate || job.response?.candidate;
    const declaredProposalIds = [job.proposalId, job.packet?.proposalId, candidate?.proposalId, packet?.proposalId].filter(Boolean);
    if (declaredProposalIds.some(id => id !== proposal.id)) return false;
    const packetIds = [packet?.id, packet?.packetId, proposal.packetId].filter(Boolean);
    const jobPacketIds = [job.packetId, typeof job.packet === 'string' ? job.packet : null, candidate?.packetId, candidate?.packet?.id, candidate?.packet?.packetId].filter(Boolean);
    return declaredProposalIds.includes(proposal.id) || jobPacketIds.some(id => packetIds.includes(id)) || packet?.jobId === job.id || job.id === packet?.jobId;
  }
  proposalForJob(job = this.job, candidate = job?.candidate || job?.response?.candidate) {
    if (!job) return null;
    const projectId = job.projectId;
    const packets = (this.workspace?.packets || []).filter(item => !projectId || item.projectId === projectId);
    const nestedPacket = [job.packet, job.response?.packet].find(item => item && typeof item === 'object' && !Array.isArray(item));
    const jobPacketIds = [job.packetId, typeof job.packet === 'string' ? job.packet : null, job.packet?.id, job.packet?.packetId, candidate?.packetId, candidate?.packet?.id, candidate?.packet?.packetId].filter(Boolean);
    const locatedPacket = nestedPacket || packets.find(item =>
      [item.id, item.packetId].some(id => id && jobPacketIds.includes(id)) || item.jobId === job.id) || null;
    const packet = this.packetForCandidate(job, candidate);
    if (locatedPacket && !packet) return null;
    if (packet?.approvedProposal && packet.projectId === projectId && packet.approvedProposal.id === packet.proposalId && packet.approvedProposal.revision === packet.proposalRevision) return packet.approvedProposal;
    if (packet?.userText !== undefined && packet.projectId === projectId && packet.proposalId && Number.isInteger(packet.proposalRevision)) return { id: packet.proposalId, projectId, revision: packet.proposalRevision, text: packet.userText, changeRequest: packet.changeRequest, feedback: packet.feedback, visualReferences: packet.visualReferences, assets: packet.assets, document: packet.document };
    const proposals = [...new Map([
      ...(this.workspace?.proposals || []),
      ...(this.proposal ? [this.proposal] : []),
    ].filter(item => item?.id && (!projectId || item.projectId === projectId)).map(item => [item.id, item])).values()];
    const declaredProposalIds = [job.proposalId, candidate?.proposalId, job.packet?.proposalId, packet?.proposalId].filter(Boolean);
    const distinctProposalIds = [...new Set(declaredProposalIds)];
    if (distinctProposalIds.length > 1) return null;
    if (distinctProposalIds.length === 1) return proposals.find(item => item.id === distinctProposalIds[0]) || null;
    return proposals.find(item => {
      if (candidate?.proposalId && candidate.proposalId !== item.id) return false;
      const proposalPacket = item.id === this.proposal?.id && this.packet?.projectId === projectId
        ? this.packet
        : packets.find(value => value.proposalId === item.id || (item.packetId && [value.id, value.packetId].includes(item.packetId))) || null;
      return this.jobMatchesProposal(job, item, proposalPacket);
    }) || null;
  }
  isHistoricalJob(job = this.job) {
    if (!job) return false;
    const projectId = job.projectId || this.projectId;
    if (projectId !== this.projectId) return true;
    const selectedJobId = this.selectedJobForProject(projectId);
    if (selectedJobId && selectedJobId !== job.id) return true;
    const view = this.projectView?.projectId === projectId ? this.projectView : null;
    if (view?.job?.id && view.job.id !== job.id) return true;
    const proposal = this.proposal?.projectId === projectId ? this.proposal : null;
    if (proposal && !this.jobMatchesProposal(job, proposal, this.packet?.projectId === projectId ? this.packet : null)) {
      const candidate = job.candidate || job.response?.candidate;
      const proposalIds = [job.proposalId, job.packet?.proposalId, candidate?.proposalId].filter(Boolean);
      if (proposalIds.some(id => id !== proposal.id)) return true;
      const jobPacketIds = [job.packetId, typeof job.packet === 'string' ? job.packet : null, job.packet?.id, job.packet?.packetId, candidate?.packetId, candidate?.packet?.id, candidate?.packet?.packetId].filter(Boolean);
      const currentPacketIds = [this.packet?.id, this.packet?.packetId, proposal.packetId].filter(Boolean);
      if (currentPacketIds.length && jobPacketIds.length && jobPacketIds.every(id => !currentPacketIds.includes(id))) return true;
      const knownPacket = (this.workspace?.packets || []).find(item => item.projectId === projectId &&
        ([item.id, item.packetId].some(id => id && jobPacketIds.includes(id)) || item.jobId === job.id));
      if (knownPacket?.proposalId && knownPacket.proposalId !== proposal.id) return true;
      if (PLANNING.has(proposal.status) || ['NEEDS_CLARIFICATION', 'READY', 'FAILED'].includes(proposal.status)) return true;
    }
    return false;
  }
  renderWorkflowStatus() {
    const status = $('#workflow-status-copy'); if (!status) return;
    if (!this.projectId) { status.textContent = '请选择或创建一个项目。'; return; }
    const labels = { discussion: '讨论', execution: '执行', production: '制作', candidate: '候选待验收', iteration: '迭代工作台', archived: '已归档' };
    const phase = this.projectView?.phase ? String(this.projectView.phase).toLowerCase() : '';
    const phaseLabel = phase ? (labels[phase] || this.projectView.phase) : '';
    const freshness = this.streamFresh ? '状态流实时' : this.streamReconnecting ? '状态流重连中' : '状态流陈旧，正在恢复';
    const phaseContext = action => phaseLabel && !String(action || '').includes(phaseLabel) ? phaseLabel : '';
    if (this.activity) {
      status.textContent = [this.activity, phaseContext(this.activity), ...(phase ? [freshness] : [])].filter(Boolean).join(' · '); return;
    }
    if (this.projectView?.phase) {
      const productionStatus = this.projectView.job?.status || this.job?.status;
      const producing = productionStatus === 'RUNNING' ? 'AI 正在制作；完成后进入独立验证' : ['QUEUED', 'DISPATCHING'].includes(productionStatus) ? '等待制作执行器接单' : '正在制作；等待服务更新进度';
      const stepLabels = { concept: '描述初始想法', planning: '等待策划反馈', planning_failed: '策划未完成；查看诊断后重试', clarification: '回答策划问题', proposal_review: '审阅并确认方案', frozen: '开始制作', producing, verifying: '后端正在独立验证', candidate_review: '试玩并审阅候选', accepted: '进入迭代工作台', repair: '填写问题与调整，重新策划返修', archived: '查看已归档项目', uncertain: '读取服务记录并对账' };
      const phase = String(this.projectView.phase).toLowerCase(), attention = this.projectView.attention;
      const action = attention === 'uncertain' ? '状态待核实；请读取服务记录并对账' : (stepLabels[this.projectView.step] || labels[phase] || this.projectView.step || phase);
      status.textContent = [action, phaseContext(action), freshness].filter(Boolean).join(' · '); return;
    }
    const proposal = this.proposal, job = this.isHistoricalJob(this.job) ? null : this.job;
    const accepted = this.canEnterIteration();
    let actor = '等待用户输入', action = '描述初始想法';
    if (job?.status === 'UNCERTAIN' || proposal?.status === 'PLANNING_UNCERTAIN') { actor = '状态待核实'; action = '读取服务记录并对账'; }
    else if (job?.status === 'READY_FOR_REVIEW') { actor = '等待用户反馈'; action = '预览并审阅制作候选'; }
    else if (job?.status === 'VERIFYING') { actor = '后端验证'; action = '等待运行验证结果'; }
    else if (job?.status === 'QUEUED' || job?.status === 'DISPATCHING') { actor = '等待 AI 制作'; action = JOB_LABELS[job.status] || '等待制作 session'; }
    else if (job?.status === 'RUNNING') { actor = 'AI 正在制作'; action = '等待制作结果'; }
    else if (job?.status === 'PROJECTING') { actor = '系统整理结果'; action = '等待结果映射与回流'; }
    else if (job?.status === 'CANCEL_REQUESTED' || job?.status === 'CANCELLING') { actor = '正在停止制作'; action = '等待服务确认停止'; }
    else if (proposal && PLANNING.has(proposal.status)) { actor = proposal.status.includes('CANCELLING') ? '正在停止策划' : 'AI 策划'; action = proposal.status.includes('CANCELLING') ? '等待停止确认' : '等待策划反馈'; }
    else if (proposal?.status === 'NEEDS_CLARIFICATION') { actor = '等待用户反馈'; action = '回答 AI 策划问题'; }
    else if (proposal?.status === 'READY') { actor = '等待用户反馈'; action = '审阅并确认制作范围'; }
    else if (proposal?.status === 'FROZEN' && !accepted) { actor = '等待 AI 制作'; action = '恢复已冻结的制作表单'; }
    else if (job?.status === 'BLOCKED') { actor = '当前步骤受阻'; action = '查看阻塞原因与可用恢复操作'; }
    else if (job?.status === 'REJECTED') { actor = accepted ? '等待用户反馈' : '等待用户输入'; action = accepted ? '候选已拒绝，可在返修工作台提交问题与调整' : '候选已拒绝，可修改初始想法并重新策划'; }
    else if (job?.status === 'FAILED' || proposal?.status === 'FAILED') { actor = '流程失败'; action = '查看诊断并决定是否重试'; }
    else if (this.stage === 'iteration' && accepted) { actor = '迭代工作台'; action = '选择对象并提交调整或反馈'; }
    else if (accepted) { actor = '等待用户反馈'; action = this.workspace?.iterationReadyTestOnly ? '测试演示已就绪（测试数据）' : '首个 Demo 已完成，可进入迭代'; }
    status.textContent = `${actor} · 下一步：${action}`;
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
    const relations = Array.isArray(object.relations) ? object.relations : [];
    const sourceBindings = Array.isArray(object.sourceBindings) ? object.sourceBindings : [];
    if (object.parentId || relations.length || sourceBindings.length) {
      const associations = el('details', 'object-associations');
      associations.append(el('summary', '', '查看对象关联与源文件'));
      if (object.parentId) associations.append(el('p', 'muted', `父对象：${object.parentId}`));
      if (relations.length) associations.append(el('p', 'muted', `关系：${relations.map(r => `${r.type || '关联'} → ${r.targetId || r.target}`).join('、')}`));
      if (sourceBindings.length) associations.append(el('p', 'meta-line', `源文件：${sourceBindings.join('、')}`));
      root.append(associations);
    }
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
  selectObject(objectId) {
    if (!this.objectItems().some(object => object.id === objectId)) return;
    this.saveFeedbackInputForCurrentTarget(); this.legacyWorkbench.beforeTargetChange(); this.captureVisibleFields(); this.selectedObjectId = objectId; this.loadFeedbackInputForCurrentTarget();
    this.renderDynamicFields(this.objectItems(), this.capabilities); this.renderObjectCatalog(this.objectItems()); this.renderObjectDetail(); this.renderFeedback();
    this.legacyWorkbench.onTargetChange();
  }
  renderDynamicFields(objects, capabilities) {
    const root = $('#dynamic-fields'); if (!root) return; root.replaceChildren();
    const caps = this.allCapabilities(capabilities).filter(cap => this.splitCapability(cap).objectId === this.selectedObjectId);
    const object = objects.find(item => item.id === this.selectedObjectId);
    for (const cap of caps) {
      const { objectId, fieldId } = this.splitCapability(cap); const field = (object?.fields || []).find(item => item.id === fieldId) || {};
      const type = cap.type || field.type || 'text'; const editable = this.capabilityEditable(cap, object);
      const label = el(type === 'vector2' ? 'div' : 'label', 'dynamic-field'); label.append(el('span', 'field-label', cap.label || field.label || fieldId));
      if (cap.description || field.description) label.append(el('small', 'muted', cap.description || field.description));
      const current = this.capabilityValue(cap, object || {}); let control;
      if (type === 'choice') { const options = cap.options || field.options || []; control = el('select'); this.configureChoice(control, options); }
      else if (type === 'boolean') { control = el('select'); for (const [value, title] of [['', '请选择'], ['true', '是'], ['false', '否']]) { const opt = el('option', '', title); opt.value = value; control.append(opt); } }
      else if (type === 'vector2') {
        control = el('div', 'vector2-control'); control.dataset.vector = 'true'; control.setAttribute('role', 'group'); control.setAttribute('aria-label', cap.label || field.label || fieldId);
        for (const axis of ['x', 'y']) {
          const axisLabel = el('label', 'vector2-axis'); axisLabel.append(el('span', 'muted', axis.toUpperCase()));
          const input = el('input'); input.type = 'number'; input.step = String(cap.step || field.step || 'any'); input.dataset.axis = axis; input.setAttribute('aria-label', `${cap.label || field.label || fieldId} ${axis.toUpperCase()}`);
          axisLabel.append(input); control.append(axisLabel);
        }
      }
      else if (type === 'text') { control = el('textarea'); control.rows = 2; control.maxLength = Number(cap.maxLength || field.maxLength || 2000); }
      else { control = el('input'); control.type = 'number'; control.step = numberInputStep(cap.step ?? field.step, type === 'integer' || cap.integer === true); const bounds = this.fieldBounds(cap, field); for (const bound of ['min', 'max']) if (bounds[bound] != null) control[bound] = String(bounds[bound]); }
      control.name = this.legacyFieldName(objectId, fieldId); control.dataset.fieldId = `${objectId}.${fieldId}`; control.dataset.fieldKey = fieldId; control.dataset.capabilityId = cap.id || `${objectId}.${fieldId}`; control.dataset.objectId = objectId; control.dataset.type = type; control.disabled = !editable;
      if (type === 'vector2') { const v = Object.hasOwn(this.fieldDraftValues, control.dataset.fieldId) ? this.fieldDraftValues[control.dataset.fieldId] : current; this.writeControlValue(control, v); for (const input of control.querySelectorAll('input')) { input.dataset.fieldId = control.dataset.fieldId; input.dataset.fieldKey = fieldId; input.dataset.capabilityId = control.dataset.capabilityId; input.dataset.objectId = objectId; input.dataset.type = type; input.disabled = !editable; } }
      else this.writeControlValue(control, Object.hasOwn(this.fieldDraftValues, control.dataset.fieldId) ? this.fieldDraftValues[control.dataset.fieldId] : current);
      if (!this.objectsWorkflow() && TEMPLATE_FIELDS.includes(fieldId)) control.name = fieldId;
      label.append(control);
      const guidance = el('small', 'workbench-field-guidance'); guidance.dataset.fieldGuidance = `${objectId}.${fieldId}`; guidance.setAttribute('aria-live', 'polite'); label.append(guidance); root.append(label);
      this.updateDynamicFieldGuidance(control, cap, field, current);
    }
    if (!caps.length) {
      const localTarget = !object && this.selectedObjectId ? this.legacyWorkbench.draftTarget(this.selectedObjectId) : null;
      root.append(el('p', 'muted', object ? '此对象当前没有服务声明可编辑的属性。'
        : localTarget ? '此本地提案当前没有服务声明可编辑的属性；可以继续编辑本目标意见。'
          : '请选择对象查看可编辑属性。'));
    }
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
      const field = this.objectItems().find(object => object.id === 'player')?.fields?.find(item => item.id === key) || {};
      const declaredStep = cap?.step ?? field.step;
      const label = el('label', 'dynamic-field'); label.append(el('span', 'field-label', LABELS[key]));
      label.append(el('small', 'muted', typeof cap?.description === 'string' && cap.description.trim() ? cap.description.trim() : '旧版来源未提供字段说明。'));
      const input = el('input'); input.type = 'number'; input.name = key; input.dataset.fieldId = key; input.dataset.fieldKey = key; input.dataset.fieldGuidanceKey = key; input.dataset.capabilityId = key; input.dataset.objectId = 'player'; input.dataset.type = 'scalar'; input.min = min ?? ''; input.max = max ?? ''; input.step = numberInputStep(declaredStep, cap?.integer === true || cap?.type === 'integer' || field.type === 'integer' || key === 'goalCount');
      input.disabled = !(cap === true || cap && (cap.editable === true || cap.supported === true || cap.enabled === true)) || min == null || max == null;
      input.value = this.snapshot?.decisions?.[key] ?? ''; label.append(input);
      const guidance = el('small', 'workbench-field-guidance'); guidance.dataset.fieldGuidance = key; guidance.setAttribute('aria-live', 'polite'); label.append(guidance); root.append(label);
      const metadata = cap && typeof cap === 'object' ? { ...cap, objectId: 'player', fieldId: key, id: cap.id || key } : { objectId: 'player', fieldId: key, id: key, min, max, type: 'scalar' };
      if (declaredStep == null) delete metadata.step; else metadata.step = declaredStep;
      this.updateDynamicFieldGuidance(input, metadata, {}, this.snapshot?.decisions?.[key]);
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
  describeFieldValue(value) {
    if (value === undefined || value === null) return '未声明';
    if (value === '') return '空值';
    if (typeof value === 'boolean') return value ? 'true' : 'false';
    if (typeof value === 'object') return JSON.stringify(value);
    return String(value);
  }
  fieldUnit(capability, field) {
    const value = capability?.unit ?? capability?.units ?? field?.unit ?? field?.units ?? null;
    return typeof value === 'string' ? value.trim() || null : value;
  }
  fieldBounds(capability, field) {
    const range = Array.isArray(capability?.range) ? capability.range : Array.isArray(field?.range) ? field.range : null;
    return { min: capability?.min ?? capability?.limits?.min ?? field?.min ?? field?.limits?.min ?? range?.[0] ?? null, max: capability?.max ?? capability?.limits?.max ?? field?.max ?? field?.limits?.max ?? range?.[1] ?? null };
  }
  normalizeFieldValue(type, value) {
    if (type === 'boolean') {
      if (typeof value === 'boolean') return value;
      if (value === 1 || value === '1' || String(value).toLowerCase() === 'true') return true;
      if (value === 0 || value === '0' || String(value).toLowerCase() === 'false') return false;
      return value;
    }
    return ['scalar', 'number', 'integer'].includes(type) && value !== '' && value != null ? Number(value) : value;
  }
  updateDynamicFieldGuidance(control, capability = null, field = null, sourceValue = undefined) {
    const root = control?.closest?.('[data-vector="true"]') || control;
    const id = root?.dataset?.fieldId; if (!id) return;
    const identity = root.dataset.fieldGuidanceKey || id;
    const explicitObjectId = root.dataset.objectId || null;
    const objectId = explicitObjectId || (id.includes('.') ? id.slice(0, id.indexOf('.')) : null);
    const fieldId = root.dataset.fieldKey || (explicitObjectId ? (id.startsWith(`${explicitObjectId}.`) ? id.slice(explicitObjectId.length + 1) : id) : id.includes('.') ? id.slice(id.indexOf('.') + 1) : id);
    capability ||= this.allCapabilities().find(item => { const parts = this.splitCapability(item); return parts.objectId === objectId && parts.fieldId === fieldId; })
      || this.allCapabilities().find(item => item.id === id || item.name === fieldId || item.id === fieldId);
    const object = objectId ? this.objectItems().find(item => item.id === objectId) : null;
    field ||= object?.fields?.find(item => item.id === fieldId || item.key === fieldId) || {};
    if (sourceValue === undefined) sourceValue = capability && object ? this.capabilityValue(capability, object) : object ? field?.value : this.snapshot?.decisions?.[fieldId];
    const unit = this.fieldUnit(capability, field);
    const bounds = this.fieldBounds(capability, field);
    const min = bounds.min == null ? null : bounds.min, max = bounds.max == null ? null : bounds.max;
    const rangeText = `下限 ${min == null ? '未声明' : min} 至 上限 ${max == null ? '未声明' : max}`;
    const step = capability?.step ?? field?.step ?? null;
    const type = root.dataset.type || 'text';
    const controlValue = this.readControlValue(root);
    const hasDraftValue = Object.hasOwn(this.fieldDraftValues || {}, id);
    const requested = hasDraftValue ? this.fieldDraftValues[id] : controlValue;
    const hasRequestedValue = hasDraftValue;
    const normalize = value => this.normalizeFieldValue(type, value);
    const sameAsSource = sourceValue !== undefined && sourceValue !== null && hasRequestedValue && sameValue(normalize(requested), normalize(sourceValue));
    const desired = !hasRequestedValue ? '本轮未提出修改'
      : sameAsSource ? '本轮与来源值相同，当前没有净修改'
        : `本轮期望：${this.describeFieldValue(requested)}${unit ? ` ${unit}` : ''}（尚未制作）`;
    const guide = [...($('#dynamic-fields')?.querySelectorAll('[data-field-guidance]') || [])].find(item => item.dataset.fieldGuidance === identity);
    if (!guide) return;
    const revision = this.snapshot?.publicationRevision ?? '未提供';
    guide.textContent = `来源版本 ${revision} · 来源当前值：${this.describeFieldValue(sourceValue)} · 单位（来源声明）：${unit || '未声明'} · 允许范围：${rangeText} · 步长：${step == null ? '未声明' : step} · ${desired}`;
    guide.dataset.netChange = String(hasRequestedValue && !sameAsSource);
  }
  captureVisibleFields() {
    for (const control of $('#dynamic-fields')?.querySelectorAll('[data-capability-id]:not([data-axis])') || []) {
      if (control.disabled) continue;
      const id = control.dataset.fieldId, value = this.readControlValue(control), type = control.dataset.type || 'text';
      if (value === '' && type !== 'text') { delete this.fieldDraftValues[id]; this.dirtyFields.delete(id); continue; }
      const cap = this.allCapabilities().find(item => {
        const parts = this.splitCapability(item);
        return `${parts.objectId}.${parts.fieldId}` === id || parts.fieldId === id && !control.dataset.objectId;
      });
      const object = control.dataset.objectId ? this.objectItems().find(item => item.id === control.dataset.objectId) : null;
      const base = cap && object ? this.capabilityValue(cap, object) : this.snapshot?.decisions?.[id];
      const normalize = current => this.normalizeFieldValue(type, current);
      if (base != null && sameValue(normalize(value), normalize(base))) { delete this.fieldDraftValues[id]; this.dirtyFields.delete(id); }
      else if (value !== '') this.fieldDraftValues[id] = value;
    }
  }
  onDynamicFieldEdit(control) { if (control.disabled) return; const root = control.closest('[data-vector="true"]') || control; const id = root.dataset.fieldId; if (id) { this.dirtyFields.add(id); const value = this.readControlValue(root); if (value === '' && root.dataset.type !== 'text') delete this.fieldDraftValues[id]; else this.fieldDraftValues[id] = value; this.updateDynamicFieldGuidance(root); } this.queueDraftSave(); }
  feedbackInputForTarget(objectId = this.selectedObjectId) {
    const item = objectId ? this.feedbackInputs?.[objectId] : null;
    return item && typeof item === 'object' ? item : null;
  }
  saveFeedbackInputForCurrentTarget() {
    const editor = $('#feedback-message'), category = $('#feedback-category');
    if (!editor) return;
    const targetId = this.feedbackInputTargetId;
    const message = String(editor.value || ''), kind = category?.value || 'general';
    if (targetId && targetId === this.selectedObjectId) {
      if (message.trim()) this.feedbackInputs[targetId] = { message, category: kind };
      else delete this.feedbackInputs[targetId];
    } else if (!targetId && !this.selectedObjectId && message.trim()) {
      this.legacyUnboundFeedback = { message, category: kind };
    }
  }
  loadFeedbackInputForCurrentTarget(targetId = this.selectedObjectId) {
    const target = typeof targetId === 'string' && targetId ? targetId : null;
    this.feedbackInputTargetId = target;
    const item = target ? this.feedbackInputForTarget(target) : null;
    const editor = $('#feedback-message'), category = $('#feedback-category');
    if (editor) editor.value = String(item?.message || '');
    if (category) category.value = item?.category || 'general';
  }
  handleFeedbackInput() {
    if (this.feedbackInputTargetId !== this.selectedObjectId) this.feedbackInputTargetId = this.selectedObjectId || null;
    this.saveFeedbackInputForCurrentTarget();
    this.queueDraftSave();
  }
  addFeedback({ fromLegacy = false } = {}) {
    this.saveFeedbackInputForCurrentTarget();
    const legacy = fromLegacy ? this.legacyUnboundFeedback : null;
    const current = this.feedbackInputForTarget(this.selectedObjectId);
    const message = fromLegacy ? String(legacy?.message || '') : String($('#feedback-message')?.value || current?.message || '');
    if (!message.trim()) return this.notify('先写下反馈内容。');
    if (!this.selectedObjectId) return this.notify('先选择一个关联对象。');
    const category = fromLegacy ? legacy?.category || 'general' : current?.category || $('#feedback-category')?.value || 'general';
    this.legacyWorkbench.pushHistory?.();
    this.feedback.push({ feedbackId: this.newFeedbackId(), objectId: this.selectedObjectId, message, category });
    if (fromLegacy) this.legacyUnboundFeedback = null;
    else delete this.feedbackInputs[this.selectedObjectId];
    this.loadFeedbackInputForCurrentTarget(); this.renderFeedback(); this.queueDraftSave(); this.legacyWorkbench.pushHistory?.();
  }
  removeLegacyUnboundFeedback() {
    if (!this.legacyUnboundFeedback) return;
    this.legacyWorkbench.pushHistory?.(); this.legacyUnboundFeedback = null;
    this.renderFeedback(); this.queueDraftSave(); this.legacyWorkbench.pushHistory?.();
  }
  newFeedbackId() { return globalThis.crypto?.randomUUID?.() || `feedback-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 12)}`; }
  ensureFeedbackIds(items = []) { return items.map(item => item.feedbackId ? item : { ...item, feedbackId: this.newFeedbackId() }); }
  renderFeedback() {
    const list = $('#feedback-list'); if (!list) return; list.replaceChildren();
    for (const [index, item] of (this.feedback || []).entries()) { const category = this.legacyWorkbench.feedbackCategoryLabel(item.category); const row = el('li', 'feedback-item', `${item.objectId} · ${category}：${item.message}`); const remove = el('button', 'quiet', '移除'); remove.type = 'button'; remove.addEventListener('click', () => { this.legacyWorkbench.pushHistory?.(); this.feedback.splice(index, 1); this.renderFeedback(); this.queueDraftSave(); this.legacyWorkbench.pushHistory?.(); }); row.append(remove); list.append(row); }
    for (const [objectId, item] of Object.entries(this.feedbackInputs || {})) {
      if (!String(item?.message || '').trim()) continue;
      list.append(el('li', 'feedback-item pending-feedback-item', `待添加 · ${objectId} · ${this.legacyWorkbench.feedbackCategoryLabel(item.category)}：${item.message}`));
    }
    if (this.legacyUnboundFeedback?.message) {
      const row = el('li', 'feedback-item pending-feedback-item legacy-unbound-feedback', `旧版待关联反馈 · 目标不明 · ${this.legacyWorkbench.feedbackCategoryLabel(this.legacyUnboundFeedback.category)}：${this.legacyUnboundFeedback.message}`);
      const associate = el('button', 'quiet', this.selectedObjectId ? '关联到所选对象并添加' : '先选择对象再关联'); associate.type = 'button'; associate.disabled = !this.selectedObjectId; associate.addEventListener('click', () => this.addFeedback({ fromLegacy: true }));
      const remove = el('button', 'quiet', '移除'); remove.type = 'button'; remove.addEventListener('click', () => this.removeLegacyUnboundFeedback());
      row.append(associate, remove); list.append(row);
    }
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
      const normalizedValue = this.normalizeFieldValue(type, value);
      const normalizedCurrent = this.normalizeFieldValue(type, current);
      if (JSON.stringify(normalizedValue) === JSON.stringify(normalizedCurrent)) continue;
      if (['text', 'clarify'].includes(this.legacyWorkbench.fieldDecision?.(objectId, fieldId))) continue;
      fields.push({ objectId, fieldId, value });
    }
    const noteFeedback = Object.entries(this.targetNotes || {}).flatMap(([key, note]) => {
      const message = String(note?.text || '');
      if (!message.trim()) return [];
      if (note?.decisionFor && this.legacyWorkbench.isDecisionCurrent?.(note, key) === false) return [];
      const objectId = this.legacyWorkbench.noteTargetId(key, note);
      const feedbackId = note.feedbackId || this.newFeedbackId();
      if (!note.feedbackId) this.targetNotes[key] = { ...note, feedbackId };
      return [{ feedbackId, objectId, message, category: 'general' }];
    });
    this.feedback = this.ensureFeedbackIds(this.feedback || []);
    const feedback = [...this.feedback, ...noteFeedback];
    const operations = (this.structuralProposals || []).map((item, index) => {
      const operationId = item.operationId || item.proposalId || this.newFeedbackId();
      if (!item.operationId) this.structuralProposals[index] = { ...item, operationId };
      const { createdAt, proposalId, ...fields } = this.structuralProposals[index];
      return { operationId, ...fields };
    });
    const draftTargetIds = new Set(operations.flatMap(item => item.kind === 'new-scene' && item.sceneId
      ? [item.sceneId] : item.kind === 'new-instance' && item.instanceId ? [item.instanceId] : []));
    const isCurrentTarget = id => this.objectItems().some(object => object.id === id) || draftTargetIds.has(id) || this.legacyWorkbench.isDraftTarget?.(id) === true;
    const operationTargets = operations.flatMap(item => {
      if (item.kind === 'new-scene') return [item.sceneId];
      if (item.kind === 'new-instance') return [item.instanceId];
      return [item.objectId];
    });
    const referenced = [this.selectedObjectId, ...fields.map(field => field.objectId), ...feedback.map(item => item.objectId), ...operationTargets].filter(id => typeof id === 'string' && isCurrentTarget(id));
    const targetObjectIds = [...new Set(referenced)];
    return { baseRevision: this.snapshot.publicationRevision, sourceCommit: this.snapshot.sourceCommit || this.snapshot.baseCommit, targetObjectIds, fields, feedback, operations };
  }
  legacyChangeRequest(request) {
    return request;
  }
  buildIterationIntent() { return { text: this.legacyWorkbench.effectiveText(), changeRequest: this.objectsWorkflow() ? this.buildChangeRequest() : null }; }
  storageId() { return this.workspace?.storeId || this.manager?.storeId || null; }
  makeDraftKey(snap) { const storeId = this.storageId(); return storeId && snap ? `${storeId}:${snap.projectId || snap.id}:iteration:${snap.publicationRevision ?? 'unknown'}${snap.kind === 'REPAIR' ? `:repair:${snap.candidateId || snap.jobId}:${snap.sourceCommit}` : ''}` : null; }
  conceptDraftKey(projectId) { const storeId = this.storageId(); return storeId && projectId ? `${storeId}:${projectId}:initial:concept:v1` : null; }
  rememberCorruptDraft(key, error, metadata = {}) {
    if (!key || !this.drafts?.rememberCorrupt) return null;
    return this.drafts.rememberCorrupt(key, error, metadata);
  }
  corruptDraftsForCurrentScope() {
    const snapshot = this.snapshot, currentKey = snapshot && this.makeDraftKey(snapshot);
    if (!currentKey || !this.projectId) return [];
    const projectId = snapshot.projectId || snapshot.id, revision = Number(snapshot.publicationRevision);
    const olderPrefix = `${this.storageId()}:${projectId}:iteration:`;
    const currentKeys = new Set([currentKey, `${currentKey}:saved`, `${currentKey}:saved:backup`]);
    return [...(this.drafts?.corruptRecords?.values?.() || [])].filter(record => {
      if (currentKeys.has(record.key)) return true;
      return record.kind === 'older' && record.projectId === projectId && Number.isSafeInteger(revision) &&
        Number(record.publicationRevision) < revision && String(record.key || '').startsWith(olderPrefix);
    }).map(record => ({ ...record }));
  }
  buildCorruptDraftArchive() {
    const records = this.corruptDraftsForCurrentScope();
    if (!records.length) return null;
    const projectId = this.snapshot?.projectId || this.snapshot?.id || this.projectId;
    let currentPageDraft = null;
    try { currentPageDraft = this.readVisibleDraft(); } catch {}
    const payload = {
      schemaVersion: 'ptah.workbench-draft-recovery.v1',
      purpose: '用于人工恢复损坏的本地草稿或检查点；raw 保留浏览器存储中的原始字符串，不会自动恢复、覆盖、迁移或提交。',
      exportedAt: new Date().toISOString(), projectId,
      publicationRevision: this.snapshot?.publicationRevision ?? null,
      currentDraftKey: this.draftKey || this.makeDraftKey(this.snapshot),
      currentPageDraft, corruptRawRecords: records,
    };
    return { payload, text: JSON.stringify(payload, null, 2), projectId, recordCount: records.length };
  }
  downloadCorruptDraftArchive() {
    const archive = this.buildCorruptDraftArchive();
    if (!archive) return this.notify('当前项目和版本没有需要导出的损坏存档。');
    const { projectId, recordCount } = archive;
    const blob = new Blob([archive.text], { type: 'application/json;charset=utf-8' });
    const url = URL.createObjectURL(blob), link = this.document.createElement('a');
    link.href = url; link.download = `ptah-workbench-${projectId || 'project'}-raw-recovery.json`; link.click(); URL.revokeObjectURL(url);
    this.notify(`已准备 ${recordCount} 份损坏存档的 JSON 下载；如果浏览器拦截或未开始下载，可打开“查看/复制原始存档”。`);
  }
  showCorruptDraftArchive() {
    const archive = this.buildCorruptDraftArchive();
    if (!archive) return this.notify('当前项目和版本没有需要查看的损坏存档。');
    const dialog = $('#raw-draft-recovery-dialog'), content = $('#raw-draft-recovery-content');
    if (!dialog || !content) return this.notify('原始存档查看窗口暂不可用；请重试下载。');
    content.value = archive.text;
    $('#raw-draft-recovery-status').textContent = '';
    if (!this.legacyWorkbench.showWorkbenchDialog(dialog)) return false;
    content.focus?.({ preventScroll: true });
    return true;
  }
  async copyCorruptDraftArchive() {
    const dialog = $('#raw-draft-recovery-dialog'), content = $('#raw-draft-recovery-content'), status = $('#raw-draft-recovery-status');
    if (!dialog || !content || !status) return false;
    const attempt = this.rawDraftCopyAttempt = (this.rawDraftCopyAttempt || 0) + 1;
    const manualCopyStatus = '原文已选中，可按 Ctrl+C 或 ⌘C 复制。';
    const isCurrentAttempt = () => dialog.open && this.rawDraftCopyAttempt === attempt && status.textContent === manualCopyStatus;
    content.focus?.({ preventScroll: true }); content.select?.();
    status.textContent = manualCopyStatus;
    const clipboard = this.document.defaultView?.navigator?.clipboard;
    if (!clipboard?.writeText) return false;

    let timeoutHandle = null, writeResult;
    try { writeResult = clipboard.writeText(content.value); }
    catch { writeResult = Promise.reject(new Error('clipboard write failed')); }
    const copied = await Promise.race([
      Promise.resolve(writeResult).then(() => true, () => false),
      new Promise(resolve => { timeoutHandle = this.timers.setTimeout(() => resolve(false), 1500); }),
    ]);
    if (timeoutHandle != null) this.timers.clearTimeout(timeoutHandle);
    if (copied && isCurrentAttempt()) {
      status.textContent = '原始存档 JSON 已复制到剪贴板。';
      return true;
    }
    if (isCurrentAttempt()) { content.focus?.({ preventScroll: true }); content.select?.(); }
    return false;
  }
  resetDraftConflictContext() {
    this.draftBaselineKey = null; this.draftStorageBaseline = undefined; this.draftAlternates = []; this.pendingDraftConflict = null; this.draftConflictRefresh = null;
    const dialog = $('#draft-conflict-dialog'); if (dialog?.open) dialog.close?.();
  }
  draftConflictTarget(snapshot) {
    if (!snapshot) return null;
    return { storeId: this.storageId(), key: this.makeDraftKey(snapshot), projectId: snapshot.projectId || snapshot.id,
      publicationRevision: snapshot.publicationRevision ?? 'unknown', kind: snapshot.kind || null,
      sourceCommit: snapshot.sourceCommit || null, baseCommit: snapshot.baseCommit || null,
      candidateId: snapshot.candidateId || null, snapshotId: snapshot.id || null };
  }
  sameDraftConflictTarget(conflict, snapshot) {
    const prior = conflict?.scope || this.draftConflictTarget(conflict?.snapshot), next = this.draftConflictTarget(snapshot);
    if (!prior || !next || !prior.key || prior.key !== next.key) return false;
    return prior.storeId === next.storeId && prior.projectId === next.projectId &&
      String(prior.publicationRevision) === String(next.publicationRevision) && prior.kind === next.kind &&
      prior.sourceCommit === next.sourceCommit && prior.baseCommit === next.baseCommit &&
      prior.candidateId === next.candidateId &&
      (!prior.snapshotId || !next.snapshotId || prior.snapshotId === next.snapshotId);
  }
  beginDraftConflictRefresh(generation, projectId, snapshot) {
    this.draftConflictRefresh = null;
    if (!snapshot || (snapshot.projectId || snapshot.id) !== projectId) return;
    const refresh = { generation, projectId, snapshot, scope: this.draftConflictTarget(snapshot) };
    this.draftConflictRefresh = refresh;
    const conflict = this.pendingDraftConflict;
    if (!conflict || conflict.key !== this.draftKey || !this.sameDraftConflictTarget(conflict, snapshot)) return;
    conflict.refreshing = true; conflict.refreshGeneration = generation; conflict.refreshError = null; conflict.scopeChanged = false;
    conflict.local = this.currentDraftRecord() || conflict.local;
    this.renderDraftConflictDialog(); this.showDraftState();
  }
  finishDraftConflictRefresh(generation, snapshot, { error = null, preservedDraft = null } = {}) {
    const refresh = this.draftConflictRefresh;
    if (!refresh || refresh.generation !== generation) return;
    this.draftConflictRefresh = null;
    const conflict = this.pendingDraftConflict;
    if (!conflict) return;
    if (error && this.snapshot === refresh.snapshot && this.projectId === refresh.projectId && this.sameDraftConflictTarget(conflict, refresh.snapshot)) {
      conflict.snapshot = refresh.snapshot; conflict.scope = refresh.scope; conflict.generation = this.workbenchGeneration;
      conflict.refreshing = false; conflict.refreshGeneration = null; conflict.scopeChanged = false;
      conflict.refreshError = error.message || '状态读取失败';
    } else if (!error && this.snapshot === snapshot && this.projectId === refresh.projectId && this.sameDraftConflictTarget(conflict, snapshot)) {
      conflict.snapshot = snapshot; conflict.scope = this.draftConflictTarget(snapshot); conflict.generation = this.workbenchGeneration;
      conflict.refreshing = false; conflict.refreshGeneration = null; conflict.scopeChanged = false; conflict.refreshError = null;
      const local = this.draftCopy(preservedDraft) || this.currentDraftRecord();
      if (local) conflict.local = { ...conflict.local, ...local, key: conflict.key,
        projectId: snapshot.projectId || snapshot.id, publicationRevision: snapshot.publicationRevision,
        sourceCommit: snapshot.sourceCommit || null, baseCommit: snapshot.baseCommit || null,
        draftRevision: this.draftRevision || local.draftRevision || 0 };
    } else if (conflict.refreshGeneration === generation) {
      conflict.refreshing = false; conflict.refreshGeneration = null; conflict.scopeChanged = true;
      conflict.refreshError = error?.message || '当前项目、发布版本、来源或返修候选已变化';
    }
    if (this.pendingDraftConflict === conflict) { this.renderDraftConflictDialog(); this.showDraftState(); }
  }
  draftContent(value) {
    if (!value || typeof value !== 'object') return null;
    const content = cloneValue(value);
    for (const key of ['key', 'projectId', 'publicationRevision', 'sourceCommit', 'baseCommit', 'candidateId',
      'draftRevision', 'updatedAt', 'draftConflictAlternates', 'selectedObjectId']) delete content[key];
    content.text = value.text || '';
    content.values = cloneValue(value.values || {});
    content.fields = cloneValue(value.fields || {});
    content.feedback = cloneValue(Array.isArray(value.feedback) ? value.feedback : []);
    content.feedbackInputs = cloneValue(value.feedbackInputs || {});
    content.feedbackInputTargetId = value.feedbackInputTargetId || null;
    content.legacyUnboundFeedback = cloneValue(value.legacyUnboundFeedback || null);
    content.proposalInputs = cloneValue(value.proposalInputs || {});
    content.feedbackMessage = value.feedbackMessage || '';
    content.feedbackCategory = value.feedbackCategory || 'general';
    content.targetNotes = cloneValue(value.targetNotes || {});
    content.structuralProposals = cloneValue(Array.isArray(value.structuralProposals) ? value.structuralProposals : []);

    // In objects-v1, `text` mirrors the note in the currently selected target.
    // Ignore that editor mirror only when the same text is present on the same
    // bound target; old unbound text and notes bound elsewhere remain content.
    const selectedTarget = value.selectedObjectId || null;
    const notes = value.targetNotes && typeof value.targetNotes === 'object' ? value.targetNotes : {};
    const noteTargetId = (key, note) => this.legacyWorkbench?.noteTargetId
      ? this.legacyWorkbench.noteTargetId(key, note)
      : (note && Object.hasOwn(note, 'objectId') ? note.objectId : key === '__project__' ? null : key);
    const emptyObjectsText = this.objectsWorkflow() && !String(value.text || '').trim();
    const textMirror = this.objectsWorkflow() && (emptyObjectsText || Object.entries(notes).some(([key, note]) =>
      String(note?.text || '') === String(value.text || '') && noteTargetId(key, note) === selectedTarget));
    if (textMirror) delete content.text;

    // These legacy editor fields mirror a target-bound pending input, or the
    // legacy unbound input. Keep them when the binding/content does not match.
    const feedbackMessage = String(value.feedbackMessage || '');
    const feedbackCategory = value.feedbackCategory || 'general';
    const feedbackTargetId = typeof value.feedbackInputTargetId === 'string' ? value.feedbackInputTargetId : null;
    const boundInput = feedbackTargetId ? value.feedbackInputs?.[feedbackTargetId] : null;
    const boundFeedbackMirror = !!feedbackMessage && !!boundInput &&
      String(boundInput.message || '') === feedbackMessage && (boundInput.category || 'general') === feedbackCategory;
    const unboundInput = value.legacyUnboundFeedback;
    const unboundFeedbackMirror = !!feedbackMessage && !!unboundInput &&
      String(unboundInput.message || '') === feedbackMessage && (unboundInput.category || 'general') === feedbackCategory;
    if (boundFeedbackMirror || unboundFeedbackMirror || !feedbackMessage) {
      delete content.feedbackMessage; delete content.feedbackCategory; delete content.feedbackInputTargetId;
    }

    const timestamps = new Set(['createdAt', 'updatedAt', 'timestamp', 'capturedAt', 'savedAt', 'backedUpAt']);
    const stripKnownTimes = item => {
      if (Array.isArray(item)) return item.map(stripKnownTimes);
      if (!item || typeof item !== 'object') return item;
      return Object.fromEntries(Object.entries(item).filter(([key]) => !timestamps.has(key))
        .map(([key, nested]) => [key, stripKnownTimes(nested)]));
    };
    return stripKnownTimes(content);
  }
  semanticDraftEntries(value) {
    const draftObjectNames = new Map();
    for (const operation of Array.isArray(value?.structuralProposals) ? value.structuralProposals : []) {
      if (!operation || typeof operation !== 'object' || typeof operation.name !== 'string' || !operation.name.trim()) continue;
      const id = operation.kind === 'new-scene' ? operation.sceneId : operation.kind === 'new-instance' ? operation.instanceId : null;
      if (typeof id === 'string' && id.trim()) draftObjectNames.set(id, operation.name.trim());
    }
    const entries = new Map(), targetLabel = id => {
      if (id == null || id === '__project__') return '项目';
      const name = draftObjectNames.get(id) || this.objectItems().find(item => item.id === id)?.name || id;
      return `${name}（${id}）`;
    };
    const categoryLabel = value => this.legacyWorkbench?.feedbackCategoryLabel?.(value) || String(value || 'general');
    const clean = (item, parentKey = '') => {
      if (Array.isArray(item)) return item.map(value => clean(value));
      if (!item || typeof item !== 'object') return item;
      return Object.fromEntries(Object.entries(item).filter(([key]) => !['createdAt', 'updatedAt', 'timestamp', 'capturedAt', 'savedAt', 'backedUpAt'].includes(key)).map(([key, nested]) => [key, clean(nested, key)]));
    };
    const add = (key, targetId, category, content, legacy = false) => entries.set(key, { key, targetId: targetId || null, target: targetLabel(targetId), category, content: clean(content), legacy });
    if (!this.objectsWorkflow() && String(value?.text || '').trim()) add('project:text', null, '项目意见', String(value.text));
    if (this.objectsWorkflow() && String(value?.text || '').trim() && !Object.values(value?.targetNotes || {}).some(note => String(note?.text || '') === String(value.text))) {
      add('legacy-unbound-text', null, '旧版未绑定意见', String(value.text), true);
    }
    for (const [id, fieldValue] of Object.entries(value?.fields || {})) {
      const objectId = id.includes('.') ? id.slice(0, id.indexOf('.')) : null;
      add(`field:${id}`, objectId, `属性 ${id.includes('.') ? id.slice(id.indexOf('.') + 1) : id}`, fieldValue);
    }
    for (const [id, fieldValue] of Object.entries(value?.values || {})) add(`value:${id}`, null, `旧版属性 ${id}`, fieldValue, true);
    for (const [key, note] of Object.entries(value?.targetNotes || {})) {
      if (!note || typeof note !== 'object' || !String(note.text || '').trim()) continue;
      const objectId = Object.hasOwn(note, 'objectId') ? note.objectId : key === '__project__' ? null : key;
      const identity = note.feedbackId || key;
      if (note.decisionFor) {
        add(`note-source:${identity}`, objectId, '相关意见原文', note.decisionContext?.sourceText || '原意见原文未保留', !note.decisionContext?.sourceText);
        add(`note-decision:${identity}`, objectId, '用户处理决定', String(note.text));
      } else {
        const hasBoundTarget = note.objectId === null || (typeof note.objectId === 'string' && !!note.objectId) || key === '__project__' || this.objectItems().some(item => item.id === key);
        add(`note:${identity}`, objectId, '意见原文', String(note.text), !note.feedbackId || !hasBoundTarget);
      }
    }
    for (const item of Array.isArray(value?.feedback) ? value.feedback : []) {
      if (!item || typeof item !== 'object') continue;
      const category = item.category || 'general', stable = item.feedbackId || `legacy:${canonicalValue([item.objectId || null, category, String(item.message || '')])}`;
      add(`feedback:${stable}`, item.objectId || null, `${item.feedbackId ? '分类意见' : '旧版未编号意见'} · 类别 ${categoryLabel(category)}`, String(item.message || ''), !item.feedbackId || !item.objectId);
    }
    for (const [objectId, item] of Object.entries(value?.feedbackInputs || {})) {
      if (!item || typeof item !== 'object' || !String(item.message || '').trim()) continue;
      add(`feedback-input:${objectId}`, objectId, `待添加分类意见 · 类别 ${categoryLabel(item.category)}`, String(item.message));
    }
    const unbound = value?.legacyUnboundFeedback && typeof value.legacyUnboundFeedback === 'object' ? value.legacyUnboundFeedback : null;
    if (String(unbound?.message || '').trim()) add('legacy-unbound-feedback', null, `旧版未绑定反馈 · 类别 ${categoryLabel(unbound.category)}`, String(unbound.message), true);
    else if (!Object.values(value?.feedbackInputs || {}).some(item => String(item?.message || '').trim()) && String(value?.feedbackMessage || '').trim()) add('legacy-feedback-mirror', null, `旧版未绑定反馈 · 类别 ${categoryLabel(value.feedbackCategory)}`, String(value.feedbackMessage), true);
    for (const [proposalId, revisions] of Object.entries(value?.proposalInputs || {})) {
      if (!revisions || typeof revisions !== 'object' || Array.isArray(revisions)) continue;
      for (const [revision, record] of Object.entries(revisions)) {
        if (!record || typeof record !== 'object' || Array.isArray(record)) continue;
        const proposalRevision = `方案 ${proposalId} · 修订 r${revision}`;
        const questions = record.questions && typeof record.questions === 'object' && !Array.isArray(record.questions) ? record.questions : {};
        const prompts = record.questionPrompts && typeof record.questionPrompts === 'object' && !Array.isArray(record.questionPrompts) ? record.questionPrompts : {};
        for (const [questionId, answer] of Object.entries(questions)) {
          if (answer == null || !String(answer).trim()) continue;
          const prompt = String(prompts[questionId] || questionId);
          const key = `proposal-answer:${canonicalValue([proposalId, revision, questionId])}`;
          add(key, null, `策划问题回答 · ${proposalRevision} · ${prompt}（问题 ${questionId}）`, String(answer));
          entries.get(key).displayContent = this.storedQuestionLabel(record, questionId, answer);
        }
        const supplement = String(record.readySupplement ?? '').trim();
        if (supplement) add(`proposal-ready-supplement:${canonicalValue([proposalId, revision])}`, null,
          `READY 补充 · ${proposalRevision}`, supplement);
        if (Array.isArray(record.visualReferences)) add(`proposal-visual-references:${canonicalValue([proposalId, revision])}`, null,
          `视觉参考修订 · ${proposalRevision}`, record.visualReferences);
      }
    }
    const operations = Array.isArray(value?.structuralProposals) ? value.structuralProposals : [];
    for (const operation of operations) {
      if (!operation || typeof operation !== 'object') continue;
      const stable = operation.operationId || operation.proposalId;
      const targetId = operation.objectId || operation.instanceId || operation.sceneId || null;
      const fallback = `legacy:${operation.kind || 'operation'}:${targetId || operation.name || canonicalValue(clean(operation))}`;
      add(`operation:${stable || fallback}`, targetId, stable ? '结构操作' : '旧版未绑定结构操作', this.semanticOperationSummary(operation), !stable);
    }
    return entries;
  }
  semanticOperationSummary(operation) {
    const labels = { 'new-scene': '提议新场景', 'new-instance': '提议新实例', 'delete-instance': '提议移除实例', 'set-lock': '提议更改实例约束', 'move-instance': '提议移动实例', 'transition': '提议场景过渡' };
    const names = { sceneId: '场景', instanceId: '实例', objectId: '对象', definitionId: '共享定义', name: '名称', scope: '影响范围', requestedPosition: '期望位置', position: '位置', requestedLock: '期望约束', lock: '约束', bounds: '边界', targetSceneId: '目标场景', entryId: '入口', mode: '方式', presetId: '预设' };
    const parts = [labels[operation.kind] || operation.kind || '结构提案'];
    for (const [key, value] of Object.entries(operation)) {
      if (['operationId', 'proposalId', 'createdAt', 'updatedAt', 'kind'].includes(key) || value == null || value === '') continue;
      parts.push(`${names[key] || key}：${this.semanticDraftValue(value)}`);
    }
    return parts.join(' · ');
  }
  draftConflictScopeIsCurrent() {
    const conflict = this.pendingDraftConflict, snapshot = this.snapshot;
    return !!conflict && conflict.key === this.draftKey && !conflict.scopeChanged &&
      conflict.generation === this.workbenchGeneration && conflict.snapshot === snapshot &&
      this.projectId === (snapshot?.projectId || snapshot?.id) && this.sameDraftConflictTarget(conflict, snapshot);
  }
  draftFieldSourceContext(entryKey) {
    const identity = String(entryKey || '').startsWith('field:') ? String(entryKey).slice(6) : '';
    if (!identity || !this.draftConflictScopeIsCurrent()) return { resolvable: false, declared: false };
    const capabilities = this.allCapabilities();
    const exactCapability = capabilities.find(item => {
      const parts = this.splitCapability(item);
      return !!parts.objectId && !!parts.fieldId && `${parts.objectId}.${parts.fieldId}` === identity;
    });
    const objects = this.objectItems();
    const object = exactCapability
      ? objects.find(item => item.id === this.splitCapability(exactCapability).objectId)
      : objects.filter(item => typeof item.id === 'string' && identity.startsWith(`${item.id}.`))
        .sort((left, right) => right.id.length - left.id.length)[0];
    const splitAt = object ? object.id.length : identity.indexOf('.');
    if (splitAt <= 0 || splitAt >= identity.length - 1) return { resolvable: false, declared: false };
    const objectId = object?.id || identity.slice(0, splitAt);
    const fieldId = identity.slice(splitAt + 1);
    const capability = exactCapability || capabilities.find(item => {
      const parts = this.splitCapability(item);
      return parts.objectId === objectId && parts.fieldId === fieldId;
    });
    if (!object || object.id !== objectId) return { resolvable: false, declared: false, objectId, fieldId };
    const field = (object.fields || []).find(item => item?.id === fieldId) || null;
    let declaredNull = false;
    for (const source of [capability, field]) {
      if (!source || typeof source !== 'object') continue;
      for (const property of ['currentValue', 'value']) {
        if (!Object.hasOwn(source, property) || source[property] === undefined) continue;
        if (source[property] === null) { declaredNull = true; continue; }
        return { resolvable: true, declared: true, objectId, fieldId, value: source[property],
          unit: this.fieldUnit(capability, field) };
      }
    }
    if (declaredNull) {
      return { resolvable: true, declared: true, objectId, fieldId, value: null,
        unit: this.fieldUnit(capability, field) };
    }
    return { resolvable: true, declared: false, objectId, fieldId, unit: this.fieldUnit(capability, field) };
  }
  semanticFieldValue(value, unit = null, { source = false } = {}) {
    let label = value === '' ? '空文本'
      : value === null && source ? 'null（来源声明）' : this.semanticDraftValue(value);
    if (unit && value !== null) label += ` ${unit}`;
    return label;
  }
  semanticFieldSourceLabel(source) {
    if (!source.resolvable) return '来源当前值无法确认';
    if (!source.declared) return '来源当前值未声明';
    const revision = this.snapshot?.publicationRevision ?? '未知';
    return `沿用来源版本 ${revision} 的当前值：${this.semanticFieldValue(source.value, source.unit, { source: true })}`;
  }
  renderDraftSemanticComparison(local, remote, remoteLabel = '存储活动稿') {
    const localEntries = this.semanticDraftEntries(local), remoteEntries = this.semanticDraftEntries(remote);
    const keys = new Set([...localEntries.keys(), ...remoteEntries.keys()]), changed = [];
    for (const key of keys) {
      const left = localEntries.get(key), right = remoteEntries.get(key);
      if (left && right && left.targetId === right.targetId && left.category === right.category && sameValue(left.content, right.content)) continue;
      const differences = [];
      if (left && right && left.targetId !== right.targetId) differences.push('目标变化');
      if (left && right && left.category !== right.category) differences.push('分类变化');
      if (left && right && !sameValue(left.content, right.content)) differences.push('内容变化');
      const propertyCoverage = (!left || !right) && key.startsWith('field:');
      const status = propertyCoverage ? '本轮属性修改不同'
        : !left ? '新增' : !right ? '删除' : differences.length ? `修改 · ${differences.join('、')}` : '修改';
      changed.push({ left, right, target: (right || left).target, category: (right || left).category, status,
        propertyCoverage, fieldSource: propertyCoverage ? this.draftFieldSourceContext(key) : null });
    }
    const comparison = el('section', 'draft-conflict-semantic');
    comparison.append(el('h3', '', '按目标比较实际内容'));
    comparison.append(el('p', 'muted', '比较按属性 ID、意见 ID 和操作 ID 匹配；不按列表位置猜测。时间、当前选中对象和编辑框镜像值不作为内容差异。旧版或未绑定内容会按现有信息显示，并标明未绑定。'));
    if (!changed.length) comparison.append(el('p', 'notice', '没有发现实际内容差异。'));
    const groups = new Map();
    for (const item of changed) { if (!groups.has(item.target)) groups.set(item.target, []); groups.get(item.target).push(item); }
    for (const [target, items] of groups) {
      const section = el('section', 'draft-conflict-target'); section.append(el('h4', '', `目标：${target}`));
      for (const item of items) {
        const row = el('article', 'draft-conflict-diff');
        row.append(el('b', '', `${item.status} · ${item.category}${(item.left || item.right).legacy ? ' · 旧版 / 未绑定' : ''}`));
        if (item.left) row.append(el('p', '', `本页当前稿：目标 ${item.left.target} · ${item.left.category}：${item.propertyCoverage
          ? `本轮期望 ${this.semanticFieldValue(item.left.content, item.fieldSource.unit)}（尚未制作）`
          : item.left.displayContent ?? this.semanticDraftValue(item.left.content)}`));
        else row.append(el('p', 'muted', item.propertyCoverage
          ? `本页当前稿：无本轮覆盖；${this.semanticFieldSourceLabel(item.fieldSource)}` : '本页当前稿：无此内容'));
        if (item.right) row.append(el('p', '', `${remoteLabel}：目标 ${item.right.target} · ${item.right.category}：${item.propertyCoverage
          ? `本轮期望 ${this.semanticFieldValue(item.right.content, item.fieldSource.unit)}（尚未制作）`
          : item.right.displayContent ?? this.semanticDraftValue(item.right.content)}`));
        else row.append(el('p', 'muted', item.propertyCoverage
          ? `${remoteLabel}：无本轮覆盖；${this.semanticFieldSourceLabel(item.fieldSource)}` : `${remoteLabel}：无此内容`));
        if (item.left?.displayContent !== undefined || item.right?.displayContent !== undefined) {
          const stored = el('details'); stored.append(el('summary', '', '查看回答存档值'),
            el('pre', '', `本页当前稿：${this.semanticDraftValue(item.left?.content)}\n${remoteLabel}：${this.semanticDraftValue(item.right?.content)}`));
          row.append(stored);
        }
        section.append(row);
      }
      comparison.append(section);
    }
    return comparison;
  }
  semanticDraftValue(value) { return typeof value === 'string' ? value : JSON.stringify(value, null, 2); }
  sameDraftContent(left, right) { return sameValue(this.draftContent(left), this.draftContent(right)); }
  draftRecordMatchesScope(value, key = this.draftKey, snapshot = this.snapshot) {
    if (!value || typeof value !== 'object' || !snapshot || !key) return false;
    return value.key === key && value.projectId === (snapshot.projectId || snapshot.id) &&
      String(value.publicationRevision ?? 'unknown') === String(snapshot.publicationRevision ?? 'unknown') &&
      (value.sourceCommit || null) === (snapshot.sourceCommit || null) &&
      (value.baseCommit || null) === (snapshot.baseCommit || null);
  }
  readDraftRawRecord(key, raw) {
    if (raw == null || raw === 'null') return null;
    return this.drafts.readStored(key, raw);
  }
  async reconcileEnvelopeDrift({ baselineRaw, latestRaw, latest, active = null, variants = [], operationId = null }) {
    const key = this.draftKey, snapshot = this.snapshot, generation = this.workbenchGeneration;
    operationId ??= this.beginDraftOperation();
    const ownsOperation = () => this.draftOperationMatches(operationId, key, generation, snapshot);
    let baseline;
    try { baseline = this.readDraftRawRecord(key, baselineRaw); }
    catch (error) { return { status: 'error', error, latest, latestRaw }; }
    const isEnvelopeOnly = value => !!baseline && !!value &&
      this.draftRecordMatchesScope(baseline, key, snapshot) && this.draftRecordMatchesScope(value, key, snapshot) &&
      this.sameDraftContent(baseline, value);
    if (!isEnvelopeOnly(latest)) return { status: 'changed', baseline, latest, latestRaw };
    for (let attempt = 0; attempt < 3; attempt++) {
      if (!ownsOperation()) return { status: 'stale', baseline, latest, latestRaw };
      if (!isEnvelopeOnly(latest)) return { status: 'changed', baseline, latest, latestRaw };
      try {
        const merged = await this.saveConflictEnvelope(active || latest, [latest, baseline, ...variants].filter(Boolean), latestRaw, operationId);
        const mergedRaw = merged.draftStorageRaw;
        if (!this.draftContextMatches(key, generation, snapshot) || !ownsOperation()) {
          return { status: 'stale', baseline, latest: merged, latestRaw: mergedRaw };
        }
        return { status: 'saved', baseline, latest: merged, latestRaw: mergedRaw };
      } catch (error) {
        if (!ownsOperation() || error.name === 'DraftOperationStaleError') return { status: 'stale', baseline, latest, latestRaw };
        if (error.name !== 'DraftConflictError') return { status: 'error', error, baseline, latest, latestRaw };
        latest = error.latest; latestRaw = error.latestRaw;
        if (!isEnvelopeOnly(latest)) return { status: 'changed', baseline, latest, latestRaw };
      }
    }
    return { status: 'exhausted', baseline, latest, latestRaw };
  }
  formatDraftAlternateTime(value) {
    if (!value) return '时间未知';
    const date = new Date(value);
    if (!Number.isFinite(date.getTime())) return '时间未知';
    return new Intl.DateTimeFormat('zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }).format(date);
  }
  draftAlternateSummary(draft) {
    const compact = value => {
      const text = typeof value === 'string' ? value : JSON.stringify(value);
      const line = String(text ?? '').replace(/\s+/g, ' ').trim();
      return line.length > 68 ? `${line.slice(0, 30)}…${line.slice(-34)}` : line;
    };
    const parts = [];
    for (const [field, value] of Object.entries(draft?.fields || {})) parts.push(`字段 ${field}=${compact(value)}`);
    for (const [field, value] of Object.entries(draft?.values || {})) parts.push(`属性 ${field}=${compact(value)}`);
    const notes = Object.entries(draft?.targetNotes || {}).filter(([, note]) => String(note?.text || '').trim());
    for (const [target, note] of notes) parts.push(`意见 ${note.objectId || target}：${compact(note.text)}`);
    for (const item of (Array.isArray(draft?.structuralProposals) ? draft.structuralProposals : [])) {
      const bounds = Array.isArray(item?.bounds) && item.bounds.length >= 2 ? ` ${item.bounds[0]}×${item.bounds[1]}` : '';
      parts.push(`结构 ${item?.name || item?.kind || '提案'}${bounds}${item?.template ? ` · ${item.template}` : ''}`);
      if (item?.connections) parts.push(`连接：${compact(item.connections)}`);
    }
    return parts.join(' · ') || '没有可显示的内容摘要';
  }
  draftCopy(value) {
    if (!value || typeof value !== 'object') return null;
    const copy = cloneValue(value); delete copy.draftConflictAlternates; return copy;
  }
  draftAlternatesFrom(value) {
    return Array.isArray(value?.draftConflictAlternates)
      ? value.draftConflictAlternates.filter(item => item && typeof item === 'object' && item.draft && typeof item.draft === 'object')
      : [];
  }
  sameDraftAlternateSet(left, right) {
    const prior = this.draftAlternatesFrom({ draftConflictAlternates: left });
    const next = this.draftAlternatesFrom({ draftConflictAlternates: right });
    return prior.length === next.length && next.every(item => prior.some(existing => this.sameDraftContent(existing.draft, item.draft)));
  }
  storedDraftAlternates(active) {
    const result = [];
    for (const item of this.draftAlternatesFrom(active)) {
      const draft = this.draftCopy(item.draft);
      if (!draft || this.sameDraftContent(active, draft) || result.some(existing => this.sameDraftContent(existing.draft, draft))) continue;
      result.push({ ...item, draft });
    }
    return result;
  }
  mergeDraftAlternates(active, drafts = []) {
    const inheritedAlternates = drafts.flatMap(draft => this.draftAlternatesFrom(draft));
    const result = [], candidates = [...this.draftAlternatesFrom(active), ...this.draftAlternates, ...inheritedAlternates, ...drafts
      .filter(draft => draft && typeof draft === 'object')
      .map(draft => ({ label: '自动保留的完整版本', capturedAt: new Date().toISOString(), draft: this.draftCopy(draft) }))];
    for (const item of candidates) {
      const draft = this.draftCopy(item.draft);
      if (!draft || this.sameDraftContent(active, draft) || result.some(existing => this.sameDraftContent(existing.draft, draft))) continue;
      result.push({ label: item.label || '已保留的草稿', capturedAt: item.capturedAt || new Date().toISOString(), draft });
    }
    return result;
  }
  currentDraftRecord() {
    if (!this.draftKey || !this.snapshot) return null;
    return { ...this.readVisibleDraft(), key: this.draftKey, projectId: this.snapshot.projectId || this.snapshot.id,
      publicationRevision: this.snapshot.publicationRevision, sourceCommit: this.snapshot.sourceCommit || null,
      baseCommit: this.snapshot.baseCommit || null, draftRevision: this.draftRevision || 0,
      draftConflictAlternates: cloneValue(this.draftAlternates || []), updatedAt: new Date().toISOString() };
  }
  updateDraftBaseline(key, value, raw) {
    if (this.draftKey !== key) return false;
    if (raw === undefined) throw new TypeError('更新草稿基线必须提供与记录成对的 exact raw。');
    this.draftBaselineKey = key;
    this.draftStorageBaseline = raw;
    this.draftAlternates = this.draftAlternatesFrom(value);
    return true;
  }
  pairDraftRecordWithRaw(record, raw) {
    if (record && typeof record === 'object') Object.defineProperty(record, 'draftStorageRaw', { value: raw, configurable: true });
    return record;
  }
  async saveConflictEnvelope(active, variants, expectedRaw, operationId = null) {
    const key = this.draftKey, snapshot = this.snapshot, generation = this.workbenchGeneration;
    operationId ??= this.beginDraftOperation();
    const ownsOperation = () => this.draftOperationMatches(operationId, key, generation, snapshot);
    const alternatives = this.mergeDraftAlternates(active, variants);
    // Compare against the actual record represented by expectedRaw. `active`
    // can be a local candidate and the page cache cannot stand in for storage.
    const persistedActive = this.readDraftRawRecord(key, expectedRaw);
    const existingAlternates = this.storedDraftAlternates(persistedActive);
    if (persistedActive && this.sameDraftContent(persistedActive, active) &&
        this.sameDraftAlternateSet(existingAlternates, alternatives) && typeof this.drafts.raw === 'function') {
      const currentRaw = this.drafts.raw(key);
      if (currentRaw !== expectedRaw) {
        const error = new Error('存储中的活动草稿已变化；当前输入仍在本页，没有覆盖存储内容。');
        error.name = 'DraftConflictError'; error.latestRaw = currentRaw;
        error.latest = currentRaw === null || currentRaw === 'null' ? null : this.drafts.readStored(key, currentRaw);
        throw error;
      }
      if (!ownsOperation()) { const error = new Error('草稿操作已被较新的同范围操作取代。'); error.name = 'DraftOperationStaleError'; throw error; }
      if (this.draftContextMatches(key, generation, snapshot)) {
        this.draftRevision = Math.max(this.draftRevision || 0, Number(persistedActive?.draftRevision || 0));
        this.updateDraftBaseline(key, persistedActive, expectedRaw);
      }
      return this.pairDraftRecordWithRaw(persistedActive, expectedRaw);
    }
    if (!ownsOperation()) { const error = new Error('草稿操作已被较新的同范围操作取代。'); error.name = 'DraftOperationStaleError'; throw error; }
    const newestRevision = Math.max(Number(active?.draftRevision || 0), ...variants.map(item => Number(item?.draftRevision || 0))) + 1;
    const record = { ...(this.draftCopy(active) || {}), key,
      projectId: snapshot?.projectId || snapshot?.id, publicationRevision: snapshot?.publicationRevision,
      draftRevision: newestRevision, updatedAt: new Date().toISOString(), draftConflictAlternates: alternatives };
    const raw = JSON.stringify(record);
    if (this.drafts.putIfUnchanged) this.drafts.putIfUnchanged(record, expectedRaw);
    else await this.drafts.put(record);
    if (this.draftOperationMatches(operationId, key, generation, snapshot)) {
      this.draftRevision = Math.max(this.draftRevision || 0, newestRevision);
      this.updateDraftBaseline(key, record, raw);
    }
    return this.pairDraftRecordWithRaw(record, raw);
  }
  async beginDraftConflict(local, remote, remoteRaw, prior = null, operationId = null) {
    const key = this.draftKey, snapshot = this.snapshot, generation = this.workbenchGeneration;
    operationId ??= this.beginDraftOperation();
    const ownsOperation = () => this.draftOperationMatches(operationId, key, generation, snapshot);
    if (!key || !snapshot || !ownsOperation()) return false;
    const retainedPrior = prior && this.hasUnsubmittedDraft(prior) ? this.draftCopy(prior) : null;
    const conflict = { key, local: this.draftCopy(local) || this.currentDraftRecord(), remote: this.draftCopy(remote),
      remoteRaw, activeRaw: remoteRaw, comparisonActive: this.draftCopy(remote), prior: retainedPrior,
      recovery: false, generation, snapshot, scope: this.draftConflictTarget(snapshot) };
    if (this.draftConflictRefresh?.generation === generation && this.sameDraftConflictTarget(conflict, this.draftConflictRefresh.snapshot)) {
      conflict.refreshing = true; conflict.refreshGeneration = generation;
    }
    this.pendingDraftConflict = conflict;
    this.draftAlternates = this.mergeDraftAlternates(remote, [conflict.local, conflict.prior].filter(Boolean));
    let latest = conflict.remote, latestRaw = remoteRaw;
    // If another page writes again while we are preserving this conflict, retry
    // against its exact bytes. Never turn a failed comparison into an overwrite.
    for (let attempt = 0; latest && attempt < 3; attempt++) {
      try {
        const merged = await this.saveConflictEnvelope(latest, [conflict.local, conflict.prior].filter(Boolean), latestRaw, operationId);
        if (this.pendingDraftConflict !== conflict || !ownsOperation()) return false;
        latestRaw = merged.draftStorageRaw;
        conflict.remote = this.draftCopy(merged); conflict.remoteRaw = latestRaw;
        conflict.activeRaw = latestRaw; conflict.comparisonActive = this.draftCopy(merged);
        break;
      } catch (error) {
        if (this.pendingDraftConflict !== conflict || !ownsOperation() || error.name === 'DraftOperationStaleError') return false;
        if (error.name !== 'DraftConflictError') {
          this.showDraftState(`草稿分支保留失败：${error.message}。当前输入仍在本页，请先复制保存。`, true);
          break;
        }
        latest = error.latest; latestRaw = error.latestRaw;
        conflict.remote = this.draftCopy(latest); conflict.remoteRaw = latestRaw;
        this.draftAlternates = this.draftAlternatesFrom(latest);
      }
    }
    if (!latest) {
      // A deletion/tombstone is still a meaningful competing state. Let the
      // user compare it, and make a later explicit choice use that exact base.
      this.updateDraftBaseline(key, null, latestRaw);
      conflict.remote = null; conflict.remoteRaw = latestRaw;
    }
    if (this.pendingDraftConflict === conflict && ownsOperation()) {
      this.renderDraftConflictDialog(); this.showDraftState();
      return true;
    }
    return false;
  }
  async retainPendingDraftInput(operationId = null) {
    const conflict = this.pendingDraftConflict, key = this.draftKey;
    if (!conflict || conflict.key !== key) return false;
    const generation = this.workbenchGeneration, snapshot = this.snapshot;
    operationId ??= this.beginDraftOperation();
    const ownsOperation = () => this.pendingDraftConflict === conflict && this.draftOperationMatches(operationId, key, generation, snapshot);
    if (!ownsOperation()) return false;
    if (conflict.scopeChanged || !this.sameDraftConflictTarget(conflict, this.snapshot)) {
      conflict.local = this.currentDraftRecord() || conflict.local;
      this.showDraftState('比较来源已变化；当前输入仍留在页面，旧冲突不会写入新的项目或发布范围。', true);
      return false;
    }
    const local = this.currentDraftRecord() || conflict.local;
    const currentRaw = this.drafts.raw ? this.drafts.raw(key) : conflict.remoteRaw;
    const remote = currentRaw === null || currentRaw === 'null' ? null : this.drafts.readStored(key, currentRaw);
    conflict.local = local;
    if (!remote) {
      conflict.remote = null; conflict.remoteRaw = currentRaw;
      this.updateDraftBaseline(key, null, currentRaw);
      this.renderDraftConflictDialog(); this.showDraftState(); return false;
    }
    try {
      const merged = await this.saveConflictEnvelope(remote, [local], currentRaw, operationId);
      if (!ownsOperation()) return false;
      conflict.remote = this.draftCopy(merged); conflict.remoteRaw = merged.draftStorageRaw;
      this.renderDraftConflictDialog(); this.showDraftState();
      return true;
    } catch (error) {
      if (!ownsOperation() || error.name === 'DraftOperationStaleError') return false;
      if (error.name === 'DraftConflictError') {
        conflict.remote = error.latest; conflict.remoteRaw = error.latestRaw; this.draftAlternates = this.draftAlternatesFrom(error.latest);
        this.renderDraftConflictDialog(); this.showDraftState();
      } else this.showDraftState(`草稿分支保留失败：${error.message}。输入仍在此页面，请先比较并保存。`, true);
      return false;
    }
  }
  ensureDraftConflictDialog() {
    let dialog = $('#draft-conflict-dialog'); if (dialog) return dialog;
    dialog = el('dialog', 'draft-conflict-dialog'); dialog.id = 'draft-conflict-dialog'; dialog.setAttribute('aria-labelledby', 'draft-conflict-title');
    this.document.body.append(dialog); return dialog;
  }
  canDeferHistoricalDraftConflict(conflict) {
    if (this.pendingDraftConflict !== conflict || conflict?.recovery !== true || !this.draftConflictScopeIsCurrent()) return false;
    const key = conflict.key, snapshot = this.snapshot, generation = this.workbenchGeneration;
    if (!this.persistenceOK || this.draftBaselineKey !== key || conflict.refreshing || conflict.refreshGeneration != null || conflict.scopeChanged || conflict.refreshError ||
        this.draftSaveQueuedDuringRestore || this.matchesDraftRestore(this.draftRestoreContext, key, generation, snapshot) ||
        (this.draftConflictRefresh?.generation === generation && this.draftConflictRefresh.snapshot === snapshot) ||
        this.makeDraftKey(snapshot) !== key || typeof this.drafts?.raw !== 'function' || typeof this.drafts?.readStored !== 'function') return false;
    try {
      const currentRaw = this.drafts.raw(key);
      if (typeof currentRaw !== 'string' || !currentRaw || currentRaw !== this.draftStorageBaseline || currentRaw !== conflict.activeRaw) return false;
      const active = this.readDraftRawRecord(key, currentRaw);
      const comparedActive = conflict.comparisonActive;
      // `local` is the full page draft captured when this modal opened. Normal
      // edits made while a conflict is pending refresh it through the existing
      // save path, so compare the whole business record without recapturing or
      // mutating the page model here.
      return !!active && !!comparedActive && !!conflict.local &&
        this.draftRecordMatchesScope(active, key, snapshot) &&
        this.draftRecordMatchesScope(comparedActive, key, snapshot) &&
        this.draftRecordMatchesScope(conflict.local, key, snapshot) &&
        this.sameDraftContent(active, comparedActive) && this.sameDraftContent(active, conflict.local);
    } catch {
      return false;
    }
  }
  deferDraftConflict(conflict, dialog) {
    if (this.pendingDraftConflict !== conflict) return false;
    const safeToEndBrowsing = this.canDeferHistoricalDraftConflict(conflict);
    if (this.pendingDraftConflict !== conflict) return false;
    if (safeToEndBrowsing) this.pendingDraftConflict = null;
    if (dialog?.open) {
      try { dialog.close?.(); } catch {}
      if (dialog.open) dialog.open = false;
    }
    this.showDraftState(safeToEndBrowsing
      ? '已结束保留稿比较；当前工作稿未切换，保留版本仍可查看。'
      : null);
    return safeToEndBrowsing;
  }
  renderDraftConflictDialog() {
    const conflict = this.pendingDraftConflict; if (!conflict) return;
    const dialog = this.ensureDraftConflictDialog();
    const activeElement = this.document.activeElement;
    const focusedAlternate = activeElement?.__draftAlternate ? this.draftCopy(activeElement.__draftAlternate) : null;
    const focusedSearch = activeElement?.dataset?.draftAlternateSearch === 'true';
    const searchCaret = focusedSearch ? activeElement.selectionStart : null;
    dialog.replaceChildren();
    mountVisual(dialog, { title: '草稿差异概览', status: '比较不会覆盖草稿或提交', rows: [{ label: '本页工作稿', value: this.draftAlternateSummary(conflict.local || {}) }, { label: '所选保留稿', value: this.draftAlternateSummary(conflict.remote || {}) }], details: [{ label: '草稿键', value: conflict.key }] }, `draft-compare:${conflict.key}`);
    const title = el('h2', '', conflict.recovery ? '恢复保留的草稿' : '草稿内容存在差异'); title.id = 'draft-conflict-title'; dialog.append(title);
    dialog.append(el('p', 'notice', '这里比较本页工作稿与存储活动稿或保留稿。明确选择保存成功后，所选稿成为当前工作稿；独立恢复点不会更新。要更新恢复点，请返回后再次点击“创建 / 更新恢复点”。纯历史浏览且活动稿与本页内容均未变化时，“稍后处理”会结束浏览；发现差异或无法确认时仍保留待处理比较。'));
    const status = conflict.refreshing ? '正在刷新此项目状态。当前输入和比较内容已保留；读取完成前不能确认选择。'
      : conflict.scopeChanged ? `比较来源已变化，旧选择已停用，不能写入当前范围。${conflict.refreshError ? ` ${conflict.refreshError}` : ''}`
        : conflict.refreshError ? `状态刷新未完成。原草稿范围与比较内容仍保留，可以继续明确选择。${conflict.refreshError}` : null;
    const comparisonRemoteLabel = conflict.recovery ? '所选保留稿' : '存储活动稿';
    dialog.append(el('p', conflict.refreshing || conflict.scopeChanged ? 'muted danger-text' : 'muted', status || (conflict.remote
      ? `${comparisonRemoteLabel}与本页当前稿存在差异。两份内容均已保留；比较后选择要继续使用的版本，其他版本仍可从草稿状态栏查看或恢复。`
      : conflict.recovery ? '当前所选保留稿不可用。本页输入仍然保留；请从草稿状态栏重新选择完整版本。'
        : '存储中不再有原活动稿。本页输入仍然保留；比较后可明确选择是否继续使用本页当前稿。')));
    let searchInput = null;
    if (conflict.recovery && this.draftAlternates.length > 0) {
      const picker = el('section', 'draft-conflict-picker');
      picker.append(el('h3', '', '选择要比较的保留版本'));
      const selected = this.draftAlternates.find(item => conflict.remote && this.sameDraftContent(item.draft, conflict.remote)) ||
        (conflict.remote ? { label: conflict.remoteLabel || '当前比较版本', capturedAt: null, draft: conflict.remote } : null);
      const selectedSummary = el('div', 'draft-conflict-selected');
      selectedSummary.append(el('strong', '', selected
        ? `当前所选版本：${this.formatDraftAlternateTime(selected.capturedAt)} · ${selected.label || '已保留的草稿'}`
        : '当前没有选中的保留版本'));
      if (selected) selectedSummary.append(el('p', 'muted', this.draftAlternateSummary(selected.draft)));
      const toolbar = el('div', 'draft-conflict-filter-row');
      const label = el('label', 'draft-conflict-filter-label', '筛选完整版本内容');
      searchInput = el('input', 'draft-conflict-filter'); searchInput.type = 'search'; searchInput.value = conflict.alternateFilter || '';
      searchInput.dataset.draftAlternateSearch = 'true'; searchInput.setAttribute('aria-label', '筛选保留版本的完整字段、意见和结构内容');
      label.append(searchInput);
      const clear = el('button', 'button quiet', '清空筛选'); clear.type = 'button'; clear.dataset.draftConflictAction = 'clear-filter';
      const count = el('span', 'muted draft-conflict-filter-count'); count.setAttribute('aria-live', 'polite');
      toolbar.append(label, clear, count);
      const choices = el('div', 'draft-conflict-alternate-list'); choices.setAttribute('role', 'group'); choices.setAttribute('aria-label', '可比较的完整保留版本');
      const renderChoices = () => {
        const query = String(searchInput.value || '').trim().toLocaleLowerCase();
        const recentFirst = [...this.draftAlternates].reverse();
        const matches = recentFirst.filter(item => !query || JSON.stringify({ label: item.label || '', draft: item.draft }).toLocaleLowerCase().includes(query));
        count.textContent = `找到 ${matches.length} / ${recentFirst.length} 份保留版本`;
        choices.replaceChildren();
        if (!matches.length) { choices.append(el('p', 'muted draft-conflict-empty', '没有匹配的完整版本；清空筛选后可查看全部。')); return; }
        for (const alternate of matches) {
          const choice = el('button', 'button quiet draft-conflict-alternate'); choice.type = 'button';
          choice.__draftAlternate = alternate.draft;
          const selectedNow = !!conflict.remote && this.sameDraftContent(alternate.draft, conflict.remote);
          const titleText = `${this.formatDraftAlternateTime(alternate.capturedAt)} · ${alternate.label || '已保留的草稿'}`;
          choice.append(el('strong', '', titleText), el('small', 'muted draft-conflict-alternate-summary', this.draftAlternateSummary(alternate.draft)));
          choice.setAttribute('aria-pressed', String(selectedNow));
          choice.addEventListener('click', () => {
            conflict.remote = this.draftCopy(alternate.draft); conflict.remoteLabel = alternate.label || '已保留的草稿';
            conflict.selectedAlternate = this.draftCopy(alternate.draft);
            this.renderDraftConflictDialog();
          });
          choices.append(choice);
        }
      };
      searchInput.addEventListener('input', () => { conflict.alternateFilter = searchInput.value; renderChoices(); });
      clear.addEventListener('click', () => { searchInput.value = ''; conflict.alternateFilter = ''; renderChoices(); searchInput.focus?.({ preventScroll: true }); });
      renderChoices(); picker.append(selectedSummary, toolbar, choices); dialog.append(picker);
    }
    const compare = el('div', 'draft-conflict-compare');
    compare.append(this.renderDraftSemanticComparison(conflict.local, conflict.remote, comparisonRemoteLabel));
    const full = el('details', 'draft-conflict-full-json'); full.append(el('summary', '', '展开查看两份完整原稿 JSON'));
    const side = (label, value) => {
      const section = el('section', 'draft-conflict-side'); section.append(el('h3', '', label));
      const pre = el('pre', 'draft-conflict-value', JSON.stringify(value, null, 2));
      pre.style.whiteSpace = 'pre-wrap'; pre.style.overflowWrap = 'anywhere'; pre.style.maxHeight = '38vh'; pre.style.overflow = 'auto';
      section.append(pre); return section;
    };
    full.append(side('本页当前稿完整原稿', conflict.local), side(conflict.recovery ? (conflict.remoteLabel || '所选保留稿完整原稿') : conflict.remote ? '存储活动稿完整原稿' : '存储活动稿已删除或提交', conflict.remote));
    compare.append(full); dialog.append(compare);
    const actions = el('div', 'dialog-actions');
    const unavailable = !!conflict.refreshing || !!conflict.scopeChanged;
    const keep = el('button', 'button secondary', '保留本页当前稿'); keep.type = 'button'; keep.dataset.draftConflictAction = 'keep-local'; keep.disabled = unavailable; keep.addEventListener('click', () => { void this.resolveDraftConflict('local'); });
    const useOther = el('button', 'button primary', conflict.recovery ? '恢复这份保留稿' : '采用存储活动稿'); useOther.type = 'button'; useOther.dataset.draftConflictAction = 'use-remote'; useOther.disabled = unavailable || !conflict.remote; useOther.addEventListener('click', () => { void this.resolveDraftConflict('remote'); });
    const defer = el('button', 'button quiet', '稍后处理'); defer.type = 'button'; defer.dataset.draftConflictAction = 'defer'; defer.addEventListener('click', () => this.deferDraftConflict(conflict, dialog)); actions.append(keep, useOther, defer); dialog.append(actions);
    if (focusedAlternate) {
      [...dialog.querySelectorAll('.draft-conflict-alternate')].find(button => this.sameDraftContent(button.__draftAlternate, focusedAlternate))?.focus?.({ preventScroll: true });
    } else if (focusedSearch) {
      const replacementSearch = dialog.querySelector('[data-draft-alternate-search="true"]');
      replacementSearch?.focus?.({ preventScroll: true });
      if (searchCaret != null) replacementSearch?.setSelectionRange?.(searchCaret, searchCaret);
    }
  }
  openDraftConflict() {
    const existing = this.pendingDraftConflict;
    if (!existing) {
      const alternate = this.draftAlternates.at(-1); if (!alternate) return;
      this.pendingDraftConflict = { key: this.draftKey, local: this.currentDraftRecord(), remote: alternate.draft,
        remoteLabel: alternate.label || '保留版本', remoteRaw: this.draftStorageBaseline, activeRaw: this.draftStorageBaseline,
        comparisonActive: this.readDraftRawRecord(this.draftKey, this.draftStorageBaseline), recovery: true,
        alternateIndex: this.draftAlternates.length - 1, generation: this.workbenchGeneration, snapshot: this.snapshot,
        scope: this.draftConflictTarget(this.snapshot) };
      if (this.draftConflictRefresh?.generation === this.workbenchGeneration && this.sameDraftConflictTarget(this.pendingDraftConflict, this.draftConflictRefresh.snapshot)) {
        this.pendingDraftConflict.refreshing = true; this.pendingDraftConflict.refreshGeneration = this.workbenchGeneration;
      }
    } else existing.local = this.currentDraftRecord() || existing.local;
    this.renderDraftConflictDialog();
    const dialog = this.ensureDraftConflictDialog(); if (typeof dialog.showModal === 'function' && !dialog.open) dialog.showModal(); else dialog.open = true;
  }
  async handleDraftStorageEvent(event) {
    const key = this.draftKey;
    if (this.destroyed || !key || this.draftBaselineKey !== key || event?.key !== DRAFT_STORAGE_PREFIX + key) return;
    const generation = this.workbenchGeneration, snapshot = this.snapshot;
    const baselineRaw = this.draftStorageBaseline;
    let latestRaw = event.newValue;
    const currentRaw = this.drafts.raw?.(key);
    if (currentRaw !== undefined) latestRaw = currentRaw;
    if (latestRaw === baselineRaw) return;
    const operationId = this.beginDraftOperation();
    const ownsOperation = () => this.draftOperationMatches(operationId, key, generation, snapshot);
    let remote, prior;
    try {
      remote = this.readDraftRawRecord(key, latestRaw);
      prior = this.readDraftRawRecord(key, baselineRaw);
    }
    catch (error) {
      this.persistenceOK = false;
      this.rememberCorruptDraft(key, error, { kind: 'current', projectId: this.snapshot?.projectId || this.snapshot?.id, publicationRevision: this.snapshot?.publicationRevision });
      const message = `草稿活动版本或基线无法读取：${error.message}。本页输入仍保留，自动写入已暂停。`;
      this.showDraftState(message, true);
      const note = $('#persistence-note'); if (note) { note.textContent = `${message} 原始存档已保留。`; note.className = 'muted danger-text'; }
      return;
    }
    const local = this.currentDraftRecord(); if (!local) return;
    const conflict = this.pendingDraftConflict?.key === key && this.sameDraftConflictTarget(this.pendingDraftConflict, this.snapshot)
      ? this.pendingDraftConflict : null;
    const comparisonActive = conflict?.comparisonActive || prior;
    const comparisonRaw = conflict?.activeRaw ?? baselineRaw;
    const envelopeOnly = !!remote && !!comparisonActive && this.draftRecordMatchesScope(remote, key, this.snapshot) &&
      this.draftRecordMatchesScope(comparisonActive, key, this.snapshot) && this.sameDraftContent(remote, comparisonActive);
    if (envelopeOnly) {
      const selectedRecoveryBranch = conflict?.recovery ? this.draftCopy(conflict.remote) : null;
      const pendingVariants = conflict
        ? [conflict.local, conflict.prior, selectedRecoveryBranch].filter(Boolean)
        : [prior].filter(Boolean);
      const unsavedLocal = !conflict && prior && !this.sameDraftContent(local, prior);
      const active = conflict || !unsavedLocal ? remote : local;
      const result = await this.reconcileEnvelopeDrift({ baselineRaw: comparisonRaw, latestRaw, latest: remote,
        active, variants: pendingVariants, operationId });
      if (!ownsOperation()) return;
      if (result.status === 'saved') {
        const merged = result.latest, raw = result.latestRaw;
        if (conflict && this.pendingDraftConflict === conflict) {
          conflict.activeRaw = raw; conflict.remoteRaw = raw; conflict.comparisonActive = this.draftCopy(merged);
          conflict.local = this.currentDraftRecord() || conflict.local;
          if (!conflict.recovery) conflict.remote = this.draftCopy(merged);
          else if (selectedRecoveryBranch) {
            const selected = this.draftAlternates.find(item => this.sameDraftContent(item.draft, selectedRecoveryBranch));
            if (selected) { conflict.remote = this.draftCopy(selected.draft); conflict.remoteLabel = selected.label || conflict.remoteLabel; }
          }
          if (!conflict.recovery && conflict.local && conflict.remote && this.sameDraftContent(conflict.local, conflict.remote)) {
            this.pendingDraftConflict = null;
            const dialog = $('#draft-conflict-dialog'); if (dialog?.open) dialog.close?.();
          }
          this.renderDraftConflictDialog(); this.showDraftState();
        } else {
          this.showDraftState(unsavedLocal
            ? `存储活动稿只更新了保留分支；本页当前稿已合并并保存 · 草稿修订 ${this.draftRevision}。`
            : '存储活动稿只更新了保留分支；完整版本已合并，本页输入可以继续保存。');
        }
        return;
      }
      if (result.status === 'exhausted') {
        if (result.latest) {
          this.draftAlternates = this.mergeDraftAlternates(result.latest, [...pendingVariants, local].filter(Boolean));
          if (conflict && this.pendingDraftConflict === conflict) { conflict.activeRaw = result.latestRaw; conflict.remoteRaw = result.latestRaw; }
        }
        this.showDraftState('草稿保留分支连续更新；当前稿尚未完成持久保存，输入仍在本页，请再次保存或处理比较状态。', true);
        return;
      }
      if (result.status === 'error') {
        if (!ownsOperation()) return;
        if (result.error?.name !== 'DraftConflictError') this.persistenceOK = false;
        this.showDraftState(`草稿分支合并未完成：${result.error?.message || '状态已变化'}。当前稿仍在本页，请先比较或复制保存。`, true);
        return;
      }
      if (result.status === 'stale') return;
      remote = result.latest; latestRaw = result.latestRaw;
    }
    const differs = !remote || !this.sameDraftContent(local, remote);
    this.draftAlternates = this.draftAlternatesFrom(remote);
    if (!differs) {
      if (conflict?.key === key && !conflict.recovery && this.sameDraftConflictTarget(conflict, this.snapshot)) {
        const pendingVariants = [conflict.local, conflict.prior].filter(item => item && !this.sameDraftContent(remote, item));
        const alternatives = this.draftAlternatesFrom(remote);
        const missingVariant = pendingVariants.some(item => !alternatives.some(alternate => this.sameDraftContent(alternate.draft, item)));
        if (missingVariant) {
          try {
            remote = await this.saveConflictEnvelope(remote, pendingVariants, latestRaw, operationId);
            if (!ownsOperation() || this.pendingDraftConflict !== conflict) return;
            latestRaw = remote.draftStorageRaw;
          } catch (error) {
            if (!ownsOperation() || this.pendingDraftConflict !== conflict || error.name === 'DraftOperationStaleError') return;
            if (error.name === 'DraftConflictError') {
              await this.beginDraftConflict(local, error.latest, error.latestRaw, remote, operationId);
              return;
            }
            this.updateDraftBaseline(key, remote, latestRaw);
            this.showDraftState(`相同内容已同步，但先前的冲突分支尚未成功保留：${error.message}。当前输入和比较仍保留。`, true);
            return;
          }
        }
        this.pendingDraftConflict = null;
        const dialog = $('#draft-conflict-dialog'); if (dialog?.open) dialog.close?.();
      }
      if (!ownsOperation()) return;
      this.draftRevision = Math.max(this.draftRevision || 0, Number(remote?.draftRevision || 0));
      this.updateDraftBaseline(key, remote, latestRaw);
      this.showDraftState('存储活动稿与本页内容相同；本页继续使用此版本。'); return;
    }
    if (!ownsOperation()) return;
    await this.beginDraftConflict(local, remote, latestRaw, conflict?.comparisonActive || prior, operationId);
  }
  async resolveDraftConflict(choice) {
    const conflict = this.pendingDraftConflict, key = this.draftKey;
    if (!conflict || conflict.key !== key || conflict.refreshing || conflict.scopeChanged ||
        conflict.generation !== this.workbenchGeneration || conflict.snapshot !== this.snapshot ||
        !this.sameDraftConflictTarget(conflict, this.snapshot) || this.makeDraftKey(this.snapshot) !== key ||
        this.projectId !== (this.snapshot?.projectId || this.snapshot?.id)) return;
    const generation = this.workbenchGeneration, snapshot = this.snapshot;
    const operationId = this.beginDraftOperation();
    const contextMatches = () => this.pendingDraftConflict === conflict && this.draftOperationMatches(operationId, key, generation, snapshot) &&
      !conflict.scopeChanged && this.sameDraftConflictTarget(conflict, snapshot);
    const refreshForActiveChange = async (latest, latestRaw) => {
      if (!contextMatches()) return;
      const local = this.currentDraftRecord() || conflict.local;
      const prior = conflict.comparisonActive || conflict.remote;
      await this.beginDraftConflict(local, latest, latestRaw, prior, operationId);
      if (this.pendingDraftConflict && contextMatches()) {
        this.notify('比较期间存储活动稿再次变化；完整版本都已保留，请比较更新后的内容再选择。');
      }
    };
    const reconcileIfEnvelopeOnly = async (latest, latestRaw) => {
      const baselineRaw = conflict.activeRaw ?? this.draftStorageBaseline;
      const selectedRecoveryBranch = conflict.recovery ? this.draftCopy(conflict.remote) : null;
      const result = await this.reconcileEnvelopeDrift({ baselineRaw, latestRaw, latest, active: latest,
        variants: [conflict.local, conflict.prior, selectedRecoveryBranch].filter(Boolean), operationId });
      if (!contextMatches() || result.status === 'stale') return { status: 'stale' };
      if (result.status === 'saved') {
        conflict.activeRaw = result.latestRaw; conflict.remoteRaw = result.latestRaw;
        conflict.comparisonActive = this.draftCopy(result.latest);
        if (!conflict.recovery) conflict.remote = this.draftCopy(result.latest);
        else if (selectedRecoveryBranch) {
          const selected = this.draftAlternates.find(item => this.sameDraftContent(item.draft, selectedRecoveryBranch));
          if (selected) { conflict.remote = this.draftCopy(selected.draft); conflict.remoteLabel = selected.label || conflict.remoteLabel; }
        }
        conflict.local = this.currentDraftRecord() || conflict.local;
      }
      return result;
    };
    for (let attempt = 0; attempt < 3; attempt++) {
      if (!contextMatches()) return;
      let currentRaw = this.drafts.raw ? this.drafts.raw(key) : this.draftStorageBaseline;
      if (currentRaw !== conflict.activeRaw) {
        let latest;
        try { latest = this.readDraftRawRecord(key, currentRaw); }
        catch (error) {
          this.persistenceOK = false;
          this.rememberCorruptDraft(key, error, { kind: 'current', projectId: snapshot?.projectId || snapshot?.id, publicationRevision: snapshot?.publicationRevision });
          this.showDraftState(`草稿在比较期间变得无法读取：${error.message}。本页内容仍保留，不能确认选择。`, true);
          this.renderDraftConflictDialog(); return;
        }
        const comparedActive = conflict.comparisonActive;
        const envelopeOnly = !!latest && !!comparedActive && this.draftRecordMatchesScope(latest, key, snapshot) &&
          this.draftRecordMatchesScope(comparedActive, key, snapshot) && this.sameDraftContent(latest, comparedActive);
        if (envelopeOnly) {
          const result = await reconcileIfEnvelopeOnly(latest, currentRaw);
          if (!contextMatches() || result.status === 'stale') return;
          if (result.status === 'saved') { currentRaw = result.latestRaw; }
          else if (result.status === 'changed') {
            await refreshForActiveChange(result.latest, result.latestRaw); return;
          } else if (result.status === 'exhausted') {
            this.showDraftState('草稿保留分支连续更新；本次选择尚未保存，请在状态稳定后再次确认。', true);
            this.renderDraftConflictDialog(); return;
          } else if (result.status === 'error') {
            this.showDraftState(`合并保留分支失败：${result.error?.message || '草稿状态已变化'}。本次选择尚未保存。`, true);
            this.renderDraftConflictDialog(); return;
          }
        } else {
          await refreshForActiveChange(latest, currentRaw); return;
        }
      }

      const local = this.currentDraftRecord() || conflict.local;
      const remote = conflict.remote;
      const selected = choice === 'remote' && remote ? remote : local;
      const latestStored = this.readDraftRawRecord(key, currentRaw);
      const variants = [local, remote, conflict.prior, conflict.comparisonActive, latestStored]
        .filter(item => item && !this.sameDraftContent(selected, item));
      const alternatives = this.mergeDraftAlternates(selected, variants);
      const record = { ...this.draftCopy(selected), key, projectId: snapshot.projectId || snapshot.id,
        publicationRevision: snapshot.publicationRevision, sourceCommit: snapshot.sourceCommit || null,
        baseCommit: snapshot.baseCommit || null, draftRevision: Math.max(this.draftRevision || 0, Number(local?.draftRevision || 0), Number(remote?.draftRevision || 0), Number(latestStored?.draftRevision || 0)) + 1,
        updatedAt: new Date().toISOString(), draftConflictAlternates: alternatives };
      try {
        if (!contextMatches()) return false;
        const recordRaw = JSON.stringify(record);
        if (this.drafts.putIfUnchanged) this.drafts.putIfUnchanged(record, currentRaw);
        else await this.drafts.put(record);
        if (!contextMatches()) return;
        if (choice === 'remote' && remote) {
          const workbench = this.legacyWorkbench;
          if (workbench?.historyTimer != null) {
            globalThis.clearTimeout(workbench.historyTimer);
            workbench.historyTimer = null;
          }
          workbench?.pushHistory?.();
          this.applyVisibleDraft({ ...this.draftCopy(remote), draftConflictAlternates: alternatives });
          if (!contextMatches()) return false;
          if (this.objectsWorkflow() && workbench) workbench.syncUrl(true);
          workbench?.pushHistory?.();
        }
        this.draftRevision = record.draftRevision; this.draftAlternates = alternatives; this.updateDraftBaseline(key, record, recordRaw);
        this.pendingDraftConflict = null;
        const dialog = $('#draft-conflict-dialog'); if (dialog?.open) dialog.close?.();
        const selectedDescription = choice === 'remote' && remote
          ? (conflict.recovery ? '已恢复所选保留稿为当前工作稿' : '已采用存储活动稿为当前工作稿')
          : '已保留本页当前稿为当前工作稿';
        this.showDraftState(`${selectedDescription}并已保存 · 草稿修订 ${record.draftRevision}；另一份输入仍可恢复。独立恢复点未更新；如需保存恢复点，请再次点击“创建 / 更新恢复点”。`);
        return true;
      } catch (error) {
        if (!contextMatches() || error.name === 'DraftOperationStaleError') return false;
        if (error.name !== 'DraftConflictError') {
          this.showDraftState(`保存冲突处理结果失败：${error.message}。当前稿没有完成持久保存，两份原始输入仍保留。`, true);
          this.notify(`保存冲突处理结果失败：${error.message}。两份原始输入仍保留，请先不要关闭此页。`); return false;
        }
        if (!contextMatches()) return;
        const latest = error.latest, latestRaw = error.latestRaw;
        const comparedActive = conflict.comparisonActive;
        const envelopeOnly = !!latest && !!comparedActive && this.draftRecordMatchesScope(latest, key, snapshot) &&
          this.draftRecordMatchesScope(comparedActive, key, snapshot) && this.sameDraftContent(latest, comparedActive);
        if (!envelopeOnly) { await refreshForActiveChange(latest, latestRaw); return false; }
        const result = await reconcileIfEnvelopeOnly(latest, latestRaw);
        if (!contextMatches() || result.status === 'stale') return false;
        if (result.status !== 'saved') {
          this.showDraftState(result.status === 'error'
            ? `合并保留分支失败：${result.error?.message || '草稿状态已变化'}。本次选择尚未保存。`
            : '草稿保留分支连续更新；本次选择尚未保存，请在状态稳定后再次确认。', true);
          this.renderDraftConflictDialog(); return false;
        }
      }
    }
    if (contextMatches()) this.showDraftState('草稿持续被更新；本次选择尚未保存，请再次确认。', true);
    return false;
  }
  queueConceptDraftSave() {
    if (!this.projectId || !this.persistenceOK) return;
    if (!this.conceptDraftKey(this.projectId)) return;
    return this.saveConceptDraft(this.projectId);
  }
  async saveConceptDraft(projectId = this.projectId) {
    if (!projectId || !this.persistenceOK || this.projectId !== projectId) return false;
    const key = this.conceptDraftKey(projectId);
    if (!key) return;
    const generation = this.selectionGeneration;
    try {
      const record = { key, projectId, stage: 'initial', text: $('#concept').value, assets: cloneValue(this.assets), referenceIntents: cloneValue(this.referenceIntents || {}), conceptGenerationRequests: cloneValue(this.conceptGenerationRequests || []), interpretation: $('#concept-visual-interpretation')?.value || '', proposalInputs: cloneValue(this.proposalInputs || {}), updatedAt: new Date().toISOString() };
      this.conceptDraftBaselines ||= new Map();
      if (!this.conceptDraftBaselines.has(key)) this.conceptDraftBaselines.set(key, this.drafts.raw?.(key) ?? null);
      if (this.drafts.putIfUnchanged) {
        try { this.drafts.putIfUnchanged(record, this.conceptDraftBaselines.get(key)); }
        catch (error) {
          if (error.name !== 'DraftConflictError') throw error;
          this.showConceptDraftConflict(record, error.latestRaw); return false;
        }
        this.conceptDraftBaselines.set(key, JSON.stringify(record));
      } else await this.drafts.put(record);
      return true;
    } catch (error) {
      this.persistenceOK = false;
      if (this.projectId === projectId && this.selectionGeneration === generation) { $('#persistence-note').textContent = `概念草稿保存失败：${error.message}。当前文字仍留在页面中，请先复制保存。`; $('#persistence-note').className = 'muted danger-text'; }
      return false;
    }
  }
  showConceptDraftConflict(local, storedRaw) {
    const note = $('#persistence-note'); if (!note) return;
    note.className = 'muted danger-text';
    note.replaceChildren(document.createTextNode('另一页面已修改概念草稿。本页输入仍保留，未覆盖已保存稿；请先复制两份草稿，再刷新载入已保存稿。'));
    const inspect = el('button', 'button quiet', '查看 / 复制两份概念草稿'); inspect.type = 'button';
    inspect.addEventListener('click', () => {
      const dialog = $('#raw-draft-recovery-dialog'), content = $('#raw-draft-recovery-content');
      if (!dialog || !content) return;
      content.value = JSON.stringify({ purpose: '人工比较与恢复；不自动覆盖或提交', local, storedRaw }, null, 2);
      $('#raw-draft-recovery-status').textContent = '';
      if (this.legacyWorkbench.showWorkbenchDialog(dialog)) content.focus?.({ preventScroll: true });
    }); note.append(inspect);
  }
  restoreBaselineReferences(snapshot) {
    if (!snapshot || (snapshot.projectId || snapshot.id) !== this.projectId || !['MVP', 'REPAIR'].includes(snapshot.kind)) return;
    this.assets = cloneValue(snapshot.assets || []);
    this.referenceIntents = Object.fromEntries((snapshot.visualReferences || []).map((reference, index) => [reference.assetId || `text-${index}`, cloneValue(reference)]));
    this.renderAssets();
  }
  async restoreConceptDraft(projectId, generation) {
    if (!this.persistenceOK) return;
    const key = this.conceptDraftKey(projectId); if (!key) return;
    let draft, restoredRaw = null;
    try {
      draft = await this.drafts.get(key);
      if (this.drafts.raw && this.drafts.readStored) {
        restoredRaw = this.drafts.raw(key);
        draft = restoredRaw == null ? null : this.drafts.readStored(key, restoredRaw);
      }
    }
    catch (error) {
      this.persistenceOK = false;
      if (this.projectId === projectId && this.selectionGeneration === generation) { $('#persistence-note').textContent = `读取概念草稿失败：${error.message}。`; $('#persistence-note').className = 'muted danger-text'; }
      return;
    }
    if (this.projectId !== projectId || this.selectionGeneration !== generation) return;
    this.conceptDraftBaselines ||= new Map(); this.conceptDraftBaselines.set(key, restoredRaw);
    if (!draft) { this.restoreBaselineReferences(this.snapshot); this.renderAssets(); this.loadConceptReferences(); return; }
    $('#concept').value = draft.text || ''; this.referenceIntents = cloneValue(draft.referenceIntents || {}); this.conceptGenerationRequests = cloneValue(draft.conceptGenerationRequests || []); this.assets = Array.isArray(draft.assets) ? draft.assets.filter(asset => typeof asset.id === 'string') : []; this.proposalInputs = draft.proposalInputs && typeof draft.proposalInputs === 'object' && !Array.isArray(draft.proposalInputs) ? cloneValue(draft.proposalInputs) : {}; this.renderAssets(); const interpretation = $('#concept-visual-interpretation'); if (interpretation) interpretation.value = draft.interpretation || ''; this.renderConceptReferenceResults(); this.loadConceptReferences();
  }
  async deleteConceptDraft(projectId) {
    const key = this.conceptDraftKey(projectId); if (!key) return;
    try {
      const latest = this.drafts.raw?.(key) ?? null;
      if (this.conceptDraftBaselines?.has(key) && latest !== this.conceptDraftBaselines.get(key)) {
        if (this.projectId === projectId) this.showConceptDraftConflict({ key, projectId, text: $('#concept').value, assets: cloneValue(this.assets), referenceIntents: cloneValue(this.referenceIntents) }, latest);
        return false;
      }
      const deletion = this.drafts.delete(key);
      this.conceptDraftBaselines?.set(key, 'null'); await deletion; return true;
    } catch { return false; }
  }
  async restoreDraft(expectedGeneration = this.workbenchGeneration) {
    if (!this.persistenceOK || !this.snapshot) return;
    const targetSnapshot = this.snapshot;
    const key = this.makeDraftKey(targetSnapshot);
    if (!key) { this.draftKey = null; this.showDraftState('服务未提供存储实例标识，草稿不会从其他工作区恢复或写入。'); return; }
    if (this.draftBaselineKey !== key) { this.resetDraftConflictContext(); this.draftBaselineKey = key; this.draftStorageBaseline = this.drafts.raw ? this.drafts.raw(key) : null; }
    const operationId = this.beginDraftOperation();
    const ownsOperation = () => this.draftOperationMatches(operationId, key, expectedGeneration, targetSnapshot);
    const restoreContext = this.matchesDraftRestore(this.draftRestoreContext, key, expectedGeneration, targetSnapshot)
      ? this.draftRestoreContext : this.beginDraftRestore(expectedGeneration, targetSnapshot);
    let appliedStoredDraft = false;
    const projectId = targetSnapshot.projectId || targetSnapshot.id;
    const checkpointKeys = [`${key}:saved`, `${key}:saved:backup`];
    if (this.drafts?.raw && this.drafts?.readStored) {
      for (const [index, checkpointKey] of checkpointKeys.entries()) {
        let raw = null;
        try { raw = this.drafts.raw(checkpointKey); } catch {}
        if (raw == null || raw === 'null') continue;
        try {
          const checkpoint = this.drafts.readStored(checkpointKey, raw);
          const validationError = this.legacyWorkbench.savedCheckpointRecordError?.(checkpoint, {
            key: checkpointKey, draftKey: key, projectId, publicationRevision: targetSnapshot.publicationRevision, backup: index === 1,
          });
          if (validationError) throw validationError;
        }
        catch (error) {
          if (expectedGeneration === this.workbenchGeneration && this.snapshot === targetSnapshot) {
            this.rememberCorruptDraft(checkpointKey, error, { kind: checkpointKey.endsWith(':backup') ? 'saved-checkpoint-backup' : 'saved-checkpoint', projectId, publicationRevision: targetSnapshot.publicationRevision, baseDraftKey: key });
          }
        }
      }
    }
    try {
      const loadedDraft = await this.drafts.get(key);
      if (!ownsOperation()) return;
      if (this.pendingDraftConflict?.key === key) return;
      this.draftKey = key;
      const restoredRaw = this.drafts.raw ? this.drafts.raw(key) : (loadedDraft ? JSON.stringify(loadedDraft) : null);
      const draft = this.drafts.raw ? this.readDraftRawRecord(key, restoredRaw) : loadedDraft;
      this.updateDraftBaseline(key, draft, restoredRaw);
      if (draft) {
        const routeTarget = this.legacyWorkbench.routeSelectionOverride;
        this.applyVisibleDraft(routeTarget === undefined ? draft : { ...draft, selectedObjectId: routeTarget });
        this.draftRevision = draft.draftRevision || 0;
        appliedStoredDraft = true;
      } else if (targetSnapshot.kind !== 'REPAIR' && this.drafts.findOlderIterationDraft) {
        const priorDrafts = await this.drafts.findOlderIterationDraft({ storeId: this.storageId(),
          projectId: targetSnapshot.projectId || targetSnapshot.id, publicationRevision: targetSnapshot.publicationRevision, currentKey: key });
        if (!ownsOperation()) return;
        const prior = priorDrafts.find(item => this.hasUnsubmittedDraft(item.draft));
        if (prior && this.hasUnsubmittedDraft(prior.draft)) {
          const oldSnapshot = { id: targetSnapshot.projectId || targetSnapshot.id, projectId: targetSnapshot.projectId || targetSnapshot.id,
            publicationRevision: prior.draft.publicationRevision, sourceCommit: prior.draft.sourceCommit || null,
            baseCommit: prior.draft.baseCommit || null, kind: 'MVP' };
          this.handleRebase(oldSnapshot, targetSnapshot, prior.draft);
          this.unrebasedDraft = { ...this.unrebasedDraft, key: prior.key, draft: prior.draft };
          const otherDraftCount = priorDrafts.filter(item => item.key !== prior.key && this.hasUnsubmittedDraft(item.draft)).length;
          if (otherDraftCount) {
            this.pendingRebase.otherDraftCount = otherDraftCount;
            this.renderRebasePreview(this.pendingRebase);
          }
        }
      }
      const corrupt = this.corruptDraftsForCurrentScope();
      this.showDraftState(corrupt.length ? `发现 ${corrupt.length} 份无法解析的草稿原文；原始存档已保留，可下载后人工恢复。` : null, !!corrupt.length);
      this.legacyWorkbench.routeSelectionOverride = undefined;
      if (appliedStoredDraft && this.draftRestoreContext === restoreContext &&
          this.matchesDraftRestore(restoreContext, key, expectedGeneration, targetSnapshot) &&
          expectedGeneration === this.workbenchGeneration && this.snapshot === targetSnapshot &&
          this.projectId === (targetSnapshot.projectId || targetSnapshot.id)) {
        this.legacyWorkbench.resetHistory?.();
      }
    }
    catch (error) {
      if (!ownsOperation()) return;
      this.persistenceOK = false;
      if (this.draftContextMatches(key, expectedGeneration, targetSnapshot)) {
        this.rememberCorruptDraft(key, error, { kind: 'current', projectId, publicationRevision: targetSnapshot.publicationRevision });
        $('#persistence-note').textContent = `读取草稿失败：${error.message}。原始存档已保留。`; $('#persistence-note').className = 'muted danger-text';
        this.showDraftState(`读取草稿失败：${error.message}。当前页面内容已保留。`, true);
      }
    } finally {
      if (expectedGeneration === this.workbenchGeneration && this.snapshot === targetSnapshot) this.legacyWorkbench.finishInitialRouteHydration?.();
      this.finishDraftRestore(restoreContext);
    }
  }
  beginDraftRestore(generation, snapshot) {
    const context = { key: this.makeDraftKey(snapshot), generation, snapshot };
    this.draftRestoreContext = context;
    this.draftSaveQueuedDuringRestore = false;
    return context;
  }
  hasUnsubmittedDraft(draft) {
    if (!draft || typeof draft !== 'object') return false;
    if (String(draft.text || '').trim() || String(draft.feedbackMessage || '').trim()) return true;
    if (Object.keys(draft.values || {}).length || Object.keys(draft.fields || {}).length) return true;
    if ((draft.feedback || []).some(item => String(item?.message || '').trim())) return true;
    if (Object.values(draft.feedbackInputs || {}).some(item => String(item?.message || '').trim())) return true;
    if (String(draft.legacyUnboundFeedback?.message || '').trim()) return true;
    if (Object.values(draft.targetNotes || {}).some(note => String(note?.text || '').trim())) return true;
    if ((draft.structuralProposals || []).some(item => item && typeof item === 'object')) return true;
    return Object.values(draft.proposalInputs || {}).some(revisions => revisions && typeof revisions === 'object' &&
      Object.values(revisions).some(record => record && typeof record === 'object' && (
        Object.values(record.questions || {}).some(value => String(value ?? '').trim()) || String(record.readySupplement || '').trim() || Array.isArray(record.visualReferences)
      )));
  }
  matchesDraftRestore(context, key, generation, snapshot) {
    return !!context && context.key === key && context.generation === generation && context.snapshot === snapshot;
  }
  finishDraftRestore(context) {
    if (!context || this.draftRestoreContext !== context) return;
    this.draftRestoreContext = null;
    if (this.draftSaveQueuedDuringRestore) {
      this.draftSaveQueuedDuringRestore = false;
      if (!this.pendingRebase) this.saveDraft();
    }
  }
  queueDraftSave() {
    if (this.serializingVisibleDraft) return;
    return this.saveDraft();
  }
  async saveDraft() {
    const pendingRestore = this.draftRestoreContext;
    if (this.matchesDraftRestore(pendingRestore, pendingRestore?.key, this.workbenchGeneration, this.snapshot)) {
      this.beginDraftOperation();
      this.draftSaveQueuedDuringRestore = true;
      return;
    }
    this.draftTimer = null; if (!this.draftKey) return;
    if (!this.persistenceOK) { this.showDraftState('本地存储不可用，当前修改只在页面内暂存。请先复制保存文字。', true); return; }
    const key = this.draftKey, targetSnapshot = this.snapshot, generation = this.workbenchGeneration;
    const operationId = this.beginDraftOperation();
    const ownsOperation = () => this.draftOperationMatches(operationId, key, generation, targetSnapshot);
    if (this.pendingDraftConflict?.key === key) { await this.retainPendingDraftInput(operationId); return false; }
    if (this.draftBaselineKey !== key) {
      this.resetDraftConflictContext(); this.draftBaselineKey = key;
      this.draftStorageBaseline = this.drafts.raw ? this.drafts.raw(key) : null;
    }
    const expectedRaw = this.draftStorageBaseline;
    let record = null;
    try {
      const visible = this.readVisibleDraft();
      record = { ...visible, key, projectId: targetSnapshot.projectId || targetSnapshot.id,
        publicationRevision: targetSnapshot.publicationRevision, sourceCommit: targetSnapshot.sourceCommit || null,
        baseCommit: targetSnapshot.baseCommit || null, draftRevision: ++this.draftRevision, updatedAt: new Date().toISOString() };
      const recordRaw = JSON.stringify(record);
      if (this.drafts.putIfUnchanged) {
        this.drafts.putIfUnchanged(record, expectedRaw);
        // localStorage's compare and write are synchronous. Advance this tab's
        // baseline as this operation's own serialization. A later independent
        // write must remain a CAS conflict for the next save.
        if (!ownsOperation()) return false;
        this.updateDraftBaseline(key, record, recordRaw);
      } else {
        await this.drafts.put(record);
        if (!ownsOperation()) return false;
        this.updateDraftBaseline(key, record, recordRaw);
      }
      if (ownsOperation() && this.draftRevision === record.draftRevision) this.showDraftState(`已保存在此浏览器 · 草稿修订 ${record.draftRevision}`);
      return ownsOperation();
    } catch (error) {
      if (!ownsOperation() || error.name === 'DraftOperationStaleError') return false;
      if (error.name === 'DraftConflictError') {
        let prior = null;
        try { prior = this.readDraftRawRecord(key, expectedRaw); }
        catch (baselineError) {
          this.persistenceOK = false;
          this.rememberCorruptDraft(key, baselineError, { kind: 'current', projectId: targetSnapshot?.projectId || targetSnapshot?.id, publicationRevision: targetSnapshot?.publicationRevision });
          this.showDraftState(`原草稿基线无法读取：${baselineError.message}。当前输入仍在本页，自动写入已暂停。`, true);
          return false;
        }
        const result = await this.reconcileEnvelopeDrift({ baselineRaw: expectedRaw, latestRaw: error.latestRaw,
          latest: error.latest, active: record || this.currentDraftRecord(), variants: [prior].filter(Boolean), operationId });
        if (!ownsOperation()) return false;
        if (result.status === 'saved') {
          this.showDraftState(`存储活动稿只更新了保留分支；本页当前稿已合并并保存 · 草稿修订 ${this.draftRevision}。`);
          return true;
        }
        if (result.status === 'changed') {
          await this.beginDraftConflict(record || this.currentDraftRecord(), result.latest, result.latestRaw, prior, operationId);
          return false;
        }
        if (result.status === 'exhausted') {
          if (result.latest) {
            this.draftAlternates = this.mergeDraftAlternates(result.latest, [record, prior].filter(Boolean));
          }
          this.showDraftState('草稿保留分支连续更新；本页当前稿尚未完成持久保存，输入仍在本页，请再次保存或比较。', true);
          return false;
        }
        if (result.status === 'error') {
          if (result.error?.name !== 'DraftConflictError') {
            this.persistenceOK = false;
            $('#persistence-note').textContent = '草稿存储写入失败。'; $('#persistence-note').className = 'muted danger-text';
          }
          this.showDraftState(`草稿合并失败：${result.error?.message || '上下文已变化'}。当前输入仍在本页，请先复制保存。`, true);
          return false;
        }
        return false;
      }
      this.persistenceOK = false;
      if (ownsOperation()) { this.showDraftState(`草稿保存失败：${error.message}。请先复制保存文字。`, true); $('#persistence-note').textContent = '草稿存储写入失败。'; $('#persistence-note').className = 'muted danger-text'; }
    }
  }
  beginDraftOperation() { return ++this.draftOperationSequence; }
  draftOperationMatches(operationId, key, generation, snapshot) {
    return operationId === this.draftOperationSequence && this.draftContextMatches(key, generation, snapshot);
  }
  draftContextMatches(key, generation, snapshot) { return generation === this.workbenchGeneration && this.draftKey === key && this.snapshot === snapshot && this.makeDraftKey(snapshot) === key && this.projectId === (snapshot.projectId || snapshot.id); }
  showDraftState(text = null, error = false) {
    const node = $('#draft-state'); if (!node) return;
    const pendingConflict = this.pendingDraftConflict;
    const conflict = pendingConflict?.key === this.draftKey;
    const corrupt = this.corruptDraftsForCurrentScope();
    const conflictMessage = pendingConflict?.refreshing ? '正在刷新草稿范围。当前输入和比较内容已保留，读取完成前不能确认选择。'
      : pendingConflict?.scopeChanged ? `比较来源已变化，旧选择已停用，不能写入当前范围。${pendingConflict.refreshError ? ` ${pendingConflict.refreshError}` : ''}`
        : pendingConflict?.refreshError ? `状态刷新未完成。原草稿范围与比较内容仍保留，可以继续明确选择。${pendingConflict.refreshError}`
          : pendingConflict?.recovery === true
            ? '保留稿比较尚未结束；本页输入仍在。请继续比较并明确选择后再保存。'
            : '存储中的活动草稿与本页基线不同。当前输入仍在本页，两份内容已保留；请比较后选择。';
    const message = conflict ? conflictMessage
      : text || (corrupt.length ? `发现 ${corrupt.length} 份损坏的本地存档；原文已保留，可下载后人工恢复。`
        : (this.draftKey ? '草稿按项目、发布版本与返修候选分别保存。' : '等待项目版本及存储实例身份。'));
    node.replaceChildren(el('span', error || conflict ? 'danger-text' : '', message));
    if (conflict) {
      const review = el('button', 'button secondary', '比较并选择'); review.type = 'button'; review.addEventListener('click', () => this.openDraftConflict()); node.append(review);
    } else if (this.draftBaselineKey === this.draftKey && this.draftAlternates.length) {
      const restore = el('button', 'button secondary', `查看/恢复另一份草稿 (${this.draftAlternates.length})`); restore.type = 'button'; restore.addEventListener('click', () => this.openDraftConflict()); node.append(restore);
    }
    if (corrupt.length) {
      const download = el('button', 'button secondary', `下载原始存档 (${corrupt.length})`); download.type = 'button'; download.dataset.action = 'download-corrupt-drafts';
      download.addEventListener('click', () => this.downloadCorruptDraftArchive()); node.append(download);
      const view = el('button', 'button secondary', '查看/复制原始存档'); view.type = 'button'; view.dataset.action = 'view-corrupt-drafts';
      view.addEventListener('click', () => this.showCorruptDraftArchive()); node.append(view);
    }
    node.className = `draft-state${error || conflict ? ' danger-text' : ''}`;
  }
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
    if (pending.notice) this.notifyRebase(pending.notice);
    mountVisual(content, { title: '重关联前后', status: '旧稿保留，等待明确选择', rows: [{ label: '旧基线', value: oldSnapshot.publicationRevision }, { label: '新基线', value: nextSnapshot.publicationRevision }, { label: '原文', value: pending.draft.text || '按目标分别保留' }], details: [{ label: '旧 Git', value: oldSnapshot.sourceCommit }, { label: '新 Git', value: nextSnapshot.sourceCommit }] }, `rebase:${this.projectId}`);
    if (pending.otherDraftCount) content.append(el('p', 'muted danger-text', `另有 ${pending.otherDraftCount} 份不同旧版本的未提交草稿仍保留在本地，本次只预览最新一份。`));
    if (!pending.persistenceOK) content.append(el('p', 'muted danger-text', '本地存储不可用；确认后仅在当前页面内重关联，刷新或关闭页面后不会保留。'));
    const sourceIdentity = snapshot => {
      const details = [snapshot.sourceCommit ? `源 Git ${snapshot.sourceCommit}` : '', snapshot.baseCommit ? `基线 Git ${snapshot.baseCommit}` : ''].filter(Boolean);
      return details.join(' · ') || '旧草稿未记录 Git 来源';
    };
    const changes = el('ul', 'requirement-list'); changes.append(el('li', '', `旧草稿来源：${sourceIdentity(oldSnapshot)}`), el('li', '', `当前版本来源：${sourceIdentity(nextSnapshot)}`)); content.append(changes);
    const preview = el('div', 'rebase-preview'); preview.append(el('h3', '', '草稿预览'));
    const targetNotes = pending.draft.targetNotes && typeof pending.draft.targetNotes === 'object' ? pending.draft.targetNotes : {};
    if (pending.draft.text && !Object.keys(targetNotes).length) preview.append(el('p', '', `保留自然语言调整：${pending.draft.text}`));
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
    for (const feedback of pending.draft.feedback || []) fieldPreview.append(el('li', '', `${feedback.objectId} · ${this.legacyWorkbench.feedbackCategoryLabel(feedback.category)} 反馈：${feedback.message}`));
    const nextObjects = this.objectItems(nextSnapshot), sceneIds = new Set(this.legacyWorkbench.scenes().map(scene => scene.id));
    for (const [objectId, item] of Object.entries(pending.draft.feedbackInputs || {})) {
      if (!String(item?.message || '').trim()) continue;
      const object = nextObjects.find(candidate => candidate.id === objectId);
      fieldPreview.append(el('li', '', `待添加反馈 · ${object?.name || objectId}（${objectId}） · ${this.legacyWorkbench.feedbackCategoryLabel(item.category)}：${item.message}；此反馈仍未加入本轮`));
    }
    const unbound = pending.draft.legacyUnboundFeedback;
    if (String(unbound?.message || '').trim()) fieldPreview.append(el('li', 'danger-text', `旧版待关联反馈 · 目标不明 · ${this.legacyWorkbench.feedbackCategoryLabel(unbound.category)}：${unbound.message}；需要明确关联或移除`));
    for (const [proposalId, revisions] of Object.entries(pending.draft.proposalInputs || {})) {
      if (!revisions || typeof revisions !== 'object' || Array.isArray(revisions)) continue;
      for (const [revision, record] of Object.entries(revisions)) {
        if (!record || typeof record !== 'object' || Array.isArray(record)) continue;
        for (const [questionId, answer] of Object.entries(record.questions || {})) {
          if (!String(answer ?? '').trim()) continue;
          const prompt = record.questionPrompts?.[questionId] || questionId;
          fieldPreview.append(el('li', '', `方案输入 · ${proposalId} r${revision} · ${prompt}：${this.storedQuestionLabel(record, questionId, answer)}；此修订文字仅供核对`));
        }
        if (String(record.readySupplement || '').trim()) fieldPreview.append(el('li', '', `方案输入 · ${proposalId} r${revision} · READY 补充：${record.readySupplement}；此修订文字仅供核对`));
        if (Array.isArray(record.visualReferences)) {
          const references = record.visualReferences;
          if (!references.length) fieldPreview.append(el('li', '', `方案输入 · ${proposalId} r${revision} · 视觉参考修订：明确移除全部参考；此修订仅供核对`));
          for (const reference of references) fieldPreview.append(el('li', '', `方案输入 · ${proposalId} r${revision} · 视觉参考修订：${reference.intent || '用途未填写'}；保持：${reference.preserve || '未声明'}；未知：${reference.unknown || '未声明'}；关联目标：${reference.targetObjectIds?.join('、') || '本轮项目视觉方向'}；图片：${reference.assetId || '未选用'}；此修订仅供核对`));
        }
      }
    }
    for (const [key, note] of Object.entries(targetNotes)) {
      const objectId = this.legacyWorkbench.noteTargetId(key, note);
      const object = objectId ? nextObjects.find(item => item.id === objectId) : null;
      const targetLabel = objectId ? `${object?.name || objectId}（ID ${objectId}）` : '当前项目';
      const targetStatus = objectId && !object ? '；新版本未映射此对象，意见仍保留并需核对目标' : '';
      fieldPreview.append(el('li', '', `目标意见 · ${targetLabel} · ${note?.feedbackId || '无稳定意见编号'}：${note?.text || ''}${targetStatus}`));
    }
    const operations = Array.isArray(pending.draft.structuralProposals) ? pending.draft.structuralProposals : [];
    for (const operation of operations) {
      const references = [operation.objectId, operation.definitionId, operation.sceneId, operation.entryId, operation.presetId].filter(value => typeof value === 'string' && value);
      const unresolved = references.filter(value => !nextObjects.some(object => object.id === value) && !sceneIds.has(value));
      fieldPreview.append(el('li', '', `结构提案 · ${this.legacyWorkbench.operationLabel(operation)}${unresolved.length ? `；新版本未映射引用 ${unresolved.join('、')}，需要人工核对` : ''}`));
    }
    if (fieldPreview.childNodes.length) preview.append(fieldPreview);
    if (!pending.draft.text && !fieldPreview.childNodes.length) preview.append(el('p', 'muted', '当前没有待重关联的修改内容。'));
    if (operations.length) preview.append(el('p', 'muted', '结构提案仍是用户意图，不会随基线迁移而自动执行。'));
    preview.append(el('p', 'muted', '此操作只复制草稿并标记待核对，不会发布或覆盖项目。')); content.append(preview);
  }
  rebaseContextMatches(pending) { return this.pendingRebase === pending && pending.generation === this.workbenchGeneration && this.snapshot === pending.nextSnapshot && this.makeDraftKey(this.snapshot) === pending.newKey && this.projectId === (pending.nextSnapshot.projectId || pending.nextSnapshot.id); }
  sameRebaseTarget(pending, snapshot) {
    const prior = pending?.nextSnapshot;
    if (!prior || !snapshot || pending.newKey !== this.makeDraftKey(snapshot)) return false;
    const projectId = snapshot.projectId || snapshot.id;
    return projectId === (prior.projectId || prior.id) &&
      Number(snapshot.publicationRevision) === Number(prior.publicationRevision) &&
      (snapshot.kind || null) === (prior.kind || null) &&
      (snapshot.candidateId || null) === (prior.candidateId || null) &&
      (snapshot.sourceCommit || null) === (prior.sourceCommit || null) &&
      (snapshot.baseCommit || null) === (prior.baseCommit || null) &&
      (!prior.id || !snapshot.id || snapshot.id === prior.id);
  }
  sameReviewedDraft(preview, stored) {
    return !!stored && this.sameDraftContent({ ...preview, stage: preview.stage || 'iteration' }, { ...stored, stage: stored.stage || 'iteration' });
  }
  notifyRebase(message) {
    if (!this.pendingRebase || !$('#rebase-dialog')?.open) return this.notify(message);
    this.pendingRebase.notice = message;
    const content = $('#rebase-content');
    content.querySelector('[data-rebase-notice]')?.remove();
    const notice = el('p', 'notice', message); notice.dataset.rebaseNotice = 'true'; notice.setAttribute('role', 'alert');
    content.prepend(notice);
  }
  async confirmRebase() {
    const pending = this.pendingRebase; if (!pending) return;
    try {
      if (!this.rebaseContextMatches(pending)) return;
      if (pending.persistenceOK) {
        const stored = await this.drafts.get(pending.oldKey);
        if (!this.rebaseContextMatches(pending)) return;
        if (!stored) { this.notifyRebase('未找到旧草稿；没有修改当前版本。'); return; }
        if (!this.sameReviewedDraft(pending.draft, stored)) { pending.draft = { ...stored, values: { ...(stored.values || {}) }, fields: { ...(stored.fields || {}) }, feedback: [...(stored.feedback || [])] }; this.unrebasedDraft = { ...this.unrebasedDraft, draft: pending.draft }; this.renderRebasePreview(pending); this.notifyRebase('旧草稿在预览后发生变化；已更新预览，请重新确认。'); return; }
      }
      const old = pending.draft;
      const migrated = { ...old, key: pending.newKey, previousKey: pending.oldKey, projectId: pending.nextSnapshot.projectId || pending.nextSnapshot.id,
        publicationRevision: pending.nextSnapshot.publicationRevision,
        rebasedFrom: { publicationRevision: old.publicationRevision ?? pending.oldSnapshot.publicationRevision,
          sourceCommit: old.sourceCommit || pending.oldSnapshot.sourceCommit || null, baseCommit: old.baseCommit || pending.oldSnapshot.baseCommit || null },
        sourceCommit: pending.nextSnapshot.sourceCommit || null, baseCommit: pending.nextSnapshot.baseCommit || null,
        draftRevision: (old.draftRevision || 0) + 1, rebaseNeedsReview: true, updatedAt: new Date().toISOString() };
      if (pending.persistenceOK) {
        if (this.drafts.putIfAbsent) await this.drafts.putIfAbsent(migrated);
        else {
          const existing = await this.drafts.get(pending.newKey);
          if (existing || this.drafts.isTombstoned?.(pending.newKey)) throw new Error('新版本已有草稿或提交记录，未覆盖。');
          await this.drafts.put(migrated);
        }
        if (!this.rebaseContextMatches(pending)) return;
      }
      if (!this.rebaseContextMatches(pending)) return;
      this.draftKey = pending.newKey; this.applyVisibleDraft(migrated); this.draftRevision = migrated.draftRevision; this.pendingRebase = null; this.unrebasedDraft = null;
      $('#rebase-dialog').close?.(); this.showDraftState(pending.persistenceOK ? '草稿已复制到新基线并标记为待核对；原草稿仍保留。' : '草稿已在当前页面内重关联；本次修改不会持久保存。', true);
    } catch (error) { if (this.rebaseContextMatches(pending)) this.notifyRebase(`草稿迁移失败：${error.message}。旧草稿仍保留。`); }
  }
  async submitIteration(options = {}) {
    const blocked = reason => { const outcome = this.submissionOutcome('blocked', { type: 'iteration.submit', projectId: this.projectId, reason }); this.lastSubmissionOutcome = outcome; this.notify(reason); return outcome; };
    if (this.pendingRebase) return blocked('请先确认或取消草稿重关联，再提交迭代。');
    if (!this.readiness?.ready) return blocked('新工作流尚未通过启动检查，调整不会提交。');
    if (this.selectionBusy) return blocked('正在读取所选项目版本，请稍后再提交。');
    const selectedProject = this.projectId;
    if (!selectedProject || !this.snapshotMatchesProject(selectedProject)) return blocked('所选项目的版本尚未读取成功；当前调整没有提交。');
    const projectViewJob = this.projectView?.projectId === selectedProject ? this.projectView.job : null;
    const activeJob = [
      projectViewJob && (!projectViewJob.projectId || projectViewJob.projectId === selectedProject) ? projectViewJob : null,
      this.job?.projectId === selectedProject ? this.job : null,
      ...(this.workspace?.jobs || []).filter(job => job.projectId === selectedProject),
    ].find(job => job && ACTIVE.has(job.status));
    if (activeJob) {
      const candidateId = activeJob.candidateId || activeJob.candidate?.id || activeJob.response?.candidate?.id || null;
      const jobLabel = activeJob.id ? `（${activeJob.id}）` : '';
      const reason = `项目已有活动制作任务${jobLabel}；请先通过当前制作记录入口审阅候选或处理该任务，再提交迭代。`;
      const outcome = {
        ...this.submissionOutcome('blocked', { type: 'iteration.submit', projectId: selectedProject, reason }),
        ...(activeJob.id ? { jobId: activeJob.id } : {}),
        ...(candidateId ? { candidateId } : {}),
      };
      this.lastSubmissionOutcome = outcome; this.notify(reason); return outcome;
    }
    if (this.proposal?.projectId === selectedProject && ['PLANNING', 'PLANNING_UNCERTAIN', 'NEEDS_CLARIFICATION', 'READY'].includes(this.proposal.status)) return blocked('当前提案仍在策划或等待确认；请先完成、取消或对账本轮提案。');
    const frozenReport = options.reviewedReport ? cloneValue(options.reviewedReport) : null;
    if (frozenReport) {
      const currentSource = this.snapshot.sourceCommit || this.snapshot.baseCommit || null;
      if (!options.skipReport || frozenReport.projectId !== selectedProject || Number(frozenReport.publicationRevision) !== Number(this.snapshot.publicationRevision) || (frozenReport.sourceCommit || null) !== currentSource || !frozenReport.intent || typeof frozenReport.intent.text !== 'string' || !frozenReport.intent.changeRequest || typeof frozenReport.intent.changeRequest !== 'object') return blocked('已审阅申报与当前项目、版本、源 Git 或请求内容不匹配；没有提交，请重新打开并审阅申报。');
      const request = frozenReport.intent.changeRequest;
      if (Number(request.baseRevision) !== Number(this.snapshot.publicationRevision) || (request.sourceCommit || null) !== currentSource) return blocked('冻结申报中的修改请求没有绑定当前发布版本与源 Git；没有提交。');
    }
    if (this.objectsWorkflow() && !frozenReport) this.legacyWorkbench.persistCurrentNote();
    const text = frozenReport ? String(frozenReport.intent.text || '') : this.objectsWorkflow() ? this.legacyWorkbench.effectiveText() : $('#edit-text').value.trim(); const values = {};
    if (this.objectsWorkflow()) {
      const changeRequest = frozenReport ? cloneValue(frozenReport.intent.changeRequest) : this.buildChangeRequest();
      const pendingFeedback = Object.entries(this.feedbackInputs || {}).find(([, item]) => String(item?.message || '').trim());
      if (this.legacyUnboundFeedback?.message) return blocked('有一条旧版草稿反馈的目标不明；请先选择对象，将它明确关联并添加，或显式移除。');
      if (pendingFeedback && !frozenReport) return blocked(`对象“${pendingFeedback[0]}”的反馈尚未加入本轮；请先定位该对象并点击“添加到所选对象”。`);
      const unaddedFeedback = $('#feedback-message').value.trim();
      if (unaddedFeedback && !frozenReport) return blocked(this.selectedObjectId ? `对象“${this.selectedObjectId}”的反馈尚未加入本轮；请先点击“添加到所选对象”。` : '有未加入本轮的反馈；请先选择对象并点击“添加到所选对象”。');
      if (!text && !changeRequest.fields.length && !changeRequest.feedback.length && !changeRequest.operations.length && !(frozenReport?.visualReferences ?? this.referencePayload()).some(r => r.intent?.trim())) return blocked('写下对象调整或反馈，或修改一项明确支持的属性。');
      for (const field of changeRequest.fields) {
        const cap = this.allCapabilities().find(item => { const parts = this.splitCapability(item); return parts.objectId === field.objectId && parts.fieldId === field.fieldId; });
        if (cap?.min != null && Number(field.value) < Number(cap.min) || cap?.max != null && Number(field.value) > Number(cap.max)) return blocked(`${cap.label || field.fieldId}超出允许范围。`);
        if (cap?.type === 'choice' && !(cap.options || []).some(option => String(typeof option === 'object' ? option.value : option) === String(field.value))) return blocked(`${cap.label || field.fieldId}不在服务声明的选项中。`);
      }
      return this.submitConcept(text, true, null, { reviewedReport: frozenReport });
    }
    for (const key of TEMPLATE_FIELDS) { const input = this.parameterInput(key); if (!input || input.disabled || !input.value) continue; const value = Number(input.value); if (value < Number(input.min) || value > Number(input.max)) return this.notify(`${LABELS[key]}超出允许范围。`); values[key] = value; }
    if (!text && !Object.keys(values).length) return blocked('写下调整内容，或修改一个受支持的选项。');
    const details = Object.entries(values).map(([key, value]) => `${LABELS[key]}调整为 ${value}`).join('；');
    return this.submitConcept([text, details].filter(Boolean).join('\n'), true, values);
  }
  clearNotice() { const box = $('#notice'); if (box) { box.textContent = ''; hide(box); } }
  notify(message) { const box = $('#notice'); if (!box) return; box.textContent = message; hide(box, false); box.scrollIntoView?.({ behavior: 'smooth', block: 'nearest' }); }
  destroy() {
    if (this.destroyed) return;
    this.destroyed = true; this.selectionGeneration++; this.workbenchGeneration++; this.workbenchLoad = null; this.draftConflictRefresh = null;
    this.draftStorageTarget?.removeEventListener?.('storage', this.boundDraftStorageChange);
    this.stopPolling(); this.stopProposalPolling(); this.stopEventStream(); this.stopConceptReferencePoll();
    if (this.document?.getElementById('app')) releaseVisuals(this.document.getElementById('app'));
    if (this.draftTimer != null) this.timers.clearTimeout(this.draftTimer); if (this.conceptDraftTimer != null) this.timers.clearTimeout(this.conceptDraftTimer);
  }
}

installVisualPlanning(StudioApp, { $, el, hide, cloneValue, sameValue, ACTIVE, PLANNING });
installImagePlanning(StudioApp, { $, el, cloneValue, sameValue });

if (typeof document !== 'undefined' && document.getElementById('app')) {
  const studio = new StudioApp(); studio.start();
  globalThis.ptahStudio = studio;
  globalThis.addEventListener?.('pagehide', () => studio.destroy(), { once: true });
}
