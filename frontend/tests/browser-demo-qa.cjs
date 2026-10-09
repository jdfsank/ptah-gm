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
    url: 'https://dna-velvet-workbench.mbvs9mqhp8.chatgpt.site/',
    runScripts: 'outside-only',
    pretendToBeVisual: true,
    virtualConsole,
  });
  openWindows.add(dom.window);
  const w = dom.window;
  const d = w.document; w.structuredClone = clone;
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
  await until(() => d.querySelector('.demo-tag') && (d.querySelector('.action-feedback').textContent.includes('演示已就绪') || d.querySelector('.action-feedback').textContent.includes('演示快照') || d.querySelector('.action-feedback').textContent.includes('模拟') || d.querySelector('.action-feedback').textContent.includes('演示验证')), 'Demo should initialize without network');
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

(async()=>{
 const a=await setup();
 assert.equal(a.calls.length,0);assert.match(a.text(),/[未不]发送给 Agent/);
 await a.click(a.button('日间'));assert.equal(a.d.documentElement.dataset.theme,'day');
 await a.note('project','测试：调整场景装饰，不调用模型');
 await a.editPosition(800);const rev=a.snapshot().revision;assert.ok(rev>0);
 const submit=a.submitButton();submit.click();submit.click();await delay(50);assert.ok(a.d.querySelector('.submission-preview'));assert.equal(JSON.parse(a.w.localStorage.getItem('dna-browser-submit-demo-v1')).last,null);const confirm=a.button('确认并提交这份载荷');confirm.click();confirm.click();await until(()=>JSON.parse(a.w.localStorage.getItem('dna-browser-submit-demo-v1')).last!==null,'Explicit confirmation persists receipt',8000);
 await until(()=>a.text().includes('演示快照已保存')||a.text().includes('正在本浏览器模拟')||a.text().includes('演示验证已返回'),'Receipt status is visible',8000);assert.ok(a.submitButton().disabled||a.text().includes('演示验证已返回'));
 const store=JSON.parse(a.w.localStorage.getItem('dna-browser-submit-demo-v1'));assert.equal(Object.keys(store.submissions).length,1);assert.equal(store.last.payload.draftRevision,rev);assert.equal(a.calls.length,0);
 const storage=a.storage();a.close();
 const b=await setup({storage});await b.openPanel();assert.equal(b.d.documentElement.dataset.theme,'day');await b.change('.submit-panel select','project');assert.equal(b.q('textarea').value,'测试：调整场景装饰，不调用模型');
 await until(()=>b.text().includes('演示验证已返回'),'Receipt returns after reload',4500);
 assert.match(b.text(),/未修改 Godot 项目/);assert.equal(Object.keys(JSON.parse(b.w.localStorage.getItem('dna-browser-submit-demo-v1')).submissions).length,1);assert.equal(b.calls.length,0);
 assert.equal(b.errors.length,0);b.close();
 console.log('PASS: hosted demo theme, notes, typed edits, immediate receipt, duplicate-click block, refresh recovery, zero network/model calls');
})().catch(e=>{for(const w of openWindows)w.close();console.error(e);process.exitCode=1});
