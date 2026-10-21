/* Real Studio controllers and React cards, with an explicitly fake provider. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { pathToFileURL } = require('node:url');
const { JSDOM } = require('jsdom');
const root = path.resolve(__dirname, '..');
const dom = new JSDOM(fs.readFileSync(path.join(root, 'studio/index.html'), 'utf8'), { url: 'http://127.0.0.1:8123/', pretendToBeVisual: true });
global.Option = dom.window.Option; global.FormData = dom.window.FormData;
const tick = () => new Promise(resolve => setTimeout(resolve, 0));
(async () => {
  const { StudioApp, DraftStore } = await import(pathToFileURL(path.join(root, 'studio/studio.js')).href);
  global.document = dom.window.document; global.window = dom.window; global.location = dom.window.location; global.history = dom.window.history;
  const urls = [];
  const routing = new StudioApp({ documentImpl: document, timers: globalThis, fetchImpl: async (url, options) => {
    urls.push([url, options.method]); return { ok: true, status: 200, text: async () => '{}' };
  } });
  routing.projectId = 'project-routing'; routing.token = 'fixture-token';
  for (const route of ['/visual-plans', '/concept-reference-batches', '/concept-reference-batches/batch-id/pause']) {
    await routing.request(route);
    await routing.request(route, { method: 'POST', token: true, body: {} });
  }
  assert(urls.every(([url]) => url.startsWith('/api/projects/project-routing/')), 'new routes retain project scope through the real request method');
  routing.destroy();
  const app = new StudioApp({ documentImpl: document, timers: globalThis, fetchImpl: async () => { throw Error('unexpected fetch'); } });
  app.projectId = 'project-image'; app.protocolVersion = 1; app.workflow = 'objects-v1';
  app.handshake = { storeId: 'image-plan-store' }; app.sessionPreferences = { revision: 0 };
  app.manager = { storeId: app.handshake.storeId, projects: [{ id: app.projectId, protocolVersion: 1, publicationRevision: 0 }] };
  app.workspace = { projects: app.manager.projects, jobs: [], proposals: [], packets: [] };
  app.drafts = new DraftStore(null, dom.window.localStorage); app.persistenceOK = true; app.readiness = { ready: true };
  app.renderWorkflowStages = () => {}; app.renderWorkflowStatus = () => {}; app.startProposalPolling = () => {}; app.renderPacketPreview = () => {}; app.loadReviewedPlan = async () => null;
  app.proposal = { id: 'proposal-image', projectId: app.projectId, revision: 1, publicationRevision: 0, status: 'READY', workflow: 'objects-v1',
    text: '已提交赛博朋克概念', summary: '已提交反馈', discussion: [{ role: 'planner', summary: '已提交反馈', revision: 1 }], questions: [], assets: [], visualReferences: [], updatedAt: 'v1' };
  const source = () => ({ proposalId: app.proposal.id, proposalRevision: app.proposal.revision, feedbackId: 'discussion:0', contextVersion: app.proposal.updatedAt });
  const image = (id, title) => ({ id, title, quickDescription: `检查${title}的轮廓和风格`, purpose: `独立检查${title}`, concepts: [title], materialIds: [`object:${id}`], subject: title, composition: '清晰的概念对照', style: '青紫金属插画', preserve: '保留已提交主题', unknown: '精确规则和运行效果未知' });
  const result = { sharedStyle: '统一赛博朋克色调', images: [image('table', '牌桌氛围'), image('tools', '六种工具')],
    coverage: [{ concept: '牌桌', imageIds: ['table'], reason: '构图独立检查' }, { concept: '工具', imageIds: ['tools'], reason: '轮廓独立检查' }] };
  let plans = [{ id: 'visual-plan-fixture', source: source(), status: 'READY', result }], batches = [], planPosts = [], batchPosts = [], offline = false;
  const context = () => ({ projectId: app.projectId, source: source(), feedbackRevision: 1, promptHeader: 'Submitted materials:\n', instructionLabel: '\nVisual instructions for this image only:\n', promptLimit: 32000,
    materials: [{ id: 'plan', label: '完整技术方案', text: '长'.repeat(32403) }], imageMaterials: [{ id: 'original', label: '原始需求', text: '已提交需求' }, { id: 'object:table', label: '牌桌', text: '牌桌的暗金属与霓虹灯' }, { id: 'object:tools', label: '六工具', text: '六个可区分的义体工具' }] });
  app.request = async (route, options = {}) => {
    if (route.endsWith('/visual-context')) return context();
    if (route === '/visual-plans' && options.method === 'POST') { planPosts.push(structuredClone(options.body)); const p = { id: options.body.requestId, source: source(), status: 'READY', result }; plans.push(p); return { plan: p }; }
    if (route === '/visual-plans') return { plans };
    if (route === '/concept-reference-batches' && options.method === 'POST') {
      batchPosts.push(structuredClone(options.body));
      const saved = await app.drafts.get(app.conceptDraftKey(app.projectId));
      const inputs = Object.values(saved.proposalInputs).flatMap(Object.values);
      assert(inputs.some(i => i.imageBatchIntent?.requestId === options.body.requestId), 'batch identity persisted before POST');
      if (offline) throw new TypeError('offline');
      const prior = batches.find(b => b.id === options.body.requestId);
      if (prior) return { batch: prior };
      const batch = { id: options.body.requestId, projectId: app.projectId, source: source(), status: 'QUEUED', items: options.body.images.map(i => ({ imageId: i.id, imagePlan: i, status: 'WAITING' })) };
      batches.push(batch); return { batch };
    }
    if (route === '/concept-reference-batches') return { batches };
    if (route === '/concept-references') return { requests: [] };
    if (route.endsWith('/cancel')) { batches = batches.map(b => ({ ...b, status: 'CANCELLED' })); return { batch: batches[0] }; }
    throw Error(`unexpected route ${route}`);
  };
  app.renderProposal(); const supplement = document.querySelector('#ready-supplement'); supplement.value = '未提交补充不得进入图'; app.saveReadySupplementInput(supplement.value);
  const inputsBeforeOpen = structuredClone(app.proposalInputs);
  await app.openVisualPlanning();
  assert.deepEqual(app.proposalInputs, inputsBeforeOpen, 'loading valid suggestions does not change the reviewed local draft');
  assert.equal(planPosts.length, 0); assert.equal(batchPosts.length, 0, 'opening is read-only');
  assert.equal(document.querySelectorAll('.image-plan-editor').length, 2);
  assert(document.querySelector('#image-planning-area').textContent.includes('建议生成 2 张'));
  assert.equal(document.querySelector('#ready-supplement'), supplement);
  assert.equal(supplement.value, '未提交补充不得进入图');
  const draft = app.imagePlanningDraft();
  assert(!app.imagePlanningPrompt(draft.images[0]).includes('未提交'));
  assert(!app.imagePlanningPrompt(draft.images[0]).includes('义体工具'), 'per-image sources are isolated');
  assert([...app.imagePlanningPrompt(draft.images[0])].length < 1000, 'large technical plan is not in image prompt');
  assert(!document.querySelector('#generate-image-batch').disabled, 'long full plan does not disable scoped batch');
  assert(!document.querySelector('.legacy-single-image').open, 'full-material entry is collapsed');
  plans.push({ id: 'visual-plan-latest', source: source(), status: 'READY', result: { ...structuredClone(result), sharedStyle: '最新建议' } });
  await app.loadVisualPlanningRecords();
  assert.equal(app.imagePlanningDraft().planId, 'visual-plan-latest');
  [...document.querySelectorAll('#image-planning-area button')].find(b => b.textContent.startsWith('采用这份分图建议')).click();
  assert.equal(app.imagePlanningDraft().planId, 'visual-plan-fixture', 'selecting an older current-source plan uses that exact record');
  await app.loadVisualPlanningRecords();
  assert.equal(app.imagePlanningDraft().planId, 'visual-plan-fixture', 'polling retains the explicitly chosen plan');
  const edit = document.querySelector('.image-plan-details'); edit.open = true;
  const description = edit.querySelector('[data-image-field="quickDescription"]'); description.focus(); description.value = '只检查暗牌桌构图'; description.dispatchEvent(new dom.window.Event('input', { bubbles: true }));
  await app.loadVisualPlanningRecords();
  assert.equal(document.activeElement, description, 'polling preserves editing focus');
  assert.equal(description.value, '只检查暗牌桌构图'); description.blur(); await tick();
  assert(document.querySelector('.image-plan-details').open, 'expanded editor survives refresh');
  assert(document.querySelector('.image-plan-editor').textContent.includes('只检查暗牌桌构图'));
  const split = [...document.querySelectorAll('.image-plan-editor button')].find(b => b.textContent === '拆分此图'); split.click();
  assert.equal(app.imagePlanningDraft().images.length, 3);
  assert.equal(app.imagePlanningDraft().images[1].selected, false, 'split requires deliberate selection');
  const down = [...document.querySelectorAll('.image-plan-editor button')].find(b => b.textContent === '下移'); down.click();
  assert(app.imagePlanningDraft().images[0].id.startsWith('image-'));
  await app.submitImageBatch();
  assert.equal(batchPosts.length, 1); assert.equal(batchPosts[0].images.length, 2);
  assert.equal(app.proposal.visualReferences.length, 0, 'batch does not adopt images');
  assert(document.querySelector('#generate-image-batch').disabled, 'active batch blocks new images');
  await app.openVisualPlanning(); assert.equal(batchPosts.length, 1, 'refresh does not resubmit');
  await app.controlImageBatch(batches[0], 'cancel');
  assert(!document.querySelector('#generate-image-batch').disabled, JSON.stringify({batches:app.referenceBatches,pending:app.hasPendingConceptGeneration(),intent:app.proposalRevisionDraft().imageBatchIntent,images:app.imagePlanningDraft().images.map(i=>({id:i.id,selected:i.selected,error:app.imagePlanError(i)}))}));
  offline = true; await app.submitImageBatch();
  const requestId = app.proposalRevisionDraft().imageBatchIntent.requestId;
  assert.equal(batchPosts.at(-1).requestId, requestId);
  offline = false; await app.submitImageBatch(true);
  assert.equal(batchPosts.at(-1).requestId, requestId, 'unknown outcome reuses original batch id');
  assert.equal(app.proposalRevisionDraft().imageBatchIntent, undefined);
  await app.controlImageBatch(batches.at(-1), 'cancel');
  // Additional pictures remain separate; the batch cap is checked before POST.
  const d = app.imagePlanningDraft();
  for (let n = 3; n < 8; n++) d.images.push({ ...structuredClone(result.images[0]), id: `extra-${n}`, selected: true });
  app.renderImagePlanningArea(); assert(document.querySelector('#generate-image-batch').disabled);
  const before = batchPosts.length; await app.submitImageBatch(); assert.equal(batchPosts.length, before);
  const focusedEditor = document.querySelector('[data-image-field="subject"]');
  focusedEditor.focus();
  app.manager.projects[0].archived = true;
  app.applyProjectView({ projectId: app.projectId, project: app.manager.projects[0] });
  assert(document.querySelector('#plan-proposal-images').disabled);
  assert(document.querySelector('#generate-image-batch').disabled);
  assert(document.querySelector('[data-image-field="subject"]').disabled, 'remote archive immediately makes focused edits read-only');
  app.manager.projects[0].archived = false;
  app.proposal.updatedAt = 'v2'; await app.openVisualPlanning();
  assert.equal(app.imagePlanningDraft().images.length, 0, 'old source draft never becomes current');
  assert(app.visualPlanning.priorImagePlanning.length, 'old visual instructions remain inspectable');
  assert(document.querySelector('#image-planning-area').textContent.includes('历史来源'));
  await app.requestImagePlan(); assert.equal(planPosts.length, 1);
  assert.equal(app.proposal.revision, 1, 'explicit visual planning never revises game plan');
  app.destroy();
  console.log('PASS image planning: short cards, scoped prompts, preserved drafts/focus, split/order, serial batch confirmation, durable retry, archive, source changes and explicit planning');
})().catch(error => { console.error(error); process.exitCode = 1; });
