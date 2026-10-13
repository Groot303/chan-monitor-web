#!/usr/bin/env python3
"""A-share major indices chan-analysis pipeline (mirrors run2.py for US stocks).

Data: East Money kline API directly (no API key needed).
  secid 1.xxxxxx = Shanghai, 0.xxxxxx = Shenzhen
  klt: 101=daily, 102=weekly, 30=30min
Output: out_cn/signals.json + out_cn/<name>_chan2.png (+ out_cn/signals_summary.md)
Then: python scripts/build_data.py out_cn --market cn
"""
import json, datetime, warnings
warnings.filterwarnings("ignore")
import pandas as pd
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
import os, requests
from zoneinfo import ZoneInfo
from chan2 import analyze_level, resonance, score_signal

CACHED = os.environ.get('CACHED') == '1'          # re-use out_cn/data2_*.csv instead of re-downloading
FORCE_RUN = os.environ.get('FORCE_RUN') == 'true'  # bypass market-hours gate (workflow_dispatch)
SH_TZ = "Asia/Shanghai"
OUT = "out_cn"

# (display name, eastmoney secid)
CN_SYMS = [
    ("上证指数", "1.000001"),
    ("科创50", "1.000688"),
    ("银行指数", "0.399986"),   # 中证银行
    ("平均股价", "47.800005"),  # A股平均股价
]
LEVELS = [("weekly", "102"), ("daily", "101"), ("30m", "30"), ("5m", "5")]

# Trend-filter mode for pivot-edge signals that conflict with the higher-timeframe trend
# (2026-10-13 opt): 'downweight' keeps the signal at half size (backtest: variant D +373.5%
# vs variant C +269.2% showed hard-drop threw away LITE/AMD/TSM winners);
# set to 'drop' to restore the old hard-discard behavior.
TREND_FILTER_MODE = 'downweight'  # 'downweight' | 'drop' 

EM_URL = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
EM_UT = "7eea3edcaed734bea9cbfc24409ed989"


def in_cn_session(now=None):
    """True during A-share regular session 9:30-11:30, 13:00-15:00 Asia/Shanghai.
    Skips weekends + XSHG exchange holidays."""
    now = now or datetime.datetime.now(ZoneInfo(SH_TZ))
    if now.weekday() >= 5:
        return False
    try:
        import exchange_calendars as xcals
        if not xcals.get_calendar("XSHG").is_session(now.date()):
            return False
    except Exception:
        pass  # calendar unavailable: fall back to weekday+hours check
    t = now.time()
    return (datetime.time(9, 30) <= t < datetime.time(11, 35)) or \
           (datetime.time(13, 0) <= t < datetime.time(15, 5))


if not CACHED and not FORCE_RUN and not in_cn_session():
    print("skip: outside A-share trading session (Asia/Shanghai); set FORCE_RUN=true to override")
    raise SystemExit(0)


def fetch_em_kline(secid, klt, lmt="1000"):
    """Fetch one index/level from East Money. Returns df with tz-aware
    Asia/Shanghai index, columns Open/High/Low/Close/Volume, or None."""
    params = {"secid": secid, "ut": EM_UT,
              "fields1": "f1,f2,f3,f4,f5,f6", "fields2": "f51,f52,f53,f54,f55,f56,f57,f58",
              "klt": klt, "fqt": "1", "beg": "0", "end": "20500000", "lmt": lmt}
    r = requests.get(EM_URL, params=params, timeout=30)
    r.raise_for_status()
    data = r.json().get("data") or {}
    klines = data.get("klines") or []
    if not klines:
        return None
    rows = [k.split(",") for k in klines]
    df = pd.DataFrame(rows, columns=["ts", "Open", "Close", "High", "Low", "Volume", "Amount", "Amp"])
    for c in ("Open", "Close", "High", "Low", "Volume"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["ts"] = pd.to_datetime(df["ts"], errors="coerce")
    df = df.dropna(subset=["ts"]).set_index("ts")
    df.index = df.index.tz_localize(SH_TZ)
    df = df[["Open", "High", "Low", "Close", "Volume"]].sort_index()
    df = df[~df.index.duplicated(keep="last")]
    return df


def fetch_em_frames():
    """Fetch OHLC bars for all indices/levels. Returns {level: {name: df}}."""
    frames = {}
    for lv, klt in LEVELS:
        per = {}
        for name, secid in CN_SYMS:
            try:
                # 5m 级别多取一些 K 线 (2000根 ≈ 40个交易日)
                _lmt = "2000" if lv == "5m" else "1000"
                df = fetch_em_kline(secid, klt, lmt=_lmt)
                if df is not None and len(df):
                    per[name] = df
                    print(f"  {name} {lv}: {len(df)} bars, last={df.index[-1]}")
            except Exception as e:
                print(f"  {name} {lv}: fetch failed: {e}")
        frames[lv] = per
    return frames


def fmt(ts):
    return str(ts)[:16] if hasattr(ts, 'hour') and ts.hour else str(ts)[:10]


def plot(sym, res, dfs):
    fig, axes = plt.subplots(4, 1, figsize=(15, 20))
    for ax, (lv, _) in zip(axes, LEVELS):
        if lv not in res:
            ax.set_title(f"{sym} {lv}: NO DATA")
            continue
        df = dfs[lv]
        r = res[lv]
        for i, (d, x) in enumerate(df.iterrows()):
            c = "g" if x.Close >= x.Open else "r"
            ax.plot([i, i], [x.Low, x.High], color=c, lw=0.7)
            ax.plot([i, i], [x.Open, x.Close], color=c, lw=2)
        ax.plot([p[0] for p in r['pts']], [p[2] for p in r['pts']], color="gray", lw=0.8, label="strokes")
        for sg in r['segs']:
            ax.plot([sg.s_i, sg.e_i], [sg.s_p, sg.e_p], color="blue", lw=2.2, ls="-" if sg.confirmed else "--")
        ax.plot([], [], color="blue", lw=2, label="segments (dashed=unconfirmed)")
        for P in r['pivots']:
            x0 = r['segs'][P['first']].s_i
            x1 = r['segs'][P['last']].e_i
            ax.add_patch(Rectangle((x0, P['zd']), max(x1 - x0, 1), P['zg'] - P['zd'], alpha=0.25, color="orange"))
            ax.text(x1, P['zg'], f" ZG {P['zg']:.2f}", fontsize=7, color="#9a6200", va="bottom", ha="right", clip_on=True)
            ax.text(x1, P['zd'], f" ZD {P['zd']:.2f}", fontsize=7, color="#9a6200", va="top", ha="right", clip_on=True)
        for s in r['signals']:
            buy = s['type'].endswith('B')
            edge = s.get('kind') == 'pivot_edge'
            if edge:
                ax.scatter([s['idx']], [s['price']], marker="D", s=90,
                           color="cyan" if buy else "orange", edgecolor="k", zorder=5)
                label = ("下沿买" if buy else "上沿卖")
            else:
                ax.scatter([s['idx']], [s['price']], marker="^" if buy else "v", s=110,
                           color="lime" if buy else "magenta", edgecolor="k", zorder=5)
                label = s['type']
            ax.annotate(label + ("" if s['confirmed'] else "?") + (f" {s['score']:.1f}" if 'score' in s else ""),
                        (s['idx'], s['price']), textcoords="offset points", xytext=(0, -16 if buy else 8),
                        ha="center", fontsize=8 if edge else 9, weight="bold")
        n = len(df)
        step = max(n // 10, 1)
        ax.set_xticks(range(0, n, step))
        ax.set_xticklabels([fmt(df.index[i]) for i in range(0, n, step)], rotation=25, fontsize=8)
        st = r['state']
        ax.set_title(f"{sym} {lv}  bars={n} segs={len(r['segs'])} pivots={len(r['pivots'])} state={st['direction']}  (? = unconfirmed, may repaint; not advice)", fontsize=10)
        ax.legend(loc="upper left", fontsize=8)
    fig.tight_layout()
    fig.savefig(f"{OUT}/{sym}_chan2.png", dpi=80)
    plt.close(fig)


os.makedirs(OUT, exist_ok=True)
FRAMES = {} if CACHED else fetch_em_frames()

def cn_regime():
    """Bear-regime check for A-shares (2026-10-13 opt, matches backtest REGIME=pause):
    上证指数 daily close < 200d SMA -> bear. Never raises; on failure returns
    bear=False with an error note so the pipeline keeps flowing."""
    try:
        df = FRAMES["daily"].get("上证指数")
        closes = df["Close"].dropna()
        if len(closes) < 210:
            raise ValueError(f"too few 上证指数 bars: {len(closes)}")
        sma200 = float(closes.iloc[-200:].mean())
        last = float(closes.iloc[-1])
        return {"benchmark": "上证指数", "bear": bool(last < sma200),
                "close": round(last, 2), "sma200": round(sma200, 2)}
    except Exception as e:
        return {"benchmark": "上证指数", "bear": False, "error": str(e)[:120]}

REGIME = {} if CACHED else cn_regime()
out = {"generated": datetime.datetime.now(datetime.timezone.utc).isoformat() + "Z",
       "market": "cn", "symbols": {}, "failures": {}, "regime": REGIME}
for s, secid in CN_SYMS:
    res = {}
    dfs = {}
    ent = {"levels": {}}
    for lv, klt in LEVELS:
        try:
            if CACHED:
                df = pd.read_csv(f"{OUT}/data2_{s}_{lv}.csv", index_col=0)
                df.index = pd.to_datetime(df.index, utc=True).tz_convert(SH_TZ)
            else:
                df = FRAMES[lv].get(s)
                if df is None or len(df) == 0:
                    raise ValueError("no bars from East Money")
            df = df.dropna(subset=["High", "Low", "Open", "Close"])
            if len(df) < 40:
                raise ValueError(f"too few bars: {len(df)}")
            if not CACHED:
                df.to_csv(f"{OUT}/data2_{s}_{lv}.csv")
            dfs[lv] = df
            res[lv] = analyze_level(df, level=lv)
        except Exception as e:
            out["failures"][f"{s}/{lv}"] = str(e)[:200]
            continue
    for lv, _ in LEVELS:
        if lv not in res:
            continue
        r = res[lv]
        df = dfs[lv]
        ent["levels"][lv] = dict(
            bars=len(df), first=fmt(df.index[0]), last=fmt(df.index[-1]),
            last_close=float(df.Close.iloc[-1]),
            n_segments=len(r['segs']), n_pivots=len(r['pivots']), state=r['state'],
            last_segment=dict(up=r['segs'][-1].up, start=fmt(df.index[r['segs'][-1].s_i]),
                              end=fmt(df.index[r['segs'][-1].e_i]), end_price=r['segs'][-1].e_p,
                              confirmed=r['segs'][-1].confirmed) if r['segs'] else None,
            signals=[dict(symbol=s, level=lv, **{k: (float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else v)
                                                  for k, v in sg.items() if k not in ('idx', 'seg', 'confirmed')},
                          time=fmt(df.index[sg['idx']]), bars_ago=len(df) - 1 - sg['idx'],
                          recent=(len(df) - 1 - sg['idx']) < {'weekly': 4, 'daily': 10, '30m': 40, '5m': 120}[lv],
                          confirmed=bool(sg['confirmed']),
                          repaint_warning=None if sg['confirmed'] else "unconfirmed: last segment not yet confirmed by feature-sequence fractal; may repaint")
                     for sg in r['signals']])
    # resonance
    for lv, bigs in (("5m", ["30m", "daily", "weekly"]), ("30m", ["daily", "weekly"]), ("daily", ["weekly"])):
        if lv in ent["levels"]:
            bs = [ent["levels"][b]["state"] for b in bigs if b in ent["levels"]]
            for sg in ent["levels"][lv]["signals"]:
                sg["resonance"] = resonance(sg["type"], bs)
                sg["resonance_vs"] = [b for b in bigs if b in ent["levels"]]
    # trend filter (2026-10-13, 优化 2026-10-13晚): pivot-edge buys/sells that fight the
    # bigger trend are DOWNWEIGHTED (kept at half size) instead of dropped.
    # 一键切回硬丢弃: TREND_FILTER_MODE='drop' (见文件顶部).
    for lv in ent["levels"]:
        kept = []
        for sg in ent["levels"][lv]["signals"]:
            if sg.get("kind") == "pivot_edge" and sg.get("resonance") == "conflict":
                msg = (f"{sg['type']} conflicts with higher-timeframe trend "
                       f"({'/'.join(sg.get('resonance_vs', []))})")
                if TREND_FILTER_MODE == 'drop':
                    out.setdefault("filtered", {})[f"{s}/{lv}/{sg['type']}"] = "dropped: " + msg
                    continue
                sg["downweighted"] = True  # pipeline marks; execution sizes it at half
                out.setdefault("filtered", {})[f"{s}/{lv}/{sg['type']}"] = "downweighted (half size): " + msg
            kept.append(sg)
        ent["levels"][lv]["signals"] = kept
    # regime pause (2026-10-13 opt, matches backtest REGIME=pause):
    # bear regime -> buy-type signals flagged regime_paused; sells unaffected.
    if REGIME.get("bear"):
        for lv in ent["levels"]:
            for sg in ent["levels"][lv]["signals"]:
                if sg["type"].endswith("B"):
                    sg["regime_paused"] = True
    for lv in ent["levels"]:
        for sg, raw in zip(ent["levels"][lv]["signals"], res[lv]['signals']):
            sg["score"], sg["score_breakdown"] = score_signal(sg, lv)
            raw["score"] = sg["score"]
    out["symbols"][s] = ent
    if res:
        plot(s, res, dfs)
    print(s, {lv: (len(r['segs']), len(r['pivots']), len(r['signals'])) for lv, r in res.items()})
json.dump(out, open(f"{OUT}/signals.json", "w"), indent=1, default=str, ensure_ascii=False)

# summary md
L = ["# Chan v2 signals summary (A股指数, 含中枢沿 ZG_S/ZD_B)", "",
     f"Generated {out['generated']} (UTC). Prototype, read-only analysis. NOT investment advice.",
     "'?'/unconfirmed = last segment not yet confirmed, signal may repaint or vanish.", ""]
if out["failures"]:
    L += ["## Data failures", *[f"- {k}: {v}" for k, v in out["failures"].items()], ""]
rec = [g for e in out["symbols"].values() for d in e["levels"].values() for g in d["signals"] if g["recent"]]
rec.sort(key=lambda g: -g["score"])
L += ["## Recent signals ranked by heuristic strength score (0-10, higher = stronger)", "",
      "Score is a transparent heuristic, NOT backtested, NOT a win rate, NOT investment advice.", "",
      "| # | Score | Symbol | Level | Type | Time | Price | Breakdown |",
      "|---|---|---|---|---|---|---|---|"]
for i, g in enumerate(rec, 1):
    b = g["score_breakdown"]
    L.append(f"| {i} | **{g['score']:.1f}** | {g['symbol']} | {g['level']} | {g['type']}{'' if g['confirmed'] else '?'} | {g['time']} | {g['price']:.2f} | base {b['base']:+.2f}, div {b['divergence']:+.2f}, reson {b['resonance']:+.2f}, conf {b['confirmed']:+.2f}, fresh {b['freshness']:+.2f}, quality {b['quality']:+.2f} |")
if not rec:
    L.append("| - | - | no recent signals | | | | | |")
L += [""]
open(f"{OUT}/signals_summary.md", "w").write("\n".join(L))
print(f"wrote {OUT}/signals.json")
