from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional
import pandas as pd

@dataclass
class BarData:
    symbol: str
    df: pd.DataFrame  # index=DatetimeTZ or naive date; cols Open High Low Close Volume
    source: str
    delayed: bool = True
    note: str = ""

class MarketDataAdapter(ABC):
    name: str = "base"

    @abstractmethod
    def get_daily(self, symbol: str, start: Optional[str] = None, end: Optional[str] = None) -> BarData:
        ...
