"""Glossary knowledge-base validation (tests/test_glossary.py).
Checks: schema completeness, unique ids, related_indicators resolve,
canvas_node_ids reference real TX_NODES ids from site/app.js,
and no term claims a real-time value (knowledge != live data)."""
import json, os, re, sys, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JSON_PATH = os.path.join(ROOT, "site", "data", "indicator_glossary.json")
APP_JS = os.path.join(ROOT, "site", "app.js")

REQ = ["id", "abbreviation", "chinese_name", "english_name", "simple_explanation",
       "definition", "why_it_matters", "frequency", "higher_than_expected",
       "lower_than_expected", "transmission_paths", "asset_impacts", "exceptions",
       "trading_application", "related_indicators", "sources", "canvas_node_ids"]
TA_REQ = ["short_term", "before_release", "after_release", "combine_with", "avoid"]
ASSETS = ["us_stocks", "a_shares", "bonds", "usd", "gold"]
# Terms the task requires at minimum (task §四).
REQUIRED_IDS = {"cpi", "core-cpi", "ppi", "pce", "core-pce", "gdp", "pmi", "nfp",
                "unemployment", "initial-claims", "fomc", "fed-funds-rate",
                "treasury-10y", "treasury-2y", "yield-curve", "real-rate", "bp",
                "vix", "dxy", "credit-spread", "liquidity", "risk-appetite",
                "market-breadth", "pe", "pb", "eps", "macd", "rsi", "atr"}


class T(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(JSON_PATH, encoding="utf-8") as f:
            cls.data = json.load(f)
        cls.terms = cls.data["terms"]
        cls.by_id = {t["id"]: t for t in cls.terms}
        with open(APP_JS, encoding="utf-8") as f:
            cls.app_js = f.read()
        cls.tx_nodes = set(re.findall(r'\{\s*id:\s*"([^"]+)"', cls.app_js))

    def test_required_terms_present(self):
        missing = REQUIRED_IDS - set(self.by_id)
        self.assertEqual(missing, set(), f"missing required terms: {missing}")

    def test_unique_ids(self):
        self.assertEqual(len(self.by_id), len(self.terms), "duplicate term ids")

    def test_schema(self):
        for t in self.terms:
            for k in REQ:
                self.assertIn(k, t, f"{t.get('id')} missing {k}")
                if k not in ("canvas_node_ids", "sources"):
                    self.assertTrue(t[k], f"{t['id']} empty {k}")
            for k in TA_REQ:
                self.assertIn(k, t["trading_application"], f"{t['id']} trading missing {k}")
                self.assertTrue(t["trading_application"][k], f"{t['id']} trading empty {k}")
            for k in ASSETS:
                self.assertIn(k, t["asset_impacts"], f"{t['id']} assets missing {k}")

    def test_related_indicators_resolve(self):
        for t in self.terms:
            for r in t["related_indicators"]:
                self.assertIn(r, self.by_id, f"{t['id']} related -> unknown {r}")

    def test_canvas_nodes_exist(self):
        for t in self.terms:
            for n in t["canvas_node_ids"]:
                self.assertIn(n, self.tx_nodes, f"{t['id']} canvas -> unknown node {n}")

    def test_no_fabricated_live_values(self):
        # Knowledge text must not claim a current value (it has no live data).
        bad = re.compile(r"(当前|最新|截至今日).{0,12}(报|为|涨|跌)\s*\d")
        for t in self.terms:
            blob = " ".join([str(t[k]) for k in ("simple_explanation", "definition",
                                                 "higher_than_expected", "lower_than_expected")])
            self.assertIsNone(bad.search(blob), f"{t['id']} looks like a live value claim")

    def test_conditional_language(self):
        # Impact descriptions must use conditional wording, not deterministic forecasts.
        cond = re.compile(r"(可能|通常|若|当|取决于|需看|不等于|不是)")
        for t in self.terms:
            blob = t["higher_than_expected"] + t["lower_than_expected"]
            self.assertTrue(cond.search(blob), f"{t['id']} impact lacks conditional wording")


if __name__ == "__main__":
    unittest.main()
