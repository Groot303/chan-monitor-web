import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd

from scripts.fetch_nasdaq import fetch_nasdaq_frames


class NasdaqFetchTest(unittest.TestCase):
    def test_all_four_levels_keep_index_ohlc_and_exchange_time(self):
        calls = []

        def download(symbol, **options):
            calls.append((symbol, options["interval"], options["period"]))
            cols = pd.MultiIndex.from_product(
                [["Open", "High", "Low", "Close", "Volume"], ["^IXIC"]])
            return pd.DataFrame([[100, 110, 90, 105, 1000]],
                                index=pd.DatetimeIndex(["2026-10-23 16:00:00"], tz="America/New_York"),
                                columns=cols)

        with patch.dict(sys.modules, {"yfinance": SimpleNamespace(download=download)}):
            frames, failures = fetch_nasdaq_frames()

        self.assertEqual(failures, {})
        self.assertEqual(calls, [("^IXIC", "1wk", "5y"), ("^IXIC", "1d", "2y"),
                                 ("^IXIC", "30m", "60d"), ("^IXIC", "5m", "30d")])
        for frame in frames.values():
            self.assertEqual(list(frame.columns), ["Open", "High", "Low", "Close", "Volume"])
            self.assertEqual(frame.iloc[0]["Close"], 105)
            self.assertEqual(str(frame.index.tz), "America/New_York")

    def test_failed_interval_does_not_discard_other_levels(self):
        def download(symbol, **options):
            if options["interval"] == "5m":
                raise ValueError("intraday source unavailable")
            return pd.DataFrame({"Open": [100], "High": [110], "Low": [90], "Close": [105]},
                                index=pd.DatetimeIndex(["2026-10-23"]))

        with patch.dict(sys.modules, {"yfinance": SimpleNamespace(download=download)}):
            frames, failures = fetch_nasdaq_frames()

        self.assertEqual(set(frames), {"weekly", "daily", "30m"})
        self.assertEqual(failures, {"5m": "intraday source unavailable"})
        self.assertEqual(frames["daily"].iloc[0]["Volume"], 0)


if __name__ == "__main__":
    unittest.main()
