"""Behavioral contract tests for the Oracle Track B dashboard API.

The tests isolate Flask/PostgreSQL at the module boundary because the project
requirements are not installed in this execution environment. SQL and response
contracts are exercised against deterministic DB-API fakes; no live DB is used.
"""
from __future__ import annotations

import importlib.util
import os
import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DASHBOARD = ROOT / "dashboard.py"


class FakeFlask:
    def __init__(self, name):
        self.name = name
        self.routes = {}

    def get(self, path):
        def decorate(fn):
            self.routes[path] = fn
            return fn
        return decorate


def _install_import_stubs(monkeypatch):
    flask = types.ModuleType("flask")
    flask.Flask = FakeFlask
    flask.jsonify = lambda value: value
    flask.request = types.SimpleNamespace(headers={}, cookies={})
    monkeypatch.setitem(sys.modules, "flask", flask)

    resolver = types.ModuleType("canonical_resolver")
    resolver.resolve_price_to_beat = lambda *a, **k: None
    resolver.unavailable_price_to_beat = lambda *a, **k: None
    monkeypatch.setitem(sys.modules, "canonical_resolver", resolver)

    ptb = types.ModuleType("polymarket_us_ptb")
    ptb.acquire_official_price_to_beat = lambda *a, **k: None
    ptb.current_btc_15m_slug = lambda *a, **k: None
    monkeypatch.setitem(sys.modules, "polymarket_us_ptb", ptb)

    main = types.ModuleType("main")
    main.TradingBot = object
    monkeypatch.setitem(sys.modules, "main", main)


def _base_rows():
    now = datetime.now(timezone.utc)
    quote_time = now - timedelta(seconds=8)
    inputs = {
        "spot_quote_snapshot": {
            "coinbase": {"source": "coinbase", "product_id": "BTC-USD", "currency": "USD",
                          "bid": 65000.0, "ask": 65002.0, "midpoint": 65001.0,
                          "observed_at": quote_time.isoformat(), "available_at": quote_time.isoformat(),
                          "captured_at": quote_time.isoformat(), "age_seconds_at_checkpoint": 2.0},
            "kraken": {"source": "kraken", "product_id": "XBT-USD", "currency": "USD",
                        "bid": 64999.0, "ask": 65003.0, "midpoint": 65001.0,
                        "observed_at": quote_time.isoformat(), "available_at": quote_time.isoformat(),
                        "captured_at": quote_time.isoformat(), "age_seconds_at_checkpoint": 3.0},
            "binance": {"source": "binance", "product_id": "BTC-USD", "currency": "USD",
                         "bid": 64998.0, "ask": 65004.0, "midpoint": 65001.0,
                         "observed_at": quote_time.isoformat(), "available_at": quote_time.isoformat(),
                         "captured_at": quote_time.isoformat(), "age_seconds_at_checkpoint": 4.0},
        },
        "entry_checkpoint": (now - timedelta(seconds=10)).isoformat(),
    }
    entry = {
        "market_slug": "cpc-btc-updown-15m-2026-10-18-1900z",
        "official_market_id": "official-market-123", "official_ptb": 65000.25,
        "window_start": now - timedelta(minutes=7), "window_end": now + timedelta(minutes=8),
        "entry_at": now - timedelta(minutes=7), "source_direction": "UP", "oracle_direction": "UP",
        "oracle_score": 0.61, "oracle_model_version": "baseline-follow-main-v1", "decision": "ENTER",
        "reason": "eligible baseline agreement", "source_forecast_at": now - timedelta(minutes=8),
        "source_age_seconds": 60.0, "checkpoint_processed_at": now - timedelta(minutes=6, seconds=50),
        "entry_inputs": inputs, "checkpoint_processing_lag_seconds": 10.0,
        "paper_entry_status": "UNAVAILABLE", "fill_price": None, "outcome": None,
        "resolved_at": None, "correct": None, "created_at": now, "updated_at": now,
    }
    return now, entry


class FakeCursor:
    def __init__(self, row=None, rows=None):
        self.row = row
        self.rows = rows

    def fetchone(self):
        return self.row

    def fetchall(self):
        return self.rows or []


class FakeConnection:
    def __init__(self, now, entry, optional_error=False, primary_error=None):
        self.now, self.entry = now, entry
        self.optional_error = optional_error
        self.primary_error = primary_error
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, sql, params=None):
        normalized = " ".join(sql.split())
        self.calls.append(normalized)
        if self.primary_error and "FROM oracle_decisions d LEFT JOIN oracle_paper_entries" in normalized:
            raise self.primary_error
        if normalized.startswith("SELECT to_regclass") and " AS t" in normalized:
            return FakeCursor({"t": "oracle_learning_runs"})
        if normalized.startswith("SELECT to_regclass"):
            return FakeCursor({"decisions": "oracle_decisions", "forecasts": "oracle_source_forecasts",
                               "entries": "oracle_paper_entries", "state": "oracle_track_b_state",
                               "models": "oracle_model_versions", "learning": "oracle_learning_runs",
                               "discovery": "oracle_market_discovery"})
        if "COUNT(*) AS eligible_opportunities" in normalized:
            return FakeCursor({"eligible_opportunities": 1, "entries": 1, "skips": 0,
                               "resolved": 0, "correct": 0, "incorrect": 0, "pending": 1,
                               "simulated_fills": 0, "coverage": 1.0, "latest_decision_at": self.now})
        if "SELECT e.correct FROM oracle_paper_entries" in normalized:
            return FakeCursor({"resolved": 0, "correct": 0, "incorrect": 0})
        if "FROM oracle_model_versions" in normalized:
            return FakeCursor({"version": "baseline-follow-main-v1", "status": "BASELINE",
                               "trained_at": None, "training_cutoff": None, "training_samples": 0,
                               "validation_samples": 0, "validation_accuracy": None,
                               "baseline_accuracy": None, "validation_coverage": None,
                               "baseline_coverage": None, "parameters": {},
                               "details": {"entry_tolerance_seconds": 20}})
        if "FROM oracle_learning_runs ORDER BY" in normalized:
            return FakeCursor({"accepted": False, "reason": "No learning run yet", "training_cutoff": None,
                               "training_samples": 0, "validation_samples": 0, "baseline_accuracy": None,
                               "candidate_accuracy": None, "baseline_coverage": None,
                               "candidate_coverage": None, "candidate_version": None, "rollback_version": None})
        if "FROM oracle_decisions d LEFT JOIN oracle_paper_entries e USING (market_slug)" in normalized:
            return FakeCursor(rows=[self.entry])
        if "MAX(recorded_at) AS latest" in normalized:
            return FakeCursor({"latest": self.now})
        if normalized == "SAVEPOINT oracle_discovery_optional" or normalized.startswith("RELEASE SAVEPOINT") or normalized.startswith("ROLLBACK TO SAVEPOINT"):
            return FakeCursor({})
        if "FROM oracle_market_discovery" in normalized:
            if self.optional_error:
                raise RuntimeError("optional discovery unavailable")
            return FakeCursor({"count": 4, "latest_at": self.now})
        raise AssertionError("Unexpected SQL in dashboard API test: " + normalized)


@pytest.fixture
def dashboard_env(monkeypatch):
    _install_import_stubs(monkeypatch)
    now, entry = _base_rows()
    state = {"connection": FakeConnection(now, entry)}
    psycopg = types.ModuleType("psycopg")
    psycopg.connect = lambda *a, **k: state["connection"]
    rows = types.ModuleType("psycopg.rows")
    rows.dict_row = object()
    psycopg.rows = rows
    monkeypatch.setitem(sys.modules, "psycopg", psycopg)
    monkeypatch.setitem(sys.modules, "psycopg.rows", rows)
    monkeypatch.setenv("CONNECTOME_DATABASE_URL", "postgresql://test.invalid/testdb")
    monkeypatch.setenv("ORACLE_DASHBOARD_API_TOKEN", "test-token")
    sys.modules["flask"].request.headers = {"Authorization": "Bearer test-token"}
    sys.modules["flask"].request.cookies = {}
    spec = importlib.util.spec_from_file_location("dashboard_candidate_under_test", DASHBOARD)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module, state


def _payload(result):
    if isinstance(result, tuple):
        return result[0], result[1]
    return result, 200


def test_api_exposes_checkpoint_and_per_venue_quote_provenance(dashboard_env):
    module, state = dashboard_env
    payload, status = _payload(module.oracle_track_b_status())
    assert status == 200
    assert payload["ok"] is True
    row = payload["entries"][0]
    assert row["checkpoint_processed_at"] is not None
    assert row["checkpoint_processing_lag_seconds"] == 10.0
    assert row["entry_inputs"]["spot_quote_snapshot"]["coinbase"]["product_id"] == "BTC-USD"
    assert row["entry_inputs"]["spot_quote_snapshot"]["kraken"]["currency"] == "USD"
    assert row["entry_inputs"]["spot_quote_snapshot"]["binance"]["observed_at"]
    sql = "\n".join(state["connection"].calls)
    assert "d.checkpoint_processed_at,d.entry_inputs" in sql
    assert "EXTRACT(EPOCH FROM (d.checkpoint_processed_at - d.entry_at))" in sql


def test_runtime_tolerance_is_unknown_and_model_metadata_is_separate(dashboard_env):
    module, _ = dashboard_env
    payload, status = _payload(module.oracle_track_b_status())
    assert status == 200
    assert payload["runtime_tolerance_seconds"] is None
    assert "UNKNOWN" in payload["runtime_tolerance_status"]
    assert payload["model_metadata_tolerance_seconds"] == 20
    assert payload["model_metadata_tolerance_source"] == "oracle_model_versions.parameters/details"
    assert "MATCHES WORKER CODE DEFAULT" in payload["model_metadata_tolerance_status"]


def test_optional_discovery_failure_rolls_back_savepoint_without_poisoning_primary_query(dashboard_env):
    module, state = dashboard_env
    state["connection"].optional_error = True
    payload, status = _payload(module.oracle_track_b_status())
    assert status == 200
    assert payload["ok"] is True
    assert payload["discovery"]["status"] == "OPTIONAL QUERY FAILED: RuntimeError"
    assert any(call.startswith("ROLLBACK TO SAVEPOINT oracle_discovery_optional") for call in state["connection"].calls)
    assert any("FROM oracle_decisions d LEFT JOIN oracle_paper_entries" in call for call in state["connection"].calls)


def test_primary_database_failure_returns_error_without_metrics_or_entries(dashboard_env):
    module, state = dashboard_env
    state["connection"].primary_error = RuntimeError("primary query failed")
    payload, status = _payload(module.oracle_track_b_status())
    assert status == 500
    assert payload["ok"] is False
    assert payload["metrics"] == {}
    assert payload["entries"] == []


def test_missing_database_configuration_is_explicit_and_empty(dashboard_env, monkeypatch):
    module, _ = dashboard_env
    monkeypatch.delenv("CONNECTOME_DATABASE_URL", raising=False)
    payload, status = _payload(module.oracle_track_b_status())
    assert status == 503
    assert payload["status"] == "NOT CONFIGURED"
    assert payload["metrics"] == {}
    assert payload["entries"] == []



def test_persisted_30_second_model_tolerance_is_flagged_without_claiming_runtime_value(dashboard_env):
    module, state = dashboard_env
    original_execute = state["connection"].execute
    def execute_with_30s(sql, params=None):
        result = original_execute(sql, params)
        if "FROM oracle_model_versions" in " ".join(sql.split()):
            result.row["details"] = {"entry_tolerance_seconds": 30}
        return result
    state["connection"].execute = execute_with_30s
    payload, status = _payload(module.oracle_track_b_status())
    assert status == 200
    assert payload["model_metadata_tolerance_seconds"] == 30
    assert payload["runtime_tolerance_seconds"] is None
    assert "DIFFERS FROM WORKER CODE DEFAULT" in payload["model_metadata_tolerance_status"]


def test_missing_quote_snapshots_remain_unavailable_not_fabricated(dashboard_env):
    module, state = dashboard_env
    state["connection"].entry["entry_inputs"] = {"spot_quote_snapshot": {}}
    payload, status = _payload(module.oracle_track_b_status())
    assert status == 200
    quotes = payload["entries"][0]["entry_inputs"]["spot_quote_snapshot"]
    assert quotes == {}
    assert payload["entries"][0]["fill_price"] is None


def test_frontend_uses_safe_text_and_clears_stale_oracle_values_on_refresh_error():
    source = DASHBOARD.read_text(encoding="utf-8")
    assert "td.textContent=String(v)" in source
    assert "oracleCheckpointQuoteSummary(x)" in source
    assert "previous values cleared to avoid presenting stale metrics" in source
    assert "Runtime tolerance: " in source
    assert "entry_tolerance_seconds: 30" not in source


def test_oracle_route_has_a_real_fail_closed_auth_guard(dashboard_env, monkeypatch):
    module, _ = dashboard_env
    monkeypatch.delenv("ORACLE_DASHBOARD_API_TOKEN", raising=False)
    payload, status = _payload(module.oracle_track_b_status())
    assert status == 503
    assert payload["status"] == "AUTH NOT CONFIGURED"
    monkeypatch.setenv("ORACLE_DASHBOARD_API_TOKEN", "test-token")
    module.request.headers = {"Authorization": "Bearer wrong-token"}
    payload, status = _payload(module.oracle_track_b_status())
    assert status == 401
    assert payload["status"] == "UNAUTHORIZED"
    module.request.headers = {"Authorization": "Bearer test-token"}
    payload, status = _payload(module.oracle_track_b_status())
    assert status == 200
