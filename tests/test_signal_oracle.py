import tempfile
import unittest
from pathlib import Path
from bot.signal_oracle import (OracleConfig, OracleTestStore, decide, encode_features,
                               signal_id, SETTLEMENT_SOURCE)

class OracleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = OracleTestStore(str(Path(self.tmp.name) / "oracle.sqlite3"))
    def tearDown(self):
        self.tmp.cleanup()
    def pred(self, action="UP", contract="us-verified-1", start="2026-10-18T12:00:00Z"):
        return {"contract_id":contract,"window_start":start,"window_end":"2026-10-18T12:15:00Z",
          "issued_at":"2026-10-18T12:05:00Z","action":action,"score":.7,"features":[0]*8,
          "provenance":{"source":"fixture","verified_contract":True},"reason":"fixture"}
    def test_defaults_disabled_and_paper_only(self):
        self.assertFalse(OracleConfig().enabled)
        with self.assertRaises(ValueError): OracleConfig(paper_only=False)
    def test_decision_is_deterministic(self):
        self.assertEqual(decide([1]*8, [0,1,0,0,0,0,0,0,0])["action"], "UP")
        self.assertEqual(decide([0]*8)["action"], "NO TRADE")
    def test_repeat_poll_keeps_first_prediction(self):
        first=self.store.record(self.pred("UP"))
        second=self.store.record(self.pred("DOWN"))
        self.assertEqual(first["prediction_id"], second["prediction_id"])
        self.assertEqual(second["action"], "UP")
    def test_settlement_authority_and_dedup(self):
        row=self.store.record(self.pred())
        with self.assertRaises(ValueError):
            self.store.settle(row["prediction_id"], "UP", "polymarket_gamma", "2026-10-18T12:16:00Z", "e1")
        self.assertTrue(self.store.settle(row["prediction_id"], "UP", SETTLEMENT_SOURCE, "2026-10-18T12:16:00Z", "e1"))
        self.assertFalse(self.store.settle(row["prediction_id"], "UP", SETTLEMENT_SOURCE, "2026-10-18T12:16:01Z", "e1"))
        self.assertEqual(self.store.metrics()["lifetime_accuracy_pct"], 100.0)
    def test_empty_metrics_are_na(self):
        m=self.store.metrics()
        self.assertIsNone(m["rolling_accuracy_pct"])
        self.assertIsNone(m["lifetime_accuracy_pct"])
        self.assertEqual(m["lifetime_count"], 0)
        self.store.record(self.pred())
        self.assertEqual(self.store.metrics()["pending_count"], 1)
    def test_features_are_bounded(self):
        x=encode_features([{"probability_up":.8,"confidence":.7,"direction":"UP"}],
                          {"midpoint":.6,"depth_imbalance":2,"short_momentum":.1})
        self.assertEqual(len(x),8)
        self.assertTrue(all(-1 <= v <= 1 for v in x))
    def test_id_stable(self):
        self.assertEqual(signal_id("c","w"),signal_id("c","w"))

if __name__ == "__main__": unittest.main()
