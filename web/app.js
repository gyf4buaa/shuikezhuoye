(() => {
  "use strict";

  const STATUS_LABEL = { error: "阻断", warning: "需复核", info: "提示", pass: "通过" };
  const FILTERS = [
    ["all", "全部"],
    ["error", "阻断错误"],
    ["warning", "需复核"],
    ["info", "提示"],
    ["pass", "通过"],
  ];

  const state = {
    report: null,
    request: null,
    filter: "all",
    search: "",
    expanded: new Set(),
    demos: [],
    health: null,
    busy: false,
  };

  const $ = (selector) => document.querySelector(selector);
  const els = {
    demoSelect: $("#demo-select"),
    loadDemo: $("#load-demo"),
    target: $("#target-locale"),
    uiProfile: $("#ui-profile"),
    format: $("#format"),
    llmToggle: $("#llm-toggle"),
    textarea: $("#dataset-input"),
    inputCount: $("#input-count"),
    analyze: $("#analyze"),
    fileInput: $("#file-input"),
    exportButtons: Array.from(document.querySelectorAll("[data-export]")),
    welcome: $("#welcome"),
    results: $("#results-content"),
    summary: $("#summary"),
    meta: $("#meta-strip"),
    filters: $("#filters"),
    search: $("#search"),
    resultCount: $("#result-count"),
    unitList: $("#unit-list"),
    modeBadge: $("#mode-badge"),
    methodButton: $("#method-button"),
    methodModal: $("#method-modal"),
    methodBody: $("#method-body"),
    methodClose: $("#method-close"),
    toast: $("#toast"),
  };

  const esc = (value) => String(value == null ? "" : value).replace(/[&<>"']/g, (ch) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[ch]));

  const pct = (value) => `${Math.round((Number(value) || 0) * 100)}%`;

  let toastTimer = null;
  function toast(message, isError = false) {
    els.toast.textContent = message;
    els.toast.className = "toast" + (isError ? " error" : "");
    els.toast.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { els.toast.hidden = true; }, 5200);
  }

  async function api(path, options = {}) {
    const response = await fetch(path, options);
    let data = null;
    try { data = await response.json(); } catch (err) { data = null; }
    if (!response.ok) {
      throw new Error((data && data.error) || `请求失败 (${response.status})`);
    }
    return data;
  }

  function updateCount() {
    const lines = els.textarea.value.split("\n").filter((line) => line.trim()).length;
    els.inputCount.textContent = lines ? `≈ ${lines} 行` : "";
  }

  async function init() {
    els.textarea.addEventListener("input", updateCount);
    els.loadDemo.addEventListener("click", () => loadDemo(els.demoSelect.value));
    els.analyze.addEventListener("click", runAnalysis);
    els.fileInput.addEventListener("change", handleFile);
    els.search.addEventListener("input", () => {
      state.search = els.search.value.trim().toLowerCase();
      renderUnits();
    });
    els.exportButtons.forEach((button) => {
      button.addEventListener("click", () => exportReport(button.dataset.export));
    });
    els.methodButton.addEventListener("click", openMethod);
    els.methodClose.addEventListener("click", closeMethod);
    els.methodModal.addEventListener("click", (event) => {
      if (event.target === els.methodModal) closeMethod();
    });
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && !els.methodModal.hidden) closeMethod();
    });

    renderFilters();

    try {
      state.health = await api("/api/health");
      const llm = state.health.llm_configured ? `LLM: ${state.health.llm_model}` : "确定性模式 · LLM 未配置";
      els.modeBadge.textContent = llm;
      els.modeBadge.className = "badge " + (state.health.llm_configured ? "badge-live" : "badge-live");
    } catch (err) {
      els.modeBadge.textContent = "离线/接口异常";
    }

    try {
      const data = await api("/api/demos");
      state.demos = data.demos || [];
      els.demoSelect.innerHTML = state.demos
        .map((demo) => `<option value="${esc(demo.name)}">${esc(demo.label)}</option>`)
        .join("");
    } catch (err) {
      els.demoSelect.innerHTML = '<option value="zh_ptbr">中 → 巴西葡语（主演示）</option>';
    }

    if (state.demos.length) {
      const params = new URLSearchParams(window.location.search);
      const requested = params.get("demo");
      const demoName = state.demos.some((demo) => demo.name === requested) ? requested : state.demos[0].name;
      await loadDemo(demoName, true);
      const unit = params.get("unit");
      if (unit && state.report && state.report.units.some((item) => item.id === unit)) {
        state.expanded.add(unit);
        renderUnits();
        requestAnimationFrame(() => {
          const card = els.unitList.querySelector(`.unit[data-unit-id="${cssEscape(unit)}"]`);
          if (card) card.scrollIntoView({ block: "start" });
        });
      }
    }
  }

  async function loadDemo(name, silent = false) {
    if (!name) return;
    try {
      const payload = await api(`/api/demo?name=${encodeURIComponent(name)}`);
      els.textarea.value = JSON.stringify(payload, null, 2);
      updateCount();
      if (payload.target_locale) els.target.value = payload.target_locale;
      if (payload.ui_profile) els.uiProfile.value = payload.ui_profile;
      els.format.value = "json";
      await runAnalysis();
    } catch (err) {
      if (!silent) toast(err.message, true);
    }
  }

  function handleFile(event) {
    const file = event.target.files && event.target.files[0];
    if (!file) return;
    if (file.size > 2 * 1024 * 1024) {
      toast("文件超过 2MB 上限", true);
      return;
    }
    const reader = new FileReader();
    reader.onload = async () => {
      els.textarea.value = String(reader.result || "");
      updateCount();
      const name = file.name.toLowerCase();
      if (name.endsWith(".xliff") || name.endsWith(".xlf") || name.endsWith(".xml")) {
        els.format.value = "xliff";
      } else if (name.endsWith(".csv")) {
        els.format.value = "csv";
      } else if (name.endsWith(".jsonl")) {
        els.format.value = "jsonl";
      } else if (name.endsWith(".json")) {
        els.format.value = "json";
      } else {
        els.format.value = "auto";
      }
      await runAnalysis();
    };
    reader.onerror = () => toast("文件读取失败", true);
    reader.readAsText(file, "utf-8");
    event.target.value = "";
  }

  async function runAnalysis() {
    if (state.busy) return;
    const text = els.textarea.value;
    if (!text.trim()) {
      toast("请先粘贴或载入批量文本", true);
      return;
    }
    state.busy = true;
    const original = els.analyze.innerHTML;
    els.analyze.disabled = true;
    els.analyze.innerHTML = '<span class="spinner"></span>分析中…';
    try {
      const body = {
        text,
        format: els.format.value,
        target_locale: els.target.value,
        ui_profile: els.uiProfile.value,
        llm_enhance: Boolean(els.llmToggle && els.llmToggle.checked),
      };
      const report = await api("/api/analyze", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      state.report = report;
      state.request = body;
      state.expanded = new Set();
      renderReport();
      els.exportButtons.forEach((button) => { button.disabled = false; });
      if (report.llm && report.llm.requested && !report.llm.configured) {
        toast("已请求 LLM 语气建议，但未配置 LLM_API_KEY；已按确定性模式完成。", false);
      }
    } catch (err) {
      toast(err.message, true);
    } finally {
      state.busy = false;
      els.analyze.disabled = false;
      els.analyze.innerHTML = original;
    }
  }

  function renderFilters() {
    els.filters.innerHTML = FILTERS.map(([key, label]) =>
      `<button type="button" class="filter${state.filter === key ? " active" : ""}" data-filter="${key}">${label}</button>`
    ).join("");
    els.filters.querySelectorAll("[data-filter]").forEach((button) => {
      button.addEventListener("click", () => {
        state.filter = button.dataset.filter;
        renderFilters();
        renderUnits();
      });
    });
  }

  function renderReport() {
    const report = state.report;
    if (!report) return;
    els.welcome.hidden = true;
    els.results.hidden = false;

    const summary = report.summary;
    const cards = [
      { value: summary.total_units, label: "文本条数", sub: `${esc(report.meta.project || "")}`, cls: "accent", filter: "all" },
      { value: summary.issues.by_severity.error, label: "阻断错误", sub: `${summary.unit_status.error} 条文本`, cls: "error", filter: "error" },
      { value: summary.issues.by_severity.warning, label: "需复核", sub: `${summary.unit_status.warning} 条文本`, cls: "warning", filter: "warning" },
      { value: summary.overflow.overflow_units, label: "渲染溢出", sub: `实测 ${summary.overflow.measured_units} · 未测 ${summary.overflow.unsupported_units}`, cls: "error", filter: "error" },
      { value: summary.context.insufficient, label: "消歧弃答", sub: `命中词条 ${summary.context.matched_units}`, cls: "warning", filter: "warning" },
      { value: summary.needs_human_units, label: "需人工处理", sub: `占位符错误 ${summary.placeholders.units_with_errors} 条`, cls: "info", filter: "warning" },
    ];
    els.summary.innerHTML = cards.map((card) => `
      <div class="summary-card ${card.cls}" data-summary-filter="${card.filter}" role="button" tabindex="0">
        <div class="value">${card.value}</div>
        <div class="label">${card.label}</div>
        <div class="sub">${card.sub}</div>
      </div>`).join("");
    els.summary.querySelectorAll("[data-summary-filter]").forEach((card) => {
      const activate = () => {
        state.filter = card.dataset.summaryFilter;
        renderFilters();
        renderUnits();
        els.results.scrollIntoView({ behavior: "smooth", block: "start" });
      };
      card.addEventListener("click", activate);
      card.addEventListener("keydown", (event) => { if (event.key === "Enter" || event.key === " ") activate(); });
    });

    const context = summary.context;
    const overflow = summary.overflow;
    els.meta.innerHTML = [
      `<span class="pill">项目 <strong>${esc(report.meta.project)}</strong></span>`,
      `<span class="pill">${esc(report.meta.source_locale)} → <strong>${esc(report.meta.target_locale)}</strong></span>`,
      `<span class="pill">上下文覆盖 <strong>${pct(context.coverage.ratio)}</strong></span>`,
      `<span class="pill">字符基线误判 <strong>${overflow.naive_false_positive_units + overflow.naive_false_negative_units}</strong></span>`,
      `<span class="pill">占位符错误 <strong>${summary.placeholders.errors}</strong></span>`,
      `<span class="pill">LLM <strong>${llmLabel(report.llm)}</strong></span>`,
      report.meta.synthetic ? '<span class="pill">合成示例数据</span>' : "",
    ].join("");

    renderUnits();
    renderMethod();
  }

  function llmLabel(llm) {
    if (!llm) return "未知";
    if (llm.configured && llm.requested) return `实时 ${esc(llm.model || "已配置")} · 调用 ${llm.calls} 次`;
    if (llm.configured) return "已配置 · 本次未调用";
    if (llm.requested) return "未配置 · 已降级";
    return "未配置（确定性）";
  }

  function filterUnits() {
    const report = state.report;
    if (!report) return [];
    const order = { error: 0, warning: 1, info: 2, pass: 3 };
    return report.units
      .filter((unit) => state.filter === "all" || unit.status === state.filter)
      .filter((unit) => {
        if (!state.search) return true;
        const haystack = [unit.id, unit.source, unit.target, unit.key, unit.screen].join(" ").toLowerCase();
        return haystack.includes(state.search);
      })
      .sort((a, b) => (order[a.status] - order[b.status]) || a.id.localeCompare(b.id));
  }

  function renderUnits() {
    const units = filterUnits();
    els.resultCount.textContent = `显示 ${units.length} / ${state.report ? state.report.units.length : 0} 条`;
    if (!units.length) {
      els.unitList.innerHTML = '<div class="welcome"><h2>没有匹配的文本</h2><p>调整筛选条件或搜索词。</p></div>';
      return;
    }
    els.unitList.innerHTML = units.map(renderUnit).join("");
    els.unitList.querySelectorAll(".unit").forEach((card) => {
      const head = card.querySelector(".unit-head");
      const detail = card.querySelector(".unit-detail");
      const id = card.dataset.unitId;
      const expanded = state.expanded.has(id);
      head.setAttribute("aria-expanded", expanded ? "true" : "false");
      detail.hidden = !expanded;
      head.addEventListener("click", () => {
        const open = state.expanded.has(id);
        if (open) state.expanded.delete(id); else state.expanded.add(id);
        detail.hidden = open;
        head.setAttribute("aria-expanded", open ? "false" : "true");
        if (!open) requestAnimationFrame(() => measureBrowserFor(id));
      });
    });
    state.expanded.forEach((id) => {
      const card = els.unitList.querySelector(`.unit[data-unit-id="${cssEscape(id)}"]`);
      if (card) {
        card.querySelector(".unit-detail").hidden = false;
        card.querySelector(".unit-head").setAttribute("aria-expanded", "true");
        requestAnimationFrame(() => measureBrowserFor(id));
      }
    });
  }

  function renderUnit(unit) {
    const issueCodes = [...new Set(unit.issues.map((issue) => issue.code))].slice(0, 3);
    const worst = unit.issues.find((issue) => issue.severity === "error")
      || unit.issues.find((issue) => issue.severity === "warning")
      || unit.issues.find((issue) => issue.severity === "info");
    const chipClass = worst ? worst.severity : "pass";
    const chips = issueCodes.map((code) => {
      const issue = unit.issues.find((item) => item.code === code);
      return `<span class="chip ${issue ? issue.severity : "pass"}">${esc(code)}</span>`;
    }).join("");
    const target = unit.target ? esc(unit.target) : '<span class="muted">（空译文）</span>';
    return `
      <article class="unit status-${unit.status}" data-unit-id="${esc(unit.id)}">
        <button class="unit-head" type="button" aria-expanded="false">
          <span class="status-dot ${unit.status}" aria-hidden="true"></span>
          <span class="unit-id">${esc(unit.id)}</span>
          <span class="unit-text">
            <span class="src">${esc(unit.source)}</span>
            <span class="arrow">→</span>
            <span class="tgt">${target}</span>
          </span>
          <span class="chips">${chips || `<span class="chip pass">${STATUS_LABEL[unit.status]}</span>`}</span>
          <span class="chevron">▾</span>
        </button>
        <div class="unit-detail" hidden>${renderDetail(unit)}</div>
      </article>`;
  }

  function renderDetail(unit) {
    const sections = [];
    sections.push(renderIssues(unit));
    if (unit.context) sections.push(renderContext(unit));
    if (unit.overflow) sections.push(renderOverflow(unit));
    if (unit.placeholder) sections.push(renderPlaceholder(unit));
    if (unit.source_gaps && unit.source_gaps.length) sections.push(renderGaps(unit));
    if (unit.register_risks && unit.register_risks.length) sections.push(renderRisks(unit));
    if (!sections.some(Boolean)) {
      return '<div class="empty-detail">未发现可自动检查的问题。注意：“通过”只表示已实现的检查项没有命中，不代表目标语语法或游戏引擎布局已经验证。</div>';
    }
    return `<div class="detail-grid">${sections.filter(Boolean).join("")}</div>`;
  }

  function renderIssues(unit) {
    if (!unit.issues.length) return "";
    const items = unit.issues.map((issue) => `
      <div class="issue ${issue.severity}">
        <div class="issue-head">
          <span class="severity ${issue.severity}">${issue.severity}</span>
          <span class="issue-code">${esc(issue.code)}</span>
          <span class="hint">${esc(issue.category_label || issue.category)}</span>
        </div>
        <div class="issue-msg">${esc(issue.message)}</div>
        ${issue.evidence && issue.evidence.length ? `<ul>${issue.evidence.map((line) => `<li>${esc(line)}</li>`).join("")}</ul>` : ""}
        ${issue.suggestion ? `<div class="suggestion">建议：${esc(issue.suggestion)}</div>` : ""}
      </div>`).join("");
    return `<section class="detail-section wide"><h4>问题明细 <span class="tag">${unit.issues.length} 项</span></h4><div class="issue-list">${items}</div></section>`;
  }

  function renderContext(unit) {
    const context = unit.context;
    const selected = context.selected || {};
    const statusText = context.status === "resolved" ? "已判定" : context.status === "inferred" ? "由词形/弱证据推断" : "证据不足，已弃答";
    const confidence = context.confidence || 0;
    const evidence = (context.evidence || []).map((item) => `
      <div class="evidence-item">
        <span class="weight">+${item.weight}</span>
        <span class="et">${esc(item.type)}</span>
        <span class="ev">${esc(item.label)}：${esc(item.value)}</span>
      </div>`).join("");
    const alternatives = (context.alternatives || []).map((alt) => `
      <tr>
        <td>${esc(alt.label)}</td>
        <td>${esc(alt.translation)}</td>
        <td class="score">${alt.score}</td>
      </tr>`).join("");
    const check = context.target_check;
    let checkHtml = "";
    if (check && check.conflict_with) {
      checkHtml = `<div class="callout"><strong>译名冲突</strong>当前义项建议“${esc(check.expected)}”，译文却用了另一义项的“${esc(check.conflict_with.translation)}”。</div>`;
    } else if (check && check.expected_present) {
      checkHtml = `<div class="callout info"><strong>译名与上下文一致</strong>译文包含建议译名“${esc(check.expected)}”。</div>`;
    } else if (check) {
      checkHtml = `<div class="callout"><strong>未找到建议译名</strong>可能使用了变格/同义表达；请确认并在术语表登记。</div>`;
    }
    return `
      <section class="detail-section">
        <h4>上下文消歧 <span class="tag exp">实验性</span></h4>
        ${context.status === "insufficient"
          ? `<div class="callout"><strong>拒绝猜测</strong>${esc(context.reason || "证据不足")}</div>`
          : `<div class="kv">
              <dt>同源词</dt><dd>${esc(context.matched_alias)} → ${esc(selected.label || "")}</dd>
              <dt>建议译名</dt><dd>${esc(selected.translation || "")}</dd>
              <dt>判定</dt><dd>${statusText}</dd>
             </div>
             <div class="confidence" style="margin-top:8px"><span>置信度</span><span class="confidence-bar"><i style="width:${pct(confidence)}"></i></span><span>${pct(confidence)}</span></div>`}
        ${checkHtml}
        ${evidence ? `<div class="evidence">${evidence}</div>` : ""}
        ${alternatives ? `<table class="alt-table"><thead><tr><th>候选义项</th><th>译名</th><th>分数</th></tr></thead><tbody>${alternatives}</tbody></table>` : ""}
        ${context.status === "insufficient" && context.question ? `<div class="suggestion">${esc(context.question)}</div>` : ""}
        <p class="hint" style="margin-top:7px">依据：${esc(context.method || "现有 key / 界面 / 组件 / 相邻文案的加权证据；不是语义理解。")}</p>
      </section>`;
  }

  function renderOverflow(unit) {
    const data = unit.overflow;
    if (!data) return "";
    if (!data.supported) {
      return `
        <section class="detail-section wide">
          <h4>宽度风险 <span class="tag">未测量</span></h4>
          <div class="callout"><strong>拒绝给出伪测量值</strong>${esc(data.reason || "当前字形/模板不受支持")}</div>
          <p class="hint">文本框：${data.box ? `${data.box.box_w}×${data.box.box_h}px，字号 ${data.box.font_size}px` : "未知"}。请为目标语加载对应字体，或在目标 UI 中实测。</p>
        </section>`;
    }
    const box = data.box;
    const measured = data.measured;
    const naive = data.naive;
    const nowrap = box.max_lines === 1 ? "nowrap" : "";
    const overflowClass = measured.overflow ? "measured-overflow" : "";
    const style = [
      `width:${box.box_w}px`, `height:${box.box_h}px`, `padding:${box.padding}px`,
      `font-size:${box.font_size}px`, `line-height:${box.line_height}`,
      `letter-spacing:${box.letter_spacing}px`,
    ].join(";");
    const naiveStatus = naive.fits ? '<span class="good">可容纳</span>' : '<span class="bad">预警溢出</span>';
    const actualStatus = measured.overflow ? '<span class="bad">溢出</span>' : '<span class="good">可容纳</span>';
    const assumptions = (data.assumptions || []).map((line) => `<li>${esc(line)}</li>`).join("");
    return `
      <section class="detail-section wide">
        <h4>宽度风险 <span class="tag">给定字体/布局假设</span></h4>
        <div class="ui-stage">
          <div class="ui-box ${nowrap} ${overflowClass}" style="${style}" data-ui-box="${esc(unit.id)}"><span>${esc(data.text)}</span></div>
          <div class="stage-label">盒模型 <b>${box.box_w}×${box.box_h}px</b> · 内容区 <b>${box.content_width}×${box.content_height}px</b> · 字号 <b>${box.font_size}px</b> · 上限 <b>${box.max_lines}</b> 行</div>
          <div class="stage-label" data-browser-check="${esc(unit.id)}">浏览器 DOM 实测：等待渲染…</div>
        </div>
        <table class="metric-table">
          <tbody>
            <tr><th>字符数</th><td class="num">${data.char_count}${data.max_chars ? ` / 预算 ${data.max_chars}` : ""}</td></tr>
            <tr><th>字符数基线</th><td class="num">${naive.estimated_width_px}px · ${naive.estimated_lines} 行 · ${naiveStatus}</td></tr>
            <tr><th>实测最宽行</th><td class="num">${measured.max_line_width_px}px / ${box.content_width}px · ${actualStatus}</td></tr>
            <tr><th>实测行数 / 高度</th><td class="num">${measured.line_count} 行 / 需要 ${measured.required_height_px}px（盒高 ${box.box_h}px）</td></tr>
            <tr><th>判定</th><td class="num">${measured.overflow ? `<span class="bad">${esc(measured.reasons.join("；"))}</span>` : '<span class="good">按当前假设可容纳</span>'}</td></tr>
          </tbody>
        </table>
        ${assumptions ? `<ul class="assumptions">${assumptions}</ul>` : ""}
        <p class="hint" style="margin-top:7px">浏览器实测使用同一 TTF 与 CSS 盒模型做独立交叉检查；两者都不是游戏引擎内的最终布局验证。</p>
      </section>`;
  }

  function renderPlaceholder(unit) {
    const data = unit.placeholder;
    if (!data) return "";
    const missing = data.missing && data.missing.length ? data.missing.join(", ") : "无";
    const extra = data.extra && data.extra.length ? data.extra.join(", ") : "无";
    return `
      <section class="detail-section">
        <h4>模板完整性 <span class="tag">核心闭环</span></h4>
        <div class="kv">
          <dt>源文占位符</dt><dd class="mono">${esc((data.source_keys || []).join(", ") || "无")}</dd>
          <dt>译文占位符</dt><dd class="mono">${esc((data.target_keys || []).join(", ") || "无")}</dd>
          <dt>缺失 / 多出</dt><dd>${esc(missing)} / ${esc(extra)}</dd>
        </div>
        <p class="hint" style="margin-top:6px">只验证变量保留与重排合法性；不验证目标语语法是否正确。</p>
      </section>`;
  }

  function renderGaps(unit) {
    const cards = unit.source_gaps.map((gap) => `
      <div class="gap-card">
        <div class="gap-type">${esc(gap.type)} · 置信 ${esc(gap.confidence)}</div>
        <div class="q">${esc(gap.message)}</div>
        <ul>${(gap.evidence || []).map((line) => `<li>${esc(line)}</li>`).join("")}</ul>
        <div class="suggestion">需要补充：${esc(gap.question)}</div>
      </div>`).join("");
    return `<section class="detail-section"><h4>源文语境缺口 <span class="tag exp">实验性</span></h4><div class="gap-grid">${cards}</div></section>`;
  }

  function renderRisks(unit) {
    const cards = unit.register_risks.map((risk) => `
      <div class="risk-card">
        <div class="gap-type">${esc(risk.type)} · ${esc(risk.strategy)}</div>
        <div class="q">“${esc(risk.pattern)}”</div>
        <ul><li>${esc(risk.note)}</li></ul>
        <div class="suggestion">需要人工确认：${esc(risk.question)}</div>
        ${risk.llm_suggestion && risk.llm_suggestion.suggestion
          ? `<div class="suggestion">LLM（实时，仅供参考）：${esc(risk.llm_suggestion.suggestion.candidate || risk.llm_suggestion.suggestion.strategy || "")}</div>`
          : ""}
      </div>`).join("");
    return `<section class="detail-section"><h4>语气/修辞风险 <span class="tag exp">实验性</span></h4><div class="risk-grid">${cards}</div></section>`;
  }

  function measureBrowserFor(unitId) {
    const unit = state.report && state.report.units.find((item) => item.id === unitId);
    if (!unit || !unit.overflow || !unit.overflow.supported) return;
    const box = els.unitList.querySelector(`.ui-box[data-ui-box="${cssEscape(unitId)}"]`);
    const label = els.unitList.querySelector(`[data-browser-check="${cssEscape(unitId)}"]`);
    if (!box || !label || box.closest(".unit-detail").hidden) return;
    const widthOverflow = box.scrollWidth > box.clientWidth + 1;
    const heightOverflow = box.scrollHeight > box.clientHeight + 1;
    const overflow = widthOverflow || heightOverflow;
    const server = unit.overflow.measured.overflow;
    const agreement = overflow === server;
    const details = [];
    if (widthOverflow) details.push("宽度");
    if (heightOverflow) details.push("高度");
    label.innerHTML = `浏览器 DOM 实测：<b class="${overflow ? "bad" : "good"}">${overflow ? "溢出" : "未溢出"}</b>` +
      (details.length ? `（${details.join("、")}）` : "") +
      ` · 与 Pillow 判定${agreement ? "一致" : "不一致，需人工复核"} · <span class="hint">仍非游戏引擎布局</span>`;
  }

  function cssEscape(value) {
    if (window.CSS && CSS.escape) return CSS.escape(value);
    return String(value).replace(/["\\]/g, "\\$&");
  }

  async function exportReport(format) {
    if (!state.request) return;
    try {
      const response = await fetch(`/api/export?format=${encodeURIComponent(format)}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(state.request),
      });
      if (!response.ok) {
        let data = null;
        try { data = await response.json(); } catch (err) { data = null; }
        throw new Error((data && data.error) || "导出失败");
      }
      const blob = await response.blob();
      const disposition = response.headers.get("Content-Disposition") || "";
      const match = disposition.match(/filename="([^"]+)"/);
      const filename = match ? match[1] : `preflight.${format}`;
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = filename;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      setTimeout(() => URL.revokeObjectURL(url), 3000);
      toast(`已导出 ${filename}`);
    } catch (err) {
      toast(err.message, true);
    }
  }

  function renderMethod() {
    const report = state.report;
    if (!report) return;
    const engine = report.engine || {};
    const assumptions = (report.units.find((unit) => unit.overflow && unit.overflow.assumptions) || {}).overflow;
    els.methodBody.innerHTML = `
      <h3>核心闭环（可测试）</h3>
      <ul>${(engine.core_checks || []).map((line) => `<li>${esc(line)}</li>`).join("")}</ul>
      <h3>实验性功能</h3>
      <ul>${(engine.experimental_checks || []).map((line) => `<li>${esc(line)}</li>`).join("")}</ul>
      <h3>明确不做 / 未支持</h3>
      <ul>${(engine.limitations || []).map((line) => `<li>${esc(line)}</li>`).join("")}</ul>
      <h3>验证口径提醒</h3>
      <ul>${(engine.caveats || []).map((line) => `<li>${esc(line)}</li>`).join("")}</ul>
      ${assumptions ? `<h3>本次字体测量假设</h3><ul>${assumptions.assumptions.map((line) => `<li>${esc(line)}</li>`).join("")}</ul>` : ""}
      <h3>现有项目如何接入</h3>
      <p>把 CAT/TMS 或项目字符串表导出的 CSV / JSON / XLIFF 1.2 直接粘贴或导入；key、screen、component、neighbors、max_chars 以及 UI 盒模型来自现有资源（字符串导出、界面/控件路径、同屏相邻文案、设计稿尺寸）。缺失的上下文不会要求用户逐条手填，而是显示覆盖率并把证据不足的条目标为“需上下文”。</p>
      <p>XLIFF 导入会读取本工具导出的 <code class="mono">dsh-context</code> JSON note；其他 XLIFF 的纯文本可导入，内联 <code class="mono">&lt;g&gt;/&lt;ph&gt;</code> 标记在 v0.1 中会展平，属于已知限制。</p>`;
  }

  function openMethod() {
    if (!state.report) {
      els.methodBody.innerHTML = "<p>先运行一次预检，这里会显示本次引擎的能力边界、测量假设与接入说明。</p>";
    }
    els.methodModal.hidden = false;
  }
  function closeMethod() { els.methodModal.hidden = true; }

  document.addEventListener("DOMContentLoaded", init);
})();
