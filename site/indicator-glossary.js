/* indicator-glossary.js — 金融术语交互式知识系统。
 * 三级交互：1) 术语 Popover（桌面）/ 底部弹层（iPhone） 2) 详情三标签 3) 联动宏观传导画布。
 * 通过 [data-indicator] 事件委托统一处理；不正则替换页面 HTML；动态内容自动兼容。
 * 知识内容与实时数据分离：本模块只展示知识库文本，绝不显示实时数值。
 * 浏览器下挂到 window.Glossary；Node 下 via module.exports（纯函数可测试）。
 */
(function (global) {
  "use strict";
  var GLOSSARY_URL = "data/indicator_glossary.json";
  var LS_KEY = "chan.glossaryHints"; // "1" = 显示辅助下划线（默认开），"0" = 关闭
  var MOBILE_MAX = 760; // 与 style.css 的移动端断点一致

  /* 最小兜底术语：JSON 拉取失败时仍能显示本地解释（验收 11）。 */
  var FALLBACK_TERMS = [
    { id: "cpi", abbreviation: "CPI", chinese_name: "消费者价格指数", english_name: "Consumer Price Index",
      simple_explanation: "衡量美国居民日常消费品和服务价格变化的指标。",
      definition: "由美国劳工统计局（BLS）每月编制，反映居民消费价格水平。",
      why_it_matters: "美联储 2% 通胀目标的重要参考；影响利率预期与资产定价。",
      frequency: "每月一次。", higher_than_expected: "通胀压力可能超预期 → 降息预期可能下调。",
      lower_than_expected: "通胀压力可能缓和 → 降息预期可能增强。",
      transmission_paths: ["CPI 超预期 → 降息预期下调 → 10Y 收益率上行 → 成长股估值承压"],
      asset_impacts: { us_stocks: "超预期通常偏利空。", a_shares: "间接传导。", bonds: "超预期通常偏利空。", usd: "超预期通常偏利多。", gold: "不确定。" },
      exceptions: ["headline 与核心分项背离时持续性存疑"],
      trading_application: { short_term: "公布当天波动通常较大，以观察为主。", before_release: "检查市场定价与仓位。", after_release: "看核心分项与市场实际反应。", combine_with: "结合趋势、成交量、波动率与已有技术信号。", avoid: "不要仅凭一次读数做方向性交易。" },
      related_indicators: ["core-cpi", "pce"], sources: ["美国劳工统计局 BLS"], canvas_node_ids: ["n_infl"] },
    { id: "vix", abbreviation: "VIX", chinese_name: "恐慌指数", english_name: "CBOE Volatility Index",
      simple_explanation: "衡量市场预期未来 30 天波动程度的指数。",
      definition: "由 CBOE 基于标普 500 期权价格计算的预期波动率指数。注意：它衡量的是预期波动率，不是确定的跌幅预测。",
      why_it_matters: "风险偏好的晴雨表；VIX 飙升通常伴随恐慌，但本身不预测方向。",
      frequency: "市场实时交易。", higher_than_expected: "VIX 上升 → 预期波动加大 → 恐慌情绪升温。",
      lower_than_expected: "VIX 下降 → 市场平静 → 风险偏好回升。",
      transmission_paths: ["VIX 飙升 → 恐慌情绪 → 风险偏好下降 → 风险资产抛售"],
      asset_impacts: { us_stocks: "飙升通常偏利空。", a_shares: "间接传导。", bonds: "飙升通常偏利多（避险）。", usd: "飙升通常偏利多（避险）。", gold: "飙升通常偏利多（避险）。" },
      exceptions: ["VIX 是预期波动率，不是跌幅预测"],
      trading_application: { short_term: "VIX 是环境指标，不是买卖信号。", before_release: "不适用。", after_release: "看 VIX 是否见顶回落。", combine_with: "结合趋势、成交量与已有技术信号。", avoid: "不要把 VIX 数值直接翻译成跌幅预测。" },
      related_indicators: ["risk-appetite"], sources: ["芝加哥期权交易所 CBOE"], canvas_node_ids: [] },
    { id: "fomc", abbreviation: "FOMC", chinese_name: "联邦公开市场委员会", english_name: "Federal Open Market Committee",
      simple_explanation: "美联储内部决定利率政策的委员会，一年开 8 次会决定加息、降息还是不动。",
      definition: "美联储的货币政策决策机构，每年召开 8 次议息会议，决定联邦基金目标利率区间，并发布声明与点阵图。",
      why_it_matters: "直接决定利率路径；声明措辞与点阵图常比决议本身更重要。",
      frequency: "每年 8 次。", higher_than_expected: "鹰派 → 降息预期下调 → 利率上行。",
      lower_than_expected: "鸽派 → 降息预期增强 → 利率下行。",
      transmission_paths: ["FOMC 鹰派 → 降息预期下调 → 10Y 上行 → 成长股估值承压"],
      asset_impacts: { us_stocks: "鹰派通常偏利空；鸽派通常偏利多。", a_shares: "间接传导。", bonds: "鹰派通常偏利空；鸽派通常偏利多。", usd: "鹰派通常偏利多；鸽派通常偏利空。", gold: "鹰派通常偏利空；鸽派通常偏利多。" },
      exceptions: ["声明措辞与发布会口径背离", "市场已提前定价"],
      trading_application: { short_term: "FOMC 当天波动通常较大，以观察声明与点阵图为主。", before_release: "检查市场定价；区分决议本身与市场预期的差别。", after_release: "看声明、点阵图与发布会是否一致。", combine_with: "结合趋势、成交量与已有技术信号。", avoid: "不要把决议本身等同于市场方向；市场反应取决于决议与预期的差距。" },
      related_indicators: ["fed-funds-rate"], sources: ["美联储"], canvas_node_ids: ["n_cut", "n_cutup"] }
  ];

  var glossary = null;      // { byId: {id: term} }
  var loading = null;       // fetch promise
  var pendingOpen = null;   // JSON 未加载完时的待打开术语
  var layer = null;         // 当前弹层：{ kind: "pop"|"sheet"|"detail", el, trigger }
  var isMobile = function () { return typeof window !== "undefined" && window.innerWidth <= MOBILE_MAX; };

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  function loadGlossary() {
    if (glossary) return Promise.resolve(glossary);
    if (loading) return loading;
    loading = (typeof fetch !== "undefined" ? fetch(GLOSSARY_URL, { cache: "no-store" }).then(function (r) {
      if (!r.ok) throw new Error("HTTP " + r.status);
      return r.json();
    }).catch(function () { return null; }) : Promise.resolve(null)).then(function (data) {
      var byId = {};
      var list = (data && data.terms) || FALLBACK_TERMS;
      list.forEach(function (t) { byId[t.id] = t; });
      /* 兜底术语始终可用（即使 JSON 加载成功，也补齐缺失的兜底项）。 */
      FALLBACK_TERMS.forEach(function (t) { if (!byId[t.id]) byId[t.id] = t; });
      glossary = { byId: byId };
      if (pendingOpen) { var p = pendingOpen; pendingOpen = null; openTerm(p.id, p.trigger); }
      return glossary;
    });
    return loading;
  }

  /* 术语映射（供 app.js 宏观渲染调用；无对应术语则返回原文，不包装）。 */
  var MACRO_IND_GLOSSARY = { vix: "vix", us10y: "treasury-10y", us3m: "treasury-3m",
    gold: "gold", silver: "silver", oil: "oil", copper: "copper", dxy: "dxy", spread: "yield-curve" };
  var RELEASE_GLOSSARY = { cpi: "cpi", pce: "pce", nfp: "nfp", unemp: "unemployment",
    gdp: "gdp", pmi: "pmi", fomc: "fomc" };
  var MATRIX_GLOSSARY = { rate: "treasury-10y", dxy: "dxy", safe: "gold" };
  function termSpan(map, key, labelHTML) {
    var gid = map && map[key];
    if (!gid) return labelHTML;
    return '<span data-indicator="' + gid + '">' + labelHTML + '</span>';
  }

  function getTerm(id) {
    if (!glossary) return null;
    return glossary.byId[id] || null;
  }

  /* ---------- 纯函数：HTML 生成（可 Node 测试） ---------- */

  function popoverHTML(term) {
    return '<div class="gl-pop-head"><span class="gl-pop-abbr">' + esc(term.abbreviation) + '</span>' +
      '<span class="gl-pop-cn">' + esc(term.chinese_name) + '</span>' +
      '<button type="button" class="gl-close" data-glossary-close aria-label="关闭术语解释">×</button></div>' +
      '<div class="gl-pop-en muted small">' + esc(term.english_name) + '</div>' +
      '<p class="gl-pop-simple">' + esc(term.simple_explanation) + '</p>' +
      '<p class="gl-pop-why"><b>为什么市场关注：</b>' + esc(term.why_it_matters) + '</p>' +
      '<button type="button" class="gl-detail-btn" data-glossary-detail="' + esc(term.id) + '">查看影响链路 →</button>';
  }

  var TABS = [
    { id: "explain", label: "通俗解释" },
    { id: "impact", label: "市场影响" },
    { id: "trading", label: "交易应用" }
  ];

  function tabBodyHTML(term, tab) {
    if (tab === "impact") {
      var assets = term.asset_impacts || {};
      var rows = [["美股", assets.us_stocks], ["A股", assets.a_shares], ["债券", assets.bonds], ["美元", assets.usd], ["黄金", assets.gold]]
        .filter(function (r) { return r[1]; })
        .map(function (r) { return '<tr><th>' + esc(r[0]) + '</th><td>' + esc(r[1]) + '</td></tr>'; }).join("");
      var paths = (term.transmission_paths || []).map(function (p) { return '<li>' + esc(p) + '</li>'; }).join("");
      var exc = (term.exceptions || []).map(function (e) { return '<li>' + esc(e) + '</li>'; }).join("");
      return '<h4>典型传导路径（条件成立时，非预测）</h4>' +
        '<p class="gl-branch-note">高于预期：' + esc(term.higher_than_expected) + '</p>' +
        '<p class="gl-branch-note">符合预期：市场反应通常有限，关注声明与分项是否超预期。</p>' +
        '<p class="gl-branch-note">低于预期：' + esc(term.lower_than_expected) + '</p>' +
        '<ul class="gl-paths">' + paths + '</ul>' +
        '<h4>对不同资产的可能影响（有条件表述）</h4>' +
        '<table class="gl-assets"><tbody>' + rows + '</tbody></table>' +
        '<h4>可能反向反应的情况</h4><ul>' + exc + '</ul>' +
        '<h4>后续验证指标</h4><p>' + (term.related_indicators || []).map(function (r) {
          return '<button type="button" class="gl-link" data-indicator="' + esc(r) + '">' + esc(r.toUpperCase()) + '</button>';
        }).join(" ") + '</p>';
    }
    if (tab === "trading") {
      var ta = term.trading_application || {};
      var canvasBtn = (term.canvas_node_ids && term.canvas_node_ids.length)
        ? '<button type="button" class="gl-detail-btn" data-glossary-canvas="' + esc(term.id) + '">在传导画布中查看 →</button>'
        : '<p class="muted small">该指标在传导画布中无对应节点；传导链路见上方“市场影响”标签的文字描述。</p>';
      return '<h4>对短线交易的参考价值</h4><p>' + esc(ta.short_term || "") + '</p>' +
        '<h4>公布前需要注意什么</h4><p>' + esc(ta.before_release || "") + '</p>' +
        '<h4>公布后应该观察什么</h4><p>' + esc(ta.after_release || "") + '</p>' +
        '<h4>如何结合其他信号判断</h4><p>' + esc(ta.combine_with || "") + '</p>' +
        '<h4>哪些情况下不应该仅凭该指标交易</h4><p>' + esc(ta.avoid || "") + '</p>' +
        '<h4>联动宏观传导画布</h4>' + canvasBtn;
    }
    /* explain */
    return '<p><b>中文名称：</b>' + esc(term.chinese_name) + '</p>' +
      '<p><b>英文名称：</b>' + esc(term.english_name) + '</p>' +
      '<p><b>一句话理解：</b>' + esc(term.simple_explanation) + '</p>' +
      '<p><b>指标衡量什么：</b>' + esc(term.definition) + '</p>' +
      '<p><b>为什么重要：</b>' + esc(term.why_it_matters) + '</p>' +
      '<p><b>多久公布一次：</b>' + esc(term.frequency) + '</p>' +
      '<p><b>数值升高意味着什么：</b>' + esc(term.higher_than_expected) + '</p>' +
      '<p><b>数值降低意味着什么：</b>' + esc(term.lower_than_expected) + '</p>' +
      '<p class="muted small">注意：同比（与去年同期比）、环比（与上月比）、季调（剔除季节因素）是三种不同的比较口径；读数时需确认是哪一种。同比看趋势，环比看边际变化，季调剔除季节性扭曲。</p>' +
      '<p class="muted small">来源：' + esc((term.sources || []).join("、") || "—") + '。本解释为知识内容，不含实时数值。</p>';
  }

  function detailHTML(term, tab) {
    var tabs = TABS.map(function (t) {
      return '<button type="button" role="tab" class="gl-tab' + (t.id === tab ? " is-on" : "") + '" data-glossary-tab="' + t.id + '" aria-selected="' + (t.id === tab ? "true" : "false") + '">' + esc(t.label) + '</button>';
    }).join("");
    var related = (term.related_indicators || []).map(function (r) {
      return '<button type="button" class="gl-link" data-indicator="' + esc(r) + '">' + esc(r.toUpperCase()) + '</button>';
    }).join(" ");
    return '<div class="gl-detail-head"><span class="gl-pop-abbr">' + esc(term.abbreviation) + '</span>' +
      '<span class="gl-pop-cn">' + esc(term.chinese_name) + '</span>' +
      '<button type="button" class="gl-close" data-glossary-close aria-label="关闭详情">×</button></div>' +
      '<div class="gl-tabs" role="tablist">' + tabs + '</div>' +
      '<div class="gl-tab-body">' + tabBodyHTML(term, tab) + '</div>' +
      (related ? '<div class="gl-related"><span class="muted small">关联指标：</span>' + related + '</div>' : "");
  }

  /* ---------- DOM 层 ---------- */

  function ensureLayer(kind) {
    closeLayer();
    var el = document.createElement("div");
    el.className = kind === "detail" ? "gl-detail" : (kind === "sheet" ? "gl-sheet" : "gl-pop");
    el.setAttribute("role", kind === "pop" ? "tooltip" : "dialog");
    if (kind !== "pop") el.setAttribute("aria-modal", "true");
    el.setAttribute("aria-label", "金融术语解释");
    document.body.appendChild(el);
    layer = { kind: kind, el: el, trigger: null };
    return el;
  }

  function closeLayer() {
    if (!layer) return;
    var trigger = layer.trigger;
    if (layer.el && layer.el.parentNode) layer.el.parentNode.removeChild(layer.el);
    var backdrop = document.querySelector(".gl-backdrop");
    if (backdrop && backdrop.parentNode) backdrop.parentNode.removeChild(backdrop);
    layer = null;
    document.removeEventListener("scroll", onScrollClose, true);
    if (trigger && trigger.focus) { try { trigger.focus(); } catch (e) {} }
  }

  function onScrollClose() { closeLayer(); }

  function showBackdrop() {
    var b = document.createElement("div");
    b.className = "gl-backdrop";
    b.setAttribute("data-glossary-backdrop", "1");
    document.body.appendChild(b);
  }

  function positionPop(el, anchor) {
    var r = anchor.getBoundingClientRect();
    var w = Math.min(340, window.innerWidth - 24);
    el.style.width = w + "px";
    var top = r.bottom + 8, left = r.left;
    if (left + w > window.innerWidth - 12) left = window.innerWidth - w - 12;
    if (left < 12) left = 12;
    /* 下方空间不足时翻到上方。 */
    var h = el.offsetHeight || 260;
    if (top + h > window.innerHeight - 12 && r.top - h - 8 > 12) top = r.top - h - 8;
    el.style.left = left + "px";
    el.style.top = Math.max(12, top) + "px";
    document.addEventListener("scroll", onScrollClose, true);
  }

  function openTerm(id, triggerEl) {
    if (!glossary) { pendingOpen = { id: id, trigger: triggerEl }; loadGlossary(); return; }
    var term = getTerm(id);
    if (!term) return;
    closeLayer();
    var anchor = triggerEl && triggerEl.closest ? (triggerEl.closest("[data-indicator]") || triggerEl) : triggerEl;
    var kind = isMobile() ? "sheet" : "pop";
    var el = ensureLayer(kind);
    layer.trigger = anchor || null;
    el.innerHTML = popoverHTML(term);
    el.setAttribute("data-glossary-term", term.id);
    if (kind === "sheet") showBackdrop();
    else if (anchor) positionPop(el, anchor);
    var closeBtn = el.querySelector("[data-glossary-close]");
    if (closeBtn) closeBtn.focus();
  }

  function openDetail(id, tab) {
    if (!glossary) { pendingOpen = { id: id, trigger: null }; loadGlossary(); return; }
    var term = getTerm(id);
    if (!term) return;
    var trigger = layer ? layer.trigger : null;
    closeLayer();
    var el = ensureLayer("detail");
    layer.trigger = trigger;
    layer.term = term.id;
    layer.tab = tab || "explain";
    el.innerHTML = detailHTML(term, layer.tab);
    el.setAttribute("data-glossary-term", term.id);
    showBackdrop();
    var closeBtn = el.querySelector("[data-glossary-close]");
    if (closeBtn) closeBtn.focus();
  }

  function switchTab(tab) {
    if (!layer || layer.kind !== "detail" || !layer.term) return;
    var term = getTerm(layer.term);
    if (!term) return;
    layer.tab = tab;
    var el = layer.el;
    el.innerHTML = detailHTML(term, tab);
  }

  /* 第三级：联动宏观传导画布。优先用 app.js 暴露的 hook，fallback 为合成点击。 */
  function highlightCanvas(id) {
    var term = getTerm(id);
    if (!term || !term.canvas_node_ids || !term.canvas_node_ids.length) return false;
    var nodeId = term.canvas_node_ids[0];
    closeLayer();
    /* 切换到大环境视图（点击现有导航按钮，复用原有逻辑）。 */
    var tab = document.querySelector('[data-view="macro"]');
    if (tab) tab.click();
    var tries = 0;
    (function wait() {
      var node = document.querySelector('[data-tx-node="' + nodeId + '"]');
      if (node) {
        try { node.scrollIntoView({ behavior: "smooth", block: "center" }); } catch (e) {}
        if (global.MacroCanvas && global.MacroCanvas.highlightNode) global.MacroCanvas.highlightNode(nodeId);
        else node.click();
        return;
      }
      if (++tries < 25) setTimeout(wait, 200);
    })();
    return true;
  }

  function hintsEnabled() {
    try { var v = localStorage.getItem(LS_KEY); return v !== "0"; } catch (e) { return true; }
  }

  function applyHints() {
    if (typeof document === "undefined") return;
    document.body.classList.toggle("glossary-hints", hintsEnabled());
  }

  function setHints(on) {
    try { localStorage.setItem(LS_KEY, on ? "1" : "0"); } catch (e) {}
    applyHints();
  }

  function init() {
    if (typeof document === "undefined") return;
    if (document.body) applyHints();
    /* 事件委托：一次绑定，覆盖动态内容（验收 8）。 */
    document.addEventListener("click", function (ev) {
      var t = ev.target;
      if (!t || !t.closest) return;
      var backdrop = t.closest("[data-glossary-backdrop]");
      if (backdrop) { closeLayer(); return; }
      var closeBtn = t.closest("[data-glossary-close]");
      if (closeBtn) { closeLayer(); return; }
      var tabBtn = t.closest("[data-glossary-tab]");
      if (tabBtn && layer && layer.kind === "detail") { switchTab(tabBtn.getAttribute("data-glossary-tab")); return; }
      var detailBtn = t.closest("[data-glossary-detail]");
      if (detailBtn) { openDetail(detailBtn.getAttribute("data-glossary-detail"), "explain"); return; }
      var canvasBtn = t.closest("[data-glossary-canvas]");
      if (canvasBtn) { highlightCanvas(canvasBtn.getAttribute("data-glossary-canvas")); return; }
      var termEl = t.closest("[data-indicator]");
      if (termEl) {
        /* 若点击的是详情面板内的关联指标链接，切换术语（不关闭面板逻辑：重新打开详情）。 */
        if (layer && layer.kind === "detail") { openDetail(termEl.getAttribute("data-indicator"), layer.tab); return; }
        openTerm(termEl.getAttribute("data-indicator"), termEl);
        return;
      }
      /* 术语辅助显示开关（设置面板）。 */
      var sw = t.closest("#glossary-hints-toggle");
      if (sw) {
        var next = sw.getAttribute("aria-checked") !== "true";
        sw.setAttribute("aria-checked", next ? "true" : "false");
        setHints(next);
        return;
      }
      /* 点击弹层外部 → 关闭（仅 Popover；sheet/detail 通过 backdrop/关闭按钮关闭）。 */
      if (layer && layer.kind === "pop" && !t.closest(".gl-pop")) closeLayer();
    });
    document.addEventListener("keydown", function (ev) {
      if (ev.key === "Escape" && layer) { closeLayer(); }
    });
    loadGlossary();
  }

  var Glossary = {
    getTerm: getTerm, popoverHTML: popoverHTML, detailHTML: detailHTML,
    tabBodyHTML: tabBodyHTML, openTerm: openTerm, openDetail: openDetail,
    close: closeLayer, highlightCanvas: highlightCanvas,
    hintsEnabled: hintsEnabled, setHints: setHints, load: loadGlossary,
    termSpan: termSpan,
    MACRO_IND_GLOSSARY: MACRO_IND_GLOSSARY,
    RELEASE_GLOSSARY: RELEASE_GLOSSARY,
    MATRIX_GLOSSARY: MATRIX_GLOSSARY,
    FALLBACK_TERMS: FALLBACK_TERMS
  };
  if (typeof module !== "undefined" && module.exports) module.exports = Glossary;
  global.Glossary = Glossary;
  if (typeof document !== "undefined") {
    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
    else init();
  }
})(typeof window !== "undefined" ? window : globalThis);
