"""Fetch Nasdaq Composite (^IXIC) OHLC bars for the US signal pipeline."""

import pandas as pd


def normalize_bars(raw):
    """Convert yfinance's single- or multi-index columns to the Alpaca layout."""
    if raw is None or raw.empty:
        raise ValueError("no Nasdaq Composite bars from Yahoo Finance")
    df = raw.copy()
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    needed = ["Open", "High", "Low", "Close"]
    missing = [name for name in needed if name not in df.columns]
    if missing:
        raise ValueError(f"Nasdaq Composite missing OHLC fields: {missing}")
    if "Volume" not in df.columns:
        df["Volume"] = 0
    df = df[needed + ["Volume"]]
    df.index = pd.DatetimeIndex(df.index)
    if df.index.tz is None:
        df.index = df.index.tz_localize("America/New_York")
    else:
        df.index = df.index.tz_convert("America/New_York")
    return df.sort_index().loc[lambda frame: ~frame.index.duplicated(keep="last")]


def fetch_nasdaq_frames():
    intervals = {"weekly": ("1wk", "5y"), "daily": ("1d", "2y"),
                 "30m": ("30m", "60d"), "5m": ("5m", "30d")}
    try:
        import yfinance as yf
    except ImportError as exc:
        return {}, {level: str(exc)[:200] for level in intervals}
    frames, failures = {}, {}
    for level, (interval, period) in intervals.items():
        try:
            raw = yf.download("^IXIC", period=period, interval=interval,
                              progress=False, auto_adjust=False, threads=False, timeout=20)
            frames[level] = normalize_bars(raw)
        except Exception as exc:
            failures[level] = str(exc)[:200]
    return frames, failures
