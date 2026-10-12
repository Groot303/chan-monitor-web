"""Daily backtest: signal on close T, fill at next open T+1. Long only."""
from __future__ import annotations
from typing import Dict, Any, List, Optional, Tuple
from collections import defaultdict
import pandas as pd
from .config import StrategyConfig
from .adapters.base import MarketDataAdapter
from .market_regime import latest_regime, enrich as _unused  # noqa
from .indicators import enrich
from .strategies.trend import TrendFollowStrategy
from .strategies.relative_strength import RelativeStrengthStrategy
from .strategies.breakout import BreakoutStrategy
from .scoring import score_signal
from .risk import PortfolioState, check_entry, update_equity_peak
from .performance import report


def _apply_slippage(price: float, side: str, bps: float) -> float:
    slip = price * (bps / 10000.0)
    if side == "BUY":
        return price + slip
    return price - slip


def _commission(shares: int, cfg) -> float:
    return max(cfg.commission_min, cfg.commission_per_share * shares)


class DailyBacktester:
    def __init__(self, cfg: StrategyConfig | None = None):
        self.cfg = cfg or StrategyConfig()
        self.strategies = [
            TrendFollowStrategy(self.cfg.risk.atr_stop_mult),
            RelativeStrengthStrategy(self.cfg.risk.atr_stop_mult),
            BreakoutStrategy(self.cfg.breakout_lookback, atr_stop_mult=self.cfg.risk.atr_stop_mult),
        ]

    def _mark_equity(self, state: PortfolioState, bars: Dict[str, pd.Series]) -> float:
        eq = state.cash
        for sym, pos in state.positions.items():
            px = bars.get(sym)
            last = float(px["Close"]) if px is not None and not pd.isna(px["Close"]) else pos["entry"]
            pos["last"] = last
            eq += pos["qty"] * last
        return eq

    def run(
        self,
        data: Dict[str, pd.DataFrame],
        benchmarks: Dict[str, pd.DataFrame],
        start: Optional[str] = None,
        end: Optional[str] = None,
    ) -> Dict[str, Any]:
        cfg = self.cfg
        # calendar = union of all dates
        all_dates = sorted(set().union(*[set(df.index) for df in data.values() if len(df)]))
        if start:
            all_dates = [d for d in all_dates if d >= pd.Timestamp(start)]
        if end:
            all_dates = [d for d in all_dates if d <= pd.Timestamp(end)]
        if len(all_dates) < 5:
            return {"error": "日期范围过短或无数据", "fill_rule": cfg.fill_rule}

        # Precompute signals per symbol keyed by date
        regime_end = latest_regime(benchmarks.get("QQQ"), benchmarks.get("SPY"))
        ctx_base = {"benchmarks": benchmarks, "regime": regime_end}

        signals_by_date: Dict[pd.Timestamp, List] = defaultdict(list)
        all_signals_scored = []
        for sym, df in data.items():
            for strat in self.strategies:
                raw = strat.generate(sym, df, ctx_base)
                for sig in raw:
                    total, parts, notes = score_signal(sig, df, ctx_base, cfg.scores)
                    sig.score = total
                    sig.extras["score_parts"] = parts
                    sig.extras["score_notes"] = notes
                    if total >= cfg.score_entry_min and sig.side == "BUY":
                        ts = pd.Timestamp(sig.date)
                        signals_by_date[ts].append(sig)
                        all_signals_scored.append(sig.to_dict())

        state = PortfolioState(
            cash=cfg.risk.initial_cash,
            equity=cfg.risk.initial_cash,
            peak_equity=cfg.risk.initial_cash,
        )
        pending: List[Dict[str, Any]] = []  # fills for next open
        trades: List[Dict[str, Any]] = []
        equity_rows = []
        events: List[Dict[str, Any]] = []

        date_index = {d: i for i, d in enumerate(all_dates)}

        for i, dt in enumerate(all_dates):
            # 1) Process pending entries/exits at today's open
            still_pending = []
            for order in pending:
                sym = order["symbol"]
                if sym not in data or dt not in data[sym].index:
                    still_pending.append(order)  # wait for next session with data
                    continue
                bar = data[sym].loc[dt]
                o, h, l, c = float(bar["Open"]), float(bar["High"]), float(bar["Low"]), float(bar["Close"])

                if order["type"] == "entry":
                    fill = _apply_slippage(o, "BUY", cfg.costs.slippage_bps)
                    stop = order["stop"]
                    # if open gaps through stop, skip entry (invalid)
                    if fill <= stop:
                        events.append({"date": str(dt.date()), "type": "entry_skipped_gap", "symbol": sym})
                        continue
                    decision = check_entry(
                        sym, fill, stop, state, cfg.risk, order["order_key"], stale_quote=False
                    )
                    if not decision.ok:
                        events.append({"date": str(dt.date()), "type": "entry_rejected", "symbol": sym, "reasons": decision.reasons})
                        continue
                    shares = decision.shares
                    comm = _commission(shares, cfg.costs)
                    cost = shares * fill + comm
                    if cost > state.cash:
                        events.append({"date": str(dt.date()), "type": "entry_rejected", "symbol": sym, "reasons": ["现金不足(含佣金)"]})
                        continue
                    state.cash -= cost
                    state.positions[sym] = {
                        "qty": shares,
                        "entry": fill,
                        "stop": stop,
                        "entry_date": str(dt.date()),
                        "strategy": order["strategy"],
                        "signal_date": order["signal_date"],
                        "score": order["score"],
                        "comm_entry": comm,
                        "order_key": order["order_key"],
                        "last": fill,
                    }
                    state.order_ids.add(order["order_key"])
                    trades.append({
                        "id": order["order_key"],
                        "symbol": sym,
                        "status": "open",
                        "strategy": order["strategy"],
                        "signal_date": order["signal_date"],
                        "entry_date": str(dt.date()),
                        "entry_price": fill,
                        "stop": stop,
                        "qty": shares,
                        "score": order["score"],
                        "reasons": order.get("reasons", []),
                        "risk_checks": decision.checks,
                    })
                elif order["type"] == "exit":
                    if sym not in state.positions:
                        continue
                    pos = state.positions[sym]
                    # gap through stop: fill at open; else if stop in range fill stop; else target exit at open
                    reason = order.get("reason", "exit")
                    if reason == "stop":
                        if o <= pos["stop"]:
                            raw_px = o  # gap through
                            reason = "stop_gap_open"
                        elif l <= pos["stop"] <= h:
                            raw_px = pos["stop"]
                        else:
                            # stop not touched today — should not happen if scheduled correctly
                            still_pending.append(order)
                            continue
                    else:
                        raw_px = o
                    fill = _apply_slippage(raw_px, "SELL", cfg.costs.slippage_bps)
                    shares = pos["qty"]
                    comm = _commission(shares, cfg.costs)
                    proceeds = shares * fill - comm
                    state.cash += proceeds
                    pnl = proceeds - (shares * pos["entry"] + pos.get("comm_entry", 0))
                    entry_dt = pd.Timestamp(pos["entry_date"])
                    hold = (dt - entry_dt).days
                    # update trade record
                    for t in trades:
                        if t["id"] == pos["order_key"] and t["status"] == "open":
                            t.update({
                                "status": "closed",
                                "exit_date": str(dt.date()),
                                "exit_price": fill,
                                "exit_reason": reason,
                                "pnl": pnl,
                                "pnl_pct": fill / pos["entry"] - 1,
                                "hold_days": hold,
                                "comm_exit": comm,
                            })
                            break
                    del state.positions[sym]

            pending = still_pending

            # 2) Intrabar stop check for open positions (using today's H/L; exit next open if touched — conservative: exit same-day at stop if touched, documenting ambiguity)
            # Spec: prefer next-day open for signal exits; for stops, if day's range trades through stop, fill at stop (or open if gapped).
            # We handle stops same day after open processing:
            to_exit = []
            for sym, pos in list(state.positions.items()):
                if sym not in data or dt not in data[sym].index:
                    continue
                # skip if just entered today
                if pos["entry_date"] == str(dt.date()):
                    continue
                bar = data[sym].loc[dt]
                o, h, l = float(bar["Open"]), float(bar["High"]), float(bar["Low"])
                stop = pos["stop"]
                if o <= stop:
                    # already should have been caught — force exit at open
                    pending.append({
                        "type": "exit", "symbol": sym, "reason": "stop",
                        "order_key": pos["order_key"] + "|stop|" + str(dt.date()),
                    })
                    # process immediately via synthetic: do exit now
                    fill = _apply_slippage(o, "SELL", cfg.costs.slippage_bps)
                    shares = pos["qty"]
                    comm = _commission(shares, cfg.costs)
                    proceeds = shares * fill - comm
                    state.cash += proceeds
                    pnl = proceeds - (shares * pos["entry"] + pos.get("comm_entry", 0))
                    hold = (dt - pd.Timestamp(pos["entry_date"])).days
                    for t in trades:
                        if t["id"] == pos["order_key"] and t["status"] == "open":
                            t.update({
                                "status": "closed", "exit_date": str(dt.date()),
                                "exit_price": fill, "exit_reason": "stop_gap_open",
                                "pnl": pnl, "pnl_pct": fill / pos["entry"] - 1,
                                "hold_days": hold, "comm_exit": comm,
                            })
                            break
                    to_exit.append(sym)
                elif l <= stop:
                    fill = _apply_slippage(stop, "SELL", cfg.costs.slippage_bps)
                    shares = pos["qty"]
                    comm = _commission(shares, cfg.costs)
                    proceeds = shares * fill - comm
                    state.cash += proceeds
                    pnl = proceeds - (shares * pos["entry"] + pos.get("comm_entry", 0))
                    hold = (dt - pd.Timestamp(pos["entry_date"])).days
                    for t in trades:
                        if t["id"] == pos["order_key"] and t["status"] == "open":
                            t.update({
                                "status": "closed", "exit_date": str(dt.date()),
                                "exit_price": fill, "exit_reason": "stop",
                                "pnl": pnl, "pnl_pct": fill / pos["entry"] - 1,
                                "hold_days": hold, "comm_exit": comm,
                            })
                            break
                    to_exit.append(sym)
            for sym in to_exit:
                state.positions.pop(sym, None)

            # 3) Time exit
            for sym, pos in list(state.positions.items()):
                hold = (dt - pd.Timestamp(pos["entry_date"])).days
                if hold >= cfg.hold_max_days and sym in data and dt in data[sym].index:
                    # schedule exit next open
                    if i + 1 < len(all_dates):
                        pending.append({
                            "type": "exit", "symbol": sym, "reason": "time",
                            "order_key": pos["order_key"] + "|time|" + str(dt.date()),
                        })

            # 4) New signals at close → queue entry for next open
            day_sigs = signals_by_date.get(dt, [])
            # pick highest score per symbol
            best: Dict[str, Any] = {}
            for sig in day_sigs:
                if sig.symbol in state.positions:
                    continue
                if sig.symbol not in best or sig.score > best[sig.symbol].score:
                    best[sig.symbol] = sig
            # sort by score, respect capacity
            ranked = sorted(best.values(), key=lambda s: -s.score)
            for sig in ranked:
                if state.pause_new_entries:
                    events.append({"date": str(dt.date()), "type": "signal_paused", "symbol": sig.symbol})
                    continue
                order_key = f"{sig.symbol}|{sig.date}|{sig.strategy}|{sig.side}"
                if order_key in state.order_ids:
                    continue
                if any(p.get("order_key") == order_key for p in pending):
                    continue
                pending.append({
                    "type": "entry",
                    "symbol": sig.symbol,
                    "stop": sig.stop,
                    "strategy": sig.strategy,
                    "signal_date": sig.date,
                    "score": sig.score,
                    "reasons": sig.reasons,
                    "order_key": order_key,
                })

            # 5) mark to market
            bars = {}
            for sym in list(state.positions.keys()) + list(data.keys()):
                if sym in data and dt in data[sym].index:
                    bars[sym] = data[sym].loc[dt]
            eq = self._mark_equity(state, bars)
            update_equity_peak(state, eq, str(dt.date()))
            if state.peak_equity > 0:
                dd = 1.0 - eq / state.peak_equity
                if dd >= cfg.risk.max_drawdown and not state.pause_new_entries:
                    state.pause_new_entries = True
                    state.pause_reason = f"回撤 {dd*100:.1f}% 触及 {cfg.risk.max_drawdown*100:.0f}% 阈值"
                    events.append({
                        "date": str(dt.date()),
                        "type": "drawdown_pause",
                        "message": state.pause_reason,
                        "action": "暂停新开仓，未自动清仓",
                    })
            equity_rows.append({"date": str(dt.date()), "equity": eq, "cash": state.cash, "n_pos": state.n_positions})

        equity = pd.Series({pd.Timestamp(r["date"]): r["equity"] for r in equity_rows}).sort_index()

        # benchmark buy&hold over same window
        bench_rets = {}
        for b, bdf in benchmarks.items():
            sub = bdf.loc[(bdf.index >= all_dates[0]) & (bdf.index <= all_dates[-1])]
            if len(sub) >= 2:
                bench_rets[b] = float(sub["Close"].iloc[-1] / sub["Close"].iloc[0] - 1)

        # close remaining at last close (mark) — label as open_eod
        open_trades = [t for t in trades if t["status"] == "open"]
        for t in open_trades:
            t["status"] = "open_eod"
            t["mark_price"] = state.positions.get(t["symbol"], {}).get("last")
            if t.get("mark_price") and t.get("entry_price"):
                t["unrealized_pnl"] = (t["mark_price"] - t["entry_price"]) * t["qty"]

        perf = report(equity, trades, cfg.risk.initial_cash, bench_rets)
        # cost drag: compare rough — already included in trades
        perf_gross = None  # costs already in pnl; document separately

        return {
            "version": cfg.version,
            "fill_rule": cfg.fill_rule,
            "config": cfg.to_dict(),
            "regime_latest": regime_end,
            "performance": perf,
            "performance_note": (
                "成本已计入佣金与滑点。评分仅表示规则匹配度，不等于上涨概率。"
                "结果为历史研究，不能外推未来盈利能力。不构成投资建议。"
            ),
            "equity_curve": equity_rows,
            "trades": trades,
            "events": events,
            "signals_count": len(all_signals_scored),
            "signals_sample": sorted(all_signals_scored, key=lambda x: -x["score"])[:50],
            "open_positions": {k: {kk: vv for kk, vv in v.items() if kk != "order_key" or True} for k, v in state.positions.items()},
            "data_sources": {s: "provided" for s in data},
            "disclaimer": "研究原型 / Research prototype. Not investment advice. No live trading.",
        }


def load_universe(adapter: MarketDataAdapter, symbols: List[str], benches: List[str], start=None, end=None):
    data, benchmarks, failures = {}, {}, {}
    for s in symbols:
        try:
            bar = adapter.get_daily(s, start=start, end=end)
            data[s] = bar.df
        except Exception as e:
            failures[s] = str(e)[:200]
    for s in benches:
        try:
            bar = adapter.get_daily(s, start=start, end=end)
            benchmarks[s] = bar.df
        except Exception as e:
            failures[s] = str(e)[:200]
    return data, benchmarks, failures
