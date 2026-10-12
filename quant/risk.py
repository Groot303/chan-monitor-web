"""Risk engine — must pass before any simulated order."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional, Set
from .config import RiskConfig


TECH_SYMBOLS = {
    "NVDA", "TSLA", "MU", "SNDK", "AAOI", "SPCX", "RKLB", "AMD", "AVGO",
    "AAPL", "META", "GOOG", "TSM", "ORCL", "INTC", "MRVL", "LITE", "PLTR",
}


@dataclass
class PortfolioState:
    cash: float
    equity: float
    peak_equity: float
    positions: Dict[str, Dict[str, Any]] = field(default_factory=dict)  # sym -> {qty, entry, stop, ...}
    pause_new_entries: bool = False
    pause_reason: Optional[str] = None
    events: List[Dict[str, Any]] = field(default_factory=list)
    order_ids: Set[str] = field(default_factory=set)

    @property
    def n_positions(self) -> int:
        return len(self.positions)


@dataclass
class RiskDecision:
    ok: bool
    shares: int = 0
    reasons: List[str] = field(default_factory=list)
    checks: Dict[str, Any] = field(default_factory=dict)


def position_size(equity: float, entry: float, stop: float, cfg: RiskConfig) -> int:
    """Shares from risk budget, capped by max position % and cash later."""
    if entry <= 0 or stop <= 0 or stop >= entry or equity <= 0:
        return 0
    risk_per_share = entry - stop
    if risk_per_share <= 0:
        return 0
    budget = equity * cfg.risk_per_trade
    by_risk = int(budget // risk_per_share)
    by_cap = int((equity * cfg.max_position_pct) // entry)
    return max(0, min(by_risk, by_cap))


def check_entry(
    symbol: str,
    entry_price: float,
    stop: float,
    state: PortfolioState,
    cfg: RiskConfig,
    order_key: str,
    stale_quote: bool = False,
) -> RiskDecision:
    reasons: List[str] = []
    checks: Dict[str, Any] = {}

    if order_key in state.order_ids:
        return RiskDecision(False, 0, ["重复订单防护: order_key 已存在"], {"duplicate": True})

    if stale_quote:
        return RiskDecision(False, 0, ["行情过期/异常，拒绝开仓"], {"stale_quote": True})

    if entry_price <= 0 or stop <= 0 or stop >= entry_price:
        return RiskDecision(False, 0, ["无效价格或止损方向错误"], {"invalid_stop": True})

    # drawdown pause
    if state.peak_equity > 0:
        dd = 1.0 - state.equity / state.peak_equity
        checks["drawdown"] = dd
        if dd >= cfg.max_drawdown or state.pause_new_entries:
            state.pause_new_entries = True
            state.pause_reason = state.pause_reason or f"组合回撤 {dd*100:.1f}% ≥ {cfg.max_drawdown*100:.0f}%"
            return RiskDecision(
                False, 0,
                [f"回撤保护: 暂停新开仓 ({state.pause_reason})。未自动清仓。"],
                checks,
            )

    if symbol in state.positions:
        return RiskDecision(False, 0, ["已持有该标的，拒绝重复加仓"], {"already_held": True})

    if state.n_positions >= cfg.max_positions:
        return RiskDecision(False, 0, [f"持仓数已达上限 {cfg.max_positions}"], {"max_positions": True})

    shares = position_size(state.equity, entry_price, stop, cfg)
    checks["shares_raw"] = shares
    notional = shares * entry_price
    if shares <= 0:
        return RiskDecision(False, 0, ["风险预算或仓位上限下可买股数为0"], checks)
    if notional > state.cash:
        shares = int(state.cash // entry_price)
        notional = shares * entry_price
        reasons.append("按可用现金下调股数")
        if shares <= 0:
            return RiskDecision(False, 0, ["现金不足"], checks)

    # concentration soft check
    tech_notional = sum(
        p["qty"] * p.get("last", p["entry"])
        for s, p in state.positions.items() if s in TECH_SYMBOLS
    )
    if symbol in TECH_SYMBOLS:
        if state.equity > 0 and (tech_notional + notional) / state.equity > cfg.sector_cap_pct:
            reasons.append(
                f"科技集中度将超过 {cfg.sector_cap_pct*100:.0f}%（软限制，仍允许但记录）"
            )
            checks["sector_soft_breach"] = True

    reasons.append(
        f"仓位 {shares} 股, 名义 {notional:.2f}, "
        f"单笔风险预算 {cfg.risk_per_trade*100:.2f}%, 单股上限 {cfg.max_position_pct*100:.0f}%"
    )
    reasons.append("止损不保证成交价，跳空可能导致损失超过预算")
    checks["shares"] = shares
    checks["notional"] = notional
    return RiskDecision(True, shares, reasons, checks)


def update_equity_peak(state: PortfolioState, equity: float, date: str) -> None:
    state.equity = equity
    if equity > state.peak_equity:
        state.peak_equity = equity
    if state.peak_equity > 0:
        dd = 1.0 - equity / state.peak_equity
        if dd >= state.peak_equity and False:
            pass
        if dd >= 0:  # always track
            if dd >= 0.10 and not state.pause_new_entries:
                # actual threshold applied via cfg in check_entry; here record event when crossed
                pass
