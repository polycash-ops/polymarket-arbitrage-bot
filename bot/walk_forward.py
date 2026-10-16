"""Chronological walk-forward evaluation for persisted Connectome snapshots."""
import json
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

_ALLOWED_FEATURES = {
    "checkpoint", "remaining_fine", "midpoint_fine", "odds_change_magnitude",
    "spread_fine", "time_of_day", "weekday", "depth_15m", "depth_1h",
    "depth", "odds_momentum", "exchange_relationship", "market_horizon",
    "contract_phase", "midpoint_regime", "bid_ask_spread", "btc_consensus",
    "checkpoint_midpoint", "remaining_depth", "direction_move", "odds_momentum_source",
    "delay_spread", "consensus_confidence", "exchange_consensus",
}


def run_if_due(graph, min_samples=50, interval=25):
    """Evaluate a held-out chronological window and persist the result to model_runs."""
    started = datetime.now(timezone.utc)
    with graph._connect() as con:
        rows = con.execute(
            "SELECT event_id,market_id,observed_at,settled_at,features_json,actual_up "
            "FROM observations WHERE outcome IS NOT NULL AND actual_up IS NOT NULL "
            "AND settled_at IS NOT NULL ORDER BY observed_at ASC,event_id ASC"
        ).fetchall()
        settled_count = len(rows)
        # Bound runtime as the snapshot archive grows while retaining a recent chronological window.
        if len(rows) > 2500:
            rows = rows[-2500:]
        count_row = con.execute(
            "SELECT value FROM metadata WHERE key='last_training_settled_count'"
        ).fetchone()
        last_count = int(count_row["value"]) if count_row else 0
        time_row = con.execute(
            "SELECT value FROM metadata WHERE key='last_training_run_at'"
        ).fetchone()
        last_run_at = float(time_row["value"]) if time_row else 0.0
        if settled_count < min_samples or settled_count - last_count < interval:
            return None
        changed_edges = int(con.execute(
            "SELECT COUNT(*) FROM edges WHERE updated_at > ?", (last_run_at,)
        ).fetchone()[0])
        node_count = int(con.execute("SELECT COUNT(*) FROM nodes").fetchone()[0])
        edge_count = int(con.execute("SELECT COUNT(*) FROM edges").fetchone()[0])
        updates = int(con.execute(
            "SELECT COALESCE(SUM(weight_updates),0) FROM edges"
        ).fetchone()[0])

    split = max(25, int(len(rows) * 0.70))
    validation = rows[split:]
    baseline_scores, candidate_scores = [], []
    for row in validation:
        observed_at = float(row["observed_at"])
        actual_up = int(row["actual_up"])
        try:
            current = json.loads(row["features_json"])
        except Exception:
            continue
        prior = current.get("_snapshot_market_up_probability")
        if prior is None:
            prior = current.get("_snapshot_midpoint", 0.5)
        baseline_p = min(0.999, max(0.001, float(prior)))

        # A label is usable only after its verified settlement time, preventing
        # future labels from leaking into a historical validation prediction.
        history = []
        for previous in rows[:split]:
            if float(previous["settled_at"]) <= observed_at:
                history.append(previous)
        if len(history) < 10:
            continue
        global_up = sum(int(item["actual_up"]) for item in history)
        global_p = (global_up + 1.0) / (len(history) + 2.0)
        estimates = []
        parsed_history = []
        for previous in history:
            try:
                parsed_history.append((json.loads(previous["features_json"]), int(previous["actual_up"])))
            except Exception:
                pass
        for key in _ALLOWED_FEATURES:
            value = current.get(key)
            if value is None:
                continue
            labels = [label for features, label in parsed_history if features.get(key) == value]
            if len(labels) >= 2:
                strength = len(labels) / (len(labels) + 5.0)
                estimate = (sum(labels) + 2.0 * global_p) / (len(labels) + 2.0)
                estimates.append((estimate, strength))
        if estimates:
            strength_total = sum(weight for _, weight in estimates)
            candidate_p = (sum(p * weight for p, weight in estimates) + 2.0 * global_p) / (strength_total + 2.0)
        else:
            candidate_p = global_p
        candidate_p = min(0.999, max(0.001, candidate_p))
        baseline_scores.append((baseline_p - actual_up) ** 2)
        candidate_scores.append((candidate_p - actual_up) ** 2)

    validation_count = len(baseline_scores)
    if validation_count < 10:
        logger.info(
            "CONNECTOME_WALK_FORWARD_SKIPPED graph=%s settled=%d validation=%d reason=need_10_valid_validation_samples",
            graph.name, settled_count, validation_count,
        )
        return None

    baseline_brier = sum(baseline_scores) / validation_count
    candidate_brier = sum(candidate_scores) / validation_count
    accepted = candidate_brier < baseline_brier
    finished = datetime.now(timezone.utc)
    details = {
        "graph_name": graph.name,
        "method": "chronological_walk_forward_feature_readout_v1",
        "settled_samples": settled_count,
        "initial_train_window_rows": split,
        "validation_samples": validation_count,
        "acceptance_reason": "candidate_brier_below_market_baseline" if accepted else "candidate_did_not_beat_market_baseline",
        "label_integrity": "official_settlement_only",
        "anti_leakage": "training labels used only when settled_at <= validation observed_at",
    }
    # Existing table is reused; graph_name is additive for per-graph reporting.
    with graph._pg_connect() as pg:
        pg.execute("""
            CREATE TABLE IF NOT EXISTS model_runs (
                id BIGSERIAL PRIMARY KEY, started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                finished_at TIMESTAMPTZ, model_version INTEGER NOT NULL DEFAULT 1,
                node_count BIGINT NOT NULL DEFAULT 0, edge_count BIGINT NOT NULL DEFAULT 0,
                updates BIGINT NOT NULL DEFAULT 0, changed_edges BIGINT NOT NULL DEFAULT 0,
                accepted BOOLEAN, baseline_brier DOUBLE PRECISION, candidate_brier DOUBLE PRECISION,
                details JSONB NOT NULL DEFAULT '{}'::jsonb, graph_name TEXT
            )
        """)
        pg.execute("ALTER TABLE model_runs ADD COLUMN IF NOT EXISTS graph_name TEXT")
        pg.execute(
            "INSERT INTO model_runs (started_at,finished_at,model_version,node_count,edge_count,updates,"
            "changed_edges,accepted,baseline_brier,candidate_brier,details,graph_name) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s)",
            (started, finished, 1, node_count, edge_count, updates, changed_edges, accepted,
             baseline_brier, candidate_brier, json.dumps(details), graph.name),
        )
    with graph._connect() as con:
        con.execute("INSERT OR REPLACE INTO metadata(key,value) VALUES('last_training_settled_count',?)",
                    (str(settled_count),))
        con.execute("INSERT OR REPLACE INTO metadata(key,value) VALUES('last_training_run_at',?)",
                    (str(finished.timestamp()),))
    logger.info(
        "CONNECTOME_WALK_FORWARD graph=%s settled=%d validation=%d baseline_brier=%.6f "
        "candidate_brier=%.6f changed_edges=%d accepted=%s",
        graph.name, settled_count, validation_count, baseline_brier, candidate_brier, changed_edges, accepted,
    )
    return {"accepted": accepted, "baseline_brier": baseline_brier, "candidate_brier": candidate_brier,
            "validation_samples": validation_count, "changed_edges": changed_edges}


def status(graph):
    """Return persisted run count and latest evaluation for the dashboard."""
    try:
        with graph._pg_connect() as pg:
            count = pg.execute("SELECT COUNT(*) FROM model_runs WHERE graph_name=%s", (graph.name,)).fetchone()[0]
            row = pg.execute(
                "SELECT started_at,finished_at,model_version,node_count,edge_count,updates,changed_edges,"
                "accepted,baseline_brier,candidate_brier,details FROM model_runs "
                "WHERE graph_name=%s ORDER BY started_at DESC LIMIT 1", (graph.name,)
            ).fetchone()
        latest = None
        if row:
            details = row[10] if isinstance(row[10], dict) else json.loads(row[10] or "{}")
            latest = {"started_at": row[0].isoformat() if row[0] else None,
                      "finished_at": row[1].isoformat() if row[1] else None,
                      "model_version": int(row[2]), "node_count": int(row[3]), "edge_count": int(row[4]),
                      "updates": int(row[5]), "changed_edges": int(row[6]), "accepted": row[7],
                      "baseline_brier": float(row[8]) if row[8] is not None else None,
                      "candidate_brier": float(row[9]) if row[9] is not None else None, "details": details}
        return {"run_count": int(count), "latest": latest}
    except Exception as exc:
        logger.warning("CONNECTOME_TRAINING_STATUS_UNAVAILABLE graph=%s error=%s", graph.name, exc)
        return {"run_count": 0, "latest": None, "error": str(exc)}
