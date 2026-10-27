#!/usr/bin/env python3
"""Export interactive-chart JSON for one (or more) symbols from data2_*.csv + chan2.
Writes site/data/charts/{SYM}.json with OHLC and Chan overlays (strokes, segments,
pivots, signals) keyed by time+price so the frontend can draw without PNGs.

Usage:
  .venv/bin/python scripts/export_chart.py NVDA
  .venv/bin/python scripts/export_chart.py NVDA --data-dir /path/to/csvs
"""
from __future__ import annotations
import argparse, json, os, sys
from datetime import timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import pandas as pd
from chan2 import analyze_level, score_signal, resonance
from signal_safety import snapshot_contract

LEVELS = ("weekly", "daily", "30m", "5m")
RECENT = {"weekly": 4, "daily": 10, "30m": 40, "5m": 120}


def find_csv(sym: str, lv: str, data_dirs: list[str]) -> str:
    name = f"data2_{sym}_{lv}.csv"
    for d in data_dirs:
        p = os.path.join(d, name)
        if os.path.isfile(p):
            return p
    raise FileNotFoundError(name)


def load_df(path: str, tz: str = "America/New_York") -> pd.DataFrame:
    df = pd.read_csv(path, index_col=0)
    df.index = pd.to_datetime(df.index, utc=True).tz_convert(tz)
    df = df.dropna(subset=["High", "Low", "Open", "Close"])
    return df


def bar_time(ts, lv: str):
    """Lightweight Charts time: YYYY-MM-DD for daily/weekly, unix seconds (UTC) for intraday."""
    if hasattr(ts, "to_pydatetime"):
        ts = ts.to_pydatetime()
    if lv in ("30m", "5m"):
        # LWC expects UTCTimestamp (seconds)
        if ts.tzinfo is None:
            raise ValueError("intraday bar missing tz")
        return int(ts.astimezone(timezone.utc).timestamp())
    # business-day string in the market-local calendar date
    return ts.strftime("%Y-%m-%d")


def idx_time(df: pd.DataFrame, i: int, lv: str):
    return bar_time(df.index[i], lv)


def export_level(df: pd.DataFrame, lv: str, sym: str, big_states: list | None = None) -> dict:
    r = analyze_level(df)
    ohlc = []
    for ts, row in df.iterrows():
        ohlc.append({
            "time": bar_time(ts, lv),
            "open": round(float(row.Open), 6),
            "high": round(float(row.High), 6),
            "low": round(float(row.Low), 6),
            "close": round(float(row.Close), 6),
        })
    strokes = [
        {"time": idx_time(df, p[0], lv), "price": float(p[2]), "kind": p[1], "idx": int(p[0])}
        for p in r["pts"]
    ]
    segments = []
    for sg in r["segs"]:
        segments.append({
            "startTime": idx_time(df, sg.s_i, lv),
            "startPrice": float(sg.s_p),
            "endTime": idx_time(df, sg.e_i, lv),
            "endPrice": float(sg.e_p),
            "up": bool(sg.up),
            "confirmed": bool(sg.confirmed),
            "by_break": bool(sg.by_break),
        })
    pivots = []
    for P in r["pivots"]:
        s0 = r["segs"][P["first"]]
        s1 = r["segs"][P["last"]]
        pivots.append({
            "startTime": idx_time(df, s0.s_i, lv),
            "endTime": idx_time(df, s1.e_i, lv),
            "zg": float(P["zg"]),
            "zd": float(P["zd"]),
            "n_segs": int(P["n_segs"]),
            "third": bool(P["third"]),
        })
    # score signals (resonance optional; filled by caller for multi-level)
    signals = []
    for raw in r["signals"]:
        sg = {
            "type": raw["type"],
            "kind": raw.get("kind", "chan"),
            "time": idx_time(df, raw["idx"], lv),
            "price": float(raw["price"]),
            "confirmed": bool(raw["confirmed"]),
            "idx": int(raw["idx"]),
            "bars_ago": int(len(df) - 1 - raw["idx"]),
            "recent": (len(df) - 1 - raw["idx"]) < RECENT[lv],
        }
        for k in ("ratio", "margin_pct", "zd", "zg", "area_enter", "area_leave",
                  "dif_enter", "dif_leave", "ref_low", "ref_high", "dist_pct", "edge"):
            if k in raw and raw[k] is not None:
                v = raw[k]
                sg[k] = float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else v
        if big_states is not None:
            sg["resonance"] = resonance(sg["type"], big_states)
        score, bd = score_signal(sg, lv)
        sg["score"] = score
        sg["score_breakdown"] = bd
        sg.update(snapshot_contract(raw, df.index))
        signals.append(sg)
    return {
        "bars": len(df),
        "first": str(df.index[0])[:16],
        "last": str(df.index[-1])[:16],
        "last_close": float(df.Close.iloc[-1]),
        "state": r["state"],
        "ohlc": ohlc,
        "strokes": strokes,
        "segments": segments,
        "pivots": pivots,
        "signals": signals,
    }


def export_symbol(sym: str, data_dirs: list[str], tz: str = "America/New_York") -> dict:
    dfs, raw_levels = {}, {}
    for lv in LEVELS:
        try:
            path = find_csv(sym, lv, data_dirs)
        except FileNotFoundError as e:
            raw_levels[lv] = None
            continue
        df = load_df(path, tz=tz)
        if len(df) < 40:
            raw_levels[lv] = None
            continue
        dfs[lv] = df
        # first pass without resonance
        raw_levels[lv] = export_level(df, lv, sym, big_states=None)

    # resonance: 30m vs daily+weekly, daily vs weekly
    for lv, bigs in (("5m", ["30m", "daily", "weekly"]), ("30m", ["daily", "weekly"]), ("daily", ["weekly"])):
        if lv not in dfs or raw_levels.get(lv) is None:
            continue
        bs = []
        for b in bigs:
            if raw_levels.get(b):
                bs.append(raw_levels[b]["state"])
        # re-score with resonance
        raw_levels[lv] = export_level(dfs[lv], lv, sym, big_states=bs)

    levels = {lv: raw_levels[lv] for lv in LEVELS if raw_levels.get(lv)}
    from datetime import datetime, timezone
    return {
        "symbol": sym,
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
        "interactive": True,
        "levels": levels,
        "disclaimer": "缠论结构为启发式近似,未回测,不构成投资建议。末段未确认信号可能重绘。",
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("symbols", nargs="+", help="e.g. NVDA")
    ap.add_argument("--data-dir", action="append", default=[],
                    help="Directory containing data2_SYM_LEVEL.csv (repeatable)")
    ap.add_argument("--out-dir", default=None, help="Default: site/data/charts")
    args = ap.parse_args()
    data_dirs = args.data_dir or []
    data_dirs += [ROOT, os.path.join(ROOT, "..", "chan-monitor")]
    out_dir = args.out_dir or os.path.join(ROOT, "site", "data", "charts")
    os.makedirs(out_dir, exist_ok=True)
    for sym in args.symbols:
        sym = sym.upper()
        payload = export_symbol(sym, data_dirs)
        path = os.path.join(out_dir, f"{sym}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))
        n = {lv: len(payload["levels"][lv]["ohlc"]) for lv in payload["levels"]}
        ns = sum(len(payload["levels"][lv]["signals"]) for lv in payload["levels"])
        print(f"wrote {path} bars={n} signals={ns} size={os.path.getsize(path)}")


if __name__ == "__main__":
    main()
