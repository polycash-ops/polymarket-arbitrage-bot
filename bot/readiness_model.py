"""Independent live-trading readiness auditor for the three Connectomes.

This module only audits evidence; it cannot enable or execute live trading.
Forecast statistics are kept distinct from realized trade statistics.
"""
import json
import logging
import time
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

TARGETS = {
    "win_rate": 0.98,
    "daily_return": 0.032,
    "monthly_return": 1.40,
    "max_drawdown": 0.05,
    "trades_per_day": 240,
}
MIN_INDEPENDENT_CONTRACTS = 100
MAX_REPORT_AGE_SECONDS = 300


def _read_forecast_evidence(graph):
    """Use one earliest, independently settled contract forecast for contract-level accuracy."""
    with graph._connect() as con:
        rows = con.execute(
            "SELECT market_id,observed_at,settled_at,features_json,actual_up "
            "FROM observations WHERE actual_up IS NOT NULL AND settled_at IS NOT NULL "
            "AND market_id IS NOT NULL ORDER BY observed_at ASC"
        ).fetchall()
    by_market = {}
    settled_snapshots = 0
    snapshot_correct = 0
    snapshot_brier = []
    for row in rows:
        try:
            features = json.loads(row["features_json"] or "{}")
            p_up = float(features.get("_forecast_up_probability"))
            actual = int(row["actual_up"])
            if not 0.0 <= p_up <= 1.0:
                continue
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        settled_snapshots += 1
        snapshot_correct += int((p_up >= 0.5) == bool(actual))
        snapshot_brier.append((p_up - actual) ** 2)
        market_id = str(row["market_id"])
        # First observed forecast per contract is the conservative entry-like test;
        # later snapshots from the same contract cannot inflate the contract count.
        if market_id not in by_market:
            by_market[market_id] = {
                "observed_at": float(row["observed_at"]),
                "actual_up": actual,
                "p_up": p_up,
                "market_p": features.get("_snapshot_market_up_probability",
                                         features.get("_snapshot_midpoint")),
            }
    contract_rows = sorted(by_market.values(), key=lambda x: x["observed_at"])
    n = len(contract_rows)
    wins = sum(int((x["p_up"] >= 0.5) == bool(x["actual_up"])) for x in contract_rows)
    contract_brier = sum((x["p_up"] - x["actual_up"]) ** 2 for x in contract_rows) / n if n else None
    market_scores = []
    for x in contract_rows:
        try:
            p = float(x["market_p"])
            if 0.0 <= p <= 1.0:
                market_scores.append((p - x["actual_up"]) ** 2)
        except (TypeError, ValueError):
            pass
    return {
        "settled_contracts": n,
        "settled_snapshots": settled_snapshots,
        "contract_forecast_win_rate": wins / n if n else None,
        "contract_forecast_brier": contract_brier,
        "snapshot_forecast_win_rate": snapshot_correct / settled_snapshots if settled_snapshots else None,
        "snapshot_forecast_brier": sum(snapshot_brier) / len(snapshot_brier) if snapshot_brier else None,
        "market_baseline_brier": sum(market_scores) / len(market_scores) if market_scores else None,
    }


def _latest_trade_metrics(graph):
    """Do not infer trading returns from forecasts or quote-based hypothetical fills."""
    # The current Connectome observation store has no authoritative realized trade ledger.
    # If a dedicated paper/live trade ledger is added later, wire it here explicitly.
    return {
        "source": "no_authoritative_trade_ledger_connected",
        "daily_return": None,
        "monthly_return": None,
        "max_drawdown": None,
        "trades_per_day": None,
        "realized_trades": 0,
    }


def build_report(graph, training_status=None):
    now = datetime.now(timezone.utc)
    evidence = _read_forecast_evidence(graph)
    trades = _latest_trade_metrics(graph)
    training = (training_status or {}).get("latest") or {}
    contract_count = evidence["settled_contracts"]
    win_rate = evidence["contract_forecast_win_rate"]
    candidate_brier = training.get("candidate_brier")
    baseline_brier = training.get("baseline_brier")
    training_accepted = training.get("accepted") is True
    brier_beats_market = (
        candidate_brier is not None and baseline_brier is not None
        and float(candidate_brier) < float(baseline_brier)
    )
    # A walk-forward readout is evaluation evidence, not an active production model.
    model_applied = False
    checks = {
        "minimum_100_independent_settled_contracts": {
            "status": "PASS" if contract_count >= MIN_INDEPENDENT_CONTRACTS else "COLLECTING_DATA",
            "actual": contract_count, "required": MIN_INDEPENDENT_CONTRACTS,
        },
        "forecast_win_rate_target": {
            "status": "PASS" if win_rate is not None and win_rate >= TARGETS["win_rate"] and contract_count >= MIN_INDEPENDENT_CONTRACTS
                      else "FAIL" if win_rate is not None and contract_count >= MIN_INDEPENDENT_CONTRACTS
                      else "INSUFFICIENT_DATA",
            "actual": win_rate, "target": TARGETS["win_rate"],
            "note": "Forecast accuracy is not a realized trading win rate.",
        },
        "walk_forward_candidate_beats_market": {
            "status": "PASS" if training_accepted and brier_beats_market else
                      "FAIL" if training.get("accepted") is False else "NO_VALIDATED_RUN",
            "actual_candidate_brier": candidate_brier, "market_baseline_brier": baseline_brier,
            "accepted": training.get("accepted"),
        },
        "daily_return_target": {
            "status": "NOT_MEASURABLE" if trades["daily_return"] is None else
                      "PASS" if trades["daily_return"] >= TARGETS["daily_return"] else "FAIL",
            "actual": trades["daily_return"], "target": TARGETS["daily_return"],
        },
        "monthly_return_target": {
            "status": "NOT_MEASURABLE" if trades["monthly_return"] is None else
                      "PASS" if trades["monthly_return"] >= TARGETS["monthly_return"] else "FAIL",
            "actual": trades["monthly_return"], "target": TARGETS["monthly_return"],
        },
        "max_drawdown_target": {
            "status": "NOT_MEASURABLE" if trades["max_drawdown"] is None else
                      "PASS" if trades["max_drawdown"] < TARGETS["max_drawdown"] else "FAIL",
            "actual": trades["max_drawdown"], "target_exclusive_max": TARGETS["max_drawdown"],
        },
        "trades_per_day_target": {
            "status": "NOT_MEASURABLE" if trades["trades_per_day"] is None else
                      "PASS" if trades["trades_per_day"] >= TARGETS["trades_per_day"] else "FAIL",
            "actual": trades["trades_per_day"], "target": TARGETS["trades_per_day"],
        },
        "candidate_model_actively_applied": {
            "status": "BLOCKED" if not model_applied else "PASS",
            "actual": model_applied,
            "note": "Current walk-forward candidate is an evaluation readout, not wired into active forecasts.",
        },
        "live_execution_guard": {
            "status": "BLOCKED_BY_DESIGN",
            "actual": False,
            "note": "This report never enables live trading. Manual code/config review and separate authorization remain required.",
        },
    }
    required_pass = (
        checks["minimum_100_independent_settled_contracts"]["status"] == "PASS"
        and checks["forecast_win_rate_target"]["status"] == "PASS"
        and checks["walk_forward_candidate_beats_market"]["status"] == "PASS"
        and all(checks[k]["status"] == "PASS" for k in (
            "daily_return_target", "monthly_return_target", "max_drawdown_target", "trades_per_day_target"
        ))
        and model_applied
    )
    report = {
        "report_version": "live_readiness_audit_v1",
        "graph_name": graph.name,
        "generated_at": now.isoformat(),
        "overall_status": "READY_FOR_MANUAL_REVIEW" if required_pass else "NOT_READY",
        "live_trading_enabled": False,
        "targets": TARGETS,
        "evidence": evidence,
        "trade_metrics": trades,
        "training": training_status or {},
        "checks": checks,
        "required_conditions_met": required_pass,
        "interpretation": (
            "All gates passed; manual review is still required."
            if required_pass else
            "Not ready. Missing evidence, failed performance gates, or a candidate model not applied to forecasts prevents a readiness pass."
        ),
    }
    _persist_report(graph, report)
    return report


def _persist_report(graph, report):
    """Persist audit snapshots in the explicitly configured paid PostgreSQL database."""
    try:
        with graph._pg_connect() as pg:
            pg.execute("""
                CREATE TABLE IF NOT EXISTS connectome_readiness_reports (
                    id BIGSERIAL PRIMARY KEY,
                    graph_name TEXT NOT NULL,
                    generated_at TIMESTAMPTZ NOT NULL,
                    overall_status TEXT NOT NULL,
                    report_version TEXT NOT NULL,
                    report_json JSONB NOT NULL
                )
            """)
            pg.execute(
                "INSERT INTO connectome_readiness_reports "
                "(graph_name,generated_at,overall_status,report_version,report_json) "
                "VALUES (%s,%s,%s,%s,%s::jsonb)",
                (graph.name, datetime.fromisoformat(report["generated_at"]),
                 report["overall_status"], report["report_version"], json.dumps(report)),
            )
    except Exception:
        logger.exception("CONNECTOME_READINESS_PERSIST_FAILED graph=%s", graph.name)


def status(graph):
    """Return the most recently saved report without running a new evaluation."""
    try:
        with graph._pg_connect() as pg:
            row = pg.execute(
                "SELECT generated_at,overall_status,report_json FROM connectome_readiness_reports "
                "WHERE graph_name=%s ORDER BY generated_at DESC LIMIT 1", (graph.name,)
            ).fetchone()
        if not row:
            return None
        payload = row[2] if isinstance(row[2], dict) else json.loads(row[2] or "{}")
        payload["saved_at"] = row[0].isoformat() if row[0] else None
        return payload
    except Exception as exc:
        logger.warning("CONNECTOME_READINESS_STATUS_UNAVAILABLE graph=%s error=%s", graph.name, exc)
        return {"graph_name": graph.name, "overall_status": "REPORT_UNAVAILABLE", "error": str(exc)}
