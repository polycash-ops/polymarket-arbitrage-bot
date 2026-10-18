"""Shared PostgreSQL persistence for Signal Oracle Track B.

This adapter intentionally does not create or migrate production tables. Apply the
reviewed proposal separately before enabling writes. It stores direction research,
not exchange/contract fills or contract P&L.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from typing import Any


class OraclePostgresStore:
    production_shared_store = True

    def __init__(self, database_url: str | None = None):
        self.database_url = database_url or os.getenv("CONNECTOME_DATABASE_URL")
        if not self.database_url:
            raise RuntimeError("CONNECTOME_DATABASE_URL is required for shared Oracle persistence")

    def _connect(self):
        import psycopg
        from psycopg.rows import dict_row
        return psycopg.connect(self.database_url, connect_timeout=5, row_factory=dict_row)

    @staticmethod
    def _window_id(window_start: str) -> str:
        return hashlib.sha256(("signal_oracle|binance_window|" + window_start).encode()).hexdigest()

    @staticmethod
    def _prediction_id(window_start: str, strategy_version: str) -> str:
        return hashlib.sha256(("signal_oracle|" + strategy_version + "|" + window_start).encode()).hexdigest()

    def record_window(self, benchmark: dict[str, Any], *, contract_id: str | None = None,
                      contract_verified: bool = False, heartbeat_at: str | None = None) -> dict[str, Any]:
        """Persist benchmark once; later polls cannot overwrite the first open price."""
        start = benchmark["window_start"]
        end = benchmark["window_end"]
        with self._connect() as conn:
            row = conn.execute("""
                INSERT INTO signal_oracle_windows
                  (window_id, window_start, window_end, contract_id, contract_verified,
                   benchmark_name, benchmark_qualifier, benchmark_symbol, benchmark_interval,
                   benchmark_quote_currency, benchmark_price, benchmark_source_timestamp,
                   benchmark_acquired_at, benchmark_status, current_price, current_price_timestamp,
                   candle_close_price, candle_close_source_timestamp, candle_finalized,
                   outcome, heartbeat_at, updated_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'available',%s,%s,%s,%s,%s,%s,%s,now())
                ON CONFLICT (window_start) DO UPDATE SET
                  contract_id = COALESCE(signal_oracle_windows.contract_id, EXCLUDED.contract_id),
                  contract_verified = signal_oracle_windows.contract_verified OR EXCLUDED.contract_verified,
                  current_price = EXCLUDED.current_price,
                  current_price_timestamp = EXCLUDED.current_price_timestamp,
                  candle_close_price = CASE WHEN EXCLUDED.candle_finalized THEN EXCLUDED.candle_close_price ELSE signal_oracle_windows.candle_close_price END,
                  candle_close_source_timestamp = CASE WHEN EXCLUDED.candle_finalized THEN EXCLUDED.candle_close_source_timestamp ELSE signal_oracle_windows.candle_close_source_timestamp END,
                  candle_finalized = signal_oracle_windows.candle_finalized OR EXCLUDED.candle_finalized,
                  outcome = CASE WHEN signal_oracle_windows.outcome IS NULL AND EXCLUDED.candle_finalized THEN EXCLUDED.outcome ELSE signal_oracle_windows.outcome END,
                  heartbeat_at = EXCLUDED.heartbeat_at, updated_at = now()
                RETURNING *
            """, (
                self._window_id(start), start, end, contract_id, bool(contract_verified),
                benchmark["benchmark_name"], benchmark["qualifier"], benchmark["symbol"],
                benchmark["interval"], benchmark["quote_currency"], benchmark["benchmark_price"],
                benchmark["benchmark_source_timestamp"], benchmark["acquired_at"],
                benchmark.get("current_price"), benchmark.get("current_price_timestamp"),
                benchmark.get("close_price") if benchmark.get("finalized") else None,
                benchmark.get("candle_close_source_timestamp") if benchmark.get("finalized") else None,
                bool(benchmark.get("finalized")), benchmark.get("outcome") if benchmark.get("finalized") else None,
                heartbeat_at or datetime.now(timezone.utc).isoformat(),
            )).fetchone()
        return dict(row)

    def record_prediction(self, *, window_start: str, window_end: str, issued_at: str,
                          action: str, score: float | None, features: list[float],
                          provenance: dict[str, Any], reason: str,
                          strategy_version: str, contract_id: str | None = None,
                          contract_verified: bool = False) -> dict[str, Any]:
        if action not in {"UP", "DOWN", "NO TRADE"}:
            raise ValueError("invalid Oracle direction")
        pid = self._prediction_id(window_start, strategy_version)
        with self._connect() as conn:
            row = conn.execute("""
                INSERT INTO signal_oracle_predictions
                  (prediction_id, contract_id, window_start, window_end, issued_at, action, score,
                   features_json, provenance_json, reason, status, strategy_id, strategy_version,
                   benchmark_source, contract_verified, execution_status, pnl)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s,'pending','signal_oracle',%s,
                        'binance_spot_btcusdt_15m',%s,'unavailable_no_verified_contract_quotes',NULL)
                ON CONFLICT (prediction_id) DO NOTHING
                RETURNING *
            """, (pid, contract_id, window_start, window_end, issued_at, action, score,
                  json.dumps(features), json.dumps(provenance), reason, strategy_version,
                  bool(contract_verified))).fetchone()
            if row is None:
                row = conn.execute("SELECT * FROM signal_oracle_predictions WHERE prediction_id=%s", (pid,)).fetchone()
        return dict(row)

    def settle_binance_window(self, window_start: str, *, outcome: str, finalized: bool,
                              close_price: float, close_source_timestamp: str,
                              settled_at: str) -> int:
        if not finalized or outcome not in {"UP", "DOWN", "TIE"}:
            return 0
        with self._connect() as conn:
            conn.execute("""
                UPDATE signal_oracle_windows SET candle_close_price=%s,
                  candle_close_source_timestamp=%s,candle_finalized=true,outcome=%s,updated_at=now()
                WHERE window_start=%s AND outcome IS NULL
            """, (close_price, close_source_timestamp, outcome, window_start))
            status = "tie" if outcome == "TIE" else "resolved"
            result = conn.execute("""
                UPDATE signal_oracle_predictions SET status=%s,outcome=%s,
                  outcome_source='binance_spot_btcusdt_15m',settled_at=%s
                WHERE window_start=%s AND status='pending'
                RETURNING prediction_id
            """, (status, outcome, settled_at, window_start)).fetchall()
        return len(result)

    def heartbeat(self, *, state: str, message: str | None = None,
                  at: str | None = None) -> None:
        with self._connect() as conn:
            conn.execute("""
                INSERT INTO signal_oracle_worker_state (id, heartbeat_at, state, message, updated_at)
                VALUES (1,%s,%s,%s,now())
                ON CONFLICT (id) DO UPDATE SET heartbeat_at=EXCLUDED.heartbeat_at,
                  state=EXCLUDED.state,message=EXCLUDED.message,updated_at=now()
            """, (at or datetime.now(timezone.utc).isoformat(), state, message))

    def dashboard_payload(self) -> dict[str, Any]:
        with self._connect() as conn:
            window = conn.execute("SELECT * FROM signal_oracle_windows ORDER BY window_start DESC LIMIT 1").fetchone()
            worker = conn.execute("SELECT * FROM signal_oracle_worker_state WHERE id=1").fetchone()
            latest = conn.execute("""
                SELECT * FROM signal_oracle_predictions ORDER BY window_end DESC, issued_at DESC LIMIT 1
            """).fetchone()
            metrics = conn.execute("""
                WITH eligible AS (
                  SELECT prediction_id, action, outcome, window_end,
                    (action=outcome) AS correct
                  FROM signal_oracle_predictions
                  WHERE status='resolved' AND action IN ('UP','DOWN') AND outcome IN ('UP','DOWN')
                    AND outcome_source='binance_spot_btcusdt_15m'
                ), ranked AS (
                  SELECT *, row_number() OVER (ORDER BY window_end DESC, prediction_id DESC) AS rn
                  FROM eligible
                )
                SELECT count(*) AS lifetime_total,
                  count(*) FILTER (WHERE correct) AS lifetime_correct,
                  count(*) FILTER (WHERE rn<=100) AS rolling_total,
                  count(*) FILTER (WHERE rn<=100 AND correct) AS rolling_correct
                FROM ranked
            """).fetchone()
            counts = conn.execute("""
                SELECT count(*) FILTER (WHERE status='pending') AS pending,
                  count(*) FILTER (WHERE status='tie') AS ties,
                  count(*) FILTER (WHERE action='NO TRADE' OR status='excluded') AS excluded,
                  count(*) FILTER (WHERE status='resolved' AND action IN ('UP','DOWN') AND outcome IN ('UP','DOWN')) AS eligible
                FROM signal_oracle_predictions
            """).fetchone()
        def pct(correct, total):
            return round(100.0 * int(correct or 0) / int(total), 2) if int(total or 0) else None
        now = datetime.now(timezone.utc)
        heartbeat_age = None
        if worker and worker.get("heartbeat_at"):
            stamp = worker["heartbeat_at"]
            if isinstance(stamp, str):
                stamp = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
            heartbeat_age = max(0, (now - stamp.astimezone(timezone.utc)).total_seconds())
        return {
            "ok": True, "track": "Track B — Signal Oracle",
            "mode": "PAPER DIRECTION SIMULATION", "paper_only": True, "live_trading_enabled": False,
            "label": "Binance direction accuracy",
            "benchmark_label": "Oracle paper PTB — Binance",
            "benchmark_qualifier": "Binance window-open benchmark; not official Polymarket PTB.",
            "window": dict(window) if window else None,
            "worker": dict(worker) if worker else None,
            "heartbeat_age_seconds": heartbeat_age,
            "worker_status": ("ERROR" if worker and worker.get("state") == "error" else
                "STALE" if heartbeat_age is None or heartbeat_age > 90 else "WORKING"),
            "latest": dict(latest) if latest else None,
            "metrics": {
                "rolling_window": 100, "rolling_correct": int(metrics["rolling_correct"] or 0),
                "rolling_total": int(metrics["rolling_total"] or 0),
                "rolling_accuracy_pct": pct(metrics["rolling_correct"], metrics["rolling_total"]),
                "lifetime_correct": int(metrics["lifetime_correct"] or 0),
                "lifetime_total": int(metrics["lifetime_total"] or 0),
                "lifetime_accuracy_pct": pct(metrics["lifetime_correct"], metrics["lifetime_total"]),
                "pending_count": int(counts["pending"] or 0), "tie_count": int(counts["ties"] or 0),
                "excluded_count": int(counts["excluded"] or 0), "eligible_count": int(counts["eligible"] or 0),
            },
            "execution": {"status": "unavailable", "pnl": None,
                          "reason": "Binance direction benchmark does not establish Polymarket contract fills or P&L."},
        }
