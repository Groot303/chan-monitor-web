import sys, os, unittest
import numpy as np
import pandas as pd
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from chan2 import find_pivot_edge_signals, score_signal, analyze_level, Seg

class TestPivotEdge(unittest.TestCase):
    def test_touch_zg_and_zd(self):
        # two pivots worth of toy segs; simple synthetic
        segs = [
            Seg(0, 100, 5, 110, True, True, 0, 1),
            Seg(5, 110, 10, 102, False, True, 1, 2),
            Seg(10, 102, 15, 108, True, True, 2, 3),
        ]
        pivots = [dict(first=0, last=2, zg=108.0, zd=102.0, enter=None, leave=None,
                       leave_up=None, third=False, n_segs=3, exits=[])]
        n = 16
        closes = np.linspace(100, 106, n)
        highs = closes + 1.5
        lows = closes - 1.5
        # force a clear ZG touch and ZD touch
        highs[12] = 108.2; lows[12] = 107.0; closes[12] = 107.8
        highs[8] = 103.0; lows[8] = 101.7; closes[8] = 102.1
        sigs = find_pivot_edge_signals(segs, pivots, highs, lows, closes)
        types = {s["type"] for s in sigs}
        self.assertIn("ZG_S", types)
        self.assertIn("ZD_B", types)
        for s in sigs:
            self.assertEqual(s["kind"], "pivot_edge")
            sc, bd = score_signal(s, "daily")
            self.assertTrue(0 <= sc <= 10)
            self.assertIn("base", bd)

    def test_score_routes(self):
        s, bd = score_signal(dict(type="ZG_S", kind="pivot_edge", price=100, confirmed=True,
                                  bars_ago=1, resonance="strong", zg=100, zd=95, dist_pct=0.1), "daily")
        self.assertGreaterEqual(s, 3.0)
        s2, _ = score_signal(dict(type="3B", price=100, confirmed=True, bars_ago=1,
                                  resonance="neutral", zg=95, zd=90, margin_pct=2), "daily")
        self.assertTrue(0 <= s2 <= 10)

if __name__ == "__main__":
    unittest.main()
