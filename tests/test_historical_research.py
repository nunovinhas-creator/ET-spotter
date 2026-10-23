"""Testes offline do motor de investigação; não usam Yahoo nem alteram produção."""
import math
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import historical_research as hr


class HistoricalResearchTests(unittest.TestCase):
    def test_metrics_identical_strategy_and_benchmark(self):
        idx = pd.bdate_range("2021-01-01", periods=80)
        nav = pd.Series(10000 * (1.0005 ** np.arange(len(idx))), index=idx)
        result = hr.calculate_metrics(nav, nav.copy())
        self.assertAlmostEqual(result["active_cagr_pp"], 0.0, places=9)
        self.assertAlmostEqual(result["strategy"]["max_drawdown"], 0.0)

    def test_past_snapshot_ignores_future(self):
        idx = pd.bdate_range("2020-01-01", periods=280)
        df = pd.DataFrame({"vol_21": .2, "ret_21d": np.arange(280)}, index=idx)
        snap = hr.snapshot_at(idx[252], {"A": df})
        self.assertEqual(snap.iloc[0]["ret_21d"], 252)
        self.assertEqual(len(hr.snapshot_at(idx[251], {"A": df})), 0)

    def test_next_open_and_one_way_transaction_cost(self):
        idx = pd.bdate_range("2021-01-04", periods=280)
        entry_start = 210
        with tempfile.TemporaryDirectory() as d:
            folder = Path(d)
            base = np.full(len(idx), 100.0)
            asset = base.copy()
            asset[entry_start+2:] = 200.0  # salto APÓS compra na abertura da 2.ª sessão
            for ticker, opens in (("SPY", base), ("VWCE.DE", base), ("A", asset)):
                pd.DataFrame({"Date": idx, "open": opens, "high": opens,
                              "low": opens, "close": opens, "volume": 100}).to_csv(
                                  folder / f"{ticker}.csv", index=False)
            with patch.object(hr, "_load_etf_metadata", return_value={
                    "A": {"category_id": "a", "category_cap": 1.0}}), \
                 patch.object(hr, "construct_weights",
                              return_value=({"A": 1.0}, {"status": "selected"})), \
                 patch.object(hr, "classify_regime", return_value="BULL"):
                curve, result = hr.backtest(folder, str(idx[entry_start].date()),
                                            str(idx[-1].date()), 15.0)
            self.assertEqual(curve.iloc[0]["equity"], 10000.0)
            self.assertAlmostEqual(curve.iloc[1]["cost"], 15.0)
            self.assertAlmostEqual(curve.iloc[1]["equity"], 9985.0)
            self.assertAlmostEqual(curve.iloc[2]["equity"], 19970.0)
            self.assertEqual(result["rebalance_count"], 1)

    def test_invalid_costs_rejected(self):
        with self.assertRaises(ValueError):
            hr.backtest(Path("."), "2022-01-01", "2022-12-01", -1)


if __name__ == "__main__":
    unittest.main()
