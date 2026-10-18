"""Signal Oracle Track B scaffold.

This module deliberately has no network/order-submission code. The strategy is
disabled until a verified provider adapter and shared durable PostgreSQL store
are wired into the existing worker. SQLite is for isolated tests only.
"""
from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

STRATEGY_ID = "signal_oracle"
STRATEGY_VERSION = "oracle-logistic-head-v1"
FEATURE_SCHEMA = "oracle-eight-features-v1"
OFFICIAL_US_SOURCE = "polymarket_us_official"
SETTLEMENT_SOURCE = "polymarket_us_verified_settlement"


@dataclass(frozen=True)
class OracleConfig:
    enabled: bool = False
    paper_only: bool = True
    configured: bool = False
    rolling_window: int = 100
    freshness_seconds: int = 120
    bankroll: float = 1000.0
    stake: float = 5.0
    max_open_positions: int = 1
    entry_cutoff_seconds: int = 60

    def __post_init__(self):
        if not self.paper_only:
            raise ValueError("Signal Oracle cannot run outside paper-only mode")
        if self.rolling_window < 1 or self.freshness_seconds < 1:
            raise ValueError("window and freshness must be positive")
        if self.bankroll <= 0 or not (0 < self.stake <= self.bankroll):
            raise ValueError("invalid bankroll/stake")
        if self.max_open_positions < 1 or self.entry_cutoff_seconds < 0:
            raise ValueError("invalid position/cutoff limits")


def _sigmoid(value: float) -> float:
    value = max(-60.0, min(60.0, float(value)))
    return 1.0 / (1.0 + math.exp(-value))


def encode_features(signals: list[dict[str, Any]], snapshot: dict[str, Any]) -> list[float]:
    """Encode the supplied prototype's eight bounded summary features."""
    valid = []
    for signal in signals:
        try:
            p = float(signal["probability_up"])
            c = float(signal.get("confidence") or 0.0)
            direction = str(signal.get("direction", "")).upper()
            if not (math.isfinite(p) and 0 <= p <= 1 and math.isfinite(c)):
                continue
            signed = 1.0 if direction == "UP" else -1.0 if direction == "DOWN" else 0.0
            valid.append((2 * (p - .5), signed, max(0.0, min(1.0, c))))
        except (KeyError, TypeError, ValueError):
            continue
    n = len(valid)
    mean_p = sum(x[0] for x in valid) / n if n else 0.0
    mean_dir = sum(x[1] for x in valid) / n if n else 0.0
    mean_conf = sum(x[2] for x in valid) / n if n else 0.0
    disagreement = sum(1 for _, d, _ in valid if d != (1 if mean_p >= 0 else -1)) / n if n else 0.0
    depth = max(-1.0, min(1.0, float(snapshot.get("depth_imbalance") or 0.0)))
    midpoint = max(0.0, min(1.0, float(snapshot.get("midpoint", .5))))
    short_momentum = max(-1.0, min(1.0, 10 * float(snapshot.get("short_momentum") or 0.0)))
    values = [mean_p, mean_dir, 2 * (midpoint - .5), depth, short_momentum,
              mean_conf, min(n, 10) / 10.0, disagreement]
    if not all(math.isfinite(x) for x in values):
        raise ValueError("non-finite Oracle feature")
    return values


def decide(features: list[float], weights: list[float] | None = None) -> dict[str, Any]:
    if len(features) != 8 or not all(math.isfinite(float(x)) for x in features):
        return {"action": "NO TRADE", "score": None, "reason": "invalid feature vector"}
    weights = weights or [0.0] * 9
    if len(weights) != 9 or not all(math.isfinite(float(x)) for x in weights):
        raise ValueError("invalid Oracle readout weights")
    p_up = _sigmoid(weights[0] + sum(w * x for w, x in zip(weights[1:], features)))
    if abs(p_up - .5) < 1e-12:
        return {"action": "NO TRADE", "score": p_up, "probability_up": p_up,
                "reason": "readout has no directional edge"}
    return {"action": "UP" if p_up > .5 else "DOWN", "score": p_up,
            "probability_up": p_up, "reason": "oracle logistic readout"}


def signal_id(contract_id: str, window_start: str) -> str:
    raw = f"{STRATEGY_ID}|{STRATEGY_VERSION}|{contract_id}|{window_start}"
    return hashlib.sha256(raw.encode()).hexdigest()


class OracleTestStore:
    """SQLite fixture/shadow store only; not safe for worker/dashboard sharing."""
    def __init__(self, path: str):
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS oracle_predictions(
              prediction_id TEXT PRIMARY KEY, contract_id TEXT NOT NULL,
              window_start TEXT NOT NULL, window_end TEXT NOT NULL,
              issued_at TEXT NOT NULL, action TEXT NOT NULL, score REAL,
              features_json TEXT NOT NULL, provenance_json TEXT NOT NULL,
              reason TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
              outcome TEXT, outcome_source TEXT, settled_at TEXT,
              UNIQUE(contract_id, window_start, strategy_id)
            );
            """) if False else None
            # Explicit migration, compatible with a fresh test database.
            db.execute("""CREATE TABLE IF NOT EXISTS oracle_predictions(
              prediction_id TEXT PRIMARY KEY, contract_id TEXT NOT NULL,
              window_start TEXT NOT NULL, window_end TEXT NOT NULL,
              issued_at TEXT NOT NULL, action TEXT NOT NULL, score REAL,
              features_json TEXT NOT NULL, provenance_json TEXT NOT NULL,
              reason TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
              outcome TEXT, outcome_source TEXT, settled_at TEXT,
              strategy_id TEXT NOT NULL, strategy_version TEXT NOT NULL,
              UNIQUE(contract_id, window_start, strategy_id))""")
            db.execute("""CREATE TABLE IF NOT EXISTS oracle_paper_trades(
              trade_id TEXT PRIMARY KEY, prediction_id TEXT NOT NULL UNIQUE,
              stake REAL NOT NULL, entry_price REAL, status TEXT NOT NULL,
              blocking_reason TEXT, pnl REAL, opened_at TEXT,
              settled_at TEXT, FOREIGN KEY(prediction_id) REFERENCES oracle_predictions(prediction_id))""")
            db.execute("""CREATE TABLE IF NOT EXISTS oracle_label_events(
              event_id TEXT PRIMARY KEY, prediction_id TEXT NOT NULL,
              outcome TEXT NOT NULL, source TEXT NOT NULL, verified_at TEXT NOT NULL,
              FOREIGN KEY(prediction_id) REFERENCES oracle_predictions(prediction_id))""")

    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA busy_timeout=10000")
        return db

    def record(self, prediction: dict[str, Any]) -> dict[str, Any]:
        if prediction.get("action") not in {"UP", "DOWN", "NO TRADE"}:
            raise ValueError("invalid Oracle action")
        required = ("contract_id", "window_start", "window_end", "issued_at", "features", "provenance")
        if any(not prediction.get(k) for k in required):
            raise ValueError("missing required prediction fields")
        pid = signal_id(prediction["contract_id"], prediction["window_start"])
        with self.connect() as db:
            db.execute("""INSERT OR IGNORE INTO oracle_predictions(
              prediction_id,contract_id,window_start,window_end,issued_at,action,score,
              features_json,provenance_json,reason,strategy_id,strategy_version)
              VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
              (pid, prediction["contract_id"], prediction["window_start"], prediction["window_end"],
               prediction["issued_at"], prediction["action"], prediction.get("score"),
               json.dumps(prediction["features"], sort_keys=True),
               json.dumps(prediction["provenance"], sort_keys=True),
               prediction.get("reason", ""), STRATEGY_ID, STRATEGY_VERSION))
            row = db.execute("SELECT * FROM oracle_predictions WHERE prediction_id=?", (pid,)).fetchone()
            return dict(row)

    def settle(self, prediction_id: str, outcome: str, source: str,
               verified_at: str, event_id: str) -> bool:
        if outcome not in {"UP", "DOWN", "VOID"}:
            raise ValueError("outcome must be UP, DOWN, or VOID")
        if source != SETTLEMENT_SOURCE:
            raise ValueError("non-authoritative settlement source")
        with self.connect() as db:
            row = db.execute("SELECT * FROM oracle_predictions WHERE prediction_id=?", (prediction_id,)).fetchone()
            if row is None:
                raise KeyError("unknown prediction")
            inserted = db.execute("""INSERT OR IGNORE INTO oracle_label_events
              (event_id,prediction_id,outcome,source,verified_at) VALUES(?,?,?,?,?)""",
              (event_id, prediction_id, outcome, source, verified_at)).rowcount
            if not inserted:
                return False
            # First authoritative settlement is immutable; corrections remain events for review.
            if row["status"] != "pending":
                return False
            db.execute("""UPDATE oracle_predictions SET status=?,outcome=?,outcome_source=?,settled_at=?
              WHERE prediction_id=? AND status='pending'""",
              ("void" if outcome == "VOID" else "resolved", outcome, source, verified_at, prediction_id))
            return True

    def metrics(self, rolling_window: int = 100) -> dict[str, Any]:
        with self.connect() as db:
            rows = [dict(r) for r in db.execute("""SELECT * FROM oracle_predictions
              WHERE status IN ('resolved','void') ORDER BY window_end DESC, issued_at DESC""")]
            trades = [dict(r) for r in db.execute("SELECT * FROM oracle_paper_trades")]
        eligible = [r for r in rows if r["status"] == "resolved" and r["action"] in {"UP","DOWN"}
                    and r["outcome"] in {"UP","DOWN"}]
        rolling = eligible[:rolling_window]
        correct = lambda values: sum(r["action"] == r["outcome"] for r in values)
        accuracy = lambda values: round(100 * correct(values) / len(values), 2) if values else None
        return {"rolling_window": rolling_window, "rolling_count": len(rolling),
                "rolling_correct": correct(rolling), "rolling_accuracy_pct": accuracy(rolling),
                "lifetime_count": len(eligible), "lifetime_correct": correct(eligible),
                "lifetime_accuracy_pct": accuracy(eligible),
                "pending_count": sum(r["status"] == "pending" for r in rows),
                "void_count": sum(r["status"] == "void" for r in rows),
                "excluded_count": sum(r["action"] == "NO TRADE" for r in rows),
                "paper_trade_count": len(trades),
                "paper_trade_pnl": sum(float(t["pnl"] or 0) for t in trades if t["status"] == "settled")}
