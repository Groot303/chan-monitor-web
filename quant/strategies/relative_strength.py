"""B. Relative strength / momentum vs QQQ & SPY. Long only."""
from __future__ import annotations
from typing import Dict, Any, List
import pandas as pd
from .base import Strategy, Signal
from ..indicators import enrich, returns


class RelativeStrengthStrategy(Strategy):
    name = "relative_strength"

    def __init__(self, atr_stop_mult: float = 2.0):
        self.atr_stop_mult = atr_stop_mult

    def generate(self, symbol: str, df: pd.DataFrame, ctx: Dict[str, Any]) -> List[Signal]:
        en = enrich(df)
        bench = ctx.get("benchmarks") or {}
        qqq = bench.get("QQQ")
        spy = bench.get("SPY")
        out: List[Signal] = []
        if qqq is None or spy is None:
            return out
        qqq_e = enrich(qqq)
        spy_e = enrich(spy)
        for i in range(len(en)):
            row = en.iloc[i]
            dt = en.index[i]
            if pd.isna(row.get("RET20")) or pd.isna(row.get("RET60")) or pd.isna(row.get("ATR14")):
                continue
            # align benchmark by date (asof)
            if dt not in qqq_e.index or dt not in spy_e.index:
                # try nearest previous
                q_idx = qqq_e.index.get_indexer([dt], method="ffill")[0]
                s_idx = spy_e.index.get_indexer([dt], method="ffill")[0]
                if q_idx < 0 or s_idx < 0:
                    continue
                qrow, srow = qqq_e.iloc[q_idx], spy_e.iloc[s_idx]
            else:
                qrow, srow = qqq_e.loc[dt], spy_e.loc[dt]
            if pd.isna(qrow.get("RET20")) or pd.isna(srow.get("RET20")):
                continue
            rs20 = float(row["RET20"] - qrow["RET20"])
            rs60 = float(row["RET60"] - max(qrow["RET60"], srow["RET60"]))
            # require positive absolute momentum and beat QQQ on 20d
            if row["RET20"] <= 0 or rs20 <= 0:
                continue
            if row["Close"] < row["MA50"] if not pd.isna(row["MA50"]) else True:
                continue
            stop = float(row["Close"] - self.atr_stop_mult * row["ATR14"])
            reasons = [
                f"20日收益 {row['RET20']*100:.1f}% , 相对QQQ超额 {rs20*100:.1f}%",
                f"60日相对强度 {rs60*100:.1f}%",
                f"价格在 MA50 上方",
            ]
            out.append(Signal(
                symbol=symbol,
                date=str(dt.date()),
                side="BUY",
                strategy=self.name,
                score=0.0,
                reasons=reasons,
                stop=stop,
                extras={
                    "close": float(row["Close"]),
                    "ret20": float(row["RET20"]),
                    "rs20_qqq": rs20,
                    "rs60": rs60,
                    "idx": i,
                },
            ))
        return out
