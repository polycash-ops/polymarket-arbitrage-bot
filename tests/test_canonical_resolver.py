import unittest
from datetime import datetime, timezone, timedelta

from canonical_resolver import resolve_price_to_beat, unavailable_price_to_beat


class CanonicalResolverTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 18, 12, 0, tzinfo=timezone.utc)
        self.payload = {
            "contract_id": "us-contract-123",
            "source": "polymarket_us_official",
            "provenance_verified": True,
            "price_to_beat": 67234.5,
            "observed_at": (self.now - timedelta(seconds=5)).isoformat(),
            "contract_start_at": (self.now - timedelta(seconds=10)).isoformat(),
            "contract_end_at": (self.now + timedelta(minutes=15)).isoformat(),
        }

    def test_default_state_is_explicitly_unavailable(self):
        state = unavailable_price_to_beat()
        self.assertEqual(state["status"], "unavailable")
        self.assertIsNone(state["price_to_beat"])
        self.assertIsNone(state["contract_id"])
        self.assertIn("trusted Polymarket US", state["reason"])

    def test_accepts_only_fresh_verified_matching_us_contract(self):
        state = resolve_price_to_beat(self.payload, expected_contract_id="us-contract-123", now=self.now)
        self.assertEqual(state["status"], "verified")
        self.assertEqual(state["price_to_beat"], 67234.5)

    def test_rejects_exchange_or_international_source(self):
        for source in ("BINANCE", "COINBASE", "polymarket_gamma", "polymarket_clob"):
            with self.subTest(source=source):
                state = resolve_price_to_beat({**self.payload, "source": source}, expected_contract_id="us-contract-123", now=self.now)
                self.assertEqual(state["status"], "unavailable")
                self.assertIsNone(state["price_to_beat"])

    def test_rejects_unverified_or_mismatched_contract(self):
        for payload, expected in (({**self.payload, "provenance_verified": False}, "us-contract-123"), (self.payload, "different-contract"), (self.payload, None)):
            state = resolve_price_to_beat(payload, expected_contract_id=expected, now=self.now)
            self.assertEqual(state["status"], "unavailable")
            self.assertIsNone(state["price_to_beat"])

    def test_rejects_invalid_price_and_timestamp(self):
        for price in (None, 0, -1, float("nan"), float("inf"), "not-a-price"):
            with self.subTest(price=price):
                state = resolve_price_to_beat({**self.payload, "price_to_beat": price}, expected_contract_id="us-contract-123", now=self.now)
                self.assertEqual(state["status"], "unavailable")
        state = resolve_price_to_beat({**self.payload, "observed_at": "not-a-time"}, expected_contract_id="us-contract-123", now=self.now)
        self.assertEqual(state["status"], "unavailable")

    def test_fixed_target_remains_valid_during_its_active_contract(self):
        later = self.now + timedelta(minutes=14)
        state = resolve_price_to_beat(self.payload, expected_contract_id="us-contract-123", now=later)
        self.assertEqual(state["status"], "verified")
        self.assertEqual(state["price_to_beat"], 67234.5)

    def test_rejects_late_future_naive_and_expired_lifecycle_timestamps(self):
        bad_payloads = (
            {**self.payload, "observed_at": (self.now + timedelta(seconds=3)).isoformat()},
            {**self.payload, "observed_at": "2026-10-18T11:59:00"},
            {**self.payload, "observed_at": (self.now + timedelta(minutes=2)).isoformat()},
            {**self.payload, "contract_end_at": (self.now - timedelta(seconds=1)).isoformat()},
        )
        for payload in bad_payloads:
            with self.subTest(payload=payload):
                state = resolve_price_to_beat(payload, expected_contract_id="us-contract-123", now=self.now)
                self.assertEqual(state["status"], "unavailable")


if __name__ == "__main__":
    unittest.main()
