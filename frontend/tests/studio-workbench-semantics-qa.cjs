#!/usr/bin/env node
/* Focused DOM QA for semantic previews and the source coverage ledger. */
const assert = require('node:assert/strict');
const path = require('node:path');
const { pathToFileURL } = require('node:url');
const { JSDOM } = require('jsdom');

const root = path.resolve(__dirname, '..');
const dom = new JSDOM('<!doctype html><main><div id="preview"></div><div id="coverage"></div></main>', { pretendToBeVisual: true });

(async () => {
  const { renderSemanticPreview, renderSourceCoverage } = await import(pathToFileURL(path.join(root, 'studio/workbench-semantics.js')).href);
  const document = dom.window.document;
  const previewRoot = document.querySelector('#preview');

  const motion = {
    id: 'motion-01', name: '移动目标', fields: [{ id: 'speed', label: '巡航速度', unit: '米/秒', value: 3 }],
    relations: [], workbench: { role: 'behavior', preview: { type: 'motion', driver: '巡逻控制器', speedFieldId: 'speed', stages: [{ label: '巡逻', duration: 4 }] } },
  };
  let section = renderSemanticPreview(previewRoot, motion, { metadata: motion.workbench, objects: [motion], speed: 5, speedField: motion.fields[0], stages: [{ label: '巡逻', duration: 4 }] });
  assert.equal(section.dataset.semanticType, 'motion');
  assert(previewRoot.textContent.includes('巡逻控制器'), 'motion preview names the declared driver');
  assert(previewRoot.textContent.includes('巡航速度') && previewRoot.textContent.includes('5 米/秒'), 'motion preview uses the caller-normalized speed');
  assert(previewRoot.textContent.includes('参数推导：速度 × 时长 = 20 米'), 'motion preview relates normalized speed to declared time');
  assert(previewRoot.textContent.includes('不代表物理运行'), 'motion preview states its browser-demo boundary');

  const response = { id: 'response-01', fields: [], relations: [], workbench: { preview: { type: 'response', trigger: '进入危险区域', stages: [{ label: '受击反应', duration: 0.25 }], recovery: '恢复可操作状态' } } };
  renderSemanticPreview(previewRoot, response, { metadata: response.workbench, objects: [response] });
  assert(previewRoot.textContent.includes('进入危险区域'), 'response preview displays the trigger');
  assert(previewRoot.textContent.includes('受击反应'), 'response preview displays declared reaction stages');
  assert(previewRoot.textContent.includes('恢复可操作状态'), 'response preview displays recovery');

  const interaction = {
    id: 'use-door', name: '开门交互', fields: [], relations: [{ type: 'targets', targetId: 'door' }],
    workbench: { preview: { type: 'interaction', condition: '持有钥匙', result: '门打开' } },
  };
  renderSemanticPreview(previewRoot, interaction, { metadata: interaction.workbench, objects: [interaction, { id: 'door', name: '<门>', kind: 'entity' }] });
  assert(previewRoot.textContent.includes('持有钥匙') && previewRoot.textContent.includes('门打开'), 'interaction preview displays condition and result');
  assert.equal(previewRoot.querySelector('[data-object-id="door"]').dataset.objectId, 'door', 'interaction relation keeps a stable target ID');
  assert.equal(previewRoot.querySelector('script'), null, 'object names render as text');

  const rule = { id: 'rule-01', fields: [], relations: [], workbench: { preview: { type: 'rule', guard: 'energy > 0', fromState: 'idle', toState: 'active' } } };
  renderSemanticPreview(previewRoot, rule, { metadata: rule.workbench, objects: [rule] });
  assert(previewRoot.textContent.includes('energy > 0') && previewRoot.textContent.includes('idle → active'), 'rule preview shows guard and explicit state transition');

  const spawn = {
    id: 'spawn-01', fields: [], relations: [{ type: 'spawns', targetId: 'enemy-def' }],
    workbench: { role: 'spawn', preview: { type: 'spawn', trigger: '回合开始', positionPolicy: '区域边界', cleanup: '回合结束时移除' } },
  };
  renderSemanticPreview(previewRoot, spawn, { metadata: spawn.workbench, objects: [spawn, { id: 'enemy-def', name: '敌人定义', kind: 'entity', workbench: { role: 'definition' } }] });
  assert(previewRoot.textContent.includes('回合开始') && previewRoot.textContent.includes('区域边界') && previewRoot.textContent.includes('回合结束时移除'), 'spawn preview shows trigger, position policy, and cleanup');
  assert(previewRoot.textContent.includes('敌人定义 · enemy-def'), 'spawn preview relates the declared spawned type');

  const transition = { id: 'edge', workbench: { preview: { type: 'transition' } } };
  assert.equal(renderSemanticPreview(previewRoot, transition, { metadata: transition.workbench }), null, 'transition stays in the existing directed-transition section');
  assert.equal(previewRoot.childElementCount, 0, 'transition does not duplicate semantic content');

  const objects = [
    { id: 'mapped-id', name: '有映射对象', kind: 'entity', sourceBindings: ['scripts/enemy.gd'], workbench: { role: 'definition', provenance: { kind: 'fact', sourcePaths: ['resources/enemy.tres'] } } },
    { id: 'inferred-id', name: '推断对象', kind: 'entity', workbench: { role: 'behavior', provenance: { kind: 'inference' } } },
    { id: 'proposal-id', name: '待提案对象', kind: 'rule', workbench: { role: 'system', provenance: { kind: 'proposal' } } },
    { id: 'missing-id', name: '缺映射对象', kind: 'scene', workbench: { role: 'unmapped' } },
  ];
  const coverageRoot = document.querySelector('#coverage');
  const ledger = renderSourceCoverage(coverageRoot, objects);
  assert.equal(ledger.open, false, 'coverage ledger stays collapsed by default');
  const statusFilter = ledger.querySelector('[aria-label="按来源覆盖状态筛选"]');
  const categoryFilter = ledger.querySelector('[aria-label="按对象类别筛选"]');
  const statusFor = id => ledger.querySelector(`[data-object-id="${id}"]`)?.closest('tr')?.dataset.coverageStatus;
  assert.equal(statusFor('mapped-id'), 'mapped');
  assert.equal(statusFor('inferred-id'), 'inference');
  assert.equal(statusFor('proposal-id'), 'proposal');
  assert.equal(statusFor('missing-id'), 'missing');
  assert.deepEqual([...ledger.querySelectorAll('.workbench-coverage-paths li')].map(item => item.textContent), ['scripts/enemy.gd', 'resources/enemy.tres']);
  assert.equal(ledger.querySelector('[data-object-id="mapped-id"]').dataset.objectId, 'mapped-id', 'ledger returns the target by its stable ID');

  statusFilter.value = 'missing'; statusFilter.dispatchEvent(new dom.window.Event('change', { bubbles: true }));
  assert.equal(ledger.querySelectorAll('tbody tr[data-coverage-status]').length, 1, 'status filter selects one coverage category');
  assert.equal(statusFor('missing-id'), 'missing');
  categoryFilter.value = 'scene'; categoryFilter.dispatchEvent(new dom.window.Event('change', { bubbles: true }));
  assert.equal(ledger.querySelector('tbody tr[data-coverage-status]')?.dataset.coverageCategory, 'scene', 'category filter narrows ledger rows');

  dom.window.close();
  console.log('PASS semantic-preview QA: motion, response, interaction, rule, spawn, transition exclusion, and source coverage filters');
})().catch(error => {
  dom.window.close();
  console.error(error.stack || error);
  process.exitCode = 1;
});
