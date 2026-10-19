"""Real Flask + PostgreSQL integration tests for Oracle Track B.

The schema fixture is a verbatim mirror of
polycash-ops/Polymarket-AI-Trader:migrations/20261018_oracle_track_b.sql
at worker revision d9e930e5924cb4a9dcd51f7b37a273338b829d45.
Unlike tests/test_oracle_dashboard_contract.py, these tests do not stub Flask,
psycopg, or DB-API behavior. They use the real application and isolated PG.
"""
from __future__ import annotations

import importlib.util
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import psycopg
from psycopg.rows import dict_row
import pytest

ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "tests" / "fixtures" / "oracle_track_b_migration.sql"
DASHBOARD = ROOT / "dashboard.py"
ADMIN_DSN = os.environ["CONNECTOME_DATABASE_URL"]
TOKEN = os.environ["ORACLE_DASHBOARD_API_TOKEN"]
USERNAME = os.environ["ORACLE_DASHBOARD_USERNAME"]
PASSWORD = os.environ["ORACLE_DASHBOARD_PASSWORD"]
SESSION_SECRET = os.environ["ORACLE_DASHBOARD_SESSION_SECRET"]


@pytest.fixture(scope="session")
def dashboard_module():
    os.environ["CONNECTOME_DATABASE_URL"] = ADMIN_DSN
    os.environ["ORACLE_DASHBOARD_API_TOKEN"] = TOKEN
    os.environ["ORACLE_DASHBOARD_USERNAME"] = USERNAME
    os.environ["ORACLE_DASHBOARD_PASSWORD"] = PASSWORD
    os.environ["ORACLE_DASHBOARD_SESSION_SECRET"] = SESSION_SECRET
    spec = importlib.util.spec_from_file_location("dashboard_postgres_integration", DASHBOARD)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    assert module.app.url_map.bind("").match("/", method="GET")
    assert module.app.url_map.bind("").match("/api/oracle-track-b", method="GET")
    return module


@pytest.fixture(scope="session", autouse=True)
def migrated_schema():
    sql = MIGRATION.read_text(encoding="utf-8")
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        conn.execute(sql, prepare=False)
        tables = conn.execute("""
          SELECT to_regclass('public.oracle_market_discovery') AS discovery,
                 to_regclass('public.oracle_source_forecasts') AS forecasts,
                 to_regclass('public.oracle_decisions') AS decisions,
                 to_regclass('public.oracle_paper_entries') AS entries,
                 to_regclass('public.oracle_model_versions') AS models,
                 to_regclass('public.oracle_learning_runs') AS learning
        """).fetchone()
        assert all(tables), f"migration did not create expected Oracle tables: {tables}"
    yield


@pytest.fixture
def seeded_db(migrated_schema):
    now = datetime.now(timezone.utc)
    with psycopg.connect(ADMIN_DSN, row_factory=dict_row) as conn:
        conn.execute("""
          TRUNCATE oracle_paper_entries, oracle_decisions, oracle_source_forecasts,
                   oracle_learning_runs, oracle_market_discovery RESTART IDENTITY CASCADE
        """)
        for i, (slug, direction, outcome, correct, decision) in enumerate([
            ("cpc-btc-updown-15m-it-up", "UP", "UP", True, "ENTER"),
            ("cpc-btc-updown-15m-it-down", "DOWN", "UP", False, "ENTER"),
            ("cpc-btc-updown-15m-it-pending", "UP", None, None, "ENTER"),
            ("cpc-btc-updown-15m-it-skip", "DOWN", None, None, "SKIP"),
        ], start=1):
            start = now - timedelta(minutes=7)
            end = now + timedelta(minutes=8)
            forecast = conn.execute("""
              INSERT INTO oracle_source_forecasts
                (source_observation_id,market_slug,official_market_id,official_ptb,
                 window_start,window_end,forecast_at,source_model_version,direction,
                 probability_up,input_features,source_details)
              VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb)
              RETURNING id
            """, (i, slug, f"official-{i}", 65000.25, start, end, now-timedelta(minutes=8),
                  1, direction, 0.65 if direction == "UP" else 0.35,
                  json.dumps({"test_fixture": True}), json.dumps({"source": "integration-test"}))).fetchone()["id"]
            quote_age = 240 if i == 1 else 8
            quote = {
                "spot_quote_snapshot": {
                    "coinbase": {
                        "source": "coinbase", "product_id": "BTC-USD", "currency": "USD",
                        "bid": 65000.0, "ask": 65002.0, "midpoint": 65001.0,
                        "observed_at": (now-timedelta(seconds=quote_age)).isoformat(),
                        "available_at": (now-timedelta(seconds=quote_age-1)).isoformat(),
                        "age_seconds_at_checkpoint": quote_age,
                    }
                } if i != 3 else {},
                "entry_checkpoint": (now-timedelta(minutes=7)).isoformat(),
            }
            conn.execute("""
              INSERT INTO oracle_decisions
                (market_slug,official_market_id,official_ptb,window_start,window_end,
                 entry_at,checkpoint_processed_at,source_forecast_id,source_direction,
                 oracle_direction,oracle_score,oracle_model_version,decision,reason,
                 source_forecast_at,source_age_seconds,entry_inputs,paper_entry_status,
                 outcome,resolved_at,outcome_source,correct,created_at,updated_at)
              VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,
                      'FILL_UNAVAILABLE',%s,%s,%s,%s,%s,%s)
            """, (slug, f"official-{i}", 65000.25, start, end, now-timedelta(minutes=7),
                  now-timedelta(minutes=6, seconds=59), forecast, direction, direction, 0.65,
                  "baseline-follow-main-v1", decision, "integration fixture",
                  now-timedelta(minutes=8), 60.0, json.dumps(quote), outcome,
                  now if outcome else None, "polymarket_us_official_verified" if outcome else None,
                  correct, now, now))
            if decision == "ENTER":
                conn.execute("""
                  INSERT INTO oracle_paper_entries
                    (market_slug,entry_at,official_market_id,official_ptb,direction,
                     source_forecast_id,oracle_model_version,source_forecast_at,entry_inputs,
                     fill_status,fill_price,fill_assumptions,outcome,resolved_at,outcome_source,correct)
                  VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,'UNAVAILABLE',NULL,'{}'::jsonb,
                          %s,%s,%s,%s)
                """, (slug, now-timedelta(minutes=7), f"official-{i}", 65000.25, direction,
                      forecast, "baseline-follow-main-v1", now-timedelta(minutes=8),
                      json.dumps(quote), outcome, now if outcome else None,
                      "polymarket_us_official_verified" if outcome else None, correct))
        conn.commit()
    return now


@pytest.fixture
def client(dashboard_module, seeded_db):
    return dashboard_module.app.test_client()


def test_real_flask_routes_register_and_unauthenticated_or_wrong_token_is_denied(dashboard_module):
    client = dashboard_module.app.test_client()
    assert client.get("/").status_code == 200
    assert client.get("/api/oracle-track-b").status_code == 401
    assert client.get("/api/oracle-track-b", headers={"Authorization": "Bearer wrong"}).status_code == 401
    response = client.get("/api/oracle-track-b", headers={"Authorization": f"Bearer {TOKEN}"})
    assert response.status_code == 200



def test_browser_login_creates_read_only_session_without_exposing_api_token(dashboard_module):
    client = dashboard_module.app.test_client()
    page = client.get("/oracle-login", base_url="https://localhost")
    assert page.status_code == 200
    assert b'name="password"' in page.data
    assert TOKEN.encode() not in page.data
    assert client.get("/api/oracle-track-b").status_code == 401
    wrong = client.post("/oracle-login", base_url="https://localhost", data={"username": USERNAME, "password": "wrong"})
    assert wrong.status_code == 401
    accepted = client.post("/oracle-login", base_url="https://localhost", data={"username": USERNAME, "password": PASSWORD})
    assert accepted.status_code == 303
    assert client.get("/api/oracle-track-b", base_url="https://localhost").status_code == 200
    assert dashboard_module.app.config["SESSION_COOKIE_HTTPONLY"] is True
    assert dashboard_module.app.config["SESSION_COOKIE_SECURE"] is True
    assert dashboard_module.app.config["SESSION_COOKIE_SAMESITE"] == "Strict"


def test_missing_api_token_configuration_fails_closed_for_anonymous_request(dashboard_module, monkeypatch):
    monkeypatch.delenv("ORACLE_DASHBOARD_API_TOKEN", raising=False)
    client = dashboard_module.app.test_client()
    assert client.get("/api/oracle-track-b").status_code == 503


def test_missing_browser_login_configuration_fails_closed(dashboard_module, monkeypatch):
    monkeypatch.delenv("ORACLE_DASHBOARD_USERNAME", raising=False)
    assert dashboard_module.app.test_client().get("/oracle-login").status_code == 503


def test_real_migration_sql_and_persisted_outcome_counts(client):
    response = client.get("/api/oracle-track-b", headers={"Authorization": f"Bearer {TOKEN}"})
    assert response.status_code == 200
    body = response.get_json()
    assert body["schema_ready"] is True
    metrics = body["metrics"]
    assert metrics["entries"] == 3
    assert metrics["skips"] == 1
    assert metrics["resolved"] == 2
    assert metrics["correct"] == 1
    assert metrics["incorrect"] == 1
    assert metrics["pending"] == 1
    assert metrics["accuracy_pct"] == 50.0
    assert metrics["rolling_100_resolved"] == 2
    assert metrics["rolling_100_correct"] == 1
    assert metrics["rolling_100_accuracy_pct"] == 50.0
    assert body["live_trading_enabled"] is False
    assert body["research_only"] is True


def test_real_sql_preserves_stale_and_missing_quote_snapshots_without_fabrication(client):
    response = client.get("/api/oracle-track-b", headers={"Authorization": f"Bearer {TOKEN}"})
    assert response.status_code == 200
    entries = {row["market_slug"]: row for row in response.get_json()["entries"]}
    stale = entries["cpc-btc-updown-15m-it-up"]["entry_inputs"]["spot_quote_snapshot"]["coinbase"]
    assert stale["age_seconds_at_checkpoint"] == 240
    assert stale["source"] == "coinbase"
    assert stale["product_id"] == "BTC-USD"
    assert stale["currency"] == "USD"
    assert stale["bid"] == 65000.0 and stale["ask"] == 65002.0
    assert stale["observed_at"] and stale["available_at"]
    assert entries["cpc-btc-updown-15m-it-up"]["fill_price"] is None
    missing = entries["cpc-btc-updown-15m-it-pending"]["entry_inputs"]["spot_quote_snapshot"]
    assert missing == {}
    assert entries["cpc-btc-updown-15m-it-pending"]["fill_price"] is None


def test_real_postgres_optional_discovery_permission_failure_recovers_via_savepoint(
    dashboard_module, seeded_db, monkeypatch
):
    role = "oracle_integration_reader"
    password = "oracle_integration_reader_password"
    with psycopg.connect(ADMIN_DSN, autocommit=True) as admin:
        admin.execute(f'DROP ROLE IF EXISTS "{role}"')
        from psycopg import sql as psycopg_sql
        admin.execute(psycopg_sql.SQL("CREATE ROLE {} LOGIN PASSWORD {}").format(psycopg_sql.Identifier(role), psycopg_sql.Literal(password)))
        admin.execute(psycopg_sql.SQL("GRANT CONNECT ON DATABASE oracle_test TO {}").format(psycopg_sql.Identifier(role)))
        admin.execute(psycopg_sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(psycopg_sql.Identifier(role)))
        for table in ("oracle_track_b_state", "oracle_source_forecasts", "oracle_decisions",
                      "oracle_paper_entries", "oracle_model_versions", "oracle_learning_runs"):
            admin.execute(psycopg_sql.SQL("GRANT SELECT ON TABLE public.{} TO {}").format(psycopg_sql.Identifier(table), psycopg_sql.Identifier(role)))
    reader_dsn = ADMIN_DSN.replace("postgresql://postgres:postgres@", 
                                   f"postgresql://{role}:{password}@")
    monkeypatch.setenv("CONNECTOME_DATABASE_URL", reader_dsn)
    try:
        response = dashboard_module.app.test_client().get(
            "/api/oracle-track-b", headers={"Authorization": f"Bearer {TOKEN}"}
        )
        assert response.status_code == 200
        body = response.get_json()
        assert body["ok"] is True
        assert body["discovery"]["status"] == "OPTIONAL QUERY FAILED: InsufficientPrivilege"
        assert body["metrics"]["resolved"] == 2
    finally:
        monkeypatch.setenv("CONNECTOME_DATABASE_URL", ADMIN_DSN)
        with psycopg.connect(ADMIN_DSN, autocommit=True) as admin:
            admin.execute(psycopg_sql.SQL("DROP OWNED BY {}").format(psycopg_sql.Identifier(role)))
            admin.execute(psycopg_sql.SQL("DROP ROLE IF EXISTS {}").format(psycopg_sql.Identifier(role)))


def test_primary_database_failure_returns_error_without_metrics_or_entries(
    dashboard_module, seeded_db, monkeypatch
):
    monkeypatch.setenv("CONNECTOME_DATABASE_URL", "postgresql://postgres:wrong@127.0.0.1:1/oracle_test")
    response = dashboard_module.app.test_client().get(
        "/api/oracle-track-b", headers={"Authorization": f"Bearer {TOKEN}"}
    )
    assert response.status_code == 500
    body = response.get_json()
    assert body["ok"] is False
    assert body["metrics"] == {}
    assert body["entries"] == []
