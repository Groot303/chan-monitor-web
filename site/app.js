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
  // API_BASE: 后端API地址 (Cloudflare Tunnel HTTPS)。localStorage 可覆盖。
  var API_BASE = localStorage.getItem("chan.apiBase") || ""; // default same-origin: backend serves frontend
  var MK = {
    us: { label: "美股", signals: "data/signals.json", api: "/api/signals", tz: "ET", src: "Alpaca(IEX 免费版)", delay: "Alpaca 可能延迟",
          watch: ["AAOI","AAPL","AMD","AVGO","GOOG","INTC","LITE","META","MRNA","MRVL","MU","NOK","NVDA","ORCL","PLTR","SKHY","SNDK","SPCX","TSLA","TSM"],
          searchPh: "搜索代码,如 NVDA" },
    cn: { label: "A股", signals: "data/signals_cn.json", api: "/api/signals_cn", tz: "北京时间", src: "东方财富", delay: "东财数据可能延迟",
          watch: ["上证指数","科创50","银行指数","平均股价"],
          searchPh: "搜索指数,如 上证指数" }
  };
  function apiURL() { var m = MK[MARKET]; return (API_BASE || "") + m.api; }
  function staticURL() { return MK[MARKET].signals; }
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
  // API 地址设置
  (function initApiBase() {
    var input = $("api-base-input");
    input.value = API_BASE;
    input.addEventListener("change", function () {
      var v = this.value.trim().replace(/\/+$/, "");
      localStorage.setItem("chan.apiBase", v);
      API_BASE = v;
      toast(v ? "API 地址已保存，重新加载数据" : "已切换为静态模式");
      loadData();
    });
  })();

  // ---------- 导航 ----------
  function setView(v, noHash) {
    if (["signals", "symbols", "holdings", "about"].indexOf(v) < 0) v = "signals";
    VIEW = v;
    ["signals", "symbols", "holdings", "about"].forEach(function (x) { $("view-" + x).hidden = x !== v; });
    qsa(".tab[data-view]").forEach(function (b) {
      if (b.getAttribute("data-view") === v) b.setAttribute("aria-current", "page"); else b.removeAttribute("aria-current");
    });
    if (!noHash && location.hash.slice(1) !== v) history.replaceState(null, "", "#" + v);
    if (v === "symbols" && D) renderSymbols();
    if (v === "holdings") renderHoldings();
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
    $("sig-results").innerHTML = stateHTML("err", "数据加载失败", "无法读取 " + esc(url) + "(" + esc(e.message || e) + ")。若直接用 file:// 打开页面,请改用本地服务器,例如 <code>python3 -m http.server</code>。", '<button type="button" class="btn primary" id="retry">重试</button>');
    var r = $("retry"); if (r) r.addEventListener("click", load);
  }
  function load() {
    showLoading();
    $("meta-short").textContent = "加载中…";
    var apiU = apiURL() + "?t=" + Date.now(), staticU = staticURL() + "?t=" + Date.now();
    function getJSON(u) {
      return fetch(u, { cache: "no-store" })
        .then(function (r) { if (!r.ok) throw new Error("HTTP " + r.status); return r.json(); });
    }
    // 先走同源 API,失败时回落到静态 JSON(Cloudflare Pages 部署)
    getJSON(apiU).then(handleData).catch(function () {
      getJSON(staticU).then(handleData).catch(function (e) { showLoadErr(e, apiU); });
    });
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
    var head = '<h2 id="dr-title">' + esc(sym) + (g ? ' <span class="side-tag ' + (isEdge(g) ? (isBuy(g) ? "edge-buy" : "edge-sell") : (isBuy(g) ? "buy" : "sell")) + '">' + (isEdge(g) ? esc(typeName(g.type)) : ((isBuy(g) ? "买" : "卖") + " · " + typeName(g.type))) + '</span>' : ' <span class="chip">暂无信号</span>') + '</h2>' + (g ? chipsHTML(g, { res: true }) : "");
    $("dr-headline").innerHTML = head;
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
    h += '<section class="d-block"><h3>交互缠论图 <span class="muted small">可缩放拖动 · Lightweight Charts</span></h3>' +
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
    if (e.key === "Escape") { if (lbOpen) closeLightbox(); else if (drOpen) closeDrawer(); }
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
