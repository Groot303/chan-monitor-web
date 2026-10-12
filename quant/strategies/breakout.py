"""C. Breakout with volume confirmation. Signal on close; fill next open."""
from __future__ import annotations
from typing import Dict, Any, List
import pandas as pd
from .base import Strategy, Signal
from ..indicators import enrich


class BreakoutStrategy(Strategy):
    name = "breakout"

    def __init__(self, lookback: int = 20, vol_mult: float = 1.2, atr_stop_mult: float = 2.0):
        self.lookback = lookback
        self.vol_mult = vol_mult
        self.atr_stop_mult = atr_stop_mult

    def generate(self, symbol: str, df: pd.DataFrame, ctx: Dict[str, Any]) -> List[Signal]:
        en = enrich(df)
        out: List[Signal] = []
        for i in range(len(en)):
            row = en.iloc[i]
            hh = row.get("HH20")  # prior 20-day high (shifted)
            if pd.isna(hh) or pd.isna(row["ATR14"]) or pd.isna(row["VOL_MA20"]):
                continue
            # Close breaks above prior 20-day high
            if not (row["Close"] > hh):
                continue
            # Volume confirmation
            if row["VOL_MA20"] <= 0 or row["Volume"] < self.vol_mult * row["VOL_MA20"]:
                continue
            stop = float(min(row["Close"] - self.atr_stop_mult * row["ATR14"], float(hh) * 0.98))
            if stop <= 0 or stop >= row["Close"]:
                continue
            reasons = [
                f"收盘价 {row['Close']:.2f} 突破前{self.lookback}日高点 {float(hh):.2f}",
                f"成交量 {row['Volume']:.0f} ≥ {self.vol_mult}×20日均量 {row['VOL_MA20']:.0f}",
                "信号于日线收盘确认，模拟成交用次日开盘",
            ]
            out.append(Signal(
                symbol=symbol,
                date=str(en.index[i].date()),
                side="BUY",
                strategy=self.name,
                score=0.0,
                reasons=reasons,
                stop=stop,
                extras={"close": float(row["Close"]), "hh20": float(hh), "idx": i},
            ))
        return out
