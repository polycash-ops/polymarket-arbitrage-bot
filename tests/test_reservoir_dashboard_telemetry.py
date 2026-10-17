from __future__ import annotations
import sys

import importlib
import sys
import types
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch


class FakeResult:
    def __init__(self, row=None, rows=None):
        self.row = row or {}
        self.rows = rows or []

    def fetchone(self):
        return self.row

    def fetchall(self):
        return self.rows


class FakeConnection:
    def __init__(self, *, model_columns=(), verified_count=2, correct_count=1, price_rows=None):
        self.model_columns = set(model_columns)
        self.verified_count = verified_count
        self.correct_count = correct_count
        self.price_rows = list(price_rows or [])
        self.sql = []
        self.params = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, query, params=None):
        self.sql.append(query)
        self.params.append(params)
        if "to_regclass('public.snapshots')" in query:
            return FakeResult(row={"table_name": "snapshots"})
        if "FROM bounded ORDER BY captured_at ASC" in query:
            return FakeResult(rows=self.price_rows)
        if "to_regclass('public.biological_reservoir_model_state')" in query:
            return FakeResult(row={"model_table": "biological_reservoir_model_state",
                                   "obs_table": "biological_reservoir_observations"})
        if "to_regclass('public.biological_reservoir_observations')" in query:
            return FakeResult(row={"obs_table": "biological_reservoir_observations"})
        if "information_schema.columns" in query:
            return FakeResult(rows=[{"column_name": name} for name in self.model_columns])
        if "FROM biological_reservoir_model_state WHERE id=1" in query:
            return FakeResult(row={
                "model_version": 2, "graph_snapshot": "test", "graph_hash": "abc",
                "node_count": 3, "edge_count": 2, "learning_updates": 0,
                "last_snapshot_id": 1, "last_expansion_at": None,
                "updated_at": datetime.now(timezone.utc),
                "worker_heartbeat_at": None, "source_snapshot_at": None,
            })
        if "count(DISTINCT market_slug) AS verified" in query:
            return FakeResult(row={"verified": self.verified_count, "last_verified_at": None})
        if "WITH verified_outcomes AS" in query:
            return FakeResult(rows=[
                {"market_slug": "contract-a", "outcome": "UP", "settlement_source": "verified"},
                {"market_slug": "contract-b", "outcome": "DOWN", "settlement_source": "verified"},
            ])
        if "WITH ranked AS" in query:
            return FakeResult(rows=[{"market_slug": "contract-a", "history_rank": 1,
                                     "forecast_direction": "UP", "outcome": None,
                                     "outcome_verified": False}])
        if "AS total" in query and "biological_reservoir_observations" in query:
            return FakeResult(row={"total": 4, "latest_at": datetime.now(timezone.utc),
                                   "latest_snapshot_id": 4, "settled_directional": 0,
                                   "correct_directional": 0, "brier_score": None,
                                   "learning_updates": 0})
        if "AS score" in query:
            return FakeResult(row={"score": None})
        if "FROM biological_reservoir_observations" in query:
            return FakeResult(rows=[])
        return FakeResult()


class ReservoirDashboardTelemetryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # dashboard.py imports TradingBot for unrelated routes; keep this test
        # focused on the Reservoir API and independent of bot startup side effects.
        main_stub = types.ModuleType("main")
        main_stub.TradingBot = object
        cls.main_patch = patch.dict(sys.modules, {"main": main_stub})
        cls.main_patch.start()
        import dashboard
        cls.dashboard = importlib.reload(dashboard)

    @classmethod
    def tearDownClass(cls):
        cls.main_patch.stop()

    def test_missing_telemetry_columns_are_explicit_not_inferred(self):
        conn = FakeConnection(model_columns={"model_version", "updated_at"})
        with patch.dict("os.environ", {"CONNECTOME_DATABASE_URL": "postgresql://test"}), \
             patch("psycopg.connect", return_value=conn):
            response = self.dashboard.app.test_client().get("/api/biological-reservoir")
        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertEqual(body["status"], "TELEMETRY SCHEMA INCOMPLETE")
        self.assertEqual(body["freshness"]["worker_heartbeat"]["status"], "UNAVAILABLE")
        self.assertEqual(body["freshness"]["source_snapshot"]["status"], "UNAVAILABLE")
        self.assertNotEqual(body["freshness"]["worker_heartbeat"]["timestamp"], body["model"]["updated_at"])
        self.assertTrue(any("information_schema.columns" in query for query in conn.sql))

    def test_contract_price_series_is_exact_slug_bounded_and_timestamped(self):
        slug = "cpc-btc-updown-15m-2026-10-17-1945z"
        now = datetime.now(timezone.utc)
        start = now - timedelta(minutes=2)
        end = start + timedelta(minutes=15)
        conn = FakeConnection(price_rows=[
            {"market_slug": slug, "captured_at": start + timedelta(minutes=1),
             "midpoint": 0.48, "window_start": start, "window_end": end},
            {"market_slug": slug, "captured_at": start + timedelta(minutes=2),
             "midpoint": 0.51, "window_start": start, "window_end": end},
        ])
        with patch.dict("os.environ", {"CONNECTOME_DATABASE_URL": "postgresql://test"}), \
             patch("psycopg.connect", return_value=conn):
            response = self.dashboard.app.test_client().get(
                "/api/contract-price-series?market_slug=" + slug
            )
        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertEqual(body["status"], "AVAILABLE")
        self.assertEqual(body["contract_identity"], slug)
        self.assertEqual(body["point_count"], 2)
        self.assertEqual(conn.params[-1], (slug,))
        self.assertIn("LIMIT 500", conn.sql[-1])
        self.assertIn("ORDER BY captured_at DESC, id DESC", conn.sql[-1])
        self.assertIn("ORDER BY captured_at ASC, id ASC", conn.sql[-1])
        self.assertNotIn(slug, conn.sql[-1])  # slug is passed as a SQL parameter

    def test_contract_price_series_hides_database_exception_details(self):
        slug = "cpc-btc-updown-15m-2026-10-17-1945z"
        secret_like_error = "postgresql://user:pass@db.example/private-db connection refused"
        with patch.dict("os.environ", {"CONNECTOME_DATABASE_URL": "postgresql://test"}), \
             patch("psycopg.connect", side_effect=RuntimeError(secret_like_error)):
            response = self.dashboard.app.test_client().get(
                "/api/contract-price-series?market_slug=" + slug
            )
        self.assertEqual(response.status_code, 500)
        body = response.get_json()
        self.assertEqual(body["status"], "UNAVAILABLE_QUERY_ERROR")
        self.assertNotIn("user:pass", body["message"])
        self.assertNotIn("db.example", body["message"])
        self.assertEqual(body["message"], "Price history is temporarily unavailable; server-side query failed.")

    def test_contract_price_series_rejects_invalid_slug_before_database_access(self):
        response = self.dashboard.app.test_client().get(
            "/api/contract-price-series?market_slug=bad%20slug"
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["status"], "UNAVAILABLE_INVALID_REQUEST")

    def test_accuracy_is_unavailable_until_contract_scoring_policy_is_approved(self):
        conn = FakeConnection(verified_count=2, correct_count=1)
        with patch.dict("os.environ", {"CONNECTOME_DATABASE_URL": "postgresql://test"}), \
             patch("psycopg.connect", return_value=conn):
            response = self.dashboard.app.test_client().get("/api/verified-contracts")
        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertEqual(body["metrics"]["verified"], 2)
        self.assertIsNone(body["metrics"]["accuracy_pct"])
        self.assertEqual(body["metrics"]["accuracy_status"], "UNAVAILABLE_POLICY_PENDING")
        self.assertEqual(body["scoring_policy"], {
            "status": "UNAPPROVED", "unit": None, "forecast_selection": None
        })
        self.assertIn("require approval", body["metrics"]["accuracy_denominator"])
        # Verified outcomes are independent of forecast selection and contain no score fields.
        self.assertEqual([row["outcome"] for row in body["contracts"]], ["UP", "DOWN"])
        self.assertNotIn("forecast_direction", body["contracts"][0])
        self.assertNotIn("correct", body["contracts"][0])
        self.assertNotIn("brier_score", body["contracts"][0])
        outcome_query = next(query for query in conn.sql if "WITH verified_outcomes AS" in query)
        self.assertIn("outcome_verified", outcome_query)
        self.assertNotIn("checkpoint='5m_remaining'", outcome_query)

    def test_signal_history_is_partitioned_by_contract_and_excludes_fixtures(self):
        conn = FakeConnection()
        with patch.dict("os.environ", {"CONNECTOME_DATABASE_URL": "postgresql://test"}), \
             patch("psycopg.connect", return_value=conn):
            response = self.dashboard.app.test_client().get("/api/reservoir-signal-history")
        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertEqual(body["history_per_contract"], 5)
        query = next(query for query in conn.sql if "WITH ranked AS" in query)
        self.assertIn("PARTITION BY market_slug", query)
        self.assertIn("history_rank <= 5", query)
        self.assertIn("fixture_key", query)
        self.assertIn("outcome_verified", query)


if __name__ == "__main__":
    unittest.main()
