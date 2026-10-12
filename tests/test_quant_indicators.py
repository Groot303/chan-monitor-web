import unittest
import pandas as pd
import numpy as np
from quant.indicators import sma, atr, enrich


def _bars(n=60, start=100.0):
    rng = np.random.default_rng(0)
    idx = pd.bdate_range("2024-01-02", periods=n)
    close = start + np.cumsum(rng.normal(0, 1, n))
    high = close + 1
    low = close - 1
    open_ = close.copy()
    vol = rng.integers(1_000_000, 2_000_000, n)
    return pd.DataFrame({"Open": open_, "High": high, "Low": low, "Close": close, "Volume": vol}, index=idx)


class TestIndicators(unittest.TestCase):
    def test_sma_causal(self):
        s = pd.Series([1, 2, 3, 4, 5], dtype=float)
        m = sma(s, 3)
        self.assertTrue(np.isnan(m.iloc[1]))
        self.assertAlmostEqual(m.iloc[2], 2.0)
        self.assertAlmostEqual(m.iloc[4], 4.0)

    def test_enrich_hh20_no_lookahead(self):
        df = _bars(40)
        en = enrich(df)
        # HH20 at i uses High[i-20:i] max, not including today
        i = 25
        expected = df["High"].iloc[i - 20 : i].max()
        self.assertAlmostEqual(en["HH20"].iloc[i], expected)

    def test_atr_positive(self):
        df = _bars(30)
        a = atr(df, 14)
        self.assertTrue((a.dropna() > 0).all())


if __name__ == "__main__":
    unittest.main()
