"""Two independent, outcome-trained sparse Connectome graphs for paper research.

Each graph supports up to one million nodes and one million directed edges. Capacity
is virtual: only observed nodes/edges are persisted. Every market snapshot is retained
independently of paper trades and labelled after verified contract settlement.
"""
import hashlib
import json
import logging
import os
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

logger = logging.getLogger(__name__)
MAX_NODES_DEFAULT = 1_000_000
MAX_EDGES_DEFAULT = 1_000_000


def _stable_id(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:32]


class Connectome:
    """Sparse SQLite-backed graph with independently learned feature edges."""

    def __init__(self, name: str, config: Optional[dict] = None):
        self.name = name
        config = config or {}
        self.max_nodes = max(1, int(config.get("max_nodes", MAX_NODES_DEFAULT)))
        self.max_edges = max(1, int(config.get("max_edges", MAX_EDGES_DEFAULT)))
        default_dir = os.getenv("CONNECTOME_DATA_DIR", "connectome_data")
        Path(default_dir).mkdir(parents=True, exist_ok=True)
        filename = f"{name.lower().replace(' ', '_')}.sqlite3"
        self.db_path = str(Path(default_dir) / filename)
        self.min_samples_for_gate = max(1, int(config.get("min_samples_for_gate", 20)))
        self.learning_rate = min(0.25, max(0.001, float(config.get("learning_rate", 0.03))))
        self._initialize()

    def _connect(self):
        con = sqlite3.connect(self.db_path, timeout=15)
        con.row_factory = sqlite3.Row
        return con

    def _initialize(self):
        with self._connect() as con:
            con.execute("PRAGMA journal_mode=WAL")
            con.execute("PRAGMA synchronous=NORMAL")
            con.executescript("""
                CREATE TABLE IF NOT EXISTS nodes (
                    node_id TEXT PRIMARY KEY,
                    kind TEXT NOT NULL,
                    signature TEXT NOT NULL,
                    visits INTEGER NOT NULL DEFAULT 0,
                    wins INTEGER NOT NULL DEFAULT 0,
                    losses INTEGER NOT NULL DEFAULT 0,
                    up_count INTEGER NOT NULL DEFAULT 0,
                    down_count INTEGER NOT NULL DEFAULT 0,
                    updated_at REAL NOT NULL
                );
                CREATE UNIQUE INDEX IF NOT EXISTS nodes_kind_signature
                    ON nodes(kind, signature);
                CREATE TABLE IF NOT EXISTS edges (
                    edge_id TEXT PRIMARY KEY,
                    source_id TEXT NOT NULL,
                    target_id TEXT NOT NULL,
                    weight REAL NOT NULL DEFAULT 0.0,
                    updates INTEGER NOT NULL DEFAULT 0,
                    wins INTEGER NOT NULL DEFAULT 0,
                    losses INTEGER NOT NULL DEFAULT 0,
                    updated_at REAL NOT NULL,
                    UNIQUE(source_id, target_id)
                );
                CREATE TABLE IF NOT EXISTS observations (
                    event_id TEXT PRIMARY KEY,
                    market_id TEXT,
                    observed_at REAL NOT NULL,
                    features_json TEXT NOT NULL,
                    outcome INTEGER,
                    actual_up INTEGER,
                    settled_at REAL
                );
                CREATE INDEX IF NOT EXISTS observations_market
                    ON observations(market_id, observed_at);
                CREATE TABLE IF NOT EXISTS metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
            """)
            node_columns = {row["name"] for row in con.execute("PRAGMA table_info(nodes)").fetchall()}
            if "up_count" not in node_columns:
                con.execute("ALTER TABLE nodes ADD COLUMN up_count INTEGER NOT NULL DEFAULT 0")
            if "down_count" not in node_columns:
                con.execute("ALTER TABLE nodes ADD COLUMN down_count INTEGER NOT NULL DEFAULT 0")
            observation_columns = {row["name"] for row in con.execute("PRAGMA table_info(observations)").fetchall()}
            if "actual_up" not in observation_columns:
                con.execute("ALTER TABLE observations ADD COLUMN actual_up INTEGER")
            # Backfill older correctness-only labels into the actual Up/Down outcome.
            legacy = con.execute(
                "SELECT event_id,features_json,outcome FROM observations WHERE outcome IS NOT NULL AND actual_up IS NULL"
            ).fetchall()
            for row in legacy:
                direction = str(json.loads(row["features_json"]).get("direction", "unknown")).lower()
                if direction == "up":
                    actual_up = int(row["outcome"])
                elif direction == "down":
                    actual_up = 1 - int(row["outcome"])
                else:
                    continue
                con.execute("UPDATE observations SET actual_up=? WHERE event_id=?", (actual_up, row["event_id"]))
                features = json.loads(row["features_json"])
                for kind, signature in features.items():
                    if kind.startswith("_"):
                        continue
                    node = con.execute("SELECT node_id FROM nodes WHERE kind=? AND signature=?", (kind, signature)).fetchone()
                    if node:
                        con.execute(
                            "UPDATE nodes SET up_count=up_count+?,down_count=down_count+? WHERE node_id=?",
                            (actual_up, 1 - actual_up, node["node_id"]),
                        )
            con.execute("INSERT OR REPLACE INTO metadata(key,value) VALUES('graph_name',?)", (self.name,))
            con.execute("INSERT OR REPLACE INTO metadata(key,value) VALUES('node_capacity',?)", (str(self.max_nodes),))
            con.execute("INSERT OR REPLACE INTO metadata(key,value) VALUES('edge_capacity',?)", (str(self.max_edges),))

    @staticmethod
    def _features(opportunity: Any, role: str) -> Dict[str, str]:
        move = float(getattr(opportunity, "price_difference", 0.0) or 0.0)
        delay = float(getattr(opportunity, "polymarket_delay", 0.0) or 0.0)
        confidence = float(getattr(opportunity, "confidence", 0.0) or 0.0)
        direction = str(getattr(opportunity, "direction", "unknown"))
        action = str(getattr(opportunity, "recommended_action", "unknown"))
        exchanges = str(getattr(opportunity, "exchange_moved", "unknown"))
        market_id = str(getattr(opportunity, "market_id", "") or "")
        quote_spread = None
        bid = getattr(opportunity, "yes_bid", None)
        ask = getattr(opportunity, "yes_ask", None)
        if bid is not None and ask is not None:
            quote_spread = max(0.0, float(ask) - float(bid))
        move_bucket = "small" if move < 0.05 else "medium" if move < 0.15 else "large"
        delay_bucket = "fast" if delay < 7 else "normal" if delay < 12 else "slow"
        confidence_bucket = "low" if confidence < 0.7 else "mid" if confidence < 0.85 else "high"
        spread_bucket = "unknown" if quote_spread is None else "tight" if quote_spread <= 0.03 else "wide"
        checkpoint = str(getattr(opportunity, "checkpoint", "unknown"))
        remaining = float(getattr(opportunity, "time_remaining", 0.0) or 0.0)
        midpoint = float(getattr(opportunity, "midpoint", 0.5) or 0.5)
        depth = getattr(opportunity, "depth_imbalance", None)
        odds_change = float(getattr(opportunity, "market_probability_change", 0.0) or 0.0)
        odds_momentum = "rising" if odds_change > 0.005 else "falling" if odds_change < -0.005 else "flat"
        source = str(getattr(opportunity, "prediction_source", "btc_consensus") or "btc_consensus")
        agreeing_count = int(getattr(opportunity, "agreeing_exchange_count", 0) or 0)
        consensus_bucket = "none" if agreeing_count == 0 else "two" if agreeing_count == 2 else "three_plus"
        exchange_moves = {
            "binance": getattr(opportunity, "exchange_binance_move", None),
            "coinbase": getattr(opportunity, "exchange_coinbase_move", None),
            "kraken": getattr(opportunity, "exchange_kraken_move", None),
        }
        def exchange_signal(value):
            if value is None:
                return "missing"
            value = float(value)
            if value > 0.005:
                return "up"
            if value < -0.005:
                return "down"
            return "flat"
        exchange_signals = {name: exchange_signal(value) for name, value in exchange_moves.items()}
        exchange_relationship = str(getattr(opportunity, "exchange_relationship", "unknown"))
        pair_relationships = getattr(opportunity, "exchange_pair_relationships", {}) or {}
        remaining_bucket = "early" if remaining > 600 else "mid" if remaining > 300 else "late" if remaining > 60 else "expiry"
        midpoint_bucket = "low" if midpoint < 0.35 else "lean_down" if midpoint < 0.48 else "balanced" if midpoint <= 0.52 else "lean_up" if midpoint <= 0.65 else "high"
        depth_bucket = "unknown" if depth is None else "sell_heavy" if float(depth) < -0.2 else "balanced" if float(depth) <= 0.2 else "buy_heavy"
        base = {
            "checkpoint": checkpoint,
            "remaining": remaining_bucket,
            "midpoint": midpoint_bucket,
            "depth": depth_bucket,
            "odds_momentum": odds_momentum,
            "prediction_source": source,
            "consensus": consensus_bucket,
            "binance_signal": exchange_signals["binance"],
            "coinbase_signal": exchange_signals["coinbase"],
            "kraken_signal": exchange_signals["kraken"],
            "exchange_relationship": exchange_relationship,
            "binance_coinbase_relation": str(pair_relationships.get("binance_coinbase", "unknown")),
            "binance_kraken_relation": str(pair_relationships.get("binance_kraken", "unknown")),
            "coinbase_kraken_relation": str(pair_relationships.get("coinbase_kraken", "unknown")),
            "direction": direction,
            "action": action,
            "move": move_bucket,
            "delay": delay_bucket,
            "confidence": confidence_bucket,
            "exchanges": exchanges,
            "spread": spread_bucket,
            # Raw observation values are stored for calibration/audit, but excluded
            # from node signatures so tiny numeric changes do not create endless nodes.
            "_raw_scan_confidence": round(min(0.999, max(0.001, confidence)), 6),
            "_snapshot_midpoint": round(midpoint, 6),
            "_snapshot_market_up_probability": round(float(getattr(opportunity, "market_up_probability", midpoint) or midpoint), 6),
            "_snapshot_odds_change": round(odds_change, 6),
            "_snapshot_time_remaining_seconds": round(remaining, 3),
            "_snapshot_delay_seconds": round(delay, 3),
            "_snapshot_btc_move": round(move, 6),
            "_snapshot_binance_move": round(float(exchange_moves["binance"]), 6) if exchange_moves["binance"] is not None else None,
            "_snapshot_coinbase_move": round(float(exchange_moves["coinbase"]), 6) if exchange_moves["coinbase"] is not None else None,
            "_snapshot_kraken_move": round(float(exchange_moves["kraken"]), 6) if exchange_moves["kraken"] is not None else None,
            "_snapshot_exchange_relationship": exchange_relationship,
            "_snapshot_direction": direction,
        }
        if role == "research":
            # Research independently combines time, odds, momentum and exchange agreement.
            base = {
                "checkpoint": checkpoint,
                "direction": direction,
                "checkpoint_midpoint": f"{checkpoint}:{midpoint_bucket}",
                "remaining_depth": f"{remaining_bucket}:{depth_bucket}",
                "direction_move": f"{direction}:{move_bucket}",
                "odds_momentum_source": f"{odds_momentum}:{source}",
                "delay_spread": f"{delay_bucket}:{spread_bucket}",
                "consensus_confidence": f"{consensus_bucket}:{confidence_bucket}",
                "exchange_consensus": exchanges,
                "binance_signal": exchange_signals["binance"],
                "coinbase_signal": exchange_signals["coinbase"],
                "kraken_signal": exchange_signals["kraken"],
                "exchange_relationship": exchange_relationship,
                "binance_coinbase_relation": str(pair_relationships.get("binance_coinbase", "unknown")),
                "binance_kraken_relation": str(pair_relationships.get("binance_kraken", "unknown")),
                "coinbase_kraken_relation": str(pair_relationships.get("coinbase_kraken", "unknown")),
                "action": action,
            }
        # Preserve exact values in each observation row for audit and calibration,
        # while the graph itself learns only from the bounded categorical signatures.
        base.update({
            "_raw_scan_confidence": round(min(0.999, max(0.001, confidence)), 6),
            "_snapshot_midpoint": round(midpoint, 6),
            "_snapshot_market_up_probability": round(float(getattr(opportunity, "market_up_probability", midpoint) or midpoint), 6),
            "_snapshot_odds_change": round(odds_change, 6),
            "_snapshot_time_remaining_seconds": round(remaining, 3),
            "_snapshot_delay_seconds": round(delay, 3),
            "_snapshot_btc_move": round(move, 6),
            "_snapshot_binance_move": round(float(exchange_moves["binance"]), 6) if exchange_moves["binance"] is not None else None,
            "_snapshot_coinbase_move": round(float(exchange_moves["coinbase"]), 6) if exchange_moves["coinbase"] is not None else None,
            "_snapshot_kraken_move": round(float(exchange_moves["kraken"]), 6) if exchange_moves["kraken"] is not None else None,
            "_snapshot_exchange_relationship": exchange_relationship,
            "_snapshot_direction": direction,
        })
        return base

    def record_signal(self, opportunity: Any, role: str = "decision") -> str:
        features = self._features(opportunity, role)
        event_id = str(getattr(opportunity, "connectome_event_id", "") or "")
        if not event_id:
            event_id = f"{getattr(opportunity, 'market_id', '')}:{int(float(getattr(opportunity, 'timestamp', time.time())) * 1000)}"
        now = time.time()
        forecast_probability = getattr(opportunity, "_connectome_forecast_probability", None)
        if forecast_probability is not None:
            features["_forecast_probability"] = min(0.999, max(0.001, float(forecast_probability)))
        forecast_up_probability = getattr(opportunity, "_connectome_up_probability", None)
        if forecast_up_probability is not None:
            features["_forecast_up_probability"] = min(0.999, max(0.001, float(forecast_up_probability)))
        with self._connect() as con:
            # Same contract/checkpoint rescans are idempotent and cannot inflate graph visits.
            if con.execute("SELECT 1 FROM observations WHERE event_id=?", (event_id,)).fetchone():
                return event_id
            con.execute(
                "INSERT INTO observations(event_id,market_id,observed_at,features_json) VALUES(?,?,?,?)",
                (event_id, getattr(opportunity, "market_id", None), now, json.dumps(features, sort_keys=True)),
            )
            node_features = {k: v for k, v in features.items() if not k.startswith("_")}
            node_ids = []
            for kind, signature in node_features.items():
                node_id = _stable_id(f"{self.name}|{kind}|{signature}")
                exists = con.execute("SELECT 1 FROM nodes WHERE node_id=?", (node_id,)).fetchone()
                if not exists:
                    count = con.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
                    if count >= self.max_nodes:
                        continue
                    con.execute(
                        "INSERT INTO nodes(node_id,kind,signature,updated_at) VALUES(?,?,?,?)",
                        (node_id, kind, signature, now),
                    )
                con.execute("UPDATE nodes SET visits=visits+1,updated_at=? WHERE node_id=?", (now, node_id))
                node_ids.append(node_id)
            # Link consecutive feature nodes, with a hard graph-capacity guard.
            for source, target in zip(node_ids, node_ids[1:]):
                edge_id = _stable_id(f"{self.name}|{source}|{target}")
                exists = con.execute("SELECT 1 FROM edges WHERE edge_id=?", (edge_id,)).fetchone()
                if not exists:
                    count = con.execute("SELECT COUNT(*) FROM edges").fetchone()[0]
                    if count >= self.max_edges:
                        continue
                    con.execute(
                        "INSERT INTO edges(edge_id,source_id,target_id,weight,updated_at) VALUES(?,?,?,?,?)",
                        (edge_id, source, target, 0.0, now),
                    )
        return event_id

    def predict(self, opportunity: Any, role: str = "decision") -> Dict[str, Any]:
        features = self._features(opportunity, role)
        node_probabilities = []
        node_up_probabilities = []
        evidence_nodes = 0
        weighted_sum = weight_total = 0.0
        with self._connect() as con:
            total_row = con.execute(
                "SELECT COUNT(*) AS n, COALESCE(SUM(outcome),0) AS wins, "
                "SUM(CASE WHEN actual_up=1 THEN 1 ELSE 0 END) AS up_count, "
                "SUM(CASE WHEN actual_up=0 THEN 1 ELSE 0 END) AS down_count "
                "FROM observations WHERE outcome IS NOT NULL"
            ).fetchone()
            samples = int(total_row["n"])
            total_wins = int(total_row["wins"])
            up_samples = int(total_row["up_count"] or 0) + int(total_row["down_count"] or 0)
            global_up_probability = (int(total_row["up_count"] or 0) + 1.0) / (up_samples + 2.0)
            for kind, signature in features.items():
                row = con.execute(
                    "SELECT wins,losses,up_count,down_count FROM nodes WHERE kind=? AND signature=?",
                    (kind, signature),
                ).fetchone()
                if row:
                    node_wins, node_losses = int(row["wins"]), int(row["losses"])
                    node_samples = node_wins + node_losses
                    if node_samples:
                        node_probabilities.append((node_wins + 1.0) / (node_samples + 2.0))
                    up_node_samples = int(row["up_count"]) + int(row["down_count"])
                    if up_node_samples:
                        node_up_probabilities.append((int(row["up_count"]) + 1.0) / (up_node_samples + 2.0))
                    evidence_nodes += 1
            items = list(features.items())
            for (kind_a, sig_a), (kind_b, sig_b) in zip(items, items[1:]):
                a = con.execute("SELECT node_id FROM nodes WHERE kind=? AND signature=?", (kind_a, sig_a)).fetchone()
                b = con.execute("SELECT node_id FROM nodes WHERE kind=? AND signature=?", (kind_b, sig_b)).fetchone()
                if a and b:
                    edge = con.execute(
                        "SELECT weight,updates FROM edges WHERE source_id=? AND target_id=?",
                        (a["node_id"], b["node_id"]),
                    ).fetchone()
                    if edge and int(edge["updates"]) > 0:
                        weight = min(1.0, float(edge["updates"]) / 20.0)
                        weighted_sum += (float(edge["weight"]) + 1.0) / 2.0 * weight
                        weight_total += weight
        # Directional correctness and Up/Down outcome probabilities are separate targets.
        global_probability = (total_wins + 1.0) / (samples + 2.0)
        node_probability = sum(node_probabilities) / len(node_probabilities) if node_probabilities else global_probability
        probability = 0.6 * node_probability + 0.4 * global_probability if node_probabilities else global_probability
        if weight_total:
            probability = 0.8 * probability + 0.2 * (weighted_sum / weight_total)
        market_up_prior = min(0.999, max(0.001, float(features.get("_snapshot_market_up_probability", 0.5))))
        if up_samples:
            node_up_probability = (
                sum(node_up_probabilities) / len(node_up_probabilities)
                if node_up_probabilities else global_up_probability
            )
            up_probability = 0.6 * node_up_probability + 0.4 * global_up_probability if node_up_probabilities else global_up_probability
            # Keep a market-price prior, but let settled feature evidence move it.
            up_probability = 0.8 * up_probability + 0.2 * market_up_prior
        else:
            up_probability = market_up_prior
        return {
            # probability = probability the indicated direction is correct.
            "probability": round(min(0.999, max(0.001, probability)), 6),
            # up_probability = calibrated target for final Up/Down settlement.
            "up_probability": round(min(0.999, max(0.001, up_probability)), 6),
            "samples": samples,
            "up_samples": up_samples,
            "evidence_nodes": evidence_nodes,
            "ready_for_gate": samples >= self.min_samples_for_gate,
        }

    def settle(self, event_id: str, won: bool, actual_up: Optional[bool] = None) -> bool:
        """Apply each verified binary outcome once; return False for duplicate/missing events."""
        outcome = 1 if won else 0
        now = time.time()
        with self._connect() as con:
            row = con.execute("SELECT features_json,outcome FROM observations WHERE event_id=?", (event_id,)).fetchone()
            if not row or row["outcome"] is not None:
                return False
            features = json.loads(row["features_json"])
            con.execute("UPDATE observations SET outcome=?,actual_up=?,settled_at=? WHERE event_id=? AND outcome IS NULL",
                        (outcome, int(bool(actual_up)) if actual_up is not None else None, now, event_id))
            node_ids = []
            for kind, signature in features.items():
                if kind.startswith("_"):
                    continue
                node = con.execute("SELECT node_id FROM nodes WHERE kind=? AND signature=?", (kind, signature)).fetchone()
                if node:
                    node_id = node["node_id"]
                    node_ids.append(node_id)
                    con.execute(
                        "UPDATE nodes SET wins=wins+?,losses=losses+?,up_count=up_count+?,down_count=down_count+?,updated_at=? WHERE node_id=?",
                        (outcome, 1 - outcome, int(bool(actual_up)) if actual_up is not None else 0,
                         (1 - int(bool(actual_up))) if actual_up is not None else 0, now, node_id),
                    )
            for source, target in zip(node_ids, node_ids[1:]):
                edge = con.execute("SELECT edge_id,weight,updates FROM edges WHERE source_id=? AND target_id=?",
                                   (source, target)).fetchone()
                if not edge:
                    continue
                old_weight = float(edge["weight"])
                target_weight = 1.0 if outcome else -1.0
                new_weight = old_weight + self.learning_rate * (target_weight - old_weight)
                con.execute(
                    "UPDATE edges SET weight=?,updates=updates+1,wins=wins+?,losses=losses+?,updated_at=? WHERE edge_id=?",
                    (new_weight, outcome, 1 - outcome, now, edge["edge_id"]),
                )
        logger.info("CONNECTOME_LEARNING graph=%s event=%s outcome=%s", self.name, event_id, outcome)
        return True

    def record_scan_observation(
        self, opportunity: Any, role: str,
        forecast_probability: Optional[float] = None,
        forecast_up_probability: Optional[float] = None,
    ) -> str:
        """Persist pre-settlement directional confidence and P(Up) for later calibration."""
        if forecast_probability is not None:
            opportunity._connectome_forecast_probability = float(forecast_probability)
        if forecast_up_probability is not None:
            opportunity._connectome_up_probability = float(forecast_up_probability)
        return self.record_signal(opportunity, role=role)

    def settle_market(self, market_id: str, actual_up: bool) -> int:
        """Label every pending checkpoint for a closed contract against its actual direction."""
        with self._connect() as con:
            rows = con.execute(
                "SELECT event_id,features_json FROM observations WHERE market_id=? AND outcome IS NULL",
                (market_id,),
            ).fetchall()
        settled = 0
        for row in rows:
            features = json.loads(row["features_json"])
            direction = str(features.get("direction", "unknown")).lower()
            won = (direction == "up" and actual_up) or (direction == "down" and not actual_up)
            if direction in ("up", "down") and self.settle(str(row["event_id"]), won, actual_up=actual_up):
                settled += 1
        if settled:
            logger.info("CONNECTOME_CONTRACT_SETTLED graph=%s market=%s checkpoints=%d actual_up=%s",
                        self.name, market_id, settled, actual_up)
        return settled

    def pending_markets(self) -> list[str]:
        """Markets with scan forecasts awaiting an authoritative final outcome."""
        with self._connect() as con:
            rows = con.execute(
                "SELECT DISTINCT market_id FROM observations WHERE outcome IS NULL AND market_id IS NOT NULL"
            ).fetchall()
        return [str(row["market_id"]) for row in rows]

    def pending_for_market(self, market_id: str) -> list[dict]:
        with self._connect() as con:
            rows = con.execute(
                "SELECT event_id,features_json FROM observations WHERE market_id=? AND outcome IS NULL",
                (market_id,),
            ).fetchall()
        return [{"event_id": row["event_id"], "features": json.loads(row["features_json"])} for row in rows]

    def stats(self) -> Dict[str, Any]:
        with self._connect() as con:
            nodes = con.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
            edges = con.execute("SELECT COUNT(*) FROM edges").fetchone()[0]
            observations = con.execute("SELECT COUNT(*) FROM observations").fetchone()[0]
            settled = con.execute("SELECT COUNT(*) FROM observations WHERE outcome IS NOT NULL").fetchone()[0]
            wins = con.execute("SELECT COUNT(*) FROM observations WHERE outcome=1").fetchone()[0]
            losses = con.execute("SELECT COUNT(*) FROM observations WHERE outcome=0").fetchone()[0]
            rows = con.execute("SELECT features_json,outcome,actual_up FROM observations WHERE outcome IS NOT NULL").fetchall()
            checkpoint_counts = {}
            for row in rows:
                features = json.loads(row["features_json"])
                checkpoint = str(features.get("checkpoint", "trade_signal"))
                item = checkpoint_counts.setdefault(checkpoint, {"wins": 0, "losses": 0, "settled": 0})
                item["settled"] += 1
                item["wins" if int(row["outcome"]) == 1 else "losses"] += 1
            brier_total = 0.0
            brier_n = 0
            directional_brier_total = 0.0
            directional_brier_n = 0
            raw_brier_total = 0.0
            raw_brier_n = 0
            for row in rows:
                features = json.loads(row["features_json"])
                label = int(row["outcome"])
                bucket = checkpoint_counts[str(features.get("checkpoint", "trade_signal"))]
                forecast = features.get("_forecast_probability")
                if forecast is not None:
                    score = (float(forecast) - label) ** 2
                    bucket.setdefault("directional_brier_sum", 0.0)
                    bucket.setdefault("directional_brier_n", 0)
                    bucket["directional_brier_sum"] += score
                    bucket["directional_brier_n"] += 1
                    directional_brier_total += score
                    directional_brier_n += 1
                forecast_up = features.get("_forecast_up_probability")
                if forecast_up is not None and row["actual_up"] is not None:
                    up_score = (float(forecast_up) - int(row["actual_up"])) ** 2
                    bucket.setdefault("brier_sum", 0.0)
                    bucket.setdefault("brier_n", 0)
                    bucket["brier_sum"] += up_score
                    bucket["brier_n"] += 1
                    brier_total += up_score
                    brier_n += 1
                raw_confidence = features.get("_raw_scan_confidence")
                if raw_confidence is not None:
                    raw_score = (float(raw_confidence) - label) ** 2
                    bucket.setdefault("raw_brier_sum", 0.0)
                    bucket.setdefault("raw_brier_n", 0)
                    bucket["raw_brier_sum"] += raw_score
                    bucket["raw_brier_n"] += 1
                    raw_brier_total += raw_score
                    raw_brier_n += 1
            for item in checkpoint_counts.values():
                item["win_rate"] = round(item["wins"] / item["settled"], 6) if item["settled"] else None
                item["brier_score"] = round(item.get("brier_sum", 0.0) / item["brier_n"], 6) if item.get("brier_n") else None
                item["directional_confidence_brier"] = round(item.get("directional_brier_sum", 0.0) / item["directional_brier_n"], 6) if item.get("directional_brier_n") else None
                item["raw_confidence_brier"] = round(item.get("raw_brier_sum", 0.0) / item["raw_brier_n"], 6) if item.get("raw_brier_n") else None
                item.pop("brier_sum", None)
                item.pop("brier_n", None)
                item.pop("directional_brier_sum", None)
                item.pop("directional_brier_n", None)
                item.pop("raw_brier_sum", None)
                item.pop("raw_brier_n", None)
            candidates = {
                key: value for key, value in checkpoint_counts.items()
                if key in {"first_seen", "10m", "5m", "3m", "1m"} and value["settled"] >= self.min_samples_for_gate
            }
            recommended = min(
                candidates,
                key=lambda key: (
                    candidates[key]["brier_score"] if candidates[key]["brier_score"] is not None else 1.0 - candidates[key]["win_rate"],
                    -candidates[key]["settled"],
                ),
            ) if candidates else None
            return {
                "name": self.name,
                "storage": self.db_path,
                "node_capacity": self.max_nodes,
                "edge_capacity": self.max_edges,
                "nodes_active": int(nodes),
                "edges_active": int(edges),
                "observations": int(observations),
                "settled_observations": int(settled),
                "wins": int(wins),
                "losses": int(losses),
                "win_rate": round(wins / settled, 6) if settled else None,
                "brier_score": round(brier_total / brier_n, 6) if brier_n else None,
                "directional_confidence_brier": round(directional_brier_total / directional_brier_n, 6) if directional_brier_n else None,
                "up_probability_samples": brier_n,
                "raw_confidence_brier": round(raw_brier_total / raw_brier_n, 6) if raw_brier_n else None,
                "checkpoint_performance": checkpoint_counts,
                "recommended_checkpoint": recommended,
                "learning": "settlement_only",
            }
