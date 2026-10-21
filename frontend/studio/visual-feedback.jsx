import React, { useId, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { flushSync } from 'react-dom';

// Display preferences never enter the command, draft or undo state.
const density = new Map();
const mounted = new Map();
const observers = new WeakMap();
const text = value => value == null ? '未提供' : typeof value === 'object' ? JSON.stringify(value) : String(value);

export function releaseVisuals(container) {
  for (const [host, root] of mounted) {
    if (host === container || container.contains(host)) {
      root.unmount(); mounted.delete(host);
    }
  }
}

function Reference({ reference }) {
  const [failed, setFailed] = useState(false);
  return <figure className="visual-reference">
    {reference.url && !failed && <img src={reference.url} alt={reference.intent || '本轮概念参考'} onError={() => setFailed(true)} />}
    <figcaption>
      <strong>{reference.kind === 'capture' ? '操作员提供的运行画面 · 采集条件未独立验证' : reference.url ? '概念参考 · 不代表运行效果' : '文字视觉要求'}</strong>
      {failed && <p role="status">图片无法读取；采纳文字仍保留，视觉符合尚未验证。</p>}
      <p className="visual-raw">{reference.intent || '采纳用途尚未声明'}</p>
      {reference.kind !== 'capture' && <p>关联目标：{reference.targetLabels?.length ? reference.targetLabels.join('、') : reference.targetObjectIds?.length ? reference.targetObjectIds.join('、') : '本轮项目视觉方向'}</p>}
      {reference.dimensions && <p>{reference.dimensions}</p>}
      {reference.provenance && <p>图片原来源：{reference.provenance}</p>}
      {reference.preserve && <p>保持：{reference.preserve}</p>}
      <p>未知：{reference.unknown || (reference.kind === 'capture' ? '截图不证明连续运动、规则正确或动作手感' : '未声明的玩法、坐标、时长与碰撞不从图片推断')}</p>
    </figcaption>
  </figure>;
}

function Quantity({ item }) {
  const values = [item.before, item.expected].filter(v => typeof v === 'number' && Number.isFinite(v));
  const maximum = Math.max(...values.map(Math.abs), 1);
  const comparable = values.length === 2 && item.comparable === true;
  return <div className="visual-quantity">
    <strong>{item.label}</strong>
    <div>来源值：{text(item.before)} {item.unit || ''}</div>
    <div>{item.expected === undefined ? '数值期望未确认，按原文或待澄清意图处理' : `本轮期望：${text(item.expected)} ${item.unit || ''} · 尚未制作`}</div>
    {comparable && <svg viewBox="0 0 100 12" preserveAspectRatio="none" role="img" aria-label="来源与本轮期望的比例，精确值见文字">
      <rect x="0" y="1" width={Math.abs(item.before) / maximum * 100} height="4" className="visual-before" />
      <rect x="0" y="7" width={Math.abs(item.expected) / maximum * 100} height="4" className="visual-expected" />
    </svg>}
  </div>;
}

function VisualCard({ model, preferenceKey }) {
  const [expanded, setExpanded] = useState(density.get(preferenceKey) === true);
  const detailId = useId();
  return <section className="visual-card" aria-label={model.title}>
    <header><h4>{model.title}</h4><button type="button" className="button quiet" aria-expanded={expanded} aria-controls={detailId}
      onClick={() => { density.set(preferenceKey, !expanded); setExpanded(!expanded); }}>{expanded ? '收起详细' : '展开详细'}</button></header>
    {model.status && <p className="visual-status">{model.status}</p>}
    {model.warning && <p className="notice">{model.warning}</p>}
    {model.rawText != null && <div><strong>用户原文</strong><p className="visual-raw">{model.rawText || '此轮没有补充文字'}</p></div>}
    {model.interpretation && <p>AI 解释：{model.interpretation}</p>}
    <div className="visual-rows">{(model.rows || []).map((row, i) => <div key={i}><strong>{row.label}</strong><span className="visual-raw">{text(row.value)}</span></div>)}</div>
    {!!model.targets?.length && <ul className="visual-targets">{model.targets.map(target => <li key={target.id}>
      {model.onLocate ? <button type="button" className="button quiet" onClick={() => model.onLocate(target.id)}>{target.label || target.id}</button> : <span>{target.label || target.id}</span>}
      {target.scope && <small>此项影响：{target.scope}</small>}
    </li>)}</ul>}
    <div className="visual-reference-grid">{(model.references || []).map((reference, i) => <Reference key={reference.key || reference.url || i} reference={reference} />)}</div>
    <div className="visual-quantities">{(model.quantities || []).map((item, i) => <Quantity key={item.id || i} item={item} />)}</div>
    <div id={detailId} hidden={!expanded} className="visual-details"><dl>{(model.details || []).map((row, i) => <React.Fragment key={i}><dt>{row.label}</dt><dd>{text(row.value)}</dd></React.Fragment>)}</dl></div>
  </section>;
}

export function mountVisual(container, model, preferenceKey = model.title) {
  if (!container) return null;
  const doc = container.ownerDocument;
  if (!observers.has(doc) && doc.defaultView?.MutationObserver) {
    const observer = new doc.defaultView.MutationObserver(() => {
      for (const [host, root] of mounted) {
        if (host.ownerDocument === doc && !host.isConnected) { root.unmount(); mounted.delete(host); }
      }
    });
    observer.observe(doc.documentElement, { childList: true, subtree: true }); observers.set(doc, observer);
  }
  const host = doc.createElement('div'); host.className = 'visual-mount';
  container.append(host);
  // Read-only consumers (including DOM tools) may have a document without a
  // browser window. Keep the original card usable without mounting React there.
  if (typeof window === 'undefined') {
    host.textContent = model.title;
    return host;
  }
  try {
    const root = createRoot(host); mounted.set(host, root);
    flushSync(() => root.render(<VisualCard model={model} preferenceKey={preferenceKey} />));
  } catch {
    mounted.get(host)?.unmount(); mounted.delete(host);
    host.textContent = '视觉卡暂不可用；下方原有内容与操作仍可使用。';
  }
  return host;
}

export function referenceModel(record, projectId) {
  const assets = new Map((record?.assets || []).map(asset => [asset.id, asset]));
  const objects = new Map((record?.currentDocument?.objects || record?.document?.objects || []).map(object => [object.id, object]));
  return (record?.visualReferences || []).map((reference, index) => {
    const asset = assets.get(reference.assetId);
    return { ...reference, key: reference.assetId || `text-${index}`,
      provenance: asset?.generation?.provenance?.source ? `${asset.generation.provenance.projectId} · ${asset.generation.provenance.source.proposalId} r${asset.generation.provenance.source.proposalRevision} · ${asset.generation.provenance.source.feedbackId}` : null,
      targetLabels: (reference.targetObjectIds || []).map(id => objects.get(id)?.name ? `${objects.get(id).name}（${id}）` : id),
      url: reference.assetId && projectId ? `/api/projects/${encodeURIComponent(projectId)}/assets/${encodeURIComponent(reference.assetId)}` : null,
      dimensions: asset ? `实际 ${asset.width ?? '未知'} × ${asset.height ?? '未知'}${asset.generation?.requestedSize ? `；请求 ${asset.generation.requestedSize}` : ''} · ${asset.generation?.model || '用户上传'} · ${asset.size ?? '未知'} 字节` : null };
  });
}
