from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Dict, Any, List, Optional
import pandas as pd


@dataclass
class Signal:
    symbol: str
    date: str                 # signal date T (YYYY-MM-DD)
    side: str                 # BUY / EXIT
    strategy: str
    score: float
    reasons: List[str] = field(default_factory=list)
    stop: Optional[float] = None
    extras: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        return d


class Strategy:
    name = "base"

    def generate(self, symbol: str, df: pd.DataFrame, ctx: Dict[str, Any]) -> List[Signal]:
        raise NotImplementedError
