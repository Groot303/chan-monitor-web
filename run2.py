import json, datetime, warnings
warnings.filterwarnings("ignore")
import pandas as pd
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
import os
from zoneinfo import ZoneInfo
from chan2 import analyze_level, resonance, score_signal, RECENT_BARS
CACHED=os.environ.get('CACHED')=='1'  # re-use data2_*.csv instead of re-downloading
FORCE_RUN=os.environ.get('FORCE_RUN')=='true'  # bypass market-hours gate (workflow_dispatch)
NY_TZ="America/New_York"
SYMS="MU SNDK SPCX SKHY INTC NVDA TSLA LITE AAOI MRVL AMD META MRNA TSM ORCL AVGO AAPL PLTR NOK GOOG".split()
LEVELS=[("weekly","1wk","5y"),("daily","1d","2y"),("30m","30m","60d"),("5m","5m","10d")]

# NOTE 2026-10-13: US pipeline runs 24/7 per user request (no market-hours gate).

# Trend-filter mode for pivot-edge signals that conflict with the higher-timeframe trend
# (2026-10-13 opt): 'downweight' keeps the signal at half size (backtest: variant D +373.5%
# vs variant C +269.2% showed hard-drop threw away LITE/AMD/TSM winners);
# set to 'drop' to restore the old hard-discard behavior.
TREND_FILTER_MODE = 'downweight'  # 'downweight' | 'drop'

# Regime pause (2026-10-13 opt; backtest parity: backtest_opt.py REGIME=pause).
# When the benchmark (SPY) daily close is below its 200-day SMA, new BUY entries
# are paused (signals are marked, not deleted; sells are unaffected).
# Backtest (recommended combo half+pause): +574.9% vs +269.2% base; 2022 loss -3787 -> -970.
# Fewer than 200 daily bars -> no filtering (same as backtest).
REGIME_BENCH = "SPY"
REGIME_SMA = 200
REGIME_MODE = 'pause'  # 'pause' | 'off'

def fetch_alpaca_frames():
    """Fetch OHLC bars from Alpaca (IEX feed, free tier). Returns {level: {sym: df}}.
    df: tz-aware America/New_York index, columns Open/High/Low/Close/Volume."""
    from alpaca.data.historical import StockHistoricalDataClient
    from alpaca.data.requests import StockBarsRequest
    from alpaca.data.timeframe import TimeFrame, TimeFrameUnit
    from alpaca.data.enums import DataFeed
    key=os.environ.get("ALPACA_API_KEY"); secret=os.environ.get("ALPACA_SECRET_KEY")
    if not key or not secret:
        raise SystemExit("ALPACA_API_KEY / ALPACA_SECRET_KEY not set (repo Settings -> Secrets and variables -> Actions)")
    client=StockHistoricalDataClient(key, secret)
    tf={"weekly":TimeFrame(1,TimeFrameUnit.Week),
        "daily":TimeFrame(1,TimeFrameUnit.Day),
        "30m":TimeFrame(30,TimeFrameUnit.Minute),
        "5m":TimeFrame(5,TimeFrameUnit.Minute)}
    days={"weekly":5*366,"daily":2*366,"30m":61,"5m":10}
    now=datetime.datetime.now(datetime.timezone.utc)
    frames={}
    for lv in ("weekly","daily","30m","5m"):
        req=StockBarsRequest(symbol_or_symbols=SYMS, timeframe=tf[lv],
                             start=now-datetime.timedelta(days=days[lv]),
                             end=now, feed=DataFeed.IEX)
        df=client.get_stock_bars(req).df
        per={}
        if df is not None and len(df):
            # alpaca-py>=0.30: multi-symbol .df has a MultiIndex row index
            # (symbol, timestamp) with UNNAMED levels; df.tz_convert() on it
            # raises KeyError('Level None not found'). Split per symbol first,
            # then tz-convert each plain DatetimeIndex.
            for s in SYMS:
                try: sdf=df.xs(s, level=0)
                except KeyError: continue
                sdf.index=pd.DatetimeIndex(sdf.index)
                if sdf.index.tz is None:
                    sdf.index=sdf.index.tz_localize("UTC")
                sdf.index=sdf.index.tz_convert(NY_TZ)
                sdf=(sdf.rename(columns={"open":"Open","high":"High","low":"Low",
                                         "close":"Close","volume":"Volume"})
                        [["Open","High","Low","Close","Volume"]].sort_index())
                sdf=sdf[~sdf.index.duplicated(keep="last")]
                per[s]=sdf
        frames[lv]=per
    return frames

def fetch_regime_benchmark():
    """Fetch SPY daily bars (Alpaca IEX) for the regime-pause filter.
    Returns dict(bear, close, sma200, asof) or None when unavailable.
    bear = last daily close < 200-day SMA (backtest parity: backtest_opt.py
    REGIME=pause skips new BUY entries when SPY close < 200d SMA asof exec date;
    sells are unaffected). <200 bars -> bear=False (no filtering), same as backtest.
    CACHED=1 reads data2_SPY_daily.csv instead of hitting Alpaca."""
    cache = "data2_SPY_daily.csv"
    try:
        if CACHED:
            df = pd.read_csv(cache, index_col=0)
            df.index = pd.to_datetime(df.index, utc=True).tz_convert(NY_TZ)
        else:
            from alpaca.data.historical import StockHistoricalDataClient
            from alpaca.data.requests import StockBarsRequest
            from alpaca.data.timeframe import TimeFrame, TimeFrameUnit
            from alpaca.data.enums import DataFeed
            key = os.environ.get("ALPACA_API_KEY"); secret = os.environ.get("ALPACA_SECRET_KEY")
            if not key or not secret:
                print("regime: no Alpaca keys, skipping regime filter")
                return None
            client = StockHistoricalDataClient(key, secret)
            now = datetime.datetime.now(datetime.timezone.utc)
            req = StockBarsRequest(symbol_or_symbols=[REGIME_BENCH],
                                   timeframe=TimeFrame(1, TimeFrameUnit.Day),
                                   start=now - datetime.timedelta(days=2 * 366),
                                   end=now, feed=DataFeed.IEX)
            rdf = client.get_stock_bars(req).df
            if rdf is None or len(rdf) == 0:
                return None
            try:
                sdf = rdf.xs(REGIME_BENCH, level=0)
            except KeyError:
                return None
            sdf.index = pd.DatetimeIndex(sdf.index)
            if sdf.index.tz is None:
                sdf.index = sdf.index.tz_localize("UTC")
            sdf.index = sdf.index.tz_convert(NY_TZ)
            df = (sdf.rename(columns={"open": "Open", "high": "High", "low": "Low",
                                      "close": "Close", "volume": "Volume"})
                     [["Open", "High", "Low", "Close", "Volume"]].sort_index())
            df = df[~df.index.duplicated(keep="last")]
            df.to_csv(cache)
        df = df.dropna(subset=["Close"])
        if len(df) < 2:
            return None
        closes = df["Close"]
        sma = closes.rolling(REGIME_SMA).mean().iloc[-1]
        last = float(closes.iloc[-1])
        bear = False if pd.isna(sma) else bool(last < float(sma))
        return {"bear": bear, "close": last,
                "sma200": None if pd.isna(sma) else float(sma),
                "asof": fmt(df.index[-1])}
    except Exception as e:
        print(f"regime benchmark unavailable ({e}); continuing without regime filter")
        return None

def fmt(ts): 
    return str(ts)[:16] if hasattr(ts,'hour') and ts.hour else str(ts)[:10]
def plot(sym, res, dfs):
    fig, axes = plt.subplots(4,1,figsize=(15,20))
    for ax,(lv,_,_) in zip(axes,LEVELS):
        if lv not in res: ax.set_title(f"{sym} {lv}: NO DATA"); continue
        df=dfs[lv]; r=res[lv]
        for i,(d,x) in enumerate(df.iterrows()):
            c="g" if x.Close>=x.Open else "r"
            ax.plot([i,i],[x.Low,x.High],color=c,lw=0.7); ax.plot([i,i],[x.Open,x.Close],color=c,lw=2)
        ax.plot([p[0] for p in r['pts']],[p[2] for p in r['pts']],color="gray",lw=0.8,label="strokes")
        for sg in r['segs']:
            ax.plot([sg.s_i,sg.e_i],[sg.s_p,sg.e_p],color="blue",lw=2.2,ls="-" if sg.confirmed else "--")
        ax.plot([],[],color="blue",lw=2,label="segments (dashed=unconfirmed)")
        for P in r['pivots']:
            x0=r['segs'][P['first']].s_i; x1=r['segs'][P['last']].e_i
            ax.add_patch(Rectangle((x0,P['zd']),max(x1-x0,1),P['zg']-P['zd'],alpha=0.25,color="orange"))
            # label pivot edge prices on the chart
            ax.text(x1,P['zg'],f" ZG {P['zg']:.2f}",fontsize=7,color="#9a6200",va="bottom",ha="right",clip_on=True)
            ax.text(x1,P['zd'],f" ZD {P['zd']:.2f}",fontsize=7,color="#9a6200",va="top",ha="right",clip_on=True)
        for s in r['signals']:
            buy=s['type'].endswith('B'); edge=s.get('kind')=='pivot_edge'
            if edge:
                ax.scatter([s['idx']],[s['price']],marker="D" if buy else "D",s=90,color="cyan" if buy else "orange",edgecolor="k",zorder=5)
                label=("下沿买" if buy else "上沿卖")
            else:
                ax.scatter([s['idx']],[s['price']],marker="^" if buy else "v",s=110,color="lime" if buy else "magenta",edgecolor="k",zorder=5)
                label=s['type']
            ax.annotate(label+("" if s['confirmed'] else "?")+(f" {s['score']:.1f}" if 'score' in s else ""),(s['idx'],s['price']),textcoords="offset points",xytext=(0,-16 if buy else 8),ha="center",fontsize=8 if edge else 9,weight="bold")
        n=len(df); step=max(n//10,1)
        ax.set_xticks(range(0,n,step)); ax.set_xticklabels([fmt(df.index[i]) for i in range(0,n,step)],rotation=25,fontsize=8)
        st=r['state']
        ax.set_title(f"{sym} {lv}  bars={n} segs={len(r['segs'])} pivots={len(r['pivots'])} state={st['direction']}  (? = unconfirmed, may repaint; not advice)",fontsize=10)
        ax.legend(loc="upper left",fontsize=8)
    fig.tight_layout(); fig.savefig(f"out/{sym}_chan2.png",dpi=80); plt.close(fig)
FRAMES={} if CACHED else fetch_alpaca_frames()
out={"generated":datetime.datetime.utcnow().isoformat()+"Z","symbols":{},"failures":{}}
REG = fetch_regime_benchmark()
REGIME_BEAR = bool(REG and REG["bear"]) and REGIME_MODE == 'pause'
out["regime"] = {"benchmark": REGIME_BENCH, "sma_days": REGIME_SMA, "mode": REGIME_MODE,
                 "bear": bool(REG and REG["bear"]),
                 "close": REG["close"] if REG else None,
                 "sma200": REG["sma200"] if REG else None,
                 "asof": REG["asof"] if REG else None,
                 "note": "bear regime: new BUY entries paused (backtest REGIME=pause parity); sells unaffected; <200 bars -> no filter"}
print("regime:", out["regime"]["benchmark"], "bear=" + str(out["regime"]["bear"]),
      "close=", out["regime"]["close"], "sma200=", out["regime"]["sma200"])
for s in SYMS:
    res={}; dfs={}; ent={"levels":{}}
    for lv,iv,per in LEVELS:
        try:
            if CACHED:
                df=pd.read_csv(f"data2_{s}_{lv}.csv",index_col=0)
                df.index=pd.to_datetime(df.index,utc=True).tz_convert(NY_TZ)
            else:
                df=FRAMES[lv].get(s)
                if df is None or len(df)==0: raise ValueError("no bars from Alpaca")
            df=df.dropna(subset=["High","Low","Open","Close"])
            if len(df)<40: raise ValueError(f"too few bars: {len(df)}")
            if not CACHED: df.to_csv(f"data2_{s}_{lv}.csv")
            dfs[lv]=df; res[lv]=analyze_level(df, level=lv)
        except Exception as e:
            out["failures"][f"{s}/{lv}"]=str(e)[:200]; continue
    for lv,_,_ in LEVELS:
        if lv not in res: continue
        r=res[lv]; df=dfs[lv]
        ent["levels"][lv]=dict(bars=len(df),first=fmt(df.index[0]),last=fmt(df.index[-1]),last_close=float(df.Close.iloc[-1]),
            n_segments=len(r['segs']),n_pivots=len(r['pivots']),state=r['state'],
            last_segment=dict(up=r['segs'][-1].up,start=fmt(df.index[r['segs'][-1].s_i]),end=fmt(df.index[r['segs'][-1].e_i]),end_price=r['segs'][-1].e_p,confirmed=r['segs'][-1].confirmed) if r['segs'] else None,
            signals=[dict(symbol=s,level=lv,**{k:(float(v) if isinstance(v,(int,float)) and not isinstance(v,bool) else v) for k,v in sg.items() if k not in('idx','seg','confirmed')},time=fmt(df.index[sg['idx']]),bars_ago=len(df)-1-sg['idx'],recent=(len(df)-1-sg['idx'])<=RECENT_BARS[lv],
                          confirmed=bool(sg['confirmed']),repaint_warning=None if sg['confirmed'] else "unconfirmed: last segment not yet confirmed by feature-sequence fractal; may repaint") for sg in r['signals']])
    # resonance
    for lv,bigs in (("5m",["30m","daily","weekly"]),("30m",["daily","weekly"]),("daily",["weekly"])):
        if lv in ent["levels"]:
            bs=[ent["levels"][b]["state"] for b in bigs if b in ent["levels"]]
            for sg in ent["levels"][lv]["signals"]:
                sg["resonance"]=resonance(sg["type"],bs); sg["resonance_vs"]=[b for b in bigs if b in ent["levels"]]
    # trend filter (2026-10-13, 优化 2026-10-13晚): pivot-edge buys/sells that fight the
    # bigger trend are DOWNWEIGHTED (kept at half size) instead of dropped.
    # ZD_B with resonance 'conflict' = buying the lower edge while higher timeframes
    # are in a downtrend -> classic falling-knife. Same for ZG_S in an uptrend.
    # 一键切回硬丢弃: TREND_FILTER_MODE='drop' (见文件顶部).
    for lv in ent["levels"]:
        kept=[]
        for sg in ent["levels"][lv]["signals"]:
            if sg.get("kind")=="pivot_edge" and sg.get("resonance")=="conflict":
                msg=(f"{sg['type']} conflicts with higher-timeframe trend "
                     f"({'/'.join(sg.get('resonance_vs',[]))})")
                if TREND_FILTER_MODE=='drop':
                    out.setdefault("filtered",{})[f"{s}/{lv}/{sg['type']}"]="dropped: "+msg
                    continue
                sg["downweighted"]=True  # pipeline marks; execution sizes it at half
                out.setdefault("filtered",{})[f"{s}/{lv}/{sg['type']}"]="downweighted (half size): "+msg
            kept.append(sg)
        ent["levels"][lv]["signals"]=kept
    # regime pause: mark buy-type signals while in bear regime (new buys paused)
    if REGIME_BEAR:
        for lv in ent["levels"]:
            for sg in ent["levels"][lv]["signals"]:
                if sg["type"].endswith("B"):
                    sg["regime_paused"] = True
    for lv in ent["levels"]:
        for sg,raw in zip(ent["levels"][lv]["signals"],res[lv]['signals']):
            sg["score"],sg["score_breakdown"]=score_signal(sg,lv); raw["score"]=sg["score"]
    out["symbols"][s]=ent
    if res: plot(s,res,dfs)
    print(s,{lv:(len(r['segs']),len(r['pivots']),len(r['signals'])) for lv,r in res.items()})
json.dump(out,open("out/signals.json","w"),indent=1,default=str)
# summary md
L=["# Chan v2 signals summary (含中枢沿 ZG_S/ZD_B)","",f"Generated {out['generated']} (UTC). Prototype, read-only analysis. NOT investment advice.",
"?'/unconfirmed = last segment not yet confirmed, signal may repaint or vanish. Last-close data may include today's incomplete bar.",""]
rg=out.get("regime") or {}
L+=["",f"Regime ({rg.get('benchmark','?')} {rg.get('sma_days','?')}d SMA, asof {rg.get('asof','?')}): "
       f"{'BEAR - new BUY entries paused' if rg.get('bear') else 'bull/neutral - no pause'} "
       f"(close {rg.get('close')}, SMA {rg.get('sma200')})",""]
if out["failures"]:
    L+=["## Data failures",*[f"- {k}: {v}" for k,v in out["failures"].items()],""]
rec=[g for e in out["symbols"].values() for d in e["levels"].values() for g in d["signals"] if g["recent"]]
rec.sort(key=lambda g:-g["score"])
L+=["## Recent signals ranked by heuristic strength score (0-10, higher = stronger)","",
"Score is a transparent heuristic (see DOCS_chan2.md), NOT backtested, NOT a win rate, NOT investment advice.","",
"| # | Score | Symbol | Level | Type | Time | Price | Breakdown (base/div/reson/conf/fresh/quality) |","|---|---|---|---|---|---|---|---|"]
for i,g in enumerate(rec,1):
    b=g["score_breakdown"]
    L.append(f"| {i} | **{g['score']:.1f}** | {g['symbol']} | {g['level']} | {g['type']}{'' if g['confirmed'] else '?'} | {g['time']} | {g['price']:.2f} | base {b['base']:+.2f}, div {b['divergence']:+.2f}, reson {b['resonance']:+.2f} ({g.get('resonance','n/a')}), conf {b['confirmed']:+.2f}, fresh {b['freshness']:+.2f} (age {g['bars_ago']}), quality {b['quality']:+.2f} = raw {b['raw_total']:.2f}{' (capped)' if b['capped'] else ''} |")
if not rec: L.append("| - | - | no recent signals | | | | | |")
L+=[""]
L+=["## Per symbol (latest signal per level, plus higher-level state)",""]
for s,e in out["symbols"].items():
    L.append(f"### {s}")
    for lv in ("weekly","daily","30m","5m"):
        d=e["levels"].get(lv)
        if not d: L.append(f"- {lv}: NO DATA"); continue
        st=d["state"]; z="" if st["zg"] is None else f" last pivot ZD={st['zd']:.2f}-ZG={st['zg']:.2f} ({st['pivot_pos']})"
        ls=d["last_segment"]; lsd="" if not ls else f"; last seg {'up' if ls['up'] else 'down'} to {ls['end_price']:.2f} on {ls['end']} ({'confirmed' if ls['confirmed'] else 'UNCONFIRMED'})"
        L.append(f"- {lv} [{d['first']}..{d['last']}, close {d['last_close']:.2f}]: dir={st['direction']}{z}{lsd}; segs={d['n_segments']} pivots={d['n_pivots']}")
        if d["signals"]:
            g=d["signals"][-1]
            ev=[f"SCORE {g['score']:.1f}/10"]
            if "ratio" in g and g["ratio"] is not None: ev.append(f"MACD area leave/enter={g['ratio']:.2f}")
            if "margin_pct" in g: ev.append(f"margin vs ref={g['margin_pct']:.1f}%")
            if "zg" in g and g.get("zg") is not None: ev.append(f"ZD={g['zd']:.2f} ZG={g['zg']:.2f}")
            L.append(f"  - latest signal: **{g['type']}** at {g['time']} price {g['price']:.2f}; {'; '.join(ev)}; {'confirmed' if g['confirmed'] else 'UNCONFIRMED (may repaint)'}; {g['bars_ago']} bars ago{'' if g['recent'] else ' -> STALE, not a current signal'}"+(f"; resonance vs {'/'.join(g['resonance_vs'])}: {g['resonance']}" if 'resonance' in g else ""))
            if len(d["signals"])>1: L.append(f"  - ({len(d['signals'])} signals in window; see signals.json)")
        else: L.append("  - no signal in window")
    L.append("")
open("out/signals_summary.md","w").write("\n".join(L))
