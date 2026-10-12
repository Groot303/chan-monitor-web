/* Interactive Chan chart (Lightweight Charts, local vendor). Currently NVDA sample. */
(function (global) {
  "use strict";
  var SUPPORTED = { NVDA: true };
  var LV_LABEL = { weekly: "周线", daily: "日线", "30m": "30分钟" };
  var LV_ORDER = ["weekly", "daily", "30m"];
  var TYPE_NAME = { "1B": "一买", "2B": "二买", "3B": "三买", "1S": "一卖", "2S": "二卖", "3S": "三卖" };

  var state = {
    root: null,
    chart: null,
    candle: null,
    stroke: null,
    segSeries: [],
    overlay: null,
    host: null,
    data: null,
    symbol: null,
    level: "daily",
    show: { strokes: true, segments: true, pivots: true, signals: true },
    ro: null,
    unsub: null,
  };

  function css(name) {
    return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  }
  function isBuy(t) { return String(t).indexOf("B") >= 0; }
  function theme() {
    var dark = document.documentElement.getAttribute("data-theme") !== "light";
    return {
      dark: dark,
      bg: css("--surface") || (dark ? "#121826" : "#ffffff"),
      text: css("--text-2") || "#aab3c5",
      grid: dark ? "rgba(148,163,184,.10)" : "rgba(15,23,42,.08)",
      border: css("--border") || "rgba(148,163,184,.14)",
      up: css("--buy") || "#f0505e",
      down: css("--sell") || "#1fc47d",
      stroke: dark ? "rgba(200,210,230,.55)" : "rgba(60,70,90,.55)",
      seg: css("--hi") || "#5b8cff",
      pivot: "rgba(245,177,76,.22)",
      pivotStroke: "rgba(245,177,76,.55)",
    };
  }

  function destroyChart() {
    if (state.unsub) { try { state.unsub(); } catch (e) {} state.unsub = null; }
    if (state.ro) { try { state.ro.disconnect(); } catch (e) {} state.ro = null; }
    if (state.chart) { try { state.chart.remove(); } catch (e) {} }
    state.chart = null; state.candle = null; state.stroke = null; state.segSeries = [];
    if (state.host) state.host.innerHTML = "";
  }

  function destroy() {
    destroyChart();
    if (state.root) state.root.innerHTML = "";
    state.root = null; state.data = null; state.symbol = null; state.overlay = null; state.host = null;
  }

  function buildToolbar(root, levels) {
    var bar = document.createElement("div");
    bar.className = "ichart-toolbar";
    var lvWrap = document.createElement("div");
    lvWrap.className = "seg ichart-levels";
    lvWrap.setAttribute("role", "tablist");
    lvWrap.setAttribute("aria-label", "K线级别");
    LV_ORDER.forEach(function (lv) {
      if (!levels[lv]) return;
      var b = document.createElement("button");
      b.type = "button";
      b.className = "seg-btn";
      b.setAttribute("role", "tab");
      b.dataset.lv = lv;
      b.textContent = LV_LABEL[lv] || lv;
      b.setAttribute("aria-selected", lv === state.level ? "true" : "false");
      b.setAttribute("aria-pressed", lv === state.level ? "true" : "false");
      b.addEventListener("click", function () {
        if (state.level === lv) return;
        state.level = lv;
        Array.prototype.forEach.call(lvWrap.querySelectorAll(".seg-btn"), function (x) {
          var on = x.dataset.lv === lv;
          x.setAttribute("aria-selected", on ? "true" : "false");
          x.setAttribute("aria-pressed", on ? "true" : "false");
        });
        renderLevel();
      });
      lvWrap.appendChild(b);
    });
    bar.appendChild(lvWrap);

    var toggles = document.createElement("div");
    toggles.className = "ichart-toggles";
    [
      ["strokes", "笔"],
      ["segments", "线段"],
      ["pivots", "中枢"],
      ["signals", "买卖点"],
    ].forEach(function (pair) {
      var key = pair[0], label = pair[1];
      var b = document.createElement("button");
      b.type = "button";
      b.className = "ichart-tog";
      b.setAttribute("aria-pressed", state.show[key] ? "true" : "false");
      b.textContent = label;
      b.addEventListener("click", function () {
        state.show[key] = !state.show[key];
        b.setAttribute("aria-pressed", state.show[key] ? "true" : "false");
        renderLevel();
      });
      toggles.appendChild(b);
    });
    bar.appendChild(toggles);
    root.appendChild(bar);
  }

  function drawPivots() {
    var ov = state.overlay, candle = state.candle, chart = state.chart;
    if (!ov || !candle || !chart) return;
    var lv = state.data && state.data.levels[state.level];
    var pivots = (lv && state.show.pivots) ? (lv.pivots || []) : [];
    var w = ov.clientWidth, h = ov.clientHeight;
    var dpr = Math.min(window.devicePixelRatio || 1, 2);
    ov.width = Math.max(1, Math.floor(w * dpr));
    ov.height = Math.max(1, Math.floor(h * dpr));
    var ctx = ov.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);
    if (!pivots.length) return;
    var ts = chart.timeScale();
    var th = theme();
    pivots.forEach(function (p) {
      var x1 = ts.timeToCoordinate(p.startTime);
      var x2 = ts.timeToCoordinate(p.endTime);
      var y1 = candle.priceToCoordinate(p.zg);
      var y2 = candle.priceToCoordinate(p.zd);
      if (x1 == null || x2 == null || y1 == null || y2 == null) return;
      var left = Math.min(x1, x2), right = Math.max(x1, x2);
      var top = Math.min(y1, y2), bot = Math.max(y1, y2);
      // extend a little so thin pivots remain visible
      if (right - left < 4) right = left + 4;
      ctx.fillStyle = th.pivot;
      ctx.strokeStyle = th.pivotStroke;
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.rect(left, top, right - left, bot - top);
      ctx.fill();
      ctx.stroke();
    });
  }

  function renderLevel() {
    if (!state.host || !state.data || !global.LightweightCharts) return;
    var lv = state.data.levels[state.level];
    if (!lv) return;
    destroyChart();
    var th = theme();
    var LC = global.LightweightCharts;
    state.host.innerHTML = "";
    var wrap = document.createElement("div");
    wrap.className = "ichart-canvas-wrap";
    var el = document.createElement("div");
    el.className = "ichart-canvas";
    var ov = document.createElement("canvas");
    ov.className = "ichart-overlay";
    ov.setAttribute("aria-hidden", "true");
    wrap.appendChild(el);
    wrap.appendChild(ov);
    state.host.appendChild(wrap);
    state.overlay = ov;

    var chart = LC.createChart(el, {
      autoSize: true,
      layout: {
        background: { color: th.bg },
        textColor: th.text,
        fontSize: 11,
        attributionLogo: false,
      },
      grid: {
        vertLines: { color: th.grid },
        horzLines: { color: th.grid },
      },
      crosshair: { mode: LC.CrosshairMode ? LC.CrosshairMode.Normal : 1 },
      rightPriceScale: { borderColor: th.border, scaleMargins: { top: 0.08, bottom: 0.08 } },
      timeScale: {
        borderColor: th.border,
        timeVisible: state.level === "30m",
        secondsVisible: false,
        rightOffset: 4,
      },
      handleScroll: { vertTouchDrag: false },
    });
    state.chart = chart;

    var candle = chart.addCandlestickSeries({
      upColor: th.up,
      downColor: th.down,
      borderUpColor: th.up,
      borderDownColor: th.down,
      wickUpColor: th.up,
      wickDownColor: th.down,
    });
    candle.setData(lv.ohlc);
    state.candle = candle;

    if (state.show.strokes && lv.strokes && lv.strokes.length) {
      var stroke = chart.addLineSeries({
        color: th.stroke,
        lineWidth: 1,
        priceLineVisible: false,
        lastValueVisible: false,
        crosshairMarkerVisible: false,
      });
      stroke.setData(lv.strokes.map(function (p) { return { time: p.time, value: p.price }; }));
      state.stroke = stroke;
    }

    state.segSeries = [];
    if (state.show.segments && lv.segments) {
      lv.segments.forEach(function (sg) {
        var series = chart.addLineSeries({
          color: th.seg,
          lineWidth: 2,
          lineStyle: sg.confirmed ? (LC.LineStyle ? LC.LineStyle.Solid : 0) : (LC.LineStyle ? LC.LineStyle.Dashed : 2),
          priceLineVisible: false,
          lastValueVisible: false,
          crosshairMarkerVisible: false,
        });
        series.setData([
          { time: sg.startTime, value: sg.startPrice },
          { time: sg.endTime, value: sg.endPrice },
        ]);
        state.segSeries.push(series);
      });
    }

    if (state.show.signals && lv.signals && lv.signals.length && candle.setMarkers) {
      var markers = lv.signals.map(function (s) {
        var buy = isBuy(s.type);
        var label = (TYPE_NAME[s.type] || s.type) + (s.confirmed ? "" : "?") + (s.score != null ? " " + Number(s.score).toFixed(1) : "");
        return {
          time: s.time,
          position: buy ? "belowBar" : "aboveBar",
          color: buy ? th.up : th.down,
          shape: buy ? "arrowUp" : "arrowDown",
          text: label,
        };
      });
      // markers must be sorted by time
      markers.sort(function (a, b) { return (a.time > b.time) - (a.time < b.time); });
      candle.setMarkers(markers);
    } else if (candle.setMarkers) {
      candle.setMarkers([]);
    }

    chart.timeScale().fitContent();
    var sub = function () { drawPivots(); };
    chart.timeScale().subscribeVisibleLogicalRangeChange(sub);
    chart.subscribeCrosshairMove(sub);
    state.unsub = function () {
      try { chart.timeScale().unsubscribeVisibleLogicalRangeChange(sub); } catch (e) {}
    };
    // resize observer for overlay DPR
    if (typeof ResizeObserver !== "undefined") {
      state.ro = new ResizeObserver(function () { drawPivots(); });
      state.ro.observe(wrap);
    }
    // first paint after layout
    requestAnimationFrame(function () { requestAnimationFrame(drawPivots); });
  }

  function mount(root, symbol, opts) {
    opts = opts || {};
    destroy();
    if (!SUPPORTED[symbol]) return Promise.resolve(false);
    if (!global.LightweightCharts) {
      root.innerHTML = '<div class="state" style="padding:16px"><p>交互图库未加载</p></div>';
      return Promise.resolve(false);
    }
    state.root = root;
    state.symbol = symbol;
    state.level = opts.level || "daily";
    root.innerHTML = '<div class="ichart-loading muted small">加载交互图数据…</div>';
    return fetch("data/charts/" + symbol + ".json", { cache: "no-cache" })
      .then(function (r) {
        if (!r.ok) throw new Error("HTTP " + r.status);
        return r.json();
      })
      .then(function (data) {
        if (!state.root) return false;
        state.data = data;
        if (!data.levels[state.level]) {
          state.level = LV_ORDER.find(function (l) { return data.levels[l]; }) || "daily";
        }
        root.innerHTML = "";
        var note = document.createElement("p");
        note.className = "ichart-note muted small";
        note.textContent = "交互图样例 · 可缩放拖动 · 灰线=笔 · 蓝线=线段(虚线未确认) · 橙块=中枢 · 箭头=买卖点。其他标的仍用静态 PNG。";
        root.appendChild(note);
        buildToolbar(root, data.levels);
        var host = document.createElement("div");
        host.className = "ichart-host";
        host.setAttribute("role", "img");
        host.setAttribute("aria-label", symbol + " 交互缠论图");
        root.appendChild(host);
        state.host = host;
        var tip = document.createElement("p");
        tip.className = "ichart-disclaimer muted small";
        tip.textContent = data.disclaimer || "启发式分析,不构成投资建议。";
        root.appendChild(tip);
        renderLevel();
        return true;
      })
      .catch(function (err) {
        if (!state.root) return false;
        root.innerHTML = '<div class="state" style="padding:16px"><p>交互图加载失败: ' + String(err.message || err) + '</p></div>';
        return false;
      });
  }

  function refreshTheme() {
    if (state.data && state.host) renderLevel();
  }

  global.ChanInteractive = {
    isSupported: function (sym) { return !!SUPPORTED[sym]; },
    supportedList: function () { return Object.keys(SUPPORTED); },
    mount: mount,
    destroy: destroy,
    refreshTheme: refreshTheme,
  };
})(window);
