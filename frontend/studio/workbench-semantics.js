const ROLE_LABELS = {
  definition: '共享定义', scene: '场景', instance: '场景实例', entry: '入口 / 定位', spawn: '生成规则',
  behavior: '行为', state: '状态', resource: '资源', transition: '场景过渡', preset: '配置预设', system: '系统',
};

const SEMANTIC_LABELS = {
  motion: '连续运动', response: '被动响应', interaction: '交互', rule: '规则', spawn: '生成规则',
};

const COVERAGE_LABELS = {
  mapped: '有映射', inference: '推断', proposal: '待提案', missing: '缺映射',
};

const hasValue = value => value !== undefined && value !== null && value !== '';
const own = (value, key) => value != null && Object.hasOwn(value, key);

function node(document, tag, className = '', text = null) {
  const result = document.createElement(tag);
  if (className) result.className = className;
  if (text !== null && text !== undefined) result.textContent = String(text);
  return result;
}

function option(document, label, value) {
  const result = node(document, 'option', '', label);
  result.value = value;
  return result;
}

function formatValue(value) {
  if (!hasValue(value)) return '未声明';
  if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') return String(value);
  if (Array.isArray(value)) return value.map(formatValue).join('、');
  if (typeof value === 'object') {
    try { return JSON.stringify(value); } catch { return '[无法显示的已声明值]'; }
  }
  return String(value);
}

function fieldsOf(object) {
  return Array.isArray(object?.fields) ? object.fields.filter(field => field && typeof field === 'object') : [];
}

function fieldById(fields, id) {
  return id == null ? null : fields.find(field => field.id === id || field.key === id) || null;
}

function findNamedField(fields, keys) {
  const names = new Set(keys.map(value => String(value).toLowerCase()));
  return fields.find(field => [field.id, field.key, field.name].some(value => value != null && names.has(String(value).toLowerCase()))) || null;
}

function declaredValue(object, metadata, preview, keys) {
  const fields = fieldsOf(object);
  for (const key of keys) {
    const fieldId = preview?.[`${key}FieldId`] ?? metadata?.[`${key}FieldId`];
    const referencedField = fieldById(fields, fieldId);
    if (referencedField && hasValue(referencedField.value)) {
      return { value: referencedField.value, field: referencedField, declared: true };
    }
    if (own(preview, key) && hasValue(preview[key])) return { value: preview[key], field: referencedField, declared: true };
    if (own(metadata, key) && hasValue(metadata[key])) return { value: metadata[key], field: referencedField, declared: true };
    const field = referencedField || findNamedField(fields, [key]);
    if (field && hasValue(field.value)) return { value: field.value, field, declared: true };
  }
  return { value: undefined, field: null, declared: false };
}

function fieldLabel(field, fallback) {
  return field?.label || field?.name || fallback;
}

function appendDefinitionRow(document, list, label, value, suffix = '') {
  const term = node(document, 'dt', '', label);
  const detail = node(document, 'dd', '', `${formatValue(value)}${hasValue(value) ? suffix : ''}`);
  list.append(term, detail);
}

function semanticSection(root, type) {
  const document = root.ownerDocument || globalThis.document;
  const section = node(document, 'section', 'workbench-semantic-preview');
  section.dataset.semanticType = type;
  section.append(node(document, 'h4', '', `${SEMANTIC_LABELS[type]}关系`));
  return section;
}

function appendStages(document, section, stages, { motionSpeed = null, speedUnit = '' } = {}) {
  const heading = node(document, 'h5', '', '已声明阶段');
  section.append(heading);
  if (!stages.length) {
    section.append(node(document, 'p', 'muted workbench-semantic-missing', '阶段：未声明。'));
    return;
  }
  const list = node(document, 'ol', 'workbench-semantic-stages');
  for (const [index, stage] of stages.entries()) {
    const item = node(document, 'li', '');
    const title = hasValue(stage?.label) ? stage.label : `阶段 ${index + 1}`;
    item.append(node(document, 'b', '', title));
    const duration = stage?.duration;
    const numericDuration = typeof duration === 'number' ? duration : (typeof duration === 'string' && duration.trim() ? Number(duration) : NaN);
    const hasDuration = Number.isFinite(numericDuration) && numericDuration >= 0;
    item.append(node(document, 'span', 'workbench-semantic-duration', hasDuration ? `时长：${formatValue(duration)} 秒` : '时长：未提供'));
    if (hasValue(stage?.effect)) item.append(node(document, 'span', 'workbench-semantic-effect', `效果：${formatValue(stage.effect)}`));
    if (hasDuration && typeof motionSpeed === 'number' && Number.isFinite(motionSpeed)) {
      const derived = motionSpeed * numericDuration;
      const unitMatch = String(speedUnit || '').match(/^\s*(.*?)\s*(?:\/|每)\s*(?:秒|s|sec|second|seconds)\s*$/i);
      const distanceUnit = unitMatch?.[1]?.trim();
      item.append(node(document, 'small', 'workbench-semantic-derived', `参数推导：速度 × 时长 = ${formatValue(derived)}${distanceUnit ? ` ${distanceUnit}` : ''}`));
    }
    list.append(item);
  }
  section.append(list);
}

function directRelations(object, objects) {
  const knownObjects = new Map((Array.isArray(objects) ? objects : []).filter(item => item?.id != null).map(item => [item.id, item]));
  return (Array.isArray(object?.relations) ? object.relations : []).flatMap(relation => {
    if (!relation || typeof relation !== 'object') return [];
    const rawTarget = relation.targetId ?? relation.target;
    const targetId = rawTarget && typeof rawTarget === 'object' ? rawTarget.id : rawTarget;
    if (!hasValue(targetId)) return [];
    return [{ relation, targetId: String(targetId), target: knownObjects.get(String(targetId)) || null }];
  });
}

function appendTargets(document, section, object, objects, declaredTargets = []) {
  const targets = [];
  const seen = new Set();
  for (const item of directRelations(object, objects)) {
    const key = `${item.relation.type || ''}\u0000${item.targetId}`;
    if (!seen.has(key)) { seen.add(key); targets.push(item); }
  }
  const declaredList = Array.isArray(declaredTargets) ? declaredTargets : (hasValue(declaredTargets) ? [declaredTargets] : []);
  for (const value of declaredList) {
    const rawTarget = typeof value === 'string' ? value : value?.targetId ?? value?.id ?? value?.target;
    const targetId = rawTarget && typeof rawTarget === 'object' ? rawTarget.id : rawTarget;
    if (!hasValue(targetId)) continue;
    const relationType = typeof value === 'object' ? value.type || value.relation || '' : '';
    const key = `${relationType}\u0000${targetId}`;
    if (seen.has(key)) continue;
    seen.add(key);
    const target = (Array.isArray(objects) ? objects : []).find(item => item?.id === targetId) || null;
    targets.push({ relation: { type: relationType }, targetId: String(targetId), target });
  }

  section.append(node(document, 'h5', '', '相关目标'));
  if (!targets.length) {
    section.append(node(document, 'p', 'muted workbench-semantic-missing', '相关目标：未声明。'));
    return;
  }
  const list = node(document, 'ul', 'workbench-semantic-targets');
  for (const { relation, targetId, target } of targets) {
    const item = node(document, 'li', '');
    const relationLabel = hasValue(relation.type) ? `${formatValue(relation.type)} · ` : '';
    const targetName = target?.name || target?.label || targetId;
    const button = node(document, 'button', 'text-link workbench-semantic-target', `${relationLabel}${targetName} · ${targetId}`);
    button.type = 'button';
    button.dataset.objectId = targetId;
    item.append(button);
    if (target) {
      const targetMetadata = target.workbench && typeof target.workbench === 'object' ? target.workbench : {};
      const objectType = targetMetadata.role || target.role || target.kind;
      if (hasValue(objectType)) item.append(node(document, 'small', 'muted', `类型：${ROLE_LABELS[objectType] || objectType}`));
    }
    list.append(item);
  }
  section.append(list);
}

function appendStagesAndMissing(section, document, stages, options = {}) {
  appendStages(document, section, stages, options);
}

/**
 * Render an explicit, browser-side semantic preview into a dedicated mount node.
 * `speed` may be supplied by the caller after it resolves published and draft field values.
 * Transition previews are intentionally left to the workbench's directed-transition section.
 */
export function renderSemanticPreview(root, object, { metadata = object?.workbench || {}, objects = [], speed, speedField = null, stages } = {}) {
  if (!root) return null;
  root.replaceChildren();
  if (!object || !metadata || typeof metadata !== 'object') return null;
  const preview = metadata.preview && typeof metadata.preview === 'object' ? metadata.preview : {};
  const type = String(preview.type || (metadata.role === 'spawn' ? 'spawn' : '')).toLowerCase();
  if (!type || type === 'transition' || !Object.hasOwn(SEMANTIC_LABELS, type)) return null;

  const document = root.ownerDocument || globalThis.document;
  const section = semanticSection(root, type);
  const fields = fieldsOf(object);
  const stageList = Array.isArray(stages) ? stages : (Array.isArray(preview.stages) ? preview.stages : []);
  const details = node(document, 'dl', 'workbench-semantic-facts');

  if (type === 'motion') {
    const driver = declaredValue(object, metadata, preview, ['driver']);
    const declaredSpeed = declaredValue(object, metadata, preview, ['speed']);
    const normalizedSpeed = typeof speed === 'number' && Number.isFinite(speed) ? speed : undefined;
    const shownSpeed = speed === undefined ? declaredSpeed.value : normalizedSpeed;
    const resolvedSpeedField = speedField || declaredSpeed.field || fieldById(fields, preview.speedFieldId ?? metadata.speedFieldId);
    const speedUnit = resolvedSpeedField?.unit || resolvedSpeedField?.units || '';
    appendDefinitionRow(document, details, '驱动', driver.value);
    appendDefinitionRow(document, details, fieldLabel(resolvedSpeedField, '速度'), shownSpeed, hasValue(shownSpeed) && speedUnit ? ` ${speedUnit}` : '');
    appendDefinitionRow(document, details, '运动关系', '速度 × 时间 → 参数推导位移');
    section.append(details);
    appendStagesAndMissing(section, document, stageList, { motionSpeed: normalizedSpeed ?? null, speedUnit });
    section.append(node(document, 'p', 'muted workbench-semantic-note', '参数推导演示，使用调用方归一化速度和已声明阶段时长；不代表物理运行或引擎播放。'));
  } else if (type === 'response') {
    const trigger = declaredValue(object, metadata, preview, ['trigger', 'condition']);
    const reaction = declaredValue(object, metadata, preview, ['reaction']);
    const recovery = declaredValue(object, metadata, preview, ['recovery', 'cleanup']);
    appendDefinitionRow(document, details, '触发', trigger.value);
    appendDefinitionRow(document, details, '反应', reaction.value);
    appendDefinitionRow(document, details, '恢复', recovery.value);
    section.append(details);
    appendStagesAndMissing(section, document, stageList);
    section.append(node(document, 'p', 'muted workbench-semantic-note', '阶段只展示当前快照声明的响应过程。'));
  } else if (type === 'interaction') {
    const condition = declaredValue(object, metadata, preview, ['condition', 'guard']);
    const result = declaredValue(object, metadata, preview, ['result', 'outcome', 'effect']);
    appendDefinitionRow(document, details, '条件', condition.value);
    appendDefinitionRow(document, details, '结果', result.value);
    section.append(details);
    appendTargets(document, section, object, objects, preview.targets);
  } else if (type === 'rule') {
    const guard = declaredValue(object, metadata, preview, ['guard', 'condition']);
    const fromState = declaredValue(object, metadata, preview, ['fromState', 'from']);
    const toState = declaredValue(object, metadata, preview, ['toState', 'to']);
    appendDefinitionRow(document, details, '守卫条件', guard.value);
    section.append(details);
    section.append(node(document, 'h5', '', '状态转换'));
    if (fromState.declared || toState.declared) {
      section.append(node(document, 'p', 'workbench-semantic-transition', `${formatValue(fromState.value)} → ${formatValue(toState.value)}`));
    } else {
      const relations = directRelations(object, objects).filter(item => /state|transition/i.test(String(item.relation.type || '')));
      if (relations.length) {
        const list = node(document, 'ul', 'workbench-semantic-targets');
        for (const item of relations) {
          const row = node(document, 'li', '');
          const button = node(document, 'button', 'text-link workbench-semantic-target', `${formatValue(item.relation.type)} · ${item.target?.name || item.target?.label || item.targetId} · ${item.targetId}`);
          button.type = 'button'; button.dataset.objectId = item.targetId; row.append(button); list.append(row);
        }
        section.append(list);
      } else {
        section.append(node(document, 'p', 'muted workbench-semantic-missing', '状态转换：未声明。'));
      }
    }
  } else if (type === 'spawn') {
    const trigger = declaredValue(object, metadata, preview, ['trigger', 'condition', 'spawnCondition']);
    const position = declaredValue(object, metadata, preview, ['positionPolicy', 'positionStrategy']);
    const cleanup = declaredValue(object, metadata, preview, ['cleanup']);
    const lifecycle = declaredValue(object, metadata, preview, ['lifecycle']);
    appendDefinitionRow(document, details, '触发条件', trigger.value);
    appendDefinitionRow(document, details, '位置策略', position.value);
    appendDefinitionRow(document, details, '清理', cleanup.value);
    if (!cleanup.declared && lifecycle.declared) appendDefinitionRow(document, details, '生命周期', lifecycle.value);
    section.append(details);
    appendTargets(document, section, object, objects, preview.targets);
  }

  root.append(section);
  return section;
}

function declaredPaths(object, metadata) {
  const paths = [];
  const add = value => {
    if (typeof value === 'string' && value.trim()) paths.push(value.trim());
    else if (value && typeof value === 'object' && typeof value.path === 'string' && value.path.trim()) paths.push(value.path.trim());
  };
  const addMany = value => { if (Array.isArray(value)) value.forEach(add); else add(value); };
  addMany(object?.sourceBindings);
  addMany(metadata?.sourceBindings);
  addMany(metadata?.sourcePaths);
  addMany(metadata?.provenance?.sourcePaths);
  for (const field of fieldsOf(object)) {
    addMany(field.sourceBindings);
    addMany(field.sourcePaths);
    add(field.sourcePath);
  }
  for (const relation of Array.isArray(object?.relations) ? object.relations : []) {
    addMany(relation?.sourceBindings);
    addMany(relation?.sourcePaths);
    add(relation?.sourcePath);
  }
  return [...new Set(paths)];
}

function categoryFor(object, metadata) {
  const role = metadata?.role || object?.role;
  if (role && role !== 'unmapped' && Object.hasOwn(ROLE_LABELS, role)) return { value: role, label: ROLE_LABELS[role] };
  if (role && role !== 'unmapped') return { value: String(role), label: `未映射 · ${role}` };
  if (object?.kind) return { value: String(object.kind), label: `未映射 · ${object.kind}` };
  return { value: 'unmapped', label: '未映射' };
}

function coverageStatus(metadata, paths) {
  const kind = metadata?.provenance?.kind;
  if (kind === 'inference') return 'inference';
  if (kind === 'proposal') return 'proposal';
  return paths.length ? 'mapped' : 'missing';
}

function coverageRows(objects, metadataFor) {
  return (Array.isArray(objects) ? objects : []).filter(object => object && hasValue(object.id)).map(object => {
    const metadata = metadataFor(object) || {};
    const paths = declaredPaths(object, metadata);
    const category = categoryFor(object, metadata);
    const status = coverageStatus(metadata, paths);
    return { object, metadata, paths, category, status };
  });
}

/**
 * Render a collapsed, filterable source-coverage ledger. Target buttons use the
 * workbench's existing `data-object-id` selection event and retain stable IDs.
 */
export function renderSourceCoverage(root, objects, { metadataFor = object => object?.workbench || {} } = {}) {
  if (!root) return null;
  root.replaceChildren();
  const document = root.ownerDocument || globalThis.document;
  const rows = coverageRows(objects, metadataFor);
  const details = node(document, 'details', 'workbench-coverage-ledger');
  details.append(node(document, 'summary', '', `来源覆盖台账 · ${rows.length} 个目标`));

  if (!rows.length) {
    details.append(node(document, 'p', 'muted', '当前快照没有可列出的稳定对象目标。'));
    root.append(details);
    return details;
  }

  const filters = node(document, 'div', 'workbench-coverage-filters');
  const statusLabel = node(document, 'label', '', '覆盖状态');
  const statusSelect = node(document, 'select', '');
  statusSelect.setAttribute('aria-label', '按来源覆盖状态筛选');
  statusSelect.append(option(document, '全部状态', 'all'));
  for (const [value, label] of Object.entries(COVERAGE_LABELS)) statusSelect.append(option(document, label, value));
  statusLabel.append(statusSelect);

  const categories = [...new Map(rows.map(row => [row.category.value, row.category.label])).entries()]
    .sort((left, right) => left[1].localeCompare(right[1], 'zh-CN'));
  const categoryLabel = node(document, 'label', '', '对象类别');
  const categorySelect = node(document, 'select', '');
  categorySelect.setAttribute('aria-label', '按对象类别筛选');
  categorySelect.append(option(document, '全部类别', 'all'));
  for (const [value, label] of categories) categorySelect.append(option(document, label, value));
  categoryLabel.append(categorySelect);
  filters.append(statusLabel, categoryLabel);

  const count = node(document, 'p', 'muted workbench-coverage-count', '');
  const table = node(document, 'table', 'workbench-coverage-table');
  const head = node(document, 'thead', '');
  const headerRow = node(document, 'tr', '');
  for (const title of ['稳定目标', '类别', '覆盖', '来源路径']) headerRow.append(node(document, 'th', '', title));
  head.append(headerRow);
  const body = node(document, 'tbody', '');
  table.append(head, body);

  const renderRows = () => {
    const status = statusSelect.value;
    const category = categorySelect.value;
    const visible = rows.filter(row => (status === 'all' || row.status === status) && (category === 'all' || row.category.value === category));
    count.textContent = `显示 ${visible.length} / ${rows.length} 个目标`;
    body.replaceChildren();
    if (!visible.length) {
      const empty = node(document, 'tr', 'workbench-coverage-empty');
      const cell = node(document, 'td', '', '当前筛选没有目标。'); cell.colSpan = 4; empty.append(cell); body.append(empty); return;
    }
    for (const row of visible) {
      const tr = node(document, 'tr', '');
      tr.dataset.coverageStatus = row.status;
      tr.dataset.coverageCategory = row.category.value;
      const targetCell = node(document, 'td', 'workbench-coverage-target-cell');
      const target = node(document, 'button', 'text-link workbench-coverage-target', row.object.name || row.object.label || row.object.id);
      target.type = 'button'; target.dataset.objectId = String(row.object.id);
      targetCell.append(target, node(document, 'small', 'muted', String(row.object.id)));
      tr.append(targetCell, node(document, 'td', '', row.category.label));
      tr.append(node(document, 'td', `workbench-coverage-status ${row.status}`, COVERAGE_LABELS[row.status]));
      const pathCell = node(document, 'td', 'workbench-coverage-path-cell');
      if (!row.paths.length) pathCell.append(node(document, 'span', 'muted', '未提供来源路径'));
      else {
        const paths = node(document, 'ul', 'workbench-coverage-paths');
        for (const path of row.paths) paths.append(node(document, 'li', '', path));
        pathCell.append(paths);
      }
      tr.append(pathCell);
      body.append(tr);
    }
  };
  statusSelect.addEventListener('change', renderRows);
  categorySelect.addEventListener('change', renderRows);
  renderRows();

  details.append(filters, count, table);
  root.append(details);
  return details;
}
