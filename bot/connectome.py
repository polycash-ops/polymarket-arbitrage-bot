"""Two independent, outcome-trained sparse Connectome graphs for paper research.

Each graph supports up to one million nodes and one million directed edges. Capacity
is virtual: only observed nodes/edges are persisted. Learning labels are applied only
after a paper trade has a verified, final settlement.
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
                    settled_at REAL
                );
                CREATE INDEX IF NOT EXISTS observations_market
                    ON observations(market_id, observed_at);
                CREATE TABLE IF NOT EXISTS metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
            """)
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
        base = {
            "direction": direction,
            "action": action,
            "move": move_bucket,
            "delay": delay_bucket,
            "confidence": confidence_bucket,
            "exchanges": exchanges,
            "spread": spread_bucket,
        }
        if role == "research":
            # Research has a separate representation and independently learned graph.
            base = {
                "direction": direction,
                "move_delay": f"{move_bucket}:{delay_bucket}",
                "spread_confidence": f"{spread_bucket}:{confidence_bucket}",
                "exchange_consensus": exchanges,
                "action": action,
            }
        return base

    def record_signal(self, opportunity: Any, role: str = "decision") -> str:
        features = self._features(opportunity, role)
        event_id = str(getattr(opportunity, "connectome_event_id", "") or "")
        if not event_id:
            event_id = f"{getattr(opportunity, 'market_id', '')}:{int(float(getattr(opportunity, 'timestamp', time.time())) * 1000)}"
        now = time.time()
        with self._connect() as con:
            con.execute(
                "INSERT OR IGNORE INTO observations(event_id,market_id,observed_at,features_json) VALUES(?,?,?,?)",
                (event_id, getattr(opportunity, "market_id", None), now, json.dumps(features, sort_keys=True)),
            )
            node_ids = []
            for kind, signature in features.items():
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
        evidence_nodes = 0
        weighted_sum = weight_total = 0.0
        with self._connect() as con:
            total_row = con.execute(
                "SELECT COUNT(*) AS n, COALESCE(SUM(outcome),0) AS wins "
                "FROM observations WHERE outcome IS NOT NULL"
            ).fetchone()
            samples = int(total_row["n"])
            total_wins = int(total_row["wins"])
            for kind, signature in features.items():
                row = con.execute(
                    "SELECT wins,losses FROM nodes WHERE kind=? AND signature=?",
                    (kind, signature),
                ).fetchone()
                if row:
                    node_wins, node_losses = int(row["wins"]), int(row["losses"])
                    node_samples = node_wins + node_losses
                    if node_samples:
                        node_probabilities.append((node_wins + 1.0) / (node_samples + 2.0))
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
        # Count each settled paper trade once; feature-node visits are not independent samples.
        global_probability = (total_wins + 1.0) / (samples + 2.0)
        node_probability = sum(node_probabilities) / len(node_probabilities) if node_probabilities else global_probability
        probability = 0.6 * node_probability + 0.4 * global_probability if node_probabilities else global_probability
        if weight_total:
            probability = 0.8 * probability + 0.2 * (weighted_sum / weight_total)
        return {
            "probability": round(min(0.999, max(0.001, probability)), 6),
            "samples": samples,
            "evidence_nodes": evidence_nodes,
            "ready_for_gate": samples >= self.min_samples_for_gate,
        }

    def settle(self, event_id: str, won: bool) -> bool:
        """Apply each verified binary outcome once; return False for duplicate/missing events."""
        outcome = 1 if won else 0
        now = time.time()
        with self._connect() as con:
            row = con.execute("SELECT features_json,outcome FROM observations WHERE event_id=?", (event_id,)).fetchone()
            if not row or row["outcome"] is not None:
                return False
            features = json.loads(row["features_json"])
            con.execute("UPDATE observations SET outcome=?,settled_at=? WHERE event_id=? AND outcome IS NULL",
                        (outcome, now, event_id))
            node_ids = []
            for kind, signature in features.items():
                node = con.execute("SELECT node_id FROM nodes WHERE kind=? AND signature=?", (kind, signature)).fetchone()
                if node:
                    node_id = node["node_id"]
                    node_ids.append(node_id)
                    con.execute(
                        "UPDATE nodes SET wins=wins+?,losses=losses+?,updated_at=? WHERE node_id=?",
                        (outcome, 1 - outcome, now, node_id),
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

    def stats(self) -> Dict[str, Any]:
        with self._connect() as con:
            nodes = con.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
            edges = con.execute("SELECT COUNT(*) FROM edges").fetchone()[0]
            observations = con.execute("SELECT COUNT(*) FROM observations").fetchone()[0]
            settled = con.execute("SELECT COUNT(*) FROM observations WHERE outcome IS NOT NULL").fetchone()[0]
            wins = con.execute("SELECT COUNT(*) FROM observations WHERE outcome=1").fetchone()[0]
            losses = con.execute("SELECT COUNT(*) FROM observations WHERE outcome=0").fetchone()[0]
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
                "learning": "settlement_only",
            }
