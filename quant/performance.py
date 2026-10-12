"""Performance metrics from equity curve and trades."""
from __future__ import annotations
from typing import List, Dict, Any, Optional
import math
import numpy as np
import pandas as pd


def max_drawdown(equity: pd.Series) -> float:
    if equity.empty:
        return 0.0
    peak = equity.cummax()
    dd = equity / peak - 1.0
    return float(dd.min())


def sharpe(equity: pd.Series, periods_per_year: int = 252) -> Optional[float]:
    if len(equity) < 3:
        return None
    rets = equity.pct_change().dropna()
    if rets.std() == 0 or np.isnan(rets.std()):
        return None
    return float(np.sqrt(periods_per_year) * rets.mean() / rets.std())


def sortino(equity: pd.Series, periods_per_year: int = 252) -> Optional[float]:
    if len(equity) < 3:
        return None
    rets = equity.pct_change().dropna()
    downside = rets[rets < 0]
    if len(downside) == 0 or downside.std() == 0:
        return None
    return float(np.sqrt(periods_per_year) * rets.mean() / downside.std())


def cagr(equity: pd.Series, periods_per_year: int = 252) -> Optional[float]:
    if len(equity) < 2 or equity.iloc[0] <= 0:
        return None
    n = len(equity) - 1
    years = n / periods_per_year
    if years <= 0:
        return None
    return float((equity.iloc[-1] / equity.iloc[0]) ** (1 / years) - 1)


def summarize_trades(trades: List[Dict[str, Any]]) -> Dict[str, Any]:
    closed = [t for t in trades if t.get("status") == "closed"]
    if not closed:
        return {
            "trades": 0,
            "win_rate": None,
            "avg_win": None,
            "avg_loss": None,
            "avg_rr": None,
            "expectancy": None,
            "profit_factor": None,
            "avg_hold_days": None,
        }
    pnls = [float(t["pnl"]) for t in closed]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    avg_win = float(np.mean(wins)) if wins else 0.0
    avg_loss = float(np.mean(losses)) if losses else 0.0
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    pf = (gross_profit / gross_loss) if gross_loss > 0 else None
    holds = [t.get("hold_days") for t in closed if t.get("hold_days") is not None]
    avg_rr = (avg_win / abs(avg_loss)) if avg_loss < 0 else None
    return {
        "trades": len(closed),
        "win_rate": len(wins) / len(closed),
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "avg_rr": avg_rr,
        "expectancy": float(np.mean(pnls)),
        "profit_factor": pf,
        "avg_hold_days": float(np.mean(holds)) if holds else None,
        "total_pnl": float(sum(pnls)),
    }


def report(equity: pd.Series, trades: List[Dict[str, Any]], initial_cash: float, benchmark_rets: Optional[Dict[str, float]] = None) -> Dict[str, Any]:
    total_ret = float(equity.iloc[-1] / initial_cash - 1) if len(equity) else 0.0
    tr = summarize_trades(trades)
    out = {
        "total_return": total_ret,
        "cagr": cagr(equity),
        "max_drawdown": max_drawdown(equity),
        "sharpe": sharpe(equity),
        "sortino": sortino(equity),
        **tr,
        "final_equity": float(equity.iloc[-1]) if len(equity) else initial_cash,
        "initial_cash": initial_cash,
    }
    if benchmark_rets:
        out["benchmarks"] = benchmark_rets
    return out
