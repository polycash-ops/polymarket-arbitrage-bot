from __future__ import annotations

import importlib
import sys
import types
import unittest
from datetime import datetime, timezone
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
    def __init__(self, *, model_columns=(), verified_count=2, correct_count=1):
        self.model_columns = set(model_columns)
        self.verified_count = verified_count
        self.correct_count = correct_count
        self.sql = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, query, params=None):
        self.sql.append(query)
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
        if "WITH selected AS" in query and "AS verified" in query:
            return FakeResult(row={"verified": self.verified_count, "correct": self.correct_count,
                                   "mean_brier": 0.2, "last_verified_at": None})
        if "WITH selected AS" in query and "AS correct" in query:
            return FakeResult(rows=[{"market_slug": "contract-a"}, {"market_slug": "contract-b"}])
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

    def test_verified_accuracy_uses_unique_contract_denominator(self):
        conn = FakeConnection(verified_count=2, correct_count=1)
        with patch.dict("os.environ", {"CONNECTOME_DATABASE_URL": "postgresql://test"}), \
             patch("psycopg.connect", return_value=conn):
            response = self.dashboard.app.test_client().get("/api/verified-contracts")
        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertEqual(body["metrics"]["verified"], 2)
        self.assertEqual(body["metrics"]["correct"], 1)
        self.assertEqual(body["metrics"]["accuracy_pct"], 50.0)
        self.assertIn("unique verified contracts", body["metrics"]["accuracy_denominator"])
        selection = next(query for query in conn.sql if "WITH selected AS" in query)
        self.assertIn("DISTINCT ON (market_slug)", selection)
        self.assertIn("captured_at ASC, snapshot_id ASC", selection)
        self.assertIn("checkpoint='5m_remaining'", selection)
        self.assertIn("outcome_verified", selection)

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
