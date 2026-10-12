"""Paper trading executor — simulated only, never calls live order APIs."""
from __future__ import annotations
from typing import Dict, Any, List, Optional
from .config import StrategyConfig
from .risk import PortfolioState, check_entry
from .strategies.base import Signal


class PaperBroker:
    """Maintains simulated cash/positions. Idempotent order keys."""

    def __init__(self, cfg: StrategyConfig | None = None):
        self.cfg = cfg or StrategyConfig()
        self.state = PortfolioState(
            cash=self.cfg.risk.initial_cash,
            equity=self.cfg.risk.initial_cash,
            peak_equity=self.cfg.risk.initial_cash,
        )
        self.orders: List[Dict[str, Any]] = []

    def submit_entry(self, signal: Signal, fill_price: float) -> Dict[str, Any]:
        if signal.side != "BUY":
            return {"ok": False, "reason": "only long entries in v1"}
        order_key = f"paper|{signal.symbol}|{signal.date}|{signal.strategy}"
        decision = check_entry(
            signal.symbol, fill_price, signal.stop or 0.0,
            self.state, self.cfg.risk, order_key,
        )
        rec = {
            "order_key": order_key,
            "signal": signal.to_dict(),
            "fill_price": fill_price,
            "decision": {"ok": decision.ok, "shares": decision.shares, "reasons": decision.reasons, "checks": decision.checks},
            "kind": "paper",  # never 'live'
        }
        if not decision.ok:
            self.orders.append(rec)
            return rec
        shares = decision.shares
        cost = shares * fill_price
        self.state.cash -= cost
        self.state.positions[signal.symbol] = {
            "qty": shares, "entry": fill_price, "stop": signal.stop,
            "entry_date": signal.date, "strategy": signal.strategy, "last": fill_price,
            "order_key": order_key,
        }
        self.state.order_ids.add(order_key)
        self.orders.append(rec)
        return rec
