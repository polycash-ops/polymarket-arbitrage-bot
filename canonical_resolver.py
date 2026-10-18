"""Fail-closed resolver for Polymarket US price-to-beat values.

No trusted Polymarket US PTB producer is currently configured. This module
therefore returns an explicit unavailable state unless every provenance and
contract-lifecycle check passes; exchange prices and international quotes are
never accepted as PTB values.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import math
from typing import Any

TRUSTED_US_SOURCE = "polymarket_us_official"
MAX_START_OBSERVATION_DELAY_SECONDS = 60


def unavailable_price_to_beat(reason: str = "No trusted Polymarket US price-to-beat source is configured.") -> dict[str, Any]:
    return {
        "status": "unavailable",
        "price_to_beat": None,
        "contract_id": None,
        "source": None,
        "observed_at": None,
        "reason": reason,
    }


def resolve_price_to_beat(
    payload: dict[str, Any] | None,
    *,
    expected_contract_id: str | None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Accept only a fresh, explicit, contract-matched official US PTB record."""
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
        observed_at = datetime.fromisoformat(str(payload.get("observed_at", "")).replace("Z", "+00:00"))
        contract_start = datetime.fromisoformat(str(payload.get("contract_start_at", "")).replace("Z", "+00:00"))
        contract_end = datetime.fromisoformat(str(payload.get("contract_end_at", "")).replace("Z", "+00:00"))
        if any(value.tzinfo is None for value in (observed_at, contract_start, contract_end)):
            return unavailable_price_to_beat("Price-to-beat lifecycle timestamps must include timezones.")
    except (TypeError, ValueError):
        return unavailable_price_to_beat("Price-to-beat lifecycle timestamps are missing or invalid.")
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    observed_at = observed_at.astimezone(timezone.utc)
    contract_start = contract_start.astimezone(timezone.utc)
    contract_end = contract_end.astimezone(timezone.utc)
    now = now.astimezone(timezone.utc)
    if contract_end <= contract_start or not (contract_start <= now < contract_end):
        return unavailable_price_to_beat("Price-to-beat contract is not currently active.")
    delay = (observed_at - contract_start).total_seconds()
    if delay < -1 or delay > MAX_START_OBSERVATION_DELAY_SECONDS or observed_at > now + timedelta(seconds=1):
        return unavailable_price_to_beat("Price-to-beat was observed outside the contract-start window.")
    return {
        "status": "verified",
        "price_to_beat": price,
        "contract_id": contract_id,
        "source": TRUSTED_US_SOURCE,
        "provenance_verified": True,
        "observed_at": observed_at.isoformat(),
        "contract_start_at": contract_start.isoformat(),
        "contract_end_at": contract_end.isoformat(),
        "reason": None,
    }
