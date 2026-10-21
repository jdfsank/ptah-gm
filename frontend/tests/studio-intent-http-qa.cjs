#!/usr/bin/env node
/* Real StudioApp -> independent frontend -> HTTP command -> retained request.
 * The temporary backend suppresses native planning; this proves transport only.
 */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { spawn } = require('node:child_process');
const { once } = require('node:events');
const { pathToFileURL } = require('node:url');
const { JSDOM } = require('jsdom');
const root = path.resolve(__dirname, '..');
const fixture = String.raw`
import json, sys, tempfile, threading
from pathlib import Path
from backend.coordinator import Coordinator
from backend.server import REPO_ROOT, make_server
from backend.object_protocol import catalog_from_document
from backend.tests.test_object_protocol import workbench_document
from tools.studio_frontend import make_frontend_server
with tempfile.TemporaryDirectory() as directory:
    c = Coordinator(REPO_ROOT, state_root=Path(directory), test_data=True)
    c._plan_generic = lambda *_args, **_kwargs: None
    c.iteration_status = lambda _pid: {'iterationReady': True, 'iterationReadyTestOnly': True}
    p = c.create_project(operator_id=c.operator_id, title='HTTP intent fixture')
    d = workbench_document()
    s = {'id':'intent-http-snapshot','projectId':p['id'],'publicationRevision':1,
        'sourceCommit':'intent-http-base','workflow':'objects-v1','kind':'MVP','playable':True,
        'document':d,'catalog':catalog_from_document(d,'intent-http-base')}
    with c.transaction():
        c._put('snapshot',s)
        p.update(snapshotId=s['id'],publicationRevision=1)
        c._put('project',p)
    api = make_server(c,port=0)
    front = make_frontend_server(port=0,backend_port=api.server_port)
    for server in (api,front):
        threading.Thread(target=server.serve_forever,daemon=True).start()
    print(json.dumps({'base':f'http://127.0.0.1:{front.server_port}','projectId':p['id']}),flush=True)
    try: sys.stdin.read()
    finally:
        for server in (front,api): server.shutdown(); server.server_close()
        c.close()
`;

(async () => {
  const child = spawn(path.join(path.dirname(root), '.venv/bin/python'), ['-B', '-u', '-c', fixture], { cwd: path.dirname(root), stdio: ['pipe', 'pipe', 'inherit'] });
  let app, dom, releaseReceipt;
  try {
    const ready = await new Promise((resolve, reject) => {
      let text = '';
      child.stdout.on('data', chunk => { text += chunk; if (text.includes('\n')) { try { resolve(JSON.parse(text.split('\n')[0])); } catch (error) { reject(error); } } });
      child.once('error', reject);
      child.once('exit', code => reject(new Error(`HTTP fixture exited before ready: ${code}`)));
    });
    dom = new JSDOM(fs.readFileSync(path.join(root, 'studio/index.html'), 'utf8'), { url: ready.base+'/studio/', pretendToBeVisual: true });
    dom.window.HTMLDialogElement.prototype.showModal = function () { this.open = true; };
    dom.window.HTMLDialogElement.prototype.close = function () { this.open = false; };
    global.FormData = dom.window.FormData;
    global.HTMLElement = dom.window.HTMLElement;
    global.Option = dom.window.Option;
    global.location = dom.window.location;
    global.history = dom.window.history;
    global.localStorage = dom.window.localStorage;
    global.confirm = () => { throw new Error('Transport QA must not accept a candidate.'); };
    delete global.document;
    const { StudioApp } = await import(pathToFileURL(path.join(root, 'studio/studio.js')).href);
    global.document = dom.window.document;
    const sent = [];
    let markReceived;
    const iterationReceived = new Promise(resolve => { markReceived = resolve; });
    const receiptGate = new Promise(resolve => { releaseReceipt = resolve; });
    const fetchImpl = async (url, options = {}) => {
      const body = options.method === 'POST' ? JSON.parse(options.body) : null;
      if (body) sent.push(body);
      const response = await fetch(new URL(url, ready.base), { ...options, headers: { ...options.headers, Origin: ready.base } });
      if (body?.type === 'iteration.submit') { markReceived(); await receiptGate; }
      return response;
    };
    app = new StudioApp({ fetchImpl, documentImpl: dom.window.document, timers: globalThis });
    await app.start();
    await app.openProject(ready.projectId, 'iteration');
    assert(app.snapshot, document.querySelector('#blocked-copy').textContent);
    app.selectObject('player');
    const speed = document.querySelector('[data-field-id="player.speed"]');
    speed.value = '280';
    speed.dispatchEvent(new dom.window.Event('input', { bubbles: true }));
    app.selectObject('player-instance');
    assert.equal(app.selectedObjectId, 'player-instance');
    const note = document.querySelector('#edit-text');
    note.value = '只调整当前实例的外观，其他同类保持不变；奖励数量保持原值。';
    note.dispatchEvent(new dom.window.Event('input', { bubbles: true }));
    app.targetNotes.player = {
      objectId: 'player', feedbackId: 'stale-decision', text: '旧决定只保留供核对。',
      decisionFor: 'player.speed:source-note', decisionContext: {},
    };
    app.structuralProposals.push({ operationId: 'http-scene-op', kind: 'new-scene', sceneId: 'draft-scene-http', name: '独立备场', template: 'blank', bounds: [200, 160], connections: '不接入主流程', scope: '新场景' });
    app.legacyWorkbench.openReport();
    const reviewed = structuredClone(app.legacyWorkbench.reportData());
    assert(reviewed.notes.some(item => item.feedbackId === 'stale-decision'), 'stale decision remains visible in the local review record');
    assert.equal(reviewed.intent.changeRequest.feedback.length, 1, JSON.stringify({ notes: reviewed.notes, selected: app.selectedObjectId, text: note.value }));
    const ordinaryNote = reviewed.notes.find(item => item.objectId === 'player-instance' && !item.decisionFor);
    assert(ordinaryNote, 'ordinary user feedback remains in the review record');
    assert.equal(reviewed.intent.changeRequest.feedback[0].feedbackId, ordinaryNote.feedbackId);
    assert.equal(reviewed.intent.changeRequest.feedback[0].objectId, 'player-instance', 'ordinary user feedback without a decision is still sent');
    assert(!reviewed.intent.changeRequest.feedback.some(item => item.feedbackId === 'stale-decision'), 'a stale decision is excluded from the outbound request');
    assert.equal(document.querySelector('#workbench-report-confirm').disabled, false);
    const submitting = app.legacyWorkbench.confirmReport();
    await Promise.race([iterationReceived, submitting.then(() => { throw new Error('The reviewed report did not send an iteration command.'); })]);
    app.selectObject('player');
    const laterSpeed = document.querySelector('[data-field-id="player.speed"]');
    laterSpeed.value = '290'; laterSpeed.dispatchEvent(new dom.window.Event('input', { bubbles: true }));
    note.value = '这是发送后新增的下一轮意见。';
    note.dispatchEvent(new dom.window.Event('input', { bubbles: true }));
    releaseReceipt(); await submitting;
    const command = sent.find(item => item.type === 'iteration.submit');
    assert(command, document.querySelector('#notice').textContent);
    const response = await fetch(ready.base+`/api/projects/${ready.projectId}/workspace`);
    const workspace = await response.json();
    const retained = workspace.proposals.find(item => item.changeRequest?.operations?.some(op => op.operationId === 'http-scene-op'));
    assert(retained, 'the HTTP service retains the exact mixed submission');
    assert.deepEqual(retained.changeRequest.fields, reviewed.intent.changeRequest.fields);
    assert.deepEqual(retained.changeRequest.feedback, reviewed.intent.changeRequest.feedback);
    assert.deepEqual(retained.changeRequest.operations, reviewed.intent.changeRequest.operations);
    assert.deepEqual(command.payload.feedback, retained.changeRequest.feedback);
    assert.equal(retained.changeRequest.feedback[0].objectId, 'player-instance');
    assert(!retained.changeRequest.feedback.some(item => item.feedbackId === 'stale-decision'), 'the retained HTTP request excludes stale decisions');
    assert.match(retained.changeRequest.feedback[0].message, /其他同类保持不变.*奖励数量保持原值/);
    assert.equal(retained.changeRequest.fields[0].value, 280);
    assert.equal(app.fieldDraftValues['player.speed'], 290, 'the receipt preserves the later field edit');
    assert.equal(app.targetNotes.player.text, '这是发送后新增的下一轮意见。');
    if (process.env.STUDIO_INTENT_HTTP_EVIDENCE) fs.writeFileSync(process.env.STUDIO_INTENT_HTTP_EVIDENCE, JSON.stringify({
      level: 'real HTTP transport with native planning suppressed', userAcceptance: 'NOT_PERFORMED',
      command, proposalId: retained.id, retainedChangeRequest: retained.changeRequest,
      postReceiptDraft: { fields: app.fieldDraftValues, targetNotes: app.targetNotes },
      limitations: 'No real Agent, game implementation, Godot execution, or user acceptance was performed by this test.',
    }, null, 2)+'\n');
    console.log('PASS Studio intent HTTP QA: reviewed mixed intent, stable feedback identity, local scope and preservation text reach the retained HTTP request; no native Agent or acceptance performed');
  } finally {
    releaseReceipt?.();
    app?.destroy(); dom?.window.close(); child.stdin.end();
    if (child.exitCode === null) await once(child, 'exit');
  }
})().catch(error => { console.error(error.stack || error); process.exitCode = 1; });
