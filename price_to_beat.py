"""Authoritative Price-to-Beat eligibility for Polymarket US BTC Up/Down 15m.

Phase A safety module — local, reviewable, no production writes.

Rules (from Polymarket US official docs, Oct 2026):
- Authoritative field: assetPriceTerms.priceToBeat
- Type: Amount { value: decimal-string, currency: "USD" }
- Null until a few seconds after windowStart; re-fetch ≤2s, stop after ~60s
- Binding: exact contract identity + matching windowStart/windowEnd
- indexSymbol is expected to be BRTI but remains a fail-closed runtime check
- strike and tradingReferencePx are NOT equivalent for Up/Down contracts
- International Gamma/CLOB prices must never be used as the target

This module does not fetch live data. Callers supply already-retrieved
market metadata. The function only decides eligibility and extracts the
value when the documented authority conditions are met.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional


def _aware_utc(value: Any) -> Optional[datetime]:
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


def _num(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str) and value.strip():
        try:
            return float(value.strip())
        except ValueError:
            return None
    if isinstance(value, dict):
        return _num(value.get("value"))
    return None


@dataclass(frozen=True)
class PriceToBeatResult:
    status: str  # AVAILABLE | UNAVAILABLE
    value: Optional[float]
    currency: Optional[str]
    reason: Optional[str]
    source_field: Optional[str]
    contract_id: Optional[str]
    window_start: Optional[str]
    window_end: Optional[str]
    index_symbol: Optional[str]
    notes: tuple[str, ...] = ()


def extract_price_to_beat(
    market: dict,
    *,
    require_brti: bool = True,
    allow_unverified_index: bool = False,
    provenance_trusted: bool = False,
) -> PriceToBeatResult:
    """Return the authoritative Price to Beat or an explicit UNAVAILABLE result.

    Parameters
    ----------
    market:
        A market object (or metadata dict) that may contain assetPriceTerms.
        Expected shape mirrors the Polymarket US Retail Markets API.
    require_brti:
        When True (default), indexSymbol must equal "BRTI".
    allow_unverified_index:
        Does NOT promote to AVAILABLE. Kept only for diagnostic parsing tests.
    provenance_trusted:
        Must be True for AVAILABLE. Set only by a backend path that has an
        established trusted source (e.g. live Polymarket US gateway response
        validated in-process). Stored market_contracts.metadata of unknown
        producer/refresh provenance must pass provenance_trusted=False.
        Client-supplied flags are never accepted as trust.
    """
    if not isinstance(market, dict):
        return PriceToBeatResult(
            status="UNAVAILABLE",
            value=None,
            currency=None,
            reason="invalid_market_object",
            source_field=None,
            contract_id=None,
            window_start=None,
            window_end=None,
            index_symbol=None,
        )

    # Accept either a full market row or a nested metadata object.
    meta = market.get("metadata") if isinstance(market.get("metadata"), dict) else market
    if isinstance(meta.get("metadata"), dict):
        meta = meta["metadata"]

    terms = meta.get("assetPriceTerms") or market.get("assetPriceTerms")
    if not isinstance(terms, dict):
        return PriceToBeatResult(
            status="UNAVAILABLE",
            value=None,
            currency=None,
            reason="missing_asset_price_terms",
            source_field=None,
            contract_id=str(market.get("slug") or market.get("market_slug") or "") or None,
            window_start=None,
            window_end=None,
            index_symbol=None,
            notes=("Do not fall back to strike or tradingReferencePx.",),
        )

    market_type = str(terms.get("marketType") or "").strip().upper()
    if market_type and market_type not in {
        "ASSET_PRICE_MARKET_TYPE_UP_DOWN",
        "UP_DOWN",
        "ASSET_PRICE_MARKET_TYPE_UNSPECIFIED",  # tolerate newer enum if present
    }:
        # Explicit non-Up/Down types must not use priceToBeat as the open reference.
        if market_type in {
            "ASSET_PRICE_MARKET_TYPE_ABOVE_BELOW",
            "ASSET_PRICE_MARKET_TYPE_RANGE",
            "ASSET_PRICE_MARKET_TYPE_ONE_TOUCH",
        }:
            return PriceToBeatResult(
                status="UNAVAILABLE",
                value=None,
                currency=None,
                reason="not_up_down_market_type",
                source_field=None,
                contract_id=str(market.get("slug") or market.get("market_slug") or "") or None,
                window_start=None,
                window_end=None,
                index_symbol=str(terms.get("indexSymbol") or "") or None,
                notes=(f"marketType={market_type}",),
            )

    horizon = "".join(str(terms.get("horizon") or "").lower().split()).replace("_", "")
    if horizon and horizon not in {"15m", "15min", "15minutes"}:
        return PriceToBeatResult(
            status="UNAVAILABLE",
            value=None,
            currency=None,
            reason="not_15m_horizon",
            source_field=None,
            contract_id=str(market.get("slug") or market.get("market_slug") or "") or None,
            window_start=None,
            window_end=None,
            index_symbol=str(terms.get("indexSymbol") or "") or None,
            notes=(f"horizon={horizon}",),
        )

    window_start = _aware_utc(terms.get("windowStart"))
    window_end = _aware_utc(terms.get("windowEnd"))
    if window_start is None or window_end is None:
        return PriceToBeatResult(
            status="UNAVAILABLE",
            value=None,
            currency=None,
            reason="missing_window_bounds",
            source_field=None,
            contract_id=str(market.get("slug") or market.get("market_slug") or "") or None,
            window_start=None,
            window_end=None,
            index_symbol=str(terms.get("indexSymbol") or "") or None,
        )

    index_symbol = str(terms.get("indexSymbol") or "").strip().upper() or None
    index_verified = index_symbol == "BRTI"
    if require_brti and not index_verified and not allow_unverified_index:
        return PriceToBeatResult(
            status="UNAVAILABLE",
            value=None,
            currency=None,
            reason="index_symbol_unverified_or_mismatch",
            source_field=None,
            contract_id=str(market.get("slug") or market.get("market_slug") or "") or None,
            window_start=window_start.isoformat(),
            window_end=window_end.isoformat(),
            index_symbol=index_symbol,
            notes=(
                "Runtime assumption: indexSymbol must be BRTI. "
                "Fail closed until a live response confirms the field.",
            ),
        )

    # BTC asset identity — required for authoritative path (missing ≠ accepted)
    asset = terms.get("asset") if isinstance(terms.get("asset"), dict) else {}
    symbol = str(asset.get("symbol") or "").strip().upper()
    if not symbol:
        return PriceToBeatResult(
            status="UNAVAILABLE",
            value=None,
            currency=None,
            reason="missing_btc_asset",
            source_field=None,
            contract_id=str(market.get("slug") or market.get("market_slug") or "") or None,
            window_start=window_start.isoformat(),
            window_end=window_end.isoformat(),
            index_symbol=index_symbol,
        )
    if symbol not in {"BTC", "BTCUSD", "BTCUSDT", "BITCOIN"}:
        return PriceToBeatResult(
            status="UNAVAILABLE",
            value=None,
            currency=None,
            reason="not_btc_asset",
            source_field=None,
            contract_id=str(market.get("slug") or market.get("market_slug") or "") or None,
            window_start=window_start.isoformat(),
            window_end=window_end.isoformat(),
            index_symbol=index_symbol,
            notes=(f"asset.symbol={symbol}",),
        )

    raw = terms.get("priceToBeat")
    if raw is None:
        return PriceToBeatResult(
            status="UNAVAILABLE",
            value=None,
            currency=None,
            reason="price_to_beat_null",
            source_field="assetPriceTerms.priceToBeat",
            contract_id=str(market.get("slug") or market.get("market_slug") or "") or None,
            window_start=window_start.isoformat(),
            window_end=window_end.isoformat(),
            index_symbol=index_symbol,
            notes=(
                "Null until a few seconds after windowStart. "
                "Re-fetch at most every 2s; stop after ~60s.",
            ),
        )

    value = _num(raw)
    currency = None
    if isinstance(raw, dict):
        currency = str(raw.get("currency") or "").strip().upper() or None
    if value is None:
        return PriceToBeatResult(
            status="UNAVAILABLE",
            value=None,
            currency=currency,
            reason="price_to_beat_unparsable",
            source_field="assetPriceTerms.priceToBeat",
            contract_id=str(market.get("slug") or market.get("market_slug") or "") or None,
            window_start=window_start.isoformat(),
            window_end=window_end.isoformat(),
            index_symbol=index_symbol,
        )
    if not (value > 0) or value != value:  # positive and finite (NaN != NaN)
        return PriceToBeatResult(
            status="UNAVAILABLE",
            value=None,
            currency=currency,
            reason="price_to_beat_not_positive_finite",
            source_field="assetPriceTerms.priceToBeat",
            contract_id=str(market.get("slug") or market.get("market_slug") or "") or None,
            window_start=window_start.isoformat(),
            window_end=window_end.isoformat(),
            index_symbol=index_symbol,
        )
    if isinstance(raw, dict) and not currency:
        return PriceToBeatResult(
            status="UNAVAILABLE",
            value=None,
            currency=None,
            reason="missing_price_to_beat_currency",
            source_field="assetPriceTerms.priceToBeat",
            contract_id=str(market.get("slug") or market.get("market_slug") or "") or None,
            window_start=window_start.isoformat(),
            window_end=window_end.isoformat(),
            index_symbol=index_symbol,
        )
    if currency is not None and currency != "USD":
        return PriceToBeatResult(
            status="UNAVAILABLE",
            value=None,
            currency=currency,
            reason="price_to_beat_currency_not_usd",
            source_field="assetPriceTerms.priceToBeat",
            contract_id=str(market.get("slug") or market.get("market_slug") or "") or None,
            window_start=window_start.isoformat(),
            window_end=window_end.isoformat(),
            index_symbol=index_symbol,
        )
    # Bare numeric priceToBeat without currency object: require explicit USD context via trusted path only
    if not isinstance(raw, dict) and currency is None:
        # Allow only when provenance_trusted will be checked below; still demand currency evidence
        return PriceToBeatResult(
            status="UNAVAILABLE",
            value=None,
            currency=None,
            reason="missing_price_to_beat_currency",
            source_field="assetPriceTerms.priceToBeat",
            contract_id=str(market.get("slug") or market.get("market_slug") or "") or None,
            window_start=window_start.isoformat(),
            window_end=window_end.isoformat(),
            index_symbol=index_symbol,
            notes=("Bare numeric priceToBeat requires Amount{value,currency} form.",),
        )

    # Unverified-index path must never claim full authority
    if not index_verified:
        return PriceToBeatResult(
            status="UNAVAILABLE",
            value=None,
            currency=currency or "USD",
            reason="index_symbol_unverified_or_mismatch",
            source_field="assetPriceTerms.priceToBeat",
            contract_id=str(market.get("slug") or market.get("market_slug") or "") or None,
            window_start=window_start.isoformat(),
            window_end=window_end.isoformat(),
            index_symbol=index_symbol,
            notes=(
                "Value parsed but indexSymbol is not verified BRTI; "
                "refusing authoritative AVAILABLE. allow_unverified_index "
                "does not promote to AVAILABLE.",
            ),
        )

    if not provenance_trusted:
        return PriceToBeatResult(
            status="UNAVAILABLE",
            value=None,
            currency=currency or "USD",
            reason="metadata_source_unverified",
            source_field="assetPriceTerms.priceToBeat",
            contract_id=str(market.get("slug") or market.get("market_slug") or "") or None,
            window_start=window_start.isoformat(),
            window_end=window_end.isoformat(),
            index_symbol=index_symbol,
            notes=(
                "Structurally valid candidate only. Stored metadata without an "
                "established trusted producer/refresh path cannot yield AVAILABLE.",
            ),
        )

    return PriceToBeatResult(
        status="AVAILABLE",
        value=value,
        currency=currency or "USD",
        reason=None,
        source_field="assetPriceTerms.priceToBeat",
        contract_id=str(market.get("slug") or market.get("market_slug") or "") or None,
        window_start=window_start.isoformat(),
        window_end=window_end.isoformat(),
        index_symbol=index_symbol,
        notes=("Authoritative Polymarket US open reference for Up/Down 15m.",),
    )


def reject_non_authoritative_fallbacks(candidate_fields: dict) -> list[str]:
    """Return warnings for any non-authoritative fields that must not be used."""
    warnings = []
    for key in ("strike", "tradingReferencePx", "trading_reference_px", "reference_price"):
        if key in candidate_fields and candidate_fields[key] is not None:
            warnings.append(
                f"Field '{key}' is present but is not the authoritative Price to Beat "
                f"for US BTC Up/Down 15m; do not display it as the target."
            )
    return warnings
