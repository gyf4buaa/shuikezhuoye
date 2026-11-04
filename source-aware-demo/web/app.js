'use strict';

const $ = (id) => document.getElementById(id);

const KIND_LABELS = {
  'code-key': '代码 · Key 引用',
  'code-literal': '代码 · 同文本字面量',
  'string-table': '字符串表',
};
const CONFIDENCE_LABELS = { high: '高', medium: '中', low: '低', none: '无' };
const LOCALE_FALLBACK = [{ code: 'pt-BR', name: 'Brazilian Portuguese' }];

const state = {
  health: null,
  strings: [],
  selectedKey: null,
  locale: 'pt-BR',
  evidence: null,
  evidenceController: null,
  filter: '',
  comparing: false,
};

document.addEventListener('DOMContentLoaded', init);

async function init() {
  bindEvents();
  try {
    const [health, stringsPayload] = await Promise.all([
      fetchJSON('/api/health'),
      fetchJSON('/api/strings'),
    ]);
    state.health = health;
    state.strings = stringsPayload.strings || [];
    renderModel();
    renderLocales(stringsPayload.target_locales || health.target_locales || LOCALE_FALLBACK);
    renderStringList();
    const wanted = new URLSearchParams(location.search).get('key');
    const initial =
      state.strings.find((item) => item.key === wanted) ||
      state.strings.find((item) => item.key === 'ui.leaderboard.rank_column') ||
      state.strings[0];
    if (!initial) {
      showFatal('字符串表为空。');
      return;
    }
    await selectKey(initial.key, false);
  } catch (error) {
    showFatal(error.message || String(error));
  }
}

function bindEvents() {
  $('filter').addEventListener('input', (event) => {
    state.filter = event.target.value.trim().toLowerCase();
    renderStringList();
  });
  $('run-compare').addEventListener('click', runCompare);
}

async function fetchJSON(url, options) {
  const response = await fetch(url, {
    headers: { Accept: 'application/json' },
    ...(options || {}),
  });
  let payload = null;
  try {
    payload = await response.json();
  } catch (error) {
    payload = null;
  }
  if (!response.ok) {
    const message = (payload && (payload.message || payload.error)) || `HTTP ${response.status}`;
    const failure = new Error(message);
    failure.status = response.status;
    failure.payload = payload;
    throw failure;
  }
  return payload;
}

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined && text !== null) node.textContent = String(text);
  return node;
}

function badge(text, className) {
  return el('span', `badge ${className}`, text);
}

function configured() {
  return Boolean(state.health && state.health.model && state.health.model.configured);
}

function renderModel() {
  const node = $('model-badge');
  const model = state.health.model || {};
  node.className = 'badge ' + (configured() ? 'badge-live' : 'badge-offline');
  node.textContent = configured()
    ? `LIVE 可用 · ${model.model || '已配置模型'}`
    : '检索模式 · 未调用模型';

  const banner = $('offline-banner');
  if (configured()) {
    banner.hidden = true;
  } else {
    banner.hidden = false;
    banner.className = 'banner banner-warn';
    banner.textContent =
      '未配置 SOURCEAWARE_API_KEY：当前仅展示源码检索与证据，未调用任何模型，页面不会显示 AI 译文。';
  }

  const note = $('compare-note');
  const button = $('run-compare');
  if (configured()) {
    note.textContent =
      `已配置 ${model.model || '模型'}。点击按钮会用同一个模型、同一组参数真实调用两次：A 只给文本，B 给源文与检索证据；界面会把结果标为 LIVE。`;
    button.disabled = false;
    button.textContent = '运行同模型对照翻译（真实调用）';
  } else {
    note.textContent =
      '未配置 API Key：不调用模型，也不会用示意译文冒充结果。启用方式：在启动服务的终端执行 export SOURCEAWARE_API_KEY=...（变量只保存在服务进程，不进入浏览器）。';
    button.disabled = true;
    button.textContent = '未配置 API Key · 仅检索演示';
  }
  resetCompare();
}

function renderLocales(locales) {
  const select = $('locale');
  select.replaceChildren();
  const list = Array.isArray(locales) && locales.length ? locales : LOCALE_FALLBACK;
  for (const item of list) {
    const option = el('option', null, `${item.code} — ${item.name}`);
    option.value = item.code;
    select.append(option);
  }
  select.value = 'pt-BR';
  state.locale = select.value || list[0].code;
  select.addEventListener('change', () => {
    state.locale = select.value;
    resetCompare();
  });
}

function recordFor(key) {
  return state.strings.find((item) => item.key === key) || null;
}

function renderStringList() {
  const list = $('string-list');
  list.replaceChildren();
  const query = state.filter;
  const filtered = state.strings.filter((item) => {
    if (!query) return true;
    return (
      item.key.toLowerCase().includes(query) ||
      item.source.toLowerCase().includes(query)
    );
  });
  $('string-count').textContent = `${filtered.length} / ${state.strings.length}`;
  if (!filtered.length) {
    list.append(el('p', 'empty', '没有匹配的 Key。'));
    return;
  }
  for (const item of filtered) {
    const button = el('button', 'string-item');
    button.type = 'button';
    button.setAttribute('role', 'option');
    button.setAttribute('aria-selected', item.key === state.selectedKey ? 'true' : 'false');
    button.dataset.key = item.key;
    button.append(el('span', 'key', item.key));
    button.append(el('span', 'source', item.source));
    const meta = el('span', 'meta');
    if (item.shared_with && item.shared_with.length) {
      meta.append(el('span', 'mini-badge shared', `同文本 ×${item.shared_with.length + 1}`));
    }
    if (meta.childNodes.length) button.append(meta);
    button.addEventListener('click', () => selectKey(item.key, true));
    list.append(button);
  }
}

async function selectKey(key, updateUrl) {
  const record = recordFor(key);
  if (!record) return;
  state.selectedKey = key;
  state.evidence = null;
  resetCompare();
  renderStringList();

  $('selected-key').textContent = record.key;
  $('source-text').textContent = record.source;
  const shared = record.shared_with || [];
  $('shared-keys').textContent = shared.length
    ? `同文本还属于：${shared.map((item) => `“${item}”`).join('、')}。字面匹配可能指向其他 Key，见下方“同文本候选”。`
    : '该源文本在字符串表中没有其他同文本 Key。';
  $('shared-note').hidden = !shared.length;
  $('shared-note').textContent = shared.length
    ? `当前源文本 “${record.source}” 同时属于 ${shared.length + 1} 个 Key：${[record.key, ...shared].join(' / ')}`
    : '';

  $('evidence-count').textContent = '—';
  $('search-stats').textContent = '正在读取 demo_project 并检索…';
  $('evidence-list').replaceChildren(el('p', 'empty', '检索中…'));

  if (updateUrl) {
    history.replaceState(null, '', `${location.pathname}?key=${encodeURIComponent(key)}`);
  }

  if (state.evidenceController) state.evidenceController.abort();
  const controller = new AbortController();
  state.evidenceController = controller;
  try {
    const payload = await fetchJSON(`/api/evidence?key=${encodeURIComponent(key)}`, {
      signal: controller.signal,
    });
    if (state.selectedKey !== key) return;
    state.evidence = payload;
    renderEvidence(payload);
  } catch (error) {
    if (error.name === 'AbortError') return;
    if (state.selectedKey !== key) return;
    $('search-stats').textContent = '';
    $('evidence-list').replaceChildren();
    const banner = el('div', 'banner banner-error', `检索失败：${error.message || error}`);
    $('evidence-list').append(banner);
  }
}

function renderEvidence(payload) {
  const counts = payload.counts || {};
  const scope = payload.scope || {};
  const stats = [
    `${counts.total || 0} 条证据`,
    `直接 Key 引用 ${counts.code_key || 0}`,
    `同文本候选 ${counts.code_literal || 0}`,
    `字符串表 ${counts.string_table || 0}`,
    `扫描 ${scope.files_scanned || 0} 个文件 / ${scope.lines_scanned || 0} 行`,
    `${payload.elapsed_ms || 0} ms`,
  ];
  if (payload.truncated) stats.push('结果已截断');
  $('search-stats').textContent = stats.join(' · ');
  $('evidence-count').textContent = `${counts.total || 0} 条`;

  const list = $('evidence-list');
  list.replaceChildren();
  if (payload.note) {
    const banner = el('div', 'banner banner-info', payload.note);
    list.append(banner);
  }
  if (!payload.evidence || !payload.evidence.length) {
    list.append(el('p', 'empty', '没有找到引用。检索器不会编造证据。'));
    return;
  }
  for (const evidence of payload.evidence) {
    list.append(renderEvidenceCard(evidence));
  }
}

function renderEvidenceCard(evidence) {
  const card = el('article', `evidence-card kind-${evidence.kind}`);
  const head = el('div', 'evidence-head');
  const kindText = KIND_LABELS[evidence.kind] || evidence.kind;
  head.append(el('span', `kind-label ${evidence.kind}`, kindText));
  head.append(el('span', 'path', `${evidence.path}:${evidence.line}`));
  head.append(el('span', 'line-no', `列 ${evidence.column}`));
  const symbol = evidence.symbol || {};
  if (symbol.class) {
    head.append(el('span', 'symbol', symbol.member ? `${symbol.class}.${symbol.member}` : symbol.class));
  }
  head.append(el('span', 'spacer'));
  let directText = evidence.direct ? '直接引用所选 Key' : '同文本候选';
  if (evidence.kind === 'string-table' && evidence.direct) directText = '同 Key 表定义';
  head.append(el('span', `direct-label ${evidence.direct ? 'yes' : 'no'}`, directText));
  card.append(head);

  const snippet = el('pre', 'snippet');
  for (const line of evidence.snippet || []) {
    const row = el('div', 'code-line' + (line.match ? ' match' : ''));
    row.append(el('span', 'ln', line.line));
    row.append(el('span', 'code-text', line.text));
    snippet.append(row);
  }
  card.append(snippet);

  const inference = evidence.inference || {};
  const box = el('div', 'inference');
  const inferenceHead = el('div', 'inference-head');
  inferenceHead.append(el('span', 'inference-title', '推断 · 确定性启发式'));
  const confidence = inference.confidence || 'none';
  inferenceHead.append(
    badge(`置信度 ${CONFIDENCE_LABELS[confidence] || confidence}`, `badge-${confidence}`)
  );
  box.append(inferenceHead);
  box.append(el('p', null, inference.summary || '无推断。'));
  if (inference.signals && inference.signals.length) {
    const chips = el('div', 'chips');
    for (const signal of inference.signals) chips.append(el('span', 'chip', signal));
    box.append(chips);
  }
  if (inference.needs_human) {
    box.append(el('p', 'needs-human', '需人工确认：该条证据不是充分语义结论。'));
  }
  card.append(box);
  return card;
}

function renderIdleCards() {
  const configuredNow = configured();
  renderResultCard($('baseline-card'), {
    title: 'A · 只给文本',
    badgeText: configuredNow ? '尚未运行' : '未调用模型',
    badgeClass: configuredNow ? 'badge-muted' : 'badge-offline',
    empty: configuredNow
      ? '点击上方按钮后才会调用同一模型。'
      : '未调用模型，因此没有译文。',
  });
  renderResultCard($('contextual-card'), {
    title: 'B · 源文 + 检索证据',
    badgeText: configuredNow ? '尚未运行' : '未调用模型',
    badgeClass: configuredNow ? 'badge-muted' : 'badge-offline',
    empty: configuredNow
      ? '点击上方按钮后才会调用同一模型。'
      : '未调用模型，因此没有译文。',
  });
}

function resetCompare() {
  if (state.comparing) return;
  const status = $('compare-status');
  status.className = 'compare-status';
  status.textContent = '';
  renderIdleCards();
}

function renderResultCard(card, data) {
  card.className = 'result-card' + (data.live ? ' live' : '');
  card.replaceChildren();
  const head = el('div', 'result-head');
  head.append(el('h3', null, data.title));
  head.append(badge(data.badgeText, data.badgeClass));
  card.append(head);
  const body = el('div', 'result-body');
  if (data.empty) {
    body.append(el('p', 'empty', data.empty));
  } else {
    if (data.meta) {
      const meta = el('div', 'result-meta');
      for (const item of data.meta) meta.append(el('span', null, item));
      body.append(meta);
    }
    body.append(el('p', 'translation', data.translation));
    if (data.rationale) body.append(el('p', 'rationale', data.rationale));
    for (const note of data.notes || []) body.append(el('p', 'note', note));
  }
  card.append(body);
}

async function runCompare() {
  if (!configured() || !state.selectedKey || state.comparing) return;
  const key = state.selectedKey;
  const locale = state.locale;
  state.comparing = true;
  const button = $('run-compare');
  const status = $('compare-status');
  button.disabled = true;
  button.textContent = '真实调用中…（同模型两次）';
  status.className = 'compare-status loading';
  status.textContent = '正在调用同一模型两次：先只给文本，再给源文与检索证据…';
  renderResultCard($('baseline-card'), {
    title: 'A · 只给文本',
    badgeText: '调用中',
    badgeClass: 'badge-medium',
    empty: '等待模型返回…',
  });
  renderResultCard($('contextual-card'), {
    title: 'B · 源文 + 检索证据',
    badgeText: '调用中',
    badgeClass: 'badge-medium',
    empty: '等待模型返回…',
  });

  try {
    const response = await fetch('/api/compare', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
      body: JSON.stringify({ key, target_locale: locale }),
    });
    let payload = null;
    try {
      payload = await response.json();
    } catch (error) {
      payload = null;
    }
    if (state.selectedKey !== key) return;
    if (!response.ok || !payload || payload.status === 'error') {
      renderCompareError(payload && (payload.message || payload.error), payload);
      return;
    }
    if (payload.status === 'disabled') {
      renderIdleCards();
      status.className = 'compare-status error';
      status.textContent = payload.message || '未配置 API Key，未调用模型。';
      return;
    }
    renderCompare(payload);
  } catch (error) {
    if (state.selectedKey === key) {
      renderCompareError(error.message || String(error), null);
    }
  } finally {
    state.comparing = false;
    if (state.selectedKey === key) {
      button.disabled = false;
      button.textContent = '运行同模型对照翻译（真实调用）';
    } else {
      button.disabled = !configured();
      button.textContent = configured()
        ? '运行同模型对照翻译（真实调用）'
        : '未配置 API Key · 仅检索演示';
      resetCompare();
    }
  }
}

function usageText(usage) {
  if (!usage) return '无 usage 字段';
  const parts = [];
  if (typeof usage.prompt_tokens === 'number') parts.push(`prompt ${usage.prompt_tokens}`);
  if (typeof usage.completion_tokens === 'number') parts.push(`completion ${usage.completion_tokens}`);
  if (typeof usage.total_tokens === 'number') parts.push(`total ${usage.total_tokens}`);
  return parts.length ? `usage: ${parts.join(' / ')}` : '无 usage 字段';
}

function renderCompare(payload) {
  const status = $('compare-status');
  const same =
    payload.baseline && payload.contextual &&
    payload.baseline.translation === payload.contextual.translation;
  status.className = 'compare-status ok';
  status.textContent =
    `真实 API 调用完成（LIVE）· 模型 ${payload.model} · 目标 ${payload.target_locale} · ` +
    `使用 ${payload.evidence_used.length}/${payload.evidence_total} 条证据 · 上下文 ${payload.context_chars} 字符` +
    (payload.context_truncated ? '（已截断）' : '') +
    '。未做人工审校。';

  const common = [
    `模型 ${payload.model}`,
    `${payload.parameters.temperature === 0 ? 'temperature 0' : 'temperature ' + payload.parameters.temperature}`,
    `max_tokens ${payload.parameters.max_output_tokens}`,
  ];
  const baseline = payload.baseline;
  renderResultCard($('baseline-card'), {
    title: 'A · 只给文本',
    badgeText: 'LIVE · 真实 API 调用',
    badgeClass: 'badge-live',
    live: true,
    meta: [
      ...common,
      `${baseline.elapsed_ms} ms`,
      `${baseline.prompt_chars} prompt chars`,
      usageText(baseline.usage),
    ],
    translation: baseline.translation,
    rationale: baseline.rationale || '模型未提供 rationale。',
    notes: [
      baseline.parsed_json ? '' : '模型未返回严格 JSON，以上为原始文本内容。',
      same ? '注意：A/B 两次译文相同，可能说明该文本本身歧义较小。' : '',
    ].filter(Boolean),
  });

  const contextual = payload.contextual;
  renderResultCard($('contextual-card'), {
    title: 'B · 源文 + 检索证据',
    badgeText: 'LIVE · 真实 API 调用',
    badgeClass: 'badge-live',
    live: true,
    meta: [
      ...common,
      `${contextual.elapsed_ms} ms`,
      `${contextual.prompt_chars} prompt chars`,
      usageText(contextual.usage),
      `证据 ${payload.evidence_used.join(', ') || '无'}`,
    ],
    translation: contextual.translation,
    rationale: contextual.rationale || '模型未提供 rationale。',
    notes: [
      contextual.parsed_json ? '' : '模型未返回严格 JSON，以上为原始文本内容。',
      payload.context_truncated ? '证据上下文达到字符上限，已截断。' : '',
    ].filter(Boolean),
  });
}

function renderCompareError(message, payload) {
  const status = $('compare-status');
  status.className = 'compare-status error';
  status.textContent =
    `模型调用失败，未生成译文：${message || '未知错误'}` +
    (payload && payload.stage ? `（阶段：${payload.stage}）` : '');
  renderResultCard($('baseline-card'), {
    title: 'A · 只给文本',
    badgeText: '调用失败',
    badgeClass: 'badge-low',
    live: false,
    empty: '未生成译文。页面不会用示意内容替代真实结果。',
  });
  renderResultCard($('contextual-card'), {
    title: 'B · 源文 + 检索证据',
    badgeText: '调用失败',
    badgeClass: 'badge-low',
    live: false,
    empty: '未生成译文。页面不会用示意内容替代真实结果。',
  });
}

function showFatal(message) {
  const banner = $('offline-banner');
  banner.hidden = false;
  banner.className = 'banner banner-error';
  banner.textContent = `无法加载演示数据：${message}`;
  $('selected-key').textContent = '加载失败';
  $('source-text').textContent = '—';
  $('search-stats').textContent = '';
  $('evidence-list').replaceChildren(el('p', 'empty', '无法加载证据。'));
  $('string-list').replaceChildren(el('p', 'empty', '无法加载字符串表。'));
  $('run-compare').disabled = true;
}
