#!/usr/bin/env node
/* Regression for inspector object links nested under the stage's mobile-pane attribute. */
const assert = require('node:assert/strict');
const path = require('node:path');
const { pathToFileURL } = require('node:url');
let JSDOM;
try { ({ JSDOM } = require('jsdom')); }
catch { console.log('SKIP workbench selection click QA: jsdom is unavailable.'); process.exit(0); }

const dom = new JSDOM(`<!doctype html><section id="object-catalog">
  <div id="workbench-mobile-panes"><button type="button" data-mobile-pane="inspect">详情</button></div>
  <div id="workbench-body" data-mobile-pane="stage">
    <main id="workbench-stage"></main>
    <aside id="workbench-inspector"><div id="object-detail">
      <section class="workbench-relations"><button type="button" class="workbench-relation-link" data-object-id="hero-run">使用处</button></section>
      <details class="workbench-coverage-ledger"><button type="button" class="workbench-coverage-target" data-object-id="hero-idle">覆盖目标</button></details>
    </div></aside>
  </div>
</section>`, { url: 'http://127.0.0.1:8123/studio/?project=selection-click' });
global.document = dom.window.document;
global.localStorage = dom.window.localStorage;
global.location = dom.window.location;
global.history = dom.window.history;

(async () => {
  const { LegacyWorkbench } = await import(pathToFileURL(path.join(__dirname, '../studio/workbench.js')).href);
  const objects = [{ id: 'hero-art' }, { id: 'hero-run' }, { id: 'hero-idle' }];
  const selected = [];
  const app = {
    projectId: 'selection-click', selectedObjectId: 'hero-art', targetNotes: {}, structuralProposals: [],
    objectItems: () => objects,
    selectObject(id) { selected.push(id); this.selectedObjectId = id; },
  };
  const wb = new LegacyWorkbench(app);
  wb.bind();

  document.querySelector('.workbench-relation-link').click();
  assert.equal(app.selectedObjectId, 'hero-run', 'a real inspector relation click selects its stable target');
  assert.deepEqual(selected, ['hero-run']);

  document.querySelector('.workbench-coverage-target').click();
  assert.equal(app.selectedObjectId, 'hero-idle', 'a real source-coverage click selects its stable target');
  assert.deepEqual(selected, ['hero-run', 'hero-idle']);

  document.querySelector('#workbench-mobile-panes button[data-mobile-pane="inspect"]').click();
  assert.equal(document.querySelector('#workbench-body').dataset.mobilePane, 'inspect', 'the actual pane button still switches the mobile view');

  wb.stopPreview();
  dom.window.close();
  console.log('PASS workbench selection click QA: inspector relation and coverage clicks select targets; pane button still switches view');
})().catch(error => {
  dom.window.close();
  console.error(error.stack || error);
  process.exitCode = 1;
});
