"""Pure Reservoir dashboard consumer helpers (no Flask/DB dependency).

Producer-data trust
-------------------
`details.issued_at` is treated as a *proposed* field. Its presence in an API
row does not establish issuance semantics until a trusted producer contract is
confirmed (inspect worker writer code, or set ISSUANCE_SEMANTICS_TRUSTED=1
after owner verification). While untrusted, records remain
alert_issuance_unverified and are excluded from active-alert claims and scoring.

Outcome verification
--------------------
Accepted verified representations only:
  bool True, or strings "true" / "1" / "yes" (case-insensitive).
Rejected: False, "false", "0", "no", empty, missing, other strings.
A verification flag alone is not independent settlement proof; upstream
settlement_source / settled_at remain part of the verified-outcome contract
read by the dashboard, but producer provenance is still unverified here.

Sequence semantics
------------------
`alert_sequence` / `issuance_sequence` is data, not authority. Equal-time
conflicts may be resolved by sequence only when the independent
`ALERT_SEQUENCE_ORDERING_TRUSTED=true` configuration contract has been
established after reviewing the producer's documented monotonic ordering
guarantee. This defaults to false. Sequence presence never enables trust.

Outcome provenance
------------------
A row-level outcome flag is not independent settlement proof. Scoring also
requires non-empty settlement_source and timezone-aware settled_at, and the
separate OUTCOME_PROVENANCE_TRUSTED=true owner/config contract. Until the
worker's authoritative settlement writer contract is verified, scoring stays
unavailable. No source allowlist is invented here.
"""
from __future__ import annotations

import math
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Optional


SCORING_POLICY = {
    "id": "proposed-24h-first-eligible-updown-v1",
    "status": "UNAPPROVED",
    "unit": "15-minute contract window",
    "forecast_selection": (
        "first eligible persisted UP/DOWN alert with trusted issued_at, "
        "issued within the window and strictly before close "
        "(earliest issued_at; earliest alert_sequence on ties)"
    ),
    "lookback": "contracts closing within (T-24h, T]",
    "description": (
        "Score one prediction per contract: first eligible UP/DOWN alert "
        "issued inside the open window and strictly before close; verified "
        "final outcome only; pending outside denominator."
    ),
}

FRESHNESS_DEFAULTS = {
    "worker_heartbeat_fresh_seconds": 30,
    "worker_heartbeat_recent_seconds": 180,
    "source_fresh_seconds": 30,
    "source_recent_seconds": 180,
    "observation_fresh_seconds": 120,
    "observation_recent_seconds": 600,
    "assumed_worker_cadence_seconds": 60,
    "assumption_note": (
        "Thresholds are configurable defaults pending documented worker "
        "cadence; they are not production-authoritative."
    ),
}


def _strict_env_true(name: str) -> bool:
    """Only the exact documented literal 'true' enables a global trust flag."""
    return os.getenv(name, "").strip().lower() == "true"


def issuance_semantics_trusted() -> bool:
    """Owner-verified producer issued_at semantics; defaults to untrusted."""
    return _strict_env_true("ISSUANCE_SEMANTICS_TRUSTED")


def sequence_ordering_trusted() -> bool:
    """Owner-verified monotonic sequence semantics; defaults to untrusted."""
    return _strict_env_true("ALERT_SEQUENCE_ORDERING_TRUSTED")


def outcome_provenance_trusted() -> bool:
    """Owner-verified settlement provenance semantics; defaults to untrusted."""
    return _strict_env_true("OUTCOME_PROVENANCE_TRUSTED")


def _strict_optional_bool(value: Any, name: str) -> Optional[bool]:
    if value is None:
        return None
    if type(value) is not bool:
        raise TypeError(f"{name} must be bool or None")
    return value


def _parse_boundary(value: Any) -> Optional[datetime]:
    """Contract boundaries must be explicitly timezone-aware."""
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            return None
        return value.astimezone(timezone.utc)
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        dt = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None or dt.utcoffset() is None:
        return None
    return dt.astimezone(timezone.utc)


def parse_aware_timestamp(value: Any) -> Optional[datetime]:
    """Parse timestamps to timezone-aware UTC. Returns None if missing/invalid."""
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            return None
        return value.astimezone(timezone.utc)
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if dt.tzinfo is None or dt.utcoffset() is None:
        return None
    return dt.astimezone(timezone.utc)


def is_explicitly_verified(value: Any) -> bool:
    """Accept only a boolean true or the canonical serialized string 'true'."""
    if value is True:
        return True
    if isinstance(value, str):
        return value.strip().lower() == "true"
    return False


def is_15_minute_product(start: datetime, end: datetime, *, tolerance_seconds: float = 1.0) -> bool:
    if start is None or end is None:
        return False
    duration = (end - start).total_seconds()
    return abs(duration - 900.0) <= tolerance_seconds



def normalize_contract_price_series(
    rows: list,
    contract_identity: str,
    evaluation_time: datetime,
    *,
    max_age_seconds: float = 120.0,
) -> dict:
    """Validate a real, exact-contract midpoint series; never synthesize points.

    Rows must carry the exact market identity, aware capture timestamps, midpoint
    probabilities, and consistent timezone-aware 15-minute contract boundaries.
    Old data is returned as STALE, not represented as live/fresh.
    """
    t = _parse_boundary(evaluation_time)
    base = {
        "status": "UNAVAILABLE_NO_SERIES",
        "contract_identity": contract_identity,
        "window_start": None,
        "window_end": None,
        "latest_at": None,
        "age_seconds": None,
        "point_count": 0,
        "points": [],
    }
    if not contract_identity or t is None:
        return {**base, "status": "UNAVAILABLE_INVALID_REQUEST"}

    by_time = {}
    boundaries = set()
    for row in rows or []:
        if not isinstance(row, dict) or row.get("market_slug") != contract_identity:
            continue
        captured = _parse_boundary(row.get("captured_at"))
        start = _parse_boundary(row.get("window_start"))
        end = _parse_boundary(row.get("window_end"))
        try:
            midpoint = float(row.get("midpoint"))
        except (TypeError, ValueError):
            continue
        if (captured is None or start is None or end is None
                or end <= start or not is_15_minute_product(start, end)
                or captured < start or captured >= end or captured > t
                or not math.isfinite(midpoint) or not 0.0 <= midpoint <= 1.0):
            continue
        boundaries.add((start, end))
        by_time[captured] = {"captured_at": captured.isoformat(), "midpoint": midpoint}

    if not boundaries:
        return {**base, "status": "UNAVAILABLE_NO_SERIES"}
    if len(boundaries) != 1:
        return {**base, "status": "UNAVAILABLE_INVALID_OR_CONFLICTING_BOUNDARIES"}
    start, end = next(iter(boundaries))
    points = [by_time[k] for k in sorted(by_time)]
    if len(points) < 2:
        return {**base, "window_start": start.isoformat(), "window_end": end.isoformat(),
                "points": points, "point_count": len(points),
                "status": "UNAVAILABLE_INSUFFICIENT_POINTS"}
    latest = _parse_boundary(points[-1]["captured_at"])
    age = max(0.0, (t - latest).total_seconds())
    return {
        "status": "AVAILABLE" if age <= max_age_seconds else "STALE",
        "contract_identity": contract_identity,
        "window_start": start.isoformat(),
        "window_end": end.isoformat(),
        "latest_at": latest.isoformat(),
        "age_seconds": round(age, 3),
        "point_count": len(points),
        "points": points,
        "message": None if age <= max_age_seconds else "Price series exists but is stale; it is not current live evidence.",
    }


def select_open_contract(candidates: list, evaluation_time: datetime) -> dict:
    """Select the unique open contract at T using start <= T < end."""
    t = _parse_boundary(evaluation_time)
    if t is None:
        return {
            "status": "ERROR",
            "reason": "evaluation_time_invalid",
            "contract": None,
            "matches": [],
        }

    matches = []
    ambiguous_raw = []
    for raw in candidates or []:
        if not isinstance(raw, dict):
            continue
        identity = raw.get("identity") or raw.get("market_slug") or raw.get("slug")
        start = _parse_boundary(raw.get("start_at") or raw.get("start") or raw.get("window_start"))
        end = _parse_boundary(raw.get("end_at") or raw.get("end") or raw.get("window_end"))
        if identity is None:
            ambiguous_raw.append({"reason": "missing_identity", "raw": raw})
            continue
        if start is None or end is None:
            ambiguous_raw.append({"identity": identity, "reason": "missing_or_malformed_boundaries"})
            continue
        if end <= start:
            ambiguous_raw.append({"identity": identity, "reason": "invalid_contract_boundaries"})
            continue
        if not (start <= t < end):
            continue
        product_ok = is_15_minute_product(start, end)
        timeframe = (raw.get("timeframe") or raw.get("contract_timeframe") or "").lower()
        if timeframe and "15" not in timeframe and not product_ok:
            continue
        matches.append({
            "identity": identity,
            "start_at": start.isoformat(),
            "end_at": end.isoformat(),
            "is_15_minute_product": product_ok,
            "question": raw.get("question"),
            "source": raw.get("source"),
        })

    pool = [m for m in matches if m["is_15_minute_product"]]

    if not pool:
        return {
            "status": "NO_OPEN_CONTRACT",
            "reason": "no_valid_open_15_minute_contract",
            "contract": None,
            "matches": [],
            "rejected": ambiguous_raw[:20],
            "evaluation_time": t.isoformat(),
        }
    if len(pool) > 1:
        return {
            "status": "AMBIGUOUS",
            "reason": "multiple_open_contracts",
            "contract": None,
            "matches": pool,
            "evaluation_time": t.isoformat(),
        }
    chosen = pool[0]
    if not chosen["is_15_minute_product"]:
        return {
            "status": "REJECTED_PRODUCT",
            "reason": "open_contract_not_15_minute_product",
            "contract": chosen,
            "matches": pool,
            "evaluation_time": t.isoformat(),
        }
    return {
        "status": "OPEN",
        "reason": None,
        "contract": chosen,
        "matches": pool,
        "evaluation_time": t.isoformat(),
    }


def _direction_norm(value: Any) -> Optional[str]:
    if value is None:
        return None
    s = str(value).strip().upper()
    if s in ("UP", "DOWN"):
        return s
    return None


def _sequence_key(raw: dict) -> Optional[int]:
    for k in ("alert_sequence", "issuance_sequence"):
        v = raw.get(k)
        if v is None:
            continue
        if isinstance(v, bool):
            continue
        if isinstance(v, int) and v >= 0:
            return v
        if isinstance(v, str) and v.strip().isdigit():
            return int(v.strip())
    return None


def select_active_up_down_alert(
    records: list,
    contract_identity: Optional[str],
    evaluation_time: datetime,
    *,
    contract_start: Any = None,
    contract_end: Any = None,
    trust_issuance: Optional[bool] = None,
) -> dict:
    """
    Active UP/DOWN alert for the exact open contract.

    - Requires issuance_semantics_trusted() (or trust_issuance=True override for tests
      of ordering only after trust is assumed).
    - Requires issued_at; captured_at alone is never sufficient.
    - Among eligible, prefers latest issued_at; on equal issued_at with sequences,
      latest sequence (current active / lifecycle). Without sequence and conflicting
      directions: AMBIGUOUS_ALERT.
    """
    override = _strict_optional_bool(trust_issuance, "trust_issuance")
    trusted = issuance_semantics_trusted() if override is None else override
    ordered = sequence_ordering_trusted()
    t = _parse_boundary(evaluation_time)
    start = _parse_boundary(contract_start)
    end = _parse_boundary(contract_end)
    if not contract_identity:
        return {
            "status": "NO_ACTIVE_ALERT",
            "message": "No active UP/DOWN alert.",
            "alert": None,
            "reason": "no_contract",
            "unverified_observations": [],
            "issuance_semantics_trusted": trusted,
            "sequence_ordering_trusted": ordered,
        }
    if t is None:
        return {"status": "UNAVAILABLE", "message": "Timezone-aware evaluation time required.",
                "alert": None, "reason": "invalid_evaluation_time",
                "unverified_observations": [], "issuance_semantics_trusted": trusted,
                "sequence_ordering_trusted": ordered}
    if start is None or end is None or end <= start or not is_15_minute_product(start, end):
        return {"status": "UNAVAILABLE", "message": "Valid timezone-aware 15-minute contract boundaries required.",
                "alert": None, "reason": "invalid_contract_boundaries",
                "contract_identity": contract_identity, "unverified_observations": [],
                "issuance_semantics_trusted": trusted, "sequence_ordering_trusted": ordered}
    eligible = []
    unverified = []
    for raw in records or []:
        if not isinstance(raw, dict):
            continue
        identity = raw.get("contract_identity") or raw.get("market_slug") or raw.get("slug")
        if identity != contract_identity:
            continue
        direction = _direction_norm(raw.get("direction") or raw.get("forecast_direction"))
        if direction is None:
            continue
        issued = parse_aware_timestamp(raw.get("issued_at"))
        if issued is None or not trusted:
            unverified.append({
                "contract_identity": identity,
                "direction": direction,
                "captured_at": (
                    parse_aware_timestamp(raw.get("captured_at")).isoformat()
                    if parse_aware_timestamp(raw.get("captured_at")) else None
                ),
                "issued_at": issued.isoformat() if issued else None,
                "snapshot_id": raw.get("snapshot_id"),
                "state": "alert_issuance_unverified",
                "reason": (
                    "missing_trustworthy_issued_at" if issued is None
                    else "issuance_semantics_not_trusted"
                ),
            })
            continue
        if issued < start or not (issued < end) or issued > t:
            continue
        eligible.append({
            "contract_identity": identity,
            "direction": direction,
            "issued_at": issued.isoformat(),
            "issuance_timestamp_source": "issued_at",
            "snapshot_id": raw.get("snapshot_id"),
            "alert_sequence": _sequence_key(raw),
            "checkpoint": raw.get("checkpoint"),
            "probability_up": raw.get("probability_up"),
            "lifecycle": raw.get("lifecycle") or "active",
        })
    if not eligible:
        return {
            "status": "NO_ACTIVE_ALERT",
            "message": "No active UP/DOWN alert.",
            "alert": None,
            "reason": "no_eligible_issued_up_down_for_contract",
            "contract_identity": contract_identity,
            "unverified_observations": unverified,
            "issuance_semantics_trusted": trusted,
        }
    by_time: dict = {}
    for a in eligible:
        by_time.setdefault(a["issued_at"], []).append(a)
    latest_time = max(by_time.keys())
    group = by_time[latest_time]
    directions = {g["direction"] for g in group}
    if len(directions) > 1:
        sequenced = [g for g in group if g.get("alert_sequence") is not None]
        if not ordered or len(sequenced) != len(group):
            return {
                "status": "AMBIGUOUS_ALERT",
                "message": "No active UP/DOWN alert.",
                "alert": None,
                "reason": "equal_issuance_without_authoritative_order",
                "sequence_ordering_trusted": ordered,
                "contract_identity": contract_identity,
                "candidates": group,
                "unverified_observations": unverified,
                "issuance_semantics_trusted": trusted,
            }
        # Active lifecycle: latest sequence
        group = sorted(sequenced, key=lambda g: g["alert_sequence"], reverse=True)
    else:
        def sort_key(g):
            seq = g.get("alert_sequence")
            snap = g.get("snapshot_id")
            return (seq if seq is not None else -1, snap if snap is not None else -1)
        group = sorted(group, key=sort_key, reverse=True)
    chosen = group[0]
    return {
        "status": "ACTIVE",
        "message": None,
        "alert": chosen,
        "reason": None,
        "contract_identity": contract_identity,
        "alternate_count": len(eligible) - 1,
        "unverified_observations": unverified,
        "issuance_semantics_trusted": trusted,
        "sequence_ordering_trusted": ordered,
    }


def alerts_to_graph_annotations(alerts: list) -> list:
    """Annotation payloads only. Not a chart overlay (interim)."""
    annotations = []
    for a in alerts or []:
        if not isinstance(a, dict):
            continue
        issued = a.get("issued_at")
        direction = _direction_norm(a.get("direction"))
        identity = a.get("contract_identity")
        if not issued or not direction or not identity:
            continue
        annotations.append({
            "x": issued,
            "label": direction,
            "contract_identity": identity,
            "direction": direction,
            "text": f"{direction} @ {issued}",
        })
    return annotations


def compute_rolling_accuracy(
    records: list,
    evaluation_time: datetime,
    *,
    policy_approved: bool = False,
    lookback_hours: float = 24.0,
    trust_issuance: Optional[bool] = None,
) -> dict:
    """
    Proposed 24h rolling UP/DOWN accuracy. Disabled until policy_approved=True.

    First-alert selection (not latest): earliest issued_at; on equal issued_at
    with sequences, earliest sequence. Conflicting equal-time without sequence
    => unscorable.

    Requires complete contract boundaries (identity + start + end) per contract.
    Requires trusted issuance semantics and explicit verified outcomes.
    """
    policy = dict(SCORING_POLICY)
    override = _strict_optional_bool(trust_issuance, "trust_issuance")
    approved = _strict_optional_bool(policy_approved, "policy_approved")
    trusted = issuance_semantics_trusted() if override is None else override
    ordered = sequence_ordering_trusted()
    provenance = outcome_provenance_trusted()
    base = {
        "policy": policy,
        "correct": None,
        "incorrect": None,
        "scored_total": None,
        "accuracy_pct": None,
        "pending": None,
        "excluded": None,
        "last_verified_outcome_at": None,
        "exclusion_reasons": {},
        "issuance_semantics_trusted": trusted,
        "sequence_ordering_trusted": ordered,
        "outcome_provenance_trusted": provenance,
    }
    if not approved:
        return {
            **base,
            "status": "UNAVAILABLE_POLICY_PENDING",
            "message": "Accuracy unavailable pending scoring-policy approval.",
            "accuracy_pct": None,
        }
    if not trusted:
        return {**base, "status": "UNAVAILABLE",
                "message": "Accuracy unavailable — issuance semantics not trusted.",
                "exclusion_reasons": {"issuance_semantics_not_trusted": 1}}
    if not provenance:
        return {**base, "status": "UNAVAILABLE_OUTCOME_PROVENANCE_PENDING",
                "message": "Accuracy unavailable — authoritative outcome provenance semantics are not verified.",
                "exclusion_reasons": {"outcome_provenance_not_trusted": 1}}

    t = _parse_boundary(evaluation_time)
    if t is None:
        return {
            **base,
            "status": "UNAVAILABLE",
            "message": "Accuracy unavailable — invalid evaluation time.",
        }
    lower = t - timedelta(hours=lookback_hours)

    by_contract: dict = {}
    for raw in records or []:
        if not isinstance(raw, dict):
            continue
        identity = raw.get("contract_identity") or raw.get("market_slug")
        if not identity:
            continue
        by_contract.setdefault(identity, []).append(raw)

    correct = incorrect = pending = 0
    excluded = 0
    reasons: dict = {}
    last_verified = None
    scored_details = []

    def _bump(reason: str):
        nonlocal excluded
        excluded += 1
        reasons[reason] = reasons.get(reason, 0) + 1

    for identity, rows in by_contract.items():
        boundaries = []
        for row in rows:
            raw_start = row.get("contract_start") or row.get("start_at") or row.get("window_start")
            raw_end = row.get("contract_end") or row.get("end_at") or row.get("window_end")
            if raw_start is not None or raw_end is not None:
                pair = (_parse_boundary(raw_start), _parse_boundary(raw_end))
                if pair[0] is None or pair[1] is None or pair[1] <= pair[0] or not is_15_minute_product(*pair):
                    boundaries.append(("invalid", pair))
                else:
                    boundaries.append(("valid", pair))
        if not boundaries or any(kind != "valid" for kind, _ in boundaries):
            _bump("missing_or_invalid_contract_boundaries")
            continue
        unique_pairs = {pair for _, pair in boundaries}
        if len(unique_pairs) != 1:
            _bump("conflicting_contract_boundaries")
            continue
        start, close = next(iter(unique_pairs))
        if not (lower < close <= t):
            _bump("outside_lookback")
            continue

        outcomes = []
        for r in rows:
            o = _direction_norm(r.get("outcome"))
            source = r.get("settlement_source")
            settled_at = _parse_boundary(r.get("settled_at") or r.get("verified_at"))
            if o and is_explicitly_verified(r.get("outcome_verified")) and isinstance(source, str) and source.strip() and settled_at is not None:
                outcomes.append((o, settled_at, source.strip()))
        if not outcomes:
            has_forecast = any(
                _direction_norm(r.get("forecast_direction") or r.get("direction"))
                and parse_aware_timestamp(r.get("issued_at")) is not None
                for r in rows
            )
            if has_forecast:
                pending += 1
            else:
                _bump("no_verified_outcome")
            continue
        outcomes.sort(key=lambda x: x[1])
        final_outcome, verified_at, _settlement_source = outcomes[-1]
        if verified_at and (last_verified is None or verified_at > last_verified):
            last_verified = verified_at

        alerts = []
        for r in rows:
            d = _direction_norm(r.get("direction") or r.get("forecast_direction"))
            if not d:
                continue
            issued = _parse_boundary(r.get("issued_at"))
            if issued is None:
                continue
            if issued < start:
                continue
            if not (issued < close):
                continue
            alerts.append((issued, _sequence_key(r), r.get("snapshot_id"), d))
        if not alerts:
            _bump("no_eligible_issued_alert_before_close")
            continue
        # FIRST alert: earliest issued_at
        alerts.sort(key=lambda x: x[0])
        first_time = alerts[0][0]
        first_group = [a for a in alerts if a[0] == first_time]
        dirs = {a[3] for a in first_group}
        if len(dirs) > 1:
            if not ordered or any(a[1] is None for a in first_group):
                _bump("ambiguous_equal_issuance")
                continue
            # First-scored selection uses earliest authoritative sequence, distinct
            # from active-alert selection which uses latest sequence.
            first_group = sorted(first_group, key=lambda a: a[1])
        pred = first_group[0][3]
        if pred == final_outcome:
            correct += 1
        else:
            incorrect += 1
        scored_details.append({"contract": identity, "prediction": pred, "outcome": final_outcome})

    scored = correct + incorrect
    pct = round(100.0 * correct / scored, 2) if scored else None
    message = None if scored else "Accuracy unavailable — no scored outcomes."
    return {
        "status": "SCORED" if scored else "UNAVAILABLE_NO_SCORED",
        "message": message,
        "policy": policy,
        "correct": correct,
        "incorrect": incorrect,
        "scored_total": scored,
        "accuracy_pct": pct,
        "pending": pending,
        "excluded": excluded,
        "exclusion_reasons": reasons,
        "last_verified_outcome_at": last_verified.isoformat() if last_verified else None,
        "scored_contracts": scored_details,
        "issuance_semantics_trusted": trusted,
    }
