/* Real controller and React cards; injected transport is a regression fixture. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { pathToFileURL } = require('node:url');
const { JSDOM } = require('jsdom');
const root = path.resolve(__dirname, '..');
const dom = new JSDOM(fs.readFileSync(path.join(root, 'studio/index.html'), 'utf8'), { url: 'http://127.0.0.1:8123/', pretendToBeVisual: true });
delete global.document;
global.Option = dom.window.Option; global.FormData = dom.window.FormData;
const tick = () => new Promise(resolve => setTimeout(resolve, 0));

(async () => {
  const { StudioApp, DraftStore } = await import(pathToFileURL(path.join(root, 'studio/studio.js')).href);
  global.document = dom.window.document; global.window = dom.window; global.location = dom.window.location; global.history = dom.window.history;
  const app = new StudioApp({ documentImpl: document, timers: globalThis, fetchImpl: async () => { throw new Error('unexpected fetch'); } });
  app.projectId = 'project-a'; app.protocolVersion = 1;
  app.handshake = { storeId: 'visual-planning-store' };
  app.manager = { storeId: app.handshake.storeId, projects: [{ id: 'project-a', protocolVersion: 1, workflow: 'objects-v1', publicationRevision: 0 }] };
  app.workspace = { projects: app.manager.projects, jobs: [], proposals: [], packets: [] };
  app.workflow = 'objects-v1'; app.snapshot = { projectId: app.projectId, publicationRevision: 0, sourceCommit: null };
  app.drafts = new DraftStore(null, dom.window.localStorage); app.persistenceOK = true;
  app.readiness = { ready: true }; app.sessionPreferences = { revision: 0 };
  app.renderWorkflowStages = () => {}; app.renderWorkflowStatus = () => {}; app.startProposalPolling = () => {}; app.renderPacketPreview = () => {};
  app.loadReviewedPlan = async () => null;
  let commands = [], generations = [], contexts = 0;
  const asset = { id: 'visual-asset', name: 'concept.png', width: 1536, height: 1024, generation: { model: 'gpt-image-2', requestedSize: '1536x1024', provenance: { projectId: app.projectId, source: { proposalId: 'proposal-a', proposalRevision: 1, feedbackId: 'discussion:1' } } } };
  const p = { id: 'proposal-a', projectId: app.projectId, revision: 1, publicationRevision: 0, workflow: 'objects-v1', status: 'NEEDS_CLARIFICATION', text: '已提交原始需求', summary: '已提交策划反馈', assets: [], visualReferences: [], questions: [{ id: 'direction', prompt: '选择方向', type: 'text', required: true }], discussion: [{ role: 'planner', summary: '已提交策划反馈', revision: 1 }], updatedAt: 'version-1' };
  let sourceContext = () => ({ projectId: app.projectId, source: { proposalId: app.proposal.id, proposalRevision: app.proposal.revision, feedbackId: 'discussion:1', contextVersion: app.proposal.updatedAt }, feedbackRevision: 1,
    materials: [{ id: 'original', label: '原始需求', text: '已提交原始需求' }, { id: 'feedback', label: '当前反馈', text: '已提交策划反馈' }, { id: 'plan', label: '当前方案', text: '已提交方案' }], promptHeader: 'Submitted materials:\n', instructionLabel: '\nVisual instructions:\n', promptLimit: 32000 });
  app.request = async (route, options = {}) => {
    if (route.endsWith('/visual-context')) { contexts++; return sourceContext(); }
    if (route === '/concept-references' && options.method === 'POST') {
      generations.push(structuredClone(options.body));
      const saved = await app.drafts.get(app.conceptDraftKey(app.projectId));
      assert(saved.conceptGenerationRequests.some(r => r.id === options.body.requestId), 'request identity is durable before POST');
      return { request: { id: options.body.requestId, projectId: app.projectId, request: structuredClone(options.body), status: 'GENERATED', asset, sourceSnapshot: { projectId: app.projectId, source: structuredClone(options.body.source) }, prompt: app.visualPlanningPrompt() } };
    }
    if (route === '/concept-references') return { requests: app.conceptGenerationRequests };
    throw new Error(`unexpected route ${route}`);
  };
  app.sendCommand = async (type, payload) => {
    commands.push({ type, payload: structuredClone(payload) });
    return { proposal: { ...app.proposal, revision: app.proposal.revision + 1, status: 'PLANNING', questions: [], visualReferences: payload.visualReferences ?? app.proposal.visualReferences, assets: payload.assetRefs?.length ? [asset] : [], updatedAt: 'version-next' } };
  };
  app.proposal = p; app.renderProposal();
  const entry = document.querySelector('[data-action="open-visual-planning"]');
  const shortcut = document.querySelector('#project-visual-entry');
  const panel = document.querySelector('#proposal-visual-planning');
  const reveals = []; panel.scrollIntoView = options => reveals.push(options);
  assert(entry, 'clarification feedback has visual entry');
  for (const button of [entry, shortcut]) {
    assert.equal(button.getAttribute('aria-controls'), panel.id, 'entries identify the panel they open');
    assert.equal(button.getAttribute('aria-expanded'), 'false', 'closed panel state is exposed');
  }
  const answer = document.querySelector('#questions [name="direction"]'); answer.value = '未提交回答应完整保留'; app.saveProposalQuestionInput('direction', answer.value);
  document.querySelector('#concept').value = '未提交初始草稿'; document.querySelector('#edit-text').value = '未提交工作台草稿';
  entry.click();
  assert.equal(document.activeElement, panel, 'explicit opening focuses the visible panel before context arrives');
  await tick();
  assert.equal(document.activeElement, panel, 'context rendering retains panel focus');
  assert.deepEqual(reveals, [{ block: 'start', behavior: 'instant' }], 'explicit opening brings an offscreen panel into view');
  assert([entry, shortcut].every(button => button.getAttribute('aria-expanded') === 'true'));
  [...panel.querySelectorAll('button')].find(button => button.textContent === '收起视觉策划').click();
  assert.equal(document.activeElement, entry, 'closing returns focus to the feedback entry');
  assert([entry, shortcut].every(button => button.getAttribute('aria-expanded') === 'false'));
  shortcut.click(); await tick();
  assert.equal(reveals.length, 2, 'the project header entry also reveals the panel');
  assert.equal(document.activeElement, panel);
  answer.focus();
  await app.openVisualPlanning();
  [...panel.querySelectorAll('button')].find(button => button.textContent === '刷新已提交依据').click(); await tick();
  assert.equal(reveals.length, 2, 'context refresh never scrolls the page again');
  assert.equal(document.activeElement, answer, 'background context refresh never steals input focus');
  assert.equal(document.querySelector('#questions [name="direction"]'), answer, 'opening does not rebuild answer controls');
  assert.equal(answer.value, '未提交回答应完整保留');
  assert.equal(generations.length, 0, 'opening only reads context');
  const overview = document.querySelector('[aria-label="当前反馈与已采纳参考"]');
  assert(overview.textContent.includes('已提交策划反馈') && !overview.textContent.includes('"questions"'), 'overview shows feedback prose, while exact source remains expandable');
  assert(!app.visualPlanningPrompt().includes('未提交'), 'prompt excludes all unsent controls');
  const instruction = document.querySelector('#proposal-visual-instructions'); instruction.value = '只核对灯光与轮廓'; instruction.dispatchEvent(new dom.window.Event('input', { bubbles: true }));
  document.querySelector('#generate-proposal-reference').click(); await tick(); await tick();
  assert.equal(generations.length, 1, document.querySelector('#notice').textContent + JSON.stringify({ requests: app.conceptGenerationRequests, persistenceOK: app.persistenceOK, key: app.conceptDraftKey(app.projectId), disabled: document.querySelector('#generate-proposal-reference').disabled })); assert.equal(generations[0].sourceText, '');
  assert.equal(generations[0].interpretation, instruction.value);
  assert.equal(generations[0].size, '1536x1024'); assert.equal(generations[0].quality, 'low');
  assert.equal(app.proposal.visualReferences.length, 0, 'generation remains check-only');
  await app.openVisualPlanning(); await app.loadConceptReferences(); assert.equal(generations.length, 1, 'refresh never regenerates');
  document.querySelector('#proposal-visual-results [data-action="select-concept-reference"]').click();
  assert.equal(commands.length, 0, 'adoption edits a local revision draft');
  const ref = app.proposalRevisionDraft().visualReferences[0]; Object.assign(ref, { intent: '暖光构图', preserve: '保留规则', unknown: '手感未知' });
  answer.value = ''; await app.answerQuestions(); assert.equal(commands.length, 0, 'required answers cannot be bypassed by reference adoption');
  answer.value = '向灯光前进'; await app.answerQuestions();
  assert.equal(commands.length, 1); assert.equal(commands[0].type, 'proposal.revise');
  assert.equal(commands[0].payload.answers[0].text, '向灯光前进'); assert.equal(commands[0].payload.visualReferences[0].intent, '暖光构图');
  assert.equal(app.proposal.revision, 2);
  assert(document.querySelector('[data-action="open-visual-planning"]'), 'waiting/iteration planning has entry');
  await app.openVisualPlanning();
  assert(document.querySelector('#proposal-visual-results').textContent.includes('proposal-a r1'), 'old image retains original revision');
  assert(document.querySelector('#proposal-visual-results').textContent.includes('不视为新版方案'));
  assert(document.querySelector('#proposal-visual-results').textContent.includes('已纳入当前方案'), 'submitted adoption is distinct from an unsubmitted draft');

  app.proposal = { ...app.proposal, status: 'READY', questions: [], updatedAt: 'ready-2' }; app.renderProposal(); await tick();
  const supplement = document.querySelector('#ready-supplement'); supplement.value = '未提交 READY 补充'; app.saveReadySupplementInput(supplement.value);
  await app.openVisualPlanning(); assert.equal(document.querySelector('#ready-supplement'), supplement); assert.equal(supplement.value, '未提交 READY 补充');
  assert(!app.visualPlanningPrompt().includes('未提交 READY'), 'READY draft excluded');
  app.proposalRevisionDraft(app.proposal, true).visualReferences = [{ ...ref, intent: 'READY 更新用途' }];
  await app.reviseVisualReferences(app.proposal, app.proposalRevisionDraft().visualReferences, { disabled: false });
  assert.equal(commands.at(-1).payload.supplement, '未提交 READY 补充'); assert.equal(commands.at(-1).payload.visualReferences[0].intent, 'READY 更新用途');
  app.proposal = { ...app.proposal, status: 'READY', questions: [] }; app.renderProposal();
  app.proposalRevisionDraft(app.proposal, true).visualReferences = [];
  await app.reviseReadyProposal(app.proposal.id, '');
  assert.equal(commands.at(-1).payload.visualReferences.length, 0, 'READY reference-only removal submits');
  assert.equal(commands.at(-1).payload.supplement, undefined);

  app.proposal = { ...app.proposal, status: 'READY', questions: [] }; app.renderProposal();
  app.proposalRevisionDraft(app.proposal, true).visualReferences = [{ ...ref }];
  const count = commands.length; document.querySelector('#reviewed').checked = true;
  await app.freezeProposal(); assert.equal(commands.length, count, 'pending reference draft blocks freeze before command');
  assert(document.querySelector('#notice').textContent.includes('参考草稿有未提交变更'));
  await app.openVisualPlanning();
  [...document.querySelectorAll('#proposal-visual-planning button')].find(b => b.textContent === '撤销本轮参考草稿').click();
  assert.equal(app.hasPendingProposalReferences(), false);

  const baseContext = sourceContext;
  sourceContext = () => ({ ...baseContext(), materials: [{ id: 'original', label: '原始需求', text: '原文' }, { id: 'plan', label: '大方案', text: '长'.repeat(33000) }] });
  await app.openVisualPlanning(); assert(document.querySelector('#generate-proposal-reference').disabled, 'oversized full material is blocked');
  const material = document.querySelector('[data-material-id="plan"]'); material.checked = false; material.dispatchEvent(new dom.window.Event('change'));
  assert(!document.querySelector('#generate-proposal-reference').disabled, 'explicit reduction enables generation');
  assert(!app.visualPlanningPrompt().includes('长'.repeat(100)), 'unselected material is excluded, not truncated');
  const originalMaterial = document.querySelector('[data-material-id="original"]'); originalMaterial.checked = false; originalMaterial.dispatchEvent(new dom.window.Event('change'));
  app.renderConceptReferenceResults(); assert(document.querySelector('#generate-proposal-reference').disabled, 'polling cannot enable generation with no selected material');
  delete app.proposalRevisionDraft().visualPlanning; sourceContext = baseContext;

  app.manager.projects[0].archived = true; await app.openVisualPlanning();
  assert(document.querySelector('#generate-proposal-reference').disabled);
  assert(!document.querySelector('#proposal-visual-planning .reference-revision-editor'), 'archive has no reference mutation controls');
  app.manager.projects[0].archived = false;
  app.proposal = { ...app.proposal, status: 'FROZEN' }; app.job = { projectId: app.projectId, status: 'RUNNING' }; await app.openVisualPlanning();
  assert(!document.querySelector('#generate-proposal-reference').disabled, 'production allows manual visual inspection');
  assert(document.querySelector('.reference-revision-actions button').disabled, 'active production cannot submit reference revision');
  app.job = null;

  app.proposalRevisionDraft(app.proposal, true).visualReferences = [{ ...ref, intent: '冻结后仅提交参考' }];
  await app.openVisualPlanning();
  const previousProposal = app.proposal;
  const referenceSubmit = document.querySelector('#proposal-visual-planning .reference-revision-actions button');
  const beforeReferenceSubmit = commands.length;
  app.proposal = structuredClone(app.proposal); app.renderProposal();
  assert.notEqual(app.proposal, previousProposal, 'polling replaces the object with the same persisted identity');
  assert.equal(document.querySelector('#proposal-visual-planning .reference-revision-actions button'), referenceSubmit, 'same-source polling preserves the panel controls');
  referenceSubmit.click(); await tick(); await tick();
  assert.equal(commands.length, beforeReferenceSubmit + 1, 'reference submit survives same-revision polling');
  assert.equal(commands.at(-1).payload.visualReferences[0].intent, '冻结后仅提交参考');
  assert.equal(commands.at(-1).payload.supplement, undefined, 'frozen reference-only submission adds no hidden supplement');
  referenceSubmit.click(); await tick();
  assert.equal(commands.length, beforeReferenceSubmit + 1, 'old revision handler cannot submit to the new revision');
  assert(document.querySelector('#notice').textContent.includes('修订已变化'), 'stale handler explains why it was refused');

  const workingRequest = app.request;
  app.conceptGenerationRequests = [];
  app.request = async (route, options) => {
    if (options?.method === 'POST') { const error = new Error('策划反馈已变化，请重新核对'); error.status = 409; error.body = { code: 'REFERENCE_SOURCE_STALE' }; throw error; }
    return workingRequest(route, options);
  };
  await app.openVisualPlanning(); document.querySelector('#generate-proposal-reference').click(); await tick(); await tick();
  assert.equal(app.conceptGenerationRequests[0].status, 'FAILED', 'definite stale-source rejection never becomes an unresolved provider request');
  assert.equal(app.hasPendingConceptGeneration(), false); assert(document.querySelector('#generate-proposal-reference').disabled, 'stale preview requires explicit recheck');
  app.request = workingRequest; await app.openVisualPlanning(); assert(!document.querySelector('#generate-proposal-reference').disabled, 'refreshing canonical source releases the stale-preview gate');

  // A persisted request can recover after an unknown network outcome, with its original identity.
  const normalRequest = app.request;
  app.conceptGenerationRequests = []; app.request = async (route, options) => { if (options?.method === 'POST') throw new TypeError('offline'); return normalRequest(route, options); };
  await app.openVisualPlanning();
  document.querySelector('#generate-proposal-reference').click(); await tick(); await tick();
  const pending = app.conceptGenerationRequests[0]; assert.equal(pending.status, 'UNCERTAIN');
  const saved = await app.drafts.get(app.conceptDraftKey(app.projectId)); assert.equal(saved.conceptGenerationRequests[0].id, pending.id);
  app.request = normalRequest; await app.recoverConceptRequest(pending); assert.equal(generations.at(-1).requestId, pending.id);

  // Late generation completion cannot render into a different selected project.
  let resolveGeneration;
  app.conceptGenerationRequests = [];
  app.request = async (route, options) => options?.method === 'POST' ? new Promise(resolve => { resolveGeneration = resolve; }) : normalRequest(route, options);
  const late = app.dispatchConceptReference({ requestId: 'late-project-request-001', sourceText: '原始需求', interpretation: '', size: '1536x1024', quality: 'low' });
  await tick(); app.advanceSelection(); app.projectId = 'project-b'; app.proposal = null; app.conceptGenerationRequests = [];
  resolveGeneration({ request: { id: 'late-project-request-001', projectId: 'project-a', status: 'GENERATED', asset } }); await late;
  assert.equal(app.conceptGenerationRequests.length, 0); assert(!document.querySelector('#proposal-visual-planning').textContent.includes('project-b'));
  app.destroy();
  console.log(`PASS Studio visual planning: submitted context, preservation, atomic adoption, READY, freeze, archive, limits, recovery, switching (${contexts} context reads, ${generations.length} explicit fixture generations)`);
})().catch(error => { console.error(error); process.exitCode = 1; });
