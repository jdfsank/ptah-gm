/* Regressions for the closed C6 trial. Isolated QA does not constitute user acceptance. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { pathToFileURL } = require('node:url');
const { JSDOM } = require('jsdom');
const root = path.resolve(__dirname, '..');
const dom = new JSDOM(fs.readFileSync(path.join(root, 'studio/index.html'), 'utf8'), {
  url: 'http://127.0.0.1:8123/?project=cycle-c6', pretendToBeVisual: true,
});
for (const key of ['location', 'history', 'localStorage', 'Option', 'FileReader']) global[key] = dom.window[key];
const tick = () => new Promise(resolve => setTimeout(resolve, 0));

(async () => {
  const { StudioApp } = await import(pathToFileURL(path.join(root, 'studio/studio.js')).href);
  const { releaseVisuals } = await import(pathToFileURL(path.join(root, 'studio/visual-feedback.js')).href);
  global.document = dom.window.document; global.window = dom.window;
  const app = new StudioApp({ documentImpl: document });
  const project = { id: 'cycle-c6', title: '绑定与采集回归', workflow: 'objects-v1' };
  app.projectId = project.id; app.workflow = project.workflow;
  app.manager = { projects: [project] }; app.workspace = { storeId: 'c6-store', projects: [project], packets: [], jobs: [] };
  const notices = [];
  app.notify = message => notices.push(message); app.queueDraftSave = () => {}; app.queueConceptDraftSave = () => {};
  app.bind();
  const vector = (id, value) => ({ id, label: id, type: 'vector2', value, editable: true });
  const scene = { id: 'stage', kind: 'scene', name: '场景', fields: [], sourceBindings: ['scenes/main.tscn'],
    workbench: { role: 'scene', bounds: [960, 540] } };
  const definition = { id: 'shared', kind: 'entity', name: '共享定义', sourceBindings: [], fields: [
    vector('extent', [40, 72]), { id: 'rate', label: '速度', type: 'number', value: 240, min: 0, max: 600, unit: '像素/秒', editable: true },
    { id: 'duration', label: '持续', type: 'number', value: 1, min: 0, max: 10, editable: true },
  ], workbench: { role: 'definition', size: [40, 72], sizeFieldId: 'extent', preview: {
    type: 'motion', label: '定义运动', speed: 240, speedFieldId: 'rate', stages: [{ label: '移动', duration: 1, durationFieldId: 'duration' }],
  } } };
  const instance = { id: 'placed', kind: 'entity', name: '场景实例', sourceBindings: [], fields: [vector('origin', [160, 400])],
    workbench: { role: 'instance', sceneId: scene.id, definitionId: definition.id, lock: 'free', position: [160, 400],
      positionFieldId: 'origin', size: [40, 72], preview: { type: 'motion', label: '实例运动', stages: [] } } };
  const objects = [scene, definition, instance];
  const source = JSON.stringify(objects);
  app.snapshot = { projectId: project.id, publicationRevision: 1, sourceCommit: 'git-source',
    document: { objects }, catalog: { objects: objects.map(({ fields, ...object }) => object) } };
  app.draftKey = app.makeDraftKey(app.snapshot);
  app.capabilities = { fields: objects.flatMap(object => object.fields.map(field => ({ ...field,
    id: `${object.id}.${field.id}`, objectId: object.id, fieldId: field.id, currentValue: field.value }))) };
  const wb = app.legacyWorkbench;
  const selected = () => app.objectItems().find(object => object.id === app.selectedObjectId);
  const token = () => document.querySelector('.workbench-object-token[data-object-id="placed"]');
  const setField = async (label, value) => {
    const control = document.querySelector(`#dynamic-fields [aria-label="${label}"]`)
      || document.querySelector(`#dynamic-fields input[data-field-key="${label}"]`);
    assert.ok(control, `field ${label} is present`); control.focus(); control.value = value;
    control.dispatchEvent(new dom.window.Event('input', { bubbles: true })); await tick(); return control;
  };

  app.selectObject(definition.id);
  const vectorGroup = document.querySelector('.vector2-control[role="group"]');
  assert.equal(vectorGroup.getAttribute('aria-label'), 'extent');
  assert.deepEqual([...vectorGroup.querySelectorAll('label')].map(label => label.textContent), ['X', 'Y']);
  assert.equal(vectorGroup.closest('.dynamic-field').tagName, 'DIV', 'two axis labels do not nest inside another label');
  const width = await setField('extent X', '60');
  assert.equal(document.activeElement, width, 'derived refresh keeps the native property input and focus');
  await setField('rate', '300'); await setField('duration', '2');
  app.selectObject(instance.id); wb.render();
  assert.equal(token().style.width, '6.25%', 'instance scene geometry follows the shared definition draft without duplicating the instance field');
  assert.match(document.querySelector('#object-detail').textContent, /60, 72/);
  assert.match(document.querySelector('#workbench-preview').textContent, /速度：300 像素\/秒/);
  assert.match(document.querySelector('#workbench-preview').textContent, /速度 × 时长 = 600/);
  assert.deepEqual(wb.metadata(selected(), { draft: false }).size, [40, 72], 'published geometry remains separate from the draft');
  assert.equal(JSON.stringify(objects), source, 'derivation never rewrites the published document');

  await setField('origin X', '700');
  assert.equal(token().style.left, `${700 / 960 * 100}%`, 'position property edits update the scene immediately');
  assert.equal(document.querySelector('[aria-label="提案位置 X"]').value, '700');
  assert.match(document.querySelector('.workbench-position-controls').textContent, /源码位置仍为 160, 400/);
  wb.resetHistory();
  assert.equal(wb.proposeMove(selected(), [720, 400]), true);
  assert.deepEqual(app.fieldDraftValues['placed.origin'], [720, 400]);
  assert.equal(app.structuralProposals.filter(operation => operation.kind === 'move').length, 0, 'bound position tools create one property draft, never a conflicting structural move');
  assert.equal(document.querySelector('[aria-label="origin X"]').value, '720');
  await wb.restoreHistory(wb.historyIndex - 1);
  assert.deepEqual(app.fieldDraftValues['placed.origin'], [700, 400], 'one undo restores the prior position property and scene');
  assert.equal(token().style.left, `${700 / 960 * 100}%`);
  await wb.restoreHistory(wb.historyIndex + 1);
  assert.deepEqual(app.fieldDraftValues['placed.origin'], [720, 400]);
  assert.equal(wb.proposeMove(selected(), [160, 400]), true);
  assert.equal(Object.hasOwn(app.fieldDraftValues, 'placed.origin'), false, 'returning to the source position removes the net property change');
  const capabilities = app.capabilities;
  app.capabilities = { fields: [] };
  assert.equal(wb.proposeMove(selected(), [200, 400]), false, 'an editable field without a current service capability cannot create a position draft');
  app.capabilities = capabilities;

  app.fieldDraftValues['shared.extent'] = [0, 72]; app.fieldDraftValues['shared.rate'] = -1;
  wb.render();
  assert.equal(wb.metadata(selected()).size, null, 'invalid bound size is unknown instead of using a stale static size');
  assert.equal(wb.resolvePreview(selected()).speed, null);
  assert.match(document.querySelector('#workbench-preview').textContent, /速度未声明|未声明/);
  assert.ok(!document.querySelector('#workbench-preview').textContent.includes('240 像素/秒'));
  assert.equal(wb.proposeMove(selected(), [200, 400]), false, 'unknown size prevents an ungrounded boundary claim');
  delete app.fieldDraftValues['shared.extent']; delete app.fieldDraftValues['shared.rate'];
  assert.equal(wb.resolvePreview({ ...instance, workbench: { ...instance.workbench, preview: { ...instance.workbench.preview, speed: 0 } } }).speed, 0, 'explicit instance zero overrides shared speed');
  assert.deepEqual(wb.metadata({ ...instance, workbench: { ...instance.workbench, overrides: { size: [20, 30] } } }).size, [20, 30]);
  assert.equal(wb.resolvePreview({ ...instance, workbench: { ...instance.workbench, definitionId: 'missing' } }).speed, null, 'missing definitions never borrow a different motion object');
  assert.deepEqual(wb.metadata({ ...instance, workbench: { ...instance.workbench, definitionId: 'missing' } }).size, [40, 72], 'legacy static geometry is retained when no explicit shared binding is available');

  const question = { id: 'scope', type: 'choice', prompt: '本轮是否只调整速度？', options: [{ value: 'rate-only', label: '仅速度改为300，其余保持' }] };
  const packet = { id: 'packet-c6', jobId: 'job-c6', projectId: project.id, proposalId: 'proposal-c6', proposalRevision: 2, publicationRevision: 1,
    userText: '初始原文', discussion: [{ role: 'planner', questions: [question] }, { role: 'user', answers: [{ questionId: question.id, text: 'rate-only' }] }],
    document: { objects }, changeRequest: {}, assets: [] };
  const candidate = { id: 'candidate-c6', jobId: 'job-c6', projectId: project.id, packetId: packet.id, candidateCommit: 'git-candidate', status: 'READY_FOR_REVIEW' };
  app.workspace.packets = [packet]; app.job = { id: 'job-c6', projectId: project.id, packetId: packet.id, status: 'READY_FOR_REVIEW', candidate };
  app.packet = packet; app.proposal = null;
  const posts = []; let failPost = true, pendingPost = null;
  app.request = async (route, options = {}) => {
    assert.match(route, /^\/candidates\/candidate-c6\/visuals$/);
    if (options.method === 'POST') {
      posts.push(structuredClone(options.body));
      if (pendingPost) await pendingPost;
      if (failPost) throw new Error('simulated network interruption');
    }
    return { captures: [] };
  };
  app.renderCandidate(candidate); await tick();
  const capturePanel = document.querySelector('.candidate-captures'), form = capturePanel.querySelector('form');
  const file = form.querySelector('[type="file"]');
  const image = new dom.window.File(['test image bytes'], 'capture.png', { type: 'image/png' });
  Object.defineProperty(file, 'files', { configurable: true, value: [image] });
  for (const input of form.querySelectorAll('input:not([type="file"])')) input.value = '实际采集条件';
  const sceneInput = form.querySelector('[aria-label="截图场景"]'); sceneInput.focus(); sceneInput.setSelectionRange(1, 3);
  assert.match(document.querySelector('.candidate-visual-comparison').textContent, /本轮是否只调整速度？\n选择：仅速度改为300，其余保持/);
  app.previews = [{ id: 'preview-c6', projectId: project.id, status: 'RUNNING', artifactRef: { jobId: app.job.id, packetId: packet.id, sourceCommit: candidate.candidateCommit } }];
  app.renderCandidate({ ...candidate }); await tick();
  assert.equal(document.querySelector('.candidate-captures'), capturePanel, 'preview polling retains the exact native capture panel');
  assert.equal(document.querySelector('.candidate-capture-form [type="file"]'), file);
  assert.equal(file.files[0], image); assert.equal(sceneInput.value, '实际采集条件');
  assert.equal(document.activeElement, sceneInput); assert.equal(sceneInput.selectionStart, 1);
  form.dispatchEvent(new dom.window.Event('submit', { bubbles: true, cancelable: true }));
  for (let i = 0; i < 30 && !posts.length; i++) await tick();
  assert.equal(posts.length, 1); await tick();
  app.renderCandidate(candidate); await tick();
  assert.equal(sceneInput.value, '实际采集条件');
  assert.match(notices.at(-1), /保留原文件与条件/);
  let finishPost;
  pendingPost = new Promise(resolve => { finishPost = resolve; }); failPost = false;
  form.dispatchEvent(new dom.window.Event('submit', { bubbles: true, cancelable: true }));
  for (let i = 0; i < 30 && posts.length < 2; i++) await tick();
  assert.equal(posts[1].requestId, posts[0].requestId, 'the original failed request identity survives polling and retry');
  app.renderCandidate(candidate); await tick();
  assert.equal(document.querySelector('.candidate-captures'), capturePanel, 'a submission in flight keeps its panel and disabled submit state');
  assert.equal(form.querySelector('[type="submit"]').disabled, true);
  assert.equal(sceneInput.disabled, true, 'conditions remain fixed while the image and request are being saved');
  finishPost(); await tick(); await tick();
  assert.equal(sceneInput.value, '', 'a confirmed save resets the retained form');
  assert.equal(sceneInput.disabled, false);

  let releaseOldRead, firstRead = true;
  const oldRead = new Promise(resolve => { releaseOldRead = resolve; });
  const savedCapture = { id: 'capture-saved', candidateId: candidate.id, candidateCommit: candidate.candidateCommit,
    jobId: app.job.id, projectId: project.id, packetId: packet.id,
    asset: { id: 'capture-asset', width: 960, height: 540 }, conditions: { scene: '已保存采集' } };
  app.request = async (route, options = {}) => {
    if (options.method === 'POST') return {};
    if (firstRead) { firstRead = false; return oldRead; }
    return { captures: [savedCapture] };
  };
  for (const input of form.querySelectorAll('input:not([type="file"])')) input.value = '新条件';
  app.renderCandidate(candidate);
  form.dispatchEvent(new dom.window.Event('submit', { bubbles: true, cancelable: true }));
  for (let i = 0; i < 30 && !capturePanel.textContent.includes('已保存采集'); i++) await tick();
  assert.match(capturePanel.textContent, /已保存采集/);
  releaseOldRead({ captures: [] }); await tick();
  assert.match(capturePanel.textContent, /已保存采集/, 'a slow pre-save poll cannot erase the newly confirmed capture result');

  sceneInput.value = '不得借给其他候选';
  const changed = { ...candidate, candidateCommit: 'different-git' }; app.job.candidate = changed;
  app.renderCandidate(changed); await tick();
  assert.notEqual(document.querySelector('.candidate-captures'), capturePanel, 'a changed Git version creates a clean capture form');
  assert.equal(document.querySelector('[aria-label="截图场景"]').value, '');
  const otherPanel = document.querySelector('.candidate-captures');
  app.advanceSelection(); app.renderCandidate(changed); await tick();
  assert.notEqual(document.querySelector('.candidate-captures'), otherPanel, 'a new selection generation never revives an older unsaved native file');
  app.job.status = 'PUBLISHED'; app.renderCandidate(changed); await tick();
  assert.equal(document.querySelector('.candidate-capture-form'), null, 'a published candidate is read only and cannot reuse an editable form');
  app.projectId = 'different-project';
  assert.equal(app.candidateCaptureKey(changed, packet), null, 'cross-project candidates cannot retain a form');
  const css = fs.readFileSync(path.join(root, 'studio/studio.css'), 'utf8');
  assert.match(css, /\.evidence-list li\{overflow-wrap:anywhere\}/, 'technical evidence wraps within its own list rather than hiding page overflow');
  releaseVisuals(document.body); app.destroy(); dom.window.close();
  console.log('PASS C6: shared geometry and motion drafts, source separation, position controls and undo, unknown values, frozen Chinese answers, exact-candidate native form retention, in-flight retry identity, and read-only transitions');
})().catch(error => { console.error(error); dom.window.close(); process.exitCode = 1; });
