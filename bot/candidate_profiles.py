"""Persistent research-candidate registry for Connectome entry-timing strategies.

Top-five rankings are exploratory candidates only. Profiles are updated from settled
contract evidence and never enable or modify live execution.
"""
import hashlib
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


def _candidate_identity(graph_key, bucket):
    """Return a stable, versioned ID for a strategy candidate."""
    slug = str(bucket).strip().lower().replace(" ", "_").replace("-", "_")
    return f"{graph_key}:entry_{slug}:v1"


def _display_name(graph_key, bucket):
    graph = GRAPH_LABELS.get(graph_key, graph_key.title())
    labels = {"first_seen": "First Seen", "10m": "10-Minute Entry", "5m": "5-Minute Entry",
              "3m": "3-Minute Entry", "1m": "1-Minute Entry"}
    return f"{graph} — {labels.get(bucket, str(bucket).replace('_', ' ').title())}"


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
                "candidate_id": _candidate_identity(graph_key, bucket),
                "display_name": _display_name(graph_key, bucket),
                "strategy_version": 1,
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
        # Register concrete multi-signal arrangements as independent candidates.
        # The combo key hashes to a stable ID; rank changes never change identity.
        for combo in timing.get("combo_candidates", []):
            combo_key = str(combo.get("combo_key") or "")
            if not combo_key:
                continue
            digest = hashlib.sha1(combo_key.encode("utf-8")).hexdigest()[:12]
            n = int(combo.get("contracts") or 0)
            ret = combo.get("mean_return_per_dollar")
            eligible = n >= MIN_CONTRACTS_FOR_RANKING and ret is not None
            features = combo.get("features") or []
            feature_label = " + ".join(
                str(item.get("name")) + "=" + str(item.get("value"))
                for item in features
            )
            checkpoint = str(combo.get("checkpoint") or "unknown")
            candidate = {
                "candidate_id": graph_key + ":combo:" + digest + ":v1",
                "display_name": GRAPH_LABELS[graph_key] + " — " + checkpoint + " combo: " + feature_label,
                "strategy_version": 1,
                "graph_key": graph_key,
                "graph_name": GRAPH_LABELS[graph_key],
                "strategy_type": "checkpoint_signal_combination",
                "settings": {
                    "checkpoint": checkpoint,
                    "feature_combination": features,
                    "combo_key": combo_key,
                    "evaluation_unit": "one_snapshot_per_settled_contract_per_combo",
                    "minimum_contracts_for_provisional_ranking": MIN_CONTRACTS_FOR_RANKING,
                    "minimum_contracts_for_readiness_review": MIN_CONTRACTS_FOR_READINESS,
                    "execution_enabled": False,
                    "live_trading_enabled": False,
                },
                "metrics": {
                    "settled_contracts": n, "accuracy": combo.get("accuracy"),
                    "brier": combo.get("brier"), "estimated_return_per_dollar": ret,
                    "positive_return_rate": combo.get("positive_return_rate"),
                    "priced_entries": combo.get("priced_entries"),
                    "ranking_eligible": eligible,
                    "metric_source": combo.get("metric_source", "historical_quotes_estimated_binary_settlement"),
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
            # Migrate legacy graph:bucket IDs to stable versioned IDs without losing history.
            for graph_key in GRAPH_LABELS:
                legacy_rows = pg.execute(
                    "SELECT candidate_id, profile_json FROM connectome_candidate_profiles WHERE graph_key=%s",
                    (graph_key,)
                ).fetchall()
                for legacy_id, legacy_json in legacy_rows:
                    legacy_profile = legacy_json if isinstance(legacy_json, dict) else json.loads(legacy_json or "{}")
                    legacy_bucket = (legacy_profile.get("settings") or {}).get("entry_timing_bucket")
                    if not legacy_bucket:
                        continue
                    stable_id = _candidate_identity(graph_key, legacy_bucket)
                    if legacy_id == stable_id:
                        continue
                    legacy_profile["candidate_id"] = stable_id
                    legacy_profile["display_name"] = _display_name(graph_key, legacy_bucket)
                    legacy_profile["strategy_version"] = 1
                    pg.execute(
                        "INSERT INTO connectome_candidate_profiles (candidate_id,graph_key,strategy_type,rank,status,profile_json,updated_at) VALUES (%s,%s,%s,%s,%s,%s::jsonb,%s) ON CONFLICT (candidate_id) DO NOTHING",
                        (stable_id, graph_key, legacy_profile.get("strategy_type", "contract_entry_timing"),
                         legacy_profile.get("rank"), legacy_profile.get("status", "COLLECTING_DATA"),
                         json.dumps(legacy_profile), now)
                    )
                    pg.execute(
                        "UPDATE connectome_candidate_profile_history SET candidate_id=%s WHERE candidate_id=%s",
                        (stable_id, legacy_id)
                    )
                    pg.execute("DELETE FROM connectome_candidate_profiles WHERE candidate_id=%s", (legacy_id,))
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
