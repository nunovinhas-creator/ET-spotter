"""Testes para FX com proveniência e separação temporal XGBoost."""
import json
import math
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import research_fx
from research_walkforward import split_with_label_purge


class FXTests(unittest.TestCase):
    def setUp(self):
        self.dates = pd.bdate_range("2025-05-05", periods=7)
        self.bars = pd.DataFrame({"open": 100., "high": 102.,
                                  "low": 98., "close": 101.}, index=self.dates)
        self.fx = pd.DataFrame({"open": 1.1, "high": 1.12,
                                "low": 1.08, "close": 1.1}, index=self.dates)

    def test_usd_to_eur(self):
        v = research_fx.to_eur(self.bars, "USD", self.fx)
        self.assertAlmostEqual(v["open"].iloc[0], 100 / 1.1)
        self.assertAlmostEqual(v["close"].iloc[0], 101 / 1.1)

    def test_gbpence_not_same_as_gbp(self):
        rate = self.fx.copy()
        rate.loc[:, :] = .80
        for alias in ("GBp", "GBX", "GBpence"):
            v = research_fx.to_eur(self.bars, alias, rate)
            self.assertAlmostEqual(v["open"].iloc[0], 1.25)
        gbp = research_fx.to_eur(self.bars, "GBP", rate)
        self.assertAlmostEqual(gbp["open"].iloc[0], 125)

    def test_missing_early_fx_fails(self):
        with self.assertRaises(ValueError):
            research_fx.to_eur(self.bars, "USD", self.fx.iloc[1:])

    def test_old_quote_fails(self):
        stale_fx = self.fx.iloc[:1]
        with self.assertRaises(ValueError):
            research_fx.to_eur(self.bars, "USD", stale_fx)

    def test_unidentified_currency_does_not_guess_lse(self):
        with self.assertRaises(ValueError):
            research_fx.normalize_currency("")
        with self.assertRaises(ValueError):
            research_fx.normalize_currency("LSE")
        with tempfile.TemporaryDirectory() as p:
            with self.assertRaises(FileNotFoundError):
                research_fx.convert_folder(Path(p), ["CSPX.L"])


class PurgeTests(unittest.TestCase):
    def test_purge_removes_december_labels_finishing_in_january(self):
        dates = pd.bdate_range("2025-11-01", periods=100)
        df = pd.DataFrame({"date": dates, "label_end": dates + pd.offsets.BDay(21)})
        border = pd.Timestamp("2026-01-02")
        train, test = split_with_label_purge(df, border, pd.Timestamp("2026-02-01"))
        self.assertTrue((train.label_end < border).all())
        self.assertTrue((test.date >= border).all())
        self.assertLess(train.date.max(), border - pd.offsets.BDay(20))
        self.assertEqual(len(set(train.index) & set(test.index)), 0)

    def test_empty_test_is_allowed(self):
        day = pd.Timestamp("2025-05-01")
        df = pd.DataFrame({"date": [day], "label_end": [day + pd.Timedelta(days=30)]})
        train, test = split_with_label_purge(df, pd.Timestamp("2027-01-01"),
                                             pd.Timestamp("2027-02-01"))
        self.assertEqual(len(test), 0)


class UserInterfaceTests(unittest.TestCase):
    def test_research_panel_in_nav_and_generator(self):
        root = Path(__file__).resolve().parents[1]
        html = (root / "docs/index.html").read_text(encoding="utf-8")
        py = (root / "scripts/generate_dashboard.py").read_text(encoding="utf-8")
        for value in ("switchTab('research',this)", 'id="tab-research"',
                      "EXPERIMENTAL", "39964452566"):
            self.assertIn(value, html)
        self.assertIn("research-panel.html", py)
        self.assertIn("['overview','signals','reports','simulation','research','guides']", py)
        for lang in ("pt", "en"):
            d = json.loads((root / f"docs/i18n/{lang}.json").read_text(encoding="utf-8"))
            self.assertIn("research", d["nav"])


if __name__ == "__main__":
    unittest.main()
