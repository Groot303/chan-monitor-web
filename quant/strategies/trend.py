"""A. Trend following — MA filter + ATR stop. Long only."""
from __future__ import annotations
from typing import Dict, Any, List
import pandas as pd
from .base import Strategy, Signal
from ..indicators import enrich


class TrendFollowStrategy(Strategy):
    name = "trend"

    def __init__(self, atr_stop_mult: float = 2.0):
        self.atr_stop_mult = atr_stop_mult

    def generate(self, symbol: str, df: pd.DataFrame, ctx: Dict[str, Any]) -> List[Signal]:
        en = enrich(df)
        regime = (ctx.get("regime") or {}).get("combined_trend", "")
        out: List[Signal] = []
        for i in range(len(en)):
            row = en.iloc[i]
            if pd.isna(row["MA50"]) or pd.isna(row["ATR14"]) or pd.isna(row["MA20"]):
                continue
            # Long setup: close > MA20 > MA50, rising structure
            up = row["Close"] > row["MA20"] > row["MA50"]
            slope = True
            if i >= 5 and not pd.isna(en["MA50"].iloc[i - 5]):
                slope = row["MA50"] >= en["MA50"].iloc[i - 5]
            if not (up and slope):
                continue
            # Soft filter: avoid hard down regime
            if regime == "下降趋势":
                continue
            stop = float(row["Close"] - self.atr_stop_mult * row["ATR14"])
            if stop <= 0 or stop >= row["Close"]:
                continue
            reasons = [
                f"Close {row['Close']:.2f} > MA20 {row['MA20']:.2f} > MA50 {row['MA50']:.2f}",
                f"MA50 slope non-negative over 5 bars",
                f"ATR stop {self.atr_stop_mult}x → {stop:.2f}",
            ]
            if regime:
                reasons.append(f"市场状态: {regime}")
            out.append(Signal(
                symbol=symbol,
                date=str(en.index[i].date()),
                side="BUY",
                strategy=self.name,
                score=0.0,  # filled by scorer
                reasons=reasons,
                stop=stop,
                extras={"close": float(row["Close"]), "atr": float(row["ATR14"]), "idx": i},
            ))
        return out
