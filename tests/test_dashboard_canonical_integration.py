"""Endpoint fixtures for the canonical resolver patch; requires repo deps and patched dashboard.py."""
from __future__ import annotations
import importlib
import os
import sys
import types
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from canonical_resolver import select_canonical_open_contract

UTC = timezone.utc
START = datetime(2026, 10, 17, 21, 15, tzinfo=UTC)
END = START + timedelta(minutes=15)
NOW = START + timedelta(minutes=8)
SLUG = "cpc-btc-updown-15m-2026-10-17-2115z"


def canonical_row(**overrides):
    row = {
        "market_slug": SLUG, "market_id": "1517399", "timeframe": "15m",
        "title": "BTC Up or Down 15m", "active": True,
        "window_start": START, "window_end": END,
        "metadata": {
            "marketType": "ASSET_PRICE_MARKET_TYPE_UP_DOWN",
            "assetPriceTerms": {
                "asset": {"symbol": "BTC"}, "horizon": "15m",
                "windowStart": START.isoformat(), "windowEnd": END.isoformat(),
            },
            "endDate": "2026-10-17T22:00:00Z",
        },
    }
    row.update(overrides)
    return row


class Cursor:
    def __init__(self, rows=None, one=None):
        self.rows = list(rows or [])
        self.one = one
    def fetchall(self): return self.rows
    def fetchone(self): return self.one if self.one is not None else (self.rows[0] if self.rows else None)


class FakeConnection:
    def __init__(self, canonical=None, snapshots=None, observations=None, fail=False):
        self.canonical = list(canonical if canonical is not None else [canonical_row()])
        self.snapshots = list(snapshots if snapshots is not None else [])
        self.observations = list(observations if observations is not None else [])
        self.fail = fail
        self.calls = []
    def __enter__(self): return self
    def __exit__(self, *_): return False
    def execute(self, sql, params=None):
        self.calls.append((sql, params))
        if self.fail:
            raise RuntimeError("FAKE_SECRET postgresql://private:password@host/db")
        if "SELECT to_regclass('public.snapshots')" in sql:
            return Cursor(one={"table_name": "public.snapshots"})
        if "FROM public.market_contracts" in sql:
            return Cursor(rows=self.canonical)
        if "FROM public.snapshots" in sql:
            return Cursor(rows=self.snapshots)
        if "FROM biological_reservoir_observations" in sql:
            return Cursor(rows=self.observations)
        raise AssertionError("Unexpected SQL in fixture: " + sql[:100])


class DashboardCanonicalIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.saved_dashboard = sys.modules.pop("dashboard", None)
        cls.saved_main = sys.modules.get("main")
        stub = types.ModuleType("main")
        stub.TradingBot = object
        sys.modules["main"] = stub
        try:
            cls.dashboard = importlib.import_module("dashboard")
        except Exception:
            sys.modules.pop("dashboard", None)
            if cls.saved_main is None: sys.modules.pop("main", None)
            else: sys.modules["main"] = cls.saved_main
            raise

    @classmethod
    def tearDownClass(cls):
        sys.modules.pop("dashboard", None)
        if cls.saved_dashboard is not None: sys.modules["dashboard"] = cls.saved_dashboard
        if cls.saved_main is None: sys.modules.pop("main", None)
        else: sys.modules["main"] = cls.saved_main

    def client(self, connection, **env):
        self.env = patch.dict(os.environ, {"CONNECTOME_DATABASE_URL": "postgresql://fixture",
                                           "RESERVOIR_SCORING_POLICY_APPROVED": "false",
                                           "ISSUANCE_SEMANTICS_TRUSTED": "false", **env})
        self.env.start()
        self.addCleanup(self.env.stop)
        import psycopg
        self.connect_patch = patch("psycopg.connect", return_value=connection)
        self.connect_patch.start()
        self.addCleanup(self.connect_patch.stop)
        return self.dashboard.app.test_client()

    def get(self, client, path):
        return client.get(path, headers={"X-Evaluation-Time": NOW.isoformat()})

    def test_fresh_canonical_prices_without_observations_and_policy_pending(self):
        points = [
            {"market_slug": SLUG, "captured_at": START + timedelta(minutes=i), "midpoint": 0.45+i/100,
             "window_start": START, "window_end": END, "id": i}
            for i in (6, 7, 8)
        ]
        conn = FakeConnection(snapshots=points, observations=[])
        client = self.client(conn)
        contract = self.get(client, "/api/current-contract").get_json()
        canonical_query = next(q for q in conn.calls if "FROM public.market_contracts" in q[0])
        self.assertEqual(canonical_query[1], ("15m", NOW, NOW))
        self.assertIn("window_end - window_start = INTERVAL '15 minutes'", canonical_query[0])
        self.assertFalse(any("FROM biological_reservoir_observations" in q[0] for q in conn.calls),
                         "canonical contract discovery must not depend on Reservoir observations")
        series = self.get(client, "/api/contract-price-series?market_slug="+SLUG).get_json()
        alert = self.get(client, "/api/active-alert").get_json()
        accuracy = self.get(client, "/api/rolling-accuracy").get_json()
        self.assertEqual(contract["status"], "OPEN")
        self.assertEqual(series["status"], "AVAILABLE")
        self.assertEqual(series["contract_identity"], SLUG)
        self.assertNotEqual(alert.get("status"), "ACTIVE")
        self.assertIn("UNAVAILABLE", accuracy.get("status", "UNAVAILABLE"))

    def test_previous_window_observations_do_not_attach_to_current_alert(self):
        conn = FakeConnection(observations=[{
            "snapshot_id": 1, "market_slug": "previous-contract", "captured_at": START-timedelta(minutes=1),
            "forecast_direction": "UP", "probability_up": 0.9, "issued_at": (START-timedelta(minutes=2)).isoformat(),
        }])
        client = self.client(conn, ISSUANCE_SEMANTICS_TRUSTED="true")
        body = self.get(client, "/api/active-alert").get_json()
        self.assertNotEqual(body.get("status"), "ACTIVE")
        query = next((q for q in conn.calls if "FROM biological_reservoir_observations" in q[0]), None)
        self.assertIsNotNone(query)
        self.assertEqual(query[1], (SLUG, START, END))

    def test_trust_disabled_keeps_chart_available_but_no_alert(self):
        points = [{"market_slug": SLUG, "captured_at": START+timedelta(minutes=i), "midpoint": 0.4+i/100,
                   "window_start": START, "window_end": END, "id": i} for i in (6, 7, 8)]
        obs = [{"snapshot_id": 2, "market_slug": SLUG, "captured_at": START+timedelta(minutes=2),
                "forecast_direction": "UP", "probability_up": 0.8, "issued_at": (START+timedelta(minutes=2)).isoformat()}]
        conn = FakeConnection(snapshots=points, observations=obs)
        client = self.client(conn, ISSUANCE_SEMANTICS_TRUSTED="false")
        series = self.get(client, "/api/contract-price-series?market_slug="+SLUG).get_json()
        alert = self.get(client, "/api/active-alert").get_json()
        self.assertEqual(series["status"], "AVAILABLE")
        self.assertNotEqual(alert.get("status"), "ACTIVE")
        self.assertEqual(alert.get("graph_annotations", []), [])

    def test_chart_requires_current_identity_and_exact_window_parameters(self):
        points = [{"market_slug": SLUG, "captured_at": START+timedelta(minutes=i), "midpoint": 0.4+i/100,
                   "window_start": START, "window_end": END, "id": i} for i in (6, 7, 8)]
        conn = FakeConnection(snapshots=points)
        client = self.client(conn)
        wrong = self.get(client, "/api/contract-price-series?market_slug=previous-contract").get_json()
        self.assertEqual(wrong["status"], "UNAVAILABLE_CONTRACT_ROLLOVER")
        self.get(client, "/api/contract-price-series?market_slug="+SLUG)
        sql, params = next((q for q in conn.calls if "FROM public.snapshots" in q[0]))
        self.assertIn("market_slug=%s", sql)
        self.assertIn("window_start=%s AND window_end=%s", sql)
        self.assertEqual(params, (SLUG, START, END))

    def test_invalid_ambiguous_and_conflicting_contracts_fail_closed(self):
        bad = canonical_row(window_end=END+timedelta(minutes=15))
        bad["metadata"] = dict(bad["metadata"])
        bad["metadata"]["assetPriceTerms"] = dict(bad["metadata"]["assetPriceTerms"])
        bad["metadata"]["assetPriceTerms"]["windowEnd"] = bad["window_end"].isoformat()
        self.assertNotEqual(select_canonical_open_contract([bad], NOW)["status"], "OPEN")
        self.assertEqual(select_canonical_open_contract([canonical_row(), canonical_row(market_slug="other", market_id="2")], NOW)["reason"], "ambiguous_canonical_contracts")
        client = self.client(FakeConnection(canonical=[canonical_row(), canonical_row(market_slug="other", market_id="2")]))
        self.assertEqual(self.get(client, "/api/current-contract").get_json()["status"], "NO_OPEN_CONTRACT")

        conflicting = canonical_row()
        conflicting["metadata"] = dict(conflicting["metadata"])
        conflicting["metadata"]["assetPriceTerms"] = dict(conflicting["metadata"]["assetPriceTerms"])
        conflicting["metadata"]["assetPriceTerms"]["windowEnd"] = (END + timedelta(minutes=15)).isoformat()
        conflict_client = self.client(FakeConnection(canonical=[conflicting]))
        self.assertEqual(self.get(conflict_client, "/api/current-contract").get_json()["status"], "NO_OPEN_CONTRACT")

    def test_missing_issuance_has_no_alert_or_graph_marker(self):
        conn = FakeConnection(observations=[{
            "snapshot_id": 7, "market_slug": SLUG,
            "captured_at": START + timedelta(minutes=4),
            "forecast_direction": "UP", "probability_up": 0.91,
            "issued_at": None,
        }])
        client = self.client(conn, ISSUANCE_SEMANTICS_TRUSTED="true")
        body = self.get(client, "/api/active-alert").get_json()
        self.assertNotEqual(body.get("status"), "ACTIVE")
        self.assertIsNone(body.get("alert"))
        self.assertEqual(body.get("graph_annotations"), [])
        query = next(q for q in conn.calls if "FROM biological_reservoir_observations" in q[0])
        self.assertEqual(query[1], (SLUG, START, END))

    def test_database_errors_are_sanitized(self):
        client = self.client(FakeConnection(fail=True))
        response = self.get(client, "/api/current-contract")
        self.assertEqual(response.status_code, 500)
        body = response.get_data(as_text=True)
        self.assertNotIn("FAKE_SECRET", body)
        self.assertNotIn("private:password", body)

    def test_price_series_handles_canonical_lookup_error_without_secondary_exception(self):
        client = self.client(FakeConnection(fail=True))
        response = self.get(client, "/api/contract-price-series?market_slug=" + SLUG)
        self.assertEqual(response.status_code, 500)
        body = response.get_json()
        self.assertEqual(body["status"], "UNAVAILABLE_QUERY_ERROR")
        self.assertEqual(body["message"], "Price history is temporarily unavailable; server-side query failed.")
        self.assertEqual(body["contract_identity"], SLUG)
        self.assertEqual(body["points"], [])
        self.assertNotIn("FAKE_SECRET", response.get_data(as_text=True))
        self.assertNotIn("private:password", response.get_data(as_text=True))


if __name__ == "__main__":
    unittest.main()
