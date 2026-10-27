import ast
import json
import subprocess
import sys
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
import numpy as np
import pandas as pd
from chan2 import find_pivot_edge_signals, Seg, score_signal
from signal_safety import (unknown_regime, measured_regime, regime_state,
                           regime_decision, snapshot_contract, confirmation_contract)
from signal_replay import replay
from scripts.replay_p0_example import fixture


class ContractTests(unittest.TestCase):
    def test_export_preserves_contract_and_old_data_fails_closed(self):
        from scripts.export_chart import export_level
        exported = export_level(fixture(), "30m", "TEST")
        self.assertTrue(exported["signals"])
        self.assertTrue(all(s["first_seen_time"] is None and not s["backtest_eligible"]
                            for s in exported["signals"]))
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "src"
            dst = Path(tmp) / "dst"
            src.mkdir()
            for regime in ({}, unknown_regime("SPY", "offline")):
                (src / "signals.json").write_text(json.dumps({"generated": "2025-01-01",
                    "symbols": {}, "signals": [], "regime": regime}))
                subprocess.run([sys.executable, "scripts/build_data.py", str(src), "--outdir", str(dst)],
                               check=True, capture_output=True)
                result = json.loads((dst / "data/signals.json").read_text())
                self.assertEqual(result["regime"], regime)
                self.assertEqual(result["strategy_context"]["new_long_environment"], "unknown")

    def test_benchmark_failure_and_legacy_are_unknown(self):
        for value in ({}, {"bear": False}, {"bear": False, "error": "offline"},
                      unknown_regime("SPY", "offline"), measured_regime("上证指数", None),
                      measured_regime("SPY", [100] * 209),
                      measured_regime("SPY", [100] * 209 + [float("nan")])):
            self.assertEqual(regime_state(value), "unknown")
            self.assertEqual(regime_decision(value)["new_long_environment"], "unknown")
        self.assertIs(unknown_regime("SPY", "offline")["bear"], False)

    def test_regime_three_states_and_incomplete_benchmark(self):
        good = measured_regime("SPY", range(1, 220), bar_complete=True)
        bad = measured_regime("上证指数", range(220, 1, -1), bar_complete=True)
        self.assertEqual(regime_decision(good)["new_long_environment"], "permitted")
        self.assertEqual(regime_decision(bad)["new_long_environment"], "blocked")
        for completion in (None, False):
            provisional = measured_regime("SPY", range(1, 220), bar_complete=completion)
            self.assertEqual(regime_decision(provisional)["new_long_environment"], "unknown")

    def test_real_pipeline_failure_handlers(self):
        # Execute actual function ASTs without importing the scripts' network/main loops.
        for filename, name in (("run2.py", "fetch_regime"), ("run_cn.py", "cn_regime")):
            tree = ast.parse(Path(filename).read_text())
            fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name)
            scope = {"unknown_regime": unknown_regime, "measured_regime": measured_regime, "FRAMES": {}}
            exec(compile(ast.Module(body=[fn], type_ignores=[]), filename, "exec"), scope)
            with patch("builtins.__import__", side_effect=ImportError("offline test")):
                result = scope[name]()
            self.assertEqual(result["status"], "unknown")
            self.assertIn("error", result)

    def test_snapshot_additions_do_not_change_legacy_or_score(self):
        signal = dict(type="ZD_B", kind="pivot_edge", idx=0, price=100, confirmed=True,
                      zg=110, zd=100, dist_pct=0, bars_ago=0)
        before = dict(signal)
        metadata = snapshot_contract(signal, pd.date_range("2025-01-01", periods=1, tz="UTC"))
        self.assertEqual(signal, before)
        self.assertEqual(score_signal(signal, "30m"), score_signal({**signal, **metadata}, "30m"))
        for name in ("first_seen_time", "confirmed_time", "earliest_executable_time", "entry_confirmed", "structure_confirmed"):
            self.assertIsNone(metadata[name])
        self.assertTrue(metadata["touch_confirmed"])
        self.assertIsNone(metadata["extreme_bar_time"])
        self.assertEqual(metadata["bar_time_role"], "touch")
        self.assertEqual(confirmation_contract({"type": "3B", "confirmed": True})["structure_confirmed"], True)

    def test_future_break_removes_old_edge_from_batch(self):
        segs = [Seg(0, 100, 2, 110, True, True), Seg(2, 110, 4, 102, False, True),
                Seg(4, 102, 6, 108, True, True)]
        pivots = [dict(first=0, last=2, zg=108., zd=102., leave=None)]
        close = np.array([105., 105, 105, 105, 105, 105, 102])
        old = find_pivot_edge_signals(segs, pivots, close + .2, close - .2, close)
        self.assertTrue(any(x["type"] == "ZD_B" for x in old))
        new = np.append(close, 98.)
        later = find_pivot_edge_signals(segs, pivots, new + .2, new - .2, new)
        self.assertFalse(any(x["type"] == "ZD_B" for x in later))


class ReplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.df = fixture()
        cls.evidence = dict(available_at=cls.df.index + pd.Timedelta(minutes=30),
                            open_times=cls.df.index, complete=[True] * len(cls.df))
        cls.result = replay(cls.df, **cls.evidence)

    def test_prefix_invariance_and_delayed_recognition(self):
        short = self.df.iloc[:240]
        early = replay(short, available_at=short.index + pd.Timedelta(minutes=30),
                       open_times=short.index, complete=[True] * len(short))
        self.assertEqual(early["snapshots"], self.result["snapshots"][:240])
        seen = [e for e in self.result["events"] if e["event"] == "first_seen"]
        self.assertTrue(any(pd.Timestamp(e["time"]) > pd.Timestamp(e["signal_bar_time"]) + pd.Timedelta(minutes=30) for e in seen))
        first = {e["id"]: e for e in seen}
        for event in self.result["events"]:
            if event["event"] in ("execution_window", "structure_confirmed"):
                self.assertGreaterEqual(pd.Timestamp(event["time"]), pd.Timestamp(first[event["id"]]["time"]))

    def test_repaint_ledger_is_not_erased(self):
        events = self.result["events"]
        gone = [e for e in events if e["event"] == "disappeared"]
        self.assertTrue(gone)
        for removal in gone:
            self.assertTrue(any(e["id"] == removal["id"] and e["event"] == "first_seen" for e in events))
        self.assertTrue(any(e["event"] == "structure_confirmed" for e in events))

    def test_confirmation_rollback_is_auditable(self):
        frame = self.df.iloc[:3]
        base = dict(type="3B", idx=0, price=100., kind="chan", confirmed=True)
        with patch("signal_replay.analyze_level", side_effect=[
                {"signals": [base]}, {"signals": [{**base, "type": "PRE_3B", "confirmed": False}]},
                {"signals": [base]}]):
            result = replay(frame, available_at=frame.index + pd.Timedelta(minutes=30), complete=[True]*3)
        self.assertEqual([e["event"] for e in result["events"]],
                         ["first_seen", "structure_confirmed", "confirmation_revoked", "structure_confirmed"])
        self.assertFalse(result["snapshots"][1]["signals"][0]["structure_confirmed"])
        self.assertEqual(result["snapshots"][0]["signals"][0]["confirmed_time"],
                         result["snapshots"][2]["signals"][0]["confirmed_time"])

    def test_unfinished_last_bar_never_enters_analysis(self):
        frame = self.df.iloc[:60]
        result = replay(frame, available_at=frame.index + pd.Timedelta(minutes=30), complete=[True]*59+[False])
        expected = replay(frame.iloc[:-1], available_at=frame.index[:-1] + pd.Timedelta(minutes=30), complete=[True]*59)
        self.assertEqual(result, expected)
        self.assertTrue(all(s["earliest_executable_time"] is None for snap in result["snapshots"] for s in snap["signals"]))

    def test_missing_prices_or_completion_evidence_fail_closed(self):
        damaged = self.df.copy()
        damaged.iloc[30, 1] = float("nan")
        with self.assertRaises(ValueError):
            replay(damaged, **self.evidence)
        with self.assertRaises(ValueError):
            replay(self.df, **{**self.evidence, "complete": [True]*20+[False]+[True]*339})
        with self.assertRaises(ValueError):
            replay(self.df, **{**self.evidence, "available_at": self.df.index.tz_localize(None)})


if __name__ == "__main__":
    unittest.main()
