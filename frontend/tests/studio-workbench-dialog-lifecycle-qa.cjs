#!/usr/bin/env node
/* Focused QA for report/proposal dialog focus wrapping and close restoration. */
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const { pathToFileURL } = require('node:url');
let JSDOM;
try { ({ JSDOM } = require('jsdom')); }
catch { console.log('SKIP Studio workbench dialog lifecycle QA: jsdom is unavailable.'); process.exit(0); }

const root = path.resolve(__dirname, '..');
const dom = new JSDOM(fs.readFileSync(path.join(root, 'studio/index.html'), 'utf8'), {
  url: 'http://127.0.0.1:8123/studio/?project=dialog-lifecycle', pretendToBeVisual: true,
});
const { window } = dom;
const saved = { document: global.document, FormData: global.FormData, Option: global.Option, localStorage: global.localStorage };
global.document = window.document;
global.FormData = window.FormData;
global.Option = window.Option;
global.localStorage = window.localStorage;

const setScroll = (x, y) => {
  Object.defineProperty(window, 'scrollX', { configurable: true, value: x });
  Object.defineProperty(window, 'scrollY', { configurable: true, value: y });
};
const scrollCalls = [];
window.scrollTo = (x, y) => { scrollCalls.push([x, y]); setScroll(x, y); };
const tab = (dialog, shiftKey = false) => {
  const event = new window.KeyboardEvent('keydown', { key: 'Tab', shiftKey, bubbles: true, cancelable: true });
  dialog.dispatchEvent(event);
  assert(event.defaultPrevented, `Tab${shiftKey ? ' with Shift' : ''} is intercepted at a dialog boundary`);
};

(async () => {
  const { LegacyWorkbench } = await import(pathToFileURL(path.join(root, 'studio/workbench.js')).href);
  const app = { targetNotes: {}, structuralProposals: [], objectItems: () => [] };
  const wb = new LegacyWorkbench(app);
  wb.persistCurrentNote = () => {};
  wb.refreshReport = () => {};
  wb.bind();

  const body = window.document.body;
  const report = window.document.querySelector('#workbench-report-dialog');
  report.showModal = function () { this.open = true; };
  report.close = function () { this.open = false; };
  const reportOpener = window.document.createElement('button');
  reportOpener.textContent = '打开申报'; body.append(reportOpener);
  body.style.setProperty('overflow', 'auto', 'important');
  setScroll(12, 245); reportOpener.focus();
  wb.openReport();
  assert(report.open, 'the report dialog opens through its shared lifecycle');
  assert.equal(body.style.getPropertyValue('overflow'), 'hidden', 'opening locks body scrolling');
  const reportButtons = [...report.querySelectorAll('button')];
  const reportFirst = reportButtons[0], reportLast = reportButtons.at(-1);
  const hiddenButton = window.document.createElement('button'); hiddenButton.style.display = 'none'; report.append(hiddenButton);
  const disabledButton = window.document.createElement('button'); disabledButton.disabled = true; report.append(disabledButton);
  assert(!wb.dialogFocusableElements(report).includes(hiddenButton), 'hidden controls do not enter the focus loop');
  assert(!wb.dialogFocusableElements(report).includes(disabledButton), 'disabled controls do not enter the focus loop');
  reportLast.focus(); tab(report);
  assert.equal(window.document.activeElement, reportFirst, 'Tab from the last report control wraps to the first');
  reportFirst.focus(); tab(report, true);
  assert.equal(window.document.activeElement, reportLast, 'Shift+Tab from the first report control wraps to the last');
  setScroll(12, 390);
  report.querySelector('[data-workbench-action="close-report"]').click();
  assert(!report.open, 'the report close action closes the dialog');
  assert.equal(window.document.activeElement, reportOpener, 'report close restores focus to the opener');
  assert.equal(body.style.getPropertyValue('overflow'), 'auto', 'report close restores the prior body overflow');
  assert.equal(body.style.getPropertyPriority('overflow'), 'important', 'report close restores the overflow priority');
  assert.deepEqual(scrollCalls.at(-1), [12, 245], 'report close restores the saved scroll position');

  const proposal = window.document.querySelector('#workbench-proposal-dialog');
  proposal.showModal = function () { this.open = true; };
  proposal.close = function () { this.open = false; };
  const proposalOpener = window.document.createElement('button');
  proposalOpener.textContent = '打开提案'; body.append(proposalOpener);
  body.style.setProperty('overflow', 'clip');
  setScroll(7, 510); proposalOpener.focus();
  wb.openProposal('new-scene');
  assert(proposal.open, 'the proposal dialog opens through its shared lifecycle');
  assert.equal(body.style.getPropertyValue('overflow'), 'hidden', 'the proposal dialog locks body scrolling');
  const proposalButtons = [...proposal.querySelectorAll('button')];
  const proposalFirst = proposalButtons[0], proposalLast = proposalButtons.at(-1);
  proposalLast.focus(); tab(proposal);
  assert.equal(window.document.activeElement, proposalFirst, 'Tab from the last proposal control wraps to the first');
  proposalFirst.focus(); tab(proposal, true);
  assert.equal(window.document.activeElement, proposalLast, 'Shift+Tab from the first proposal control wraps to the last');
  proposalOpener.remove(); setScroll(7, 630);
  proposal.dispatchEvent(new window.Event('cancel', { cancelable: true }));
  assert.equal(wb.pendingProposalType, null, 'Escape cancellation clears the pending proposal type');
  proposal.open = false;
  proposal.dispatchEvent(new window.Event('close'));
  assert.equal(window.document.activeElement, window.document.querySelector('#edit-text'), 'native close restores editor focus if the opener was removed');
  assert.equal(body.style.getPropertyValue('overflow'), 'clip', 'native close restores proposal body overflow');
  assert.deepEqual(scrollCalls.at(-1), [7, 510], 'native close restores the proposal scroll position');

  console.log('PASS Studio workbench dialog lifecycle QA: first/last Tab wrapping, hidden/disabled filtering, focus, body overflow, and scroll restoration');
})().catch(error => { console.error(error.stack || error); process.exitCode = 1; }).finally(() => {
  dom.window.close();
  for (const [key, value] of Object.entries(saved)) {
    if (value === undefined) delete global[key]; else global[key] = value;
  }
});
