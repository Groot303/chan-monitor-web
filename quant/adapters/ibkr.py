"""IBKR adapter stub — NOT connected. No credentials required or accepted here."""
from __future__ import annotations
from typing import Optional
from .base import BarData, MarketDataAdapter


class IbkrAdapterStub(MarketDataAdapter):
    """Placeholder for Interactive Brokers historical data.

    Status: NOT CONNECTED.
    Intended future use: IB Gateway / Client Portal for delayed or realtime bars,
    account equity (read-only), positions (read-only). Live order placement is
    explicitly out of scope for v1.

    Credentials must live only in server-side env vars (e.g. IBKR_HOST, IBKR_PORT,
    IBKR_CLIENT_ID) — never in frontend, git, or logs.
    """

    name = "ibkr_stub"
    connected = False
    status = "尚未连接"

    def get_daily(self, symbol: str, start: Optional[str] = None, end: Optional[str] = None) -> BarData:
        raise NotImplementedError(
            "IbkrAdapterStub is not connected. Use YahooCsvAdapter for research, "
            "or configure IBKR env vars and implement the live adapter in a later phase. "
            "Live trading is disabled in v1."
        )

    def health(self) -> dict:
        return {
            "adapter": self.name,
            "connected": False,
            "status": self.status,
            "live_trading": False,
            "hint": "Set IBKR_* env vars only on a protected host; do not commit secrets.",
        }
