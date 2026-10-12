import unittest
from quant.risk import PortfolioState, position_size, check_entry
from quant.config import RiskConfig


class TestRisk(unittest.TestCase):
    def setUp(self):
        self.cfg = RiskConfig(initial_cash=100_000)

    def test_position_size_respects_risk_and_cap(self):
        # equity 100k, risk 0.5%=500, stop dist 5 → 100 shares; cap 10% = 10k/100=100
        shares = position_size(100_000, entry=100, stop=95, cfg=self.cfg)
        self.assertEqual(shares, 100)

    def test_invalid_stop_direction(self):
        st = PortfolioState(100_000, 100_000, 100_000)
        d = check_entry("NVDA", 100, 105, st, self.cfg, "k1")
        self.assertFalse(d.ok)

    def test_max_positions(self):
        st = PortfolioState(100_000, 100_000, 100_000)
        for i, s in enumerate(["A", "B", "C", "D"]):
            st.positions[s] = {"qty": 1, "entry": 10, "last": 10}
        d = check_entry("E", 50, 45, st, self.cfg, "k2")
        self.assertFalse(d.ok)
        self.assertTrue(d.checks.get("max_positions"))

    def test_drawdown_pause(self):
        st = PortfolioState(cash=80_000, equity=80_000, peak_equity=100_000)
        d = check_entry("MU", 100, 95, st, self.cfg, "k3")
        self.assertFalse(d.ok)
        self.assertTrue(st.pause_new_entries)

    def test_duplicate_order(self):
        st = PortfolioState(100_000, 100_000, 100_000)
        st.order_ids.add("dup")
        d = check_entry("MU", 100, 95, st, self.cfg, "dup")
        self.assertFalse(d.ok)
        self.assertTrue(d.checks.get("duplicate"))

    def test_already_held(self):
        st = PortfolioState(100_000, 100_000, 100_000)
        st.positions["TSLA"] = {"qty": 10, "entry": 200, "last": 200}
        d = check_entry("TSLA", 200, 190, st, self.cfg, "k4")
        self.assertFalse(d.ok)


if __name__ == "__main__":
    unittest.main()
