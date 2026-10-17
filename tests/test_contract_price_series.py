"""Pure validation tests for real timestamped exact-contract price-series data."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import reservoir_consumer as rc


class ContractPriceSeriesTests(unittest.TestCase):
    def setUp(self):
        self.start = datetime(2026, 10, 17, 19, 45, tzinfo=timezone.utc)
        self.end = self.start + timedelta(minutes=15)
        self.now = self.start + timedelta(minutes=3, seconds=1)
        self.slug = "cpc-btc-updown-15m-2026-10-17-1945z"

    def rows(self):
        return [
            {"market_slug": self.slug, "captured_at": self.start + timedelta(minutes=i),
             "midpoint": 0.45 + i / 100, "window_start": self.start, "window_end": self.end}
            for i in (1, 2, 3)
        ]

    def test_returns_exact_contract_timestamped_midpoints(self):
        result = rc.normalize_contract_price_series(self.rows(), self.slug, self.now)
        self.assertEqual(result["status"], "AVAILABLE")
        self.assertEqual(result["point_count"], 3)
        self.assertTrue(all(p["captured_at"].endswith("+00:00") for p in result["points"]))

    def test_rollover_identity_excludes_prior_contract_points(self):
        other = dict(self.rows()[0], market_slug="cpc-btc-updown-15m-2026-10-17-1930z")
        result = rc.normalize_contract_price_series(self.rows() + [other], self.slug, self.now)
        self.assertEqual(result["point_count"], 3)
        self.assertTrue(all(p["midpoint"] != 0.46 or p["captured_at"] == (self.start + timedelta(minutes=1)).isoformat() for p in result["points"]))

    def test_stale_series_is_not_labelled_available(self):
        result = rc.normalize_contract_price_series(self.rows(), self.slug, self.end + timedelta(hours=1))
        self.assertEqual(result["status"], "STALE")
        self.assertEqual(result["point_count"], 3)

    def test_naive_timestamp_wrong_duration_and_out_of_range_midpoint_are_rejected(self):
        rows = self.rows()
        rows[0]["captured_at"] = "2026-10-17T19:46:00"
        rows[1]["window_end"] = self.start + timedelta(hours=1)
        rows[2]["midpoint"] = 1.2
        result = rc.normalize_contract_price_series(rows, self.slug, self.now)
        self.assertEqual(result["status"], "UNAVAILABLE_NO_SERIES")
        self.assertEqual(result["point_count"], 0)


if __name__ == "__main__":
    unittest.main()
