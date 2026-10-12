"""Yahoo Finance / local CSV adapter (research grade, may be delayed or rate-limited)."""
from __future__ import annotations
import os
from typing import Optional, List
import pandas as pd
from .base import BarData, MarketDataAdapter

REQUIRED = ["Open", "High", "Low", "Close", "Volume"]


def _normalize(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    # flatten multiindex columns if any
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
    cols = {c: c.title() if c.lower() in ("open", "high", "low", "close", "volume") else c for c in df.columns}
    df = df.rename(columns=cols)
    # prefer Adj Close for Close only when Close missing
    if "Close" not in df.columns and "Adj Close" in df.columns:
        df["Close"] = df["Adj Close"]
    missing = [c for c in REQUIRED if c not in df.columns]
    if missing:
        raise ValueError(f"missing columns: {missing}")
    df = df[REQUIRED].dropna(subset=["Open", "High", "Low", "Close"])
    df = df[~df.index.duplicated(keep="last")].sort_index()
    if getattr(df.index, "tz", None) is not None:
        df.index = df.index.tz_convert("America/New_York").tz_localize(None).normalize()
    else:
        df.index = pd.to_datetime(df.index).tz_localize(None).normalize()
    df["Volume"] = df["Volume"].fillna(0).astype(float)
    return df


class YahooCsvAdapter(MarketDataAdapter):
    """Load data2_{SYM}_daily.csv from search paths, else download via yfinance."""

    name = "yahoo_csv"

    def __init__(self, search_dirs: Optional[List[str]] = None, cache_dir: Optional[str] = None, allow_download: bool = True):
        root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        self.search_dirs = search_dirs or [
            root,
            os.path.join(root, "..", "chan-monitor"),
            cache_dir or os.path.join(root, "data_cache"),
        ]
        self.cache_dir = cache_dir or os.path.join(root, "data_cache")
        self.allow_download = allow_download
        os.makedirs(self.cache_dir, exist_ok=True)

    def _find_csv(self, symbol: str) -> Optional[str]:
        name = f"data2_{symbol}_daily.csv"
        for d in self.search_dirs:
            if not d:
                continue
            p = os.path.join(d, name)
            if os.path.isfile(p) or os.path.islink(p):
                try:
                    if os.path.exists(p):
                        return p
                except OSError:
                    continue
        # also accept cache
        p = os.path.join(self.cache_dir, name)
        return p if os.path.isfile(p) else None

    def get_daily(self, symbol: str, start: Optional[str] = None, end: Optional[str] = None) -> BarData:
        path = self._find_csv(symbol)
        note = ""
        if path:
            df = pd.read_csv(path, index_col=0)
            df.index = pd.to_datetime(df.index, utc=True, errors="coerce")
            df = df[~df.index.isna()]
            df = _normalize(df)
            note = f"loaded {path}"
            source = "csv_cache"
        elif self.allow_download:
            import yfinance as yf
            hist = yf.Ticker(symbol).history(period="5y", interval="1d", auto_adjust=False)
            if hist is None or hist.empty:
                raise ValueError(f"no Yahoo data for {symbol}")
            df = _normalize(hist)
            out = os.path.join(self.cache_dir, f"data2_{symbol}_daily.csv")
            df.to_csv(out)
            note = f"downloaded via yfinance → {out}"
            source = "yahoo_download"
        else:
            raise FileNotFoundError(f"no CSV for {symbol} and download disabled")

        if start:
            df = df[df.index >= pd.Timestamp(start)]
        if end:
            df = df[df.index <= pd.Timestamp(end)]
        if df.empty:
            raise ValueError(f"{symbol}: empty after date filter")
        return BarData(symbol=symbol, df=df, source=source, delayed=True, note=note)
