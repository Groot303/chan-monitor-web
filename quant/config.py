"""Default research configuration (overridable via YAML / CLI)."""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Any

WATCHLIST = ["SNDK", "MU", "AAOI", "NVDA", "TSLA", "SPCX", "RKLB"]
BENCHMARKS = ["QQQ", "SPY"]

@dataclass
class RiskConfig:
    risk_per_trade: float = 0.005      # 0.5% of equity
    max_position_pct: float = 0.10    # 10% per name
    max_positions: int = 4
    max_drawdown: float = 0.10        # pause new entries
    sector_cap_pct: float = 0.40      # soft tech concentration
    atr_stop_mult: float = 2.0
    initial_cash: float = 100_000.0

@dataclass
class CostConfig:
    commission_per_share: float = 0.005
    commission_min: float = 1.0
    slippage_bps: float = 5.0         # 0.05% of notional each way

@dataclass
class ScoreWeights:
    trend: float = 25.0
    relative_strength: float = 25.0
    momentum: float = 20.0
    breakout_volume: float = 20.0
    risk_penalty: float = 10.0        # subtracted when risk poor

@dataclass
class StrategyConfig:
    version: str = "us-lab-v1"
    watchlist: List[str] = field(default_factory=lambda: list(WATCHLIST))
    benchmarks: List[str] = field(default_factory=lambda: list(BENCHMARKS))
    score_entry_min: float = 55.0
    ma_fast: int = 20
    ma_slow: int = 50
    ma_long: int = 200
    atr_period: int = 14
    breakout_lookback: int = 20
    rs_lookbacks: tuple = (20, 60)
    hold_max_days: int = 30
    risk: RiskConfig = field(default_factory=RiskConfig)
    costs: CostConfig = field(default_factory=CostConfig)
    scores: ScoreWeights = field(default_factory=ScoreWeights)
    # Fill rule documented for reproducibility
    fill_rule: str = (
        "Signal confirmed after daily bar close on day T; "
        "simulated fill at next session open on T+1 "
        "(open price +/- slippage). Stop gaps fill at open."
    )

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["rs_lookbacks"] = list(self.rs_lookbacks)
        return d
