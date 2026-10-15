#!/usr/bin/env python3
"""Fetch a macro snapshot (VIX, Treasury yields, gold/silver/oil/copper, USD index)
via Yahoo Finance (yfinance) and write out/macro.json.

Called best-effort from run2.py at the end of the US pipeline; a macro failure
must NEVER break signal generation, so every symbol is isolated and failures
are recorded in the output file instead of raising.

Output (out/macro.json):
  generated: UTC ISO timestamp
  source: "Yahoo Finance (yfinance)"
  indicators: {key: {name, value, unit, kind, change, change_label, read, asof, status,
                     series, window_chg, window_label, range}}
    series: [[date, close], ...] sampled to <= 60 points over ~90 days (for sparklines)
    window_chg: change over the series window (pp for yields, % otherwise)
    range: [window low, window high]
  regime: {label, risk_off_count, reasons}
  failures: {key: error}

Extension points (NOT yet wired — the frontend marks them 待接入, never fakes them):
  2Y yield (^FVX exists on Yahoo but has no clean series), CPI/core CPI, PCE/core PCE,
  NFP actuals, unemployment rate, initial claims, GDP, ISM PMI, Fed funds target rate.
  Adding one = new SYMBOLS-style entry + a dedicated fetcher (BLS/BEA/ISM/FRED),
  not a new macro.json schema.
"""
import json, os, datetime

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(ROOT, "out", "macro.json")

# key: (yahoo symbol, Chinese name, unit, kind)
SYMBOLS = {
    "vix":    ("^VIX",   "恐慌指数 VIX",   "",      "index"),
    "us10y":  ("^TNX",   "10年美债收益率", "%",     "yield"),
    "us3m":   ("^IRX",   "3个月美债收益率", "%",    "yield"),
    "gold":   ("GC=F",   "黄金 (COMEX)",   "$/盎司", "price"),
    "silver": ("SI=F",   "白银 (COMEX)",   "$/盎司", "price"),
    "oil":    ("CL=F",   "原油 WTI",       "$/桶",   "price"),
    "copper": ("HG=F",   "铜 (COMEX)",     "$/磅",   "price"),
    "dxy":    ("DX-Y.NYB", "美元指数",      "",      "index"),
}


def _read(ind, value, prev):
    """One-line Chinese interpretation. Plain rules, no black box."""
    if value is None:
        return "暂无数据"
    if ind == "vix":
        if value < 15:
            return "市场平静"
        if value < 20:
            return "波动处于正常区间"
        if value < 30:
            return "波动加剧，注意风险"
        return "恐慌区间"
    if ind == "spread":
        if value < 0:
            return "收益率曲线倒挂，衰退预警信号"
        if value < 1:
            return "利差收窄，关注曲线变化"
        return "收益率曲线正常"
    if ind in ("us10y", "us3m"):
        if prev is None:
            return ""
        d = value - prev
        if abs(d) < 0.005:
            return "收益率基本持平"
        return "收益率" + ("上行" if d > 0 else "下行")
    if ind == "gold":
        if prev is None:
            return ""
        c = (value - prev) / prev * 100
        if c > 1:
            return "避险情绪升温"
        if c < -1:
            return "避险情绪降温"
        return "变化不大"
    if ind == "silver":
        if prev is None:
            return ""
        c = (value - prev) / prev * 100
        if c > 1:
            return "跟随黄金走强"
        if c < -1:
            return "跟随黄金走弱"
        return "变化不大"
    if ind == "oil":
        if prev is None:
            return ""
        c = (value - prev) / prev * 100
        if c > 3:
            return "油价急涨，通胀压力"
        if c > 1:
            return "油价温和上涨，需求偏强"
        if c < -3:
            return "油价急跌，需求担忧"
        return "变化不大"
    if ind == "copper":
        if prev is None:
            return ""
        c = (value - prev) / prev * 100
        if c > 1:
            return "经济预期改善"
        if c < -1:
            return "经济预期转弱"
        return "变化不大"
    if ind == "dxy":
        if prev is None:
            return ""
        c = (value - prev) / prev * 100
        if c > 0.5:
            return "美元走强，对美股偏负面"
        if c < -0.5:
            return "美元走弱，对美股偏正面"
        return "变化不大"
    return ""


def _regime(indicators):
    """Count risk-off signals with the documented rules; label is a heuristic."""
    reasons = []
    n = 0

    def flag(cond, reason):
        nonlocal n
        if cond:
            n += 1
            reasons.append(reason)

    v = indicators.get("vix", {}).get("value")
    flag(v is not None and v >= 30, "VIX ≥ 30，恐慌区间")
    sp = indicators.get("spread", {}).get("value")
    flag(sp is not None and sp < 0, "10Y−3M 利差倒挂")
    dxy = indicators.get("dxy", {})
    flag(dxy.get("change_pct") is not None and dxy["change_pct"] > 0.5, "美元指数单日涨超 0.5%")
    gold = indicators.get("gold", {})
    flag(gold.get("change_pct") is not None and gold["change_pct"] > 1, "黄金单日涨超 1%，避险升温")
    cu = indicators.get("copper", {})
    flag(cu.get("change_pct") is not None and cu["change_pct"] < -1, "铜单日跌超 1%，经济预期转弱")
    oil = indicators.get("oil", {})
    flag(oil.get("change_pct") is not None and oil["change_pct"] > 3, "原油单日涨超 3%，通胀压力")
    if n == 0:
        label = "乐观"
    elif n == 1:
        label = "中性"
    elif n == 2:
        label = "谨慎"
    else:
        label = "风险"
    return {"label": label, "risk_off_count": n, "reasons": reasons}


def _series_list(df):
    """Extract [[date, close], ...] from a yfinance download, sampled to <= 60 pts.
    Handles both Series and single-column DataFrame Close (newer yfinance)."""
    try:
        closes = df["Close"]
        if hasattr(closes, "columns"):  # DataFrame: take first column
            closes = closes.iloc[:, 0]
        vals = []
        for ts, v in closes.items():
            try:
                f = float(v)
            except Exception:
                continue
            if f != f:  # NaN
                continue
            vals.append([str(ts.date()) if hasattr(ts, "date") else str(ts), round(f, 4)])
        if len(vals) > 60:
            m = 60
            idx = sorted(set(int(round(i * (len(vals) - 1) / (m - 1))) for i in range(m)))
            vals = [vals[i] for i in idx]
        return vals
    except Exception:
        return []


def _window_stats(series, kind):
    """(window_chg, window_label, [lo, hi]) over the series window."""
    if not series or len(series) < 2:
        return None, "", None
    first, last = series[0][1], series[-1][1]
    lo = min(p[1] for p in series)
    hi = max(p[1] for p in series)
    if kind == "yield":
        chg = round(last - first, 4)
        label = f"{chg * 100:+.0f}bp"
    else:
        chg = round((last - first) / first * 100, 2) if first else None
        label = f"{chg:+.2f}%" if chg is not None else ""
    return chg, label, [round(lo, 2), round(hi, 2)]


def _write_error(reason):
    """Write a diagnostic macro.json so a fetch failure is VISIBLE via the API
    (instead of a bare 404 that hides the cause). Never raises."""
    try:
        out = {"generated": datetime.datetime.now(datetime.timezone.utc).isoformat(),
               "source": "Yahoo Finance (yfinance)", "indicators": {},
               "regime": {"label": "未知", "risk_off_count": 0, "reasons": ["宏观抓取失败"]},
               "failures": {"_fatal": str(reason)[:500]}, "error": str(reason)[:500]}
        os.makedirs(os.path.dirname(OUT), exist_ok=True)
        with open(OUT, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=1)
        print(f"[macro] wrote error snapshot -> {OUT}: {str(reason)[:200]}")
    except Exception:
        pass


def main():
    try:
        return _run()
    except Exception as e:
        _write_error(e)
        return None


def _run():
    indicators = {}
    failures = {}
    try:
        import yfinance as yf
    except Exception as e:  # yfinance missing -> every indicator unavailable, file still written
        failures["yfinance"] = f"import failed: {e}"
        for key, (_, name, unit, kind) in SYMBOLS.items():
            indicators[key] = {"name": name, "value": None, "unit": unit, "kind": kind,
                               "change": None, "change_label": "", "read": "暂无数据",
                               "asof": None, "status": "unavailable",
                               "series": None, "window_chg": None, "window_label": "", "range": None}
        indicators["spread"] = {"name": "10Y−3M 利差", "value": None, "unit": "百分点",
                                "kind": "spread", "change": None, "change_label": "",
                                "read": "暂无数据", "asof": None, "status": "unavailable",
                                "series": None, "window_chg": None, "window_label": "", "range": None}
        out = {"generated": datetime.datetime.now(datetime.timezone.utc).isoformat(),
               "source": "Yahoo Finance (yfinance)", "indicators": indicators,
               "regime": {"label": "未知", "risk_off_count": 0, "reasons": ["宏观数据源不可用"]},
               "failures": failures, "error": failures.get("yfinance", "")[:500]}
        os.makedirs(os.path.dirname(OUT), exist_ok=True)
        with open(OUT, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=1)
        print(f"[macro] yfinance unavailable, wrote empty snapshot -> {OUT}")
        return out

    for key, (sym, name, unit, kind) in SYMBOLS.items():
        try:
            df = yf.download(sym, period="90d", interval="1d", progress=False, auto_adjust=False)
            if df is None or df.empty or len(df) < 1:
                raise ValueError("empty data")
            closes = df["Close"]
            value = float(closes.iloc[-1].iloc[0]) if hasattr(closes.iloc[-1], "iloc") else float(closes.iloc[-1])
            prev = None
            if len(df) >= 2:
                prev = float(closes.iloc[-2].iloc[0]) if hasattr(closes.iloc[-2], "iloc") else float(closes.iloc[-2])
            asof = str(df.index[-1].date())
            series = _series_list(df)
            wchg, wlabel, wrange = _window_stats(series, kind)
            if kind == "yield":
                change = (value - prev) if prev is not None else None
                change_label = "" if change is None else f"{change * 100:+.0f}bp"
                change_pct = None
            else:
                change = ((value - prev) / prev * 100) if prev else None
                change_label = "" if change is None else f"{change:+.2f}%"
                change_pct = change
            indicators[key] = {"name": name, "value": round(value, 2), "unit": unit, "kind": kind,
                               "change": (round(change, 4) if change is not None else None),
                               "change_pct": (round(change_pct, 2) if change_pct is not None else None),
                               "change_label": change_label,
                               "read": _read(key, value, prev),
                               "asof": asof, "status": "ok",
                               "series": series, "window_chg": wchg, "window_label": wlabel, "range": wrange}
        except Exception as e:
            failures[key] = str(e)[:200]
            indicators[key] = {"name": name, "value": None, "unit": unit, "kind": kind,
                               "change": None, "change_pct": None, "change_label": "",
                               "read": "暂无数据", "asof": None, "status": "unavailable",
                               "series": None, "window_chg": None, "window_label": "", "range": None}
    # 10Y-3M spread (computed; the NY Fed's preferred recession indicator)
    y10 = indicators["us10y"]["value"]
    m3 = indicators["us3m"]["value"]
    if y10 is not None and m3 is not None:
        sp = round(y10 - m3, 2)
        prev_sp = None
        if indicators["us10y"]["change"] is not None and indicators["us3m"]["change"] is not None:
            prev_sp = sp - (indicators["us10y"]["change"] - indicators["us3m"]["change"])
        s10 = {d: v for d, v in (indicators["us10y"].get("series") or [])}
        s3 = {d: v for d, v in (indicators["us3m"].get("series") or [])}
        sps = [[d, round(s10[d] - s3[d], 4)] for d in sorted(set(s10) & set(s3))]
        wchg, wlabel, wrange = _window_stats(sps, "yield")
        indicators["spread"] = {"name": "10Y−3M 利差", "value": sp, "unit": "百分点", "kind": "spread",
                                "change": None, "change_pct": None,
                                "change_label": "", "read": _read("spread", sp, prev_sp),
                                "asof": indicators["us10y"]["asof"], "status": "ok",
                                "series": sps, "window_chg": wchg, "window_label": wlabel, "range": wrange}
    else:
        failures["spread"] = "missing us10y/us3m"
        indicators["spread"] = {"name": "10Y−3M 利差", "value": None, "unit": "百分点",
                                "kind": "spread", "change": None, "change_pct": None,
                                "change_label": "", "read": "暂无数据",
                                "asof": None, "status": "unavailable",
                                "series": None, "window_chg": None, "window_label": "", "range": None}
    out = {"generated": datetime.datetime.now(datetime.timezone.utc).isoformat(),
           "source": "Yahoo Finance (yfinance)", "indicators": indicators,
           "regime": _regime(indicators), "failures": failures}
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"[macro] wrote {len(indicators)} indicators -> {OUT} (failures: {list(failures)})")
    return out


if __name__ == "__main__":
    main()
