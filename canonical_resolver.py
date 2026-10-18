"""Fail-closed canonical BTC 15m contract resolver, independent of observations."""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
from typing import Any


def aware_utc(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            return None
        return value.astimezone(timezone.utc)
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc)


def _metadata_contract(row: dict) -> tuple[bool, str | None]:
    """Use canonical product metadata; title/slug alone never identify product."""
    meta = row.get("metadata") or {}
    if isinstance(meta, str):
        import json
        try:
            meta = json.loads(meta)
        except (ValueError, TypeError):
            return False, "invalid_metadata_json"
    if not isinstance(meta, dict):
        return False, "invalid_metadata"
    terms = meta.get("assetPriceTerms")
    if not isinstance(terms, dict):
        return False, "missing_asset_price_terms"
    asset = terms.get("asset")
    if not isinstance(asset, dict):
        return False, "missing_asset_identity"
    symbol = str(asset.get("symbol") or "").strip().upper()
    horizon = "".join(str(terms.get("horizon") or "").lower().split()).replace("_", "")
    market_type = str(meta.get("marketType") or meta.get("market_type") or "").strip().upper()
    title = str(row.get("title") or meta.get("question") or meta.get("title") or "").lower()
    if symbol not in {"BTC", "BTCUSD", "BTCUSDT", "BITCOIN"}:
        return False, "not_btc_product"
    if horizon not in {"15m", "15min", "15minutes"}:
        return False, "not_15m_product_metadata"
    if market_type not in {"ASSET_PRICE_MARKET_TYPE_UP_DOWN", "UP_DOWN"}:
        return False, "missing_or_wrong_market_type"
    if not ("up or down" in title or "up/down" in title or "up down" in title):
        return False, "not_up_down_question"
    # These fields represent the per-contract window. Generic startDate/endDate are
    # event/market lifecycle fields and may legitimately differ (e.g. endDate=22:00).
    meta_start = aware_utc(terms.get("windowStart"))
    meta_end = aware_utc(terms.get("windowEnd"))
    start = aware_utc(row.get("window_start"))
    end = aware_utc(row.get("window_end"))
    if meta_start is None or meta_end is None:
        return False, "missing_explicit_contract_window_metadata"
    if start is None or end is None:
        return False, "missing_or_unaware_window_boundary"
    if meta_start != start:
        return False, "conflicting_window_start"
    if meta_end != end:
        return False, "conflicting_window_end"
    return True, None


def select_canonical_open_contract(rows: list[dict], evaluation_time: Any) -> dict:
    """Select one active canonical BTC UP/DOWN 15m contract at T; fail closed."""
    t = aware_utc(evaluation_time)
    if t is None:
        return {"status": "NO_OPEN_CONTRACT", "reason": "invalid_evaluation_time", "contract": None}
    eligible = []
    rejected = []
    # The canonical schema declares market_slug as the primary key, so duplicate
    # rows are not expected from PostgreSQL. Keep this helper defensive for fixture
    # inputs and future adapters: repeated identities must agree on market_id,
    # timeframe, active flag, metadata product identity, and exact window bounds.
    by_identity: dict[str, tuple] = {}
    fatal_candidate_reason = None
    boundary_failure_reasons = {
        "missing_explicit_contract_window_metadata",
        "missing_or_unaware_window_boundary",
        "conflicting_window_start",
        "conflicting_window_end",
    }
    for row in rows or []:
        if not isinstance(row, dict) or row.get("active") is not True or row.get("timeframe") != "15m":
            continue
        ok, reason = _metadata_contract(row)
        slug = row.get("market_slug")
        market_id = row.get("market_id")
        start = aware_utc(row.get("window_start"))
        end = aware_utc(row.get("window_end"))
        columns_open = start is not None and end is not None and start <= t < end
        if not isinstance(slug, str) or not slug.strip() or market_id is None or not str(market_id).strip():
            rejected.append("missing_canonical_identity")
            if columns_open and (ok or reason in boundary_failure_reasons):
                fatal_candidate_reason = "missing_canonical_identity"
            continue
        identity_key = str(slug)
        metadata = row.get("metadata") or {}
        if isinstance(metadata, str):
            import json
            try:
                metadata = json.loads(metadata)
            except (ValueError, TypeError):
                metadata = {}
        terms = metadata.get("assetPriceTerms") if isinstance(metadata, dict) else {}
        terms = terms if isinstance(terms, dict) else {}
        asset = terms.get("asset") if isinstance(terms.get("asset"), dict) else {}
        record_signature = (
            str(market_id), str(row.get("timeframe")), start, end, bool(row.get("active")),
            str(asset.get("symbol") or "").strip().upper(),
            "".join(str(terms.get("horizon") or "").lower().split()).replace("_", ""),
            str((metadata.get("marketType") or metadata.get("market_type") or "")).strip().upper()
                if isinstance(metadata, dict) else "",
            str(row.get("title") or (metadata.get("question") if isinstance(metadata, dict) else "") or "").strip().lower(),
            aware_utc(terms.get("windowStart")), aware_utc(terms.get("windowEnd")),
        )
        previous = by_identity.get(identity_key)
        if previous is not None and previous != record_signature:
            return {"status": "NO_OPEN_CONTRACT", "reason": "conflicting_records_for_same_identity", "contract": None}
        by_identity[identity_key] = record_signature
        if not ok:
            rejected.append(reason)
            if columns_open and reason in boundary_failure_reasons:
                fatal_candidate_reason = reason
            continue
        if start is None or end is None:
            rejected.append("missing_or_unaware_window_boundary")
            continue
        if end <= start or end - start != timedelta(minutes=15):
            rejected.append("invalid_window_duration")
            if columns_open:
                fatal_candidate_reason = "invalid_window_duration"
            continue
        if not (start <= t < end):
            continue
        eligible.append((row, start, end))
    # A target-product row with missing/conflicting window evidence blocks selection;
    # do not silently pick a second overlapping row around an inconsistent record.
    if fatal_candidate_reason:
        return {"status": "NO_OPEN_CONTRACT", "reason": "invalid_or_conflicting_canonical_candidate",
                "detail": fatal_candidate_reason, "contract": None}
    # Distinct eligible identities are ambiguity, not a tie-break opportunity.
    identities = {(r[0]["market_slug"], str(r[0]["market_id"]), r[1], r[2]) for r in eligible}
    if len(identities) > 1:
        return {"status": "NO_OPEN_CONTRACT", "reason": "ambiguous_canonical_contracts", "contract": None}
    if not eligible:
        reason = rejected[0] if rejected else "no_eligible_canonical_contract"
        return {"status": "NO_OPEN_CONTRACT", "reason": reason, "contract": None}
    row, start, end = eligible[0]
    metadata = row.get("metadata") or {}
    if isinstance(metadata, str):
        import json
        try:
            metadata = json.loads(metadata)
        except (ValueError, TypeError):
            metadata = {}
    return {"status": "OPEN", "reason": None, "contract": {
        "identity": row["market_slug"], "market_slug": row["market_slug"],
        "market_id": str(row["market_id"]), "timeframe": "15m",
        "question": row.get("title") or (metadata.get("question") if isinstance(metadata, dict) else None),
        "start_at": start.isoformat(), "end_at": end.isoformat(),
        "source": "canonical_market_contracts",
    }}
