"""Technical indicators — causal only (no future bars)."""
from __future__ import annotations
import numpy as np
import pandas as pd


def sma(series: pd.Series, n: int) -> pd.Series:
    return series.rolling(n, min_periods=n).mean()


def ema(series: pd.Series, n: int) -> pd.Series:
    return series.ewm(span=n, adjust=False, min_periods=n).mean()


def true_range(df: pd.DataFrame) -> pd.Series:
    prev_close = df["Close"].shift(1)
    ranges = pd.concat([
        df["High"] - df["Low"],
        (df["High"] - prev_close).abs(),
        (df["Low"] - prev_close).abs(),
    ], axis=1)
    return ranges.max(axis=1)


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    return true_range(df).rolling(n, min_periods=n).mean()


def returns(series: pd.Series, n: int) -> pd.Series:
    return series / series.shift(n) - 1.0


def realized_vol(series: pd.Series, n: int = 20) -> pd.Series:
    logret = np.log(series / series.shift(1))
    return logret.rolling(n, min_periods=n).std() * np.sqrt(252)


def enrich(df: pd.DataFrame, ma_fast=20, ma_slow=50, ma_long=200, atr_period=14) -> pd.DataFrame:
    out = df.copy()
    out["MA20"] = sma(out["Close"], ma_fast)
    out["MA50"] = sma(out["Close"], ma_slow)
    out["MA200"] = sma(out["Close"], ma_long)
    out["ATR14"] = atr(out, atr_period)
    out["ATR_PCT"] = out["ATR14"] / out["Close"]
    out["RET20"] = returns(out["Close"], 20)
    out["RET60"] = returns(out["Close"], 60)
    out["VOL20"] = realized_vol(out["Close"], 20)
    out["VOL_MA20"] = sma(out["Volume"].astype(float), 20)
    out["HH20"] = out["High"].rolling(20, min_periods=20).max().shift(1)  # prior 20-day high (no lookahead)
    return out
