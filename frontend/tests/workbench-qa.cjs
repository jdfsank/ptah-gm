'use strict';

// React shell integration against the real, built domain scripts. Every fetch is
// intercepted here: this suite never opens a browser, bridge, or Codex session.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { JSDOM, VirtualConsole } = require('jsdom');

const root = process.env.WORKBENCH_DIST || path.resolve(__dirname, '../dist');
const catalog = JSON.parse(fs.readFileSync(path.join(root, 'semantic-data.json'), 'utf8'));
const clone = value => JSON.parse(JSON.stringify(value));
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
const checks = [];
const openWindows = new Set();
const THREAD = 'mock-existing-local-thread';
const TOKEN = 'mock-page-session-token';
const STORE = 'mock-durable-store';
const BASELINE = 'mock-source-baseline';
const PENDING_KEY = 'velvet-eclipse-pending-submission';
const defaultStatus = () => ({
  mode: 'demo', threadId: THREAD, revision: 7, last: null,
  storeId: STORE, sourceBaseline: BASELINE, sourceMatchesAdapter: true,
});

function deferred() {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}

async function until(predicate, message, timeout = 1600) {
  const deadline = Date.now() + timeout;
  while (Date.now() < deadline) {
    if (predicate()) return;
    await delay(5);
  }
  assert.ok(predicate(), message);
}

async function setup(options = {}) {
  const errors = [];
  const virtualConsole = new VirtualConsole();
  virtualConsole.on('jsdomError', error => errors.push(error));
  virtualConsole.on('error', (...args) => errors.push(args.map(String).join(' ')));
  const dom = new JSDOM(fs.readFileSync(path.join(root, 'index.html'), 'utf8'), {
    url: 'http://127.0.0.1:8765/',
    runScripts: 'outside-only',
    pretendToBeVisual: true,
    virtualConsole,
  });
  openWindows.add(dom.window);
  const w = dom.window;
  const d = w.document;
  w.addEventListener('error', event => errors.push(event.error || event.message));
  w.addEventListener('unhandledrejection', event => errors.push(event.reason));
  for (const [key, value] of Object.entries(options.storage || {})) w.localStorage.setItem(key, value);

  const calls = [];
  const bridge = {
    status: clone({ ...defaultStatus(), ...options.status }),
    offline: !!options.offline,
    session: null,
    statusHandler: null,
    submitHandler: null,
    submissionHandler: null,
  };
  w.fetch = async (url, init = {}) => {
    const call = { url: String(url), method: (init.method || 'GET').toUpperCase(), ...init };
    if (call.body) call.payload = JSON.parse(call.body);
    calls.push(call);
    if (bridge.offline) throw new TypeError('Mock bridge offline');
    let value;
    if (call.url === '/api/session' && call.method === 'GET') {
      value = bridge.session ? await bridge.session(call) : { token: TOKEN };
    } else if (call.url === '/api/status' && call.method === 'GET') {
      value = bridge.statusHandler ? await bridge.statusHandler(call) : bridge.status;
    } else if (call.url.startsWith('/api/submission/') && call.method === 'GET') {
      const submissionId = decodeURIComponent(call.url.slice('/api/submission/'.length));
      value = bridge.submissionHandler ? await bridge.submissionHandler(submissionId, call)
        : { submission: bridge.status.last?.submissionId === submissionId ? bridge.status.last : null };
    } else if (call.url === '/api/submit' && call.method === 'POST') {
      call.pendingAtSend = JSON.parse(w.localStorage.getItem(PENDING_KEY) || 'null');
      if (bridge.submitHandler) value = await bridge.submitHandler(call);
      else {
        const receipt = record(call.payload, 'succeeded');
        bridge.status = { ...bridge.status, revision: bridge.status.revision + 1, last: receipt };
        value = receipt;
      }
    } else {
      throw new Error(`Unexpected fetch ${call.method} ${call.url}`);
    }
    if (value && value.mockHttpError) {
      const { status, error } = value;
      return { ok: false, status, json: async () => ({ error }) };
    }
    const body = clone(value);
    return { ok: true, status: call.method === 'POST' ? 202 : 200, json: async () => body };
  };

  for (const name of ['demo-data', 'semantic-model', 'semantic-data', 'app', 'workbench']) {
    w.eval(fs.readFileSync(path.join(root, name + '.js'), 'utf8'));
  }
  const q = selector => {
    const el = d.querySelector(selector);
    assert.ok(el, `Missing element: ${selector}`);
    return el;
  };
  const button = text => {
    const el = [...d.querySelectorAll('#workbench-root button')].find(b => b.textContent.includes(text));
    assert.ok(el, `Missing shell button: ${text}`);
    return el;
  };
  const click = async selector => {
    const el = typeof selector === 'string' ? q(selector) : selector;
    assert.equal(el.disabled, false, `Disabled button: ${el.textContent}`);
    el.click();
    await delay(10);
    return el;
  };
  const change = async (selector, value) => {
    if(selector === '.submit-panel select'){w.DNAWorkbench.navigateTarget(value);await delay(10);return;}
    const el = q(selector);
    // Native prototype setters bypass React's value tracker, just as a real
    // input event does. Direct assignment alone would give a false test pass.
    const prototype = el.tagName === 'TEXTAREA' ? w.HTMLTextAreaElement.prototype
      : el.tagName === 'SELECT' ? w.HTMLSelectElement.prototype : w.HTMLInputElement.prototype;
    Object.getOwnPropertyDescriptor(prototype, 'value').set.call(el, value);
    el.dispatchEvent(new w.Event(el.tagName === 'TEXTAREA' ? 'input' : el.tagName === 'SELECT' || !el.closest('#workbench-root') ? 'change' : 'input', { bubbles: true }));
    await delay(10);
  };
  const openPanel = async () => {
    if (!d.querySelector('.submit-panel')) await click(button('预览与提交'));
    await until(() => d.querySelector('.submit-panel'), 'Submit panel should open');
  };
  const note = async (scope, text) => {
    await openPanel();
    await change('.submit-panel select', scope);
    await change('#target-comment', text);
  };
  const editPosition = async value => {
    await click('[data-action="view"][data-id="stage"]');
    await click('.room-nav [data-id="grand_lobby"]');
    await click('[data-action="object"][data-id="entry_arch"]');
    await change('#object-x', String(value));
  };
  const previewAndConfirm = async () => {const before=calls.filter(c=>c.method==='POST').length;await click(q('.submit-panel button[type="submit"]'));assert.equal(calls.filter(c=>c.method==='POST').length,before,'Preview is read-only');if(d.querySelector('.submission-preview'))await click(button('确认并提交这份载荷'));};
  const close = () => { w.close(); openWindows.delete(w); };
  await until(() => d.querySelector('.workbench-shell'), 'Built React shell should mount');
  await until(() => calls.length && (bridge.offline || calls.some(c => c.url === '/api/status')), 'Shell should check bridge connection');
  await delay(15);
  return {
    w, d, dom, q, button, click, change, openPanel, note, editPosition, close,
    bridge, calls, errors, previewAndConfirm,
    posts: () => calls.filter(call => call.method === 'POST'),
    text: () => d.querySelector('#workbench-root').textContent,
    snapshot: () => clone(w.DNAWorkbench.snapshot()),
    submitButton: () => q('.submit-panel button[type="submit"]'),
    storage: () => Object.fromEntries(Array.from({ length: w.localStorage.length }, (_, i) => {
      const key = w.localStorage.key(i);
      return [key, w.localStorage.getItem(key)];
    })),
  };
}

function record(payload, state, message = `Mock ${state}`) {
  return {
    submissionId: payload.submissionId,
    payload: clone(payload),
    state,
    result: {
      message,
      items: payload.items.map(item => ({ id: item.id, status: state === 'succeeded' ? 'demo_validated' : 'failed' })),
    },
  };
}

async function test(name, fn) {
  const before = new Set(openWindows);
  try {
    await fn();
    checks.push({ name, status: 'pass' });
  } catch (error) {
    checks.push({ name, status: 'FAIL', error: error.stack });
  } finally {
    for (const w of openWindows) {
      if (!before.has(w)) { w.close(); openWindows.delete(w); }
    }
  }
}

async function main() {
  await test('Idle, typed edits, navigation, notes and theme controls never POST or poll a model', async () => {
    const a = await setup();
    assert.deepEqual(a.calls.map(c => `${c.method} ${c.url}`), ['GET /api/session', 'GET /api/status']);
    await a.openPanel();
    await a.note('background:grand_lobby', 'Make the lobby background warmer.');
    await a.editPosition(200);
    await a.click('[data-action="view"][data-id="combat"]');
    await a.change('#semantic-object', 'actor.player');
    await a.change('#semantic-behavior', 'player.move');
    await a.change('#param-speed', '420');
    assert.equal(a.snapshot().behaviorDrafts['player.move'].speed, 420);
    const oldTheme = a.d.documentElement.dataset.theme;
    await a.click(a.d.querySelector('.shell-actions [aria-pressed]'));
    assert.notEqual(a.d.documentElement.dataset.theme, oldTheme);
    assert.equal(a.w.localStorage.getItem('workbench-theme'), a.d.documentElement.dataset.theme);
    await a.click(a.button('关闭')); 
    await a.openPanel();
    await delay(1050); // Exceeds the bridge's active-job polling interval.
    assert.equal(a.calls.length, 2, 'Idle/edit operations must not make further bridge requests');
    assert.equal(a.posts().length, 0);
    assert.ok(a.snapshot().revision >= 2);
    assert.equal(a.errors.length, 0, a.errors.map(String).join('\n'));
  });

  await test('Target catalog covers each scene/background/instance, all 21 definitions and all 38 behaviors', async () => {
    const a = await setup();
    await a.openPanel();
    const ids = a.w.DNAWorkbench.scopes().map(o => o.id);
    assert.equal(ids.length, new Set(ids).size, 'Scope IDs must be unique');
    assert.equal(ids.filter(id => id.startsWith('object:')).length, 21);
    assert.equal(ids.filter(id => id.startsWith('behavior:')).length, 38);
    assert.ok(ids.includes('project'));
    for (const room of a.snapshot().rooms) {
      assert.ok(ids.includes(`scene:${room.id}`));
      assert.ok(ids.includes(`background:${room.id}`));
      for (const object of room.objects) assert.ok(ids.includes(`instance:${room.id}:${object.id}`));
    }
    for (const object of catalog.objects) {
      assert.ok(ids.includes(`object:${object.id}`));
      for (const behavior of object.behaviors) assert.ok(ids.includes(`behavior:${behavior.id}`));
    }
    await a.click('[data-action="new-scene"]');
    await a.change('#new-name', 'QA scoped background');
    await a.click('[data-action="create-scene"]');
    const added = a.snapshot().rooms.at(-1);
    assert.equal(added.name, 'QA scoped background');
    assert.ok(a.w.DNAWorkbench.scopes().some(o => o.id === `background:${added.id}`));
    assert.equal(a.posts().length, 0);
    assert.equal(a.errors.length, 0, a.errors.map(String).join('\n'));
  });

  await test('Notes stay scoped through switches, panel close, domain edits and page reload', async () => {
    const a = await setup();
    const notes = {
      project: 'Overall project note.',
      'background:grand_lobby': 'Background note, not an instance note.',
      'object:actor.player': 'Shared player definition note.',
      'behavior:player.move': 'Move behavior note.',
      'instance:grand_lobby:entry_arch': 'Only this arch instance.',
    };
    for (const [scope, text] of Object.entries(notes)) await a.note(scope, text);
    await a.editPosition(210);
    await a.click(a.button('关闭')); 
    await a.openPanel();
    for (const [scope, text] of Object.entries(notes)) {
      await a.change('.submit-panel select', scope);
      assert.equal(a.q('#target-comment').value, text);
    }
    assert.deepEqual(JSON.parse(a.w.localStorage.getItem('velvet-eclipse-notes')), notes);
    const storage = a.storage();
    assert.equal(a.posts().length, 0);
    a.close();
    const b = await setup({ storage });
    await b.openPanel();
    for (const [scope, text] of Object.entries(notes)) {
      await b.change('.submit-panel select', scope);
      assert.equal(b.q('#target-comment').value, text);
    }
    assert.equal(b.posts().length, 0);
    assert.equal(b.errors.length, 0, b.errors.map(String).join('\n'));
  });

  await test('Explicit Submit freezes one authenticated snapshot with thread/base revision and blocks double clicks', async () => {
    const a = await setup();
    await a.note('background:grand_lobby', 'Keep this submitted background note.');
    await a.note('behavior:player.move', 'Keep this submitted behavior note.');
    await a.note('object:actor.player', '   ');
    await a.editPosition(220);
    const expected = a.snapshot();
    const gate = deferred();
    a.bridge.submitHandler = () => gate.promise;
    const submit = a.submitButton();
    submit.click();
    submit.click();
    a.q('.submit-panel').dispatchEvent(new a.w.Event('submit', { bubbles: true, cancelable: true }));
    await delay(20);assert.equal(a.posts().length,0,'Repeated preview events never POST');
    const confirm=a.button('确认并提交这份载荷');confirm.click();confirm.click();
    await until(() => a.posts().length > 0, 'Explicit confirmation should issue one POST');
    assert.equal(a.posts().length, 1, 'Fast repeated submit events must not duplicate a submission');
    const call = a.posts()[0];
    const payload = call.payload;
    assert.equal(call.url, '/api/submit');
    assert.equal(call.headers['Content-Type'], 'application/json');
    assert.equal(call.headers['X-Workbench-Token'], TOKEN);
    assert.equal(payload.version, 1);
    assert.equal(payload.taskId, 'velvet-eclipse');
    assert.equal(payload.threadId, THREAD);
    assert.equal(payload.baseRevision, 7);
    assert.equal(payload.storeId, STORE);
    assert.equal(payload.sourceBaseline, BASELINE);
    assert.deepEqual(call.pendingAtSend, payload, 'The durable recovery envelope must exist before POST');
    assert.equal(payload.draftRevision, expected.revision);
    assert.match(payload.submissionId, /^[0-9a-f-]{36}$/i);
    assert.deepEqual(payload.snapshot, expected);
    assert.deepEqual(payload.items, [
      { id: 'background:grand_lobby', instruction: 'Keep this submitted background note.' },
      { id: 'behavior:player.move', instruction: 'Keep this submitted behavior note.' },
    ]);
    await until(() => a.submitButton().disabled, 'Submit must disable while the request is pending');
    await a.editPosition(260);
    await a.note('background:grand_lobby', 'Newer unsent background note.');
    assert.deepEqual(JSON.parse(call.body).snapshot, expected, 'Further edits cannot mutate the frozen request');
    assert.equal(JSON.parse(call.body).items[0].instruction, 'Keep this submitted background note.');
    const receipt = record(payload, 'succeeded', 'Mock immutable submission finished');
    a.bridge.status = { ...a.bridge.status, revision: 8, last: receipt };
    gate.resolve(record(payload, 'accepted'));
    await until(() => a.text().includes('Mock immutable submission finished'), 'Terminal result should render');
    await until(() => !a.submitButton().disabled, 'Terminal receipt must release Submit');
    assert.equal(a.snapshot().rooms[0].objects.find(o => o.id === 'entry_arch').x, 260);
    assert.ok(a.text().includes('结果不会自动覆盖草稿'));
    assert.equal(a.q('#target-comment').value, 'Newer unsent background note.');
    assert.equal(a.posts().length, 1);
    assert.equal(a.w.localStorage.getItem(PENDING_KEY), null, 'A confirmed receipt should clear pending recovery data');
    assert.equal(a.errors.length, 0, a.errors.map(String).join('\n'));
  });

  await test('Empty unchanged draft is rejected locally; typed-only changes can be explicitly submitted', async () => {
    const a = await setup();
    await a.openPanel();
    await a.previewAndConfirm();
    assert.equal(a.posts().length, 0);
    assert.ok(a.text().includes('没有净内容变化'));
    assert.equal(a.d.activeElement, a.q('.submit-panel .action-feedback'));
    await a.editPosition(230);
    await a.previewAndConfirm();
    await until(() => a.posts().length === 1, 'Edited draft should submit without requiring a natural-language note');
    assert.deepEqual(a.posts()[0].payload.items, [{ id: 'project', instruction: 'Review the typed edits in this immutable snapshot.' }]);
    await until(() => !a.submitButton().disabled, 'Typed-only submit should finish');
    assert.equal(a.errors.length, 0, a.errors.map(String).join('\n'));
  });

  await test('Offline startup keeps browser editing usable and explicit refresh restores the connection', async () => {
    const a = await setup({ offline: true });
    await a.openPanel();
    assert.equal(a.submitButton().disabled, true);
    assert.ok(a.text().includes('本地桥接未连接'));
    await a.note('project', 'Preserve while bridge is offline.');
    await a.editPosition(240);
    assert.equal(a.posts().length, 0);
    a.bridge.offline = false;
    await a.click(a.button('刷新连接 / 状态'));
    await until(() => !a.submitButton().disabled, 'Refresh should enable Submit after the bridge becomes available');
    await a.change('.submit-panel select','project');
    assert.equal(a.q('#target-comment').value, 'Preserve while bridge is offline.');
    assert.equal(a.snapshot().rooms[0].objects.find(o => o.id === 'entry_arch').x, 240);
    assert.equal(a.posts().length, 0, 'Refresh must never submit');
    assert.equal(a.errors.length, 0, a.errors.map(String).join('\n'));
  });

  await test('Uncertain POST blocks retries until refresh verifies no receipt; refresh never auto-resubmits', async () => {
    const a = await setup();
    await a.note('project', 'Network interruption test.');
    a.bridge.submitHandler = async () => { throw new TypeError('Mock request connection dropped'); };
    await a.previewAndConfirm();
    await until(() => a.text().includes('刷新状态'), 'Delivery error should ask for status reconciliation');
    assert.equal(a.posts().length, 1);
    assert.equal(a.submitButton().disabled, true, 'Unknown delivery must prevent blind retry');
    assert.equal(JSON.parse(a.w.localStorage.getItem(PENDING_KEY)).submissionId, a.posts()[0].payload.submissionId);
    a.q('.submit-panel').dispatchEvent(new a.w.Event('submit', { bubbles: true, cancelable: true }));
    await delay(20);
    assert.equal(a.posts().length, 1);
    await a.click(a.button('刷新连接 / 状态'));
    await until(() => !a.submitButton().disabled, 'A verified no-receipt status should clear transient uncertainty');
    assert.equal(a.calls.filter(c => c.url === '/api/submission/' + a.posts()[0].payload.submissionId).length, 1,
      'Recovery must look up this submission ID instead of guessing from last=null');
    assert.equal(a.w.localStorage.getItem(PENDING_KEY), null);
    assert.equal(a.posts().length, 1, 'Reconciliation must not resend a request automatically');
    assert.equal(a.q('#target-comment').value, 'Network interruption test.');
    assert.equal(a.errors.length, 0, a.errors.map(String).join('\n'));
  });

  await test('A lost POST response recovers the accepted exact-ID receipt without resubmission', async () => {
    const a = await setup();
    await a.note('project', 'Lost response, accepted operation.');
    a.bridge.submitHandler = async call => {
      a.bridge.status = { ...a.bridge.status, revision: 8, last: record(call.payload, 'succeeded', 'Recovered accepted receipt') };
      throw new TypeError('Mock response lost after acceptance');
    };
    await a.previewAndConfirm();
    await until(() => a.submitButton().disabled && a.text().includes('刷新状态'), 'Lost response should require reconciliation');
    const storage = a.storage();
    const status = clone(a.bridge.status);
    const id = a.posts()[0].payload.submissionId;
    a.close();
    const b = await setup({ storage, status });
    await b.openPanel();
    await until(() => b.text().includes('Recovered accepted receipt'), 'Reload should reconcile the persisted submission ID');
    assert.ok(b.calls.some(c => c.url === '/api/submission/' + id));
    assert.equal(b.posts().length, 0);
    assert.equal(b.w.localStorage.getItem(PENDING_KEY), null);
    assert.equal(b.submitButton().disabled, false);
    await b.change('.submit-panel select','project');
    assert.equal(b.q('#target-comment').value, 'Lost response, accepted operation.');
    assert.equal(b.errors.length, 0, b.errors.map(String).join('\n'));
  });

  await test('Changing durable store or thread cannot clear an unresolved envelope; restoring the original mapping can', async () => {
    const a = await setup();
    await a.note('project', 'Keep unresolved delivery tied to its bridge.');
    a.bridge.submitHandler = async () => { throw new TypeError('Mock disconnected delivery'); };
    await a.previewAndConfirm();
    await until(() => a.submitButton().disabled && a.text().includes('刷新状态'), 'Delivery should be unresolved');
    const envelope = a.w.localStorage.getItem(PENDING_KEY);
    for (const changed of [{ storeId: 'different-store', threadId: THREAD }, { storeId: STORE, threadId: 'different-thread' }]) {
      a.bridge.status = { ...a.bridge.status, ...changed };
      await a.click(a.button('刷新连接 / 状态'));
      await until(() => a.text().includes('桥接存储或线程已改变'), 'Mapping change should be explained');
      assert.equal(a.submitButton().disabled, true);
      assert.equal(a.w.localStorage.getItem(PENDING_KEY), envelope, 'Unresolved envelope must survive a mapping mismatch');
      assert.equal(a.calls.filter(c => c.url.startsWith('/api/submission/')).length, 0);
    }
    a.bridge.status = { ...a.bridge.status, storeId: STORE, threadId: THREAD };
    await a.click(a.button('刷新连接 / 状态'));
    await until(() => !a.submitButton().disabled, 'Original store can verify exact-ID nonacceptance');
    assert.equal(a.calls.filter(c => c.url.startsWith('/api/submission/')).length, 1);
    assert.equal(a.w.localStorage.getItem(PENDING_KEY), null);
    assert.equal(a.posts().length, 1, 'Reconciliation must never trigger a second POST');
    assert.equal(a.errors.length, 0, a.errors.map(String).join('\n'));
  });

  await test('Unavailable recovery storage prevents POST instead of losing the immutable recovery envelope', async () => {
    const a = await setup();
    await a.note('project', 'Storage failure should stop the request.');
    const originalSet = a.w.Storage.prototype.setItem;
    a.w.Storage.prototype.setItem = function (key, value) {
      if (key === PENDING_KEY) throw new a.w.DOMException('Mock recovery storage quota exceeded', 'QuotaExceededError');
      return originalSet.call(this, key, value);
    };
    await a.previewAndConfirm();
    await until(() => a.text().includes('Mock recovery storage quota exceeded'), 'Local storage failure should be visible');
    assert.equal(a.posts().length, 0);
    assert.equal(a.q('#target-comment').value, 'Storage failure should stop the request.');
    a.w.Storage.prototype.setItem = originalSet;
    await a.previewAndConfirm();
    await until(() => a.posts().length === 1, 'A new explicit Submit can proceed after storage is available');
    assert.equal(a.errors.length, 0, a.errors.map(String).join('\n'));
  });

  await test('Stale source baseline disables submission until a refreshed adapter match is verified', async () => {
    const a = await setup({ status: { sourceMatchesAdapter: false } });
    await a.note('project', 'Do not write against a stale source baseline.');
    assert.equal(a.submitButton().disabled, true);
    assert.ok(a.q('[role="alert"]').textContent.includes('源文件与已审阅的适配器不一致'));
    assert.equal(a.posts().length, 0);
    a.bridge.status = { ...a.bridge.status, sourceMatchesAdapter: true, sourceBaseline: 'reviewed-new-source-baseline' };
    await a.click(a.button('刷新连接 / 状态'));
    await until(() => !a.submitButton().disabled, 'A verified current source mapping should permit Submit');
    await a.previewAndConfirm();
    await until(() => a.posts().length === 1, 'Explicit Submit should now proceed');
    assert.equal(a.posts()[0].payload.sourceBaseline, 'reviewed-new-source-baseline');
    assert.equal(a.errors.length, 0, a.errors.map(String).join('\n'));
  });

  await test('Polling interruption keeps a known receipt visible and refresh can recover without duplicate POST', async () => {
    const a = await setup();
    await a.note('project', 'Polling interruption test.');
    a.bridge.submitHandler = async call => {
      const receipt = record(call.payload, 'accepted', 'Accepted before connection interruption');
      a.bridge.status = { ...a.bridge.status, revision: 8, last: receipt };
      a.bridge.statusHandler = async () => { throw new TypeError('Mock status connection interrupted'); };
      return receipt;
    };
    await a.previewAndConfirm();
    await until(() => a.text().includes('连接中断'), 'Polling failure should explain uncertainty');
    assert.ok(a.text().includes('Accepted before connection interruption'));
    assert.equal(a.submitButton().disabled, true);
    assert.equal(a.w.localStorage.getItem(PENDING_KEY), null, 'A known accepted receipt is already durable in the bridge');
    a.bridge.statusHandler = null;
    a.bridge.status.last = record(a.posts()[0].payload, 'succeeded', 'Recovered after polling interruption');
    await a.click(a.button('刷新连接 / 状态'));
    await until(() => a.text().includes('Recovered after polling interruption'), 'Refresh should recover the terminal status');
    assert.equal(a.submitButton().disabled, false);
    assert.equal(a.posts().length, 1);
    assert.equal(a.errors.length, 0, a.errors.map(String).join('\n'));
  });

  await test('HTTP conflict reconciles to another-tab receipt and uses its updated base revision only on the next Submit', async () => {
    const a = await setup();
    await a.note('project', 'Conflict remains an unsent note.');
    a.bridge.submitHandler = async () => ({ mockHttpError: true, status: 409, error: 'Another tab submitted first.' });
    await a.previewAndConfirm();
    await until(() => a.text().includes('Another tab submitted first.'), 'HTTP error detail should be shown');
    const previous = { ...a.posts()[0].payload, submissionId: 'other-tab-receipt' };
    a.bridge.status = { ...a.bridge.status, revision: 8, last: record(previous, 'succeeded', 'Other tab completed') };
    await a.click(a.button('刷新连接 / 状态'));
    await until(() => !a.submitButton().disabled, 'A terminal reconciled receipt should permit a reviewed new submit');
    assert.ok(a.text().includes('Other tab completed'));
    assert.equal(a.posts().length, 1);
    a.bridge.submitHandler = null;
    await a.previewAndConfirm();
    await until(() => a.posts().length === 2, 'The next explicit Submit should issue a new request');
    assert.equal(a.posts()[1].payload.baseRevision, 8);
    assert.equal(a.posts()[1].payload.threadId, THREAD);
    assert.notEqual(a.posts()[1].payload.submissionId, a.posts()[0].payload.submissionId);
    assert.equal(a.errors.length, 0, a.errors.map(String).join('\n'));
  });

  await test('Reload restores an active receipt, polls to failure and preserves notes without issuing any POST', async () => {
    const seed = await setup();
    const payload = {
      version: 1, taskId: 'velvet-eclipse', submissionId: 'persisted-active-submission',
      threadId: THREAD, baseRevision: 7, draftRevision: 0, snapshot: seed.snapshot(),
      items: [{ id: 'project', instruction: 'Previously submitted note.' }],
    };
    seed.close();
    const a = await setup({
      storage: { 'velvet-eclipse-notes': JSON.stringify({ project: 'Current local note.' }) },
      status: { mode: 'demo', threadId: THREAD, revision: 8, last: record(payload, 'processing', 'Still processing') },
    });
    await a.openPanel();
    assert.ok(a.text().includes('Still processing'), 'Existing active result should display on reload');
    assert.equal(a.submitButton().disabled, true);
    a.bridge.status.last = record(payload, 'failed', 'Mock processing failed safely');
    await until(() => a.text().includes('Mock processing failed safely'), 'Active status polling should reach failure', 2200);
    assert.equal(a.submitButton().disabled, false);
    await a.change('.submit-panel select','project');
    assert.equal(a.q('#target-comment').value, 'Current local note.');
    assert.equal(a.posts().length, 0);
    const count = a.calls.length;
    await delay(1050);
    assert.equal(a.calls.length, count, 'Terminal failure must stop polling');
    assert.equal(a.errors.length, 0, a.errors.map(String).join('\n'));
  });

  const failed = checks.filter(check => check.status !== 'pass');
  console.log(JSON.stringify({
    type: 'Built React workbench and real domain-script integration in jsdom with mocked fetch',
    checks,
    summary: `${checks.length - failed.length}/${checks.length} passed`,
    limitations: 'No rendered-browser visual/accessibility claim, real network, Codex inference, or source-writeback claim.',
  }, null, 2));
  if (failed.length) process.exitCode = 1;
}

main().catch(error => {
  for (const w of openWindows) w.close();
  console.error(error);
  process.exitCode = 1;
});
