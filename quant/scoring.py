"""Explainable 0–100 rule score. Matching degree ≠ rise probability."""
from __future__ import annotations
from typing import Dict, Any, List, Tuple
import pandas as pd
from .config import ScoreWeights
from .indicators import enrich
from .strategies.base import Signal


def score_signal(sig: Signal, df: pd.DataFrame, ctx: Dict[str, Any], weights: ScoreWeights | None = None) -> Tuple[float, Dict[str, float], List[str]]:
    w = weights or ScoreWeights()
    en = enrich(df)
    # find row by date
    try:
        ts = pd.Timestamp(sig.date)
        if ts not in en.index:
            idx = en.index.get_indexer([ts], method="ffill")[0]
            if idx < 0:
                return 0.0, {}, ["无对应K线"]
            row = en.iloc[idx]
        else:
            row = en.loc[ts]
            if isinstance(row, pd.DataFrame):
                row = row.iloc[-1]
    except Exception:
        return 0.0, {}, ["日期对齐失败"]

    parts: Dict[str, float] = {}
    notes: List[str] = []

    # Trend quality 0..w.trend
    trend_pts = 0.0
    if not pd.isna(row.get("MA20")) and not pd.isna(row.get("MA50")):
        if row["Close"] > row["MA20"] > row["MA50"]:
            trend_pts += w.trend * 0.7
            notes.append("均线多头排列")
        elif row["Close"] > row["MA50"]:
            trend_pts += w.trend * 0.35
            notes.append("价格在MA50上方")
        if not pd.isna(row.get("MA200")) and row["Close"] > row["MA200"]:
            trend_pts += w.trend * 0.3
            notes.append("价格在MA200上方")
    parts["trend"] = min(w.trend, trend_pts)

    # Relative strength
    rs_pts = 0.0
    rs20 = (sig.extras or {}).get("rs20_qqq")
    if rs20 is None:
        bench = (ctx.get("benchmarks") or {}).get("QQQ")
        if bench is not None:
            be = enrich(bench)
            if ts in be.index and not pd.isna(row.get("RET20")) and not pd.isna(be.loc[ts].get("RET20") if not isinstance(be.loc[ts], pd.DataFrame) else be.loc[ts].iloc[-1].get("RET20")):
                brow = be.loc[ts]
                if isinstance(brow, pd.DataFrame):
                    brow = brow.iloc[-1]
                rs20 = float(row["RET20"] - brow["RET20"])
    if rs20 is not None:
        if rs20 > 0.05:
            rs_pts = w.relative_strength
            notes.append(f"相对QQQ 20日超额 {rs20*100:.1f}%")
        elif rs20 > 0:
            rs_pts = w.relative_strength * 0.5
            notes.append(f"相对QQQ略强 {rs20*100:.1f}%")
        else:
            rs_pts = 0.0
            notes.append("相对QQQ偏弱")
    parts["relative_strength"] = rs_pts

    # Momentum
    mom = 0.0
    if not pd.isna(row.get("RET20")):
        if row["RET20"] > 0.10:
            mom = w.momentum
        elif row["RET20"] > 0.03:
            mom = w.momentum * 0.6
        elif row["RET20"] > 0:
            mom = w.momentum * 0.3
        notes.append(f"20日收益 {float(row['RET20'])*100:.1f}%")
    parts["momentum"] = mom

    # Breakout / volume
    br = 0.0
    if sig.strategy == "breakout":
        br = w.breakout_volume * 0.8
        notes.append("突破策略成交量确认")
        if (sig.extras or {}).get("hh20"):
            br = w.breakout_volume
    elif not pd.isna(row.get("HH20")) and row["Close"] >= row["HH20"]:
        br = w.breakout_volume * 0.5
        notes.append("接近或突破前高")
    elif not pd.isna(row.get("Volume")) and not pd.isna(row.get("VOL_MA20")) and row["VOL_MA20"] > 0:
        if row["Volume"] > 1.2 * row["VOL_MA20"]:
            br = w.breakout_volume * 0.4
            notes.append("放量")
    parts["breakout_volume"] = br

    # Risk penalty (subtract up to risk_penalty)
    penalty = 0.0
    if not pd.isna(row.get("ATR_PCT")) and row["ATR_PCT"] > 0.05:
        penalty += w.risk_penalty * 0.6
        notes.append("ATR%偏高，扣风险分")
    regime = (ctx.get("regime") or {}).get("combined_trend")
    if regime == "下降趋势":
        penalty += w.risk_penalty * 0.5
        notes.append("大盘下降趋势，扣风险分")
    if sig.stop and sig.extras.get("close"):
        risk_pct = (sig.extras["close"] - sig.stop) / sig.extras["close"]
        if risk_pct > 0.12:
            penalty += w.risk_penalty * 0.4
            notes.append("止损距离偏大")
    parts["risk_penalty"] = -min(w.risk_penalty, penalty)

    total = parts["trend"] + parts["relative_strength"] + parts["momentum"] + parts["breakout_volume"] + parts["risk_penalty"]
    total = max(0.0, min(100.0, total))
    parts["total"] = total
    return total, parts, notes
