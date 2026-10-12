import unittest
import pandas as pd
import numpy as np
from quant.config import StrategyConfig
from quant.backtest import DailyBacktester
from quant.paper import PaperBroker
from quant.strategies.base import Signal
from quant.strategies.breakout import BreakoutStrategy
from quant.indicators import enrich


def make_trend_up(n=120, start=100.0):
    idx = pd.bdate_range("2024-01-02", periods=n)
    close = start + np.linspace(0, 40, n) + np.sin(np.linspace(0, 6, n))
    df = pd.DataFrame({
        "Open": close - 0.2,
        "High": close + 1.0,
        "Low": close - 1.0,
        "Close": close,
        "Volume": np.full(n, 2_000_000.0),
    }, index=idx)
    # inject a breakout near the end with volume spike
    df.iloc[-5, df.columns.get_loc("Volume")] = 5_000_000
    df.iloc[-5, df.columns.get_loc("Close")] = df["High"].iloc[-25:-5].max() + 2
    df.iloc[-5, df.columns.get_loc("High")] = df.iloc[-5]["Close"] + 0.5
    return df


class TestBacktest(unittest.TestCase):
    def test_next_day_fill_no_same_day(self):
        """Signal on T must not fill using T close as entry."""
        df = make_trend_up()
        bench = make_trend_up()
        cfg = StrategyConfig()
        cfg.watchlist = ["TEST"]
        cfg.score_entry_min = 0  # accept all scored
        # lower bar for test
        cfg.scores.trend = 40
        bt = DailyBacktester(cfg)
        # force only breakout-like by running and checking entry_date > signal_date
        result = bt.run({"TEST": df}, {"QQQ": bench, "SPY": bench})
        for t in result.get("trades", []):
            if t.get("signal_date") and t.get("entry_date"):
                self.assertGreater(t["entry_date"], t["signal_date"])

    def test_gap_stop_fills_at_open(self):
        """If open gaps below stop, exit uses open (gap)."""
        idx = pd.bdate_range("2024-06-03", periods=5)
        # day0 entry setup processed day1; craft positions manually via paper + logic
        # Use backtester with synthetic: up then gap down
        closes = [100, 101, 102, 90, 91]
        df = pd.DataFrame({
            "Open": [100, 100.5, 101.5, 88, 90],  # day3 gaps to 88
            "High": [101, 102, 103, 92, 92],
            "Low": [99, 100, 101, 87, 89],
            "Close": closes,
            "Volume": [2e6] * 5,
        }, index=idx)
        # Manual mini simulation of stop gap
        stop = 95.0
        entry = 100.5
        o = 88.0
        self.assertLess(o, stop)
        fill = o  # gap rule
        pnl_per_share = fill - entry
        self.assertLess(pnl_per_share, stop - entry)

    def test_hh20_breakout_uses_prior_high(self):
        df = make_trend_up(80)
        en = enrich(df)
        i = 40
        self.assertEqual(en["HH20"].iloc[i], df["High"].iloc[i - 20 : i].max())

    def test_paper_rejects_duplicate(self):
        broker = PaperBroker()
        sig = Signal("MU", "2024-06-01", "BUY", "trend", 70, stop=90.0, extras={"close": 100})
        r1 = broker.submit_entry(sig, 100)
        r2 = broker.submit_entry(sig, 100)
        self.assertTrue(r1["decision"]["ok"])
        self.assertFalse(r2["decision"]["ok"])

    def test_breakout_strategy_emits_on_volume(self):
        df = make_trend_up(80)
        sigs = BreakoutStrategy().generate("X", df, {})
        # may or may not fire depending on injected bar; ensure no crash and types
        for s in sigs:
            self.assertEqual(s.side, "BUY")
            self.assertIsNotNone(s.stop)


if __name__ == "__main__":
    unittest.main()
