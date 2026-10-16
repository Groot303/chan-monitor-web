/* 缠论信号看板 — 纯原生 JS。数据: data/signals.json, 图片: img/*_chan2.png, 交互图: data/charts/*.json + Lightweight Charts(本地) */
(function () {
  "use strict";

  // ---------- 常量 ----------
  var LV = { weekly: "周线", daily: "日线", "30m": "30分钟", "5m": "5分钟" };
  var LV_ORDER = ["weekly", "daily", "30m", "5m"];
  var RECENT_WIN = { weekly: 4, daily: 10, "30m": 40, "5m": 120 };
  var TY = { "1B": "一买", "2B": "二买", "3B": "三买", "1S": "一卖", "2S": "二卖", "3S": "三卖", "ZG_S": "中枢上沿卖", "ZD_B": "中枢下沿买", "BC_B": "盘整背驰买", "BC_S": "盘整背驰卖" };
  var BK = [
    ["base", "基础分"], ["divergence", "背驰"], ["resonance", "共振"],
    ["confirmed", "确认"], ["freshness", "新鲜度"], ["quality", "中枢质量"]
  ];
  var RES = { strong: "强共振", partial: "部分共振", mixed: "混合", neutral: "中性", conflict: "冲突" };
  var DIR = { up: "向上", down: "向下", range: "震荡", inside: "震荡" };
  var POS = { above: "中枢上方", below: "中枢下方", inside: "中枢内", none: "无中枢" };
  var TIER = [[5, "hi", "高"], [2.5, "mid", "中"], [-Infinity, "lo", "低"]];
  // 市场配置:美股(us) / A股指数(cn)
  // API_BASE: 恒为空串 = 同源后端(api.py 同源托管 site/ + /api/*)。设置面板的 API 地址输入已删除。
  var API_BASE = "";
  var MK = {
    us: { label: "美股", api: "/api/signals", tz: "ET", src: "Alpaca(IEX 免费版)", delay: "Alpaca 可能延迟",
          watch: ["AAOI","AAPL","AMD","AVGO","GOOG","INTC","LITE","META","MRNA","MRVL","MU","NOK","NVDA","ORCL","PLTR","SKHY","SNDK","SPCX","TSLA","TSM"],
          searchPh: "搜索代码,如 NVDA" },
    cn: { label: "A股", api: "/api/signals_cn", tz: "北京时间", src: "东方财富", delay: "东财数据可能延迟",
          watch: ["上证指数","科创50","银行指数","平均股价"],
          searchPh: "搜索指数,如 上证指数" }
  };
  function apiURL() { var m = MK[MARKET]; return (API_BASE || "") + m.api; }
  function signalsURL() { return apiURL(); }
  var MARKET = lsGet("chan.market") === "cn" ? "cn" : "us";
  var DEFAULT_F = { q: "", level: "", type: "", conf: "", min: 3, recent: false, sort: "score", dir: "desc" };
  // filters.v2:旧版默认 recent=true 已写入 localStorage,换键后首次加载回落到新默认(显示全部信号)
  var LS = { theme: "chan.theme", mode: "chan.mode", filters: "chan.filters.v2" };

  // ---------- 工具 ----------
  var $ = function (id) { return document.getElementById(id); };
  var qsa = function (sel, root) { return Array.prototype.slice.call((root || document).querySelectorAll(sel)); };
  function esc(s) { return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]; }); }
  function lsGet(k) { try { return localStorage.getItem(k); } catch (e) { return null; } }
  function lsSet(k, v) { try { localStorage.setItem(k, v); } catch (e) { /* 隐私模式 */ } }
  function num(v, d) { return (typeof v === "number" && isFinite(v)) ? v : (d === undefined ? null : d); }
  function fmtPrice(v) { v = num(v); return v == null ? "—" : v.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 }); }
  function fmtSigned(v, n) { v = num(v, 0); var s = v.toFixed(n == null ? 2 : n); return v > 0 ? "+" + s : (v < 0 ? "−" + s.slice(1) : s); }
  function fmtPct(v) { v = num(v); return v == null ? "—" : v.toFixed(2) + "%"; }
  function isBuy(g) { return /B$/.test((g && g.type) || g || ""); }
  function isEdge(g) { return (g && g.kind === "pivot_edge") || g.type === "ZG_S" || g.type === "ZD_B"; }
  function tier(score) { for (var i = 0; i < TIER.length; i++) if (score >= TIER[i][0]) return { k: TIER[i][1], label: TIER[i][2] }; return { k: "lo", label: "低" }; }
  function typeName(t) { return TY[t] || t; }
  function isPre(g) { return g.type && g.type.indexOf("PRE_") === 0; }
  function preBadge(g) { return isPre(g) ? '<span class="pre-badge">预</span>' : ''; }
  function fmtTime(t, level) { if (!t) return "—"; return level === "30m" ? t + " " + MK[MARKET].tz : t; }
  var uid = 0;

  function relTime(date) {
    var diff = (Date.now() - date.getTime()) / 1000;
    if (diff < 0) return "刚刚";
    if (diff < 60) return Math.round(diff) + " 秒前";
    if (diff < 3600) return Math.round(diff / 60) + " 分钟前";
    if (diff < 86400) return Math.round(diff / 3600) + " 小时前";
    return Math.round(diff / 86400) + " 天前";
  }

  // SVG 环形分数
  function ringHTML(score, lg) {
    var t = tier(score), id = "rg" + (++uid);
    var r = 26, c = 2 * Math.PI * r, pct = Math.max(0, Math.min(1, score / 10));
    return '<div class="ring tier-' + t.k + (lg ? " lg" : "") + '" role="img" aria-label="分数 ' + score.toFixed(1) + ' / 10,' + t.label + '分段">' +
      '<svg viewBox="0 0 60 60" aria-hidden="true"><defs><linearGradient id="' + id + '" x1="0" y1="0" x2="1" y2="1">' +
      '<stop offset="0" style="stop-color:var(--t1)"/><stop offset="1" style="stop-color:var(--t2)"/></linearGradient></defs>' +
      '<circle class="track" cx="30" cy="30" r="' + r + '" fill="none" stroke-width="5"/>' +
      '<circle class="val" cx="30" cy="30" r="' + r + '" fill="none" stroke-width="5" stroke="url(#' + id + ')" ' +
      'stroke-dasharray="' + c.toFixed(2) + '" stroke-dashoffset="' + c.toFixed(2) + '" data-off="' + (c * (1 - pct)).toFixed(2) + '"/></svg>' +
      '<div class="ring-txt" aria-hidden="true"><div>' + score.toFixed(1) + '<small>/ 10</small></div></div></div>';
  }
  function sbarHTML(score) {
    var t = tier(score);
    return '<div class="sbar tier-' + t.k + '"><span class="sbar-num">' + score.toFixed(1) + '</span>' +
      '<div class="sbar-track" role="img" aria-label="分数 ' + score.toFixed(1) + ' / 10,' + t.label + '分段"><div class="sbar-fill" data-w="' + (score * 10) + '%"></div></div>' +
      '<span class="tier-txt">' + t.label + '</span></div>';
  }
  function animateIn(root) {
    requestAnimationFrame(function () {
      requestAnimationFrame(function () {
        qsa("[data-off]", root).forEach(function (el) { el.setAttribute("stroke-dashoffset", el.getAttribute("data-off")); });
        qsa("[data-w]", root).forEach(function (el) { el.style.width = el.getAttribute("data-w"); });
      });
    });
  }

  function chipsHTML(g, opts) {
    opts = opts || {};
    var buy = isBuy(g), edge = isEdge(g), out = [];
    out.push('<span class="chip chip-lv">' + esc(LV[g.level] || g.level) + '</span>');
    if (edge) {
      out.push('<span class="chip ' + (buy ? "chip-edge-buy" : "chip-edge-sell") + '">' + esc(typeName(g.type)) + ' · ' + esc(g.type) + '</span>');
      out.push('<span class="chip chip-lv" title="中枢沿启发式,非经典一二三类买卖点">中枢沿</span>');
    } else {
      out.push('<span class="chip ' + (buy ? "chip-buy" : "chip-sell") + '">' + esc(typeName(g.type)) + ' · ' + esc(g.type) + '</span>');
    }
    out.push(g.confirmed
      ? '<span class="chip chip-ok">已确认</span>'
      : '<span class="chip chip-un" title="最后一段尚未被特征序列分型确认,信号可能重绘或消失">未确认 · 可能重绘</span>');
    if (!g.recent) out.push('<span class="chip chip-stale" title="超出近期窗口">已过期</span>');
    if (opts.res && g.resonance) out.push('<span class="chip chip-res-' + esc(g.resonance) + '" title="与更大级别的共振">' + esc(RES[g.resonance] || g.resonance) + '</span>');
    return '<div class="chips">' + out.join("") + '</div>';
  }

  // ---------- 状态 ----------
  var D = null, SIGS = [], F = loadFilters(), MODE = lsGet(LS.mode) === "table" ? "table" : "cards", VIEW = "signals";
  var POSDATA = null, HELD = {};  // IBKR positions (public /api/positions), HELD: symbol -> position
  var lastFocus = null, current = null;

  function loadFilters() {
    var f = {}, k;
    for (k in DEFAULT_F) f[k] = DEFAULT_F[k];
    try { var s = JSON.parse(lsGet(LS.filters) || "{}"); for (k in DEFAULT_F) if (s[k] !== undefined && typeof s[k] === typeof DEFAULT_F[k]) f[k] = s[k]; } catch (e) { }
    return f;
  }
  function saveFilters() { lsSet(LS.filters, JSON.stringify(F)); }
  function allSymbols() {
    var set = {}, i, s, keys, wl = MK[MARKET].watch;
    for (i = 0; i < wl.length; i++) set[wl[i]] = true;
    if (D && D.symbols) { keys = Object.keys(D.symbols); for (i = 0; i < keys.length; i++) set[keys[i]] = true; }
    return Object.keys(set).sort();
  }

  // ---------- 主题 ----------
  var root = document.documentElement;
  // 配色固定为绿买红卖(美股习惯),2026-10-13 起不再提供切换
  root.setAttribute("data-color", "us");
  function applyThemeMeta() {
    var m = document.querySelector('meta[name="theme-color"]');
    if (m) m.setAttribute("content", root.getAttribute("data-theme") === "light" ? "#f4f6fa" : "#0b0f17");
    $("btn-theme").setAttribute("aria-pressed", root.getAttribute("data-theme") === "light" ? "true" : "false");
  }
  $("btn-theme").addEventListener("click", function () {
    var t = root.getAttribute("data-theme") === "light" ? "dark" : "light";
    root.setAttribute("data-theme", t); lsSet(LS.theme, t); applyThemeMeta();
    if (window.ChanInteractive) ChanInteractive.refreshTheme();
    toast(t === "light" ? "已切换为浅色主题" : "已切换为深色主题");
  });
  applyThemeMeta();

  var toastTimer;
  function toast(msg) {
    var t = $("toast"); t.textContent = msg; t.hidden = false;
    clearTimeout(toastTimer); toastTimer = setTimeout(function () { t.hidden = true; }, 2200);
  }

  // ---------- 设置面板 (iOS 风格) ----------
  var SCORE_KEY = "chan.scoreThreshold", SHOWLOW_KEY = "chan.showLow";
  function getThreshold() {
    var v = parseFloat(localStorage.getItem(SCORE_KEY));
    return isNaN(v) ? 3 : v;
  }
  function getShowLow() {
    return localStorage.getItem(SHOWLOW_KEY) === "1";
  }
  function applyScoreFilter() {
    var th = getThreshold(), showLow = getShowLow();
    F.min = showLow ? 0 : th;
    $("score-threshold").value = th;
    $("score-val").textContent = th.toFixed(1) + " 分以下隐藏";
    $("score-filter-toggle").setAttribute("aria-checked", showLow ? "true" : "false");
    renderSignals();
  }
  function openSettings() {
    $("settings-sheet").hidden = false;
    $("settings-scrim").hidden = false;
    // force reflow for transition
    void $("settings-sheet").offsetWidth;
  }
  function closeSettings() {
    $("settings-sheet").hidden = true;
    $("settings-scrim").hidden = true;
  }
  $("btn-settings").addEventListener("click", openSettings);
  $("settings-close").addEventListener("click", closeSettings);
  $("settings-scrim").addEventListener("click", closeSettings);
  $("score-threshold").addEventListener("input", function () {
    var v = parseFloat(this.value);
    localStorage.setItem(SCORE_KEY, v);
    // 如果用户拖动滑块，自动开启过滤（关闭"显示低分"）
    if (getShowLow()) {
      localStorage.setItem(SHOWLOW_KEY, "0");
    }
    applyScoreFilter();
  });
  $("score-filter-toggle").addEventListener("click", function () {
    var showLow = !getShowLow();
    localStorage.setItem(SHOWLOW_KEY, showLow ? "1" : "0");
    applyScoreFilter();
    toast(showLow ? "已显示全部信号" : "已隐藏低分信号");
  });
  // 初始化：应用保存的阈值
  (function initScoreFilter() {
    F.min = getShowLow() ? 0 : getThreshold();
  })();
  // ---------- 导航 ----------
  function setView(v, noHash) {
    if (["signals", "symbols", "holdings", "macro", "about"].indexOf(v) < 0) v = "signals";
    VIEW = v;
    ["signals", "symbols", "holdings", "macro", "about"].forEach(function (x) { $("view-" + x).hidden = x !== v; });
    qsa(".tab[data-view]").forEach(function (b) {
      if (b.getAttribute("data-view") === v) b.setAttribute("aria-current", "page"); else b.removeAttribute("aria-current");
    });
    if (!noHash && location.hash.slice(1) !== v) history.replaceState(null, "", "#" + v);
    if (v === "symbols" && D) renderSymbols();
    if (v === "holdings") renderHoldings();
    if (v === "macro") renderMacro();
    var kp = $("kpis"); if (kp) kp.style.display = (v === "holdings") ? "none" : "";
  }
  qsa(".tab[data-view]").forEach(function (b) {
    b.addEventListener("click", function () { setView(b.getAttribute("data-view")); window.scrollTo({ top: 0, behavior: "smooth" }); });
  });
  window.addEventListener("hashchange", function () { setView(location.hash.slice(1), true); });

  // ---------- 市场切换(美股 / A股) ----------
  function updateMarketTexts() {
    var about = $("about-src");
    if (about) about.textContent = "行情来自 " + MK[MARKET].src + "。信号时间为极值K线时间(" + MK[MARKET].tz + "),确认会滞后若干根K线。周线最后一根为当周未完成K线。";
    var ff = $("foot-syms");
    if (ff) ff.textContent = MK[MARKET].watch.length + " 个" + (MARKET === "cn" ? "指数" : "标的") + "均为可缩放交互 K 线(Lightweight Charts,叠加笔/线段/中枢)。箭头=缠论一二三类买卖点;青绿/琥珀圆点=中枢下沿买/上沿卖。静态 PNG 可在详情中展开对照。";
    var disc = $("foot-disc-src");
    if (disc) disc.textContent = "数据源 " + MK[MARKET].src + ",可能延迟或缺失。";
  }
  function syncMarketUI() {
    qsa("[data-market]").forEach(function (b) {
      b.setAttribute("aria-pressed", b.getAttribute("data-market") === MARKET ? "true" : "false");
    });
    var q = $("f-q"); if (q) q.setAttribute("placeholder", MK[MARKET].searchPh);
    updateMarketTexts();
  }
  function switchMarket(m) {
    if (!MK[m] || m === MARKET) { syncMarketUI(); return; }
    MARKET = m; lsSet("chan.market", m);
    if (window.ChanInteractive && ChanInteractive.setMarket) ChanInteractive.setMarket(m);
    F.q = "";
    closeDrawer();
    syncMarketUI();
    load();
  }
  qsa("[data-market]").forEach(function (b) {
    b.addEventListener("click", function () { switchMarket(b.getAttribute("data-market")); window.scrollTo({ top: 0, behavior: "smooth" }); });
  });

  // ---------- 筛选控件 ----------
  function syncControls() {
    $("f-q").value = F.q;
    $("f-type").value = F.type;
    $("f-min").value = F.min; $("f-min-out").textContent = (+F.min).toFixed(1);
    $("f-recent").checked = !!F.recent;
    $("f-sort").value = F.sort;
    var d = $("f-dir"); d.setAttribute("data-dir", F.dir);
    d.setAttribute("aria-label", "排序方向:" + (F.dir === "desc" ? "降序" : "升序") + ",点击切换");
    d.style.transform = F.dir === "asc" ? "scaleY(-1)" : "";
    qsa(".chips-group").forEach(function (g) {
      var key = g.getAttribute("data-filter");
      qsa(".fchip", g).forEach(function (b) { b.setAttribute("aria-pressed", b.getAttribute("data-v") === F[key] ? "true" : "false"); });
    });
    qsa(".seg-btn").forEach(function (b) { b.setAttribute("aria-pressed", b.getAttribute("data-mode") === MODE ? "true" : "false"); });
    var n = 0;
    ["q", "level", "type", "conf"].forEach(function (k) { if (F[k]) n++; });
    if (+F.min > 0) n++; if (F.recent !== DEFAULT_F.recent) n++;
    var bd = $("filter-badge"); bd.hidden = !n; bd.textContent = n;
  }
  function onFilter() { saveFilters(); syncControls(); renderSignals(); }
  $("f-q").addEventListener("input", function () { F.q = this.value.trim(); onFilter(); });
  $("f-type").addEventListener("change", function () { F.type = this.value; onFilter(); });
  $("f-min").addEventListener("input", function () { F.min = +this.value; onFilter(); });
  $("f-recent").addEventListener("change", function () { F.recent = this.checked; onFilter(); });
  $("f-sort").addEventListener("change", function () { F.sort = this.value; F.dir = (F.sort === "symbol" || F.sort === "bars_ago") ? "asc" : "desc"; onFilter(); });
  $("f-dir").addEventListener("click", function () { F.dir = F.dir === "desc" ? "asc" : "desc"; onFilter(); });
  $("f-reset").addEventListener("click", resetFilters);
  qsa(".chips-group").forEach(function (g) {
    g.addEventListener("click", function (e) {
      var b = e.target.closest(".fchip"); if (!b) return;
      F[g.getAttribute("data-filter")] = b.getAttribute("data-v"); onFilter();
    });
  });
  qsa(".seg-btn").forEach(function (b) {
    b.addEventListener("click", function () { MODE = b.getAttribute("data-mode"); lsSet(LS.mode, MODE); syncControls(); renderSignals(); });
  });
  $("btn-filters").addEventListener("click", function () {
    var f = $("filters"), open = !f.classList.contains("open");
    f.classList.toggle("open", open); this.setAttribute("aria-expanded", open ? "true" : "false");
  });
  function resetFilters() {
    for (var k in DEFAULT_F) F[k] = DEFAULT_F[k];
    onFilter();
  }

  // ---------- 数据 ----------
  function showLoading() {
    $("sig-results").innerHTML = '<div class="cards" aria-busy="true" aria-label="加载中">' +
      new Array(7).join('<div class="skel-card skeleton"></div>') + '</div>';
  }
  function handleData(d) {
    if (!d || !Array.isArray(d.signals) || !d.symbols) throw new Error("数据格式不正确");
    D = d;
    SIGS = d.signals.filter(function (g) { return g && g.symbol && g.type; }).map(function (g, i) {
      g._id = i; g.score = num(g.score, 0);
      if (!g.kind) g.kind = (g.type === "ZG_S" || g.type === "ZD_B") ? "pivot_edge" : "chan";
      return g;
    });
    init();
  }
  function showLoadErr(e, url) {
    $("meta-short").textContent = "数据加载失败";
    qsa("#meta-sub .dot").forEach(function (x) { x.className = "dot err"; });
    $("kpis").innerHTML = "";
    $("sig-results").innerHTML = stateHTML("err", "数据加载失败", "后端接口不可用（" + esc(e.message || e) + "）—— 已不再回落到本地静态数据，以免展示过期行情。请检查后端 chan-api 与 /api 状态（请求地址：" + esc(url) + "）。", '<button type="button" class="btn primary" id="retry">重试</button>');
    var r = $("retry"); if (r) r.addEventListener("click", load);
  }
  function load() {
    showLoading();
    $("meta-short").textContent = "加载中…";
    var apiU = apiURL() + "?t=" + Date.now();
    function getJSON(u) {
      return fetch(u, { cache: "no-store" })
        .then(function (r) { if (!r.ok) throw new Error("HTTP " + r.status); return r.json(); });
    }
    // 只请求后端 API；失败直接报错，不再回落到本地静态 JSON，以免展示过期行情
    getJSON(apiU).then(handleData).catch(function (e) { showLoadErr(e, apiU); });
  }

  function stateHTML(kind, title, text, action) {
    var ico = kind === "err"
      ? '<svg viewBox="0 0 24 24" width="26" height="26" aria-hidden="true"><circle cx="12" cy="12" r="9" fill="none" stroke="currentColor" stroke-width="2"/><path d="M12 7v6M12 16.5v.01" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"/></svg>'
      : '<svg viewBox="0 0 24 24" width="26" height="26" aria-hidden="true"><circle cx="11" cy="11" r="7" fill="none" stroke="currentColor" stroke-width="2"/><path d="M20 20l-4-4M8 11h6" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>';
    return '<div class="state ' + kind + '" role="' + (kind === "err" ? "alert" : "status") + '"><div class="state-ico">' + ico + '</div><h3>' + title + '</h3><p>' + text + '</p>' + (action || "") + '</div>';
  }

  function init() {
    var gen = new Date(D.generated);
    var ok = !isNaN(gen.getTime());
    var ageH = ok ? (Date.now() - gen.getTime()) / 36e5 : 999;
    $("meta-short").textContent = ok ? "更新于 " + relTime(gen) + " · " + gen.toLocaleString("zh-CN", { hour12: false, month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" }) : "更新时间未知";
    qsa("#meta-sub .dot").forEach(function (x) { x.className = "dot" + (ageH > 72 ? " stale" : " pulse"); });
    var symsAll = allSymbols();
    $("foot-meta").textContent = "数据生成时间(UTC):" + (D.generated || "").slice(0, 19).replace("T", " ") + " · 标的 " + symsAll.length + " 个 · 信号 " + SIGS.length + " 条 · 分数为启发式 0–10,不是胜率。";
    var dl = $("sym-list");
    dl.innerHTML = symsAll.map(function (s) { return '<option value="' + esc(s) + '">'; }).join("");
    renderKPIs(gen, ok, ageH);
    renderFailures();
    syncControls();
    renderSignals();
    renderSymbols();
    try { loadPositions(); } catch (e) { /* 持仓加载失败不影响信号看板 */ }
  }

  // ---------- 持仓 ----------
  function positionsURL() { return (API_BASE || "") + "/api/positions"; }
  function loadPositions() {
    fetch(positionsURL() + "?t=" + Date.now(), { cache: "no-store" })
      .then(function (r) { if (!r.ok) throw new Error("HTTP " + r.status); return r.json(); })
      .then(function (d) {
        try {
          POSDATA = d; HELD = {};
          (d.positions || []).forEach(function (p) { if (p && p.symbol) HELD[p.symbol] = p; });
          renderHoldings();
          if (VIEW === "symbols" && D) renderSymbols();  // refresh 持有 badges
        } catch (e) { /* 持仓渲染失败不影响信号看板 */ }
      })
      .catch(function () { renderHoldings(); });  // 持仓缺失不影响主流程
  }
  function fmtReportDate(s) {
    s = String(s || "");
    return s.length === 8 ? s.slice(0, 4) + "-" + s.slice(4, 6) + "-" + s.slice(6, 8) : s;
  }
  // ---------- 大环境 ----------
  var MACRO = null, EVENTS = null, macroLoading = false;
  var TX_SEL = { node: null, edge: -1, theme: "all" };
  var TX_THEMES = [
    { id: "rate", label: "利率" }, { id: "infl", label: "通胀" }, { id: "jobs", label: "就业" },
    { id: "usd", label: "美元" }, { id: "liq", label: "流动性" }, { id: "growth", label: "增长" }
  ];
  // 传导画布：节点。kind: src=源头变量 / mech=传导机制 / asset=资产。
  // live: 对应 macro.json 里的 indicator key（有则显示实时值），null = 理论框架节点（暂无实时数据）。
  var TX_NODES = [
    { id: "n_infl", label: "通胀超预期", layer: 0, x: 100, y: 70, theme: "infl", kind: "src",
      def: "CPI / PCE 实际值高于市场预期。",
      meaning: "通胀高于预期会压缩美联储的降息空间，是利率与债券定价的关键变量。注意区分 headline 与核心分项：食品能源波动常主导 headline，核心分项更能反映持续性。",
      live: null, liveNote: "CPI / PCE 实际值未接入（接口扩展点），本节点为理论传导框架。" },
    { id: "n_jobs", label: "就业数据走弱", layer: 0, x: 100, y: 190, theme: "jobs", kind: "src",
      def: "非农就业低于预期，或失业率上升。",
      meaning: "就业走弱有两条相反的链：降息预期增强（支撑估值）与盈利预期下降（压制股价）。哪条主导取决于通胀是否构成约束，以及走弱是降温还是衰退信号。",
      live: null, liveNote: "NFP 实际值未接入，下次公布见下方数据日历。" },
    { id: "n_yield", label: "美债收益率上行", layer: 0, x: 100, y: 310, theme: "rate", kind: "src",
      def: "10 年期美债收益率上升。",
      meaning: "美债收益率是全球资产定价的锚。10Y 上行直接抬高无风险利率，并通过利差吸引资金流向美元。",
      live: "us10y", liveNote: "" },
    { id: "n_liq", label: "流动性收紧", layer: 0, x: 100, y: 430, theme: "liq", kind: "src",
      def: "资金成本上升、信用利差走阔、融资可得性下降。",
      meaning: "流动性收紧通过融资成本传导到企业扩张、回购与高杠杆主体；信用利差是比政策利率更直接的观测指标。",
      live: null, liveNote: "流动性指标未接入（接口扩展点：准备金余额 / 逆回购 / 信用利差）。" },
    { id: "n_growth", label: "经济增长放缓", layer: 0, x: 100, y: 540, theme: "growth", kind: "src",
      def: "GDP 增速放缓、PMI 跌破荣枯线。",
      meaning: "增长放缓压制企业盈利预期；但若同时缓解通胀压力，也可能打开降息空间。铜价是常用代理指标，但不是增长本身。",
      live: "copper", liveNote: "以铜价为代理指标（非 GDP 本身）。" },
    { id: "n_cut", label: "降息预期下调", layer: 1, x: 350, y: 100, theme: "rate", kind: "mech",
      def: "市场下调未来 12 个月降息次数 / 幅度预期。",
      meaning: "降息预期是连接通胀与利率的枢纽：它同时影响远端利率、美元与估值。",
      live: null, liveNote: "降息概率（CME FedWatch）未接入，需手动查看。" },
    { id: "n_cutup", label: "降息预期增强", layer: 1, x: 350, y: 250, theme: "rate", kind: "mech",
      def: "市场提高未来降息预期。",
      meaning: "降息预期增强降低折现率、支撑估值；但如果源于衰退担忧，盈利端的压力可能更大。",
      live: null, liveNote: "降息概率（CME FedWatch）未接入，需手动查看。" },
    { id: "n_dxy", label: "美元走强", layer: 1, x: 350, y: 400, theme: "usd", kind: "mech",
      def: "美元指数 DXY 上行。",
      meaning: "美元走强通常与美债收益率上行同步（利差驱动），对以美元计价的商品与跨国公司盈利构成压力。",
      live: "dxy", liveNote: "" },
    { id: "n_rf", label: "无风险利率提高", layer: 1, x: 350, y: 540, theme: "rate", kind: "mech",
      def: "折现公式中的无风险利率上升。",
      meaning: "折现率 = 无风险利率 + 风险溢价。前者上升时，即使风险溢价不变，估值也会承压。",
      live: "us10y", liveNote: "以 10Y 收益率为代理。" },
    { id: "n_disc", label: "折现价值下降", layer: 2, x: 620, y: 110, theme: "rate", kind: "mech",
      def: "未来现金流按更高折现率折现，现值下降。",
      meaning: "远期现金流占比越高的资产对折现率越敏感——这是成长股、科技股对利率最敏感的数学原因。",
      live: null, liveNote: "机制节点，无直接实时数据。" },
    { id: "n_earn", label: "盈利预期下降", layer: 2, x: 620, y: 260, theme: "growth", kind: "mech",
      def: "市场下调企业未来盈利预期。",
      meaning: "盈利预期是股价的核心支撑。增长放缓与就业走弱都会压制盈利预期；需结合营收、利润率与指引一起看。",
      live: null, liveNote: "盈利预期（分析师一致预期）未接入。" },
    { id: "n_safe", label: "避险需求上升", layer: 2, x: 620, y: 410, theme: "liq", kind: "mech",
      def: "资金从风险资产流向避险资产。",
      meaning: "避险升温时黄金、美元、日元与美债通常受益；但若避险源于利率冲击，美债价格也可能下跌（股债双杀）。",
      live: "gold", liveNote: "以黄金涨幅为代理信号。" },
    { id: "n_fin", label: "融资成本上升", layer: 2, x: 620, y: 540, theme: "liq", kind: "mech",
      def: "企业与居民的融资利率上升。",
      meaning: "融资成本上升压制资本开支、回购与高杠杆主体；信用利差走阔是融资条件恶化的直接信号。",
      live: null, liveNote: "信用利差未接入（接口扩展点）。" },
    { id: "n_tech", label: "科技成长股（纳指）", layer: 3, x: 880, y: 70, theme: "growth", kind: "asset",
      def: "纳斯达克 100 为代表的高成长科技股。",
      meaning: "对折现率与风险偏好双重敏感：利率上行压制估值，盈利预期下调压制股价；两者叠加时跌幅放大。",
      live: null, liveNote: "指数实时行情未接入；本站美股信号页有成分股信号。" },
    { id: "n_spx", label: "标普 500", layer: 3, x: 880, y: 170, theme: "growth", kind: "asset",
      def: "标普 500 指数，覆盖全市场大盘股。",
      meaning: "盈利预期与估值的综合反映；行业结构决定它对利率与增长的敏感度介于成长与价值之间。",
      live: null, liveNote: "指数实时行情未接入。" },
    { id: "n_semi", label: "半导体（NVDA / MU）", layer: 3, x: 880, y: 270, theme: "growth", kind: "asset",
      def: "半导体板块，本站覆盖 NVDA、MU 等。",
      meaning: "资本开支大、盈利周期长，对折现率敏感；AI 资本开支周期可部分对冲利率压力，但订单与库存周期仍主导中期走势。",
      live: null, liveNote: "个股信号见本站美股页。" },
    { id: "n_gold", label: "黄金", layer: 3, x: 880, y: 370, theme: "liq", kind: "asset",
      def: "COMEX 黄金期货。",
      meaning: "避险与通胀对冲资产，但受实际利率与美元压制：避险升温利多，实际利率上行利空，两者常同时出现，需看哪边更强。",
      live: "gold", liveNote: "" },
    { id: "n_bond", label: "美债价格", layer: 3, x: 880, y: 470, theme: "rate", kind: "asset",
      def: "美国国债价格（与收益率反向变动）。",
      meaning: "收益率上行 → 价格下跌；久期越长跌幅越大。避险买入通常支撑债价，但利率冲击引发的避险可能出现股债双杀。",
      live: "us10y", liveNote: "以 10Y 收益率反向推断（收益率↑ → 价格↓）。" },
    { id: "n_acn", label: "A股成长（科创50）", layer: 3, x: 880, y: 550, theme: "growth", kind: "asset",
      def: "科创 50 为代表的 A 股高成长板块。",
      meaning: "传导是间接的：全球估值锚与风险偏好影响外资与情绪，但国内政策、流动性与基本面往往起更大作用。不能把美债传导直接等同于 A 股涨跌。",
      live: null, liveNote: "指数信号见本站 A 股页。" }
  ];
  // 传导边。sign: plus=促进 / minus=抑制 / unk=不确定。dir: 对目标端资产的方向提示（— = 机制边，无直接资产方向）。
  var TX_EDGES = [
    { from: "n_infl", to: "n_cut", sign: "plus", mech: "通胀高于预期，美联储缺乏降息空间。", cond: "核心分项同样走强时更成立；若仅食品能源波动，持续性存疑。", dir: "—" },
    { from: "n_cut", to: "n_rf", sign: "plus", mech: "降息预期下调 → 远端利率上行。", cond: "市场定价已充分反映时，影响减弱。", dir: "—" },
    { from: "n_yield", to: "n_rf", sign: "plus", mech: "10Y 上行直接抬高无风险利率。", cond: "—", dir: "—" },
    { from: "n_cut", to: "n_dxy", sign: "plus", mech: "降息预期下调 → 美债相对吸引力上升 → 资金流入美元。", cond: "利差扩大是关键中介。", dir: "—" },
    { from: "n_yield", to: "n_dxy", sign: "plus", mech: "美债收益率上行扩大与他国利差。", cond: "—", dir: "—" },
    { from: "n_yield", to: "n_bond", sign: "minus", mech: "收益率与债券价格反向变动。", cond: "久期越长，价格跌幅越大。", dir: "利空（债价）" },
    { from: "n_jobs", to: "n_cutup", sign: "plus", mech: "就业降温降低通胀压力，增强降息预期。", cond: "通胀不构成约束时；若通胀仍高，就业降温未必换来降息。", dir: "—" },
    { from: "n_jobs", to: "n_earn", sign: "plus", mech: "就业走弱 → 消费与企业盈利预期下调。", cond: "走弱是降温还是衰退信号，决定幅度。", dir: "—" },
    { from: "n_jobs", to: "n_safe", sign: "plus", mech: "增长担忧 → 避险需求。", cond: "避险情绪主导时。", dir: "—" },
    { from: "n_cutup", to: "n_disc", sign: "minus", mech: "降息预期增强 → 折现率下行 → 抑制折现价值下降。", cond: "若衰退担忧同时推高风险溢价，对冲甚至反转。", dir: "—" },
    { from: "n_rf", to: "n_disc", sign: "plus", mech: "折现率 = 无风险利率 + 风险溢价。", cond: "风险溢价不变时。", dir: "—" },
    { from: "n_disc", to: "n_tech", sign: "minus", mech: "成长股远期现金流占比高，对折现率最敏感。", cond: "风险溢价同步回落可对冲。", dir: "利空" },
    { from: "n_disc", to: "n_semi", sign: "minus", mech: "半导体资本开支大、盈利周期长，折现敏感。", cond: "AI 资本开支周期可部分对冲。", dir: "利空" },
    { from: "n_disc", to: "n_acn", sign: "minus", mech: "全球估值锚同步上移时传导。", cond: "A 股还受国内政策与流动性影响，传导不完全。", dir: "不确定" },
    { from: "n_earn", to: "n_spx", sign: "minus", mech: "盈利预期是股价的核心支撑。", cond: "估值已提前下调时，影响减弱。", dir: "利空" },
    { from: "n_earn", to: "n_tech", sign: "minus", mech: "科技股盈利预期下调 → 估值与盈利双杀风险。", cond: "个股指引分化时需逐个看。", dir: "利空" },
    { from: "n_safe", to: "n_gold", sign: "plus", mech: "避险资金流向黄金。", cond: "实际利率同步上行时会削弱黄金吸引力。", dir: "利多（黄金）" },
    { from: "n_safe", to: "n_spx", sign: "minus", mech: "风险偏好下降 → 风险资产承压。", cond: "避险情绪主导时。", dir: "利空" },
    { from: "n_dxy", to: "n_gold", sign: "minus", mech: "美元走强 → 以美元计价的黄金承压。", cond: "实际利率同步上行时更明显。", dir: "利空（黄金）" },
    { from: "n_dxy", to: "n_tech", sign: "minus", mech: "美元走强 → 跨国公司汇兑压力 + 全球流动性收紧。", cond: "持续走强时。", dir: "利空" },
    { from: "n_growth", to: "n_earn", sign: "plus", mech: "增长放缓 → 盈利预期下调。", cond: "需看是需求放缓还是供给冲击。", dir: "—" },
    { from: "n_liq", to: "n_fin", sign: "plus", mech: "流动性收紧 → 融资成本上升。", cond: "信用利差走阔是直接信号。", dir: "—" },
    { from: "n_fin", to: "n_tech", sign: "minus", mech: "高投入、高杠杆企业承压。", cond: "现金流充裕的龙头相对抗压。", dir: "利空" },
    { from: "n_fin", to: "n_spx", sign: "minus", mech: "融资成本上升压制回购与扩张。", cond: "信用利差同步走阔时。", dir: "利空" }
  ];
  // 数据公布解读：next: events=从 events.json 取排期 / nfp=规则生成 / none=见官方日历。
  var RELEASES = [
    { id: "cpi", name: "CPI / 核心 CPI", next: "events", nextType: "CPI",
      measures: "衡量居民消费价格水平；核心 CPI 剔除食品与能源，更能反映持续性通胀。",
      why: "美联储 2% 通胀目标的参考锚；债券与股票的定价都受它影响。",
      up: "通胀压力可能持续 → 降息预期可能减弱 → 利率可能上行 → 美元可能走强、成长股可能承压",
      upNote: "核心分项同步走强时更可信。",
      mid: "观察市场是否已提前定价 → 关注核心分项趋势与前值修正",
      down: "通胀压力可能缓和 → 降息预期可能增强 → 利率可能下行",
      reversals: ["headline 与核心分项背离（如仅食品能源波动）", "前值大幅修正改变趋势判断", "市场已提前定价或仓位拥挤 → 公布后反向波动"],
      watch: ["核心 CPI", "PCE", "10Y 收益率反应", "美联储官员表态"] },
    { id: "pce", name: "PCE / 核心 PCE", next: "none", nextNote: "BEA 官方日历（每月下旬）",
      measures: "个人消费支出价格指数；美联储首选的通胀指标，权重与统计方法与 CPI 不同。",
      why: "美联储政策框架直接盯住 PCE；比 CPI 更能反映消费者替代行为。",
      up: "通胀粘性可能超预期 → 降息预期可能减弱 → 利率可能上行",
      upNote: "与 CPI 背离时，以 PCE 为准。",
      mid: "关注核心 PCE 的 3 个月年化趋势，比单月 headline 更有信息量",
      down: "通胀压力缓和 → 降息预期可能增强",
      reversals: ["与 CPI 背离", "权重调整与历史修正"],
      watch: ["核心 PCE", "CPI", "美联储表态"] },
    { id: "nfp", name: "非农就业（NFP）", next: "nfp", nextType: "",
      measures: "新增非农就业人数、失业率、平均时薪。",
      why: "增长与通胀的双重信号：就业韧性支撑盈利，但也限制降息空间。",
      up: "增长韧性 → 降息预期可能减弱（利空利率敏感资产），但盈利预期获支撑（利多股价）→ 净方向取决于哪条链主导",
      upNote: "高于预期不是单向利空。",
      mid: "关注失业率与时薪是否同步",
      down: "双链并行：降息预期增强（支撑估值）与盈利预期下降（压制股价）→ 净方向看通胀约束与衰退担忧",
      reversals: ["失业率与新增就业背离", "前值大幅修正", "平均时薪超预期 → 通胀担忧盖过就业降温"],
      watch: ["失业率", "平均时薪", "劳动参与率", "前值修正"] },
    { id: "unemp", name: "失业率", next: "nfp", nextType: "",
      measures: "劳动力中失业人口占比。",
      why: "就业市场松紧的核心指标；萨姆规则（Sahm Rule）用失业率变化预警衰退。",
      up: "失业率上升 → 增长担忧 → 盈利预期承压",
      upNote: "失业率上升是本项的“差”方向。",
      mid: "关注失业率变化的方向与幅度，而非单月绝对值",
      down: "失业率下降 → 就业韧性 → 降息空间受限",
      reversals: ["劳动参与率变化扭曲失业率（分母效应）", "失业率上升但新增就业仍强"],
      watch: ["新增就业", "劳动参与率", "平均时薪"] },
    { id: "gdp", name: "GDP", next: "none", nextNote: "BEA 官方日历（季度）",
      measures: "国内生产总值，衡量经济总产出。",
      why: "增长动能的最终验证；决定盈利预期与衰退判断。",
      up: "超预期 → 增长韧性 → 利率上行压力",
      upNote: "",
      mid: "区分 headline 与最终销售：库存与净出口常扭曲单季读数",
      down: "低于预期 → 衰退担忧 → 降息预期增强但盈利承压",
      reversals: ["库存与净出口扭曲 headline，应看最终销售", "提前值 / 修正值差异"],
      watch: ["个人消费支出", "最终销售", "PMI"] },
    { id: "pmi", name: "ISM 制造业 / 服务业 PMI", next: "none", nextNote: "ISM 官方日历（每月初）",
      measures: "采购经理人指数；50 为荣枯线。",
      why: "领先于 GDP 的景气信号；新订单分项比 headline 更领先。",
      up: "高于 50 且回升 → 扩张 → 增长预期改善",
      upNote: "",
      mid: "在 50 附近徘徊时，关注新订单分项的方向",
      down: "跌破 50 → 收缩 → 增长担忧",
      reversals: ["新订单与 headline 背离", "价格分项走强 → 通胀压力"],
      watch: ["新订单分项", "价格分项", "就业分项"] },
    { id: "fomc", name: "美联储利率决议", next: "events", nextType: "FOMC",
      measures: "政策利率决定 + 声明 + 点阵图 + 新闻发布会。",
      why: "直接决定利率路径；声明措辞与点阵图常比决议本身更重要。",
      up: "鹰派（higher for longer）→ 降息预期下调 → 利率上行",
      upNote: "“鹰派”对应本项的“超预期紧缩”方向。",
      mid: "符合预期 → 关注声明措辞与点阵图变化",
      down: "鸽派 → 降息预期增强 → 利率下行",
      reversals: ["声明措辞与发布会口径背离", "点阵图变化超预期", "市场已提前定价"],
      watch: ["点阵图", "鲍威尔发布会", "10Y 与美元反应"] }
  ];
  // 影响矩阵：dir: neg=偏利空 / pos=偏利多 / unk=不确定 / na=不适用。均为理论传导方向（条件成立时），非预测。
  var MATRIX_FACTORS = [
    { id: "rate", label: "利率上行", live: "us10y" },
    { id: "infl", label: "通胀超预期", live: null },
    { id: "jobs", label: "就业走弱", live: null },
    { id: "dxy", label: "美元走强", live: "dxy" },
    { id: "safe", label: "避险升温", live: "gold" }
  ];
  var MATRIX_ASSETS = [
    { id: "nasdaq", label: "纳指 100", cells: {
      rate: { dir: "neg", note: "折现敏感" }, infl: { dir: "neg", note: "降息预期下调" },
      jobs: { dir: "unk", note: "降息支撑 vs 盈利压力" }, dxy: { dir: "neg", note: "汇兑 + 流动性" },
      safe: { dir: "neg", note: "风险偏好下降" } } },
    { id: "spx", label: "标普 500", cells: {
      rate: { dir: "neg", note: "估值承压" }, infl: { dir: "neg", note: "降息预期下调" },
      jobs: { dir: "unk", note: "降息支撑 vs 盈利压力" }, dxy: { dir: "neg", note: "汇兑压力" },
      safe: { dir: "neg", note: "风险偏好下降" } } },
    { id: "semi", label: "半导体 NVDA / MU", cells: {
      rate: { dir: "neg", note: "折现 + 资本开支" }, infl: { dir: "neg", note: "降息预期下调" },
      jobs: { dir: "unk", note: "需求 vs 降息" }, dxy: { dir: "neg", note: "汇兑压力" },
      safe: { dir: "neg", note: "风险偏好下降" } } },
    { id: "sse", label: "上证指数", cells: {
      rate: { dir: "unk", note: "间接：全球风险偏好 + 汇率" }, infl: { dir: "unk", note: "输入性通胀 vs 国内需求" },
      jobs: { dir: "unk", note: "外需" }, dxy: { dir: "neg", note: "汇率 + 外资流出压力" },
      safe: { dir: "unk", note: "外资流出，但国内政策可对冲" } } },
    { id: "star", label: "科创 50", cells: {
      rate: { dir: "unk", note: "全球估值锚 + 国内流动性" }, infl: { dir: "unk", note: "间接" },
      jobs: { dir: "unk", note: "外需" }, dxy: { dir: "neg", note: "汇率 + 外资" },
      safe: { dir: "unk", note: "风险偏好 + 国内政策" } } },
    { id: "gold", label: "黄金", cells: {
      rate: { dir: "neg", note: "实际利率上行压制" }, infl: { dir: "pos", note: "通胀对冲（长期；短期受实际利率主导）" },
      jobs: { dir: "pos", note: "避险 + 降息预期" }, dxy: { dir: "neg", note: "美元计价" },
      safe: { dir: "pos", note: "避险首选" } } },
    { id: "usd", label: "美元", cells: {
      rate: { dir: "pos", note: "利差驱动" }, infl: { dir: "pos", note: "降息预期下调" },
      jobs: { dir: "neg", note: "降息预期增强" }, dxy: { dir: "na", note: "—" },
      safe: { dir: "pos", note: "避险货币" } } },
    { id: "bond", label: "美债价格", cells: {
      rate: { dir: "neg", note: "收益率↑ → 价格↓" }, infl: { dir: "neg", note: "降息预期下调" },
      jobs: { dir: "pos", note: "降息预期增强" }, dxy: { dir: "unk", note: "间接" },
      safe: { dir: "unk", note: "避险买入 vs 利率冲击（股债双杀时失效）" } } }
  ];
  // 待接入指标：接口扩展点，不展示任何数值。
  var MACRO_PENDING = [
    { name: "2 年期美债收益率", note: "扩展点：Yahoo 无干净标的，需 FRED 等来源" },
    { name: "CPI / 核心 CPI", note: "扩展点：BLS 公布值与市场预期" },
    { name: "PCE / 核心 PCE", note: "扩展点：BEA 公布值与市场预期" },
    { name: "非农就业 / 失业率 / 初请失业金", note: "扩展点：BLS 公布值与市场预期" },
    { name: "GDP", note: "扩展点：BEA 季度值" },
    { name: "ISM 制造业 / 服务业 PMI", note: "扩展点：ISM 公布值" },
    { name: "美联储政策利率 / 降息预期", note: "扩展点：FOMC 决议 + CME FedWatch" },
    { name: "流动性（准备金 / 逆回购 / 信用利差）", note: "扩展点：美联储 H.4.1 / 信用利差" }
  ];

  function loadMacro() {
    if (macroLoading) return; macroLoading = true;
    function gj(u) { return fetch(u, { cache: "no-store" }).then(function (r) { if (!r.ok) throw new Error("HTTP " + r.status); return r.json(); }); }
    Promise.all([gj("/api/macro").catch(function () { return null; }),
                 gj("data/events.json").catch(function () { return null; })])
      .then(function (res) { MACRO = res[0]; EVENTS = res[1]; renderMacro(); })
      .catch(function () { renderMacro(); })
      .finally(function () { macroLoading = false; });
  }
  function fmtMacroVal(ind) {
    if (!ind || ind.value == null) return "—";
    var v = ind.value;
    var s = (ind.kind === "yield" || ind.kind === "spread") ? v.toFixed(2) : (Math.abs(v) >= 1000 ? v.toLocaleString("en-US", { maximumFractionDigits: 2 }) : v.toFixed(2));
    return s + (ind.unit ? " " + ind.unit : "");
  }
  function fmtMacroRange(ind) {
    if (!ind || !ind.range || ind.value == null) return "";
    var lo = Math.min(ind.range[0], ind.value), hi = Math.max(ind.range[1], ind.value);
    return lo.toFixed(2) + " – " + hi.toFixed(2);
  }
  function nextFirstFridays() {
    // 非农就业: 每月第一个周五 (BLS 固定排期), 返回未来两个
    var out = [], d = new Date(); d.setHours(0, 0, 0, 0);
    for (var m = 0; m < 3 && out.length < 2; m++) {
      var y = d.getFullYear(), mo = d.getMonth() + m;
      var first = new Date(y, mo, 1);
      var off = (5 - first.getDay() + 7) % 7; // 周五=5
      var fri = new Date(y, mo, 1 + off);
      if (fri >= d) out.push(fri);
    }
    return out;
  }
  function daysUntil(ds) {
    var t = new Date(ds + "T00:00:00"), now = new Date(); now.setHours(0, 0, 0, 0);
    return Math.round((t - now) / 86400000);
  }
  /* 术语包装（薄调用；映射在 indicator-glossary.js。模块未加载时返回原文）。 */
  function glossaryTermSpan(mapName, key, labelHTML) {
    var G = window.Glossary;
    if (!G || !G[mapName] || !G.termSpan) return labelHTML;
    return G.termSpan(G[mapName], key, labelHTML);
  }
  function macroInd(key) {
    var inds = (MACRO && MACRO.indicators) || {};
    return inds[key] || null;
  }
  function macroSparkline(ind) {
    var s = ind && ind.series;
    if (!s || s.length < 2) return '<span class="muted small">历史走势待更新</span>';
    var w = 120, h = 28, vals = s.map(function (p) { return p[1]; });
    var lo = Math.min.apply(null, vals), hi = Math.max.apply(null, vals);
    var span = (hi - lo) || 1;
    var pts = s.map(function (p, i) {
      var x = (i / (s.length - 1)) * w;
      var y = h - 3 - ((p[1] - lo) / span) * (h - 6);
      return x.toFixed(1) + "," + y.toFixed(1);
    }).join(" ");
    var last = s[s.length - 1], first = s[0];
    var arrow = last[1] >= first[1] ? "▲" : "▼";
    return '<svg class="mspark" width="' + w + '" height="' + h + '" viewBox="0 0 ' + w + ' ' + h + '" role="img" aria-label="近 90 日走势">' +
      '<polyline class="mspark-poly" points="' + esc(pts) + '"/>' +
      '<circle class="mspark-dot" cx="' + w + '" cy="' + (h - 3 - ((last[1] - lo) / span) * (h - 6)).toFixed(1) + '" r="2"/></svg>' +
      '<span class="mspark-arrow muted small">' + arrow + '</span>';
  }
  function macroRowHTML(key) {
    var ind = macroInd(key);
    if (!ind) return "";
    if (ind.status !== "ok" || ind.value == null) {
      return '<div class="mrow" data-ind="' + esc(key) + '"><span class="mrow-name">' + glossaryTermSpan("MACRO_IND_GLOSSARY", key, esc(ind.name)) + '</span>' +
        '<span class="mrow-val muted">暂无数据</span><span class="mrow-spark muted small">—</span>' +
        '<span class="mrow-range muted small">—</span><span class="mrow-read">' + esc(ind.read || "") + '</span>' +
        '<span class="mrow-asof muted small">—</span></div>';
    }
    var chg = ind.change_label ? '<span class="mrow-chg">' + esc(ind.change_label) + ' 日</span>' : "";
    var wchg = ind.window_label ? '<span class="mrow-chg">' + esc(ind.window_label) + " 90日</span>" : "";
    return '<div class="mrow" data-ind="' + esc(key) + '"><span class="mrow-name">' + glossaryTermSpan("MACRO_IND_GLOSSARY", key, esc(ind.name)) + '</span>' +
      '<span class="mrow-val">' + esc(fmtMacroVal(ind)) + " " + chg + " " + wchg + '</span>' +
      '<span class="mrow-spark">' + macroSparkline(ind) + '</span>' +
      '<span class="mrow-range muted small">90日 ' + esc(fmtMacroRange(ind)) + '</span>' +
      '<span class="mrow-read">' + esc(ind.read || "") + '</span>' +
      '<span class="mrow-asof muted small">' + (ind.asof ? ("截至 " + esc(ind.asof)) : "") + '</span></div>';
  }
  function macroSectionA() {
    var upd = MACRO.generated ? MACRO.generated.slice(0, 16).replace("T", " ") : "";
    var h = '<section class="msec" id="msec-overview"><h3 class="msec-title">A · 宏观数据总览' +
      '<span class="msec-sub">更新于 ' + esc(upd) + ' · 来源：Yahoo Finance（yfinance）· 变化为较上一交易日 / 近 90 日</span></h3>' +
      '<p class="msec-note">以下为实时抓取的市场指标。每个指标同时给出最新值、日变化、90 日走势与区间。没有可靠来源的指标列在文末“待接入”，不展示数值。</p>';
    var groups = [
      { title: "利率与债", keys: ["us10y", "us3m", "spread"] },
      { title: "恐慌与波动", keys: ["vix"] },
      { title: "避险与大宗", keys: ["gold", "silver", "oil", "copper", "dxy"] }
    ];
    groups.forEach(function (g) {
      h += '<h4 class="mgrp">' + esc(g.title) + '</h4><div class="mrows">' + g.keys.map(macroRowHTML).join("") + '</div>';
    });
    h += '<h4 class="mgrp">待接入指标（接口扩展点，不展示数值）</h4><ul class="mpending">';
    MACRO_PENDING.forEach(function (p) {
      h += '<li><span class="mpending-name">' + esc(p.name) + '</span><span class="muted small">' + esc(p.note) + '</span></li>';
    });
    h += '</ul></section>';
    return h;
  }
  // 当前被实时数据触发的信号（透明规则，见下方列表）。
  function macroActiveSignals() {
    var out = [];
    var gold = macroInd("gold"), dxy = macroInd("dxy"), y10 = macroInd("us10y"),
        cu = macroInd("copper"), oil = macroInd("oil"), vix = macroInd("vix"),
        sp = macroInd("spread");
    if (gold && gold.change_pct != null && gold.change_pct > 1) out.push({ id: "safe", label: "避险升温", detail: "黄金单日涨超 1%。" });
    if (dxy && dxy.change_pct != null && dxy.change_pct > 0.5) out.push({ id: "usd", label: "美元走强", detail: "美元指数单日涨超 0.5%。" });
    if (y10 && y10.change != null && y10.change > 0) out.push({ id: "rate", label: "利率上行", detail: "10Y 收益率较上一交易日上行 " + Math.round(y10.change * 100) + "bp。" });
    if (cu && cu.change_pct != null && cu.change_pct < -1) out.push({ id: "growth", label: "增长预期转弱", detail: "铜单日跌超 1%（代理指标）。" });
    if (oil && oil.change_pct != null && oil.change_pct > 3) out.push({ id: "infl", label: "成本侧通胀压力", detail: "原油单日涨超 3%（成本侧代理，非通胀本身）。" });
    if (vix && vix.value != null && vix.value >= 30) out.push({ id: "panic", label: "恐慌区间", detail: "VIX ≥ 30。" });
    else if (vix && vix.value != null && vix.value >= 20) out.push({ id: "vol", label: "波动加剧", detail: "VIX 处于 20–30 区间。" });
    if (sp && sp.value != null && sp.value < 0) out.push({ id: "inv", label: "收益率曲线倒挂", detail: "10Y−3M 利差 < 0，衰退预警信号。" });
    return out;
  }
  function macroUpcomingEvents(n) {
    var evs = [];
    if (EVENTS && Array.isArray(EVENTS.events)) {
      EVENTS.events.forEach(function (e) {
        var ds = e.date || e.start; if (!ds) return;
        evs.push({ type: e.type, name: e.name, date: ds, detail: e.detail || "" });
      });
    }
    nextFirstFridays().forEach(function (fri) {
      var ds = fri.getFullYear() + "-" + String(fri.getMonth() + 1).padStart(2, "0") + "-" + String(fri.getDate()).padStart(2, "0");
      evs.push({ type: "NFP", name: "美国非农就业", date: ds, detail: "20:30 北京时间（8:30 美东）" });
    });
    return evs.filter(function (e) { return daysUntil(e.date) >= 0; })
      .sort(function (a, b) { return a.date < b.date ? -1 : 1; }).slice(0, n || 6);
  }
  function macroNextEventDate(type) {
    var evs = macroUpcomingEvents(30);
    for (var i = 0; i < evs.length; i++) { if (evs[i].type === type) return evs[i].date; }
    return null;
  }

  function txNodeById(id) {
    for (var i = 0; i < TX_NODES.length; i++) if (TX_NODES[i].id === id) return TX_NODES[i];
    return null;
  }
  function txEdgesOf(id) {
    var out = [], inn = [];
    TX_EDGES.forEach(function (e, i) {
      if (e.from === id) out.push(i);
      if (e.to === id) inn.push(i);
    });
    return { out: out, inn: inn };
  }
  function txSignText(sign) {
    return sign === "plus" ? "+ 促进" : (sign === "minus" ? "− 抑制" : "? 不确定");
  }
  function txLiveLine(node) {
    var ind = node.live ? macroInd(node.live) : null;
    if (ind && ind.value != null) return '<span class="tx-live">' + esc(fmtMacroVal(ind)) + (ind.change_label ? "（" + esc(ind.change_label) + "）" : "") + '</span>';
    return '<span class="tx-live muted">' + esc(node.liveNote || "暂无实时数据") + '</span>';
  }
  function txEdgePathHTML(e, i) {
    var a = txNodeById(e.from), b = txNodeById(e.to);
    if (!a || !b) return "";
    var dx = Math.max(40, (b.x - a.x) * 0.5);
    var d = "M " + a.x + " " + a.y + " C " + (a.x + dx) + " " + a.y + ", " + (b.x - dx) + " " + b.y + ", " + b.x + " " + b.y;
    var mx = (a.x + b.x) / 2, my = (a.y + b.y) / 2;
    return '<g class="tx-edge" data-tx-edge="' + i + '" data-from="' + esc(e.from) + '" data-to="' + esc(e.to) + '" data-sign="' + esc(e.sign) + '">' +
      '<path d="' + d + '" class="tx-path tx-path-' + esc(e.sign) + '"/>' +
      '<text x="' + mx.toFixed(0) + '" y="' + (my - 6).toFixed(0) + '" class="tx-edge-label" text-anchor="middle">' + esc(txSignText(e.sign)) + '</text></g>';
  }
  function txNodeHTML(node) {
    var kindCls = "tx-kind-" + node.kind;
    return '<button type="button" class="tx-node ' + kindCls + '" data-tx-node="' + esc(node.id) + '" data-theme="' + esc(node.theme) + '" ' +
      'style="left:' + node.x + 'px;top:' + node.y + 'px" aria-label="' + esc(node.label) + '">' +
      '<span class="tx-node-label">' + esc(node.label) + '</span>' + txLiveLine(node) + '</button>';
  }
  function txDetailNodeHTML(node) {
    var rel = txEdgesOf(node.id);
    var h = '<h4 class="tx-detail-title">' + esc(node.label) + '</h4>' +
      '<p class="tx-detail-def">' + esc(node.def) + '</p>' +
      '<p><span class="tx-detail-k">经济含义</span> ' + esc(node.meaning) + '</p>' +
      '<p><span class="tx-detail-k">当前状态</span> ' + txLiveLine(node) + '</p>';
    if (rel.inn.length) {
      h += '<p><span class="tx-detail-k">上游（什么影响它）</span> ' + rel.inn.map(function (i) {
        var e = TX_EDGES[i];
        return '<button type="button" class="tx-link" data-tx-edge-jump="' + i + '">' + esc(txNodeById(e.from).label) + " " + esc(txSignText(e.sign)) + ' → ' + esc(node.label) + '</button>';
      }).join(" ") + '</p>';
    }
    if (rel.out.length) {
      h += '<p><span class="tx-detail-k">下游（它影响什么）</span> ' + rel.out.map(function (i) {
        var e = TX_EDGES[i];
        return '<button type="button" class="tx-link" data-tx-edge-jump="' + i + '">' + esc(node.label) + " " + esc(txSignText(e.sign)) + ' → ' + esc(txNodeById(e.to).label) + '</button>';
      }).join(" ") + '</p>';
    }
    return h;
  }
  function txDetailEdgeHTML(i) {
    var e = TX_EDGES[i];
    if (!e) return "";
    return '<h4 class="tx-detail-title">' + esc(txNodeById(e.from).label) + " " + esc(txSignText(e.sign)) + " → " + esc(txNodeById(e.to).label) + '</h4>' +
      '<p><span class="tx-detail-k">为什么会影响</span> ' + esc(e.mech) + '</p>' +
      '<p><span class="tx-detail-k">成立条件</span> ' + esc(e.cond || "—") + '</p>' +
      '<p><span class="tx-detail-k">对相关资产的方向提示</span> ' + esc(e.dir || "—") + '</p>' +
      '<p class="muted small">方向提示为理论传导方向（条件成立时），不是预测；实际反应还受市场定价、仓位与同时发生的其他因素影响。</p>';
  }
  function macroSectionB() {
    var h = '<section class="msec" id="msec-canvas"><h3 class="msec-title">B · 宏观经济传导画布' +
      '<span class="msec-sub">点击任意节点或连线查看传导机制与成立条件</span></h3>' +
      '<p class="msec-note">从左到右：源头变量 → 传导机制 → 资产影响。连线标注 <b>+ 促进</b> / <b>− 抑制</b> / <b>? 不确定</b>，方向提示为理论传导方向（条件成立时），不是预测。同一源头可能同时触发相反的链——例如就业走弱既可能增强降息预期（支撑估值），也可能压低盈利预期（压制股价）。</p>' +
      '<div class="tx-tools"><span class="tx-tools-label">主题：</span>' +
      '<button type="button" class="tx-chip' + (TX_SEL.theme === "all" ? " is-on" : "") + '" data-tx-theme="all">全部</button>' +
      TX_THEMES.map(function (t) {
        return '<button type="button" class="tx-chip' + (TX_SEL.theme === t.id ? " is-on" : "") + '" data-tx-theme="' + esc(t.id) + '">' + esc(t.label) + '</button>';
      }).join("") +
      '<span class="tx-tools-sep"></span><span class="tx-tools-label">画布：</span>' +
      '<button type="button" class="tx-chip" data-tx-zoom="in">放大 +</button>' +
      '<button type="button" class="tx-chip" data-tx-zoom="out">缩小 −</button>' +
      '<button type="button" class="tx-chip" data-tx-zoom="reset">复位</button>' +
      '<span class="tx-tools-hint muted small">桌面端可拖动平移、滚轮缩放；手机端为纵向流程。</span></div>';
    // 桌面画布
    h += '<div class="tx-viewport"><div class="tx-canvas" id="tx-canvas">' +
      '<svg class="tx-svg" width="1000" height="620" viewBox="0 0 1000 620" aria-hidden="true">' +
      '<defs>' +
      '<marker id="tx-arrow-plus" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" fill="#2e9e5b"/></marker>' +
      '<marker id="tx-arrow-minus" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" fill="#d64541"/></marker>' +
      '<marker id="tx-arrow-unk" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" fill="#c98a1b"/></marker>' +
      '</defs>' +
      TX_EDGES.map(txEdgePathHTML).join("") + '</svg>' +
      TX_NODES.map(txNodeHTML).join("") + '</div></div>';
    // 手机纵向流程：按层分组的节点链
    h += '<div class="tx-vertical">';
    [0, 1, 2, 3].forEach(function (layer) {
      var nodes = TX_NODES.filter(function (n) { return n.layer === layer; });
      var layerName = ["源头变量", "政策与预期", "传导机制", "资产影响"][layer];
      h += '<div class="tx-vlayer"><div class="tx-vlayer-title">' + layerName + '</div>';
      nodes.forEach(function (n, idx) {
        var down = txEdgesOf(n.id).out.map(function (i) { return TX_EDGES[i]; });
        h += '<button type="button" class="tx-vnode" data-tx-node="' + esc(n.id) + '" data-theme="' + esc(n.theme) + '">' +
          '<span class="tx-vnode-label">' + esc(n.label) + '</span>' + txLiveLine(n) +
          (down.length ? '<span class="tx-vnode-down muted small">→ ' + down.map(function (e) { return esc(txSignText(e.sign)) + " " + esc(txNodeById(e.to).label); }).join("；") + '</span>' : "") + '</button>';
        if (idx < nodes.length - 1) h += '<div class="tx-varrow" aria-hidden="true">↓</div>';
      });
      h += '</div>';
      if (layer < 3) h += '<div class="tx-vlayer-arrow" aria-hidden="true">⇓ 传导</div>';
    });
    h += '</div>';
    h += '<div class="tx-detail" id="tx-detail"><p class="muted">点击任意节点查看定义、经济含义与上下游路径；点击任意连线查看“为什么会影响”与成立条件。</p></div></section>';
    return h;
  }
  var TX_VIEW = { scale: 1, x: 0, y: 0, dragging: false, moved: false, sx: 0, sy: 0, ox: 0, oy: 0 };
  function txApplyView() {
    var cv = $("tx-canvas"); if (!cv) return;
    cv.style.transform = "translate(" + TX_VIEW.x + "px," + TX_VIEW.y + "px) scale(" + TX_VIEW.scale + ")";
  }
  function txSelectNode(id) {
    TX_SEL.node = id; TX_SEL.edge = -1;
    var d = $("tx-detail"); if (d) d.innerHTML = txDetailNodeHTML(txNodeById(id));
    var nodes = document.querySelectorAll("[data-tx-node]");
    var rel = txEdgesOf(id);
    var keep = {}; keep[id] = true;
    rel.inn.forEach(function (i) { keep[TX_EDGES[i].from] = true; });
    rel.out.forEach(function (i) { keep[TX_EDGES[i].to] = true; });
    nodes.forEach(function (el) {
      el.classList.toggle("is-sel", el.getAttribute("data-tx-node") === id);
      el.classList.toggle("is-dim", !keep[el.getAttribute("data-tx-node")]);
    });
    document.querySelectorAll("[data-tx-edge]").forEach(function (el) {
      var i = parseInt(el.getAttribute("data-tx-edge"), 10);
      el.classList.toggle("is-hl", rel.inn.indexOf(i) >= 0 || rel.out.indexOf(i) >= 0);
      el.classList.toggle("is-dim", !(rel.inn.indexOf(i) >= 0 || rel.out.indexOf(i) >= 0));
    });
  }
  /* 术语系统第三级联动：暴露画布高亮入口（供 indicator-glossary.js 调用）。 */
  window.MacroCanvas = { highlightNode: function (id) { txSelectNode(id); } };
  function txSelectEdge(i) {
    TX_SEL.edge = i; TX_SEL.node = null;
    var d = $("tx-detail"); if (d) d.innerHTML = txDetailEdgeHTML(i);
    document.querySelectorAll("[data-tx-edge]").forEach(function (el) {
      el.classList.toggle("is-hl", parseInt(el.getAttribute("data-tx-edge"), 10) === i);
      el.classList.toggle("is-dim", parseInt(el.getAttribute("data-tx-edge"), 10) !== i);
    });
    var e = TX_EDGES[i];
    document.querySelectorAll("[data-tx-node]").forEach(function (el) {
      var id = el.getAttribute("data-tx-node");
      el.classList.toggle("is-sel", id === e.from || id === e.to);
      el.classList.toggle("is-dim", !(id === e.from || id === e.to));
    });
  }
  function txClearSel() {
    TX_SEL.node = null; TX_SEL.edge = -1;
    var d = $("tx-detail"); if (d) d.innerHTML = '<p class="muted">点击任意节点查看定义、经济含义与上下游路径；点击任意连线查看“为什么会影响”与成立条件。</p>';
    document.querySelectorAll("[data-tx-node], [data-tx-edge]").forEach(function (el) {
      el.classList.remove("is-sel", "is-dim", "is-hl");
    });
  }
  function txSetTheme(theme) {
    TX_SEL.theme = theme;
    document.querySelectorAll("[data-tx-theme]").forEach(function (el) {
      el.classList.toggle("is-on", el.getAttribute("data-tx-theme") === theme);
    });
    document.querySelectorAll("[data-tx-node]").forEach(function (el) {
      var n = txNodeById(el.getAttribute("data-tx-node"));
      var on = theme === "all" || n.theme === theme ||
        TX_EDGES.some(function (e) { return (e.from === n.id || e.to === n.id) && (txNodeById(e.from).theme === theme || txNodeById(e.to).theme === theme); });
      el.classList.toggle("is-dim", !on);
    });
    document.querySelectorAll("[data-tx-edge]").forEach(function (el) {
      var e = TX_EDGES[parseInt(el.getAttribute("data-tx-edge"), 10)];
      var on = theme === "all" || txNodeById(e.from).theme === theme || txNodeById(e.to).theme === theme;
      el.classList.toggle("is-dim", !on);
    });
  }
  function txFindUp(el, attr) {
    while (el && el !== document.body) {
      if (el.getAttribute && el.getAttribute(attr) != null) return el;
      el = el.parentNode;
    }
    return null;
  }
  function bindMacroEvents() {
    var body = $("macro-body"); if (!body) return;
    // Click delegation binds once (body survives innerHTML re-renders);
    // viewport wheel/drag re-binds every render (the viewport element is new each time).
    if (!body.dataset.macroBound) {
      body.dataset.macroBound = "1";
      body.addEventListener("click", function (ev) {
      if (TX_VIEW.moved) { TX_VIEW.moved = false; return; }
      var jump = txFindUp(ev.target, "data-tx-edge-jump");
      if (jump) { txSelectEdge(parseInt(jump.getAttribute("data-tx-edge-jump"), 10)); return; }
      var nodeEl = txFindUp(ev.target, "data-tx-node");
      if (nodeEl) { txSelectNode(nodeEl.getAttribute("data-tx-node")); return; }
      var edgeEl = txFindUp(ev.target, "data-tx-edge");
      if (edgeEl) { txSelectEdge(parseInt(edgeEl.getAttribute("data-tx-edge"), 10)); return; }
      var chip = txFindUp(ev.target, "data-tx-theme");
      if (chip) { txSetTheme(chip.getAttribute("data-tx-theme")); return; }
      var zoom = txFindUp(ev.target, "data-tx-zoom");
      if (zoom) {
        var z = zoom.getAttribute("data-tx-zoom");
        if (z === "in") TX_VIEW.scale = Math.min(1.8, TX_VIEW.scale * 1.25);
        else if (z === "out") TX_VIEW.scale = Math.max(0.6, TX_VIEW.scale / 1.25);
        else { TX_VIEW.scale = 1; TX_VIEW.x = 0; TX_VIEW.y = 0; }
        txApplyView();
        return;
      }
      });
    }
    var vp = body.querySelector(".tx-viewport");
    if (vp) {
      vp.addEventListener("wheel", function (ev) {
        ev.preventDefault();
        TX_VIEW.scale = Math.min(1.8, Math.max(0.6, TX_VIEW.scale * Math.exp(-ev.deltaY * 0.0015)));
        txApplyView();
      }, { passive: false });
      vp.addEventListener("pointerdown", function (ev) {
        TX_VIEW.dragging = true; TX_VIEW.moved = false;
        TX_VIEW.sx = ev.clientX; TX_VIEW.sy = ev.clientY;
        TX_VIEW.ox = TX_VIEW.x; TX_VIEW.oy = TX_VIEW.y;
        vp.setPointerCapture(ev.pointerId);
      });
      vp.addEventListener("pointermove", function (ev) {
        if (!TX_VIEW.dragging) return;
        TX_VIEW.x = TX_VIEW.ox + (ev.clientX - TX_VIEW.sx);
        TX_VIEW.y = TX_VIEW.oy + (ev.clientY - TX_VIEW.sy);
        if (Math.abs(ev.clientX - TX_VIEW.sx) > 5 || Math.abs(ev.clientY - TX_VIEW.sy) > 5) TX_VIEW.moved = true;
        txApplyView();
      });
      var endDrag = function () { TX_VIEW.dragging = false; };
      vp.addEventListener("pointerup", endDrag);
      vp.addEventListener("pointercancel", endDrag);
    }
  }

  function macroSectionC() {
    var h = '<section class="msec" id="msec-releases"><h3 class="msec-title">C · 重要经济数据公布解读' +
      '<span class="msec-sub">公布前 — 公布时 — 公布后</span></h3>' +
      '<p class="msec-note">每个数据都给出“高于预期 / 符合预期 / 低于预期”三条基础分支。以下只是基础情景：实际结果还受核心分项、前值修正、市场仓位、经济增长预期和美联储表态等因素影响。排期来自官方日历（FOMC / CPI）与规则生成（非农：每月第一个周五）；未标注排期的请以 BEA / ISM 官方日历为准。</p>';
    RELEASES.forEach(function (r) {
      var nextTxt = "";
      if (r.next === "events") {
        var d = macroNextEventDate(r.nextType);
        nextTxt = d ? ("下次公布：" + d + "（" + (daysUntil(d) === 0 ? "今天" : daysUntil(d) + " 天后") + "）") : "下次公布：见官方日历";
      } else if (r.next === "nfp") {
        var fri = nextFirstFridays()[0];
        var ds = fri.getFullYear() + "-" + String(fri.getMonth() + 1).padStart(2, "0") + "-" + String(fri.getDate()).padStart(2, "0");
        nextTxt = "下次公布：" + ds + "（" + (daysUntil(ds) === 0 ? "今天" : daysUntil(ds) + " 天后") + "，每月第一个周五，规则生成）";
      } else {
        nextTxt = "下次公布：" + (r.nextNote || "见官方日历");
      }
      h += '<details class="rel"><summary><span class="rel-name">' + glossaryTermSpan("RELEASE_GLOSSARY", r.id, esc(r.name)) + '</span><span class="rel-next muted small">' + esc(nextTxt) + '</span></summary>' +
        '<div class="rel-body">' +
        '<p><span class="tx-detail-k">衡量什么</span> ' + esc(r.measures) + '</p>' +
        '<p><span class="tx-detail-k">为什么市场关注</span> ' + esc(r.why) + '</p>' +
        '<div class="branch"><div class="branch-root">公布</div>' +
        '<div class="branch-arm"><span class="branch-tag">高于预期</span><div class="branch-path">' + esc(r.up) + (r.upNote ? ' <span class="muted">（' + esc(r.upNote) + '）</span>' : "") + '</div></div>' +
        '<div class="branch-arm"><span class="branch-tag">符合预期</span><div class="branch-path">' + esc(r.mid) + '</div></div>' +
        '<div class="branch-arm"><span class="branch-tag">低于预期</span><div class="branch-path">' + esc(r.down) + '</div></div></div>' +
        '<p><span class="tx-detail-k">可能反向反应的情况</span> ' + r.reversals.map(esc).join("；") + '。</p>' +
        '<p><span class="tx-detail-k">后续验证指标</span> ' + r.watch.map(esc).join("、") + '。</p>' +
        '</div></details>';
    });
    h += '</section>';
    return h;
  }
  function macroSectionD() {
    var h = '<section class="msec" id="msec-assets"><h3 class="msec-title">D · 从宏观变量到市场资产' +
      '<span class="msec-sub">影响矩阵：理论传导方向（条件成立时），非预测</span></h3>' +
      '<p class="msec-note">单元格为“某个宏观因素出现时，对某类资产的理论传导方向”。每个判断都有条件；方向不等于必然涨跌，实际结果取决于市场是否已定价、仓位与其他同时发生的因素。A 股的传导是间接的（全球风险偏好、汇率、外资流动），不能把美债传导直接等同于 A 股涨跌。</p>';
    h += '<div class="mx-live"><span class="tx-detail-k">各因素当前状态（实时数据触发）：</span>';
    MATRIX_FACTORS.forEach(function (f) {
      var state = "暂无实时数据";
      if (f.id === "rate") { var y = macroInd("us10y"); state = y && y.value != null ? ("10Y " + fmtMacroVal(y) + "（" + (y.change_label || "—") + "）") : "暂无数据"; }
      if (f.id === "dxy") { var d = macroInd("dxy"); state = d && d.value != null ? ("DXY " + fmtMacroVal(d) + "（" + (d.change_label || "—") + "）") : "暂无数据"; }
      if (f.id === "safe") { var g = macroInd("gold"); state = g && g.value != null ? ("黄金 " + fmtMacroVal(g) + "（" + (g.change_label || "—") + "）") : "暂无数据"; }
      if (f.id === "infl") state = "CPI / PCE 未接入";
      if (f.id === "jobs") { var fri = nextFirstFridays()[0]; state = "NFP 未接入，下次公布 " + fri.getFullYear() + "-" + String(fri.getMonth() + 1).padStart(2, "0") + "-" + String(fri.getDate()).padStart(2, "0"); }
      h += '<span class="mx-live-item"><b>' + glossaryTermSpan("MATRIX_GLOSSARY", f.id, esc(f.label)) + '</b> ' + esc(state) + '</span>';
    });
    h += '</div>';
    h += '<div class="mx-wrap"><table class="mx"><thead><tr><th>资产</th>' +
      MATRIX_FACTORS.map(function (f) { return '<th>' + esc(f.label) + '</th>'; }).join("") + '</tr></thead><tbody>';
    MATRIX_ASSETS.forEach(function (a) {
      h += '<tr><th>' + esc(a.label) + '</th>';
      MATRIX_FACTORS.forEach(function (f) {
        var c = a.cells[f.id] || { dir: "na", note: "—" };
        var dirTxt = c.dir === "neg" ? "偏利空" : (c.dir === "pos" ? "偏利多" : (c.dir === "unk" ? "不确定" : "—"));
        h += '<td class="mx-cell mx-' + esc(c.dir) + '" data-mx-cell="' + esc(a.id + ":" + f.id) + '"><span class="mx-dir">' + dirTxt + '</span><span class="mx-note">' + esc(c.note) + '</span></td>';
      });
      h += '</tr>';
    });
    h += '</tbody></table></div>';
    h += '<p class="muted small" style="margin-top:8px">数据不足时标注“不确定”，不伪造确定性结论。</p></section>';
    return h;
  }
  function macroSectionE() {
    var y10 = macroInd("us10y"), m3 = macroInd("us3m"), sp = macroInd("spread"),
        vix = macroInd("vix"), dxy = macroInd("dxy"), gold = macroInd("gold"),
        cu = macroInd("copper"), oil = macroInd("oil");
    var dims = [];
    dims.push({ name: "通胀压力", status: "暂无足够依据",
      evidence: "CPI / PCE 实际值未接入。成本侧代理：原油 " + (oil && oil.value != null ? fmtMacroVal(oil) + "（" + (oil.change_label || "—") + "）" : "暂无数据") + "（代理指标，非通胀本身）。",
      overturn: "核心 CPI / PCE 连续两个月超预期或低于预期。" });
    var gStatus = "中性", gEv = "";
    if (cu && cu.change_pct != null && cu.change_pct < -1) gStatus = "偏弱";
    else if (cu && cu.change_pct != null && cu.change_pct > 1) gStatus = "偏强";
    gEv = "铜 " + (cu && cu.value != null ? fmtMacroVal(cu) + "（" + (cu.change_label || "—") + "）" : "暂无数据") + "（代理指标，非 GDP 本身）；10Y−3M 利差 " + (sp && sp.value != null ? sp.value.toFixed(2) + " 百分点" : "暂无数据") + "。";
    dims.push({ name: "增长动能", status: gStatus, evidence: gEv, overturn: "GDP 连续两季负增长，或 PMI 跌破 50。" });
    var fri = nextFirstFridays()[0];
    var nfpDate = fri.getFullYear() + "-" + String(fri.getMonth() + 1).padStart(2, "0") + "-" + String(fri.getDate()).padStart(2, "0");
    dims.push({ name: "就业韧性", status: "暂无足够依据", evidence: "NFP 实际值未接入；下次公布 " + nfpDate + "。", overturn: "失业率连续上升，或 NFP 大幅低于预期。" });
    var rStatus = "中性";
    if (y10 && y10.window_chg != null && y10.window_chg > 0.2) rStatus = "偏紧";
    else if (y10 && y10.window_chg != null && y10.window_chg < -0.2) rStatus = "偏松";
    dims.push({ name: "利率环境", status: rStatus,
      evidence: "10Y " + (y10 && y10.value != null ? fmtMacroVal(y10) + "（90日 " + (y10.window_label || "—") + "）" : "暂无数据") + "；3M " + (m3 && m3.value != null ? fmtMacroVal(m3) : "暂无数据") + "；利差 " + (sp && sp.value != null ? sp.value.toFixed(2) + " 百分点" : "暂无数据") + "。",
      overturn: "美联储意外降息 / 加息，或点阵图大幅移动。" });
    var uStatus = "中性";
    if (dxy && dxy.change_pct != null && dxy.change_pct > 0.5) uStatus = "美元走强";
    else if (dxy && dxy.change_pct != null && dxy.change_pct < -0.5) uStatus = "美元走弱";
    dims.push({ name: "美元与全球金融条件", status: uStatus,
      evidence: "DXY " + (dxy && dxy.value != null ? fmtMacroVal(dxy) + "（" + (dxy.change_label || "—") + "）" : "暂无数据") + "；VIX " + (vix && vix.value != null ? fmtMacroVal(vix) : "暂无数据") + "。",
      overturn: "利差转向，或避险情绪逆转。" });
    var kStatus = "中性";
    if (vix && vix.value != null && vix.value < 15) kStatus = "偏高";
    else if (vix && vix.value != null && vix.value >= 30) kStatus = "极低";
    else if (vix && vix.value != null && vix.value >= 20) kStatus = "偏低";
    dims.push({ name: "市场风险偏好", status: kStatus,
      evidence: "VIX " + (vix && vix.value != null ? fmtMacroVal(vix) + "（" + (vix.read || "") + "）" : "暂无数据") + "；黄金 " + (gold && gold.value != null ? fmtMacroVal(gold) + "（" + (gold.change_label || "—") + "）" : "暂无数据") + "。",
      overturn: "VIX 突破 30，或黄金急涨。" });
    var h = '<section class="msec" id="msec-assess"><h3 class="msec-title">E · 当前宏观环境综合判断' +
      '<span class="msec-sub">分项评估 + 情景（框架，非实时结论）</span></h3>' +
      '<p class="msec-note">每项判断都标注依据与可能推翻它的条件。标注“暂无足够依据”的维度是分析框架，不是结论——不要用代理指标假装它就是该维度本身。</p>';
    dims.forEach(function (d) {
      h += '<div class="dim"><span class="dim-name">' + esc(d.name) + '</span><span class="dim-status">' + esc(d.status) + '</span>' +
        '<span class="dim-ev">' + esc(d.evidence) + '</span><span class="dim-over muted small">推翻条件：' + esc(d.overturn) + '</span></div>';
    });
    var sigs = macroActiveSignals();
    var contradiction = sigs.length ?
      "当前被实时数据触发的信号：" + sigs.map(function (s) { return s.label + "（" + s.detail + "）"; }).join(" ") +
      "。若多信号并存且指向不同方向，说明市场正处于多股力量拉扯中，单一结论不可靠。" :
      "当前暂无强信号主导；市场处于等待数据的状态，关注下方待验证数据。";
    var activeEdges = [];
    sigs.forEach(function (s) {
      var srcMap = { safe: "n_safe", usd: "n_dxy", rate: "n_yield", growth: "n_growth", infl: "n_infl", panic: null, vol: null, inv: "n_yield" };
      var src = srcMap[s.id];
      if (!src) return;
      TX_EDGES.forEach(function (e) {
        if (e.from === src) activeEdges.push(e);
      });
    });
    var pathsTxt = activeEdges.length ?
      activeEdges.map(function (e) { return txNodeById(e.from).label + " " + txSignText(e.sign) + " → " + txNodeById(e.to).label + "（" + e.mech + "）"; }).join("；") :
      "暂无被实时数据触发的传导路径；上方画布为理论框架。";
    var impactTxt = sigs.length ?
      "被触发的信号对应的资产影响见上方影响矩阵的相应列；方向均为条件成立时的理论传导，不是预测。重点看多条链是否指向同一方向：同向时信号更可信，反向时需等数据验证。" :
      "暂无被触发的信号；不对风险资产做方向判断。";
    var upcoming = macroUpcomingEvents(3);
    var verifyTxt = upcoming.length ?
      upcoming.map(function (e) { return e.name + "（" + e.date + "）"; }).join("、") :
      "暂无排期事件。";
    h += '<div class="assess-block"><h4>当前主导的宏观矛盾</h4><p>' + esc(contradiction) + '</p></div>' +
      '<div class="assess-block"><h4>正在发生的主要传导路径</h4><p>' + esc(pathsTxt) + '</p></div>' +
      '<div class="assess-block"><h4>对风险资产的潜在影响</h4><p>' + esc(impactTxt) + '</p></div>' +
      '<div class="assess-block"><h4>后续需要验证的关键数据</h4><p>' + esc(verifyTxt) + '</p></div>' +
      '<div class="assess-block"><h4>三种情景（情景假设，需数据验证）</h4>' +
      '<p><b>基准：</b>数据大体符合预期，利率与风险偏好维持现状，关注核心分项。触发：CPI / PCE 符合预期。</p>' +
      '<p><b>乐观：</b>通胀降温 + 就业温和 → 降息预期增强，估值获支撑。触发：核心 CPI 低于预期且就业未恶化。</p>' +
      '<p><b>悲观：</b>通胀反复 + 增长放缓 → 滞胀担忧，股债承压。触发：核心 CPI 超预期 + PMI 跌破 50。</p></div>' +
      '</section>';
    return h;
  }
  function renderMacro() {
    var body = $("macro-body"); if (!body) return;
    if (!MACRO && !macroLoading) { loadMacro(); return; }
    if (!MACRO) { body.innerHTML = '<p class="muted">宏观数据未就绪（后端 pipeline 正在拉取或数据源暂不可用）。</p>'; return; }
    if (MACRO.error) { body.innerHTML = '<div class="msec"><h3 class="msec-title">宏观抓取失败</h3><p class="muted">后端 pipeline 已运行，但抓取宏观数据时出错（信号不受影响）：</p><p style="word-break:break-all">' + esc(MACRO.error) + '</p><p class="muted small">更新于 ' + esc((MACRO.generated || "").slice(0, 16).replace("T", " ")) + '</p></div>'; return; }
    var upd = $("macro-updated");
    if (upd) upd.textContent = MACRO.generated ? ("更新于 " + MACRO.generated.slice(0, 16).replace("T", " ")) : "";
    TX_SEL.node = null; TX_SEL.edge = -1;
    body.innerHTML = macroSectionA() + macroSectionB() + macroSectionC() + macroSectionD() + macroSectionE() +
      '<p class="muted small" style="margin-top:14px">方法说明：解读规则（VIX 分段、利差倒挂、美元/黄金/铜/油的定性规则）为启发式汇总，不是预测，不构成投资建议。实际公布值、市场预期、历史数据、模型推断与情景假设在文中明确区分；未标注来源的判断均为理论框架。</p>';
    bindMacroEvents();
  }

  function renderHoldings() {
   try {
    var tb = $("pos-tbody");
    if (!tb) return;
    if (!POSDATA || !Array.isArray(POSDATA.positions) || !POSDATA.positions.length) {
      tb.innerHTML = '<tr><td colspan="5" class="muted">暂无持仓数据</td></tr>';
      var pc0 = $("pos-count"); if (pc0) pc0.textContent = "";
      var pu0 = $("pos-updated"); if (pu0) pu0.textContent = "持仓数据未就绪";
      renderPosCharts();
      return;
    }
    var ps = POSDATA.positions.slice().sort(function (a, b) { return num(b.value, 0) - num(a.value, 0); });
    $("pos-count").textContent = ps.length;
    var gen = POSDATA.generated ? new Date(POSDATA.generated) : null, gok = gen && !isNaN(gen.getTime());
    $("pos-updated").textContent = "更新于 " + (gok ? relTime(gen) + " · " + gen.toLocaleString("zh-CN", { hour12: false, month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" }) : "未知") +
      (POSDATA.report_date ? " · 报告日 " + fmtReportDate(POSDATA.report_date) : "");
    tb.innerHTML = ps.map(function (p) {
      var u = num(p.unrealized, 0), cls = u >= 0 ? "pnl-pos" : "pnl-neg";
      return "<tr>" +
        '<td><span class="t-sym">' + esc(p.symbol) + "</span>" + (p.asset && p.asset !== "STK" ? ' <span class="chip">' + esc(p.asset) + "</span>" : "") + "</td>" +
        '<td class="r num">' + esc(fmtPrice(p.qty)) + "</td>" +
        '<td class="r num">$' + esc(fmtPrice(p.cost)) + "</td>" +
        '<td class="r num">$' + esc(fmtPrice(p.mark)) + "</td>" +
        '<td class="r num ' + cls + '">' + (u >= 0 ? "+" : "\u2212") + "$" + esc(fmtPrice(Math.abs(u))) + "</td>" +
        "</tr>";
    }).join("");
    renderPosCharts();
   } catch (e) {
     var tb2 = $("pos-tbody");
     if (tb2) tb2.innerHTML = '<tr><td colspan="5" class="muted">持仓加载失败，请稍后重试</td></tr>';
   }
  }

  // ---------- 持仓图表 ----------
  var CHART_CACHE = {};  // symbol -> chart json (avoid refetch on view switch)
  var POS_CHART_OBJS = [];  // live Lightweight Charts instances (removed on re-render)
  function posTheme() {
    function css(n) { try { return getComputedStyle(document.documentElement).getPropertyValue(n).trim(); } catch (e) { return ""; } }
    var dark = document.documentElement.getAttribute("data-theme") !== "light";
    return {
      bg: css("--surface") || (dark ? "#121826" : "#ffffff"),
      text: css("--text-2") || "#aab3c5",
      grid: dark ? "rgba(148,163,184,.10)" : "rgba(15,23,42,.08)",
      border: css("--border") || "rgba(148,163,184,.14)",
      up: css("--buy") || "#f0505e",
      down: css("--sell") || "#1fc47d",
      accent: css("--accent") || "#5b8cff",
      muted: css("--text-3") || "#8a93a6"
    };
  }
  function posChartBase() { return (typeof API_BASE !== "undefined" ? (API_BASE || "") : "") + "/api/charts/"; }
  function renderPosCharts() {
    var host = $("pos-charts");
    if (!host) return;
    // only render when holdings view is visible (Lightweight Charts needs layout)
    if (VIEW !== "holdings") return;
    try {
      if (!POSDATA || !Array.isArray(POSDATA.positions) || !POSDATA.positions.length) {
        host.innerHTML = '<p class="muted">暂无持仓数据</p>';
        return;
      }
      var ps = POSDATA.positions.slice().sort(function (a, b) { return num(b.value, 0) - num(a.value, 0); });
      POS_CHART_OBJS.forEach(function (c) { try { c.remove(); } catch (e) {} });
      POS_CHART_OBJS = [];
      host.innerHTML = "";
      // -- 组合:浮盈亏对比 + 成本现价对比 --
      var duo = document.createElement("div");
      duo.className = "pos-duo";
      var c1 = document.createElement("div"); c1.className = "pos-chart-card";
      c1.innerHTML = '<div class="pos-chart-head"><b>浮盈亏对比</b><span class="muted small">正=盈利/负=亏损</span></div><div class="pos-pnlchart" id="pos-pnl"></div>';
      var c2 = document.createElement("div"); c2.className = "pos-chart-card";
      c2.innerHTML = '<div class="pos-chart-head"><b>成本 vs 现价</b><span class="muted small">灰=成本/彩=现价</span></div><div id="pos-cm"></div>';
      duo.appendChild(c1); duo.appendChild(c2); host.appendChild(duo);
      renderPnlChart($("pos-pnl"), ps);
      renderCostMark($("pos-cm"), ps);
      // -- 每只: K 线 + 成本/现价线 --
      ps.forEach(function (p, i) {
        var u = num(p.unrealized, 0);
        var card = document.createElement("div");
        card.className = "pos-chart-card";
        card.innerHTML = '<div class="pos-chart-head"><b>' + esc(p.symbol) + '</b>' +
          '<span class="muted small">' + esc(fmtPrice(p.qty)) + ' 股 · 成本 $' + esc(fmtPrice(p.cost)) + ' · 现价 $' + esc(fmtPrice(p.mark)) + '</span>' +
          '<span class="num ' + (u >= 0 ? "pnl-pos" : "pnl-neg") + '">' + (u >= 0 ? "浮盈 +" : "浮亏 \u2212") + "$" + esc(fmtPrice(Math.abs(u))) + "</span></div>" +
          '<div class="pos-klegend muted small" id="kleg-' + i + '"></div>' +
          '<div class="pos-kchart" id="kchart-' + i + '"></div>';
        host.appendChild(card);
        renderSymbolKChart($("kchart-" + i), $("kleg-" + i), p);
      });
    } catch (e) { host.innerHTML = '<p class="muted">图表加载失败</p>'; }
  }
  function renderPnlChart(el, ps) {
    if (!el) return;
    try {
      var LC = window.LightweightCharts;
      if (!LC) { el.innerHTML = '<p class="muted">图表库未加载</p>'; return; }
      var th = posTheme();
      var chart = LC.createChart(el, {
        autoSize: true,
        layout: { background: { color: th.bg }, textColor: th.text, fontSize: 11, attributionLogo: false },
        grid: { vertLines: { color: th.grid }, horzLines: { color: th.grid } },
        rightPriceScale: { borderColor: th.border },
        timeScale: {
          borderColor: th.border,
          tickMarkFormatter: function (time) { var i = Math.round(time) - 1; return (ps[i] && ps[i].symbol) || ""; }
        }
      });
      var hist = chart.addHistogramSeries({
        priceFormat: { type: "custom", formatter: function (v) { return (v < 0 ? "\u2212$" : "$") + Math.abs(v).toFixed(0); } },
        lastValueVisible: false, priceLineVisible: false
      });
      hist.setData(ps.map(function (p, i) {
        var u = num(p.unrealized, 0);
        return { time: i + 1, value: u, color: u >= 0 ? th.up : th.down };
      }));
      chart.timeScale().fitContent();
      POS_CHART_OBJS.push(chart);
    } catch (e) { el.innerHTML = '<p class="muted">图表加载失败</p>'; }
  }
  function renderCostMark(el, ps) {
    if (!el) return;
    try {
      var mx = 0;
      ps.forEach(function (p) { mx = Math.max(mx, num(p.cost, 0), num(p.mark, 0)); });
      if (!(mx > 0)) { el.innerHTML = '<p class="muted">暂无数据</p>'; return; }
      el.innerHTML = '<div class="cm-rows">' + ps.map(function (p) {
        var u = num(p.unrealized, 0);
        return '<div class="cm-sym">' + esc(p.symbol) + '</div>' +
          '<div class="cm-bar-row"><span class="cm-label">成本</span><div class="cm-track"><div class="cm-fill cm-cost" style="width:' + (num(p.cost, 0) / mx * 100).toFixed(1) + '%"></div></div><span class="cm-val num">$' + esc(fmtPrice(p.cost)) + "</span></div>" +
          '<div class="cm-bar-row"><span class="cm-label">现价</span><div class="cm-track"><div class="cm-fill ' + (u >= 0 ? "cm-mark-p" : "cm-mark-n") + '" style="width:' + (num(p.mark, 0) / mx * 100).toFixed(1) + '%"></div></div><span class="cm-val num">$' + esc(fmtPrice(p.mark)) + "</span></div>";
      }).join("") + "</div>";
    } catch (e) { el.innerHTML = '<p class="muted">图表加载失败</p>'; }
  }
  function renderSymbolKChart(el, legEl, p) {
    if (!el) return;
    try {
      var LC = window.LightweightCharts;
      if (!LC) { el.innerHTML = '<p class="muted">图表库未加载</p>'; return; }
      el.innerHTML = '<p class="muted small">加载 K 线…</p>';
      var sym = p.symbol;
      function done(data) {
        try {
          var lv = data && data.levels && (data.levels.daily || data.levels["30m"] || data.levels.weekly);
          if (!lv || !lv.ohlc || !lv.ohlc.length) { el.innerHTML = '<p class="muted">K 线数据缺失</p>'; return; }
          el.innerHTML = "";
          var th = posTheme();
          var chart = LC.createChart(el, {
            autoSize: true,
            layout: { background: { color: th.bg }, textColor: th.text, fontSize: 11, attributionLogo: false },
            grid: { vertLines: { color: th.grid }, horzLines: { color: th.grid } },
            crosshair: { mode: LC.CrosshairMode ? LC.CrosshairMode.Normal : 1 },
            rightPriceScale: { borderColor: th.border, scaleMargins: { top: 0.08, bottom: 0.08 } },
            timeScale: { borderColor: th.border, rightOffset: 4 },
            handleScroll: { vertTouchDrag: false }
          });
          var candle = chart.addCandlestickSeries({
            upColor: th.up, downColor: th.down,
            borderUpColor: th.up, borderDownColor: th.down,
            wickUpColor: th.up, wickDownColor: th.down,
            lastValueVisible: false, priceLineVisible: false
          });
          candle.setData(lv.ohlc);
          // 缠论买卖点标记(与详情图同一套逻辑):箭头=一二三类,圆点=中枢沿,黄色=预信号
          try {
            if (lv.signals && lv.signals.length && candle.setMarkers) {
              var markers = lv.signals.map(function (s) {
                var buy = isBuy(s);
                var edge = isEdge(s);
                var pre = isPre(s);
                var base = String(s.type || "").replace(/^PRE_/, "");
                var label = (pre ? "【预】" : "") + typeName(base) + (s.confirmed ? "" : "?") + (s.score != null ? " " + Number(s.score).toFixed(1) : "") + (s.price != null ? " @" + Number(s.price).toFixed(2) : "");
                var mc = pre ? "#ffcc00" : (edge ? (buy ? "#22d3ee" : "#f59e0b") : (buy ? th.up : th.down));
                return { time: s.time, position: buy ? "belowBar" : "aboveBar", color: mc, shape: edge ? "circle" : (buy ? "arrowUp" : "arrowDown"), text: label };
              });
              markers.sort(function (a, b) { return (a.time > b.time) - (a.time < b.time); });
              candle.setMarkers(markers);
            }
          } catch (e2) {}
          var u = num(p.unrealized, 0);
          if (num(p.cost) != null) candle.createPriceLine({ price: p.cost, color: "#f59e0b", lineWidth: 2, lineStyle: LC.LineStyle.Dashed, axisLabelVisible: true, title: "成本 " + fmtPrice(p.cost) });
          if (num(p.mark) != null) candle.createPriceLine({ price: p.mark, color: u >= 0 ? th.up : th.down, lineWidth: 2, lineStyle: LC.LineStyle.Solid, axisLabelVisible: true, title: "现价 " + fmtPrice(p.mark) });
          chart.timeScale().fitContent();
          POS_CHART_OBJS.push(chart);
          if (legEl) {
            chart.subscribeCrosshairMove(function (param) {
              try {
                if (!param || !param.time) { legEl.textContent = ""; return; }
                var b = param.seriesData.get(candle);
                legEl.textContent = b ? ("开 " + b.open.toFixed(2) + "  高 " + b.high.toFixed(2) + "  低 " + b.low.toFixed(2) + "  收 " + b.close.toFixed(2)) : "";
              } catch (e2) {}
            });
          }
        } catch (e) { el.innerHTML = '<p class="muted">图表加载失败</p>'; }
      }
      if (CHART_CACHE[sym]) { done(CHART_CACHE[sym]); return; }
      fetch(posChartBase() + encodeURIComponent(sym) + ".json", { cache: "no-cache" })
        .then(function (r) { if (!r.ok) throw new Error("HTTP " + r.status); return r.json(); })
        .then(function (d) { CHART_CACHE[sym] = d; done(d); })
        .catch(function () { el.innerHTML = '<p class="muted">K 线数据缺失</p>'; });
    } catch (e) { el.innerHTML = '<p class="muted">图表加载失败</p>'; }
  }

  // ---------- 概览 ----------
  function renderKPIs(gen, ok, ageH) {
    var recent = SIGS.filter(function (g) { return g.recent; });
    var rb = recent.filter(isBuy).length;
    var conf = SIGS.filter(function (g) { return g.confirmed; }).length, un = SIGS.length - conf;
    var unRecent = recent.filter(function (g) { return !g.confirmed; }).length;
    var h = "";
    h += '<button type="button" class="kpi clickable" id="k-recent" style="--k1:var(--hi);--k2:var(--hi2)" aria-label="近期信号 ' + recent.length + ' 条,点击仅看近期">' +
      '<div class="kpi-label">近期信号</div><div class="kpi-value num">' + recent.length + '<small>/ 共 ' + SIGS.length + ' 条</small></div>' +
      '<div class="kpi-foot"><span class="t-buy">买 ' + rb + '</span>·<span class="t-sell">卖 ' + (recent.length - rb) + '</span>·<span>未确认 ' + unRecent + '</span></div></button>';
    var pc = SIGS.length ? conf / SIGS.length * 100 : 0;
    h += '<div class="kpi" style="--k1:var(--accent);--k2:var(--warn)"><div class="kpi-label">已确认 / 未确认</div>' +
      '<div class="kpi-value num">' + conf + '<small>/</small><span style="color:var(--warn)">' + un + '</span></div>' +
      '<div class="split-bar" role="img" aria-label="已确认 ' + conf + ' 条,未确认 ' + un + ' 条"><i class="ok" style="width:' + pc + '%"></i><i class="un" style="width:' + (100 - pc) + '%"></i></div>' +
      '<div class="kpi-foot">未确认信号可能重绘</div></div>';
    $("kpis").innerHTML = h;
    var kr = $("k-recent"); if (kr) kr.addEventListener("click", function () { F.recent = true; onFilter(); setView("signals"); $("h-signals").scrollIntoView({ behavior: "smooth", block: "start" }); });
  }

  function renderFailures() {
    var f = D.failures || {}, ks = Object.keys(f);
    $("failures").innerHTML = ks.length
      ? '<h3>本次获取失败</h3><ul class="fail-list">' + ks.map(function (k) { return '<li><b>' + esc(k) + '</b>:' + esc(f[k]) + '</li>'; }).join("") + '</ul>'
      : '<p class="muted small">本次无获取失败。</p>';
  }

  // ---------- 信号列表 ----------
  function filtered() {
    var q = F.q.toUpperCase();
    var a = SIGS.filter(function (g) {
      if (q && g.symbol.toUpperCase().indexOf(q) < 0) return false;
      if (F.level && g.level !== F.level) return false;
      if (F.type) {
        if (F.type === "edge") { if (!isEdge(g)) return false; }
        else if (F.type === "chan") { if (isEdge(g)) return false; }
        else if (F.type.length === 1) { if (g.type.slice(-1) !== F.type) return false; }
        else if (g.type !== F.type) return false;
      }
      if (F.conf !== "" && String(+!!g.confirmed) !== F.conf) return false;
      if (g.score < +F.min) return false;
      if (F.recent && !g.recent) return false;
      return true;
    });
    var s = F.dir === "asc" ? 1 : -1;
    var key = {
      score: function (g) { return g.score; },
      time: function (g) { return g.time || ""; },
      bars_ago: function (g) { return num(g.bars_ago, 1e9); },
      symbol: function (g) { return g.symbol; },
      margin: function (g) { return num(g.margin_pct, -1e9); }
    }[F.sort] || function (g) { return g.score; };
    a.sort(function (x, y) {
      var kx = key(x), ky = key(y);
      if (kx < ky) return -s; if (kx > ky) return s;
      return y.score - x.score || (x.symbol < y.symbol ? -1 : 1);
    });
    return a;
  }

  function renderSignals() {
    if (!D) return;
    var a = filtered(), box = $("sig-results");
    $("sig-count").textContent = a.length + " / " + SIGS.length;
    if (!a.length) {
      box.innerHTML = stateHTML("empty", "没有符合条件的信号",
        F.recent ? "当前开启了「仅近期」,近期内可能没有满足条件的信号。可以关闭近期开关或降低分数下限。" : "试试放宽筛选条件,例如清空搜索、降低分数下限。",
        '<button type="button" class="btn primary" id="clear-f">清除全部筛选</button>');
      $("clear-f").addEventListener("click", resetFilters);
      return;
    }
    box.innerHTML = MODE === "table" ? tableHTML(a) : cardsHTML(a);
    qsa("[data-sig]", box).forEach(function (el) {
      var g = SIGS[+el.getAttribute("data-sig")];
      el.addEventListener("click", function () { openDrawer(g.symbol, g, el); });
      if (el.tagName === "TR") el.addEventListener("keydown", function (e) {
        if (e.key === "Enter" || e.key === " ") { e.preventDefault(); openDrawer(g.symbol, g, el); }
        else if (e.key === "ArrowDown" && el.nextElementSibling) { e.preventDefault(); el.nextElementSibling.focus(); }
        else if (e.key === "ArrowUp" && el.previousElementSibling) { e.preventDefault(); el.previousElementSibling.focus(); }
      });
    });
    qsa("th [data-sort]", box).forEach(function (b) {
      b.addEventListener("click", function () {
        var k = b.getAttribute("data-sort");
        if (F.sort === k) F.dir = F.dir === "desc" ? "asc" : "desc";
        else { F.sort = k; F.dir = (k === "symbol" || k === "bars_ago") ? "asc" : "desc"; }
        onFilter();
        var nb = document.querySelector('#sig-results th [data-sort="' + k + '"]'); if (nb) nb.focus();
      });
    });
    animateIn(box);
  }

  function cardsHTML(a) {
    return '<div class="cards">' + a.map(function (g, i) {
      var buy = isBuy(g), edge = isEdge(g);
      var sideCls = edge ? (buy ? "edge-buy" : "edge-sell") : (buy ? "buy" : "sell");
      var cardCls = edge ? (buy ? "is-edge-buy" : "is-edge-sell") : (buy ? "is-buy" : "is-sell");
      return '<button type="button" class="card ' + cardCls + (g.recent ? "" : " stale") + '" data-sig="' + g._id + '" style="animation-delay:' + Math.min(i * 35, 400) + 'ms" ' +
        'aria-label="' + esc(g.symbol + " " + (LV[g.level] || g.level) + " " + typeName(g.type) + ",分数 " + g.score.toFixed(1) + "," + (g.confirmed ? "已确认" : "未确认,可能重绘")) + '">' +
        '<div class="card-top">' + ringHTML(g.score) +
        '<div class="card-id"><div class="sym">' + esc(g.symbol) + '<span class="side-tag ' + sideCls + '">' + (edge ? (buy ? "下沿买" : "上沿卖") : ((buy ? "买" : "卖") + " · " + typeName(g.type))) + preBadge(g) + '</span></div>' +
        '<div class="card-price">信号价 <span class="num">' + fmtPrice(g.price) + '</span></div></div></div>' +
        chipsHTML(g) +
        '<div class="card-meta">' +
        '<div><div class="meta-k">信号时间</div><div class="meta-v num" title="' + esc(fmtTime(g.time, g.level)) + '">' + esc(shortTime(g.time)) + '</div></div>' +
        '<div><div class="meta-k">距今</div><div class="meta-v"><span class="num">' + esc(g.bars_ago) + '</span> 根</div></div>' +
        '<div><div class="meta-k">共振</div><div class="meta-v">' + esc(RES[g.resonance] || "—") + '</div></div>' +
        '</div></button>';
    }).join("") + '</div>';
  }
  function shortTime(t) { if (!t) return "—"; return t.length > 10 ? t.slice(5) : t; }

  function tableHTML(a) {
    function th(label, key, cls) {
      var sorted = F.sort === key, arr = sorted ? (F.dir === "desc" ? "▼" : "▲") : "↕";
      return '<th scope="col" class="' + (cls || "") + '"' + (sorted ? ' aria-sort="' + (F.dir === "desc" ? "descending" : "ascending") + '"' : "") + '>' +
        '<button type="button" class="th-btn" data-sort="' + key + '">' + label + ' <span class="arr" aria-hidden="true">' + arr + '</span></button></th>';
    }
    var head = '<tr>' + th("分数", "score") + th("标的", "symbol") +
      '<th scope="col" class="plain">类型</th><th scope="col" class="plain">级别</th><th scope="col" class="plain">确认</th>' +
      th("信号时间", "time") + th("距今", "bars_ago", "r") + '<th scope="col" class="plain r">价格</th>' + th("离中枢", "margin", "r") +
      '<th scope="col" class="plain">共振</th></tr>';
    var rows = a.map(function (g) {
      var buy = isBuy(g);
      return '<tr tabindex="0" data-sig="' + g._id + '" aria-label="' + esc(g.symbol + " " + typeName(g.type) + " 分数 " + g.score.toFixed(1) + ",按回车查看详情") + '">' +
        '<td>' + sbarHTML(g.score) + '</td>' +
        '<td class="t-sym">' + esc(g.symbol) + '</td>' +
        '<td><span class="chip ' + (isEdge(g) ? (buy ? "chip-edge-buy" : "chip-edge-sell") : (buy ? "chip-buy" : "chip-sell")) + '">' + esc(typeName(g.type)) + '</span>' + preBadge(g) + '</td>' +
        '<td><span class="chip chip-lv">' + esc(LV[g.level] || g.level) + '</span></td>' +
        '<td>' + (g.confirmed ? '<span class="chip chip-ok">已确认</span>' : '<span class="chip chip-un" title="可能重绘">未确认</span>') + (g.recent ? "" : ' <span class="chip chip-stale">过期</span>') + '</td>' +
        '<td class="num">' + esc(fmtTime(g.time, g.level)) + '</td>' +
        '<td class="r num">' + esc(g.bars_ago) + '</td>' +
        '<td class="r num">' + fmtPrice(g.price) + '</td>' +
        '<td class="r num">' + (g.margin_pct != null ? fmtPct(g.margin_pct) : "—") + '</td>' +
        '<td>' + esc(RES[g.resonance] || "—") + '</td></tr>';
    }).join("");
    return '<div class="table-wrap"><table><caption class="sr-only">信号表格,点击表头排序,点击行查看详情</caption><thead>' + head + '</thead><tbody>' + rows + '</tbody></table></div>';
  }

  // ---------- 标的总览 ----------
  function symInfo(sym) {
    var list = SIGS.filter(function (g) { return g.symbol === sym; });
    var latest = list.slice().sort(function (a, b) { return (a.time < b.time ? 1 : a.time > b.time ? -1 : b.score - a.score); })[0] || null;
    var best = list.slice().sort(function (a, b) { return b.score - a.score; })[0] || null;
    return { list: list, latest: latest, best: best };
  }
  function lastClose(s) {
    var lv = s.levels || {};
    var x = lv.daily || lv["30m"] || lv.weekly;
    return x ? x : null;
  }
  function renderSymbols() {
    if (!D) return;
    var syms = allSymbols();
    $("sym-count").textContent = syms.length;
    if (!syms.length) { $("sym-grid").innerHTML = stateHTML("empty", "暂无标的", "数据中没有任何标的。"); return; }
    $("sym-grid").innerHTML = syms.map(function (sym, i) {
      var s = (D.symbols && D.symbols[sym]) || {}, info = symInfo(sym), lc = lastClose(s);
      var dirs = LV_ORDER.map(function (l) {
        var x = (s.levels || {})[l];
        if (!x) return '<span class="dir na" title="' + esc(LV[l]) + ' 无数据">' + esc(LV[l]) + '</span>';
        var d = x.state && x.state.direction;
        return '<span class="dir ' + esc(d) + '" title="' + esc(LV[l] + ":" + (DIR[d] || d) + "," + (POS[x.state.pivot_pos] || "")) + '">' + esc(LV[l]) + ' ' + (d === "up" ? "↑" : d === "down" ? "↓" : "→") + '</span>';
      }).join("");
      var body;
      if (info.latest) {
        var L = info.latest, B = info.best, tb = tier(B.score);
        body = '<div class="sym-latest">' +
          '<div class="row"><span class="muted">最新</span><span class="' + (isBuy(L) ? "t-buy" : "t-sell") + '" style="font-weight:650">' + esc(LV[L.level] || L.level) + ' ' + esc(typeName(L.type)) + (L.confirmed ? "" : ' <span style="color:var(--warn)" title="未确认,可能重绘">!</span>') + '</span></div>' +
          '<div class="row"><span class="muted">时间</span><span class="num">' + esc(shortTime(L.time)) + '</span></div>' +
          '<div class="row"><span class="muted">最高分</span><span class="mini-score tier-' + tb.k + '"><span class="mini-bar"><i style="width:' + B.score * 10 + '%"></i></span><b class="num" style="color:var(--t1)">' + B.score.toFixed(1) + '</b></span></div>' +
          '<div class="row"><span class="muted">信号数</span><span>' + info.list.length + ' 条 · 近期 ' + info.list.filter(function (g) { return g.recent; }).length + '</span></div></div>';
      } else {
        body = '<div class="sym-empty" role="status">暂无信号<span class="muted"> · 仍可打开查看多级别状态</span></div>';
      }
      return '<button type="button" class="sym-card' + (info.latest ? "" : " is-empty") + '" data-sym="' + esc(sym) + '" style="animation-delay:' + Math.min(i * 25, 400) + 'ms" aria-label="' + esc(sym + (info.latest ? ",查看详情" : ",暂无信号,查看状态")) + '">' +
        '<div class="sym-head"><span class="sym">' + esc(sym) + ((HELD && HELD[sym]) ? ' <span class="held-badge" title="IBKR 持仓中">持有</span>' : "") + '</span><span class="sym-close">' + (lc ? '<span class="num">' + fmtPrice(lc.last_close) + '</span>' : "—") + '</span></div>' +
        '<div class="dirs">' + dirs + '</div>' + body + '</button>';
    }).join("");
    qsa("[data-sym]", $("sym-grid")).forEach(function (el) {
      el.addEventListener("click", function () { var sym = el.getAttribute("data-sym"), info = symInfo(sym); openDrawer(sym, info.best, el); });
    });
  }

  // ---------- 详情抽屉 ----------
  function explain(g) {
    var b = g.score_breakdown || {}, out = [], t = g.type, buy = isBuy(g);
    if (isEdge(g)) {
      out.push(["base", typeName(t) + "为中枢沿启发式信号(非经典一二三类买卖点):价格接近/触及中枢" + (buy ? "下沿 ZD" : "上沿 ZG") + ",基础分 " + fmtSigned(b.base, 1) + "。" + (g.dist_pct != null ? "距沿 " + num(g.dist_pct, 0).toFixed(3) + "%。" : "")]);
    } else {
    var kind = t.charAt(0);
    if (kind === "1") out.push(["base", typeName(t) + "为逆势信号(趋势背驰),基础分 " + fmtSigned(b.base, 1) + ",主要依赖背驰证据。"]);
    else if (kind === "2") out.push(["base", typeName(t) + ":一" + (buy ? "买" : "卖") + "之后的回抽未" + (buy ? "跌破前低" : "突破前高") + ",反转已部分确认,基础分 " + fmtSigned(b.base, 1) + "。" + (g.ref_low != null ? "参考低点 " + fmtPrice(g.ref_low) + "。" : "")]);
    else if (kind === "3") out.push(["base", typeName(t) + ":离开中枢后回抽未重新进入中枢,属趋势延续,基础分 " + fmtSigned(b.base, 1) + "。"]);
    }
    if (g.ratio != null) out.push(["divergence", "MACD 面积比(离开段/进入段)= " + num(g.ratio, 0).toFixed(2) + ",越小背驰越明显,背驰项 " + fmtSigned(b.divergence) + "。"]);
    else out.push(["divergence", "该类型不计背驰项(仅一买/一卖计算)。"]);
    var vs = (g.resonance_vs || []).map(function (l) { return LV[l] || l; }).join("、");
    var resTxt = { strong: "与更大级别(" + vs + ")方向一致,强共振", partial: "与部分更大级别(" + vs + ")方向一致,部分共振", mixed: "更大级别方向不一,混合", neutral: "更大级别处于中枢内或方向不明,中性", conflict: "与更大级别(" + vs + ")方向相反,冲突" }[g.resonance];
    out.push(["resonance", (resTxt || (g.level === "weekly" ? "周线无更大级别可比较" : "无共振信息")) + ",共振项 " + fmtSigned(b.resonance) + "。"]);
    out.push(["confirmed", g.confirmed ? "所在线段已被特征序列分型确认,确认项 " + fmtSigned(b.confirmed) + "。" : "最后一段尚未被特征序列分型确认,扣 " + fmtSigned(b.confirmed) + ";该信号可能重绘或消失。"]);
    var R = RECENT_WIN[g.level];
    out.push(["freshness", "距今 " + g.bars_ago + " 根K线(近期窗口 " + R + " 根)" + (g.bars_ago > R ? ",已过期,大幅扣分" : g.bars_ago <= R / 4 ? ",非常新鲜" : g.bars_ago <= R / 2 ? ",较新" : ",仍在窗口内") + ",新鲜度 " + fmtSigned(b.freshness) + "。"]);
    var qp = [];
    if (g.zg != null && g.zd != null && g.price) qp.push("中枢宽度 " + ((g.zg - g.zd) / g.price * 100).toFixed(2) + "%(≥6% 满分)");
    if (g.margin_pct != null) qp.push((buy ? "回抽低点高于中枢上沿 ZG " : "反弹高点低于中枢下沿 ZD ") + fmtPct(g.margin_pct) + "(≥4% 满分)");
    if (kind === "1" && g.dif_leave != null) qp.push("DIF 极值" + (Math.abs(g.dif_leave) < Math.abs(g.dif_enter) ? "同步背驰" : "未同步背驰"));
    out.push(["quality", (qp.length ? qp.join(";") : "无额外质量指标") + ",质量项 " + fmtSigned(b.quality) + "。"]);
    return out;
  }

  function breakdownHTML(g) {
    var b = g.score_breakdown || {}, MAX = 4;
    var rows = BK.map(function (p) {
      var v = num(b[p[0]], 0), w = Math.min(Math.abs(v), MAX) / MAX * 50;
      var cls = v > 0 ? "pos" : v < 0 ? "neg" : "zero";
      var left = v >= 0 ? 50 : 50 - w;
      return '<div class="bd-row"><span class="bd-name">' + p[1] + '</span>' +
        '<div class="bd-axis" style="--zero:50%" role="img" aria-label="' + p[1] + ' ' + fmtSigned(v) + '">' +
        (v ? '<span class="bd-fill ' + cls + '" style="left:' + left + '%;width:0" data-w="' + w + '%"></span>' : "") + '</div>' +
        '<span class="bd-val num ' + cls + '">' + fmtSigned(v) + '</span></div>';
    }).join("");
    return '<div class="bd-list">' + rows + '<div class="bd-total"><span>原始合计 <b class="num">' + fmtSigned(b.raw_total) + '</b>' + (b.capped ? "(已截断到 0–10)" : "") + '</span><span>最终分数 <b class="num" style="color:var(--text)">' + g.score.toFixed(1) + '</b> / 10</span></div>' +
      '<p class="muted small" style="margin:2px 0 0">刻度 −4 … 0 … +4;启发式权重,未回测,不是胜率。</p></div>';
  }

  function levelsHTML(sym) {
    var s = D.symbols[sym] || {}, lv = s.levels || {};
    return '<div class="levels">' + LV_ORDER.map(function (l) {
      var x = lv[l];
      if (!x) return '<div class="lv-card"><div class="lv-name">' + LV[l] + '<span class="dir na">无数据</span></div><div class="muted">历史过短或获取失败</div></div>';
      var st = x.state || {}, d = st.direction, seg = x.last_segment || {};
      return '<div class="lv-card"><div class="lv-name">' + LV[l] + '<span class="dir ' + esc(d) + '">' + esc(DIR[d] || d || "—") + '</span></div>' +
        '<div>收盘 <b class="num">' + fmtPrice(x.last_close) + '</b></div>' +
        '<div class="muted">' + esc(POS[st.pivot_pos] || st.pivot_pos || "—") + (st.zg != null ? ' · ZG ' + fmtPrice(st.zg) + ' / ZD ' + fmtPrice(st.zd) : "") + '</div>' +
        '<div class="muted">末段 ' + (seg.up ? "↑" : "↓") + ' ' + esc(shortTime(seg.start)) + ' → ' + esc(shortTime(seg.end)) + (seg.confirmed === false ? '(未确认)' : '') + '</div>' +
        '<div class="muted">' + esc(x.bars) + ' 根 · 截至 ' + esc(x.last) + '</div></div>';
    }).join("") + '</div>';
  }

  function openDrawer(sym, g, opener) {
    if (!D) return;
    var s = D.symbols[sym] || {};
    current = { sym: sym, g: g };
    if (opener && !$("drawer").contains(opener)) lastFocus = opener;
    var head = '<h2 id="dr-title">' + esc(sym) + (g ? ' <span class="side-tag ' + (isEdge(g) ? (isBuy(g) ? "edge-buy" : "edge-sell") : (isBuy(g) ? "buy" : "sell")) + '">' + (isEdge(g) ? esc(typeName(g.type)) : ((isBuy(g) ? "买" : "卖") + " · " + typeName(g.type))) + '</span>' : ' <span class="chip">暂无信号</span>') + '</h2><button type="button" class="mini-btn" id="dr-profile" data-sym="' + esc(sym) + '">简介</button>' + (g ? chipsHTML(g, { res: true }) : "");
    $("dr-headline").innerHTML = head;
    var pfb = $("dr-profile");
    if (pfb) pfb.addEventListener("click", function () { openProfile(sym, pfb); });
    var h = "";
    if (g) {
      h += '<div class="d-hero">' + ringHTML(g.score, true) + '<div class="d-hero-stats">' +
        stat("信号价", fmtPrice(g.price), true) + (g.stop_price != null ? stat("止损价", fmtPrice(g.stop_price), true) : "") + stat("信号时间", fmtTime(g.time, g.level), true) + stat("距今", g.bars_ago + " 根K线") +
        stat("中枢 ZG", fmtPrice(g.zg), true) + stat("中枢 ZD", fmtPrice(g.zd), true) +
        (g.ratio != null ? stat("MACD 面积比", num(g.ratio, 0).toFixed(2), true) : stat("离中枢", g.margin_pct != null ? fmtPct(g.margin_pct) : "—", true)) +
        '</div></div>';
      if (!g.confirmed) h += '<div class="d-warn" role="note"><span aria-hidden="true">⚠</span><div><b>未确认信号,可能重绘。</b>最后一段尚未被特征序列分型确认,后续K线可能使该信号改变或消失。' + (g.repaint_warning ? '<div class="muted small" style="margin-top:4px">' + esc(g.repaint_warning) + '</div>' : "") + '</div></div>';
      h += '<section class="d-block"><h3>分项评分 <span class="tier-txt tier-' + tier(g.score).k + '">' + tier(g.score).label + '分段</span></h3>' + breakdownHTML(g) + '</section>';
      h += '<section class="d-block"><h3>解读</h3><ul class="explain">' + explain(g).map(function (e) {
        var v = num((g.score_breakdown || {})[e[0]], 0);
        return '<li style="--b:' + (v > 0 ? "var(--hi)" : v < 0 ? "var(--mid2)" : "var(--text-3)") + '"><span>' + esc(e[1]) + '</span></li>';
      }).join("") + '</ul></section>';
    } else {
      h += '<div class="d-warn" role="note" style="border-style:solid"><div>该标的当前数据中没有检测到信号。</div></div>';
    }
    h += '<section class="d-block"><h3>多级别状态</h3>' + levelsHTML(sym) + '</section>';
    var interactive = !!(window.ChanInteractive && ChanInteractive.isSupported(sym));
    h += '<section class="d-block"><h3>交互缠论图</h3>' +
      '<div id="ichart-root" class="ichart-root"></div></section>';
    if (s.image) {
      h += '<section class="d-block"><h3>静态对照图(可选)<span class="muted small">周 / 日 / 30分钟 PNG</span></h3>';
      h += '<details class="png-details"><summary class="muted small">展开静态 PNG</summary>';
      h += '<button type="button" class="chart-box" id="chart-btn" aria-label="全屏查看 ' + esc(sym) + ' 缠论图"><div class="chart-skel skeleton" id="chart-skel"></div><img id="chart-img" alt="' + esc(sym) + ' 缠论图:周线、日线、30分钟" hidden>' +
        '<span class="zoom-hint" aria-hidden="true">⤢ 全屏</span></button></details></section>';
    }

    var others = SIGS.filter(function (x) { return x.symbol === sym; }).sort(function (a, b) { return b.score - a.score; });
    if (others.length > 1 || (others.length && !g)) {
      h += '<section class="d-block"><h3>该标的全部信号 <span class="count">' + others.length + '</span></h3><div class="other-sigs">' + others.map(function (x) {
        var t = tier(x.score);
        return '<button type="button" class="other" data-other="' + x._id + '"' + (g && x._id === g._id ? ' aria-current="true"' : "") + '>' +
          '<span class="mini-score tier-' + t.k + '"><b class="num" style="color:var(--t1);width:28px">' + x.score.toFixed(1) + '</b></span>' +
          '<span class="' + (isEdge(x) ? (isBuy(x) ? "t-edge-buy" : "t-edge-sell") : (isBuy(x) ? "t-buy" : "t-sell")) + '" style="font-weight:650">' + esc(typeName(x.type)) + '</span>' +
          '<span class="grow">' + esc(LV[x.level] || x.level) + ' · ' + esc(fmtTime(x.time, x.level)) + '</span>' +
          (x.confirmed ? "" : '<span class="chip chip-un">未确认</span>') + (x.recent ? "" : '<span class="chip chip-stale">过期</span>') + '</button>';
      }).join("") + '</div></section>';
    }
    h += '<button type="button" class="btn" id="dr-filter" style="align-self:flex-start">在信号列表中只看 ' + esc(sym) + '</button>';
    $("dr-body").innerHTML = h;
    $("dr-body").scrollTop = 0;

    if (window.ChanInteractive && $("ichart-root")) {
      var preferred = (g && g.level) || "daily";
      ChanInteractive.mount($("ichart-root"), sym, { level: preferred });
    }
    if (s.image && $("chart-img")) {
      var img = $("chart-img");
      img.onload = function () { img.hidden = false; var sk = $("chart-skel"); if (sk) sk.remove(); };
      img.onerror = function () { var sk = $("chart-skel"); if (sk) { sk.classList.remove("skeleton"); sk.style.aspectRatio = "auto"; sk.style.padding = "20px"; sk.style.color = "#666"; sk.textContent = "图片加载失败"; } };
      img.src = s.image;
      if ($("chart-btn")) $("chart-btn").addEventListener("click", function () { openLightbox(s.image, sym + " 缠论图(周/日/30分钟)", this); });
    }
    qsa("[data-other]", $("dr-body")).forEach(function (b) {
      b.addEventListener("click", function () { var x = SIGS[+b.getAttribute("data-other")]; openDrawer(x.symbol, x); var f = document.querySelector('[data-other="' + x._id + '"]'); if (f) f.focus(); });
    });
    $("dr-filter").addEventListener("click", function () {
      F.q = sym; F.recent = false; onFilter(); closeDrawer(); setView("signals");
      $("h-signals").scrollIntoView({ behavior: "smooth", block: "start" });
    });

    var dr = $("drawer");
    if (dr.hidden) {
      dr.classList.remove("closing"); dr.hidden = false; $("scrim").hidden = false;
      document.body.style.overflow = "hidden";
      setTimeout(function () { $("dr-close").focus(); }, 30);
    }
    animateIn(dr);
  }
  function stat(k, v, mono) { return '<div><div class="meta-k">' + k + '</div><div class="meta-v' + (mono ? " num" : "") + '" title="' + esc(v) + '">' + esc(v) + '</div></div>'; }

  function closeDrawer() {
    var dr = $("drawer"); if (dr.hidden) return;
    dr.classList.add("closing");
    $("scrim").hidden = true;
    setTimeout(function () { dr.hidden = true; dr.classList.remove("closing"); }, 200);
    document.body.style.overflow = "";
    current = null;
    if (window.ChanInteractive) ChanInteractive.destroy();
    if (lastFocus && document.body.contains(lastFocus)) lastFocus.focus();
  }
  $("dr-close").addEventListener("click", closeDrawer);
  $("scrim").addEventListener("click", closeDrawer);

  // ---------- 全屏图 ----------
  var LB = { s: 1, fit: 1, x: 0, y: 0, w: 0, h: 0, opener: null, ptrs: {}, pinch: null };
  function lbApply() {
    var img = $("lb-img");
    img.style.transform = "translate(calc(-50% + " + LB.x + "px), calc(-50% + " + LB.y + "px)) scale(" + LB.s + ")";
    $("lb-zoom").textContent = Math.round(LB.s * 100) + "%";
  }
  function lbFit() {
    var st = $("lb-stage").getBoundingClientRect();
    if (!LB.w) return;
    LB.fit = Math.min((st.width - 24) / LB.w, (st.height - 24) / LB.h, 1.5);
    LB.s = LB.fit; LB.x = 0; LB.y = 0; lbApply();
  }
  function lbZoom(f, cx, cy) {
    var ns = Math.max(LB.fit * 0.5, Math.min(LB.s * f, 6));
    if (cx != null) {
      var st = $("lb-stage").getBoundingClientRect();
      var ox = cx - st.left - st.width / 2, oy = cy - st.top - st.height / 2;
      LB.x = ox - (ox - LB.x) * ns / LB.s; LB.y = oy - (oy - LB.y) * ns / LB.s;
    } else { LB.x *= ns / LB.s; LB.y *= ns / LB.s; }
    LB.s = ns; lbApply();
  }
  function openLightbox(src, title, opener) {
    LB.opener = opener;
    var lb = $("lightbox"), img = $("lb-img");
    $("lb-title").textContent = title; img.alt = title; $("lb-open").href = src;
    lb.hidden = false;
    img.onload = function () { LB.w = img.naturalWidth; LB.h = img.naturalHeight; img.style.width = LB.w + "px"; img.style.height = LB.h + "px"; lbFit(); };
    img.src = src;
    if (img.complete && img.naturalWidth) img.onload();
    setTimeout(function () { $("lb-close").focus(); }, 30);
  }
  function closeLightbox() {
    $("lightbox").hidden = true;
    if (LB.opener && document.body.contains(LB.opener)) LB.opener.focus();
  }
  // ---------- 公司简介 ----------
  var PROFILE_CACHE = null, pfOpener = null;
  function loadProfiles(cb) {
    if (PROFILE_CACHE) { cb(PROFILE_CACHE); return; }
    fetch("data/company_profiles.json", { cache: "no-store" })
      .then(function (r) { if (!r.ok) throw new Error("HTTP " + r.status); return r.json(); })
      .then(function (d) { PROFILE_CACHE = d || {}; cb(PROFILE_CACHE); })
      .catch(function () { PROFILE_CACHE = {}; cb(PROFILE_CACHE); });
  }
  function openProfile(sym, opener) {
    pfOpener = opener || null;
    var m = $("profile-modal");
    if (!m) return;
    $("pf-title").textContent = sym + " 简介";
    $("pf-body").innerHTML = '<p class="muted">加载中…</p>';
    m.hidden = false;
    loadProfiles(function (P) {
      var p = P[sym];
      $("pf-body").innerHTML = p
        ? '<div class="pf-name">' + esc(p.name) + '</div><p>' + esc(p.desc) + '</p>'
        : '<p class="muted">暂无该标的的简介。</p>';
    });
    setTimeout(function () { $("pf-close").focus(); }, 30);
  }
  function closeProfile() {
    $("profile-modal").hidden = true;
    if (pfOpener && document.body.contains(pfOpener)) pfOpener.focus();
  }
  $("pf-close").addEventListener("click", closeProfile);
  $("profile-modal").addEventListener("click", function (e) { if (e.target === this) closeProfile(); });
  $("lb-close").addEventListener("click", closeLightbox);
  $("lb-in").addEventListener("click", function () { lbZoom(1.25); });
  $("lb-out").addEventListener("click", function () { lbZoom(0.8); });
  $("lb-fit").addEventListener("click", lbFit);
  var stage = $("lb-stage");
  stage.addEventListener("wheel", function (e) { e.preventDefault(); lbZoom(e.deltaY < 0 ? 1.12 : 0.89, e.clientX, e.clientY); }, { passive: false });
  stage.addEventListener("dblclick", function (e) { if (LB.s > LB.fit * 1.05) lbFit(); else lbZoom(2.2 / (LB.s / LB.fit), e.clientX, e.clientY); });
  stage.addEventListener("pointerdown", function (e) {
    stage.setPointerCapture(e.pointerId); LB.ptrs[e.pointerId] = { x: e.clientX, y: e.clientY };
    stage.classList.add("dragging");
    var ids = Object.keys(LB.ptrs);
    if (ids.length === 2) { var a = LB.ptrs[ids[0]], b = LB.ptrs[ids[1]]; LB.pinch = Math.hypot(a.x - b.x, a.y - b.y); }
  });
  stage.addEventListener("pointermove", function (e) {
    var p = LB.ptrs[e.pointerId]; if (!p) return;
    var ids = Object.keys(LB.ptrs);
    if (ids.length === 2 && LB.pinch) {
      p.x = e.clientX; p.y = e.clientY;
      var a = LB.ptrs[ids[0]], b = LB.ptrs[ids[1]], d = Math.hypot(a.x - b.x, a.y - b.y);
      lbZoom(d / LB.pinch, (a.x + b.x) / 2, (a.y + b.y) / 2); LB.pinch = d; return;
    }
    LB.x += e.clientX - p.x; LB.y += e.clientY - p.y; p.x = e.clientX; p.y = e.clientY; lbApply();
  });
  function ptrEnd(e) { delete LB.ptrs[e.pointerId]; if (Object.keys(LB.ptrs).length < 2) LB.pinch = null; if (!Object.keys(LB.ptrs).length) stage.classList.remove("dragging"); }
  stage.addEventListener("pointerup", ptrEnd); stage.addEventListener("pointercancel", ptrEnd);
  stage.addEventListener("keydown", function (e) {
    var step = 60, k = e.key;
    if (k === "ArrowLeft") LB.x += step; else if (k === "ArrowRight") LB.x -= step;
    else if (k === "ArrowUp") LB.y += step; else if (k === "ArrowDown") LB.y -= step;
    else if (k === "+" || k === "=") return lbZoom(1.25); else if (k === "-") return lbZoom(0.8); else if (k === "0") return lbFit();
    else return;
    e.preventDefault(); lbApply();
  });
  window.addEventListener("resize", function () { if (!$("lightbox").hidden) lbFit(); });

  // ---------- 键盘:Esc 与焦点陷阱 ----------
  function trap(container, e) {
    var f = qsa('button:not([disabled]),[href],input,select,[tabindex]:not([tabindex="-1"])', container).filter(function (el) { return el.offsetParent !== null || el === document.activeElement; });
    if (!f.length) return;
    var first = f[0], last = f[f.length - 1];
    if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
    else if (!container.contains(document.activeElement)) { e.preventDefault(); first.focus(); }
  }
  document.addEventListener("keydown", function (e) {
    var lbOpen = !$("lightbox").hidden, drOpen = !$("drawer").hidden;
    if (e.key === "Escape") { if (!$("profile-modal").hidden) closeProfile(); else if (lbOpen) closeLightbox(); else if (drOpen) closeDrawer(); }
    else if (e.key === "Tab") { if (lbOpen) trap($("lightbox"), e); else if (drOpen) trap($("drawer"), e); }
    else if (e.key === "/" && !lbOpen && !drOpen && document.activeElement.tagName !== "INPUT") {
      e.preventDefault(); setView("signals"); var fs = $("filters"); fs.classList.add("open"); $("btn-filters").setAttribute("aria-expanded", "true"); $("f-q").focus();
    }
  });

  // ---------- 启动 ----------
  syncControls();
  if (window.ChanInteractive && ChanInteractive.setMarket) ChanInteractive.setMarket(MARKET);
  syncMarketUI();
  setView(location.hash.slice(1) || "signals", true);
  load();
  // 每分钟刷新相对时间
  setInterval(function () { if (D) { var g = new Date(D.generated); if (!isNaN(g)) $("meta-short").textContent = "更新于 " + relTime(g) + " · " + g.toLocaleString("zh-CN", { hour12: false, month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" }); } }, 60000);
})();
