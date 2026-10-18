"""Official Polymarket US BTC 15-minute price-to-beat acquisition.

The adapter uses the documented public market-by-slug endpoint and reads only
market.assetPriceTerms.priceToBeat. Exchange prices and international-market
APIs are deliberately not used as fallbacks.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import math
import time
from typing import Any, Callable
from urllib.parse import quote
from urllib.request import Request, urlopen

from canonical_resolver import unavailable_price_to_beat

OFFICIAL_MARKET_URL = "https://gateway.polymarket.us/v1/market/slug/{}"
CONTRACT_SECONDS = 15 * 60


def _utc(value: datetime | None = None) -> datetime:
    value = value or datetime.now(timezone.utc)
    if value.tzinfo is None:
        raise ValueError("Datetime must include a timezone.")
    return value.astimezone(timezone.utc)


def polymarket_us_btc_15m_slug(window_start: datetime) -> str:
    """Build the canonical official Polymarket US BTC 15m slug for an exact UTC boundary."""
    start = _utc(window_start)
    if start.microsecond or int(start.timestamp()) % CONTRACT_SECONDS:
        raise ValueError("Polymarket US BTC 15m slug requires an exact 15-minute UTC boundary.")
    return "cpc-btc-updown-15m-" + start.strftime("%Y-%m-%d-%H%M") + "z"


def current_btc_15m_window(now: datetime | None = None) -> tuple[str, datetime, datetime]:
    """Return the official US BTC 15m slug and its exact UTC window."""
    now = _utc(now)
    start_epoch = int(now.timestamp()) // CONTRACT_SECONDS * CONTRACT_SECONDS
    start = datetime.fromtimestamp(start_epoch, timezone.utc)
    end = start + timedelta(seconds=CONTRACT_SECONDS)
    return polymarket_us_btc_15m_slug(start), start, end


def current_btc_15m_slug(now: datetime | None = None) -> str:
    return current_btc_15m_window(now)[0]


def _fetch_json(url: str, timeout: float = 4.0) -> dict[str, Any]:
    request = Request(url, headers={"User-Agent": "biological-reservoir-dashboard/1.0", "Accept": "application/json"})
    with urlopen(request, timeout=timeout) as response:
        data = json.loads(response.read().decode("utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Official Polymarket US endpoint returned a non-object JSON response.")
    return data


def _parse_timestamp(value: Any) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Official contract window timestamps must include a timezone.")
    return parsed.astimezone(timezone.utc)


def acquire_official_price_to_beat(
    now: datetime | None = None,
    *,
    fetch_json: Callable[[str], dict[str, Any]] | None = None,
    retry_attempts: int = 0,
    retry_interval: float = 2.0,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    """Read a validated current contract's official PTB; fail closed on any ambiguity."""
    try:
        now = _utc(now)
        slug, expected_start, expected_end = current_btc_15m_window(now)
        url = OFFICIAL_MARKET_URL.format(quote(slug, safe="-"))
        response = (fetch_json or (lambda target: _fetch_json(target)))(url)
        market = response.get("market") if isinstance(response, dict) else None
        if not isinstance(market, dict):
            return unavailable_price_to_beat("Official Polymarket US response has no market object.")
        if market.get("slug") != slug:
            return unavailable_price_to_beat("Official Polymarket US market slug does not match the current contract window.")
        if market.get("active") is not True or market.get("closed") is not False:
            return unavailable_price_to_beat("Official Polymarket US contract is not explicitly active.")
        terms = market.get("assetPriceTerms")
        if not isinstance(terms, dict):
            return unavailable_price_to_beat("Official market response has no assetPriceTerms.")
        asset = terms.get("asset")
        if not isinstance(asset, dict) or str(asset.get("symbol", "")).lower() != "btc" or asset.get("assetClass") != "ASSET_CLASS_CRYPTO":
            return unavailable_price_to_beat("Official market asset is not the expected crypto BTC asset.")
        start = _parse_timestamp(terms.get("windowStart"))
        end = _parse_timestamp(terms.get("windowEnd"))
        if start != expected_start or end != expected_end:
            return unavailable_price_to_beat("Official market window does not match the current 15-minute UTC contract.")
        target = terms.get("priceToBeat")
        # The official US service can publish the active market before PTB is
        # populated. Retry only that known transient state; never substitute an
        # exchange quote or another window's value.
        if target is None and retry_attempts > 0:
            sleep_fn(max(0.0, float(retry_interval)))
            return acquire_official_price_to_beat(
                now, fetch_json=fetch_json, retry_attempts=retry_attempts - 1,
                retry_interval=retry_interval, sleep_fn=sleep_fn,
            )
        if not isinstance(target, dict) or str(target.get("currency", "")).upper() != "USD":
            return unavailable_price_to_beat("Official market has no USD priceToBeat value yet.")
        try:
            price = float(target.get("value"))
        except (TypeError, ValueError):
            return unavailable_price_to_beat("Official priceToBeat value is invalid.")
        if not math.isfinite(price) or price <= 0:
            return unavailable_price_to_beat("Official priceToBeat value is invalid.")
        return {
            "contract_id": slug,
            "source": "polymarket_us_official",
            "provenance_verified": True,
            "price_to_beat": price,
            "retrieved_at": now.isoformat(),
            "contract_start_at": start.isoformat(),
            "contract_end_at": end.isoformat(),
            "source_field": "market.assetPriceTerms.priceToBeat",
            "source_url": url,
        }
    except Exception as exc:
        return unavailable_price_to_beat("Official Polymarket US PTB acquisition failed: " + type(exc).__name__ + ": " + str(exc))
