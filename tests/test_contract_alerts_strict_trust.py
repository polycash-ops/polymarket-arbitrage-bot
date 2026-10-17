"""Regression tests for trust boundaries in contract alert selection/scoring."""
from datetime import datetime, timedelta, timezone
import sys
from pathlib import Path
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import reservoir_consumer as rc


class StrictTrustRegressionTests(unittest.TestCase):
    def setUp(self):
        self.t = datetime(2026, 10, 17, 15, 0, tzinfo=timezone.utc)
        self.start = self.t
        self.end = self.t + timedelta(minutes=15)
        self.issued = self.t + timedelta(minutes=3)
        self.base_env = patch.dict("os.environ", {
            "ISSUANCE_SEMANTICS_TRUSTED": "true",
            "ALERT_SEQUENCE_ORDERING_TRUSTED": "",
            "OUTCOME_PROVENANCE_TRUSTED": "",
            "RESERVOIR_SCORING_POLICY_APPROVED": "",
        }, clear=False)
        self.base_env.start()
        self.addCleanup(self.base_env.stop)

    def alert_rows(self):
        return [
            {"market_slug": "c", "forecast_direction": "UP", "issued_at": self.issued,
             "alert_sequence": 1, "snapshot_id": 1},
            {"market_slug": "c", "forecast_direction": "DOWN", "issued_at": self.issued,
             "alert_sequence": 2, "snapshot_id": 2},
        ]

    def test_global_issuance_trust_requires_explicit_true_literal(self):
        for value in ("", "1", "yes", "false", "enabled"):
            with self.subTest(value=value), patch.dict("os.environ", {"ISSUANCE_SEMANTICS_TRUSTED": value}):
                self.assertFalse(rc.issuance_semantics_trusted())
        with patch.dict("os.environ", {"ISSUANCE_SEMANTICS_TRUSTED": " TRUE "}):
            self.assertTrue(rc.issuance_semantics_trusted())

    def test_sequence_presence_does_not_establish_order(self):
        result = rc.select_active_up_down_alert(
            self.alert_rows(), "c", self.t + timedelta(minutes=5),
            contract_start=self.start, contract_end=self.end,
        )
        self.assertEqual(result["status"], "AMBIGUOUS_ALERT")
        self.assertFalse(result["sequence_ordering_trusted"])

    def test_documented_sequence_trust_resolves_active_latest_but_not_by_presence_alone(self):
        with patch.dict("os.environ", {"ALERT_SEQUENCE_ORDERING_TRUSTED": "true"}):
            result = rc.select_active_up_down_alert(
                self.alert_rows(), "c", self.t + timedelta(minutes=5),
                contract_start=self.start, contract_end=self.end,
            )
        self.assertEqual(result["status"], "ACTIVE")
        self.assertEqual(result["alert"]["direction"], "DOWN")

    def test_active_alert_requires_aware_exact_15_minute_boundaries(self):
        rows = [{"market_slug": "c", "forecast_direction": "UP",
                 "issued_at": self.issued}]
        for start, end in [
            (None, self.end),
            (self.start.replace(tzinfo=None), self.end),
            (self.start, self.start),
            (self.start, self.start + timedelta(hours=1)),
        ]:
            result = rc.select_active_up_down_alert(
                rows, "c", self.t + timedelta(minutes=5),
                contract_start=start, contract_end=end, trust_issuance=True,
            )
            self.assertEqual(result["status"], "UNAVAILABLE")

    def test_issuance_timestamp_must_be_timezone_aware(self):
        naive = self.issued.replace(tzinfo=None)
        self.assertIsNone(rc.parse_aware_timestamp(naive))
        self.assertIsNone(rc.parse_aware_timestamp("2026-10-17T15:03:00"))
        rows = [{"market_slug": "c", "forecast_direction": "UP", "issued_at": naive}]
        result = rc.select_active_up_down_alert(
            rows, "c", self.t + timedelta(minutes=5),
            contract_start=self.start, contract_end=self.end, trust_issuance=True,
        )
        self.assertEqual(result["status"], "NO_ACTIVE_ALERT")

    def test_trust_override_requires_actual_boolean(self):
        with self.assertRaises(TypeError):
            rc.select_active_up_down_alert(
                self.alert_rows(), "c", self.t + timedelta(minutes=5),
                contract_start=self.start, contract_end=self.end,
                trust_issuance="false",
            )
        with self.assertRaises(TypeError):
            rc.compute_rolling_accuracy([], self.t, policy_approved="true")

    def test_payload_verification_and_source_presence_do_not_enable_global_provenance(self):
        row = {
            "market_slug": "c", "forecast_direction": "UP", "issued_at": self.issued,
            "outcome": "UP", "outcome_verified": True,
            "settlement_source": "anything", "settled_at": self.end + timedelta(minutes=1),
            "contract_start": self.start, "contract_end": self.end,
        }
        result = rc.compute_rolling_accuracy(
            [row], self.end + timedelta(hours=1),
            policy_approved=True, trust_issuance=True,
        )
        self.assertEqual(result["status"], "UNAVAILABLE_OUTCOME_PROVENANCE_PENDING")
        self.assertIsNone(result["accuracy_pct"])
        self.assertFalse(result["outcome_provenance_trusted"])

    def test_scoring_rejects_naive_or_wrong_duration_boundaries_after_trust(self):
        row = {
            "market_slug": "c", "forecast_direction": "UP", "issued_at": self.issued,
            "outcome": "UP", "outcome_verified": True,
            "settlement_source": "worker", "settled_at": self.end + timedelta(minutes=1),
            "contract_start": self.start, "contract_end": self.end,
        }
        with patch.dict("os.environ", {"OUTCOME_PROVENANCE_TRUSTED": "true"}):
            row["contract_start"] = self.start.replace(tzinfo=None)
            result = rc.compute_rolling_accuracy(
                [row], self.end + timedelta(hours=1),
                policy_approved=True, trust_issuance=True,
            )
        self.assertEqual(result["status"], "UNAVAILABLE_NO_SCORED")
        self.assertIn("missing_or_invalid_contract_boundaries", result["exclusion_reasons"])

    def test_first_scored_and_latest_active_use_distinct_sequence_rules(self):
        rows = [
            {"market_slug": "c", "forecast_direction": "UP", "issued_at": self.issued,
             "alert_sequence": 1, "snapshot_id": 1, "outcome": "UP", "outcome_verified": True,
             "settlement_source": "worker", "settled_at": self.end + timedelta(minutes=1),
             "contract_start": self.start, "contract_end": self.end},
            {"market_slug": "c", "forecast_direction": "DOWN", "issued_at": self.issued,
             "alert_sequence": 2, "snapshot_id": 2, "outcome": "UP", "outcome_verified": True,
             "settlement_source": "worker", "settled_at": self.end + timedelta(minutes=1),
             "contract_start": self.start, "contract_end": self.end},
        ]
        with patch.dict("os.environ", {
            "ALERT_SEQUENCE_ORDERING_TRUSTED": "true",
            "OUTCOME_PROVENANCE_TRUSTED": "true",
        }):
            scored = rc.compute_rolling_accuracy(
                rows, self.end + timedelta(hours=1),
                policy_approved=True, trust_issuance=True,
            )
            active = rc.select_active_up_down_alert(
                rows, "c", self.end - timedelta(seconds=1),
                contract_start=self.start, contract_end=self.end, trust_issuance=True,
            )
        self.assertEqual(scored["status"], "SCORED")
        self.assertEqual(scored["scored_contracts"][0]["prediction"], "UP")
        self.assertEqual(active["status"], "ACTIVE")
        self.assertEqual(active["alert"]["direction"], "DOWN")


if __name__ == "__main__":
    unittest.main()
