"""Fail-closed resolver for official Polymarket US price-to-beat values."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import math
from typing import Any

TRUSTED_US_SOURCE = "polymarket_us_official"
MAX_RETRIEVAL_AGE_SECONDS = 30


def unavailable_price_to_beat(reason: str = "No trusted Polymarket US price-to-beat source is configured.") -> dict[str, Any]:
    return {
        "status": "unavailable",
        "price_to_beat": None,
        "contract_id": None,
        "source": None,
        "retrieved_at": None,
        "contract_start_at": None,
        "contract_end_at": None,
        "reason": reason,
    }


def resolve_price_to_beat(
    payload: dict[str, Any] | None,
    *,
    expected_contract_id: str | None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Accept only fresh official US PTB for the exact currently active contract.

    retrieved_at records when the official endpoint was read; it is deliberately
    not confused with the price's measurement time. The official priceToBeat is
    a fixed value for the contract's opening boundary and remains valid throughout
    that contract's active window.
    """
    if not isinstance(payload, dict):
        return unavailable_price_to_beat("Price-to-beat record is missing.")
    contract_id = payload.get("contract_id")
    if not expected_contract_id or not contract_id or contract_id != expected_contract_id:
        return unavailable_price_to_beat("Price-to-beat contract identity is missing or mismatched.")
    if payload.get("source") != TRUSTED_US_SOURCE or payload.get("provenance_verified") is not True:
        return unavailable_price_to_beat("Price-to-beat provenance is not verified for Polymarket US.")
    try:
        price = float(payload.get("price_to_beat"))
    except (TypeError, ValueError):
        return unavailable_price_to_beat("Price-to-beat value is missing or invalid.")
    if not math.isfinite(price) or price <= 0:
        return unavailable_price_to_beat("Price-to-beat value is missing or invalid.")
    try:
        retrieved_at = datetime.fromisoformat(str(payload.get("retrieved_at", "")).replace("Z", "+00:00"))
        contract_start = datetime.fromisoformat(str(payload.get("contract_start_at", "")).replace("Z", "+00:00"))
        contract_end = datetime.fromisoformat(str(payload.get("contract_end_at", "")).replace("Z", "+00:00"))
        if any(value.tzinfo is None for value in (retrieved_at, contract_start, contract_end)):
            return unavailable_price_to_beat("PTB retrieval and lifecycle timestamps must include timezones.")
    except (TypeError, ValueError):
        return unavailable_price_to_beat("PTB retrieval and lifecycle timestamps are missing or invalid.")
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    retrieved_at = retrieved_at.astimezone(timezone.utc)
    contract_start = contract_start.astimezone(timezone.utc)
    contract_end = contract_end.astimezone(timezone.utc)
    now = now.astimezone(timezone.utc)
    if contract_end - contract_start != timedelta(minutes=15) or not (contract_start <= now < contract_end):
        return unavailable_price_to_beat("Price-to-beat contract window is not the currently active 15-minute window.")
    retrieval_age = (now - retrieved_at).total_seconds()
    if retrieval_age < -1 or retrieval_age > MAX_RETRIEVAL_AGE_SECONDS:
        return unavailable_price_to_beat("Official PTB retrieval timestamp is stale or in the future.")
    return {
        "status": "verified",
        "price_to_beat": price,
        "contract_id": contract_id,
        "source": TRUSTED_US_SOURCE,
        "provenance_verified": True,
        "retrieved_at": retrieved_at.isoformat(),
        "contract_start_at": contract_start.isoformat(),
        "contract_end_at": contract_end.isoformat(),
        "source_field": payload.get("source_field", "market.assetPriceTerms.priceToBeat"),
        "source_url": payload.get("source_url"),
        "reason": None,
    }
