"""Persistent research-candidate registry for Connectome entry-timing strategies.

Top-five rankings are exploratory candidates only. Profiles are updated from settled
contract evidence and never enable or modify live execution.
"""
import json
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

GRAPH_LABELS = {"decision": "Decision", "research": "Research", "analysis": "Analysis"}
TARGETS = {
    "win_rate": 0.98,
    "daily_return": 0.032,
    "monthly_return": 1.40,
    "max_drawdown": 0.05,
    "trades_per_day": 240,
}
MIN_CONTRACTS_FOR_RANKING = 30
MIN_CONTRACTS_FOR_READINESS = 100


def _bucket_settings(bucket):
    fixed = {"first_seen": None, "10m": 600, "5m": 300, "3m": 180, "1m": 60}
    if bucket in fixed:
        seconds = fixed[bucket]
    elif str(bucket).endswith("m_remaining"):
        try:
            seconds = int(str(bucket).split("m_")[0]) * 60
        except ValueError:
            seconds = None
    else:
        seconds = None
    return {
        "entry_timing_bucket": bucket,
        "target_seconds_to_contract_close": seconds,
        "evaluation_unit": "one_snapshot_per_settled_contract_per_bucket",
        "minimum_contracts_for_provisional_ranking": MIN_CONTRACTS_FOR_RANKING,
        "minimum_contracts_for_readiness_review": MIN_CONTRACTS_FOR_READINESS,
        "execution_enabled": False,
        "live_trading_enabled": False,
    }


def build_and_persist(entry_timing_by_graph, readiness_by_graph=None):
    """Refresh candidate profiles and persist both current state and immutable history."""
    readiness_by_graph = readiness_by_graph or {}
    now = datetime.now(timezone.utc)
    candidates = []
    for graph_key in ("decision", "research", "analysis"):
        timing = entry_timing_by_graph.get(graph_key) or {}
        readiness = readiness_by_graph.get(graph_key) or {}
        for metric in timing.get("buckets", []):
            bucket = str(metric.get("bucket") or "")
            if not bucket:
                continue
            n = int(metric.get("contracts") or 0)
            ret = metric.get("mean_return_per_dollar")
            accuracy = metric.get("accuracy")
            brier = metric.get("brier")
            # Ranking prefers adequately sampled candidates; within the same
            # evidence tier it favors positive estimated returns and then Brier.
            eligible = n >= MIN_CONTRACTS_FOR_RANKING and ret is not None
            score = (float(ret) if ret is not None else -999.0)
            candidate_id = f"{graph_key}:{bucket}"
            status = "PROVISIONAL_CANDIDATE" if eligible else "COLLECTING_DATA"
            profile = {
                "candidate_id": candidate_id,
                "graph_key": graph_key,
                "graph_name": GRAPH_LABELS[graph_key],
                "strategy_type": "contract_entry_timing",
                "settings": _bucket_settings(bucket),
                "metrics": {
                    "settled_contracts": n,
                    "accuracy": accuracy,
                    "brier": brier,
                    "estimated_return_per_dollar": ret,
                    "positive_return_rate": metric.get("positive_return_rate"),
                    "priced_entries": metric.get("priced_entries"),
                    "ranking_eligible": eligible,
                    "metric_source": "historical_quotes_estimated_binary_settlement",
                    "fees_included": False,
                    "slippage_included": False,
                    "verified_fills": False,
                },
                "readiness": {
                    "overall_status": readiness.get("overall_status", "NOT_READY"),
                    "live_trading_enabled": False,
                },
                "performance_targets": TARGETS,
                "profile_updated_at": now.isoformat(),
                "status": status,
                "rank": None,
                "ranking_score": score,
            }
            candidates.append(profile)

    # Keep a stable top five even when evidence is sparse, but label every
    # under-sampled row as collecting data instead of implying proven quality.
    candidates.sort(key=lambda x: (
        1 if x["metrics"]["ranking_eligible"] else 0,
        x["ranking_score"],
        float(x["metrics"]["accuracy"] or 0.0),
        -(float(x["metrics"]["brier"]) if x["metrics"]["brier"] is not None else 1.0),
        x["candidate_id"],
    ), reverse=True)
    for i, candidate in enumerate(candidates, 1):
        candidate["rank"] = i
        candidate["status"] = "TOP_5_PROVISIONAL" if i <= 5 and candidate["metrics"]["ranking_eligible"] else (
            "TOP_5_COLLECTING_DATA" if i <= 5 else candidate["status"]
        )
    top_five = candidates[:5]
    saved = _persist(entry_timing_by_graph, candidates, top_five, now)
    return {
        "updated_at": now.isoformat(),
        "candidate_count": len(candidates),
        "top_five": top_five,
        "ranking_method": "sample-gated estimated return, then accuracy and Brier tie-breakers",
        "ranking_minimum_contracts": MIN_CONTRACTS_FOR_RANKING,
        "profile_persistence": "SAVED" if saved else "SAVE_FAILED",
        "live_trading_enabled": False,
        "warning": "Top-five status is a research shortlist, not live-trading approval. Returns are quote estimates without fees, slippage, or verified fills.",
    }


def _persist(entry_timing_by_graph, candidates, top_five, now):
    # Use the same paid PostgreSQL connection already owned by the Connectome
    # service; the first graph supplies the shared database connector.
    graph = None
    # Callers attach a connector graph through a private optional argument below.
    return False


def persist_with_graph(graph, entry_timing_by_graph, readiness_by_graph=None):
    """Build and persist profiles using a known Connectome PostgreSQL connection."""
    readiness_by_graph = readiness_by_graph or {}
    now = datetime.now(timezone.utc)
    candidates = []
    for graph_key in ("decision", "research", "analysis"):
        timing = entry_timing_by_graph.get(graph_key) or {}
        readiness = readiness_by_graph.get(graph_key) or {}
        for metric in timing.get("buckets", []):
            bucket = str(metric.get("bucket") or "")
            if not bucket:
                continue
            n = int(metric.get("contracts") or 0)
            ret = metric.get("mean_return_per_dollar")
            eligible = n >= MIN_CONTRACTS_FOR_RANKING and ret is not None
            candidate = {
                "candidate_id": f"{graph_key}:{bucket}",
                "graph_key": graph_key,
                "graph_name": GRAPH_LABELS[graph_key],
                "strategy_type": "contract_entry_timing",
                "settings": _bucket_settings(bucket),
                "metrics": {
                    "settled_contracts": n, "accuracy": metric.get("accuracy"),
                    "brier": metric.get("brier"), "estimated_return_per_dollar": ret,
                    "positive_return_rate": metric.get("positive_return_rate"),
                    "priced_entries": metric.get("priced_entries"),
                    "ranking_eligible": eligible,
                    "metric_source": "historical_quotes_estimated_binary_settlement",
                    "fees_included": False, "slippage_included": False, "verified_fills": False,
                },
                "readiness": {"overall_status": readiness.get("overall_status", "NOT_READY"),
                              "live_trading_enabled": False},
                "performance_targets": TARGETS, "profile_updated_at": now.isoformat(),
                "status": "PROVISIONAL_CANDIDATE" if eligible else "COLLECTING_DATA",
                "rank": None, "ranking_score": float(ret) if ret is not None else -999.0,
            }
            candidates.append(candidate)
    candidates.sort(key=lambda x: (
        1 if x["metrics"]["ranking_eligible"] else 0,
        x["ranking_score"],
        float(x["metrics"]["accuracy"] or 0.0),
        -(float(x["metrics"]["brier"]) if x["metrics"]["brier"] is not None else 1.0),
        x["candidate_id"],
    ), reverse=True)
    for i, candidate in enumerate(candidates, 1):
        candidate["rank"] = i
        if i <= 5:
            candidate["status"] = "TOP_5_PROVISIONAL" if candidate["metrics"]["ranking_eligible"] else "TOP_5_COLLECTING_DATA"
    top_five = candidates[:5]
    saved = False
    try:
        with graph._pg_connect() as pg:
            pg.execute("""
                CREATE TABLE IF NOT EXISTS connectome_candidate_profiles (
                    candidate_id TEXT PRIMARY KEY,
                    graph_key TEXT NOT NULL,
                    strategy_type TEXT NOT NULL,
                    rank INTEGER,
                    status TEXT NOT NULL,
                    profile_json JSONB NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL
                )
            """)
            pg.execute("""
                CREATE TABLE IF NOT EXISTS connectome_candidate_profile_history (
                    id BIGSERIAL PRIMARY KEY,
                    candidate_id TEXT NOT NULL,
                    rank INTEGER,
                    status TEXT NOT NULL,
                    profile_json JSONB NOT NULL,
                    captured_at TIMESTAMPTZ NOT NULL
                )
            """)
            # Refresh all current profiles, preserving a single current row per candidate.
            for candidate in candidates:
                pg.execute("""
                    INSERT INTO connectome_candidate_profiles
                    (candidate_id,graph_key,strategy_type,rank,status,profile_json,updated_at)
                    VALUES (%s,%s,%s,%s,%s,%s::jsonb,%s)
                    ON CONFLICT (candidate_id) DO UPDATE SET
                      graph_key=EXCLUDED.graph_key,strategy_type=EXCLUDED.strategy_type,
                      rank=EXCLUDED.rank,status=EXCLUDED.status,
                      profile_json=EXCLUDED.profile_json,updated_at=EXCLUDED.updated_at
                """, (candidate["candidate_id"], candidate["graph_key"], candidate["strategy_type"],
                      candidate["rank"], candidate["status"], json.dumps(candidate), now))
                pg.execute("""
                    INSERT INTO connectome_candidate_profile_history
                    (candidate_id,rank,status,profile_json,captured_at)
                    VALUES (%s,%s,%s,%s::jsonb,%s)
                """, (candidate["candidate_id"], candidate["rank"], candidate["status"],
                      json.dumps(candidate), now))
        saved = True
    except Exception:
        logger.exception("CONNECTOME_CANDIDATE_PROFILE_PERSIST_FAILED")
    return {
        "updated_at": now.isoformat(), "candidate_count": len(candidates),
        "top_five": top_five,
        "ranking_method": "sample-gated estimated return, then accuracy and Brier tie-breakers",
        "ranking_minimum_contracts": MIN_CONTRACTS_FOR_RANKING,
        "profile_persistence": "SAVED" if saved else "SAVE_FAILED",
        "live_trading_enabled": False,
        "warning": "Top-five status is a research shortlist, not live-trading approval. Returns are quote estimates without fees, slippage, or verified fills.",
    }


def load_latest(graph):
    """Read current top-five profiles from persistent PostgreSQL for restart recovery."""
    try:
        with graph._pg_connect() as pg:
            rows = pg.execute(
                "SELECT profile_json FROM connectome_candidate_profiles "
                "ORDER BY rank ASC NULLS LAST, candidate_id ASC LIMIT 5"
            ).fetchall()
        top = []
        for row in rows:
            value = row[0]
            top.append(value if isinstance(value, dict) else json.loads(value or "{}"))
        return {"top_five": top, "profile_persistence": "SAVED", "live_trading_enabled": False}
    except Exception as exc:
        logger.warning("CONNECTOME_CANDIDATE_PROFILE_LOAD_FAILED: %s", exc)
        return {"top_five": [], "profile_persistence": "UNAVAILABLE",
                "live_trading_enabled": False, "error": str(exc)}
