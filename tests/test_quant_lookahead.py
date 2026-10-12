import unittest
import pandas as pd
import numpy as np
from quant.indicators import enrich
from quant.strategies.breakout import BreakoutStrategy


class TestLookahead(unittest.TestCase):
    def test_breakout_cannot_use_future_high(self):
        n = 50
        idx = pd.bdate_range("2024-01-02", periods=n)
        close = np.full(n, 100.0)
        high = np.full(n, 101.0)
        # future spike should not affect earlier HH20
        high[-1] = 200
        df = pd.DataFrame({
            "Open": close, "High": high, "Low": close - 1,
            "Close": close, "Volume": np.full(n, 1e6),
        }, index=idx)
        en = enrich(df)
        # at bar -5, HH20 must not equal 200
        self.assertNotEqual(en["HH20"].iloc[-5], 200)
        self.assertLessEqual(en["HH20"].iloc[-5], 101.0001)

    def test_signal_dates_within_history(self):
        n = 80
        idx = pd.bdate_range("2024-01-02", periods=n)
        close = 100 + np.linspace(0, 20, n)
        df = pd.DataFrame({
            "Open": close - 0.1, "High": close + 1, "Low": close - 1,
            "Close": close, "Volume": np.full(n, 3e6),
        }, index=idx)
        # make last bar break prior high with volume
        df.iloc[-1, df.columns.get_loc("Close")] = df["High"].iloc[-21:-1].max() + 1
        df.iloc[-1, df.columns.get_loc("High")] = df.iloc[-1]["Close"] + 0.2
        df.iloc[-1, df.columns.get_loc("Volume")] = 10e6
        sigs = BreakoutStrategy().generate("T", df, {})
        for s in sigs:
            self.assertLessEqual(pd.Timestamp(s.date), idx[-1])


if __name__ == "__main__":
    unittest.main()
