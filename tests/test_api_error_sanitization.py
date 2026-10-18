from __future__ import annotations
import importlib
import os
import sys
import types
import unittest
from unittest.mock import patch

_MISSING = object()

class ApiErrorSanitizationTests(unittest.TestCase):
    SECRET = "FAKE_SECRET_TOKEN"
    RAW_ERROR = "FAKE_SECRET_TOKEN postgresql://user:pass@private-db.example/app connection failed"

    @classmethod
    def setUpClass(cls):
        cls._saved_dashboard = sys.modules.pop("dashboard", _MISSING)
        cls._saved_main = sys.modules.get("main", _MISSING)
        main_stub = types.ModuleType("main")
        main_stub.TradingBot = object
        sys.modules["main"] = main_stub
        try:
            cls.dashboard = importlib.import_module("dashboard")
        except Exception:
            sys.modules.pop("dashboard", None)
            if cls._saved_dashboard is not _MISSING:
                sys.modules["dashboard"] = cls._saved_dashboard
            if cls._saved_main is _MISSING:
                sys.modules.pop("main", None)
            else:
                sys.modules["main"] = cls._saved_main
            raise

    @classmethod
    def tearDownClass(cls):
        sys.modules.pop("dashboard", None)
        if cls._saved_dashboard is not _MISSING:
            sys.modules["dashboard"] = cls._saved_dashboard
        if cls._saved_main is _MISSING:
            sys.modules.pop("main", None)
        else:
            sys.modules["main"] = cls._saved_main

    def request_with_database_failure(self, path, expected_log, extra_env=None):
        env = {"CONNECTOME_DATABASE_URL": "postgresql://test", **(extra_env or {})}
        with (
            patch.dict(os.environ, env),
            patch("psycopg.connect", side_effect=RuntimeError(self.RAW_ERROR)) as connect,
            self.assertLogs(level="ERROR") as captured,
        ):
            response = self.dashboard.app.test_client().get(path)
        connect.assert_called_once()
        log_text = "\n".join(captured.output)
        self.assertIn(expected_log, log_text)
        self.assertNotIn(self.SECRET, log_text)
        self.assertNotIn(self.RAW_ERROR, log_text)
        self.assertNotIn("private-db.example", log_text)
        self.assertNotIn("user:pass", log_text)
        return response

    def assert_sanitized_response(self, response, expected_message, required_keys):
        self.assertEqual(response.status_code, 500)
        body = response.get_json()
        self.assertIsInstance(body, dict)
        for key in required_keys:
            self.assertIn(key, body)
        self.assertEqual(body["message"], expected_message)
        response_text = response.get_data(as_text=True)
        self.assertNotIn(self.SECRET, response_text)
        self.assertNotIn(self.RAW_ERROR, response_text)
        self.assertNotIn("private-db.example", response_text)
        self.assertNotIn("user:pass", response_text)
        return body

    def test_current_contract_hides_database_exception(self):
        response = self.request_with_database_failure("/api/current-contract", "endpoint=current_contract event=query_failed")
        body = self.assert_sanitized_response(response, "Contract lookup is temporarily unavailable.", ("ok", "status", "contract"))
        self.assertFalse(body["ok"])
        self.assertEqual(body["status"], "ERROR")
        self.assertIsNone(body["contract"])

    def test_active_alert_hides_database_exception(self):
        contract = {"identity": "test-contract", "start_at": "2026-10-17T15:00:00+00:00", "end_at": "2026-10-17T15:15:00+00:00"}
        fake_contract_response = types.SimpleNamespace(get_json=lambda: {"status": "OPEN", "contract": contract})
        with patch.object(self.dashboard, "current_contract", return_value=fake_contract_response):
            response = self.request_with_database_failure("/api/active-alert", "endpoint=active_alert event=query_failed")
        body = self.assert_sanitized_response(response, "Active alert data is temporarily unavailable.", ("ok", "status", "alert", "graph_annotations"))
        self.assertFalse(body["ok"])
        self.assertEqual(body["status"], "ERROR")
        self.assertIsNone(body["alert"])
        self.assertEqual(body["graph_annotations"], [])

    def test_rolling_accuracy_hides_database_exception(self):
        response = self.request_with_database_failure("/api/rolling-accuracy", "endpoint=rolling_accuracy event=query_failed", {"RESERVOIR_SCORING_POLICY_APPROVED": "true"})
        body = self.assert_sanitized_response(response, "Rolling accuracy data is temporarily unavailable.", ("ok", "status"))
        self.assertFalse(body["ok"])
        self.assertEqual(body["status"], "ERROR")

    def test_verified_contracts_hides_database_exception(self):
        response = self.request_with_database_failure("/api/verified-contracts", "endpoint=verified_contracts event=query_failed", {"OUTCOME_PROVENANCE_TRUSTED": "true"})
        body = self.assert_sanitized_response(response, "Verified contract data is temporarily unavailable.", ("ok", "metrics", "contracts"))
        self.assertFalse(body["ok"])
        self.assertEqual(body["metrics"], {})
        self.assertEqual(body["contracts"], [])

    def test_reservoir_telemetry_hides_database_exception(self):
        response = self.request_with_database_failure("/api/biological-reservoir", "endpoint=reservoir_telemetry event=query_failed")
        body = self.assert_sanitized_response(response, "Reservoir telemetry is temporarily unavailable.", ("ok", "status", "model", "observations", "recent", "freshness"))
        self.assertFalse(body["ok"])
        self.assertEqual(body["status"], "ERROR")
        self.assertIsNone(body["model"])
        self.assertEqual(body["observations"], {})
        self.assertEqual(body["recent"], [])
        self.assertEqual(body["freshness"], {})

    def test_contract_price_series_hides_database_exception(self):
        slug = "cpc-btc-updown-15m-2026-10-17-1945z"
        response = self.request_with_database_failure("/api/contract-price-series?market_slug=" + slug, "endpoint=contract_price_series event=query_failed")
        body = self.assert_sanitized_response(response, "Price history is temporarily unavailable; server-side query failed.", ("ok", "status", "contract_identity", "points", "message"))
        self.assertFalse(body["ok"])
        self.assertEqual(body["status"], "UNAVAILABLE_QUERY_ERROR")
        self.assertEqual(body["contract_identity"], slug)
        self.assertEqual(body["points"], [])

if __name__ == "__main__":
    unittest.main()
